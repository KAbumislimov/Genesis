/* «Плюшки» вариантов в стиле Пульта (emerald, ice, crimson, alu, walnut, neve, rotor, carbon, night, synth).
   Работает поверх общей логики плеера: все действия — это события input/change на существующих ползунках громкости #vol-<ключ>,
   поэтому запросы, удержание значения, фиксация громкости и переводы работают как у обычного фейдера.
     lvl      — уровень звука 0…1 в CSS-переменной --lvl (свечение корпуса, вывеска) и --slvl у каждого канала
     peak     — пиковые огоньки: самый высокий загоревшийся сегмент уровня держится ~1,2 с и плавно падает
     trim     — кнопки «−/+» (±5) у каждого канала
     presets  — пресеты 50/100/130/150 и «−/+» у каждого канала
     dial     — поворотные ручки вместо фейдеров (тянуть вверх/вниз, колёсико, стрелки)                                            */
(function () {
  var root = document.documentElement, V = root.dataset.v;
  var FEAT = { emerald: ['peak'], ice: ['trim'], crimson: ['lvl'], alu: ['presets'], walnut: ['presets'], neve: ['trim', 'peak'],
               rotor: ['dial'], carbon: ['presets', 'peak'], night: ['peak'], synth: ['trim'] }[V];
  if (!FEAT) return;
  var has = function (f) { return FEAT.indexOf(f) !== -1; };
  var clamp = function (v) { return Math.max(0, Math.min(160, Math.round(v))); };
  var inp = function (key) { return document.getElementById('vol-' + key); };

  /* задать громкость канала так же, как это делает пользователь (input → обновление подписи, change → отправка) */
  function setVol(key, v, commit) {
    var el = inp(key); if (!el) return;
    v = clamp(v);
    if (+el.value !== v) { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); }
    if (commit) el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  /* ── lvl: уровень звука ── */
  if (has('lvl')) {
    var cur = 0, sl = {}, last = -1;
    var level = function (d) {
      if (!d || !d.active || !d.bands || !d.bands.length) return 0;
      var s = 0; d.bands.forEach(function (b) { s += b; });
      return Math.min(1, (s / d.bands.length) * (5.5 / 255));
    };
    setInterval(function () {
      var mx = 0, playing = false;
      document.querySelectorAll('.strip').forEach(function (st) {
        var k = st.dataset.key, real = level(window._audioSSE && window._audioSSE[k]);
        var isPl = st.dataset.state === 'playing'; playing = playing || isPl;
        var tgt = isPl ? (real || (.18 + .14 * Math.abs(Math.sin(Date.now() / 700 + k.length)))) : 0;
        sl[k] = (sl[k] || 0) + (tgt - (sl[k] || 0)) * .35;
        st.style.setProperty('--slvl', sl[k].toFixed(3));
        mx = Math.max(mx, sl[k]);
      });
      cur += ((playing ? mx : 0) - cur) * .35;
      if (Math.abs(cur - last) > .025 || (cur < .02 && last !== 0)) { last = cur < .02 ? 0 : cur; root.style.setProperty('--lvl', last.toFixed(3)); }
    }, 170);
  }

  /* ── peak: пиковые огоньки ── */
  if (has('peak')) {
    var pk = {};
    setInterval(function () {
      var now = Date.now();
      document.querySelectorAll('.strip').forEach(function (st) {
        var vu = st.querySelector('.vu'); if (!vu) return;
        var segs = vu.children, n = 0, i;
        for (i = 0; i < segs.length; i++) if (segs[i].classList.contains('lit')) n = i + 1;
        var o = pk[st.dataset.key] || (pk[st.dataset.key] = { v: 0, t: 0, shown: -1 });
        if (n >= o.v) { o.v = n; o.t = now; }
        else if (now - o.t > 1200) { o.v = Math.max(n, o.v - 1); o.t = now - 1050; }
        var show = o.v > n ? o.v - 1 : -1;               // огонёк виден только над текущим уровнем
        if (show !== o.shown) {
          if (o.shown >= 0 && segs[o.shown]) segs[o.shown].classList.remove('pk');
          if (show >= 0 && segs[show]) segs[show].classList.add('pk');
          o.shown = show;
        }
      });
    }, 100);
  }

  /* ── dial: поворотные ручки ── */
  if (has('dial')) {
    var dials = [];
    document.querySelectorAll('.strip').forEach(function (st) {
      var key = st.dataset.key, el = inp(key), mid = st.querySelector('.strip-mid');
      if (!el || !mid) return;
      var d = document.createElement('div');
      d.className = 'dial'; d.tabIndex = 0; d.setAttribute('role', 'slider');
      d.setAttribute('aria-valuemin', '0'); d.setAttribute('aria-valuemax', '160'); d.setAttribute('aria-label', el.title || key);
      d.innerHTML = '<i class="ring"></i><div class="dv"><span class="n">100</span><small>VOL</small></div>';
      mid.appendChild(d);
      var y0 = 0, v0 = 0, drag = false, wt = null;
      d.addEventListener('pointerdown', function (e) { drag = true; y0 = e.clientY; v0 = +el.value; d.setPointerCapture(e.pointerId); e.stopPropagation(); });
      d.addEventListener('pointermove', function (e) { if (drag) setVol(key, v0 + (y0 - e.clientY) * .9, false); });
      var end = function () { if (drag) { drag = false; setVol(key, +el.value, true); } };
      d.addEventListener('pointerup', end); d.addEventListener('pointercancel', end);
      d.addEventListener('wheel', function (e) {
        e.preventDefault(); setVol(key, +el.value + (e.deltaY < 0 ? 4 : -4), false);
        clearTimeout(wt); wt = setTimeout(function () { setVol(key, +el.value, true); }, 280);
      }, { passive: false });
      d.addEventListener('keydown', function (e) {
        var dv = { ArrowUp: 4, ArrowRight: 4, ArrowDown: -4, ArrowLeft: -4, PageUp: 20, PageDown: -20 }[e.key];
        if (dv === undefined) return; e.preventDefault(); setVol(key, +el.value + dv, true);
      });
      dials.push({ d: d, el: el });
    });
    var paint = function () {
      dials.forEach(function (o) {
        var v = clamp(+o.el.value);
        o.d.style.setProperty('--pv', (v / 160).toFixed(3));
        o.d.setAttribute('aria-valuenow', v);
        var n = o.d.querySelector('.n'); if (n && n.textContent !== String(v)) n.textContent = v;
      });
    };
    setInterval(paint, 120); paint();
  }

  /* ── trim / presets: «−/+» и пресеты ── */
  if (has('trim') || has('presets')) {
    var PRE = [50, 100, 130, 150], qks = [], withPre = has('presets');
    document.querySelectorAll('.strip').forEach(function (st) {
      var key = st.dataset.key, el = inp(key); if (!el) return;
      var box = document.createElement('div'); box.className = 'qk' + (withPre ? '' : ' only-trim');
      var btn = function (txt, cls, fn, title) {
        var b = document.createElement('button'); b.type = 'button'; b.textContent = txt; b.className = cls; b.title = title;
        b.addEventListener('click', function (e) { e.stopPropagation(); fn(); }); return b;
      };
      box.appendChild(btn('−', 'st', function () { setVol(key, +el.value - 5, true); }, '−5'));
      if (withPre) PRE.forEach(function (p) { box.appendChild(btn(String(p), 'pre', function () { setVol(key, p, true); }, 'Громкость ' + p)); });
      box.appendChild(btn('+', 'st', function () { setVol(key, +el.value + 5, true); }, '+5'));
      var sel = st.querySelector('.strip-sel');
      if (sel) st.insertBefore(box, sel); else st.appendChild(box);
      qks.push({ box: box, el: el });
    });
    if (withPre) setInterval(function () {
      qks.forEach(function (o) { o.box.querySelectorAll('.pre').forEach(function (b) { b.classList.toggle('on', +b.textContent === clamp(+o.el.value)); }); });
    }, 300);
  }
})();
