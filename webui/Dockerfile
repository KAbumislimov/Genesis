FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends socat openssl ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data && chmod +x docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/data/hf_cache
ENV XDG_CACHE_HOME=/data/cache

EXPOSE 8080 8443

# TLS cert is generated once into the persistent /data volume by the
# entrypoint (not at build time) — see docker-entrypoint.sh for why.
CMD ["./docker-entrypoint.sh"]
