'use strict';
/* 桌面窗口（无边框）。由 app\window.py 打开时 window.pywebview.api 可用。
   原生模式（native）：拖动和改大小交给 Windows —— 拖到屏幕顶部最大化、拖到两边半屏、顶部有贴靠布局条；
     双击顶栏最大化 / 还原；四边四角都能拖动改大小。
   老办法（原生没装上时）：顶栏拖动、右下角改大小，都由网页自己算。
   在普通浏览器或 Edge 里打开时这些都不出现，全屏走浏览器自己的全屏。 */
var DESK = { on: false, native: false, full: false, max: false, busy: false };
var EDGE = 6, CORNER = 16;
function deskApi() { return window.pywebview && window.pywebview.api; }
function deskApply(st) { if (st) { DESK.full = !!st.full; DESK.max = !!st.max; DESK.native = !!st.native; } deskSync(); }
function deskSync() {
  var bar = $('.topbar');
  if (bar) bar.classList.toggle('pywebview-drag-region', DESK.on && !DESK.native && !DESK.full);
  $('#grip').hidden = !DESK.on || DESK.full || DESK.max;
  root.classList.toggle('desk-max', DESK.max);
  syncFull();
  requestAnimationFrame(function () { placeInd(true); });
}
function deskRefresh() { var a = deskApi(); if (a && DESK.on) a.state().then(deskApply).catch(function () {}); }
function deskToggleFull() {
  var a = deskApi(); if (!a || DESK.busy) return;
  DESK.busy = true;
  a.toggle_fullscreen().then(deskApply).catch(function () { toast('切换失败，再点一次试试'); })
    .then(function () { DESK.busy = false; });
}
function deskInit() {
  var a = deskApi(); if (!a || DESK.on || !a.state) return;
  DESK.on = true; root.classList.add('desk');
  $('#btnMin').hidden = false; $('#btnClose').hidden = false;
  a.state().then(deskApply).catch(function () { deskSync(); });
  setTimeout(deskRefresh, 1500); setTimeout(deskRefresh, 4000);   // 原生那套是窗口出来后才装上的，稍后再问两次
}
window.addEventListener('pywebviewready', deskInit);
setTimeout(deskInit, 0);
var deskRz;
window.addEventListener('resize', function () { clearTimeout(deskRz); deskRz = setTimeout(deskRefresh, 150); });

$('#btnMin').addEventListener('click', function () { var a = deskApi(); if (a) a.minimize(); });

/* ---------- 关闭：只关窗口（后台继续），或者退出 Agent（全部停掉） ---------- */
function closeDo(how) {
  closeMenu(false);
  var a = deskApi();
  if (how === 'quit') {
    toast('正在退出 Agent…');
    var done = function () { if (a && a.close_window) a.close_window(); else window.close(); };
    (useLive() || LIVE ? api('POST', '/api/quit', {}, 4000) : Promise.resolve()).then(done, done);
    return;
  }
  if (a && a.close_window) a.close_window(); else window.close();
}
function closeMenu(show) {
  var m = $('#closeMenu');
  if (!show) { if (m) m.remove(); return; }
  if (m) { m.remove(); return; }
  m = document.createElement('div'); m.id = 'closeMenu'; m.className = 'cmenu'; m.setAttribute('role', 'menu');
  m.innerHTML = '<button role="menuitem" data-close="window"><b>关掉窗口</b><span>后台继续运行，提醒和 QQ 照常。再双击 启动.bat 就能打开</span></button>' +
    '<button role="menuitem" data-close="quit"><b>退出 Agent</b><span>全部停掉，提醒和 QQ 也停。硬件监控助手是单独的管理员窗口，要自己关</span></button>' +
    '<label class="cm-rem"><input type="checkbox" id="closeRemember"> 记住，下次直接这样（设置 › 外观 能改回来）</label>';
  document.body.appendChild(m);
  var r = $('#btnClose').getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight;
  var portrait = root.dataset.orient === 'portrait';
  var x = portrait ? Math.min(innerWidth - mw - 12, Math.max(12, r.left + r.width / 2 - mw / 2)) : r.right + 10;
  var y = portrait ? r.top - mh - 10 : Math.min(innerHeight - mh - 12, Math.max(12, r.top + r.height / 2 - mh / 2));
  m.style.left = x + 'px'; m.style.top = y + 'px';
  m.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-close]'); if (!b) return;
    if ($('#closeRemember').checked) { S.set.closeAct = b.dataset.close; save(); if (typeof pushSet === 'function') pushSet({ closeAct: b.dataset.close }); }
    closeDo(b.dataset.close);
  });
  setTimeout(function () { var b = m.querySelector('[data-close="window"]'); if (b) b.focus(); }, 0);
}
$('#btnClose').addEventListener('click', function (ev) {
  ev.stopPropagation();
  var act = S.set.closeAct || 'ask';
  if (act === 'window' || act === 'quit') { closeDo(act); return; }
  closeMenu(true);
});
document.addEventListener('pointerdown', function (ev) { var m = $('#closeMenu'); if (m && !m.contains(ev.target) && !ev.target.closest('#btnClose')) closeMenu(false); });
document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeMenu(false); });

/* ---------- 原生模式：拖动、双击、改大小 ---------- */
function edgeAt(x, y) {
  if (!DESK.native || DESK.full || DESK.max || root.dataset.mode === 'resident') return '';
  var w = window.innerWidth, h = window.innerHeight;
  var l = x < EDGE, r = x > w - 1 - EDGE, t = y < EDGE, b = y > h - 1 - EDGE;
  var lc = x < CORNER, rc = x > w - 1 - CORNER, tc = y < CORNER, bc = y > h - 1 - CORNER;
  if ((t && lc) || (l && tc)) return 'tl';
  if ((t && rc) || (r && tc)) return 'tr';
  if ((b && lc) || (l && bc)) return 'bl';
  if ((b && rc) || (r && bc)) return 'br';
  return l ? 'l' : r ? 'r' : t ? 't' : b ? 'b' : '';
}
var CURSOR = { l: 'ew', r: 'ew', t: 'ns', b: 'ns', tl: 'nwse', br: 'nwse', tr: 'nesw', bl: 'nesw' };
var press = null, lastDown = { t: 0, x: 0, y: 0 };
function onTopbar(e) { return e.target.closest('.topbar') && !e.target.closest('button,a,input,select,textarea'); }
document.addEventListener('mousemove', function (e) {
  if (!DESK.on) return;
  if (press && (e.buttons & 1)) {
    if (Math.abs(e.screenX - press.x) + Math.abs(e.screenY - press.y) > 3) {   // 真的在拖了才交给 Windows
      var p = press; press = null;
      if (p.edge) deskApi().begin_resize(p.edge); else deskApi().begin_move();
    }
    return;
  }
  var ed = edgeAt(e.clientX, e.clientY);
  if ((root.dataset.edge || '') !== (ed ? CURSOR[ed] : '')) { if (ed) root.dataset.edge = CURSOR[ed]; else delete root.dataset.edge; }
}, { passive: true });
document.addEventListener('mousedown', function (e) {
  if (!DESK.on || !DESK.native || e.button !== 0) return;
  var ed = edgeAt(e.clientX, e.clientY);
  if (ed) { e.preventDefault(); e.stopPropagation(); press = { x: e.screenX, y: e.screenY, edge: ed }; return; }
  if (!onTopbar(e) || DESK.full) return;
  var now = Date.now();
  if (now - lastDown.t < 400 && Math.abs(e.screenX - lastDown.x) < 6 && Math.abs(e.screenY - lastDown.y) < 6) {
    lastDown.t = 0; press = null;
    deskApi().toggle_max().then(deskApply); return;          // 双击顶栏：最大化 / 还原（和普通 Windows 窗口一样）
  }
  lastDown = { t: now, x: e.screenX, y: e.screenY };
  e.preventDefault();
  press = { x: e.screenX, y: e.screenY, edge: '' };
}, true);
document.addEventListener('mouseup', function () { press = null; }, true);

/* 老办法下：顶栏里的按钮不触发拖动；双击顶栏切全屏 */
$('.topbar').addEventListener('mousedown', function (e) { if (e.target.closest('button,a,input,select')) e.stopPropagation(); });
$('.topbar').addEventListener('dblclick', function (e) { if (DESK.on && !DESK.native && !e.target.closest('button,a,input,select')) deskToggleFull(); });

/* 右下角改大小：原生模式交给 Windows，老办法网页自己算 */
(function () {
  var g = $('#grip'), st = null, pend = null, sending = false;
  function send() {
    if (!pend || sending) return;
    var a = deskApi(), p = pend; pend = null; sending = true;
    a.resize(p.w, p.h).catch(function () {}).then(function () { sending = false; send(); });
  }
  g.addEventListener('mousedown', function (e) {
    if (!DESK.native || DESK.full || e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    press = { x: e.screenX, y: e.screenY, edge: 'br' };
  });
  g.addEventListener('pointerdown', function (e) {
    if (!DESK.on || DESK.full || DESK.native) return;
    e.preventDefault(); e.stopPropagation();
    g.setPointerCapture(e.pointerId);
    st = { x: e.screenX, y: e.screenY, w: window.innerWidth, h: window.innerHeight };
  });
  g.addEventListener('pointermove', function (e) {
    if (!st) return;
    pend = { w: Math.round(st.w + e.screenX - st.x), h: Math.round(st.h + e.screenY - st.y) };
    send();
  });
  function end() { st = null; }
  g.addEventListener('pointerup', end);
  g.addEventListener('pointercancel', end);
})();
