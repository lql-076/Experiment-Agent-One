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
  var st = r.st === 'ok' || S.manual[c.k] ? 'ok' : r.st; var b = row.querySelector('.bst'); b.className = 'bst ' + st; b.innerHTML = BOOT_ICON[st] || '';
  row.querySelector('.bdet').textContent = S.manual[c.k] && r.st !== 'ok' ? '已手动确认' : r.d;
}
function demoCheck(c) { return delay(rnd(120, 520)).then(function () { return { st: c.demo[0], d: c.demo[1] + '（演示）' }; }); }
function runChecks(boot) {
  if (S.checking) return Promise.resolve();
  S.checking = true;
  LIVE_CHECKS.forEach(function (c) { S.check[c.k] = { st: 'run', d: '检测中' }; });
  if ($('#prepReady')) $('#sbody').innerHTML = sectionBody(secById('prep'));
  var done = 0, total = LIVE_CHECKS.length;
  var reveal = function (c, r, i) {
    return delay((boot ? 260 : 120) + i * (boot ? 90 : 50)).then(function () {
      S.check[c.k] = r; done++;
      if (boot) { bootRow(c, r); $('#bootBar').style.transform = 'scaleX(' + (done / total).toFixed(3) + ')'; }
      updatePrepUI(c.k);
    });
  };
  var p;
  if (useLive()) {
    p = api('POST', '/api/checks/run', null, 60000).then(function (j) {
      if (j.places) PLACES = j.places;
      return Promise.all(LIVE_CHECKS.map(function (c, i) { return reveal(c, j.res[c.k] || { st: 'wait', d: '' }, i); }));
    }).catch(function (e) {
      return Promise.all(LIVE_CHECKS.map(function (c, i) { return reveal(c, { st: 'wait', d: '自检没跑完：' + e.message }, i); }));
    });
  } else {
    var t0 = performance.now();
    p = Promise.all(LIVE_CHECKS.map(function (c, i) { return demoCheck(c).then(function (r) { return delay(Math.max(0, (boot ? 380 : 160) + i * (boot ? 90 : 60) - (performance.now() - t0))).then(function () { S.check[c.k] = r; done++; if (boot) { bootRow(c, r); $('#bootBar').style.transform = 'scaleX(' + (done / total).toFixed(3) + ')'; } updatePrepUI(c.k); }); }); }));
  }
  return p.then(function () { S.checking = false; S.lastCheck = new Date(); updatePrepUI(); var pw = $('#prepWhen'); if (pw) pw.textContent = '上次自检 ' + pad(S.lastCheck.getHours()) + ':' + pad(S.lastCheck.getMinutes()) + ' · Agent 文件夹：' + P('root'); });
}
function afterCheck() { var m = missingCount(); if (m) toast('整备缺 ' + m + ' 项，去 设置 › 整备 查看', 3500); }
function boot() {
  if (!S.set.bootShow) { runChecks(false).then(afterCheck); return; }
  var b = $('#boot');
  $('#bootTitle').textContent = '启动自检' + (useLive() ? '' : '（演示）');
  $('#bootList').innerHTML = LIVE_CHECKS.map(function (c, i) { return '<div class="brow" id="br-' + c.k + '" style="--i:' + i + '"><span class="bst run"></span><span>' + esc(c.t) + '</span><span class="bdet">检测中</span></div>'; }).join('');
  b.classList.add('on');
  var closed = false;
  var close = function () { if (closed) return; closed = true; b.classList.add('out'); setTimeout(function () { b.classList.remove('on', 'out', 'done'); }, 460); };
  b.onclick = close;
  runChecks(true).then(function () {
    var n = readyCount(), m = missingCount();
    b.classList.add('done');
    $('#bootSub').textContent = m ? '有 ' + m + ' 项需要补' : '全部就绪';
    $('#bootSum').textContent = '已就绪 ' + n + ' / ' + LIVE_CHECKS.length;
    return delay(m ? 1600 : 800);
  }).then(function () { close(); afterCheck(); });
}
