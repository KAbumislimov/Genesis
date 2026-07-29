import os, sqlite3, smtplib, requests
from datetime import datetime
from functools import wraps
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, send_from_directory)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'landau-helpdesk-secret-2026')

DB        = os.environ.get('DB_PATH', '/data/helpdesk.db')
UPLOAD    = os.environ.get('UPLOAD_DIR', '/data/uploads')
MAX_MB    = int(os.environ.get('MAX_UPLOAD_MB', '50'))
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'landau2026')

TG_TOKEN  = os.environ.get('TG_TOKEN', '')
TG_CHAT   = os.environ.get('TG_CHAT', '')
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
NOTIFY_TO = os.environ.get('NOTIFY_TO', '')

ALLOWED   = {'png','jpg','jpeg','gif','webp','mp4','mov','avi','mkv','pdf'}

CAMPUSES = [
    'Narimanov','Bayıl','Ağ-Şəhər','Xatai BCR','Seabreeze',
    'Simurq Gənclik','West Town','Simurq Xaqlar','Simurq Xırdalan',
    'Simurq Zəbrat','Gəncə Bani','City Garden'
]

PROBLEM_TYPES = [
    # Hardware / Aparat / Железо
    'İşləmir / Açılmır · Not working / Dead · Не включается',
    'Fiziki zədə · Physical damage · Физическое повреждение',
    'Ekran / Displey · Screen / Display · Экран / Дисплей',
    'Çap etmir · Not printing · Не печатает',
    'Şəbəkə / Internet / Wi-Fi · Network / Wi-Fi · Сеть / Интернет',
    'Həddən artıq qızma / Səs-küy · Overheating / Noise · Перегрев / Шум',
    # Software / Proqram təminatı / Программное обеспечение
    'Proqram: işə düşmür / donur · SW: crash / freeze · ПО: зависает',
    'Proqram: xəta verir · SW: error · ПО: ошибка',
    'Virus / Yavaş işləyir · Virus / Slow · Вирус / Медленно работает',
    'Proqram: quraşdırılmır · SW: install error · ПО: не устанавливается',
    'Lisenziya problemi · License issue · Проблема с лицензией',
    'Windows / Sürücülər · Windows / Drivers · Windows / Драйверы',
    # Other / Digər / Прочее
    'Digər · Other · Другое',
]

STATUSES = {
    'open':       ('🔴', 'Новая'),
    'in_progress':('🟡', 'В работе'),
    'resolved':   ('🟢', 'Решено'),
    'closed':     ('⚫', 'Закрыто'),
}

os.makedirs(UPLOAD, exist_ok=True)

# ── DB ────────────────────────────────────────────────────────────────
def get_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

# (group, display_az, full_trilingual)
CATEGORY_GROUPS = [
    ('🌐 Şəbəkə / Network / Сеть', [
        ('Açarlar (Switch)',          'Switches · Açarlar · Свичи'),
        ('Giriş nöqtəsi (Wi-Fi)',     'Access Points · Giriş Nöqtələri · Аксесс-поинты'),
        ('Konverter',                 'Converters · Konverterlər · Конверторы'),
        ('Fortinet / Firewall',       'Fortinet / Firewall · Fortinet · Файрволл'),
    ]),
    ('🔒 Təhlükəsizlik / Security / Безопасность', [
        ('IP Kamera',                 'IP Cameras · IP Kameralar · IP-камеры'),
        ('Müşahidə Kamerası (CCTV)',  'CCTV · Müşahidə Kameraları · Камеры'),
        ('NVR',                       'NVR · NVR · НВР / Видеорегистраторы'),
        ('Turniket / SKUD',           'Turnstiles · Turniketlər · Турникеты'),
        ('Kart oxuyucu (RFID)',       'Card Readers · Kart Oxuyucular · Карт-ридеры'),
        ('RFID kart / Buraxılış',     'RFID Cards · RFID Kartlar · RFID-карты'),
        ('Barmaq izi skaneri',        'Fingerprint Scanner · Barmaq İzi · Отпечатки пальцев'),
    ]),
    ('💻 Kompüter / Computer / Компьютер', [
        ('Stasionar kompüter',        'Desktop · Stasionar Kompüter · Настольный ПК'),
        ('Noutbuk',                   'Laptop · Noutbuk · Ноутбук'),
        ('Monitor',                   'Monitor · Monitor · Монитор'),
        ('Klaviatura / Siçan',        'Keyboard / Mouse · Klaviatura/Siçan · Клавиатура/Мышь'),
        ('UPS / İBP',                 'UPS · UPS · УПС / ИБП'),
    ]),
    ('🔌 Hub / Adapter / Переходники', [
        ('HDMI Hub / Splitter',       'HDMI Hub / Splitter · HDMI Hub · HDMI Хаб'),
        ('Uzadıcı (HDMI/USB)',        'Extender · Uzadıcı · Экстендер'),
        ('USB Hub',                   'USB Hub · USB Hub · USB-хаб'),
        ('Adapter / Keçid',           'Adapter · Adapter · Адаптер/Переходник'),
    ]),
    ('🖨️ Çap / Print / Печать', [
        ('Printer (masaüstü)',        'Desktop Printer · Masaüstü Printer · Принтер настольный'),
        ('Printer (böyük / plotter)', 'Large Printer/Plotter · Böyük Printer · Плоттер'),
        ('Skaner',                    'Scanner · Skaner · Сканер'),
    ]),
    ('🖥️ Ekran / Display / Дисплей', [
        ('Televizor',                 'TV · Televizor · Телевизор'),
        ('Proyektor',                 'Projector · Proyektor · Проектор'),
        ('Ağıllı lövhə (Smart Board)','Smart Board · Ağıllı Lövhə · Смарт-доска'),
    ]),
    ('📱 Cihazlar / Devices / Устройства', [
        ('Planşet',                   'Tablet · Planşet · Планшет'),
        ('Qrafik planşet',            'Graphics Tablet · Qrafik Planşet · Графический планшет'),
        ('Mobil telefon',             'Mobile Phone · Mobil Telefon · Мобильный телефон'),
        ('IP telefon (Yealink)',      'IP Phone · IP Telefon · IP-телефон (Ялинки)'),
    ]),
    ('🔊 Audio / Audio / Аудио', [
        ('Dinamik / Kolonka',         'Speaker · Dinamik · Колонка'),
        ('Gücləndirici',              'Amplifier · Gücləndirici · Усилитель'),
        ('Mikrafon',                  'Microphone · Mikrafon · Микрофон'),
    ]),
    ('🗂️ Digər / Other / Прочее', [
        ('Kabel / Naqil',             'Cable · Kabel · Кабель/Провод'),
        ('Aksesuar / Sair',           'Accessories · Aksesuarlar · Аксессуары'),
    ]),
]

DEFAULT_CATEGORIES = [full for group, items in CATEGORY_GROUPS for _, full in items]

def init_db():
    with get_db() as c:
        c.executescript('''
            CREATE TABLE IF NOT EXISTS categories (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS assets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                cat_id     INTEGER REFERENCES categories(id),
                name       TEXT NOT NULL,
                model      TEXT,
                inv_code   TEXT,
                serial     TEXT,
                part_num   TEXT,
                campus     TEXT,
                notes      TEXT
            );
            CREATE TABLE IF NOT EXISTS reports (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at   TEXT DEFAULT (datetime('now','localtime')),
                campus       TEXT NOT NULL,
                reporter     TEXT,
                contact      TEXT,
                cat_name     TEXT,
                asset_name   TEXT,
                model        TEXT,
                inv_code     TEXT,
                serial       TEXT,
                part_num     TEXT,
                problem_type TEXT,
                description  TEXT,
                status       TEXT DEFAULT 'open',
                admin_note   TEXT,
                updated_at   TEXT
            );
            CREATE TABLE IF NOT EXISTS report_files (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER REFERENCES reports(id),
                filename  TEXT NOT NULL,
                orig_name TEXT
            );
        ''')
        for cat in DEFAULT_CATEGORIES:
            c.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (cat,))

init_db()

# ── Auth ──────────────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return wrapper

# ── Notifications ─────────────────────────────────────────────────────
def notify(report):
    text = (
        f"📋 *Новая заявка #{report['id']}*\n"
        f"🏫 Кампус: {report['campus']}\n"
        f"👤 {report['reporter'] or '—'} | {report['contact'] or '—'}\n"
        f"🗂 {report['cat_name']} → {report['asset_name']}\n"
        f"📦 Инв: {report['inv_code'] or '—'} | S/N: {report['serial'] or '—'}\n"
        f"⚠️ {report['problem_type']}\n"
        f"💬 {report['description']}"
    )
    if TG_TOKEN and TG_CHAT:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={'chat_id': TG_CHAT, 'text': text, 'parse_mode': 'Markdown'},
                timeout=5
            )
        except Exception:
            pass
    if SMTP_HOST and NOTIFY_TO:
        try:
            msg = MIMEMultipart()
            msg['Subject'] = f"[LANDAU Helpdesk] Заявка #{report['id']} — {report['campus']}"
            msg['From']    = SMTP_USER
            msg['To']      = NOTIFY_TO
            msg.attach(MIMEText(text.replace('*','').replace('_',''), 'plain', 'utf-8'))
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        except Exception:
            pass

# ── Public ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    with get_db() as c:
        cats   = c.execute('SELECT * FROM categories ORDER BY name').fetchall()
        assets = c.execute('SELECT * FROM assets ORDER BY name').fetchall()
    return render_template('index.html',
        campuses=CAMPUSES, cats=cats, assets=assets,
        problem_types=PROBLEM_TYPES, cat_groups=CATEGORY_GROUPS)

@app.route('/submit', methods=['POST'])
def submit():
    f = request.form
    files = request.files.getlist('attachments')

    with get_db() as c:
        cur = c.execute('''
            INSERT INTO reports
              (campus,reporter,contact,cat_name,asset_name,model,inv_code,serial,part_num,problem_type,description)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            f.get('campus',''), f.get('reporter',''), f.get('contact',''),
            f.get('cat_name',''), f.get('asset_name',''), f.get('model',''),
            f.get('inv_code',''), f.get('serial',''), f.get('part_num',''),
            f.get('problem_type',''), f.get('description','')
        ))
        rid = cur.lastrowid

        for file in files:
            if file and file.filename:
                ext = file.filename.rsplit('.',1)[-1].lower()
                if ext in ALLOWED:
                    fname = f"{rid}_{secure_filename(file.filename)}"
                    file.save(os.path.join(UPLOAD, fname))
                    c.execute('INSERT INTO report_files (report_id,filename,orig_name) VALUES (?,?,?)',
                              (rid, fname, file.filename))

        report = dict(c.execute('SELECT * FROM reports WHERE id=?', (rid,)).fetchone())

    notify(report)
    return redirect(url_for('success', rid=rid))

@app.route('/success/<int:rid>')
def success(rid):
    return render_template('success.html', rid=rid)

@app.route('/uploads/<path:filename>')
@admin_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD, filename)

# ── Admin auth ────────────────────────────────────────────────────────
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    err = None
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and \
           request.form.get('password') == ADMIN_PASS:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        err = 'Неверный логин или пароль'
    return render_template('admin/login.html', err=err)

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

# ── Admin: reports ─────────────────────────────────────────────────────
@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    campus  = request.args.get('campus','')
    status  = request.args.get('status','')
    cat     = request.args.get('cat','')
    q       = 'SELECT * FROM reports WHERE 1=1'
    params  = []
    if campus: q += ' AND campus=?';     params.append(campus)
    if status: q += ' AND status=?';     params.append(status)
    if cat:    q += ' AND cat_name=?';   params.append(cat)
    q += ' ORDER BY id DESC'
    with get_db() as c:
        reports  = c.execute(q, params).fetchall()
        cats     = [r[0] for r in c.execute('SELECT DISTINCT cat_name FROM reports WHERE cat_name!=""').fetchall()]
    return render_template('admin/dashboard.html',
        reports=reports, campuses=CAMPUSES, statuses=STATUSES,
        cats=cats, f_campus=campus, f_status=status, f_cat=cat)

@app.route('/admin/report/<int:rid>')
@admin_required
def admin_report(rid):
    with get_db() as c:
        report = c.execute('SELECT * FROM reports WHERE id=?', (rid,)).fetchone()
        files  = c.execute('SELECT * FROM report_files WHERE report_id=?', (rid,)).fetchall()
    if not report:
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/report.html', report=report,
                           files=files, statuses=STATUSES)

@app.route('/admin/report/<int:rid>/update', methods=['POST'])
@admin_required
def admin_update(rid):
    status = request.form.get('status')
    note   = request.form.get('admin_note','')
    with get_db() as c:
        c.execute("UPDATE reports SET status=?, admin_note=?, updated_at=datetime('now','localtime') WHERE id=?",
                  (status, note, rid))
    return redirect(url_for('admin_report', rid=rid))

# ── Admin: assets ─────────────────────────────────────────────────────
@app.route('/admin/assets')
@admin_required
def admin_assets():
    with get_db() as c:
        cats   = c.execute('SELECT * FROM categories ORDER BY name').fetchall()
        assets = c.execute('''
            SELECT a.*, c.name as cat_name FROM assets a
            LEFT JOIN categories c ON a.cat_id=c.id
            ORDER BY c.name, a.name
        ''').fetchall()
    return render_template('admin/assets.html', cats=cats, assets=assets,
                           campuses=CAMPUSES, cat_groups=CATEGORY_GROUPS)

@app.route('/admin/api/categories', methods=['POST'])
@admin_required
def api_add_category():
    name = request.json.get('name','').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Имя не указано'})
    try:
        with get_db() as c:
            c.execute('INSERT INTO categories (name) VALUES (?)', (name,))
            cat_id = c.execute('SELECT id FROM categories WHERE name=?', (name,)).fetchone()[0]
        return jsonify({'ok': True, 'id': cat_id, 'name': name})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'error': 'Категория уже существует'})

@app.route('/admin/api/categories/<int:cid>', methods=['DELETE'])
@admin_required
def api_del_category(cid):
    with get_db() as c:
        c.execute('DELETE FROM assets WHERE cat_id=?', (cid,))
        c.execute('DELETE FROM categories WHERE id=?', (cid,))
    return jsonify({'ok': True})

@app.route('/admin/api/assets', methods=['POST'])
@admin_required
def api_add_asset():
    d = request.json or {}
    if not d.get('name') or not d.get('cat_id'):
        return jsonify({'ok': False, 'error': 'Укажите категорию и название'})
    with get_db() as c:
        c.execute('INSERT INTO assets (cat_id,name,model,inv_code,serial,part_num,campus,notes) VALUES (?,?,?,?,?,?,?,?)',
                  (d['cat_id'], d['name'], d.get('model',''), d.get('inv_code',''), d.get('serial',''),
                   d.get('part_num',''), d.get('campus',''), d.get('notes','')))
        aid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    return jsonify({'ok': True, 'id': aid})

@app.route('/admin/api/assets/<int:aid>', methods=['DELETE'])
@admin_required
def api_del_asset(aid):
    with get_db() as c:
        c.execute('DELETE FROM assets WHERE id=?', (aid,))
    return jsonify({'ok': True})

@app.route('/api/assets_by_cat/<int:cat_id>')
def assets_by_cat(cat_id):
    with get_db() as c:
        rows = c.execute(
            'SELECT id,name,model,inv_code,serial,part_num FROM assets WHERE cat_id=? ORDER BY name',
            (cat_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
