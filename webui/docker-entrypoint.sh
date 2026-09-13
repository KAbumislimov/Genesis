#!/usr/bin/env bash
set -e

# TLS cert lives in the persistent /data volume, not the image — generating
# it at build time (as before) meant every `docker compose build` minted a
# brand-new self-signed cert. Browsers trust a self-signed cert per-origin
# for the tab's lifetime, but that trust doesn't survive the identity
# changing under it: after a rebuild, the page itself still loaded fine
# (top-level navigation can re-prompt), but background fetch() calls from
# an already-open tab got silently rejected with no visible error — which
# looked exactly like "нет связи с сервером" on every single poll.
CERT_DIR=/data
if [ ! -f "$CERT_DIR/ssl.key" ] || [ ! -f "$CERT_DIR/ssl.crt" ]; then
    echo "Generating persistent TLS cert in $CERT_DIR ..."
    openssl req -x509 -newkey rsa:2048 -keyout "$CERT_DIR/ssl.key" -out "$CERT_DIR/ssl.crt" \
        -days 3650 -nodes -subj "/CN=campus-webui/O=MEDIA/C=AZ"
fi

exec gunicorn --certfile="$CERT_DIR/ssl.crt" --keyfile="$CERT_DIR/ssl.key" \
     --bind=0.0.0.0:8080 --workers=1 --worker-class=gthread \
     --threads=32 --timeout=300 --log-level=info app:app
