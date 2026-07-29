#!/bin/bash
# Восстановление Docker на всех 3 машинах после поломки
# Запуск: с vm1 (откуда копируем)
# Откуда берём: /home/vm1/campus-infra/ (источник всегда vm1)

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CENTOS="kamran@10.10.4.120"
NCTK="nctk@10.20.0.41"

echo "=========================================="
echo "ВОССТАНОВЛЕНИЕ — источник: vm1 ($DIR)"
echo "=========================================="

# 1. CentOS: пересобрать и перезапустить
echo ""
echo "1. CentOS: копирую campus-infra, перезапускаю контейнеры..."
scp -r "$DIR" "$CENTOS:/home/kamran/"
ssh "$CENTOS" "cd /home/kamran/campus-infra && docker compose --profile bot --profile logs down; docker compose --profile bot --profile logs up -d"

# 2. nctk: перезапустить Promtail
echo ""
echo "2. nctk: обновляю config, перезапускаю Promtail..."
ssh "$NCTK" "mkdir -p /home/nctk/log-promtail"
scp "$DIR/promtail-clients/promtail-nctk.yaml" "$NCTK:/home/nctk/log-promtail/promtail-config.yaml"
ssh "$NCTK" "docker rm -f promtail 2>/dev/null; cd /home/nctk/log-promtail && docker run -d --name promtail --restart unless-stopped -v /home/nctk/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml"

# 3. vm1: перезапустить Promtail (локально)
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
echo "Восстановление завершено."
echo "Grafana: http://10.10.4.120:3000"
echo "=========================================="
