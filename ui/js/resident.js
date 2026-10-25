'use strict';
/* ================= 时钟 ================= */
var WD = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
var WD2 = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];
var CN = '〇一二三四五六七八九';
function cnNum(n) { if (n <= 10) return n === 10 ? '十' : CN[n]; if (n < 20) return '十' + CN[n - 10]; return CN[Math.floor(n / 10)] + '十' + (n % 10 ? CN[n % 10] : ''); }
var lastMin = -1, secDeg = null;
function renderClock() {
  var d = new Date(), h = d.getHours(), ap = '';
  if (!S.set.h24) { ap = h < 12 ? '上午' : '下午'; h = h % 12 || 12; }
  var hm = (S.set.h24 ? pad(h) : h) + ':' + pad(d.getMinutes());
  var t = $('#tTop'); if (t) t.textContent = hm;
  var dt = $('#dTop'); if (dt) dt.textContent = (ap ? ap + ' ' : '') + (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + WD[d.getDay()];
  var tb = $('#tBig'); if (tb) tb.textContent = hm;
  var sb = $('#sBig'); if (sb) sb.textContent = S.set.secs ? pad(d.getSeconds()) : '';
  var db = $('#dBig');
  var ds = db ? themeVar('--date-style') : '';
  if (db) db.textContent = ds === 'cn' ? cnNum(d.getMonth() + 1) + '月' + cnNum(d.getDate()) + '日 · ' + WD2[d.getDay()]
    : ds === 'dot' ? d.getFullYear() + '.' + pad(d.getMonth() + 1) + '.' + pad(d.getDate()) + '  ' + WD[d.getDay()]
    : (d.getMonth() + 1) + '月' + d.getDate() + '日  ' + WD[d.getDay()];
  var rs = $('#rcSub'); if (rs) rs.textContent = ap || '';
  var sec = $('#rcSec');
  if (sec) {
    var target = d.getSeconds() * 6;
    if (secDeg == null) secDeg = target; else { var cur = ((secDeg % 360) + 360) % 360, diff = target - cur; if (diff < 0) diff += 360; secDeg += diff; }
    sec.style.transform = 'rotate(' + secDeg + 'deg)';
  }
  if (d.getMinutes() !== lastMin) { lastMin = d.getMinutes(); applyLook(); }
  updateReminder();
}
function tickClock() { renderClock(); setTimeout(tickClock, 1000 - new Date().getMilliseconds() + 8); }

/* ================= 常驻 ================= */
var RR = 176, RCC = 2 * Math.PI * RR, TR = 192, TCC = 2 * Math.PI * TR;
function ringSVG() {
  var num = function (k, d) { var v = parseFloat(themeVar(k)); return isNaN(v) ? d : v; };
  var ticks = Math.max(1, Math.round(num('--ring-ticks', 60))), seg = TCC / ticks, tw = num('--ring-tick-w', 1.2);
  var aw = num('--ring-arc-w', 8), tsw = num('--ring-tick-sw', 5), sr = num('--ring-sec-r', 5);
  var cross = '<g class="rc-cross" style="stroke:var(--accent);stroke-width:2;opacity:.7"><path d="M200 0v14M200 386v14M0 200h14M386 200h14"/></g>';
  /* 断断续续的环：主题里 --ring-segs 是分成几段，--ring-fill 是每段画多长（很小 + 圆头 = 一颗颗圆点），--ring-cap 是端头 */
  var segs = Math.max(0, Math.round(num('--ring-segs', 0))), fill = Math.min(1, Math.max(0.001, num('--ring-fill', 0.7)));
  var cap = themeVar('--ring-cap') === 'round' ? 'round' : 'butt', per = segs ? RCC / segs : 0;
  var mask = segs ? '<mask id="rcMask" maskUnits="userSpaceOnUse" x="0" y="0" width="400" height="400"><circle cx="200" cy="200" r="' + RR + '" transform="rotate(-90 200 200)" fill="none" stroke="#fff" stroke-linecap="' + cap +
    '" style="stroke-width:' + (aw + (cap === 'round' ? 0 : 4)) + ';stroke-dasharray:' + (per * fill).toFixed(3) + ' ' + (per * (1 - fill)).toFixed(3) + '"/></mask>' : '';
  var mk = segs ? ' mask="url(#rcMask)"' : '';
  return '<svg class="rc-svg" viewBox="0 0 400 400" aria-hidden="true"><defs><linearGradient id="rcGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" style="stop-color:var(--ring1)"/><stop offset="1" style="stop-color:var(--ring2)"/></linearGradient><filter id="rcBlur" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="9"/></filter>' + mask + '</defs>' +
    '<circle class="rc-ticks" cx="200" cy="200" r="' + TR + '" transform="rotate(-90 200 200)" style="stroke-width:' + tsw + ';stroke-dasharray:' + tw + ' ' + (seg - tw).toFixed(3) + '"/>' + cross +
    '<circle class="rc-track" cx="200" cy="200" r="' + RR + '"' + mk + ' style="stroke-width:' + aw + '"/>' +
    '<circle class="rc-glow" cx="200" cy="200" r="' + RR + '" transform="rotate(-90 200 200)" filter="url(#rcBlur)" style="stroke:url(#rcGrad);stroke-width:' + (aw * 1.6) + ';stroke-dasharray:' + RCC.toFixed(2) + '"/>' +
    '<g' + mk + '><circle class="rc-arc" cx="200" cy="200" r="' + RR + '" transform="rotate(-90 200 200)" style="stroke:url(#rcGrad);stroke-width:' + aw + ';stroke-dasharray:' + RCC.toFixed(2) + '"/></g>' +
    '<g class="rc-sec" id="rcSec"><circle cx="200" cy="' + (200 - TR) + '" r="' + sr + '"/></g></svg>';
}
function rTile(i, tc, head, big, spark, foot) {
  return '<div class="rt rin" style="--i:' + i + ';--tc:' + tc + '"><div class="rt-h"><span>' + head[0] + '</span><span>' + head[1] + '</span></div><div class="rt-v num">' + big + '</div>' + (spark || '') + '<div class="rt-f">' + foot + '</div></div>';
}
function lastEventText() { var e = evs()[0]; return e ? e.t + ' ' + e.text.slice(0, 14) + ' → ' + (e.to === 'local' ? (e.label || '本地') : ROUTES[e.to].name) : '还没有事件'; }
function statusShort() {
  if (!LIVE) return '演示';
  if (S.set.demo) return '演示数据';
  var st = D.state; if (!st) return '连接中';
  return (st.qq.status === 'online' ? 'QQ 在线' : 'QQ 离线') + (st.models.yielding ? ' · 让路中' : '');
}
function renderResident() {
  var ab = themeVar('--res-labels') === 'en';
  $('#rWrap').innerHTML = '<div class="rs"><div class="rclock">' + ringSVG() + '<div class="rc-center"><div id="clockBig"><span id="tBig">--:--</span><span class="r-sec" id="sBig"></span></div><div id="dBig"></div><div class="rc-sub" id="rcSub"></div></div></div>' +
    '<div class="rs-side"><div class="ragent rin" style="--i:0"><span>' + (ab ? 'STATUS' : '状态') + '<b id="rStatus"></b></span><span>' + (ab ? 'NEXT' : '下一个提醒') + '<b id="rNextLeft"></b></span><span>' + (ab ? 'LAST' : '最近') + '<b id="rLast"></b></span></div>' +
    '<div class="rgrid">' +
      '<div class="rt rin fps" id="rtFps" hidden style="--i:1;--tc:var(--h4)"><div class="rt-h"><span>' + (ab ? 'FPS' : '游戏帧数') + '</span><span id="fpsProc"></span></div>' +
        '<div class="rt-fps"><div class="rt-v num">' + hw('fps.fps', 'int', 1) + '<small>FPS</small></div><div class="rt-v num lo">' + hw('fps.low1', 'f1') + '<small>' + (ab ? '1% LOW' : '1% 低帧') + '</small></div></div>' +
        sparkHTML('fps', 240) + '</div>' +
      rTile(1, 'var(--h1)', ['CPU', esc(HW.cpu.name || 'CPU')], hw('cpu.load', 'int', 1) + '<small>%</small>', sparkHTML('cpu', 100), '<span><em>频率</em>' + hw('cpu.clock', 'f2') + ' GHz</span><span><em>温度</em>' + hw('cpu.temp', 'temp') + '</span><span><em>功耗</em>' + hw('cpu.power') + ' W</span>') +
      rTile(2, 'var(--h2)', ['GPU<span data-hwtxt="gpu.topTxt"></span>', esc(HW.gpu.name || 'GPU')], hw('gpu.load', 'int', 1) + '<small>%</small>', sparkHTML('gpu', 100), '<span><em>频率</em>' + hw('gpu.clock') + ' MHz</span><span><em>温度</em>' + hw('gpu.temp', 'temp') + '</span><span><em>功耗</em>' + hw('gpu.power') + ' W</span>') +
      rTile(3, 'var(--h3)', ['内存', '<b id="ramDesc" style="font-weight:inherit">' + esc(HW.ram.desc || (Math.round(HW.ram.total || 32) + ' GB')) + '</b>'], hw('ram.load', 'int', 1) + '<small>%</small>', sparkHTML('ram', 100), '<span><em>已用</em>' + hw('ram.used', 'f1') + ' / ' + Math.round(HW.ram.total || 32) + ' GB</span><span><em>频率</em>' + hw('ram.freq') + ' MT/s</span>') +
      rTile(4, 'var(--h4)', ['显存', (HW.gpu.vramTotal ? Math.round(HW.gpu.vramTotal) + ' GB' : '—')], hw('gpu.vram', 'f1', 1) + '<small>GB</small>', sparkHTML('vram', 100), '<span><em>占比</em>' + hw('gpu.vramPct') + '%</span>') +
      rTile(5, 'var(--h5)', ['整机功耗', '估算'], hw('sys.power', 'int', 1) + '<small>W</small>', sparkHTML('pw', 350), '<span><em>CPU</em>' + hw('cpu.power') + ' W</span><span><em>显卡</em>' + hw('gpu.power') + ' W</span>') +
      '<div class="rt rin" style="--i:6;--tc:var(--accent)"><div class="rt-h"><span>硬盘温度</span><span id="diskCount">' + HW.disks.length + ' 块</span></div><div id="diskBody" style="display:flex;flex-direction:column;gap:.6rem;margin-top:.25rem">' + diskTileBody() +
      '</div></div>' +
    '</div></div></div>';
  fillResidentText();
  secDeg = null; renderClock(); renderHW();
}
function fillResidentText() { var a = $('#rStatus'); if (a) a.textContent = statusShort(); var b = $('#rLast'); if (b) b.textContent = lastEventText(); updateReminder(); }
var animOK = function () { return S.set.motion !== 'off' && !!Element.prototype.animate; };
function cancelAnims(els) { els.forEach(function (el) { if (el && el.getAnimations) el.getAnimations().forEach(function (a) { a.cancel(); }); }); }
function ringIn() {
  var svg = $('#resident .rc-svg'), arcs = $$('#resident .rc-arc, #resident .rc-glow'), ticks = $('#resident .rc-ticks'), sec = $('#rcSec');
  cancelAnims([svg, ticks, sec, $('#resident .rs-side'), $('#resident .rc-track'), $('#resident .rc-cross'), $('#dBig')].concat(arcs));
  if (!animOK() || !svg) return;
  var d = S.set.motion === 'reduced' ? 500 : 1700, ez = 'cubic-bezier(.22,1,.36,1)';
  arcs.forEach(function (a) { a.animate([{ strokeDashoffset: RCC }, { strokeDashoffset: 0 }], { duration: d, delay: 220, easing: ez, fill: 'both' }); });
  svg.animate([{ transform: 'rotate(-120deg) scale(.92)' }, { transform: 'rotate(0deg) scale(1)' }], { duration: d, delay: 220, easing: ez, fill: 'both' });
  if (ticks) ticks.animate([{ opacity: 0 }, { opacity: getComputedStyle(ticks).opacity }], { duration: d * .8, delay: 500, easing: 'ease', fill: 'both' });
  if (sec) sec.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: d, fill: 'both' });
}
var leaving = false;
function ringOut() {
  var svg = $('#resident .rc-svg'), arcs = $$('#resident .rc-arc, #resident .rc-glow'), side = $('#resident .rs-side'), rest = $$('#resident .rc-ticks, #resident .rc-cross, #rcSec, #resident .rc-track, #dBig');
  var d = S.set.motion === 'reduced' ? 450 : 1100, ez = 'cubic-bezier(.65,0,.35,1)';
  svg.animate([{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], { duration: d, easing: ez, fill: 'forwards' });
  arcs.forEach(function (a) { a.animate([{ strokeDashoffset: 0 }, { strokeDashoffset: -RCC }], { duration: d, easing: ez, fill: 'forwards' }); });
  rest.forEach(function (e) { e.animate([{ opacity: getComputedStyle(e).opacity }, { opacity: 0 }], { duration: d * .6, easing: 'ease', fill: 'forwards' }); });
  if (side) side.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(1rem)' }], { duration: d * .5, easing: 'ease', fill: 'forwards' });
  return d;
}

/* ================= 模式切换 ================= */
var driftTimer, hintTimer, idleT;
function setMode(m) {
  if (root.dataset.mode === m) return;
  if (m === 'resident') fillResidentText();
  if (moving()) root.classList.add('mode-vt');
  var t = vt(function () {
    root.dataset.mode = m;
    if (m === 'resident') { renderHW(); ringIn(); } else placeInd(true);
  });
  if (t) t.finished.then(function () { root.classList.remove('mode-vt'); }, function () { root.classList.remove('mode-vt'); });
  else { root.classList.remove('mode-vt'); replay(m === 'resident' ? $('#rWrap') : $('#content')); }
  clearInterval(driftTimer); $('#rWrap').style.transform = '';
  if (m === 'resident') {
    if (S.set.drift) driftTimer = setInterval(function () { $('#rWrap').style.transform = 'translate(' + Math.round(rnd(-10, 10)) + 'px,' + Math.round(rnd(-8, 8)) + 'px)'; }, 60000);
    hideHintSoon();
    setTimeout(function () { $('#resident').focus({ preventScroll: true }); }, 60);
  } else { $('#resident').classList.remove('nocursor'); resetIdle(); }
}
function enterResident() { closeBrain(); setMode('resident'); }
function exitResident() {
  if (root.dataset.mode !== 'resident' || leaving) return;
  if (!animOK() || !$('#resident .rc-svg')) { setMode('normal'); return; }
  leaving = true; $('#rHint').classList.remove('on');
  var d = ringOut();
  setTimeout(function () { leaving = false; setMode('normal'); }, d - 80);
}
function hideHintSoon() {
  clearTimeout(hintTimer);
  hintTimer = setTimeout(function () { $('#rHint').classList.remove('on'); if (S.set.hideCursor) $('#resident').classList.add('nocursor'); }, 2500);
}
$('#resident').addEventListener('pointermove', function () { if (leaving) return; $('#rHint').classList.add('on'); $('#resident').classList.remove('nocursor'); hideHintSoon(); });
$('#resident').addEventListener('click', exitResident);
$('#btnResident').addEventListener('click', enterResident);
$('#clockTop').addEventListener('click', enterResident);
function resetIdle() {
  clearTimeout(idleT);
  var mins = parseFloat(S.set.idleRes);
  if (mins > 0 && root.dataset.mode === 'normal') idleT = setTimeout(enterResident, mins * 60000);
}
['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(function (ev) {
  window.addEventListener(ev, function () { if (root.dataset.mode === 'normal') resetIdle(); }, { passive: true });
});
document.addEventListener('visibilitychange', function () { root.classList.toggle('paused', document.hidden); if (document.hidden) stopHW(); else { startHW(); poll(); } });
document.addEventListener('keydown', function (e) {
  var tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.ctrlKey || e.metaKey || e.altKey) return;
  var res = root.dataset.mode === 'resident';
  if (e.key === 'Escape') { if (res) exitResident(); else closeBrain(); }
  else if (e.key === 'r' || e.key === 'R') { if (res) exitResident(); else enterResident(); }
  else if (e.key === 'f' || e.key === 'F') toggleFull();
  else if (e.key === 't' || e.key === 'T') cycleTheme(innerWidth / 2, innerHeight / 2);
  else if (res && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); exitResident(); }
});
