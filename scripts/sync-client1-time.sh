#!/bin/bash
# Синхронизация времени client1 с сервера — запускается с 10.10.4.120 по cron
SSH_KEY="/home/kamran/.ssh/campus_bot"
CLIENT1="client1@10.20.0.41"
LOG="/home/kamran/log/client1-timesync.log"
mkdir -p "$(dirname "$LOG")"

# Локальное время сервера — timedatectl set-time ожидает LOCAL, не UTC
STIME=$(date '+%Y-%m-%d %H:%M:%S')

ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=8 "$CLIENT1" "
# Сервис устанавливает время от root
cat > /tmp/_tfix.sh << 'SH'
#!/bin/bash
timedatectl set-ntp false 2>/dev/null
timedatectl set-time '__STIME__' 2>/dev/null && echo 'time set ok' || true
sleep 1
timedatectl set-ntp true 2>/dev/null
SH
sed -i 's/__STIME__/${STIME}/g' /tmp/_tfix.sh

cat > /tmp/_tfix.service << 'SVC'
[Unit]
Description=Campus time correction
DefaultDependencies=no
After=network.target
[Service]
Type=oneshot
ExecStart=/bin/bash /tmp/_tfix.sh
SVC
sudo /bin/mv /tmp/_tfix.service /etc/systemd/system/campus-timecorrect.service
sudo /bin/systemctl daemon-reload
sudo /bin/systemctl start campus-timecorrect.service
echo 'done'
"

STATUS=$?
sleep 2
CLIENT1_TIME=$(ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 "$CLIENT1" "date '+%Y-%m-%d %H:%M:%S'" 2>/dev/null)
SERVER_TIME=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$(date '+%F %T')] server=$SERVER_TIME client1=$CLIENT1_TIME exit=$STATUS" >> "$LOG"
