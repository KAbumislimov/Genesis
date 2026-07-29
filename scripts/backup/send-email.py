#!/usr/bin/env python3
"""
Отправка email уведомления о бэкапе через SMTP (Gmail или другой сервер).

Настройка Gmail:
  1. Google Account → Безопасность → Двухэтапная аутентификация → Включить
  2. Google Account → Безопасность → Пароли приложений → Создать
  3. Используй сгенерированный пароль в BACKUP_SMTP_PASS

Параметры в campus-secrets/backup.env:
  BACKUP_SMTP_HOST=smtp.gmail.com
  BACKUP_SMTP_PORT=587
  BACKUP_SMTP_USER=your_gmail@gmail.com
  BACKUP_SMTP_PASS=xxxx xxxx xxxx xxxx   (App Password)
"""
import argparse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

p = argparse.ArgumentParser()
p.add_argument('--smtp-host',  default='smtp.gmail.com')
p.add_argument('--smtp-port',  type=int, default=587)
p.add_argument('--smtp-user',  required=True)
p.add_argument('--smtp-pass',  required=True)
p.add_argument('--from',       dest='from_addr', required=True)
p.add_argument('--to',         required=True)
p.add_argument('--subject',    required=True)
p.add_argument('--body',       required=True)
args = p.parse_args()

recipients = [r.strip() for r in args.to.split(',')]

msg = MIMEMultipart('alternative')
msg['Subject'] = args.subject
msg['From']    = args.from_addr
msg['To']      = ', '.join(recipients)
msg.attach(MIMEText(args.body, 'plain', 'utf-8'))

with smtplib.SMTP(args.smtp_host, args.smtp_port, timeout=30) as s:
    s.ehlo()
    s.starttls()
    s.login(args.smtp_user, args.smtp_pass)
    s.sendmail(args.from_addr, recipients, msg.as_string())

print(f"Email отправлен: {', '.join(recipients)}")
