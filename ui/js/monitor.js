'use strict';
/* 「后台」页：现在在做什么、各个服务好不好、进展报告和实时日志。
   打开这一页时：任务和服务每 2 秒刷新，进展报告 / 日志每 1.5 秒刷新。
   上次拿到的数据一直留着，再打开这一页时先显示它，不会先闪一下空白。 */
var MON = { data: null, feed: null, feedVer: -1, logName: '@feed', follow: true, timer: null, logTimer: null, jump: false };
var MON_ST = { ok: '正常', warn: '进行中', bad: '出错', off: '没在运行' };
var FEED_ICON = { head: '▶', step: '●', ok: '✓', warn: '!', err: '✗', ds: 'D', info: '·', prog: '↓' };

function fmtBytes(b) { if (b == null) return '—'; return b >= 1e9 ? (b / 1e9).toFixed(2) + ' GB' : b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB' : b >= 1e3 ? (b / 1e3).toFixed(0) + ' KB' : b + ' B'; }
function fmtSecs(s) { if (s == null || !isFinite(s)) return ''; s = Math.round(s); return s >= 3600 ? Math.floor(s / 3600) + ' 小时 ' + Math.floor(s % 3600 / 60) + ' 分' : s >= 60 ? Math.floor(s / 60) + ' 分 ' + (s % 60) + ' 秒' : s + ' 秒'; }
/* 进度条：百分比、已下/总共、速度、还剩多久（一键补齐卡片和后台页共用） */
function progHTML(p, line) {
  if (!p) return line ? '<p class="sus-line num">' + esc(line) + '</p>' : '';
  var pct = p.pct == null ? null : Math.max(0, Math.min(100, p.pct));
  var bits = [];
  if (p.total > 1) bits.push(fmtBytes(p.done) + ' / ' + fmtBytes(p.total));
  if (p.speed) bits.push(fmtBytes(p.speed) + '/s');
  if (p.eta != null && p.speed) bits.push('还剩 ' + fmtSecs(p.eta));
  if (p.src) bits.push(esc(p.src));
  var stale = p.ts && Date.now() / 1000 - p.ts > 30;
  return '<div class="prog' + (pct == null ? ' busy' : '') + '"><div class="prog-h"><span>' + esc(p.phase || '进行中') + '</span><b class="num">' + (pct == null ? '' : pct.toFixed(pct < 10 ? 1 : 0) + '%') + '</b></div>' +
    '<div class="prog-bar"><i style="transform:scaleX(' + (pct == null ? 1 : pct / 100).toFixed(4) + ')"></i></div>' +
    '<div class="prog-f num">' + bits.join(' · ') + (stale ? '<span class="stale"> · 30 秒没动静了，可能卡住（看进展报告和日志）</span>' : '') + '</div></div>';
}

/* ---------- 左边：正在做、各个部分 ---------- */
function monJob() {
  var su = MON.data && MON.data.setup;
  if (!MON.data) return '<div class="hc mon-job"><div class="hc-h"><span class="label">正在做</span></div><div class="cap loading">读取中…</div></div>';
  if (!su || (!su.running && !su.finished)) return '<div class="hc mon-job"><div class="hc-h"><span class="label">正在做</span></div><div class="cap">现在没有在跑的任务。一键补齐、每日差事跑起来时会显示在这里。</div></div>';
  var steps = su.steps, done = steps.filter(function (s) { return s.st === 'ok'; }).length;
  var cur = steps.filter(function (s) { return s.k === su.cur; })[0];
  var t = su.running ? (Date.now() / 1000 - su.started) : (su.finished - su.started);
  return '<div class="hc mon-job"><div class="hc-h"><span class="label">' + (su.running ? '正在做 · 一键补齐' : '上次的一键补齐') + '</span><button class="linkbtn" data-go-sec="prep">去整备 →</button></div>' +
    '<div class="mon-steps">' + steps.map(function (s, i) { return '<span class="ms st-' + s.st + (s.k === su.cur && su.running ? ' cur' : '') + '" title="' + esc(s.t + '：' + (s.info || SU_LABEL[s.st] || '')) + '"><i class="num">' + (i + 1) + '</i>' + esc(s.t) + '</span>'; }).join('') + '</div>' +
    (su.running && cur ? '<div class="mon-cur"><b>' + esc(cur.t) + '</b>' + progHTML(cur.prog, su.say || su.line) + (cur.prog && su.say ? '<p class="mon-say">' + esc(su.say) + '</p>' : '') + '</div>' : '<div class="cap">' + done + ' / ' + steps.length + ' 步好了</div>') +
    '<div class="cap num">' + (su.running ? '已经跑了 ' : '用时 ') + fmtSecs(t) + '</div></div>';
}
function monServices() {
  if (!MON.data) return '<div class="hc mon-svc"><div class="hc-h"><span class="label">各个部分</span></div><div class="cap loading">读取中…</div></div>';
  var list = MON.data.services || [];
  return '<div class="hc mon-svc"><div class="hc-h"><span class="label">各个部分</span><span class="cap">点一行看它的日志</span></div>' +
    list.map(function (s) {
      var meta = [];
      if (s.pid) meta.push('PID ' + s.pid);
      if (s.mem) meta.push('内存 ' + s.mem + ' MB');
      if (s.up) meta.push('已运行 ' + fmtSecs(s.up));
      return '<button class="svc st-' + s.st + '" title="' + esc(s.name + '：' + (s.detail || MON_ST[s.st] || '') + (meta.length ? '\n' + meta.join(' · ') : '')) + '"' + (s.log ? ' data-log="' + esc(s.log) + '"' : ' disabled') + '><span class="svc-dot"></span><span class="svc-n">' + esc(s.name) + '</span>' +
        '<span class="svc-d">' + esc(s.detail || MON_ST[s.st] || '') + (meta.length ? '<em class="num">' + meta.join(' · ') + '</em>' : '') + '</span></button>';
    }).join('') + '</div>';
}

/* ---------- 右边：像浏览器一样的标签页，第一个是进展报告 ---------- */
function monTabs() {
  var logs = (MON.data && MON.data.logs) || [];
  var running = MON.data && MON.data.setup && MON.data.setup.running;
  var h = '<button class="tab" role="tab" data-log="@feed" aria-selected="' + (MON.logName === '@feed') + '">' + (running ? '<i class="tab-live"></i>' : '') + '进展报告</button>';
  return h + logs.filter(function (l) { return l.name !== 'report.jsonl'; }).map(function (l) {
    return '<button class="tab" role="tab" data-log="' + esc(l.name) + '" aria-selected="' + (l.name === MON.logName) + '" title="' + esc(l.name) + '">' + esc(l.label) + '</button>';
  }).join('');
}
function feedRow(e) {
  var d = new Date(e.ts * 1000), tm = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  var tag = e.step || e.job || '';
  var body = esc(e.text);
  if (e.kind === 'prog' && e.prog) {
    var p = e.prog, pct = p.pct == null ? null : Math.max(0, Math.min(100, p.pct)), bits = [];
    if (pct != null) bits.push('<b>' + pct.toFixed(pct < 10 ? 1 : 0) + '%</b>');
    if (p.total > 1) bits.push(fmtBytes(p.done) + ' / ' + fmtBytes(p.total));
    if (p.speed) bits.push(fmtBytes(p.speed) + '/s');
    if (p.eta != null && p.speed) bits.push('还剩 ' + fmtSecs(p.eta));
    if (p.src) bits.push(esc(p.src));
    body += '<span class="fr-p num">' + bits.join(' · ') + '</span><span class="fr-bar' + (pct == null ? ' busy' : '') + '"><i style="transform:scaleX(' + (pct == null ? 1 : pct / 100).toFixed(4) + ')"></i></span>';
  }
  return '<div class="fr k-' + e.kind + (e.old ? ' old' : '') + '"><time class="num">' + tm + '</time><span class="fr-i">' + (FEED_ICON[e.kind] || '·') + '</span>' +
    '<span class="fr-tag" title="' + esc(tag) + '">' + esc(tag) + '</span>' + '<span class="fr-t">' + body + '</span></div>';
}
function renderFeed() {
  var box = $('#feedBox'); if (!box || !MON.feed) return;
  var items = MON.feed.items || [];
  var atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  if (!items.length) { box.innerHTML = '<div class="fr-empty">还没有进展。点「一键补齐」或者跑每日差事时，这里会一步一步写出它在干什么。</div>'; return; }
  var h = '', lastOld = null;
  items.forEach(function (e) {
    if (lastOld === true && !e.old) h += '<div class="fr-sep">以上是之前的记录</div>';
    lastOld = !!e.old; h += feedRow(e);
  });
  box.innerHTML = h;
  if (MON.follow && (atBottom || MON.jump)) box.scrollTop = box.scrollHeight;
  MON.jump = false;
}
function showLogBody() {
  var isFeed = MON.logName === '@feed';
  var f = $('#feedBox'), l = $('#logBox'); if (!f || !l) return;
  f.hidden = !isFeed; l.hidden = isFeed;
  var p = $('#logPath'); if (p) p.textContent = isFeed ? '每一步在干什么 · 存在 data\\logs\\report.jsonl' : '';
}
function renderMonitor() {
  var v = $('#view-monitor');
  if (!useLive()) {
    v.innerHTML = '<div class="page"><div class="ph"><h1>后台</h1><span class="sub">现在在做什么、各个部分好不好、实时日志</span></div><div class="empty">演示模式看不到后台：用 启动.bat 打开 Agent 后，这里会显示正在跑的任务、进度、进展报告和日志。</div></div>';
    return;
  }
  v.innerHTML = '<div class="page fill mon"><div class="ph"><h1>后台</h1><span class="sub">现在在做什么、各个部分好不好、每一步的进展 · 自动刷新</span></div>' +
    '<div class="mon-grid"><div class="mon-l" id="monL">' + monJob() + monServices() + '</div>' +
    '<div class="hc mon-log"><div class="tabs" role="tablist" id="logTabs">' + monTabs() + '</div>' +
    '<div class="tabbody"><div class="feed" id="feedBox"></div><pre class="logbox" id="logBox" hidden>读取中…</pre></div>' +
    '<div class="log-f"><label class="cap"><input type="checkbox" id="logFollow"' + (MON.follow ? ' checked' : '') + '> 自动滚到最新</label><span class="cap log-path" id="logPath"></span><button class="linkbtn" id="logCopy">复制路径</button></div></div></div></div>';
  showLogBody();
  if (MON.feed) { MON.jump = true; setTimeout(renderFeed, 0); } else $('#feedBox').innerHTML = '<div class="fr-empty">读取中…</div>';   // 进展报告稍后再填，切页不卡
  fetchLog();
}
function refreshMonitor() {
  var l = $('#monL'); if (l) l.innerHTML = monJob() + monServices();
  var t = $('#logTabs'); if (t) t.innerHTML = monTabs();
}
function fetchMonitor(force) {
  if (!useLive() || (!force && S.view !== 'monitor')) return;
  api('GET', '/api/monitor', null, 8000).then(function (j) { MON.data = j; if (S.view === 'monitor') { if ($('#monL')) refreshMonitor(); else renderMonitor(); } }).catch(function () {});
}
function fetchFeed(force) {
  if (!useLive() || (!force && (S.view !== 'monitor' || MON.logName !== '@feed'))) return;
  api('GET', '/api/feed?n=400', null, 8000).then(function (j) {
    if (j.ver === MON.feedVer && $('#feedBox') && $('#feedBox').children.length && !MON.jump) return;
    MON.feed = j; MON.feedVer = j.ver;
    if (S.view === 'monitor') renderFeed();
  }).catch(function () {});
}
function fetchLog() {
  if (!useLive() || S.view !== 'monitor' || !MON.logName) return;
  if (MON.logName === '@feed') { fetchFeed(); return; }
  api('GET', '/api/logs/' + encodeURIComponent(MON.logName) + '?n=400', null, 8000).then(function (j) {
    var box = $('#logBox'); if (!box || MON.logName !== j.name) return;
    var atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.textContent = j.lines.length ? j.lines.join('\n') : '（这个日志还是空的）';
    var p = $('#logPath'); if (p) p.textContent = j.path || '';
    if (MON.follow && (atBottom || MON.jump)) box.scrollTop = box.scrollHeight;
    MON.jump = false;
  }).catch(function (e) { var box = $('#logBox'); if (box) box.textContent = '读不了这个日志：' + e.message; });
}
function startMonitor() {
  stopMonitor(); renderMonitor(); fetchMonitor(true);
  MON.timer = setInterval(fetchMonitor, 2000); MON.logTimer = setInterval(fetchLog, 1500);
}
function stopMonitor() { clearInterval(MON.timer); clearInterval(MON.logTimer); MON.timer = MON.logTimer = null; }
/* 先在后台拿一次，第一次点开「后台」就有东西看 */
function prefetchMonitor() { if (!useLive()) return; fetchMonitor(true); fetchFeed(true); }

$('#view-monitor').addEventListener('click', function (ev) {
  var t = ev.target.closest('button'); if (!t) return;
  if (t.dataset.log) {
    MON.logName = t.dataset.log; MON.jump = true;
    var tb = $('#logTabs'); if (tb) tb.innerHTML = monTabs();
    showLogBody();
    if (MON.logName === '@feed') { renderFeed(); fetchFeed(); }
    else { var b = $('#logBox'); if (b) b.textContent = '读取中…'; fetchLog(); }
  }
  else if (t.dataset.goSec) { S.sec = t.dataset.goSec; renderSettings(); goView('settings'); }
  else if (t.id === 'logCopy') {
    var path = MON.logName === '@feed' ? ((MON.data && MON.data.root) || '') + '\\data\\logs\\report.jsonl' : ($('#logPath') || {}).textContent;
    if (path) copyText(path);
  }
});
$('#view-monitor').addEventListener('change', function (ev) {
  if (ev.target.id !== 'logFollow') return;
  MON.follow = ev.target.checked;
  if (MON.follow) { var b = MON.logName === '@feed' ? $('#feedBox') : $('#logBox'); if (b) b.scrollTop = b.scrollHeight; }
});
(function () { var b = document.querySelector('.nav[data-view="monitor"]'); if (b) b.addEventListener('pointerenter', function () { if (!MON.data || Date.now() - (MON.data.ts || 0) * 1000 > 5000) prefetchMonitor(); }); })();
