#!/bin/bash
# Настройка SSH reverse tunnel для Promtail: client1/client2 не могут достучаться до Loki на centos,
# поэтому centos поднимает туннели — на client1 и client2 localhost:3100 пробрасывается на Loki.
#
# 1. Обновляет promtail config на client1 и client2 (url: localhost:3100)
# 2. Устанавливает и запускает systemd-сервисы туннелей на centos
#
# Запуск с centos: bash scripts/setup-loki-tunnels.sh

set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="${SSH_KEY:-}"
[[ -z "$SSH_KEY" ]] && [[ -f "$HOME/.ssh/campus_bot" ]] && SSH_KEY="$HOME/.ssh/campus_bot"
[[ -z "$SSH_KEY" ]] && [[ -f "$HOME/.ssh/id_rsa" ]] && SSH_KEY="$HOME/.ssh/id_rsa"
[[ -z "$SSH_KEY" ]] && { echo "Нет SSH ключа (campus_bot или id_rsa)"; exit 1; }
SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"
SCP="scp -i $SSH_KEY -o StrictHostKeyChecking=no"

echo "=== 1. Установка и запуск systemd-сервисов туннелей на centos ==="
# Подставляем путь к ключу в unit-файлы
for svc in loki-tunnel-client1 loki-tunnel-client2; do
  sed "s|-i /home/kamran/.ssh/campus_bot|-i $SSH_KEY|g" "$DIR/scripts/systemd/$svc.service" | sudo tee "/etc/systemd/system/$svc.service" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable loki-tunnel-client1 loki-tunnel-client2
sudo systemctl restart loki-tunnel-client1 loki-tunnel-client2

echo ""
echo "=== 2. Обновление конфигов Promtail на client1 и client2 ==="
$SCP "$DIR/promtail-clients/promtail-client1.yaml" client1@10.20.0.41:/tmp/campus-monitoring/promtail/config.yaml
# client2: при установке через deploy-monitoring-offline — /tmp/...; у вас может быть /home/client2/...
$SCP "$DIR/promtail-clients/promtail-client2.yaml" client2@10.70.0.41:/home/client2/campus-monitoring/promtail/config.yaml
echo "  OK: конфиги скопированы"

echo ""
echo "=== 3. Перезапуск Promtail на client1 и client2 ==="
$SSH client1@10.20.0.41 "sudo systemctl restart promtail" 2>/dev/null && echo "  client1: promtail перезапущен" || echo "  client1: promtail не перезапущен (проверьте вручную)"
$SSH client2@10.70.0.41 "sudo systemctl restart promtail" 2>/dev/null && echo "  client2: promtail перезапущен" || echo "  client2: promtail не перезапущен (проверьте вручную)"

echo ""
echo "=== 4. Проверка туннелей ==="
sleep 2
for n in loki-tunnel-client1 loki-tunnel-client2; do
  if systemctl is-active --quiet $n; then
    echo "  $n: active"
  else
    echo "  $n: FAILED — journalctl -u $n -n 20"
  fi
done

echo ""
echo "Готово. Promtail на client1 и client2 теперь шлёт логи на localhost:3100 → туннель → Loki на centos."
echo "Проверка через несколько минут: journalctl -u promtail -n 5 (на client1/client2) — не должно быть 'context deadline exceeded'"
