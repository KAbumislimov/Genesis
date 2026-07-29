#!/bin/bash
# Исправление прав на каталоги Loki и Prometheus на SSD (nctk)
# При использовании SSHFS контейнеры пишут от имени пользователя nctk,
# поэтому каталоги должны быть доступны для записи (chmod 777).
#
# Запуск НА nctk:
#   sudo bash fix-ssd-permissions-on-nctk.sh
#
# Или с CentOS (по SSH):
#   ssh nctk@10.20.0.41 'sudo bash -s' < scripts/fix-ssd-permissions-on-nctk.sh

set -e

LOKI_DIR="${1:-/mnt/campus-data/loki}"
PROM_DIR="${2:-/mnt/campus-data/prometheus}"

echo "=== Исправление прав на SSD (для Loki и Prometheus) ==="
echo "Loki:      $LOKI_DIR"
echo "Prometheus: $PROM_DIR"

for d in "$LOKI_DIR" "$PROM_DIR"; do
    if [[ -d "$d" ]]; then
        sudo chmod -R 777 "$d"
        echo "[OK] chmod -R 777 $d"
    else
        echo "[SKIP] $d не найден"
    fi
done

echo ""
echo "Готово. Перезапустите контейнеры на CentOS:"
echo "  cd /home/kamran/campus-infra && bash scripts/start-with-ssd.sh down && bash scripts/start-with-ssd.sh up -d"
