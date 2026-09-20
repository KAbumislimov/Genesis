#!/usr/bin/env python3
"""Выгрузка «живого состояния» системы в репозиторий (campus-infra/state/) — чтобы всё, что настроено
в веб-панели, а не только код, восстанавливалось из GitHub на новом железе.

Что выгружается (каждый прогон; файлы переписываются ТОЛЬКО если содержимое изменилось):
  state/roles.json          права ролей (галочки со страницы «Роли и права»)
  state/settings.json       настройки панели (без PIN-хешей и прочего секретного)
  state/machines.json       список кампусов/устройств (страница «Машины»)
  state/users-summary.json  логины и роли пользователей (без паролей и личных данных)
  state/schedule.json       расписание автовоспроизведения
  state/crontab.txt         crontab сервера
  state/systemd/*           включённые unit-файлы campus/tg-*, ENABLED.txt
  state/etc/chrony.conf     NTP-конфиг сервера
  state/webui.db.enc        ПОЛНЫЙ снимок БД: сжат gzip и зашифрован (AES-256, ключ BACKUP_VAULT_PASS из .env,
                            который лежит в приватном campus-secrets). Обновляется, когда изменились пользователи/
                            права/настройки/машины (не чаще раза в 2 часа) и не реже раза в сутки.
Изменения состояния (кто кому что выдал, какая машина добавлена…) дописываются в docs/journal/ГГГГ-ММ-ДД.md.
Скрипт ничего не пишет в БД и ничего не удаляет; запускается из backup-to-github.sh перед каждым коммитом.
"""
import gzip, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))          # .../campus-infra
DB = os.environ.get('CAMPUS_WEBUI_DB', os.path.join(ROOT, 'data', 'webui', 'webui.db'))
STATE = os.path.join(ROOT, 'state')
SECRET_KEY_RE = re.compile(r'pass|token|secret|hash|pin', re.I)
SNAP_MIN_INTERVAL = 2 * 3600
SNAP_MAX_AGE = 24 * 3600

sys.path.insert(0, os.path.dirname(__file__))
from update_journal import journal_add  # noqa: E402


def read(path):
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def write_if_changed(rel, data, mode='t'):
    """Пишет файл только если содержимое изменилось. Возвращает (изменён?, старое содержимое)."""
    path = os.path.join(STATE, rel)
    raw = data.encode('utf-8') if isinstance(data, str) else data
    old = read(path)
    if old == raw:
        return False, old
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(raw)
    os.replace(tmp, path)
    return True, old


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def ro_connect():
    return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=10)


def role_label(role):
    return {'guest': 'Гость', 'user': 'Пользователь', 'staff': 'Персонал', 'helpdesk': 'HelpDesk',
            'eventmanager': 'Event Manager', 'admin': 'Админ', 'viewer': 'Viewer'}.get(role, role)


def perm_labels():
    """Русские названия привилегий — из каталога в app.py (без импорта самого приложения)."""
    src = read(os.path.join(ROOT, 'webui', 'app.py')) or b''
    out = {}
    for m in re.finditer(r"\(\s*'([a-z_]+)',\s*'([^']+)',\s*'[^']*'\s*\)", src.decode('utf-8', 'ignore')):
        out[m.group(1)] = m.group(2)
    return out


def main():
    if not os.path.isfile(DB):
        print('export_state: БД не найдена, пропускаю:', DB)
        return 0
    os.makedirs(STATE, exist_ok=True)
    events = []
    con = ro_connect()
    con.row_factory = sqlite3.Row

    # ── роли ────────────────────────────────────────────────────────────────
    roles = {}
    try:
        for r in con.execute('SELECT role, perm, allowed FROM role_perms ORDER BY role, perm'):
            roles.setdefault(r['role'], [])
            if r['allowed']:
                roles[r['role']].append(r['perm'])
    except sqlite3.Error:
        roles = {}
    if roles:
        changed, old = write_if_changed('roles.json', dumps(roles))
        if changed and old:
            try:
                prev = json.loads(old)
            except ValueError:
                prev = {}
            lab = perm_labels()
            for role in sorted(roles):
                add = sorted(set(roles[role]) - set(prev.get(role, [])))
                rem = sorted(set(prev.get(role, [])) - set(roles[role]))
                if add:
                    events.append(f"Права роли «{role_label(role)}»: выдано — " + ', '.join(lab.get(p, p) for p in add))
                if rem:
                    events.append(f"Права роли «{role_label(role)}»: снято — " + ', '.join(lab.get(p, p) for p in rem))

    # ── настройки ───────────────────────────────────────────────────────────
    settings = {r['key']: r['value'] for r in con.execute('SELECT key, value FROM settings ORDER BY key')
                if not SECRET_KEY_RE.search(r['key'])}
    changed, old = write_if_changed('settings.json', dumps(settings))
    if changed and old:
        try:
            prev = json.loads(old)
        except ValueError:
            prev = {}
        for k in sorted(set(settings) | set(prev)):
            if settings.get(k) != prev.get(k):
                events.append(f"Настройка «{k}»: {prev.get(k, '—')} → {settings.get(k, '—')}")

    # ── машины ──────────────────────────────────────────────────────────────
    machines = [dict(r) for r in con.execute(
        'SELECT id, name, host, user, mac, cockpit_url, is_audio_client, music_path FROM thin_clients ORDER BY id')]
    changed, old = write_if_changed('machines.json', dumps(machines))
    if changed and old:
        try:
            prev = {m['id']: m for m in json.loads(old)}
        except ValueError:
            prev = {}
        cur = {m['id']: m for m in machines}
        for i in sorted(set(cur) - set(prev)):
            events.append(f"Добавлена машина: {cur[i]['name']} ({cur[i]['host']})")
        for i in sorted(set(prev) - set(cur)):
            events.append(f"Удалена машина: {prev[i]['name']} ({prev[i]['host']})")
        for i in sorted(set(cur) & set(prev)):
            if cur[i] != prev[i]:
                events.append(f"Изменена машина: {cur[i]['name']}")

    # ── пользователи (только логин, роль, блокировка) ───────────────────────
    users = [{'username': r['username'], 'role': r['role'], 'blocked': bool(r['is_blocked'])}
             for r in con.execute('SELECT username, role, is_blocked FROM users ORDER BY username')]
    changed, old = write_if_changed('users-summary.json', dumps(users))
    if changed and old:
        try:
            prev = {u['username']: u for u in json.loads(old)}
        except ValueError:
            prev = {}
        cur = {u['username']: u for u in users}
        for n in sorted(set(cur) - set(prev)):
            events.append(f"Создан пользователь {n} (роль {role_label(cur[n]['role'])})")
        for n in sorted(set(prev) - set(cur)):
            events.append(f"Удалён пользователь {n}")
        for n in sorted(set(cur) & set(prev)):
            if cur[n]['role'] != prev[n]['role']:
                events.append(f"Пользователь {n}: роль {role_label(prev[n]['role'])} → {role_label(cur[n]['role'])}")
            if cur[n]['blocked'] != prev[n]['blocked']:
                events.append(f"Пользователь {n}: {'заблокирован' if cur[n]['blocked'] else 'разблокирован'}")

    # ── расписание, crontab, systemd, chrony ────────────────────────────────
    sched = read(os.path.join(ROOT, 'data', 'webui', 'schedule.json'))
    if sched:
        try:
            changed, old = write_if_changed('schedule.json', dumps(json.loads(sched)))
            if changed and old:
                events.append('Изменено расписание автовоспроизведения')
        except ValueError:
            pass
    try:
        cron = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=10).stdout
        if cron.strip():
            changed, old = write_if_changed('crontab.txt', cron)
            if changed and old:
                events.append('Изменён crontab сервера')
    except Exception:
        pass
    enabled = []
    try:
        out = subprocess.run(['systemctl', 'list-unit-files', '--no-pager', '--state=enabled', '--type=service'],
                             capture_output=True, text=True, timeout=15).stdout
        enabled = sorted(m.group(1) for m in re.finditer(r'^((?:tg-|campus)[\w@.-]+\.service)\s', out, re.M))
    except Exception:
        pass
    if enabled:
        write_if_changed('systemd/ENABLED.txt', '\n'.join(enabled) + '\n')
        for unit in enabled:
            src = read('/etc/systemd/system/' + unit)
            if src is not None:
                write_if_changed('systemd/' + unit, src)
    chrony = read('/etc/chrony.conf')
    if chrony:
        write_if_changed('etc/chrony.conf', chrony)

    # ── зашифрованный полный снимок БД ──────────────────────────────────────
    snap_msg = snapshot(con)
    con.close()

    for e in events:
        journal_add('state', e)
    print('export_state: событий состояния —', len(events), '|', snap_msg)
    return 0


def core_hash(con):
    """Хеш «главных» таблиц (без журналов, чата, сессий) — по нему решаем, пора ли обновлять снимок."""
    h = hashlib.sha256()
    for t, order in (('users', 'id'), ('role_perms', 'role, perm'), ('settings', 'key'), ('thin_clients', 'id'),
                     ('announcements', 'id'), ('favorites', 'rowid')):
        try:
            for row in con.execute(f'SELECT * FROM {t} ORDER BY {order}'):
                h.update(repr(tuple(row)).encode('utf-8'))
        except sqlite3.Error:
            pass
    return h.hexdigest()


def vault_pass():
    v = os.environ.get('BACKUP_VAULT_PASS')
    if v:
        return v
    raw = (read(os.path.join(ROOT, '.env')) or b'').decode('utf-8', 'ignore')
    m = re.search(r'^BACKUP_VAULT_PASS=(.+)$', raw, re.M)
    return m.group(1).strip().strip('"\'') if m else ''


def snapshot(con):
    enc = os.path.join(STATE, 'webui.db.enc')
    meta_p = os.path.join(STATE, 'webui.db.meta.json')
    pw = vault_pass()
    if not pw:
        return 'снимок БД пропущен: нет BACKUP_VAULT_PASS в .env'
    try:
        meta = json.loads((read(meta_p) or b'{}').decode())
    except ValueError:
        meta = {}
    now = time.time()
    h = core_hash(con)
    age = now - meta.get('ts', 0)
    if os.path.isfile(enc) and meta.get('core') == h and age < SNAP_MAX_AGE:
        return 'снимок БД актуален'
    if os.path.isfile(enc) and meta.get('core') != h and age < SNAP_MIN_INTERVAL:
        return 'снимок БД: изменения есть, подождём (не чаще раза в 2 часа)'
    if os.path.isfile(enc) and meta.get('core') == h and age >= SNAP_MAX_AGE:
        pass  # суточное обновление (журналы/чат за день)
    with tempfile.TemporaryDirectory() as td:
        raw_p = os.path.join(td, 'webui.db')
        dst = sqlite3.connect(raw_p)
        con.backup(dst)                      # согласованная копия «на лету»
        dst.close()
        gz_p = raw_p + '.gz'
        with open(raw_p, 'rb') as fi, gzip.open(gz_p, 'wb', compresslevel=9) as fo:
            shutil.copyfileobj(fi, fo)
        env = dict(os.environ, CAMPUS_VAULT=pw)
        r = subprocess.run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', '200000', '-salt',
                            '-in', gz_p, '-out', os.path.join(td, 'x.enc'), '-pass', 'env:CAMPUS_VAULT'],
                           env=env, capture_output=True, text=True)
        if r.returncode != 0:
            return 'снимок БД: ошибка шифрования ' + r.stderr.strip()[:100]
        with open(os.path.join(td, 'x.enc'), 'rb') as f:
            data = f.read()
    write_if_changed('webui.db.enc', data)
    write_if_changed('webui.db.meta.json', dumps({
        'core': h, 'ts': now, 'when': datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M'),
        'how': 'gzip + openssl enc -aes-256-cbc -pbkdf2 -iter 200000; ключ — BACKUP_VAULT_PASS из campus-secrets/server/.env'}))
    journal_add('state', 'Обновлён зашифрованный снимок БД в GitHub (state/webui.db.enc)')
    return 'снимок БД обновлён'


if __name__ == '__main__':
    sys.exit(main())
