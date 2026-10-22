'use strict';
/* ================= 大脑 ================= */
function brainList() { return useLive() ? (D.brains || []) : BRAINS; }
function actLabel(a) { return typeof a === 'string' ? a : a.label; }
function renderBrains() {
  var v = $('#view-brains'), list = brainList();
  if (useLive() && !D.brains) { v.innerHTML = '<div class="empty">正在读取…</div>'; return; }
  v.innerHTML = '<div class="page fill"><div class="ph"><h1>大脑</h1><span class="sub">点一块，放大看它的成长记录</span></div><div class="bgrid">' +
    list.map(function (b, i) {
      return '<button class="bcard stag" data-b="' + i + '" style="--c:' + b.c + ';--i:' + i + '"><div class="dwrap bring">' + donutHTML(82, 12, 1) + '<div class="dc"><b class="num' + (String(b.ring[1]).length + String(b.ring[2]).length > 4 ? ' long' : '') + '">' + esc(b.ring[1]) + '<small>' + esc(b.ring[2]) + '</small></b><span>' + esc(b.ring[3]) + '</span></div></div>' +
        '<div><div class="k">' + esc(b.kind) + '</div><div class="n">' + esc(b.name) + '</div><div class="s">' + esc(b.sub) + '</div><span class="pill st">' + esc(b.st) + '</span></div>' +
        '<div class="bfoot">' + (b.stats || []).slice(0, 3).map(function (s) { return '<span><em>' + esc(s[0]) + '</em><b class="num">' + esc(s[1]) + (s[2] ? '<small>' + esc(s[2]) + '</small>' : '') + '</b></span>'; }).join('') + '</div>' +
        '<div class="bspark"><span class="label">近 7 天 · ' + esc(b.tl) + '</span>' + miniTrend(b) + '</div></button>';
    }).join('') + '</div></div>';
  requestAnimationFrame(function () { $$('.bcard').forEach(function (c) { var b = list[+c.dataset.b]; setRing(c.querySelector('.donut'), b.ring[0], b.c); }); });
}
function miniTrend(b) {
  var t = b.trend || [], n = t.length, mx = Math.max(b.tmax || 1, Math.max.apply(null, t.concat([1])));
  if (n < 2) return '';
  var pts = t.map(function (v, i) { return (i / (n - 1) * 100).toFixed(1) + ',' + (28 - Math.max(0, v) / mx * 26).toFixed(1); }).join(' ');
  return '<svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true" style="--tc:' + b.c + '"><polygon points="' + pts + ' 100,30 0,30" style="fill:var(--tc);opacity:.12"/><polyline points="' + pts + '" style="fill:none;stroke:var(--tc);stroke-width:1.6;vector-effect:non-scaling-stroke;stroke-linejoin:round"/></svg>';
}
function trendSVG(b) {
  var n = b.trend.length, mn = Math.min.apply(null, b.trend), mx = Math.max.apply(null, b.trend), span = Math.max(mx - mn, 1);
  var lo = Math.max(0, mn - span * .5), hi = Math.min(b.tmax, mx + span * .25); if (hi <= lo) hi = lo + 1;
  var pts = b.trend.map(function (v, i) { return [(i / Math.max(1, n - 1) * 100), (92 - (v - lo) / (hi - lo) * 72)]; });
  var line = pts.map(function (p) { return p[0].toFixed(2) + ',' + p[1].toFixed(2); }).join(' ');
  return '<div style="position:relative;--tc:' + b.c + '"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polygon points="' + line + ' 100,100 0,100" style="fill:var(--tc);opacity:.12"/><polyline points="' + line + '" style="fill:none;stroke:var(--tc);stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round"/></svg>' +
    pts.map(function (p, i) { return '<span class="tdot' + (i === n - 1 ? ' last' : '') + '" style="left:' + p[0] + '%;top:' + p[1] + '%"><em class="num">' + b.trend[i] + '</em></span>'; }).join('') + '</div>';
}
function dayLabels() { var out = []; for (var i = 6; i >= 0; i--) { var d = new Date(Date.now() - i * 864e5); out.push(i ? pad(d.getMonth() + 1) + '-' + pad(d.getDate()) : '今天'); } return out; }
function brainPanel(b) {
  return '<button class="ov-x" data-close="1" aria-label="关闭">×</button><div class="label">' + esc(b.kind) + '</div><div style="font-size:1.75rem;font-weight:600;margin-top:.25rem;color:' + b.c + '">' + esc(b.name) + '</div><div class="cap" style="margin-top:.25rem">' + esc(b.note) + '</div>' +
    '<div class="ov-top"><div class="dwrap" style="width:100%">' + donutHTML(82, 12, 1) + '<div class="dc"><b class="num">' + esc(b.ring[1]) + '<small>' + esc(b.ring[2]) + '</small></b><span class="cap">' + esc(b.ring[3]) + '</span></div></div>' +
    '<div class="stats">' + (b.stats || []).map(function (s) { return '<div class="stat"><span class="label">' + esc(s[0]) + '</span><b class="num">' + esc(s[1]) + (s[2] ? '<small style="font-size:.5em;color:var(--text3);margin-left:.2rem">' + esc(s[2]) + '</small>' : '') + '</b></div>'; }).join('') + '</div></div>' +
    '<div class="trend"><div class="label" style="margin-bottom:.5rem">近 7 天 · ' + esc(b.tl) + '</div>' + trendSVG(b) + '<div class="tdays">' + dayLabels().map(function (w) { return '<span>' + w + '</span>'; }).join('') + '</div></div>' +
    '<div class="btnrow">' + (b.acts || []).map(function (x, i) { return '<button class="btn" data-act-i="' + i + '">' + esc(actLabel(x)) + '</button>'; }).join('') + '</div>';
}
function openBrain(i) {
  var b = brainList()[i], card = $('.bcard[data-b="' + i + '"]'), ov = $('#ov'), pn = $('#ovPanel');
  S.bsel = i;
  var fill = function () { pn.innerHTML = brainPanel(b); ov.classList.add('on'); ov.setAttribute('aria-hidden', 'false'); requestAnimationFrame(function () { setRing(pn.querySelector('.donut'), b.ring[0], b.c); }); };
  if (!smooth() || !card) { fill(); pn.classList.remove('pop'); void pn.offsetWidth; pn.classList.add('pop'); return; }
  card.style.viewTransitionName = 'brainx';
  var t = document.startViewTransition(function () { card.style.viewTransitionName = ''; fill(); pn.style.viewTransitionName = 'brainx'; });
  t.finished.then(function () { pn.style.viewTransitionName = ''; }, function () { pn.style.viewTransitionName = ''; });
}
function closeBrain() {
  var ov = $('#ov'), pn = $('#ovPanel'); if (!ov.classList.contains('on')) return;
  var card = $('.bcard[data-b="' + S.bsel + '"]');
  var hide = function () { ov.classList.remove('on'); ov.setAttribute('aria-hidden', 'true'); };
  if (!smooth() || !card) { hide(); return; }
  pn.style.viewTransitionName = 'brainx';
  var t = document.startViewTransition(function () { pn.style.viewTransitionName = ''; hide(); card.style.viewTransitionName = 'brainx'; });
  t.finished.then(function () { card.style.viewTransitionName = ''; }, function () { card.style.viewTransitionName = ''; });
}
$('#view-brains').addEventListener('click', function (ev) { var t = ev.target.closest('.bcard'); if (t) openBrain(+t.dataset.b); });
$('#ov').addEventListener('click', function (ev) {
  var t = ev.target.closest('[data-close],[data-act-i]'); if (!t) return;
  if (t.dataset.close) { closeBrain(); return; }
  var b = brainList()[S.bsel], a = b.acts[+t.dataset.actI];
  if (typeof a === 'string' || !useLive()) { toast('「' + actLabel(a) + '」：接上后端后生效'); return; }
  doAct(a.act, t);
});
function doAct(act, btn) {
  if (act === 'topup') { window.open('https://platform.deepseek.com/top_up', '_blank', 'noopener'); return; }
  if (act === 'go_cloud') { closeBrain(); S.sec = 'cloud'; renderSettings(); goView('settings'); return; }
  if (act === 'import_summary') { $('#sumFile').click(); return; }
  if (act === 'copy_prompt') { api('POST', '/api/actions/copy_prompt', {}).then(function (j) { copyText(j.prompt); }).catch(function (e) { toast(e.message); }); return; }
  var old = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
  return api('POST', '/api/actions/' + act, {}, 600000).then(function (j) { toast(j.msg || '好了', 4000); fetchBrains(); return j; })
    .catch(function (e) { toast(e.message, 5000); })
    .then(function (j) { if (btn) { btn.disabled = false; btn.textContent = old; } return j; });
}
$('#sumFile').addEventListener('change', function () {
  var f = this.files && this.files[0]; if (!f) return;
  var r = new FileReader();
  r.onload = function () {
    api('POST', '/api/claude/import', { name: f.name, content: String(r.result) }, 120000).then(function (j) { toast(j.msg, 4500); fetchBrains(); }).catch(function (e) { toast(e.message); });
  };
  r.readAsText(f, 'utf-8'); this.value = '';
});
