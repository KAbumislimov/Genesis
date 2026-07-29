# Проверка крона перемен для vm1 — запускать на СЕРВЕРЕ

Команды ниже выполняются **на сервере** (kamran@centos / 10.10.4.120), а не на vm1.

Подключитесь к серверу, затем:

```bash
# Лог (последние записи по vm1)
tail -30 /home/kamran/campus-infra/cron-landau.log

# Скрипт проверки
/home/kamran/campus-infra/scripts/check-cron-vm1.sh

# Ручной тест воспроизведения на vm1
HOME=/home/kamran ENV_FILE=/home/kamran/vm1.env /home/kamran/bin/campus-cron-landau.sh 1peremena

# Крон установлен?
crontab -l | grep campus-cron
# или от kamran:
sudo -u kamran crontab -l | grep campus-cron
```

---

**На самой vm1** можно только убедиться, что плеер и inbox на месте:

```bash
ls -la /var/lib/campus-player/inbox
/usr/local/bin/campus-playerctl status
```

Лог и скрипты крона на vm1 не лежат — крон крутится на сервере и по SSH отдаёт команды на vm1.
