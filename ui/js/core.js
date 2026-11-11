'use strict';
/* ================= 主页中间那颗「核心」（v3.0）=================
   一块画布，画的全是真状态，不是装饰：
   - 一颗点阵球：闲着是主题色、慢慢转；Agent 在干活变成「干活色」（琥珀）、转得快；
   - 外面一圈 = 计划：它列了几步就分几段，做完的一段亮绿、正在做的那段在跳、没做的是暗线；没列计划就是一段来回扫的弧；
   - 每做一步（写文件、运行、看画面……），球上冒出这一步的名字往上飘、荡开一圈；
   - 说话 / 听写的时候，最外面一圈跟着声音大小跳（js/voice.js 喂进来）；一件事做完闪一下绿。
   省资源：一秒 30 帧；窗口不在前面、不在主页、常驻屏、省电模式、动效关着的时候不连续画（只在状态变了时画一帧）。
   颜色从主题变量读（--accent / --hot / --ok / --bad / --h5），换深浅色跟着变；浅色底不用叠加发光。 */
var CORE = { cv: null, ctx: null, W: 0, H: 0, dpr: 1, t: 0, last: 0, raf: 0, state: 'idle', over: null, plan: [], level: 0, lv: 0, pulses: [], labels: [], pts: [], eid: null, nstep: 0,
  col: null, colKey: '', rot: 0, speed: .2, mix: 0, sweep: 0, word: '', sub: '', ro: null, doneAt: 0, light: false };

(function () {                                          // 球上的点：斐波那契点阵，挖掉几块（像被侵蚀过）
  for (var k = 0, N = 1500; k < N; k++) {
    var y = 1 - 2 * (k + .5) / N, rr = Math.sqrt(1 - y * y), ph = k * 2.399963, x = Math.cos(ph) * rr, z = Math.sin(ph) * rr;
    if (Math.sin(5.1 * x + 1.3) * Math.sin(4.7 * y + 2.1) * Math.sin(5.3 * z + .7) > .3) continue;
    CORE.pts.push({ x: x, y: y, z: z, fam: Math.sin(2.2 * x + 3 * y) + Math.cos(2.6 * z - y) > .2 ? 0 : 1, j: (k * 7.13) % 6.28 });
  }
})();

function coreRGB(v) {                                   // 任何 CSS 颜色 → [r,g,b]
  var c = CORE.ctx; c.fillStyle = '#000'; c.fillStyle = v; var h = c.fillStyle;
  if (h.charAt(0) === '#') return [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)];
  var m = h.match(/[\d.]+/g) || [0, 0, 0]; return [+m[0], +m[1], +m[2]];
}
function coreColors() {
  var key = root.dataset.theme + '|' + (S.set.theme || '');
  if (CORE.col && CORE.colKey === key) return CORE.col;
  var cs = getComputedStyle(root), g = function (n, d) { var v = cs.getPropertyValue(n).trim(); return coreRGB(v || d); };
  CORE.light = cs.colorScheme === 'light' || root.dataset.theme === 'light';
  CORE.col = { a: g('--accent', '#3fe0ff'), hot: g('--hot', '#ffb02e'), ok: g('--ok', '#3dffa8'), bad: g('--bad', '#ff5470'), mag: g('--h5', '#ff5fd2'), dim: g('--text3', '#7393a8'), tx: g('--text', '#fff') };
  CORE.colKey = key; return CORE.col;
}
function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + Math.max(0, Math.min(1, a)).toFixed(3) + ')'; }
function mixc(a, b, t) { return [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)]; }

function coreMount(cv) {
  CORE.cv = cv; CORE.ctx = cv.getContext('2d'); CORE.col = null;
  if (CORE.ro) CORE.ro.disconnect();
  var fit = function () {
    var r = cv.getBoundingClientRect(); if (!r.width || !r.height) return;
    CORE.dpr = Math.min(window.devicePixelRatio || 1, 1.5); CORE.W = r.width; CORE.H = r.height;
    cv.width = Math.round(r.width * CORE.dpr); cv.height = Math.round(r.height * CORE.dpr);
    coreDraw(0);
  };
  if (window.ResizeObserver) { CORE.ro = new ResizeObserver(fit); CORE.ro.observe(cv.parentNode); }
  fit(); coreLoop();
}
function coreActive() {                                  // 该不该连续画
  return CORE.cv && CORE.cv.isConnected && !document.hidden && S.view === 'home' && root.dataset.mode === 'normal' && root.dataset.motion !== 'off' && root.dataset.perf !== 'on';
}
function coreLoop() {
  cancelAnimationFrame(CORE.raf);
  CORE.raf = requestAnimationFrame(function tick(ts) {
    if (!CORE.cv || !CORE.cv.isConnected) return;
    if (coreActive()) { if (ts - CORE.last >= 30) { var dt = Math.min(.08, (ts - CORE.last) / 1000 || .033); CORE.last = ts; coreDraw(dt); } }
    else CORE.last = ts;
    CORE.raf = requestAnimationFrame(tick);
  });
}
document.addEventListener('visibilitychange', function () { if (!document.hidden && CORE.cv) coreDraw(0); });

/* 主页每次刷新都来对一下：现在该是什么状态、计划几步、有没有新做的一步 */
function coreSync() {
  if (!CORE.cv) return;
  var live = typeof nowLive === 'function' ? nowLive() : null, st = CORE.over || (live ? 'work' : 'idle');
  if (live) {
    var n = (live.steps || []).length;
    if (CORE.eid !== live.id) { CORE.eid = live.id; CORE.nstep = n; corePulse('hot'); }
    else if (n > CORE.nstep) {
      var s = live.steps[n - 1]; CORE.nstep = n;
      if (s && s[0] !== '计划') coreLabel(s[0], String(s[1] || '').replace(/\s+/g, ' ').slice(0, 26)); corePulse('hot');
    }
    CORE.plan = (live.plan || []).map(function (p) { return p.st; });
  } else {
    if (CORE.eid != null && CORE.state === 'work') {      // 刚做完
      var ev = (typeof homeEvs === 'function' ? homeEvs() : []).filter(function (e) { return e.id === CORE.eid; })[0];
      corePulse(ev && ev.status === 'error' ? 'bad' : 'ok'); CORE.doneAt = CORE.t;
    }
    CORE.eid = null; CORE.nstep = 0;
    var v = typeof nowView === 'function' ? nowView() : null; CORE.plan = v && NOW.sel != null ? (v.plan || []).map(function (p) { return p.st; }) : [];
  }
  CORE.state = st;
  var word, sub;
  if (st === 'listen') { word = '在听'; sub = '说完停一下就发出去 · 再点一下取消'; }
  else if (st === 'think') { word = '在认字'; sub = '把你说的话变成文字'; }
  else if (st === 'speak') { word = '在说'; sub = '点一下核心打断'; }
  else if (st === 'work') { var pc = live && planCount(live); word = '干活中'; sub = (live.engine === 'cc' ? 'Claude Code · ' : '') + (pc ? '计划 ' + pc + ' · ' : '') + '做了 ' + Math.max(0, (live.steps || []).length - 1) + ' 步'; }
  else { word = '待命'; sub = (typeof voiceReady === 'function' && voiceReady()) ? '点一下核心说话' : '在下面打字，回车就发'; }
  if (word !== CORE.word) { CORE.word = word; var w = $('#coreWord'); if (w) w.textContent = word; }
  if (sub !== CORE.sub) { CORE.sub = sub; var sb = $('#coreSub'); if (sb) sb.textContent = sub; }
  var nc = $('#nwCore'); if (nc) nc.dataset.st = st;
  if (!coreActive()) coreDraw(0);
}
function coreOver(st) { CORE.over = st || null; coreSync(); }            // 语音那边：'listen' / 'think' / 'speak' / null
function coreLevel(v) { CORE.level = Math.max(0, Math.min(1, v || 0)); }  // 语音那边：现在声音多大（0~1）
function corePulse(c) { if (CORE.pulses.length < 6) CORE.pulses.push({ t: CORE.t, c: c || 'a' }); }
function coreLabel(a, b) { CORE.labels.push({ t: CORE.t, a: a, b: b || '' }); if (CORE.labels.length > 3) CORE.labels.shift(); }

function coreDraw(dt) {
  var c = CORE.ctx, W = CORE.W, H = CORE.H; if (!c || !W || !H) return;
  var col = coreColors(), light = CORE.light, st = CORE.state, busy = st === 'work', voice = st === 'listen' || st === 'speak';
  CORE.t += dt; var now = CORE.t;
  c.setTransform(CORE.dpr, 0, 0, CORE.dpr, 0, 0); c.clearRect(0, 0, W, H);
  var cx = W / 2, cy = H * .46, R = Math.min(W * .25, H * .232);
  CORE.mix += ((busy ? 1 : 0) - CORE.mix) * Math.min(1, dt * 3 || 1);
  CORE.speed += ((busy ? .9 : voice ? .5 : .16) - CORE.speed) * Math.min(1, dt * 2 || 1); CORE.rot += CORE.speed * dt;
  CORE.lv += (CORE.level - CORE.lv) * Math.min(1, dt * 14 || 1);
  var main = st === 'listen' ? col.ok : mixc(col.a, col.hot, CORE.mix), add = light ? 'source-over' : 'lighter', A = light ? 1.5 : 1;

  // 背后的光
  if (!light) {
    var g = c.createRadialGradient(cx, cy, R * .2, cx, cy, R * 2.2); g.addColorStop(0, rgba(main, .13 + CORE.lv * .12)); g.addColorStop(1, rgba(main, 0));
    c.fillStyle = g; c.fillRect(cx - R * 2.3, cy - R * 2.3, R * 4.6, R * 4.6);
  }
  // 球
  c.globalCompositeOperation = add;
  var cr = Math.cos(CORE.rot), sr = Math.sin(CORE.rot), tilt = .36 + Math.sin(now * .23) * .1, ct = Math.cos(tilt), stl = Math.sin(tilt), Rs = R * (.9 + CORE.lv * .08), cam = Rs * 3.2;
  var alt = busy ? col.a : col.mag, fills = [[], []];
  for (var q = 0; q < 6; q++) { fills[0].push(rgba(main, (.14 + q * .15) * A)); fills[1].push(rgba(alt, (.1 + q * .12) * A)); }
  for (var i = 0; i < CORE.pts.length; i++) {
    var p = CORE.pts[i], n = 1 + .06 * Math.sin(3 * p.x + now * 1.2) * Math.cos(3 * p.y + now * .9) + (busy ? .03 : 0) * Math.sin(9 * p.z + now * 7 + p.j) + CORE.lv * .1 * Math.sin(p.j + now * 9);
    var x = p.x * n, y = p.y * n, z = p.z * n, x1 = x * cr - z * sr, z1 = x * sr + z * cr, y1 = y * ct - z1 * stl, z2 = y * stl + z1 * ct;
    var f = cam / (cam + z2 * Rs), dep = (1 - z2) / 2, sz = .8 + dep * 2;
    c.fillStyle = fills[p.fam][Math.min(5, Math.floor(dep * 6))]; c.fillRect(cx + x1 * Rs * f, cy + y1 * Rs * f, sz, sz);
  }
  c.globalCompositeOperation = 'source-over';

  c.save(); c.translate(cx, cy);
  // 刻度
  c.rotate(-now * .04);
  for (var k = 0; k < 96; k++) { var a = k / 96 * 6.2832, l = k % 8 === 0 ? R * .07 : R * .03; c.strokeStyle = rgba(main, k % 8 === 0 ? .7 : .3); c.lineWidth = 1; c.beginPath(); c.moveTo(Math.cos(a) * R * 1.62, Math.sin(a) * R * 1.62); c.lineTo(Math.cos(a) * (R * 1.62 - l), Math.sin(a) * (R * 1.62 - l)); c.stroke(); }
  c.rotate(now * .04);
  // 虚线环
  c.lineWidth = 1.2; c.strokeStyle = rgba(main, .4); c.setLineDash([R * .09, R * .05]); c.lineDashOffset = now * 30; c.beginPath(); c.arc(0, 0, R * 1.12, 0, 6.2832); c.stroke(); c.setLineDash([]);
  // 计划环：一段一步
  var pr = R * 1.28, pl = CORE.plan, top = -Math.PI / 2;
  if (pl.length) {
    var gap = pl.length > 1 ? .06 : 0, seg = 6.2832 / pl.length;
    for (var s = 0; s < pl.length; s++) {
      var a0 = top + s * seg + gap / 2, a1 = top + (s + 1) * seg - gap / 2, ps = pl[s];
      c.beginPath(); c.arc(0, 0, pr, a0, a1);
      if (ps === 'done') { c.strokeStyle = rgba(col.ok, .95); c.lineWidth = 5; if (!light) { c.shadowColor = rgba(col.ok, .8); c.shadowBlur = 10; } }
      else if (ps === 'doing') { c.strokeStyle = rgba(col.hot, .55 + .45 * Math.abs(Math.sin(now * 3))); c.lineWidth = 6; if (!light) { c.shadowColor = rgba(col.hot, .9); c.shadowBlur = 16; } }
      else { c.strokeStyle = rgba(col.dim, .35); c.lineWidth = 3; }
      c.stroke(); c.shadowBlur = 0;
      if (ps === 'doing') { var am = a0 + (a1 - a0) * ((now * .6) % 1); c.fillStyle = '#fff'; c.beginPath(); c.arc(Math.cos(am) * pr, Math.sin(am) * pr, 3.2, 0, 6.2832); c.fill(); }
    }
  } else {
    c.lineWidth = 3; c.strokeStyle = rgba(main, .14); c.beginPath(); c.arc(0, 0, pr, 0, 6.2832); c.stroke();
    if (busy) {                                            // 没列计划：一段弧来回扫
      CORE.sweep += dt * 2.2; c.lineWidth = 5; c.strokeStyle = rgba(col.hot, .95); if (!light) { c.shadowColor = rgba(col.hot, .9); c.shadowBlur = 14; }
      c.beginPath(); c.arc(0, 0, pr, CORE.sweep, CORE.sweep + 1.1 + Math.sin(now * 2) * .5); c.stroke(); c.shadowBlur = 0;
    }
  }
  // 最外面一圈：跟着声音 / 干活的劲头跳
  var bars = 120, r0 = R * 1.4, amp = voice ? .05 + CORE.lv * .5 : busy ? .11 : .035;
  for (var b = 0; b < bars; b++) {
    var ba = b / bars * 6.2832, nn = Math.abs(Math.sin(b * .37 + now * (busy || voice ? 5.5 : 1.2)) * Math.cos(b * .11 - now * (busy || voice ? 3.1 : .7)));
    var bl = R * (.015 + nn * amp); c.strokeStyle = rgba(main, .2 + nn * .65); c.lineWidth = 2;
    c.beginPath(); c.moveTo(Math.cos(ba) * r0, Math.sin(ba) * r0); c.lineTo(Math.cos(ba) * (r0 + bl), Math.sin(ba) * (r0 + bl)); c.stroke();
  }
  // 绕着转的三颗小卫星
  var sats = [[1.12, 1.0, main], [1.62, -.45, col.mag], [1.4, .7, col.ok]];
  for (var sI = 0; sI < sats.length; sI++) {
    var sa = now * sats[sI][1] * (busy ? 1.8 : 1) + sI * 2.1, sc = sats[sI][2], rr2 = R * sats[sI][0];
    for (var tl = 0; tl < 12; tl++) { var tb = sa - tl * .045 * (sats[sI][1] < 0 ? -1 : 1); c.fillStyle = rgba(sc, (1 - tl / 12) * .85); c.fillRect(Math.cos(tb) * rr2 - 1.4, Math.sin(tb) * rr2 - 1.4, 2.8, 2.8); }
  }
  // 荡开的圈
  for (var w = CORE.pulses.length - 1; w >= 0; w--) {
    var pu = CORE.pulses[w], age = now - pu.t; if (age > 1.1 || age < 0) { CORE.pulses.splice(w, 1); continue; }
    var pc = pu.c === 'ok' ? col.ok : pu.c === 'bad' ? col.bad : pu.c === 'hot' ? col.hot : main;
    c.beginPath(); c.arc(0, 0, R * (1 + age * 1.1), 0, 6.2832); c.lineWidth = 3 * (1 - age / 1.1); c.strokeStyle = rgba(pc, .8 * (1 - age / 1.1)); c.stroke();
  }
  // 四个方向的小刻线
  c.strokeStyle = rgba(main, .65); c.lineWidth = 1.5;
  [[0, -1], [0, 1], [-1, 0], [1, 0]].forEach(function (d) { c.beginPath(); c.moveTo(d[0] * R * 1.7, d[1] * R * 1.7); c.lineTo(d[0] * R * 1.8, d[1] * R * 1.8); c.stroke(); });
  c.restore();

  // 每一步冒出来的字
  var fs = Math.max(13, Math.min(18, R * .13)), font = getComputedStyle(document.body).fontFamily;
  c.textAlign = 'center'; c.textBaseline = 'middle';
  for (var li = CORE.labels.length - 1; li >= 0; li--) {
    var lb = CORE.labels[li], la = now - lb.t; if (la > 2.6) { CORE.labels.splice(li, 1); continue; }
    var op = la < .25 ? la / .25 : 1 - Math.max(0, (la - 1.6)) / 1, ly = cy - R * .1 - la * R * .28;
    c.globalAlpha = Math.max(0, op);
    c.font = '700 ' + fs + 'px ' + font; c.fillStyle = light ? rgba(col.tx, 1) : '#fff'; if (!light) { c.shadowColor = rgba(col.hot, .9); c.shadowBlur = 12; }
    c.fillText(lb.a, cx, ly); c.shadowBlur = 0;
    if (lb.b) { c.font = '500 ' + (fs * .78) + 'px ' + font; c.fillStyle = rgba(light ? col.tx : col.hot, .9); c.fillText(lb.b, cx, ly + fs * 1.25); }
    c.globalAlpha = 1;
  }
}
