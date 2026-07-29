# Disaster Recovery: сгоревший/заменённый тонкий клиент

Сценарий: свет пропал, при включении клиент кампуса (client1 или client2) не поднялся —
физически сгорел. Принесли новую машину на замену. Что делать, чтобы всё
заработало точно так же, как было.

## Что уже автоматизировано

| Шаг | Скрипт | Откуда запускать |
|---|---|---|
| Пакеты, плеер, боты, cron, мониторинг, FFT-визуализатор | `machines/<campus>/install.sh` | На новой машине кампуса |
| SSH-доступ сервера к новой машине без пароля | `scripts/setup-recovery-ssh-keys.sh` | С центрального сервера |
| Cockpit (веб-консоль машины) | `scripts/restore-client1.sh` / `scripts/restore-client2.sh` | С центрального сервера |
| Конфиги ботов/секреты | `bootstrap.sh` | С центрального сервера |

## Что НЕ автоматизировано (руками)

- **Сама музыка/звонки (`Media`)** — это ~800МБ реального аудио (звонки, гимн,
  плейлисты). `campus-backup.sh` теперь бэкапит эту папку еженедельно на Proxmox
  (`root@10.20.1.106:/mnt/campus-backup/<campus>/media-music.tar.gz` для client1,
  внутри `home-client2.tar.gz` для client2) — но **восстановление на новую машину нужно
  запустить руками** (см. ниже).
- **Сетевые настройки** (статический IP / DHCP-резервация, MAC для Wake-on-LAN
  в `.env` → `CLIENT1_MAC`) — у новой сетевой карты будет новый MAC, `.env` нужно
  обновить вручную.
- **Samba-шара** (`/etc/samba/smb.conf`, `[music]`) — конфиг не в репозитории,
  настраивается руками по образцу со второго кампуса.

## Порядок действий (пошагово)

### 1. На новой машине кампуса

```bash
git clone <репозиторий Genesis или campus-infra>
cd genesis/machines/<campus>
bash install.sh
```

Ставит: mpv, Telegram-бот, node_exporter, promtail, cron-расписание,
audio-analyzer (FFT-визуализатор), все systemd-сервисы. Бот и cron_notify
нужно будет донастроить токенами (`config.env`) — либо руками, либо
через `bootstrap.sh` с сервера (см. ниже).

### 2. С центрального сервера — доступ и конфиги

```bash
cd campus-infra
bash scripts/setup-recovery-ssh-keys.sh     # SSH-доступ без пароля
bash scripts/restore-<campus>.sh            # Cockpit
bash bootstrap.sh <campus>                  # токены ботов из campus-secrets
```

### 3. Восстановить музыку/звонки из бэкапа

```bash
# На Proxmox бэкапы лежат в /mnt/campus-backup/<campus>/<дата>/
# Последний по дате — самый свежий. Скачать и распаковать на новую машину:

scp root@10.20.1.106:/mnt/campus-backup/client1/<дата>/media-music.tar.gz /tmp/
ssh client1@<host> "tar xzf /tmp/media-music.tar.gz -C /mnt/music/"

# client2: Media внутри home-client2.tar.gz
scp root@10.20.1.106:/mnt/campus-backup/client2/<дата>/home-client2.tar.gz /tmp/
ssh client2@<host> "tar xzf /tmp/home-client2.tar.gz -C / --strip-components=2 home/client2/Media"
```

### 4. Обновить сеть

- Узнать MAC новой сетевой карты: `ip link show` на новой машине
- Обновить `CLIENT1_MAC` (или аналог для client2) в `.env` на сервере — иначе Wake-on-LAN
  не будет работать
- Убедиться, что IP машины совпадает с тем, что ожидает `.env`/`docker-compose.yaml`
  (или обновить IP везде, если он изменился)

### 5. Проверка

```bash
bash check-status.sh
curl http://<новый-host>:9100/metrics   # node_exporter отвечает?
```

В веб-панели (`/monitor`) и в Grafana — метрики и статус должны появиться
в течение минуты.

---

**Итог:** после этих правок «пара команд» — это `install.sh` на месте плюс
3-4 команды с сервера. Полностью в одну команду это сделать нельзя из-за
сетевых настроек (MAC/IP меняются физически) и того, что музыку до 800МБ
нет смысла гонять автоматически при каждом деплое — но сам процесс теперь
задокументирован и ничего не теряется.
