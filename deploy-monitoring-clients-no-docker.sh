#!/bin/bash
# Установка node_exporter + promtail БЕЗ Docker (systemd + бинарники)
# Для nctk и vm1, где Docker не установлен
# Запуск: bash deploy-monitoring-clients-no-docker.sh

set -e
SSH="ssh -i ${SSH_KEY:-$HOME/.ssh/campus_bot} -o StrictHostKeyChecking=no"
SCP="scp -i ${SSH_KEY:-$HOME/.ssh/campus_bot} -o StrictHostKeyChecking=no"
DIR="$(cd "$(dirname "$0")" && pwd)"
LOKI_URL="http://10.10.4.120:3100"

deploy_host() {
    local host="$1"
    local user="$2"
    local instance="$3"
    echo "=== $instance ($user@$host) ==="
    
    # node_exporter (apt на Ubuntu)
    $SSH "$user@$host" "which node_exporter 2>/dev/null || sudo apt-get install -y prometheus-node-exporter 2>/dev/null" || true
    if $SSH "$user@$host" "systemctl is-active node_exporter 2>/dev/null" 2>/dev/null; then
        echo "  node_exporter уже запущен"
    else
        $SSH "$user@$host" "sudo systemctl enable node_exporter 2>/dev/null; sudo systemctl start node_exporter 2>/dev/null" && echo "  OK: node_exporter" || echo "  Ошибка node_exporter (apt install prometheus-node-exporter?)"
    fi
    
    # promtail — скачать .deb или zip
    $SSH "$user@$host" "mkdir -p /home/$user/promtail"
    [[ "$instance" == "vm1" ]] && pcfg="promtail-vm1.yaml" || pcfg="promtail-nctk.yaml"
    $SCP "$DIR/promtail-clients/$pcfg" "$user@$host:/home/$user/promtail/config.yaml"
    
    # Установка promtail (бинарник)
    $SSH "$user@$host" "
        if ! command -v promtail &>/dev/null; then
            cd /tmp && wget -q https://github.com/grafana/loki/releases/download/v2.9.5/promtail-linux-amd64.zip -O p.zip && unzip -o p.zip
            bin=\$(find . -maxdepth 2 \\( -name promtail -o -name 'promtail-*' \\) -type f 2>/dev/null | head -1)
            [[ -n \"\$bin\" ]] && sudo cp \"\$bin\" /usr/local/bin/promtail || sudo cp ./promtail-linux-amd64/promtail /usr/local/bin/promtail
            sudo chmod +x /usr/local/bin/promtail
            rm -rf promtail-* p.zip 2>/dev/null
        fi
    " 2>/dev/null || true
    
    # systemd unit
    $SSH "$user@$host" "echo '[Unit]
Description=Promtail
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/promtail -config.file=/home/$user/promtail/config.yaml
Restart=always

[Install]
WantedBy=multi-user.target' | sudo tee /etc/systemd/system/promtail.service"
    $SSH "$user@$host" "sudo systemctl daemon-reload; sudo systemctl enable promtail; sudo systemctl restart promtail" 2>/dev/null && echo "  OK: promtail" || echo "  Ошибка promtail"
    echo ""
}

deploy_host "10.20.0.41" "nctk" "nctk"
deploy_host "10.70.0.41" "vm1" "vm1"

echo "Готово. Перезапустите Prometheus: docker compose --profile logs restart prometheus"
