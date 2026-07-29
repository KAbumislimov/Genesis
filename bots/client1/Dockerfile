# Campus Telegram bot — best practices: фикс. версия, requirements.txt, .dockerignore
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.description="Campus Telegram bot (narimanov/genclik)"

# Системные зависимости — один RUN, очистка в том же слое
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python-зависимости — отдельный слой для кэша (меняется реже кода)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY bot_main.py .

# Конфиг через env_file (config.env) — не в образе
CMD ["python3", "-u", "bot_main.py"]
