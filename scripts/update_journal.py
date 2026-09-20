#!/usr/bin/env python3
"""Автоматический журнал «что и когда менялось» → docs/journal/ГГГГ-ММ-ДД.md (уходит в GitHub вместе с кодом).

Запускается из backup-to-github.sh (каждые ~45 с при изменениях) ПЕРЕД коммитом:
  • смотрит, какие файлы сейчас изменены (git status), и складывает их в 15-минутное «окно»
    с человеческими названиями областей (веб-панель, кампус, скрипты, документация…);
  • события состояния (права ролей, настройки, машины, пользователи, расписание, crontab, снимок БД)
    дописывает export_state.py через journal_add().
Ручные заметки можно писать в раздел «Заметки» этого же файла — скрипт их не трогает.
Файл state/ и сам журнал в отчёт не попадают (иначе журнал вёл бы журнал самого себя).
"""
import json, os, re, subprocess, sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))            # .../campus-infra
JOURNAL_DIR = os.path.join(ROOT, 'docs', 'journal')
CACHE = os.path.expanduser('~/.cache/campus-journal-cache.json')
WEEKDAYS = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
SECTIONS = {
    'code':  '## Изменения кода и конфигов',
    'state': '## Изменения состояния системы (права, настройки, машины, снимки БД)',
    'notes': '## Заметки',
}
HEADER_NOTE = ('> Ведётся автоматически: `scripts/update_journal.py` и `scripts/export_state.py` (каждые ~45 секунд при изменениях, '
               'запись идёт в GitHub вместе с кодом). Ручные пояснения — в разделе «Заметки».')

# (подстрока пути → человеческое название области); первое совпадение выигрывает
AREAS = [
    ('campus-infra/webui/app.py', 'Веб-панель: серверный код'),
    ('campus-infra/webui/templates/roles.html', 'Веб-панель: роли и права'),
    ('campus-infra/webui/templates/', 'Веб-панель: страницы и шаблоны'),
    ('campus-infra/webui/static/i18n', 'Веб-панель: переводы (RU/EN/AZ)'),
    ('campus-infra/webui/static/', 'Веб-панель: стили и скрипты'),
    ('campus-infra/webui/', 'Веб-панель'),
    ('campus-infra/machines/', 'Скрипты и настройки кампусов'),
    ('campus-infra/bots/', 'Telegram-боты'),
    ('campus-infra/scripts/', 'Скрипты сервера (бэкапы, синхронизация, восстановление)'),
    ('campus-infra/config/', 'Конфиги Prometheus/Grafana/Loki'),
    ('campus-infra/docs/', 'Документация'),
    ('campus-infra/restore', 'Восстановление из GitHub'),
    ('campus-infra/RESTORE', 'Восстановление из GitHub'),
    ('campus-infra/docker-compose', 'Docker Compose'),
    ('campus-infra/data/', 'Данные панели (звуки, обои)'),
    ('campus-infra/', 'Прочее в campus-infra'),
    ('helpdesk-ops/', 'Helpdesk Ops'),
    ('ops-journal/', 'Журнал ops'),
]
SKIP = ('campus-infra/docs/journal/', 'campus-infra/state/')


def area_of(path):
    for key, label in AREAS:
        if key in path:
            return label
    return 'Прочее'


def journal_path(day=None):
    d = day or datetime.now()
    return os.path.join(JOURNAL_DIR, d.strftime('%Y-%m-%d') + '.md')


def _new_file(now):
    return (f"# Журнал — {now.strftime('%Y-%m-%d')} ({WEEKDAYS[now.weekday()]})\n\n{HEADER_NOTE}\n\n"
            f"{SECTIONS['code']}\n\n{SECTIONS['state']}\n\n{SECTIONS['notes']}\n\n")


def _load(now):
    p = journal_path(now)
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    if not os.path.isfile(p):
        return p, _new_file(now)
    with open(p, encoding='utf-8') as f:
        text = f.read()
    for k in ('code', 'state', 'notes'):          # если раздел кто-то удалил — вернём
        if SECTIONS[k] not in text:
            text = text.rstrip('\n') + f"\n\n{SECTIONS[k]}\n\n"
    return p, text


def _insert(text, section, line, marker=None):
    """Вставляет строку в конец раздела; если есть marker — заменяет уже существующую строку с ним."""
    if marker and marker in text:
        return re.sub(r'^.*' + re.escape(marker) + r'.*$', lambda m: line, text, count=1, flags=re.M)
    head = SECTIONS[section]
    i = text.index(head) + len(head)
    j = text.find('\n## ', i)
    if j == -1:
        j = len(text)
    body = text[i:j].rstrip('\n')
    if not body.strip():
        body = '\n'
    tail = text[j:].lstrip('\n')
    return text[:i] + body + '\n' + line + '\n' + ('\n' + tail if tail else '')


def journal_add(section, text):
    """Дописать событие в раздел журнала за сегодня (та же строка подряд повторно не пишется)."""
    now = datetime.now()
    p, t = _load(now)
    seg = t.split(SECTIONS[section], 1)[1].split('\n## ')[0]
    if any(l.rstrip().endswith(text) for l in seg.strip().split('\n')[-3:]):
        return
    t = _insert(t, section, f"- {now.strftime('%H:%M')} · {text}")
    with open(p, 'w', encoding='utf-8') as f:
        f.write(t)


def git_changes():
    """[(статус, путь)] по изменённым файлам campus-infra/helpdesk-ops/ops-journal (пути — относительно ~/projects)."""
    top = subprocess.run(['git', '-C', ROOT, 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
    if not top:
        return []
    out = subprocess.run(['git', '-C', top, 'status', '--porcelain', '-uall', '--',
                          'projects/campus-infra', 'projects/helpdesk-ops', 'projects/ops-journal'],
                         capture_output=True, text=True).stdout
    res = []
    for ln in out.splitlines():
        if len(ln) < 4:
            continue
        st, path = ln[:2].strip(), ln[3:].strip().strip('"')
        if ' -> ' in path:
            path = path.split(' -> ')[1]
        path = path.replace('projects/', '', 1)
        if any(s in path for s in SKIP):
            continue
        res.append((st, path))
    return res


def main():
    now = datetime.now()
    changes = git_changes()
    if not changes:
        return 0
    try:
        cache = json.load(open(CACHE))
    except (OSError, ValueError):
        cache = {}
    bucket = now.strftime('%Y%m%d') + f"{now.hour:02d}{(now.minute // 15) * 15:02d}"
    win = cache.get(bucket, {'areas': {}, 'added': 0, 'removed': 0, 'changed': 0})
    for st, path in changes:
        a = win['areas'].setdefault(area_of(path), [])
        name = os.path.basename(path)
        if name not in a:
            a.append(name)
    # чистим кэш прошлых окон
    cache = {bucket: win}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, 'w'), ensure_ascii=False)

    start = f"{now.hour:02d}:{(now.minute // 15) * 15:02d}"
    parts = []
    for label, names in win['areas'].items():
        shown = ', '.join(names[:4]) + (f' (+{len(names) - 4})' if len(names) > 4 else '')
        parts.append(f"**{label}** — {shown}")
    line = f"- {start} · " + '; '.join(parts) + f" <!--b:{bucket}-->"
    p, t = _load(now)
    t = _insert(t, 'code', line, marker=f"<!--b:{bucket}-->")
    with open(p, 'w', encoding='utf-8') as f:
        f.write(t)
    return 0


if __name__ == '__main__':
    sys.exit(main())
