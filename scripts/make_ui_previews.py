#!/usr/bin/env python3
"""Превью дизайнов плеера для Настроек → «Дизайн интерфейса» → webui/ui_previews/<ключ>.jpg.

Картинки приватные: на них видны названия кампусов, поэтому отдаются только вошедшим (маршрут /ui-preview/<ключ>.jpg),
а сама папка лежит вне static/. Все POST /api/* подменяются заглушкой — на боевые колонки ничего не уходит.

Запуск (нужен Playwright и cookie сессии администратора — в репозиторий её не кладём):
    python3 scripts/make_ui_previews.py --cookie-file /путь/cookie.txt [--only glass,oled] [--base https://127.0.0.1:8090]
После пересборки контейнера изменения подхватываются (папка копируется в образ вместе с webui/).
"""
import argparse, io, os, ssl, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'webui', 'ui_previews')
# ключ → (адрес страницы, cookie ui). Ключи совпадают с UI_VARIANT_INFO в webui/app.py.
PAGES = {
    'studio': '/v3', 'console': '/v4', 'bento': '/v5', 'neon': '/v6', 'lumen': '/v7', 'rack': '/v8', 'deck': '/v9',
    'glass': '/v10', 'rows': '/v11', 'dial': '/v12', 'oled': '/v13', 'soft': '/v14', 'onair': '/v15', 'compact': '/v16',
    'off': '/?classic=1', 'tabler': '/v2',
}
HIDE = '.bug-fab,#chat-widget,#chat-toggle,.fdock-master,.fdock-master-btn{display:none!important}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cookie-file', required=True)
    ap.add_argument('--base', default='https://127.0.0.1:8090')
    ap.add_argument('--only', default='')
    ap.add_argument('--wait', type=int, default=7000, help='мс ожидания после загрузки (статусы кампусов, визуализатор)')
    a = ap.parse_args()
    from PIL import Image
    from playwright.sync_api import sync_playwright
    cookie = open(a.cookie_file).read().strip()
    keys = [k for k in (a.only.split(',') if a.only else PAGES) if k in PAGES]
    ctx0 = ssl._create_unverified_context()
    for _ in range(40):                       # контейнер раз в час перезапускается — ждём страницу входа
        try:
            if urllib.request.urlopen(a.base + '/login', context=ctx0, timeout=3).status == 200:
                break
        except Exception:
            time.sleep(2)
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, ignore_https_errors=True)
        ctx.add_cookies([{'name': 'session', 'value': cookie, 'url': a.base}])
        ctx.add_init_script("localStorage.setItem('lang','ru');localStorage.setItem('v3pal','amber');")
        for k in keys:
            pg = ctx.new_page()
            pg.route(lambda u: '/api/' in u, lambda r, q: r.fulfill(status=200, content_type='application/json', body='{"ok":true}') if q.method == 'POST' else r.continue_())
            url = a.base + PAGES[k] + ('&' if '?' in PAGES[k] else '?') + 'preview=1'
            pg.goto(url, wait_until='domcontentloaded')
            pg.add_style_tag(content=HIDE)
            pg.wait_for_timeout(a.wait)
            im = Image.open(io.BytesIO(pg.screenshot())).convert('RGB').resize((640, 400), Image.LANCZOS)
            im.save(os.path.join(OUT, k + '.jpg'), 'JPEG', quality=80, optimize=True)
            pg.close()
            print('ok', k)
        b.close()


if __name__ == '__main__':
    sys.exit(main())
