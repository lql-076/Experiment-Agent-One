'use strict';
/* ================= 交互引擎：每套风格自己的滚动方式和手感 =================
   主题在 CSS 文件头写 @fx（用哪几种），这里按名字开关；每种效果"长什么样"写在主题自己的 CSS 里。
   想给新主题换手感：改它文件头的 @fx 就行，不用动这里。

   reveal    滚动触发：卡片滚进视野时才出场（出场动画由主题的 .fx-in 决定）
   parallax  视差滚动：背景光斑、页面标题和内容按不同速度移动
   tilt      卡片跟着鼠标微微倾斜，带一块跟着鼠标走的光斑
   glide     惯性滚动：滚轮滚完还会顺着滑一段，停得很柔
   sticky    吸顶：页面标题吸在顶部，往下滚会收窄
   progress  滚动联动：顶部一条细线显示滚到哪了，右下角显示第几块 / 一共几块
   snap      滚动吸附：滚动停下时对齐到最近的卡片
   hrail     横向滚动：一组卡片排成横条，滚轮往下 = 往右翻一张，也能按住拖
   headline  滚动联动：标题后面一行巨大的空心字，随滚动平移、放大、变淡
   count     数字进入视野时从 0 跳到实际值
   magnet    磁吸：鼠标在按钮上移动时，按钮被"吸"过去一点
   press     点击反馈：点下去的位置出一圈波纹（样子由主题决定）

   动效「关闭」：只留吸顶、吸附、横向排列这些不会动的；「减弱」或省电模式：再去掉视差、倾斜、惯性、磁吸、数字跳动。 */
var FX = { has: {}, lv: 2, io: null, last: null, raf: 0, rail: { lock: 0, acc: 0, t: 0 }, glide: typeof WeakMap === 'function' ? new WeakMap() : null };
var FX_ROOTS = '.view, .sbody, .detail, .evlist';
var FX_CARDS = '.hc, .bcard, .tcard, .sus, .su, .setup, .field, .rem, .ev, .tl-step';
var FX_RAILS = '.bgrid, .tpick';
var FX_NUMS = '.big.num, .dc b.num, .rt-v, .bfoot b.num, .stat b.num';
var FX_SKIP = '#view-monitor, .feed, .logbox, #ov, #resident, #cards';

function fxLevel() { return S.set.motion === 'off' ? 0 : (S.set.motion === 'reduced' || root.dataset.perf === 'on') ? 1 : 2; }
function fxOn(name, minLv) { return !!FX.has[name] && FX.lv >= (minLv || 0); }

function applyFx() {
  var t = THEMES.filter(function (x) { return x.id === root.dataset.theme; })[0];
  var list = (t && t.fx) || [];
  var sig = list.join(' ') + '|' + fxLevel();
  if (sig === FX.sig) return;
  FX.sig = sig; FX.has = {}; list.forEach(function (n) { FX.has[n] = true; });
  FX.lv = fxLevel();
  root.dataset.fx = list.join(' ');
  root.dataset.fxlv = FX.lv;
  /* 换主题时，把上一套留下的倾斜、磁吸、待出场状态都清掉 */
  $$('.fx-pend, .fx-stuck').forEach(function (el) { el.classList.remove('fx-pend', 'fx-stuck'); });
  $$('.fx-lit, .fx-tilt, .fx-mag').forEach(fxReset);
  if (FX.io) FX.io.disconnect();
  FX.io = null;
  fxProgressEls();
  fxDecorate(document.getElementById('content'));
  var v = $('.view.active'); if (v) fxShown(v);
  fxFrame();
}

/* ---------- 滚动：一个监听管所有能滚的区域 ---------- */
function fxMainRoot() {
  var v = $('.view.active'); if (!v) return null;
  if (FX.last && FX.last.isConnected && v.contains(FX.last)) return FX.last;
  var sb = v.querySelector('.sbody'); if (sb) return sb;
  return v;
}
function fxSchedule() { if (!FX.raf) FX.raf = requestAnimationFrame(fxFrame); }
function fxFrame() {
  FX.raf = 0;
  var r = fxMainRoot();
  if (!r) return;
  var st = r.scrollTop, max = r.scrollHeight - r.clientHeight;
  r.classList.toggle('fx-scroll', max > 24);          // 这一页真的能滚：吸顶、视差这些才生效
  r.style.setProperty('--sy', st.toFixed(1));
  root.style.setProperty('--psy', st.toFixed(1));
  if (FX.has.sticky) r.classList.toggle('fx-stuck', st > 8);
  if (FX.has.progress) {
    var bar = document.getElementById('fxBar'), idx = document.getElementById('fxIdx');
    var on = max > 24;
    if (bar) { bar.classList.toggle('on', on); bar.style.setProperty('--p', on ? Math.min(1, st / max).toFixed(4) : 0); }
    if (idx) {
      idx.classList.toggle('on', on);
      if (on) {
        var top = r.getBoundingClientRect().top + r.clientHeight * .3;
        var cards = $$('.hc, .bcard, .tcard, .sus, .fields', r).filter(function (c) { return c.offsetParent; });
        var n = cards.filter(function (c) { return c.getBoundingClientRect().top < top; }).length;
        idx.textContent = (cards.length ? pad(Math.max(1, n)) + ' / ' + pad(cards.length) + '  ·  ' : '') + Math.round(st / max * 100) + '%';
      }
    }
  }
}
document.addEventListener('scroll', function (e) {
  var t = e.target;
  if (!t || t === document || !t.matches) return;
  if (t.matches(FX_RAILS)) { fxRailEdges(t); return; }
  if (!t.matches(FX_ROOTS)) return;
  FX.last = t; fxSchedule();
}, true);
function fxProgressEls() {
  var c = document.getElementById('content'); if (!c) return;
  var want = !!FX.has.progress;
  ['fxBar', 'fxIdx'].forEach(function (id) {
    var el = document.getElementById(id);
    if (want && !el) { el = document.createElement(id === 'fxBar' ? 'i' : 'span'); el.id = id; el.setAttribute('aria-hidden', 'true'); c.appendChild(el); }
    else if (!want && el) el.remove();
  });
}

/* ---------- 滚动触发：在视野外的卡片先藏着，滚到了再出场 ---------- */
function fxIO() {
  if (FX.io || !('IntersectionObserver' in window)) return FX.io;
  FX.io = new IntersectionObserver(function (ents) {
    var k = 0;
    ents.forEach(function (en) {
      if (!en.isIntersecting) return;
      var el = en.target;
      FX.io.unobserve(el);
      el.style.setProperty('--fxd', Math.min(k++, 6) * 55 + 'ms');
      el.classList.remove('fx-pend'); el.classList.add('fx-in');
      el.addEventListener('animationend', function done(ev) { if (ev.target !== el) return; el.classList.remove('fx-in'); el.removeEventListener('animationend', done); });
      setTimeout(function () { el.classList.remove('fx-in'); }, 1600);
      if (fxOn('count', 2)) $$(FX_NUMS, el).concat(el.matches(FX_NUMS) ? [el] : []).forEach(fxCount);
    });
  }, { threshold: [0, .12], rootMargin: '0px 0px -4% 0px' });
  return FX.io;
}
function fxHideBelow(scope) {
  if (!fxOn('reveal', 1) || !scope || !scope.querySelectorAll) return;
  var io = fxIO(); if (!io) return;
  var list = $$(FX_CARDS, scope); if (scope.matches && scope.matches(FX_CARDS)) list.push(scope);
  list.forEach(function (el) {
    if (el.classList.contains('fx-pend') || el.closest(FX_SKIP) || !el.offsetParent) return;
    var box = el.closest(FX_RAILS) || el.closest(FX_ROOTS); if (!box) return;
    var r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
    var out = box.matches(FX_RAILS) ? r.left > b.right - 8 : r.top > b.bottom - 16;
    if (!out) return;
    el.classList.add('fx-pend'); io.observe(el);
  });
}
/* 一个页面刚切出来：视野外的藏起来；视野里的数字跳一下 */
function fxShown(view) {
  if (view.matches(FX_SKIP)) return;
  fxHideBelow(view);
  if (fxOn('count', 2)) $$(FX_NUMS, view).forEach(function (n) { if (!n.closest('.fx-pend') && n.offsetParent && !n.closest(FX_SKIP)) fxCount(n); });
  $$(FX_RAILS, view).forEach(fxRailEdges);
  FX.last = null; fxFrame();
}
function fxCount(el) {
  var w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null), tn;
  while ((tn = w.nextNode())) if (/\d/.test(tn.nodeValue)) break;
  if (!tn) return;
  var orig = tn.nodeValue, m = orig.match(/\d+(\.\d+)?/);
  if (/\d[:：-]\d/.test(orig)) return;                     // 时间、日期不跳
  var to = m ? parseFloat(m[0]) : 0; if (!m || !to) return;
  var dec = m[1] ? m[1].length - 1 : 0, t0 = performance.now(), d = 900, last = null;
  (function step(now) {
    if (last !== null && tn.nodeValue !== last) return;      // 别处已经更新了这个数字，不抢
    var p = Math.min(1, (now - t0) / d), e = 1 - Math.pow(1 - p, 3);
    last = tn.nodeValue = p < 1 ? orig.replace(m[0], (to * e).toFixed(dec)) : orig;
    if (p < 1) requestAnimationFrame(step);
  })(t0);
}

/* ---------- 标题后面的大空心字 ---------- */
function fxDecorate(scope) {
  if (!scope || !scope.querySelectorAll) return;
  if (FX.has.headline) {
    $$('.ph', scope).forEach(function (ph) { var h = ph.querySelector('h1'); if (h) ph.dataset.big = h.textContent.trim(); });
    $$('#view-settings .sbody > h2', scope).forEach(function (h) { h.dataset.big = h.textContent.trim(); });
    if (scope.matches && scope.matches('#view-settings .sbody > h2')) scope.dataset.big = scope.textContent.trim();
  }
}

/* ---------- 页面内容变了（切页、刷新）：补上装饰、把新出现的视野外卡片藏起来 ---------- */
(function () {
  var c = document.getElementById('content'); if (!c || !window.MutationObserver) return;
  new MutationObserver(function (ms) {
    var added = [], shown = [];
    ms.forEach(function (m) {
      if (m.type === 'attributes') { if (m.target.classList.contains('view') && m.target.classList.contains('active')) shown.push(m.target); return; }
      for (var i = 0; i < m.addedNodes.length; i++) if (m.addedNodes[i].nodeType === 1) added.push(m.addedNodes[i]);
    });
    if (!added.length && !shown.length) return;
    added.forEach(function (n) { if (!n.closest(FX_SKIP)) { fxDecorate(n.parentNode || n); fxHideBelow(n); } });
    shown.forEach(fxShown);
    $$(FX_RAILS, c).forEach(fxRailEdges);
    fxSchedule();
  }).observe(c, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  new MutationObserver(applyFx).observe(root, { attributes: true, attributeFilter: ['data-theme', 'data-motion', 'data-perf', 'data-orient'] });
})();

/* ---------- 鼠标：倾斜、光斑、磁吸 ---------- */
function fxReset(el) {
  el.classList.remove('fx-lit', 'fx-tilt', 'fx-mag');
  el.style.translate = ''; el.style.removeProperty('--rx'); el.style.removeProperty('--ry');
}
document.addEventListener('pointermove', function (e) {
  if (e.pointerType === 'touch' || root.dataset.mode === 'resident') return;
  var t = e.target;
  if (FX.has.tilt) {
    var lit = t.closest ? t.closest('.hc, .bcard, .tcard') : null;
    if (FX.lit && FX.lit !== lit) fxReset(FX.lit);
    FX.lit = lit;
    if (lit && !lit.closest(FX_SKIP)) {
      var r = lit.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      lit.classList.add('fx-lit');
      lit.style.setProperty('--mx', (x * 100).toFixed(1) + '%'); lit.style.setProperty('--my', (y * 100).toFixed(1) + '%');
      if (FX.lv >= 2 && lit.matches('button, .bcard, .tcard')) {
        lit.classList.add('fx-tilt');
        lit.style.setProperty('--rx', (-(y - .5) * 6).toFixed(2) + 'deg'); lit.style.setProperty('--ry', ((x - .5) * 8).toFixed(2) + 'deg');
      }
    }
  }
  if (fxOn('magnet', 2)) {
    var b = t.closest ? t.closest('.btn, .chip, .linkbtn') : null;
    if (FX.mag && FX.mag !== b) fxReset(FX.mag);
    FX.mag = b;
    if (b && !b.closest(FX_SKIP) && !b.disabled) {
      var q = b.getBoundingClientRect();
      var dx = Math.max(-7, Math.min(7, (e.clientX - q.left - q.width / 2) * .25)), dy = Math.max(-5, Math.min(5, (e.clientY - q.top - q.height / 2) * .35));
      b.classList.add('fx-mag'); b.style.translate = dx.toFixed(1) + 'px ' + dy.toFixed(1) + 'px';
    }
  }
}, { passive: true });
document.addEventListener('pointerleave', function () { if (FX.lit) fxReset(FX.lit); if (FX.mag) fxReset(FX.mag); FX.lit = FX.mag = null; });

/* ---------- 点击反馈：按下的位置出一圈波纹（画在最上层，不改按钮本身） ---------- */
document.addEventListener('pointerdown', function (e) {
  if (!fxOn('press', 1) || e.button !== 0) return;
  var el = e.target.closest ? e.target.closest('button, .btn, .chip, .nav, .sitem, .tab, .svc, .ev, .tcard') : null;
  if (!el || el.disabled || el.closest('#resident')) return;
  var r = el.getBoundingClientRect(); if (!r.width) return;
  var box = document.createElement('span'), dot = document.createElement('i');
  box.className = 'fx-pbox';
  box.style.cssText = 'left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;height:' + r.height + 'px;border-radius:' + getComputedStyle(el).borderRadius;
  var x = e.clientX - r.left, y = e.clientY - r.top, d = 2 * Math.hypot(Math.max(x, r.width - x), Math.max(y, r.height - y));
  dot.style.cssText = 'left:' + x + 'px;top:' + y + 'px;--d:' + d.toFixed(0) + 'px';
  box.appendChild(dot); document.body.appendChild(box);
  setTimeout(function () { box.remove(); }, 1000);
}, true);

/* ---------- 滚轮：横条里往下滚 = 往右翻一张；星云的惯性滚动 ---------- */
function fxCanScroll(el, d, axis) {
  if (axis === 'x') { var mx = el.scrollWidth - el.clientWidth; return mx > 1 && (d > 0 ? el.scrollLeft < mx - 1 : el.scrollLeft > 1); }
  var my = el.scrollHeight - el.clientHeight; return my > 1 && (d > 0 ? el.scrollTop < my - 1 : el.scrollTop > 1);
}
function fxScroller(t, d) {
  for (var el = t; el && el !== document.body; el = el.parentElement) {
    if (el.matches('.feed, .logbox, .ov-panel, textarea, select')) return null;
    var oy = getComputedStyle(el).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && fxCanScroll(el, d, 'y')) return el;
  }
  return null;
}
function fxRailStep(rail, dir) {
  var kids = $$(':scope > *', rail).filter(function (k) { return k.offsetParent; }); if (!kids.length) return;
  var x0 = rail.getBoundingClientRect().left, cur = 0;
  kids.forEach(function (k, i) { if (k.getBoundingClientRect().left - x0 <= 8) cur = i; });
  var to = kids[Math.max(0, Math.min(kids.length - 1, cur + dir))];
  rail.scrollTo({ left: to.offsetLeft - kids[0].offsetLeft, behavior: FX.lv >= 1 ? 'smooth' : 'auto' });
}
function fxRailEdges(rail) {
  if (!FX.has.hrail || !rail || !rail.classList) return;
  var mx = rail.scrollWidth - rail.clientWidth;
  rail.classList.toggle('at-start', rail.scrollLeft < 10);
  rail.classList.toggle('at-end', rail.scrollLeft > mx - 10);
}
document.addEventListener('wheel', function (e) {
  if (e.ctrlKey || e.defaultPrevented || root.dataset.mode === 'resident') return;
  var t = e.target; if (!t.closest) return;
  var vertical = Math.abs(e.deltaY) >= Math.abs(e.deltaX);
  if (FX.has.hrail && vertical) {
    var rail = t.closest(FX_RAILS);
    if (rail && !rail.closest(FX_SKIP) && fxCanScroll(rail, e.deltaY, 'x')) {
      e.preventDefault();
      var now = performance.now();
      FX.rail.acc = now - FX.rail.t > 250 ? e.deltaY : FX.rail.acc + e.deltaY; FX.rail.t = now;
      if (now > FX.rail.lock && Math.abs(FX.rail.acc) > 30) { FX.rail.lock = now + 380; FX.rail.acc = 0; fxRailStep(rail, e.deltaY > 0 ? 1 : -1); }
      return;
    }
  }
  if (!fxOn('glide', 2) || !vertical || !FX.glide || t.closest('input, textarea, select, ' + FX_SKIP)) return;
  var d = e.deltaY * (e.deltaMode === 1 ? 36 : e.deltaMode === 2 ? window.innerHeight * .8 : 1);
  var el = fxScroller(t, d); if (!el) return;
  e.preventDefault();
  var g = FX.glide.get(el);
  if (!g || !g.on || Math.abs(el.scrollTop - g.set) > 2) { g = { cur: el.scrollTop, target: el.scrollTop, set: el.scrollTop, on: false }; FX.glide.set(el, g); }
  g.target = Math.max(0, Math.min(el.scrollHeight - el.clientHeight, g.target + d * 1.1));
  if (g.on) return;
  g.on = true;
  (function step() {
    if (Math.abs(el.scrollTop - g.set) > 2) { g.on = false; return; }   // 中途拖了滚动条：交还给系统
    var diff = g.target - g.cur;
    if (Math.abs(diff) < .4) { el.scrollTop = g.set = g.target; g.on = false; return; }
    g.cur += diff * .11; el.scrollTop = g.cur; g.set = el.scrollTop;
    requestAnimationFrame(step);
  })();
}, { passive: false });

/* ---------- 横条：按住鼠标左右拖 ---------- */
document.addEventListener('pointerdown', function (e) {
  if (!FX.has.hrail || e.button !== 0 || e.pointerType !== 'mouse') return;
  var rail = e.target.closest ? e.target.closest(FX_RAILS) : null;
  if (!rail || e.target.closest('input, select, textarea') || rail.scrollWidth <= rail.clientWidth + 1) return;
  var x0 = e.clientX, s0 = rail.scrollLeft, moved = false;
  function mv(ev) {
    var dx = ev.clientX - x0;
    if (!moved && Math.abs(dx) < 6) return;
    if (!moved) { moved = true; rail.classList.add('fx-drag'); }
    rail.scrollLeft = s0 - dx;
  }
  function up() {
    document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up);
    if (!moved) return;
    rail.classList.remove('fx-drag');
    var stop = function (ev) { ev.stopPropagation(); ev.preventDefault(); };
    rail.addEventListener('click', stop, { capture: true, once: true });     // 拖完松手不算点了卡片
    setTimeout(function () { rail.removeEventListener('click', stop, true); }, 50);
  }
  document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up);
});

window.addEventListener('resize', fxSchedule);
applyFx();
