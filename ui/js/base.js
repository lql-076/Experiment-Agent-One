'use strict';
var $ = function (s, r) { return (r || document).querySelector(s); };
var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
var root = document.documentElement;
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function rnd(a, b) { return a + Math.random() * (b - a); }
function pad(n) { return n < 10 ? '0' + n : '' + n; }

function toast(msg, ms) {
  var el = document.createElement('div');
  el.className = 'toast'; el.textContent = msg;
  $('#toasts').appendChild(el);
  requestAnimationFrame(function () { requestAnimationFrame(function () { el.classList.add('in'); }); });
  setTimeout(function () { el.classList.remove('in'); setTimeout(function () { el.remove(); }, 400); }, ms || 2800);
}
function fetchT(url, opt, ms) {
  var ac = window.AbortController ? new AbortController() : null;
  var t = setTimeout(function () { if (ac) ac.abort(); }, ms || 1500);
  opt = Object.assign({ cache: 'no-store' }, opt || {}); if (ac) opt.signal = ac.signal;
  return fetch(url, opt).then(function (r) { clearTimeout(t); return r; }, function (e) { clearTimeout(t); throw e; });
}
function api(method, path, body, ms) {
  var opt = { method: method, headers: method === 'GET' ? {} : { 'X-Agent': '1' } };
  if (body !== undefined && body !== null) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  return fetchT(path, opt, ms || 20000).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.detail || j.msg || ('出错了 ' + r.status)); return j; });
  });
}
var ICONS = {
  ext: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></svg>',
  check: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  cross: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
  dash: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 12h10"/></svg>',
  eye: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true" width="18" height="18"><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  brain: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="7" cy="8" r="2.5"/><circle cx="17" cy="8" r="2.5"/><circle cx="12" cy="17" r="2.5"/><path d="M8.3 10.2l2.4 4.6M15.7 10.2l-2.4 4.6M9.5 8h5"/></svg>',
  file: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8.5L18 7v13.5H6z"/><path d="M9 11h6M9 14.5h6"/></svg>',
  clock: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/></svg>',
  tool: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 5.5a4 4 0 0 0 4.9 4.9l-8.6 8.6a2 2 0 0 1-2.8-2.8l8.6-8.6"/></svg>',
  trash: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13"/></svg>',
  coin: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M9 9.5h6M9 13h6M12 9.5V17"/></svg>',
  full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  unfull: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
  land: '<rect x="3.5" y="6.5" width="17" height="11" rx="2"/>',
  port: '<rect x="6.5" y="3.5" width="11" height="17" rx="2"/>',
  auto: '<rect x="3.5" y="6.5" width="11" height="8" rx="1.5"/><rect x="14" y="9" width="6.5" height="11" rx="1.5"/>'
};
var KIND_ICON = { 'memory.write': 'file', 'reminder.create': 'clock', 'reminder.update': 'clock', 'brain.create': 'brain', 'prompt.update': 'file',
  money: 'coin', 'file.delete': 'trash', 'tool.add': 'tool', 'privacy.send': 'tool' };
var KIND_COLOR = { 'memory.write': 'var(--accent)', 'reminder.create': 'var(--c-neu)', 'brain.create': 'var(--c-local)', money: 'var(--c-cl)', 'file.delete': 'var(--bad)' };
function money(v) { return v == null || isNaN(v) ? '—' : '¥' + (+v).toFixed(2); }
function copyText(t) {
  if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(t).then(function () { toast('已复制'); }, function () { toast('复制失败，手动选中复制吧'); });
  toast('这里不能自动复制，手动选中复制吧');
}

/* ================= 数字动画 ================= */
var tweens = [], twOn = false;
function tweenTo(el, to, dec, suf) {
  suf = suf || '';
  var from = parseFloat(el.dataset.cur);
  el.dataset.cur = to;
  if (isNaN(from) || from === to || S.set.motion === 'off' || document.hidden) { el.textContent = to.toFixed(dec) + suf; return; }
  tweens = tweens.filter(function (t) { return t.el !== el; });
  tweens.push({ el: el, from: from, to: to, dec: dec, suf: suf, t0: performance.now(), d: S.set.motion === 'reduced' ? 250 : 650 });
  if (!twOn) { twOn = true; requestAnimationFrame(twLoop); }
}
function twLoop(now) {
  tweens = tweens.filter(function (t) {
    var p = Math.min(1, (now - t.t0) / t.d), e = 1 - Math.pow(1 - p, 3);
    t.el.textContent = (t.from + (t.to - t.from) * e).toFixed(t.dec) + t.suf;
    return p < 1;
  });
  if (tweens.length) requestAnimationFrame(twLoop); else twOn = false;
}

/* ================= 环形图 / 走势线 ================= */
function donutHTML(r, sw, n, cls, id) {
  var s = '<svg class="donut ' + (cls || '') + '"' + (id ? ' id="' + id + '"' : '') + ' viewBox="0 0 200 200" aria-hidden="true"><circle class="d-track" cx="100" cy="100" r="' + r + '" style="stroke-width:' + sw + '"/>';
  for (var i = 0; i < n; i++) s += '<circle class="d-arc" cx="100" cy="100" r="' + r + '" transform="rotate(-90 100 100)" style="stroke-width:' + sw + ';stroke-dasharray:0 999"/>';
  return s + '</svg>';
}
function setDonut(svg, segs, gap) {
  if (!svg) return;
  var arcs = svg.querySelectorAll('.d-arc'), r = +arcs[0].getAttribute('r'), C = 2 * Math.PI * r;
  var tot = segs.reduce(function (a, g) { return a + g.v; }, 0), start = 0;
  gap = gap == null ? 3 : gap;
  segs.forEach(function (g, i) {
    var a = arcs[i]; if (!a) return;
    var len = tot ? Math.max(0, g.v / tot * C - (g.v ? gap : 0)) : 0;
    a.style.stroke = g.color;
    a.style.strokeDasharray = len.toFixed(2) + ' ' + C.toFixed(2);
    a.style.strokeDashoffset = (-start).toFixed(2);
    if (g.w) a.style.strokeWidth = g.w;
    a.classList.toggle('dim', !!g.dim);
    start += tot ? g.v / tot * C : 0;
  });
}
function setRing(svg, pct, color) {
  if (!svg) return;
  var a = svg.querySelector('.d-arc'), r = +a.getAttribute('r'), C = 2 * Math.PI * r;
  a.classList.add('round'); a.style.stroke = color;
  a.style.strokeDasharray = (Math.max(0, Math.min(100, pct)) / 100 * C).toFixed(2) + ' ' + C.toFixed(2);
  a.style.strokeDashoffset = '0';
}
function sparkHTML(key, max, h) {
  return '<svg class="spark" viewBox="0 0 120 32" preserveAspectRatio="none" aria-hidden="true"' + (h ? ' style="height:' + h + '"' : '') + '><polygon class="sa" points=""/><polyline class="sl" points="" data-spark="' + key + '" data-max="' + (max || 100) + '"/></svg>';
}
function weekBars(h, compact, data) {
  data = data || weekData();
  var mx = Math.max(60, Math.max.apply(null, data.map(function (w) { return w[1]; })) || 0);
  return '<div class="week" style="height:' + h + '">' + data.map(function (w, i) {
    return '<div class="wcol' + (i === data.length - 1 ? ' today' : '') + '" style="--i:' + i + '">' + (compact ? '' : '<b class="num">' + w[1] + '%</b>') +
      '<i style="height:' + Math.max(2, w[1] / mx * 100) + '%"></i><span class="num">' + (compact ? (i === data.length - 1 ? '今天' : w[0].slice(3)) : w[0]) + '</span></div>';
  }).join('') + '</div>';
}
