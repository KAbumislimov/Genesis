# Мониторинг Campus — руководство

## Быстрое восстановление (нет логов/метрик)

```bash
cd /home/kamran/campus-infra
bash scripts/fix-logs-and-metrics.sh
```

Скрипт: запускает Grafana, Loki, Promtail, Prometheus; проверяет туннели nctk/vm1; при цикле перезапуска Grafana — сбрасывает volume.

**Туннели** (логи с nctk и vm1): `sudo systemctl start loki-tunnel-nctk loki-tunnel-vm1`  
**Полная настройка туннелей:** `bash scripts/setup-loki-tunnels.sh`

---

## Деплой (важно)
При копировании на сервер **исключайте** `remote-logs` — там сотни МБ логов, они создаются на сервере:
```bash
rsync -avz --exclude '.git' --exclude 'remote-logs' /home/kamran/campus-infra/ kamran@10.10.4.120:/home/kamran/campus-infra/
```
Или используйте: `bash scripts/deploy-to-server.sh`

## Автозапуск (всё всегда работает)

### Campus-server (10.10.4.120)
- **Docker** — сервисы с `restart: unless-stopped` запускаются после перезагрузки
- **Cron** — `sync-remote-logs.sh` каждую минуту (установить: `bash scripts/install-sync-logs-cron.sh`)
- **Полная настройка:** `bash scripts/install-auto-start.sh`

### nctk и vm1 (node_exporter + promtail)
Для автозапуска после перезагрузки — установить systemd (один раз, с sudo):
```bash
# На nctk:
sudo cp /home/nctk/promtail/node_exporter.service /etc/systemd/system/
sudo cp /home/nctk/promtail/promtail.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now node_exporter promtail

# Аналогично на vm1
```

---

## Дашборды Grafana

| Дашборд | Назначение |
|---------|------------|
| **Campus Overview** | Метрики (CPU, RAM, диск) + логи по каждому хосту |
| **Campus Logs** | Группы логов: универсальный, системные, ошибки, по хостам |

### Группы логов
- **Универсальный** — всё что происходит на всех серверах (`{}`)
- **Системные** — syslog, messages, kern, auth
- **Ошибки** — только строки с error, exception, failed
- **По хостам** — campus-server, nctk, vm1 отдельно

---

## Мобильный доступ (Samsung A55 и др.)

### Шаг 1: Сеть
Телефон должен быть в той же сети, что и campus-server (10.10.4.120):
- **Wi‑Fi кампуса** — подключитесь к той же точке, что и сервер
- **Дома/вне кампуса** — нужен VPN в сеть кампуса

### Шаг 2: Браузер
Откройте в браузере (Chrome, Samsung Internet): **http://10.10.4.120:3000**

- Логин: `admin` (или из `.env`: `GRAFANA_USER`)
- Пароль: из `.env` (`GRAFANA_PASSWORD`)

### Шаг 3: Закладка
Сохраните в закладки дашборд: **http://10.10.4.120:3000/d/campus-overview**

Grafana адаптивна — 8 ГБ ОЗУ телефона достаточно для комфортного просмотра.

### Вариант 2: Grafana IRM (для алертов)
- **iOS:** [App Store — Grafana IRM](https://apps.apple.com/us/app/grafana-irm/id1669759048)
- **Android:** Google Play — «Grafana IRM»

Приложение для управления алертами и уведомлениями (требует Grafana OnCall или Cloud).

### Вариант 3: Прямая ссылка
Сохраните в закладки: `http://10.10.4.120:3000/d/campus-overview`

---

## Что ещё можно сделать с Grafana

- **Алерты в Telegram** — настроить Contact point (Alerting → Contact points)
- **Explore** — свободный поиск по логам и метрикам
- **Трассировка** — добавить Tempo для распределённой трассировки
- **Доп. дашборды** — Node Exporter Full, Loki, Prometheus
- **Плагины** — календарь, worldmap и др.
