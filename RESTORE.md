# Восстановление всей системы из GitHub

> **Одна команда на новой или пустой машине** (CentOS 9 / Ubuntu, обычный пользователь с `sudo`):
>
> ```bash
> export GH_TOKEN=ghp_xxxxxxxx     # токен GitHub с доступом к репозиториям campus-infra и campus-secrets
> git clone --depth 1 https://${GH_TOKEN}@github.com/KAbumislimov/campus-infra.git /tmp/ci \
>   && bash /tmp/ci/projects/campus-infra/restore.sh
> ```
>
> Если репозиторий уже на машине: `bash ~/projects/campus-infra/restore.sh`
>
> **Пошаговая инструкция «что куда вставлять» — в [README.md в корне репозитория](../../README.md).**

Скрипт сам: ставит Docker/Git/cron → получает код (частичный клон ≈ 100 МБ) → берёт секреты из `campus-secrets` →
возвращает **пользователей, роли и права, настройки, список машин, расписание** и **Helpdesk Ops** (тикеты, отчёты, вложения)
из зашифрованных снимков → ставит crontab и systemd-службы (Telegram-бот и др.) → открывает порты →
поднимает все контейнеры → по вопросу переустанавливает кампусные клиенты → проверяет, что панель отвечает.

## Проверка «а восстановится ли?» — без изменений на машине

```bash
bash ~/projects/campus-infra/restore.sh --verify
```

Проверяет: репозиторий и GitHub доступны, `.env` и ключ расшифровки на месте, **снимки БД расшифровываются и целы**
(показывает число пользователей, прав, тикетов), unit-файлы и crontab в снимке есть, `docker-compose.yaml` разбирается.
Делайте это раз в месяц и после крупных изменений. Итог: `ГОТОВО` или список проблем `✗`.

## Опции

| Опция | Что делает |
|---|---|
| `--verify` | только проверка, ничего не меняет |
| `--state-only` | только данные (БД, права, настройки), без контейнеров/cron/служб |
| `--no-clients` | не трогать кампусные машины (client1, client2 …) |
| `--force-data` | заменить существующие БД снимками из GitHub (старые сохраняются рядом как `*.before_restore_*`) |
| `--yes` | не задавать вопросов |

## Что где хранится

| Что | Где | Как попадает |
|---|---|---|
| Код, шаблоны, конфиги, скрипты кампусов, документация | GitHub `campus-infra` | автоматически: `github-live-sync.sh` проверяет изменения каждые 45 с и пушит; плюс часовой cron |
| **Пользователи, РОЛИ И ПРАВА, настройки, машины, журнал** | `state/webui.db.enc` (зашифровано) + читаемые `state/roles.json`, `settings.json`, `machines.json` | `scripts/export_state.py` перед каждым коммитом |
| Helpdesk Ops: тикеты, отчёты, вложения | `state/helpdesk_ops.db.enc`, `state/helpdesk_ops_uploads.tar.gz.enc` | тем же скриптом, раз в сутки |
| crontab, systemd-службы, NTP-конфиг сервера | `state/crontab.txt`, `state/systemd/`, `state/etc/` | тем же скриптом |
| **Секреты**: `.env`, токены ботов, SSH-ключ `campus_bot`, **ключ шифрования снимков** | GitHub `campus-secrets` (приватный) | вручную; в `campus-infra` секретов нет (защита `.gitignore` + проверка перед коммитом) |
| Что и когда менялось | `docs/journal/ГГГГ-ММ-ДД.md` | автоматически: `scripts/update_journal.py` |
| Media (звонки/гимн, ~800 МБ) | диск сервера + еженедельный бэкап на Proxmox | **не в GitHub**; восстановление: `scripts/restore-music.sh` |
| Музыкальная библиотека «Kamran Music» (~33 ГБ) | только диск сервера | **нигде не бэкапится** — нужна отдельная копия |

Снимки шифруются (`AES-256`, ключ `BACKUP_VAULT_PASS` из `.env`, который живёт только в `campus-secrets`).
Без токена `campus-secrets` данные из GitHub прочитать нельзя — это сделано намеренно.

## Если что-то пошло не так

* Логи: `~/log/restore-git.log`, `docker logs campus-webui --tail 100`.
* Только поднять контейнеры (код уже есть): `cd ~/projects/campus-infra && docker compose --profile webui --profile logs --profile bot --profile cockpit --profile helpdesk up -d --build`.
* БД не восстановилась из снимка → `python3 scripts/import_state.py verify` покажет причину (обычно неверный ключ). Запасной путь: `restore.sh` сам применит роли/настройки/машины из JSON (пользователей придётся создать заново).
* Кампусные машины по одной: `bash machines/<кампус>/install.sh` (см. `docs/DISASTER-RECOVERY.md`).
* Старая версия скрипта: `scripts/legacy/restore-v1.sh`.

## После восстановления вручную

1. **Доступ к GitHub для автосинхронизации.** Если на новой машине нет SSH-ключа GitHub, скрипт оставит HTTPS-remote с токеном. Лучше:
   `ssh-keygen -t ed25519` → добавить ключ в GitHub (Settings → SSH keys) → `git -C ~ remote set-url origin git@github.com:KAbumislimov/campus-infra.git`.
2. Новая сетевая карта = новый MAC: обновить `CLIENT1_MAC` в `.env` (Wake-on-LAN).
3. Проверить `https://<адрес сервера>:8090` — вход под своим логином (пользователи вернулись из снимка).
4. `bash restore.sh --verify` ещё раз — убедиться, что цепочка резервного копирования снова замкнулась.

Подробности и устройство бэкапов: [docs/BACKUP-AND-RESTORE.md](docs/BACKUP-AND-RESTORE.md).
