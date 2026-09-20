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
    snap_msg += ' | ' + helpdesk_snapshots()

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


def encrypt_file(src, dst, pw):
    r = subprocess.run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', '200000', '-salt',
                        '-in', src, '-out', dst, '-pass', 'env:CAMPUS_VAULT'],
                       env=dict(os.environ, CAMPUS_VAULT=pw), capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()[:100]


def should_refresh(meta, h, min_interval, max_age, have_file):
    """Обновлять снимок: если нет файла; если данные изменились и прошёл min_interval; либо прошло max_age."""
    if not have_file:
        return True
    age = time.time() - meta.get('ts', 0)
    if meta.get('core') != h:
        return age >= min_interval
    return age >= max_age


def load_meta(rel):
    try:
        return json.loads((read(os.path.join(STATE, rel)) or b'{}').decode())
    except ValueError:
        return {}


def save_meta(rel, h, note):
    now = time.time()
    write_if_changed(rel, dumps({'core': h, 'ts': now, 'when': datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M'), 'how': note}))


HOW = 'gzip + openssl enc -aes-256-cbc -pbkdf2 -iter 200000; ключ — BACKUP_VAULT_PASS из campus-secrets/server/.env'


def snapshot(con):
    """Полный снимок БД веб-панели (пользователи, права, настройки, машины, журналы)."""
    enc = os.path.join(STATE, 'webui.db.enc')
    pw = vault_pass()
    if not pw:
        return 'снимок БД пропущен: нет BACKUP_VAULT_PASS в .env'
    meta, h = load_meta('webui.db.meta.json'), core_hash(con)
    if not should_refresh(meta, h, SNAP_MIN_INTERVAL, SNAP_MAX_AGE, os.path.isfile(enc)):
        return 'снимок БД актуален'
    with tempfile.TemporaryDirectory() as td:
        raw_p = os.path.join(td, 'webui.db')
        dst = sqlite3.connect(raw_p)
        con.backup(dst)                      # согласованная копия «на лету»
        dst.close()
        gz_p = raw_p + '.gz'
        with open(raw_p, 'rb') as fi, gzip.open(gz_p, 'wb', compresslevel=9) as fo:
            shutil.copyfileobj(fi, fo)
        ok, err = encrypt_file(gz_p, os.path.join(td, 'x.enc'), pw)
        if not ok:
            return 'снимок БД: ошибка шифрования ' + err
        with open(os.path.join(td, 'x.enc'), 'rb') as f:
            data = f.read()
    write_if_changed('webui.db.enc', data)
    save_meta('webui.db.meta.json', h, HOW)
    journal_add('state', 'Обновлён зашифрованный снимок БД веб-панели в GitHub (state/webui.db.enc)')
    return 'снимок БД обновлён'


def helpdesk_snapshots():
    """Helpdesk Ops (тикеты, отчёты) и его вложения — раз в сутки, тоже зашифрованно."""
    base = os.path.abspath(os.path.join(ROOT, '..', 'helpdesk-ops', 'data'))
    db_p, up_p = os.path.join(base, 'helpdesk_ops.db'), os.path.join(base, 'uploads')
    pw = vault_pass()
    msgs = []
    if not pw:
        return 'Helpdesk Ops: пропущено (нет BACKUP_VAULT_PASS)'
    DAY = 24 * 3600
    if os.path.isfile(db_p):
        enc = os.path.join(STATE, 'helpdesk_ops.db.enc')
        try:
            con = sqlite3.connect(f'file:{db_p}?mode=ro', uri=True, timeout=10)
            h = hashlib.sha256('\n'.join(con.iterdump()).encode('utf-8', 'ignore')).hexdigest()
            meta = load_meta('helpdesk_ops.db.meta.json')
            if should_refresh(meta, h, DAY, DAY, os.path.isfile(enc)):
                with tempfile.TemporaryDirectory() as td:
                    raw_p = os.path.join(td, 'h.db')
                    dst = sqlite3.connect(raw_p)
                    con.backup(dst)
                    dst.close()
                    with open(raw_p, 'rb') as fi, gzip.open(raw_p + '.gz', 'wb', compresslevel=9) as fo:
                        shutil.copyfileobj(fi, fo)
                    ok, err = encrypt_file(raw_p + '.gz', os.path.join(td, 'x.enc'), pw)
                    if ok:
                        with open(os.path.join(td, 'x.enc'), 'rb') as f:
                            write_if_changed('helpdesk_ops.db.enc', f.read())
                        save_meta('helpdesk_ops.db.meta.json', h, HOW)
                        journal_add('state', 'Обновлён зашифрованный снимок БД Helpdesk Ops (state/helpdesk_ops.db.enc)')
                        msgs.append('helpdesk БД обновлена')
                    else:
                        msgs.append('helpdesk БД: ошибка шифрования ' + err)
            con.close()
        except sqlite3.Error as e:
            msgs.append('helpdesk БД: ' + str(e)[:60])
    if os.path.isdir(up_p):
        files = []
        for dp, _, fns in os.walk(up_p):
            for fn in fns:
                fp = os.path.join(dp, fn)
                try:
                    files.append((os.path.relpath(fp, up_p), os.path.getsize(fp)))
                except OSError:
                    pass
        h = hashlib.sha256(repr(sorted(files)).encode()).hexdigest()
        total = sum(x[1] for x in files)
        enc = os.path.join(STATE, 'helpdesk_ops_uploads.tar.gz.enc')
        meta = load_meta('helpdesk_ops_uploads.meta.json')
        if files and total <= 40 * 1024 * 1024 and should_refresh(meta, h, DAY, 7 * DAY, os.path.isfile(enc)):
            with tempfile.TemporaryDirectory() as td:
                tar_p = os.path.join(td, 'u.tar.gz')
                subprocess.run(['tar', 'czf', tar_p, '-C', base, 'uploads'], capture_output=True)
                ok, err = encrypt_file(tar_p, os.path.join(td, 'x.enc'), pw)
                if ok:
                    with open(os.path.join(td, 'x.enc'), 'rb') as f:
                        write_if_changed('helpdesk_ops_uploads.tar.gz.enc', f.read())
                    save_meta('helpdesk_ops_uploads.meta.json', h, 'tar.gz + openssl enc -aes-256-cbc -pbkdf2')
                    journal_add('state', 'Обновлён зашифрованный архив вложений Helpdesk Ops')
                    msgs.append('вложения обновлены')
        elif files and total > 40 * 1024 * 1024:
            msgs.append(f'вложения {total // 1048576} МБ — слишком велики для GitHub, только локальный бэкап')
    return '; '.join(msgs) or 'Helpdesk Ops: актуально'


if __name__ == '__main__':
    sys.exit(main())
