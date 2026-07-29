#!/bin/bash
# Запуск всего: бэкапы, Telegram-боты, мониторинг, автовосстановление
# Использование: bash scripts/start-all.sh [up|down|restart]

set -e
cd "$(dirname "$0")/.."

# 1. Попытка примонтировать SSD client1 (для Loki/Prometheus)
if [[ "$1" != "down" ]] && [[ "$1" != "stop" ]]; then
    if [[ ! -d /mnt/client1-ssd/loki ]] || ! [[ -w /mnt/client1-ssd/loki ]]; then
        echo "Попытка примонтировать SSD client1..."
        bash scripts/mount-client1-ssd-on-centos.sh 2>/dev/null || echo "SSD не примонтирован — используем локальные volumes"
    fi
fi

# 2. Установка COMPOSE_FILE (как в start-with-ssd)
DATA_PATH="${DOCKER_DATA_PATH:-/mnt/client1-ssd}"
[[ -f .env ]] && DATA_PATH=$(grep -E '^DOCKER_DATA_PATH=' .env 2>/dev/null | cut -d= -f2-) || true
DATA_PATH="${DATA_PATH:-/mnt/client1-ssd}"
if [[ -d "$DATA_PATH/loki" ]] && [[ -w "$DATA_PATH/loki" ]]; then
    export COMPOSE_FILE="docker-compose.yaml:docker-compose.ssd.yaml"
    export DOCKER_DATA_PATH="$DATA_PATH"
    echo "Используется SSD: $DATA_PATH"
else
    export COMPOSE_FILE="docker-compose.yaml"
fi

PROFILES="--profile logs --profile bot --profile watchdog --profile recovery"
case "${1:-up}" in
    up|start)
        docker compose $PROFILES up -d
        ;;
    down|stop)
        docker compose $PROFILES down
        ;;
    restart)
        docker compose $PROFILES restart
        ;;
    *)
        echo "Использование: $0 [up|down|restart]"
        exit 1
        ;;
esac

echo ""
echo "=== Статус ==="
docker compose $PROFILES ps 2>/dev/null || true
