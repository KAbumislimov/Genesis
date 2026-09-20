#!/usr/bin/env python3
"""Проверка всех дизайнов плеера (Настройки → «Дизайн интерфейса»).

Что проверяется:
  1. каждая страница /v3../v16 открывается (200), без ошибок JS, без горизонтального скролла — на 1500 и 390 px;
  2. три палитры (amber/aurora/rose): текст названий кампусов, трека и подписей читается (контраст >= 3:1);
  3. ?preview=1 не меняет выбранный дизайн (cookie 'ui' не появляется);
  4. «плюшки» вариантов в стиле Пульта: поворотные ручки (перетаскивание, колёсико, стрелки), «−/+», пресеты громкости, пиковые огоньки.
Все POST /api/* подменены заглушкой и записываются — на боевые колонки ничего не отправляется.

    python3 scripts/tests/ui_variants_check.py --cookie-file /путь/cookie.txt [--only glass,dial] [--base https://127.0.0.1:8090]
Код возврата 0 — всё в порядке.
"""
import argparse, json, ssl, sys, time, urllib.request

PAGES = {'studio': 3, 'console': 4, 'bento': 5, 'neon': 6, 'lumen': 7, 'rack': 8, 'deck': 9,
         'emerald': 10, 'ice': 11, 'crimson': 12, 'alu': 13, 'walnut': 14, 'neve': 15, 'rotor': 16, 'carbon': 17, 'night': 18, 'synth': 19}
PALS = ('amber', 'aurora', 'rose')
SEL = {'name': '.cpm-campus-name', 'track': '.c4-track', 'label': '.strip .cpm-campus-vol-val'}

CONTRAST_JS = """(sels) => {
  const parse = c => { const m = c.match(/[\\d.]+/g).map(Number); return {r:m[0], g:m[1], b:m[2], a: m.length > 3 ? m[3] : 1}; };
  const lum = ({r,g,b}) => { const f = v => { v /= 255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); }; return .2126*f(r)+.7152*f(g)+.0722*f(b); };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.backgroundImage !== 'none') return null; const c = parse(cs.backgroundColor); if (c.a > .6) return c; } return parse(getComputedStyle(document.body).backgroundColor); };  // градиент/картинка под текстом — контраст по цвету не определить, пропускаем
  const out = {};
  for (const [k, s] of Object.entries(sels)) {
    const el = document.querySelector(s); if (!el) { out[k] = null; continue; }
    const fg = parse(getComputedStyle(el).color), bg = bgOf(el); if (!bg) { out[k] = null; continue; }
    const l1 = lum(fg), l2 = lum(bg); out[k] = +((Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05)).toFixed(2);
  }
  return out; }"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--base', default='https://127.0.0.1:8090')
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    cookie = open(a.cookie_file).read().strip()
    keys = [k for k in (a.only.split(',') if a.only else PAGES) if k in PAGES]
    ctx0 = ssl._create_unverified_context()
    for _ in range(40):
        try:
            if urllib.request.urlopen(a.base + '/login', context=ctx0, timeout=3).status == 200:
                break
        except Exception:
            time.sleep(2)
    fails, posts = [], []

    def bad(msg):
        fails.append(msg); print('  ✗', msg)

    with sync_playwright() as p:
        b = p.chromium.launch()

        def new_ctx(w, h, pal='amber'):
            ctx = b.new_context(viewport={'width': w, 'height': h}, ignore_https_errors=True)
            ctx.add_cookies([{'name': 'session', 'value': cookie, 'url': a.base}])
            ctx.add_init_script(f"localStorage.setItem('lang','ru');localStorage.setItem('v3pal','{pal}')")
            return ctx

        def open_page(ctx, key, wait=6000):
            pg = ctx.new_page(); errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            def route(r, q):
                if q.method == 'POST':
                    posts.append((q.url.split('/api/')[-1], q.post_data)); r.fulfill(status=200, content_type='application/json', body='{"ok":true}')
                else:
                    r.continue_()
            pg.route(lambda u: '/api/' in u, route)
            resp = pg.goto(f'{a.base}/v{PAGES[key]}?preview=1', wait_until='domcontentloaded'); pg.wait_for_timeout(wait)
            return pg, resp, errs

        # 1–3. страницы × ширины, палитры, preview
        for key in keys:
            print(key)
            for w, h in ((1500, 1000), (390, 844)):
                ctx = new_ctx(w, h); pg, resp, errs = open_page(ctx, key)
                if resp.status != 200: bad(f'{key} {w}px: статус {resp.status}')
                if pg.evaluate('document.documentElement.dataset.v') != key and key != 'studio': bad(f'{key} {w}px: data-v={pg.evaluate("document.documentElement.dataset.v")}')
                if errs: bad(f'{key} {w}px: ошибки JS {errs[:2]}')
                if pg.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth + 1'): bad(f'{key} {w}px: горизонтальный скролл')
                if w == 1500 and any(c['name'] == 'ui' for c in ctx.cookies()): bad(f'{key}: ?preview=1 поставил cookie ui')
                ctx.close()
            for pal in PALS:
                ctx = new_ctx(1500, 1000, pal); pg, resp, errs = open_page(ctx, key, 3500)
                cr = pg.evaluate(CONTRAST_JS, SEL)
                low = {k: v for k, v in cr.items() if v is not None and v < 3}
                if low: bad(f'{key}/{pal}: низкий контраст {low}')
                ctx.close()

        # 4. «плюшки»
        def strip_val(pg, k='nar'):
            return pg.evaluate("(k)=>{const e=document.querySelector('.strip .cpm-campus-vol')||document.querySelector('input[id^=vol-]'); return e?+e.value:null}", k)

        if not a.only or 'rotor' in keys:
            print('rotor: перетаскивание / колёсико / стрелки')
            ctx = new_ctx(1500, 1000); pg, _, _ = open_page(ctx, 'rotor')
            d = pg.query_selector('.strip .dial')
            if not d: bad('rotor: нет .dial')
            else:
                inp = pg.query_selector('.strip input[id^=vol-]'); v0 = float(inp.input_value()); n0 = len(posts)
                bx = d.bounding_box(); cx, cy = bx['x'] + bx['width'] / 2, bx['y'] + bx['height'] / 2
                pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx, cy - 30, steps=5); pg.mouse.up(); pg.wait_for_timeout(600)
                v1 = float(inp.input_value())
                if not (v1 > v0): bad(f'dial: перетаскивание вверх не подняло громкость ({v0}→{v1})')
                d.focus(); pg.keyboard.press('ArrowDown'); pg.wait_for_timeout(500); v2 = float(inp.input_value())
                if not (v2 < v1): bad(f'dial: стрелка вниз не снизила ({v1}→{v2})')
                pg.mouse.move(cx, cy); pg.mouse.wheel(0, -100); pg.wait_for_timeout(900); v3 = float(inp.input_value())
                if not (v3 > v2): bad(f'dial: колёсико вверх не подняло ({v2}→{v3})')
                if len(posts) == n0: bad('rotor: изменения не ушли в /api (ожидался POST)')
                print(f'  громкость {v0}→{v1}→{v2}→{v3}, POST-ов: {len(posts) - n0}')
            ctx.close()

        for key, pre in (('ice', False), ('alu', True), ('walnut', True)):
            if a.only and key not in keys: continue
            print(f'{key}: кнопки −/+' + (' и пресеты' if pre else ''))
            ctx = new_ctx(1500, 1000); pg, _, _ = open_page(ctx, key)
            inp = pg.query_selector('.strip input[id^=vol-]'); v0 = float(inp.input_value())
            btns = pg.query_selector_all('.strip .qk button.st')
            if len(btns) < 2: bad(f'{key}: нет кнопок −/+')
            else:
                btns[1].click(); pg.wait_for_timeout(500); v1 = float(inp.input_value())
                if v1 != min(160, v0 + 5): bad(f'{key}: «+» дал {v0}→{v1}, ожидалось +5')
                btns[0].click(); pg.wait_for_timeout(500); v2 = float(inp.input_value())
                if v2 != v0: bad(f'{key}: «−» вернул {v2}, ожидалось {v0}')
            if pre:
                for target in (50, 130):
                    pg.click(f'.strip .qk button.pre:text-is("{target}")'); pg.wait_for_timeout(500)
                    if float(inp.input_value()) != target: bad(f'{key}: пресет {target} не применился ({inp.input_value()})')
                pg.wait_for_timeout(500)
                if not pg.query_selector('.strip .qk button.pre.on'): bad(f'{key}: активный пресет не подсвечен')
            ctx.close()
        if not a.only or 'emerald' in keys:
            print('emerald: пиковые огоньки')
            ctx = new_ctx(1500, 1000); pg, _, _ = open_page(ctx, 'emerald', 3000)
            pg.evaluate("document.querySelectorAll('.strip')[0].dataset.state='playing'")   # уровни в плеере «играют» по имитации, огонёк пика должен появиться
            found = False
            for _ in range(40):
                pg.wait_for_timeout(100)
                if pg.query_selector('.strip .vu i.pk'): found = True; break
            if not found: bad('emerald: пиковый огонёк не появился за 4 с')
            ctx.close()
        b.close()
    print(f'\nПОЛОМОК: {len(fails)}' if fails else '\nВСЁ В ПОРЯДКЕ')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
