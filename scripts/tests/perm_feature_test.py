"""Проверка новой функции на КОПИИ БД: назначение/снятие привилегий, закреплённые права, сброс."""
import os, sys, shutil, sqlite3, json
shutil.copy('/data/webui.db', '/tmp/perm_feat.db')
os.environ['DB_PATH'] = '/tmp/perm_feat.db'
sys.path.insert(0, '/app')
import app as A
from werkzeug.security import generate_password_hash

db = sqlite3.connect('/tmp/perm_feat.db')
ids = {}
for role in ('admin', 'staff', 'helpdesk', 'eventmanager', 'user'):
    db.execute("INSERT OR REPLACE INTO users (username,password_hash,role) VALUES (?,?,?)", ('zt_' + role, generate_password_hash('x'), role))
    ids[role] = db.execute("SELECT id FROM users WHERE username=?", ('zt_' + role,)).fetchone()[0]
db.commit()


def client(role):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(ids[role]); s['_fresh'] = True
    return c


def show(name, ok, extra=''):
    print(('✔ ' if ok else '✘ ') + name + (' — ' + str(extra) if extra else ''))
    return ok


ad = client('admin'); hd = client('helpdesk'); st = client('staff')
res = []
res.append(show('админ открывает /admin/roles', ad.get('/admin/roles').status_code == 200))
res.append(show('helpdesk НЕ открывает /admin/roles', hd.get('/admin/roles').status_code == 302))
res.append(show('матрица: 6 ролей × 39 привилегий', (lambda j: len(j['roles']) == 6 and sum(len(c['perms']) for c in j['categories']) == 39)(ad.get_json('/api/roles/matrix') if False else ad.get('/api/roles/matrix').get_json())))

# терминал: у helpdesk по умолчанию нет
r = hd.post('/api/terminal', json={}).get_json()
res.append(show('helpdesk без привилегии terminal → отказ', 'Недостаточно прав' in json.dumps(r, ensure_ascii=False), r))
r = ad.post('/api/roles/set', json={'role': 'helpdesk', 'perm': 'terminal', 'allowed': True}).get_json()
res.append(show('админ выдаёт helpdesk «terminal»', r.get('ok'), r))
r = hd.post('/api/terminal', json={}).get_json()
res.append(show('helpdesk теперь проходит проверку (нет отказа по правам)', 'Недостаточно прав' not in json.dumps(r, ensure_ascii=False), r))
r = ad.post('/api/roles/set', json={'role': 'helpdesk', 'perm': 'terminal', 'allowed': False}).get_json()
r2 = hd.post('/api/terminal', json={}).get_json()
res.append(show('админ снимает — снова отказ', 'Недостаточно прав' in json.dumps(r2, ensure_ascii=False), r2))

# снять у staff мониторинг → страница закрывается
ad.post('/api/roles/set', json={'role': 'staff', 'perm': 'monitor_view', 'allowed': False})
res.append(show('staff без monitor_view: /monitor → редирект', st.get('/monitor').status_code == 302))
res.append(show('staff без monitor_view: пункт «Мониторинг» скрыт в меню', 'url_for' not in st.get('/tracks').get_data(as_text=True) and '/monitor' not in st.get('/tracks').get_data(as_text=True).split('class="rail-list"')[1].split('</ul>')[0]))
ad.post('/api/roles/set', json={'role': 'staff', 'perm': 'monitor_view', 'allowed': True})
res.append(show('вернули — /monitor открывается', st.get('/monitor').status_code == 200))

# защита от эскалации
r = ad.post('/api/roles/set', json={'role': 'helpdesk', 'perm': 'roles_manage', 'allowed': True})
res.append(show('roles_manage нельзя выдать helpdesk', r.status_code == 400, r.get_json()))
r = ad.post('/api/roles/set', json={'role': 'helpdesk', 'perm': 'users_manage', 'allowed': True})
res.append(show('users_manage нельзя выдать helpdesk', r.status_code == 400))
r = ad.post('/api/roles/set', json={'role': 'admin', 'perm': 'play', 'allowed': False})
res.append(show('роль admin менять нельзя', r.status_code == 400))
r = hd.post('/api/roles/set', json={'role': 'helpdesk', 'perm': 'terminal', 'allowed': True})
res.append(show('helpdesk не может сам себе выдать права', r.status_code == 302, r.status_code))
r = ad.post('/api/roles/set', json={'role': 'helpdesk', 'perm': 'zzz', 'allowed': True})
res.append(show('неизвестная привилегия отклоняется', r.status_code == 400))

# bulk + reset
r = ad.post('/api/roles/bulk', json={'role': 'user', 'perms': ['himn', 'minuta'], 'allowed': True}).get_json()
uc = client('user')
res.append(show('bulk: user получил himn+minuta', uc.post('/api/himn/zzz', json={}).get_json().get('error') == 'Неизвестный кампус'))
ad.post('/api/roles/reset', json={'role': 'user'})
res.append(show('reset: у user снова нет himn', uc.post('/api/himn/zzz', json={}).get_json().get('error') == 'Нет прав на гимн'))

# журнал активности
n = db.execute("select count(*) from activity_log where action='role_perm'").fetchone()[0]
db2 = sqlite3.connect('/tmp/perm_feat.db'); n = db2.execute("select count(*) from activity_log where action='role_perm'").fetchone()[0]
res.append(show('изменения пишутся в журнал активности', n >= 5, f'{n} записей'))
print('\nИТОГО:', sum(1 for x in res if x), '/', len(res))
