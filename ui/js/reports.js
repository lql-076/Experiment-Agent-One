'use strict';
/* ================= 报告 ================= */
function missingCount() { return LIVE_CHECKS.filter(function (c) { return S.check[c.k] && S.check[c.k].st === 'miss' && !S.manual[c.k]; }).length; }
function syncBadges() {
  var n = pendingAsks(), b = $('#repBadge'); b.hidden = !n; b.textContent = n;
  var m = missingCount(), sb = $('#setBadge'); sb.hidden = !m; sb.textContent = m;
}
function renderReports() {
  var v = $('#view-reports'), live = useLive();
  if (live && !D.report) { v.innerHTML = '<div class="empty">正在读取…</div>'; return; }
  var R = live ? D.report : null;
  var split = live ? R.split : WEEK_SPLIT, wtot = ORDER.reduce(function (a, k) { return a + split[k]; }, 0);
  var changes = live ? R.changes : CHANGES, asks = live ? R.asks.filter(function (a) { return a.status === 'pending'; }) : ASKS;
  var kpi = function (i, l, val, unit, cap, c) { return '<div class="hc stag" style="--i:' + i + '"><span class="label">' + l + '</span><div class="big num"' + (c ? ' style="color:' + c + '"' : '') + '>' + val + '<small>' + unit + '</small></div><span class="cap">' + cap + '</span></div>'; };
  var d0 = new Date(Date.now() - 6 * 864e5), d1 = new Date();
  var lp = live ? R.local_pct : Math.round(WEEK_SPLIT.local / wtot * 100), fixes = live ? R.fixes : 2, cost = live ? R.cost_month : 0.41;
  var draft = live && R.draft && R.draft.lines && R.draft.lines.length ? R.draft : null;
  v.innerHTML = '<div class="page"><div class="ph"><h1>本周报告</h1><span class="sub">' + (d0.getMonth() + 1) + ' 月 ' + d0.getDate() + ' 日到 ' + (d1.getMonth() + 1) + ' 月 ' + d1.getDate() + ' 日 · 每条都能追到事件</span></div>' +
    '<div class="kpis">' + kpi(0, '分流', wtot, '件', '平均每天 ' + Math.round(wtot / 7) + ' 件') + kpi(1, '本地处理', lp, '%', '越高，说明小脑越能干', 'var(--c-local)') + kpi(2, '被你纠正', fixes, '次', '都成了语义路由的新判例') + kpi(3, 'DeepSeek 本月', '¥' + (+cost).toFixed(2), '', '本机估算 · 余额 ' + (live ? (R.balance && R.balance.key ? money(R.balance.total) : '没填 Key') : '¥8.59')) + '</div>' +
    (draft ? '<div class="hc stag" style="--i:4;margin-bottom:1rem;min-height:0"><div class="hc-h"><span class="label">本周要点 · DeepSeek 起草</span><span class="cap">每条都核对过事件编号</span></div><div>' + draft.lines.map(function (l) { return '<p style="margin:.35rem 0;line-height:1.7">' + esc(l) + '</p>'; }).join('') + '</div></div>' : '') +
    '<div class="rcharts"><div class="hc stag" style="--i:4"><div class="hc-h"><span class="label">每天本地处理比例</span><span class="cap">越高，说明小脑越能干</span></div>' + weekBars('11rem') + '</div>' +
      '<div class="hc stag" style="--i:5"><span class="label">本周谁接的活</span><div style="display:flex;align-items:center;gap:1.25rem;flex-wrap:wrap"><div class="dwrap" style="width:9rem">' + donutHTML(78, 20, 4) + '<div class="dc"><b class="big num" style="font-size:2rem">' + wtot + '</b></div></div>' +
        '<div class="legend" style="min-width:8rem;gap:.5rem">' + ORDER.map(function (k) { return '<div class="lg" style="--c:' + ROUTES[k].color + ';font-size:.8125rem"><i></i><span>' + ROUTES[k].name + '</span><span class="num">' + split[k] + '</span></div>'; }).join('') + '</div></div></div></div>' +
    '<div class="rlists"><div class="hc stag" style="--i:6"><div class="hc-h"><span class="label">先斩后奏的改动</span><span class="cap">不满意可以撤销</span></div><div>' +
      (changes.length ? changes.map(function (c) { var d = live ? c.undone : S.done['c' + c.id]; var ic = ICONS[KIND_ICON[c.kind] || 'file']; return '<div class="ritem' + (d ? ' done' : '') + '"><span class="ricon" style="--c:' + (KIND_COLOR[c.kind] || 'var(--accent)') + '">' + ic + '</span><div><div class="w">' + esc(c.w) + '</div><div class="e">' + esc(c.e) + '</div></div>' + (c.can_undo === false ? '<span class="cap">—</span>' : '<button class="btn" data-undo="' + c.id + '"' + (d ? ' disabled' : '') + '>' + (d ? '已撤销' : '撤销') + '</button>') + '</div>'; }).join('') : '<div class="cap" style="padding:1rem 0">这周还没有改动。</div>') +
    '</div></div><div class="hc stag" style="--i:7"><div class="hc-h"><span class="label">等你决定</span><span class="cap">撤销不了的事必须先问</span></div><div>' +
      (asks.length ? asks.map(function (c) { var d = !live && S.done['a' + c.id]; var ic = ICONS[KIND_ICON[c.kind] || 'tool']; return '<div class="ritem' + (d ? ' done' : '') + '"><span class="ricon" style="--c:' + (KIND_COLOR[c.kind] || 'var(--c-cl)') + '">' + ic + '</span><div><div class="w">' + esc(c.w) + '</div><div class="e">' + esc(c.e) + '</div></div><div class="btnrow">' + (d ? '<span class="cap">' + d + '</span>' : '<button class="btn primary" data-ok="' + c.id + '">同意</button><button class="btn" data-no="' + c.id + '">不同意</button>') + '</div></div>'; }).join('') : '<div class="cap" style="padding:1rem 0">没有要你决定的事。</div>') +
    '</div></div></div></div>';
  requestAnimationFrame(function () { setDonut($('#view-reports .rcharts .donut'), ORDER.map(function (k) { return { v: split[k], color: ROUTES[k].color }; }), 4); });
  syncBadges();
}
$('#view-reports').addEventListener('click', function (ev) {
  var t = ev.target.closest('button'); if (!t || t.disabled) return;
  var live = useLive();
  if (t.dataset.undo !== undefined) {
    if (live) api('POST', '/api/changes/' + t.dataset.undo + '/undo', {}).then(function (j) { toast(j.msg); fetchReport(); }).catch(function (e) { toast(e.message); });
    else { S.done['c' + t.dataset.undo] = 1; renderReports(); toast('已撤销（演示）'); }
  } else if (t.dataset.ok !== undefined || t.dataset.no !== undefined) {
    var id = t.dataset.ok || t.dataset.no, ok = t.dataset.ok !== undefined;
    if (live) api('POST', '/api/asks/' + id, { approve: ok }).then(function (j) { toast(j.msg); fetchReport(); poll(); }).catch(function (e) { toast(e.message); });
    else { S.done['a' + id] = ok ? '已同意' : '已拒绝'; renderReports(); renderHome(true); toast(ok ? '已同意' : '已拒绝'); }
  }
});
