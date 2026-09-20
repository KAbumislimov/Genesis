#!/usr/bin/env python3
"""Генератор 10 вариантов в стиле «Пульта» (/v4): webui/static/v10.css … v19.css.

Все варианты — та же микшерная консоль (разметка player_v4.html, каркас и размеры из v4.css, который подключается первым),
меняются материал корпуса, цвет экрана и светодиодов, клавиши, колпачки фейдеров и «плюшки» (webui/static/console-extras.js).
Запуск:  python3 scripts/make_pult_skins.py   — перезаписывает v10..v19.css и печатает список для проверки.
Метаданные вариантов (SKINS) использует и scripts/patch_pult_registry.py (реестр в app.py, переводы).
"""
import os
from string import Template

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'webui', 'static')

# Пульт по умолчанию (значения как в v4.css) — варианты переопределяют только нужное.
D = dict(
    ink='#131418', ink2='#1a1c21', ink3='#22252c', tx='#e9e7e0', tx2='#9d9c96', tx3='#66655f',
    line='rgba(255,255,255,.07)', line2='rgba(255,255,255,.13)',
    a='#ffb000', a2='#ff7a00', a_ink='#1a1100',
    m_bg='linear-gradient(180deg,#2b2e36,#1e2026)', m_bd='#3a3e48',
    m_sh='inset 0 1px 0 rgba(255,255,255,.1), inset 0 -3px 0 rgba(0,0,0,.45), 0 30px 70px rgba(0,0,0,.5)',
    scr='#07080a', scr_ring='#2c2f37',
    k_bg='linear-gradient(180deg,#3d414b,#282b32)', k_edge='#0d0e11', k_bd='#000', k_ink='#d9d7d0', k_hi='rgba(255,255,255,.2)', k_em='#08090b',
    pad_hov='linear-gradient(180deg,#464a55,#2e3138)', sel_ink='var(--tx2)',
    knob_bg='conic-gradient(from 0deg,#464a55,#24272e,#464a55,#24272e,#464a55)', kn_bd='#0b0c0e', kn_bez='#17181c', kn_bez2='#363a44',
    es_ring='#f2c200', es_bez='#1b1c20', es_edge='#4a0508',
    tray='#0e0f12', tray_ring='#23262d',
    s_bg='linear-gradient(180deg,#2c2f38,#21232a)', s_bd='#000', s_hi='rgba(255,255,255,.09)',
    lcd='#06070a', lcd_ring='#272a32', vu_off='#1a1c21', trk='#040405', trk_ring='#2c2f37',
    thumb='linear-gradient(#22242a,#22242a) center/100% 2px no-repeat, linear-gradient(180deg,#eceae4,#a3a29b 48%,#cfcec7 52%,#8c8b85)',
    pl_bg='linear-gradient(180deg,#e9e5d6,#cdc8b6)', pl_ink='#17181c',
    r_bg='linear-gradient(180deg,#2d3038,#21232a)', r_edge='#0b0c0e',
    lib='#14161a', libf='#0e0f12', libt='var(--tx)',
    bodybg='var(--ink) repeating-linear-gradient(90deg,rgba(255,255,255,.014) 0 1px,transparent 1px 3px)', rail='#16171b',
    paper='#e6e2d8', light=False, extra='',
)

CARBON = ('linear-gradient(27deg,#151515 5px,transparent 5px) 0 5px/20px 20px, linear-gradient(207deg,#151515 5px,transparent 5px) 10px 0/20px 20px, '
          'linear-gradient(27deg,#222 5px,transparent 5px) 0 10px/20px 20px, linear-gradient(207deg,#222 5px,transparent 5px) 10px 5px/20px 20px, '
          'linear-gradient(90deg,#1b1b1b 10px,transparent 10px) 0 0/20px 20px, linear-gradient(#1d1d1d 25%,#1a1a1a 25%,#1a1a1a 50%,transparent 50%,transparent 75%,#242424 75%,#242424) 0 0/20px 20px #131313')

SKINS = [
    dict(key='emerald', num=10, name='Изумруд', feat=['peak'],
         desc='Зелёный фосфорный экран, как у старой ЭЛТ-техники: строки развёртки, мерцание, зелёные светодиоды. Пиковые огоньки на уровнях.',
         tags=['Фосфорный экран', 'Пик-индикаторы'], demo=['#16211c', '#4dff9a', '#0b120e'],
         p=dict(ink='#0f1512', ink2='#151d19', ink3='#1c2621', tx='#e3ede7', tx2='#8fa398', tx3='#5d6e64',
                a='#4dff9a', a2='#12d67a', a_ink='#03210f',
                m_bg='linear-gradient(180deg,#26332c,#18211c)', m_bd='#34473c', scr='radial-gradient(120% 90% at 50% 40%,#0c2a1a,#03100a 75%)', scr_ring='#2b3d33',
                k_bg='linear-gradient(180deg,#3a4a41,#25312a)', k_edge='#0a100c', s_bg='linear-gradient(180deg,#27332c,#1d2622)', tray='#0b110e', tray_ring='#1f2b25',
                lcd='#04100a', lcd_ring='#233a2c', bodybg='var(--ink) repeating-linear-gradient(90deg,rgba(120,255,180,.018) 0 1px,transparent 1px 3px)', rail='#121a16'),
         extra="""
$P .c4-screen::after{ background:repeating-linear-gradient(0deg,rgba(0,0,0,.30) 0 1px,transparent 1px 3px), radial-gradient(ellipse at center,transparent 55%,rgba(0,0,0,.6)); }
$P .c4-track, $P .c4-time span{ animation:crtflick 6s steps(1) infinite; }
@keyframes crtflick{ 0%,92%,100%{ opacity:1 } 93%{ opacity:.84 } 95%{ opacity:.96 } 97%{ opacity:.9 } }
@media (prefers-reduced-motion:reduce){ $P .c4-track, $P .c4-time span{ animation:none; } }
"""),
    dict(key='ice', num=11, name='Лёд', feat=['trim'],
         desc='Холодная голубая сталь, серебристые клавиши, бирюзовый экран с бликом. Кнопки «−/+» для точной подстройки громкости каждого канала.',
         tags=['Стальной корпус', 'Точная подстройка −/+'], demo=['#2a3442', '#5ee6ff', '#dbe6f0'],
         p=dict(ink='#10151b', ink2='#171d25', ink3='#1f2731', tx='#e6eef5', tx2='#93a4b4', tx3='#5f7080',
                a='#5ee6ff', a2='#2fa8ff', a_ink='#031b24',
                m_bg='linear-gradient(180deg,#34414f,#222c37)', m_bd='#48586a', scr='#050b10', scr_ring='#33465a',
                k_bg='linear-gradient(180deg,#f0f5fa,#aab9c8)', k_edge='#2a3542', k_ink='#1c2733', k_hi='rgba(255,255,255,.7)', k_em='#0a1218',
                pad_hov='linear-gradient(180deg,#ffffff,#b9c6d3)', knob_bg='conic-gradient(from 0deg,#dfe8f1,#8ea0b3,#dfe8f1,#8ea0b3,#dfe8f1)',
                kn_bez='#1a222b', kn_bez2='#4a5a6b', s_bg='linear-gradient(180deg,#354250,#27313c)', tray='#0c1218', tray_ring='#233040',
                lcd='#050b10', lcd_ring='#2a3b4d', sel_ink='#1c2733', rail='#141b22', pl_bg='linear-gradient(180deg,#eef3f8,#c4d0dc)',
                bodybg='var(--ink) repeating-linear-gradient(90deg,rgba(140,200,255,.02) 0 1px,transparent 1px 3px)'),
         extra="""
$P .c4-master::before{ content:''; position:absolute; inset:0; border-radius:inherit; pointer-events:none; background:linear-gradient(115deg,transparent 28%,rgba(190,235,255,.10) 44%,transparent 60%); }
$P .c4 .strip-sel{ background:linear-gradient(180deg,#f0f5fa,#aab9c8); }
"""),
    dict(key='crimson', num=12, name='Кармин', feat=['lvl'],
         desc='Тёмно-красный корпус, красный экран и огромная вывеска «В ЭФИРЕ»: корпус светится сильнее, когда звук громче.',
         tags=['Вывеска «В эфире»', 'Свечение в такт звуку'], demo=['#3a1518', '#ff4b55', '#120507'],
         p=dict(ink='#150b0c', ink2='#1e1012', ink3='#291619', tx='#f3e6e6', tx2='#b49a9c', tx3='#7a6062',
                a='#ff4b55', a2='#ff8a3d', a_ink='#2a0508',
                m_bg='linear-gradient(180deg,#3d1a1e,#26100f)', m_bd='#5a2a2e', scr='#0a0304', scr_ring='#4a2226',
                k_bg='linear-gradient(180deg,#4a2a2e,#2e181b)', k_edge='#0e0405', s_bg='linear-gradient(180deg,#3a1d20,#2a1416)', tray='#100607', tray_ring='#2c1417',
                lcd='#0a0304', lcd_ring='#3c1c20', thumb='linear-gradient(#ff4b55,#ff4b55) center/100% 2px no-repeat, linear-gradient(180deg,#3a3a3e,#131316 50%,#2a2a2e)',
                vu_off='#26141a', rail='#1a0d0f', bodybg='var(--ink) repeating-linear-gradient(90deg,rgba(255,120,120,.016) 0 1px,transparent 1px 3px)'),
         extra="""
$P .c4-master{ box-shadow:inset 0 1px 0 rgba(255,255,255,.1), inset 0 -3px 0 rgba(0,0,0,.45), 0 30px 70px rgba(0,0,0,.5), 0 0 calc(8px + var(--lvl,0) * 80px) rgba(255,59,71,calc(.10 + var(--lvl,0) * .5)); transition:box-shadow .25s; }
$P .c4 .c4-led-tag{ padding:6px 16px; border:2px solid rgba(255,75,85,.35); border-radius:6px; font-size:17px; letter-spacing:.32em; background:rgba(255,59,71,.06); }
$P .c4-master.is-playing .c4-led-tag{ border-color:var(--a); box-shadow:0 0 calc(6px + var(--lvl,0) * 40px) var(--a), inset 0 0 14px rgba(255,59,71,.25); text-shadow:0 0 12px var(--a); }
$P .c4 .strip[data-state="playing"]{ box-shadow:inset 0 1px 0 rgba(255,255,255,.09), 0 0 calc(4px + var(--slvl,0) * 34px) color-mix(in srgb,var(--row-accent) 70%,transparent); }
"""),
    dict(key='alu', num=13, name='Алюминий', feat=['presets'],
         desc='Светлый шлифованный алюминий, чёрные клавиши и колпачки, бумажные шильдики каналов. Кнопки-пресеты громкости 50/100/130/150.',
         tags=['Светлый корпус', 'Пресеты громкости'], demo=['#cfd3d9', '#ffb000', '#1c1e22'], light=True, paper='#d4d7dc',
         p=dict(ink='#d4d7dc', ink2='#e6e8ec', ink3='#eff0f3', tx='#1a1c20', tx2='#4b505a', tx3='#7a808c', line='rgba(0,0,0,.10)', line2='rgba(0,0,0,.18)',
                m_bg='repeating-linear-gradient(90deg,rgba(255,255,255,.22) 0 1px,rgba(0,0,0,.025) 1px 3px), linear-gradient(180deg,#e2e5ea,#b9bec7)', m_bd='#9aa0aa',
                m_sh='inset 0 1px 0 #fff, inset 0 -3px 0 rgba(0,0,0,.18), 0 26px 50px rgba(40,46,60,.28)',
                k_bg='linear-gradient(180deg,#43464e,#23252b)', k_edge='#0d0e11', k_ink='#e6e4dc', pad_hov='linear-gradient(180deg,#52565f,#2b2d34)',
                knob_bg='conic-gradient(from 0deg,#4a4d56,#1f2126,#4a4d56,#1f2126,#4a4d56)', kn_bez='#c9cdd4', kn_bez2='#8d939d',
                es_bez='#b5bac2', tray='#9da2ab', tray_ring='#868b95',
                s_bg='repeating-linear-gradient(90deg,rgba(255,255,255,.2) 0 1px,rgba(0,0,0,.02) 1px 3px), linear-gradient(180deg,#dfe2e7,#c3c8cf)', s_bd='#8b919b', s_hi='rgba(255,255,255,.8)',
                vu_off='#2a2c33', thumb='linear-gradient(#f2f0e8,#f2f0e8) center/100% 2px no-repeat, linear-gradient(180deg,#54575f,#1c1e23 50%,#33353b)',
                pl_bg='#fbfaf5', pl_ink='#15161a', r_bg='linear-gradient(180deg,#43464e,#2a2c33)', sel_ink='#e6e4dc', rail='#c5c9d0',
                lib='#e7e9ed', libf='#d5d8de', bodybg='#d4d7dc'),
         extra="""
$P .c4 .strip{ box-shadow:inset 0 1px 0 rgba(255,255,255,.8), 0 6px 14px rgba(40,46,60,.22); }
$P .c4 .strip-plate{ font-family:'Caveat','Oswald',cursive; box-shadow:inset 0 0 0 1px rgba(0,0,0,.12), 0 1px 2px rgba(0,0,0,.25); }
$P .c4 .strip-plate .cpm-campus-name{ font-family:'Oswald',sans-serif; }
$P .c4 .cnt, $P .c4 .strip-lcd, $P .c4 .cpm-campus-vol-val{ color:var(--a); }
$P .c4 .strip-sel{ color:#e6e4dc; }
$P .c4-rockers{ background:#a9aeb7; box-shadow:inset 0 0 0 2px #8b919b; }
$P .c4 .rocker{ color:#e6e4dc; }
$P .c4 .pad{ color:#e6e4dc; }
$P .c4 .scale{ color:#4b505a; }
"""),
    dict(key='walnut', num=14, name='Орех', feat=['presets'],
         desc='Винтажная консоль: боковины из ореха, латунные винты, тёплый янтарный экран. Пресеты громкости 50/100/130/150 под каждым фейдером.',
         tags=['Деревянные боковины', 'Пресеты громкости'], demo=['#5a3218', '#ffb000', '#1c1612'],
         p=dict(ink='#17110d', ink2='#1f1712', ink3='#2a1f18', tx='#eee4d6', tx2='#a89882', tx3='#6f6252',
                a='#ffb43a', a2='#ff8a1f', a_ink='#1f1200',
                m_bg=('repeating-linear-gradient(0deg,rgba(0,0,0,.20) 0 1px,transparent 1px 5px) left/22px 100% no-repeat, repeating-linear-gradient(0deg,rgba(0,0,0,.20) 0 1px,transparent 1px 5px) right/22px 100% no-repeat, '
                      'linear-gradient(90deg,#8a5528,#6a3c1a 60%,#5a3218) left/22px 100% no-repeat, linear-gradient(270deg,#8a5528,#6a3c1a 60%,#5a3218) right/22px 100% no-repeat, linear-gradient(180deg,#2b2621,#1c1814)'),
                m_bd='#3a2a1c', k_bg='linear-gradient(180deg,#4a4038,#2c2520)', k_edge='#0d0a08', s_bg='linear-gradient(180deg,#2f2924,#221d19)', tray='repeating-linear-gradient(0deg,rgba(0,0,0,.2) 0 1px,transparent 1px 5px) left/18px 100% no-repeat, repeating-linear-gradient(0deg,rgba(0,0,0,.2) 0 1px,transparent 1px 5px) right/18px 100% no-repeat, linear-gradient(90deg,#7a4a24,#5a3218) left/18px 100% no-repeat, linear-gradient(270deg,#7a4a24,#5a3218) right/18px 100% no-repeat, #0f0c0a',
                tray_ring='#2a2018', lcd='#070504', lcd_ring='#3a2c20', thumb='linear-gradient(#2a1c10,#2a1c10) center/100% 2px no-repeat, linear-gradient(180deg,#f1e2b8,#c79a4a 48%,#e3c884 52%,#a87c30)',
                rail='#150f0b', bodybg='var(--ink) repeating-linear-gradient(90deg,rgba(255,200,140,.014) 0 1px,transparent 1px 3px)'),
         extra="""
$P .c4-master{ padding-inline:52px; }
$P .c4-strips{ padding-inline:34px; }
$P .c4 .screw{ background:radial-gradient(circle at 35% 30%,#f5dca0,#a37a2c 65%); }
$P .c4-master .screw.tl{ left:34px; } $P .c4-master .screw.bl{ left:34px; } $P .c4-master .screw.tr{ right:34px; } $P .c4-master .screw.br{ right:34px; }
"""),
    dict(key='neve', num=15, name='Неве', feat=['trim', 'peak'],
         desc='Сине-серый корпус в духе студийных консолей: у каждого канала свой цветной колпачок фейдера. Точная подстройка «−/+» и пиковые огоньки.',
         tags=['Цветные колпачки', 'Пик-индикаторы', 'Точная подстройка −/+'], demo=['#5b6b7d', '#e8b40c', '#d8342c'],
         p=dict(ink='#161a20', ink2='#1e242c', ink3='#272f39', tx='#e8ecf1', tx2='#9aa6b4', tx3='#66727f',
                m_bg='linear-gradient(180deg,#5a6a7c,#3d4957)', m_bd='#6d7f93', m_sh='inset 0 1px 0 rgba(255,255,255,.22), inset 0 -3px 0 rgba(0,0,0,.35), 0 30px 70px rgba(0,0,0,.5)',
                k_bg='linear-gradient(180deg,#e9e5d6,#b7b19c)', k_edge='#2b3138', k_ink='#22262c', k_hi='rgba(255,255,255,.8)', pad_hov='linear-gradient(180deg,#f6f3e8,#c4bea8)',
                sel_ink='#22262c', knob_bg='conic-gradient(from 0deg,#e9e5d6,#a49e88,#e9e5d6,#a49e88,#e9e5d6)', kn_bez='#2a323c', kn_bez2='#7d8fa3',
                s_bg='linear-gradient(180deg,#4d5c6d,#3a4655)', s_bd='#1c222a', s_hi='rgba(255,255,255,.16)', tray='#232a33', tray_ring='#5a6a7c',
                lcd='#070a0e', lcd_ring='#3a4756', rail='#1a2028', thumb='linear-gradient(#f4f1e6,#f4f1e6) center/100% 2px no-repeat, linear-gradient(180deg,var(--cap,#d8342c),color-mix(in srgb,var(--cap,#d8342c) 55%,#000))',
                pl_bg='linear-gradient(180deg,#f3efe0,#d9d3bd)'),
         extra="""
$P .c4 .strip:nth-child(6n+1){ --cap:#d8342c; } $P .c4 .strip:nth-child(6n+2){ --cap:#2f6fd6; } $P .c4 .strip:nth-child(6n+3){ --cap:#2fa04a; }
$P .c4 .strip:nth-child(6n+4){ --cap:#e8b40c; } $P .c4 .strip:nth-child(6n+5){ --cap:#e8792c; } $P .c4 .strip:nth-child(6n){ --cap:#8a55c9; }
$P .c4 .strip::before{ content:''; position:absolute; left:10px; right:10px; top:0; height:4px; border-radius:0 0 3px 3px; background:var(--cap,transparent); }
$P .c4 .strip-sel{ background:linear-gradient(180deg,#e9e5d6,#b7b19c); }
"""),
    dict(key='rotor', num=16, name='Ротор', feat=['dial'],
         desc='Вместо фейдеров — рифлёные ручки со светодиодным кольцом у каждого кампуса: тяните вверх-вниз, крутите колёсиком, стрелками на клавиатуре.',
         tags=['Поворотные ручки', 'Колёсико и стрелки'], demo=['#2c2f38', '#ff8a3d', '#c9c6bd'],
         p=dict(a='#ff8a3d', a2='#ff5a1f', a_ink='#1f0d00', m_bg='linear-gradient(180deg,#30333b,#202329)',
                thumb='linear-gradient(#22242a,#22242a) center/100% 2px no-repeat, linear-gradient(180deg,#eceae4,#8c8b85)'),
         extra="""
$P .c4 .strip-mid{ align-items:center; }
$P .c4 .strip-mid .fader{ position:absolute; width:1px; height:1px; overflow:hidden; opacity:0; pointer-events:none; }
$P .c4 .strip-mid .scale{ display:none; }
$P .c4 .dial{ --pv:.6; position:relative; width:80px; height:80px; border-radius:50%; cursor:ns-resize; touch-action:none; outline:none; flex:none;
  background:repeating-conic-gradient(from 0deg,#4a4d56 0 4deg,#2a2c33 4deg 8deg); border:2px solid #0b0c0e;
  box-shadow:0 10px 18px rgba(0,0,0,.6), inset 0 2px 0 rgba(255,255,255,.22), 0 0 0 6px #17181c, 0 0 0 7px #3b3f49; }
$P .c4 .dial:focus-visible{ box-shadow:0 10px 18px rgba(0,0,0,.6), 0 0 0 6px #17181c, 0 0 0 8px var(--row-accent); }
$P .c4 .dial::before{ content:''; position:absolute; inset:14px; border-radius:50%; background:radial-gradient(circle at 35% 30%,#5b5f6a,#26282e 70%); box-shadow:inset 0 2px 0 rgba(255,255,255,.18), 0 2px 6px rgba(0,0,0,.6); }
$P .c4 .dial::after{ content:''; position:absolute; left:50%; top:5px; width:4px; height:15px; margin-left:-2px; border-radius:2px; background:var(--row-accent); box-shadow:0 0 9px var(--row-accent);
  transform-origin:50% 35px; transform:rotate(calc(-135deg + var(--pv) * 270deg)); }
$P .c4 .dial .ring{ position:absolute; inset:-15px; border-radius:50%; pointer-events:none;
  background:conic-gradient(from 225deg,var(--row-accent) calc(var(--pv) * 270deg),#1a1c21 calc(var(--pv) * 270deg) 270deg,transparent 270deg);
  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 6px),#000 calc(100% - 5px)); mask:radial-gradient(farthest-side,transparent calc(100% - 6px),#000 calc(100% - 5px)); filter:drop-shadow(0 0 4px color-mix(in srgb,var(--row-accent) 60%,transparent)); }
$P .c4 .dial .dv{ position:absolute; inset:0; display:grid; place-content:center; text-align:center; z-index:1; pointer-events:none; }
$P .c4 .dial .dv .n{ font:500 17px/1 var(--f-mono); color:var(--row-accent); } $P .c4 .dial .dv small{ font:600 8px var(--f-display); letter-spacing:.2em; color:var(--tx3); }
$P .c4 .strip-mid{ height:150px; }
"""),
    dict(key='carbon', num=17, name='Карбон', feat=['presets', 'peak'],
         desc='Карбоновое плетение, оранжевые акценты и чёрные клавиши: гоночный характер. Пресеты громкости и пиковые индикаторы.',
         tags=['Карбон', 'Пресеты громкости', 'Пик-индикаторы'], demo=['#1b1b1b', '#ff5a1f', '#c9c9c9'],
         p=dict(ink='#0f0f10', ink2='#161617', ink3='#1e1e20', tx='#ececec', tx2='#9a9a9e', tx3='#66666a',
                a='#ff5a1f', a2='#ff9a3d', a_ink='#200a00', m_bg=CARBON, m_bd='#3a3a3e',
                m_sh='inset 0 2px 0 #ff5a1f, inset 0 -3px 0 rgba(0,0,0,.5), 0 30px 70px rgba(0,0,0,.6)',
                s_bg=CARBON, k_bg='linear-gradient(180deg,#2a2a2d,#141416)', k_edge='#050506', k_ink='#ececec', k_hi='rgba(255,255,255,.14)',
                pad_hov='linear-gradient(180deg,#38383c,#1a1a1d)', tray='#0a0a0b', tray_ring='#232326', rail='#111112', lcd='#050506', lcd_ring='#2a2a2e',
                bodybg='var(--ink)', es_ring='#ff5a1f', thumb='linear-gradient(#ff5a1f,#ff5a1f) center/100% 2px no-repeat, linear-gradient(180deg,#3a3a3e,#131316 50%,#2a2a2e)'),
         extra="""
$P .c4 .strip{ background:linear-gradient(180deg,rgba(0,0,0,.05),rgba(0,0,0,.35)), $s_bg_raw; }
$P .c4 .strip[data-state="playing"]{ box-shadow:0 0 0 1px var(--row-accent), 0 8px 18px rgba(0,0,0,.5); }
"""),
    dict(key='night', num=18, name='Ночь', feat=['peak'],
         desc='Ночной режим для вечерних смен: приглушённые красно-бурые тона, минимум яркости и бликов, глаза не устают. Пиковые огоньки на уровнях.',
         tags=['Приглушённый свет', 'Пик-индикаторы'], demo=['#1c1210', '#d94a3a', '#0a0605'],
         p=dict(ink='#0c0807', ink2='#120c0a', ink3='#1a110e', tx='#d9c9c2', tx2='#8c766e', tx3='#5a4842', line='rgba(255,140,120,.06)', line2='rgba(255,140,120,.11)',
                a='#d94a3a', a2='#b8321f', a_ink='#1a0503', m_bg='linear-gradient(180deg,#1f1512,#150d0b)', m_bd='#2e1f1a', m_sh='inset 0 1px 0 rgba(255,180,160,.06), inset 0 -3px 0 rgba(0,0,0,.5), 0 30px 70px rgba(0,0,0,.55)',
                scr='#050302', scr_ring='#2a1b16', k_bg='linear-gradient(180deg,#2b1f1b,#1a110e)', k_edge='#070403', k_ink='#c7b3ab', k_hi='rgba(255,180,160,.08)', pad_hov='linear-gradient(180deg,#34251f,#1e1512)',
                knob_bg='conic-gradient(from 0deg,#33241f,#1a110e,#33241f,#1a110e,#33241f)', kn_bez='#120c0a', kn_bez2='#2e1f1a', es_ring='#8a5a1a', es_bez='#120c0a',
                tray='#080504', tray_ring='#1c120e', s_bg='linear-gradient(180deg,#21160f,#180f0c)', lcd='#040201', lcd_ring='#241611', vu_off='#160e0b',
                thumb='linear-gradient(#150c08,#150c08) center/100% 2px no-repeat, linear-gradient(180deg,#b8a49b,#7d6b63 48%,#a3908a 52%,#6a5a53)',
                pl_bg='linear-gradient(180deg,#c8b8a8,#a49482)', r_bg='linear-gradient(180deg,#22160f,#170f0c)', lib='#0f0a08', libf='#0a0605', rail='#0e0908',
                bodybg='var(--ink)'),
         extra="""
$P .c4 .c4-viz{ filter:none; opacity:.8; }
$P .c4-track, $P .c4-time span, $P .c4-clock, $P .c4 .cnt b{ text-shadow:none; }
$P .c4 .vu i.lit, $P .c4 .vu i.lit:nth-child(n+7), $P .c4 .vu i.lit:nth-child(n+9){ box-shadow:none; }
"""),
    dict(key='synth', num=19, name='Синт', feat=['trim'],
         desc='Тёплая кремовая панель винтажного синтезатора с цветной полосой, шоколадные клавиши и «−/+» для подстройки громкости.',
         tags=['Кремовая панель', 'Цветная полоса', 'Точная подстройка −/+'], demo=['#e2d6b8', '#e8542c', '#3b2e24'], light=True, paper='#d9cdb0',
         p=dict(ink='#d9cdb0', ink2='#ebe1c8', ink3='#f3ecd8', tx='#2a2118', tx2='#5c4e3e', tx3='#8a7a66', line='rgba(60,40,20,.12)', line2='rgba(60,40,20,.2)',
                a='#ff9a1f', a2='#e8542c', a_ink='#2a1200', m_bg='linear-gradient(180deg,#eadfc4,#cfc09c)', m_bd='#a99a78',
                m_sh='inset 0 1px 0 rgba(255,255,255,.7), inset 0 -3px 0 rgba(90,60,20,.25), 0 26px 50px rgba(70,50,20,.3)',
                scr='#0a0805', scr_ring='#6b5a3e', k_bg='linear-gradient(180deg,#5a4536,#332619)', k_edge='#150e08', k_ink='#f0e4cc', pad_hov='linear-gradient(180deg,#6a5343,#3d2e20)',
                knob_bg='conic-gradient(from 0deg,#5a4536,#2a1f15,#5a4536,#2a1f15,#5a4536)', kn_bez='#c9bb98', kn_bez2='#a08e68', es_bez='#b8a980',
                tray='#b5a680', tray_ring='#9a8a63', s_bg='linear-gradient(180deg,#e9debf,#d0c199)', s_bd='#a08f68', s_hi='rgba(255,255,255,.7)', vu_off='#332a20',
                thumb='linear-gradient(#f5ecd6,#f5ecd6) center/100% 2px no-repeat, linear-gradient(180deg,#e8542c,#b93a18 50%,#d24a24)',
                pl_bg='#fbf6e6', pl_ink='#2a2118', r_bg='linear-gradient(180deg,#5a4536,#3b2d20)', sel_ink='#f0e4cc', rail='#cfc3a3', lib='#eee4cc', libf='#dfd3b6', bodybg='#d9cdb0'),
         extra="""
$P .c4-master::after{ content:''; position:absolute; left:14px; right:14px; bottom:0; height:9px; border-radius:0 0 8px 8px; background:linear-gradient(90deg,#e8542c 0 25%,#f0a12e 25% 50%,#5c8f5a 50% 75%,#3b6e9c 75%); pointer-events:none; }
$P .c4-master{ padding-bottom:38px; }
$P .c4 .cnt, $P .c4 .strip-lcd, $P .c4 .cpm-campus-vol-val{ color:var(--a); }
$P .c4-rockers{ background:#b5a680; box-shadow:inset 0 0 0 2px #9a8a63; }
$P .c4 .rocker, $P .c4 .pad{ color:#f0e4cc; }
$P .c4 .scale{ color:#5c4e3e; }
"""),
]

LIGHT_MARK_A = 'html[data-v="lumen"]{ background:#eceef2 !important; }'
LIGHT_MARK_B = '/* ═══ Плеер «Свет» — под .c4'


def light_chrome(key, paper):
    """Общая «светлая» обвязка страницы (меню, всплывающие окна, скроллбары) — берётся из v7.css (вариант «Свет»)."""
    src = open(os.path.join(STATIC, 'v7.css'), encoding='utf-8').read()
    a, b = src.index(LIGHT_MARK_A), src.index(LIGHT_MARK_B)
    blk = src[a:b].replace('[data-v="lumen"]', f'[data-v="{key}"]').replace('#eceef2', paper)
    return blk


TEMPLATE = Template(r"""/* ═══ «Пульт · $name» — вариант в стиле Пульта (/v4). Сгенерировано scripts/make_pult_skins.py, руками не править ═══
   Каркас и размеры — v4.css (подключается перед этим файлом); здесь материал корпуса, цвета и «плюшки». */
$P, $P[data-pal="aurora"], $P[data-pal="rose"]{
  --ink:$ink; --ink2:$ink2; --ink3:$ink3; --tx:$tx; --tx2:$tx2; --tx3:$tx3; --line:$line; --line2:$line2;
  --f-display:'Oswald','Onest',system-ui,sans-serif; --f-mono:'IBM Plex Mono',ui-monospace,monospace; --r-lg:14px; --r-md:10px; $scheme
}
$P, $P[data-pal="amber"]{ --a:$a; --a2:$a2; --a-ink:$a_ink; --sa:$a; --sa2:$a2; }
$P[data-pal="aurora"]{ --a:#39f28c; --a2:#12b5ff; --a-ink:#03210f; --sa:#39f28c; --sa2:#12b5ff; }
$P[data-pal="rose"]{ --a:#ff4f7a; --a2:#ff9a3d; --a-ink:#2a0410; --sa:#ff4f7a; --sa2:#ff9a3d; }
/* статус связи (data-fleet) красит клавиши, светодиод-табло и ободок стопа, но экран остаётся «фирменного» цвета варианта */
html[data-fleet]$P .c4-master .c4-screen{ --a:var(--sa); --a2:var(--sa2); }
$lightfix
$chrome
/* ── корпус ── */
$P .c4-master{ border-color:$m_bd; background:$m_bg; box-shadow:$m_sh; }
$P .c4-screen{ background:$scr; box-shadow:inset 0 0 0 2px $scr_ring, inset 0 10px 40px rgba(0,0,0,.85); }
$P .c4 .key{ background:$k_bg; color:$k_ink; border-color:$k_bd; box-shadow:0 5px 0 $k_edge, 0 9px 16px rgba(0,0,0,.5), inset 0 1px 0 $k_hi; }
$P .c4 .key:active{ box-shadow:0 1px 0 $k_edge, 0 2px 6px rgba(0,0,0,.5), inset 0 1px 0 $k_hi; }
$P .c4 .key em{ background:$k_em; }
$P .c4 .key.cpm-toggle.on{ background:$k_bg !important; color:var(--a) !important; border-color:$k_bd !important; box-shadow:0 5px 0 $k_edge, 0 9px 16px rgba(0,0,0,.5), inset 0 1px 0 $k_hi !important; }
$P .c4 .knob4{ background:$knob_bg; border-color:$kn_bd; box-shadow:0 12px 22px rgba(0,0,0,.6), inset 0 2px 0 rgba(255,255,255,.22), 0 0 0 7px $kn_bez, 0 0 0 8px $kn_bez2; }
$P .c4 .knob4:focus-visible{ box-shadow:0 12px 22px rgba(0,0,0,.6), 0 0 0 7px $kn_bez, 0 0 0 9px var(--a); }
$P .c4 .estop-cap{ border-color:$es_ring; box-shadow:0 9px 0 $es_edge, 0 16px 26px rgba(0,0,0,.6), inset 0 -7px 14px rgba(0,0,0,.35), 0 0 0 4px $es_bez; }
$P .c4 .estop:active .estop-cap{ box-shadow:0 2px 0 $es_edge, 0 4px 10px rgba(0,0,0,.6), inset 0 -7px 14px rgba(0,0,0,.35), 0 0 0 4px $es_bez; }
/* ── каналы ── */
$P .c4-strips{ background:$tray; box-shadow:inset 0 0 0 2px $tray_ring, inset 0 14px 40px rgba(0,0,0,.5); }
$P .c4 .strip{ background:$s_bg; border-color:$s_bd; box-shadow:inset 0 1px 0 $s_hi, 0 8px 18px rgba(0,0,0,.4); }
$P .c4 .strip.is-active{ box-shadow:inset 0 1px 0 $s_hi, 0 0 0 2px var(--row-accent), 0 0 34px color-mix(in srgb,var(--row-accent) 24%,transparent); }
$P .c4 .cnt, $P .c4 .strip-lcd, $P .c4 .cpm-campus-vol-val{ background:$lcd; box-shadow:inset 0 0 0 1px #000, inset 0 0 0 2px $lcd_ring; }
$P .c4 .vu i{ background:$vu_off; }
$P .c4 .cpm-campus-vol::-webkit-slider-runnable-track{ background:$trk; box-shadow:inset 0 1px 3px #000, 0 0 0 1px $trk_ring; }
$P .c4 .cpm-campus-vol::-webkit-slider-thumb{ background:$thumb; }
$P .c4 .cpm-campus-vol::-moz-range-track{ background:$trk; }
$P .c4 .strip-plate{ background:$pl_bg; } $P .c4 .strip-plate .cpm-campus-name{ color:$pl_ink; }
$P .c4 .strip-sel{ background:$k_bg; box-shadow:0 3px 0 $k_edge; color:$sel_ink; }
$P .c4 .strip.is-active .strip-sel{ color:var(--a-ink); background:linear-gradient(180deg,var(--a),var(--a2)); box-shadow:0 3px 0 rgba(0,0,0,.5), 0 0 18px color-mix(in srgb,var(--a) 45%,transparent); }
$P .c4 .pad{ background:$k_bg; box-shadow:0 6px 0 $k_edge, 0 11px 18px rgba(0,0,0,.45), inset 0 1px 0 $k_hi; }
$P .c4 .pad:hover{ background:$pad_hov; }
$P .c4 .pad:active{ box-shadow:0 1px 0 $k_edge, 0 2px 6px rgba(0,0,0,.5), inset 0 1px 0 $k_hi; }
$P .c4 .pad.danger{ background:repeating-linear-gradient(-45deg,#3c1519 0 12px,#2a0d10 12px 24px); }
$P .c4 .pad.danger, $P .c4 .pad.danger b{ color:#f3e6e6; }
$P .c4-rockers{ background:$tray; box-shadow:inset 0 0 0 2px $tray_ring; }
$P .c4 .rocker, $P .c4 .rocker.wa-toggle-btn[data-state]{ background:$r_bg; box-shadow:0 3px 0 $r_edge; }
$P .c4 .lib{ background:$lib; box-shadow:inset 0 0 0 2px $tray_ring; } $P .c4 .lib-folders, $P .c4 .search, $P .c4 .sel{ background-color:$libf; }
/* ── «плюшки»: пиковые огоньки, «−/+» и пресеты (console-extras.js) ── */
$P .c4 .vu i.pk.pk{ background:#fff; box-shadow:0 0 8px #fff, 0 0 2px #fff; }
$P .c4 .qk{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:4px; min-width:0; }
$P .c4 .qk button{ min-width:0; height:26px; padding:0; border-radius:5px; border:1px solid #000; background:$k_bg; color:$k_ink; font:600 10.5px var(--f-mono); cursor:pointer; box-shadow:0 3px 0 $k_edge, inset 0 1px 0 $k_hi; }
$P .c4 .qk button:active{ transform:translateY(2px); box-shadow:0 1px 0 $k_edge; }
$P .c4 .qk .pre{ order:1; } $P .c4 .qk .st{ order:2; grid-column:span 2; font-size:15px; } $P .c4 .qk .st:last-child{ order:3; }
$P .c4 .qk.only-trim{ grid-template-columns:1fr 1fr; } $P .c4 .qk.only-trim .st{ grid-column:auto; }
$P .c4 .qk button.on{ color:var(--a); box-shadow:0 3px 0 $k_edge, 0 0 10px color-mix(in srgb,var(--a) 50%,transparent), inset 0 1px 0 $k_hi; }
$extra
""")

CHROME_DARK = Template(r"""$P .aurora{ display:none; } $P .grain{ opacity:.09; }
html$P body{ background:$bodybg !important; }
$P .rail{ background:$rail; border-right-color:#000; box-shadow:inset -1px 0 0 rgba(255,255,255,.05); }
$P .topbar{ background:linear-gradient(var(--ink),color-mix(in srgb,var(--ink) 70%,transparent)); }
$P .rail-logo, $P .usr-av, $P .rail-a{ border-radius:8px; }
$P .sec-h h3{ letter-spacing:.14em; font-weight:500; } $P .sec-h h3 i{ border-radius:6px; }""")


def build(sk):
    p = dict(D); p.update(sk['p']); p['light'] = sk.get('light', False); p['paper'] = sk.get('paper', D['paper'])
    P = f'[data-v="{sk["key"]}"]'
    p['P'] = P; p['name'] = sk['name']; p['scheme'] = 'color-scheme:light;' if p['light'] else ''
    p['chrome'] = light_chrome(sk['key'], p['paper']) if p['light'] else CHROME_DARK.substitute(p)
    p['s_bg_raw'] = p['s_bg']
    p['lightfix'] = (f'html[data-fleet]{P} .c4-master #vol-num, html[data-fleet]{P} .c4-master .c4-vol span{{ color:var(--tx) !important; text-shadow:none !important; }}\n'
                     f'html[data-fleet]{P} .c4-master .c4-cap, html[data-fleet]{P} .c4-master .knob-ticks{{ color:var(--tx3); }}') if p['light'] else ''
    extra = Template(sk['extra']).safe_substitute(p)
    p['extra'] = extra
    return TEMPLATE.substitute(p)


def main():
    for sk in SKINS:
        css = build(sk)
        path = os.path.join(STATIC, f'v{sk["num"]}.css')
        open(path, 'w', encoding='utf-8').write(css)
        print(f'v{sk["num"]}.css  {sk["key"]:8s} {len(css)//1024} КБ')


if __name__ == '__main__':
    main()
