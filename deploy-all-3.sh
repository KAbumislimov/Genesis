#!/bin/bash
# Деплой Docker на все 3 машины
# Запуск: с vm1. CentOS = сервер (бот + Loki + Grafana), nctk и vm1 = Promtail.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CENTOS="kamran@10.10.4.120"
NCTK="nctk@10.20.0.41"

# Пароли (или из credentials.env)
if [ -f /home/vm1/credentials.env ]; then
  set -a
  . /home/vm1/credentials.env
  set +a
fi
export CLIENT_PASSWORD="${CLIENT_PASSWORD:?Укажите CLIENT_PASSWORD}"
export SERVER_PASSWORD="${SERVER_PASSWORD:?Укажите SERVER_PASSWORD}"

echo "=========================================="
echo "1. CentOS (сервер): campus-infra (бот + Loki + Grafana + Promtail)"
echo "=========================================="
scp -r "$DIR" "$CENTOS:/home/kamran/"
ssh "$CENTOS" "cd /home/kamran/campus-infra && docker compose --profile bot --profile logs up -d"

echo ""
echo "=========================================="
echo "2. nctk: Promtail (логи → CentOS)"
echo "=========================================="
ssh "$NCTK" "mkdir -p /home/nctk/log-promtail"
scp "$DIR/promtail-clients/promtail-nctk.yaml" "$NCTK:/home/nctk/log-promtail/promtail-config.yaml"
ssh "$NCTK" "cd /home/nctk/log-promtail && docker run -d --name promtail --restart unless-stopped -v /home/nctk/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml 2>/dev/null || (docker rm -f promtail; docker run -d --name promtail --restart unless-stopped -v /home/nctk/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml)"

echo ""
echo "=========================================="
echo "3. vm1: Promtail (логи → CentOS)"
echo "=========================================="
mkdir -p /home/vm1/log-promtail
cp "$DIR/promtail-clients/promtail-vm1.yaml" /home/vm1/log-promtail/promtail-config.yaml
cd /home/vm1/log-promtail
docker run -d --name promtail --restart unless-stopped \
  -v /home/vm1/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro \
  -v /var/log:/var/log:ro \
  grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml 2>/dev/null || \
  (docker rm -f promtail 2>/dev/null; docker run -d --name promtail --restart unless-stopped \
  -v /home/vm1/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro \
  -v /var/log:/var/log:ro \
  grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml)

echo ""
echo "=========================================="
echo "Готово. Grafana: http://10.10.4.120:3000 (admin/admin)"
echo "Логи: host=centos|nctk|vm1"
echo "=========================================="
