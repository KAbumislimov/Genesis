#!/usr/bin/env python3
"""Восстановление данных системы из снимков в GitHub (campus-infra/state/) — обратная сторона export_state.py.

  import_state.py verify  [--state DIR]                     проверить, что снимки расшифровываются и целы (ничего не меняет)
  import_state.py restore [--state DIR] [--force]           положить БД из снимков на место (webui + helpdesk-ops + вложения)
  import_state.py json --db PATH [--state DIR]              накатить роли/настройки/машины из JSON в уже созданную БД
                                                            (запасной путь, если снимка БД нет или ключ утерян)

Ключ расшифровки — BACKUP_VAULT_PASS (из окружения или campus-infra/.env). Нужен только для verify/restore.
"""
import argparse, gzip, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
HELPDESK = os.path.abspath(os.path.join(ROOT, '..', 'helpdesk-ops'))


def vault_pass():
    v = os.environ.get('BACKUP_VAULT_PASS')
    if v:
        return v
    try:
        raw = open(os.path.join(ROOT, '.env'), encoding='utf-8', errors='ignore').read()
    except OSError:
        return ''
    m = re.search(r'^BACKUP_VAULT_PASS=(.+)$', raw, re.M)
    return m.group(1).strip().strip('"\'') if m else ''


def decrypt(enc, out, pw):
    r = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
                        '-in', enc, '-out', out, '-pass', 'env:CAMPUS_VAULT'],
                       env=dict(os.environ, CAMPUS_VAULT=pw), capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()[:120]


def unpack_db(enc, dest, pw):
    """Расшифровать + распаковать gzip → dest. Возвращает (ok, сообщение)."""
    with tempfile.TemporaryDirectory() as td:
        gz = os.path.join(td, 'x.gz')
        ok, err = decrypt(enc, gz, pw)
        if not ok:
            return False, 'не удалось расшифровать (неверный BACKUP_VAULT_PASS?) ' + err
        raw = os.path.join(td, 'x.db')
        try:
            with gzip.open(gz, 'rb') as fi, open(raw, 'wb') as fo:
                shutil.copyfileobj(fi, fo)
        except OSError as e:
            return False, 'повреждённый архив: ' + str(e)
        try:
            con = sqlite3.connect(raw)
            res = con.execute('PRAGMA integrity_check').fetchone()[0]
            tables = {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
                      for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            con.close()
        except sqlite3.Error as e:
            return False, 'не открывается как SQLite: ' + str(e)
        if res != 'ok':
            return False, 'integrity_check: ' + res
        if dest:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(raw, dest)
        return True, ', '.join(f'{k}={v}' for k, v in sorted(tables.items())[:8])


def snapshots(state):
    return [
        ('webui.db.enc', os.path.join(ROOT, 'data', 'webui', 'webui.db'), 'БД веб-панели (пользователи, права, настройки, машины)'),
        ('helpdesk_ops.db.enc', os.path.join(HELPDESK, 'data', 'helpdesk_ops.db'), 'БД Helpdesk Ops (тикеты, отчёты)'),
    ]


def cmd_verify(a):
    pw = vault_pass()
    bad = 0
    if not pw:
        print('✗ BACKUP_VAULT_PASS не найден (нужен .env из campus-secrets) — снимки проверить нельзя')
        return 1
    for name, _dest, title in snapshots(a.state):
        p = os.path.join(a.state, name)
        if not os.path.isfile(p):
            print(f'⚠ нет файла {name} — {title}')
            continue
        ok, msg = unpack_db(p, None, pw)
        print(('✓ ' if ok else '✗ ') + f'{name}: {msg}')
        bad += 0 if ok else 1
    up = os.path.join(a.state, 'helpdesk_ops_uploads.tar.gz.enc')
    if os.path.isfile(up):
        with tempfile.TemporaryDirectory() as td:
            ok, err = decrypt(up, os.path.join(td, 'u.tgz'), pw)
            if ok:
                r = subprocess.run(['tar', 'tzf', os.path.join(td, 'u.tgz')], capture_output=True, text=True)
                n = len(r.stdout.splitlines())
                print(('✓ ' if r.returncode == 0 else '✗ ') + f'helpdesk_ops_uploads: файлов в архиве {n}')
                bad += 0 if r.returncode == 0 else 1
            else:
                print('✗ helpdesk_ops_uploads: не расшифровывается ' + err)
                bad += 1
    for j in ('roles.json', 'settings.json', 'machines.json', 'users-summary.json', 'schedule.json'):
        ok = os.path.isfile(os.path.join(a.state, j))
        print(('✓ ' if ok else '⚠ ') + j)
    return 1 if bad else 0


def cmd_restore(a):
    pw = vault_pass()
    if not pw:
        print('✗ BACKUP_VAULT_PASS не найден — расшифровать снимки нельзя')
        return 1
    rc = 0
    for name, dest, title in snapshots(a.state):
        p = os.path.join(a.state, name)
        if not os.path.isfile(p):
            print(f'⚠ нет {name} — пропуск ({title})')
            continue
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            if not a.force:
                print(f'• {os.path.basename(dest)} уже существует — не трогаю (флаг --force заменит, старая копия сохранится)')
                continue
            bak = dest + '.before_restore_' + time.strftime('%Y%m%d_%H%M%S')
            shutil.copyfile(dest, bak)
            print(f'  старая {os.path.basename(dest)} сохранена как {os.path.basename(bak)}')
        ok, msg = unpack_db(p, dest, pw)
        print(('✓ восстановлено: ' if ok else '✗ ошибка: ') + f'{title} — {msg}')
        rc |= 0 if ok else 1
    up = os.path.join(a.state, 'helpdesk_ops_uploads.tar.gz.enc')
    target = os.path.join(HELPDESK, 'data')
    if os.path.isfile(up) and (not os.path.isdir(os.path.join(target, 'uploads')) or a.force):
        with tempfile.TemporaryDirectory() as td:
            ok, err = decrypt(up, os.path.join(td, 'u.tgz'), pw)
            if ok:
                os.makedirs(target, exist_ok=True)
                subprocess.run(['tar', 'xzf', os.path.join(td, 'u.tgz'), '-C', target])
                print('✓ вложения Helpdesk Ops восстановлены')
            else:
                print('✗ вложения: не расшифровываются ' + err)
                rc = 1
    sched = os.path.join(a.state, 'schedule.json')
    dst = os.path.join(ROOT, 'data', 'webui', 'schedule.json')
    if os.path.isfile(sched) and not os.path.isfile(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(sched, dst)
        print('✓ расписание восстановлено (schedule.json)')
    return rc


def cmd_json(a):
    """Роли/настройки/машины из JSON → в существующую БД (приложение уже создало таблицы)."""
    con = sqlite3.connect(a.db)
    st = a.state
    n = {'roles': 0, 'settings': 0, 'machines': 0}
    try:
        roles = json.load(open(os.path.join(st, 'roles.json'), encoding='utf-8'))
        perms = {r for lst in roles.values() for r in lst}
        allp = [r[0] for r in con.execute('SELECT DISTINCT perm FROM role_perms')] or sorted(perms)
        for role, have in roles.items():
            for perm in allp:
                con.execute('INSERT OR REPLACE INTO role_perms (role, perm, allowed) VALUES (?,?,?)', (role, perm, 1 if perm in have else 0))
                n['roles'] += 1
    except (OSError, ValueError, sqlite3.Error) as e:
        print('⚠ роли не восстановлены:', e)
    try:
        for k, v in json.load(open(os.path.join(st, 'settings.json'), encoding='utf-8')).items():
            con.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', (k, v))
            n['settings'] += 1
    except (OSError, ValueError, sqlite3.Error) as e:
        print('⚠ настройки не восстановлены:', e)
    try:
        for m in json.load(open(os.path.join(st, 'machines.json'), encoding='utf-8')):
            if con.execute('SELECT 1 FROM thin_clients WHERE host=? AND user=?', (m['host'], m['user'])).fetchone():
                continue
            con.execute('INSERT INTO thin_clients (host, name, mac, user, cockpit_url, is_audio_client, music_path) VALUES (?,?,?,?,?,?,?)',
                        (m['host'], m['name'], m.get('mac', ''), m['user'], m.get('cockpit_url', ''), m.get('is_audio_client', 1), m.get('music_path', '')))
            n['machines'] += 1
    except (OSError, ValueError, sqlite3.Error) as e:
        print('⚠ машины не восстановлены:', e)
    con.commit()
    con.close()
    print(f"✓ из JSON: права {n['roles']}, настроек {n['settings']}, новых машин {n['machines']}")
    print('  Пользователей из JSON восстановить нельзя (нет паролей) — используйте снимок БД. Создайте админа заново на странице входа/через панель.')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('verify', 'restore', 'json'):
        sp = sub.add_parser(name)
        sp.add_argument('--state', default=os.path.join(ROOT, 'state'))
        if name == 'restore':
            sp.add_argument('--force', action='store_true')
        if name == 'json':
            sp.add_argument('--db', required=True)
    a = ap.parse_args()
    return {'verify': cmd_verify, 'restore': cmd_restore, 'json': cmd_json}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
