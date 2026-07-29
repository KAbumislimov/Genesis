# Запуск всего: 4 главных компонента

## 1. Бэкапы (campus-recovery)
- Бэкапы server, nctk, vm1 раз в сутки
- Копирование на nctk в `/mnt/campus-data/backups` (если SYNC_BACKUPS_TO_NCTK=1)
- Уведомления в Telegram

## 2. Telegram-боты
- tg-campus-bot (narimanov), tg-campus-genclik
- Если используете systemd — не включайте профиль `bot`, watchdog не перезапускает ботов

## 3. Мониторинг (Loki, Prometheus, Grafana)
- Логи: campus-server, nctk, vm1
- Метрики: CPU, RAM, диск
- Алерты в Telegram
- При монтировании SSD nctk — данные Loki/Prometheus на SSD

## 4. Автовосстановление
- **campus-watchdog**: перезапуск контейнеров (loki, grafana, prometheus, promtail, node-exporter, campus-recovery) и systemd на nctk/vm1 (node_exporter, promtail)
- **campus-recovery**: бэкапы, проверка nctk/vm1, восстановление при сбое

---

## Быстрый старт

```bash
cd /home/kamran/campus-infra

# На nctk (один раз): подготовить каталоги
ssh nctk@10.20.0.41 'sudo mkdir -p /mnt/campus-data/{loki,prometheus,backups} && sudo chown -R nctk:nctk /mnt/campus-data'

# На CentOS: примонтировать SSD (опционально, для экономии места)
sudo bash scripts/mount-nctk-ssd-on-centos.sh

# Запуск всего
bash scripts/start-all.sh up
```

---

## Проверка

```bash
docker compose --profile logs --profile bot --profile watchdog --profile recovery ps
curl -s http://10.10.4.120:3000  # Grafana
curl -s http://10.10.4.120:3100/ready  # Loki
```
