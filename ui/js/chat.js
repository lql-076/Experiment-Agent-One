'use strict';
/* ================= 对话 =================
   左边一条窄栏只放你和它的一来一回（QQ 上发的也在这里）；回复按 Markdown 显示。
   每条回复下面一行小字：交给谁、把握、查了什么、花了多少——点它，右边换成"这条怎么处理的"（分数、为什么、每一步、来源、纠正）。
   右边大块平时是「Agent 状态」仪表盘：健康环、一条消息怎么走（链路图）、一排大数字、每项一个图标卡片，缺的直接给按钮。
   竖屏：仪表盘在上、对话在下，仪表盘能收起。
   发消息是异步的：先拿 token，每半秒问一次处理到哪了（正在联网搜索……），处理完换成回复。 */
var CHAT = { sel: null, tab: 'status', pending: null, more: null, dashMin: false, stick: true, sig: '' };
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
  if (e.private) bits.push(e.to === 'local' ? '隐私 · 只在本地' : '隐私 · 你确认了发出本机'); else bits.push(confWord(e));
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
  v.innerHTML = '<div class="chatv' + (CHAT.dashMin ? ' dash-min' : '') + '"><div class="chat-main">' +
    '<div class="chat-log" id="chatLog"></div>' +
    '<form class="composer" id="composer"><textarea id="cIn" rows="1" title="Enter 发送，Shift + Enter 换行" placeholder="' + (live ? '和它说点什么……（Enter 发送）' : '演示模式：启动.bat 打开后能聊') + '"' + (live ? '' : ' disabled') + '></textarea>' +
    '<button class="btn primary" type="submit" id="cSend"' + (live ? '' : ' disabled') + '>发送</button></form></div>' +
    '<aside class="chat-side" id="chatSide"><div class="side-head"><div class="seg" role="tablist"><button data-ctab="status" aria-pressed="' + (CHAT.tab === 'status') + '">Agent 状态</button>' +
    '<button data-ctab="event" aria-pressed="' + (CHAT.tab === 'event') + '">这条怎么处理的</button></div><span class="dash-sum" id="dashSum"></span><button class="side-toggle" id="sideToggle" aria-label="收起或展开状态">' + (CHAT.dashMin ? '展开 ▾' : '收起 ▴') + '</button></div>' +
    '<div class="side-body" id="sideBody"></div></aside></div>';
  CHAT.sig = ''; fillChatLog(true); fillSide();
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
/* ---------- Agent 状态（对话页右边的大仪表盘 + 总览上的小卡片） ----------
   每项一个专属图标，外面一圈状态环：有数的项（今天搜了几次、样本攒了多少、余额还剩多少）环就是进度，
   没数的项：正常满圈、闲着满圈但淡、要注意转圈、缺了红圈闪、没开只剩虚线。右下角一个小角标再标一次状态（不只靠颜色）。 */
var AGI = {
  route: '<circle cx="5" cy="12" r="2.2"/><circle cx="19" cy="5.5" r="2.2"/><circle cx="19" cy="12" r="2.2"/><circle cx="19" cy="18.5" r="2.2"/><path d="M7.2 12h9.6M7 11c4-1 5.6-4.8 9.8-5.3M7 13c4 1 5.6 4.8 9.8 5.3"/>',
  vote: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M7.5 9.2l1.6 1.6 3-3.2M14.2 9.5h2.6M7.5 15h2.8M13 15h3.8"/>',
  chip: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><rect x="9.6" y="9.6" width="4.8" height="4.8" rx=".8"/><path d="M9.5 3.5v3M14.5 3.5v3M9.5 17.5v3M14.5 17.5v3M3.5 9.5h3M3.5 14.5h3M17.5 9.5h3M17.5 14.5h3"/>',
  brain: '<circle cx="7" cy="8" r="2.5"/><circle cx="17" cy="8" r="2.5"/><circle cx="12" cy="17" r="2.5"/><path d="M8.3 10.2l2.4 4.6M15.7 10.2l-2.4 4.6M9.5 8h5"/>',
  sprout: '<path d="M12 20.5v-8.5"/><path d="M12 12c0-4 2.6-6.5 7-6.5 0 4.2-2.7 6.5-7 6.5z"/><path d="M12 14.5c0-3.3-2.2-5.5-6.5-5.5 0 3.6 2.4 5.5 6.5 5.5z"/><path d="M8 20.5h8"/>',
  cloud: '<path d="M7.5 18.5h10a3.8 3.8 0 0 0 .5-7.55A5.6 5.6 0 0 0 7.2 9.6 4.5 4.5 0 0 0 7.5 18.5z"/>',
  web: '<circle cx="10.5" cy="10.5" r="6.2"/><ellipse cx="10.5" cy="10.5" rx="2.6" ry="6.2"/><path d="M4.3 10.5h12.4M15.2 15.2l5 5"/>',
  prompt: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M3.5 8.8h17M7.5 12.5l2.6 2.2-2.6 2.2M12.5 17h4"/>',
  msg: '<path d="M4.5 6.5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H11l-4 3.5v-3.5h-.5a2 2 0 0 1-2-2z"/><path d="M8.6 10.5h.01M12 10.5h.01M15.4 10.5h.01" stroke-width="2.4"/>',
  bell: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  server: '<rect x="4" y="4" width="16" height="7" rx="1.8"/><rect x="4" y="13" width="16" height="7" rx="1.8"/><path d="M7.5 7.5h.01M7.5 16.5h.01" stroke-width="2.4"/><path d="M11 7.5h5M11 16.5h5"/>',
  gpu: '<rect x="3" y="6.5" width="18" height="10.5" rx="1.8"/><circle cx="8.8" cy="11.75" r="2.7"/><circle cx="15.6" cy="11.75" r="2.7"/><path d="M6 17v3M9 17v3M12 17v3"/>',
  pulse: '<path d="M3.5 12.5h3.6l2.1-5.5 3.6 10.5 2.6-7.5 1.4 2.5h3.7"/>',
  moon: '<path d="M19 14.8A7.8 7.8 0 0 1 9.2 5a7.8 7.8 0 1 0 9.8 9.8z"/><path d="M16.5 3.5v3.4M14.8 5.2h3.4"/>',
  pad: '<path d="M7.2 7.5h9.6a4.6 4.6 0 0 1 4.5 5.5l-.7 3.7a2.6 2.6 0 0 1-4.6 1.1L14.4 16H9.6L8 17.8a2.6 2.6 0 0 1-4.6-1.1L2.7 13a4.6 4.6 0 0 1 4.5-5.5z"/><path d="M8 10.3v3.4M6.3 12h3.4"/><path d="M15.3 11h.01M17.4 13h.01" stroke-width="2.4"/>',
  hourglass: '<path d="M7 3.5h10M7 20.5h10M8 3.5v3.2a4 4 0 0 0 1.6 3.2L12 12l2.4-2.1A4 4 0 0 0 16 6.7V3.5M8 20.5v-3.2a4 4 0 0 1 1.6-3.2L12 12l2.4 2.1a4 4 0 0 1 1.6 3.2v3.2"/>',
  book: '<path d="M12 6.5c-2-1.6-4.6-2-8-1.8v13.5c3.4-.2 6 .2 8 1.8 2-1.6 4.6-2 8-1.8V4.7c-3.4-.2-6 .2-8 1.8z"/><path d="M12 6.5v13.5"/>',
  coin: '<circle cx="12" cy="12" r="8"/><path d="M9 9.5h6M9 13h6M12 9.5V17"/>',
  tool: '<path d="M14.5 5.5a4 4 0 0 0 4.9 4.9l-8.6 8.6a2 2 0 0 1-2.8-2.8l8.6-8.6"/>',
  screen: '<rect x="3.5" y="4.5" width="17" height="11.5" rx="2"/><path d="M9 20h6M12 16v4"/>',
  antenna: '<circle cx="12" cy="11" r="2"/><path d="M12 13v7.5M9 20.5h6M8.2 7.2a5.4 5.4 0 0 0 0 7.6M15.8 7.2a5.4 5.4 0 0 1 0 7.6M5.4 4.4a9.3 9.3 0 0 0 0 13.2M18.6 4.4a9.3 9.3 0 0 1 0 13.2"/>',
  layers: '<path d="M12 3.5l8.5 4.5-8.5 4.5L3.5 8z"/><path d="M3.5 12l8.5 4.5 8.5-4.5M3.5 16l8.5 4.5 8.5-4.5"/>'
};
var AG_ICON = { embed: 'route', kev: 'vote', base: 'chip', lora: 'brain', loras: 'sprout', cats: 'sprout', ds: 'cloud', search: 'web', claude: 'prompt', qq: 'msg', remind: 'bell',
  backend: 'server', model: 'gpu', hw: 'pulse', nightly: 'moon', osd: 'pad', queue: 'hourglass', memory: 'book' };
var AG_SHORT = { embed: '语义路由', kev: 'Kev', base: '底座', loras: '小脑', cats: '新类别', ds: 'DeepSeek', search: '联网搜索', claude: '更强的模型', qq: 'QQ', remind: '提醒',
  backend: '后端', model: '模型服务', hw: '硬件监控', nightly: '每日差事', osd: '游戏内显示', queue: '排队', memory: '记忆' };
var AG_GROUP_ICON = { '大脑': 'brain', '云端': 'cloud', '通道': 'antenna', '后台': 'layers' };
var ST_ORDER = ['ok', 'idle', 'warn', 'bad', 'off'];
var ST_GLYPH = { ok: '<path d="M7 12.5l3.2 3.2L17 9"/>', idle: '<path d="M9.5 8v8M14.5 8v8"/>', warn: '<path d="M12 7v6.5M12 17v.2"/>', bad: '<path d="M8 8l8 8M16 8l-8 8"/>', off: '<path d="M8 12h8"/>' };
function agi(name, cls) { return '<svg class="i ' + (cls || '') + '" viewBox="0 0 24 24" aria-hidden="true">' + (AGI[name] || AGI.layers) + '</svg>'; }
function agKey(it) { var k = it.k || ''; return k.indexOf('lora:') === 0 ? 'lora' : k.indexOf('cat:') === 0 ? 'cat' : k; }
function agShort(it) { var k = agKey(it); return k === 'lora' ? it.name.replace(/^小脑\s*·\s*/, '') : k === 'claude' ? it.name : AG_SHORT[k] || it.name.split('（')[0]; }
function agSplit(name) { var m = /^(.*?)（(.*)）$/.exec(name || ''); return m ? [m[1], m[2]] : [name || '', '']; }
/* 图标外面那一圈：r=20，周长 125.66 */
function agBadge(it, sz) {
  var C = 125.66, p = it.m && it.m.p != null ? it.m.p : it.st === 'off' ? 0 : it.st === 'warn' ? .62 : 1;
  var len = Math.max(it.m && it.m.p != null && p > 0 ? 3 : 0, p * C);
  return '<span class="ab st-' + it.st + (sz ? ' ' + sz : '') + (it.m && it.m.p != null ? ' has-p' : '') + '"><svg class="ab-ring" viewBox="0 0 48 48" aria-hidden="true"><circle class="ab-t" cx="24" cy="24" r="20"/>' +
    '<circle class="ab-a" cx="24" cy="24" r="20" transform="rotate(-90 24 24)" stroke-dasharray="' + len.toFixed(1) + ' ' + C + '"/></svg>' + agi(AG_ICON[agKey(it)], 'ab-i') +
    '<svg class="ab-st" viewBox="0 0 24 24" aria-hidden="true">' + ST_GLYPH[it.st] + '</svg></span>';
}
var AGENT_DEMO = { head: '缺：Kev、底座', count: { ok: 9, idle: 1, warn: 1, bad: 2, off: 3 }, prep: { ready: 9, total: 14 },
  kpi: { bal: { st: 'ok', v: '¥8.59', p: .95, sub: '本月花了 ¥0.41' }, search: { st: 'ok', v: '7', unit: '/ 200 次', p: .035, sub: '本月 63 次 · ¥0.34' },
    remind: { st: 'ok', v: '22:00', sub: '吃药 · 共开着 3 条' }, mem: { st: 'ok', v: '12', unit: '段', sub: '说明书 240 段已建索引' }, prep: { st: 'warn', v: '9', unit: '/ 14 项', p: .64, sub: '缺 5 项 · 去补齐' } },
  groups: [
  { name: '大脑', items: [{ k: 'embed', name: '语义路由（嵌入模型）', st: 'ok', detail: '在线 · 决策脑第一票、找记忆、查说明书都靠它' },
    { k: 'kev', name: 'Kev（决策脑第二票）', st: 'bad', detail: '权重还没下载（约 2GB）', act: { label: '去补齐', sec: 'prep' } },
    { k: 'base', name: '本地通用（底座 MiniCPM5-2B）', st: 'bad', detail: '还没下载：本地小脑用不了，隐私的事只能排队', act: { label: '去补齐', sec: 'prep' } },
    { k: 'loras', name: '训练出来的小脑', st: 'off', detail: '还没有 · 某类事攒够样本、你同意后才训练 · 正在攒 2 类', m: { p: .43, txt: '最多 86 / 200' },
      sub: [{ k: 'cat:宠物', name: '宠物', st: 'idle', detail: '攒样本中 86 / 200', m: { p: .43, txt: '86 / 200' } }, { k: 'cat:做饭', name: '做饭', st: 'idle', detail: '攒样本中 37 / 200', m: { p: .185, txt: '37 / 200' } }] }] },
  { name: '云端', items: [{ k: 'ds', name: 'DeepSeek', st: 'ok', detail: 'Key 正常 · 余额 ¥8.59 · 模型 deepseek-flash', m: { p: .95, txt: '¥8.59' } },
    { k: 'search', name: '联网搜索', st: 'ok', detail: '开着 · 今天 7 / 200 次', m: { p: .035, txt: '7 / 200' } }, { k: 'claude', name: '更强的模型', st: 'ok', detail: '特别复杂的事写好提示词，你自己去问（网页 Claude、ChatGPT……）' }] },
  { name: '通道', items: [{ k: 'qq', name: 'QQ', st: 'warn', detail: '在线 · 还没绑定你的 QQ', act: { label: '去补齐', sec: 'prep' } }, { k: 'remind', name: '提醒', st: 'ok', detail: '开着 3 条 · 下一个 22:00 吃药', m: { txt: '22:00' } }] },
  { name: '后台', items: [{ k: 'backend', name: '后端', st: 'ok', detail: '127.0.0.1:8765 · 界面和所有接口' }, { k: 'model', name: '本地模型服务', st: 'ok', detail: '嵌入模型已加载 · 底座闲置 · 占显存 1.2 GB', m: { p: .15, txt: '1.2 GB' } },
    { k: 'hw', name: '硬件监控助手', st: 'off', detail: '没在运行：设置 › 硬件监控 打开' }, { k: 'nightly', name: '每日差事', st: 'idle', detail: '上次 5 小时前' },
    { k: 'osd', name: '游戏内显示', st: 'off', detail: '没开（设置 › 游戏内显示）', act: { label: '去打开', sec: 'osd' } },
    { k: 'queue', name: '排队的事', st: 'ok', detail: '没有' }, { k: 'memory', name: '记忆和说明书', st: 'ok', detail: '记忆 12 段 · 说明书 240 段已建索引', m: { txt: '12 · 240' } }] }] };
function agentData() { return useLive() ? (D.state && D.state.agent) || null : AGENT_DEMO; }
function agItems(a) { var o = {}; (a.groups || []).forEach(function (g) { g.items.forEach(function (it) { o[it.k] = it; }); }); return o; }
function agUsable(st) { return st === 'ok' || st === 'idle'; }
function agWorst(list) { return list.indexOf('bad') >= 0 ? 'bad' : list.indexOf('warn') >= 0 ? 'warn' : list.every(function (s) { return s === 'off'; }) ? 'off' : list.indexOf('ok') >= 0 ? 'ok' : 'idle'; }
/* 健康环：按状态分段 */
function agRing(c, sz) {
  var R = 42, C = 2 * Math.PI * R, tot = ST_ORDER.reduce(function (s, k) { return s + (c[k] || 0); }, 0) || 1, start = 0, gap = 2.2, arcs = '';
  ST_ORDER.forEach(function (k) {
    var n = c[k] || 0; if (!n) return;
    var len = Math.max(0, n / tot * C - gap);
    arcs += '<circle class="hr-a st-' + k + '" cx="50" cy="50" r="' + R + '" transform="rotate(-90 50 50)" stroke-dasharray="' + len.toFixed(2) + ' ' + C.toFixed(2) + '" stroke-dashoffset="' + (-start).toFixed(2) + '"/>';
    start += n / tot * C;
  });
  var ok = (c.ok || 0) + (c.idle || 0);
  return '<div class="hring' + (sz ? ' ' + sz : '') + '"><svg viewBox="0 0 100 100" aria-hidden="true"><circle class="hr-t" cx="50" cy="50" r="' + R + '"/>' + arcs + '</svg>' +
    '<div class="hr-c"><b class="num">' + ok + '<small>/' + (tot === 1 && !ok ? 0 : tot) + '</small></b><span>项能用</span></div></div>';
}
function agLegend(c, mini) {
  return '<div class="ag-legend' + (mini ? ' mini' : '') + '">' + ST_ORDER.map(function (k) {
    return '<span class="lgd st-' + k + (c[k] ? '' : ' zero') + '" title="' + ST_TXT[k] + ' ' + (c[k] || 0) + ' 项"><svg viewBox="0 0 24 24" aria-hidden="true">' + ST_GLYPH[k] + '</svg>' + (mini ? '' : ST_TXT[k]) + '<b class="num">' + (c[k] || 0) + '</b></span>';
  }).join('') + '</div>';
}
/* 顶上一排大数字 */
var KPI_DEF = [['bal', 'coin', 'DeepSeek 余额', 'cloud'], ['search', 'web', '今天联网搜索', 'cloud'], ['remind', 'bell', '下一个提醒', 'remind'], ['prep', 'tool', '整备', 'prep'], ['mem', 'book', '记忆', null]];
function agKpis(a) {
  var K = a.kpi || {};
  return '<div class="ag-kpis">' + KPI_DEF.map(function (d) {
    var k = K[d[0]]; if (!k) return '';
    var tag = d[3] ? 'button' : 'div';
    return '<' + tag + ' class="kp st-' + k.st + '"' + (d[3] ? ' data-go-sec="' + d[3] + '"' : '') + '><span class="kp-ic">' + agi(d[1]) + '</span><span class="kp-cap">' + d[2] + '</span>' +
      '<b class="kp-v num">' + esc(k.v) + (k.unit ? '<small>' + esc(k.unit) + '</small>' : '') + '</b><span class="kp-sub">' + esc(k.sub || '') + '</span>' +
      (k.p != null ? '<i class="kp-bar"><b style="transform:scaleX(' + Math.max(0, Math.min(1, k.p)) + ')"></b></i>' : '') + '</' + tag + '>';
  }).join('') + '</div>';
}
/* 一条消息怎么走：入口 → 决策脑（两票）→ 三个去向；下面一条提醒的专线（不经过任何模型） */
function agFlow(a) {
  var I = agItems(a), g = function (k, d) { return (I[k] || {}).st || d || 'off'; };
  var qq = g('qq'), em = g('embed'), kv = g('kev'), base = g('base'), ds = g('ds'), se = g('search'), cl = g('claude', 'ok'), rm = g('remind');
  var brainSt = agUsable(em) || agUsable(kv) ? (agUsable(em) && agUsable(kv) ? 'ok' : 'warn') : 'bad';
  var lor = (a.groups || []).reduce(function (n, gr) { return n + gr.items.filter(function (it) { return (it.k || '').indexOf('lora:') === 0; }).length; }, 0);
  var baseTxt = { ok: '底座已加载', idle: '底座闲着，用到才加载', warn: '底座要注意', bad: '底座没装', off: '底座没开' }[base] + ' · 小脑 ' + lor + ' 个';
  var pass = function (st) { return st !== 'bad' && st !== 'off'; };      // 要注意的（比如决策脑只剩一票）也算通
  var wire = function (from, to, a1, b1, color) { return [from, to, pass(a1) && pass(b1) ? 'on' : (a1 === 'bad' || b1 === 'bad') ? 'bad' : 'off', color]; };
  var wires = [wire('ui', 'brain', 'ok', brainSt, 'var(--accent)'), wire('qq', 'brain', qq, brainSt, 'var(--accent)'),
    wire('brain', 'local', brainSt, base, 'var(--c-local)'), wire('brain', 'ds', brainSt, ds, 'var(--c-ds)'), wire('brain', 'cl', brainSt, cl, 'var(--c-cl)')];
  var node = function (id, st, ic, name, sub, color) {
    return '<div class="fn st-' + st + '" data-fl="' + id + '"' + (color ? ' style="--rc:' + color + '"' : '') + '>' + agi(ic, 'fn-i') + '<div class="fn-t"><b>' + name + '</b>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</div><i class="fn-d"></i></div>';
  };
  return '<div class="ag-flow"><div class="fl-h"><span class="label">一条消息怎么走</span><span class="fl-key"><i class="on"></i>通的<i class="bad"></i>断了</span></div>' +
    '<div class="fl-grid" data-w="' + esc(JSON.stringify(wires)) + '">' +
    '<div class="fl-col n2">' + node('ui', 'ok', 'screen', '界面', '对话页') + node('qq', qq, 'msg', 'QQ', { ok: '在线', warn: '要注意', bad: '断了', off: '关着', idle: '闲着' }[qq]) + '</div><div class="fl-w"></div>' +
    '<div class="fl-col n1"><div class="fn fn-brain st-' + brainSt + '" data-fl="brain"><div class="fn-bh">' + agi('brain', 'fn-i') + '<b>决策脑</b><small>两票打分</small></div>' +
      '<div class="fn-r st-' + em + '">' + agi('route') + '<span>语义路由</span><i class="fn-d"></i></div><div class="fn-r st-' + kv + '">' + agi('vote') + '<span>Kev</span><i class="fn-d"></i></div></div></div><div class="fl-w"></div>' +
    '<div class="fl-col n3">' + node('local', base, 'chip', '本地小脑', baseTxt, 'var(--c-local)') +
      node('ds', ds, 'cloud', 'DeepSeek', agUsable(ds) ? (agUsable(se) ? '可以联网搜索' : '联网搜索' + (se === 'off' ? '关着' : '用不了')) : '用不了', 'var(--c-ds)') +
      node('cl', cl, 'prompt', esc(ROUTES.cl.name), cl === 'off' ? '你选了不用 · 难事也交 DeepSeek' : '写好提示词你去问', 'var(--c-cl)') + '</div>' +
  '</div><div class="fl-lane">' + node('rm', rm, 'bell', '提醒', '不经过任何模型') + '<span class="fl-arrow ' + (agUsable(rm) ? 'on' : 'off') + '"></span>' +
    '<div class="fl-dests"><span class="fd st-' + qq + '">' + agi('msg') + 'QQ</span><span class="fd-or">发不出就</span><span class="fd st-ok">' + agi('screen') + '电脑通知</span><span class="fd-or">同时</span><span class="fd st-ok">' + agi('layers') + '界面卡片</span></div></div></div>';
}
/* 链路图的连线：按节点的实际位置画（窗口一变就重画） */
var FLOW_RO = window.ResizeObserver ? new ResizeObserver(function (es) { es.forEach(function (e) { drawFlow(e.target); }); }) : null;
function drawFlow(g) {
  var w; try { w = JSON.parse(g.dataset.w || '[]'); } catch (e) { return; }
  var R = g.getBoundingClientRect(); if (!R.width || !R.height) return;
  var pos = function (id) { var n = g.querySelector('[data-fl="' + id + '"]'); if (!n) return null; var r = n.getBoundingClientRect(); return { l: r.left - R.left, r: r.right - R.left, y: r.top - R.top + r.height / 2 }; };
  var f = function (n) { return Math.round(n * 10) / 10; }, s = '';
  w.forEach(function (x) {
    var a = pos(x[0]), b = pos(x[1]); if (!a || !b) return;
    var x1 = a.r + 2, y1 = a.y, x2 = b.l - 3, y2 = b.y, dx = Math.max(10, (x2 - x1) * .5);
    s += '<path class="' + x[2] + '" style="--wc:' + x[3] + '" d="M' + f(x1) + ' ' + f(y1) + ' C' + f(x1 + dx) + ' ' + f(y1) + ' ' + f(x2 - dx) + ' ' + f(y2) + ' ' + f(x2) + ' ' + f(y2) + '"/>' +
      '<path class="hd ' + x[2] + '" style="--wc:' + x[3] + '" d="M' + f(x2 - 6) + ' ' + f(y2 - 4) + 'L' + f(x2 + 1) + ' ' + f(y2) + 'L' + f(x2 - 6) + ' ' + f(y2 + 4) + 'Z"/>';
  });
  var svg = g.querySelector('svg.fl-svg');
  if (!svg) { svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('class', 'fl-svg'); svg.setAttribute('aria-hidden', 'true'); g.appendChild(svg); }
  svg.setAttribute('viewBox', '0 0 ' + f(R.width) + ' ' + f(R.height)); svg.innerHTML = s;
}
function drawFlows(scope) {
  if (FLOW_RO) FLOW_RO.disconnect();
  $$('.fl-grid', scope).forEach(function (g) { drawFlow(g); if (FLOW_RO) FLOW_RO.observe(g); });
}
var AG_TILE_NAME = { loras: ['小脑', '训练出来的 LoRA'], cats: ['新类别', '正在攒样本'] };
/* 一项一行：图标 + 状态环 | 名字 · 副名 ……… 状态（缺了的换成按钮） | 一句话 | 有数的再加一条进度 */
function agTile(it) {
  var nm = agSplit(it.name), k = agKey(it);
  if (k === 'lora') nm = [agShort(it), 'LoRA 小脑'];
  else if (AG_TILE_NAME[k]) nm = AG_TILE_NAME[k];
  return '<div class="at st-' + it.st + '" data-k="' + esc(it.k || '') + '" title="' + esc(it.name + '：' + (ST_TXT[it.st] || '') + ' · ' + it.detail) + '">' + agBadge(it) +
    '<div class="at-b"><div class="at-h"><b class="at-n">' + esc(nm[0]) + '</b>' + (nm[1] ? '<em>' + esc(nm[1]) + '</em>' : '') +
    (it.act ? '<button class="at-act" data-go-sec="' + it.act.sec + '">' + esc(it.act.label) + ' →</button>' : '<span class="at-tag">' + (ST_TXT[it.st] || '') + '</span>') + '</div>' +
    '<p class="at-d">' + esc(it.detail) + '</p>' +
    (it.m && it.m.p != null && !it.sub ? '<div class="at-m"><i><b style="transform:scaleX(' + it.m.p + ')"></b></i><span class="num">' + esc(it.m.txt) + '</span></div>' : '') +
    (it.sub ? '<ul class="at-sub">' + it.sub.map(function (s) {
      return '<li class="st-' + s.st + '"><span>' + esc(s.name) + '</span><i><b style="transform:scaleX(' + ((s.m && s.m.p) || 0) + ')"></b></i><em class="num">' + esc((s.m && s.m.txt) || ST_TXT[s.st]) + '</em></li>';
    }).join('') + '</ul>' : '') + '</div></div>';
}
function agGroup(g, span) {
  var sts = g.items.map(function (it) { return it.st; }), ok = sts.filter(agUsable).length;
  return '<section class="ag-grp st-' + agWorst(sts) + '" style="--span:' + span + '"><header>' + agi(AG_GROUP_ICON[g.name] || 'layers', 'gi') + '<b>' + esc(g.name) + '</b>' +
    '<span class="gseg">' + g.items.map(function (it) { return '<i class="st-' + it.st + '" title="' + esc(agShort(it) + '：' + ST_TXT[it.st]) + '"></i>'; }).join('') + '</span>' +
    '<span class="cap num">' + ok + ' / ' + g.items.length + ' 能用</span></header><div class="ag-tiles">' + g.items.map(agTile).join('') + '</div></section>';
}
/* 按组排成几列，一屏放下：把几组按顺序分进 C 列——几组上下叠在一列，或者一组占两三列（里面再分两三列），
   挑最高那一列最矮的分法（组不多，全试一遍也很快） */
function agWeight(g) { return g.items.reduce(function (n, it) { return n + 1 + (it.m && it.m.p != null && !it.sub ? 0.25 : 0) + (it.sub ? 0.4 * it.sub.length : 0); }, 0); }
function agColumns(groups, C) {
  var H = function (g, span) { return Math.ceil(agWeight(g) / span) + 0.7; }, best = null;
  (function go(i, cols, used) {
    if (used > C) return;
    if (i === groups.length) {
      var mx = Math.max.apply(null, cols.map(function (c) { return c.h; })), score = mx + cols.length * 0.001;
      if (!best || score < best.score) best = { score: score, cols: cols, used: used };
      return;
    }
    for (var j = i, h = 0; j < groups.length; j++) { h += H(groups[j], 1); go(j + 1, cols.concat([{ groups: groups.slice(i, j + 1), span: 1, h: h }]), used + 1); }
    for (var sp = 2; sp <= C - used; sp++) go(i + 1, cols.concat([{ groups: [groups[i]], span: sp, h: H(groups[i], sp) }]), used + sp);
  })(0, [], 0);
  return best || { cols: [{ groups: groups, span: 1 }], used: 1 };
}
function agGroupsHTML(groups, C) {
  var L = agColumns(groups, C);
  return '<div class="ag-cols" data-c="' + C + '" style="--C:' + L.used + '">' + L.cols.map(function (c) {
    return '<div class="ag-col" style="grid-column:span ' + c.span + '">' + c.groups.map(function (g) { return agGroup(g, c.span); }).join('') + '</div>';
  }).join('') + '</div>';
}
function agCols() {                                   // 右边有多宽就分几列（每列至少 15rem）
  var b = $('#sideBody'), rem = parseFloat(getComputedStyle(root).fontSize) || 16;
  var w = b && b.clientWidth ? b.clientWidth - 2 * rem : 0;
  return w ? Math.max(1, Math.min(5, Math.floor(w / (15 * rem)))) : 4;
}
function agentHTML() {
  var a = agentData();
  if (!a) return '<div class="cap" style="padding:1rem 0">读取中……</div>';
  var c = a.count || {}, worst = c.bad ? 'bad' : c.warn ? 'warn' : 'ok';
  return '<div class="ag-dash"><div class="ag-top"><div class="ag-health st-' + worst + '">' + agRing(c) +
    '<div class="ag-sum"><b class="ag-hl">' + esc(a.head || '') + '</b>' + agLegend(c) +
    '<div class="ag-btns">' + (c.bad ? '<button class="btn mini primary" data-go-sec="prep">去补齐</button>' : '') + '<button class="btn mini" data-recheck="1">重新自检</button></div></div></div>' +
    agFlow(a) + '</div>' + agKpis(a) + agGroupsHTML(a.groups || [], agCols()) + '</div>';
}
/* 一屏放不下就收紧：先藏每项的那句话（停在上面还能看到），再缩健康环、链路图和大数字的小字 */
function agFit() {
  var b = $('#sideBody'), d = b && b.querySelector('.ag-dash'); if (!d || !b.clientHeight) return;
  d.classList.remove('dense', 'dense2');
  if (b.scrollHeight > b.clientHeight + 2) d.classList.add('dense');
  if (b.scrollHeight > b.clientHeight + 2) d.classList.add('dense2');
}
var SIDE_RO = window.ResizeObserver ? new ResizeObserver(function () {
  if (CHAT.tab !== 'status') return;
  var d = $('#sideBody .ag-cols'); if (d && +d.dataset.c !== agCols()) { CHAT.sig = ''; fillSide(); } else agFit();
}) : null;
/* 总览上的小卡片：健康环 + 一格一个图标 */
function agentMiniHTML() {
  var a = agentData();
  if (!a) return '<div class="cap" style="padding:1rem 0">读取中……</div>';
  var c = a.count || {}, worst = c.bad ? 'bad' : c.warn ? 'warn' : 'ok', all = [];
  (a.groups || []).forEach(function (g) { g.items.forEach(function (it) { all.push(it); }); });
  return '<div class="ag-mini"><div class="agm-top st-' + worst + '">' + agRing(c, 'sm') + '<div class="agm-s"><b class="ag-hl">' + esc(a.head || '') + '</b>' + agLegend(c, true) + '</div></div>' +
    '<div class="agm-grid">' + all.map(function (it) {
      var tip = it.name + '：' + ST_TXT[it.st] + ' · ' + it.detail + (it.act ? '（点了' + it.act.label + '）' : '');
      return '<button class="agm st-' + it.st + '" title="' + esc(tip) + '" ' + (it.act ? 'data-go-sec="' + it.act.sec + '"' : 'data-go-view="chat"') + '>' + agBadge(it, 'sm') +
        '<span class="agm-n">' + esc(agShort(it)) + '</span><em class="agm-v' + (it.m && it.m.txt ? ' num' : '') + '">' + esc(it.st === 'ok' && it.m && it.m.txt ? it.m.txt : ST_TXT[it.st]) + '</em></button>';
    }).join('') + '</div></div>';
}
/* ---------- 右边：这条怎么处理的 ---------- */
function eventSideHTML(e) {
  if (!e) return '<div class="cap" style="padding:1rem 0">点任意一条回复下面那行小字，这里会显示它是怎么处理的：交给谁、为什么、每一步、查了哪些网页。</div>';
  var links = [], seen = {};
  String(e.reply || '').replace(/https?:\/\/[^\s)）」"']+/g, function (u) { if (!seen[u]) { seen[u] = 1; links.push(u); } return u; });
  var steps = (e.steps && e.steps.length ? e.steps : [['收到', e.src]]);
  var fix = useLive() ? e.fix : S.fix[e.id];
  return '<div class="ev-side"><div class="es-col"><div class="cap num">' + esc((e.date ? e.date + ' ' : '') + e.t + ' · ' + e.src + ' · 事件 #' + e.id) + '</div>' +
    '<div class="es-q">' + esc(e.text) + '</div>' +
    '<div class="es-to" style="--c:' + ROUTES[e.to].color + '"><b>交给 ' + esc(routeName(e)) + '</b><span>' + (e.private ? (e.to === 'local' ? '隐私 · 只在本地' : '隐私 · 你确认了发出本机') : confWord(e) + ' · ' + e.s[e.to] + '%') + '</span></div>' +
    '<div class="es-bars">' + ORDER.map(function (k) { return '<div class="es-bar' + (k === e.to ? ' win' : '') + '" style="--c:' + ROUTES[k].color + '"><span>' + ROUTES[k].name + '</span><i><b style="transform:scaleX(' + (e.s[k] / 100) + ')"></b></i><em class="num">' + e.s[k] + '%</em></div>'; }).join('') + '</div>' +
    '<div class="label">为什么这么判</div><p class="es-why">' + esc(e.why || '—') + '</p>' +
    '<div class="es-cost cap">' + (e.cost ? '花了 ¥' + (+e.cost).toFixed(4) + ' · ' : '') + (e.latency ? '用时 ' + (+e.latency).toFixed(1) + ' 秒' : '') + '</div></div>' +
    '<div class="es-col"><div class="label">每一步</div><ol class="es-steps">' + steps.map(function (s, i) {
      var cur = e.status === 'running' && i === steps.length - 1;
      return '<li class="' + (cur ? 'cur' : 'done') + '"><b>' + esc(s[0]) + '</b><span>' + esc(s[1]) + '</span></li>';
    }).join('') + (e.status === 'running' ? '<li class="cur"><b>进行中</b><span>' + esc(e.result || '') + '</span></li>' : '') + '</ol>' +
    (links.length ? '<div class="label">查过的网页</div><ul class="es-links">' + links.slice(0, 6).map(function (u) { return '<li><a href="' + esc(u) + '" target="_blank" rel="noopener">' + esc(u.replace(/^https?:\/\//, '').slice(0, 60)) + '</a></li>'; }).join('') + '</ul>' : '') +
    '<div class="label">判错了？记一下应该交给（以后照这个判）</div><div class="es-fix">' + ORDER.map(function (k) { return '<button class="chip" data-cfix="' + k + '" aria-pressed="' + (fix === k) + '">' + ROUTES[k].name + '</button>'; }).join('') + '</div>' +
    (e.src === '定时任务' || e.src === '系统' ? '' : '<div class="label">换它重做（现在就按你选的再处理一遍，也会记下）</div><div class="es-fix">' + ['local', 'ds', 'cl'].filter(function (k) { return k !== e.to && (k !== 'cl' || strongOn()); }).map(function (k) {
      return '<button class="btn mini" data-redo="' + k + '">交给' + (k === 'local' ? '本地小脑' : ROUTES[k].name) + '重做</button>'; }).join('') + '</div>') +
    '<button class="linkbtn" data-open-events="' + e.id + '">在「事件」页看完整记录 →</button></div></div>';
}
function fillSide() {
  var b = $('#sideBody'); if (!b) return;
  $$('#chatSide [data-ctab]').forEach(function (x) { x.setAttribute('aria-pressed', x.dataset.ctab === CHAT.tab); });
  var a = agentData(), ds = $('#dashSum');                 // 竖屏收起时，标题栏上也留一行各状态的个数
  if (ds) ds.innerHTML = a ? agLegend(a.count || {}, true) : '';
  var html = CHAT.tab === 'event' ? eventSideHTML(findChatEv(CHAT.sel)) : agentHTML();
  if (html === CHAT.sig) return;                     // 没变就不重画（链路图的流动线、闪烁不会每 5 秒跳一下）
  CHAT.sig = html; b.innerHTML = html;
  drawFlows(b); agFit();
  if (SIDE_RO && !b.dataset.ro) { b.dataset.ro = 1; SIDE_RO.observe(b); }
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
      if (j.err) toast(j.confirm ? j.err + '（在「这条怎么处理的」里点「换它重做」可以确认后再发）' : '这条没处理完：' + j.err, 6000);
      fillChatLog(true); fillSide();
      return;
    }
    setTimeout(chatPoll, 500);
  }).catch(function () { setTimeout(chatPoll, 1200); });
}
/* 换它重做：同一句话按你选的去向再处理一遍（后端也记一次纠正）。隐私的事交给云端，要再点一次确认 */
function chatRedo(t) {
  var e = findChatEv(CHAT.sel), to = t.dataset.redo; if (!e) return;
  if (!useLive()) { toast('演示模式不能重做'); return; }
  if (CHAT.pending) { toast('上一条还在处理，等它好了再试'); return; }
  var allow = !!t.dataset.arm, name = to === 'local' ? '本地小脑' : ROUTES[to].name;
  t.disabled = true;
  api('POST', '/api/events/' + e.id + '/redo', { to: to, allow_private: allow }, 15000).then(function (j) {
    var d = new Date();
    CHAT.pending = { text: e.text, t: pad(d.getHours()) + ':' + pad(d.getMinutes()), step: '换「' + name + '」重做……', token: j.token };
    e.fix = to; fillChatLog(true); fillSide(); setTimeout(chatPoll, 400);
  }).catch(function (er) {
    t.disabled = false;
    if (er.status === 409) { t.dataset.arm = 1; t.textContent = '涉及隐私，再点一次确认发出本机'; t.classList.add('danger'); toast(er.message, 5000); }
    else toast('没重做成：' + er.message, 5000);
  });
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
    CHAT.sel = +t.dataset.ev; CHAT.tab = 'event'; CHAT.dashMin = false;
    $$('.why-chip').forEach(function (c) { c.setAttribute('aria-pressed', +c.dataset.ev === CHAT.sel); });
    $('#view-chat .chatv').classList.remove('dash-min'); var tg = $('#sideToggle'); if (tg) tg.textContent = '收起 ▴'; fillSide();
    setTimeout(function () { var m = $('.msg.ai[data-id="' + CHAT.sel + '"]'); if (m) m.scrollIntoView({ block: 'nearest' }); }, 320);     // 竖屏时仪表盘展开会挤一下对话，把这条留在看得见的地方
  }
  else if (t.dataset.ctab) { CHAT.tab = t.dataset.ctab; if (CHAT.tab === 'event' && !CHAT.sel) { var l = chatList().filter(function (e) { return e.src !== '定时任务'; }); CHAT.sel = l.length ? l[l.length - 1].id : null; } fillSide(); }
  else if (t.id === 'sideToggle') { CHAT.dashMin = !CHAT.dashMin; $('#view-chat .chatv').classList.toggle('dash-min', CHAT.dashMin); t.textContent = CHAT.dashMin ? '展开 ▾' : '收起 ▴'; }
  else if (t.dataset.goSec) { S.sec = t.dataset.goSec; renderSettings(); goView('settings'); }
  else if (t.dataset.recheck) { S.sec = 'prep'; renderSettings(); goView('settings'); setTimeout(function () { checkPanel(true); }, 450); }
  else if (t.dataset.openEvents) { S.selId = +t.dataset.openEvents; renderEvents(); goView('events'); }
  else if (t.id === 'chatMore') { t.disabled = true; api('GET', '/api/events?limit=300').then(function (l) { CHAT.more = l; var log = $('#chatLog'), h = log.scrollHeight; fillChatLog(false); log.scrollTop = log.scrollHeight - h; }).catch(function (e) { toast(e.message); }); }
  else if (t.dataset.redo) chatRedo(t);
  else if (t.dataset.cfix) {
    var e = findChatEv(CHAT.sel), k = t.dataset.cfix; if (!e) return;
    var to = (useLive() ? e.fix : S.fix[e.id]) === k ? null : k;
    if (useLive()) api('POST', '/api/events/' + e.id + '/fix', { to: to }).then(function (ne) { Object.assign(e, ne); fillSide(); toast(to ? '记下了：这类事以后交给「' + ROUTES[to].name + '」' : '取消了纠正'); }).catch(function (er) { toast(er.message); });
    else { if (to) S.fix[e.id] = to; else delete S.fix[e.id]; fillSide(); }
  }
});
