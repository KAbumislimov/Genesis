#!/usr/bin/env python3
"""Превью вариантов страницы входа для Настройки → «Стартовая страница входа» → webui/static/login-previews/<ключ>.jpg (480×300).
Запуск: python3 scripts/make_login_previews.py   (Playwright + Pillow; сервер должен быть доступен на https://127.0.0.1:8090)."""
import io
from PIL import Image
from playwright.sync_api import sync_playwright
OUT='/home/kamran/projects/campus-infra/webui/static/login-previews/'
keys=['classic']+[str(i) for i in range(1,20)]
wait={'classic':4500,'11':7600,'12':4200,'17':3000,'18':3000}
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1440,'height':900}, ignore_https_errors=True)
    ctx.add_init_script("localStorage.setItem('lang','ru'); localStorage.setItem('login_theme','dark')")
    for k in keys:
        pg=ctx.new_page(); pg.goto(f'https://127.0.0.1:8090/login?style={k}', wait_until='domcontentloaded')
        pg.add_style_tag(content='.pv{display:none!important}')
        pg.wait_for_timeout(wait.get(k,2600))
        if k=='12': pg.keyboard.press('Shift'); pg.wait_for_timeout(1400)     # показать форму без ожидания печати
        png=pg.screenshot(); pg.close()
        im=Image.open(io.BytesIO(png)).convert('RGB').resize((480,300),Image.LANCZOS)
        im.save(OUT+f'{k}.jpg','JPEG',quality=80,optimize=True)
    b.close()
import os; print(sorted(os.listdir(OUT))[:6], len(os.listdir(OUT)), 'файлов,', sum(os.path.getsize(OUT+f) for f in os.listdir(OUT))//1024, 'КБ')
