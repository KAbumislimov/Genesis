#!/bin/bash
# Настройка SSH-ключей для campus-recovery (доступ к nctk и vm1 без пароля)
# Запуск на сервере (10.10.4.120): bash scripts/setup-recovery-ssh-keys.sh

KEY="${SSH_KEY:-$HOME/.ssh/campus_bot}"
[[ ! -f "$KEY" ]] && { echo "Создайте ключ: ssh-keygen -t ed25519 -f $KEY -N ''"; exit 1; }

echo "=== Копирование ключа на nctk и vm1 ==="
echo "Пароль nctk: см. campus-secrets / .env (NCTK_PASS)"
ssh-copy-id -i "$KEY" nctk@10.20.0.41

echo ""
echo "Пароль vm1: см. campus-secrets / .env (VM1_PASS)"
ssh-copy-id -i "$KEY" vm1@10.70.0.41

echo ""
echo "Проверка:"
ssh -i "$KEY" -o BatchMode=yes nctk@10.20.0.41 "echo OK nctk" && echo "nctk: OK" || echo "nctk: FAIL"
ssh -i "$KEY" -o BatchMode=yes vm1@10.70.0.41 "echo OK vm1" && echo "vm1: OK" || echo "vm1: FAIL"
