#!/bin/bash
# Открыть порт 3100 (Loki) для приёма логов с client1 и client2
# Запускать НА 10.10.4.120, вручную (нужен sudo):
#   ssh kamran@10.10.4.120
#   sudo bash /home/kamran/campus-infra/scripts/open-loki-port.sh

firewall-cmd --add-port=3100/tcp --permanent 2>/dev/null && firewall-cmd --reload && echo "Порт 3100 открыт" || echo "Ошибка (запустите с sudo)"
