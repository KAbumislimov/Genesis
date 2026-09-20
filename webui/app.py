from flask import Flask, render_template, redirect, url_for, request, jsonify, flash, session, send_from_directory, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, re, json, glob, socket, threading, time, shutil
import urllib.request, urllib.error
from functools import wraps
from datetime import datetime, timedelta
import paramiko
from itsdangerous import URLSafeTimedSerializer

def _require_secret(name, min_length=16):
    """No hardcoded fallback on purpose: a weak default that 'just works'
    is how a security review finds a real secret still set to it in prod."""
    val = os.environ.get(name, '')
    if len(val) < min_length:
        raise RuntimeError(
            f'{name} is missing or too short (need >= {min_length} chars). '
            f'Set a real random value in .env — refusing to start with a weak default.')
    return val

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = _require_secret('SECRET_KEY')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB max upload

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Необходимо войти в систему'

@login_manager.unauthorized_handler
def _unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'session_expired', 'reload': True}), 401
    return redirect(url_for('login', next=request.url))

@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Permissions-Policy'] = 'geolocation=(), camera=()'
    # Pragmatic CSP: the app relies on inline <script>/onclick handlers and
    # inline <style> blocks throughout its templates (not nonce-based), so a
    # strict CSP would break the UI. This still blocks the main real-world
    # threat — loading script/frames from an attacker-controlled origin.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; "
        "font-src 'self' cdn.jsdelivr.net fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response

@app.after_request
def _no_cache_html(response):
    if 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.before_request
def _profile_cors_preflight():
    if request.method == 'OPTIONS' and request.path in _PROFILE_CORS_PATHS:
        return ('', 204)

@app.after_request
def _profile_cors_headers(response):
    origin = request.headers.get('Origin', '')
    if request.path in _PROFILE_CORS_PATHS and origin == HELPDESK_URL:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ── Config ────────────────────────────────────────
CLIENT1_HOST = os.environ.get('CLIENT1_HOST', '10.20.0.41')
CLIENT1_USER = os.environ.get('CLIENT1_USER', 'client1')
SSH_KEY   = os.environ.get('SSH_KEY',   '/secrets/campus_bot')
MUSIC_DIR  = os.environ.get('MUSIC_DIR', '/music')
DB_PATH    = os.environ.get('DB_PATH',  '/data/webui.db')
SSO_BRIDGE_SECRET = _require_secret('SSO_BRIDGE_SECRET')
HELPDESK_URL = os.environ.get('HELPDESK_URL', 'https://10.10.4.120:8094')
_sso_serializer = URLSafeTimedSerializer(SSO_BRIDGE_SECRET)
_PROFILE_CORS_PATHS = ('/api/profile/update', '/api/profile/avatar', '/api/profile/password')
AVATAR_DIR = os.path.join(os.path.dirname(DB_PATH), 'avatars')
os.makedirs(AVATAR_DIR, exist_ok=True)
WALLPAPER_DIR = os.path.join(os.path.dirname(DB_PATH), 'wallpapers')
os.makedirs(WALLPAPER_DIR, exist_ok=True)
ALLOWED_IMG_EXT = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'avif'}
MPV_SOCK  = '/run/campus-player/mpv.sock'
BACKUP_DIR        = os.environ.get('BACKUP_DIR', '/campus-backups')
BACKUP_VAULT_PASS = os.environ.get('BACKUP_VAULT_PASS', '')
# Пароль входа на страницу «Бэкапы» (скачивание архивов). Отдельный от ключа шифрования снимков (BACKUP_VAULT_PASS):
# его можно менять свободно, не трогая снимки в GitHub. Если не задан — как раньше, используется BACKUP_VAULT_PASS.
BACKUP_UI_PASS = os.environ.get('BACKUP_UI_PASS', '')
BACKUP_ADMIN_EMAILS = os.environ.get('BACKUP_ADMIN_EMAILS', '')
VOICE_DIR = os.path.join(os.path.dirname(DB_PATH), 'voices')
os.makedirs(VOICE_DIR, exist_ok=True)
ANNOUNCE_DIR = os.path.join(os.path.dirname(DB_PATH), 'announces')
os.makedirs(ANNOUNCE_DIR, exist_ok=True)

# ── Machines ──────────────────────────────────────
MACHINES = []   # rebuilt by reload_machines() after DB init

def _default_music_path(user, host):
    """Best-guess remote Media music folder for a machine that never had
    one explicitly set — matches the convention every machine added so far
    has used (client1 is the one historical exception, hardcoded below)."""
    return f'/home/{user or host}/Media'

def reload_machines():
    """Rebuild MACHINES from env vars + DB thin_clients table. Every entry
    now also carries is_audio_client (should it show up as a campus in the
    player — tabs, status strip, EQ, special actions — or is it monitoring-
    only infra like a Proxmox host) and music_path (remote Media folder
    used for playback), so a machine added via /machines is fully wired
    into the player without touching any other code."""
    global MACHINES
    machines = []
    for _i in range(1, 6):
        _h = os.environ.get(f'MACHINE{_i}_HOST', '')
        _n = os.environ.get(f'MACHINE{_i}_NAME', '')
        _m = os.environ.get(f'MACHINE{_i}_MAC', '')
        _u = os.environ.get(f'MACHINE{_i}_USER', CLIENT1_USER)
        _c = os.environ.get(f'MACHINE{_i}_COCKPIT', '')
        _mp = os.environ.get(f'MACHINE{_i}_MUSIC_PATH', '') or _default_music_path(_u, _h)
        # Lets an env-configured machine (unlike a /machines thin_client row)
        # be pulled out of the player's campus lists without deleting its
        # connection info — e.g. a decommissioned campus still reachable for
        # terminal/monitoring but no longer a playback target.
        _ia = os.environ.get(f'MACHINE{_i}_IS_AUDIO_CLIENT', '1').strip().lower() not in ('0', 'false', '')
        if _h and _n:
            machines.append({'id': f'm{_i}', 'host': _h, 'name': _n, 'mac': _m,
                              'user': _u, 'cockpit_url': _c, 'from_db': False,
                              'is_audio_client': _ia, 'music_path': _mp})
    if not any(m['host'] == CLIENT1_HOST for m in machines):
        machines.insert(0, {
            'id': 'client1', 'host': CLIENT1_HOST,
            'name': 'Client1 Campus',
            'mac': os.environ.get('CLIENT1_MAC', ''),
            'user': CLIENT1_USER,
            'cockpit_url': f'http://{CLIENT1_HOST}:1991',
            'from_db': False,
            'is_audio_client': True,
            'music_path': os.environ.get('CLIENT1_MUSIC_PATH', '/mnt/music/Media'),
        })
    try:
        with get_db() as c:
            rows = c.execute('SELECT * FROM thin_clients ORDER BY id').fetchall()
        for row in rows:
            row_d = dict(row)
            machines.append({
                'id':          f'db_{row["id"]}',
                'host':        row['host'],
                'name':        row['name'],
                'mac':         row['mac'],
                'user':        row['user'],
                'cockpit_url': row['cockpit_url'],
                'from_db':     True,
                'db_id':       row['id'],
                'is_audio_client': bool(row_d.get('is_audio_client', 1)),
                'music_path': row_d.get('music_path') or _default_music_path(row['user'], row['host']),
            })
    except Exception:
        pass
    MACHINES = machines

def music_machines():
    """MACHINES entries that should appear as a campus in the player."""
    return [m for m in MACHINES if m.get('is_audio_client')]

def _campus_key(m):
    """The short slug used everywhere (URLs, _activeCampus, api calls) to
    refer to a campus — 'client1' for the main machine, otherwise its `user`
    (the SSH login, already a short readable slug like 'client2'/'cgtk'/'sbtk'
    by convention for every machine added so far). 'client1' is reserved for the
    real Client1 host — _resolve_machine() never searches MACHINES for it,
    so a thin_client whose `user` was (mis)typed as literally "client1" must not
    collide with that slug, or it silently becomes an unreachable duplicate
    (falls back to its own MACHINES-list id instead)."""
    if m['host'] == CLIENT1_HOST:
        return 'client1'
    key = m.get('user') or m['id']
    return m['id'] if key == 'client1' else key

_CAMPUS_SHORT_LABELS = {'client1': 'NAR', 'client2': 'GNC', 'cgtk': 'CG'}
# The original three machines' `name` field is whatever MACHINE1_NAME/etc
# happens to be set to in .env (e.g. "client2 Campus" — a generic ops label, not
# what staff actually call the place) — everywhere in the UI has always shown
# the real campus name instead, so keep that override here rather than
# leaking the env label once name display started coming from this function.
_CAMPUS_DISPLAY_OVERRIDE = {'client1': 'Client1'}

def music_machines_json():
    """[{key,name,short}, ...] for every player-visible campus — feeds the
    campus switcher/status-strip/labels in the frontend, so a machine
    added via /machines shows up everywhere without template changes.
    `short` is a compact badge label (NAR/GNC/CG for the original three,
    kept for familiarity; auto-derived from the key for anything newer)."""
    out = []
    for m in music_machines():
        key = _campus_key(m)
        short = _CAMPUS_SHORT_LABELS.get(key) or key[:4].upper()
        name = _CAMPUS_DISPLAY_OVERRIDE.get(key) or m['name']
        out.append({'key': key, 'name': name, 'short': short})
    # Два кампуса с общим префиксом ключа (lhmtk / lhmtk2) давали одинаковую
    # плашку "LHMT" — при коллизии показываем ключ целиком.
    from collections import Counter
    _cnt = Counter(o['short'] for o in out)
    for o in out:
        if _cnt[o['short']] > 1:
            o['short'] = o['key'].upper()
    return out

def _music_path_for(machine_key):
    """Remote Media music folder for any machine key (id/user/name/host),
    including client1 and anything added later via /machines — replaces the
    old hardcoded _MEDIA_PATHS 3-entry dict."""
    if not machine_key or machine_key == 'client1':
        m = next((x for x in MACHINES if x['host'] == CLIENT1_HOST), None)
        return (m and m.get('music_path')) or '/mnt/music/Media'
    m = _resolve_machine(machine_key, strict=True)
    if m and m.get('music_path'):
        return m['music_path']
    return _default_music_path(machine_key, machine_key)

def _is_known_campus(machine_key):
    """True for client1 or any machine _resolve_machine can find — the dynamic
    replacement for `campus in _MEDIA_PATHS`."""
    if machine_key == 'client1':
        return True
    return _resolve_machine(machine_key, strict=True) is not None

PROMETHEUS_CONFIG = os.environ.get('PROMETHEUS_CONFIG', '')
PROMETHEUS_RELOAD_URL = os.environ.get('PROMETHEUS_RELOAD_URL', '')

def sync_prometheus_targets():
    """Adds a scrape target for any machine (from MACHINES) whose host_ip
    isn't already in prometheus.yml's `node` job — additive only, never
    removes an existing target (a stale one just shows as "down" in
    Prometheus, which is a visible, safe failure mode, unlike accidentally
    dropping a target something else still depends on). Preserves the file's
    existing formatting/comments via targeted text insertion rather than a
    full YAML parse+dump, since the file is hand-maintained."""
    if not PROMETHEUS_CONFIG or not os.path.isfile(PROMETHEUS_CONFIG):
        return
    try:
        with open(PROMETHEUS_CONFIG, encoding='utf-8') as f:
            text = f.read()
        added = []
        for m in MACHINES:
            host = m.get('host')
            if not host or f'host_ip: {host}' in text:
                continue
            # Prefer the human-typed 'user' field (e.g. "cgtk") over the
            # DB row id ("db_6") so Grafana/Prometheus labels stay readable
            nodename = (m.get('user') or m.get('id') or m.get('name') or host).replace(' ', '_')
            block = (f"      - targets: ['{host}:9100']\n"
                     f"        labels:\n"
                     f"          nodename: {nodename}\n"
                     f"          host_ip: {host}\n")
            marker = '    relabel_configs:'
            if marker not in text:
                continue
            text = text.replace(marker, block + marker, 1)
            added.append(nodename)
        if added:
            with open(PROMETHEUS_CONFIG, 'w', encoding='utf-8') as f:
                f.write(text)
            if PROMETHEUS_RELOAD_URL:
                try:
                    urllib.request.urlopen(
                        urllib.request.Request(PROMETHEUS_RELOAD_URL, method='POST'), timeout=5)
                except Exception:
                    pass
    except Exception:
        pass

# ── CentOS server (terminal only) ─────────────────
CENTOS_HOST    = os.environ.get('CENTOS_HOST', '10.10.4.120')
CENTOS_USER    = os.environ.get('CENTOS_USER', 'kamran')
CENTOS_SSH_KEY = os.environ.get('CENTOS_SSH_KEY', SSH_KEY)
CLIENT2_HOST = os.environ.get('CLIENT2_HOST', os.environ.get('MACHINE2_HOST', '10.70.0.41'))
CLIENT2_USER = os.environ.get('MACHINE2_USER', 'client2')
# Base URL for streaming audio to campus machines (HTTP so no TLS issues with internal cert)
WEBUI_STREAM_BASE = os.environ.get('WEBUI_STREAM_BASE', f'https://{CENTOS_HOST}:8090')

def _resolve_machine(machine_key, strict=False):
    """Find a MACHINES entry by explicit id/user/name match. With strict=False
    (the default, used by _client2_conn/_get_client2 for backward compatibility)
    falls back to "first non-client1 machine" when nothing matches exactly —
    that's the historical behavior for setups with just client1 + client2. With
    strict=True (used wherever a caller explicitly named a machine, e.g. the
    terminal) an unmatched key returns None instead of silently guessing —
    connecting to the wrong machine because of a typo is worse than erroring."""
    if not machine_key or machine_key == 'client1':
        return None
    m = next((x for x in MACHINES if x['host'] != CLIENT1_HOST and
              (x.get('id') == machine_key or x.get('user') == machine_key or
               (x.get('name') or '').lower() == machine_key.lower())), None)
    if m or strict:
        return m
    return next((x for x in MACHINES if x['host'] != CLIENT1_HOST), None)

def _get_client2(machine_key='client2'):
    m = _resolve_machine(machine_key)
    return (m['host'], m.get('user', CLIENT1_USER)) if m else (None, None)

TERMINAL_MACHINES = {
    'client1':   {'host': CLIENT1_HOST,    'user': CLIENT1_USER,   'label': 'Client1', 'key': SSH_KEY},
    'client2':    {'host': None,          'user': None,         'label': 'Client2',  'key': SSH_KEY},
    'centos': {'host': CENTOS_HOST,   'user': CENTOS_USER,  'label': 'CentOS',   'key': CENTOS_SSH_KEY},
}

# ── Cron track cache (avoids SSH on every status poll) ────────────────────────
_cron_track_cache: dict = {}  # machine_key → (track_name_or_None, unix_timestamp)
_CRON_TTL = 5   # seconds (short so track switches appear quickly)

# ── Play-request generation counter (per machine) ─────────────────────────────
# A track click kicks off a background thread that may spend 5-30s SFTP-ing the
# file to the campus before it ever calls loadfile. If the user clicks STOP (or
# a different track) while that upload is still running, the old thread would
# otherwise finish later and call loadfile anyway — playback "coming back from
# the dead" seconds after STOP was pressed, which is exactly what looks like
# "stop doesn't work". Every play/stop bumps this counter for its machine; a
# background thread checks its own captured generation against the current one
# right before actually issuing loadfile, and gives up quietly if it's stale.
_play_gen: dict = {}
_play_gen_lock = threading.Lock()

def _bump_play_gen(machine_id):
    with _play_gen_lock:
        _play_gen[machine_id] = _play_gen.get(machine_id, 0) + 1
        return _play_gen[machine_id]

def _current_play_gen(machine_id):
    with _play_gen_lock:
        return _play_gen.get(machine_id, 0)

# Per-campus "what actually went wrong" — a real, human-readable reason,
# not just a silent failure. Set whenever a play/stop attempt on a machine
# fails, cleared the moment that machine succeeds again. Surfaced through
# /api/status so the UI can show the real problem instead of just quietly
# not working.
_last_error: dict = {}
_last_error_lock = threading.Lock()

def _set_last_error(machine_id, msg):
    with _last_error_lock:
        _last_error[machine_id] = {'msg': msg, 'ts': time.time()}

def _clear_last_error(machine_id):
    with _last_error_lock:
        _last_error.pop(machine_id, None)

def _get_last_error(machine_id, max_age=300):
    with _last_error_lock:
        e = _last_error.get(machine_id)
    if not e or (time.time() - e['ts']) > max_age:
        return None
    return e['msg']

def _humanize_ssh_error(e):
    if isinstance(e, paramiko.ssh_exception.AuthenticationException):
        return 'Отказ доступа по SSH-ключу — доступ к кампусу настроен неверно'
    if isinstance(e, (paramiko.ssh_exception.NoValidConnectionsError, socket.timeout, ConnectionRefusedError, OSError)):
        return 'Кампус не отвечает по сети (недоступен)'
    if isinstance(e, paramiko.ssh_exception.SSHException):
        return f'Ошибка SSH-соединения с кампусом: {e}'
    return f'Техническая ошибка: {e}'

# ── Brute-force login protection ──────────────────────────────────────────────
_login_attempts: dict = {}   # IP → {'count': int, 'lockout_until': float}
_MAX_ATTEMPTS  = 5
_LOCKOUT_SECS  = 900         # 15 minutes

# ── Telegram notifications ─────────────────────────
import urllib.request as _ur
import urllib.parse   as _up

def _tg_load_token():
    """Try env var first, then bot config.env file."""
    tok = os.environ.get('BOT_TOKEN', '').strip()
    if tok:
        return tok
    for path in ('/bot_config.env', '/etc/bot_config.env'):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('BOT_TOKEN='):
                        return line.split('=', 1)[1].strip()
        except Exception:
            pass
    return ''

def _tg_load_chats():
    """Return list of chat_id strings to notify."""
    # 1. DB-stored custom list (admin can override)
    try:
        with get_db() as c:
            row = c.execute("SELECT value FROM settings WHERE key='tg_chat_ids'").fetchone()
            if row and row['value'].strip():
                return [x.strip() for x in row['value'].split(',') if x.strip()]
    except Exception:
        pass
    # 2. Env var TG_LOG_GROUPS
    env_ids = os.environ.get('TG_LOG_GROUPS', '').strip()
    if env_ids:
        return [x.strip() for x in env_ids.split(',') if x.strip()]
    # 3. Bot config.env — check multiple known keys
    for path in ('/bot_config.env', '/etc/bot_config.env'):
        try:
            collected = {}
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    for key in ('LOG_GROUP_ID', 'LOG_GROUP_IDS', 'ALLOWED_CHAT_ID'):
                        if line.startswith(key + '='):
                            val = line.split('=', 1)[1].strip()
                            if val:
                                collected[key] = val
            # Prefer LOG_GROUP_ID/IDS, fall back to ALLOWED_CHAT_ID
            for key in ('LOG_GROUP_IDS', 'LOG_GROUP_ID', 'ALLOWED_CHAT_ID'):
                if key in collected:
                    return [x.strip() for x in collected[key].split(',') if x.strip()]
        except Exception:
            pass
    return []

def tg_notify(text, event_type='misc'):
    """Send Telegram notification in background thread."""
    def _send():
        try:
            with get_db() as c:
                key = f'tg_notify_{event_type}'
                row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                if row and row['value'] == '0':
                    return
        except Exception:
            pass
        token  = _tg_load_token()
        chats  = _tg_load_chats()
        if not token or not chats:
            return
        for chat_id in chats:
            try:
                data = _up.urlencode({
                    'chat_id':    chat_id,
                    'text':       text,
                    'parse_mode': 'HTML',
                }).encode()
                req = _ur.Request(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    data=data, method='POST'
                )
                req.add_header('Content-Type', 'application/x-www-form-urlencoded')
                _ur.urlopen(req, timeout=8)
            except Exception:
                pass
    threading.Thread(target=_send, daemon=True).start()

def email_notify(subject, body):
    """Send email notification in background thread. Uses SMTP env vars."""
    def _send():
        import smtplib
        from email.mime.text import MIMEText
        host  = os.environ.get('NOTIFY_SMTP_HOST', 'smtp.gmail.com')
        port  = int(os.environ.get('NOTIFY_SMTP_PORT', '587'))
        user  = os.environ.get('NOTIFY_SMTP_USER', '')
        pw    = os.environ.get('NOTIFY_SMTP_PASS', '')
        to    = os.environ.get('NOTIFY_EMAIL_TO', '')
        if not (user and pw and to):
            return
        try:
            msg = MIMEText(body, 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From']    = user
            msg['To']      = to
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls()
                s.login(user, pw)
                s.sendmail(user, [a.strip() for a in to.split(',')], msg.as_string())
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()

def notify(tg_text, subject=None, body=None, event_type='misc'):
    """Send to both Telegram and email (if subject/body given)."""
    tg_notify(tg_text, event_type=event_type)
    if subject and body:
        email_notify(subject, body)

def _tg_fmt_time():
    return datetime.now().strftime('%H:%M  %d.%m.%Y')

# ── Database ──────────────────────────────────────
def get_db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT DEFAULT "viewer",
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS play_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT NOT NULL,
            track_name TEXT NOT NULL,
            played_at  TEXT NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS online_sessions (
            username  TEXT PRIMARY KEY,
            last_seen TEXT NOT NULL,
            page      TEXT DEFAULT 'dashboard'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user TEXT NOT NULL,
            content   TEXT NOT NULL,
            sent_at   TEXT NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS activity_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT NOT NULL,
            action     TEXT NOT NULL,
            machine    TEXT NOT NULL DEFAULT "client1",
            detail     TEXT,
            happened_at TEXT NOT NULL
        )''')
        # Safe migrations — ALTER TABLE is idempotent via try/except
        for col_sql in [
            'ALTER TABLE users ADD COLUMN can_himn INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE users ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE users ADD COLUMN force_logout INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE users ADD COLUMN first_name TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN last_name  TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN position   TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN campus     TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN phone      TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN email      TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN birth_year TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN avatar     TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE messages ADD COLUMN to_user TEXT DEFAULT NULL',
            'ALTER TABLE messages ADD COLUMN voice_file TEXT DEFAULT NULL',
            'ALTER TABLE users ADD COLUMN ui_skin   TEXT NOT NULL DEFAULT "classic"',
            'ALTER TABLE users ADD COLUMN ui_accent TEXT NOT NULL DEFAULT "amber"',
            'ALTER TABLE activity_log ADD COLUMN ip TEXT',
            'ALTER TABLE activity_log ADD COLUMN user_agent TEXT',
            'ALTER TABLE users ADD COLUMN panel_color TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN ui_variant TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE users ADD COLUMN ui_palette TEXT NOT NULL DEFAULT ""',
        ]:
            try:
                c.execute(col_sql)
            except Exception:
                pass
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ""
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS announcements (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            author     TEXT NOT NULL,
            title      TEXT NOT NULL,
            content    TEXT NOT NULL,
            priority   TEXT NOT NULL DEFAULT "normal",
            pin_top    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        # Default settings
        for k, v in [
            ('tg_notify_himn',   '1'),
            ('tg_notify_upload', '1'),
            ('tg_notify_users',  '1'),
            ('tg_notify_play',   '0'),
            ('tg_notify_login',  '1'),
            ('tg_notify_backup', '1'),
            ('tg_chat_ids',      ''),
            ('silence_mode',     '0'),
        ]:
            c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (k, v))
        if not c.execute('SELECT 1 FROM users WHERE username="admin"').fetchone():
            c.execute('INSERT INTO users (username,password_hash,role) VALUES (?,?,?)',
                ('admin', generate_password_hash('admin123'), 'admin'))
        c.execute('''CREATE TABLE IF NOT EXISTS thin_clients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            host        TEXT NOT NULL,
            name        TEXT NOT NULL,
            mac         TEXT NOT NULL DEFAULT "",
            user        TEXT NOT NULL DEFAULT "client1",
            cockpit_url TEXT NOT NULL DEFAULT "",
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        for col_sql in [
            'ALTER TABLE thin_clients ADD COLUMN is_audio_client INTEGER NOT NULL DEFAULT 1',
            'ALTER TABLE thin_clients ADD COLUMN music_path TEXT NOT NULL DEFAULT ""',
        ]:
            try:
                c.execute(col_sql)
            except Exception:
                pass
        c.execute('''CREATE TABLE IF NOT EXISTS bug_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT DEFAULT "anonymous",
            message     TEXT NOT NULL,
            category    TEXT DEFAULT "bug",
            status      TEXT DEFAULT "new",
            campus      TEXT DEFAULT "",
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS favorites (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL,
            folder      TEXT NOT NULL DEFAULT "",
            name        TEXT NOT NULL,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(username, folder, name)
        )''')
    reload_machines()
    sync_prometheus_targets()
    _start_audio_poll_thread()

def log_action(username, action, machine='client1', detail=None):
    ip = None
    ua = None
    try:
        from flask import has_request_context
        if has_request_context():
            ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            ua = request.headers.get('User-Agent', '')[:200]
    except Exception:
        pass
    try:
        with get_db() as c:
            c.execute(
                'INSERT INTO activity_log (username,action,machine,detail,happened_at,ip,user_agent) VALUES (?,?,?,?,?,?,?)',
                (username, action, machine, detail, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ip, ua)
            )
    except Exception:
        pass  # never crash main flow

# ── Auth ──────────────────────────────────────────
class User(UserMixin):
    def __init__(self, row):
        def _g(k, d=''):
            try: return row[k] or d
            except: return d
        self.id         = row['id']
        self.username   = row['username']
        self.role       = row['role']
        self.first_name = _g('first_name')
        self.last_name  = _g('last_name')
        self.position   = _g('position')
        self.campus     = _g('campus')
        self.phone      = _g('phone')
        self.email      = _g('email')
        self.birth_year = _g('birth_year')
        self.avatar     = _g('avatar')

    @property
    def display_name(self):
        n = f'{self.first_name} {self.last_name}'.strip()
        return n if n else self.username

@login_manager.user_loader
def load_user(uid):
    with get_db() as c:
        row = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    return User(row) if row else None

def admin_only(f):
    @wraps(f)
    def wrap(*a, **kw):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return redirect(url_for('dashboard'))
        return f(*a, **kw)
    return wrap

# ── Права (привилегии) ────────────────────────────────────────────────────────
# Каталог привилегий по категориям. Что разрешено каждой роли, хранится в таблице
# role_perms и правится админом галочками на странице «Роли и права» (/admin/roles).
# Значения по умолчанию (DEFAULT_ROLE_PERMS) повторяют прежнее поведение системы,
# поэтому пока админ ничего не трогает — доступ у всех ролей остаётся как раньше.
# Роль admin всегда имеет всё; users_manage и roles_manage закреплены за admin.
PERM_CATALOG = [
    ('player', 'Плеер и звук', 'bi-play-circle', [
        ('play',   'Включать треки и плейлисты',   'Запуск треков, «Играть всё», зацикливание'),
        ('stop',   'Пауза, стоп и перемотка',       'Пауза, остановка на кампусе и на всех, перемотка'),
        ('nav',    'Следующий / предыдущий трек',   'Переключение треков в плейлисте'),
        ('volume', 'Громкость и эквалайзер',        'Громкость кампусов, «Все → 150», эквалайзер'),
        ('mute',   'Отключение звука (тишина)',     'Кнопка «Тишина» на активном кампусе'),
    ]),
    ('special', 'Эфир на весь кампус', 'bi-broadcast-pin', [
        ('himn',           'Гимн',                             'Запуск государственного гимна'),
        ('minuta',         'Минута тишины',                    'Запуск минуты молчания вне расписания'),
        ('alarm',          'Сигнал тревоги',                   'Запуск тревоги и выбор звука сирены'),
        ('special_events', 'Особые даты',                      'Zəfər Günü и National Music Day'),
        ('perem_trigger',  'Быстрый запуск перемены',          'Запуск любой перемены вне расписания'),
        ('special_volume', 'Громкость спецсигналов',           'Уровень громкости гимна, тревоги и других спецсигналов'),
        ('mic',            'Голосовые объявления',             'Микрофон и голос в эфир на кампус'),
    ]),
    ('automation', 'Автоматика и расписание', 'bi-alarm', [
        ('cron_pause',      'Пауза автозвонков (крон)',        'Остановить и снова включить звонки по расписанию'),
        ('schedule_toggle', 'Утро / Перемены: вкл и выкл',     'Массовое включение и отключение групп «Утро» и «Перемены»'),
        ('perem_edit',      'Время перемен по кампусам',       'Правка времени и громкости перемен для кампуса'),
        ('schedule_edit',   'Редактор расписания',             'Полная правка расписания автовоспроизведения'),
        ('cron_view',       'Страница «Крон» и логи запусков', 'Просмотр расписания на машинах и логов cron'),
    ]),
    ('library', 'Музыкальная библиотека', 'bi-collection-play', [
        ('upload',         'Загрузка треков',                  'Добавление новых файлов в библиотеку'),
        ('download',       'Скачивание треков',                'Скачивание музыкальных файлов'),
        ('library_sync',   'Синхронизация библиотек',          'Сверка и синхронизация треков между кампусами'),
        ('tracks_edit',    'Переименование и перенос треков',  'Смена имени файла и перенос между папками'),
        ('tracks_delete',  'Удаление треков',                  'Удаление файлов из библиотеки'),
        ('folders_manage', 'Управление папками',               'Создание, переименование, копирование и удаление папок'),
    ]),
    ('monitoring', 'Мониторинг и сервис', 'bi-activity', [
        ('monitor_view',    'Мониторинг серверов',             'Загрузка CPU, памяти, дисков и служб'),
        ('timesync',        'Синхронизация времени',           'Синхронизация часов кампусов с сервером'),
        ('cheatsheet',      'Шпаргалка команд',                'Справочник команд Windows, Linux, Cisco'),
        ('terminal',        'SSH-терминал',                    'Выполнение команд на машинах через терминал'),
        ('machines_manage', 'Машины: добавить, изменить, удалить', 'Управление списком кампусов и устройств'),
        ('service_restart', 'Перезапуск служб',                'Перезапуск служб на серверах и кампусах'),
        ('activity_log',    'Журнал активности',               'Кто и что делал в системе'),
        ('backups',         'Резервные копии',                 'Просмотр и скачивание бэкапов'),
        ('bug_reports',     'Отчёты о проблемах',              'Просмотр отчётов и смена их статуса'),
    ]),
    ('content', 'Контент и оформление', 'bi-palette', [
        ('announcements_manage', 'Доска объявлений',           'Создание, закрепление и удаление объявлений'),
        ('appearance_manage',    'Обои, эмодзи и тема',        'Обои, эмодзи и тема по умолчанию для всех'),
        ('login_style',          'Стартовая страница входа',   'Выбор внешнего вида страницы входа для всех (Настройки → «Стартовая страница входа»)'),
        ('ui_default',           'Дизайн плеера по умолчанию', 'Выбор основного дизайна плеера для всех, кто не выбрал свой (Настройки → «Дизайн интерфейса»)'),
        ('telegram_settings',    'Уведомления в Telegram',     'Настройка оповещений в Telegram'),
    ]),
    ('admin', 'Администрирование', 'bi-shield-lock', [
        ('users_manage',  'Пользователи',                      'Создание, блокировка, роли и пароли пользователей'),
        ('roles_manage',  'Роли и привилегии',                 'Эта страница: назначение привилегий ролям'),
        ('silence_mode',  'Режим тишины',                      'Отключение воспроизведения для всех пользователей'),
        ('security_view', 'Страница «Безопасность»',           'Описание защиты системы'),
    ]),
]
# опасные привилегии подсвечиваются на странице; закреплённые нельзя выдать никому кроме admin
PERM_DANGER = {'terminal', 'machines_manage', 'service_restart', 'silence_mode', 'tracks_delete', 'folders_manage', 'schedule_edit', 'telegram_settings'}
PERM_LOCKED = {'users_manage', 'roles_manage'}
PERM_INFO = {}          # ключ → {cat, label, desc}
for _cat, _cl, _ic, _items in PERM_CATALOG:
    for _k, _l, _d in _items:
        PERM_INFO[_k] = {'cat': _cat, 'label': _l, 'desc': _d}

# роли, которые показываются в матрице (admin — всегда всё, закреплён)
ROLE_ORDER = ['guest', 'user', 'staff', 'helpdesk', 'eventmanager', 'admin']
ROLES_ALL = ROLE_ORDER + ['viewer']       # viewer — устаревшая роль, держит права как user без загрузки

_P_MUSIC   = {'play', 'stop', 'nav', 'volume', 'mute'}
_P_SPECIAL = {'himn', 'minuta', 'alarm', 'special_events', 'perem_trigger', 'special_volume'}
_P_DAILY   = _P_MUSIC | _P_SPECIAL | {'mic', 'schedule_toggle', 'perem_edit', 'upload', 'download'}
DEFAULT_ROLE_PERMS = {
    'guest':        {'download'},
    'user':         _P_MUSIC | {'upload', 'download'},
    'viewer':       _P_MUSIC | {'download'},
    'staff':        _P_DAILY | {'library_sync', 'monitor_view', 'timesync', 'cheatsheet', 'terminal'},
    'helpdesk':     _P_DAILY | {'cron_pause'},
    'eventmanager': _P_DAILY,
    'admin':        set(PERM_INFO),
}
# что раньше выдавалось отдельному пользователю флагом can_himn («право на гимн») — оставляем
SPECIAL_USER_PERMS = _P_SPECIAL | {'schedule_toggle', 'perem_edit'}
# старые имена привилегий, которые ещё встречаются в коде и шаблонах
_PERM_ALIASES = {'next': 'nav', 'prev': 'nav', 'vol': 'volume', 'cron': 'cron_pause', 'admin': 'users_manage'}

ROLE_LABELS = {
    'guest':    ('Гость',    'Только просмотр — кнопки управления недоступны'),
    'user':     ('Польз.',   'Музыка: включать, останавливать, регулировать громкость'),
    'staff':    ('Персонал', 'Музыка + гимн: все функции кроме управления пользователями'),
    'helpdesk': ('HelpDesk', 'Всё, что связано с музыкой: играть/стоп, гимн, воис, загрузка треков, крон — без удаления и без управления пользователями'),
    'eventmanager': ('Event Manager', 'Играть музыку, спецвозможности (гимн/мик/тревога и т.д.), загрузка треков, голосовые объявления — без крона, без удаления, без пользователей'),
    'admin':    ('Админ',    'Полный доступ: управление пользователями и всеми функциями'),
}

def ensure_role_perms():
    """Создаёт таблицу role_perms и добавляет недостающие строки со значениями по умолчанию.
    Существующие галочки (то, что настроил админ) не перезаписываются."""
    with get_db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS role_perms (
            role    TEXT NOT NULL,
            perm    TEXT NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (role, perm)
        )''')
        for role in ROLES_ALL:
            have = DEFAULT_ROLE_PERMS.get(role, set())
            for perm in PERM_INFO:
                c.execute('INSERT OR IGNORE INTO role_perms (role, perm, allowed) VALUES (?,?,?)',
                          (role, perm, 1 if perm in have else 0))
    _rp_cache['ts'] = 0.0

_rp_cache = {'ts': 0.0, 'data': None}

def _role_perm_map():
    """{role: {perm, …}} из БД; кэш 5 секунд (сбрасывается при изменении галочек)."""
    now = time.time()
    if _rp_cache['data'] is not None and now - _rp_cache['ts'] < 5:
        return _rp_cache['data']
    data = {}
    try:
        with get_db() as c:
            for r in c.execute('SELECT role, perm, allowed FROM role_perms'):
                s = data.setdefault(r['role'], set())
                if r['allowed']:
                    s.add(r['perm'])
    except Exception:
        data = {}
    if not data:                       # таблицы ещё нет / пусто — работаем по умолчаниям
        data = {r: set(v) for r, v in DEFAULT_ROLE_PERMS.items()}
    _rp_cache['data'] = data
    _rp_cache['ts'] = now
    return data

def role_has(role, perm):
    """Есть ли привилегия у роли (без учёта режима тишины и личных выдач)."""
    perm = _PERM_ALIASES.get(perm, perm)
    if perm not in PERM_INFO:
        return False
    if role == 'admin':
        return True
    if perm in PERM_LOCKED:
        return False
    return perm in _role_perm_map().get(role, set())

def _silence_active():
    try:
        with get_db() as c:
            row = c.execute("SELECT value FROM settings WHERE key='silence_mode'").fetchone()
            return row and row['value'] == '1'
    except Exception:
        return False

def has_perm(perm):
    perm = _PERM_ALIASES.get(perm, perm)
    role = getattr(current_user, 'role', 'guest')
    if perm == 'play' and role != 'admin' and _silence_active():
        return False
    if role_has(role, perm):
        return True
    if perm in SPECIAL_USER_PERMS and getattr(current_user, 'is_authenticated', False):
        # личная выдача админом («право на гимн») по-прежнему открывает спецсигналы
        try:
            with get_db() as c:
                row = c.execute('SELECT can_himn FROM users WHERE id=?', (current_user.id,)).fetchone()
            return bool(row and row['can_himn'])
        except Exception:
            return False
    return False

def has_himn_perm():
    """Совместимость со старым кодом и шаблонами: право на гимн."""
    return has_perm('himn')

def perm_required(*perms):
    """Как @admin_only, но по привилегии: пускает, если есть хотя бы одна из перечисленных."""
    def deco(f):
        @wraps(f)
        def wrap(*a, **kw):
            if not current_user.is_authenticated or not any(has_perm(p) for p in perms):
                return redirect(url_for('dashboard'))
            return f(*a, **kw)
        return wrap
    return deco

def user_perms():
    """Словарь флагов текущего пользователя для шаблонов: новые ключи = названия привилегий,
    плюс старые (vol, next, prev, himn, admin, cron) и role."""
    d = {k: has_perm(k) for k in PERM_INFO}
    d.update({
        'vol':   d['volume'],
        'next':  d['nav'],
        'prev':  d['nav'],
        'admin': d['users_manage'],
        'cron':  d['cron_pause'],
        'role':  getattr(current_user, 'role', 'guest'),
    })
    return d

# ── SSH / MPV ─────────────────────────────────────
def ssh_run_on(host, user, cmd, key=None, timeout=15, connect_timeout=10):
    if key is None:
        key = SSH_KEY
    s = None
    try:
        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # Some campuses (Ağ-Şəhər confirmed) sit behind a genuinely slow/
        # lossy link — measured 3-7s for even a trivial `echo` round trip.
        # 5s here was cutting it too close, occasionally timing out a
        # connection that would have succeeded with a couple more seconds.
        # connect_timeout is overridable — the status poll (every 5s, one
        # attempt per campus in parallel) uses a much shorter one: waiting
        # 10s to learn an offline campus is offline, every 5s, was pushing
        # the WHOLE batched /api/status-all past the browser's own fetch
        # timeout, which failed the request for every campus at once —
        # including the ones that were actually fine.
        s.connect(host, username=user, key_filename=key, timeout=connect_timeout)
        _, out, _ = s.exec_command(cmd, timeout=timeout)
        result = out.read().decode().strip()
        return {'ok': True, 'data': result}
    except Exception as e:
        return {'ok': False, 'error': str(e) or repr(e)}
    finally:
        if s:
            try: s.close()
            except Exception: pass

def ssh_run(cmd):
    return ssh_run_on(CLIENT1_HOST, CLIENT1_USER, cmd)

def _last_cron_track(host, user, log_path, machine_key):
    """Last cron-played track + its timestamp from action.log; cached _CRON_TTL s."""
    now = time.time()
    cached = _cron_track_cache.get(machine_key)
    if cached and now - cached[2] < _CRON_TTL:
        return cached[0], cached[1]          # (track, datetime)
    r = ssh_run_on(host, user,
        f"awk '/Cron Media/{{line=$0}} END{{print line}}' {log_path} 2>/dev/null || true")
    track, dt = None, None
    if r.get('ok') and r.get('data', '').strip():
        line = r['data'].strip()
        m_t = _re.search(r'\| (\S+)$', line)
        if m_t:
            track = m_t.group(1)
        m_d = _re.search(r'\[(\d{2}:\d{2}:\d{2}) (\d{2}\.\d{2})\]', line)
        if m_d:
            try:
                yr = datetime.now().year
                dt = datetime.strptime(f"{m_d.group(2)}.{yr} {m_d.group(1)}", "%d.%m.%Y %H:%M:%S")
            except Exception:
                pass
    _cron_track_cache[machine_key] = (track, dt, now)
    return track, dt

def mpv_cmd(payload):
    escaped = json.dumps(payload).replace('"', '\\"')
    return ssh_run(f'echo "{escaped}" | socat - {MPV_SOCK} 2>/dev/null')

def mpv_cmd_on(host, user, payload):
    escaped = json.dumps(payload).replace('"', '\\"')
    return ssh_run_on(host, user, f'echo "{escaped}" | socat - {MPV_SOCK} 2>/dev/null')

def mpv_get(prop):
    r = mpv_cmd({'command': ['get_property', prop]})
    if r['ok']:
        try: return json.loads(r['data']).get('data')
        except: pass
    return None

def mpv_get_on(host, user, prop):
    r = mpv_cmd_on(host, user, {'command': ['get_property', prop]})
    if r['ok']:
        try: return json.loads(r['data']).get('data')
        except: pass
    return None

def mpv_set(prop, val):
    return mpv_cmd({'command': ['set_property', prop, val]})

def _mpv_cmd_to_campus(campus, cmd):
    """Send an mpv IPC command (e.g. the EQ filter) to 'client1', one specific
    campus key, or every player-visible campus ('both' — kept as the
    historical name for 'all', not just the original two)."""
    if campus in ('client1', 'both'):
        mpv_cmd(cmd)
    if campus == 'both':
        for m in music_machines():
            if m['host'] != CLIENT1_HOST:
                mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cmd)
    elif campus != 'client1':
        m = _resolve_machine(campus, strict=True)
        if m:
            mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cmd)

def mpv_set_all(prop, val):
    """Set mpv property on client1 (waited on, response depends on it) and all
    additional machines (fired in background threads — an offline campus
    otherwise stalls the whole request behind an SSH connect timeout, which
    is exactly why the volume knob felt frozen for several seconds whenever
    any one campus was down)."""
    cmd = {'command': ['set_property', prop, val]}
    r = mpv_cmd(cmd)
    for m in MACHINES:
        if m['host'] != CLIENT1_HOST:
            threading.Thread(
                target=mpv_cmd_on, args=(m['host'], m.get('user', CLIENT1_USER), cmd), daemon=True
            ).start()
    return r

# ── Wake-on-LAN / host ping ──────────────────────
def send_wol(mac_address, host=None):
    mac_clean = mac_address.replace(':', '').replace('-', '').replace('.', '').upper()
    if len(mac_clean) != 12:
        return False, 'Неверный MAC-адрес'
    mac_bytes = bytes.fromhex(mac_clean)
    magic = b'\xff' * 6 + mac_bytes * 16
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(magic, ('<broadcast>', 9))
            if host:
                s.sendto(magic, (host, 9))
        return True, 'ok'
    except Exception as e:
        return False, str(e)

def host_online(host, port=22, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

@app.route('/api/machines')
@login_required
def api_machines():
    result = [None] * len(MACHINES)
    def _check(i, m):
        result[i] = {
            'id':     m['id'],
            'name':   m['name'],
            'host':   m['host'],
            'has_mac': bool(m['mac']),
            'is_audio_client': bool(m.get('is_audio_client', True)),
            'online': host_online(m['host']),
        }
    # host_online() blocks up to 2s per machine — run them in parallel so the
    # page doesn't stall for N*2s once there are more than 2-3 machines
    threads = [threading.Thread(target=_check, args=(i, m)) for i, m in enumerate(MACHINES)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=5)
    return jsonify({'ok': True, 'machines': [r for r in result if r]})

@app.route('/api/wol/<mid>', methods=['POST'])
@login_required
def api_wol(mid):
    m = next((x for x in MACHINES if x['id'] == mid), None)
    if not m:
        return jsonify({'ok': False, 'error': 'Машина не найдена'})
    if not m['mac']:
        return jsonify({'ok': False, 'error': 'MAC-адрес не настроен. Добавьте CLIENT1_MAC в .env'})
    ok, msg = send_wol(m['mac'], m['host'])
    return jsonify({'ok': ok, 'error': msg if not ok else None})

# ── Thin clients CRUD (admin only) ────────────────
@app.route('/api/machines/list')
@login_required
@perm_required('machines_manage')
def api_machines_list():
    with get_db() as c:
        rows = c.execute('SELECT * FROM thin_clients ORDER BY id').fetchall()
    return jsonify({'ok': True, 'machines': [dict(r) for r in rows]})

@app.route('/api/machines/add', methods=['POST'])
@login_required
@perm_required('machines_manage')
def api_machines_add():
    data = request.get_json() or {}
    host = data.get('host', '').strip()
    name = data.get('name', '').strip()
    mac  = data.get('mac',  '').strip()
    user = data.get('user', '').strip()
    cockpit = data.get('cockpit_url', f'http://{host}:1991').strip()
    is_audio = bool(data.get('is_audio_client', True))
    music_path = data.get('music_path', '').strip() or _default_music_path(user, host)
    if not host or not name:
        return jsonify({'ok': False, 'error': 'IP-адрес и имя обязательны'})
    # "client1" is the reserved slug for the real Client1 host everywhere in
    # the app (URLs, campus switcher, _resolve_machine) — a thin_client with
    # a different host but user="client1" would silently collide with it and
    # become an unreachable duplicate in the player (see _campus_key).
    if user == 'client1' and host != CLIENT1_HOST:
        return jsonify({'ok': False, 'error': '"client1" зарезервирован за настоящим Client1 — укажите другой SSH-логин'})
    with get_db() as c:
        c.execute('''INSERT INTO thin_clients (host,name,mac,user,cockpit_url,is_audio_client,music_path)
                     VALUES (?,?,?,?,?,?,?)''',
                  (host, name, mac, user, cockpit, int(is_audio), music_path))
    reload_machines()
    sync_prometheus_targets()
    log_action(current_user.username, 'machine_add', 'webui', f'{name} ({host})')
    return jsonify({'ok': True})

@app.route('/api/machines/edit/<int:db_id>', methods=['POST'])
@login_required
@perm_required('machines_manage')
def api_machines_edit(db_id):
    data = request.get_json() or {}
    host = data.get('host', '').strip()
    name = data.get('name', '').strip()
    mac  = data.get('mac',  '').strip()
    user = data.get('user', '').strip()
    cockpit = data.get('cockpit_url', '').strip()
    is_audio = bool(data.get('is_audio_client', True))
    music_path = data.get('music_path', '').strip() or _default_music_path(user, host)
    if not host or not name:
        return jsonify({'ok': False, 'error': 'IP-адрес и имя обязательны'})
    if user == 'client1' and host != CLIENT1_HOST:
        return jsonify({'ok': False, 'error': '"client1" зарезервирован за настоящим Client1 — укажите другой SSH-логин'})
    with get_db() as c:
        c.execute('''UPDATE thin_clients SET host=?,name=?,mac=?,user=?,cockpit_url=?,
                     is_audio_client=?,music_path=? WHERE id=?''',
                  (host, name, mac, user, cockpit, int(is_audio), music_path, db_id))
    reload_machines()
    sync_prometheus_targets()
    log_action(current_user.username, 'machine_edit', 'webui', f'{name} ({host})')
    return jsonify({'ok': True})

@app.route('/api/machines/delete/<int:db_id>', methods=['POST'])
@login_required
@perm_required('machines_manage')
def api_machines_delete(db_id):
    with get_db() as c:
        row = c.execute('SELECT name,host FROM thin_clients WHERE id=?', (db_id,)).fetchone()
        c.execute('DELETE FROM thin_clients WHERE id=?', (db_id,))
    reload_machines()
    if row:
        log_action(current_user.username, 'machine_delete', 'webui', f'{row["name"]} ({row["host"]})')
    return jsonify({'ok': True})

# ── Роли и привилегии: страница админа ─────────────────────────────────────
app.jinja_env.globals['can'] = lambda perm: bool(current_user.is_authenticated and has_perm(perm))

def _roles_payload():
    """Данные для страницы «Роли и права»: роли (с числом пользователей и выданных привилегий) и матрица."""
    with get_db() as c:
        cnt = {r['role']: r['n'] for r in c.execute('SELECT role, COUNT(*) AS n FROM users GROUP BY role')}
    roles = []
    for r in ROLE_ORDER:
        label, desc = ROLE_LABELS.get(r, (r, ''))
        roles.append({'key': r, 'label': label, 'desc': desc, 'users': cnt.get(r, 0),
                      'granted': sum(1 for p in PERM_INFO if role_has(r, p)), 'total': len(PERM_INFO),
                      'locked': r == 'admin'})
    cats = []
    for ck, cl, ci, items in PERM_CATALOG:
        cats.append({'key': ck, 'label': cl, 'icon': ci, 'perms': [{
            'key': k, 'label': l, 'desc': d, 'danger': k in PERM_DANGER, 'locked': k in PERM_LOCKED,
            'have':     {r: role_has(r, k) for r in ROLE_ORDER},
            'defaults': {r: (r == 'admin') or (k in DEFAULT_ROLE_PERMS.get(r, set()) and k not in PERM_LOCKED) for r in ROLE_ORDER},
        } for k, l, d in items]})
    return {'roles': roles, 'categories': cats}

@app.route('/admin/roles')
@login_required
@perm_required('roles_manage')
def admin_roles():
    return render_template('roles.html', data=_roles_payload())

@app.route('/api/roles/matrix')
@login_required
@perm_required('roles_manage')
def api_roles_matrix():
    return jsonify({'ok': True, **_roles_payload()})

def _role_perm_check(role, perm, allowed):
    if role not in ROLE_ORDER or role == 'admin':
        return 'Роль admin всегда имеет все права — её менять нельзя' if role == 'admin' else 'Неизвестная роль'
    if perm not in PERM_INFO:
        return 'Неизвестная привилегия'
    if allowed and perm in PERM_LOCKED:
        return 'Эту привилегию нельзя выдавать никому, кроме админа'
    return None

def _set_role_perms(role, perms, allowed):
    with get_db() as c:
        for perm in perms:
            c.execute('INSERT OR REPLACE INTO role_perms (role, perm, allowed) VALUES (?,?,?)',
                      (role, perm, 1 if allowed else 0))
    _rp_cache['ts'] = 0.0

@app.route('/api/roles/set', methods=['POST'])
@login_required
@perm_required('roles_manage')
def api_roles_set():
    d = request.get_json(silent=True) or {}
    role, perm, allowed = d.get('role'), d.get('perm'), bool(d.get('allowed'))
    err = _role_perm_check(role, perm, allowed)
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    _set_role_perms(role, [perm], allowed)
    log_action(current_user.username, 'role_perm', 'webui',
               f"{role}: {'+' if allowed else '−'}{perm} ({PERM_INFO[perm]['label']})")
    return jsonify({'ok': True, 'granted': sum(1 for p in PERM_INFO if role_has(role, p))})

@app.route('/api/roles/bulk', methods=['POST'])
@login_required
@perm_required('roles_manage')
def api_roles_bulk():
    d = request.get_json(silent=True) or {}
    role, perms, allowed = d.get('role'), d.get('perms') or [], bool(d.get('allowed'))
    perms = [p for p in perms if p in PERM_INFO and not (allowed and p in PERM_LOCKED)]
    err = _role_perm_check(role, perms[0] if perms else 'play', allowed)
    if err or not perms:
        return jsonify({'ok': False, 'error': err or 'Нет привилегий для изменения'}), 400
    _set_role_perms(role, perms, allowed)
    log_action(current_user.username, 'role_perm', 'webui', f"{role}: {'+' if allowed else '−'}{len(perms)} привилегий")
    return jsonify({'ok': True, 'granted': sum(1 for p in PERM_INFO if role_has(role, p))})

@app.route('/api/roles/reset', methods=['POST'])
@login_required
@perm_required('roles_manage')
def api_roles_reset():
    d = request.get_json(silent=True) or {}
    target = d.get('role')
    roles = ROLE_ORDER[:-1] if target == 'all' else [target]
    for role in roles:
        if role not in ROLE_ORDER or role == 'admin':
            return jsonify({'ok': False, 'error': 'Неизвестная роль'}), 400
    for role in roles:
        have = DEFAULT_ROLE_PERMS.get(role, set())
        with get_db() as c:
            for perm in PERM_INFO:
                c.execute('INSERT OR REPLACE INTO role_perms (role, perm, allowed) VALUES (?,?,?)',
                          (role, perm, 1 if (perm in have and perm not in PERM_LOCKED) else 0))
    _rp_cache['ts'] = 0.0
    log_action(current_user.username, 'role_perm', 'webui', f"сброс к умолчаниям: {', '.join(roles)}")
    return jsonify({'ok': True})

# ── Local music scanning ──────────────────────────
MUSIC_FOLDERS   = ['Общая', 'Русские', 'Зарубежные', 'Азербайджанские', 'Турецкие', 'Смешанная', 'KAMRAN']
KAMRAN_FOLDER   = 'KAMRAN'
AUDIO_EXTS      = ('.mp3', '.ogg', '.wav', '.flac', '.m4a', '.aac')

def all_music_folders():
    """MUSIC_FOLDERS (fixed order, existing content untouched) + any custom
    folders an admin created afterwards via /api/tracks/create-folder."""
    extra = []
    try:
        extra = sorted(
            d for d in os.listdir(MUSIC_DIR)
            if d not in MUSIC_FOLDERS and os.path.isdir(os.path.join(MUSIC_DIR, d))
        )
    except Exception:
        pass
    return MUSIC_FOLDERS + extra

# ── Metadata cache (built in background) ──────────
import threading as _threading
_meta_cache = {}   # path → {dur, size, fmt, kbps}
_meta_lock  = _threading.Lock()

def _get_meta(path):
    with _meta_lock:
        if path in _meta_cache:
            return _meta_cache[path]
    try:
        from mutagen import File as _MFile
        af = _MFile(path)
        dur  = round(af.info.duration) if af and af.info else None
        kbps = round(getattr(af.info, 'bitrate', 0) / 1000) if af and af.info else None
    except Exception:
        dur = kbps = None
    size = 0
    try:
        size = os.path.getsize(path)
    except Exception:
        pass
    fmt = os.path.splitext(path)[1].lstrip('.').upper()
    meta = {'dur': dur, 'size': size, 'fmt': fmt, 'kbps': kbps}
    with _meta_lock:
        _meta_cache[path] = meta
    return meta

def _warm_meta_cache():
    """Background thread: load metadata for all tracks."""
    import time as _time
    _time.sleep(3)  # let server start first
    for sub in MUSIC_FOLDERS:
        if sub == KAMRAN_FOLDER:
            continue
        d = os.path.join(MUSIC_DIR, sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(AUDIO_EXTS):
                _get_meta(os.path.join(d, f))

_threading.Thread(target=_warm_meta_cache, daemon=True).start()

def _kamran_unlocked():
    try:
        from flask import session as _s
        return _s.get('kamran_unlocked', False) or (KAMRAN_FOLDER in _s.get('unlocked_folders', []))
    except Exception:
        return False

def scan_tracks(q='', folder_filter=None):
    """Scan /music subfolders, return list of {name, path, idx, folder}."""
    q_low = q.lower() if q else ''
    tracks = []
    idx = 0
    try:
        # Collect (folder_name, dir_path) pairs to scan
        scan_dirs = []
        # Named subfolders first (fixed ones + any custom folders created later)
        for sub in all_music_folders():
            sub_path = os.path.join(MUSIC_DIR, sub)
            if not os.path.isdir(sub_path):
                continue
            if sub == KAMRAN_FOLDER and not _kamran_unlocked():
                continue
            if folder_filter and sub != folder_filter:
                continue
            scan_dirs.append((sub, sub_path))
        # Root (unclassified) files
        if not folder_filter:
            scan_dirs.append(('', MUSIC_DIR))

        for folder_name, dir_path in scan_dirs:
            files = sorted(
                f for f in os.listdir(dir_path)
                if f.lower().endswith(AUDIO_EXTS)
                and os.path.isfile(os.path.join(dir_path, f))
            )
            for name in files:
                if q_low and q_low not in name.lower():
                    continue
                idx += 1
                fpath = os.path.join(dir_path, name)
                meta = _get_meta(fpath)
                tracks.append({
                    'idx':    idx,
                    'name':   name,
                    'path':   fpath,
                    'folder': folder_name,
                    'dur':    meta.get('dur'),
                    'size':   meta.get('size', 0),
                    'fmt':    meta.get('fmt', ''),
                    'kbps':   meta.get('kbps'),
                })
    except Exception:
        pass
    return tracks

def total_tracks():
    try:
        count = sum(
            1 for f in os.listdir(MUSIC_DIR)
            if f.lower().endswith(AUDIO_EXTS)
            and os.path.isfile(os.path.join(MUSIC_DIR, f))
        )
        for sub in all_music_folders():
            sub_path = os.path.join(MUSIC_DIR, sub)
            if os.path.isdir(sub_path):
                count += sum(
                    1 for f in os.listdir(sub_path)
                    if f.lower().endswith(AUDIO_EXTS)
                    and os.path.isfile(os.path.join(sub_path, f))
                )
        return count
    except Exception:
        return 0

# ── Schedule ──────────────────────────────────────
_SCHEDULE_DEFAULT = [
    {'time':'07:45','event':'▶ Утро',       'file':'utro.mp3',      'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'07:59','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'08:00','event':'▶ Гос. гимн',  'file':'himn.mp3',      'vol':160,'days':'Только ПН','dow':[0],'play':True,'special':True},
    {'time':'08:03','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Только ПН','dow':[0],'play':False,'special':True},
    {'time':'08:40','event':'▶ 1 перемена', 'file':'1peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'08:45','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'09:25','event':'▶ 2 перемена', 'file':'2peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'09:35','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'10:15','event':'▶ 3 перемена', 'file':'3peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'10:20','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'11:00','event':'▶ 4 перемена', 'file':'4peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'11:05','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'11:45','event':'▶ 5 перемена', 'file':'5peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'11:55','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'12:35','event':'▶ 6 перемена', 'file':'6peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'12:40','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'13:20','event':'▶ 7 перемена', 'file':'7peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'13:30','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'14:10','event':'▶ 8 перемена', 'file':'8peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'14:15','event':'⏹ Стоп',       'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
    {'time':'14:55','event':'▶ 9 перемена', 'file':'9peremena.mp3', 'vol':110,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':True},
    {'time':'15:10','event':'⏹ Финал',      'file':'—',             'vol':None,'days':'Пн–Пт','dow':[0,1,2,3,4],'play':False},
]
SCHEDULE_JSON = os.path.join(os.path.dirname(DB_PATH), 'schedule.json')
_sched_lock = threading.Lock()

# ── Quick-access perem triggers (dashboard "быстрый доступ") ────────────────
# Один список слотов на все кампусы — источник: тот же _SCHEDULE_DEFAULT,
# что рисует страницу расписания, так что кнопки быстрого доступа всегда
# совпадают с тем, что реально стоит в кроне.
PEREM_SLOTS = [e['file'][:-4] for e in _SCHEDULE_DEFAULT if e.get('play')]
PEREM_SLOT_LABELS = {e['file'][:-4]: e['event'].lstrip('▶').strip() for e in _SCHEDULE_DEFAULT if e.get('play')}
# Громкость по кампусам — совпадает с их crontab (client1: 110/160, client2/cgtk: 115/150)
_PEREM_VOL = {
    'client1': {'himn': 160, '_default': 110},
    'client2':  {'himn': 150, '_default': 115},
    'cgtk': {'himn': 150, '_default': 115},
}
def _perem_vol(campus, slot):
    d = _PEREM_VOL.get(campus, {'himn': 150, '_default': 115})
    return d.get(slot, d['_default'])

# ── Live crontab read/edit for perem quick-access panel ─────────────────────
# Каждый кампус хранит своё СОБСТВЕННОЕ время/громкость (подтверждено
# пользователем — не единое расписание на все три). Редактирование идёт
# напрямую в реальный crontab машины (не в декоративный SCHEDULE), чтобы
# изменение реально что-то меняло, а не только отображалось в UI.
_HHMM_RE = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')

def _crontab_find_slot_lines(lines, slot):
    """Индексы (start_idx, stop_idx) для строк слота в списке строк crontab."""
    marker = f'campus-cron-media-notify.sh {slot} '
    for i, line in enumerate(lines):
        if marker in line:
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith('#')):
                j += 1
            if j < len(lines) and 'campus-cron-stop-notify.sh' in lines[j]:
                return i, j
            return i, None
    return None, None

def _crontab_parse_time(line):
    parts = line.split(' ')
    return f'{int(parts[1]):02d}:{int(parts[0]):02d}'

def _crontab_parse_vol(line):
    return line.strip().split(' ')[-1]

def _crontab_replace_time(line, hh, mm):
    parts = line.split(' ')
    if len(parts) < 5:
        return line
    parts[0], parts[1] = str(mm), str(hh)
    return ' '.join(parts)

def _crontab_replace_time_and_vol(line, hh, mm, vol):
    parts = line.split(' ')
    if len(parts) < 6:
        return line
    parts[0], parts[1] = str(mm), str(hh)
    parts[-1] = str(vol)
    return ' '.join(parts)

def _crontab_toggle_group(host, user, group, enable):
    """Комментирует (выключить) или раскомментирует (включить) РЕАЛЬНЫЕ
    строки crontab для группы слотов — 'utro' или 'perem' (1..9peremena).
    Время/громкость не трогает — просто включает/выключает срабатывание.
    Использует тот же _crontab_find_slot_lines, что и обычный редактор
    расписания, поэтому работает независимо от того, был ли слот уже
    закомментирован раньше."""
    r = ssh_run_on(host, user, 'crontab -l 2>/dev/null', timeout=10)
    if not r.get('ok'):
        return r
    lines = r['data'].split('\n')
    slots = ['utro'] if group == 'utro' else [f'{i}peremena' for i in range(1, 10)]
    changed = False
    for slot in slots:
        si, ei = _crontab_find_slot_lines(lines, slot)
        if si is None:
            continue
        for idx in ([si] + ([ei] if ei is not None else [])):
            bare = lines[idx].lstrip('#')
            if enable:
                if lines[idx] != bare:
                    lines[idx] = bare
                    changed = True
            else:
                if not lines[idx].lstrip().startswith('#'):
                    lines[idx] = '#' + lines[idx]
                    changed = True
    if not changed:
        return {'ok': True, 'data': 'NOCHANGE'}
    new_content = '\n'.join(lines)
    if not new_content.endswith('\n'):
        new_content += '\n'
    return _crontab_push(host, user, new_content)

def _crontab_push(host, user, new_content):
    """Атомарно устанавливает новый crontab через heredoc (без stdin-пайпа)."""
    marker = 'CRONEOF9f3a'
    cmd = (f"cat > /tmp/.newcron_{marker} << '{marker}'\n{new_content}{marker}\n"
           f"crontab /tmp/.newcron_{marker} && rm -f /tmp/.newcron_{marker} && echo INSTALLED")
    return ssh_run_on(host, user, cmd, timeout=15)

def load_schedule():
    try:
        if os.path.exists(SCHEDULE_JSON):
            with open(SCHEDULE_JSON, encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return [dict(e) for e in _SCHEDULE_DEFAULT]

def save_schedule(sched):
    os.makedirs(os.path.dirname(SCHEDULE_JSON), exist_ok=True)
    with open(SCHEDULE_JSON, 'w', encoding='utf-8') as f:
        json.dump(sched, f, ensure_ascii=False, indent=2)

SCHEDULE = load_schedule()

# ── Routes ────────────────────────────────────────
@app.before_request
def _before():
    if current_user.is_authenticated:
        uid = current_user.id
        # Force-logout check
        try:
            with get_db() as c:
                row = c.execute('SELECT force_logout FROM users WHERE id=?', (uid,)).fetchone()
            if row and row['force_logout']:
                with get_db() as c:
                    c.execute('UPDATE users SET force_logout=0 WHERE id=?', (uid,))
                logout_user()
                # An /api/ call is background JS (heartbeat/chat-poll/status
                # poll) — a redirect there gets silently followed to the
                # login page's HTML, fetch().json() throws, and the catch
                # block swallows it, so the kicked user's already-open tab
                # just sits there looking normal until they navigate by
                # hand. A distinct 401 the frontend actually checks for
                # (see cpLoadMsgs) makes the kick visible right away.
                if request.path.startswith('/api/'):
                    return jsonify({'ok': False, 'force_logout': True}), 401
                flash('Ваша сессия завершена администратором', 'warning')
                return redirect(url_for('login'))
        except Exception:
            pass
        # Track online session
        try:
            page = request.path[:64]
            now_s = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with get_db() as c:
                c.execute(
                    'INSERT OR REPLACE INTO online_sessions(username,last_seen,page) VALUES(?,?,?)',
                    (current_user.username, now_s, page)
                )
        except Exception:
            pass

# Варианты стартовой страницы входа. 'classic' — прежняя страница с пазлом (templates/login.html), 1..19 — templates/login_alt.html.
# Выбор хранится в settings.login_style (по умолчанию «12 — Герб-круг» с печатающейся надписью); менять может только тот, у кого есть привилегия login_style.
_LOGIN_STYLES = tuple(str(i) for i in range(1, 20))
_LOGIN_STYLE_KEYS = ('classic',) + _LOGIN_STYLES
_LOGIN_STYLE_DEFAULT = '12'
LOGIN_STYLE_INFO = [
    ('classic', 'Классическая', 'Прежняя страница: логотипы собираются из пазла'),
    ('1',  'Эфир',           'Равнайзер на фоне, часы Баку, приветствие'),
    ('2',  'Пульт',          'Светодиоды сервера и Caps Lock, часы на табло'),
    ('3',  'Сцена',          'Бренд-панель с логотипами и подсказками'),
    ('4',  'Шаги',           'Сначала логин, потом пароль; помнит прошлый логин'),
    ('5',  'Центр',          'Что нового, горячие клавиши, быстрые ссылки'),
    ('6',  'Герб',           'Большой логотип, контурная надпись, лозунги'),
    ('7',  'Дуэт',           'Media и LEG по бокам, форма посередине'),
    ('8',  'Неон',           'Гигантская неоновая надпись MEDIA'),
    ('9',  'Плакат',         'Огромные слова на фоне, лозунг справа'),
    ('10', 'Витрина',        'Две карточки с логотипами, форма в одну строку'),
    ('11', 'Интро',          'Логотип с бликом, печатающаяся надпись, затем форма'),
    ('12', 'Герб-круг',      'Два вращающихся круга (Media и LEG), сборка из мозаики, печатающаяся надпись'),
    ('13', 'Прожектор',      'Логотип в луче света с отражением'),
    ('14', 'Дуэт сверху',    'Оба логотипа в ряд над формой'),
    ('15', 'Дуэт-диагональ', 'Экран разрезан по диагонали: Media и LEG'),
    ('16', 'Неон-два',       'MEDIA и SCHOOL двумя неонами, светящаяся рамка'),
    ('17', 'Неон-волна',     'Звуковые волны за гигантской надписью'),
    ('18', 'Плакат-ленты',   'Бегущие строки на фоне'),
    ('19', 'Плакат-сцена',   'Гигантские MEDIA / SCHOOL слева, форма справа'),
]

def _login_style_current():
    try:
        with get_db() as c:
            row = c.execute("SELECT value FROM settings WHERE key='login_style'").fetchone()
        if row and row['value'] in _LOGIN_STYLE_KEYS:
            return row['value']
    except Exception:
        pass
    return _LOGIN_STYLE_DEFAULT

def _render_login():
    """Страница входа: выбранная админом (по умолчанию №11) или предпросмотр по ?style=classic|1..19."""
    st = request.args.get('style', '')
    preview = st in _LOGIN_STYLE_KEYS
    if not preview:
        st = _login_style_current()
    if st == 'classic':
        return render_template('login.html')
    return render_template('login_alt.html', style=st, preview=preview)

@app.route('/api/login-style', methods=['GET', 'POST'])
@login_required
def api_login_style():
    """Выбор стартовой страницы входа — только с привилегией login_style (у админа есть всегда)."""
    if not has_perm('login_style'):
        return jsonify({'ok': False, 'error': 'Нет прав'}), 403
    if request.method == 'GET':
        return jsonify({'ok': True, 'current': _login_style_current(), 'styles': [k for k, _, _ in LOGIN_STYLE_INFO]})
    st = str((request.get_json(silent=True) or {}).get('style', ''))
    if st not in _LOGIN_STYLE_KEYS:
        return jsonify({'ok': False, 'error': 'Неизвестный вариант'}), 400
    with get_db() as c:
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('login_style',?)", (st,))
    log_action(current_user.username, 'login_style', 'webui', st)
    return jsonify({'ok': True, 'current': st})

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'GET' and request.args.get('style', '') in _LOGIN_STYLE_KEYS:
        return _render_login()            # предпросмотр вариантов доступен и при открытой сессии
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    ip  = request.remote_addr or '0.0.0.0'
    now = time.time()
    rec = _login_attempts.get(ip, {'count': 0, 'lockout_until': 0.0})
    if rec['lockout_until'] > now:
        mins = int((rec['lockout_until'] - now) // 60) + 1
        flash(f'Слишком много неудачных попыток. Попробуйте через {mins} мин.', 'danger')
        return _render_login()
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        with get_db() as c:
            row = c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        if row and dict(row).get('is_blocked'):
            flash('Ваш аккаунт заблокирован. Обратитесь к администратору.', 'danger')
            return _render_login()
        if row and check_password_hash(row['password_hash'], password):
            _login_attempts.pop(ip, None)   # сбросить счётчик при успехе
            login_user(User(row), remember=True, duration=timedelta(days=30))
            session.permanent = True
            log_action(username, 'login', 'webui', f'ip={ip}')
            ua = request.user_agent.string[:80] if request.user_agent else '?'
            _msg = (f'🔐 <b>Вход в систему</b>\n'
                    f'👤 <b>{username}</b> [{row["role"]}]\n'
                    f'🌐 IP: <code>{ip}</code>\n'
                    f'📱 {ua}\n'
                    f'🕐 {_tg_fmt_time()}')
            notify(_msg, subject=f'Campus WEB Login: {username}',
                   body=f'Вход в веб-интерфейс\nПользователь: {username} [{row["role"]}]\nIP: {ip}\nBrowser: {ua}\nВремя: {_tg_fmt_time()}',
                   event_type='login')
            return redirect(url_for('dashboard'))
        rec['count'] += 1
        if rec['count'] >= _MAX_ATTEMPTS:
            rec['lockout_until'] = now + _LOCKOUT_SECS
            rec['count'] = 0
            _login_attempts[ip] = rec
            flash('Слишком много неудачных попыток. IP заблокирован на 15 минут.', 'danger')
            tg_notify(f'🚫 <b>IP заблокирован</b>\nПопытки: <code>{ip}</code>\nЛогин: <code>{username}</code>\n🕐 {_tg_fmt_time()}',
                      event_type='login')
        else:
            _login_attempts[ip] = rec
            left = _MAX_ATTEMPTS - rec['count']
            flash(f'Неверный логин или пароль. Осталось попыток: {left}', 'danger')
            tg_notify(f'⚠️ <b>Неверный пароль</b>\nЛогин: <code>{username}</code>\nIP: <code>{ip}</code> (попытка {rec["count"]}/{_MAX_ATTEMPTS})\n🕐 {_tg_fmt_time()}',
                      event_type='login')
    return _render_login()

@app.route('/logout')
@login_required
def logout():
    uname = current_user.username
    role  = current_user.role
    logout_user()
    tg_notify(f'👋 <b>Выход из системы</b>\n👤 <b>{uname}</b> [{role}]\n🕐 {_tg_fmt_time()}',
              event_type='login')
    return redirect(url_for('login'))

_UI_DEFAULT = 'console'   # основной дизайн для всех, кто явно не выбрал другой ('off' в cookie — старый)

# Все варианты дизайна. key — значение cookie/поля users.ui_variant, route — страница плеера,
# css — номер файла static/v<N>.css (None — у «Студии» стили общие), demo — цвета для карточки-превью.
UI_VARIANT_INFO = [
    {'key': 'console', 'name': 'Пульт',  'route': 'dashboard_v4', 'desc': 'Микшерная консоль: каналы с фейдерами, светодиодные уровни, аварийный стоп. Основной дизайн.', 'demo': ['#1c1e24', '#ffb000', '#ff7a00']},
    {'key': 'studio',  'name': 'Студия', 'route': 'dashboard_v3', 'desc': 'Тёмный, стеклянные карточки кампусов, янтарная лампа «В ЭФИРЕ», визуализатор звука.', 'demo': ['#0d0c11', '#ffb347', '#ff6a3d']},
    {'key': 'neon',    'name': 'Неон',   'route': 'dashboard_v6', 'desc': 'Тёмное плоское стекло, свечение, тонкие фейдеры. Разметка «Пульта», современный вид.', 'demo': ['#07080c', '#ff7a45', '#ff3d7f']},
    {'key': 'bento',   'name': 'Бенто',  'route': 'dashboard_v5', 'desc': 'Светлый, крупные цветные карточки, плитки со статистикой.', 'demo': ['#e4e8f1', '#3d5afe', '#7c4dff']},
    {'key': 'lumen',   'name': 'Свет',   'route': 'dashboard_v7', 'desc': 'Светлый и графичный: белые каналы, чёрные акценты, уровни-точки.', 'demo': ['#eceef2', '#ff5b2e', '#111318']},
    {'key': 'rack',    'name': 'Рэк',    'route': 'dashboard_v8', 'desc': 'Студийная стойка: юниты на рейках, стрелочные VU-метры, светодиодные шкалы.', 'demo': ['#141518', '#ffb400', '#e6e2d3']},
    {'key': 'deck',    'name': 'Дека',   'route': 'dashboard_v9', 'desc': 'Светлый корпус в духе Teenage Engineering: точечный экран, энкодер, пэды.', 'demo': ['#c8ccd1', '#ff5a1f', '#111214']},
    # ── варианты в стиле «Пульта»: разметка player_v4.html + v4.css, свой материал/цвета (static/v10..v19.css, генератор scripts/make_pult_skins.py) и «плюшки» (static/console-extras.js) ──
    {'key': 'emerald', 'name': 'Изумруд', 'route': 'dashboard_v10', 'desc': 'Зелёный фосфорный экран, как у старой ЭЛТ-техники: строки развёртки, мерцание, зелёные светодиоды. Пиковые огоньки на уровнях.', 'demo': ['#16211c', '#4dff9a', '#0b120e']},
    {'key': 'ice', 'name': 'Лёд', 'route': 'dashboard_v11', 'desc': 'Холодная голубая сталь, серебристые клавиши, бирюзовый экран с бликом. Кнопки «−/+» для точной подстройки громкости каждого канала.', 'demo': ['#2a3442', '#5ee6ff', '#dbe6f0']},
    {'key': 'crimson', 'name': 'Кармин', 'route': 'dashboard_v12', 'desc': 'Тёмно-красный корпус, красный экран и огромная вывеска «В ЭФИРЕ»: корпус светится сильнее, когда звук громче.', 'demo': ['#3a1518', '#ff4b55', '#120507']},
    {'key': 'alu', 'name': 'Алюминий', 'route': 'dashboard_v13', 'desc': 'Светлый шлифованный алюминий, чёрные клавиши и колпачки, бумажные шильдики каналов. Кнопки-пресеты громкости 50/100/130/150.', 'demo': ['#cfd3d9', '#ffb000', '#1c1e22']},
    {'key': 'walnut', 'name': 'Орех', 'route': 'dashboard_v14', 'desc': 'Винтажная консоль: боковины из ореха, латунные винты, тёплый янтарный экран. Пресеты громкости 50/100/130/150 под каждым фейдером.', 'demo': ['#5a3218', '#ffb000', '#1c1612']},
    {'key': 'neve', 'name': 'Неве', 'route': 'dashboard_v15', 'desc': 'Сине-серый корпус в духе студийных консолей: у каждого канала свой цветной колпачок фейдера. Точная подстройка «−/+» и пиковые огоньки.', 'demo': ['#5b6b7d', '#e8b40c', '#d8342c']},
    {'key': 'rotor', 'name': 'Ротор', 'route': 'dashboard_v16', 'desc': 'Вместо фейдеров — рифлёные ручки со светодиодным кольцом у каждого кампуса: тяните вверх-вниз, крутите колёсиком, стрелками на клавиатуре.', 'demo': ['#2c2f38', '#ff8a3d', '#c9c6bd']},
    {'key': 'carbon', 'name': 'Карбон', 'route': 'dashboard_v17', 'desc': 'Карбоновое плетение, оранжевые акценты и чёрные клавиши: гоночный характер. Пресеты громкости и пиковые индикаторы.', 'demo': ['#1b1b1b', '#ff5a1f', '#c9c9c9']},
    {'key': 'night', 'name': 'Ночь', 'route': 'dashboard_v18', 'desc': 'Ночной режим для вечерних смен: приглушённые красно-бурые тона, минимум яркости и бликов, глаза не устают. Пиковые огоньки на уровнях.', 'demo': ['#1c1210', '#d94a3a', '#0a0605']},
    {'key': 'synth', 'name': 'Синт', 'route': 'dashboard_v19', 'desc': 'Тёплая кремовая панель винтажного синтезатора с цветной полосой, шоколадные клавиши и «−/+» для подстройки громкости.', 'demo': ['#e2d6b8', '#e8542c', '#3b2e24']},
]
# «Плюшки» — короткие теги-возможности на карточках выбора дизайна (Настройки → «Дизайн интерфейса»)
_UI_FEATURES = {
    'console': ['Фейдеры и VU-уровни', 'Аварийный стоп', 'Светодиоды'],
    'studio':  ['Приветствие', 'Стеклянные карточки', 'Визуализатор'],
    'neon':    ['Свечение', 'Тонкие фейдеры'],
    'bento':   ['Плитки статистики', 'Светлый'],
    'lumen':   ['Светлый', 'Уровни-точки'],
    'rack':    ['Стрелочные VU-метры', 'Стойка'],
    'deck':    ['Точечный экран', 'Энкодер', 'Пэды'],
    'emerald': ['Фосфорный экран', 'Пик-индикаторы'],
    'ice': ['Стальной корпус', 'Точная подстройка −/+'],
    'crimson': ['Вывеска «В эфире»', 'Свечение в такт звуку'],
    'alu': ['Светлый корпус', 'Пресеты громкости'],
    'walnut': ['Деревянные боковины', 'Пресеты громкости'],
    'neve': ['Цветные колпачки', 'Пик-индикаторы', 'Точная подстройка −/+'],
    'rotor': ['Поворотные ручки', 'Колёсико и стрелки'],
    'carbon': ['Карбон', 'Пресеты громкости', 'Пик-индикаторы'],
    'night': ['Приглушённый свет', 'Пик-индикаторы'],
    'synth': ['Кремовая панель', 'Цветная полоса', 'Точная подстройка −/+'],
}
for _v in UI_VARIANT_INFO:
    _v['feat'] = _UI_FEATURES.get(_v['key'], [])
UI_PALETTES = [('amber', 'Янтарь'), ('aurora', 'Аврора'), ('rose', 'Роза')]
_UI_PALETTE_KEYS = tuple(k for k, _ in UI_PALETTES)

def _ui_pref_row():
    """Сохранённые в аккаунте ui_variant / ui_palette текущего пользователя (кэш на запрос)."""
    from flask import g
    if getattr(g, '_ui_pref', None) is None:
        row = None
        if getattr(current_user, 'is_authenticated', False):
            try:
                with get_db() as c:
                    row = c.execute('SELECT ui_variant, ui_palette FROM users WHERE id=?', (current_user.id,)).fetchone()
            except Exception:
                row = None
        g._ui_pref = {'variant': (row['ui_variant'] if row else '') or '', 'palette': (row['ui_palette'] if row else '') or ''}
    return g._ui_pref

def _effective_ui():
    """Вариант дизайна для запроса: cookie → выбор, сохранённый в аккаунте → основной.
    'off' — старый интерфейс (возвращает None)."""
    c = request.cookies.get('ui')
    if c not in _UI_VARIANTS and c != 'off':
        c = _ui_pref_row()['variant']
    if c == 'off':
        return None
    return c if c in _UI_VARIANTS else _ui_default_current()

def _ui_default_current():
    """Основной дизайн плеера для всех, кто не выбрал свой: settings.ui_default (задаёт админ), иначе «Пульт»."""
    try:
        with get_db() as c:
            row = c.execute("SELECT value FROM settings WHERE key='ui_default'").fetchone()
        if row and row['value'] in _UI_VARIANTS:
            return row['value']
    except Exception:
        pass
    return _UI_DEFAULT

def _save_ui_variant(name):
    if getattr(current_user, 'is_authenticated', False):
        try:
            with get_db() as c:
                c.execute('UPDATE users SET ui_variant=? WHERE id=?', (name, current_user.id))
        except Exception:
            pass

_UI_VARIANTS = {'studio': 'dashboard_v3', 'console': 'dashboard_v4', 'bento': 'dashboard_v5', 'neon': 'dashboard_v6', 'lumen': 'dashboard_v7', 'rack': 'dashboard_v8', 'deck': 'dashboard_v9',
                'emerald': 'dashboard_v10', 'ice': 'dashboard_v11', 'crimson': 'dashboard_v12', 'alu': 'dashboard_v13', 'walnut': 'dashboard_v14', 'neve': 'dashboard_v15', 'rotor': 'dashboard_v16', 'carbon': 'dashboard_v17', 'night': 'dashboard_v18', 'synth': 'dashboard_v19'}

@app.context_processor
def inject_globals():
    result = {'ann_count': 0, 'wallpaper_default': 'off', 'theme_default': ''}
    _ui = _effective_ui()
    result['ui_variant_list'] = [(v['key'], v['name']) for v in UI_VARIANT_INFO]
    result['ui_palette_pref'] = _ui_pref_row()['palette'] if _ui_pref_row()['palette'] in _UI_PALETTE_KEYS else ''
    if _ui:
        result.update(v3ui=True, variant=_ui, player_home=url_for(_UI_VARIANTS[_ui]))
    if current_user.is_authenticated:
        try:
            with get_db() as c:
                result['ann_count'] = c.execute('SELECT COUNT(*) FROM announcements').fetchone()[0]
                row = c.execute("SELECT value FROM settings WHERE key='wallpaper_default'").fetchone()
                if row:
                    result['wallpaper_default'] = row['value']
                row2 = c.execute("SELECT value FROM settings WHERE key='theme_default'").fetchone()
                if row2:
                    result['theme_default'] = row2['value']
        except Exception:
            pass
    return result

@app.route('/api/wallpapers/default', methods=['GET', 'POST'])
@login_required
def api_wallpaper_default():
    if request.method == 'GET':
        with get_db() as c:
            row = c.execute("SELECT value FROM settings WHERE key='wallpaper_default'").fetchone()
        return jsonify({'ok': True, 'default': row['value'] if row else 'off'})
    if not has_perm('appearance_manage'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    val = (request.get_json() or {}).get('value', 'off')
    with get_db() as c:
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('wallpaper_default',?)", (val,))
    return jsonify({'ok': True})

@app.route('/api/theme/default', methods=['GET', 'POST'])
@login_required
def api_theme_default():
    if request.method == 'GET':
        with get_db() as c:
            row = c.execute("SELECT value FROM settings WHERE key='theme_default'").fetchone()
        return jsonify({'ok': True, 'default': row['value'] if row else ''})
    if not has_perm('appearance_manage'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    val = (request.get_json() or {}).get('value', '')
    with get_db() as c:
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('theme_default',?)", (val,))
    return jsonify({'ok': True})

@app.route('/announcements')
@login_required
def announcements_page():
    with get_db() as c:
        rows = c.execute(
            'SELECT * FROM announcements ORDER BY pin_top DESC, id DESC'
        ).fetchall()
    return render_template('announcements.html', announcements=rows,
                           is_admin=has_perm('announcements_manage'))

@app.route('/api/announcements', methods=['GET'])
@login_required
def api_announcements():
    with get_db() as c:
        rows = c.execute('SELECT * FROM announcements ORDER BY pin_top DESC, id DESC').fetchall()
    return jsonify({'ok': True, 'announcements': [dict(r) for r in rows]})

@app.route('/api/announcements/create', methods=['POST'])
@login_required
def api_ann_create():
    if not has_perm('announcements_manage'):
        return jsonify({'ok': False, 'error': 'Только для администраторов'})
    data     = request.get_json() or {}
    title    = str(data.get('title',   '')).strip()[:200]
    content  = str(data.get('content', '')).strip()[:2000]
    priority = str(data.get('priority','normal'))
    pin_top  = 1 if data.get('pin_top') else 0
    if not title or not content:
        return jsonify({'ok': False, 'error': 'Заполните заголовок и текст'})
    if priority not in ('normal','info','warning','danger'):
        priority = 'normal'
    with get_db() as c:
        c.execute('INSERT INTO announcements(author,title,content,priority,pin_top) VALUES(?,?,?,?,?)',
                  (current_user.username, title, content, priority, pin_top))
    return jsonify({'ok': True})

@app.route('/api/announcements/delete', methods=['POST'])
@login_required
def api_ann_delete():
    if not has_perm('announcements_manage'):
        return jsonify({'ok': False, 'error': 'Только для администраторов'})
    ann_id = int((request.get_json() or {}).get('id', 0))
    if not ann_id:
        return jsonify({'ok': False, 'error': 'Не указан id'})
    with get_db() as c:
        c.execute('DELETE FROM announcements WHERE id=?', (ann_id,))
    return jsonify({'ok': True})

@app.route('/api/announcements/pin', methods=['POST'])
@login_required
def api_ann_pin():
    if not has_perm('announcements_manage'):
        return jsonify({'ok': False, 'error': 'Только для администраторов'})
    data = request.get_json() or {}
    ann_id = int(data.get('id', 0))
    pin_top = bool(data.get('pin_top', False))
    if not ann_id:
        return jsonify({'ok': False, 'error': 'Не указан id'})
    with get_db() as c:
        c.execute('UPDATE announcements SET pin_top=? WHERE id=?', (1 if pin_top else 0, ann_id))
    return jsonify({'ok': True})

@app.route('/qr')
@login_required
def qr_page():
    host = request.host_url.rstrip('/')
    return render_template('qr.html', site_url=host)

@app.route('/qr/image')
@login_required
def qr_image():
    import qrcode
    from io import BytesIO
    url = request.host_url.rstrip('/')
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.getvalue(), 200, {'Content-Type': 'image/png', 'Cache-Control': 'no-cache'}

# ── Wallpapers ─────────────────────────────────────
@app.route('/wallpapers/<path:filename>')
@login_required
def serve_wallpaper(filename):
    if current_user.role == 'guest':
        return '', 403
    return send_from_directory(WALLPAPER_DIR, filename)

@app.route('/api/wallpapers/list')
@login_required
def api_wallpapers_list():
    if current_user.role == 'guest':
        return jsonify({'ok': False})
    try:
        files = sorted(f for f in os.listdir(WALLPAPER_DIR)
                       if f.rsplit('.', 1)[-1].lower() in ALLOWED_IMG_EXT)
        return jsonify({'ok': True, 'wallpapers': files})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/wallpapers/upload', methods=['POST'])
@login_required
def api_wallpapers_upload():
    if not has_perm('appearance_manage'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    files = request.files.getlist('files')
    saved = []
    for f in files:
        if not f.filename:
            continue
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in ALLOWED_IMG_EXT:
            continue
        fname = secure_filename(f.filename)
        if not fname:
            continue
        dest = os.path.join(WALLPAPER_DIR, fname)
        if os.path.exists(dest):
            base, e2 = os.path.splitext(fname)
            fname = f'{base}_{int(time.time())}{e2}'
            dest = os.path.join(WALLPAPER_DIR, fname)
        f.save(dest)
        saved.append(fname)
    return jsonify({'ok': True, 'saved': saved})

@app.route('/api/wallpapers/delete', methods=['POST'])
@login_required
def api_wallpapers_delete():
    if not has_perm('appearance_manage'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data = request.get_json() or {}
    fname = secure_filename(data.get('filename', ''))
    if fname:
        fpath = os.path.join(WALLPAPER_DIR, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
    return jsonify({'ok': True})

# ── Custom Emojis ──────────────────────────────────
EMOJI_DIR = os.path.join(os.path.dirname(DB_PATH), 'emojis')
os.makedirs(EMOJI_DIR, exist_ok=True)

@app.route('/emojis/<path:filename>')
@login_required
def serve_emoji(filename):
    if current_user.role == 'guest':
        return '', 403
    return send_from_directory(EMOJI_DIR, filename)

@app.route('/api/emojis/list')
@login_required
def api_emojis_list():
    if current_user.role == 'guest':
        return jsonify({'ok': False})
    try:
        files = sorted(f for f in os.listdir(EMOJI_DIR)
                       if f.rsplit('.', 1)[-1].lower() in ALLOWED_IMG_EXT)
        return jsonify({'ok': True, 'emojis': files})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/emojis/upload', methods=['POST'])
@login_required
def api_emojis_upload():
    if not has_perm('appearance_manage'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    files = request.files.getlist('files')
    saved = []
    for f in files:
        if not f.filename:
            continue
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in ALLOWED_IMG_EXT:
            continue
        fname = secure_filename(f.filename)
        if not fname:
            continue
        dest = os.path.join(EMOJI_DIR, fname)
        if os.path.exists(dest):
            base, e2 = os.path.splitext(fname)
            fname = f'{base}_{int(time.time())}{e2}'
            dest = os.path.join(EMOJI_DIR, fname)
        f.save(dest)
        saved.append(fname)
    return jsonify({'ok': True, 'saved': saved})

@app.route('/api/emojis/delete', methods=['POST'])
@login_required
def api_emojis_delete():
    if not has_perm('appearance_manage'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data = request.get_json() or {}
    fname = secure_filename(data.get('filename', ''))
    if fname:
        fpath = os.path.join(EMOJI_DIR, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
    return jsonify({'ok': True})

_wx_cache = {'data': None, 'ts': 0}

@app.route('/api/weather')
@login_required
def api_weather():
    now = time.time()
    if _wx_cache['data'] and now - _wx_cache['ts'] < 1800:
        return jsonify(_wx_cache['data'])
    try:
        req = urllib.request.Request(
            'https://wttr.in/Baku?format=j1',
            headers={'User-Agent': 'campus-webui/1.0'}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode())
        cc = raw['current_condition'][0]
        weather = raw.get('weather', [{}])[0]
        result = {
            'ok': True,
            'temp_c':    int(cc['temp_C']),
            'feels_c':   int(cc['FeelsLikeC']),
            'humidity':  int(cc['humidity']),
            'desc':      cc['weatherDesc'][0]['value'],
            'wind_kmph': int(cc['windspeedKmph']),
            'wind_dir':  cc.get('winddir16Point',''),
            'max_c':     int(weather.get('maxtempC', cc['temp_C'])),
            'min_c':     int(weather.get('mintempC', cc['temp_C'])),
        }
        _wx_cache['data'] = result
        _wx_cache['ts']   = now
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/')
@login_required
def dashboard():
    _ui = _effective_ui()
    if _ui and not request.args.get('classic'):
        return redirect(url_for(_UI_VARIANTS[_ui]))
    return _render_dashboard()

@app.route('/ui/<name>')
@login_required
def set_ui(name):
    """Выбор дизайна (cookie 'ui'): studio / console / bento — новый каркас на всех страницах; off — старый."""
    if name in _UI_VARIANTS:
        _save_ui_variant(name)
        resp = redirect(url_for(_UI_VARIANTS[name]))
        resp.set_cookie('ui', name, max_age=365*86400, samesite='Lax')
        return resp
    _save_ui_variant('off')
    resp = redirect(url_for('dashboard', classic=1))
    resp.set_cookie('ui', 'off', max_age=365*86400, samesite='Lax')
    return resp

@app.route('/v2')
@login_required
def dashboard_v2():
    """Предпросмотр нового интерфейса (Tabler). Тот же контекст и тот же общий JS,
    что у боевого '/', отличается только каркас (base_v2.html) и разметка плеера."""
    return _render_dashboard(v2=True, base_layout='base_v2.html')

def _ui_page(html, name):
    """Ответ с запоминанием выбранного дизайна (cookie), чтобы остальные страницы открывались в нём же.
    ?preview=1 — только посмотреть: ни cookie, ни выбор в аккаунте не меняются."""
    resp = make_response(html)
    if request.args.get('preview'):
        return resp
    resp.set_cookie('ui', name, max_age=365*86400, samesite='Lax')
    if request.cookies.get('ui') != name:
        _save_ui_variant(name)
    return resp

@app.route('/v3')
@login_required
def dashboard_v3():
    """Предпросмотр нового интерфейса «Эфирная студия». Тот же контекст и тот же общий JS,
    что у боевого '/', отличается только каркас (base_v3.html) и разметка плеера."""
    return _ui_page(_render_dashboard(v3=True, v3ui=True, variant='studio',
                             player_tpl='player_v3.html', player_home=url_for('dashboard_v3')), 'studio')

@app.route('/v4')
@login_required
def dashboard_v4():
    """Вариант дизайна «Пульт» (микшерная консоль). Тот же контекст и общий JS."""
    return _ui_page(_render_dashboard(v3=True, v3ui=True, variant='console',
                             player_tpl='player_v4.html', player_home=url_for('dashboard_v4')), 'console')

@app.route('/v5')
@login_required
def dashboard_v5():
    """Вариант дизайна «Бенто» (светлый, сеточные карточки). Тот же контекст и общий JS."""
    return _ui_page(_render_dashboard(v3=True, v3ui=True, variant='bento',
                             player_tpl='player_v5.html', player_home=url_for('dashboard_v5')), 'bento')

@app.route('/v6')
@login_required
def dashboard_v6():
    """Вариант дизайна «Неон» (тёмный, плоское стекло, свечение). Разметка как у «Пульта», другой вид."""
    return _ui_page(_render_dashboard(v3=True, v3ui=True, variant='neon',
                             player_tpl='player_v4.html', player_home=url_for('dashboard_v6')), 'neon')

@app.route('/v7')
@login_required
def dashboard_v7():
    """Вариант дизайна «Свет» (светлый, графичный). Разметка как у «Пульта», другой вид."""
    return _ui_page(_render_dashboard(v3=True, v3ui=True, variant='lumen',
                             player_tpl='player_v4.html', player_home=url_for('dashboard_v7')), 'lumen')

@app.route('/v8')
@login_required
def dashboard_v8():
    """Вариант дизайна «Рэк» (студийная стойка, стрелочные VU). Тот же контекст и общий JS."""
    return _ui_page(_render_dashboard(v3=True, v3ui=True, variant='rack',
                             player_tpl='player_v8.html', player_home=url_for('dashboard_v8')), 'rack')

@app.route('/v9')
@login_required
def dashboard_v9():
    """Вариант дизайна «Дека» (светлый корпус, пэды). Тот же контекст и общий JS."""
    return _ui_page(_render_dashboard(v3=True, v3ui=True, variant='deck',
                             player_tpl='player_v9.html', player_home=url_for('dashboard_v9')), 'deck')

def _register_console_variants():
    """Варианты семейства «Пульт»: та же разметка player_v4.html, свой вид (static/vN.css) и «плюшки» (console-extras.js)."""
    for key, num in (('emerald', 10), ('ice', 11), ('crimson', 12), ('alu', 13), ('walnut', 14), ('neve', 15), ('rotor', 16), ('carbon', 17), ('night', 18), ('synth', 19)):
        def make(key=key, num=num):
            def view():
                return _ui_page(_render_dashboard(v3=True, v3ui=True, variant=key, player_tpl='player_v4.html',
                                                  player_home=url_for(f'dashboard_v{num}')), key)
            return view
        app.add_url_rule(f'/v{num}', endpoint=f'dashboard_v{num}', view_func=login_required(make()))

_register_console_variants()

@app.route('/api/ui-default', methods=['GET', 'POST'])
@login_required
def api_ui_default():
    """Основной дизайн плеера для всех — только с привилегией ui_default (у админа есть всегда)."""
    if not has_perm('ui_default'):
        return jsonify({'ok': False, 'error': 'Нет прав'}), 403
    if request.method == 'GET':
        return jsonify({'ok': True, 'current': _ui_default_current(), 'variants': list(_UI_VARIANTS)})
    st = str((request.get_json(silent=True) or {}).get('style', ''))
    if st not in _UI_VARIANTS:
        return jsonify({'ok': False, 'error': 'Неизвестный вариант'}), 400
    with get_db() as c:
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('ui_default',?)", (st,))
    log_action(current_user.username, 'ui_default', 'webui', st)
    return jsonify({'ok': True, 'current': st})

@app.route('/ui-preview/<key>.jpg')
@login_required
def ui_preview_image(key):
    """Картинки-превью дизайнов плеера (на них видны названия кампусов и треков — поэтому только для вошедших)."""
    if not re.match(r'^[a-z0-9_-]{1,24}$', key):
        return '', 404
    return send_from_directory(os.path.join(app.root_path, 'ui_previews'), key + '.jpg', max_age=3600)

def _render_dashboard(**extra):
    now = datetime.now()
    ct  = now.strftime('%H:%M')
    next_ev = next((e for e in SCHEDULE if e['time'] > ct and e['play']), None)

    tomorrow = now + timedelta(days=1)
    tdow = tomorrow.weekday()  # 0=Mon, 6=Sun
    _DOW_RU = ['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье']
    tomorrow_events = [e for e in SCHEDULE if e['play'] and tdow in e.get('dow', [])]

    with get_db() as c:
        _prefs_row = c.execute('SELECT ui_skin, ui_accent, panel_color FROM users WHERE username=?',
                                (current_user.username,)).fetchone()
    ui_skin     = (_prefs_row['ui_skin'] if _prefs_row else 'classic') or 'classic'
    ui_accent   = (_prefs_row['ui_accent'] if _prefs_row else 'amber') or 'amber'
    panel_color = (_prefs_row['panel_color'] if _prefs_row else '') or ''

    return render_template('dashboard.html',
        schedule=SCHEDULE, next_ev=next_ev, now=now,
        tomorrow_date=tomorrow.strftime('%d.%m'),
        tomorrow_name=_DOW_RU[tdow],
        tomorrow_dow_idx=tdow,
        tomorrow_is_weekend=(tdow >= 5),
        tomorrow_events=tomorrow_events,
        perms=user_perms(),
        music_folders=all_music_folders(),
        fixed_folders=MUSIC_FOLDERS,
        perem_slots=[{'id': s, 'label': PEREM_SLOT_LABELS.get(s, s)} for s in PEREM_SLOTS],
        ui_skin=ui_skin, ui_accent=ui_accent, panel_color=panel_color,
        music_machines=music_machines_json(),
        utro_enabled=any(e.get('file')=='utro.mp3' and e.get('play') for e in SCHEDULE),
        perem_enabled=any(e.get('file','').endswith('peremena.mp3') and e.get('play') for e in SCHEDULE),
        **extra,
    )

@app.route('/tracks')
@login_required
def tracks():
    q      = request.args.get('q','').strip()
    folder = request.args.get('folder','').strip()

    # Lock all folders when returning to the grid
    if not folder:
        session.pop('kamran_unlocked', None)
        session['unlocked_folders'] = []

    with get_db() as c:
        pin_rows = c.execute("SELECT key, value FROM settings WHERE key LIKE 'pin_hash_%'").fetchall()
    folder_pin_set   = {r['key'][len('pin_hash_'):]: bool(r['value']) for r in pin_rows}
    unlocked_folders = set(session.get('unlocked_folders', []))
    if session.get('kamran_unlocked') or KAMRAN_FOLDER in unlocked_folders:
        unlocked_folders.add(KAMRAN_FOLDER)
    # Auto-unlock folders that have no PIN set (except KAMRAN which always needs a PIN)
    for sub in MUSIC_FOLDERS:
        if sub != KAMRAN_FOLDER and not folder_pin_set.get(sub):
            unlocked_folders.add(sub)

    # Folder counts for the grid view
    folder_counts = {}
    for sub in MUSIC_FOLDERS:
        sub_path = os.path.join(MUSIC_DIR, sub)
        if os.path.isdir(sub_path):
            folder_counts[sub] = sum(
                1 for f in os.listdir(sub_path)
                if f.lower().endswith(AUDIO_EXTS)
            )

    # If a specific folder is requested but not unlocked → back to grid
    is_pin_owner = (current_user.username == PIN_OWNER)

    if folder and folder not in unlocked_folders:
        return render_template('tracks.html',
                               folder='', tracks=[], q='',
                               total=total_tracks(), found=0,
                               perms=user_perms(), folders=MUSIC_FOLDERS,
                               folder_counts=folder_counts,
                               unlocked_folders=unlocked_folders,
                               folder_pin_set=folder_pin_set,
                               is_pin_owner=is_pin_owner,
                               music_machines=music_machines_json(),
                               open_pin_for=folder)

    result = scan_tracks(q, folder_filter=folder) if folder else []
    return render_template('tracks.html',
                           folder=folder, tracks=result, q=q,
                           total=total_tracks(), found=len(result),
                           perms=user_perms(), folders=MUSIC_FOLDERS,
                           folder_counts=folder_counts,
                           unlocked_folders=unlocked_folders,
                           folder_pin_set=folder_pin_set,
                           is_pin_owner=is_pin_owner,
                           music_machines=music_machines_json(),
                           open_pin_for='')

@app.route('/admin')
@login_required
@perm_required('users_manage')
def admin():
    with get_db() as c:
        users = c.execute('SELECT * FROM users ORDER BY id').fetchall()
    return render_template('admin.html', users=users, role_labels=ROLE_LABELS)

@app.route('/admin/users/add', methods=['POST'])
@login_required
@perm_required('users_manage')
def add_user():
    u    = request.form.get('username','').strip()
    p    = request.form.get('password','')
    role = request.form.get('role','user')
    if role not in ('guest', 'user', 'staff', 'helpdesk', 'eventmanager', 'admin'):
        role = 'user'
    if u and p:
        try:
            with get_db() as c:
                c.execute('INSERT INTO users (username,password_hash,role) VALUES (?,?,?)',
                    (u, generate_password_hash(p), role))
            flash(f'Пользователь {u} создан', 'success')
            tg_notify(
                f'👤 <b>Новый пользователь</b>\n'
                f'Создан: <b>{u}</b> [{role}]\n'
                f'Кем: <b>{current_user.username}</b>\n'
                f'🕐 {_tg_fmt_time()}',
                event_type='users'
            )
        except Exception:
            flash('Пользователь с таким именем уже существует', 'danger')
    return redirect(url_for('admin'))

@app.route('/admin/users/delete/<int:uid>', methods=['POST'])
@login_required
@perm_required('users_manage')
def delete_user(uid):
    if uid == current_user.id:
        flash('Нельзя удалить себя', 'danger')
    else:
        with get_db() as c:
            row = c.execute('SELECT username,role FROM users WHERE id=?', (uid,)).fetchone()
            c.execute('DELETE FROM users WHERE id=?',(uid,))
        if row:
            tg_notify(
                f'🗑 <b>Пользователь удалён</b>\n'
                f'Кто: <b>{row["username"]}</b> [{row["role"]}]\n'
                f'Кем: <b>{current_user.username}</b>\n'
                f'🕐 {_tg_fmt_time()}',
                event_type='users'
            )
        flash('Пользователь удалён', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/users/passwd/<int:uid>', methods=['POST'])
@login_required
@perm_required('users_manage')
def reset_passwd(uid):
    p = request.form.get('password','')
    if p:
        with get_db() as c:
            c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(p),uid))
        flash('Пароль изменён', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/users/role/<int:uid>', methods=['POST'])
@login_required
@perm_required('users_manage')
def set_role(uid):
    role = request.form.get('role', 'user')
    if role not in ('guest', 'user', 'staff', 'helpdesk', 'eventmanager', 'admin'):
        flash('Неверная роль', 'danger')
        return redirect(url_for('admin'))
    if uid == current_user.id:
        flash('Нельзя изменить свою роль', 'danger')
        return redirect(url_for('admin'))
    with get_db() as c:
        c.execute('UPDATE users SET role=? WHERE id=?', (role, uid))
    flash('Роль обновлена', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/users/himn/<int:uid>', methods=['POST'])
@login_required
@perm_required('users_manage')
def toggle_himn(uid):
    with get_db() as c:
        row = c.execute('SELECT can_himn, username FROM users WHERE id=?', (uid,)).fetchone()
        if row:
            new_val = 0 if row['can_himn'] else 1
            c.execute('UPDATE users SET can_himn=? WHERE id=?', (new_val, uid))
            state = 'выдано' if new_val else 'отозвано'
            flash(f'Право на гимн {state}: {row["username"]}', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/users/block/<int:uid>', methods=['POST'])
@login_required
@perm_required('users_manage')
def toggle_block(uid):
    if uid == current_user.id:
        flash('Нельзя заблокировать себя', 'danger')
        return redirect(url_for('admin'))
    with get_db() as c:
        row = c.execute('SELECT is_blocked, username FROM users WHERE id=?', (uid,)).fetchone()
        if row:
            new_val = 0 if row['is_blocked'] else 1
            c.execute('UPDATE users SET is_blocked=?, force_logout=? WHERE id=?', (new_val, new_val, uid))
            state = 'заблокирован' if new_val else 'разблокирован'
            flash(f'Пользователь {state}: {row["username"]}', 'success')
            log_action(current_user.username, 'block' if new_val else 'unblock', detail=row['username'])
    return redirect(url_for('admin'))

@app.route('/admin/users/kick/<int:uid>', methods=['POST'])
@login_required
@perm_required('users_manage')
def kick_user(uid):
    if uid == current_user.id:
        return jsonify({'ok': False, 'error': 'Нельзя выкинуть себя'})
    with get_db() as c:
        row = c.execute('SELECT username FROM users WHERE id=?', (uid,)).fetchone()
        if row:
            c.execute('UPDATE users SET force_logout=1 WHERE id=?', (uid,))
            log_action(current_user.username, 'kick', detail=row['username'])
            return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Пользователь не найден'})

@app.route('/api/settings/silence', methods=['GET','POST'])
@login_required
@perm_required('silence_mode')
def api_silence():
    if request.method == 'POST':
        val = '1' if request.json.get('active') else '0'
        with get_db() as c:
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('silence_mode',?)", (val,))
        label = 'включён' if val == '1' else 'выключен'
        log_action(current_user.username, 'silence_mode', detail=label)
        tg_notify(
            f'🔇 <b>Режим тишины {label}</b>\nАдмин: <b>{current_user.username}</b>\n🕐 {_tg_fmt_time()}',
            event_type='misc'
        )
        return jsonify({'ok': True, 'active': val == '1'})
    with get_db() as c:
        row = c.execute("SELECT value FROM settings WHERE key='silence_mode'").fetchone()
    return jsonify({'ok': True, 'active': bool(row and row['value'] == '1')})

@app.route('/admin/activity')
@login_required
@perm_required('activity_log')
def admin_activity():
    username = request.args.get('user', '').strip()
    action   = request.args.get('action', '').strip()
    date     = request.args.get('date', '').strip()
    export   = request.args.get('export', '')

    query  = 'SELECT * FROM activity_log WHERE 1=1'
    params = []
    if username:
        query += ' AND username=?'; params.append(username)
    if action:
        query += ' AND action LIKE ?'; params.append(f'%{action}%')
    if date:
        query += ' AND happened_at LIKE ?'; params.append(f'{date}%')
    query += ' ORDER BY id DESC LIMIT 500'

    with get_db() as c:
        rows = c.execute(query, params).fetchall()
        users = [r['username'] for r in c.execute('SELECT DISTINCT username FROM activity_log ORDER BY username').fetchall()]

    if export == 'csv':
        import csv, io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['id', 'username', 'action', 'machine', 'detail', 'happened_at', 'ip', 'user_agent'])
        for r in rows:
            w.writerow([r['id'], r['username'], r['action'], r['machine'], r['detail'], r['happened_at'], r['ip'], r['user_agent']])
        from flask import Response
        return Response(
            buf.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=activity_log.csv'}
        )

    return render_template('activity.html',
        logs=rows, users=users,
        filter_user=username, filter_action=action, filter_date=date,
        perms=user_perms()
    )

# ── Cron pause API ────────────────────────────────
_CRON_PAUSE_FILE = '.cron_paused'

def _client2_conn(machine_key='client2'):
    m = _resolve_machine(machine_key)
    if m:
        return m
    if machine_key == 'client2' and CLIENT2_HOST:
        return {'host': CLIENT2_HOST, 'user': CLIENT2_USER}
    return None

def _cron_is_paused(host, user):
    r = ssh_run_on(host, user, f'test -f ~/{_CRON_PAUSE_FILE} && echo 1 || echo 0')
    return r.get('ok') and r.get('data', '0').strip() == '1'

@app.route('/api/cron/pause', methods=['GET'])
@login_required
def api_cron_pause_get():
    if not has_perm('cron'):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    result = {'client1': _cron_is_paused(CLIENT1_HOST, CLIENT1_USER)}
    for m in music_machines():
        if m['host'] == CLIENT1_HOST:
            continue
        result[_campus_key(m)] = _cron_is_paused(m['host'], m.get('user', CLIENT1_USER))
    return jsonify({'ok': True, **result})

@app.route('/api/cron/pause', methods=['POST'])
@login_required
def api_cron_pause_set():
    if not has_perm('cron'):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    data    = request.json or {}
    machine = data.get('machine', 'both')
    paused  = bool(data.get('paused', True))
    cmd     = f'touch ~/{_CRON_PAUSE_FILE}' if paused else f'rm -f ~/{_CRON_PAUSE_FILE}'
    if machine in ('client1', 'both'):
        ssh_run_on(CLIENT1_HOST, CLIENT1_USER, cmd)
    # 'both' means "all registered audio campuses", not just client1+client2+cgtk —
    # covers any thin client added later via /machines
    if machine == 'both':
        for m in music_machines():
            if m['host'] != CLIENT1_HOST:
                ssh_run_on(m['host'], m.get('user', CLIENT1_USER), cmd)
    elif machine != 'client1':
        m = _resolve_machine(machine, strict=True)
        if m:
            ssh_run_on(m['host'], m.get('user', CLIENT1_USER), cmd)
    return jsonify({'ok': True, 'paused': paused, 'machine': machine})

# A status poll used to open 6 separate SSH connections (one per mpv
# property) — for an unreachable machine that meant up to 6× the connect
# timeout before the request even returned, and with a dozen campuses often
# offline at once it could stall the whole worker pool. This batches all 6
# get_property calls into one SSH connection + one socat session (mpv answers
# each newline-delimited IPC request in order on the same pipe), and uses a
# short connect timeout so an offline machine fails fast instead of dragging
# the default 5s.
_STATUS_PROPS = ['path', 'pause', 'volume', 'mute', 'time-pos', 'duration']
def _mpv_status_batch(host, user):
    reqs = ' '.join("'" + json.dumps({'command': ['get_property', p]}) + "'" for p in _STATUS_PROPS)
    cmd = f"printf '%s\\n' {reqs} | socat - UNIX-CONNECT:/run/campus-player/mpv.sock 2>/dev/null"
    # Short connect timeout on purpose: this fires every 5s per campus, in
    # parallel across up to a dozen campuses inside one browser fetch — an
    # offline one only needs to fail fast, not get the generous timeout a
    # real play/stop command gets, or it drags the whole batched response
    # past the frontend's own abort timeout and blanks every campus card,
    # not just the offline one.
    r = ssh_run_on(host, user, cmd, key=None, timeout=6, connect_timeout=4)
    out = {}
    if not r['ok']:
        return dict.fromkeys(_STATUS_PROPS)
    lines = (r.get('data') or '').splitlines()
    for prop, line in zip(_STATUS_PROPS, lines):
        try:
            out[prop] = json.loads(line).get('data')
        except Exception:
            out[prop] = None
    for prop in _STATUS_PROPS:
        out.setdefault(prop, None)
    return out

# ── API ───────────────────────────────────────────
def _status_for_machine(machine):
    if machine != 'client1':
        m = next((x for x in MACHINES
                  if x.get('host') and x['host'] != CLIENT1_HOST and
                     (x.get('user','') == machine or x['host'].endswith(machine))), None)
        if m:
            host, user = m['host'], m.get('user', CLIENT1_USER)
            vals   = _mpv_status_batch(host, user)
            path   = vals['path']
            paused = vals['pause']
            vol    = vals['volume']
            muted  = vals['mute']
            pos    = vals['time-pos']
            dur    = vals['duration']
            # A live mpv always answers `pause`/`volume` even when idle — if
            # every property came back None, the machine is unreachable or
            # the player service isn't running there, not just "not playing"
            if path is None and paused is None and vol is None:
                offline_err = _get_last_error(machine) or 'Кампус не отвечает (плеер недоступен по сети)'
                return {'playing': False, 'track': None, 'online': False,
                        'error': 'offline', 'last_error': offline_err}
            raw_name = os.path.basename(path) if path else None
            if raw_name and raw_name.lower() in ('in.mp3','in.wav','in.ogg'):
                with get_db() as c:
                    last = c.execute(
                        "SELECT track_name,played_at,username FROM play_log "
                        "WHERE played_at LIKE ? ORDER BY id DESC LIMIT 1",
                        (datetime.now().strftime('%Y-%m-%d')+'%',)
                    ).fetchone()
                raw_name = last['track_name'] if last else raw_name
            return {'playing': bool(path) and not paused, 'track': raw_name,
                    'paused': bool(paused), 'muted': bool(muted), 'online': True,
                    'volume': round(vol) if vol is not None else None,
                    'position': round(pos, 1) if pos is not None else None,
                    'duration': round(dur, 1) if dur is not None else None,
                    'last_error': _get_last_error(machine)}
        return {'playing': False, 'track': None, 'online': False, 'error': 'not found'}

    # Was 6 separate SSH connections (one per property via mpv_get) — every
    # other campus already reads all properties in ONE connection via
    # _mpv_status_batch. Six sequential fresh SSH handshakes per poll is
    # slow enough that some would time out while others succeeded, giving
    # inconsistent partial reads (volume present, path/duration missing) —
    # exactly what "actually playing but the player shows nothing" looks
    # like. client1 gets the same fast, consistent single round trip now.
    _vals    = _mpv_status_batch(CLIENT1_HOST, CLIENT1_USER)
    path     = _vals['path']
    vol      = _vals['volume']
    paused   = _vals['pause']
    muted    = _vals['mute']
    pos      = _vals['time-pos']
    dur      = _vals['duration']
    with get_db() as c:
        last = c.execute(
            'SELECT username, track_name, played_at FROM play_log ORDER BY id DESC LIMIT 1'
        ).fetchone()
    raw_name = os.path.basename(path) if path else None
    display_name = raw_name
    display_by   = last['username']   if last else None
    display_at   = last['played_at']  if last else None
    if raw_name and raw_name.lower() in ('in.mp3', 'in.wav', 'in.ogg'):
        # client1 cron copies any track to in.mp3; determine actual track by comparing
        # the most recent action.log cron entry vs the most recent webui play_log entry.
        cron_t, cron_dt = _last_cron_track(CLIENT1_HOST, CLIENT1_USER, '/home/client1/action.log', 'client1')
        pl_dt = None
        if last:
            try:
                pl_dt = datetime.strptime(last['played_at'], '%Y-%m-%d %H:%M:%S')
            except Exception:
                pass
        if cron_t and cron_dt and (pl_dt is None or cron_dt >= pl_dt):
            display_name = cron_t
            display_by   = 'cron'
            display_at   = cron_dt.strftime('%Y-%m-%d %H:%M:%S')
        elif last:
            display_name = last['track_name']
            display_by   = last['username']
            display_at   = last['played_at']
        elif cron_t:
            display_name = cron_t
            display_by   = 'cron'
            display_at   = None
        else:
            display_name = raw_name
            display_by   = None
            display_at   = None
    return {
        'reachable':  not (path is None and paused is None and vol is None),   # для индикатора «В ЭФИРЕ»
        'playing':    bool(path) and not paused,
        'track':      display_name,
        'volume':     round(vol) if vol is not None else None,
        'paused':     bool(paused),
        'muted':      bool(muted),
        'last_by':    display_by,
        'last_at':    display_at,
        'last_track': display_name,
        'position':   round(pos, 1) if pos is not None else None,
        'duration':   round(dur, 1) if dur is not None else None,
        'last_error': _get_last_error('client1'),
    }

@app.route('/api/status')
@login_required
def api_status():
    machine = request.args.get('machine', 'client1')
    return jsonify(_status_for_machine(machine))

_FLEET_CACHE = {'ts': 0.0, 'data': None}
_FLEET_LOCK = threading.Lock()

def _fleet_compute():
    """Опрос всех кампусов параллельно (5–8 с, пока оффлайн-кампусы не отвалятся по таймауту SSH)."""
    from concurrent.futures import ThreadPoolExecutor
    keys = ['client1'] + [_campus_key(m) for m in music_machines() if m['host'] != CLIENT1_HOST]
    keys = list(dict.fromkeys(keys))  # de-dupe, preserve order
    result = {}
    with ThreadPoolExecutor(max_workers=max(1, len(keys))) as ex:
        futs = {ex.submit(_status_for_machine, k): k for k in keys}
        for fut, k in futs.items():
            try:
                result[k] = fut.result()
            except Exception as e:
                result[k] = {'playing': False, 'track': None, 'online': False, 'error': str(e)}
    return result

def _fleet_store(started, data):
    if started >= _FLEET_CACHE['ts']:
        _FLEET_CACHE['data'], _FLEET_CACHE['ts'] = data, started

def _fleet_status_all(max_age=0):
    """max_age=0 (опрос плиток /api/status-all) — всегда считает заново и НИКОГДА не ждёт других запросов: раньше общая
    блокировка выстраивала опросы в очередь (расчёт ~8 с, опрос раз в 5 с), запросы упирались в 15-секундный таймаут браузера
    и онлайн-кампусы ошибочно краснели. max_age>0 (/api/fleet-status для лампочки в шапке) берёт свежий кэш; если кэш
    устарел и его уже обновляет другой запрос — отдаёт последнее известное, а не встаёт в очередь."""
    c = _FLEET_CACHE
    if not max_age:
        started = time.time()
        data = _fleet_compute()
        _fleet_store(started, data)
        return data
    if c['data'] is not None and time.time() - c['ts'] < max_age:
        return c['data']
    if not _FLEET_LOCK.acquire(blocking=False):
        if c['data'] is not None:
            return c['data']
        _FLEET_LOCK.acquire()            # самый первый запрос после старта — кэша ещё нет, ждём
    try:
        if c['data'] is not None and time.time() - c['ts'] < max_age:
            return c['data']
        started = time.time()
        data = _fleet_compute()
        _fleet_store(started, data)
        return data
    finally:
        _FLEET_LOCK.release()

@app.route('/api/status-all')
@login_required
def api_status_all():
    # One request instead of one-per-campus — browsers cap concurrent HTTP/1.1
    # connections to a single origin at ~6, so polling ~10+ campuses every
    # few seconds as separate fetches queues up client-side and can starve
    # OTHER clicks (Стоп included) behind that queue. Querying every campus
    # here, in parallel server-side threads, and returning one combined
    # payload keeps the browser to a single request per poll tick.
    return jsonify(_fleet_status_all())

@app.route('/api/fleet-status')
@login_required
def api_fleet_status():
    """Сводка для лампочки «В ЭФИРЕ» в шапке (есть на каждой странице).
    fleet: green — все кампусы на связи, yellow — часть оффлайн, red — ни один не отвечает; air — кто-то играет.
    lamps: лампочка каждого кампуса — green (на связи), yellow (на связи, но пауза/без звука), red (оффлайн)."""
    data = _fleet_status_all(max_age=9)
    total = len(data)
    online = sum(1 for d in data.values() if d.get('online', d.get('reachable', True)))
    playing = sum(1 for d in data.values() if d.get('playing'))
    fleet = 'red' if total and online == 0 else ('yellow' if online < total else 'green')
    lamps = {}
    for k, d in data.items():
        if not d.get('online', d.get('reachable', True)):
            lamps[k] = 'red'
        else:
            lamps[k] = 'yellow' if (d.get('paused') or d.get('muted')) else 'green'
    return jsonify({'fleet': fleet, 'online': online, 'total': total, 'playing': playing, 'air': playing > 0, 'lamps': lamps})

def _mpv_stop_on(host, user):
    # 1. Graceful IPC stop: mpv stays alive (systemd won't restart), clears playlist.
    # 2. Kill remaining audio tools (ffmpeg announces, edge-tts TTS, bells).
    # Avoid pkill mpv: killing mpv causes systemd Restart=always to relaunch it,
    # which looks like "stop didn't work" — the IPC stop is instant and cleaner.
    # Retries once on a failed SSH attempt (transient network hiccups are common
    # on this fleet) instead of silently doing nothing — a "panic button" that
    # sometimes no-ops without telling anyone is worse than a slightly slower one.
    cmd = (
        f'printf \'{{"command":["stop"]}}\\n\' | socat - {MPV_SOCK} 2>/dev/null || true; '
        f'printf \'{{"command":["playlist-clear"]}}\\n\' | socat - {MPV_SOCK} 2>/dev/null || true; '
        'pkill -9 ffmpeg  2>/dev/null || true; '
        'pkill -9 aplay   2>/dev/null || true; '
        'pkill -9 paplay  2>/dev/null || true; '
        'pkill -9 edge-tts 2>/dev/null || true; '
        'pkill -9 mplayer 2>/dev/null || true; '
        'pkill -9 vlc     2>/dev/null || true; '
        'pkill -9 cvlc    2>/dev/null || true; '
        'pkill -9 play    2>/dev/null || true; '
        'pkill -9 festival 2>/dev/null || true; true')
        # NOTE: deliberately NOT doing `fuser -k /dev/snd/*` here. On every
        # campus in this fleet mpv plays through --ao=pulse, so /dev/snd is
        # held by PulseAudio, not by mpv or the helper tools above — fuser -k
        # was killing the PulseAudio *server* itself on every stop press.
        # mpv's own connection to it doesn't recover, so the very next play
        # attempt reports "success" but produces no audio (server gone).
        # Confirmed this is what silently broke playback on wctk (Ağ-Şəhər)
        # in production. The IPC "stop" above already fully releases the
        # stream (verified via `pactl list short sink-inputs` going empty),
        # so the device is freed without touching the audio server at all.
    # Up to 4 attempts, not 2 — measured campuses like Ağ-Şəhər can take
    # 3-7s for even a trivial SSH round trip, so a single retry sometimes
    # wasn't enough to ride out a slow moment on that link. A panic button
    # that occasionally needs the user to click it 3-4 times themselves is
    # not "working" — better the server keeps trying automatically.
    r = None
    for _attempt in range(4):
        r = ssh_run_on(host, user, cmd, timeout=8)
        if r.get('ok'):
            break
    return r

def _mpv_stop_on_tracked(machine_id, host, user):
    """Same as _mpv_stop_on, but records the real reason in _last_error when
    both attempts fail — a stop button that silently does nothing is exactly
    the kind of failure that needs to be visible, not swallowed."""
    r = _mpv_stop_on(host, user)
    if r.get('ok'):
        _clear_last_error(machine_id)
    else:
        _set_last_error(machine_id, f"Не удалось остановить: {r.get('error') or 'нет связи с кампусом'}")

@app.route('/api/pause', methods=['POST'])
@login_required
def api_pause():
    if not has_perm('stop'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data   = request.get_json() or {}
    machine = data.get('machine', 'client1')
    action  = data.get('action', 'toggle')  # 'play'→unpause, 'pause'→pause, 'toggle'→cycle
    if action == 'play':
        cmd = {'command': ['set_property', 'pause', False]}
    elif action == 'pause':
        cmd = {'command': ['set_property', 'pause', True]}
    else:
        cmd = {'command': ['cycle', 'pause']}
    if machine == 'client1':
        r = mpv_cmd(cmd)
    else:
        m = _resolve_machine(machine, strict=True)
        if not m:
            return jsonify({'ok': False, 'error': 'машина не настроена'})
        r = mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cmd)
    log_action(current_user.username, 'pause', machine)
    return jsonify(r if isinstance(r, dict) else {'ok': True})

def _stop_all_campuses(username):
    """The one real panic-stop implementation — fires every campus in
    parallel via the safe mpv-IPC stop (no pkill -9, doesn't kill the mpv
    process itself, just releases the current stream) and returns instantly
    instead of waiting on the slowest campus's SSH round-trip. Shared by the
    web '/api/stop' button and the Telegram bot's '⏹ Стоп' so both actually
    stop EVERY campus, not just whichever one happens to be SSH-reachable
    fastest or "active" in a chat."""
    for m in music_machines():
        # Invalidate any in-flight play (e.g. a slow SFTP upload for a track
        # not yet synced locally) so it can't "resurrect" playback moments
        # after this stop, once its upload finally finishes.
        _bump_play_gen(_campus_key(m))
        threading.Thread(
            target=_mpv_stop_on_tracked, args=(_campus_key(m), m['host'], m.get('user', CLIENT1_USER)), daemon=True
        ).start()
    log_action(username, 'stop', 'all')
    tg_notify(
        f'⏹ <b>СТОП — остановлено всё, на всех кампусах</b>\n'
        f'👤 {username}\n'
        f'🕐 {_tg_fmt_time()}',
        event_type='stop'
    )

@app.route('/api/stop', methods=['POST'])
@login_required
def api_stop():
    if not has_perm('stop'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    _stop_all_campuses(current_user.username)
    return jsonify({'ok': True})

BOT_STOP_TOKEN = os.environ.get('BOT_STOP_TOKEN', '')

@app.route('/api/stop-bot', methods=['POST'])
def api_stop_bot():
    """Same global panic-stop as the web '⏹ Стоп' button, callable by the
    Telegram bot (which has no browser session) via a shared secret token
    instead of @login_required. The bot's own '/stop' used to only hit
    whichever single campus was "active" for that chat, via the old
    campus-playerctl (pkill -9 mpv) path — this makes Telegram parity with
    the web button: every campus, every time, the safe way."""
    token = request.headers.get('X-Bot-Token') or (request.get_json(silent=True) or {}).get('token')
    if not BOT_STOP_TOKEN or token != BOT_STOP_TOKEN:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    who = (request.get_json(silent=True) or {}).get('username') or 'telegram-bot'
    _stop_all_campuses(who)
    return jsonify({'ok': True})

@app.route('/api/stop/<machine>', methods=['POST'])
@login_required
def api_stop_machine(machine):
    if not has_perm('stop'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    if machine == 'client1':
        host, user = CLIENT1_HOST, CLIENT1_USER
        mid = 'client1'
    else:
        m = _resolve_machine(machine, strict=True)
        if not m:
            return jsonify({'ok': False, 'error': 'машина не настроена'})
        host, user = m['host'], m.get('user', CLIENT1_USER)
        mid = m.get('user', machine)
    # Invalidate any in-flight play on this machine so a slow background
    # SFTP upload can't resurrect playback after the user has stopped it.
    _bump_play_gen(mid)
    # Fire-and-forget, same as the global panic-stop — the button should feel
    # instant, not wait on an SSH round-trip that may itself be retrying.
    threading.Thread(target=_mpv_stop_on_tracked, args=(mid, host, user), daemon=True).start()
    log_action(current_user.username, 'stop', machine)
    return jsonify({'ok': True})

@app.route('/api/seek', methods=['POST'])
@login_required
def api_seek():
    if not has_perm('stop'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data    = request.get_json(silent=True) or {}
    machine = data.get('machine', 'client1')
    pos     = float(data.get('pos', 0))
    if machine == 'client1':
        mpv_set('time-pos', pos)
    else:
        m = next((x for x in MACHINES if x.get('user', '') == machine or
                  x['host'].endswith(machine)), None)
        if m:
            mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER),
                       {'command': ['set_property', 'time-pos', pos]})
    return jsonify({'ok': True})

HIMN_CLIENT1 = '/mnt/music/Media/1/HIMN.mp3'
HIMN_CLIENT2  = '/home/client2/Media/1/himn.mp3'
HIMN_CGTK = '/home/cgtk/Media/1/himn.mp3'
# Any other campus (including ones added later via /machines): same
# convention as client2/cgtk — himn.mp3 inside folder "1" of its Media root.
def _himn_path_for(campus):
    if campus == 'client1':
        return HIMN_CLIENT1
    if campus == 'client2':
        return HIMN_CLIENT2
    if campus == 'cgtk':
        return HIMN_CGTK
    return _music_path_for(campus).rstrip('/') + '/1/himn.mp3'

# ── "Минута молчания" — специальный файл вне ротации Media, прямой IPC ─────
# (не через campus-playerctl: у него play игнорирует громкость молча —
# известный баг, здесь используем тот же безопасный сокет-путь, что и крон).
MINUTA_PATHS = {
    'client1': '/home/client1/special/minuta_molchaniya.mp3',
    'client2':  '/home/client2/special/minuta_molchaniya.mp3',
    'cgtk': '/home/cgtk/special/minuta_molchaniya.mp3',
}
MINUTA_VOL = 150

# Adjustable volume for the special-action buttons (Гимн/Минута/Тревога) —
# stored in `settings` (same key-value table silence_mode/wallpaper_default
# already use), so a slider on the page actually persists and actually
# takes effect on the very next play, not just a cosmetic UI value.
_SPECIAL_VOL_DEFAULTS = {'himn': 150, 'minuta': MINUTA_VOL, 'alarm': 155}
_SPECIAL_VOL_KEYS = ('himn', 'minuta', 'alarm')

def _get_special_vol(kind):
    default = _SPECIAL_VOL_DEFAULTS.get(kind, 100)
    try:
        with get_db() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (f'vol_{kind}',)).fetchone()
        if row and row['value']:
            return max(0, min(160, int(row['value'])))
    except Exception:
        pass
    return default

def _set_special_vol(kind, value):
    value = max(0, min(160, int(value)))
    with get_db() as c:
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (f'vol_{kind}', str(value)))
    return value

@app.route('/api/special-vol', methods=['GET'])
@login_required
def api_special_vol_get():
    return jsonify({'ok': True, **{k: _get_special_vol(k) for k in _SPECIAL_VOL_KEYS}})

@app.route('/api/special-vol/<kind>', methods=['POST'])
@login_required
def api_special_vol_set(kind):
    if not has_perm('special_volume'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    if kind not in _SPECIAL_VOL_KEYS:
        return jsonify({'ok': False, 'error': 'Неизвестный параметр'}), 400
    data = request.get_json(silent=True) or {}
    try:
        val = int(data.get('value'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Некорректное значение'})
    val = _set_special_vol(kind, val)
    log_action(current_user.username, 'set_vol', kind, str(val))
    return jsonify({'ok': True, 'value': val})

def _play_via_ipc(host, user, filepath, vol, loop=False):
    # `pause` is a sticky mpv property — it does NOT reset on loadfile, so if
    # anything earlier left the player paused (a manual pause click, a prior
    # stop, whatever), every play here would silently load-but-sit-paused:
    # volume right, file right, device right, zero sound. Explicitly force
    # pause off, both before and after loadfile (some mpv builds apply a
    # queued loadfile before honoring a property set sent just ahead of it).
    file_esc = filepath.replace('\\', '\\\\').replace('"', '\\"')
    loop_val = '"inf"' if loop else 'false'
    # 2026-09-20 — «Минута/Гимн/Тревога хрипят». Две причины, обе про громкость ПОТОКА PulseAudio (отдельную от громкости mpv):
    #  1) в новом mpv (>= 0.18.1; Клиент 1 — 0.34) `volume` — внутренний микшер (куб от процента: 150 → +10.6 dB). Прежний код
    #     дополнительно ставил потоку `pactl ... {vol}%` — второе такое же усиление сверху; теперь поток держим на 100%.
    #     Только для СТАРОГО mpv (< 0.18.1, Ağ-Şəhər 0.14: там громкость mpv = громкость потока) прежнее поведение сохранено.
    #  2) PulseAudio (module-stream-restore) выдаёт каждому НОВОМУ потоку «mpv Media Player» громкость, запомненную с прошлого
    #     раза (после прежних запусков — 150%). Поэтому файл грузим НА ПАУЗЕ, выставляем потоку нужную громкость ДО первого
    #     звука и только потом снимаем паузу (иначе первые секунды идут с +10 dB поверх — слышно как хрип).
    cmd = (
        'SOCK=/run/campus-player/mpv.sock; '
        f'[ -S "$SOCK" ] || {{ echo "no socket"; exit 1; }}; '
        f'[ -f "{filepath}" ] || {{ echo "no file"; exit 1; }}; '
        f'MPVV=$(mpv --version 2>/dev/null | head -1 | awk \'{{print $2}}\' | sed \'s/^v//\'); '
        f'if [ -n "$MPVV" ] && [ "$MPVV" != "0.18.1" ] && [ "$(printf \'%s\\n0.18.1\\n\' "$MPVV" | sort -V | head -1)" = "$MPVV" ]; then PCT={vol}; else PCT=100; fi; '
        f'fixvol() {{ PAID=$(pactl list short sink-inputs 2>/dev/null | head -1 | cut -f1); [ -n "$PAID" ] && pactl set-sink-input-volume "$PAID" ${{PCT}}% >/dev/null 2>&1; }}; '
        f'echo \'{{"command":["set_property","volume",{vol}]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; '
        f'echo \'{{"command":["set_property","loop-file",{loop_val}]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; '
        # pause — «липкое» свойство mpv (см. комментарий выше): ставим true на время загрузки, дальше ОБЯЗАТЕЛЬНО снимаем
        f'echo \'{{"command":["set_property","pause",true]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; '
        f'echo \'{{"command":["loadfile","{file_esc}","replace"]}}\' | socat - UNIX-CONNECT:"$SOCK"; '
        # ждём, пока mpv создаст поток (на паузе он «corked»), и выставляем его громкость до первого звука
        f'for i in 1 2 3 4 5 6 7 8 9 10 11 12; do sleep 0.2; [ -n "$(pactl list short sink-inputs 2>/dev/null | head -1)" ] && break; done; '
        f'fixvol; '
        f'echo \'{{"command":["set_property","pause",false]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; '
        f'sleep 0.4; fixvol; '
        f'echo \'{{"command":["set_property","volume",{vol}]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; '
        f'echo \'{{"command":["set_property","pause",false]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; '
        f'sleep 1.0; fixvol; true'
    )
    return ssh_run_on(host, user, cmd, timeout=10)

def _play_himn(host, user, filepath, vol):
    return _play_via_ipc(host, user, filepath, vol)

def _log_himn_play(username, machine, filename):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_action(username, 'himn', machine, filename)
    # also write to play_log so it shows in history
    with get_db() as c:
        c.execute('INSERT INTO play_log (username, track_name, played_at) VALUES (?,?,?)',
                  (username, f'[гимн] {filename}', ts))

@app.route('/api/himn/<campus>', methods=['POST'])
@login_required
def api_himn(campus):
    if not has_perm('himn'):
        return jsonify({'ok': False, 'error': 'Нет прав на гимн'})
    if not _is_known_campus(campus):
        return jsonify({'ok': False, 'error': 'Неизвестный кампус'}), 400
    host, user = _machine_ssh(campus)
    if not host:
        return jsonify({'ok': False, 'error': f'{campus} не подключен'})
    vol = _get_special_vol('himn')
    filepath = _himn_path_for(campus)
    # Special actions (Гимн/Минута/Тревога/Zəfər) never bumped the play
    # generation before — a regular track click still "in flight" (slow
    # SFTP upload, checked against this counter in _play_track_on) could
    # land its loadfile AFTER this one and silently replace/kill it a
    # moment later, looking exactly like "this button doesn't work" even
    # though it genuinely started playing first.
    _bump_play_gen(campus)
    r = _play_himn(host, user, filepath, vol)
    ok = r['ok'] and 'no socket' not in (r.get('data') or '') and 'no file' not in (r.get('data') or '')
    if ok:
        _log_himn_play(current_user.username, campus, os.path.basename(filepath))
        tg_notify(
            f'🎼 <b>Государственный гимн</b>\n'
            f'🏫 Кампус: <b>{_MINUTA_LABEL.get(campus, campus)}</b>\n'
            f'👤 Запустил: <b>{current_user.username}</b>\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='himn'
        )
    err = r.get('error') or r.get('data') or 'ошибка воспроизведения'
    return jsonify({'ok': ok, 'error': None if ok else err})

_MINUTA_LABEL_FALLBACK = {'client1': 'Client1'}
class _CampusLabelDict(dict):
    """Same .get(campus, campus) call sites as before, but resolves any
    campus added later via /machines to its real display name instead of
    falling back to the raw slug."""
    def get(self, campus, default=None):
        if campus in _MINUTA_LABEL_FALLBACK:
            return _MINUTA_LABEL_FALLBACK[campus]
        m = _resolve_machine(campus, strict=True)
        return (m and m.get('name')) or default
_MINUTA_LABEL = _CampusLabelDict()

@app.route('/api/minuta/<campus>', methods=['POST'])
@login_required
def api_minuta(campus):
    if not has_perm('minuta'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    if not _is_known_campus(campus):
        return jsonify({'ok': False, 'error': 'Неизвестный кампус'}), 400
    host, user = _machine_ssh(campus)
    if not host:
        return jsonify({'ok': False, 'error': f'{campus} не подключен'})
    filepath = MINUTA_PATHS.get(campus, f'/home/{user}/special/minuta_molchaniya.mp3')
    _bump_play_gen(campus)
    r = _play_via_ipc(host, user, filepath, _get_special_vol('minuta'))
    if r['ok'] and 'no socket' not in (r.get('data') or '') and 'no file' not in (r.get('data') or ''):
        log_action(current_user.username, 'minuta', campus, 'Минута молчания')
        tg_notify(
            f'🕯 <b>Минута молчания</b>\n'
            f'🏫 Кампус: <b>{_MINUTA_LABEL.get(campus, campus)}</b>\n'
            f'👤 Запустил: <b>{current_user.username}</b>\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='minuta'
        )
        return jsonify({'ok': True})
    err = r.get('error') or r.get('data') or 'ошибка воспроизведения'
    return jsonify({'ok': False, 'error': err})

# ── "Тревога" — набор звуков-сирен, живёт как файлы вне ротации Media.
# Библиотека звуков лежит централизованно на сервере webui (alarm_sounds/);
# при первом проигрывании на кампусе файл сам подтягивается по SFTP и
# кешируется там же — повторные вызовы того же звука уже не грузят SFTP.
# Играет в цикле (loop-file=inf), пока кто-то не нажмёт обычный STOP —
# тот же mpv "stop" по IPC, что останавливает любое другое воспроизведение.
ALARM_DIR  = os.environ.get('ALARM_SOUNDS_DIR', '/data/alarm_sounds')
ALARM_VOL  = 155
_ALARM_EXTS = ('.mp3', '.wav', '.ogg', '.m4a')

def _list_alarm_sounds():
    if not os.path.isdir(ALARM_DIR):
        return []
    return sorted(f for f in os.listdir(ALARM_DIR) if f.lower().endswith(_ALARM_EXTS))

def _push_and_play_special(host, user, local_path, remote_path, vol, loop=False):
    """Push a centrally-stored file to a campus (only if missing/stale there)
    and play it — same lazy-SFTP-on-first-play pattern as alarm sounds, but
    generalized so any one-off "special" track (Zəfər Günü, a swapped-in
    himn/minuta file, etc.) can reuse it instead of requiring the file to
    already be sitting on the campus's disk ahead of time."""
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        s.connect(host, username=user, key_filename=SSH_KEY, timeout=8)
        local_sz = os.path.getsize(local_path)
        _, chk, _ = s.exec_command(
            f'stat -c%s "{remote_path}" 2>/dev/null || echo 0', timeout=5)
        remote_sz = (chk.read().decode().strip() or '0')
        if remote_sz != str(local_sz):
            s.exec_command(f"mkdir -p \"$(dirname '{remote_path}')\"", timeout=5)
            sftp = s.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
    finally:
        s.close()
    return _play_via_ipc(host, user, remote_path, vol, loop=loop)

def _push_and_play_alarm(host, user, fname, vol):
    local_path  = os.path.join(ALARM_DIR, fname)
    remote_path = f'/home/{user}/special/alarm_{fname}'
    return _push_and_play_special(host, user, local_path, remote_path, vol, loop=True)

@app.route('/api/alarm/sounds')
@login_required
def api_alarm_sounds():
    return jsonify({'ok': True, 'sounds': _list_alarm_sounds()})

@app.route('/api/alarm/<campus>', methods=['POST'])
@login_required
def api_alarm(campus):
    if not has_perm('alarm'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    if not _is_known_campus(campus):
        return jsonify({'ok': False, 'error': 'Неизвестный кампус'}), 400
    sounds = _list_alarm_sounds()
    if not sounds:
        return jsonify({'ok': False, 'error': 'Звуки тревоги ещё не загружены'})
    fname = os.path.basename((request.get_json(silent=True) or {}).get('sound', ''))
    if fname not in sounds:
        fname = sounds[0]
    host, user = _machine_ssh(campus)
    if not host:
        return jsonify({'ok': False, 'error': f'{campus} не подключен'})
    try:
        _bump_play_gen(campus)
        r = _push_and_play_alarm(host, user, fname, _get_special_vol('alarm'))
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})
    if r['ok'] and 'no socket' not in (r.get('data') or '') and 'no file' not in (r.get('data') or ''):
        log_action(current_user.username, 'alarm', campus, fname)
        tg_notify(
            f'🚨 <b>ТРЕВОГА</b>\n'
            f'🏫 Кампус: <b>{_MINUTA_LABEL.get(campus, campus)}</b>\n'
            f'🔊 Звук: <b>{fname}</b>\n'
            f'👤 Запустил: <b>{current_user.username}</b>\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='alarm'
        )
        return jsonify({'ok': True, 'sound': fname})
    err = r.get('error') or r.get('data') or 'ошибка воспроизведения'
    return jsonify({'ok': False, 'error': err})

# ── "Zəfər Günü" (8 noyabr) — центрально хранимый трек, разносится по
# кампусам лениво (при первом проигрывании), тем же путём что и alarm —
# не нужно вручную копировать файл на каждую новую/будущую машину.
ZEFER_FILE = os.path.join(os.environ.get('SPECIAL_SOUNDS_DIR', '/data/special_sounds'), 'zefer_gunu.mp3')
ZEFER_VOL  = 100
ZEFER_CRON_TOKEN = os.environ.get('ZEFER_CRON_TOKEN', '')

def _play_zefer(host, user):
    remote_path = f'/home/{user}/special/zefer_gunu.mp3'
    return _push_and_play_special(host, user, ZEFER_FILE, remote_path, ZEFER_VOL, loop=False)

@app.route('/api/zefer/<campus>', methods=['POST'])
@login_required
def api_zefer(campus):
    if not has_perm('special_events'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    if not os.path.isfile(ZEFER_FILE):
        return jsonify({'ok': False, 'error': 'Файл Zəfər Günü ещё не загружен'})
    if not _is_known_campus(campus):
        return jsonify({'ok': False, 'error': 'Неизвестный кампус'}), 400
    host, user = _machine_ssh(campus)
    if not host:
        return jsonify({'ok': False, 'error': f'{campus} не подключен'})
    try:
        _bump_play_gen(campus)
        r = _play_zefer(host, user)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})
    if r['ok'] and 'no socket' not in (r.get('data') or '') and 'no file' not in (r.get('data') or ''):
        log_action(current_user.username, 'zefer', campus, 'zefer_gunu.mp3')
        tg_notify(
            f'🎖 <b>Zəfər Günü</b>\n'
            f'🏫 Кампус: <b>{_MINUTA_LABEL.get(campus, campus)}</b>\n'
            f'👤 Запустил: <b>{current_user.username}</b>\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='zefer'
        )
        return jsonify({'ok': True})
    err = r.get('error') or r.get('data') or 'ошибка воспроизведения'
    return jsonify({'ok': False, 'error': err})


# ── "National Music Day" (18 sentyabr) — тот же централизованный ленивый
# разнос файла по кампусам, что и Zəfər Günü.
NMD_FILE = os.path.join(os.environ.get('SPECIAL_SOUNDS_DIR', '/data/special_sounds'), 'national_music_day.mp3')
NMD_VOL  = 150

def _play_nmd(host, user):
    remote_path = f'/home/{user}/special/national_music_day.mp3'
    return _push_and_play_special(host, user, NMD_FILE, remote_path, NMD_VOL, loop=False)

@app.route('/api/nmd/<campus>', methods=['POST'])
@login_required
def api_nmd(campus):
    if not has_perm('special_events'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    if not os.path.isfile(NMD_FILE):
        return jsonify({'ok': False, 'error': 'Файл National Music Day ещё не загружен'})
    if not _is_known_campus(campus):
        return jsonify({'ok': False, 'error': 'Неизвестный кампус'}), 400
    host, user = _machine_ssh(campus)
    if not host:
        return jsonify({'ok': False, 'error': f'{campus} не подключен'})
    try:
        _bump_play_gen(campus)
        r = _play_nmd(host, user)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})
    if r['ok'] and 'no socket' not in (r.get('data') or '') and 'no file' not in (r.get('data') or ''):
        log_action(current_user.username, 'nmd', campus, 'national_music_day.mp3')
        tg_notify(
            f'🎵 <b>National Music Day</b>\n'
            f'🏫 Кампус: <b>{_MINUTA_LABEL.get(campus, campus)}</b>\n'
            f'👤 Запустил: <b>{current_user.username}</b>\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='nmd'
        )
        return jsonify({'ok': True})
    err = r.get('error') or r.get('data') or 'ошибка воспроизведения'
    return jsonify({'ok': False, 'error': err})

@app.route('/api/zefer-all', methods=['POST'])
def api_zefer_all():
    """Broadcast Zəfər Günü to every registered audio campus. No @login_required —
    this is the endpoint the server's own annual Nov 8 cron job calls (it isn't a
    logged-in browser session), gated instead by a shared secret token so it can't
    be triggered by a random request."""
    token = request.headers.get('X-Cron-Token') or (request.get_json(silent=True) or {}).get('token')
    if not ZEFER_CRON_TOKEN or token != ZEFER_CRON_TOKEN:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    if not os.path.isfile(ZEFER_FILE):
        return jsonify({'ok': False, 'error': 'Файл Zəfər Günü ещё не загружен'})
    results = {}
    for m in music_machines():
        key = _campus_key(m)
        try:
            r = _play_zefer(m['host'], m.get('user', CLIENT1_USER))
            results[key] = bool(r.get('ok') and 'no socket' not in (r.get('data') or '')
                                 and 'no file' not in (r.get('data') or ''))
        except Exception as e:
            results[key] = str(e)
    tg_notify(
        f'🎖 <b>Zəfər Günü — 8 noyabr</b>\n'
        f'Автоматически запущено на всех кампусах по расписанию\n'
        f'🕐 {_tg_fmt_time()}',
        event_type='zefer'
    )
    log_action('cron', 'zefer', 'all', json.dumps(results))
    return jsonify({'ok': True, 'results': results})

@app.route('/api/perem/<campus>/<slot>', methods=['POST'])
@login_required
def api_perem_trigger(campus, slot):
    """Ручной запуск любой перемены/утра/гимна вне расписания — тот же
    скрипт, что запускает cron (campus-cron-media-notify.sh), поэтому
    Telegram-уведомление, папка дня и лог получаются автоматически,
    без дублирования логики здесь."""
    if not has_perm('perem_trigger'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    if slot not in PEREM_SLOTS:
        return jsonify({'ok': False, 'error': 'Неизвестный слот'}), 400
    if not _is_known_campus(campus):
        return jsonify({'ok': False, 'error': 'Неизвестный кампус'}), 400
    host, user = _machine_ssh(campus)
    if not host:
        return jsonify({'ok': False, 'error': f'{campus} не подключен'})
    media = _music_path_for(campus)
    vol = _perem_vol(campus, slot)
    home = f'/home/{campus}'
    cmd = (f'FORCE_PLAY=1 MEDIA_ROOT="{media}" LOG_FILE="{home}/action.log" '
           f'"{home}/campus-cron-media-notify.sh" {slot} {vol}')
    # Скрипт ждёт (play-попытки + фоновые curl в Telegram) — обычному
    # ssh_run_on таймаута в 15с может не хватить, даём больше запаса.
    r = ssh_run_on(host, user, cmd, timeout=25)
    if r['ok']:
        log_action(current_user.username, 'perem', campus, slot)
    return jsonify({'ok': r['ok'], 'error': r.get('error')})

@app.route('/api/perem/slots')
@login_required
def api_perem_slots():
    return jsonify({'ok': True, 'slots': [
        {'id': s, 'label': PEREM_SLOT_LABELS.get(s, s)} for s in PEREM_SLOTS
    ]})

@app.route('/api/perem/schedule')
@login_required
def api_perem_schedule_get():
    if not has_perm('perem_edit'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    out = {}
    for _m in music_machines():
        campus = 'client1' if _m['host'] == CLIENT1_HOST else (_m.get('user') or _m['id'])
        host, user = _machine_ssh(campus)
        if not host:
            out[campus] = {'ok': False, 'error': 'не подключен'}
            continue
        r = ssh_run_on(host, user, 'crontab -l 2>/dev/null', timeout=10)
        if not r['ok']:
            out[campus] = {'ok': False, 'error': r.get('error')}
            continue
        lines = r['data'].split('\n')
        slots = {}
        for slot in PEREM_SLOTS:
            si, ei = _crontab_find_slot_lines(lines, slot)
            if si is None:
                continue
            slots[slot] = {
                'start': _crontab_parse_time(lines[si]),
                'vol':   _crontab_parse_vol(lines[si]),
                'stop':  _crontab_parse_time(lines[ei]) if ei is not None else None,
            }
        out[campus] = {'ok': True, 'slots': slots}
    return jsonify({'ok': True, 'campuses': out})

@app.route('/api/perem/schedule/<campus>/<slot>', methods=['POST'])
@login_required
def api_perem_schedule_edit(campus, slot):
    if not has_perm('perem_edit'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    if not _is_known_campus(campus):
        return jsonify({'ok': False, 'error': 'Неизвестный кампус'}), 400
    if slot not in PEREM_SLOTS:
        return jsonify({'ok': False, 'error': 'Неизвестный слот'}), 400

    data = request.get_json() or {}
    new_start = (data.get('start') or '').strip()
    new_stop  = (data.get('stop') or '').strip()
    try:
        new_vol = int(data.get('vol'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Некорректная громкость'})
    if not _HHMM_RE.match(new_start) or not _HHMM_RE.match(new_stop):
        return jsonify({'ok': False, 'error': 'Время в формате ЧЧ:ММ'})
    if not (0 <= new_vol <= 160):
        return jsonify({'ok': False, 'error': 'Громкость должна быть 0–160'})
    sh, sm = (int(x) for x in new_start.split(':'))
    th, tm = (int(x) for x in new_stop.split(':'))

    host, user = _machine_ssh(campus)
    if not host:
        return jsonify({'ok': False, 'error': f'{campus} не подключен'})
    r = ssh_run_on(host, user, 'crontab -l 2>/dev/null', timeout=10)
    if not r['ok']:
        return jsonify({'ok': False, 'error': r.get('error') or 'не удалось прочитать crontab'})
    lines = r['data'].split('\n')
    si, ei = _crontab_find_slot_lines(lines, slot)
    if si is None:
        return jsonify({'ok': False, 'error': 'Слот не найден в crontab этой машины'})

    old_start = _crontab_parse_time(lines[si])
    old_vol   = _crontab_parse_vol(lines[si])
    old_stop  = _crontab_parse_time(lines[ei]) if ei is not None else None

    lines[si] = _crontab_replace_time_and_vol(lines[si], sh, sm, new_vol)
    if ei is not None:
        lines[ei] = _crontab_replace_time(lines[ei], th, tm)

    new_content = '\n'.join(lines) + '\n'
    r2 = _crontab_push(host, user, new_content)
    if not r2['ok'] or 'INSTALLED' not in (r2.get('data') or ''):
        return jsonify({'ok': False, 'error': r2.get('error') or 'не удалось применить crontab'})

    # Репо-копия — best-effort, чтобы не разъезжалась с реальной машиной
    try:
        repo_path = os.path.join(os.path.dirname(__file__), '..', 'machines', campus, 'crontab')
        if os.path.exists(repo_path):
            with open(repo_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
    except Exception:
        pass

    label = PEREM_SLOT_LABELS.get(slot, slot)
    campus_label = _MINUTA_LABEL.get(campus, campus)
    detail = (f'{label} [{campus}]: время {old_start}→{new_start}'
              + (f', стоп {old_stop}→{new_stop}' if old_stop else '')
              + f', громкость {old_vol}→{new_vol}')
    log_action(current_user.username, 'perem_schedule_edit', campus, detail)
    tg_notify(
        f'✏️ <b>Изменено расписание звонка</b>\n'
        f'🏫 Кампус: <b>{campus_label}</b>\n'
        f'🔄 {label}\n'
        f'🕐 Время: {old_start} → <b>{new_start}</b>'
        + (f'\n⏹ Стоп: {old_stop} → <b>{new_stop}</b>' if old_stop else '')
        + f'\n🔊 Громкость: {old_vol} → <b>{new_vol}</b>\n'
        f'👤 Изменил: <b>{current_user.username}</b>\n'
        f'🕐 {_tg_fmt_time()}',
        event_type='schedule'
    )
    return jsonify({'ok': True,
                     'old': {'start': old_start, 'stop': old_stop, 'vol': old_vol},
                     'new': {'start': new_start, 'stop': new_stop, 'vol': new_vol}})

@app.route('/api/schedule/toggle-group', methods=['POST'])
@login_required
def api_schedule_toggle_group():
    """Включить/выключить целую группу слотов ('utro' или 'perem' = все
    1..9peremena) СРАЗУ в реальном crontab на всех доступных кампусах —
    и держит декоративный SCHEDULE (виджет «до звонка») в согласии с этим,
    иначе он продолжает показывать то, чего на самом деле уже нет."""
    if not has_perm('schedule_toggle'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data = request.get_json() or {}
    group = data.get('group')
    enable = bool(data.get('enable'))
    if group not in ('utro', 'perem'):
        return jsonify({'ok': False, 'error': 'Неизвестная группа'}), 400

    from concurrent.futures import ThreadPoolExecutor
    def _do_one(m):
        probe = ssh_run_on(m['host'], m.get('user', CLIENT1_USER), 'echo OK', timeout=5, connect_timeout=4)
        if not probe.get('ok'):
            return {'ok': False, 'error': 'offline'}
        return _crontab_toggle_group(m['host'], m.get('user', CLIENT1_USER), group, enable)

    machines = music_machines()
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(machines))) as ex:
        futs = {ex.submit(_do_one, m): m['id'] for m in machines}
        for fut, mid in futs.items():
            try:
                results[mid] = fut.result()
            except Exception as e:
                results[mid] = {'ok': False, 'error': str(e)}

    with _sched_lock:
        changed = False
        for e in SCHEDULE:
            fname = e.get('file', '')
            is_match = (fname == 'utro.mp3') if group == 'utro' else fname.endswith('peremena.mp3')
            if is_match and e.get('play') != enable:
                e['play'] = enable
                changed = True
        if changed:
            save_schedule(SCHEDULE)

    label = 'Утренняя музыка' if group == 'utro' else 'Перемены 1–9'
    log_action(current_user.username, f'toggle_{group}', 'all', 'включено' if enable else 'выключено')
    tg_notify(
        f'{"▶️" if enable else "⏸"} <b>{label}</b> {"включены" if enable else "выключены"} на всех доступных кампусах\n'
        f'👤 {current_user.username}\n🕐 {_tg_fmt_time()}',
        event_type='schedule'
    )
    return jsonify({'ok': True, 'group': group, 'enabled': enable, 'results': results})

# ── Фиксация громкости ───────────────────────────────────────────────
# Раньше «Все → 150» и ползунки один раз отправляли громкость в mpv и всё: оффлайн-кампусы её не получали вообще, а
# у включённых её потом сбрасывали плановые звонки (ставят громкость слота и не возвращают), Гимн/Минута/Тревога и
# перезапуск плеера (стартует со 100) — «через некоторое время каждый хаотично опускается». Теперь выставленное
# значение ЗАПОМИНАЕТСЯ (settings: vol_lock_<кампус>), а сторож раз в ~30 с возвращает его на кампусах, где сейчас
# ничего не играет (звонок/музыка доигрывают на своей громкости; после них громкость возвращается). Оффлайн-кампус
# получит значение, как только появится на связи. Новое ручное значение заменяет старое; снять — /api/volume-lock/clear.
_VOL_LOCK_PREFIX = 'vol_lock_'

def _all_campus_keys():
    keys = ['client1'] + [_campus_key(m) for m in music_machines() if m['host'] != CLIENT1_HOST]
    return list(dict.fromkeys(keys))

def _vol_lock_set(keys, val):
    with get_db() as c:
        for k in keys:
            c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (_VOL_LOCK_PREFIX + k, str(int(val))))

def _vol_lock_all():
    with get_db() as c:
        rows = c.execute("SELECT key,value FROM settings WHERE key LIKE 'vol\\_lock\\_%' ESCAPE '\\'").fetchall()
    out = {}
    for r in rows:
        try:
            out[r['key'][len(_VOL_LOCK_PREFIX):]] = int(r['value'])
        except (TypeError, ValueError):
            pass
    return out

def _volume_guard_apply(key, want):
    cmd = {'command': ['set_property', 'volume', want]}
    if key == 'client1':
        return mpv_cmd(cmd)
    m = _resolve_machine(key, strict=True)
    return mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cmd) if m else {'ok': False}

_volume_guard_started = False

def _volume_guard_tick(st, now=None):
    """Один проход сторожа. Возвращает список действий [(кампус, было, стало, ответил_ли)]."""
    now = now or time.time()
    done = []
    for key, want in _vol_lock_all().items():
        s_ = st.setdefault(key, {'next': 0, 'fails': 0, 'last': 0})
        if now < s_['next']:
            continue
        d = _status_for_machine(key)
        online = d.get('online', d.get('reachable', True))
        if not online:
            s_['next'] = now + 120
            continue
        s_['next'] = now + 30
        vol = d.get('volume')
        if vol is None or d.get('playing'):
            continue                          # играет (звонок/музыка) — не перебиваем
        if abs(vol - want) < 1:
            s_['fails'] = 0
            continue
        if now - s_['last'] < min(60 * (2 ** s_['fails']), 1800):
            continue
        s_['last'] = now
        s_['fails'] += 1                      # сбросится, когда увидим нужное значение
        r = _volume_guard_apply(key, want)
        log_action('system', 'volume_guard', key, f'{round(vol)}→{want} ({"ok" if r.get("ok") else "нет ответа"})')
        done.append((key, round(vol), want, bool(r.get('ok'))))
    return done

def _volume_guard_loop():
    """Возвращает зафиксированную громкость там, где она «уехала». Проверяет только кампусы с фиксацией и только
    по одному лёгкому запросу; оффлайн-кампусы — реже; при неудачах интервал растёт (старый mpv не берёт >100)."""
    st = {}
    time.sleep(45)                       # даём панели подняться
    while True:
        try:
            _volume_guard_tick(st)
        except Exception as e:
            app.logger.warning('volume_guard: %s', e)
        time.sleep(15)

def _start_volume_guard():
    global _volume_guard_started
    if _volume_guard_started:
        return
    _volume_guard_started = True
    threading.Thread(target=_volume_guard_loop, daemon=True, name='volume-guard').start()

@app.route('/api/volume', methods=['POST'])
@login_required
def api_volume():
    if not has_perm('volume'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data = request.get_json() or {}
    val  = max(0, min(160, int(data.get('value', 100))))
    _vol_lock_set(_all_campus_keys(), val)          # «Все → N» фиксирует N на всех кампусах (в т.ч. оффлайн — применится при появлении)
    r = mpv_set_all('volume', val)
    return jsonify({'ok': True, 'applied': bool(r.get('ok')), 'locked': True, 'value': val})

@app.route('/api/volume/<machine>', methods=['POST'])
@login_required
def api_volume_machine(machine):
    if not has_perm('volume'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data = request.get_json() or {}
    val  = max(0, min(160, int(data.get('value', 100))))
    cmd  = {'command': ['set_property', 'volume', val]}
    if machine == 'client1':
        r = mpv_cmd(cmd)
    else:
        m = _resolve_machine(machine, strict=True)
        if not m:
            return jsonify({'ok': False, 'error': f'{machine} не настроен'})
        r = mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cmd)
    _vol_lock_set([machine], val)                   # громкость, выставленная вручную, фиксируется (см. _volume_guard_loop)
    return jsonify({'ok': True, 'applied': bool(r.get('ok')), 'locked': True, 'value': val})

@app.route('/api/volume-lock/clear', methods=['POST'])
@login_required
def api_volume_lock_clear():
    """Снять фиксацию громкости: {"machine": "<ключ кампуса>"} или {"machine": "all"}."""
    if not has_perm('volume'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    m = (request.get_json(silent=True) or {}).get('machine', 'all')
    with get_db() as c:
        if m == 'all':
            c.execute("DELETE FROM settings WHERE key LIKE 'vol\\_lock\\_%' ESCAPE '\\'")
        else:
            c.execute("DELETE FROM settings WHERE key=?", (_VOL_LOCK_PREFIX + m,))
    return jsonify({'ok': True, 'locks': _vol_lock_all()})

@app.route('/api/volume-locks')
@login_required
def api_volume_locks():
    return jsonify({'ok': True, 'locks': _vol_lock_all()})

# ── Equalizer ─────────────────────────────────────────
# 10-band EQ — lavfi chained equalizer (31,62,125,250,500,1k,2k,4k,8k,16kHz)
_eq_state  = {'bands': [0.0] * 10}
_EQ_FREQS  = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

def _eq_af_cmd(bands):
    parts = ','.join(
        f'equalizer=f={_EQ_FREQS[i]}:width_type=o:width=2:g={bands[i]}'
        for i in range(10)
    )
    return {'command': ['af', 'set', f'lavfi=[{parts}]']}

@app.route('/api/eq', methods=['POST'])
@login_required
def api_eq():
    if not has_perm('vol'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data   = request.get_json() or {}
    campus = data.get('campus', 'both')
    raw_bands = data.get('bands', [0]*10)
    bands = [max(-12.0, min(12.0, round(float(v), 1))) for v in raw_bands[:10]]
    while len(bands) < 10:
        bands.append(0.0)
    cmd = _eq_af_cmd(bands)
    _mpv_cmd_to_campus(campus, cmd)
    _eq_state['bands'] = bands
    log_action(current_user.username, 'eq', campus, str(bands))
    return jsonify({'ok': True, 'bands': bands})

@app.route('/api/eq/reset', methods=['POST'])
@login_required
def api_eq_reset():
    if not has_perm('vol'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    campus = (request.get_json() or {}).get('campus', 'both')
    cmd = {'command': ['af', 'set', '']}
    _mpv_cmd_to_campus(campus, cmd)
    _eq_state['bands'] = [0.0] * 10
    return jsonify({'ok': True})

@app.route('/api/eq/state')
@login_required
def api_eq_state():
    return jsonify(_eq_state)

# ── Audio FFT polling (background thread → SSE) ──────────────────────────────
_audio_cache = {'client1': None}
_audio_lock  = threading.Lock()
_audio_thread_started = False

_audio_workers = {}          # ключ кампуса -> поток опроса
_audio_workers_lock = threading.Lock()

def _audio_targets():
    targets = {'client1': (CLIENT1_HOST, CLIENT1_USER)}
    for _m in music_machines():
        if _m['host'] != CLIENT1_HOST:
            targets[_campus_key(_m)] = (_m['host'], _m.get('user', CLIENT1_USER))
    return targets

def _audio_poll_worker(cid):
    """Опрашивает /tmp/campus-audio-level.json ОДНОГО кампуса раз в 100 мс по своему постоянному SSH-соединению.
    Раньше один общий цикл ходил по кампусам по очереди, и каждый оффлайн-кампус (таймаут подключения до 5 с) тормозил
    остальных: данные включённого Клиент 1а обновлялись раз в 10–20 с — визуализатор «замирал». Теперь у каждого кампуса
    свой поток; у оффлайна пауза между попытками растёт (2, 4 … 20 с), поток удаляется, когда кампус убрали из списка."""
    ssh = None
    fails = 0
    try:
        while True:
            tgt = _audio_targets().get(cid)
            if not tgt or not tgt[0]:
                break
            host, user = tgt
            try:
                if not ssh or not ssh.get_transport() or not ssh.get_transport().is_active():
                    try:
                        if ssh:
                            ssh.close()
                    except Exception:
                        pass
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(host, username=user, key_filename=SSH_KEY, timeout=5, banner_timeout=5)
                _, stdout, _ = ssh.exec_command('cat /tmp/campus-audio-level.json', timeout=2)
                data = json.loads(stdout.read())
                with _audio_lock:
                    _audio_cache[cid] = data
                fails = 0
                time.sleep(0.1)
            except Exception:
                with _audio_lock:
                    _audio_cache[cid] = None
                try:
                    if ssh:
                        ssh.close()
                except Exception:
                    pass
                ssh = None
                fails += 1
                time.sleep(min(2 * fails, 20))
    finally:
        try:
            if ssh:
                ssh.close()
        except Exception:
            pass
        with _audio_lock:
            _audio_cache.pop(cid, None)
        with _audio_workers_lock:
            _audio_workers.pop(cid, None)

def _audio_poll_loop():
    """Диспетчер: раз в 10 с сверяет список кампусов и держит по одному потоку опроса на каждый."""
    while True:
        try:
            with _audio_workers_lock:
                for cid in _audio_targets():
                    t = _audio_workers.get(cid)
                    if not t or not t.is_alive():
                        t = threading.Thread(target=_audio_poll_worker, args=(cid,), daemon=True, name=f'audio-{cid}')
                        _audio_workers[cid] = t
                        t.start()
        except Exception as e:
            app.logger.warning('audio poll dispatcher: %s', e)
        time.sleep(10)

def _start_audio_poll_thread():
    global _audio_thread_started
    if _audio_thread_started:
        return
    _audio_thread_started = True
    t = threading.Thread(target=_audio_poll_loop, daemon=True)
    t.start()

@app.route('/api/audio-fft')
@login_required
def api_audio_fft():
    from flask import Response, stream_with_context
    def generate():
        try:
            while True:
                with _audio_lock:
                    snap = {k: v for k, v in _audio_cache.items()}
                yield 'data: ' + json.dumps(snap) + '\n\n'
                time.sleep(0.05)
        except GeneratorExit:
            pass
    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

PLAYER_INBOX = os.environ.get('CLIENT1_INBOX', '/var/lib/campus-player/inbox')

def _play_track_on(host, user, local_path, name, machine_id, username, folder='', my_gen=None):
    """Background worker: SSH/SFTP to campus machine then start mpv playback.

    When the campus machine has the file locally synced, this loads the REST
    of that track's folder (from this track onward, same A-Z order as the
    browser list) as an mpv playlist — so mpv keeps playing the next tracks
    on its own once this one ends, instead of going silent after one track.
    Falls back to the old single-file replace if the folder can't be
    resolved (e.g. only 1 track, or file isn't on the campus machine yet).

    `my_gen`: this request's play-generation snapshot (see _bump_play_gen) —
    checked right before actually issuing loadfile/loadlist. If a newer play
    or a stop landed on this machine while we were busy SFTP-ing (which can
    take 5-30s), we abandon quietly instead of starting playback that the
    user already tried to cancel."""
    s = None
    try:
        if my_gen is not None and _current_play_gen(machine_id) != my_gen:
            return
        media_base = _music_path_for(machine_id)
        relative    = os.path.relpath(local_path, MUSIC_DIR)
        remote_path = os.path.join(media_base, relative)

        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(host, username=user, key_filename=SSH_KEY, timeout=8)

        # Try direct play from campus machine's local path first (instant)
        _, chk, _ = s.exec_command(f'test -f "{remote_path}" && echo y || echo n', timeout=5)
        have_local = chk.read().decode().strip() == 'y'

        # Without this, mpv not running there (crashed, never started, no
        # systemd unit — happened for real on Ağ-Şəhər) just makes every
        # socat call below silently no-op: no exception, no sound, no clue.
        _, sockchk, _ = s.exec_command(f'[ -S "{MPV_SOCK}" ] && echo y || echo n', timeout=5)
        if sockchk.read().decode().strip() != 'y':
            _set_last_error(machine_id, 'Плеер не запущен на кампусе (не найден сокет mpv) — нужен перезапуск службы на месте')
            return

        played_sequence = False
        if have_local and folder:
            folder_tracks = scan_tracks(folder_filter=folder)
            names = [t['name'] for t in folder_tracks]
            start_idx = names.index(name) if name in names else -1
            if start_idx >= 0 and len(folder_tracks) > 1:
                import base64 as _b64, uuid as _uuid
                seq_paths = [
                    os.path.join(media_base, os.path.relpath(t['path'], MUSIC_DIR))
                    for t in folder_tracks[start_idx:]
                ]
                m3u = '#EXTM3U\n' + '\n'.join(seq_paths) + '\n'
                b64 = _b64.b64encode(m3u.encode('utf-8')).decode()
                # Unique filename per request — two people clicking different
                # tracks on the same campus at the same moment must not race
                # on a shared temp file (one write could clobber the other's
                # playlist before its own loadlist reads it back).
                playlist_path = f'/tmp/campus-seq-{_uuid.uuid4().hex}.m3u'
                cmd_j = json.dumps({'command': ['loadlist', playlist_path, 'replace']})
                escaped = cmd_j.replace('"', '\\"')
                # One round trip instead of two: write the m3u and load it in
                # the same remote shell invocation (extra SSH exec_command
                # round trips were making single-track clicks noticeably slower).
                # `pause` is sticky in mpv — loadlist/loadfile don't reset it,
                # so a player left paused by an earlier action would silently
                # load-but-not-play forever. Force it off after loading.
                unpause = f'echo "{{\\"command\\":[\\"set_property\\",\\"pause\\",false]}}" | socat - {MPV_SOCK} 2>/dev/null'
                if my_gen is not None and _current_play_gen(machine_id) != my_gen:
                    return
                _, out, _ = s.exec_command(
                    f"echo '{b64}' | base64 -d > {playlist_path} && "
                    f'echo "{escaped}" | socat - {MPV_SOCK} 2>/dev/null; '
                    f'{unpause}; '
                    f'echo "{remote_path}" > /run/campus-player/lastfile 2>/dev/null || true',
                    timeout=5
                )
                out.read()
                played_sequence = True

        if played_sequence:
            pass
        elif have_local:
            cmd_j = json.dumps({'command': ['loadfile', remote_path, 'replace']})
            escaped = cmd_j.replace('"', '\\"')
            unpause = f'echo "{{\\"command\\":[\\"set_property\\",\\"pause\\",false]}}" | socat - {MPV_SOCK} 2>/dev/null'
            if my_gen is not None and _current_play_gen(machine_id) != my_gen:
                return
            _, out, _ = s.exec_command(
                f'echo "{escaped}" | socat - {MPV_SOCK} 2>/dev/null; '
                f'{unpause}; '
                f'echo "{remote_path}" > /run/campus-player/lastfile 2>/dev/null || true',
                timeout=5
            )
            out.read()
        else:
            # File not on campus machine → SFTP-upload to inbox (takes 5-30 s).
            # PLAYER_INBOX (/var/lib/campus-player/inbox) only exists on client1,
            # pre-provisioned with a shared "campus" group; every other campus
            # user has no permission to create anything under /var/lib, so
            # mkdir+put silently failed there (caught by the outer except,
            # nothing ever played, no error shown). Every campus user DOES
            # own their own home dir, so use a self-owned inbox for anyone
            # but client1 — always creatable, no manual provisioning needed.
            inbox = PLAYER_INBOX if host == CLIENT1_HOST else f'/home/{user}/player-inbox'
            remote_in = inbox + '/in.mp3'
            sftp = s.open_sftp()
            try:
                try:
                    sftp.mkdir(inbox)
                except IOError:
                    pass
                sftp.put(local_path, remote_in)
            except Exception as e:
                _set_last_error(machine_id, f'Не удалось загрузить файл на кампус: {e}')
                return
            finally:
                sftp.close()
            if my_gen is not None and _current_play_gen(machine_id) != my_gen:
                return
            _, out, _ = s.exec_command(
                f'/usr/local/bin/campus-playerctl play {remote_in} 2>/dev/null; '
                f'echo "{{\\"command\\":[\\"set_property\\",\\"pause\\",false]}}" | socat - {MPV_SOCK} 2>/dev/null',
                timeout=8
            )
            out.read()

        _clear_last_error(machine_id)
        with app.app_context():
            with get_db() as db:
                db.execute(
                    'INSERT INTO play_log (username, track_name, played_at) VALUES (?,?,?)',
                    (username, name, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                )
            log_action(username, 'play', machine_id, name)
            campus_lbl = 'Client1' if machine_id == 'client1' else 'Client2'
            tg_notify(
                f'▶️ <b>Музыка включена</b>\n'
                f'🎵 {name}\n'
                f'🏫 {campus_lbl}\n'
                f'👤 {username}\n'
                f'🕐 {_tg_fmt_time()}',
                event_type='play'
            )
    except Exception as e:
        app.logger.warning(f'_play_track_on {machine_id}: {e}')
        _set_last_error(machine_id, _humanize_ssh_error(e))
    finally:
        if s:
            try: s.close()
            except Exception: pass

@app.route('/api/play', methods=['POST'])
@login_required
def api_play():
    if not has_perm('play'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data    = request.get_json() or {}
    raw     = (data.get('name') or '').strip().replace('\x00','')
    name    = os.path.basename(raw)
    folder  = os.path.basename((data.get('folder') or '').strip())
    machine = data.get('machine', 'client1')
    if not name or '..' in name:
        return jsonify({'ok': False, 'error': 'недопустимое имя файла'})
    if folder == KAMRAN_FOLDER and not _kamran_unlocked():
        return jsonify({'ok': False, 'error': 'PIN требуется для KAMRAN'})
    local_path = os.path.join(MUSIC_DIR, folder, name) if folder else os.path.join(MUSIC_DIR, name)
    if not os.path.isfile(local_path):
        return jsonify({'ok': False, 'error': 'файл не найден'})

    username = current_user.username  # capture before background thread

    if machine == 'client1':
        host, user, mid = CLIENT1_HOST, CLIENT1_USER, 'client1'
    else:
        # Any other campus machine (client2, CGTK, BSTK, ...) — strict match so
        # an unrecognized machine id errors instead of silently playing
        # audio on the wrong campus's speakers
        m = _resolve_machine(machine, strict=True)
        if not m:
            return jsonify({'ok': False, 'error': f'машина {machine} не настроена'})
        host, user, mid = m['host'], m.get('user', CLIENT1_USER), m.get('user', machine)

    # Start SFTP/SSH in background — respond immediately so UI doesn't freeze
    my_gen = _bump_play_gen(mid)
    threading.Thread(
        target=_play_track_on,
        args=(host, user, local_path, name, mid, username, folder, my_gen),
        daemon=True
    ).start()
    return jsonify({'ok': True})

# Курируемый список интернет-радио — НЕ произвольный URL с голоса,
# чтобы голосовой ассистент не мог быть использован для проигрывания
# чего угодно на реальных колонках кампуса.
RADIO_STATIONS = {
    'europa_plus':  'https://ep128.hostingradio.ru:8030/ep128',
    'relax_fm':     'https://relax.hostingradio.ru:8000/relax128.mp3',
    'radio_jazz':   'https://jazz.hostingradio.ru:8000/jazz-64',
    'classic':      'https://prclassic.hostingradio.ru/prclassic128.mp3',
}

@app.route('/api/play-radio', methods=['POST'])
@login_required
def api_play_radio():
    if not has_perm('play'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data    = request.get_json() or {}
    station = (data.get('station') or 'europa_plus').strip()
    campus  = data.get('campus', 'both')
    url = RADIO_STATIONS.get(station)
    if not url:
        return jsonify({'ok': False, 'error': f'Неизвестная станция: {station}'})

    cmd = {'command': ['loadfile', url, 'replace']}
    _mpv_cmd_to_campus(campus, cmd)
    # pause is sticky — loadfile alone won't un-pause a player left paused
    _mpv_cmd_to_campus(campus, {'command': ['set_property', 'pause', False]})
    log_action(current_user.username, 'play_radio', campus, station)
    return jsonify({'ok': True, 'station': station})

@app.route('/api/tracks')
@login_required
def api_tracks():
    q         = request.args.get('q','').strip()
    folder    = request.args.get('folder','').strip()
    fav_only  = request.args.get('favorites','').strip() in ('1', 'true')
    with get_db() as c:
        fav_rows = c.execute('SELECT folder, name FROM favorites WHERE username=?',
                             (current_user.username,)).fetchall()
    fav_set = {(r['folder'], r['name']) for r in fav_rows}
    ts = scan_tracks(q, folder_filter=None if fav_only else (folder or None))
    for t in ts:
        t['fav'] = (t.get('folder', ''), t['name']) in fav_set
    if fav_only:
        ts = [t for t in ts if t['fav']]
    return jsonify({'ok': True, 'tracks': ts, 'total': total_tracks(), 'found': len(ts),
                    'folders': all_music_folders()})

@app.route('/api/play-all', methods=['POST'])
@login_required
def api_play_all():
    """List campus machine's local music via SSH, build m3u, load into mpv."""
    if not has_perm('play'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data    = request.get_json() or {}
    machine = data.get('machine', 'client1')
    do_shuf = data.get('shuffle', True)

    # Scan the campus machine's local music library over SSH.
    # Network streaming is not possible (campus machine can't reach this server).
    music_root = _music_path_for(machine)
    find_cmd = (f"find {music_root} -type f \\("
                f" -name '*.mp3' -o -name '*.flac'"
                f" -o -name '*.ogg' -o -name '*.m4a' \\) 2>/dev/null | sort")

    if machine == 'client1':
        raw = ssh_run(find_cmd)
    else:
        vm = _resolve_machine(machine, strict=True)
        if not vm:
            return jsonify({'ok': False, 'error': f'{machine} не настроен'})
        h, u = vm['host'], vm.get('user', CLIENT2_USER)
        raw = ssh_run_on(h, u, find_cmd)

    files = [l.strip() for l in raw.splitlines() if l.strip()]
    if not files:
        return jsonify({'ok': False, 'error': f'Нет треков в {music_root}'})

    if do_shuf:
        import random as _rand
        _rand.shuffle(files)

    import base64 as _b64
    m3u_content = '#EXTM3U\n' + '\n'.join(files) + '\n'
    b64 = _b64.b64encode(m3u_content.encode('utf-8')).decode()
    playlist_path = '/tmp/campus-playlist.m3u'
    write_cmd = f"echo '{b64}' | base64 -d > {playlist_path}"
    load_cmd = (f"echo '{{\"command\":[\"loadlist\",\"{playlist_path}\",\"replace\"]}}'"
                f" | socat - {MPV_SOCK} 2>/dev/null; "
                # pause is sticky — loadlist alone won't un-pause a player left paused
                f"echo '{{\"command\":[\"set_property\",\"pause\",false]}}'"
                f" | socat - {MPV_SOCK} 2>/dev/null; true")

    if machine == 'client1':
        ssh_run(write_cmd)
        ssh_run(load_cmd)
    else:
        ssh_run_on(h, u, write_cmd)
        ssh_run_on(h, u, load_cmd)

    log_action(current_user.username, 'play-all', f'{music_root} ({len(files)} tracks)')
    return jsonify({'ok': True, 'tracks': len(files)})

def _change_track(direction):
    """Play next (+1) or prev (-1) file in the same directory as current mpv track."""
    path = mpv_get('path')
    if not path:
        return jsonify({'ok': False, 'error': 'Ничего не играет'})

    dirname  = os.path.dirname(path)
    basename = os.path.basename(path)

    # inbox temp file → use Media day folder fallback
    if basename.lower() in ('in.mp3', 'in.wav', 'in.ogg') or not dirname:
        return jsonify({'ok': False, 'error': 'Текущий трек не из папки'})

    r = ssh_run(
        f'ls -1 "{dirname}" 2>/dev/null'
        r" | grep -iE '\.(mp3|ogg|wav|flac|m4a)$' | sort"
    )
    if not r['ok'] or not r['data'].strip():
        return jsonify({'ok': False, 'error': 'Не удалось получить список'})

    files = [f.strip() for f in r['data'].splitlines() if f.strip()]
    try:
        idx = files.index(basename)
    except ValueError:
        idx = 0

    new_idx  = (idx + direction) % len(files)
    new_file = f'{dirname}/{files[new_idx]}'
    vol      = mpv_get('volume') or 100

    r2 = ssh_run(f'/usr/local/bin/campus-playerctl play "{new_file}" {int(round(float(vol)))}')
    if r2['ok']:
        action = 'next' if direction > 0 else 'prev'
        log_action(current_user.username, action, 'client1', files[new_idx])
        return jsonify({'ok': True, 'track': files[new_idx]})
    return jsonify({'ok': False, 'error': r2.get('error', '—')})

@app.route('/api/next', methods=['POST'])
@login_required
def api_next():
    if not has_perm('next'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    return _change_track(+1)

@app.route('/api/prev', methods=['POST'])
@login_required
def api_prev():
    if not has_perm('prev'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    return _change_track(-1)

@app.route('/api/mute', methods=['POST'])
@login_required
def api_mute():
    if not has_perm('mute'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data  = request.get_json() or {}
    state = data.get('state')   # True=mute, False=unmute, None=toggle
    if state is None:
        cycle_cmd = {'command': ['cycle', 'mute']}
        r = mpv_cmd(cycle_cmd)
        for m in MACHINES:
            if m['host'] != CLIENT1_HOST:
                threading.Thread(
                    target=mpv_cmd_on, args=(m['host'], m.get('user', CLIENT1_USER), cycle_cmd), daemon=True
                ).start()
        return jsonify(r)
    return jsonify(mpv_set_all('mute', bool(state)))

@app.route('/api/loop', methods=['POST'])
@login_required
def api_loop():
    """Toggle mpv's own loop-file on the real campus player (not just the
    local browser preview) — repeats only the currently loaded track forever
    until STOP or another track is chosen."""
    if not has_perm('play'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data    = request.get_json() or {}
    machine = data.get('machine', 'client1')
    state   = bool(data.get('state'))
    cmd = {'command': ['set_property', 'loop-file', 'inf' if state else 'no']}
    if machine == 'client1':
        r = mpv_cmd(cmd)
    else:
        m = _resolve_machine(machine, strict=True)
        if not m:
            return jsonify({'ok': False, 'error': f'машина {machine} не настроена'})
        r = mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cmd)
    log_action(current_user.username, 'loop', machine, 'on' if state else 'off')
    return jsonify(r if isinstance(r, dict) else {'ok': True, 'loop': state})

@app.route('/api/terminal', methods=['POST'])
@login_required
def api_terminal():
    if not has_perm('terminal'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data    = request.get_json() or {}
    cmd     = (data.get('cmd') or '').strip()
    machine = (data.get('machine') or 'client1').strip()
    if not cmd:
        return jsonify({'ok': False, 'error': 'Пустая команда'})
    tm = TERMINAL_MACHINES.get(machine)
    if tm:
        host, user, key = tm['host'], tm['user'], tm['key']
        # client2 (and any other campus machine resolved at runtime) has no
        # static host in TERMINAL_MACHINES — look it up by the same key
        # the request sent, not always "client2"
        if not host:
            host, user = _get_client2(machine)
            if not host:
                return jsonify({'ok': False, 'error': f'{tm["label"]} не настроен'})
    else:
        # Not one of the 3 well-known slots — try resolving it as any
        # other campus machine (CGTK, BSTK, etc.) added via /machines
        m = _resolve_machine(machine, strict=True)
        if not m:
            return jsonify({'ok': False, 'error': f'Неизвестная машина: {machine}'})
        host, user, key = m['host'], m.get('user', CLIENT1_USER), SSH_KEY
    s = None
    try:
        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(host, username=user, key_filename=key, timeout=10, banner_timeout=30)
        _, stdout, stderr = s.exec_command(cmd, timeout=30)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        output = (out + err).rstrip('\n')
        log_action(current_user.username, 'terminal', machine, cmd[:120])
        return jsonify({'ok': True, 'output': output or '(нет вывода)'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e), 'output': ''})
    finally:
        if s:
            try: s.close()
            except Exception: pass

@app.route('/api/tracks/count')
@login_required
def api_tracks_count():
    return jsonify({'count': total_tracks()})

@app.route('/api/history')
@login_required
def api_history():
    with get_db() as c:
        rows = c.execute(
            'SELECT username, track_name, played_at FROM play_log ORDER BY id DESC LIMIT 50'
        ).fetchall()
    return jsonify({'ok': True, 'history': [dict(r) for r in rows]})

@app.route('/helpdesk-sso')
@login_required
def helpdesk_sso():
    """Bridges an already-authenticated session here into a matching
    Helpdesk Ops account (same email) — no second password prompt."""
    email = (current_user.email or '').strip()
    if not email:
        return redirect(HELPDESK_URL)
    token = _sso_serializer.dumps(email)
    return redirect(f"{HELPDESK_URL}/sso?token={token}")

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        old_pw  = request.form.get('old_password', '')
        new_pw  = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not old_pw or not new_pw:
            flash('Заполните все поля', 'danger')
        elif new_pw != confirm:
            flash('Пароли не совпадают', 'danger')
        elif len(new_pw) < 4:
            flash('Пароль слишком короткий (мин. 4 символа)', 'danger')
        else:
            with get_db() as c:
                row = c.execute('SELECT * FROM users WHERE id=?', (current_user.id,)).fetchone()
            if not check_password_hash(row['password_hash'], old_pw):
                flash('Неверный текущий пароль', 'danger')
            else:
                with get_db() as c:
                    c.execute('UPDATE users SET password_hash=? WHERE id=?',
                              (generate_password_hash(new_pw), current_user.id))
                flash('Пароль успешно изменён', 'success')
        return redirect(url_for('profile'))
    with get_db() as c:
        history = c.execute(
            'SELECT username, track_name, played_at FROM play_log ORDER BY id DESC LIMIT 30'
        ).fetchall()
        _prefs = c.execute('SELECT ui_skin, ui_accent FROM users WHERE username=?',
                            (current_user.username,)).fetchone()
    return render_template('profile.html', history=history,
        ui_skin=(_prefs['ui_skin'] if _prefs else 'classic') or 'classic',
        ui_accent=(_prefs['ui_accent'] if _prefs else 'amber') or 'amber')

@app.route('/settings')
@login_required
def settings_page():
    tg_settings = {}
    silence = False
    with get_db() as c:
        rows = c.execute("SELECT key, value FROM settings WHERE key LIKE 'tg_notify%'").fetchall()
        tg_settings = {r['key']: r['value'] for r in rows}
        s = c.execute("SELECT value FROM settings WHERE key='silence_mode'").fetchone()
        if s:
            silence = s['value'] == '1'
    return render_template('settings.html', tg_settings=tg_settings, silence=silence,
                           ui_variants=UI_VARIANT_INFO, ui_current=(_effective_ui() or 'off'), ui_palettes=UI_PALETTES,
                           login_styles=LOGIN_STYLE_INFO, login_style_current=_login_style_current(),
                           ui_default=_ui_default_current())

@app.route('/security')
@perm_required('security_view')
def security_page():
    return render_template('security.html')

@app.route('/avatars/<path:filename>')
@login_required
def serve_avatar(filename):
    return send_from_directory(AVATAR_DIR, filename)

@app.route('/api/profile/update', methods=['POST'])
@login_required
def api_profile_update():
    data       = request.get_json() or {}
    first_name = str(data.get('first_name', '')).strip()[:80]
    last_name  = str(data.get('last_name',  '')).strip()[:80]
    position   = str(data.get('position',   '')).strip()[:100]
    campus     = str(data.get('campus',     '')).strip()[:60]
    phone      = str(data.get('phone',      '')).strip()[:30]
    email      = str(data.get('email',      '')).strip()[:120]
    birth_year = str(data.get('birth_year', '')).strip()[:10]
    with get_db() as c:
        c.execute('''UPDATE users SET first_name=?,last_name=?,position=?,campus=?,phone=?,email=?,birth_year=?
                     WHERE id=?''',
                  (first_name, last_name, position, campus, phone, email, birth_year, current_user.id))
    return jsonify({'ok': True})

@app.route('/api/profile/avatar', methods=['POST'])
@login_required
def api_profile_avatar():
    f = request.files.get('avatar')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'Файл не выбран'})
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        return jsonify({'ok': False, 'error': 'Только JPG/PNG/GIF/WebP'})
    filename = f'avatar_{current_user.id}{ext}'
    dest = os.path.join(AVATAR_DIR, filename)
    f.save(dest)
    with get_db() as c:
        c.execute('UPDATE users SET avatar=? WHERE id=?', (filename, current_user.id))
    return jsonify({'ok': True, 'url': f'/avatars/{filename}'})

@app.route('/api/profile/password', methods=['POST'])
@login_required
def api_profile_password():
    data    = request.get_json() or {}
    old_pw  = data.get('old_password', '')
    new_pw  = data.get('new_password', '')
    confirm = data.get('confirm_password', '')
    if not old_pw or not new_pw:
        return jsonify({'ok': False, 'error': 'Заполните все поля'})
    if new_pw != confirm:
        return jsonify({'ok': False, 'error': 'Пароли не совпадают'})
    if len(new_pw) < 4:
        return jsonify({'ok': False, 'error': 'Пароль слишком короткий (мин. 4 символа)'})
    with get_db() as c:
        row = c.execute('SELECT * FROM users WHERE id=?', (current_user.id,)).fetchone()
    if not check_password_hash(row['password_hash'], old_pw):
        return jsonify({'ok': False, 'error': 'Неверный текущий пароль'})
    with get_db() as c:
        c.execute('UPDATE users SET password_hash=? WHERE id=?',
                   (generate_password_hash(new_pw), current_user.id))
    return jsonify({'ok': True})

import secrets as _secrets
_STREAM_TOKEN = os.environ.get('CAMPUS_STREAM_TOKEN') or _secrets.token_urlsafe(32)

def _stream_allowed():
    """True if request can access audio stream without full login."""
    tok = request.args.get('token', '')
    if tok and tok == _STREAM_TOKEN:
        return True
    # Trust campus machine IPs directly
    ip = request.remote_addr
    trusted = {CLIENT1_HOST, '127.0.0.1', '::1'}
    for m in MACHINES:
        if m.get('host'):
            trusted.add(m['host'])
    return ip in trusted

@app.route('/api/stream')
def api_stream():
    if not _stream_allowed() and not current_user.is_authenticated:
        return jsonify({'error': 'unauthorized'}), 401
    name   = os.path.basename((request.args.get('name') or '').strip())
    folder = os.path.basename((request.args.get('folder') or '').strip())
    if not name:
        return jsonify({'ok': False, 'error': 'Не указан файл'}), 400
    if folder and folder not in MUSIC_FOLDERS:
        return jsonify({'ok': False, 'error': 'Неверная папка'}), 400
    base = os.path.join(MUSIC_DIR, folder) if folder else MUSIC_DIR
    return send_from_directory(base, name, as_attachment=False, conditional=True)

@app.route('/api/tracks/download')
@login_required
def api_tracks_download():
    name   = os.path.basename((request.args.get('name') or '').strip())
    folder = os.path.basename((request.args.get('folder') or '').strip())
    if not name:
        return jsonify({'ok': False, 'error': 'Не указан файл'}), 400
    if folder and folder not in MUSIC_FOLDERS:
        return jsonify({'ok': False, 'error': 'Неверная папка'}), 400
    base = os.path.join(MUSIC_DIR, folder) if folder else MUSIC_DIR
    return send_from_directory(base, name, as_attachment=True)

@app.route('/api/heartbeat', methods=['POST'])
@login_required
def api_heartbeat():
    data = request.get_json(silent=True) or {}
    page = (data.get('page') or 'dashboard')[:64]
    now  = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as c:
        c.execute('''INSERT OR REPLACE INTO online_sessions (username, last_seen, page)
                     VALUES (?,?,?)''', (current_user.username, now, page))
    return jsonify({'ok': True})

@app.route('/api/online')
@login_required
def api_online():
    cutoff = (datetime.now() - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as c:
        rows = c.execute(
            'SELECT s.username, s.last_seen, s.page, u.id, u.role, u.is_blocked '
            'FROM online_sessions s JOIN users u ON u.username=s.username '
            'WHERE s.last_seen >= ? ORDER BY s.last_seen DESC',
            (cutoff,)
        ).fetchall()
    return jsonify({'ok': True, 'users': [dict(r) for r in rows]})

@app.route('/api/chat/send', methods=['POST'])
@login_required
def api_chat_send():
    data    = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()[:500]
    to_user = (data.get('to_user') or '').strip() or None
    if not content:
        return jsonify({'ok': False, 'error': 'пустое сообщение'})
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as c:
        # validate to_user exists
        if to_user:
            row = c.execute('SELECT id FROM users WHERE username=?', (to_user,)).fetchone()
            if not row:
                to_user = None
        c.execute('INSERT INTO messages (from_user, to_user, content, sent_at) VALUES (?,?,?,?)',
                  (current_user.username, to_user, content, now))
        # keep only messages from last 48 hours, max 500
        c.execute("DELETE FROM messages WHERE sent_at < datetime('now','-48 hours')")
        c.execute('DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 500)')
    return jsonify({'ok': True})

@app.route('/api/chat/messages')
@login_required
def api_chat_messages():
    since = request.args.get('since', 0, type=int)
    me = current_user.username
    with get_db() as c:
        rows = c.execute(
            '''SELECT id, from_user, COALESCE(to_user,'') as to_user, content, sent_at, voice_file
               FROM messages
               WHERE id > ?
                 AND (to_user IS NULL
                      OR from_user=?
                      OR to_user=?)
               ORDER BY id ASC LIMIT 80''',
            (since, me, me)
        ).fetchall()
    return jsonify({'ok': True, 'messages': [dict(r) for r in rows]})

@app.route('/api/users/list')
@login_required
def api_users_list():
    with get_db() as c:
        rows = c.execute(
            'SELECT username, role FROM users WHERE is_blocked=0 ORDER BY username'
        ).fetchall()
    users = [{'username': r['username'], 'role': r['role']}
             for r in rows if r['username'] != current_user.username]
    return jsonify({'ok': True, 'users': users})

# ── Cron log & file metadata (admin) ─────────────────────────────────────────
import re as _re

_file_meta_cache = {}   # (machine, folder, filename) -> {size, duration, format}

def _machine_ssh(machine):
    """Вернуть (host, user) для машины. 'client1' — основная (env-переменные);
    'client2' сохраняет исторический lenient-фоллбек (первая не-client1 машина);
    любой другой ключ (например 'cgtk') резолвится строго через MACHINES —
    опечатка в имени машины вернёт (None, None) вместо подключения не туда."""
    if not machine or machine == 'client1':
        return CLIENT1_HOST, CLIENT1_USER
    if machine == 'client2':
        m = _resolve_machine('client2')
        if m:
            return m['host'], m.get('user', 'client2')
        return '10.70.0.41', 'client2'
    m = _resolve_machine(machine, strict=True)
    if not m:
        return None, None
    return m['host'], m.get('user', machine)

def _load_folder_meta(folder, machine='client1'):
    folder = str(folder)
    media = _music_path_for(machine)
    host, user = _machine_ssh(machine)
    cmd = (
        f'for f in {media}/{folder}/*.mp3 {media}/{folder}/*.wav; do '
        '[ -f "$f" ] || continue; '
        'fname=$(basename "$f"); '
        'size=$(stat -c "%s" "$f" 2>/dev/null || echo 0); '
        'dur=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null || echo 0); '
        'fmt=$(ffprobe -v quiet -show_entries format=format_name -of csv=p=0 "$f" 2>/dev/null | cut -d, -f1 || echo ?); '
        f'echo "{folder}|||${{fname}}|||${{size}}|||${{dur}}|||${{fmt}}"; done'
    )
    r = ssh_run_on(host, user, cmd)
    if not r['ok']:
        return
    for line in r['data'].split('\n'):
        parts = line.strip().split('|||')
        if len(parts) != 5:
            continue
        fld, fname, size, dur, fmt = parts
        try:
            _file_meta_cache[(machine, fld.strip(), fname.strip())] = {
                'size':     int(float(size)) if size else 0,
                'duration': float(dur) if dur else 0,
                'format':   fmt.strip() or '?',
            }
        except ValueError:
            pass

def _get_remote_meta(folder, fname, machine='client1'):
    key = (machine, str(folder), fname)
    if key not in _file_meta_cache:
        _load_folder_meta(folder, machine)
    return _file_meta_cache.get(key, {})

def _fmt_size(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.1f} {u}'
        n /= 1024
    return f'{n:.1f} GB'

def _fmt_dur(sec):
    sec = int(sec)
    m, s = divmod(sec, 60)
    return f'{m}:{s:02d}'

def _parse_action_log(text):
    entries = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        ts = _re.match(r'\[(\d{2}:\d{2}:\d{2}) (\d{2}\.\d{2})\]', line)
        if not ts:
            continue
        time_s, date_s = ts.group(1), ts.group(2)
        play = _re.search(r'папка (\d+), (\S+) vol=(\d+) (✅|❌) \| (.+)$', line)
        if play:
            folder, slot, vol, status, fname = play.groups()
            fname = fname.strip()
            meta  = _get_remote_meta(folder, fname)
            entries.append({
                'type':     'play',
                'time':     time_s,
                'date':     date_s,
                'folder':   folder,
                'slot':     slot,
                'vol':      int(vol),
                'status':   status,
                'file':     fname,
                'size':     _fmt_size(meta.get('size', 0)) if meta else '—',
                'duration': _fmt_dur(meta.get('duration', 0)) if meta else '—',
                'format':   meta.get('format', '?') if meta else '—',
                'size_raw': meta.get('size', 0),
            })
        elif 'stop local' in line or 'Cron stop' in line:
            entries.append({'type': 'stop', 'time': time_s, 'date': date_s})
    return entries

@app.route('/admin/cron')
@login_required
@perm_required('cron_view')
def admin_cron():
    now = datetime.now()
    ct  = now.strftime('%H:%M')
    # Find currently active scheduled slot (play started, stop not yet)
    active_slot = None
    for i, ev in enumerate(SCHEDULE):
        if ev['play'] and ev['time'] <= ct:
            # Find next stop after this play
            nxt_stop = next((s for s in SCHEDULE[i+1:] if not s['play']), None)
            if nxt_stop and nxt_stop['time'] > ct:
                active_slot = ev
                break
    return render_template('cron.html', now=now, active_slot=active_slot, schedule=SCHEDULE)

def _mpv_get_on(host, user, prop):
    MPV = '/run/campus-player/mpv.sock'
    escaped = json.dumps({'command': ['get_property', prop]}).replace('"', '\\"')
    r = ssh_run_on(host, user, f'echo "{escaped}" | socat - {MPV} 2>/dev/null')
    if r['ok']:
        try: return json.loads(r['data']).get('data')
        except: pass
    return None

@app.route('/api/admin/cron-status')
@login_required
@perm_required('cron_view')
def api_cron_status():
    machine = request.args.get('machine', 'client1')
    host, user = _machine_ssh(machine)
    if not host:
        return jsonify({'ok': False, 'error': f'{machine} не настроен'})
    path  = _mpv_get_on(host, user, 'path')
    pause = _mpv_get_on(host, user, 'pause')
    if path and pause is False:
        return jsonify({'ok': True, 'playing': True, 'file': path.split('/')[-1], 'path': path})
    return jsonify({'ok': True, 'playing': False, 'file': '', 'path': ''})

@app.route('/api/admin/cron-log')
@login_required
@perm_required('cron_view')
def api_cron_log():
    lines   = request.args.get('lines', 100, type=int)
    machine = request.args.get('machine', 'client1')
    host, user = _machine_ssh(machine)
    if not host:
        return jsonify({'ok': False, 'error': f'{machine} не настроен'})
    log = f'/home/{user}/action.log'
    r = ssh_run_on(host, user, f'tail -n {min(lines, 300)} {log} 2>/dev/null')
    if not r['ok']:
        return jsonify({'ok': False, 'error': r.get('error', 'SSH error')})
    entries = _parse_action_log(r['data'])
    entries.reverse()
    return jsonify({'ok': True, 'entries': entries, 'machine': machine})

@app.route('/api/admin/cron-files')
@login_required
@perm_required('cron_view')
def api_cron_files():
    folder  = request.args.get('folder', '1')
    machine = request.args.get('machine', 'client1')
    if not folder.isdigit():
        return jsonify({'ok': False, 'error': 'bad folder'})
    if not any(k[0] == machine and k[1] == folder for k in _file_meta_cache):
        _load_folder_meta(folder, machine)
    files = []
    for (mach, f, fn), meta in sorted(_file_meta_cache.items()):
        if mach == machine and f == folder:
            files.append({
                'file':     fn,
                'format':   meta.get('format', '?'),
                'size':     _fmt_size(meta.get('size', 0)),
                'duration': _fmt_dur(meta.get('duration', 0)),
                'size_raw': meta.get('size', 0),
            })
    files.sort(key=lambda x: x['file'])
    return jsonify({'ok': True, 'folder': folder, 'files': files, 'machine': machine})

@app.route('/api/admin/cron-meta/refresh', methods=['POST'])
@login_required
@perm_required('cron_view')
def api_cron_meta_refresh():
    folder  = request.args.get('folder', '1')
    machine = request.args.get('machine', 'client1')
    keys = [k for k in _file_meta_cache if k[0] == machine and k[1] == folder]
    for k in keys:
        del _file_meta_cache[k]
    _load_folder_meta(folder, machine)
    return jsonify({'ok': True, 'cached': len(_file_meta_cache)})

_MACHINE_MAP = {
    'client1': {'host': CLIENT1_HOST, 'user': CLIENT1_USER, 'label': 'Client1 Campus',
              'color': 'blue', 'icon': 'building',
              'log': '/home/client1/action.log', 'cron_user': 'client1'},
    'client2':  {'host': '10.70.0.41', 'user': 'client2', 'label': 'Client2 Campus',
              'color': 'purple', 'icon': 'pc-display',
              'log': '/home/client2/action.log', 'cron_user': 'client2'},
    'cgtk': {'host': None, 'user': 'cgtk', 'label': 'City Garden Campus',
              'color': 'pink', 'icon': 'flower1',
              'log': '/home/cgtk/action.log', 'cron_user': 'cgtk'},
}

_SLOT_LABELS = {
    'utro': ('Утро', 'bi-sunrise', 'orange'),
    'himn': ('Гимн', 'bi-music-note-beamed', 'purple'),
    '1peremena': ('1 перемена', 'bi-bell', 'blue'),
    '2peremena': ('2 перемена', 'bi-bell', 'blue'),
    '3peremena': ('3 перемена', 'bi-bell', 'blue'),
    '4peremena': ('4 перемена', 'bi-bell', 'blue'),
    '5peremena': ('5 перемена', 'bi-bell', 'blue'),
    '6peremena': ('6 перемена', 'bi-bell', 'blue'),
    '7peremena': ('7 перемена', 'bi-bell', 'blue'),
    '8peremena': ('8 перемена', 'bi-bell', 'blue'),
    '9peremena': ('9 перемена', 'bi-bell', 'blue'),
}
_DOW_MAP = {
    '*':   'Каждый день',
    '1-5': 'Пн – Пт',
    '1':   'Пн',
    '2':   'Вт',
    '3':   'Ср',
    '4':   'Чт',
    '5':   'Пт',
    '6':   'Сб',
    '0':   'Вс',
}

def _parse_cron(raw_lines):
    entries = []
    for line in raw_lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        cmin, chour, _, _, dow = parts[0:5]
        rest = parts[5:]
        # skip env-var tokens
        cmd_tokens = [t for t in rest if not ('=' in t and not t.startswith('/'))]
        if not cmd_tokens:
            continue
        script = os.path.basename(cmd_tokens[0])
        args   = cmd_tokens[1:]
        is_stop = 'stop' in script
        slot    = args[0] if args and not is_stop else ('stop' if is_stop else '')
        vol     = args[1] if len(args) > 1 else ''
        try:
            time_str = f'{int(chour):02d}:{int(cmin):02d}'
        except ValueError:
            time_str = f'{chour}:{cmin}'
        label, icon, color = _SLOT_LABELS.get(slot, ('Стоп' if is_stop else slot, 'bi-x-circle', 'red') if is_stop else (slot, 'bi-question', 'muted'))
        entries.append({
            'time': time_str,
            'days': _DOW_MAP.get(dow, dow),
            'slot': slot,
            'label': label,
            'icon': icon,
            'color': color,
            'vol': vol,
            'is_stop': is_stop,
            'raw': line,
        })
    return entries

@app.route('/campus/<machine>')
@login_required
def campus_detail(machine):
    if machine not in _MACHINE_MAP:
        return redirect(url_for('index'))
    cfg = dict(_MACHINE_MAP[machine])
    host, user = cfg['host'], cfg['user']
    if not host:
        # DB-registered machine (e.g. cgtk) — no static env host, resolve via MACHINES
        m = _resolve_machine(machine, strict=True)
        if m:
            host, user = m['host'], m.get('user', cfg['user'])
        cfg['host'] = host

    online = host_online(host) if host else False

    # Crontab → parsed
    cron_entries = []
    if online:
        r = ssh_run_on(host, user, 'crontab -l 2>/dev/null')
        if r['ok']:
            raw = [l.strip() for l in r['data'].splitlines()
                   if l.strip() and not l.strip().startswith('#')]
            cron_entries = _parse_cron(raw)

    # Raw action.log from machine
    action_log = []
    if online:
        r = ssh_run_on(host, user, f'tail -n 50 {cfg["log"]} 2>/dev/null')
        if r['ok'] and r['data']:
            action_log = list(reversed(r['data'].splitlines()))

    # Merge activity_log + play_log → unified timeline
    with get_db() as c:
        act_rows = c.execute(
            '''SELECT username, action, machine, detail, happened_at
               FROM activity_log WHERE machine=? OR machine="all"
               ORDER BY id DESC LIMIT 80''',
            (machine,)
        ).fetchall()
        play_rows = c.execute(
            '''SELECT username, "play" as action, "client1" as machine,
                      track_name as detail, played_at as happened_at
               FROM play_log ORDER BY id DESC LIMIT 80'''
        ).fetchall() if machine == 'client1' else []

    # Combine and sort by time desc
    activity = []
    for r in act_rows:
        activity.append(dict(r))
    for r in play_rows:
        activity.append(dict(r))
    activity.sort(key=lambda x: x.get('happened_at',''), reverse=True)
    activity = activity[:80]

    return render_template('campus.html',
        machine=machine, cfg=cfg,
        online=online,
        cron_entries=cron_entries,
        action_log=action_log,
        activity=activity,
    )

@app.route('/api/activity-log')
@login_required
@perm_required('activity_log')
def api_activity_log():
    machine = request.args.get('machine', '')
    limit   = min(int(request.args.get('limit', 100)), 500)
    with get_db() as c:
        if machine:
            rows = c.execute(
                'SELECT * FROM activity_log WHERE machine=? ORDER BY id DESC LIMIT ?',
                (machine, limit)
            ).fetchall()
        else:
            rows = c.execute(
                'SELECT * FROM activity_log ORDER BY id DESC LIMIT ?', (limit,)
            ).fetchall()
    return jsonify({'ok': True, 'log': [dict(r) for r in rows]})

# ══════════════════════════════════════════════════
# UPLOAD TRACKS
# ══════════════════════════════════════════════════
ALLOWED_AUDIO = {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'}

def _safe_filename(name):
    """Unicode-safe filename sanitizer — preserves Cyrillic/non-ASCII chars."""
    name = os.path.basename(name)
    # Remove characters that are dangerous on any OS
    name = re.sub(r'[/\\<>:"|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    # Fallback to secure_filename if name becomes empty
    if not name:
        name = secure_filename(os.path.basename(name)) if name else ''
    return name or None

@app.route('/upload')
@login_required
def upload_page():
    if not has_perm('upload'):
        flash('Нет прав для загрузки треков', 'danger')
        return redirect(url_for('tracks'))
    used_mb = 0
    count   = 0
    for root, dirs, files in os.walk(MUSIC_DIR):
        for fname in files:
            if os.path.splitext(fname)[1].lower() in ALLOWED_AUDIO:
                fpath = os.path.join(root, fname)
                used_mb += os.path.getsize(fpath)
                count += 1
    used_mb //= (1024 * 1024)
    return render_template('upload.html', perms=user_perms(),
                           used_mb=used_mb, count=count,
                           folders=MUSIC_FOLDERS,
                           kamran_unlocked=_kamran_unlocked(),
                           sync_machines=[m for m in music_machines_json() if m['key'] != 'client1'])

@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    if not has_perm('upload'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'Файл не выбран'})
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_AUDIO:
        return jsonify({'ok': False, 'error': f'Недопустимый формат: {ext}. Разрешены: mp3 wav ogg flac'})
    filename = _safe_filename(f.filename)
    if not filename:
        return jsonify({'ok': False, 'error': 'Недопустимое имя файла'})
    folder = os.path.basename((request.form.get('folder') or '').strip())
    if folder and folder not in MUSIC_FOLDERS:
        return jsonify({'ok': False, 'error': 'Недопустимая папка'})
    if folder == KAMRAN_FOLDER and not _kamran_unlocked():
        return jsonify({'ok': False, 'error': 'PIN требуется для KAMRAN'})
    target_dir = os.path.join(MUSIC_DIR, folder) if folder else MUSIC_DIR
    os.makedirs(target_dir, exist_ok=True)
    dest = os.path.join(target_dir, filename)
    overwrite = request.form.get('overwrite') == '1'
    if os.path.exists(dest) and not overwrite:
        return jsonify({'ok': False, 'error': f'Файл уже существует: {filename}', 'exists': True})
    f.save(dest)
    size = os.path.getsize(dest)
    label = f'{folder}/{filename}' if folder else filename
    log_action(current_user.username, 'upload', 'local', label)
    tg_notify(
        f'📤 <b>Новый трек загружен</b>\n'
        f'🎵 {filename} ({round(size/1024/1024,1)} MB)\n'
        f'📁 {folder or "корень"}\n'
        f'👤 {current_user.username}\n'
        f'🕐 {_tg_fmt_time()}',
        event_type='upload'
    )
    return jsonify({'ok': True, 'name': filename, 'folder': folder, 'size': size,
                    'size_kb': round(size/1024, 1)})

@app.route('/api/tracks/delete', methods=['POST'])
@login_required
def api_tracks_delete():
    if not has_perm('tracks_delete'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data   = request.get_json() or {}
    name   = os.path.basename((data.get('name') or '').strip())
    folder = os.path.basename((data.get('folder') or '').strip())
    if not name or '..' in name:
        return jsonify({'ok': False, 'error': 'Недопустимое имя'})
    if folder == KAMRAN_FOLDER and not _kamran_unlocked():
        return jsonify({'ok': False, 'error': 'PIN требуется для KAMRAN'})
    path = os.path.join(MUSIC_DIR, folder, name) if folder else os.path.join(MUSIC_DIR, name)
    if not os.path.isfile(path):
        return jsonify({'ok': False, 'error': 'Файл не найден'})
    os.remove(path)
    log_action(current_user.username, 'delete_track', 'local', f'{folder}/{name}' if folder else name)
    return jsonify({'ok': True})

@app.route('/api/tracks/rename', methods=['POST'])
@login_required
def api_tracks_rename():
    if not has_perm('tracks_edit'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data     = request.get_json() or {}
    folder   = os.path.basename((data.get('folder') or '').strip())
    old_name = os.path.basename((data.get('old_name') or '').strip())
    new_name = os.path.basename((data.get('new_name') or '').strip())
    if not old_name or not new_name or '..' in old_name or '..' in new_name:
        return jsonify({'ok': False, 'error': 'Недопустимое имя'})
    if folder == KAMRAN_FOLDER and not _kamran_unlocked():
        return jsonify({'ok': False, 'error': 'PIN требуется для KAMRAN'})
    old_ext = os.path.splitext(old_name)[1].lower()
    if os.path.splitext(new_name)[1].lower() != old_ext:
        new_name = os.path.splitext(new_name)[0] + old_ext
    if not new_name.lower().endswith(AUDIO_EXTS):
        return jsonify({'ok': False, 'error': 'Недопустимое расширение файла'})
    base_dir = os.path.join(MUSIC_DIR, folder) if folder else MUSIC_DIR
    old_path = os.path.join(base_dir, old_name)
    new_path = os.path.join(base_dir, new_name)
    if not os.path.isfile(old_path):
        return jsonify({'ok': False, 'error': 'Файл не найден'})
    if old_name != new_name and os.path.exists(new_path):
        return jsonify({'ok': False, 'error': 'Файл с таким именем уже существует'})
    os.rename(old_path, new_path)
    with get_db() as c:
        c.execute('UPDATE favorites SET name=? WHERE folder=? AND name=?', (new_name, folder, old_name))
    log_action(current_user.username, 'rename_track', 'local',
               f'{folder}/{old_name} → {new_name}' if folder else f'{old_name} → {new_name}')
    return jsonify({'ok': True, 'name': new_name})

@app.route('/api/tracks/favorite', methods=['POST'])
@login_required
def api_tracks_favorite():
    data   = request.get_json() or {}
    name   = os.path.basename((data.get('name') or '').strip())
    folder = os.path.basename((data.get('folder') or '').strip())
    action = data.get('action', 'add')
    if not name:
        return jsonify({'ok': False, 'error': 'Недопустимое имя'})
    with get_db() as c:
        if action == 'remove':
            c.execute('DELETE FROM favorites WHERE username=? AND folder=? AND name=?',
                      (current_user.username, folder, name))
        else:
            c.execute('''INSERT OR IGNORE INTO favorites (username, folder, name)
                        VALUES (?,?,?)''', (current_user.username, folder, name))
    return jsonify({'ok': True, 'favorite': action != 'remove'})

@app.route('/api/tracks/favorites', methods=['GET'])
@login_required
def api_tracks_favorites_list():
    with get_db() as c:
        rows = c.execute('SELECT folder, name FROM favorites WHERE username=? ORDER BY created_at DESC',
                         (current_user.username,)).fetchall()
    return jsonify({'ok': True, 'favorites': [{'folder': r['folder'], 'name': r['name']} for r in rows]})

_FOLDER_NAME_RE = _re.compile(r'^[\w \-\.\(\)\[\]А-Яа-яЁёƏəÜüÖöĞğİıŞşÇç]{1,60}$')

@app.route('/api/tracks/create-folder', methods=['POST'])
@login_required
def api_tracks_create_folder():
    if not has_perm('folders_manage'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data = request.get_json() or {}
    name = os.path.basename((data.get('name') or '').strip())
    if not name or '..' in name or not _FOLDER_NAME_RE.match(name):
        return jsonify({'ok': False, 'error': 'Недопустимое название папки'})
    existing = {f.lower() for f in all_music_folders()}
    if name.lower() in existing:
        return jsonify({'ok': False, 'error': 'Такая папка уже есть'})
    os.makedirs(os.path.join(MUSIC_DIR, name), exist_ok=True)
    log_action(current_user.username, 'create_music_folder', 'local', name)
    return jsonify({'ok': True, 'folders': all_music_folders()})

@app.route('/api/tracks/move', methods=['POST'])
@login_required
def api_tracks_move():
    if not has_perm('tracks_edit'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data        = request.get_json() or {}
    name        = os.path.basename((data.get('name') or '').strip())
    src_folder  = os.path.basename((data.get('folder') or '').strip())
    dst_folder  = os.path.basename((data.get('dest_folder') or '').strip())
    if not name or '..' in name:
        return jsonify({'ok': False, 'error': 'Недопустимое имя файла'})
    folders = all_music_folders()
    if dst_folder not in folders:
        return jsonify({'ok': False, 'error': 'Папка назначения не найдена'})
    if (src_folder == KAMRAN_FOLDER or dst_folder == KAMRAN_FOLDER) and not _kamran_unlocked():
        return jsonify({'ok': False, 'error': 'PIN требуется для KAMRAN'})
    src_path = os.path.join(MUSIC_DIR, src_folder, name) if src_folder else os.path.join(MUSIC_DIR, name)
    dst_dir  = os.path.join(MUSIC_DIR, dst_folder)
    dst_path = os.path.join(dst_dir, name)
    if not os.path.isfile(src_path):
        return jsonify({'ok': False, 'error': 'Файл не найден'})
    if src_path == dst_path:
        return jsonify({'ok': True})
    if os.path.exists(dst_path):
        return jsonify({'ok': False, 'error': 'В папке назначения уже есть файл с таким именем'})
    os.makedirs(dst_dir, exist_ok=True)
    os.rename(src_path, dst_path)
    with get_db() as c:
        c.execute('UPDATE favorites SET folder=? WHERE folder=? AND name=?', (dst_folder, src_folder, name))
    log_action(current_user.username, 'move_track', 'local', f'{name}: {src_folder or "—"} → {dst_folder}')
    return jsonify({'ok': True})

@app.route('/api/tracks/bulk-move', methods=['POST'])
@login_required
def api_tracks_bulk_move():
    if not has_perm('tracks_edit'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data       = request.get_json() or {}
    items      = data.get('items') or []
    dst_folder = os.path.basename((data.get('dest_folder') or '').strip())
    folders = all_music_folders()
    if dst_folder not in folders:
        return jsonify({'ok': False, 'error': 'Папка назначения не найдена'})
    if (dst_folder == KAMRAN_FOLDER) and not _kamran_unlocked():
        return jsonify({'ok': False, 'error': 'PIN требуется для KAMRAN'})
    moved, failed = 0, []
    for it in items[:500]:
        name       = os.path.basename((it.get('name') or '').strip())
        src_folder = os.path.basename((it.get('folder') or '').strip())
        if not name or '..' in name:
            failed.append(name or '?'); continue
        if (src_folder == KAMRAN_FOLDER) and not _kamran_unlocked():
            failed.append(name); continue
        src_path = os.path.join(MUSIC_DIR, src_folder, name) if src_folder else os.path.join(MUSIC_DIR, name)
        dst_dir  = os.path.join(MUSIC_DIR, dst_folder)
        dst_path = os.path.join(dst_dir, name)
        if src_path == dst_path:
            continue
        if not os.path.isfile(src_path) or os.path.exists(dst_path):
            failed.append(name); continue
        os.makedirs(dst_dir, exist_ok=True)
        os.rename(src_path, dst_path)
        with get_db() as c:
            c.execute('UPDATE favorites SET folder=? WHERE folder=? AND name=?', (dst_folder, src_folder, name))
        moved += 1
    log_action(current_user.username, 'bulk_move_tracks', 'local', f'{moved} → {dst_folder}')
    return jsonify({'ok': True, 'moved': moved, 'failed': failed})

@app.route('/api/tracks/bulk-delete', methods=['POST'])
@login_required
def api_tracks_bulk_delete():
    if not has_perm('tracks_delete'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data  = request.get_json() or {}
    items = data.get('items') or []
    deleted, failed = 0, []
    for it in items[:500]:
        name   = os.path.basename((it.get('name') or '').strip())
        folder = os.path.basename((it.get('folder') or '').strip())
        if not name or '..' in name:
            failed.append(name or '?'); continue
        if (folder == KAMRAN_FOLDER) and not _kamran_unlocked():
            failed.append(name); continue
        path = os.path.join(MUSIC_DIR, folder, name) if folder else os.path.join(MUSIC_DIR, name)
        if not os.path.isfile(path):
            failed.append(name); continue
        os.remove(path)
        deleted += 1
    log_action(current_user.username, 'bulk_delete_tracks', 'local', f'{deleted} треков')
    return jsonify({'ok': True, 'deleted': deleted, 'failed': failed})

@app.route('/api/tracks/delete-folder', methods=['POST'])
@login_required
def api_tracks_delete_folder():
    if not has_perm('folders_manage'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data = request.get_json() or {}
    name = os.path.basename((data.get('name') or '').strip())
    if not name or '..' in name:
        return jsonify({'ok': False, 'error': 'Недопустимое название'})
    if name == KAMRAN_FOLDER:
        return jsonify({'ok': False, 'error': 'KAMRAN — защищённая PIN-кодом папка, её нельзя удалить'})
    if name not in all_music_folders():
        return jsonify({'ok': False, 'error': 'Папка не найдена'})
    path = os.path.join(MUSIC_DIR, name)
    try:
        entries = os.listdir(path)
    except OSError:
        return jsonify({'ok': False, 'error': 'Папка не найдена'})
    tracks = [f for f in entries if f.lower().endswith(AUDIO_EXTS)]
    if tracks:
        return jsonify({'ok': False, 'error': f'В папке ещё {len(tracks)} треков — сначала перемести или удали их'})
    try:
        os.rmdir(path)
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Не удалось удалить: {e}'})
    log_action(current_user.username, 'delete_music_folder', 'local', name)
    return jsonify({'ok': True, 'folders': all_music_folders()})

@app.route('/api/tracks/rename-folder', methods=['POST'])
@login_required
def api_tracks_rename_folder():
    if not has_perm('folders_manage'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data     = request.get_json() or {}
    name     = os.path.basename((data.get('name') or '').strip())
    new_name = os.path.basename((data.get('new_name') or '').strip())
    if name == KAMRAN_FOLDER:
        return jsonify({'ok': False, 'error': 'KAMRAN — защищённая PIN-кодом папка, её нельзя переименовать'})
    if name not in all_music_folders():
        return jsonify({'ok': False, 'error': 'Папка не найдена'})
    if not new_name or '..' in new_name or not _FOLDER_NAME_RE.match(new_name):
        return jsonify({'ok': False, 'error': 'Недопустимое название папки'})
    if new_name == KAMRAN_FOLDER:
        return jsonify({'ok': False, 'error': 'Это имя зарезервировано за защищённой папкой KAMRAN'})
    existing = {f.lower() for f in all_music_folders() if f != name}
    if new_name.lower() in existing:
        return jsonify({'ok': False, 'error': 'Папка с таким именем уже есть'})
    old_path = os.path.join(MUSIC_DIR, name)
    new_path = os.path.join(MUSIC_DIR, new_name)
    if not os.path.isdir(old_path):
        return jsonify({'ok': False, 'error': 'Папка не найдена'})
    try:
        os.rename(old_path, new_path)
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Не удалось переименовать: {e}'})
    with get_db() as c:
        c.execute('UPDATE favorites SET folder=? WHERE folder=?', (new_name, name))
    log_action(current_user.username, 'rename_music_folder', 'local', f'{name} → {new_name}')
    return jsonify({'ok': True, 'folders': all_music_folders(), 'new_name': new_name})

@app.route('/api/tracks/copy-folder', methods=['POST'])
@login_required
def api_tracks_copy_folder():
    if not has_perm('folders_manage'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data     = request.get_json() or {}
    name     = os.path.basename((data.get('name') or '').strip())
    new_name = os.path.basename((data.get('new_name') or '').strip())
    if name == KAMRAN_FOLDER and not _kamran_unlocked():
        return jsonify({'ok': False, 'error': 'PIN требуется для KAMRAN'})
    if name not in all_music_folders():
        return jsonify({'ok': False, 'error': 'Папка не найдена'})
    if not new_name or '..' in new_name or not _FOLDER_NAME_RE.match(new_name):
        return jsonify({'ok': False, 'error': 'Недопустимое название папки'})
    if new_name == KAMRAN_FOLDER:
        return jsonify({'ok': False, 'error': 'Это имя зарезервировано за защищённой папкой KAMRAN'})
    existing = {f.lower() for f in all_music_folders()}
    if new_name.lower() in existing:
        return jsonify({'ok': False, 'error': 'Папка с таким именем уже есть'})
    src_path = os.path.join(MUSIC_DIR, name)
    dst_path = os.path.join(MUSIC_DIR, new_name)
    if not os.path.isdir(src_path):
        return jsonify({'ok': False, 'error': 'Папка не найдена'})
    try:
        shutil.copytree(src_path, dst_path)
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Не удалось скопировать: {e}'})
    log_action(current_user.username, 'copy_music_folder', 'local', f'{name} → {new_name}')
    return jsonify({'ok': True, 'folders': all_music_folders(), 'new_name': new_name})

@app.route('/api/tracks/move-folder-contents', methods=['POST'])
@login_required
def api_tracks_move_folder_contents():
    if not has_perm('folders_manage'):
        return jsonify({'ok': False, 'error': 'Только админ'})
    data       = request.get_json() or {}
    name       = os.path.basename((data.get('name') or '').strip())
    dst_folder = os.path.basename((data.get('dest_folder') or '').strip())
    if name == dst_folder:
        return jsonify({'ok': False, 'error': 'Папка назначения совпадает с исходной'})
    if (name == KAMRAN_FOLDER or dst_folder == KAMRAN_FOLDER) and not _kamran_unlocked():
        return jsonify({'ok': False, 'error': 'PIN требуется для KAMRAN'})
    folders = all_music_folders()
    if name not in folders:
        return jsonify({'ok': False, 'error': 'Исходная папка не найдена'})
    if dst_folder not in folders:
        return jsonify({'ok': False, 'error': 'Папка назначения не найдена'})
    src_path = os.path.join(MUSIC_DIR, name)
    dst_path = os.path.join(MUSIC_DIR, dst_folder)
    try:
        entries = os.listdir(src_path)
    except OSError:
        return jsonify({'ok': False, 'error': 'Папка не найдена'})
    moved, failed = 0, []
    for fname in entries:
        if not fname.lower().endswith(AUDIO_EXTS):
            continue
        s = os.path.join(src_path, fname)
        d = os.path.join(dst_path, fname)
        if not os.path.isfile(s):
            continue
        if os.path.exists(d):
            failed.append(fname); continue
        os.makedirs(dst_path, exist_ok=True)
        os.rename(s, d)
        moved += 1
    if moved:
        with get_db() as c:
            c.execute('UPDATE favorites SET folder=? WHERE folder=?', (dst_folder, name))
    log_action(current_user.username, 'move_folder_contents', 'local', f'{name} → {dst_folder}: {moved} файлов')
    return jsonify({'ok': True, 'moved': moved, 'failed': failed})

# ══════════════════════════════════════════════════
@app.route('/machines')
@login_required
@perm_required('machines_manage')
def machines_page():
    return render_template('machines.html', perms=user_perms())

# SYSTEM MONITOR
# ══════════════════════════════════════════════════
@app.route('/monitor')
@login_required
def monitor_page():
    if not has_perm('monitor_view'):
        return redirect(url_for('dashboard'))
    return render_template('monitor.html', perms=user_perms(),
                           machines=MACHINES, centos_host=CENTOS_HOST,
                           centos_cockpit=f'http://{CENTOS_HOST}:1991')

@app.route('/api/sysinfo')
@login_required
def api_sysinfo():
    if not has_perm('monitor_view'):
        return jsonify({'ok': False})

    CMD = (
        "MEM=$(free -m | awk 'NR==2{print $2\" \"$3}'); "
        "DISK=$(df -h / | awk 'NR==2{print $5\" \"$4}'); "
        "LOAD=$(uptime | awk -F'average:' '{print $2}' | xargs); "
        "UPTIME=$(uptime -p 2>/dev/null || uptime | awk -F'up ' '{print $2}' | cut -d',' -f1-2 | xargs); "
        "CPU=$(vmstat 1 2 2>/dev/null | awk 'END{if(NF>=15) print 100-$15; else print 0}'); "
        "PLR=$(systemctl is-active campus-player 2>/dev/null || echo na); "
        "DKR=$(systemctl is-active docker 2>/dev/null || echo na); "
        "echo \"$MEM|$DISK|$LOAD|$UPTIME|$CPU|$PLR|$DKR\""
    )

    def get_info(host, user, key=SSH_KEY):
        s = None
        try:
            s = paramiko.SSHClient()
            s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            s.connect(host, username=user, key_filename=key, timeout=5, banner_timeout=15)
            _, out, _ = s.exec_command(CMD, timeout=20)
            raw = out.read().decode('utf-8', errors='replace').strip()
            parts = raw.split('|')
            if len(parts) < 2:
                return {'ok': False, 'error': 'parse error'}
            mt, mu = map(int, parts[0].strip().split())
            dp, df_ = parts[1].strip().split() if len(parts) > 1 else ('?', '?')
            load = parts[2].strip() if len(parts) > 2 else '?'
            uptime_s = parts[3].strip() if len(parts) > 3 else '?'
            cpu_pct = int(parts[4].strip()) if len(parts) > 4 and parts[4].strip().lstrip('-').isdigit() else 0
            player = parts[5].strip() if len(parts) > 5 else 'unknown'
            docker = parts[6].strip() if len(parts) > 6 else 'unknown'
            return {
                'ok': True,
                'mem_total': mt, 'mem_used': mu,
                'mem_pct': round(mu / mt * 100) if mt else 0,
                'disk_pct': dp, 'disk_free': df_,
                'load': load, 'uptime': uptime_s,
                'cpu_pct': max(0, min(100, cpu_pct)),
                'player': player,
                'docker': docker,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        finally:
            if s:
                try: s.close()
                except Exception: pass

    result = {}
    threads, out = [], {}

    def collect(label, host, user, key=SSH_KEY):
        out[label] = get_info(host, user, key)

    targets = [('client1', CLIENT1_HOST, CLIENT1_USER, SSH_KEY)]
    for m in MACHINES:
        if m['host'] != CLIENT1_HOST:
            targets.append((m['id'], m['host'], m.get('user', CLIENT1_USER), SSH_KEY))
    targets.append(('centos', CENTOS_HOST, CENTOS_USER, CENTOS_SSH_KEY))

    for label, host, user, key in targets:
        t = threading.Thread(target=collect, args=(label, host, user, key))
        t.start(); threads.append(t)
    for t in threads:
        t.join(timeout=12)

    return jsonify({'ok': True, 'machines': out})

# ══════════════════════════════════════════════════
# SERVICE RESTART
# ══════════════════════════════════════════════════
_ALLOWED_SERVICES = {'campus-player', 'docker', 'grafana-server', 'prometheus', 'loki'}

@app.route('/api/service/restart', methods=['POST'])
@login_required
@perm_required('service_restart')
def api_service_restart():
    data    = request.get_json() or {}
    machine = data.get('machine', '').strip()
    service = data.get('service', '').strip()
    if service not in _ALLOWED_SERVICES:
        return jsonify({'ok': False, 'error': 'service not allowed'})
    if machine == 'client1':
        host, user, key = CLIENT1_HOST, CLIENT1_USER, SSH_KEY
    elif machine == 'centos':
        host, user, key = CENTOS_HOST, CENTOS_USER, CENTOS_SSH_KEY
    else:
        # client2, and any other campus machine (CGTK, BSTK, etc.) added via
        # /machines — resolved dynamically by id/user/name, strict so a
        # typo errors instead of silently hitting the wrong machine
        m = _resolve_machine(machine, strict=True)
        if not m:
            return jsonify({'ok': False, 'error': f'unknown machine: {machine}'})
        host, user, key = m['host'], m.get('user', CLIENT1_USER), SSH_KEY
    r = ssh_run_on(host, user, f'systemctl restart {service} 2>&1; echo "exit:$?"', key=key)
    log_action(current_user.username, 'service_restart', machine, service)
    return jsonify({'ok': r.get('ok', False), 'output': r.get('data', ''), 'error': r.get('error', '')})

# ══════════════════════════════════════════════════
# MUSIC REQUEST
# ══════════════════════════════════════════════════
@app.route('/api/music-request', methods=['POST'])
@login_required
def api_music_request():
    data    = request.get_json() or {}
    artist  = str(data.get('artist', '')).strip()[:100]
    title   = str(data.get('title', '')).strip()[:200]
    comment = str(data.get('comment', '')).strip()[:300]
    if not title:
        return jsonify({'ok': False, 'error': 'Укажите название трека'})
    log_action(current_user.username, 'music_request', 'local', f'{artist} — {title}')
    tg_text = (
        f'🎵 <b>Запрос музыки</b>\n'
        f'👤 <b>От:</b> {current_user.username}\n'
        f'🎤 <b>Исполнитель:</b> {artist or "не указан"}\n'
        f'🎵 <b>Трек:</b> {title}\n'
    )
    if comment:
        tg_text += f'💬 <b>Комментарий:</b> {comment}\n'
    tg_text += f'🕐 {_tg_fmt_time()}'
    tg_notify(tg_text, event_type='misc')
    return jsonify({'ok': True})

# ══════════════════════════════════════════════════
# CHAT TYPING INDICATOR
# ══════════════════════════════════════════════════
_typing_state: dict = {}   # username -> last_typing_timestamp
_TYPING_TTL = 4            # seconds before "typing" expires

@app.route('/api/chat/typing', methods=['GET', 'POST'])
@login_required
def api_chat_typing():
    if request.method == 'POST':
        _typing_state[current_user.username] = time.time()
        return jsonify({'ok': True})
    now = time.time()
    typing = [u for u, ts in list(_typing_state.items())
              if now - ts < _TYPING_TTL and u != current_user.username]
    # Cleanup stale
    for u in [u for u, ts in list(_typing_state.items()) if now - ts >= _TYPING_TTL]:
        _typing_state.pop(u, None)
    return jsonify({'ok': True, 'typing': typing})

# ══════════════════════════════════════════════════
# PWA MANIFEST
# ══════════════════════════════════════════════════
@app.route('/manifest.json')
def pwa_manifest():
    from flask import Response
    manifest = {
        "name": "Campus Audio",
        "short_name": "Campus",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0d1117",
        "theme_color": "#0d1117",
        "icons": [
            {"src": "/static/media.logo.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/media.logo.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
        ]
    }
    return Response(json.dumps(manifest), mimetype='application/manifest+json')

@app.route('/sw.js')
def pwa_sw():
    from flask import Response
    sw = """
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(clients.claim()); });
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
"""
    return Response(sw, mimetype='application/javascript')

# ══════════════════════════════════════════════════
# SCHEDULE EDITOR
# ══════════════════════════════════════════════════
@app.route('/admin/schedule')
@login_required
@perm_required('schedule_edit')
def admin_schedule():
    return render_template('schedule_editor.html',
                           schedule=SCHEDULE, perms=user_perms())

@app.route('/api/schedule', methods=['GET'])
@login_required
def api_schedule_get():
    return jsonify({'ok': True, 'schedule': SCHEDULE})

@app.route('/api/schedule/add', methods=['POST'])
@login_required
@perm_required('schedule_edit')
def api_schedule_add():
    data = request.get_json() or {}
    entry = {
        'time':    data.get('time', '00:00'),
        'event':   data.get('event', ''),
        'file':    data.get('file', '—'),
        'vol':     int(data['vol']) if data.get('vol') else None,
        'days':    data.get('days', 'Пн–Пт'),
        'dow':     data.get('dow', [0,1,2,3,4]),
        'play':    bool(data.get('play', True)),
        'special': bool(data.get('special', False)),
    }
    with _sched_lock:
        SCHEDULE.append(entry)
        SCHEDULE.sort(key=lambda e: e['time'])
        save_schedule(SCHEDULE)
    log_action(current_user.username, 'sched_add', 'local', entry['time']+' '+entry['event'])
    return jsonify({'ok': True, 'schedule': SCHEDULE})

@app.route('/api/schedule/update/<int:idx>', methods=['POST'])
@login_required
@perm_required('schedule_edit')
def api_schedule_update(idx):
    data = request.get_json() or {}
    with _sched_lock:
        if idx < 0 or idx >= len(SCHEDULE):
            return jsonify({'ok': False, 'error': 'индекс вне диапазона'})
        entry = SCHEDULE[idx]
        if 'time'    in data: entry['time']    = data['time']
        if 'event'   in data: entry['event']   = data['event']
        if 'file'    in data: entry['file']    = data['file']
        if 'vol'     in data: entry['vol']     = int(data['vol']) if data['vol'] else None
        if 'days'    in data: entry['days']    = data['days']
        if 'dow'     in data: entry['dow']     = data['dow']
        if 'play'    in data: entry['play']    = bool(data['play'])
        if 'special' in data: entry['special'] = bool(data['special'])
        SCHEDULE.sort(key=lambda e: e['time'])
        save_schedule(SCHEDULE)
    log_action(current_user.username, 'sched_update', 'local', entry['time'])
    return jsonify({'ok': True, 'schedule': SCHEDULE})

@app.route('/api/schedule/delete/<int:idx>', methods=['POST'])
@login_required
@perm_required('schedule_edit')
def api_schedule_delete(idx):
    with _sched_lock:
        if idx < 0 or idx >= len(SCHEDULE):
            return jsonify({'ok': False, 'error': 'индекс вне диапазона'})
        removed = SCHEDULE.pop(idx)
        save_schedule(SCHEDULE)
    log_action(current_user.username, 'sched_delete', 'local', removed.get('time',''))
    return jsonify({'ok': True, 'schedule': SCHEDULE})

@app.route('/api/schedule/reset', methods=['POST'])
@login_required
@perm_required('schedule_edit')
def api_schedule_reset():
    with _sched_lock:
        SCHEDULE.clear()
        SCHEDULE.extend([dict(e) for e in _SCHEDULE_DEFAULT])
        save_schedule(SCHEDULE)
    log_action(current_user.username, 'sched_reset', 'local', '')
    return jsonify({'ok': True, 'schedule': SCHEDULE})

# ══════════════════════════════════════════════════
# TRACKS SYNC  (client1 local library ⇄ each spoke campus's own copy)
# ══════════════════════════════════════════════════
# client1's local MUSIC_DIR is the master library; every other audio campus keeps
# its own local copy (they can't stream over the network) that needs periodic
# sync. Any client added later via /machines gets the same treatment for free.
def SYNC_CAMPUSES():
    return [_campus_key(m) for m in music_machines() if m['host'] != CLIENT1_HOST]
CLIENT2_MUSIC_DIR = os.environ.get('CLIENT2_MUSIC_DIR', '/var/lib/campus-player/inbox/music')

def _remote_music_dir(campus):
    """Remote inbox music dir for a spoke campus. All campus-player installs
    use the same path by convention (see CLIENT2_MUSIC_DIR default); override
    per campus via <CAMPUS>_MUSIC_DIR env var if a machine's install differs."""
    return os.environ.get(f'{campus.upper()}_MUSIC_DIR', CLIENT2_MUSIC_DIR)

def _list_remote_tracks(host, user, remote_dir):
    s = None
    try:
        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(host, username=user, key_filename=SSH_KEY, timeout=8, banner_timeout=20)
        _, out, _ = s.exec_command(f'ls -1 "{remote_dir}" 2>/dev/null || echo ""', timeout=8)
        files = [l.strip() for l in out.read().decode().splitlines() if l.strip()]
        return set(f for f in files if os.path.splitext(f)[1].lower() in ALLOWED_AUDIO)
    except Exception as e:
        return None, str(e)
    finally:
        if s:
            try: s.close()
            except Exception: pass

@app.route('/api/tracks/sync/status')
@login_required
def api_tracks_sync_status():
    if not has_perm('library_sync'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    local = set(f for f in os.listdir(MUSIC_DIR)
                if os.path.splitext(f)[1].lower() in ALLOWED_AUDIO)
    campuses = {}
    for campus in SYNC_CAMPUSES():
        conn = _client2_conn(campus)
        if not conn:
            campuses[campus] = {'ok': False, 'error': f'{campus} не настроен'}
            continue
        remote = _list_remote_tracks(conn['host'], conn.get('user', CLIENT1_USER), _remote_music_dir(campus))
        if isinstance(remote, tuple):
            campuses[campus] = {'ok': False, 'error': remote[1]}
            continue
        campuses[campus] = {
            'ok': True,
            'only_client1':    sorted(local - remote),
            'only_remote':  sorted(remote - local),
            'both':         sorted(local & remote),
            'remote_count': len(remote),
        }
    return jsonify({'ok': True, 'client1_count': len(local), 'campuses': campuses})

@app.route('/api/tracks/sync', methods=['POST'])
@login_required
def api_tracks_sync():
    if not has_perm('library_sync'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data      = request.get_json() or {}
    campus    = (data.get('campus') or 'client2').strip()
    direction = data.get('direction', 'client1_to_remote')  # 'client1_to_remote' | 'remote_to_client1'
    files     = data.get('files', [])
    if campus not in SYNC_CAMPUSES():
        return jsonify({'ok': False, 'error': f'Неизвестный кампус: {campus}'})
    if not files:
        return jsonify({'ok': False, 'error': 'Список файлов пуст'})
    conn = _client2_conn(campus)
    if not conn:
        return jsonify({'ok': False, 'error': f'{campus} не настроен'})
    remote_host = conn['host']
    remote_user = conn.get('user', CLIENT1_USER)
    remote_dir  = _remote_music_dir(campus)
    copied, errors = [], []
    s = None
    try:
        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(remote_host, username=remote_user, key_filename=SSH_KEY, timeout=10, banner_timeout=20)
        sftp = s.open_sftp()
        s.exec_command(f'mkdir -p "{remote_dir}"')
        import time; time.sleep(0.3)
        for fname in files:
            fname = os.path.basename(fname)
            if not fname or '..' in fname:
                continue
            if direction == 'client1_to_remote':
                local_path  = os.path.join(MUSIC_DIR, fname)
                remote_path = f'{remote_dir}/{fname}'
                if os.path.isfile(local_path):
                    sftp.put(local_path, remote_path)
                    copied.append(fname)
                else:
                    errors.append(f'{fname}: не найден локально')
            else:
                remote_path = f'{remote_dir}/{fname}'
                local_path  = os.path.join(MUSIC_DIR, fname)
                sftp.get(remote_path, local_path)
                copied.append(fname)
        sftp.close()
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e), 'copied': copied})
    finally:
        if s:
            try: s.close()
            except Exception: pass
    campus_label = _MINUTA_LABEL.get(campus, campus)
    log_action(current_user.username, f'sync_{direction}', campus, f'{len(copied)} файлов')
    if copied:
        tg_notify(
            f'🔄 <b>Синхронизация треков</b>\n'
            f'{"client1 → " + campus_label if direction=="client1_to_remote" else campus_label + " → client1"}\n'
            f'📁 {len(copied)} файлов\n'
            f'👤 {current_user.username}\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='upload'
        )
    return jsonify({'ok': True, 'copied': copied, 'errors': errors})

# ══════════════════════════════════════════════════
# TELEGRAM SETTINGS API
# ══════════════════════════════════════════════════
@app.route('/api/tg/test', methods=['POST'])
@login_required
@perm_required('telegram_settings')
def api_tg_test():
    token  = _tg_load_token()
    chats  = _tg_load_chats()
    if not token:
        return jsonify({'ok': False, 'error': 'BOT_TOKEN не настроен'})
    if not chats:
        return jsonify({'ok': False, 'error': 'Нет Chat ID — укажите в настройках или config.env'})
    tg_notify(
        f'🔔 <b>Тест уведомлений</b>\n'
        f'Веб-интерфейс Campus Audio работает.\n'
        f'👤 {current_user.username}\n'
        f'🕐 {_tg_fmt_time()}',
        event_type='misc'
    )
    return jsonify({'ok': True, 'chats': chats})

@app.route('/api/settings/tg', methods=['GET', 'POST'])
@login_required
@perm_required('telegram_settings')
def api_settings_tg():
    if request.method == 'GET':
        with get_db() as c:
            rows = c.execute("SELECT key, value FROM settings WHERE key LIKE 'tg_%'").fetchall()
        return jsonify({'ok': True, 'settings': {r['key']: r['value'] for r in rows}})
    data = request.get_json() or {}
    allowed_keys = {'tg_notify_himn', 'tg_notify_upload', 'tg_notify_users',
                    'tg_notify_play', 'tg_notify_login', 'tg_notify_backup', 'tg_chat_ids'}
    with get_db() as c:
        for k, v in data.items():
            if k in allowed_keys:
                c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (k, str(v)))
    return jsonify({'ok': True})

# ══════════════════════════════════════════════════
# TRACKS GLOBAL PIN
# ══════════════════════════════════════════════════
# ══════════════════════════════════════════════════
# PER-FOLDER PIN
# ══════════════════════════════════════════════════
@app.route('/api/folder/unlock', methods=['POST'])
@login_required
def api_folder_unlock():
    data   = request.get_json() or {}
    pin    = str(data.get('pin', '')).strip()
    folder = os.path.basename(str(data.get('folder', '')).strip())
    if not pin:
        return jsonify({'ok': False, 'error': 'Введите PIN'})
    if not folder or folder not in MUSIC_FOLDERS:
        return jsonify({'ok': False, 'error': 'Неверная папка'})
    pin_key = f'pin_hash_{folder}'
    with get_db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (pin_key,)).fetchone()
        if not row or not row['value']:
            row = c.execute("SELECT value FROM settings WHERE key='tracks_pin_hash'").fetchone()
    if not row or not row['value']:
        if has_perm('admin'):
            unlocked = list(session.get('unlocked_folders', []))
            if folder not in unlocked:
                unlocked.append(folder)
            session['unlocked_folders'] = unlocked
            session.permanent = True
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'PIN не установлен'})
    if check_password_hash(row['value'], pin):
        unlocked = list(session.get('unlocked_folders', []))
        if folder not in unlocked:
            unlocked.append(folder)
        session['unlocked_folders'] = unlocked
        session.permanent = True
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Неверный PIN'})

@app.route('/api/folder/lock', methods=['POST'])
@login_required
def api_folder_lock():
    data   = request.get_json() or {}
    folder = os.path.basename(str(data.get('folder', '')).strip())
    if folder:
        unlocked = [f for f in session.get('unlocked_folders', []) if f != folder]
        session['unlocked_folders'] = unlocked
    else:
        session['unlocked_folders'] = []
    return jsonify({'ok': True})

PIN_OWNER = 'admin'  # only this username can set/change the PIN

@app.route('/api/tracks/set-pin', methods=['POST'])
@login_required
def api_tracks_set_pin():
    if current_user.username != PIN_OWNER:
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data   = request.get_json() or {}
    pin    = str(data.get('pin', '')).strip()
    folder = os.path.basename(str(data.get('folder', '')).strip())
    if not folder or folder not in MUSIC_FOLDERS:
        return jsonify({'ok': False, 'error': 'Укажите папку'})
    if len(pin) < 4:
        return jsonify({'ok': False, 'error': 'PIN минимум 4 символа'})
    h   = generate_password_hash(pin)
    key = f'pin_hash_{folder}'
    with get_db() as c:
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, h))
    unlocked = list(session.get('unlocked_folders', []))
    if folder not in unlocked:
        unlocked.append(folder)
    session['unlocked_folders'] = unlocked
    session.permanent = True
    return jsonify({'ok': True})

# keep old kamran endpoints for compatibility
@app.route('/api/kamran/unlock', methods=['POST'])
@login_required
def api_kamran_unlock():
    data = request.get_json() or {}
    pin  = str(data.get('pin', '')).strip()
    if not pin:
        return jsonify({'ok': False, 'error': 'Введите PIN'})
    with get_db() as c:
        row = c.execute("SELECT value FROM settings WHERE key='kamran_pin_hash'").fetchone()
    if not row or not row['value']:
        return jsonify({'ok': False, 'error': 'PIN не установлен — обратитесь к администратору'})
    if check_password_hash(row['value'], pin):
        session['kamran_unlocked'] = True
        unlocked = list(session.get('unlocked_folders', []))
        if KAMRAN_FOLDER not in unlocked:
            unlocked.append(KAMRAN_FOLDER)
        session['unlocked_folders'] = unlocked
        session.permanent = True
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Неверный PIN'})

@app.route('/api/kamran/lock', methods=['POST'])
@login_required
def api_kamran_lock():
    session.pop('kamran_unlocked', None)
    session['unlocked_folders'] = [f for f in session.get('unlocked_folders', []) if f != KAMRAN_FOLDER]
    return jsonify({'ok': True})

_UI_SKINS   = ('classic', 'modern')
_UI_ACCENTS = ('amber', 'blue', 'green', 'magenta', 'red', 'teal')
_PANEL_COLORS = ('', '#6ea8fe','#c792ea','#f5a3c7','#7bd8b0','#e8b96a',
                  '#6ec9d8','#e79b8f','#9fa8e8','#ff6b6b','#4ecdc4','#ffd93d','#a78bfa')

@app.route('/api/ui-prefs', methods=['GET', 'POST'])
@login_required
def api_ui_prefs():
    """Personal player skin/accent/panel-color — each employee picks their
    own, saved on their account so it follows them to any device they log
    in on."""
    if request.method == 'GET':
        with get_db() as c:
            row = c.execute('SELECT ui_skin, ui_accent, panel_color, ui_variant, ui_palette FROM users WHERE username=?',
                             (current_user.username,)).fetchone()
        return jsonify({'ok': True, 'skin': (row['ui_skin'] if row else 'classic'),
                        'accent': (row['ui_accent'] if row else 'amber'),
                        'panel_color': (row['panel_color'] if row else '') or '',
                        'ui_variant': (row['ui_variant'] if row else '') or '',
                        'ui_palette': (row['ui_palette'] if row else '') or ''})
    data   = request.get_json() or {}
    skin   = data.get('skin')
    accent = data.get('accent')
    updates, params = [], []
    if skin is not None:
        if skin not in _UI_SKINS:
            return jsonify({'ok': False, 'error': 'Неизвестный скин'})
        updates.append('ui_skin=?'); params.append(skin)
    if accent is not None:
        if accent not in _UI_ACCENTS:
            return jsonify({'ok': False, 'error': 'Неизвестный акцент'})
        updates.append('ui_accent=?'); params.append(accent)
    if 'ui_variant' in data:
        v = data.get('ui_variant') or ''
        if v not in _UI_VARIANTS and v not in ('off', ''):
            return jsonify({'ok': False, 'error': 'Неизвестный дизайн'})
        updates.append('ui_variant=?'); params.append(v)
    if 'ui_palette' in data:
        pal = data.get('ui_palette') or ''
        if pal not in _UI_PALETTE_KEYS and pal != '':
            return jsonify({'ok': False, 'error': 'Неизвестная палитра'})
        updates.append('ui_palette=?'); params.append(pal)
    if 'panel_color' in data:
        panel_color = data.get('panel_color') or ''
        if panel_color not in _PANEL_COLORS:
            return jsonify({'ok': False, 'error': 'Неизвестный цвет'})
        updates.append('panel_color=?'); params.append(panel_color)
    if not updates:
        return jsonify({'ok': False, 'error': 'Нечего сохранять'})
    params.append(current_user.username)
    with get_db() as c:
        c.execute(f'UPDATE users SET {", ".join(updates)} WHERE username=?', params)
    return jsonify({'ok': True})

@app.route('/api/kamran/status', methods=['GET'])
@login_required
def api_kamran_status():
    with get_db() as c:
        row = c.execute("SELECT value FROM settings WHERE key='kamran_pin_hash'").fetchone()
    pin_set = bool(row and row['value'])
    return jsonify({'ok': True, 'unlocked': _kamran_unlocked(), 'pin_set': pin_set})

@app.route('/api/kamran/set-pin', methods=['POST'])
@login_required
def api_kamran_set_pin():
    if not has_perm('admin'):
        return jsonify({'ok': False, 'error': 'Только администратор'})
    data = request.get_json() or {}
    pin  = str(data.get('pin', '')).strip()
    if len(pin) < 4:
        return jsonify({'ok': False, 'error': 'PIN минимум 4 символа'})
    with get_db() as c:
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('kamran_pin_hash',?)",
                  (generate_password_hash(pin),))
    session['kamran_unlocked'] = True
    return jsonify({'ok': True})

# ══════════════════════════════════════════════════
# TIME SYNC
# ══════════════════════════════════════════════════
@app.route('/api/timesync/status')
@login_required
def api_timesync_status():
    if not has_perm('timesync'):
        return jsonify({'ok': False})

    def get_time(host, user, key=SSH_KEY):
        s = None
        try:
            s = paramiko.SSHClient()
            s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            s.connect(host, username=user, key_filename=key, timeout=5, banner_timeout=15)
            _, out, _ = s.exec_command('date "+%Y-%m-%d %H:%M:%S"', timeout=5)
            t = out.read().decode().strip()
            return {'ok': True, 'time': t}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        finally:
            if s:
                try: s.close()
                except Exception: pass

    result, threads, out = {}, [], {}

    def collect(label, host, user, key=SSH_KEY):
        out[label] = get_time(host, user, key)

    targets = [
        ('client1',   CLIENT1_HOST,   CLIENT1_USER,   SSH_KEY),
        ('centos', CENTOS_HOST, CENTOS_USER, CENTOS_SSH_KEY),
    ]
    for m in music_machines():
        if m['host'] != CLIENT1_HOST:
            targets.append((_campus_key(m), m['host'], m.get('user', CLIENT1_USER), SSH_KEY))

    for label, host, user, key in targets:
        t = threading.Thread(target=collect, args=(label, host, user, key))
        t.start(); threads.append(t)
    for t in threads:
        t.join(timeout=8)

    return jsonify({'ok': True, 'machines': out,
                    'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

@app.route('/api/timesync/sync', methods=['POST'])
@login_required
def api_timesync_sync():
    if not has_perm('timesync'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data    = request.get_json() or {}
    machine = data.get('machine', 'all')

    # Step 1: get current time from CentOS as the reference
    ref_time = None
    s = None
    try:
        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(CENTOS_HOST, username=CENTOS_USER, key_filename=CENTOS_SSH_KEY,
                  timeout=8, banner_timeout=20)
        _, out, _ = s.exec_command('date "+%Y-%m-%d %H:%M:%S"', timeout=5)
        ref_time = out.read().decode().strip()
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Не удалось получить время с CentOS: {e}'})
    finally:
        if s:
            try: s.close()
            except Exception: pass

    if not ref_time:
        return jsonify({'ok': False, 'error': 'CentOS не вернул время'})

    # Step 2: set this time on campus machines using `date -s`
    # date -s requires root; try sudo, then try ntpdate from centos
    SET_CMD = f'sudo date -s "{ref_time}" 2>/dev/null || date -s "{ref_time}" 2>/dev/null; date "+%Y-%m-%d %H:%M:%S"'

    results = {'centos': {'ok': True, 'time': ref_time, 'note': 'эталон'}}
    targets = []
    if machine in ('all', 'client1'):
        targets.append(('client1', CLIENT1_HOST, CLIENT1_USER, SSH_KEY))
    if machine == 'all':
        for m in music_machines():
            if m['host'] != CLIENT1_HOST:
                targets.append((_campus_key(m), m['host'], m.get('user', CLIENT1_USER), SSH_KEY))
    elif machine != 'client1':
        m = _resolve_machine(machine, strict=True)
        if m:
            targets.append((machine, m['host'], m.get('user', CLIENT1_USER), SSH_KEY))

    def do_sync(label, host, user, key):
        s = None
        try:
            s = paramiko.SSHClient()
            s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            s.connect(host, username=user, key_filename=key, timeout=8, banner_timeout=20)
            _, out, _ = s.exec_command(SET_CMD, timeout=15)
            result_time = out.read().decode().strip().splitlines()[-1] if out else ref_time
            results[label] = {'ok': True, 'time': result_time}
        except Exception as e:
            results[label] = {'ok': False, 'error': str(e)}
        finally:
            if s:
                try: s.close()
                except Exception: pass

    threads = []
    for label, host, user, key in targets:
        t = threading.Thread(target=do_sync, args=(label, host, user, key))
        t.start(); threads.append(t)
    for t in threads:
        t.join(timeout=20)

    log_action(current_user.username, 'timesync', machine, f'ref={ref_time}')
    return jsonify({'ok': True, 'ref_time': ref_time, 'results': results})

# ── Backups ───────────────────────────────────────────────────────────
def _backup_scan():
    """Сканирует папку бэкапов, возвращает список dated-папок, музыку и статс машин."""
    import re
    if not os.path.isdir(BACKUP_DIR):
        return None, [], {}, {}
    entries = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        full = os.path.join(BACKUP_DIR, name)
        if os.path.isdir(full) and re.match(r'^\d{4}-\d{2}-\d{2}$', name):
            files = []
            for fname in sorted(os.listdir(full)):
                fpath = os.path.join(full, fname)
                if os.path.isfile(fpath):
                    sz = os.path.getsize(fpath)
                    files.append({'name': fname, 'size': sz,
                                  'size_h': _fmt_sz(sz), 'mtime': os.path.getmtime(fpath)})
            total = sum(f['size'] for f in files)
            report = ''
            rp = os.path.join(full, 'report.txt')
            if os.path.isfile(rp):
                with open(rp, encoding='utf-8', errors='replace') as f:
                    report = f.read()
            entries.append({'date': name, 'path': full, 'files': files,
                            'total': total, 'total_h': _fmt_sz(total), 'report': report})
    # Размеры музыки (rsync)
    music = {}
    for mname in ('music-client1', 'music-client2', 'music-cgtk'):
        mp = os.path.join(BACKUP_DIR, mname)
        if os.path.isdir(mp):
            sz = _dir_size(mp)
            music[mname] = {'size': sz, 'size_h': _fmt_sz(sz)}
    # Размеры архивов последнего бэкапа по машинам
    machines = {}
    if entries:
        latest_path = entries[0]['path']
        # client1/centos are fixed; every other audio campus is expected to have
        # its own <key>-config.tar.gz produced by the (external, not part of
        # this app) backup cron job — a client added later only shows up here
        # once that job is updated to include it too.
        backup_keys = [('client1', 'client1-config.tar.gz')]
        backup_keys += [(_campus_key(m), f'{_campus_key(m)}-config.tar.gz')
                         for m in music_machines() if m['host'] != CLIENT1_HOST]
        backup_keys.append(('centos', 'centos.tar.gz'))
        for key, fname in backup_keys:
            fp = os.path.join(latest_path, fname)
            if os.path.isfile(fp):
                sz = os.path.getsize(fp)
                machines[key] = {'size_h': _fmt_sz(sz), 'ok': True}
            else:
                machines[key] = {'size_h': '—', 'ok': False}
    return BACKUP_DIR, entries, music, machines

def _fmt_sz(b):
    for u in ('Б', 'КБ', 'МБ', 'ГБ'):
        if b < 1024: return f"{b:.0f} {u}"
        b /= 1024
    return f"{b:.1f} ТБ"

def _dir_size(path):
    total = 0
    for dp, _, fnames in os.walk(path):
        for f in fnames:
            try: total += os.path.getsize(os.path.join(dp, f))
            except: pass
    return total

# ── Сводка «что и как забэкаплено» ───────────────────────────────────
# Данные готовит хост (scripts/backup_status.py, cron */5) в campus-backups/status.json — контейнер видит эту папку
# только для чтения и не имеет доступа ни к логам Proxmox-бэкапа, ни к git, ни к crontab.
_BK_MAX_AGE_DAYS = 9          # недельный бэкап на Proxmox старше этого срока = проблема

def _bk_status():
    p = os.path.join(BACKUP_DIR, 'status.json')
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def _bk_fmt_ts(ts):
    if not ts:
        return ''
    try:
        return datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d %H:%M')
    except (ValueError, OSError, OverflowError):
        return ''

def _bk_days_ago(date_str):
    try:
        return (datetime.now().date() - datetime.strptime(date_str, '%Y-%m-%d').date()).days
    except (ValueError, TypeError):
        return None

def _bk_step_cell(px, names):
    """Ячейка «Proxmox» для строки: состояние худшего из шагов. state: ok|bad|pending|none."""
    last_run = px.get('last_run') or {}
    in_last = {s['name']: s['ok'] for s in last_run.get('steps', [])}
    seen, last_ok = set(px.get('step_seen', [])), px.get('step_last_ok', {})
    worst, when = 'ok', None
    for n in names:
        if n not in seen:
            st, w = 'pending', None
        elif in_last.get(n) is True:
            st, w = 'ok', last_run.get('date')
        else:
            w = last_ok.get(n)
            age = _bk_days_ago(w) if w else None
            st = 'bad' if (w is None or age is None or age > 0) else 'ok'
            if w and st == 'bad' and age is not None and age <= _BK_MAX_AGE_DAYS and last_run.get('result') == 'ok':
                st = 'ok'
        rank = {'ok': 0, 'pending': 1, 'bad': 2}
        if rank[st] > rank[worst]:
            worst = st
        if w and (when is None or w < when):
            when = w
    return {'state': worst, 'when': when}

def _bk_overview(st):
    """Матрица «что → где защищено» и список проблем. Возвращает (health, rows)."""
    now = time.time()
    px, gh, snap = st.get('proxmox', {}), st.get('github', {}), st.get('snapshots', {})
    sec, ldb = st.get('secrets_repo', {}), st.get('local_db', {})
    gh_ok = bool(gh.get('live_sync')) and (gh.get('unpushed') or 0) <= 3
    def gcell(ts):
        return {'state': 'ok' if gh_ok and ts else ('bad' if not gh.get('live_sync') else 'warn'), 'when': _bk_fmt_ts(ts)}
    none = {'state': 'none', 'when': ''}
    ld = (ldb.get('days') or [{}])[0].get('date')
    ld_age = _bk_days_ago(ld) if ld else None
    local_db = {'state': 'ok' if ld_age is not None and ld_age <= 1 else 'bad', 'when': ld or ''}
    rows = [
        ('code',     gcell(gh.get('last_push_ts')), _bk_step_cell(px, ['centos → campus-infra', 'centos → homelab']), none),
        ('users',    gcell(snap.get('webui')),      _bk_step_cell(px, ['centos → webui-data']), local_db),
        ('helpdesk', gcell(snap.get('helpdesk')),   _bk_step_cell(px, ['centos → helpdesk-ops']), local_db),
        ('secrets',  ({'state': 'warn', 'when': _bk_fmt_ts(sec.get('last_commit_ts')), 'note': 'dirty'} if sec.get('exists') and (sec.get('dirty') or 0) > 0
                      else {'state': 'ok' if sec.get('exists') else 'bad', 'when': _bk_fmt_ts(sec.get('last_commit_ts'))}),
                     _bk_step_cell(px, ['centos → campus-secrets', 'centos → ssh-keys']), none),
        ('services', gcell(snap.get('crontab')),   _bk_step_cell(px, ['centos → tg-campus-bot', 'centos → systemd-units']), none),
        ('media',   none,                          _bk_step_cell(px, ['centos → media-music']), none),
        ('music',    none,                          _bk_step_cell(px, ['centos → kamran-music']), none),
        ('client1',     none,                          _bk_step_cell(px, ['client1 → client1-full.tar.gz']), none),
        ('client2',      none,                          _bk_step_cell(px, ['client2 → client2-full.tar.gz']), none),
    ]
    disabled = set(st.get('disabled') or [])
    rows = [{'key': k, 'github': g, 'proxmox': ({'state': 'off', 'when': ''} if k in disabled else p), 'local': l}
            for k, g, p, l in rows]
    problems = []
    def add(level, code, **kw):
        problems.append(dict(level=level, code=code, **kw))
    last = px.get('last_run') or {}
    if not px.get('reachable'):
        add('bad', 'proxmox_down', when=px.get('last_full_ok') or max(px.get('step_last_ok', {}).values(), default=''))
    if last and last.get('result') in ('unreachable', 'aborted'):
        add('bad', 'run_failed', when=last.get('date'))
    elif last and last.get('result') == 'errors':
        add('warn', 'run_errors', when=last.get('date'))
    if any(r['key'] == 'music' and r['proxmox']['state'] == 'pending' for r in rows):
        add('warn', 'music_pending')
    if any(r['key'] == 'music' and r['proxmox']['state'] == 'bad' for r in rows):
        add('bad', 'music_missing')
    for r in rows:                      # отключённые машины (config/backup-disabled.txt) — не проблема
        if px.get('reachable') and r['key'] in ('client1', 'client2') and r['proxmox']['state'] == 'bad':   # если Proxmox лежит — причина уже названа выше
            add('bad', 'machine_missing', name=r['key'])
    if not gh.get('live_sync'):
        add('bad', 'github_sync_off')
    elif (gh.get('unpushed') or 0) > 3:
        add('warn', 'github_unpushed')
    if sec.get('exists') and (sec.get('dirty') or 0) > 0:
        add('warn', 'secrets_dirty', n=sec.get('dirty'))
    v = st.get('verify') or {}
    if not v.get('ok'):
        add('bad', 'restore_verify')
    if ld_age is None or ld_age > 1:
        add('bad', 'local_db_old', when=ld or '')
    if now - st.get('generated_at', 0) > 20 * 60:
        add('warn', 'status_stale', when=_bk_fmt_ts(st.get('generated_at')))
    level = 'bad' if any(p['level'] == 'bad' for p in problems) else ('warn' if problems else 'ok')
    return {'level': level, 'problems': problems}, rows

def _bk_schedule_view(st):
    out = {}
    for k, j in (st.get('schedule') or {}).items():
        try:
            hh = j['h'] if j['h'] == '*' else '%02d' % int(j['h'])
            mm = '%02d' % int(j['m'])
        except ValueError:
            continue
        out[k] = {'dow': j['dow'], 'time': f'{hh}:{mm}'}
    return out

@app.route('/backups')
@login_required
def backups_page():
    if not has_perm('backups'):
        return redirect(url_for('dashboard'))
    unlocked = session.get('backup_unlocked', False)
    base, entries, music, machines = _backup_scan()
    st = _bk_status()
    health, rows = _bk_overview(st) if st else ({'level': 'warn', 'problems': [{'level': 'warn', 'code': 'no_status'}]}, [])
    st = st or {}
    px, gh = st.get('proxmox', {}), st.get('github', {})
    last_run = px.get('last_run') or {}
    vitems = (st.get('verify') or {}).get('items') or []
    vchecks = {k: any(i.get('ok') and i.get('text', '').startswith(pre) for i in vitems)
               for k, pre in (('webui', 'webui.db.enc'), ('helpdesk', 'helpdesk_ops.db.enc'), ('uploads', 'helpdesk_ops_uploads'))}
    return render_template('backups.html',
                           backup_dir=base, entries=entries, music=music,
                           machines=machines, unlocked=unlocked,
                           has_vault=bool(BACKUP_UI_PASS or BACKUP_VAULT_PASS),
                           admin_emails=BACKUP_ADMIN_EMAILS,
                           st=st, health=health, rows=rows, px=px, gh=gh, last_run=last_run, vchecks=vchecks,
                           schedule=_bk_schedule_view(st), fmt_ts=_bk_fmt_ts, fmt_sz=_fmt_sz,
                           updated=_bk_fmt_ts(st.get('generated_at')))

@app.route('/api/backup/unlock', methods=['POST'])
@login_required
def api_backup_unlock():
    if not has_perm('backups'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data = request.get_json() or {}
    pwd  = data.get('password', '')
    expected = BACKUP_UI_PASS or BACKUP_VAULT_PASS
    if not expected:
        return jsonify({'ok': False, 'error': 'BACKUP_UI_PASS не задан'})
    import hmac
    if hmac.compare_digest(str(pwd).strip().encode(), expected.encode()):
        session['backup_unlocked'] = True
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Неверный пароль'})

@app.route('/api/backup/lock', methods=['POST'])
@login_required
def api_backup_lock():
    session.pop('backup_unlocked', None)
    return jsonify({'ok': True})

@app.route('/api/backup/download/<backup_date>/<path:filename>')
@login_required
def api_backup_download(backup_date, filename):
    if not has_perm('backups'):
        return '', 403
    if not session.get('backup_unlocked', False):
        return jsonify({'ok': False, 'error': 'Папка заблокирована'}), 403
    import re
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', backup_date):
        return '', 400
    safe_name = os.path.basename(filename)
    file_path = os.path.join(BACKUP_DIR, backup_date, safe_name)
    if not os.path.isfile(file_path):
        return '', 404
    from flask import send_file
    return send_file(file_path, as_attachment=True)

@app.route('/api/backup/report/<backup_date>')
@login_required
def api_backup_report(backup_date):
    if not has_perm('backups'):
        return '', 403
    import re
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', backup_date):
        return '', 400
    rp = os.path.join(BACKUP_DIR, backup_date, 'report.txt')
    if not os.path.isfile(rp):
        return '', 404
    with open(rp, encoding='utf-8', errors='replace') as f:
        return f.read(), 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/api/voice/upload', methods=['POST'])
@login_required
def api_voice_upload():
    audio = request.files.get('audio')
    if not audio:
        return jsonify({'ok': False, 'error': 'no file'}), 400
    ext = 'webm'
    ct = audio.content_type or ''
    if 'ogg' in ct:  ext = 'ogg'
    elif 'mp4' in ct or 'aac' in ct: ext = 'mp4'
    to_user = request.form.get('to_user') or None
    fname = f"voice_{int(time.time()*1000)}_{current_user.username}.{ext}"
    audio.save(os.path.join(VOICE_DIR, fname))
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            'INSERT INTO messages (from_user, to_user, content, sent_at, voice_file) VALUES (?,?,?,?,?)',
            (current_user.username, to_user, '[voice]', now, fname)
        )
    return jsonify({'ok': True, 'file': fname})

@app.route('/api/voice/<path:filename>')
@login_required
def api_voice_file(filename):
    safe = os.path.basename(filename)
    path = os.path.join(VOICE_DIR, safe)
    if not os.path.isfile(path):
        return '', 404
    from flask import send_file
    mime = 'audio/webm'
    if safe.endswith('.ogg'): mime = 'audio/ogg'
    elif safe.endswith('.mp4'): mime = 'audio/mp4'
    return send_file(path, mimetype=mime)

@app.route('/api/voice-assistant', methods=['POST'])
@login_required
def api_voice_assistant():
    import base64 as _b64
    audio = request.files.get('audio')
    if not audio:
        return jsonify({'ok': False, 'error': 'no audio file'})
    ext = 'webm'
    ct = audio.content_type or ''
    if 'ogg' in ct: ext = 'ogg'
    elif 'wav' in ct: ext = 'wav'
    tmp = os.path.join(VOICE_DIR, f'va_{int(time.time()*1000)}.{ext}')
    tts_out = tmp + '.reply.mp3'
    audio.save(tmp)
    try:
        import sys as _sys
        _sys.path.insert(0, '/app')
        from voice_cmd import handle_voice, tts
        campus = request.form.get('campus', 'both')
        result = handle_voice(tmp, campus)
        log_action(current_user.username, 'voice_cmd', campus, result.get('text', ''))
        # Generate TTS and embed as base64 in JSON response
        reply_text = result.get('reply', '')
        if reply_text and tts(reply_text, tts_out):
            with open(tts_out, 'rb') as f:
                result['audio_b64'] = _b64.b64encode(f.read()).decode()
            try: os.unlink(tts_out)
            except Exception: pass
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'text': '', 'reply': f'Ошибка: {e}', 'action': 'error'})
    finally:
        try: os.unlink(tmp)
        except Exception: pass

@app.route('/cheatsheet')
@login_required
def cheatsheet_page():
    if not has_perm('cheatsheet'):
        return '', 403
    return render_template('cheatsheet.html')

@app.route('/announce')
@login_required
def announce_page():
    if not has_perm('mic'):
        return '', 403
    return render_template('announce.html', music_machines=music_machines_json())

@app.route('/api/announce', methods=['POST'])
@login_required
def api_announce():
    if not has_perm('mic'):
        return jsonify({'ok': False, 'error': 'Нет прав'}), 403
    audio = request.files.get('audio')
    if not audio:
        return jsonify({'ok': False, 'error': 'Нет аудио'})
    campuses = request.form.get('campuses', 'all')
    fname = f"announce_{int(time.time()*1000)}_{current_user.username}.webm"
    fpath = os.path.join(ANNOUNCE_DIR, fname)
    audio.save(fpath)

    volume = max(50, min(160, int(request.form.get('volume', 150))))

    def _play_on(host, user, campus_id):
        # campus-playerctl's `play` silently ignores the volume arg (same
        # known bug as himn/minuta) — set volume via direct mpv IPC instead.
        s = None
        try:
            s = paramiko.SSHClient()
            s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            s.connect(host, username=user, key_filename=SSH_KEY, timeout=10)
            sftp = s.open_sftp()
            remote_path = '/tmp/campus_announce.webm'
            sftp.put(fpath, remote_path)
            sftp.close()
            cmd = (
                'SOCK=/run/campus-player/mpv.sock; '
                f'[ -S "$SOCK" ] || {{ echo "no socket"; exit 1; }}; '
                f'echo \'{{"command":["set_property","volume",{volume}]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; '
                f'echo \'{{"command":["set_property","pause",false]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; '
                f'echo \'{{"command":["loadfile","{remote_path}","replace"]}}\' | socat - UNIX-CONNECT:"$SOCK"; '
                f'sleep 0.3; '
                f'echo \'{{"command":["set_property","pause",false]}}\' | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1; true'
            )
            _, out, err = s.exec_command(cmd, timeout=10)
            out_data = out.read().decode('utf-8', 'replace')
            err.read()
            if 'no socket' in out_data:
                return 'нет сокета mpv'
            log_action(current_user.username, 'announce', campus_id, fname)
            return True
        except Exception as e:
            return str(e)
        finally:
            if s:
                try: s.close()
                except Exception: pass

    # 'all' means "every registered audio campus" — any client added later via
    # /machines gets announcements automatically, same convention as the
    # cron-pause 'both' handling above
    results = {}
    if campuses == 'all':
        for m in music_machines():
            ck = _campus_key(m)
            results[ck] = _play_on(m['host'], m.get('user', CLIENT1_USER), ck)
    elif campuses == 'client1':
        results['client1'] = _play_on(CLIENT1_HOST, CLIENT1_USER, 'client1')
    else:
        m = _resolve_machine(campuses, strict=True)
        if m:
            results[campuses] = _play_on(m['host'], m.get('user', CLIENT1_USER), campuses)

    campus_label = {'all': 'Все кампусы'}.get(campuses) or _MINUTA_LABEL.get(campuses, campuses)
    tg_notify(
        f'📢 <b>Объявление по радио</b>\n'
        f'🏫 {campus_label}\n'
        f'👤 {current_user.username}\n'
        f'🕐 {_tg_fmt_time()}',
        event_type='himn'
    )
    ok = all(v is True for v in results.values())
    return jsonify({'ok': ok, 'results': results})

# ══════════════════════════════════════════════════
# BUG / ISSUE REPORTS
# ══════════════════════════════════════════════════
@app.route('/api/bug_report', methods=['POST'])
def api_bug_report():
    data = request.get_json() or {}
    msg = (data.get('message') or '').strip()
    if not msg:
        return jsonify({'ok': False, 'error': 'Пустое сообщение'})
    username = current_user.username if current_user.is_authenticated else 'anonymous'
    category = (data.get('category') or 'bug').strip()[:32]
    campus   = (data.get('campus')   or '').strip()[:32]
    with get_db() as c:
        c.execute(
            'INSERT INTO bug_reports(username,message,category,campus) VALUES(?,?,?,?)',
            (username, msg[:2000], category, campus)
        )
    cat_icons = {'bug': '🐛', 'idea': '💡', 'equipment': '🔧', 'other': '📝'}
    icon = cat_icons.get(category, '📝')
    tg_notify(
        f'{icon} <b>Отчёт о проблеме</b>\n'
        f'👤 {username}  🏫 {campus or "—"}\n'
        f'📂 {category}\n'
        f'📝 {msg[:500]}\n'
        f'🕐 {_tg_fmt_time()}',
        event_type='misc'
    )
    return jsonify({'ok': True})

@app.route('/api/bug_reports/list')
@login_required
@perm_required('bug_reports')
def api_bug_reports_list():
    with get_db() as c:
        rows = c.execute(
            'SELECT * FROM bug_reports ORDER BY created_at DESC LIMIT 200'
        ).fetchall()
    return jsonify({'ok': True, 'reports': [dict(r) for r in rows]})

@app.route('/api/bug_reports/status', methods=['POST'])
@login_required
@perm_required('bug_reports')
def api_bug_reports_status():
    data = request.get_json() or {}
    rid    = data.get('id')
    status = (data.get('status') or 'new').strip()
    if status not in ('new', 'in_progress', 'resolved', 'closed'):
        return jsonify({'ok': False, 'error': 'Bad status'})
    with get_db() as c:
        c.execute('UPDATE bug_reports SET status=? WHERE id=?', (status, rid))
    return jsonify({'ok': True})

init_db()
ensure_role_perms()
_start_volume_guard()

if __name__ == '__main__':
    ssl_ctx = None
    if os.path.exists('/app/ssl.crt') and os.path.exists('/app/ssl.key'):
        ssl_ctx = ('/app/ssl.crt', '/app/ssl.key')
    app.run(host='0.0.0.0', port=8080, debug=False, ssl_context=ssl_ctx)
