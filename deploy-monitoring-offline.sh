#!/bin/bash
# Установка node_exporter + promtail БЕЗ интернета на client1/client2
# Скачивает на CentOS, копирует на удалённые машины
# Запуск: bash deploy-monitoring-offline.sh

set -e
# campus_bot или id_rsa (если campus_bot нет)
SSH_KEY="${SSH_KEY:-}"
[[ -z "$SSH_KEY" ]] && [[ -f "$HOME/.ssh/campus_bot" ]] && SSH_KEY="$HOME/.ssh/campus_bot"
[[ -z "$SSH_KEY" ]] && [[ -f "$HOME/.ssh/id_rsa" ]] && SSH_KEY="$HOME/.ssh/id_rsa"
[[ -z "$SSH_KEY" ]] && { echo "Нет SSH ключа (campus_bot или id_rsa)"; exit 1; }
SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no"
SCP="scp -i $SSH_KEY -o StrictHostKeyChecking=no"
DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE="/tmp/campus-monitoring-cache"
mkdir -p "$CACHE"

echo "=== Скачивание на CentOS ==="
# node_exporter
if [[ ! -f "$CACHE/node_exporter" ]]; then
    echo "Скачиваю node_exporter..."
    (cd "$CACHE" && wget -q https://github.com/prometheus/node_exporter/releases/download/v1.6.1/node_exporter-1.6.1.linux-amd64.tar.gz -O ne.tar.gz && tar xzf ne.tar.gz && mv node_exporter-1.6.1.linux-amd64/node_exporter . && rm -rf node_exporter-1.6.1.linux-amd64 ne.tar.gz)
fi
# promtail
if [[ ! -f "$CACHE/promtail" ]]; then
    echo "Скачиваю promtail..."
    (cd "$CACHE" && wget -q https://github.com/grafana/loki/releases/download/v2.9.5/promtail-linux-amd64.zip -O p.zip && unzip -o p.zip)
    # zip содержит файл promtail-linux-amd64 (бинарник) или папку promtail-linux-amd64/promtail
    if [[ -f "$CACHE/promtail-linux-amd64/promtail" ]]; then
        mv "$CACHE/promtail-linux-amd64/promtail" "$CACHE/"
    elif [[ -f "$CACHE/promtail-linux-amd64" ]]; then
        mv "$CACHE/promtail-linux-amd64" "$CACHE/promtail"
    fi
    rm -rf "$CACHE/promtail-linux-amd64" "$CACHE/p.zip" 2>/dev/null
fi
echo "OK: бинарники готовы"
echo ""

deploy_host() {
    local host="$1"
    local user="$2"
    local instance="$3"
    echo "=== $instance ($user@$host) ==="
    
    # /tmp всегда доступен для записи (если /home/$user/bin недоступен)
    local INSTALL_DIR="/tmp/campus-monitoring"
    $SSH "$user@$host" "mkdir -p $INSTALL_DIR/bin $INSTALL_DIR/promtail"
    $SCP "$CACHE/node_exporter" "$user@$host:$INSTALL_DIR/bin/"
    $SCP "$CACHE/promtail" "$user@$host:$INSTALL_DIR/bin/"
    $SSH "$user@$host" "chmod +x $INSTALL_DIR/bin/node_exporter $INSTALL_DIR/bin/promtail"
    
    [[ "$instance" == "client2" ]] && pcfg="promtail-client2.yaml" || pcfg="promtail-client1.yaml"
    $SCP "$DIR/promtail-clients/$pcfg" "$user@$host:$INSTALL_DIR/promtail/config.yaml"
    
    # systemd unit-файлы (для автозапуска)
    local tmpd="$CACHE/systemd-$instance"
    mkdir -p "$tmpd"
    cat > "$tmpd/node_exporter.service" << EOF
[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/bin/node_exporter
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    cat > "$tmpd/promtail.service" << EOF
[Unit]
Description=Promtail
After=network.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/bin/promtail -config.file=$INSTALL_DIR/promtail/config.yaml
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    $SCP "$tmpd/node_exporter.service" "$tmpd/promtail.service" "$user@$host:$INSTALL_DIR/promtail/"
    rm -rf "$tmpd"
    
    # Автоустановка systemd (нужен passwordless sudo на удалённой машине)
    echo "  Устанавливаю systemd и запускаю сервисы..."
    $SSH "$user@$host" "sudo cp $INSTALL_DIR/promtail/node_exporter.service /etc/systemd/system/ && sudo cp $INSTALL_DIR/promtail/promtail.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now node_exporter promtail" 2>/dev/null || {
        echo "  (sudo не сработал — запустите вручную на $host):"
        echo "  sudo cp $INSTALL_DIR/promtail/*.service /etc/systemd/system/"
        echo "  sudo systemctl daemon-reload && sudo systemctl enable --now node_exporter promtail"
    }
}

deploy_host "10.20.0.41" "client1" "client1"
deploy_host "10.70.0.41" "client2" "client2"

echo ""
echo "Готово. node_exporter и promtail должны работать на client1 и client2."
echo "Проверка: curl -s http://10.20.0.41:9100/metrics | head -3"
echo "          curl -s http://10.70.0.41:9100/metrics | head -3"
echo ""
echo "Перезапустите Prometheus: docker compose --profile logs restart prometheus"
