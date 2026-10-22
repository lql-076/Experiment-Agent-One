'use strict';
/* ================= 对话 =================
   中间只放你和它的一来一回（QQ 上发的也在这里）；回复按 Markdown 显示。
   每条回复下面一行小字：交给谁、把握、查了什么、花了多少——点它，右边才展开"这条怎么处理的"（分数、为什么、每一步、来源、纠正）。
   右边平时是「Agent 状态」：决策脑两票、底座和小脑、DeepSeek、联网搜索、QQ、后台程序……每项一个状态灯，缺的直接给按钮。
   发消息是异步的：先拿 token，每半秒问一次处理到哪了（正在联网搜索……），处理完换成回复。 */
var CHAT = { sel: null, tab: 'status', pending: null, more: null, sideOpen: false, stick: true };
var ST_TXT = { ok: '正常', idle: '闲着', warn: '要注意', bad: '缺了', off: '没开' };

function chatList() {
  var seen = {}, out = [];
  (CHAT.more || []).concat(evs() || []).forEach(function (e) { if (e && !seen[e.id]) { seen[e.id] = 1; out.push(e); } });
  return out.sort(function (a, b) { return (a.ts || a.id) - (b.ts || b.id) || a.id - b.id; }).slice(-160);
}
function confWord(e) {
  var p = e.s ? e.s[e.to] : 0;
  return p >= 70 ? '把握高' : p >= 50 ? '把握一般' : '把握低';
}
function stepCount(e, name) { return (e.steps || []).filter(function (s) { return s[0] === name; }).length; }
function routeName(e) { return e.to === 'local' ? (e.label && e.label.indexOf('提醒') < 0 ? e.label : '本地小脑') : ROUTES[e.to].name; }
function chipHTML(e) {
  var bits = [routeName(e)];
  if (e.private) bits.push('隐私 · 只在本地'); else bits.push(confWord(e));
  var s = stepCount(e, '联网搜索'), r = stepCount(e, '读网页');
  if (s || r) bits.push('联网 ' + s + ' 搜' + (r ? ' ' + r + ' 读' : ''));
  if (stepCount(e, '查了说明书')) bits.push('查了说明书');
  if (e.cost) bits.push('¥' + (+e.cost).toFixed(4));
  if (e.latency) bits.push((+e.latency).toFixed(1) + ' 秒');
  return '<button class="why-chip" data-ev="' + e.id + '" style="--c:' + ROUTES[e.to].color + '" aria-pressed="' + (CHAT.sel === e.id && CHAT.tab === 'event') + '">' +
    bits.map(esc).join(' · ') + ' <span aria-hidden="true">›</span></button>';
}
function msgHTML(e) {
  var src = e.src === 'QQ' ? '<span class="src-qq">QQ</span>' : '';
  if (e.src === '定时任务' || e.src === '系统') {
    return '<div class="sysline"><span>' + esc(e.t) + ' · ' + esc(e.text) + (e.result ? ' · ' + esc(String(e.result).split('；')[0]) : '') + '</span></div>';
  }
  var me = '<div class="msg me"><div class="bubble">' + esc(e.text) + '</div><div class="meta">' + src + esc((e.date ? e.date + ' ' : '') + e.t) + '</div></div>';
  var body;
  if (e.status === 'running') body = '<div class="bubble typing"><i></i><i></i><i></i><span>' + esc(e.result || '正在处理……') + '</span></div>';
  else if (e.status === 'queued') body = '<div class="bubble queued"><div class="q-tag">排队中 · 涉及隐私，等本地模型能用了再回你</div>' + mdHTML(e.reply || '') + '</div>';
  else body = '<div class="bubble md">' + (e.reply ? mdHTML(e.reply) : '<p class="cap">（没有回复）</p>') + fixHint(e.reply) + '</div>';
  return me + '<div class="msg ai" data-id="' + e.id + '" style="--c:' + ROUTES[e.to].color + '"><span class="ai-dot" aria-hidden="true"></span><div class="ai-col">' + body + chipHTML(e) + '</div></div>';
}
/* 出了问题的回复：直接给"下一步去哪"的按钮（出了什么事、为什么、怎么办） */
function fixHint(r) {
  r = r || '';
  if (/还没填 DeepSeek API Key/.test(r)) return '<div class="fix-hint"><button class="btn mini primary" data-go-sec="cloud">去填 DeepSeek Key</button></div>';
  if (/余额不足/.test(r)) return '<div class="fix-hint"><a class="btn mini primary" href="https://platform.deepseek.com/top_up" target="_blank" rel="noopener">去充值</a><button class="btn mini" data-go-sec="cloud">看余额</button></div>';
  if (/本地模型还没准备好|本地模型不可用/.test(r)) return '<div class="fix-hint"><button class="btn mini primary" data-go-sec="prep">去整备补齐本地模型</button></div>';
  if (/搜索次数.*用完/.test(r)) return '<div class="fix-hint"><button class="btn mini" data-go-sec="cloud">调高每天的搜索次数</button></div>';
  return '';
}
function pendingHTML() {
  var p = CHAT.pending; if (!p) return '';
  return '<div class="msg me"><div class="bubble">' + esc(p.text) + '</div><div class="meta">' + esc(p.t) + '</div></div>' +
    '<div class="msg ai pending"><span class="ai-dot" aria-hidden="true"></span><div class="ai-col"><div class="bubble typing"><i></i><i></i><i></i><span id="pendStep">' + esc(p.step) + '</span></div></div></div>';
}
function renderChat() {
  var v = $('#view-chat'); if (!v) return;
  var live = useLive();
  v.innerHTML = '<div class="chatv' + (CHAT.sideOpen ? ' side-open' : '') + '"><div class="chat-main">' +
    '<div class="chat-log" id="chatLog"></div>' +
    '<form class="composer" id="composer"><textarea id="cIn" rows="1" placeholder="' + (live ? '和它说点什么……（Enter 发送，Shift + Enter 换行）' : '演示模式：用 启动.bat 打开 Agent 后就能在这里聊') + '"' + (live ? '' : ' disabled') + '></textarea>' +
    '<button class="btn primary" type="submit" id="cSend"' + (live ? '' : ' disabled') + '>发送</button></form></div>' +
    '<aside class="chat-side" id="chatSide"><div class="side-head"><div class="seg" role="tablist"><button data-ctab="status" aria-pressed="' + (CHAT.tab === 'status') + '">Agent 状态</button>' +
    '<button data-ctab="event" aria-pressed="' + (CHAT.tab === 'event') + '">这条怎么处理的</button></div><button class="side-toggle" id="sideToggle" aria-label="展开或收起">' + (CHAT.sideOpen ? '收起' : '展开') + '</button></div>' +
    '<div class="side-body" id="sideBody"></div></aside></div>';
  fillChatLog(true); fillSide();
}
function fillChatLog(force) {
  var log = $('#chatLog'); if (!log) return;
  var near = force || log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  var list = chatList();
  var more = useLive() && !CHAT.more ? '<div class="more-row"><button class="linkbtn" id="chatMore">看更早的</button></div>' : '';
  log.innerHTML = list.length || CHAT.pending ? more + list.map(msgHTML).join('') + pendingHTML()
    : '<div class="chat-empty"><b>和它说点什么</b><p>比如：「你能做什么」「帕鲁最近更新了什么」「每天晚上十点提醒我喝水」「记住我的显示器是 27 寸的」。</p><p class="cap">QQ 上发的消息也会出现在这里。右边能看到它现在每个部分的状态。</p></div>';
  if (near) log.scrollTop = log.scrollHeight;
}
/* ---------- 右边：Agent 状态 ---------- */
var AGENT_DEMO = { head: '缺：Kev、底座', count: { ok: 7, idle: 2, warn: 1, bad: 2, off: 1 }, prep: { ready: 9, total: 14 }, groups: [
  { name: '大脑', items: [{ name: '语义路由（嵌入模型）', st: 'ok', detail: '在线 · 决策脑第一票、找记忆、查说明书都靠它' }, { name: 'Kev（决策脑第二票）', st: 'bad', detail: '权重还没下载（约 2GB）', act: { label: '去补齐', sec: 'prep' } },
    { name: '本地通用（底座 MiniCPM5-2B）', st: 'bad', detail: '还没下载：本地小脑用不了，隐私的事只能排队', act: { label: '去补齐', sec: 'prep' } },
    { name: '训练出来的小脑', st: 'off', detail: '还没有 · 某类事攒够样本、你同意后才训练 · 正在攒 1 类', sub: [{ name: '宠物', st: 'idle', detail: '攒样本中 37 / 200' }] }] },
  { name: '云端', items: [{ name: 'DeepSeek', st: 'ok', detail: 'Key 正常 · 余额 ¥8.59 · 模型 deepseek-flash' }, { name: '联网搜索', st: 'ok', detail: '开着 · 今天 7 / 200 次' }, { name: '网页 Claude', st: 'ok', detail: '特别复杂的事写好提示词，你自己去问' }] },
  { name: '通道', items: [{ name: 'QQ', st: 'warn', detail: '在线 · 还没绑定你的 QQ', act: { label: '去补齐', sec: 'prep' } }, { name: '提醒', st: 'ok', detail: '开着 1 条 · 下一个 22:00 吃药' }] },
  { name: '后台', items: [{ name: '后端', st: 'ok', detail: '127.0.0.1:8765' }, { name: '本地模型服务', st: 'ok', detail: '嵌入模型已加载 · 底座闲置' }, { name: '硬件监控助手', st: 'off', detail: '没在运行：双击 硬件监控.bat' },
    { name: '每日差事', st: 'idle', detail: '上次 5 小时前' }, { name: '排队的事', st: 'ok', detail: '没有' }, { name: '记忆和说明书', st: 'ok', detail: '记忆 12 段 · 说明书 240 段已建索引' }] }] };
function agentData() { return useLive() ? (D.state && D.state.agent) || null : AGENT_DEMO; }
function agentRow(it, small) {
  return '<div class="ag-row' + (small ? ' sub' : '') + '"><span class="ag-dot st-' + it.st + '" title="' + (ST_TXT[it.st] || '') + '"></span><div class="ag-main"><b>' + esc(it.name) + '</b><span>' + esc(it.detail) + '</span></div>' +
    (it.act ? '<button class="btn mini" data-go-sec="' + it.act.sec + '">' + esc(it.act.label) + '</button>' : '') + '</div>' +
    (it.sub ? it.sub.map(function (s) { return agentRow(s, true); }).join('') : '');
}
function agentHTML(compact) {
  var a = agentData();
  if (!a) return '<div class="cap" style="padding:1rem 0">读取中……</div>';
  var c = a.count || {};
  var pills = ['ok', 'idle', 'warn', 'bad', 'off'].filter(function (k) { return c[k]; }).map(function (k) { return '<span class="ag-pill st-' + k + '"><i></i>' + ST_TXT[k] + ' ' + c[k] + '</span>'; }).join('');
  return '<div class="ag-head"><b class="' + (c.bad ? 'bad' : c.warn ? 'warn' : 'ok') + '">' + esc(a.head || '') + '</b><div class="ag-pills">' + pills + '</div></div>' +
    (a.groups || []).map(function (g) {
      var items = compact ? g.items.filter(function (it) { return it.st !== 'ok'; }) : g.items;
      if (compact && !items.length) return '';
      return '<div class="ag-g"><div class="label">' + esc(g.name) + '</div>' + items.map(function (it) { return agentRow(it, false); }).join('') + '</div>';
    }).join('') +
    (a.prep ? '<div class="ag-foot"><span class="cap">整备 ' + a.prep.ready + ' / ' + a.prep.total + ' 项就绪</span><button class="linkbtn" data-recheck="1">重新自检</button></div>' : '');
}
/* ---------- 右边：这条怎么处理的 ---------- */
function eventSideHTML(e) {
  if (!e) return '<div class="cap" style="padding:1rem 0">点任意一条回复下面那行小字，这里会显示它是怎么处理的：交给谁、为什么、每一步、查了哪些网页。</div>';
  var links = [], seen = {};
  String(e.reply || '').replace(/https?:\/\/[^\s)）」"']+/g, function (u) { if (!seen[u]) { seen[u] = 1; links.push(u); } return u; });
  var steps = (e.steps && e.steps.length ? e.steps : [['收到', e.src]]);
  var fix = useLive() ? e.fix : S.fix[e.id];
  return '<div class="ev-side"><div class="cap num">' + esc((e.date ? e.date + ' ' : '') + e.t + ' · ' + e.src + ' · 事件 #' + e.id) + '</div>' +
    '<div class="es-q">' + esc(e.text) + '</div>' +
    '<div class="es-to" style="--c:' + ROUTES[e.to].color + '"><b>交给 ' + esc(routeName(e)) + '</b><span>' + (e.private ? '隐私 · 只在本地' : confWord(e) + ' · ' + e.s[e.to] + '%') + '</span></div>' +
    '<div class="es-bars">' + ORDER.map(function (k) { return '<div class="es-bar' + (k === e.to ? ' win' : '') + '" style="--c:' + ROUTES[k].color + '"><span>' + ROUTES[k].name + '</span><i><b style="transform:scaleX(' + (e.s[k] / 100) + ')"></b></i><em class="num">' + e.s[k] + '%</em></div>'; }).join('') + '</div>' +
    '<div class="label">为什么这么判</div><p class="es-why">' + esc(e.why || '—') + '</p>' +
    '<div class="label">每一步</div><ol class="es-steps">' + steps.map(function (s, i) {
      var cur = e.status === 'running' && i === steps.length - 1;
      return '<li class="' + (cur ? 'cur' : 'done') + '"><b>' + esc(s[0]) + '</b><span>' + esc(s[1]) + '</span></li>';
    }).join('') + (e.status === 'running' ? '<li class="cur"><b>进行中</b><span>' + esc(e.result || '') + '</span></li>' : '') + '</ol>' +
    (links.length ? '<div class="label">查过的网页</div><ul class="es-links">' + links.slice(0, 6).map(function (u) { return '<li><a href="' + esc(u) + '" target="_blank" rel="noopener">' + esc(u.replace(/^https?:\/\//, '').slice(0, 60)) + '</a></li>'; }).join('') + '</ul>' : '') +
    '<div class="es-cost cap">' + (e.cost ? '花了 ¥' + (+e.cost).toFixed(4) + ' · ' : '') + (e.latency ? '用时 ' + (+e.latency).toFixed(1) + ' 秒' : '') + '</div>' +
    '<div class="label">判错了？应该交给</div><div class="es-fix">' + ORDER.map(function (k) { return '<button class="chip" data-cfix="' + k + '" aria-pressed="' + (fix === k) + '">' + ROUTES[k].name + '</button>'; }).join('') + '</div>' +
    '<button class="linkbtn" data-open-events="' + e.id + '">在「事件」页看完整记录 →</button></div>';
}
function fillSide() {
  var b = $('#sideBody'); if (!b) return;
  $$('#chatSide [data-ctab]').forEach(function (x) { x.setAttribute('aria-pressed', x.dataset.ctab === CHAT.tab); });
  b.innerHTML = CHAT.tab === 'event' ? eventSideHTML(findChatEv(CHAT.sel)) : agentHTML(false);
}
function findChatEv(id) { return chatList().filter(function (e) { return e.id === id; })[0]; }
/* ---------- 发消息 ---------- */
function chatSend() {
  var inp = $('#cIn'); if (!inp || !useLive()) return;
  var text = inp.value.trim(); if (!text || CHAT.pending) return;
  inp.value = ''; autoGrow(inp);
  var d = new Date();
  CHAT.pending = { text: text, t: pad(d.getHours()) + ':' + pad(d.getMinutes()), step: '发出去了……', token: null };
  fillChatLog(true);
  api('POST', '/api/chat', { text: text, async: true }, 15000).then(function (j) { CHAT.pending.token = j.token; setTimeout(chatPoll, 400); })
    .catch(function (e) { CHAT.pending = null; fillChatLog(true); toast('没发出去：' + e.message, 5000); inp.value = text; });
}
function chatPoll() {
  var p = CHAT.pending; if (!p || !p.token) return;
  api('GET', '/api/chat/' + p.token, null, 8000).then(function (j) {
    if (j.event && !j.done) { p.step = j.event.result || p.step; var el = $('#pendStep'); if (el) el.textContent = p.step; }
    if (j.done) {
      CHAT.pending = null;
      if (j.event) { D.events = [j.event].concat((D.events || []).filter(function (e) { return e.id !== j.event.id; })); if (CHAT.tab === 'event') CHAT.sel = j.event.id; }
      if (j.err) toast('这条没处理完：' + j.err, 6000);
      fillChatLog(true); fillSide();
      return;
    }
    setTimeout(chatPoll, 500);
  }).catch(function () { setTimeout(chatPoll, 1200); });
}
function autoGrow(t) { t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 200) + 'px'; }
/* 后台每 5 秒拉一次状态：对话和右边跟着更新（不打断正在输入的） */
function chatRefresh() {
  if (S.view !== 'chat' || !$('#chatLog')) return;
  fillChatLog(false);
  if (CHAT.tab === 'status' || (CHAT.tab === 'event' && (findChatEv(CHAT.sel) || {}).status === 'running')) fillSide();
}

$('#view-chat').addEventListener('submit', function (ev) { ev.preventDefault(); chatSend(); });
$('#view-chat').addEventListener('keydown', function (ev) {
  if (ev.target.id === 'cIn' && ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); chatSend(); }
});
$('#view-chat').addEventListener('input', function (ev) { if (ev.target.id === 'cIn') autoGrow(ev.target); });
$('#view-chat').addEventListener('click', function (ev) {
  var t = ev.target.closest('button, a'); if (!t) return;
  if (t.dataset.ev) {
    CHAT.sel = +t.dataset.ev; CHAT.tab = 'event'; CHAT.sideOpen = true;
    $$('.why-chip').forEach(function (c) { c.setAttribute('aria-pressed', +c.dataset.ev === CHAT.sel); });
    $('#view-chat .chatv').classList.add('side-open'); var tg = $('#sideToggle'); if (tg) tg.textContent = '收起'; fillSide();
    setTimeout(function () { var m = $('.msg.ai[data-id="' + CHAT.sel + '"]'); if (m) m.scrollIntoView({ block: 'nearest' }); }, 320);     // 竖屏时右边变成下面一块，把这条留在看得见的地方
  }
  else if (t.dataset.ctab) { CHAT.tab = t.dataset.ctab; if (CHAT.tab === 'event' && !CHAT.sel) { var l = chatList().filter(function (e) { return e.src !== '定时任务'; }); CHAT.sel = l.length ? l[l.length - 1].id : null; } fillSide(); }
  else if (t.id === 'sideToggle') { CHAT.sideOpen = !CHAT.sideOpen; $('#view-chat .chatv').classList.toggle('side-open', CHAT.sideOpen); t.textContent = CHAT.sideOpen ? '收起' : '展开'; }
  else if (t.dataset.goSec) { S.sec = t.dataset.goSec; renderSettings(); goView('settings'); }
  else if (t.dataset.recheck) { S.sec = 'prep'; renderSettings(); goView('settings'); setTimeout(function () { checkPanel(true); }, 450); }
  else if (t.dataset.openEvents) { S.selId = +t.dataset.openEvents; renderEvents(); goView('events'); }
  else if (t.id === 'chatMore') { t.disabled = true; api('GET', '/api/events?limit=300').then(function (l) { CHAT.more = l; var log = $('#chatLog'), h = log.scrollHeight; fillChatLog(false); log.scrollTop = log.scrollHeight - h; }).catch(function (e) { toast(e.message); }); }
  else if (t.dataset.cfix) {
    var e = findChatEv(CHAT.sel), k = t.dataset.cfix; if (!e) return;
    var to = (useLive() ? e.fix : S.fix[e.id]) === k ? null : k;
    if (useLive()) api('POST', '/api/events/' + e.id + '/fix', { to: to }).then(function (ne) { Object.assign(e, ne); fillSide(); toast(to ? '记下了：这类事以后交给「' + ROUTES[to].name + '」' : '取消了纠正'); }).catch(function (er) { toast(er.message); });
    else { if (to) S.fix[e.id] = to; else delete S.fix[e.id]; fillSide(); }
  }
});
