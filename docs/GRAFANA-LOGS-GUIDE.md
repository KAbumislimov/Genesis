# Grafana: логи, фильтры и полезные возможности

## 1. Почему нет логов с client2?

**Проверьте на client2:**
```bash
# Promtail запущен?
sudo systemctl status promtail

# Туннель активен? (на centos)
systemctl status loki-tunnel-client2

# Логи Promtail — есть ли ошибки?
journalctl -u promtail -n 20 --no-pager
```

**Если promtail не перезапускался после настройки туннеля:**
```bash
# На centos — обновить конфиг и перезапустить
cd /home/kamran/campus-infra
scp -i ~/.ssh/campus_bot promtail-clients/promtail-client2.yaml client2@10.70.0.41:/home/client2/campus-monitoring/promtail/config.yaml
ssh client2@10.70.0.41 "sudo systemctl restart promtail"
```

**В Grafana:** проверьте временной диапазон (правый верхний угол) — выберите "Last 15 minutes" или "Last 1 hour".

---

## 2. Хорошие и плохие логи — как понимать

### Уровни серьёзности (от плохого к хорошему)

| Уровень | Значение | Когда смотреть |
|---------|----------|----------------|
| **ERROR / FATAL** | Критично | Сразу — что-то сломалось |
| **WARN / WARNING** | Внимание | Периодически — возможные проблемы |
| **INFO** | Норма | При отладке — обычная работа |
| **DEBUG** | Детали | Редко — глубокий разбор |

### Типичные «плохие» паттерны

- `error`, `ERROR`, `ОШИБКА`, `failed`, `FAILED`
- `exception`, `traceback`, `panic`
- `denied`, `permission denied`, `access denied`
- `timeout`, `timed out`, `connection refused`
- `fatal`, `critical`, `out of memory`
- `segfault`, `killed`

### «Хорошие» логи

- `started`, `listening`, `ready`, `success`
- `INFO` от стабильно работающих сервисов

---

## 3. Фильтры в Grafana (LogQL)

### Базовый синтаксис

```
{host="client2"}                    # Все логи с client2
{host="client2", job="syslog"}       # Только syslog с client2
{host=~"client2|client1"}              # client2 или client1
{job="campus_media"}           # Звонки Media / campus-cron (action.log, /tmp/media-cron.log)
{host="client2", job="campus_media"}
{job="cron"}                    # Файл демона cron (/var/log/cron*), если есть на ОС
{job="campus_telegram_bot"}     # Stdout контейнеров tg-campus-* на campus-server
{job="campus_bot"}              # Опционально /var/log/campus-bot*.log на клиентах
```

### Только ошибки и предупреждения

```
{host="client2"} |~ "(?i)(error|failed|denied|exception|timeout|fatal)"
```

### Исключить шум (например, AppArmor Rocket.Chat)

```
{host="client2"} !~ "snap.rocketchat-server"
```

### Комбинация: ошибки, но без AppArmor

```
{host="client2"} |~ "(?i)(error|failed|denied)" !~ "snap.rocketchat-server"
```

### По конкретному файлу

```
{host="client2", filename=~"/var/log/syslog"}
```

---

## 4. Полезные возможности Grafana

### Алерты

- **Alerting** → Contact points → добавить Telegram
- В панели: Edit → Alert → Create alert rule
- Пример: CPU > 90% 5 минут → уведомление в Telegram

### Аннотации

- События на графиках (деплой, перезапуск)
- Correlate → добавить аннотации из Loki по `deploy` или `restart`

### Дашборды

- **Explore** — свободный поиск по логам и метрикам
- **Variables** — выпадающий список хостов: `host=~"$host"`
- **Links** — переход из панели в детальный дашборд

### Связка логов и метрик

- На графике CPU — клик по пику → Explore → логи за это время
- Или: в панели логов добавить `__error__` как метрику

### Полезные панели

- **Heatmap** — распределение задержек
- **Stat** — один показатель (например, количество ошибок)
- **Table** — топ ошибок по типу
- **Bar gauge** — сравнение хостов

---

## 5. Быстрые запросы для Explore

| Цель | Запрос |
|------|--------|
| Все ошибки | `{job=~"varlogs|syslog"} \|~ "(?i)error"` |
| Только client2, ошибки | `{host="client2"} \|~ "(?i)(error|failed)"` |
| Auth-логи (входы) | `{job="auth"}` или `{filename=~"/var/log/auth.log"}` |
| Kernel | `{job="kern"}` или `{filename=~"/var/log/kern.log"}` |
| Без AppArmor | `{host="client2"} !~ "rocketchat"` |

---

## 6. Рекомендуемый порядок действий

1. **Убедиться, что логи приходят** — client2, client1, campus-server в панелях.
2. **Сделать панель «Только ошибки»** — фильтр по error/failed/denied.
3. **Исключить шум** — AppArmor Rocket.Chat и т.п.
4. **Настроить алерты** — CPU, RAM, критические ошибки в Telegram.
5. **Добавить переменную `$host`** — переключать хосты без правки запросов.
