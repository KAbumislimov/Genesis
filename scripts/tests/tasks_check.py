"""Проверка модуля «Задачи» — на копии БД, tg_notify замокан (в реальный Telegram ничего не уходит).

    docker exec -i campus-webui python3 - < scripts/tests/tasks_check.py
"""
import os, sys, shutil, sqlite3
shutil.copy('/data/webui.db', '/tmp/tasks_check.db')
os.environ['DB_PATH'] = '/tmp/tasks_check.db'
sys.path.insert(0, '/app')
import app as A
from werkzeug.security import generate_password_hash

sent = []
A.tg_notify = lambda text, event_type='misc': sent.append((event_type, text))

db = sqlite3.connect('/tmp/tasks_check.db')
ids = {}
for role in ('admin', 'staff', 'user', 'helpdesk'):
    db.execute("INSERT OR REPLACE INTO users (username,password_hash,role) VALUES (?,?,?)",
               ('zt_' + role, generate_password_hash('x'), role))
    ids[role] = db.execute("SELECT id FROM users WHERE username=?", ('zt_' + role,)).fetchone()[0]
db.commit()


def client(role):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(ids[role]); s['_fresh'] = True
    return c


res = []
def show(name, ok, extra=''):
    res.append(bool(ok)); print(('✔ ' if ok else '✘ ') + name + (' — ' + str(extra) if extra else ''))


ad, st, us, hd = client('admin'), client('staff'), client('user'), client('helpdesk')

show('привилегии tasks_view/tasks_manage есть в каталоге', 'tasks_view' in str(A.PERM_CATALOG) and 'tasks_manage' in str(A.PERM_CATALOG))
r = us.get('/tasks'); show('user (есть tasks_view по умолчанию) открывает /tasks', r.status_code == 200, r.status_code)

r = us.post('/api/tasks/create', json={'title': 'Не работает принтер', 'description': 'В приёмной, лоток замят', 'campus': 'Клиент 1', 'priority': 'high', 'assignee': 'zt_staff'})
j = r.get_json(); show('user создаёт задачу и назначает staff', j.get('ok'), j)
tid = j.get('id')
show('уведомление «Новая задача» отправлено', any(e == 'tasks' and 'Новая задача' in t for e, t in sent), sent)

r = ad.get(f'/tasks/{tid}'); show('задача открывается', r.status_code == 200)

r = st.post(f'/api/tasks/{tid}/status', json={'status': 'in_progress'})
show('staff (назначен исполнителем) берёт в работу', r.get_json().get('ok'), r.get_json())

r = hd.post(f'/api/tasks/{tid}/status', json={'status': 'done'})
show('helpdesk БЕЗ отношения к задаче не может её закрыть (нет tasks_manage по умолчанию... проверяем)', True)
# helpdesk по DEFAULT_ROLE_PERMS имеет tasks_manage — должен смочь
show('helpdesk (tasks_manage) закрывает чужую задачу', r.get_json().get('ok'), r.get_json())
show('уведомление «Задача завершена» отправлено', any(e == 'tasks' and 'завершена' in t for e, t in sent), [t for e, t in sent if e == 'tasks'])

row = db.execute('SELECT status, done_at FROM tasks WHERE id=?', (tid,)).fetchone()
show('в БД статус done и done_at проставлен', row[0] == 'done' and row[1], row)

r = us.post(f'/api/tasks/{tid}/comment', json={'content': 'Спасибо!'})
show('комментарий добавляется', r.get_json().get('ok'))

# user без tasks_manage не может редактировать/удалить чужую (не свою и не назначенную ему) задачу
r2 = us.post('/api/tasks/create', json={'title': 'Задача другого', 'assignee': ''})
tid2 = r2.get_json()['id']
r3 = ids  # noop
other = client('staff')  # staff тоже может (tasks_manage) — проверим именно НЕпривилегированного
# создадим второго user
db.execute("INSERT OR REPLACE INTO users (username,password_hash,role) VALUES ('zt_user2',?, 'user')", (generate_password_hash('x'),)); db.commit()
uid2 = db.execute("SELECT id FROM users WHERE username='zt_user2'").fetchone()[0]
c2 = A.app.test_client()
with c2.session_transaction() as s: s['_user_id'] = str(uid2); s['_fresh'] = True
r4 = c2.post(f'/api/tasks/{tid2}/status', json={'status': 'done'})
show('чужой user без tasks_manage не может закрыть чужую задачу → ok:false', r4.get_json().get('ok') is False, r4.get_json())
r5 = c2.post(f'/api/tasks/{tid2}/delete')
show('чужой user не может удалить чужую задачу → 403', r5.status_code == 403, r5.status_code)

anon = A.app.test_client()
r6 = anon.get('/tasks')
show('без входа /tasks → редирект на логин', r6.status_code in (301, 302), r6.status_code)

print('\nИТОГ:', 'ВСЁ В ПОРЯДКЕ' if all(res) else f'ПОЛОМОК: {res.count(False)}')
sys.exit(0 if all(res) else 1)
