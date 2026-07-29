#!/bin/bash
# Восстановление с автоматической подстановкой паролей из credentials.env
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f /home/vm1/credentials.env ]; then
  set -a
  . /home/vm1/credentials.env
  set +a
fi

CENTOS_PW="${NARIMANOV_PASSWORD:?Укажите NARIMANOV_PASSWORD}"
NCTK_PW="${CLIENT_PASSWORD:?Укажите CLIENT_PASSWORD}"

# Проверка sshpass
if ! command -v sshpass &>/dev/null; then
  echo "Установите sshpass: sudo apt install sshpass"
  exit 1
fi

echo "=========================================="
echo "ВОССТАНОВЛЕНИЕ — источник: vm1 ($DIR)"
echo "=========================================="

echo ""
echo "1. CentOS: копирую campus-infra, перезапускаю контейнеры..."
sshpass -p "$CENTOS_PW" scp -o StrictHostKeyChecking=no -r "$DIR" "kamran@10.10.4.120:/home/kamran/"
sshpass -p "$CENTOS_PW" ssh -o StrictHostKeyChecking=no kamran@10.10.4.120 "cd /home/kamran/campus-infra && docker compose --profile bot --profile logs down; docker compose --profile bot --profile logs up -d"

echo ""
echo "2. nctk: обновляю config, перезапускаю Promtail..."
sshpass -p "$NCTK_PW" ssh -o StrictHostKeyChecking=no nctk@10.20.0.41 "mkdir -p /home/nctk/log-promtail"
sshpass -p "$NCTK_PW" scp -o StrictHostKeyChecking=no "$DIR/promtail-clients/promtail-nctk.yaml" "nctk@10.20.0.41:/home/nctk/log-promtail/promtail-config.yaml"
sshpass -p "$NCTK_PW" ssh -o StrictHostKeyChecking=no nctk@10.20.0.41 "docker rm -f promtail 2>/dev/null; cd /home/nctk/log-promtail && docker run -d --name promtail --restart unless-stopped -v /home/nctk/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml"

echo ""
echo "3. vm1: перезапускаю Promtail..."
mkdir -p /home/vm1/log-promtail
cp "$DIR/promtail-clients/promtail-vm1.yaml" /home/vm1/log-promtail/promtail-config.yaml
docker rm -f promtail 2>/dev/null || true
docker run -d --name promtail --restart unless-stopped \
  -v /home/vm1/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro \
  -v /var/log:/var/log:ro \
  grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml

echo ""
echo "=========================================="
echo "Готово. Grafana: http://10.10.4.120:3000 (admin/admin)"
echo "=========================================="
