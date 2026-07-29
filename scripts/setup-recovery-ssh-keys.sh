#!/bin/bash
# Настройка SSH-ключей для campus-recovery (доступ к client1 и client2 без пароля)
# Запуск на сервере (10.10.4.120): bash scripts/setup-recovery-ssh-keys.sh

KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
[[ ! -f "$KEY" ]] && { echo "Создайте ключ: ssh-keygen -t ed25519 -f $KEY -N ''"; exit 1; }

echo "=== Копирование ключа на client1 и client2 ==="
echo "Пароль client1: см. campus-secrets / .env (CLIENT1_PASS)"
ssh-copy-id -i "$KEY" client1@10.20.0.41

echo ""
echo "Пароль client2: см. campus-secrets / .env (CLIENT2_PASS)"
ssh-copy-id -i "$KEY" client2@10.70.0.41

echo ""
echo "Проверка:"
ssh -i "$KEY" -o BatchMode=yes client1@10.20.0.41 "echo OK client1" && echo "client1: OK" || echo "client1: FAIL"
ssh -i "$KEY" -o BatchMode=yes client2@10.70.0.41 "echo OK client2" && echo "client2: OK" || echo "client2: FAIL"
