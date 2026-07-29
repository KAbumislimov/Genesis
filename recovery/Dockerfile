FROM alpine:3.19
RUN apk add --no-cache openssh-client bash docker-cli curl && \
    curl -sSL "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-linux-x86_64" -o /usr/local/bin/docker-compose && \
    chmod +x /usr/local/bin/docker-compose
WORKDIR /app
COPY config/ config/
COPY backup.sh restore.sh watchdog-recovery.sh ./
RUN chmod +x backup.sh restore.sh watchdog-recovery.sh
# Бэкапы хранятся в volume
ENV BACKUPS_ROOT=/backups
VOLUME /backups
CMD ["/app/watchdog-recovery.sh"]
