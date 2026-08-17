#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram-бот для клиента client1: кнопки, список треков, логи в группу «наримановскую», /info."""
import os
import sys
import json
import re
import tempfile
import urllib.request
import urllib.parse
import subprocess
import time
from datetime import datetime

DIR_BOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(DIR_BOT, 'config.env')
LOG_FILE = os.path.join(DIR_BOT, 'action.log')
HISTORY_FILE = os.path.join(DIR_BOT, 'play_history.txt')
MAX_HISTORY = 30
PAGE_SIZE = 15
MPV_SOCK = '/run/campus-player/mpv.sock'

def load_config():
    env = {}
    if os.path.isfile(CONFIG):
        with open(CONFIG) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    env.setdefault('BOT_TOKEN', os.environ.get('BOT_TOKEN', ''))
    env.setdefault('CHAT_ID', os.environ.get('CHAT_ID', ''))
    env.setdefault('LOG_GROUP_ID', os.environ.get('LOG_GROUP_ID', ''))
    env.setdefault('DIR_KAMRAN', '/home/client1/Media/Kamran Music')
    env.setdefault('SERVER_HOST', '10.10.4.120')
    env.setdefault('SBTK_HOST', '10.70.0.41')
    env.setdefault('SSH_KEY', os.environ.get('SSH_KEY', ''))
    env.setdefault('SSH_KEY_FOR_TIME', os.environ.get('SSH_KEY_FOR_TIME', ''))
    return env

def get_tracks_total():
    d = load_config().get('DIR_KAMRAN', '/home/client1/Media/Kamran Music')
    if not os.path.isdir(d):
        return 500
    n = 0
    for ext in ('mp3', 'mp4', 'mpeg'):
        n += len([f for f in os.listdir(d) if f.endswith('.' + ext) and re.match(r'^\d+\.', f)])
    return max(n, 1)

TRACKS_TOTAL = get_tracks_total()

def api(token, method, **kwargs):
    url = f'https://api.telegram.org/bot{token}/{method}'
    for k, v in list(kwargs.items()):
        if isinstance(v, (dict, list)):
            kwargs[k] = json.dumps(v)
    data = urllib.parse.urlencode(kwargs).encode()
    req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def send(token, chat_id, text, reply_markup=None, parse_mode=None):
    kwargs = dict(chat_id=chat_id, text=text, disable_web_page_preview=True)
    if reply_markup is not None:
        kwargs['reply_markup'] = reply_markup
    if parse_mode:
        kwargs['parse_mode'] = parse_mode
    api(token, 'sendMessage', **kwargs)

def is_chat_admin(token, chat_id, user_id):
    """В группе бот реагирует только на админов. В личке — на всех."""
    try:
        r = api(token, 'getChatMember', chat_id=chat_id, user_id=user_id)
        if not r.get('ok'):
            return False
        status = (r.get('result') or {}).get('status') or ''
        return status in ('creator', 'administrator')
    except Exception:
        return False

def run(cmd, capture=True):
    env = os.environ.copy()
    env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
    if capture:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env, timeout=30)
        return r.returncode, (r.stdout or '').strip() + (r.stderr or '').strip()
    else:
        subprocess.Popen(cmd, shell=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0, ''

def mpv_cmd(cmd_json):
    if not os.path.exists(MPV_SOCK):
        return None
    code, out = run(f'echo {json.dumps(cmd_json)!r} | socat - {MPV_SOCK} 2>/dev/null')
    if code != 0:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None

def get_volume():
    r = mpv_cmd({"command": ["get_property", "volume"]})
    if not r or "data" not in r:
        return None
    try:
        return float(r["data"])
    except (TypeError, ValueError):
        return None

def set_volume(val):
    r = mpv_cmd({"command": ["set_property", "volume", max(0, min(100, val))]})
    return r is not None

def vol_up():
    v = get_volume()
    if v is None:
        return False, "Плеер недоступен"
    new_v = min(100, v + 10)
    set_volume(new_v)
    return True, f"Громкость {int(new_v)}%"

def vol_down():
    v = get_volume()
    if v is None:
        return False, "Плеер недоступен"
    new_v = max(0, v - 10)
    set_volume(new_v)
    return True, f"Громкость {int(new_v)}%"

_log_dedup = {}  # (msg_key, log_group) -> last_time

def log_action(token, log_group_id, msg, also_file=True, chat_id=None):
    """Пишем в файл. В Telegram — только если это НЕ та же группа.
    Формат: [ЧЧ:ММ:СС] [client1] действие | @user"""
    ts = datetime.now().strftime('%H:%M:%S %d.%m')
    line = f"[{ts}] [client1] {msg}"
    if also_file:
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass
    if chat_id is not None and str(chat_id) == str(log_group_id):
        return
    if not log_group_id or not token:
        return
    key = (msg[:80], str(log_group_id))
    now = time.time()
    if key in _log_dedup and (now - _log_dedup[key]) < 15:
        return
    _log_dedup[key] = now
    if len(_log_dedup) > 100:
        _log_dedup.clear()
    try:
        send(token, log_group_id, f"📌 {line}")
    except Exception:
        pass

def get_current_track_num():
    r = mpv_cmd({"command": ["get_property", "path"]})
    if not r or "data" not in r:
        return None
    path = r.get("data", "") or ""
    base = os.path.basename(path)
    m = re.match(r'^(\d+)\.', base)
    return int(m.group(1)) if m else None

def add_to_history(num, username):
    try:
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{num}\t{username}\t{datetime.now().isoformat()}\n")
        lines = open(HISTORY_FILE, encoding='utf-8').readlines()
        if len(lines) > MAX_HISTORY:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                f.writelines(lines[-MAX_HISTORY:])
    except Exception:
        pass

def get_history():
    if not os.path.isfile(HISTORY_FILE):
        return []
    try:
        lines = open(HISTORY_FILE, encoding='utf-8').readlines()
        nums, seen = [], set()
        for line in reversed(lines[-MAX_HISTORY:]):
            parts = line.strip().split('\t')
            if parts:
                try:
                    n = int(parts[0])
                    if n not in seen and 1 <= n <= TRACKS_TOTAL:
                        seen.add(n)
                        nums.append(n)
                except ValueError:
                    pass
        return nums[:20]
    except Exception:
        return []

def get_track_path(num):
    d = load_config().get('DIR_KAMRAN', '/home/client1/Media/Kamran Music')
    for ext in ('mp3', 'mp4', 'mpeg'):
        p = os.path.join(d, f'{num}.{ext}')
        if os.path.isfile(p):
            return p
    return None

def play_track(token, log_group_id, chat_id, num, username, log=True):
    path = get_track_path(num)
    if not path:
        return False, f'Трек {num} не найден.'
    run(f'campus-playerctl vol 70 && campus-playerctl play "{path}"', capture=False)
    ext = os.path.splitext(path)[1]
    add_to_history(num, username)
    if log:
        log_action(token, log_group_id, f"▶ Воспроизведение: трек {num}{ext} | {username}", also_file=True, chat_id=chat_id)
    return True, f'▶ Играет: {num}{ext}'

def get_time_remote(host, user, key=None):
    if not host or not user:
        return '—'
    opts = '-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=3'
    key_opt = f'-i {key}' if key and os.path.isfile(key) else ''
    cmd = f'ssh {key_opt} {opts} {user}@{host} "date +\'%H:%M:%S %d.%m.%Y\'" 2>/dev/null'
    code, out = run(cmd)
    return out.strip() if code == 0 and out else '—'

def get_time_all_machines(update_date_ts=None):
    cfg = load_config()
    srv = cfg.get('SERVER_HOST', '10.10.4.120')
    sbtk_host = cfg.get('SBTK_HOST', '10.70.0.41')
    key = cfg.get('SSH_KEY') or cfg.get('SSH_KEY_FOR_TIME')
    lines = []
    lines.append(f"🖥 Server (centos): {get_time_remote(srv, 'kamran', key)}")
    lines.append(f"🖥 client1 (эта машина): {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}")
    lines.append(f"🖥 sbtk: {get_time_remote(sbtk_host, 'sbtk', key)}")
    if update_date_ts:
        try:
            dt = datetime.fromtimestamp(update_date_ts)
            lines.append(f"📱 Телефон (при нажатии): {dt.strftime('%H:%M:%S %d.%m.%Y')}")
        except Exception:
            pass
    else:
        lines.append(f"📱 Телефон: нажмите ещё раз для обновления")
    return "\n".join(lines)

def _run_sysinfo_cmd(cmd):
    try:
        code, out = run(cmd)
        return out if code == 0 else None
    except Exception:
        return None

def _ssh_sysinfo(host, user, key, cmd):
    if not key or not os.path.isfile(key):
        return None
    try:
        r = subprocess.run(
            ['ssh', '-i', key, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
             '-o', 'StrictHostKeyChecking=no', '-o', 'LogLevel=ERROR',
             f'{user}@{host}', cmd],
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or '').strip() if r.returncode == 0 else None
    except Exception:
        return None

def _format_machine_status(name, raw):
    if not raw:
        return f"🖥 <b>{name}</b>\n  ❌ Недоступен"
    lines = [l.strip() for l in raw.split('\n') if l.strip() and not l.strip().startswith('Warning')]
    return f"🖥 <b>{name}</b>\n  " + "\n  ".join(lines[:12])

def get_server_status():
    cfg = load_config()
    key = cfg.get('SSH_KEY') or cfg.get('SSH_KEY_FOR_TIME')
    results = []
    sysinfo_cmd = (
        "echo 'RAM:'; free -h | grep -E '^Mem:' | awk '{print $3\"/\"$2}'; "
        "echo 'Load:'; cat /proc/loadavg 2>/dev/null | awk '{print $1,$2,$3}'; "
        "echo 'CPU:'; nproc 2>/dev/null || grep -c processor /proc/cpuinfo; "
        "echo 'Disk:'; df -h / 2>/dev/null | tail -1 | awk '{print $3\"/\"$2\" (\"$5\")\"}'; "
        "echo 'Temp:'; t=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null); "
        "echo \"${t:-0}\" | awk '{if($1>0) printf \"%.0f°C\", $1/1000; else print \"N/A\"}'"
    )
    local_out = _run_sysinfo_cmd(sysinfo_cmd)
    results.append(_format_machine_status("client1 (локально)", local_out or "Ошибка"))
    srv = cfg.get('SERVER_HOST', '10.10.4.120')
    if srv:
        out = _ssh_sysinfo(srv, 'kamran', key, sysinfo_cmd)
        results.append(_format_machine_status(f"Сервер ({srv})", out))
    sbtk_host = cfg.get('SBTK_HOST', '10.70.0.41')
    if sbtk_host:
        out = _ssh_sysinfo(sbtk_host, 'sbtk', key, sysinfo_cmd)
        results.append(_format_machine_status(f"sbtk ({sbtk_host})", out))
    return "🖥 <b>Статус серверов</b>\n\n" + "\n\n".join(results)

def main_keyboard():
    return {
        "keyboard": [
            ["🔊 Громче", "🔉 Тише", "⏹ Стоп", "▶ Play"],
            ["▶ След. песня", "◀ Пред. песня"],
            ["📋 История", "📂 Список треков", "🕐 Время", "🖥 Сервер"],
        ],
        "resize_keyboard": True,
    }

def inline_list_page(offset=0):
    offset = max(0, min(offset, TRACKS_TOTAL - PAGE_SIZE))
    buttons, row = [], []
    for i in range(offset + 1, min(offset + PAGE_SIZE + 1, TRACKS_TOTAL + 1)):
        row.append({"text": str(i), "callback_data": f"play_{i}"})
        if len(row) >= 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = []
    if offset > 0:
        nav.append({"text": "◀ Назад", "callback_data": f"list_{max(0, offset - PAGE_SIZE)}"})
    if offset + PAGE_SIZE < TRACKS_TOTAL:
        nav.append({"text": "Вперёд ▶", "callback_data": f"list_{offset + PAGE_SIZE}"})
    if nav:
        buttons.append(nav)
    return {"inline_keyboard": buttons}

def inline_history_keyboard():
    nums = get_history()
    if not nums:
        return {"inline_keyboard": [[{"text": "История пуста", "callback_data": "noop"}]]}
    buttons, row = [], []
    for n in nums[:15]:
        row.append({"text": f"▶ {n}", "callback_data": f"play_{n}"})
        if len(row) >= 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return {"inline_keyboard": buttons}

def download_file(token, file_id):
    data = api(token, 'getFile', file_id=file_id)
    if not data.get('ok'):
        return None
    file_path = data.get('result', {}).get('file_path')
    if not file_path:
        return None
    url = f'https://api.telegram.org/file/bot{token}/{file_path}'
    suf = os.path.splitext(file_path)[1] or '.ogg'
    fd, path = tempfile.mkstemp(suffix=suf, prefix='tg_')
    os.close(fd)
    with urllib.request.urlopen(url, timeout=60) as r:
        with open(path, 'wb') as f:
            f.write(r.read())
    return path

def info_text():
    return """ℹ️ <b>Инфо — команды и кнопки</b>

<b>Кнопки:</b>
• 🔊 Громче / 🔉 Тише — громкость ±10%
• ⏹ Стоп — остановить воспроизведение
• ▶ След. песня / ◀ Пред. песня — переключить трек
• 📋 История — последние проигранные треки
• 📂 Список треков — выбор из папки (Kamran Music)

<b>Команды:</b>
/start, /menu — меню
/list — список треков
/history — история
/status — что играет
/stop — остановить
/volup, /voldown — громкость
play N или просто число — играть трек N

<b>Текст:</b> меню, инфо, громче, тише, стоп.

Aue, Ala bura Təhsil olaçııııııgıdır"""

def menu_text():
    return """📋 Управление звуком — используйте кнопки ниже.

▶ След. / Пред. — переключить трек.
📋 История — последние проигранные.
📂 Список треков — выбор из Kamran Music (1–{}).

Можно писать: play N, число, /menu, /stop, /info.""".format(TRACKS_TOTAL)

def handle_callback(token, log_group_id, chat_id, callback_query, user):
    cid = callback_query.get('id')
    data = (callback_query.get('data') or '').strip()
    username = user.get('username') or user.get('first_name') or '?'
    try:
        api(token, 'answerCallbackQuery', callback_query_id=cid)
    except Exception:
        pass
    if data == 'noop':
        return
    if data.startswith('play_'):
        try:
            num = int(data[5:])
            if 1 <= num <= TRACKS_TOTAL:
                ok, msg = play_track(token, log_group_id, chat_id, num, username, log=False)
                send(token, chat_id, msg, reply_markup=main_keyboard())
        except ValueError:
            pass
        return
    if data.startswith('list_'):
        try:
            offset = int(data[5:])
        except ValueError:
            offset = 0
        a, b = offset + 1, min(offset + PAGE_SIZE, TRACKS_TOTAL)
        send(token, chat_id, f"📂 Треки {a}–{b} (всего {TRACKS_TOTAL}). Нажмите номер:", reply_markup=inline_list_page(offset))
        return

def handle_update(token, chat_id, log_group_id, update):
    cid = chat_id or (update.get('message') or update.get('edited_message') or {}).get('chat', {}).get('id')
    if update.get('callback_query'):
        cq = update['callback_query']
        chat_id = cq.get('message', {}).get('chat', {}).get('id')
        user = cq.get('from', {})
        chat = cq.get('message', {}).get('chat', {})
        if str(chat.get('type', '')).startswith(('group', 'supergroup')):
            if not is_chat_admin(token, chat_id, user.get('id')):
                return
        handle_callback(token, log_group_id, chat_id, cq, user)
        return
    msg = update.get('message') or update.get('edited_message')
    if not msg:
        return
    chat = msg.get('chat', {})
    chat_type = str(chat.get('type', ''))
    user = msg.get('from', {})
    user_id = user.get('id')
    if chat_type in ('group', 'supergroup'):
        if not is_chat_admin(token, chat_id, user_id):
            return
    username = user.get('username') or user.get('first_name') or '?'
    text = (msg.get('text') or '').strip()
    kb = main_keyboard()

    if text in ('/start', '/menu', 'меню', 'menu'):
        send(token, chat_id, menu_text(), reply_markup=kb)
        return

    if text in ('/info', 'инфо', 'info', 'Info'):
        send(token, chat_id, info_text(), reply_markup=kb, parse_mode='HTML')
        return

    if text in ('🕐 Время', '/time', 'время', 'time'):
        ts = msg.get('date') if msg else None
        time_text = get_time_all_machines(ts)
        send(token, chat_id, f"🕐 Время на машинах:\n\n{time_text}", reply_markup=kb)
        return

    if text in ('🖥 Сервер', '/server', 'сервер', 'server'):
        status_text = get_server_status()
        send(token, chat_id, status_text, reply_markup=kb, parse_mode='HTML')
        return

    if text in ('▶ Play', '/play', 'play', 'Play', 'играть'):
        num = get_current_track_num() or next(iter(get_history()), None) or 1
        num = 1 if num < 1 or num > TRACKS_TOTAL else num
        ok, msg_play = play_track(token, log_group_id, chat_id, num, username, log=False)
        send(token, chat_id, msg_play, reply_markup=kb)
        return

    if text == '📂 Список треков' or text == '/list':
        send(token, chat_id, f"📂 Треки 1–{PAGE_SIZE} (всего {TRACKS_TOTAL}). Нажмите номер:", reply_markup=inline_list_page(0))
        return

    if text == '📋 История' or text == '/history':
        hist = get_history()
        if not hist:
            send(token, chat_id, "История пуста.", reply_markup=kb)
        else:
            send(token, chat_id, "📋 Последние треки (нажмите чтобы включить):", reply_markup=inline_history_keyboard())
        return

    if text == '▶ След. песня':
        cur = get_current_track_num()
        nxt = (cur + 1) if cur is not None else 1
        if nxt > TRACKS_TOTAL:
            nxt = 1
        ok, msg = play_track(token, log_group_id, chat_id, nxt, username, log=False)
        send(token, chat_id, msg, reply_markup=kb)
        return

    if text == '◀ Пред. песня':
        cur = get_current_track_num()
        prev = (cur - 1) if cur is not None else TRACKS_TOTAL
        if prev < 1:
            prev = TRACKS_TOTAL
        ok, msg = play_track(token, log_group_id, chat_id, prev, username, log=False)
        send(token, chat_id, msg, reply_markup=kb)
        return

    if text in ('🔊 Громче', '/volup', 'громче'):
        ok, out = vol_up()
        send(token, chat_id, out, reply_markup=kb)
        return

    if text in ('🔉 Тише', '/voldown', 'тише'):
        ok, out = vol_down()
        send(token, chat_id, out, reply_markup=kb)
        return

    if text in ('⏹ Стоп', '/stop', 'стоп', 'stop'):
        run('campus-playerctl stop')
        send(token, chat_id, 'Остановлено.', reply_markup=kb)
        return

    if text == '/status':
        cur = get_current_track_num()
        send(token, chat_id, f"Сейчас: трек {cur}." if cur else "Ничего не играет.", reply_markup=kb)
        return

    voice = msg.get('voice') or msg.get('audio')
    doc = msg.get('document')
    if voice or doc:
        file_id = (voice or {}).get('file_id') or (doc and doc.get('file_name', '').lower().endswith(('.mp3', '.ogg', '.m4a')) and doc.get('file_id'))
        if file_id:
            try:
                local = download_file(token, file_id)
                if local:
                    run(f'campus-playerctl vol 70 && campus-playerctl play "{local}"', capture=False)
                    send(token, chat_id, '▶ Воспроизведение из чата.', reply_markup=kb)
                    try: os.unlink(local)
                    except Exception: pass
                else:
                    send(token, chat_id, 'Ошибка загрузки.', reply_markup=kb)
            except Exception as e:
                send(token, chat_id, f'Ошибка: {e}', reply_markup=kb)
        else:
            send(token, chat_id, 'Пришлите голос/MP3/OGG/M4A.', reply_markup=kb)
        return

    num = None
    lower = (text or '').lower()
    if lower.startswith('play '):
        try:
            num = int(text.split(maxsplit=1)[1].strip().lstrip('0') or 0)
        except (ValueError, IndexError):
            pass
    elif text.isdigit():
        num = int(text.lstrip('0') or 0)
    if num and 1 <= num <= TRACKS_TOTAL:
        ok, msg = play_track(token, log_group_id, chat_id, num, username, log=False)
        send(token, chat_id, msg, reply_markup=kb)
        return

    if text and text.startswith('/'):
        send(token, chat_id, 'Неизвестная команда. /menu или /info.', reply_markup=kb)

_PROCESSED_UPDATES = set()
_MAX_PROCESSED = 5000

def main():
    env = load_config()
    token = env.get('BOT_TOKEN')
    if not token:
        print('Задайте BOT_TOKEN в config.env', file=sys.stderr)
        sys.exit(1)
    log_group_id = env.get('LOG_GROUP_ID', '').strip()
    if log_group_id:
        try:
            send(token, log_group_id, f"🤖 [client1] Бот запущен {datetime.now().strftime('%H:%M %d.%m')}")
        except Exception:
            pass
    url = f'https://api.telegram.org/bot{token}/getUpdates'
    offset = 0
    global _PROCESSED_UPDATES
    while True:
        try:
            req = urllib.request.Request(f'{url}?offset={offset}&timeout=50')
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            if not data.get('ok'):
                continue
            for upd in data.get('result', []):
                uid = upd.get('update_id')
                if uid in _PROCESSED_UPDATES:
                    continue
                _PROCESSED_UPDATES.add(uid)
                if len(_PROCESSED_UPDATES) > _MAX_PROCESSED:
                    _PROCESSED_UPDATES.clear()
                offset = uid + 1
                chat_id = None
                if upd.get('message'):
                    chat_id = upd['message'].get('chat', {}).get('id')
                elif upd.get('edited_message'):
                    chat_id = upd['edited_message'].get('chat', {}).get('id')
                elif upd.get('callback_query'):
                    chat_id = upd['callback_query'].get('message', {}).get('chat', {}).get('id')
                if chat_id is not None:
                    try:
                        handle_update(token, chat_id, log_group_id, upd)
                    except Exception as e:
                        try:
                            send(token, chat_id, f'Ошибка: {e}', reply_markup=main_keyboard())
                        except Exception:
                            pass
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print('Неверный BOT_TOKEN', file=sys.stderr)
                sys.exit(2)
        except Exception as e:
            import time
            time.sleep(5)

if __name__ == '__main__':
    main()
