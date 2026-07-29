#!/bin/bash
# Копирование SSH-ключей на client1 и client2 для работы Telegram-ботов
# Боты в Docker используют ~/.ssh с хоста — ключ должен быть в authorized_keys на клиентах
# Запуск: bash scripts/setup-ssh-keys-for-bots.sh

set -e
SSH_DIR="${SSH_KEY_DIR:-$HOME/.ssh}"
KEY=""

# Выбор ключа (id_ed25519 или id_rsa — без пароля для Docker)
for k in "$SSH_DIR/id_ed25519" "$SSH_DIR/id_rsa" "$SSH_DIR/campus_bot"; do
    if [[ -f "$k" ]]; then
        KEY="$k"
        break
    fi
done

if [[ -z "$KEY" ]]; then
    echo "Создаю ключ: ssh-keygen -t ed25519 -N '' -f $SSH_DIR/id_ed25519"
    ssh-keygen -t ed25519 -N "" -f "$SSH_DIR/id_ed25519" -q
    KEY="$SSH_DIR/id_ed25519"
fi

PUB="${KEY}.pub"
[[ -f "$PUB" ]] || { echo "Публичный ключ не найден: $PUB"; exit 1; }

echo "Используется ключ: $KEY"
echo "Публичный ключ:"
cat "$PUB"
echo ""

copy_key() {
    local user="$1"
    local host="$2"
    local name="$3"
    echo "=== $name ($user@$host) ==="
    ssh-copy-id -i "$PUB" "${user}@${host}" 2>/dev/null && echo "  OK" || {
        echo "  Не удалось (ssh-copy-id). Добавьте вручную:"
        echo "  ssh $user@$host 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys' < $PUB"
    }
}

copy_key "client1" "10.20.0.41" "client1"
copy_key "client2" "10.70.0.41" "client2"

echo ""
echo "Проверка:"
ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 client1@10.20.0.41 "echo OK client1" 2>/dev/null && echo "  client1: OK" || echo "  client1: требуется пароль или ключ не добавлен"
ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 client2@10.70.0.41 "echo OK client2" 2>/dev/null && echo "  client2: OK" || echo "  client2: требуется пароль или ключ не добавлен"
