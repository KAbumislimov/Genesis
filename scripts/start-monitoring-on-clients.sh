#!/bin/bash
# Запуск node_exporter и promtail на nctk и vm1 через SSH
# Требует: ssh-ключ (campus_bot или пароль)
# Запуск: bash scripts/start-monitoring-on-clients.sh

SSH_KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=5"
[[ -f "$SSH_KEY" ]] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"

run_on_host() {
    local user="$1"
    local host="$2"
    local name="$3"
    echo "=== $name ($user@$host) ==="
    ssh $SSH_OPTS "$user@$host" '
        pgrep -x node_exporter >/dev/null || (/home/'"$user"'/bin/node_exporter &)
        pgrep -x promtail >/dev/null || (/home/'"$user"'/bin/promtail -config.file=/home/'"$user"'/promtail/config.yaml &)
        sleep 1
        pgrep -x node_exporter && echo "  node_exporter: OK" || echo "  node_exporter: не запущен"
        pgrep -x promtail && echo "  promtail: OK" || echo "  promtail: не запущен"
    ' 2>/dev/null || echo "  Ошибка SSH (проверьте ключ/пароль)"
    echo ""
}

run_on_host "nctk" "10.20.0.41" "nctk"
run_on_host "vm1"  "10.70.0.41" "vm1"

echo "Готово. Подождите 1–2 мин — метрики появятся в Grafana."
echo "Если нет — проверьте сеть: с campus-server до 10.20.0.41:9100 и 10.70.0.41:9100"
