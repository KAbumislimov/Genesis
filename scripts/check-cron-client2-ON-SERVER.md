# Проверка крона перемен для client2 — запускать на СЕРВЕРЕ

Команды ниже выполняются **на сервере** (kamran@centos / 10.10.4.120), а не на client2.

Подключитесь к серверу, затем:

```bash
# Лог (последние записи по client2)
tail -30 /home/kamran/campus-infra/cron-media.log

# Скрипт проверки
/home/kamran/campus-infra/scripts/check-cron-client2.sh

# Ручной тест воспроизведения на client2
HOME=/home/kamran ENV_FILE=/home/kamran/client2.env /home/kamran/bin/campus-cron-media.sh 1peremena

# Крон установлен?
crontab -l | grep campus-cron
# или от kamran:
sudo -u kamran crontab -l | grep campus-cron
```

---

**На самой client2** можно только убедиться, что плеер и inbox на месте:

```bash
ls -la /var/lib/campus-player/inbox
/usr/local/bin/campus-playerctl status
```

Лог и скрипты крона на client2 не лежат — крон крутится на сервере и по SSH отдаёт команды на client2.
