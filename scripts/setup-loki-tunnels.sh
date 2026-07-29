#!/bin/bash
# Настройка SSH reverse tunnel для Promtail: nctk/vm1 не могут достучаться до Loki на centos,
# поэтому centos поднимает туннели — на nctk и vm1 localhost:3100 пробрасывается на Loki.
#
# 1. Обновляет promtail config на nctk и vm1 (url: localhost:3100)
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
for svc in loki-tunnel-nctk loki-tunnel-vm1; do
  sed "s|-i /home/kamran/.ssh/campus_bot|-i $SSH_KEY|g" "$DIR/scripts/systemd/$svc.service" | sudo tee "/etc/systemd/system/$svc.service" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable loki-tunnel-nctk loki-tunnel-vm1
sudo systemctl restart loki-tunnel-nctk loki-tunnel-vm1

echo ""
echo "=== 2. Обновление конфигов Promtail на nctk и vm1 ==="
$SCP "$DIR/promtail-clients/promtail-nctk.yaml" nctk@10.20.0.41:/tmp/campus-monitoring/promtail/config.yaml
# vm1: при установке через deploy-monitoring-offline — /tmp/...; у вас может быть /home/vm1/...
$SCP "$DIR/promtail-clients/promtail-vm1.yaml" vm1@10.70.0.41:/home/vm1/campus-monitoring/promtail/config.yaml
echo "  OK: конфиги скопированы"

echo ""
echo "=== 3. Перезапуск Promtail на nctk и vm1 ==="
$SSH nctk@10.20.0.41 "sudo systemctl restart promtail" 2>/dev/null && echo "  nctk: promtail перезапущен" || echo "  nctk: promtail не перезапущен (проверьте вручную)"
$SSH vm1@10.70.0.41 "sudo systemctl restart promtail" 2>/dev/null && echo "  vm1: promtail перезапущен" || echo "  vm1: promtail не перезапущен (проверьте вручную)"

echo ""
echo "=== 4. Проверка туннелей ==="
sleep 2
for n in loki-tunnel-nctk loki-tunnel-vm1; do
  if systemctl is-active --quiet $n; then
    echo "  $n: active"
  else
    echo "  $n: FAILED — journalctl -u $n -n 20"
  fi
done

echo ""
echo "Готово. Promtail на nctk и vm1 теперь шлёт логи на localhost:3100 → туннель → Loki на centos."
echo "Проверка через несколько минут: journalctl -u promtail -n 5 (на nctk/vm1) — не должно быть 'context deadline exceeded'"
