# Best Practices для Docker-образов

## 1. Базовые принципы

| Принцип | Зачем |
|---------|-------|
| **Минимальный базовый образ** | Меньше уязвимостей, быстрее pull/start |
| **Multi-stage build** | Сборка и рантайм разделены — финальный образ без компиляторов |
| **Не root** | Запуск от непривилегированного пользователя |
| **Фиксированные версии** | `python:3.11-slim`, не `python:latest` — воспроизводимость |
| **Один процесс на контейнер** | Проще масштабировать и отлаживать |

---

## 2. Структура Dockerfile

```dockerfile
# 1. Базовый образ — фиксированная версия
FROM python:3.11-slim-bookworm AS builder

# 2. Метаданные (опционально)
LABEL org.opencontainers.image.source="https://github.com/..."
LABEL org.opencontainers.image.description="Campus bot"

# 3. Системные зависимости — одной командой, очистка в том же RUN
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# 4. Python-зависимости — отдельный слой для кэша
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Код приложения — в конце (чаще меняется)
WORKDIR /app
COPY . .

# 6. Непривилегированный пользователь
RUN useradd -r -u 1000 appuser && chown -R appuser /app
USER appuser

# 7. Точка входа
CMD ["python3", "-u", "bot_main.py"]
```

---

## 3. Multi-stage build (для компилируемых языков)

```dockerfile
# Stage 1: сборка
FROM golang:1.21-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /app/binary .

# Stage 2: рантайм — только бинарник
FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=builder /app/binary /app/
USER nobody
CMD ["/app/binary"]
```

---

## 4. .dockerignore — обязательно

Исключает лишнее из контекста сборки (ускоряет build, уменьшает образ):

```
.git
.gitignore
*.md
__pycache__
*.pyc
.env
*.log
node_modules
.venv
venv
```

---

## 5. requirements.txt для Python

Не `pip install` в Dockerfile — вынести в `requirements.txt` с версиями:

```
python-telegram-bot==20.7
requests==2.31.0
```

В Dockerfile:
```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

---

## 6. Порядок слоёв (кэш)

Слои, которые меняются реже — выше:

1. `FROM`, `LABEL`
2. Системные пакеты
3. `requirements.txt` + `pip install`
4. `COPY` кода приложения
5. `USER`, `CMD`

---

## 7. Безопасность

- **USER** — не root, если возможно
- **--no-install-recommends** — меньше пакетов
- **rm -rf /var/lib/apt/lists/** — очистка кэша apt
- **pip --no-cache-dir** — без кэша pip
- Сканирование: `docker scout quickview`, `trivy image`

---

## 8. Метаданные и healthcheck

```dockerfile
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.revision="${GIT_SHA}"

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD curl -f http://localhost:8080/health || exit 1
```

---

## 9. Размер образа

| Базовый образ | Размер (примерно) |
|---------------|-------------------|
| alpine:3.19   | ~7 MB             |
| python:3.11-alpine | ~50 MB       |
| python:3.11-slim   | ~120 MB      |
| python:3.11        | ~900 MB      |

Для Python: `slim` — баланс, `alpine` — если критичен размер (могут быть проблемы с бинарными пакетами).

---

## 10. Сборка и теги

```bash
# Сборка с тегом версии
docker build -t campus-bot:1.0.0 -t campus-bot:latest .

# Для registry
docker build -t registry.example.com/campus/bot:1.0.0 .
docker push registry.example.com/campus/bot:1.0.0
```

---

## См. также

- [Dockerfile best practices (официально)](https://docs.docker.com/develop/dev-best-practices/)
- [OWASP Docker Security](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
