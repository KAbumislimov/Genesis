"""Проверка «дизайна плеера по умолчанию» и превью — на КОПИИ БД внутри контейнера (боевые данные не трогаются).

    docker exec -i campus-webui python3 - < scripts/tests/ui_default_perm_check.py
"""
import os, sys, shutil, sqlite3
shutil.copy('/data/webui.db', '/tmp/ui_def_perm.db')
os.environ['DB_PATH'] = '/tmp/ui_def_perm.db'
sys.path.insert(0, '/app')
import app as A
from werkzeug.security import generate_password_hash

db = sqlite3.connect('/tmp/ui_def_perm.db')
ids = {}
for role in ('admin', 'staff', 'helpdesk'):
    db.execute("INSERT OR REPLACE INTO users (username,password_hash,role,ui_variant) VALUES (?,?,?,'')", ('zt_' + role, generate_password_hash('x'), role))
    ids[role] = db.execute("SELECT id FROM users WHERE username=?", ('zt_' + role,)).fetchone()[0]
db.execute("DELETE FROM settings WHERE key='ui_default'")
db.commit()


def client(role):
    c = A.app.test_client()
    if role:
        with c.session_transaction() as s:
            s['_user_id'] = str(ids[role]); s['_fresh'] = True
    return c


res = []
def show(name, ok, extra=''):
    res.append(bool(ok)); print(('✔ ' if ok else '✘ ') + name + (' — ' + str(extra) if extra else ''))


def q(sql, *a):
    with sqlite3.connect('/tmp/ui_def_perm.db') as c:
        return c.execute(sql, a).fetchone()


ad, st, hd, anon = client('admin'), client('staff'), client('helpdesk'), client(None)
show('привилегия ui_default есть в каталоге', 'ui_default' in str(A.PERM_CATALOG))
r = st.post('/api/ui-default', json={'style': 'oled'}); show('staff без привилегии → 403', r.status_code == 403, r.status_code)
r = st.get('/api/ui-default'); show('staff GET → 403', r.status_code == 403)
r = ad.post('/api/ui-default', json={'style': 'oled'}); show('админ выбирает «oled»', r.status_code == 200 and r.get_json().get('current') == 'oled', r.get_json())
r = ad.post('/api/ui-default', json={'style': 'нет-такого'}); show('неизвестный вариант → 400', r.status_code == 400)
r = ad.post('/api/ui-default', json={'style': 'off'}); show('«off» нельзя сделать основным → 400', r.status_code == 400)
r = ad.post('/api/ui-default', json={'style': '../../etc'}); show('мусор в названии → 400', r.status_code == 400)
row = q("SELECT value FROM settings WHERE key='ui_default'"); show('значение сохранено в settings', bool(row) and row[0] == 'oled', row)
# у пользователя без своего выбора открывается основной, а личный выбор сильнее
r = hd.get('/'); show('helpdesk без своего выбора: «/» → /v13 (OLED)', r.status_code == 302 and r.headers['Location'].endswith('/v13'), r.headers.get('Location'))
hd.set_cookie('ui', 'glass'); r = hd.get('/'); show('личный выбор (glass) сильнее основного', r.headers['Location'].endswith('/v10'), r.headers.get('Location'))
hd.delete_cookie('ui')
# выдача привилегии роли
r = ad.post('/api/roles/set', json={'role': 'staff', 'perm': 'ui_default', 'allowed': True}); show('админ выдаёт staff «ui_default»', r.get_json().get('ok'), r.get_json())
r = st.post('/api/ui-default', json={'style': 'soft'}); show('staff теперь может → 200', r.status_code == 200, r.status_code)
html = st.get('/settings').get_data(as_text=True); show('в Настройках у staff есть кнопка «Сделать основным для всех»', 'ud-btn ghost ud-def' in html)
html_h = hd.get('/settings').get_data(as_text=True); show('у helpdesk кнопки нет', 'ud-btn ghost ud-def' not in html_h)
ad.post('/api/roles/set', json={'role': 'staff', 'perm': 'ui_default', 'allowed': False})
r = st.post('/api/ui-default', json={'style': 'rows'}); show('после снятия staff снова 403', r.status_code == 403)
# предпросмотр не сохраняет выбор
c = client('helpdesk'); r = c.get('/v11?preview=1')
show('?preview=1 → 200 без Set-Cookie', r.status_code == 200 and 'ui=' not in (r.headers.get('Set-Cookie') or ''), r.headers.get('Set-Cookie'))
pref = q('SELECT ui_variant FROM users WHERE id=?', ids['helpdesk'])[0]; show('и выбор в аккаунте не изменился', not pref, repr(pref))
r = c.get('/v11'); show('обычный заход на /v11 запоминает выбор (Set-Cookie ui=rows)', 'ui=rows' in (r.headers.get('Set-Cookie') or ''))
# превью-картинки: только для вошедших, без обхода каталога
r = ad.get('/ui-preview/glass.jpg'); show('превью glass.jpg вошедшему → 200 image/jpeg', r.status_code == 200 and r.mimetype == 'image/jpeg', (r.status_code, r.mimetype))
r = anon.get('/ui-preview/glass.jpg'); show('без входа → редирект/401 (не 200)', r.status_code in (301, 302, 401, 403), r.status_code)
r = ad.get('/ui-preview/..%2Fapp.jpg'); show('обход каталога → 404', r.status_code == 404, r.status_code)
r = ad.get('/ui-preview/nothing.jpg'); show('несуществующая картинка → 404', r.status_code == 404)
r = ad.get('/static/ui_previews/glass.jpg'); show('в /static превью не лежат', r.status_code == 404)
missing = [k for k in [v['key'] for v in A.UI_VARIANT_INFO] + ['off', 'tabler'] if not os.path.exists(f'/app/ui_previews/{k}.jpg')]
show('превью есть для всех вариантов', not missing, missing)
bad = [v['key'] for v in A.UI_VARIANT_INFO if not v.get('feat') or v['key'] not in A._UI_VARIANTS]
show('у всех вариантов есть «плюшки» и маршрут', not bad, bad)
print('\nИТОГ:', 'ВСЁ В ПОРЯДКЕ' if all(res) else f'ПОЛОМОК: {res.count(False)}')
sys.exit(0 if all(res) else 1)
