#!/bin/bash
# Проверяет и запускает node_exporter на nctk и vm1 (метрики CPU, RAM, диск в Grafana)
# Запуск на campus-server: bash scripts/ensure-node-exporter-on-clients.sh

SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
[[ -f "$SSH_KEY" ]] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"

ensure_host() {
    local user="$1" host="$2" name="$3"
    echo "=== $name ($user@$host:9100) ==="
    # Проверка: отвечает ли 9100
    if (timeout 2 nc -z "$host" 9100 2>/dev/null || timeout 2 bash -c "echo >/dev/tcp/$host/9100" 2>/dev/null); then
        echo "  node_exporter уже слушает порт 9100"
        return 0
    fi
    # Запуск через SSH
    ssh $SSH_OPTS "$user@$host" '
        if systemctl is-enabled node_exporter 2>/dev/null | grep -q enabled; then
            sudo systemctl start node_exporter 2>/dev/null && echo "  systemd: запущен" || echo "  systemd: ошибка"
        elif [[ -x /home/'"$user"'/bin/node_exporter ]]; then
            pgrep -x node_exporter >/dev/null || (nohup /home/'"$user"'/bin/node_exporter >/dev/null 2>&1 &)
            sleep 1
            pgrep -x node_exporter && echo "  bin: запущен" || echo "  bin: не запустился"
        else
            echo "  node_exporter не найден. Запустите: bash deploy-monitoring-offline.sh"
        fi
    ' 2>/dev/null || echo "  Ошибка SSH"
    echo ""
}

ensure_host "nctk" "10.20.0.41" "nctk"
ensure_host "vm1"  "10.70.0.41" "vm1"

echo "Проверка доступности с campus-server:"
(timeout 2 nc -z 10.20.0.41 9100 2>/dev/null || timeout 2 bash -c "echo >/dev/tcp/10.20.0.41/9100" 2>/dev/null) && echo "  nctk:9100 OK" || echo "  nctk:9100 недоступен"
(timeout 2 nc -z 10.70.0.41 9100 2>/dev/null || timeout 2 bash -c "echo >/dev/tcp/10.70.0.41/9100" 2>/dev/null) && echo "  vm1:9100 OK" || echo "  vm1:9100 недоступен"
echo ""
echo "Если недоступен — установите node_exporter: bash deploy-monitoring-offline.sh"
echo "Затем на nctk и vm1: sudo cp /home/USER/promtail/node_exporter.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now node_exporter"
