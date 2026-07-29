#!/bin/bash
# Запуск стека logs. Если SSD на client1 примонтирован — использует его, иначе — локальные volumes.

cd "$(dirname "$0")/.."
if [[ -f .env ]]; then
  DATA_PATH=$(grep -E '^DOCKER_DATA_PATH=' .env 2>/dev/null | cut -d= -f2-)
fi
DATA_PATH="${DATA_PATH:-/mnt/client1-ssd}"

if [[ -d "$DATA_PATH/loki" ]] && [[ -w "$DATA_PATH/loki" ]]; then
    export COMPOSE_FILE="docker-compose.yaml:docker-compose.ssd.yaml"
    export DOCKER_DATA_PATH="$DATA_PATH"
    echo "Используется SSD: $DATA_PATH"
else
    echo "SSD не примонтирован — используем локальные volumes. Для SSD: bash scripts/mount-client1-ssd-on-centos.sh"
    export COMPOSE_FILE="docker-compose.yaml"
fi

docker compose --profile logs "$@"
