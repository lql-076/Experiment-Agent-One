'use strict';
/* ================= Claude Code 工作台（v3.4）=================
   主页侧栏「Claude」/ 指令条「Claude」打开一个独立工具窗口（?tool=ccode）。
   左边：开关、任务输入、交给它 / 停下 / 继续；右边：实时步骤、当前在做什么、结果。
   后端：app/ccode.py 的 run()（和聊天里「动手干活用 Claude Code」同一条路），
   接口：GET /api/ccode、POST /api/ccode/run、/stop、/continue、PUT /api/ccode/switch。
   所有子进程由 ccode.py 用 CREATE_NO_WINDOW 起；这里只轮询状态，不直接碰命令行。 */
var CC = { st: null, job: null, timer: null, sig: '', text: '', loading: false };

function ccodeEnter() {
  if (typeof useLive === 'function' && !useLive()) { renderCCode(); return; }
  ccodeLoad(true);
  if (CC.timer) clearInterval(CC.timer);
  CC.timer = setInterval(function () { if (S.view === 'ccode') ccodeLoad(false); }, 1200);
}

function ccodeLeave() {
  if (CC.timer) { clearInterval(CC.timer); CC.timer = null; }
}

function ccodeLoad(deep) {
  if (!useLive()) { renderCCode(); return; }
  if (CC.loading && !deep) return;
  CC.loading = true;
  api('GET', '/api/ccode?deep=' + (deep ? 1 : 0), null, deep ? 25000 : 8000).then(function (j) {
    var sig = JSON.stringify([j.status, j.job]);
    CC.st = j.status; CC.job = j.job;
    var nav = $('.nav[data-tool="ccode"]'); if (nav) nav.classList.toggle('on-busy', !!(CC.job && CC.job.st === 'run'));
    if (deep || sig !== CC.sig) { CC.sig = sig; renderCCode(); }
  }).catch(function () {
    if (!CC.st) { CC.st = { on: false, found: false, version: '', path: '', minutes: 60, bash: '', model: '' }; renderCCode(); }
  }).then(function () { CC.loading = false; });
}

function ccStatusText(st, job) {
  if (!st) return ['off', '读取中…'];
  if (!st.on) return ['off', '引擎关着'];
  if (!st.found) return ['bad', '没找到 claude'];
  if (job && job.st === 'run') return ['run', '正在跑'];
  return ['ok', '已连接' + (st.version ? ' · ' + st.version : '')];
}

function ccStepHTML(s, i, last) {
  return '<li class="' + (last ? 'cur' : 'done') + '"><b>' + esc(s[0]) + '</b><span>' + esc(s[1]) + '</span></li>';
}

function renderCCode() {
  var v = $('#view-ccode'); if (!v) return;
  if (!useLive()) {
    v.innerHTML = '<div class="cc-page"><div class="hud cc-card"><b>Claude Code 工作台</b><p class="cap">演示模式：启动 Agent 后用本机 Claude Code 干活。这里不连后端。</p></div></div>';
    return;
  }
  var st = CC.st, job = CC.job;
  if (!st) {
    v.innerHTML = '<div class="cc-page"><div class="hud cc-card"><b>Claude Code 工作台</b><p class="cap">正在读取状态……</p></div></div>';
    return;
  }
  var status = ccStatusText(st, job), run = !!(job && job.st === 'run');
  var steps = (job && job.steps) || [];
  var result = job && (job.st === 'done' || job.st === 'err' || job.st === 'stopped') ? (job.result || job.err || '') : '';
  var stepsHTML = steps.length ? steps.map(function (s, i) { return ccStepHTML(s, i, run && i === steps.length - 1); }).join('')
    : '<li class="cc-empty">交一件事，它的每一步会出现在这里</li>';
  var resultTitle = !job ? '' : job.st === 'err' ? '没做成' : job.st === 'stopped' ? '停下了' : job.st === 'done' ? '做完了' : '';
  var controls = run
    ? '<button class="btn primary cc-go" id="ccRun" disabled>正在跑…</button><button class="btn" id="ccCont" disabled>继续</button><button class="btn danger" id="ccStop">停下</button>'
    : '<button class="btn primary cc-go" id="ccRun"' + (!st.on || !st.found ? ' disabled' : '') + '>交给 Claude Code</button><button class="btn" id="ccCont"' + (!job || !job.session || !st.on || !st.found ? ' disabled' : '') + '>继续</button><button class="btn danger" id="ccStop" disabled>停下</button>';
  v.innerHTML = '<div class="cc-page">' +
    '<div class="cc-head"><div class="cc-title"><b>Claude Code 工作台</b><span class="cap">把一整件事交给本机的 Claude Code：它自己列计划、改文件、跑命令，每一步在这里实时看</span></div>' +
      '<div class="cc-state st-' + status[0] + '"><i></i><span>' + esc(status[1]) + '</span></div></div>' +
    '<div class="cc-grid">' +
      '<section class="hud cc-card cc-left">' +
        '<div class="cc-row"><b>引擎</b><button class="cc-switch' + (st.on ? ' on' : '') + '" id="ccSw" aria-pressed="' + (!!st.on) + '"><i></i><span>' + (st.on ? '已开' : '关着') + '</span></button>' +
          '<span class="cap">' + (st.found ? 'claude：' + esc(st.version || st.path || '已找到') : '没找到 claude 命令行') + '</span></div>' +
        (st.on ? '' : '<div class="cc-hint">Claude Code 默认关着（给 Agent 加权限）。打开以后，工作区里的活可以交给它；它只改工作区、只跑允许的命令。</div>') +
        (!st.found ? '<div class="cc-hint bad">没找到 claude：先装 Claude Code，或者到 设置 › Agent 能力 ›「Claude Code 在哪」填路径。CC Switch 挂 DeepSeek 的配置不用改。</div>' : '') +
        '<textarea class="cc-in" id="ccText" spellcheck="false" placeholder="要它做什么？比如：把工作区里的 视频 文件夹整理一下，给每段配字幕，再合成一版。">' + esc(CC.text) + '</textarea>' +
        '<div class="cc-actions">' + controls + '</div>' +
        '<div class="cc-meta cap">' + (st.model ? '模型：' + esc(st.model) + ' · ' : '') + '最多 ' + (st.minutes || 60) + ' 分钟 · 允许的命令：' + esc(st.bash || '默认') + '</div>' +
      '</section>' +
      '<section class="hud cc-card cc-right">' +
        '<div class="cc-row"><b>执行过程</b><span class="cap cc-msg" id="ccMsg">' + esc((job && job.msg) || '还没有任务') + '</span><span class="sp"></span>' +
          (job && job.sec ? '<span class="num cap">' + job.sec + ' 秒</span>' : '') + '</div>' +
        '<ol class="cc-steps" id="ccSteps">' + stepsHTML + '</ol>' +
        (result ? '<div class="cc-result ' + (job.st === 'err' ? 'bad' : '') + '"><b>' + resultTitle + '</b><pre>' + esc(result) + '</pre></div>' : '') +
      '</section>' +
    '</div></div>';
  var ta = $('#ccText'); if (ta) ta.addEventListener('input', function () { CC.text = ta.value; });
  var sw = $('#ccSw'); if (sw) sw.addEventListener('click', ccToggle);
  var go = $('#ccRun'); if (go && !go.disabled) go.addEventListener('click', ccRun);
  var stop = $('#ccStop'); if (stop) stop.addEventListener('click', ccStop);
  var cont = $('#ccCont'); if (cont && !cont.disabled) cont.addEventListener('click', ccContinue);
}

function ccToggle() {
  if (!useLive()) { toast('演示模式'); return; }
  var on = !(CC.st && CC.st.on);
  api('PUT', '/api/ccode/switch', { on: on }).then(function (j) {
    if (CC.st) CC.st.on = on;
    toast(on ? 'Claude Code 开了：可以交任务了' : 'Claude Code 关了');
    ccodeLoad(true);
  }).catch(function (e) { toast('开关没改成：' + e.message, 5000); });
}

function ccRun() {
  var ta = $('#ccText'), text = ta ? ta.value.trim() : CC.text.trim();
  if (!text) { toast('写一句要它做的事'); if (ta) ta.focus(); return; }
  api('POST', '/api/ccode/run', { text: text }, 30000).then(function (j) {
    CC.text = ''; CC.job = j.job; renderCCode();
  }).catch(function (e) { toast(e.message, 6000); });
}

function ccStop() {
  api('POST', '/api/ccode/stop', {}, 15000).then(function (j) {
    CC.job = j.job; renderCCode(); toast(j.ok ? '停下了' : '它已经停了');
  }).catch(function (e) { toast(e.message, 5000); });
}

function ccContinue() {
  api('POST', '/api/ccode/continue', {}, 30000).then(function (j) {
    CC.job = j.job; renderCCode();
  }).catch(function (e) { toast(e.message, 6000); });
}
