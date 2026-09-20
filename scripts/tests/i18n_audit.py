#!/usr/bin/env python3
"""Ищет непереведённый (кириллический) текст на страницах панели при выбранном языке EN/AZ.
Нужен playwright (chromium) и значение cookie сессии администратора (--cookie).
Названия треков и чат игнорируются. Пример:
  python3 scripts/tests/i18n_audit.py --cookie "<session>" --lang az --pages v4,settings,admin --ui console
"""
import argparse, re
from playwright.sync_api import sync_playwright

JS = r"""
() => {
  const out = {}, cyr = /[А-Яа-яЁё]/;
  const add = (s, w) => { s = s.replace(/\s+/g, ' ').trim(); if (s && cyr.test(s)) out[s] = w; };
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
  while (n = tw.nextNode()) {
    const p = n.parentElement; if (!p || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(p.tagName)) continue;
    if (p.closest('.wamp2-pnm,#pl-list,.cp-msg-bubble')) continue;
    add(n.data, 'text');
  }
  document.querySelectorAll('[title],[placeholder],[aria-label]').forEach(e => ['title', 'placeholder', 'aria-label'].forEach(a => { const v = e.getAttribute(a); if (v) add(v, a); }));
  return out;
}
"""

ap = argparse.ArgumentParser()
ap.add_argument('--cookie', required=True); ap.add_argument('--lang', default='en'); ap.add_argument('--ui', default='console')
ap.add_argument('--pages', default='v4'); ap.add_argument('--base', default='https://127.0.0.1:8090')
a = ap.parse_args()
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(ignore_https_errors=True, viewport={'width': 1500, 'height': 950})
    ctx.add_cookies([{'name': 'session', 'value': a.cookie, 'url': a.base}, {'name': 'ui', 'value': a.ui, 'url': a.base}])
    ctx.add_init_script(f"localStorage.setItem('lang','{a.lang}')")
    pg = ctx.new_page()
    for path in a.pages.split(','):
        pg.goto(f'{a.base}/{path}', wait_until='domcontentloaded'); pg.wait_for_timeout(4500)
        rest = [k for k, _ in pg.evaluate(JS).items() if not re.search(r'\.(mp3|wav|ogg|flac|m4a)$', k, re.I)]
        print(f'{a.lang} {path}: непереведённых строк — {len(rest)}')
        for k in rest[:20]:
            print('   ', k[:110])
    b.close()
