# ВОССТАНОВЛЕНИЕ ИНФРАСТРУКТУРЫ CAMPUS

> **Если всё сломалось — одна команда поднимает всё:**
> ```bash
> bash ~/projects/campus-infra/restore.sh
> ```

---

## Что работает и где

| Сервис | URL | Логин |
|--------|-----|-------|
| **Web UI** | http://10.10.4.120:8090 | см. campus-secrets |
| **HelpDesk** | http://10.10.4.120:8091 | см. campus-secrets |
| **Cockpit — CentOS** | http://10.10.4.120:1991 | kamran / (системный) |
| **Cockpit — Клиент 1** | http://10.20.0.41:1991 | client1 / см. campus-secrets |
| **Cockpit — Клиент 2** | http://10.10.4.120:19912 | client2 / см. campus-secrets |
| **Grafana** | http://10.10.4.120:3000 | admin / см. .env |

---

## Машины

| Машина | IP | ОС | Роль |
|--------|----|----|------|
| **CentOS** | 10.10.4.120 | CentOS 9 | Главный сервер, Docker, Web UI |
| **client1** | 10.20.0.41 | Ubuntu 22.04 | Клиент 1 Campus |
| **client2** | 10.70.0.41 | Ubuntu 22.04 | Клиент 2 Campus |

SSH ключ для всех: `~/.ssh/campus_bot`

---

## ВОССТАНОВЛЕНИЕ С НУЛЯ (новый сервер или сбой)

### Один скрипт — всё готово:

```bash
# Клонировать репо
git clone https://github.com/MediaAudioserver/campus-infra.git ~/projects/campus-infra

# Запустить полное восстановление
bash ~/projects/campus-infra/restore.sh
```

Скрипт сам:
1. Обновит код из GitHub
2. Попросит GitHub-токен для campus-secrets и скачает `.env`
3. Восстановит данные БД из последнего бэкапа (если есть)
4. Откроет порты в firewall
5. Пересоберёт и запустит все Docker-контейнеры
6. Покажет статус и URL

### Если только нужно поднять контейнеры (код уже есть):

```bash
cd ~/projects/campus-infra
docker compose --profile webui --profile logs --profile bot --profile cockpit --profile helpdesk up -d --build
```

---

## Где хранятся данные

```
~/projects/campus-infra/
├── data/
│   ├── webui/
│   │   └── webui.db        ← пользователи, тонкие клиенты, настройки
│   └── helpdesk/
│       ├── helpdesk.db     ← обращения в helpdesk
│       └── uploads/        ← прикреплённые фото
├── .env                    ← токены и пароли (из campus-secrets)
└── docker-compose.yaml
```

| Данные | Где |
|--------|-----|
| Код, конфиги | **GitHub: campus-infra** (этот репо) |
| Токены, пароли, .env | **GitHub: campus-secrets** (приватный) |
| БД (пользователи, клиенты) | `data/webui/webui.db` + бэкапы |
| Музыка | `/home/kamran/Kamran Music/` на CentOS |
| Бэкапы БД | `/home/kamran/campus-backups/db/YYYY-MM-DD/` |
| Бэкапы музыки | `/home/kamran/campus-backups/` |
| SSH ключи | `~/.ssh/campus_bot` (копия в campus-secrets) |

---

## Добавить новый тонкий клиент

1. Войди в Web UI → боковое меню → **Тонкие клиенты**
2. Нажми **+ Добавить клиента**
3. Введи IP, имя, MAC (для WoL), SSH-пользователь
4. Сохранить — клиент сразу появится в мониторинге и везде

При восстановлении сервера тонкие клиенты восстанавливаются из `data/webui/webui.db`.

---

## Восстановление client1 / client2

```bash
# client1 (Клиент 1) — если машина переустановлена:
bash ~/projects/campus-infra/scripts/restore-client1.sh

# client2 (Клиент 2) — если машина переустановлена:
bash ~/projects/campus-infra/scripts/restore-client2.sh
```

---

## Бэкап данных (автоматически каждую ночь)

```bash
# Добавить в crontab:
0 3 * * * bash ~/projects/campus-infra/scripts/backup-data.sh

# Бэкапы хранятся в:
~/campus-backups/db/YYYY-MM-DD/webui.db
~/campus-backups/db/YYYY-MM-DD/helpdesk.db
```

---

## Быстрые команды

```bash
# Статус всех контейнеров
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Логи webui
docker logs campus-webui -f --tail 50

# Перезапустить webui
docker compose up -d --build campus-webui

# Перезапустить всё
docker compose --profile webui --profile logs --profile bot --profile cockpit --profile helpdesk restart

# Посмотреть данные webui.db
python3 -c "import sqlite3; c=sqlite3.connect('data/webui/webui.db'); print(c.execute('SELECT count(*) FROM users').fetchone()); print(c.execute('SELECT name,host FROM thin_clients').fetchall())"
```

---

## Если что-то не запускается

```bash
# Смотреть ошибки контейнера
docker logs campus-webui --tail 100
docker logs media-helpdesk --tail 100

# Проверить .env
cat ~/projects/campus-infra/.env | grep -v "TOKEN\|PASS\|SECRET"

# Принудительно пересоздать
docker compose up -d --force-recreate --build campus-webui
```
