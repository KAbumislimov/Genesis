FROM alpine:3.19
RUN apk add --no-cache docker-cli openssh-client bash curl
WORKDIR /app
COPY check-and-restore.sh .
RUN chmod +x check-and-restore.sh
CMD ["/app/check-and-restore.sh"]
