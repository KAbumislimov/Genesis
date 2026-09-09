import sqlite3
from werkzeug.security import generate_password_hash
c = sqlite3.connect('/data/webui.db')
h = generate_password_hash('QaTest12345!')
try:
    c.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,datetime('now'))",
               ('_qa_test_claude', h, 'admin'))
    c.commit()
except sqlite3.IntegrityError:
    pass
print('ready:', c.execute("SELECT id, role FROM users WHERE username=?", ('_qa_test_claude',)).fetchone())
