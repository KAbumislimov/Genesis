#!/bin/bash
# Перенаправление временных файлов и данных на /home (где есть место)
# Запуск: sudo bash scripts/move-temp-to-home.sh

set -e

echo "=== 1. Создание каталогов на /home ==="
mkdir -p /home/docker-tmp
chmod 1777 /home/docker-tmp
mkdir -p /home/kamran/tmp
chmod 700 /home/kamran/tmp
chown kamran:kamran /home/kamran/tmp

echo "=== 2. Docker/containerd — TMPDIR на /home ==="
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/tmpdir.conf << 'EOF'
[Service]
Environment="TMPDIR=/home/docker-tmp"
EOF

# containerd (если есть — используется Docker)
if systemctl list-unit-files | grep -q containerd.service; then
  mkdir -p /etc/systemd/system/containerd.service.d
  cat > /etc/systemd/system/containerd.service.d/tmpdir.conf << 'EOF'
[Service]
Environment="TMPDIR=/home/docker-tmp"
EOF
  echo "  containerd: TMPDIR настроен"
fi

echo "  docker: TMPDIR настроен"

echo "=== 3. Перезагрузка systemd и перезапуск Docker ==="
systemctl daemon-reload
systemctl restart docker

echo "=== 4. TMPDIR для пользователя kamran ==="
TMP_LINE='export TMPDIR=/home/kamran/tmp'
if ! grep -q 'TMPDIR=/home/kamran/tmp' /home/kamran/.bashrc 2>/dev/null; then
  echo "$TMP_LINE" >> /home/kamran/.bashrc
  echo "  Добавлено в ~/.bashrc"
fi

echo ""
echo "Готово. Docker и containerd теперь используют /home/docker-tmp для временных файлов."
echo "Данные Docker (Loki, Grafana, Prometheus) уже на /home/docker-data."
echo ""
echo "Перезапустите контейнеры:"
echo "  cd /home/kamran/campus-infra"
echo "  docker compose --profile logs --profile bot --profile watchdog --profile recovery up -d"
