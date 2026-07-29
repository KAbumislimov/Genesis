#!/bin/bash
# Восстановление Docker на всех 3 машинах после поломки
# Запуск: с client2 (откуда копируем)
# Откуда берём: /home/client2/campus-infra/ (источник всегда client2)

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CENTOS="kamran@10.10.4.120"
CLIENT1="client1@10.20.0.41"

echo "=========================================="
echo "ВОССТАНОВЛЕНИЕ — источник: client2 ($DIR)"
echo "=========================================="

# 1. CentOS: пересобрать и перезапустить
echo ""
echo "1. CentOS: копирую campus-infra, перезапускаю контейнеры..."
scp -r "$DIR" "$CENTOS:/home/kamran/"
ssh "$CENTOS" "cd /home/kamran/campus-infra && docker compose --profile bot --profile logs down; docker compose --profile bot --profile logs up -d"

# 2. client1: перезапустить Promtail
echo ""
echo "2. client1: обновляю config, перезапускаю Promtail..."
ssh "$CLIENT1" "mkdir -p /home/client1/log-promtail"
scp "$DIR/promtail-clients/promtail-client1.yaml" "$CLIENT1:/home/client1/log-promtail/promtail-config.yaml"
ssh "$CLIENT1" "docker rm -f promtail 2>/dev/null; cd /home/client1/log-promtail && docker run -d --name promtail --restart unless-stopped -v /home/client1/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml"

# 3. client2: перезапустить Promtail (локально)
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
echo "Восстановление завершено."
echo "Grafana: http://10.10.4.120:3000"
echo "=========================================="
