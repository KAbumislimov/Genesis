#!/usr/bin/env python3
# Campus Telegram-бот: управление плеером на client1/client2
# Кнопки, SSH, музыка

import os
import sys
import subprocess
import asyncio

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CLIENT_HOST = os.environ.get("CLIENT_HOST", "10.20.0.41")
CLIENT_USER = os.environ.get("CLIENT_USER", "client1")
BOT_LABEL = os.environ.get("BOT_LABEL", CLIENT_USER)

# Жесткое ограничение по chat_id (можно задать один или несколько через запятую)
_allowed_raw = os.environ.get("ALLOWED_CHAT_IDS", "").strip() or os.environ.get("ALLOWED_CHAT_ID", "").strip()
ALLOWED_CHAT_IDS = set()
if _allowed_raw:
    for part in _allowed_raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ALLOWED_CHAT_IDS.add(int(part))
        except ValueError:
            pass

# Мягкое ограничение по названию группы (fallback, если chat_id не задан)
GROUP_KEYWORDS = [k.strip().lower() for k in os.environ.get("GROUP_KEYWORDS", "").split(",") if k.strip()]

# Выбор ключа: id_ed25519 (часто без пароля), id_rsa, campus_bot
SSH_KEY = os.environ.get("SSH_KEY", "")
if not SSH_KEY or not os.path.isfile(SSH_KEY):
    for k in ["/root/.ssh/id_ed25519", "/root/.ssh/id_rsa", "/root/.ssh/campus_bot"]:
        if os.path.isfile(k):
            SSH_KEY = k
            break
if not SSH_KEY:
    SSH_KEY = "/root/.ssh/id_rsa"

if not BOT_TOKEN or BOT_TOKEN == "your_bot_token":
    print("BOT_TOKEN не задан в config.env", file=sys.stderr)
    sys.exit(1)

try:
    from telegram import Update, ReplyKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError:
    print("Установите: pip install python-telegram-bot", file=sys.stderr)
    sys.exit(1)


def run_ssh(cmd: str) -> tuple[bool, str]:
    ssh_cmd = [
        "ssh",
        "-i",
        SSH_KEY,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=5",
        f"{CLIENT_USER}@{CLIENT_HOST}",
        cmd,
    ]
    try:
        r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return False, str(e)


def main_keyboard():
    return ReplyKeyboardMarkup(
        [["▶️ Play", "⏸ Pause", "⏹ Stop"], ["🔊+ Громче", "🔊- Тише"], ["📋 Статус"]],
        resize_keyboard=True,
    )


def is_chat_allowed(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return False

    if ALLOWED_CHAT_IDS:
        return chat.id in ALLOWED_CHAT_IDS

    if GROUP_KEYWORDS and chat.type in {"group", "supergroup", "channel"}:
        title = (chat.title or "").lower()
        return any(k in title for k in GROUP_KEYWORDS)

    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_chat_allowed(update):
        chat = update.effective_chat
        print(f"[SKIP start] bot={BOT_LABEL} chat_id={getattr(chat, 'id', None)} title={getattr(chat, 'title', None)}")
        return

    await update.message.reply_text(
        f"Campus bot ({CLIENT_USER}@{CLIENT_HOST})\nИспользуйте кнопки для управления.",
        reply_markup=main_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not is_chat_allowed(update):
        print(f"[SKIP msg] bot={BOT_LABEL} chat_id={getattr(chat, 'id', None)} title={getattr(chat, 'title', None)}")
        return

    text = (update.message.text or "").strip()
    loop = asyncio.get_event_loop()

    if text == "▶️ Play":
        ok, out = await loop.run_in_executor(None, run_ssh, "pkill -CONT mpv 2>/dev/null || systemctl --user start campus-mpv 2>/dev/null || true")
        await update.message.reply_text("▶️ Play" if ok else f"Ошибка: {out}")
    elif text == "⏸ Pause":
        ok, out = await loop.run_in_executor(None, run_ssh, "pkill -STOP mpv 2>/dev/null || pkill -USR1 mpv 2>/dev/null || true")
        await update.message.reply_text("⏸ Pause" if ok else f"Ошибка: {out}")
    elif text == "⏹ Stop":
        ok, out = await loop.run_in_executor(None, run_ssh, "pkill mpv 2>/dev/null || systemctl --user stop campus-mpv 2>/dev/null || true")
        await update.message.reply_text("⏹ Stop" if ok else f"Ошибка: {out}")
    elif text == "🔊+ Громче":
        ok, out = await loop.run_in_executor(None, run_ssh, "pactl set-sink-volume @DEFAULT_SINK@ +5% 2>/dev/null || amixer set Master 5%+ 2>/dev/null || true")
        await update.message.reply_text("🔊 Громче" if ok else f"Ошибка: {out}")
    elif text == "🔊- Тише":
        ok, out = await loop.run_in_executor(None, run_ssh, "pactl set-sink-volume @DEFAULT_SINK@ -5% 2>/dev/null || amixer set Master 5%- 2>/dev/null || true")
        await update.message.reply_text("🔊 Тише" if ok else f"Ошибка: {out}")
    elif text == "📋 Статус":
        ok, out = await loop.run_in_executor(None, run_ssh, "pgrep -a mpv 2>/dev/null || echo 'Плеер не запущен'")
        await update.message.reply_text(out[:400] if out else "Нет данных")
    else:
        await update.message.reply_text("Используйте кнопки.", reply_markup=main_keyboard())


async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
    await app.initialize()
    await app.start()
    print(f"Бот запущен: {BOT_LABEL} ({CLIENT_USER}@{CLIENT_HOST}).")
    await app.updater.start_polling()
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
