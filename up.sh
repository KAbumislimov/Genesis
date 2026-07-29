#!/bin/bash
# Запуск всего: бэкапы, Telegram-боты, мониторинг, автовосстановление
# Использование: ./up.sh  или  bash scripts/start-all.sh up

cd "$(dirname "$0")"
bash scripts/start-all.sh up
