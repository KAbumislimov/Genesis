#!/bin/bash
# Установка node_exporter + promtail на nctk и vm1 для метрик и логов в Grafana
# Запуск: bash deploy-monitoring-clients.sh

set -e
SSH="ssh -i ${SSH_KEY:-$HOME/.ssh/campus_bot} -o StrictHostKeyChecking=no"
DIR="$(cd "$(dirname "$0")" && pwd)"

deploy_host() {
    local host="$1"
    local user="$2"
    local instance="$3"
    echo "=== $instance ($user@$host) ==="
    
    # node_exporter
    if $SSH "$user@$host" "docker ps -q -f name=node-exporter" 2>/dev/null; then
        echo "  node-exporter уже запущен"
    else
        echo "  Запуск node-exporter..."
        out=$($SSH "$user@$host" "docker run -d --name node-exporter --restart unless-stopped -p 9100:9100 -v /proc:/host/proc:ro -v /sys:/host/sys:ro -v /:/rootfs:ro prom/node-exporter:v1.6.1 --path.procfs=/host/proc --path.sysfs=/host/sys --path.rootfs=/rootfs" 2>&1)
        [[ $? -eq 0 ]] && echo "  OK: node-exporter" || echo "  Ошибка: $out"
    fi
    
    # promtail
    local promtail_cfg
    [[ "$instance" == "vm1" ]] && promtail_cfg="promtail-vm1.yaml" || promtail_cfg="promtail-nctk.yaml"
    $SSH "$user@$host" "mkdir -p /home/$user/promtail"
    scp -i ${SSH_KEY:-$HOME/.ssh/campus_bot} -o StrictHostKeyChecking=no "$DIR/promtail-clients/$promtail_cfg" "$user@$host:/home/$user/promtail/config.yaml"
    echo "  Запуск promtail..."
    out=$($SSH "$user@$host" "docker rm -f promtail 2>/dev/null; docker run -d --name promtail --restart unless-stopped -v /home/$user/promtail/config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml" 2>&1)
    [[ $? -eq 0 ]] && echo "  OK: promtail" || echo "  Ошибка: $out"
    echo ""
}

deploy_host "10.20.0.41" "nctk" "nctk"
deploy_host "10.70.0.41" "vm1" "vm1"

echo "Готово. Перезапустите Prometheus для применения scrape config:"
echo "  docker compose --profile logs restart prometheus"
