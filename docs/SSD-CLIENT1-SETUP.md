# Настройка SSD 512 ГБ на client1 (10.20.0.41) для хранения данных Loki/Prometheus

Сервер CentOS (10.10.4.120) переполнен.  
SSD на client1 используется через **SSHFS** (не требует интернета на client1, не требует NFS).

## Схема

```
client1 (10.20.0.41)                    CentOS (10.10.4.120)
┌─────────────────────┐              ┌─────────────────────────┐
│ SSD 512 GB (USB)    │   SSHFS      │ Docker                  │
│ /mnt/campus-data/   │ ◄──────────  │ loki_data    → SSHFS    │
│  ├── loki/          │   (SSH)      │ prometheus_data → SSHFS │
│  └── prometheus/    │              │ grafana_data  → локально│
└─────────────────────┘              └─────────────────────────┘
```

## Шаг 1: На client1 (10.20.0.41) — SSD и NFS

```bash
ssh client1@10.20.0.41
```

### 1.1 Найти диск (USB-SATA)

```bash
lsblk
# Ищите диск ~512G, например /dev/sdb
sudo fdisk -l /dev/sdb   # подставьте свой диск
```

### 1.2 Создать раздел и отформатировать (если ещё не сделано)

```bash
# ВНИМАНИЕ: это удалит все данные на диске!
sudo parted /dev/sdb mklabel gpt
sudo parted /dev/sdb mkpart primary ext4 0% 100%
sudo mkfs.ext4 -L campus-data /dev/sdb1
```

### 1.3 Примонтировать

```bash
sudo mkdir -p /mnt/campus-data
# Добавить в /etc/fstab для автозагрузки:
echo 'LABEL=campus-data /mnt/campus-data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a
df -h /mnt/campus-data
```

### 1.4 Создать каталоги для данных

При **SSHFS** контейнеры пишут от имени пользователя client1 (не 10001/65534), поэтому нужны права 777:

```bash
sudo mkdir -p /mnt/campus-data/loki /mnt/campus-data/prometheus
sudo chmod 777 /mnt/campus-data/loki /mnt/campus-data/prometheus
```

Если Loki/Prometheus уже падают с `permission denied`, выполните на client1:

```bash
# На client1 или с CentOS:
ssh client1@10.20.0.41 'sudo chmod 777 /mnt/campus-data/loki /mnt/campus-data/prometheus'
```

Либо запустите скрипт: `ssh client1@10.20.0.41 'sudo bash -s' < scripts/fix-ssd-permissions-on-client1.sh`

### 1.5 NFS не нужен

При использовании SSHFS на client1 **не нужны** ни интернет, ни nfs-kernel-server.  
Достаточно SSH (уже работает).

---

## Шаг 2: На CentOS (10.10.4.120) — монтировать через SSHFS

```bash
cd /home/kamran/campus-infra
```

### 2.1 Разрешить allow_other (для доступа Docker)

```bash
echo 'user_allow_other' | sudo tee -a /etc/fuse.conf
```

### 2.2 Установить SSHFS и примонтировать

```bash
sudo dnf install -y fuse-sshfs
bash scripts/mount-client1-ssd-on-centos.sh
```

SSH-ключ kamran → client1 должен быть без пароля (или используйте ssh-agent).

### 2.3 Включить использование SSD в campus-infra

```bash
cd /home/kamran/campus-infra
echo 'DOCKER_DATA_PATH=/mnt/client1-ssd' >> .env
```

Запуск с SSD:
```bash
bash scripts/start-with-ssd.sh up -d
# или
COMPOSE_FILE=docker-compose.yaml:docker-compose.ssd.yaml docker compose --profile logs up -d
```

### 2.4 Миграция данных (если Loki/Prometheus уже запускались)

```bash
cd /home/kamran/campus-infra

# Остановить сервисы
docker compose --profile logs stop loki prometheus grafana

# Скопировать существующие данные (если есть)
docker run --rm -v campus-infra_loki_data:/from -v /mnt/client1-ssd/loki:/to alpine cp -a /from/. /to/
docker run --rm -v campus-infra_prometheus_data:/from -v /mnt/client1-ssd/prometheus:/to alpine cp -a /from/. /to/

# Запустить с SSD (с COMPOSE_FILE из .env)
docker compose --profile logs up -d
```

---

## Шаг 3: Проверка

```bash
docker compose --profile logs ps
df -h /mnt/client1-ssd
du -sh /mnt/client1-ssd/*
```

Grafana: http://10.10.4.120:3000 (admin / см. campus-secrets)

---

## Важно

- **grafana_data** остаётся на локальном диске CentOS (SQLite не любит NFS)
- **loki_data** и **prometheus_data** — на SSD через SSHFS
- При перезагрузке client1 CentOS не сможет писать на SSHFS до его включения

## Синхронизация логов (client1, client2)

Чтобы в Grafana отображались логи с client1 и client2, запускайте периодически:

```bash
# Вручную
bash scripts/sync-remote-logs.sh

# Или через cron (каждую минуту)
(crontab -l 2>/dev/null; echo '* * * * * cd /home/kamran/campus-infra && bash scripts/sync-remote-logs.sh') | crontab -
```

Требуется SSH-доступ без пароля: `ssh client1@10.20.0.41` и `ssh client2@10.70.0.41`. Ключ по умолчанию: `~/.ssh/campus_bot` (или задайте `SSH_KEY` в окружении).

## Node exporter на клиентах (client1, client2)

Метрики CPU/RAM/Disk приходят с node_exporter. Установите его на client1 и client2:

```bash
# Есть скрипты:
bash scripts/ensure-node-exporter-on-clients.sh
# или
bash scripts/install-node-exporter-systemd-on-clients.sh
```
