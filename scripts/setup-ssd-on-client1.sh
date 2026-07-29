#!/bin/bash
# Настройка SSD 512 ГБ на client1 (10.20.0.41) + NFS export
# Запуск: sudo bash setup-ssd-on-client1.sh /dev/sdb    — диск целиком (пересоздаст раздел)
#         sudo bash setup-ssd-on-client1.sh /dev/sdb1   — только раздел (NTFS→ext4, данные удалятся)

set -e

DISK="${1:-/dev/sdb}"
CENTOS_IP="${2:-10.10.4.120}"

echo "=== Настройка SSD на client1 ==="
echo "Устройство: $DISK"
echo "NFS клиент (CentOS): $CENTOS_IP"
echo ""

if [[ ! -b "$DISK" ]]; then
    echo "Устройство $DISK не найдено. Проверьте: lsblk"
    exit 1
fi

# Режим: раздел (sdb1) или весь диск (sdb)
if [[ "$DISK" =~ [0-9]$ ]]; then
    PART="$DISK"
    echo "Режим: форматирование существующего раздела $PART"
    echo "ВНИМАНИЕ: Все данные на разделе будут удалены (NTFS «Новый том» и т.д.)"
else
    PART="${DISK}1"
    echo "Режим: пересоздание раздела на диске $DISK"
fi
read -p "Продолжить? [y/N] " -n 1 -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && exit 1

if [[ "$DISK" =~ [0-9]$ ]]; then
    echo "1. Форматирование $PART в ext4"
    sudo mkfs.ext4 -F -L campus-data "$PART"
else
    echo "1. Создание раздела"
    sudo parted "$DISK" mklabel gpt
    sudo parted "$DISK" mkpart primary ext4 0% 100%
    echo "2. Форматирование $PART"
    sudo mkfs.ext4 -L campus-data "$PART"
fi

echo "3. Монтирование"
sudo mkdir -p /mnt/campus-data
if ! grep -q campus-data /etc/fstab; then
    echo "LABEL=campus-data /mnt/campus-data ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
fi
sudo mount -a

echo "4. Каталоги для Loki и Prometheus"
sudo mkdir -p /mnt/campus-data/loki /mnt/campus-data/prometheus
sudo chown -R 10001:10001 /mnt/campus-data/loki
sudo chown -R 65534:65534 /mnt/campus-data/prometheus

echo "5. Установка NFS server"
sudo apt-get update -qq
sudo apt-get install -y nfs-kernel-server

echo "6. Экспорт NFS для CentOS"
sudo mkdir -p /etc/exports.d
echo "/mnt/campus-data $CENTOS_IP(rw,sync,no_subtree_check,no_root_squash)" | sudo tee /etc/exports.d/campus-data.exports
sudo exportfs -ra
sudo systemctl enable nfs-kernel-server
sudo systemctl restart nfs-kernel-server

echo ""
echo "=== Готово ==="
df -h /mnt/campus-data
echo ""
echo "Проверка NFS: showmount -e localhost"
