from flask import Flask, render_template, redirect, url_for, request, jsonify, flash, session, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, re, json, glob, socket, threading, time
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
BACKUP_ADMIN_EMAILS = os.environ.get('BACKUP_ADMIN_EMAILS', '')
VOICE_DIR = os.path.join(os.path.dirname(DB_PATH), 'voices')
os.makedirs(VOICE_DIR, exist_ok=True)
ANNOUNCE_DIR = os.path.join(os.path.dirname(DB_PATH), 'announces')
os.makedirs(ANNOUNCE_DIR, exist_ok=True)

# ── Machines ──────────────────────────────────────
MACHINES = []   # rebuilt by reload_machines() after DB init

def reload_machines():
    """Rebuild MACHINES from env vars + DB thin_clients table."""
    global MACHINES
    machines = []
    for _i in range(1, 6):
        _h = os.environ.get(f'MACHINE{_i}_HOST', '')
        _n = os.environ.get(f'MACHINE{_i}_NAME', '')
        _m = os.environ.get(f'MACHINE{_i}_MAC', '')
        _u = os.environ.get(f'MACHINE{_i}_USER', CLIENT1_USER)
        _c = os.environ.get(f'MACHINE{_i}_COCKPIT', '')
        if _h and _n:
            machines.append({'id': f'm{_i}', 'host': _h, 'name': _n, 'mac': _m,
                              'user': _u, 'cockpit_url': _c, 'from_db': False})
    if not any(m['host'] == CLIENT1_HOST for m in machines):
        machines.insert(0, {
            'id': 'client1', 'host': CLIENT1_HOST,
            'name': 'Client1 Campus',
            'mac': os.environ.get('CLIENT1_MAC', ''),
            'user': CLIENT1_USER,
            'cockpit_url': f'http://{CLIENT1_HOST}:1991',
            'from_db': False,
        })
    try:
        with get_db() as c:
            rows = c.execute('SELECT * FROM thin_clients ORDER BY id').fetchall()
        for row in rows:
            machines.append({
                'id':          f'db_{row["id"]}',
                'host':        row['host'],
                'name':        row['name'],
                'mac':         row['mac'],
                'user':        row['user'],
                'cockpit_url': row['cockpit_url'],
                'from_db':     True,
                'db_id':       row['id'],
            })
    except Exception:
        pass
    MACHINES = machines

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
    try:
        with get_db() as c:
            c.execute(
                'INSERT INTO activity_log (username,action,machine,detail,happened_at) VALUES (?,?,?,?,?)',
                (username, action, machine, detail, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
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

# Roles: guest=view only, user=music only, staff=music+himn, admin=full
ROLE_PERMS = {
    'guest':  frozenset(),
    'user':   frozenset({'play', 'volume', 'mute', 'stop', 'next', 'prev'}),
    'staff':  frozenset({'play', 'volume', 'mute', 'stop', 'next', 'prev', 'himn'}),
    'viewer': frozenset({'play', 'volume', 'mute', 'stop', 'next', 'prev'}),  # legacy
    'admin':  frozenset({'play', 'volume', 'mute', 'stop', 'next', 'prev', 'himn', 'admin'}),
}

ROLE_LABELS = {
    'guest': ('Гость',   'Только просмотр — кнопки управления недоступны'),
    'user':  ('Польз.',  'Музыка: включать, останавливать, регулировать громкость'),
    'staff': ('Персонал','Музыка + гимн: все функции кроме управления пользователями'),
    'admin': ('Админ',   'Полный доступ: управление пользователями и всеми функциями'),
}

def _silence_active():
    try:
        with get_db() as c:
            row = c.execute("SELECT value FROM settings WHERE key='silence_mode'").fetchone()
            return row and row['value'] == '1'
    except Exception:
        return False

def has_perm(perm):
    role = getattr(current_user, 'role', 'guest')
    if perm == 'play' and role not in ('admin',) and _silence_active():
        return False
    return perm in ROLE_PERMS.get(role, frozenset())

def has_himn_perm():
    """Staff/admin always. Others only if can_himn=1 granted by admin."""
    role = getattr(current_user, 'role', '')
    if role in ('admin', 'staff'):
        return True
    with get_db() as c:
        row = c.execute('SELECT can_himn FROM users WHERE id=?', (current_user.id,)).fetchone()
        return bool(row and row['can_himn'])

def user_perms():
    """Dict of permission flags for current user — for template rendering."""
    return {
        'play':  has_perm('play'),
        'stop':  has_perm('stop'),
        'vol':   has_perm('volume'),
        'mute':  has_perm('mute'),
        'next':  has_perm('next'),
        'prev':  has_perm('prev'),
        'himn':  has_himn_perm(),
        'admin': has_perm('admin'),
        'role':  getattr(current_user, 'role', 'guest'),
    }

# ── SSH / MPV ─────────────────────────────────────
def ssh_run_on(host, user, cmd, key=None):
    if key is None:
        key = SSH_KEY
    s = None
    try:
        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(host, username=user, key_filename=key, timeout=5)
        _, out, _ = s.exec_command(cmd, timeout=15)
        result = out.read().decode().strip()
        return {'ok': True, 'data': result}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
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

def mpv_set_all(prop, val):
    """Set mpv property on client1 and all additional machines."""
    cmd = {'command': ['set_property', prop, val]}
    r = mpv_cmd(cmd)
    for m in MACHINES:
        if m['host'] != CLIENT1_HOST:
            mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cmd)
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
    result = []
    for m in MACHINES:
        result.append({
            'id':     m['id'],
            'name':   m['name'],
            'host':   m['host'],
            'has_mac': bool(m['mac']),
            'online': host_online(m['host']),
        })
    return jsonify({'ok': True, 'machines': result})

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
@admin_only
def api_machines_list():
    with get_db() as c:
        rows = c.execute('SELECT * FROM thin_clients ORDER BY id').fetchall()
    return jsonify({'ok': True, 'machines': [dict(r) for r in rows]})

@app.route('/api/machines/add', methods=['POST'])
@login_required
@admin_only
def api_machines_add():
    data = request.get_json() or {}
    host = data.get('host', '').strip()
    name = data.get('name', '').strip()
    mac  = data.get('mac',  '').strip()
    user = data.get('user', CLIENT1_USER).strip() or CLIENT1_USER
    cockpit = data.get('cockpit_url', f'http://{host}:1991').strip()
    if not host or not name:
        return jsonify({'ok': False, 'error': 'IP-адрес и имя обязательны'})
    with get_db() as c:
        c.execute('INSERT INTO thin_clients (host,name,mac,user,cockpit_url) VALUES (?,?,?,?,?)',
                  (host, name, mac, user, cockpit))
    reload_machines()
    sync_prometheus_targets()
    log_action(current_user.username, 'machine_add', 'webui', f'{name} ({host})')
    return jsonify({'ok': True})

@app.route('/api/machines/edit/<int:db_id>', methods=['POST'])
@login_required
@admin_only
def api_machines_edit(db_id):
    data = request.get_json() or {}
    host = data.get('host', '').strip()
    name = data.get('name', '').strip()
    mac  = data.get('mac',  '').strip()
    user = data.get('user', CLIENT1_USER).strip() or CLIENT1_USER
    cockpit = data.get('cockpit_url', '').strip()
    if not host or not name:
        return jsonify({'ok': False, 'error': 'IP-адрес и имя обязательны'})
    with get_db() as c:
        c.execute('UPDATE thin_clients SET host=?,name=?,mac=?,user=?,cockpit_url=? WHERE id=?',
                  (host, name, mac, user, cockpit, db_id))
    reload_machines()
    sync_prometheus_targets()
    log_action(current_user.username, 'machine_edit', 'webui', f'{name} ({host})')
    return jsonify({'ok': True})

@app.route('/api/machines/delete/<int:db_id>', methods=['POST'])
@login_required
@admin_only
def api_machines_delete(db_id):
    with get_db() as c:
        row = c.execute('SELECT name,host FROM thin_clients WHERE id=?', (db_id,)).fetchone()
        c.execute('DELETE FROM thin_clients WHERE id=?', (db_id,))
    reload_machines()
    if row:
        log_action(current_user.username, 'machine_delete', 'webui', f'{row["name"]} ({row["host"]})')
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

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    ip  = request.remote_addr or '0.0.0.0'
    now = time.time()
    rec = _login_attempts.get(ip, {'count': 0, 'lockout_until': 0.0})
    if rec['lockout_until'] > now:
        mins = int((rec['lockout_until'] - now) // 60) + 1
        flash(f'Слишком много неудачных попыток. Попробуйте через {mins} мин.', 'danger')
        return render_template('login.html')
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        with get_db() as c:
            row = c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        if row and dict(row).get('is_blocked'):
            flash('Ваш аккаунт заблокирован. Обратитесь к администратору.', 'danger')
            return render_template('login.html')
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
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    uname = current_user.username
    role  = current_user.role
    logout_user()
    tg_notify(f'👋 <b>Выход из системы</b>\n👤 <b>{uname}</b> [{role}]\n🕐 {_tg_fmt_time()}',
              event_type='login')
    return redirect(url_for('login'))

@app.context_processor
def inject_globals():
    result = {'ann_count': 0, 'wallpaper_default': 'off', 'theme_default': ''}
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
    if current_user.role != 'admin':
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
    if current_user.role != 'admin':
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
                           is_admin=(current_user.role=='admin'))

@app.route('/api/announcements', methods=['GET'])
@login_required
def api_announcements():
    with get_db() as c:
        rows = c.execute('SELECT * FROM announcements ORDER BY pin_top DESC, id DESC').fetchall()
    return jsonify({'ok': True, 'announcements': [dict(r) for r in rows]})

@app.route('/api/announcements/create', methods=['POST'])
@login_required
def api_ann_create():
    if current_user.role != 'admin':
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
    if current_user.role != 'admin':
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
    if current_user.role != 'admin':
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
    if current_user.role != 'admin':
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
    if current_user.role != 'admin':
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
    if current_user.role != 'admin':
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
    if current_user.role != 'admin':
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
    now = datetime.now()
    ct  = now.strftime('%H:%M')
    next_ev = next((e for e in SCHEDULE if e['time'] > ct and e['play']), None)

    tomorrow = now + timedelta(days=1)
    tdow = tomorrow.weekday()  # 0=Mon, 6=Sun
    _DOW_RU = ['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье']
    tomorrow_events = [e for e in SCHEDULE if e['play'] and tdow in e.get('dow', [])]

    return render_template('dashboard.html',
        schedule=SCHEDULE, next_ev=next_ev, now=now,
        tomorrow_date=tomorrow.strftime('%d.%m'),
        tomorrow_name=_DOW_RU[tdow],
        tomorrow_dow_idx=tdow,
        tomorrow_is_weekend=(tdow >= 5),
        tomorrow_events=tomorrow_events,
        perms=user_perms(),
        music_folders=all_music_folders(),
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
                           open_pin_for='')

@app.route('/admin')
@login_required
@admin_only
def admin():
    with get_db() as c:
        users = c.execute('SELECT * FROM users ORDER BY id').fetchall()
    return render_template('admin.html', users=users, role_labels=ROLE_LABELS)

@app.route('/admin/users/add', methods=['POST'])
@login_required
@admin_only
def add_user():
    u    = request.form.get('username','').strip()
    p    = request.form.get('password','')
    role = request.form.get('role','user')
    if role not in ('guest', 'user', 'staff', 'admin'):
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
@admin_only
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
@admin_only
def reset_passwd(uid):
    p = request.form.get('password','')
    if p:
        with get_db() as c:
            c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(p),uid))
        flash('Пароль изменён', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/users/role/<int:uid>', methods=['POST'])
@login_required
@admin_only
def set_role(uid):
    role = request.form.get('role', 'user')
    if role not in ('guest', 'user', 'staff', 'admin'):
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
@admin_only
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
@admin_only
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
@admin_only
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
@admin_only
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
@admin_only
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
        w.writerow(['id', 'username', 'action', 'machine', 'detail', 'happened_at'])
        for r in rows:
            w.writerow([r['id'], r['username'], r['action'], r['machine'], r['detail'], r['happened_at']])
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
    if not has_perm('admin'):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    client2  = _client2_conn('client2')
    cgtk = _client2_conn('cgtk')
    result = {'client1': _cron_is_paused(CLIENT1_HOST, CLIENT1_USER)}
    if client2:
        result['client2'] = _cron_is_paused(client2['host'], client2.get('user', 'client2'))
    if cgtk:
        result['cgtk'] = _cron_is_paused(cgtk['host'], cgtk.get('user', 'cgtk'))
    return jsonify({'ok': True, **result})

@app.route('/api/cron/pause', methods=['POST'])
@login_required
def api_cron_pause_set():
    if not has_perm('admin'):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    data    = request.json or {}
    machine = data.get('machine', 'both')
    paused  = bool(data.get('paused', True))
    cmd     = f'touch ~/{_CRON_PAUSE_FILE}' if paused else f'rm -f ~/{_CRON_PAUSE_FILE}'
    client2     = _client2_conn('client2')
    cgtk    = _client2_conn('cgtk')
    if machine in ('client1', 'both'):
        ssh_run_on(CLIENT1_HOST, CLIENT1_USER, cmd)
    if machine in ('client2', 'both') and client2:
        ssh_run_on(client2['host'], client2.get('user', 'client2'), cmd)
    # 'both' now means "all registered campuses" (client1 + client2 + cgtk), not just two
    if machine in ('cgtk', 'both') and cgtk:
        ssh_run_on(cgtk['host'], cgtk.get('user', 'cgtk'), cmd)
    return jsonify({'ok': True, 'paused': paused, 'machine': machine})

# ── API ───────────────────────────────────────────
@app.route('/api/status')
@login_required
def api_status():
    machine = request.args.get('machine', 'client1')
    if machine != 'client1':
        m = next((x for x in MACHINES
                  if x.get('host') and x['host'] != CLIENT1_HOST and
                     (x.get('user','') == machine or x['host'].endswith(machine))), None)
        if m:
            host, user = m['host'], m.get('user', CLIENT1_USER)
            path   = mpv_get_on(host, user, 'path')
            paused = mpv_get_on(host, user, 'pause')
            vol    = mpv_get_on(host, user, 'volume')
            muted  = mpv_get_on(host, user, 'mute')
            pos    = mpv_get_on(host, user, 'time-pos')
            dur    = mpv_get_on(host, user, 'duration')
            raw_name = os.path.basename(path) if path else None
            if raw_name and raw_name.lower() in ('in.mp3','in.wav','in.ogg'):
                with get_db() as c:
                    last = c.execute(
                        "SELECT track_name,played_at,username FROM play_log "
                        "WHERE played_at LIKE ? ORDER BY id DESC LIMIT 1",
                        (datetime.now().strftime('%Y-%m-%d')+'%',)
                    ).fetchone()
                raw_name = last['track_name'] if last else raw_name
            return jsonify({'playing': bool(path) and not paused, 'track': raw_name,
                            'paused': bool(paused), 'muted': bool(muted),
                            'volume': round(vol) if vol is not None else None,
                            'position': round(pos, 1) if pos is not None else None,
                            'duration': round(dur, 1) if dur is not None else None})
        return jsonify({'playing': False, 'track': None, 'error': 'not found'})

    path     = mpv_get('path')
    vol      = mpv_get('volume')
    paused   = mpv_get('pause')
    muted    = mpv_get('mute')
    pos      = mpv_get('time-pos')
    dur      = mpv_get('duration')
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
    return jsonify({
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
    })

def _mpv_stop_on(host, user):
    # 1. Graceful IPC stop: mpv stays alive (systemd won't restart), clears playlist.
    # 2. Kill remaining audio tools (ffmpeg announces, edge-tts TTS, bells).
    # Avoid pkill mpv: killing mpv causes systemd Restart=always to relaunch it,
    # which looks like "stop didn't work" — the IPC stop is instant and cleaner.
    ssh_run_on(host, user,
        f'printf \'{{"command":["stop"]}}\\n\' | socat - {MPV_SOCK} 2>/dev/null || true; '
        f'printf \'{{"command":["playlist-clear"]}}\\n\' | socat - {MPV_SOCK} 2>/dev/null || true; '
        'pkill -9 ffmpeg 2>/dev/null || true; '
        'pkill -9 aplay  2>/dev/null || true; '
        'pkill -9 paplay 2>/dev/null || true; '
        'pkill -9 edge-tts 2>/dev/null || true; true')

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
        client2 = next((m for m in MACHINES if m['host'] != CLIENT1_HOST), None)
        host = client2['host'] if client2 else CLIENT2_HOST
        user = client2.get('user', CLIENT2_USER) if client2 else CLIENT2_USER
        if not host:
            return jsonify({'ok': False, 'error': 'client2 не настроен'})
        r = mpv_cmd_on(host, user, cmd)
    log_action(current_user.username, 'pause', machine)
    return jsonify(r if isinstance(r, dict) else {'ok': True})

@app.route('/api/stop', methods=['POST'])
@login_required
def api_stop():
    if not has_perm('stop'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    _mpv_stop_on(CLIENT1_HOST, CLIENT1_USER)
    for m in MACHINES:
        if m['host'] != CLIENT1_HOST:
            _mpv_stop_on(m['host'], m.get('user', CLIENT1_USER))
    log_action(current_user.username, 'stop', 'all')
    return jsonify({'ok': True})

@app.route('/api/stop/client1', methods=['POST'])
@login_required
def api_stop_client1():
    if not has_perm('stop'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    _mpv_stop_on(CLIENT1_HOST, CLIENT1_USER)
    log_action(current_user.username, 'stop', 'client1')
    return jsonify({'ok': True})

@app.route('/api/stop/client2', methods=['POST'])
@login_required
def api_stop_client2():
    if not has_perm('stop'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    client2 = next((m for m in MACHINES if m['host'] != CLIENT1_HOST), None)
    host = client2['host'] if client2 else CLIENT2_HOST
    user = client2.get('user', CLIENT2_USER) if client2 else CLIENT2_USER
    if host:
        _mpv_stop_on(host, user)
    log_action(current_user.username, 'stop', 'client2')
    return jsonify({'ok': True})

@app.route('/api/stop/cgtk', methods=['POST'])
@login_required
def api_stop_cgtk():
    if not has_perm('stop'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    cgtk = _client2_conn('cgtk')
    if cgtk:
        _mpv_stop_on(cgtk['host'], cgtk.get('user', 'cgtk'))
    log_action(current_user.username, 'stop', 'cgtk')
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

def _play_himn(host, user, filepath, vol):
    r = ssh_run_on(host, user,
        f'/usr/local/bin/campus-playerctl play "{filepath}" {vol} 2>/dev/null')
    return r

def _log_himn_play(username, machine, filename):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_action(username, 'himn', machine, filename)
    # also write to play_log so it shows in history
    with get_db() as c:
        c.execute('INSERT INTO play_log (username, track_name, played_at) VALUES (?,?,?)',
                  (username, f'[гимн] {filename}', ts))

@app.route('/api/himn/client1', methods=['POST'])
@login_required
def api_himn_client1():
    if not has_himn_perm():
        return jsonify({'ok': False, 'error': 'Нет прав на гимн'})
    r = _play_himn(CLIENT1_HOST, CLIENT1_USER, HIMN_CLIENT1, 160)
    if r['ok']:
        _log_himn_play(current_user.username, 'client1', os.path.basename(HIMN_CLIENT1))
        tg_notify(
            f'🎼 <b>Государственный гимн</b>\n'
            f'🏫 Кампус: <b>Client1</b>\n'
            f'👤 Запустил: <b>{current_user.username}</b>\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='himn'
        )
    return jsonify({'ok': r['ok'], 'error': r.get('error')})

@app.route('/api/himn/client2', methods=['POST'])
@login_required
def api_himn_client2():
    if not has_himn_perm():
        return jsonify({'ok': False, 'error': 'Нет прав на гимн'})
    client2 = _client2_conn()
    host = client2['host'] if client2 else CLIENT2_HOST
    user = client2.get('user', CLIENT2_USER) if client2 else CLIENT2_USER
    r = _play_himn(host, user, HIMN_CLIENT2, 150)
    if r['ok']:
        _log_himn_play(current_user.username, 'client2', os.path.basename(HIMN_CLIENT2))
        tg_notify(
            f'🎼 <b>Государственный гимн</b>\n'
            f'🏫 Кампус: <b>Client2</b>\n'
            f'👤 Запустил: <b>{current_user.username}</b>\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='himn'
        )
    return jsonify({'ok': r['ok'], 'error': r.get('error')})

@app.route('/api/himn/cgtk', methods=['POST'])
@login_required
def api_himn_cgtk():
    if not has_himn_perm():
        return jsonify({'ok': False, 'error': 'Нет прав на гимн'})
    cgtk = _client2_conn('cgtk')
    host = cgtk['host'] if cgtk else None
    user = cgtk.get('user', 'cgtk') if cgtk else 'cgtk'
    if not host:
        return jsonify({'ok': False, 'error': 'City Garden не подключен'})
    r = _play_himn(host, user, HIMN_CGTK, 150)
    if r['ok']:
        _log_himn_play(current_user.username, 'cgtk', os.path.basename(HIMN_CGTK))
        tg_notify(
            f'🎼 <b>Государственный гимн</b>\n'
            f'🏫 Кампус: <b>City Garden</b>\n'
            f'👤 Запустил: <b>{current_user.username}</b>\n'
            f'🕐 {_tg_fmt_time()}',
            event_type='himn'
        )
    return jsonify({'ok': r['ok'], 'error': r.get('error')})

@app.route('/api/volume', methods=['POST'])
@login_required
def api_volume():
    if not has_perm('volume'):
        return jsonify({'ok': False, 'error': 'Недостаточно прав'})
    data = request.get_json() or {}
    val  = max(0, min(160, int(data.get('value', 100))))
    return jsonify(mpv_set_all('volume', val))

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
    if campus in ('client1', 'both'):
        mpv_cmd(cmd)
    if campus in ('client2', 'both'):
        client2m = _client2_conn()
        if client2m:
            mpv_cmd_on(client2m['host'], client2m.get('user', CLIENT1_USER), cmd)
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
    if campus in ('client1', 'both'): mpv_cmd(cmd)
    if campus in ('client2', 'both'):
        client2m = _client2_conn()
        if client2m: mpv_cmd_on(client2m['host'], client2m.get('user', CLIENT1_USER), cmd)
    _eq_state['bands'] = [0.0] * 10
    return jsonify({'ok': True})

@app.route('/api/eq/state')
@login_required
def api_eq_state():
    return jsonify(_eq_state)

# ── Audio FFT polling (background thread → SSE) ──────────────────────────────
_audio_cache = {'client1': None, 'client2': None}
_audio_lock  = threading.Lock()
_audio_thread_started = False

def _audio_poll_loop():
    """Read /tmp/campus-audio-level.json via SSH exec every 100ms (faster than SFTP)."""
    conns = {}
    while True:
        targets = [
            ('client1', CLIENT1_HOST, CLIENT1_USER),
            ('client2',  CLIENT2_HOST,  CLIENT2_USER),
        ]
        for cid, host, user in targets:
            if not host:
                continue
            try:
                ssh = conns.get(cid)
                if not ssh or not ssh.get_transport() or not ssh.get_transport().is_active():
                    try:
                        if ssh:
                            ssh.close()
                    except Exception:
                        pass
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(host, username=user, key_filename=SSH_KEY,
                                timeout=5, banner_timeout=5)
                    conns[cid] = ssh
                _, stdout, _ = ssh.exec_command(
                    'cat /tmp/campus-audio-level.json', timeout=2)
                data = json.loads(stdout.read())
                with _audio_lock:
                    _audio_cache[cid] = data
            except Exception:
                with _audio_lock:
                    _audio_cache[cid] = None
                conns.pop(cid, None)
        time.sleep(0.1)

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

def _play_track_on(host, user, local_path, name, machine_id, username):
    """Background worker: SSH/SFTP to campus machine then start mpv playback."""
    s = None
    try:
        media_base = _MEDIA_PATHS.get(machine_id, '/mnt/music/Media')
        relative    = os.path.relpath(local_path, MUSIC_DIR)
        remote_path = os.path.join(media_base, relative)

        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(host, username=user, key_filename=SSH_KEY, timeout=8)

        # Try direct play from campus machine's local path first (instant)
        _, chk, _ = s.exec_command(f'test -f "{remote_path}" && echo y || echo n', timeout=5)
        if chk.read().decode().strip() == 'y':
            cmd_j = json.dumps({'command': ['loadfile', remote_path, 'replace']})
            escaped = cmd_j.replace('"', '\\"')
            _, out, _ = s.exec_command(
                f'echo "{escaped}" | socat - {MPV_SOCK} 2>/dev/null; '
                f'echo "{remote_path}" > /run/campus-player/lastfile 2>/dev/null || true',
                timeout=5
            )
            out.read()
        else:
            # File not on campus machine → SFTP-upload to inbox (takes 5-30 s)
            remote_in = PLAYER_INBOX + '/in.mp3'
            sftp = s.open_sftp()
            try:
                sftp.mkdir(PLAYER_INBOX)
            except IOError:
                pass
            sftp.put(local_path, remote_in)
            sftp.close()
            _, out, _ = s.exec_command(
                f'/usr/local/bin/campus-playerctl play {remote_in}', timeout=8
            )
            out.read()

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
    threading.Thread(
        target=_play_track_on,
        args=(host, user, local_path, name, mid, username),
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
    if campus in ('client1', 'both'):
        mpv_cmd(cmd)
    if campus in ('client2', 'both'):
        for m in MACHINES:
            if m['host'] != CLIENT1_HOST:
                mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cmd)
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
    music_root = _MEDIA_PATHS.get(machine, '/mnt/music/Media')
    find_cmd = (f"find {music_root} -type f \\("
                f" -name '*.mp3' -o -name '*.flac'"
                f" -o -name '*.ogg' -o -name '*.m4a' \\) 2>/dev/null | sort")

    if machine == 'client1':
        raw = ssh_run(find_cmd)
    else:
        vm = next((x for x in MACHINES if x['host'] != CLIENT1_HOST), None)
        if not vm:
            return jsonify({'ok': False, 'error': 'client2 не настроен'})
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
                mpv_cmd_on(m['host'], m.get('user', CLIENT1_USER), cycle_cmd)
        return jsonify(r)
    return jsonify(mpv_set_all('mute', bool(state)))

@app.route('/api/terminal', methods=['POST'])
@login_required
def api_terminal():
    if current_user.role not in ('admin', 'staff'):
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
    return render_template('profile.html', history=history)

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
    return render_template('settings.html', tg_settings=tg_settings, silence=silence)

@app.route('/security')
@admin_only
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

# Пути к Media на каждой машине
_MEDIA_PATHS = {
    'client1': '/mnt/music/Media',
    'client2':  '/home/client2/Media',
    'cgtk': '/home/cgtk/Media',
}

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
    media = _MEDIA_PATHS.get(machine, '/home/client1/Media')
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
@admin_only
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
@admin_only
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
@admin_only
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
@admin_only
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
@admin_only
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
@admin_only
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
    if current_user.role not in ('admin', 'staff', 'user'):
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
                           kamran_unlocked=_kamran_unlocked())

@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    if current_user.role not in ('admin', 'staff', 'user'):
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
    if current_user.role not in ('admin',):
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
    if current_user.role not in ('admin',):
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
    if current_user.role not in ('admin',):
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
    if current_user.role not in ('admin',):
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

# ══════════════════════════════════════════════════
@app.route('/machines')
@login_required
@admin_only
def machines_page():
    return render_template('machines.html', perms=user_perms())

# SYSTEM MONITOR
# ══════════════════════════════════════════════════
@app.route('/monitor')
@login_required
def monitor_page():
    if current_user.role not in ('admin', 'staff'):
        return redirect(url_for('dashboard'))
    return render_template('monitor.html', perms=user_perms(),
                           machines=MACHINES, centos_host=CENTOS_HOST,
                           centos_cockpit=f'http://{CENTOS_HOST}:1991')

@app.route('/api/sysinfo')
@login_required
def api_sysinfo():
    if current_user.role not in ('admin', 'staff'):
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
@admin_only
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
@admin_only
def admin_schedule():
    return render_template('schedule_editor.html',
                           schedule=SCHEDULE, perms=user_perms())

@app.route('/api/schedule', methods=['GET'])
@login_required
def api_schedule_get():
    return jsonify({'ok': True, 'schedule': SCHEDULE})

@app.route('/api/schedule/add', methods=['POST'])
@login_required
@admin_only
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
@admin_only
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
@admin_only
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
@admin_only
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
# client1's local MUSIC_DIR is the master library; client2/cgtk each keep their own
# local copy (they can't stream over the network) that needs periodic sync.
# Add a key here when a new spoke campus needs the same treatment.
SYNC_CAMPUSES = ['client2', 'cgtk']
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
    if current_user.role not in ('admin', 'staff'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    local = set(f for f in os.listdir(MUSIC_DIR)
                if os.path.splitext(f)[1].lower() in ALLOWED_AUDIO)
    campuses = {}
    for campus in SYNC_CAMPUSES:
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
    if current_user.role not in ('admin', 'staff'):
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data      = request.get_json() or {}
    campus    = (data.get('campus') or 'client2').strip()
    direction = data.get('direction', 'client1_to_remote')  # 'client1_to_remote' | 'remote_to_client1'
    files     = data.get('files', [])
    if campus not in SYNC_CAMPUSES:
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
    campus_label = {'client2': 'Client2', 'cgtk': 'City Garden'}.get(campus, campus)
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
@admin_only
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
@admin_only
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
    if current_user.role not in ('admin', 'staff'):
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
    client2 = _client2_conn()
    if client2:
        targets.append(('client2', client2['host'], client2.get('user', CLIENT1_USER), SSH_KEY))

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
    if current_user.role not in ('admin', 'staff'):
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
    if machine in ('all', 'client2'):
        client2 = _client2_conn()
        if client2:
            targets.append(('client2', client2['host'], client2.get('user', CLIENT1_USER), SSH_KEY))

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
        for key, fname in [('client1', 'client1-config.tar.gz'),
                            ('client2',  'client2-config.tar.gz'),
                            ('cgtk', 'cgtk-config.tar.gz'),
                            ('centos', 'centos.tar.gz')]:
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

@app.route('/backups')
@login_required
def backups_page():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    unlocked = session.get('backup_unlocked', False)
    base, entries, music, machines = _backup_scan()
    return render_template('backups.html',
                           backup_dir=base, entries=entries, music=music,
                           machines=machines, unlocked=unlocked,
                           has_vault=bool(BACKUP_VAULT_PASS),
                           admin_emails=BACKUP_ADMIN_EMAILS)

@app.route('/api/backup/unlock', methods=['POST'])
@login_required
def api_backup_unlock():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Нет прав'})
    data = request.get_json() or {}
    pwd  = data.get('password', '')
    if not BACKUP_VAULT_PASS:
        return jsonify({'ok': False, 'error': 'BACKUP_VAULT_PASS не задан'})
    if pwd == BACKUP_VAULT_PASS:
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
    if current_user.role != 'admin':
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
    if current_user.role != 'admin':
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
    if current_user.role not in ('admin', 'staff'):
        return '', 403
    return render_template('cheatsheet.html')

@app.route('/announce')
@login_required
def announce_page():
    if current_user.role not in ('admin', 'staff'):
        return '', 403
    return render_template('announce.html')

@app.route('/api/announce', methods=['POST'])
@login_required
def api_announce():
    if current_user.role not in ('admin', 'staff'):
        return jsonify({'ok': False, 'error': 'Нет прав'}), 403
    audio = request.files.get('audio')
    if not audio:
        return jsonify({'ok': False, 'error': 'Нет аудио'})
    campuses = request.form.get('campuses', 'all')
    fname = f"announce_{int(time.time()*1000)}_{current_user.username}.webm"
    fpath = os.path.join(ANNOUNCE_DIR, fname)
    audio.save(fpath)

    volume = max(50, min(160, int(request.form.get('volume', 120))))

    def _play_on(host, user, campus_id):
        s = None
        try:
            s = paramiko.SSHClient()
            s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            s.connect(host, username=user, key_filename=SSH_KEY, timeout=10)
            sftp = s.open_sftp()
            remote_path = '/tmp/campus_announce.webm'
            sftp.put(fpath, remote_path)
            sftp.close()
            _, out, err = s.exec_command(
                f'/usr/local/bin/campus-playerctl play {remote_path} {volume} 2>/dev/null')
            out.read(); err.read()
            log_action(current_user.username, 'announce', campus_id, fname)
            return True
        except Exception as e:
            return str(e)
        finally:
            if s:
                try: s.close()
                except Exception: pass

    results = {}
    if campuses in ('client1', 'all'):
        results['client1'] = _play_on(CLIENT1_HOST, CLIENT1_USER, 'client1')
    if campuses in ('client2', 'all'):
        client2 = _client2_conn('client2')
        if client2:
            results['client2'] = _play_on(client2['host'], client2.get('user', 'client2'), 'client2')
    # 'all' now means "all registered campuses" (client1 + client2 + cgtk), same
    # convention as the cron-pause 'both' handling above
    if campuses in ('cgtk', 'all'):
        cgtk = _client2_conn('cgtk')
        if cgtk:
            results['cgtk'] = _play_on(cgtk['host'], cgtk.get('user', 'cgtk'), 'cgtk')

    campus_label = {'client1': 'Client1', 'client2': 'Client2', 'cgtk': 'City Garden',
                     'all': 'Все кампусы'}.get(campuses, campuses)
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
@admin_only
def api_bug_reports_list():
    with get_db() as c:
        rows = c.execute(
            'SELECT * FROM bug_reports ORDER BY created_at DESC LIMIT 200'
        ).fetchall()
    return jsonify({'ok': True, 'reports': [dict(r) for r in rows]})

@app.route('/api/bug_reports/status', methods=['POST'])
@login_required
@admin_only
def api_bug_reports_status():
    data = request.get_json() or {}
    rid    = data.get('id')
    status = (data.get('status') or 'new').strip()
    if status not in ('new', 'in_progress', 'resolved', 'closed'):
        return jsonify({'ok': False, 'error': 'Bad status'})
    with get_db() as c:
        c.execute('UPDATE bug_reports SET status=? WHERE id=?', (status, rid))
    return jsonify({'ok': True})

if __name__ == '__main__':
    init_db()
    ssl_ctx = None
    if os.path.exists('/app/ssl.crt') and os.path.exists('/app/ssl.key'):
        ssl_ctx = ('/app/ssl.crt', '/app/ssl.key')
    app.run(host='0.0.0.0', port=8080, debug=False, ssl_context=ssl_ctx)
