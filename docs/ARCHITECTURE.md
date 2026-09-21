# Архитектура (коротко)

## Сервер (CentOS, 10.10.4.120, пользователь kamran)

| Компонент | Как запущен | Порт |
|---|---|---|
| **Веб-панель** `campus-webui` (Flask + gunicorn gthread, HTTPS, сертификат хранится в `data/webui/`) | Docker Compose, профиль `webui` | 8090 (внутри 8080) |
| Prometheus / Grafana / Loki / promtail | Docker Compose, профиль `logs` | 9091 / 3000 / 3100 |
| Cockpit (веб-консоль сервера) | Docker Compose, профиль `cockpit` | 1991 |
| Helpdesk Ops (тикеты, ежедневные отчёты) | отдельный compose в `~/projects/helpdesk-ops` | 8094 |
| Telegram-бот Клиент 1а | systemd `tg-campus-client1` (`/opt/tg-campus-bot`) | — |
| Автосинхронизация с GitHub | `github-live-sync.sh` + watchdog (cron `@reboot`, `*/5`) | — |
| Часы кампусов, дайджест, бэкапы, Zəfər Günü | cron (см. `state/crontab.txt`) | — |

Данные веб-панели: `data/webui/` (`webui.db`, `schedule.json`, `special_sounds/` — гимн, минута, NMD, Zəfər; `alarm_sounds/`, обои).
Конфигурация контейнеров — `docker-compose.yaml`, секреты — `.env` (не в GitHub).

## Кампусы (клиентские машины)

Список — на странице «Машины» (хранится в БД, копия `state/machines.json`). На каждом кампусе:
`mpv` с JSON-сокетом `/run/campus-player/mpv.sock`, обёртка `campus-playerctl`, PulseAudio, локальный cron (звонки по расписанию,
гимн по понедельникам (Клиент 1 08:30, Баил 08:00) — работает без интернета и без входа в систему), анализатор звука для визуализатора, `node_exporter` и `promtail`.
Панель управляет ими по SSH (ключ `campus_bot`) и через сокет mpv; статус всех кампусов — одним запросом `/api/status-all`.
Установка/переустановка кампуса: `machines/<кампус>/install.sh` (см. `docs/DISASTER-RECOVERY.md`).

## Веб-панель (`webui/app.py`)

* Общий плеер (JS в `templates/dashboard.html`) и 7 вариантов оформления — `docs/UI-DESIGN.md`.
* Роли и 39 привилегий — `docs/ROLES-PERMISSIONS.md`. Переводы RU/EN/AZ — `docs/I18N.md`.
* Спецсигналы (гимн, минута тишины, тревога, Zəfər Günü, National Music Day), микрофон/голос, перемены вне расписания,
  «Стоп» с выбором кампуса, синхронизация времени, библиотека треков с PIN-папками, журнал активности, чат, объявления,
  мониторинг, шпаргалка, SSH-терминал (по праву).
* Резервное копирование и восстановление — `RESTORE.md`, `docs/BACKUP-AND-RESTORE.md`.

## Журнал изменений

`docs/journal/ГГГГ-ММ-ДД.md` — ведётся автоматически (что менялось, кто кому выдал права, какие машины добавлены) + ручные заметки.
