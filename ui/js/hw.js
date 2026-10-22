'use strict';
/* ================= 硬件 ================= */
var HW = { src: 'demo', ok: true,
  cpu: { name: 'Ryzen 5 5600', load: 0, clock: 0, temp: 0, power: 0 },
  gpu: { name: 'RTX 5060 Ti', load: 0, clock: 0, temp: 0, power: 0, vram: 0, vramTotal: 16, vramPct: 0 },
  ram: { load: 0, used: 0, total: 32, freq: 3600 },
  sys: { power: 0 },
  disks: [{ n: 'NVMe 固态', temp: 0 }, { n: '机械盘 1', temp: 0 }, { n: '机械盘 2', temp: 0 }] };
var HIST = { cpu: [], gpu: [], ram: [], vram: [], pw: [], fps: [] }, HN = 60;
var sim = { cpu: 10, gpu: 5, game: 0, cpuT: 42, gpuT: 37, ram: 11.4, n0: 40, n1: 34, n2: 33 };
function calcSys() {
  var cp = HW.cpu.power || 0, gp = HW.gpu.power || 0, other = +S.set.sysOther || 0, eff = (+S.set.psuEff || 89) / 100;
  HW.sys.power = (cp + gp + other) / eff;
}
function simStep() {
  if (sim.game > 0) sim.game--; else if (Math.random() < 0.035) sim.game = Math.floor(rnd(10, 30));
  var gT = sim.game ? rnd(68, 97) : rnd(2, 11);
  var cT = sim.game ? rnd(32, 58) : rnd(3, 17) + (Math.random() < 0.07 ? rnd(20, 45) : 0);
  sim.cpu += (cT - sim.cpu) * 0.5; sim.gpu += (gT - sim.gpu) * 0.45;
  sim.cpuT += ((40 + sim.cpu * 0.42) - sim.cpuT) * 0.25; sim.gpuT += ((35 + sim.gpu * 0.36) - sim.gpuT) * 0.18;
  sim.ram += ((sim.game ? 15.5 : 11.2) + rnd(-0.3, 0.3) - sim.ram) * 0.15;
  sim.n0 += ((39 + sim.cpu * 0.08) + rnd(-.3, .3) - sim.n0) * 0.1; sim.n1 += (34 + rnd(-.2, .2) - sim.n1) * 0.05; sim.n2 += (33 + rnd(-.2, .2) - sim.n2) * 0.05;
  HW.cpu = { name: 'Ryzen 5 5600', load: sim.cpu, clock: 3.55 + Math.min(1, sim.cpu / 35) * 0.85 + rnd(-.05, .05), temp: sim.cpuT, power: 20 + sim.cpu * 0.85 };
  HW.gpu = { name: 'RTX 5060 Ti', load: sim.gpu, clock: sim.gpu > 20 ? rnd(2650, 2850) : rnd(210, 620), temp: sim.gpuT, power: 14 + sim.gpu * 1.55,
    vram: 3.6 + (sim.game ? 5.2 : 0) + rnd(-.05, .05), vramTotal: 16 };
  HW.gpu.vramPct = HW.gpu.vram / HW.gpu.vramTotal * 100;
  HW.ram = { used: sim.ram, total: 32, load: sim.ram / 32 * 100, freq: 3600, desc: '32 GB DDR4 · 2 条' };
  HW.disks = [{ n: 'NVMe 固态', temp: sim.n0 }, { n: '机械盘 1', temp: sim.n1 }, { n: '机械盘 2', temp: sim.n2 }];
  HW.fps = sim.game ? { fps: Math.round(rnd(128, 144)), low1: +rnd(86, 101).toFixed(1), proc: 'Palworld-Win64-Shipping.exe' } : null;
  calcSys(); HW.src = 'demo'; HW.ok = true;
}
function liveHW() { return useLive() && S.set.hwSource !== 'demo'; }
function pushAll() { push('cpu', HW.cpu.load); push('gpu', HW.gpu.load); push('ram', HW.ram.load); push('vram', HW.gpu.vramPct); push('pw', HW.sys.power); if (HW.fps) push('fps', HW.fps.fps); else HIST.fps = []; }
function push(k, v) { if (v == null || isNaN(v)) return; HIST[k].push(v); if (HIST[k].length > HN) HIST[k].shift(); }
function sampleHW() {
  var p;
  if (liveHW()) p = api('GET', '/api/hw', null, 3000).then(function (j) {
    HW.cpu = j.cpu; HW.gpu = j.gpu; HW.ram = j.ram; HW.sys = j.sys; HW.ok = true; HW.src = j.src; HW.sources = j.sources; HW.fps = j.fps || null;
    HW.disks = j.disks && j.disks.length ? j.disks : [];
    var sig = HW.cpu.name + '|' + HW.gpu.name + '|' + (HW.ram.desc || '') + '|' + HW.disks.map(function (d) { return d.n; }).join(',');
    if (sig !== hwSig) { hwSig = sig; if (root.dataset.mode === 'resident') updateResidentNames(); else renderResident(); }
  }).catch(function () { HW.ok = false; });
  else { simStep(); p = Promise.resolve(); }
  return p.then(function () { if (HW.ok) pushAll(); renderHW(); });
}
function getPath(p) { var o = HW; p.split('.').forEach(function (k) { o = o == null ? null : o[k]; }); return o; }
function renderHW() {
  var res = root.dataset.mode === 'resident';
  $$('[data-hw]').forEach(function (el) {
    var v = getPath(el.dataset.hw), f = el.dataset.fmt || 'int';
    if (v == null || isNaN(v)) { el.textContent = '—'; el.classList.add('na'); delete el.dataset.cur; return; }
    el.classList.remove('na');
    var dec = f === 'f1' ? 1 : f === 'f2' ? 2 : 0, suf = f === 'temp' ? '°C' : '';
    if (res && el.hasAttribute('data-tw')) tweenTo(el, +(+v).toFixed(dec), dec, suf); else el.textContent = (+v).toFixed(dec) + suf;
  });
  $$('[data-hwbar]').forEach(function (el) { var v = getPath(el.dataset.hwbar) || 0, mx = +(el.dataset.max || 100); el.style.transform = 'scaleX(' + Math.max(0, Math.min(1, v / mx)).toFixed(3) + ')'; });
  // 游戏帧数：有游戏在跑才显示（常驻页的 FPS 块、顶栏的 FPS）
  var f = HW.fps, ft = $('#rtFps'), mf = $('#mFps');
  if (ft) ft.hidden = !f;
  if (mf) { mf.hidden = !f; if (f) $('#mFpsV').textContent = f.fps; }
  if (f) {
    var fpsMax = Math.max(60, Math.ceil(Math.max.apply(null, HIST.fps.concat([f.fps])) / 30) * 30 + 15);
    var sl = $('[data-spark="fps"]'); if (sl) sl.dataset.max = fpsMax;
    var pn = $('#fpsProc'); if (pn) pn.textContent = (f.proc || '').replace(/\.exe$/i, '');
  }
  $$('[data-spark]').forEach(function (el) {
    var a = HIST[el.dataset.spark] || [], n = a.length, mx = +(el.dataset.max || 100); if (n < 2) return;
    var pts = a.map(function (v, i) { return ((HN - n + i) / (HN - 1) * 120).toFixed(1) + ',' + (31 - Math.max(0, Math.min(mx, v)) / mx * 29).toFixed(1); }).join(' ');
    el.setAttribute('points', pts);
    var area = el.previousElementSibling; if (area) area.setAttribute('points', pts + ' 120,32 ' + ((HN - n) / (HN - 1) * 120).toFixed(1) + ',32');
  });
  var src = $('#rSrc');
  if (src) src.textContent = !liveHW() ? '硬件数据：演示 · 整机功耗为估算' : !HW.ok ? '硬件数据：连不上后端' :
    (HW.sources && HW.sources.sensors ? '硬件数据：传感器 + 显卡驱动 · 整机功耗为估算' : '硬件数据：显卡驱动 + 系统（CPU 温度要运行 硬件监控.bat）· 整机功耗为估算');
}
var hwTimer = null, hwSig = '';
function diskTileBody() {
  return HW.disks.length ? HW.disks.map(function (d, i) { return '<div class="drow"><span>' + esc(d.n) + '</span><b>' + hw('disks.' + i + '.temp', 'temp') + '</b><div class="bar1"><i data-hwbar="disks.' + i + '.temp" data-max="70" style="transform:scaleX(0)"></i></div></div>'; }).join('')
    : '<div class="cap">读不到：运行 硬件监控.bat 后显示</div>';
}
function updateResidentNames() { var rd = $('#ramDesc'); if (rd && HW.ram.desc) rd.textContent = HW.ram.desc; var b = $('#diskBody'); if (b) b.innerHTML = diskTileBody(); var c = $('#diskCount'); if (c) c.textContent = HW.disks.length + ' 块'; renderHW(); }
function startHW() {
  stopHW();
  if (!liveHW() && !HIST.cpu.length) { for (var i = 0; i < HN - 1; i++) { simStep(); pushAll(); } }
  if (liveHW()) {
    HIST = { cpu: [], gpu: [], ram: [], vram: [], pw: [], fps: [] };
    api('GET', '/api/hw/history', null, 3000).then(function (h) {   // 后台一直在记，打开界面时走势线直接是满的
      Object.keys(HIST).forEach(function (k) { if (h[k] && HIST[k].length < 3) HIST[k] = h[k].filter(function (v) { return v != null; }).slice(-HN); });
      renderHW();
    }).catch(function () {});
  }
  sampleHW();
  hwTimer = setInterval(sampleHW, (+S.set.hwInterval || 2) * 1000);
}
function stopHW() { if (hwTimer) clearInterval(hwTimer); hwTimer = null; }
function hw(path, fmt, tw) { return '<span data-hw="' + path + '" data-fmt="' + (fmt || 'int') + '"' + (tw ? ' data-tw' : '') + '>—</span>'; }

/* ================= 数据来源：真实 / 演示 ================= */
function evs() { return useLive() ? D.events : EVENTS; }
function findEv(id) { return evs().filter(function (e) { return e.id === id; })[0]; }
function weekData() { return useLive() ? ((D.report && D.report.week) || []).map(function (w) { return [w[0], w[1]]; }) : WEEK; }
function todaySplit() {
  if (useLive()) return (D.state && D.state.today) || { local: 0, neu: 0, ds: 0, cl: 0 };
  var c = { local: 0, neu: 0, ds: 0, cl: 0 }; EVENTS.forEach(function (e) { c[e.to]++; }); return c;
}
function nextRem() {
  if (useLive()) return D.state && D.state.next;
  var now = new Date(), t = new Date(now); t.setHours(22, 0, 0, 0); if (t <= now) t.setDate(t.getDate() + 1);
  return { title: '吃药', at: '22:00', ts: t.getTime() / 1000 };
}
/* DeepSeek：余额来自官方接口（后端每 10 分钟查一次，调用过后 1 分钟内再查），花费是本机按 token 估算的 */
function budget() {
  if (!useLive()) return { key: true, total: 8.59, low: false, cost: 0.41, ts: Date.now() / 1000 };
  var b = (D.state && D.state.balance) || {};
  return { key: !!b.key, total: b.total, low: !!b.low, err: b.err, ts: b.ts, cost: (D.state && D.state.cost_month) || 0 };
}
function pendingAsks() { if (useLive()) return (D.state && D.state.asks_pending) || 0; return ASKS.filter(function (c) { return !S.done['a' + c.id]; }).length; }

/* ================= 提醒倒计时 ================= */
function updateReminder() {
  var n = nextRem(), a = $('#remLeft'), b = $('#rNextLeft'), ring = $('#remRing');
  if (!n) { if (a) a.textContent = '没有打开的提醒'; if (b) b.textContent = '没有打开的提醒'; setRing(ring, 0, 'var(--c-local)'); return; }
  var mins = Math.max(0, Math.round((n.ts * 1000 - Date.now()) / 60000)), h = Math.floor(mins / 60), m = mins % 60;
  var left = '还有 ' + (h ? h + ' 小时 ' : '') + m + ' 分';
  if (a) a.textContent = n.title + ' · ' + left;
  if (b) b.textContent = n.at + ' ' + n.title + ' · ' + left;
  var big = $('#remAt'); if (big && big.textContent !== n.at) big.textContent = n.at;
  setRing(ring, Math.max(2, 100 - mins / (24 * 60) * 100), 'var(--c-local)');
}
