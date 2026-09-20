#!/usr/bin/env python3
"""Сводка «что и как забэкаплено» → ~/campus-backups/status.json. Её читает страница «Бэкапы» веб-панели
(папка примонтирована в контейнер только для чтения, поэтому данные готовим здесь, на хосте).

Что собирается (только чтение, ничего не меняет):
  • Proxmox: доступен ли сейчас, итог каждого недельного запуска campus-backup.sh (по ~/log/campus-backup-*.log),
    по каждому шагу — когда он последний раз прошёл успешно;
  • GitHub: работает ли автосинхронизатор, последний коммит, есть ли непушнутые, когда сделаны снимки состояния;
  • локальные ежедневные копии БД (campus-backups/db/<дата>);
  • размеры музыки и Media; проверка «расшифровываются ли снимки» (кэш 6 часов).
Запуск: cron */5 и в конце campus-backup.sh.   Ручной:  python3 scripts/backup_status.py --print
"""
import glob, json, os, re, socket, subprocess, sys, time

HOME = os.path.expanduser('~')
INFRA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BK = os.environ.get('CAMPUS_BACKUP_DIR', os.path.join(HOME, 'campus-backups'))
LOGDIR = os.path.join(HOME, 'log')
CACHE = os.path.join(HOME, '.cache', 'backup-status-cache.json')
PROXMOX = ('10.20.1.106', 22)
MUSIC = os.environ.get('MUSIC_ROOT_PATH') or os.path.join(HOME, 'Kamran Music')
MEDIA = os.path.join(HOME, 'Media')
CACHE_TTL = 6 * 3600


def run(cmd, timeout=20, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, '', str(e)


def tcp_ok(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def load_cache():
    try:
        return json.load(open(CACHE))
    except (OSError, ValueError):
        return {}


def cached(cache, key, fn):
    """Дорогие проверки (du на 33 ГБ, расшифровка снимков) — не чаще раза в 6 часов."""
    e = cache.get(key)
    if e and time.time() - e.get('ts', 0) < CACHE_TTL:
        return e['val']
    val = fn()
    cache[key] = {'ts': time.time(), 'val': val}
    return val


# ── Proxmox: разбор логов campus-backup.sh ──────────────────────────────────────────────
ERR_RE = re.compile(r'(No route to host|Connection timed out|Connection refused|Permission denied|Host key verification failed|'
                    r'No space left|Network is unreachable)', re.I)


def parse_log(path):
    lines = []
    for ln in open(path, encoding='utf-8', errors='replace').read().splitlines():
        if not lines or lines[-1] != ln:            # cron + tee дублируют каждую строку
            lines.append(ln)
    steps, err, done, sizes, free = [], '', None, {}, None
    for ln in lines:
        m = re.search(r'\]\s+(OK|FAIL)\s+(.+?)\s*$', ln)
        if m:
            steps.append({'name': m.group(2), 'ok': m.group(1) == 'OK'})
        if not err:
            e = ERR_RE.search(ln)
            if e:
                err = e.group(1)
        if 'BACKUP ABORTED' in ln:
            done = 'unreachable'
            err = err or 'Proxmox недоступен'
        if 'BACKUP DONE' in ln:
            done = 'ok' if 'OK' in ln.split('BACKUP DONE', 1)[1][:12] and 'ERRORS' not in ln else 'errors'
        m = re.search(r'Свободно на Proxmox: (\d+)', ln)
        if m:
            free = int(m.group(1))
        m = re.match(r'\s*([\d.,]+[KMGT]?)\s+/mnt/campus-backup/(\w+)/', ln)
        if m:
            sizes[m.group(2)] = m.group(1)
    date = re.search(r'campus-backup-(\d{4}-\d{2}-\d{2})', path).group(1)
    if done:
        result = done
    elif steps:
        result = 'aborted'
    else:
        result = 'unreachable' if err else 'aborted'
    return {'date': date, 'file': os.path.basename(path), 'steps': steps, 'result': result,
            'error': err, 'sizes': sizes, 'free': free, 'mtime': os.path.getmtime(path)}


def proxmox_info():
    runs = []
    for p in sorted(glob.glob(os.path.join(LOGDIR, 'campus-backup-2*.log')))[-12:]:
        try:
            runs.append(parse_log(p))
        except OSError:
            pass
    last_ok, seen = {}, set()                         # шаг → дата последнего успеха; все шаги, что вообще запускались
    last_full_ok = ''
    sizes, sizes_date, free = {}, '', None
    for r in runs:
        for s in r['steps']:
            seen.add(s['name'])
            if s['ok']:
                last_ok[s['name']] = r['date']
        if r['result'] == 'ok':
            last_full_ok = r['date']
        if r['sizes']:
            sizes, sizes_date = r['sizes'], r['date']
        if r.get('free'):
            free = r['free']
    last = runs[-1] if runs else None
    return {'host': PROXMOX[0], 'reachable': tcp_ok(*PROXMOX), 'last_run': last, 'last_full_ok': last_full_ok,
            'step_last_ok': last_ok, 'step_seen': sorted(seen), 'sizes': sizes, 'sizes_date': sizes_date, 'free_bytes': free, 'history': [{'date': r['date'], 'result': r['result']} for r in runs][-8:]}


# ── GitHub ──────────────────────────────────────────────────────────────────────────────
def github_info():
    top = run(['git', '-C', INFRA, 'rev-parse', '--show-toplevel'])[1].strip()
    info = {'live_sync': run(['pgrep', '-f', 'github-live-sync.sh'])[0] == 0, 'repo': 'KAbumislimov/campus-infra'}
    if not top:
        return info
    rc, out, _ = run(['git', '-C', top, 'log', '-1', '--format=%ct|%s'])
    if rc == 0 and '|' in out:
        info['last_commit_ts'], info['last_commit_msg'] = int(out.split('|')[0]), out.split('|', 1)[1].strip()
    rc, out, _ = run(['git', '-C', top, 'log', '-1', '--format=%ct', 'origin/main'])
    if rc == 0 and out.strip().isdigit():
        info['last_push_ts'] = int(out.strip())
    rc, out, _ = run(['git', '-C', top, 'rev-list', '--count', 'origin/main..HEAD'])
    info['unpushed'] = int(out.strip()) if rc == 0 and out.strip().isdigit() else None
    rc, out, _ = run(['git', '-C', top, 'status', '--porcelain', '--', 'projects/campus-infra', 'projects/helpdesk-ops', 'projects/ops-journal'])
    info['pending_files'] = len(out.splitlines()) if rc == 0 else None
    return info


def secrets_repo_info():
    """Приватный репозиторий campus-secrets (пароли, токены, ключи): когда последний коммит, есть ли несохранённое."""
    d = os.path.join(HOME, 'projects', 'campus-secrets')
    if not os.path.isdir(os.path.join(d, '.git')):
        return {'exists': False}
    info = {'exists': True}
    rc, out, _ = run(['git', '-C', d, 'log', '-1', '--format=%ct'])
    info['last_commit_ts'] = int(out.strip()) if rc == 0 and out.strip().isdigit() else None
    rc, out, _ = run(['git', '-C', d, 'status', '--porcelain'])
    info['dirty'] = len(out.splitlines()) if rc == 0 else None
    rc, out, _ = run(['git', '-C', d, 'rev-list', '--count', '@{u}..HEAD'])
    info['unpushed'] = int(out.strip()) if rc == 0 and out.strip().isdigit() else None
    return info


def snapshots_info():
    res = {}
    for key, fn in (('webui', 'webui.db.meta.json'), ('helpdesk', 'helpdesk_ops.db.meta.json'), ('helpdesk_uploads', 'helpdesk_ops_uploads.meta.json')):
        try:
            res[key] = json.load(open(os.path.join(INFRA, 'state', fn))).get('ts')
        except (OSError, ValueError):
            res[key] = None
    for key, fn in (('roles', 'roles.json'), ('crontab', 'crontab.txt'), ('machines', 'machines.json'), ('schedule', 'schedule.json')):
        try:
            res[key] = os.path.getmtime(os.path.join(INFRA, 'state', fn))
        except OSError:
            res[key] = None
    return res


def verify_info():
    """Расшифровываются ли снимки из state/ (ровно то, что нужно при восстановлении)."""
    rc, out, err = run([sys.executable, os.path.join(INFRA, 'scripts', 'import_state.py'), 'verify'], timeout=90)
    items = [{'ok': ln[0] == '✓', 'text': ln[2:].strip()} for ln in out.splitlines() if ln[:1] in '✓✗']
    env_ok = False
    try:
        env_ok = bool(re.search(r'^BACKUP_VAULT_PASS=.{4,}$', open(os.path.join(INFRA, '.env'), errors='ignore').read(), re.M))
    except OSError:
        pass
    return {'ok': rc == 0 and env_ok, 'key_present': env_ok, 'items': items[:8], 'checked': time.time()}


# ── Локальные копии БД, музыка ──────────────────────────────────────────────────────────
def local_db():
    days = []
    for d in sorted(glob.glob(os.path.join(BK, 'db', '2*')), reverse=True)[:10]:
        files = [{'name': os.path.basename(f), 'size': os.path.getsize(f)} for f in sorted(glob.glob(os.path.join(d, '*'))) if os.path.isfile(f)]
        days.append({'date': os.path.basename(d), 'files': files, 'total': sum(f['size'] for f in files)})
    return {'days': days, 'count': len(glob.glob(os.path.join(BK, 'db', '2*'))), 'dir': BK + '/db'}


def dir_size(path):
    rc, out, _ = run(['du', '-sb', path], timeout=300)
    try:
        return int(out.split()[0]) if rc == 0 else None
    except (ValueError, IndexError):
        return None


def cron_schedule():
    """Расписание заданий бэкапа из crontab → {ключ: {'m','h','dow'}} (dow: 0=воскресенье, '*'=каждый день)."""
    out = run(['crontab', '-l'])[1]
    jobs = {}
    for ln in out.splitlines():
        if ln.strip().startswith('#'):
            continue
        for key, needle in (('proxmox', 'campus-backup.sh'), ('db', 'backup-data.sh'), ('github', 'backup-to-github.sh')):
            if needle in ln:
                p = ln.split()
                if len(p) > 5:
                    jobs[key] = {'m': p[0], 'h': p[1], 'dow': p[4]}
    return jobs


def disabled_machines():
    """Физически отключённые машины (config/backup-disabled.txt): их не бэкапим и не считаем проблемой."""
    try:
        lines = open(os.path.join(INFRA, 'config', 'backup-disabled.txt'), encoding='utf-8').read().splitlines()
    except OSError:
        return []
    return [re.sub(r'#.*', '', ln).strip() for ln in lines if re.sub(r'#.*', '', ln).strip()]


def main():
    cache = load_cache()
    st = {
        'generated_at': time.time(),
        'schedule': cron_schedule(),
        'disabled': disabled_machines(),
        'proxmox': proxmox_info(),
        'github': github_info(),
        'snapshots': snapshots_info(),
        'secrets_repo': secrets_repo_info(),
        'local_db': local_db(),
        'verify': cached(cache, 'verify', verify_info),
        'music': {'path': MUSIC, 'exists': os.path.isdir(MUSIC), 'size': cached(cache, 'music_size', lambda: dir_size(MUSIC)) if os.path.isdir(MUSIC) else None},
        'media': {'path': MEDIA, 'exists': os.path.isdir(MEDIA), 'size': cached(cache, 'media_size', lambda: dir_size(MEDIA)) if os.path.isdir(MEDIA) else None},
    }
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, 'w'))
    os.makedirs(BK, exist_ok=True)
    tmp = os.path.join(BK, '.status.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(BK, 'status.json'))
    if '--print' in sys.argv:
        print(json.dumps(st, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
