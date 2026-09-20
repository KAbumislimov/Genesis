"""Матрица «роль × маршрут» на КОПИИ БД (реальная БД не трогается). Запуск: perm_matrix.py <out.json>"""
import os, sys, json, shutil, sqlite3
shutil.copy('/data/webui.db', '/tmp/perm_test.db')
os.environ['DB_PATH'] = '/tmp/perm_test.db'
sys.path.insert(0, '/app')
import app as A
from werkzeug.security import generate_password_hash

db = sqlite3.connect('/tmp/perm_test.db')
ROLES = ['guest', 'user', 'viewer', 'staff', 'helpdesk', 'eventmanager', 'admin']
ids = {}
for r in ROLES + ['user+himn']:
    role = r.split('+')[0]
    name = 'zz_' + r.replace('+', '_')
    db.execute("INSERT OR REPLACE INTO users (username,password_hash,role,can_himn) VALUES (?,?,?,?)",
               (name, generate_password_hash('x'), role, 1 if '+himn' in r else 0))
    ids[r] = db.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]
db.commit()

GET = ['/', '/v4', '/tracks', '/admin', '/admin/activity', '/admin/cron', '/admin/schedule', '/machines', '/monitor', '/cheatsheet',
       '/announce', '/announcements', '/upload', '/backups', '/security', '/settings', '/profile', '/qr', '/campus/client1',
       '/api/cron/pause', '/api/special-vol', '/api/alarm/sounds', '/api/perem/schedule', '/api/schedule', '/api/activity-log',
       '/api/machines/list', '/api/admin/cron-status', '/api/admin/cron-log', '/api/admin/cron-files', '/api/sysinfo',
       '/api/tracks/sync/status', '/api/timesync/status', '/api/bug_reports/list', '/api/settings/silence', '/api/settings/tg',
       '/api/wallpapers/list', '/api/emojis/list', '/api/tracks/download', '/api/users/list', '/api/tracks']
# только POST с заведомо неверными аргументами (неизвестный кампус, пустое тело) — реальных действий не вызывают
POST = [('/api/himn/zzz', {}), ('/api/minuta/zzz', {}), ('/api/alarm/zzz', {}), ('/api/zefer/zzz', {}), ('/api/nmd/zzz', {}),
        ('/api/perem/zzz/1', {}), ('/api/perem/schedule/zzz/1', {}), ('/api/stop/zzz', {}), ('/api/volume/zzz', {'value': 50}),
        ('/api/schedule/toggle-group', {'group': 'zzz'}), ('/api/tracks/delete', {}), ('/api/tracks/rename', {}),
        ('/api/tracks/create-folder', {}), ('/api/tracks/move', {}), ('/api/tracks/bulk-move', {}), ('/api/tracks/bulk-delete', {}),
        ('/api/tracks/delete-folder', {}), ('/api/tracks/rename-folder', {}), ('/api/tracks/copy-folder', {}),
        ('/api/tracks/move-folder-contents', {}), ('/api/announcements/create', {}), ('/api/announcements/delete', {}),
        ('/api/announcements/pin', {}), ('/api/machines/add', {}), ('/api/machines/delete/999999', {}), ('/api/machines/edit/999999', {}),
        ('/api/schedule/delete/999999', {}), ('/api/terminal', {}), ('/api/backup/unlock', {}), ('/api/wallpapers/delete', {}),
        ('/api/emojis/delete', {}), ('/api/emojis/upload', {}), ('/api/wallpapers/upload', {}), ('/api/upload', {}), ('/api/announce', {}),
        ('/api/bug_reports/status', {}), ('/api/kamran/set-pin', {})]


def shape(r):
    try:
        j = r.get_json(silent=True)
    except Exception:
        j = None
    if isinstance(j, dict):
        return f"{r.status_code}|json|{j.get('error') or ('ok' if j.get('ok') else '')}"[:90]
    if r.status_code in (301, 302):
        return f"{r.status_code}|->{r.headers.get('Location', '')[:30]}"
    return f"{r.status_code}"


res = {}
for r_name, uid in ids.items():
    cl = A.app.test_client()
    with cl.session_transaction() as ss:
        ss['_user_id'] = str(uid)
        ss['_fresh'] = True
    row = {}
    for p in GET:
        try:
            row['GET ' + p] = shape(cl.get(p))
        except Exception as e:
            row['GET ' + p] = 'EXC ' + type(e).__name__
    for p, body in POST:
        try:
            row['POST ' + p] = shape(cl.post(p, json=body))
        except Exception as e:
            row['POST ' + p] = 'EXC ' + type(e).__name__
    res[r_name] = row
json.dump(res, open(sys.argv[1], 'w'), ensure_ascii=False, indent=0)
print('ok', {k: len(v) for k, v in res.items()})
