# Настройка Grafana: дашборды, метрики, алерты

## Запуск

```bash
cd /home/kamran/campus-infra
docker compose --profile logs --profile bot --profile watchdog up -d
```

Grafana: http://10.10.4.120:3000 (admin / пароль из .env)

### Если Grafana в Docker постоянно перезапускается (`docker ps` — Restarting)

Частая причина — **provisioning алертов** (`config/grafana-provisioning/alerting/`) при пустых `NOTIFICATION_BOT_TOKEN` / `NOTIFICATION_CHAT_ID`. В `docker-compose.yaml` по умолчанию смонтированы только **datasources** и **dashboards** (папка Campus появится после стабильного старта).

После правки compose:

```bash
cd /home/kamran/campus-infra
docker compose --profile logs up -d grafana
docker logs grafana --tail 30
```

Чтобы снова подключить файловые алерты и Telegram contact point: задайте переменные в `.env`, раскомментируйте в `docker-compose.yaml` строку с `.../alerting:/etc/grafana/provisioning/alerting:ro`, включите унифицированные алерты в Grafana при необходимости и перезапустите контейнер.

## Что уже настроено (provisioning)

- **Loki** — логи со всех машин
- **Prometheus** — метрики CPU, RAM, диск (node_exporter)
- **Дашборд "Campus Overview"** — логи + метрики
- **Contact point** — добавьте вручную (см. ниже), т.к. provisioning требует chat_id в формате строки

## Добавить Contact point Telegram (вручную)

1. Grafana → Alerting → Contact points → New contact point
2. Name: `telegram-campus`
3. Integration: **Telegram**
4. BOT API Token: из `.env` → `NOTIFICATION_BOT_TOKEN`
5. Chat ID: из `.env` → `NOTIFICATION_CHAT_ID` (как **строка**, например `-1003491812335`)
6. Save

## Дашборд «матрица хостов»

В Grafana: **Campus → Campus — матрица хостов (CPU, RAM, диск, температура)** (`campus-hosts-matrix`).

Показывает **10.10.4.120** (campus-server), **10.20.0.41** (nctk), **10.70.0.41** (vm1), **10.20.1.106** (цель Prometheus `host-10.20.1.106`). Для последней машины на ней должен быть запущен **node_exporter** на порту 9100 и доступ с хоста, где крутится Prometheus.

Температура берётся из `node_hwmon_temp_celsius` (максимум по датчикам). На ВМ без hwmon панель будет пустой.

## Структурированные логи (Landau, cron, боты)

На **vm1** и **nctk** в `promtail-clients/promtail-*.yaml` добавлены job-ы:

- `campus_landau` — `/home/vm1/action.log` или `/home/nctk/action.log`, плюс `/tmp/landau-cron.log`
- `cron` — `/var/log/cron*` (если файлов нет, promtail просто не хватает строк)
- `campus_bot` — опционально `/var/log/campus-bot*.log`

На **campus-server** promtail читает **stdout Docker** контейнеров `tg-campus-bot` и `tg-campus-genclik` с меткой `job=campus_telegram_bot` (нужен перезапуск compose для promtail с `docker.sock`).

После обновления конфигов:

```bash
# vm1: путь как в `systemctl status promtail` (часто /home/vm1/..., не /tmp/...)
scp promtail-clients/promtail-vm1.yaml vm1@10.70.0.41:/home/vm1/campus-monitoring/promtail/config.yaml
ssh vm1@10.70.0.41 'sudo systemctl restart promtail'
# то же для nctk с promtail-nctk.yaml
cd /home/kamran/campus-infra && docker compose --profile logs up -d promtail
```

Если promtail на клиенте в **Docker** и смонтирован только `/var/log`, добавьте том для чтения `action.log`, например `-v /home/vm1/action.log:/home/vm1/action.log:ro` (или каталог `/home/vm1`).

## Настроенные алерты (provisioning)

| Правило | Описание |
|---------|----------|
| Ошибки в логах | error, ОШИБКА, exception, failed |
| Память заполнена / OOM | oom, out of memory, killed |
| Перегрев | thermal, throttl, overheat, temperature |
| Нет интернета / сеть | network unreachable, connection refused, timeout |
| Выключение / перезагрузка | shutdown, poweroff, reboot |
| Диск заполнен (логи) | no space left, disk full, ENOSPC |
| Критичные ошибки | kernel panic, segfault, fatal |
| CPU перегрузка | > 90% (метрики) |
| Память заполнена | > 90% (метрики) |
| Диск заполнен | > 90% (метрики) |

## Добавить алерт вручную

1. Grafana → Alerting → Alert rules → New alert rule
2. **Set a query and alert condition:**
   - Section 1: Add query
   - Data source: Loki
   - LogQL: `count_over_time({job=~"varlogs|messages|secure"} |~ "(?i)(error|ОШИБКА|exception|failed)" [5m]) > 0`
   - Ref ID: A
3. **Set a condition:** Reduce → last value of A → IS ABOVE 0
4. **Configure labels and notifications:**
   - Contact point: **telegram-campus**
5. Save

## Поиск по логам

Explore → Loki → ввести запрос, например:
- `{host="campus-server"}` — все логи сервера
- `{host="nctk"}` — логи nctk
- `{job="varlogs"} |~ "error"` — логи с "error"

## Метрики и логи nctk, vm1

Дашборд показывает **отдельно** campus-server, nctk, vm1. Чтобы данные nctk и vm1 появились:

### 1. node_exporter (метрики CPU, RAM, диск)

На **nctk** (10.20.0.41):
```bash
docker run -d --name node-exporter --restart unless-stopped -p 9100:9100 \
  -v /proc:/host/proc:ro -v /sys:/host/sys:ro -v /:/rootfs:ro \
  prom/node-exporter:v1.6.1 \
  --path.procfs=/host/proc --path.sysfs=/host/sys --path.rootfs=/rootfs
```

На **vm1** (10.70.0.41) — та же команда.

### 2. Promtail (логи)

**Если Docker не установлен** на nctk/vm1 — используйте:
```bash
bash deploy-monitoring-clients-no-docker.sh
```
Скрипт установит node_exporter (apt) и promtail (бинарник) через systemd.

**Если Docker установлен** — используйте `deploy-monitoring-clients.sh`.
