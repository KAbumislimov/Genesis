# Promtail на клиентах и алерты в Telegram

## 1. Promtail на nctk и vm1

Клиенты сами отправляют логи в Loki на сервере (http://10.10.4.120:3100). Rsync и sync-remote-logs больше не нужны.

### Установка

С **campus-server** (CentOS):

```bash
cd /home/kamran/campus-infra
bash deploy-monitoring-offline.sh
```

Скрипт:
- Скачивает node_exporter и promtail (если ещё нет в кэше)
- Копирует на nctk (10.20.0.41) и vm1 (10.70.0.41)
- Устанавливает systemd и запускает сервисы (нужен passwordless sudo)

SSH-ключ: `campus_bot` или `id_rsa` (переменная `SSH_KEY`).

### Проверка

```bash
curl -s http://10.20.0.41:9100/metrics | head -3
curl -s http://10.70.0.41:9100/metrics | head -3
```

В Grafana → Explore (Loki): `{host="nctk"}` или `{host="vm1"}`.

---

## 2. Алерты в Telegram

Настроены через provisioning:
- `config/grafana-provisioning/alerting/contactpoints.yaml` — Telegram
- `config/grafana-provisioning/alerting/policytree.yaml` — маршрутизация

В `.env`:
```
NOTIFICATION_BOT_TOKEN=...
NOTIFICATION_CHAT_ID=-1003491812335
```

**Важно:** если Grafana падает с ошибкой `chatid of type string`, задайте в `.env`:
```
NOTIFICATION_CHAT_ID='-1003491812335'
```

После изменения конфигов:
```bash
docker compose --profile logs restart grafana
```

### Алерты

- CPU > 90%
- RAM > 90%
- Диск / > 90%
- Node Exporter недоступен (падение хоста)
- Ошибки/OOM/перегрев в логах
- Критичные ошибки (panic, segfault)

---

## 3. Отключение sync-remote-logs

После успешного перехода на Promtail отключите cron:

На **nctk** (где настроен cron):
```bash
crontab -e
# Удалите строку с sync-remote-logs.sh
```

Или:
```bash
bash scripts/disable-sync-remote-logs.sh
```

---

## 4. Изменения в конфигах

- `config/promtail-config.yaml` — удалены jobs remote-nctk и remote-vm1
- `promtail-clients/promtail-nctk.yaml`, `promtail-vm1.yaml` — расширены пути логов
