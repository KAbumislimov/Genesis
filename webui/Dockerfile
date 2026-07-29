FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends socat openssl ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

# Generate self-signed TLS cert (valid 10 years) — enables mic/getUserMedia via HTTPS
RUN openssl req -x509 -newkey rsa:2048 -keyout /app/ssl.key -out /app/ssl.crt -days 3650 -nodes -subj "/CN=campus-webui/O=MEDIA/C=AZ"

ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/data/hf_cache
ENV XDG_CACHE_HOME=/data/cache

EXPOSE 8080 8443

CMD ["python", "app.py"]
