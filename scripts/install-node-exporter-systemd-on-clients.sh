#!/bin/bash
# Копирует node_exporter.service на client1 и client2 (с правильным путём /home/USER/bin/)
# Запуск на campus-server: bash scripts/install-node-exporter-systemd-on-clients.sh

SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
[[ -f "$SSH_KEY" ]] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
TMP="/tmp/node_exporter.service.$$"

install_on() {
    local user="$1" host="$2" name="$3"
    echo "=== $name ($user@$host) ==="
    cat > "$TMP" << EOF
[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
ExecStart=/home/$user/bin/node_exporter
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    scp $SSH_OPTS "$TMP" "$user@$host:/tmp/node_exporter.service" 2>/dev/null || { echo "  Ошибка SCP"; return 1; }
    ssh $SSH_OPTS "$user@$host" "
        sudo cp /tmp/node_exporter.service /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable --now node_exporter
        systemctl is-active node_exporter && echo '  node_exporter: OK' || echo '  node_exporter: ошибка'
    " 2>/dev/null || echo "  Ошибка SSH"
    rm -f "$TMP"
    echo ""
}

install_on "client1" "10.20.0.41" "client1"
install_on "client2"  "10.70.0.41" "client2"
echo "Готово. node_exporter будет автозапускаться после перезагрузки."
