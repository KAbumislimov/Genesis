#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram-бот Нариманов: тот же интерфейс что vm1/nctk, воспроизведение по SSH на клиент."""
import os
import sys
import json
import html
import re
import shlex
import tempfile
import urllib.request
import urllib.parse
import subprocess
import threading
import time
from datetime import datetime

DIR_BOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(DIR_BOT, 'config.env')
LOG_FILE = os.path.join(DIR_BOT, 'action.log')
HISTORY_FILE = os.path.join(DIR_BOT, 'play_history.txt')
LAST_TRACK_FILE = os.path.join(DIR_BOT, 'last_track.txt')
MAX_HISTORY = 30
PAGE_SIZE = 15
PAGE_SIZE_LARGE = 75  # полный список: 50-100 треков на странице

# --- Мониторинг воспроизведения ---
_play_monitor_event = threading.Event()
_play_monitor_thread = None
_play_monitor_token = None

def load_config():
    env = {}
    for p in (CONFIG, os.path.join(DIR_BOT, 'narimanov.env'), os.path.join(DIR_BOT, 'vm1.env')):
        if os.path.isfile(p):
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        env[k.strip()] = v.strip()
    # Под systemd EnvironmentFile задаёт переменные — им даём приоритет
    env.setdefault('BOT_TOKEN', os.environ.get('BOT_TOKEN', ''))
    if os.environ.get('BOT_TOKEN'):
        env['BOT_TOKEN'] = os.environ.get('BOT_TOKEN')
    env.setdefault('LOG_GROUP_ID', os.environ.get('LOG_GROUP_ID', ''))
    env.setdefault('LOG_GROUP_IDS', os.environ.get('LOG_GROUP_IDS', ''))
    if os.environ.get('LOG_GROUP_ID'):
        env['LOG_GROUP_ID'] = os.environ.get('LOG_GROUP_ID', '')
    env.setdefault('MUSIC_ROOT', os.environ.get('MUSIC_ROOT', '/home/kamran/Kamran Music'))
    if os.environ.get('MUSIC_ROOT'):
        env['MUSIC_ROOT'] = os.environ.get('MUSIC_ROOT')
    env.setdefault('CLIENT_HOST', os.environ.get('CLIENT_HOST', ''))
    env.setdefault('CLIENT_USER', os.environ.get('CLIENT_USER', ''))
    env.setdefault('CLIENT_INBOX', os.environ.get('CLIENT_INBOX', '/var/lib/campus-player/inbox'))
    env.setdefault('SSH_KEY', os.environ.get('SSH_KEY', '/home/kamran/.ssh/campus_bot'))
    env.setdefault('DEFAULT_VOL', os.environ.get('DEFAULT_VOL', '70'))
    env.setdefault('SERVER_HOST', os.environ.get('SERVER_HOST', '10.10.4.120'))
    env.setdefault('VM1_HOST', os.environ.get('VM1_HOST', ''))
    env.setdefault('NCTK_HOST', os.environ.get('NCTK_HOST', ''))
    for k in ('CLIENT_HOST', 'CLIENT_USER', 'CLIENT_INBOX', 'SSH_KEY', 'DEFAULT_VOL',
              'SERVER_HOST', 'VM1_HOST', 'NCTK_HOST', 'LOG_GROUP_ID', 'LOG_GROUP_IDS'):
        if os.environ.get(k):
            env[k] = os.environ.get(k)
    return env

_TRACK_LIST_CACHE = []
_TRACK_LIST_ROOT = None  # какую папку использовали

def _scan_music_dir(d):
    """Сканирует одну папку, возвращает список имён файлов."""
    if not d or not os.path.isdir(d):
        return []
    exts = ('mp3', 'mp4', 'mpeg', 'm4a', 'ogg', 'wav')
    out = []
    try:
        for f in os.listdir(d):
            if not os.path.isfile(os.path.join(d, f)):
                continue
            low = f.lower()
            if any(low.endswith('.' + e) for e in exts):
                out.append(f)
        out.sort(key=lambda x: x.lower())
    except OSError:
        return []
    return out

def _build_track_list():
    """Сканируем папку музыки. Пробуем MUSIC_ROOT и при пустом результате — fallback."""
    global _TRACK_LIST_CACHE, _TRACK_LIST_ROOT
    cfg = load_config()
    primary = (cfg.get('MUSIC_ROOT') or '').strip()
    fallbacks = [primary]
    if primary != '/home/kamran/Kamran Music':
        fallbacks.append('/home/kamran/Kamran Music')
    if primary != '/mnt/music/Kamran Music':
        fallbacks.append('/mnt/music/Kamran Music')
    for d in fallbacks:
        if not d:
            continue
        out = _scan_music_dir(d)
        if out:
            _TRACK_LIST_CACHE = out
            _TRACK_LIST_ROOT = d
            return out
    _TRACK_LIST_CACHE = []
    _TRACK_LIST_ROOT = primary or fallbacks[-1] if fallbacks else ''
    return []

def get_tracks_total():
    return len(_build_track_list())

def _clean_track_name(filename):
    """'0001_Artist - Title.mp3' → 'Artist - Title'"""
    name = re.sub(r'^[0-9]+[_\-\.\s]+', '', filename)
    name = re.sub(r'\.(mp3|mp4|m4a|ogg|wav|mpeg)$', '', name, flags=re.IGNORECASE)
    return name.strip() or filename

def build_track_list_text(offset, count, track_list):
    """Текстовый блок с именами треков для диапазона offset..offset+count."""
    lines = []
    for i in range(offset, min(offset + count, len(track_list))):
        name = _clean_track_name(track_list[i])
        if len(name) > 58:
            name = name[:56] + '…'
        lines.append(f"{i+1}. {name}")
    return "\n".join(lines)

def get_music_root_display():
    """Папка, которую используем (для сообщений)."""
    _build_track_list()
    return _TRACK_LIST_ROOT or load_config().get('MUSIC_ROOT', '') or '(не задана)'

def clear_track_cache():
    """Сброс кэша треков — следующее чтение заново сканирует папку."""
    global _TRACK_LIST_CACHE, _TRACK_LIST_ROOT
    _TRACK_LIST_CACHE = []
    _TRACK_LIST_ROOT = None


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
    try:
        r = api(token, 'getChatMember', chat_id=chat_id, user_id=user_id)
        if not r.get('ok'):
            return False
        status = (r.get('result') or {}).get('status') or ''
        return status in ('creator', 'administrator')
    except Exception:
        return False


def set_bot_commands(token):
    """Регистрирует команды бота — при вводе / в Telegram покажется список с описаниями.
    Задаём для личных чатов и для групп, чтобы команды отображались везде."""
    commands = [
        {'command': 'start', 'description': 'Начать / меню и кнопки'},
        {'command': 'menu', 'description': 'Главное меню'},
        {'command': 'list', 'description': 'Список треков (15 на стр.)'},
        {'command': 'list_full', 'description': 'Полный список (75 треков)'},
        {'command': 'playall', 'description': 'Играть все треки подряд'},
        {'command': 'history', 'description': 'История воспроизведения'},
        {'command': 'status', 'description': 'Статус: что играет'},
        {'command': 'stop', 'description': 'Остановить'},
        {'command': 'volup', 'description': 'Громче'},
        {'command': 'voldown', 'description': 'Тише'},
        {'command': 'info', 'description': 'Полная информация'},
        {'command': 'schedule', 'description': 'Расписание'},
        {'command': 'refresh', 'description': 'Обновить кэш'},
        {'command': 'backup', 'description': 'Бэкапы'},
        {'command': 'recover', 'description': 'Перезапустить всю инфраструктуру'},
        {'command': 'help', 'description': 'Список всех команд'},
    ]
    for scope in [{'type': 'default'}, {'type': 'all_group_chats'}]:
        try:
            api(token, 'setMyCommands', commands=commands, scope=scope)
        except Exception:
            pass


def commands_help_text():
    """Текст со списком всех команд для /help и /commands."""
    return """📋 <b>Команды бота (введите / в чате для автоподсказки):</b>

<b>Управление:</b>
/start, /menu — меню и кнопки
/stop — остановить
/volup, /voldown — громкость ±10%

<b>Воспроизведение:</b>
/list — список треков (15 на стр.)
/list_full — полный список (75 на стр.)
/playall — играть все треки подряд
/history — история воспроизведения
Число или play N — трек по номеру

<b>Информация:</b>
/status — что играет, громкость
/info — полная информация
/schedule — расписание
/refresh — обновить кэш
/backup — бэкапы
/recover — перезапустить всю инфраструктуру

<b>Кнопки:</b> Громче, Тише, Стоп, След./Пред. песня, История, Список треков, Полный список, Играть всё."""

def _ssh_base(cfg):
    return [
        'ssh', '-i', cfg.get('SSH_KEY', ''),
        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
        '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null', '-o', 'LogLevel=ERROR',
        f"{cfg.get('CLIENT_USER', '')}@{cfg.get('CLIENT_HOST', '')}",
    ]

def _clean_ssh_output(text):
    """Убираем из вывода SSH строки вроде 'Warning: Permanently added...'."""
    if not text:
        return ''
    lines = [line for line in (text or '').splitlines() if not line.strip().startswith('Warning:')]
    return '\n'.join(lines).strip()

def ssh_run(cfg, cmd):
    try:
        p = subprocess.run(
            _ssh_base(cfg) + [cmd],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
        if p.returncode != 0:
            return None
        return _clean_ssh_output(p.stdout or '')
    except Exception:
        return None

def scp_to_inbox(cfg, local_path):
    """Копирует local_path на клиент в CLIENT_INBOX/in.mp3."""
    try:
        p = subprocess.run(
            [
                'scp', '-i', cfg.get('SSH_KEY', ''),
                '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                local_path,
                f"{cfg.get('CLIENT_USER')}@{cfg.get('CLIENT_HOST')}:{cfg.get('CLIENT_INBOX', '')}/in.mp3",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=30,
        )
        return p.returncode == 0
    except Exception:
        return False

def campus(cfg, cmd):
    out = ssh_run(cfg, f'/usr/local/bin/campus-playerctl {cmd}')
    return out if out is not None else 'Плеер недоступен (SSH)'

def get_time_remote(host, user, key=None):
    """Получить время на удалённой машине по SSH."""
    if not host or not user:
        return '—'
    opts = '-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=3'
    key_opt = f'-i {key}' if key and os.path.isfile(key) else ''
    cmd = f'ssh {key_opt} {opts} {user}@{host} "date +\'%H:%M:%S %d.%m.%Y\'" 2>/dev/null'
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        out = (r.stdout or '').strip()
        return out if r.returncode == 0 and out else '—'
    except Exception:
        return '—'

def get_time_all_machines(update_date_ts=None):
    """Время на Server, vm1, nctk, Телефон. Бот работает на сервере."""
    cfg = load_config()
    key = cfg.get('SSH_KEY') or cfg.get('SSH_KEY_FOR_TIME')
    srv = cfg.get('SERVER_HOST', '10.10.4.120')
    vm1_host = cfg.get('VM1_HOST') or (cfg.get('CLIENT_HOST') if cfg.get('CLIENT_USER') == 'vm1' else '')
    nctk_host = cfg.get('NCTK_HOST') or (cfg.get('CLIENT_HOST') if cfg.get('CLIENT_USER') == 'nctk' else '')
    lines = []
    lines.append(f"🖥 Server (centos): {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}")
    if nctk_host:
        lines.append(f"🖥 nctk: {get_time_remote(nctk_host, 'nctk', key)}")
    if vm1_host:
        lines.append(f"🖥 vm1: {get_time_remote(vm1_host, 'vm1', key)}")
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
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=8,
            env={**os.environ, 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'})
        return (r.stdout or '').strip() if r.returncode == 0 else None
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
    """Статус серверов: RAM, CPU, диск, температура."""
    cfg = load_config()
    key = cfg.get('SSH_KEY', '/home/kamran/.ssh/campus_bot')
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
    results.append(_format_machine_status("Сервер (локально)", local_out or "Ошибка"))
    nctk_host = cfg.get('NCTK_HOST') or (cfg.get('CLIENT_HOST') if cfg.get('CLIENT_USER') == 'nctk' else '')
    if nctk_host:
        out = _ssh_sysinfo(nctk_host, 'nctk', key, sysinfo_cmd)
        results.append(_format_machine_status(f"nctk ({nctk_host})", out))
    vm1_host = cfg.get('VM1_HOST') or (cfg.get('CLIENT_HOST') if cfg.get('CLIENT_USER') == 'vm1' else '')
    if vm1_host:
        out = _ssh_sysinfo(vm1_host, 'vm1', key, sysinfo_cmd)
        results.append(_format_machine_status(f"vm1 ({vm1_host})", out))
    return "🖥 <b>Статус серверов</b>\n\n" + "\n\n".join(results)

def _parse_volume_from_status(status_text):
    """Из вывода campus-playerctl status извлекаем громкость (0–160).
    Поддерживает форматы:
      VOL=115
      OK volume=115.0 paused=False path=-
    """
    if not status_text:
        return None
    import re
    for line in status_text.splitlines():
        line = line.strip()
        # Формат: VOL=115
        if line.startswith('VOL='):
            try:
                return int(float(line[4:].strip()))
            except ValueError:
                continue
        # Формат: OK volume=115.0 paused=False path=-
        m = re.search(r'volume=([0-9]+(?:\.[0-9]+)?)', line)
        if m:
            try:
                return int(float(m.group(1)))
            except ValueError:
                continue
    return None

def get_volume_remote(cfg):
    """Текущая громкость на клиенте (0–160) или None."""
    out = campus(cfg, 'status')
    return _parse_volume_from_status(out)

def get_current_track_num():
    if not os.path.isfile(LAST_TRACK_FILE):
        return None
    try:
        with open(LAST_TRACK_FILE) as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None

def _write_last_track(num):
    try:
        with open(LAST_TRACK_FILE, 'w') as f:
            f.write(str(num))
    except Exception:
        pass

def _vol_change(cfg, direction):
    """direction: 'volup' или 'voldown'. Возвращает (ok, message)."""
    before = get_volume_remote(cfg)
    out = campus(cfg, direction)
    # Проверка: SSH недоступен или на клиенте нет volup/voldown
    out_str = (out or '').strip()
    cmd_failed = (
        not out
        or 'недоступен' in out_str.lower()
        or 'usage:' in out_str.lower()
        or 'error' in out_str.lower()
        or 'command not found' in out_str.lower()
        or 'no such file' in out_str.lower()
    )
    after = _parse_volume_from_status(out) if out else None
    if after is None:
        after = get_volume_remote(cfg)
    # Если команда не сработала, но текущую громкость знаем — шлём vol N (работает и со старым playerctl)
    if (after is None or cmd_failed) and before is not None:
        if direction == 'volup':
            new_vol = min(160, before + 10)
        else:
            new_vol = max(0, before - 10)
        campus(cfg, f'vol {new_vol}')
        after = get_volume_remote(cfg)
    # Всегда показываем числа, когда есть
    if before is not None and after is not None:
        return True, f'Громкость: было {before}%, стало {after}%\nСейчас: {after}%'
    if after is not None:
        return True, f'Громкость: стало {after}%\nСейчас: {after}%'
    if before is not None:
        return True, f'Громкость: было {before}%, команда отправлена. (Текущее не получено — проверьте SSH и playerctl на клиенте.)'
    host = cfg.get('CLIENT_HOST', '')
    user = cfg.get('CLIENT_USER', 'vm1')
    return True, (
        'Громкость не получена с плеера.\n'
        f'Проверьте: ssh -i KEY {user}@{host} campus-playerctl status'
    )

def vol_up():
    cfg = load_config()
    if not cfg.get('CLIENT_HOST'):
        return False, 'Плеер недоступен'
    return _vol_change(cfg, 'volup')

def vol_down():
    cfg = load_config()
    if not cfg.get('CLIENT_HOST'):
        return False, 'Плеер недоступен'
    return _vol_change(cfg, 'voldown')

def _all_log_group_ids():
    """Список всех LOG_GROUP_IDS из конфига."""
    cfg = load_config()
    ids_str = (cfg.get('LOG_GROUP_IDS') or cfg.get('LOG_GROUP_ID') or '').strip()
    return [g.strip() for g in ids_str.split(',') if g.strip()]

def notify_all_groups(token, text):
    """Отправить уведомление во ВСЕ лог-группы."""
    for gid in _all_log_group_ids():
        try:
            send(token, gid, text)
        except Exception:
            pass

def notify_play_start(token, cfg, username, filename, ok):
    """Уведомление о начале воспроизведения во все группы."""
    ts = datetime.now().strftime('%H:%M:%S  %d.%m.%Y')
    client_host = cfg.get('CLIENT_HOST', '?')
    client_user = cfg.get('CLIENT_USER', '')
    status = '✅ успешно' if ok else '❌ ошибка'
    text = (
        f"▶️ Воспроизведение начато\n"
        f"👤 Кто: {_at(username)}\n"
        f"⏰ Когда: {ts}\n"
        f"🖥 Клиент: {client_user}@{client_host}\n"
        f"🎵 Файл: {filename}\n"
        f"{'✅' if ok else '❌'} Статус: {status}"
    )
    notify_all_groups(token, text)

def notify_play_end(token, filename, elapsed_sec, reason):
    """Уведомление о завершении воспроизведения во все группы."""
    ts = datetime.now().strftime('%H:%M:%S  %d.%m.%Y')
    mins, secs = divmod(int(elapsed_sec), 60)
    text = (
        f"⏹ Воспроизведение завершено\n"
        f"🎵 Файл: {filename}\n"
        f"⏱ Длительность: {mins}:{secs:02d} мин\n"
        f"⏰ Время: {ts}\n"
        f"🔚 Причина: {reason}"
    )
    notify_all_groups(token, text)

def _monitor_playback(token, cfg, filename, start_time, stop_event):
    """Фоновый поток: следит за статусом плеера, шлёт уведомление когда кончилось."""
    poll_interval = 8
    max_polls = 450  # макс 1 час
    for _ in range(max_polls):
        if stop_event.wait(poll_interval):
            return  # остановлено пользователем — уведомление уже отправлено
        out = campus(cfg, 'status') or ''
        m_paused = re.search(r'paused=(\w+)', out)
        m_path = re.search(r'path=(\S+)', out)
        if m_paused:
            paused = m_paused.group(1).lower() == 'true'
            path = m_path.group(1) if m_path else '-'
            if paused or path == '-':
                elapsed = time.time() - start_time
                notify_play_end(token, filename, elapsed, 'файл закончился')
                return

def start_play_monitor(token, cfg, filename):
    """Запустить фоновый мониторинг. Отменяет предыдущий если был."""
    global _play_monitor_event, _play_monitor_thread, _play_monitor_token
    _play_monitor_event.set()
    if _play_monitor_thread and _play_monitor_thread.is_alive():
        _play_monitor_thread.join(timeout=1)
    _play_monitor_event = threading.Event()
    _play_monitor_token = token
    t = threading.Thread(
        target=_monitor_playback,
        args=(token, cfg, filename, time.time(), _play_monitor_event),
        daemon=True
    )
    _play_monitor_thread = t
    t.start()

def stop_play_monitor():
    """Сигнализировать мониторингу что плеер остановлен пользователем."""
    _play_monitor_event.set()

def log_action(token, log_group_id, msg, also_file=True, chat_id=None):
    """Логирование: в файл и в Telegram. Только в чат, где действие (chat_id) — без дублирования в другие группы."""
    ts = datetime.now().strftime('%H:%M:%S %d.%m')
    line = f"[{ts}] {msg}"
    if also_file:
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass
    target = str(chat_id).strip() if chat_id else (str(log_group_id).strip() if log_group_id else None)
    if target and token:
        try:
            send(token, target, f"📌 {line}", reply_markup=main_keyboard())
        except Exception:
            pass

def _at(username):
    """Единый формат для логов: всегда @username."""
    u = (username or '?').strip()
    return f"@{u.lstrip('@')}" if u else '@?'

def log_event(token, log_group_id, event_type, detail, username='?', chat_id=None):
    """Логирование любого события (входное сообщение, колбэк, ошибка) — в файл и в группу."""
    log_action(token, log_group_id, f"[{event_type}] {detail} | {_at(username)}", also_file=True, chat_id=chat_id)

def get_track_path(num):
    """По номеру трека (1..N) возвращаем путь к файлу. Нумерация по отсортированному списку файлов."""
    lst = _build_track_list()
    if not lst or num < 1 or num > len(lst):
        return None
    d = _TRACK_LIST_ROOT or load_config().get('MUSIC_ROOT', '')
    return os.path.join(d, lst[num - 1])

def get_track_metadata(path):
    """Размер (байты), длительность (сек), формат. Возвращает dict или пустой."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    try:
        out['size'] = os.path.getsize(path)
        out['format'] = os.path.splitext(path)[1].lstrip('.').upper() or '?'
    except OSError:
        pass
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout:
            out['duration_sec'] = float(r.stdout.strip())
    except Exception:
        pass
    return out

def format_track_status_line(num, name, path):
    """Одна строка статуса: трек, имя, размер, длительность, формат."""
    meta = get_track_metadata(path) if path else {}
    size = meta.get('size')
    dur = meta.get('duration_sec')
    fmt = meta.get('format', '?')
    parts = [f"Трек: {num} ({name})"]
    if size is not None:
        if size >= 1024 * 1024:
            parts.append(f"Размер: {size / (1024*1024):.1f} МБ")
        else:
            parts.append(f"Размер: {size // 1024} КБ")
    if dur is not None:
        m, s = int(dur) // 60, int(dur) % 60
        parts.append(f"Длительность: {m}:{s:02d}")
    parts.append(f"Формат: {fmt}")
    return "\n".join(parts)

def get_last_cron_entries(max_lines=10):
    """Последние срабатывания крона из action.log: дата, время, действие, трек."""
    if not os.path.isfile(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        raw = [l.strip() for l in lines if 'Cron:' in l or 'Крон:' in l or 'cron' in l.lower()][-max_lines:]
        out = []
        for line in raw:
            # [10:00:05 12.02] Cron: воспроизведение запущено (громкость 80%) | TrackName.mp3
            m = re.match(r'\[(\d{2}:\d{2}:\d{2})\s+(\d{2}\.\d{2}(?:\.\d{2})?)\]\s*(.+)', line)
            if m:
                time_part, date_part, rest = m.group(1), m.group(2), m.group(3)
                track = ''
                if '|' in rest:
                    rest, track = rest.split('|', 1)
                    track = track.strip()
                if 'Landau' in rest:
                    out.append(f"📅 {date_part} {time_part[:5]} — Landau: {rest.split('|')[-1].strip() if '|' in rest else rest[:50]}")
                elif 'запущено' in rest or 'включен' in rest.lower():
                    out.append(f"📅 {date_part} {time_part[:5]} — включено: {track or '—'}")
                elif 'остановлено' in rest:
                    out.append(f"📅 {date_part} {time_part[:5]} — остановлено")
                else:
                    out.append(f"📅 {date_part} {time_part[:5]} — {rest[:50]}")
            else:
                out.append(line[:80])
        return out
    except Exception:
        return []

# Landau: 5 папок (1=пн..5=пт), сб/вс=папка 5. utro 07:45–07:59, гимн только пн 08:00–08:03 (180 с), потом перемены.
CRON_SCHEDULE_LANDAU = [
    (7, 45, "utro"), (7, 59, "stop"),
    (8, 0, "himn"), (8, 3, "stop"),   # himn только пн
    (8, 40, "1peremena"), (8, 45, "stop"),
    (9, 25, "2peremena"), (9, 40, "stop"),
    (10, 20, "3peremena"), (10, 25, "stop"),
    (11, 5, "4peremena"), (11, 10, "stop"),
    (11, 50, "5peremena"), (11, 55, "stop"),
    (12, 35, "6peremena"), (12, 40, "stop"),
    (13, 20, "7peremena"), (13, 25, "stop"),
    (14, 5, "8peremena"), (14, 10, "stop"),
    (14, 55, "9peremena"), (15, 5, "stop"),
]

def _landau_slot_label(slot):
    if slot == "utro":
        return "Утро utro.mp3 (07:45–07:59)"
    if slot == "himn":
        return "Гимн himn.mp3 (только пн 08:00–08:03, 180 с)"
    if slot == "stop":
        return "Стоп"
    if slot and slot.endswith("peremena"):
        return f"Перемена {slot[0]} ({slot}.mp3)"
    return slot or "—"

def get_next_on_schedule_text():
    """Текст: что на очереди по Landau — день (папка), слот, время, файл."""
    now = datetime.now()
    today_str = now.strftime("%d.%m")
    cur_min = now.hour * 60 + now.minute
    cfg = load_config()
    landau_root = (cfg.get("LANDAU_ROOT") or "").strip() or "/home/kamran/Landau"
    day = now.isoweekday()  # 1=пн, 7=вс
    folder = day if day <= 5 else 5  # папки только 1–5
    day_names = {1: "пн", 2: "вт", 3: "ср", 4: "чт", 5: "пт", 6: "сб", 7: "вс"}
    day_name = day_names.get(day, str(day))
    lines = []
    for h, m, slot in CRON_SCHEDULE_LANDAU:
        if slot == "stop":
            continue
        event_min = h * 60 + m
        if event_min > cur_min:
            time_str = f"{h:02d}:{m:02d}"
            label = _landau_slot_label(slot)
            filename = f"{slot}.mp3" if slot != "stop" else ""
            if slot == "himn":
                lines.append(f"• {time_str} | {label}\n  Папка: 1 (только понедельник)")
            else:
                lines.append(f"• {time_str} | {label}\n  День: {day_name}, папка: {folder}, файл: {filename}")
            if len(lines) >= 6:
                break
    if not lines:
        from datetime import timedelta
        tomorrow = now + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%d.%m")
        tday = tomorrow.isoweekday()
        tfolder = tday if tday <= 5 else 5
        tname = day_names.get(tday, str(tday))
        lines.append(f"• 07:45 | Утро utro.mp3 (07:45–07:59)")
        lines.append(f"  Завтра {tomorrow_str}, {tname}, папка {tfolder}")
        lines.append("  … 07:59 стоп, пн 08:00 гимн 180 с, 08:40 1peremena и т.д.")
        header = f"📅 На очереди (Landau)\n\nСегодня слоты прошли.\nПапки: {landau_root}/1..5 (1=пн..5=пт)\n\nСледующее:\n\n"
    else:
        header = f"📅 На очереди (Landau)\n\nСегодня {today_str}, {day_name}, папка {folder}\n{landau_root}/1..5\n\n"
    return header + "\n".join(lines)

BACKUP_DIR = "/home/kamran/backups"
BACKUP_LOG = "/home/kamran/backups/backup_nctk.log"

def get_backup_info():
    """Информация о бэкапах: когда сделано, что, размер, когда будет удалён/заменён."""
    lines = []
    # Файлы бэкапов в папке
    if os.path.isdir(BACKUP_DIR):
        try:
            for f in sorted(os.listdir(BACKUP_DIR)):
                if not f.endswith('.tgz'):
                    continue
                path = os.path.join(BACKUP_DIR, f)
                if not os.path.isfile(path):
                    continue
                try:
                    size = os.path.getsize(path)
                    mtime = os.path.getmtime(path)
                    dt = datetime.fromtimestamp(mtime)
                    date_str = dt.strftime('%d.%m.%Y %H:%M')
                    if size >= 1024 * 1024 * 1024:
                        size_str = f"{size / (1024**3):.1f} ГБ"
                    elif size >= 1024 * 1024:
                        size_str = f"{size / (1024**2):.1f} МБ"
                    else:
                        size_str = f"{size // 1024} КБ"
                    # nctk-full-* заменяется при следующем бекапе (вс 00:00)
                    if f.startswith('nctk-full-'):
                        lines.append(f"• {f}\n  Сделан: {date_str} | Размер: {size_str}\n  Будет заменён при след. бекапе (вс 00:00)")
                    else:
                        lines.append(f"• {f}\n  Сделан: {date_str} | Размер: {size_str}")
                except OSError:
                    pass
        except OSError:
            pass
    # Последние строки лога
    if os.path.isfile(BACKUP_LOG):
        try:
            with open(BACKUP_LOG, 'r', encoding='utf-8') as fp:
                log_lines = fp.readlines()
            last = [l.strip() for l in log_lines[-15:] if l.strip()]
            if last:
                lines.append("— Лог (последнее): —")
                for l in last[-5:]:
                    if len(l) > 70:
                        l = l[:67] + "..."
                    lines.append(l)
        except Exception:
            pass
    if not lines:
        return "Нет данных о бэкапах (папка недоступна или пуста)."
    return "\n".join(lines)

def run_recover():
    """Перезапускает Docker-стек и системные сервисы. Возвращает текст отчёта."""
    lines = ["🔄 <b>Восстановление инфраструктуры</b>"]
    compose_dir = "/home/kamran/projects/campus-infra"
    profiles = ["--profile", "logs", "--profile", "bot", "--profile", "watchdog", "--profile", "recovery"]

    # Docker stack
    try:
        r = subprocess.run(
            ["docker", "compose"] + profiles + ["up", "-d", "--remove-orphans"],
            cwd=compose_dir, capture_output=True, text=True, timeout=90
        )
        if r.returncode == 0:
            lines.append("✅ Docker stack: запущен/обновлён")
        else:
            lines.append(f"❌ Docker: {(r.stderr or r.stdout or '').strip()[:120]}")
    except Exception as e:
        lines.append(f"❌ Docker: {str(e)[:80]}")

    # SSH туннели Loki (работает т.к. бот запущен от root)
    for svc in ("loki-tunnel-nctk", "loki-tunnel-vm1"):
        try:
            r = subprocess.run(["systemctl", "restart", svc], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                lines.append(f"✅ {svc}: перезапущен")
            else:
                lines.append(f"⚠️ {svc}: {(r.stderr or '').strip()[:80] or 'нет прав'}")
        except Exception as e:
            lines.append(f"⚠️ {svc}: {str(e)[:60]}")

    # Статус контейнеров
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10
        )
        campus_containers = [l for l in r.stdout.strip().splitlines()
                             if any(k in l for k in ("campus", "grafana", "loki", "prometheus", "promtail", "node-exporter"))]
        if campus_containers:
            lines.append("\n<b>Контейнеры:</b>")
            for c in campus_containers[:10]:
                name, _, status = c.partition('\t')
                icon = "✅" if "Up" in status else "❌"
                lines.append(f"  {icon} {name}: {status.split('(')[0].strip()}")
    except Exception:
        pass

    # Перезапуск сестринского бота (этот бот не перезапускает сам себя — это делает systemd)
    lines.append("\nℹ️ Этот бот перезапустится при следующем сбое автоматически (systemd Restart=always).")
    lines.append("Для ручного перезапуска всех сервисов: <code>~/bin/campus-recover.sh</code>")

    return "\n".join(lines)


def play_track(token, log_group_id, chat_id, num, username, log=True):
    path = get_track_path(num)
    if not path:
        return False, f'Трек {num} не найден.'
    cfg = load_config()
    if not cfg.get('CLIENT_HOST'):
        return False, 'Плеер недоступен (нет CLIENT_HOST).'
    if not scp_to_inbox(cfg, path):
        return False, 'Ошибка копирования на плеер.'
    inbox_path = f"{cfg.get('CLIENT_INBOX', '')}/in.mp3"
    campus(cfg, f"play {shlex.quote(inbox_path)} {cfg.get('DEFAULT_VOL', '70')}")
    _write_last_track(num)
    ext = os.path.splitext(path)[1]
    filename = os.path.basename(path)
    add_to_history(num, username)
    if log:
        log_action(token, log_group_id, f"▶ Воспроизведение: трек {num}{ext} | {_at(username)}", also_file=True, chat_id=chat_id)
    notify_play_start(token, cfg, username, filename, True)
    start_play_monitor(token, cfg, filename)
    return True, f'▶ Играет: {num}{ext}'

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

# Флаг для остановки «Играть всё»
_play_all_stop = False
_play_all_active = False


def _play_all_worker(token, log_group_id, chat_id, username, track_nums):
    """Фоновый поток: воспроизводит треки по очереди. Проверяет _play_all_stop между треками."""
    global _play_all_active, _play_all_stop
    cfg = load_config()
    if not cfg.get('CLIENT_HOST'):
        try:
            send(token, chat_id, 'Плеер недоступен (нет CLIENT_HOST).', reply_markup=main_keyboard())
        except Exception:
            pass
        _play_all_active = False
        return
    for idx, num in enumerate(track_nums):
        if _play_all_stop:
            break
        path = get_track_path(num)
        if not path:
            continue
        if not scp_to_inbox(cfg, path):
            continue
        inbox_path = f"{cfg.get('CLIENT_INBOX', '')}/in.mp3"
        campus(cfg, f"play {shlex.quote(inbox_path)} {cfg.get('DEFAULT_VOL', '70')}")
        _write_last_track(num)
        add_to_history(num, username)
        try:
            log_action(token, log_group_id, f"▶ Играть всё: {num}/{len(track_nums)} | {_at(username)}", also_file=True, chat_id=chat_id)
        except Exception:
            pass
        dur = get_track_metadata(path).get('duration_sec')
        sleep_sec = (dur or 180) + 2
        for _ in range(int(sleep_sec)):
            if _play_all_stop:
                break
            time.sleep(1)
    _play_all_active = False
    try:
        if _play_all_stop:
            send(token, chat_id, '⏹ «Играть всё» остановлено.', reply_markup=main_keyboard())
            log_action(token, log_group_id, f"Играть всё остановлено | {_at(username)}", also_file=True, chat_id=chat_id)
        else:
            send(token, chat_id, '✅ «Играть всё» завершено.', reply_markup=main_keyboard())
            log_action(token, log_group_id, f"Играть всё завершено (все {len(track_nums)} треков) | {_at(username)}", also_file=True, chat_id=chat_id)
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
                    if n not in seen and 1 <= n <= get_tracks_total():
                        seen.add(n)
                        nums.append(n)
                except ValueError:
                    pass
        return nums[:20]
    except Exception:
        return []

def main_keyboard():
    return {
        'keyboard': [
            ['🔊 Громче', '🔉 Тише', '⏹ Стоп'],
            ['▶ След. песня', '◀ Пред. песня'],
            ['📋 История', '📂 Список треков', '📂 Полный список'],
            ['▶ Играть всё', 'ℹ️ Инфо', '📊 Статус', '🕐 Время', '🖥 Сервер', '📋 Меню'],
            ['🔄 Обновить', '📦 Бэкапы', '📅 На очереди'],
        ],
        'resize_keyboard': True,
    }

def inline_list_page(offset=0):
    total = get_tracks_total()
    if total == 0:
        return {'inline_keyboard': [[{'text': 'Нет треков', 'callback_data': 'noop'}]]}
    offset = max(0, min(offset, total - PAGE_SIZE))
    buttons, row = [], []
    for i in range(offset + 1, min(offset + PAGE_SIZE + 1, total + 1)):
        row.append({'text': str(i), 'callback_data': f'play_{i}'})
        if len(row) >= 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = []
    if offset > 0:
        nav.append({'text': '◀ Назад', 'callback_data': f'list_{max(0, offset - PAGE_SIZE)}'})
    if offset + PAGE_SIZE < total:
        nav.append({'text': 'Вперёд ▶', 'callback_data': f'list_{offset + PAGE_SIZE}'})
    if nav:
        buttons.append(nav)
    return {'inline_keyboard': buttons}


def inline_list_page_large(offset=0):
    """Полный список: 50-100 треков на странице (кнопки в несколько рядов)."""
    total = get_tracks_total()
    if total == 0:
        return {'inline_keyboard': [[{'text': 'Нет треков', 'callback_data': 'noop'}]]}
    offset = max(0, min(offset, total - PAGE_SIZE_LARGE))
    buttons, row = [], []
    for i in range(offset + 1, min(offset + PAGE_SIZE_LARGE + 1, total + 1)):
        row.append({'text': str(i), 'callback_data': f'play_{i}'})
        if len(row) >= 8:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = []
    if offset > 0:
        nav.append({'text': '◀ Назад', 'callback_data': f'listL_{max(0, offset - PAGE_SIZE_LARGE)}'})
    if offset + PAGE_SIZE_LARGE < total:
        nav.append({'text': 'Вперёд ▶', 'callback_data': f'listL_{offset + PAGE_SIZE_LARGE}'})
    if nav:
        buttons.append(nav)
    return {'inline_keyboard': buttons}

def inline_history_keyboard():
    nums = get_history()
    if not nums:
        return {'inline_keyboard': [[{'text': 'История пуста', 'callback_data': 'noop'}]]}
    buttons, row = [], []
    for n in nums[:15]:
        row.append({'text': f'▶ {n}', 'callback_data': f'play_{n}'})
        if len(row) >= 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return {'inline_keyboard': buttons}

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
    total = get_tracks_total()
    cfg = load_config()
    music_root = cfg.get('MUSIC_ROOT', '') or '(не задан)'
    log_group = 'включено (группа)' if (cfg.get('LOG_GROUP_ID') or '').strip() else 'только файл'
    cron_lines = get_last_cron_entries(8)
    cron_block = "\n".join(cron_lines) if cron_lines else "Пока нет записей."
    backup_block = html.escape(get_backup_info())
    return f"""ℹ️ <b>Полная информация — бот Нариманов</b>

<b>Кнопки (все):</b>
• 🔊 Громче / 🔉 Тише — громкость ±10%
• ⏹ Стоп — остановить
• ▶ След. песня / ◀ Пред. песня
• 📋 История / 📂 Список треков / 📂 Полный список (50–100 треков на стр.)
• ▶ Играть всё — воспроизвести все треки подряд
• ℹ️ Инфо / 📊 Статус / 📋 Меню
• 📅 На очереди — что дальше по расписанию крона

<b>Команды:</b>
/start, /menu — меню
/list — список треков (15 на стр.)
/list_full — полный список (75 на стр.)
/playall — играть все треки подряд
/history — история
/status — что играет (трек, размер, длительность, формат)
/schedule — что на очереди по расписанию
/stop — остановить
/volup, /voldown — громкость
play N или число — трек N

<b>Логирование:</b>
Каждое действие пишется в файл на сервере и в Telegram-группу (если задан LOG_GROUP_ID). События: меню, инфо, громкость, стоп, воспроизведение, список, история, ошибки.

<b>Сервер:</b>
Папка музыки: <code>{music_root}</code>
Треков: {total}

<b>Крон и переменные:</b>
Бот не изменяет crontab и не трогает системные переменные окружения — только читает свой конфиг.

<b>Последние срабатывания крона:</b>
{cron_block}

<b>Бэкапы:</b>
<pre>{backup_block}</pre>

Aue, Ala bura Təhsil olaçııııııgıdır"""

def menu_text():
    total = get_tracks_total()
    track_line = f"📂 Список треков — выбор из Kamran Music (1–{total})." if total else "📂 Список треков — в папке пока нет треков."
    return """📋 Управление звуком — используйте кнопки ниже.

▶ След. / Пред. — переключить трек.
📋 История — последние проигранные.
{} 
📂 Полный список — по 75 треков на странице.
▶ Играть всё — все {} треков подряд.

Можно писать: play N, число, /menu, /stop, /playall, /info.""".format(track_line, total or 0)

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
            total = get_tracks_total()
            if 1 <= num <= total:
                ok, msg = play_track(token, log_group_id, chat_id, num, username, log=True)
                send(token, chat_id, msg, reply_markup=main_keyboard())
                if not ok:
                    log_action(token, log_group_id, f"Ошибка: {msg} | {_at(username)}", also_file=True, chat_id=chat_id)
            else:
                send(token, chat_id, f"Трек {num} не найден (всего треков: {total}).", reply_markup=main_keyboard())
                log_action(token, log_group_id, f"Трек {num} вне диапазона (1–{total}) | {_at(username)}", also_file=True, chat_id=chat_id)
        except ValueError:
            pass
        return
    if data.startswith('list_'):
        try:
            offset = int(data[5:])
        except ValueError:
            offset = 0
        total = get_tracks_total()
        lst = _build_track_list()
        a, b = offset + 1, min(offset + PAGE_SIZE, total)
        names = build_track_list_text(offset, PAGE_SIZE, lst)
        msg_text = f"📂 Треки {a}–{b} из {total}:\n\n{names}\n\n▼ Нажмите номер для воспроизведения:"
        send(token, chat_id, msg_text, reply_markup=inline_list_page(offset))
        log_action(token, log_group_id, f"Список треков: стр. {a}–{b} | {_at(username)}", also_file=True, chat_id=chat_id)
        return
    if data.startswith('listL_'):
        try:
            offset = int(data[6:])
        except ValueError:
            offset = 0
        total = get_tracks_total()
        lst = _build_track_list()
        a, b = offset + 1, min(offset + PAGE_SIZE_LARGE, total)
        names = build_track_list_text(offset, PAGE_SIZE_LARGE, lst)
        msg_text = f"📂 Треки {a}–{b} из {total}:\n\n{names}\n\n▼ Нажмите номер для воспроизведения:"
        send(token, chat_id, msg_text, reply_markup=inline_list_page_large(offset))
        log_action(token, log_group_id, f"Полный список треков: стр. {a}–{b} | {_at(username)}", also_file=True, chat_id=chat_id)
        return

def handle_update(token, chat_id, log_group_id, update):
    global _play_all_active, _play_all_stop
    cid = chat_id or (update.get('message') or update.get('edited_message') or {}).get('chat', {}).get('id')
    if update.get('callback_query'):
        cq = update['callback_query']
        chat_id = cq.get('message', {}).get('chat', {}).get('id')
        user = cq.get('from', {})
        data = (cq.get('data') or '').strip()
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
    username = user.get('username') or user.get('first_name') or '?'
    text = (msg.get('text') or '').strip()
    # Нормализуем команды с @botname: /start@genclik1_bot -> /start
    cmd = text.split('@')[0].split()[0] if text and text.startswith('/') else text
    # Логирование «что нажато/отправлено и кем» — только в обработчиках действий (один лог на действие)
    if chat_type in ('group', 'supergroup'):
        if not is_chat_admin(token, chat_id, user_id):
            return
    kb = main_keyboard()
    cfg = load_config()

    if cmd in ('/start', '/menu') or text in ('меню', 'menu'):
        send(token, chat_id, menu_text(), reply_markup=kb)
        log_action(token, log_group_id, f"Меню открыто | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd in ('/help', '/commands') or text in ('помощь', 'команды'):
        send(token, chat_id, commands_help_text(), reply_markup=kb, parse_mode='HTML')
        log_action(token, log_group_id, f"Команды / help | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd == '/info' or text in ('инфо', 'info', 'Info', 'ℹ️ Инфо'):
        send(token, chat_id, info_text(), reply_markup=kb, parse_mode='HTML')
        log_action(token, log_group_id, f"Инфо открыто | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd == '/refresh' or text in ('Обновить', 'обновить', '🔄 Обновить'):
        clear_track_cache()
        total = get_tracks_total()
        path_used = get_music_root_display()
        send(token, chat_id, f"✅ Кэш обновлён.\nПапка: {path_used}\nЗагружено треков: {total}", reply_markup=kb)
        log_action(token, log_group_id, f"Обновить: кэш сброшен, треков {total} | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd == '/backup' or text in ('📦 Бэкапы', 'бэкапы', 'бекапы'):
        backup_text = get_backup_info()
        if len(backup_text) > 4000:
            backup_text = backup_text[:3990] + "\n... (обрезано)"
        send(token, chat_id, "📦 Бэкапы\n\n" + backup_text, reply_markup=kb)
        log_action(token, log_group_id, f"Бэкапы запрошены | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd == '/recover' or text in ('восстановить', 'recover', '🔄 Восстановить'):
        send(token, chat_id, "⏳ Запускаю восстановление инфраструктуры...", reply_markup=kb)
        log_action(token, log_group_id, f"RECOVER запущен | {_at(username)}", also_file=True, chat_id=chat_id)
        try:
            result = run_recover()
        except Exception as e:
            result = f"❌ Ошибка восстановления: {str(e)[:200]}"
        send(token, chat_id, result, reply_markup=kb, parse_mode='HTML')
        log_action(token, log_group_id, f"RECOVER завершён | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd == '/schedule' or text in ('📅 На очереди', 'расписание', 'на очереди'):
        sched_text = get_next_on_schedule_text()
        send(token, chat_id, sched_text, reply_markup=kb)
        log_action(token, log_group_id, f"На очереди (расписание) | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if text in ('🕐 Время', '/time', 'время', 'time'):
        ts = msg.get('date')
        time_text = get_time_all_machines(ts)
        send(token, chat_id, f"🕐 Время на машинах:\n\n{time_text}", reply_markup=kb)
        log_action(token, log_group_id, f"Время запрошено | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if text in ('🖥 Сервер', '/server', 'сервер', 'server'):
        try:
            status_text = get_server_status()
            send(token, chat_id, status_text, reply_markup=kb, parse_mode='HTML')
        except Exception as e:
            send(token, chat_id, f"❌ Ошибка: {str(e)[:200]}", reply_markup=kb)
        log_action(token, log_group_id, f"Сервер: статус запрошен | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if text == '📂 Список треков' or cmd == '/list':
        total = get_tracks_total()
        lst = _build_track_list()
        if not lst:
            path_used = get_music_root_display()
            send(token, chat_id, f"В папке нет треков.\nПапка: {path_used}\n\nПроверьте путь (MUSIC_ROOT) и права доступа на сервере.", reply_markup=kb)
            log_action(token, log_group_id, f"Список треков: папка пуста ({path_used}) | {_at(username)}", also_file=True, chat_id=chat_id)
        else:
            names = build_track_list_text(0, PAGE_SIZE, lst)
            msg_text = f"📂 Треки 1–{min(PAGE_SIZE, total)} из {total}:\n\n{names}\n\n▼ Нажмите номер для воспроизведения:"
            send(token, chat_id, msg_text, reply_markup=inline_list_page(0))
            log_action(token, log_group_id, f"Список треков открыт | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if text == '📂 Полный список' or cmd == '/list_full':
        total = get_tracks_total()
        lst = _build_track_list()
        if not lst:
            path_used = get_music_root_display()
            send(token, chat_id, f"В папке нет треков.\nПапка: {path_used}", reply_markup=kb)
            log_action(token, log_group_id, f"Полный список: папка пуста | {_at(username)}", also_file=True, chat_id=chat_id)
        else:
            show = min(PAGE_SIZE_LARGE, total)
            names = build_track_list_text(0, PAGE_SIZE_LARGE, lst)
            msg_text = f"📂 Треки 1–{show} из {total}:\n\n{names}\n\n▼ Нажмите номер для воспроизведения:"
            send(token, chat_id, msg_text, reply_markup=inline_list_page_large(0))
            log_action(token, log_group_id, f"Полный список треков открыт | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if text == '📋 История' or cmd == '/history':
        hist = get_history()
        if not hist:
            send(token, chat_id, 'История пуста.', reply_markup=kb)
        else:
            send(token, chat_id, '📋 Последние треки (нажмите чтобы включить):', reply_markup=inline_history_keyboard())
        log_action(token, log_group_id, f"История открыта | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if text == '▶ След. песня':
        cur = get_current_track_num()
        nxt = (cur + 1) if cur is not None else 1
        if nxt > get_tracks_total():
            nxt = 1
        ok, msg = play_track(token, log_group_id, chat_id, nxt, username, log=True)
        send(token, chat_id, msg, reply_markup=kb)
        return

    if text == '◀ Пред. песня':
        cur = get_current_track_num()
        total = get_tracks_total()
        prev = (cur - 1) if cur is not None else total
        if prev < 1:
            prev = total
        ok, msg = play_track(token, log_group_id, chat_id, prev, username, log=True)
        send(token, chat_id, msg, reply_markup=kb)
        return

    if cmd == '/playall' or text in ('▶ Играть всё', 'играть всё', 'играть все'):
        total = get_tracks_total()
        if total == 0:
            send(token, chat_id, 'В папке нет треков.', reply_markup=kb)
            return
        if _play_all_active:
            send(token, chat_id, 'Уже воспроизводится список. Нажмите Стоп для отмены.', reply_markup=kb)
            return
        _play_all_stop = False
        _play_all_active = True
        track_nums = list(range(1, total + 1))
        t = threading.Thread(
            target=_play_all_worker,
            args=(token, log_group_id, chat_id, username, track_nums),
            daemon=True,
        )
        t.start()
        send(token, chat_id, f"▶ Играю все {total} треков по порядку.\nНажмите ⏹ Стоп для отмены.", reply_markup=kb)
        log_action(token, log_group_id, f"▶ Играть всё запущено ({total} треков) | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd == '/volup' or text in ('🔊 Громче', 'громче'):
        ok, out = vol_up()
        send(token, chat_id, out, reply_markup=kb)
        log_action(token, log_group_id, f"🔊 Громче | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd == '/voldown' or text in ('🔉 Тише', 'тише'):
        ok, out = vol_down()
        send(token, chat_id, out, reply_markup=kb)
        log_action(token, log_group_id, f"🔉 Тише | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if cmd == '/stop' or text in ('⏹ Стоп', 'стоп', 'stop'):
        _play_all_stop = True
        stop_play_monitor()
        # Kill every audio process — mpv, ffmpeg, aplay, edge-tts, announcements
        ssh_run(cfg, 'pkill -9 mpv 2>/dev/null; pkill -9 ffmpeg 2>/dev/null; '
                     'pkill -9 aplay 2>/dev/null; pkill -9 paplay 2>/dev/null; '
                     'pkill -9 edge-tts 2>/dev/null; '
                     '/usr/local/bin/campus-playerctl stop 2>/dev/null; true')
        send(token, chat_id, '⏹ Остановлено.', reply_markup=kb)
        log_action(token, log_group_id, f"⏹ Стоп | {_at(username)}", also_file=True, chat_id=chat_id)
        ts = datetime.now().strftime('%H:%M:%S  %d.%m.%Y')
        notify_all_groups(token, (
            f"⏹ Воспроизведение остановлено\n"
            f"👤 Кто: {_at(username)}\n"
            f"⏰ Время: {ts}\n"
            f"🔚 Причина: остановлено пользователем"
        ))
        return

    if cmd == '/status' or text == '📊 Статус':
        cur = get_current_track_num()
        total = get_tracks_total()
        cfg = load_config()
        vol = get_volume_remote(cfg)
        lines = []

        # ── Воспроизведение ──────────────────────────────────────────
        lines.append("🎵 <b>Воспроизведение</b>")
        if cur is not None:
            lst = _build_track_list()
            name = _clean_track_name(lst[cur - 1]) if 1 <= cur <= len(lst) else '?'
            path = get_track_path(cur)
            meta = get_track_metadata(path) if path else {}
            dur = meta.get('duration_sec')
            dur_str = f"{int(dur)//60}:{int(dur)%60:02d}" if dur else '—'
            lines.append(f"  ▶ #{cur} {name}")
            lines.append(f"  ⏱ Длительность: {dur_str}   🔊 Громкость: {vol if vol is not None else '—'}%")
        else:
            lines.append(f"  ⏹ Ничего не играет")
            lines.append(f"  🔊 Громкость: {vol if vol is not None else '—'}%")
        lines.append(f"  📦 Треков в папке: {total}")

        # ── Сервер (локально, быстро) ────────────────────────────────
        sysinfo_cmd = (
            "free -h | grep '^Mem:' | awk '{print \"RAM: \"$3\"/\"$2}'; "
            "cat /proc/loadavg | awk '{print \"Load: \"$1\" \"$2\" \"$3}'; "
            "df -h / | tail -1 | awk '{print \"Диск: \"$3\"/\"$2\" (\"$5\")\"}'"
        )
        lines.append("\n🖥 <b>Сервер</b>")
        local = _run_sysinfo_cmd(sysinfo_cmd)
        if local:
            for l in local.strip().split('\n'):
                if l.strip():
                    lines.append(f"  {l.strip()}")
        else:
            lines.append("  ❌ Не получено")

        # ── Клиент (кампус) ──────────────────────────────────────────
        key = cfg.get('SSH_KEY', '/home/kamran/.ssh/campus_bot')
        client_host = cfg.get('CLIENT_HOST', '')
        client_user = cfg.get('CLIENT_USER', '')
        label = cfg.get('BOT_LABEL', client_user or 'клиент')
        lines.append(f"\n🖥 <b>Клиент ({label})</b>")
        if client_host and client_user:
            client_out = _ssh_sysinfo(client_host, client_user, key, sysinfo_cmd)
            if client_out:
                for l in client_out.strip().split('\n'):
                    if l.strip():
                        lines.append(f"  {l.strip()}")
            else:
                lines.append("  ❌ Недоступен")
        else:
            lines.append("  ⚠️ CLIENT_HOST не задан")

        # ── Расписание (следующие задачи крона) ─────────────────────
        lines.append("\n📅 <b>Расписание (кампус)</b>")
        sched = get_next_on_schedule_text()
        if sched:
            for l in sched.strip().split('\n')[:6]:
                if l.strip():
                    lines.append(f"  {l.strip()}")

        send(token, chat_id, "\n".join(lines), reply_markup=kb, parse_mode='HTML')
        log_action(token, log_group_id, f"Статус запрошен | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    voice = msg.get('voice') or msg.get('audio')
    doc = msg.get('document')
    if voice or doc:
        log_action(token, log_group_id, f"Голос/аудио/MP3 в чат от {_at(username)}", also_file=True, chat_id=chat_id)
        file_id = (voice or {}).get('file_id') or (doc and doc.get('file_name', '').lower().endswith(('.mp3', '.ogg', '.m4a')) and doc.get('file_id'))
        if file_id:
            try:
                local = download_file(token, file_id)
                if local:
                    if scp_to_inbox(cfg, local):
                        inbox_path = f"{cfg.get('CLIENT_INBOX', '')}/in.mp3"
                        campus(cfg, f"play {shlex.quote(inbox_path)} {cfg.get('DEFAULT_VOL', '70')}")
                        send(token, chat_id, '▶ Воспроизведение из чата.', reply_markup=kb)
                        log_action(token, log_group_id, f"▶ Из чата: голос/аудио от {_at(username)}", also_file=True, chat_id=chat_id)
                    else:
                        send(token, chat_id, 'Ошибка копирования на плеер.', reply_markup=kb)
                    try:
                        os.unlink(local)
                    except Exception:
                        pass
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
    total = get_tracks_total()
    if num and 1 <= num <= total:
        ok, msg = play_track(token, log_group_id, chat_id, num, username, log=True)
        send(token, chat_id, msg, reply_markup=kb)
        if not ok:
            log_action(token, log_group_id, f"Ошибка: {msg} | {_at(username)}", also_file=True, chat_id=chat_id)
        return
    if num and (num < 1 or num > total):
        send(token, chat_id, f"Трек {num} не найден (всего: {total}).", reply_markup=kb)
        log_action(token, log_group_id, f"Трек {num} вне диапазона | {_at(username)}", also_file=True, chat_id=chat_id)
        return

    if text and text.startswith('/'):
        send(token, chat_id, 'Неизвестная команда. /menu или /info.', reply_markup=kb)
        log_action(token, log_group_id, f"Неизвестная команда: {text[:50]} | {_at(username)}", also_file=True, chat_id=chat_id)

def main():
    env = load_config()
    token = env.get('BOT_TOKEN')
    if not token:
        print('Задайте BOT_TOKEN в config.env или narimanov.env', file=sys.stderr)
        sys.exit(1)
    if not env.get('CLIENT_HOST'):
        print('Задайте CLIENT_HOST для воспроизведения по SSH.', file=sys.stderr)
    set_bot_commands(token)  # При вводе / в Telegram — список команд с описаниями
    log_group_ids = (env.get('LOG_GROUP_IDS') or '').strip()
    if log_group_ids:
        log_group_ids = [g.strip() for g in log_group_ids.split(',') if g.strip()]
    else:
        g = (env.get('LOG_GROUP_ID') or '').strip()
        log_group_ids = [g] if g else []
    # При старте — отправить клавиатуру в группы (чтобы кнопки были видны)
    for gid in log_group_ids:
        try:
            send(token, gid, "🤖 Бот запущен. /menu или кнопки ниже.", reply_markup=main_keyboard())
        except Exception:
            pass
    url = f'https://api.telegram.org/bot{token}/getUpdates'
    offset = 0
    while True:
        try:
            req = urllib.request.Request(f'{url}?offset={offset}&timeout=50')
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            if not data.get('ok'):
                continue
            for upd in data.get('result', []):
                offset = upd['update_id'] + 1
                chat_id = None
                if upd.get('message'):
                    chat_id = upd['message'].get('chat', {}).get('id')
                elif upd.get('edited_message'):
                    chat_id = upd['edited_message'].get('chat', {}).get('id')
                elif upd.get('callback_query'):
                    chat_id = upd['callback_query'].get('message', {}).get('chat', {}).get('id')
                if chat_id is not None:
                    try:
                        lgid = log_group_ids[0] if log_group_ids else ''
                        handle_update(token, chat_id, lgid, upd)
                    except Exception as e:
                        try:
                            send(token, chat_id, f'Ошибка: {e}', reply_markup=main_keyboard())
                        except Exception:
                            pass
                        try:
                            log_action(token, lgid, f"Ошибка в handle_update: {e}", also_file=True, chat_id=chat_id)
                        except Exception:
                            pass
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print('Неверный BOT_TOKEN', file=sys.stderr)
                sys.exit(2)
        except Exception as e:
            try:
                with open(LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S %d.%m')}] Ошибка main: {e}\n")
            except Exception:
                pass
            import time
            time.sleep(5)

if __name__ == '__main__':
    main()
