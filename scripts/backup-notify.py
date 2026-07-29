#!/usr/bin/env python3
"""Отправляет Telegram-уведомление о результате бэкапа.
Запускается из campus-backup.sh в конце: python3 backup-notify.py /var/log/campus-backup.log
"""
import os
import re
import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime

BACKUP_LOG  = sys.argv[1] if len(sys.argv) > 1 else "/var/log/campus-backup.log"
SECRETS_ENV = "/home/kamran/projects/campus-secrets/backup.env"

def load_env(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env

def parse_last_run(log_path):
    """Парсит последний запуск бэкапа из лога."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return None

    # Найти последний BACKUP START
    start_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if "BACKUP START" in lines[i]:
            start_idx = i
            break
    if start_idx is None:
        return None

    run = lines[start_idx:]

    def extract_time(line):
        m = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
        return m.group(1) if m else ""

    start_time  = extract_time(run[0])
    end_time    = ""
    done        = False
    successes   = []
    errors      = []
    sizes       = []

    for line in run:
        stripped = line.strip()
        if "BACKUP DONE" in stripped:
            done = True
            end_time = extract_time(line)
        if "✅" in stripped:
            clean = re.sub(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*", "", stripped)
            successes.append(clean)
        if "ОШИБКА" in stripped or ("❌" in stripped and "ОШИБКА" in stripped):
            clean = re.sub(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*", "", stripped)
            errors.append(clean)
        # Строки du -sh: [timestamp]  1.2G /mnt/campus-backup/2026-07-13_client1
        m = re.search(r"\]\s+(\S+)\s+/mnt/campus-backup/(\S+)/?$", stripped)
        if m:
            sizes.append((m.group(2), m.group(1)))

    return {
        "start_time": start_time,
        "end_time": end_time,
        "done": done,
        "successes": successes,
        "errors": errors,
        "sizes": sizes,
    }

def build_message(run):
    if run is None:
        return "❓ Нет данных о бэкапе."

    date_str = run["start_time"][:10] if run["start_time"] else "?"
    icon = "✅" if run["done"] and not run["errors"] else ("⚠️" if run["done"] else "🔄")
    if not run["done"]:
        icon = "❌"

    lines = [
        f"{icon} <b>Campus Backup — {date_str}</b>",
        f"🕐 {run['start_time']}  →  {run['end_time'] or '...'}" ,
        "",
    ]

    if run["done"]:
        lines.append(f"✅ Успешно: {len(run['successes'])}    ❌ Ошибок: {len(run['errors'])}")
    else:
        lines.append("❌ Бэкап не завершился!")

    if run["sizes"]:
        lines.append("")
        lines.append("📁 <b>Proxmox (10.20.1.106):</b>")
        for name, size in run["sizes"]:
            lines.append(f"  • {name}: {size}")

    if run["errors"]:
        lines.append("")
        lines.append("❌ <b>Ошибки:</b>")
        for e in run["errors"][:5]:
            short = e[:100] + ("…" if len(e) > 100 else "")
            lines.append(f"  {short}")

    lines.append("")
    lines.append("📅 Следующий: воскресенье 02:00")
    return "\n".join(lines)

def send_telegram(token, chat_id, text):
    payload = json.dumps({
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"Telegram error: {e}", file=sys.stderr)
        return False

def main():
    env = load_env(SECRETS_ENV)
    token  = env.get("BACKUP_BOT_TOKEN", "")
    chat1  = env.get("BACKUP_TG_CHAT1", "")
    chat2  = env.get("BACKUP_TG_CHAT2", "")

    if not token:
        print("No BACKUP_BOT_TOKEN found", file=sys.stderr)
        sys.exit(1)

    run  = parse_last_run(BACKUP_LOG)
    text = build_message(run)

    ok = 0
    for chat in filter(None, [chat1, chat2]):
        if send_telegram(token, chat, text):
            ok += 1
            print(f"Sent to {chat}")

    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
