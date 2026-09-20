/* ═══ Автоперевод интерфейса (RU → EN / AZ) ═══
   Работает поверх старого механизма (I18N + data-i18n): переводит весь остальной текст на странице —
   текстовые узлы, title/placeholder/aria-label, тексты, которые дорисовывает JS (тосты, статусы, меню),
   а также окна confirm/alert/prompt. Словарь — i18n-auto-dict.js.
   • точное совпадение фразы → перевод; иначе подстановка известных фраз, но только если после неё
     в строке не осталось кириллицы (так не портятся названия треков и пользовательские данные);
   • оригинал (русский) запоминается, поэтому переключение RU ⇄ EN ⇄ AZ работает в любую сторону. */
(function () {
  'use strict';
  var CYR = /[А-Яа-яЁё]/;
  var DICT = window.I18N_AUTO_DICT || [];
  var PATS = window.I18N_AUTO_PATS || [];
  var maps = { en: {}, az: {} }, rx = { en: null, az: null }, pfx = { en: [], az: [] };
  var LANGS = ['en', 'az'];

  function norm(s) { return s.replace(/\s+/g, ' ').trim().toLowerCase().replace(/ё/g, 'е'); }
  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&'); }

  function build() {
    var ru = (window.I18N && I18N.ru) || {};
    /* обратный словарь из старого I18N: русский текст → перевод по тому же ключу */
    Object.keys(ru).forEach(function (k) {
      var r = ru[k];
      if (typeof r !== 'string' || !CYR.test(r) || r.indexOf('<') > -1) return;
      LANGS.forEach(function (l) {
        var v = (I18N[l] || {})[k];
        var nk = norm(r);
        if (typeof v === 'string' && v && maps[l][nk] === undefined) maps[l][nk] = v;
      });
    });
    DICT.forEach(function (e) {
      LANGS.forEach(function (l, i) {
        if (e[i + 1] === undefined) return;
        var nk = norm(e[0]);
        maps[l][nk] = e[i + 1];
        if (e[3]) pfx[l].push({ k: e[0], v: e[i + 1] });
      });
    });
    LANGS.forEach(function (l) {
      var keys = Object.keys(maps[l]).filter(function (k) { return k.length >= 1 && CYR.test(k); });
      keys.sort(function (a, b) { return b.length - a.length; });
      pfx[l].sort(function (a, b) { return b.k.length - a.k.length; });
      rx[l] = keys.length ? new RegExp('(?<![А-Яа-яЁё])(?:' + keys.map(function (k) { return esc(k).replace(/е/g, '[её]'); }).join('|') + ')(?![А-Яа-яЁё])', 'gi') : null;
    });
  }

  /* регистр: ВСЕ КАПСОМ → ПЕРЕВОД КАПСОМ; со строчной → со строчной */
  function mc(src, out) {
    var letters = src.replace(/[^А-Яа-яЁёA-Za-z]/g, '');
    if (letters.length >= 2 && letters === letters.toUpperCase() && letters !== letters.toLowerCase()) return out.toUpperCase();
    var f = src.charAt(0), o = out.charAt(0);
    if (f && f === f.toLowerCase() && f !== f.toUpperCase() && o !== o.toLowerCase()) return o.toLowerCase() + out.slice(1);
    if (f && f === f.toUpperCase() && f !== f.toLowerCase() && o !== o.toUpperCase()) return o.toUpperCase() + out.slice(1);
    return out;
  }

  function translate(str, lang, exactOnly, depth) {
    if (lang === 'ru' || typeof str !== 'string' || !CYR.test(str)) return str;
    var m = maps[lang]; if (!m) return str;
    var lead = str.match(/^\s*/)[0], trail = str.match(/\s*$/)[0], core = str.trim();
    var k = norm(core);
    if (m[k] !== undefined) return lead + mc(core, m[k]) + trail;
    if (exactOnly) return str;
    depth = depth || 0;
    if (depth < 3) {
      for (var i = 0; i < PATS.length; i++) {
        var mm = core.match(PATS[i][0]);
        if (mm) {
          var res = PATS[i][1](lang, function (x) { return translate(x, lang, false, depth + 1); }, mm);
          if (res !== null && res !== undefined) return lead + res + trail;
        }
      }
    }
    if (rx[lang]) {
      var out = core.replace(rx[lang], function (mt) { var v = m[norm(mt)]; return v === undefined ? mt : mc(mt, v); });
      if (!CYR.test(out)) return lead + out + trail;
    }
    /* префиксные тосты: «✔ Папка создана: <имя>» — перевод только начала */
    var lowered = core.toLowerCase();
    for (var j = 0; j < pfx[lang].length; j++) {
      var p = pfx[lang][j];
      if (lowered.indexOf(p.k.toLowerCase()) === 0) return lead + p.v + core.slice(p.k.length) + trail;
    }
    return str;
  }

  /* ── DOM ── */
  var SKIP_TAG = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, CODE: 1, PRE: 1 };
  /* зоны с данными (названия треков, чаты, логи): только точное совпадение, без подстановки фраз */
  var DATA_SEL = '.wamp2-pnm,.cpm-campus-track,#wa-lcd-track,#wa-lcd-info,.chat-msg,.cm-txt,.notranslate,[data-i18n-exact],td.mono,.log-detail .val';
  var SKIP_SEL = '#pl-list,.wamp2-pl-list,[data-no-i18n],.notranslate-all';
  var tState = new WeakMap();     // текстовый узел → {src,out}
  var aState = new WeakMap();     // элемент → { attr: {src,out} }
  var ATTRS = ['title', 'placeholder', 'aria-label', 'alt'];

  function lang() { return (window.currentLang || localStorage.getItem('lang') || 'ru'); }

  function inSkip(el) { return el && el.closest && el.closest(SKIP_SEL); }

  function doText(node, L) {
    var p = node.parentElement;
    if (!p || SKIP_TAG[p.tagName] || inSkip(p)) return;
    var st = tState.get(node), cur = node.data, src;
    if (st && cur === st.out) src = st.src; else src = cur;
    if (!CYR.test(src)) { if (st && cur !== st.out) tState.delete(node); return; }
    var exact = !!(p.closest && p.closest(DATA_SEL));
    var out = L === 'ru' ? src : translate(src, L, exact);
    if (out !== cur) node.data = out;
    if (out !== src) tState.set(node, { src: src, out: out }); else tState.delete(node);
  }

  function doAttrs(el, L) {
    if (!el.getAttribute) return;
    var rec = aState.get(el);
    ATTRS.forEach(function (a) {
      var cur = el.getAttribute(a);
      if (cur === null) return;
      var st = rec && rec[a], src = (st && cur === st.out) ? st.src : cur;
      if (!CYR.test(src)) { if (st && cur !== st.out) delete rec[a]; return; }
      var exact = !!(el.closest && el.closest(DATA_SEL));
      var out = L === 'ru' ? src : translate(src, L, exact);
      if (out !== cur) el.setAttribute(a, out);
      if (out !== src) { rec = rec || {}; rec[a] = { src: src, out: out }; aState.set(el, rec); } else if (rec && rec[a]) delete rec[a];
    });
    if (el.tagName === 'INPUT' && (el.type === 'button' || el.type === 'submit') && CYR.test(el.value || '')) {
      var nv = translate(el.value, L); if (nv !== el.value) el.value = nv;
    }
  }

  /* строки плейлиста (1400+ штук) не обходим целиком — только их служебные подписи */
  var ROW_SEL = '.wamp2-pfol,.wamp2-pfav,.wamp2-pren,.wamp2-pmovebtn,.wamp2-psel,.wamp2-pmeta';
  function doRow(row, L) {
    if (row.nodeType !== 1) return;
    var list = row.matches && row.matches(ROW_SEL) ? [row] : [];
    if (row.querySelectorAll) list = list.concat(Array.prototype.slice.call(row.querySelectorAll(ROW_SEL)));
    list.forEach(function (el) { doAttrs(el, L); for (var c = el.firstChild; c; c = c.nextSibling) if (c.nodeType === 3) doTextForce(c, L); });
  }
  function doTextForce(node, L) {
    var st = tState.get(node), cur = node.data, src = (st && cur === st.out) ? st.src : cur;
    if (!CYR.test(src)) return;
    var out = L === 'ru' ? src : translate(src, L, true);
    if (out !== cur) node.data = out;
    if (out !== src) tState.set(node, { src: src, out: out }); else tState.delete(node);
  }

  function walk(root, L) {
    if (!root) return;
    if (root.nodeType === 3) { doText(root, L); return; }
    if (root.nodeType !== 1) return;
    if (root.matches && root.matches(SKIP_SEL)) { doRow(root, L); return; }
    if (inSkip(root)) { doRow(root, L); return; }
    if (root.tagName === 'TEXTAREA') { doAttrs(root, L); return; }
    if (SKIP_TAG[root.tagName]) return;
    doAttrs(root, L);
    for (var c = root.firstChild; c; c = c.nextSibling) walk(c, L);
  }

  var busy = false;
  function run(root) {
    var L = lang();
    busy = true;
    try {
      walk(root || document.body, L);
      if (!root || root === document.body) {
        if (document.__ruTitle === undefined || document.title !== document.__ruTitleOut) document.__ruTitle = document.title;
        var tt = translate(document.__ruTitle, L);
        document.__ruTitleOut = tt; if (document.title !== tt) document.title = tt;
      }
    } finally { busy = false; }
  }

  /* dialog-окна */
  ['alert', 'confirm', 'prompt'].forEach(function (n) {
    var orig = window[n];
    window[n] = function (msg, def) { return orig.call(window, translate(String(msg == null ? '' : msg), lang()), def); };
  });

  var pending = false, queue = [];
  function schedule(n) {
    queue.push(n);
    if (pending) return; pending = true;
    (window.requestAnimationFrame || setTimeout)(function () {
      pending = false; var q = queue; queue = [];
      var L = lang(); if (L === 'ru') return;
      busy = true;
      try { q.forEach(function (x) { if (x.isConnected !== false) walk(x, L); }); } finally { busy = false; }
    });
  }

  function start() {
    build();
    run();
    var mo = new MutationObserver(function (list) {
      if (busy || lang() === 'ru') return;
      list.forEach(function (r) {
        if (r.type === 'childList') r.addedNodes.forEach(function (n) { schedule(n); });
        else if (r.type === 'characterData') { var st = tState.get(r.target); if (!st || r.target.data !== st.out) schedule(r.target); }
        else if (r.type === 'attributes') schedule(r.target);
      });
    });
    mo.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }

  /* после штатного applyLang() (он выставляет data-i18n) прогоняем автоперевод */
  var origApply = window.applyLang;
  window.applyLang = function () { if (origApply) origApply.apply(this, arguments); if (rx.en) run(); };
  window.autoTranslate = function (s, l) { return translate(s, l || lang()); };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
