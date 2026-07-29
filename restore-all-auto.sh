#!/bin/bash
# Восстановление с автоматической подстановкой паролей из credentials.env
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f /home/client2/credentials.env ]; then
  set -a
  . /home/client2/credentials.env
  set +a
fi

CENTOS_PW="${CLIENT1_PASSWORD:?Укажите CLIENT1_PASSWORD}"
CLIENT1_PW="${CLIENT_PASSWORD:?Укажите CLIENT_PASSWORD}"

# Проверка sshpass
if ! command -v sshpass &>/dev/null; then
  echo "Установите sshpass: sudo apt install sshpass"
  exit 1
fi

echo "=========================================="
echo "ВОССТАНОВЛЕНИЕ — источник: client2 ($DIR)"
echo "=========================================="

echo ""
echo "1. CentOS: копирую campus-infra, перезапускаю контейнеры..."
sshpass -p "$CENTOS_PW" scp -o StrictHostKeyChecking=no -r "$DIR" "kamran@10.10.4.120:/home/kamran/"
sshpass -p "$CENTOS_PW" ssh -o StrictHostKeyChecking=no kamran@10.10.4.120 "cd /home/kamran/campus-infra && docker compose --profile bot --profile logs down; docker compose --profile bot --profile logs up -d"

echo ""
echo "2. client1: обновляю config, перезапускаю Promtail..."
sshpass -p "$CLIENT1_PW" ssh -o StrictHostKeyChecking=no client1@10.20.0.41 "mkdir -p /home/client1/log-promtail"
sshpass -p "$CLIENT1_PW" scp -o StrictHostKeyChecking=no "$DIR/promtail-clients/promtail-client1.yaml" "client1@10.20.0.41:/home/client1/log-promtail/promtail-config.yaml"
sshpass -p "$CLIENT1_PW" ssh -o StrictHostKeyChecking=no client1@10.20.0.41 "docker rm -f promtail 2>/dev/null; cd /home/client1/log-promtail && docker run -d --name promtail --restart unless-stopped -v /home/client1/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml"

echo ""
echo "3. client2: перезапускаю Promtail..."
mkdir -p /home/client2/log-promtail
cp "$DIR/promtail-clients/promtail-client2.yaml" /home/client2/log-promtail/promtail-config.yaml
docker rm -f promtail 2>/dev/null || true
docker run -d --name promtail --restart unless-stopped \
  -v /home/client2/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro \
  -v /var/log:/var/log:ro \
  grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml

echo ""
echo "=========================================="
echo "Готово. Grafana: http://10.10.4.120:3000 (admin/admin)"
echo "=========================================="
