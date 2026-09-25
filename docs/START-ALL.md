# Запуск всего: 4 главных компонента

## 1. Бэкапы (campus-recovery)
- Бэкапы server, client1, client2 раз в сутки
- Копирование на client1 в `/mnt/campus-data/backups` (если SYNC_BACKUPS_TO_CLIENT1=1)
- Уведомления в Telegram

## 2. Telegram-боты
- tg-campus-bot (client1), tg-campus-client2
- Если используете systemd — не включайте профиль `bot`, watchdog не перезапускает ботов

## 3. Мониторинг (Loki, Prometheus, Grafana)
- Логи: campus-server, client1, client2
- Метрики: CPU, RAM, диск
- Алерты в Telegram
- При монтировании SSD client1 — данные Loki/Prometheus на SSD

## 4. Автовосстановление
- **campus-watchdog**: перезапуск контейнеров (loki, grafana, prometheus, promtail, node-exporter, campus-recovery) и systemd на client1/client2 (node_exporter, promtail)
- **campus-recovery**: бэкапы, проверка client1/client2, восстановление при сбое

---

## Быстрый старт

```bash
cd /home/kamran/campus-infra

# На client1 (один раз): подготовить каталоги (IP — campus-secrets/server/infra-values.md)
ssh client1@<IP client1> 'sudo mkdir -p /mnt/campus-data/{loki,prometheus,backups} && sudo chown -R client1:client1 /mnt/campus-data'

# На CentOS: примонтировать SSD (опционально, для экономии места)
sudo bash scripts/mount-client1-ssd-on-centos.sh

# Запуск всего
bash scripts/start-all.sh up
```

---

## Проверка

```bash
docker compose --profile logs --profile bot --profile watchdog --profile recovery ps
curl -s http://<IP сервера>:<порт Grafana>  # Grafana
curl -s http://<IP сервера>:<порт Loki>/ready  # Loki
```
