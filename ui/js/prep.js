'use strict';
/* ================= 整备自检 ================= */
function ping(url) { if (!url) return Promise.resolve(false); return fetchT(url, { mode: 'no-cors' }, 1500).then(function () { return true; }, function () { return false; }); }
function isReady(c) { var r = S.check[c.k]; return (r && r.st === 'ok') || !!S.manual[c.k]; }
function readyCount() { return LIVE_CHECKS.filter(isReady).length; }
function stOf(c) { var r = S.check[c.k] || { st: 'run' }; if (r.st === 'ok') return 'ok'; if (S.manual[c.k] && r.st !== 'run') return 'man'; return r.st; }
var ST_LABEL = { ok: '已就绪', miss: '缺失', wait: '待处理', run: '检测中', man: '已手动确认' };
function linksHTML(links) { return (links || []).map(function (l) { return '<a href="' + l[1] + '" target="_blank" rel="noopener noreferrer">' + esc(l[0]) + ICONS.ext + '</a>'; }).join(''); }
/* 整备卡片：要处理的放前面，同一行一样高、按钮对齐在底部；长说明收进「怎么弄」，点开才看。已就绪的缩成小卡。 */
var prepOpen = {};
function prepRow(c) {
  var r = S.check[c.k] || { st: 'run', d: '等待自检' }, st = stOf(c), done = st === 'ok' || st === 'man';
  var place = fillPlace(r.place ? r.place : c.place);
  var act = r.action || (c.act && c.act[0]), actLabel = c.act ? c.act[1] : '';
  var showAct = act && useLive() && st !== 'run' && (st !== 'ok' || act === 'qq_test');
  var ck = '<button class="ck" role="checkbox" aria-checked="' + done + '" data-man="' + c.k + '" aria-label="' + esc(c.t) + ' 手动确认">' + ICONS.check + '</button>';
  if (done) {
    return '<div class="su sm st-' + st + '" id="su-' + c.k + '">' + ck + '<div class="su-b"><div class="su-top"><h3>' + esc(c.t) + '</h3>' +
      (showAct ? '<button class="linkbtn" data-act="' + act + '" data-k="' + c.k + '">' + esc(actLabel) + '</button>' : '') + '</div><p class="su-d">' + esc(r.d) + '</p></div></div>';
  }
  var copy = /[A-Za-z]:\\|\//.test(place) ? '<button class="linkbtn" data-copy="' + esc(place.replace(/[（(].*$/, '').replace(/^.*?在 /, '').trim()) + '">复制</button>' : '';
  var go = c.go || r.go;
  return '<div class="su st-' + st + '" id="su-' + c.k + '">' + ck + '<div class="su-b">' +
    '<div class="su-top"><h3>' + esc(c.t) + '</h3><span class="pill">' + ST_LABEL[st] + '</span></div>' +
    '<p class="su-d">' + esc(r.d) + '</p>' +
    '<div class="place"><span>放到</span><code>' + esc(place) + '</code>' + copy + '</div>' +
    '<details class="su-more" data-k="' + c.k + '"' + (prepOpen[c.k] ? ' open' : '') + '><summary>怎么弄</summary><p>' + esc(c.why) + '</p><p class="su-how">检测方法：' + esc(c.how) + '</p>' +
      (c.links && c.links.length ? '<div class="links">' + linksHTML(c.links) + '</div>' : '') + '</details>' +
    '<div class="su-act">' + (c.auto ? '<span class="autotag">一键补齐能装</span>' : '') +
      (showAct ? '<button class="btn mini primary" data-act="' + act + '" data-k="' + c.k + '">' + esc(actLabel || '现在处理') + '</button>' : '') +
      (go ? '<button class="btn mini" data-go="' + go + '">去填设置</button>' : '') +
      (useLive() && st === 'miss' ? '<button class="btn mini" data-diag="' + c.k + '">问 DeepSeek</button>' : '') + '</div>' +
    '<div class="diag" id="diag-' + c.k + '" hidden></div></div></div>';
}
function prepGroups() {
  var todo = LIVE_CHECKS.filter(function (c) { var st = stOf(c); return st !== 'ok' && st !== 'man'; });
  var ok = LIVE_CHECKS.filter(function (c) { var st = stOf(c); return st === 'ok' || st === 'man'; });
  return (todo.length ? '<div class="label grp">要处理 · ' + todo.length + ' 项</div><div class="setup">' + todo.map(prepRow).join('') + '</div>' : '') +
    (ok.length ? '<div class="label grp">已就绪 · ' + ok.length + ' 项</div><div class="setup ready">' + ok.map(prepRow).join('') + '</div>' : '');
}
function prepHTML() {
  var n = readyCount(), tot = LIVE_CHECKS.length;
  var when = S.checking ? '正在自检…' : S.lastCheck ? '上次自检 ' + pad(S.lastCheck.getHours()) + ':' + pad(S.lastCheck.getMinutes()) + (useLive() ? '' : ' · 演示数据') : '还没有自检';
  return '<div class="prep-head"><div><div class="prep-num num"><b id="prepReady">' + n + '</b> / ' + tot + '</div><div class="help" id="prepWhen" style="margin-top:.375rem">' + when + ' · Agent 文件夹：' + esc(P('root')) + (LIVE ? '' : '（示例路径，按你实际放的位置）') + '</div></div><button class="btn primary" id="recheck">重新自检</button></div>' +
    '<div class="prep-bar"><i id="prepBar" style="transform:scaleX(' + (n / tot).toFixed(3) + ')"></i></div>' + setupHTML() + '<div id="prepGroups">' + prepGroups() + '</div>' +
    '<div class="label grp">以后再装 · 不参与自检</div><div class="setup ready">' +
    CHECKS.filter(function (c) { return c.later; }).map(function (c) { return '<div class="su sm later"><span></span><div class="su-b"><div class="su-top"><h3>' + esc(c.t) + '</h3></div><p class="su-d">' + esc(c.why) + '</p>' + (c.links && c.links.length ? '<div class="links">' + linksHTML(c.links) + '</div>' : '') + '</div></div>'; }).join('') + '</div>';
}
function updatePrepUI(k) {
  var n = readyCount(), tot = LIVE_CHECKS.length;
  if (k) { var g = $('#prepGroups'); if (g) g.innerHTML = prepGroups(); }
  var pr = $('#prepReady'); if (pr) pr.textContent = n;
  var pb = $('#prepBar'); if (pb) pb.style.transform = 'scaleX(' + (n / tot).toFixed(3) + ')';
  var mini = $('#prepMini'); if (mini) { mini.textContent = n + '/' + tot; mini.classList.toggle('warn', n < tot && !S.checking); }
  updatePrepHome(); syncBadges();
}
var BOOT_ICON = { ok: ICONS.check, miss: ICONS.cross, wait: ICONS.dash };
function bootRow(c, r) {
  var row = $('#br-' + c.k); if (!row) return;
  var st = r.st === 'ok' || S.manual[c.k] ? 'ok' : r.st; var b = row.querySelector('.bst'); b.className = 'bst ' + st; b.innerHTML = BOOT_ICON[st] || ''; row.className = 'brow r-' + st;
  row.querySelector('.bdet').textContent = S.manual[c.k] && r.st !== 'ok' ? '已手动确认' : r.d;
}
function demoCheck(c) { return delay(rnd(120, 520)).then(function () { return { st: c.demo[0], d: c.demo[1] + '（演示）' }; }); }
/* 自检：14 项同时查，哪项先查完先显示（相邻两项至少隔一点时间，看得清是一项一项亮的）。
   panel=true 时同步更新自检窗口（启动自检、重新自检共用一个窗口）。 */
function runChecks(panel) {
  if (S.checking) return Promise.resolve();
  S.checking = true;
  LIVE_CHECKS.forEach(function (c) { S.check[c.k] = { st: 'run', d: '检测中' }; });
  if ($('#prepReady')) $('#sbody').innerHTML = sectionBody(secById('prep'));
  var done = 0, total = LIVE_CHECKS.length, t0 = performance.now(), next = t0 + (panel ? 260 : 120), gap = panel ? 80 : 45;
  var slot = function () { var now = performance.now(); next = Math.max(now, next + gap); return delay(next - now); };
  var reveal = function (c, r) {
    return slot().then(function () {
      S.check[c.k] = r; done++;
      if (panel) { bootRow(c, r); $('#bootBar').style.transform = 'scaleX(' + (done / total).toFixed(3) + ')'; if (!$('#boot').classList.contains('done')) $('#bootSum').textContent = '已查 ' + done + ' / ' + total; }
      updatePrepUI(c.k);
    });
  };
  var p;
  if (useLive()) {
    p = Promise.all(LIVE_CHECKS.map(function (c) {
      return api('POST', '/api/checks/' + c.k + '/run?quick=1', null, 45000)
        .catch(function (e) { return { st: 'wait', d: '没查完：' + e.message }; })
        .then(function (r) { return reveal(c, r); });
    })).then(function () { return api('GET', '/api/checks').then(function (j) { if (j.places) PLACES = j.places; }, function () {}); });
  } else {
    p = Promise.all(LIVE_CHECKS.map(function (c) { return demoCheck(c).then(function (r) { return reveal(c, r); }); }));
  }
  return p.then(function () { S.checking = false; S.lastCheck = new Date(); updatePrepUI(); var pw = $('#prepWhen'); if (pw) pw.textContent = '上次自检 ' + pad(S.lastCheck.getHours()) + ':' + pad(S.lastCheck.getMinutes()) + ' · Agent 文件夹：' + P('root'); });
}
function afterCheck() { var m = missingCount(); if (m) toast('整备缺 ' + m + ' 项，去 设置 › 整备 查看', 3500); }
function boot() {
  if (!S.set.bootShow) { runChecks(false).then(afterCheck); return; }
  checkPanel(false);
}
/* 自检窗口：启动时自动弹（查完自己关）；整备里点「重新自检」也弹这个（查完停在结果上，等你看完再关）。 */
function checkPanel(manual) {
  if (S.checking) { if (manual) toast('正在自检，稍等'); return; }
  var b = $('#boot'), total = LIVE_CHECKS.length, t0 = performance.now();
  var skip = $('#bootSkip'), go = $('#bootGo');
  $('#bootTitle').textContent = (manual ? '重新自检' : '启动自检') + (useLive() ? '' : '（演示）');
  $('#bootSub').textContent = '正在检查整备清单';
  $('#bootSum').textContent = '已查 0 / ' + total;
  $('#bootBar').style.transform = 'scaleX(0)';
  $('#bootList').innerHTML = LIVE_CHECKS.map(function (c, i) { return '<div class="brow" id="br-' + c.k + '" style="--i:' + i + '"><span class="bst run"></span><span>' + esc(c.t) + '</span><span class="bdet">检测中</span></div>'; }).join('');
  skip.textContent = manual ? '后台继续' : '跳过'; go.hidden = true;
  b.classList.remove('done', 'out'); b.classList.toggle('manual', !!manual); b.classList.add('on');
  var closed = false;
  var onKey = function (e) { if (e.key === 'Escape') close(); };
  var close = function () {
    if (closed) return; closed = true; document.removeEventListener('keydown', onKey);
    b.classList.add('out'); setTimeout(function () { b.classList.remove('on', 'out', 'done', 'manual'); }, 460);
  };
  document.addEventListener('keydown', onKey);
  b.onclick = function (e) {
    if (e.target.closest('#bootGo')) { close(); gotoTodo(); return; }
    // 重新自检时，点卡片里面不关（方便看结果）；点按钮或卡片外面才关
    if (manual && e.target.closest('.boot-card') && !e.target.closest('button')) return;
    close();
  };
  runChecks(true).then(function () {
    // 开机头 2 分钟里还在启动的项（后端标成 run）不算「要处理」：后台会自己重查，好了自己变绿
    var n = readyCount(), starting = LIVE_CHECKS.filter(function (c) { var r = S.check[c.k]; return r && r.st === 'run' && !S.manual[c.k]; }).length;
    var todo = total - n - starting;
    b.classList.add('done');
    $('#bootSub').textContent = todo ? '有 ' + todo + ' 项要处理' + (starting ? '，' + starting + ' 项还在启动' : '') : starting ? starting + ' 项还在启动，好了会自己变绿' : '全部就绪';
    $('#bootSum').textContent = '已就绪 ' + n + ' / ' + total + (manual ? ' · 用时 ' + ((performance.now() - t0) / 1000).toFixed(1) + ' 秒' : '');
    if (!manual) return delay(missingCount() ? 1600 : 800).then(function () { close(); afterCheck(); });
    if (closed) { toast('自检完成：已就绪 ' + n + ' / ' + total + (todo ? '，' + todo + ' 项要处理' : ''), 3500); return; }
    skip.textContent = '好'; go.hidden = !todo;
  });
}
/* 自检窗口里点「去处理」：回到整备，滚到第一张要处理的卡片，闪一下 */
function gotoTodo() {
  var first = LIVE_CHECKS.filter(function (c) { return !isReady(c); })[0];
  if (!first) return;
  var show = function () {
    var el = $('#su-' + first.k); if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
  };
  if (S.view !== 'settings' || S.sec !== 'prep') { S.sec = 'prep'; renderSettings(); goView('settings'); setTimeout(show, 450); } else show();
}
