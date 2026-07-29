#!/bin/bash
# Деплой Docker на все 3 машины
# Запуск: с client2. CentOS = сервер (бот + Loki + Grafana), client1 и client2 = Promtail.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CENTOS="kamran@10.10.4.120"
CLIENT1="client1@10.20.0.41"

# Пароли (или из credentials.env)
if [ -f /home/client2/credentials.env ]; then
  set -a
  . /home/client2/credentials.env
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
echo "2. client1: Promtail (логи → CentOS)"
echo "=========================================="
ssh "$CLIENT1" "mkdir -p /home/client1/log-promtail"
scp "$DIR/promtail-clients/promtail-client1.yaml" "$CLIENT1:/home/client1/log-promtail/promtail-config.yaml"
ssh "$CLIENT1" "cd /home/client1/log-promtail && docker run -d --name promtail --restart unless-stopped -v /home/client1/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml 2>/dev/null || (docker rm -f promtail; docker run -d --name promtail --restart unless-stopped -v /home/client1/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro -v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml)"

echo ""
echo "=========================================="
echo "3. client2: Promtail (логи → CentOS)"
echo "=========================================="
mkdir -p /home/client2/log-promtail
cp "$DIR/promtail-clients/promtail-client2.yaml" /home/client2/log-promtail/promtail-config.yaml
cd /home/client2/log-promtail
docker run -d --name promtail --restart unless-stopped \
  -v /home/client2/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro \
  -v /var/log:/var/log:ro \
  grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml 2>/dev/null || \
  (docker rm -f promtail 2>/dev/null; docker run -d --name promtail --restart unless-stopped \
  -v /home/client2/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro \
  -v /var/log:/var/log:ro \
  grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml)

echo ""
echo "=========================================="
echo "Готово. Grafana: http://10.10.4.120:3000 (admin/admin)"
echo "Логи: host=centos|client1|client2"
echo "=========================================="
