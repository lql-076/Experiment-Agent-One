'use strict';
/* ================= 横竖屏 / 全屏 ================= */
function wantOrient() { if (S.set.layout === 'landscape' || S.set.layout === 'portrait') return S.set.layout; return window.innerHeight > window.innerWidth * 1.05 ? 'portrait' : 'landscape'; }
function applyOrient(animate) {
  var o = wantOrient();
  $('#orientIcon').innerHTML = ICONS[S.set.layout === 'auto' ? 'auto' : (o === 'portrait' ? 'port' : 'land')];
  $('#orientLabel').textContent = S.set.layout === 'auto' ? '自动' : (o === 'portrait' ? '竖屏' : '横屏');
  if (root.dataset.orient === o) return;
  var run = function () { root.dataset.orient = o; applyScale(); placeInd(true); };
  if (animate) vt(run); else run();
}
var rz;
window.addEventListener('resize', function () { cancelAnimationFrame(rz); rz = requestAnimationFrame(function () { applyOrient(true); applyScale(); placeInd(true); }); });
$('#btnOrient').addEventListener('click', function () {
  var next = { auto: 'landscape', landscape: 'portrait', portrait: 'auto' }[S.set.layout] || 'auto';
  setVal('layout', next);
  toast({ auto: '布局：自动（按窗口比例）', landscape: '布局：固定横屏', portrait: '布局：固定竖屏' }[next]);
});
function isFull() { return DESK.on ? DESK.full : !!(document.fullscreenElement || document.webkitFullscreenElement); }
function syncFull() { $('#fullIcon').innerHTML = isFull() ? ICONS.unfull : ICONS.full; $('#fullLabel').textContent = isFull() ? '窗口' : '全屏'; $('#btnFull').setAttribute('aria-label', isFull() ? '退出全屏，回到窗口模式' : '进入全屏'); }
function toggleFull() {
  if (DESK.on) { deskToggleFull(); return; }
  try {
    if (isFull()) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    else { var p = (root.requestFullscreen || root.webkitRequestFullscreen).call(root); if (p && p.catch) p.catch(function () { toast('这里不允许全屏，按 F11 也可以'); }); }
  } catch (e) { toast('这里不允许全屏，按 F11 也可以'); }
}
document.addEventListener('fullscreenchange', syncFull);
document.addEventListener('webkitfullscreenchange', syncFull);
$('#btnFull').addEventListener('click', toggleFull);
function placeInd(instant) {
  var a = $('.nav[data-view][aria-current="page"]'), ind = $('#navInd'), rail = $('.rail');
  if (!a || !ind || root.dataset.mode !== 'normal') return;
  var rr = rail.getBoundingClientRect(), br = a.getBoundingClientRect();
  if (instant) ind.classList.add('instant');
  ind.style.width = br.width + 'px'; ind.style.height = br.height + 'px';
  ind.style.transform = 'translate(' + (br.left - rr.left - rail.clientLeft) + 'px,' + (br.top - rr.top - rail.clientTop) + 'px)';
  if (instant) { void ind.offsetWidth; ind.classList.remove('instant'); }
}

/* ================= 外观与风格 ================= */
function applyLook() {
  var b = +S.set.bright || 100;
  $('#dim').style.opacity = String((100 - b) / 100 * .9);
  $('#warm').style.opacity = String(S.set.warmth / 100);
  applyScale();
  root.dataset.motion = S.set.motion;
  root.dataset.perf = S.set.perf ? 'on' : 'off';
  syncStatus();
}
/* 界面随窗口放大：按 1680×1000（横屏）/ 960×1600（竖屏）的设计尺寸等比放大，所有尺寸都是 rem，一起变大 */
function autoScale() {
  if (S.set.autoScale === false) return 1;
  var w = window.innerWidth, h = window.innerHeight;
  var s = root.dataset.orient === 'portrait' ? Math.min(w / 960, h / 1600) : Math.min(w / 1680, h / 1000);
  return Math.max(1, Math.min(2.4, s));
}
var lastFont = 0;
function applyScale() {
  var f = Math.round(16 * (+S.set.scale || 100) / 100 * autoScale() * 4) / 4;
  if (f === lastFont) return;
  lastFont = f; root.style.fontSize = f + 'px';
}
function syncStatus() {
  var t = $('#statusText'), d = $('#statusDot'); if (!t) return;
  d.className = 'dot';
  if (!LIVE) { t.textContent = '演示数据 · 后端未接入'; return; }
  if (S.set.demo) { t.textContent = '后端已连接 · 正在显示演示数据'; return; }
  var st = D.state;
  if (!st) { t.textContent = D.offline ? '后端连不上（启动.bat 的窗口关了？）' : '后端已连接'; if (D.offline) d.classList.add('bad'); return; }
  var parts = ['后端已连接', st.qq.status === 'online' ? 'QQ 在线' : st.qq.status === 'connecting' ? 'QQ 连接中' : 'QQ 离线',
    st.models.server ? (st.models.embed ? '嵌入模型已加载' : '模型服务在线') : '模型服务未启动'];
  if (st.models.yielding) parts.push('让路模式');
  t.textContent = parts.join(' · ');
  if (st.qq.status === 'online' && st.models.server) d.classList.add('ok');
}
function themeName(id) { return THEMES.filter(function (t) { return t.id === id; })[0].name; }
function setTheme(id, x, y) {
  if (S.set.theme === id) return;
  var apply = function () {
    S.set.theme = id; root.dataset.theme = id; save(); pushSet({ theme: id });
    renderResident(); placeInd(true);
    if (root.dataset.mode === 'resident') { cancelAnims($$('#resident .rc-svg, #resident .rc-arc, #resident .rc-glow, #resident .rc-ticks, #rcSec')); }
    $$('[data-theme-pick]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.themePick === id); });
  };
  if (!smooth()) { apply(); toast('风格：' + themeName(id)); return; }
  root.classList.add('theme-vt');
  var t;
  try { t = document.startViewTransition(apply); } catch (e) { root.classList.remove('theme-vt'); apply(); return; }
  t.ready.then(function () {
    var r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    root.animate({ clipPath: ['circle(0px at ' + x + 'px ' + y + 'px)', 'circle(' + r + 'px at ' + x + 'px ' + y + 'px)'] }, { duration: 750, easing: 'cubic-bezier(.22,1,.36,1)', pseudoElement: '::view-transition-new(root)' });
  }).catch(function () {});
  t.finished.then(function () { root.classList.remove('theme-vt'); }, function () { root.classList.remove('theme-vt'); });
  toast('风格：' + themeName(id));
}
function cycleTheme(x, y) { var ids = THEMES.map(function (t) { return t.id; }); setTheme(ids[(ids.indexOf(S.set.theme) + 1) % ids.length], x, y); }
$('#btnTheme').addEventListener('click', function (e) { var r = e.currentTarget.getBoundingClientRect(); cycleTheme(r.left + r.width / 2, r.top + r.height / 2); });

/* ================= 页面切换 ================= */
function goView(v) {
  if (v === 'brains') fetchBrains();
  if (v === 'reports') fetchReport();
  if (S.view === v) return;
  closeBrain();
  if (S.view === 'monitor') stopMonitor();
  if (S.view === 'tts') ttsLeave();
  if (S.view === 'img') imgLeave();
  var usingVT = moving();
  var t = vt(function () {
    S.view = v;
    $$('.nav[data-view]').forEach(function (b) { if (b.dataset.view === v) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
    $$('.view').forEach(function (el) { el.classList.toggle('active', el.id === 'view-' + v); });
    if (v === 'home' && D.homeDirty) { D.homeDirty = false; renderHome(true); }
    if (v === 'brains') renderBrains();
    if (v === 'reports') renderReports();
    if (v === 'events') renderEvents();
    if (v === 'monitor') startMonitor();
    if (v === 'docs') renderDocs();
    if (v === 'tts') { if (TTS.st) renderTTS(); ttsEnter(); }
    if (v === 'img') { if (IMG.st) renderImg(); imgEnter(); }
    if (v === 'chat') { fillChatLog(true); fillSide(); setTimeout(function () { var i = $('#cIn'); if (i && !i.disabled) i.focus(); }, 60); }
    placeInd(usingVT);
  });
  if (!t) replay($('#view-' + v));
}
$$('.nav[data-view]').forEach(function (b) { b.addEventListener('click', function () { goView(b.dataset.view); }); });
