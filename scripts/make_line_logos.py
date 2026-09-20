#!/usr/bin/env python3
"""Контурные версии логотипов Media и LEG для страницы входа (тёмная тема).
Запуск из webui/static:  cd webui/static && python3 ../../scripts/make_line_logos.py   (нужны Pillow и numpy)
Из media.logo.t.png / leg.logo.t.png делает *.logo.tline[_b].png (на исходном холсте, для пазла) и *.logo.cropline[_b].png (без пустых полей):
внутренние «глазки» букв (D, A, O…) вырезаются (в исходнике они закрашены белым), тело букв перекрашивается, по краю всех фигур — белый контур.
_b — вариант со светлой сиренью. После смены файлов поднять ?v= в templates/login.html и login_alt.html. См. docs/UI-DESIGN.md."""
import numpy as np
from PIL import Image

def dilate(m, r):
    out = m.copy()
    for i in range(r):                       # чередуем «крест» и «квадрат» → почти круглый структурный элемент
        n = out.copy()
        for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)) + (((1,1),(1,-1),(-1,1),(-1,-1)) if i % 2 else ()):
            n |= np.roll(np.roll(out, dy, 0), dx, 1)
        out = n
    return out

def erode(m, r):
    return ~dilate(~m, r)

def make_line(src, dst, keep_rule, scale, r, out_scale=3, tint=(140, 165, 255, 78), dewhite=None, recolor=None, recolor_rgb=(28, 45, 55)):
    im = Image.open(src).convert('RGBA')
    big = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    a = np.array(big); alpha = a[..., 3] > 127
    if dewhite is not None:                      # внутренние «глазки» букв (D, A, O…) в исходнике закрашены непрозрачным белым — вырезаем
        white = (a[..., :3].min(axis=2) > 205) & alpha & dewhite(a, alpha)
        a[white, 3] = 0
        alpha = a[..., 3] > 127
    if recolor is not None:                      # буквы Media School — тот же тёмный цвет, что у букв LEG (#1c2d37), поверх белый контур
        rc = recolor(a, alpha) & alpha
        a[rc, 0], a[rc, 1], a[rc, 2] = recolor_rgb
    keep = keep_rule(a, alpha) & alpha           # закрашенные части (знак, синие планки) остаются как есть
    band = dilate(alpha, r) & ~erode(alpha, r)   # контур ~2r px вокруг границы каждой фигуры
    out = np.zeros_like(a)
    body = alpha & ~keep
    out[body] = tint                             # тело букв — полупрозрачная тонировка (не белая): буква читается как форма, а не как «дырка»
    out[keep] = a[keep]
    out[keep, 3] = 255
    out[band] = (255, 255, 255, 255)             # белая линия по контуру всех фигур
    res = Image.fromarray(out)
    res = res.resize((im.width * out_scale, im.height * out_scale), Image.LANCZOS)   # сглаживание краёв (без «зубцов»)
    res.save(dst, optimize=True)
    return out

def media_rule(a, alpha):
    cols = alpha.any(axis=0); xs = np.where(cols)[0]
    x0, x1 = xs.min(), xs.max()
    best, run, start = (0, 0), 0, None
    for x in range(x0, x1 + 1):                  # самый широкий пустой промежуток между знаком и текстом
        if not cols[x]:
            start = x if start is None else start
            if x - start + 1 > best[0]: best = (x - start + 1, start)
        else: start = None
    split = best[1] + best[0] // 2
    k = np.zeros(alpha.shape, bool); k[:, :split] = True
    return k

def leg_rule(a, alpha):
    r, g, b = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    return (b > 140) & (r < 110)                 # синие планки буквы E остаются синими

# Media: тонкая линия (~1.3 px на исходном холсте) — иначе в мелких внутренних просветах A, O, D остаются «дырки»
def all_rule(a, alpha):                          # 2026-09-20: буквы ЗАКРАШЕНЫ (родным цветом логотипа) + белый контур, без «пустых» букв
    return alpha
def media_text_only(a, alpha):                  # белое вырезаем только в тексте (правее знака), белые фигуры герба остаются
    return ~media_rule(a, alpha)
def leg_all(a, alpha):
    return np.ones(alpha.shape, bool)
def build(name, rule, sc, rr, dw, rcl, rgb, suffix):
    make_line(f'{name}.logo.t.png', f'{name}.logo.tline{suffix}.png', rule, sc, rr, dewhite=dw, recolor=rcl, recolor_rgb=rgb)
    im = Image.open(f'{name}.logo.tline{suffix}.png'); bb = im.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox(); pad = 10
    bb = (max(0, bb[0]-pad), max(0, bb[1]-pad), min(im.width, bb[2]+pad), min(im.height, bb[3]+pad))
    im.crop(bb).save(f'{name}.logo.cropline{suffix}.png', optimize=True)
    c = Image.open(f'{name}.logo.cropline{suffix}.png'); bg = Image.new('RGBA', (c.width + 40, c.height + 40), (8, 13, 24, 255)); bg.alpha_composite(c, (20, 20))
    bg.save(f'/tmp/line_{name}{suffix}.png')
    print(name, suffix or 'основной', c.size)

# Media: тело букв — родной фиолетовый (#36296e), контур крупнее (r=7), в варианте B — светлая сирень; «глазки» D/A/O прозрачные и обведены
build('media', all_rule, 6, 5, media_text_only, media_text_only, (54, 41, 110), '')
build('media', all_rule, 6, 5, media_text_only, media_text_only, (139, 127, 230), '_b')
def leg_letters(a, alpha):                       # тёмные буквы LEG (синие планки не трогаем)
    r, g, b = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    return ~((b > 140) & (r < 110))
# LEG: тело букв — тот же цвет, что у Media; контур той же ВИДИМОЙ толщины (картинка LEG в ~2.5 раза крупнее — r=11 вместо 5)
build('leg', all_rule, 6, 11, leg_all, leg_letters, (54, 41, 110), '')
build('leg', all_rule, 6, 11, leg_all, leg_letters, (139, 127, 230), '_b')
