# Размещение данных (диск 200 GB)

## Текущая схема

| Раздел | Размер | Использование |
|--------|--------|---------------|
| **/** (cs-root) | 70 GB | Система, /var, /tmp — **мало места** |
| **/home** (cs-home) | 120 GB | ~95 GB свободно |
| swap | 8 GB | — |

## Где хранятся данные campus-infra

| Данные | Путь | Раздел |
|--------|------|--------|
| Docker (образы, volumes) | /home/docker-data | /home |
| Loki (логи) | docker volume loki_data | /home |
| Grafana (дашборды) | docker volume grafana_data | /home |
| Prometheus (метрики) | docker volume prometheus_data | /home |
| Бэкапы recovery | docker volume recovery_backups | /home |
| Временные файлы Docker | /home/docker-tmp | /home |

## Скрипт перенаправления

```bash
sudo bash /home/kamran/campus-infra/scripts/move-temp-to-home.sh
```

Настраивает TMPDIR для Docker/containerd на /home, чтобы сборка и `docker exec` не заполняли /.
