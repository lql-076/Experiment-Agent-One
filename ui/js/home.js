'use strict';
/* ================= 主页「指挥舱」（v3.0 重做）=================
   一眼看清「现在在干什么、计划做到第几步、后台在跑什么」，字大、留白多，一屏放下：
   - 现在：左边大字写正在干什么；它列了计划（update_plan / Claude Code 的待办清单）就把清单放出来，一步一行，做完的打勾、正在做的亮着；
     下面一条进度：收到 → 分流 → 写文件 → 运行 → 回答，每步用了几秒。正在做的时候右下角有「停下」，想改方向直接在最下面的指令条里说（插话）。
     右边是核心（js/core.js）：闲着青色慢慢转，干活变琥珀色、外面一圈是计划（一段一步），每做一步冒一个字；说话、听写时跟着声音跳。点一下核心 = 开始说话。
     平时跟着最新一条；在「刚做完」里点一条就停在那条，顶上「回到最新」。两票投给谁、每一步的时间、判错了、换它重做，收在「细节」里。
   - 后台在跑：生图、配音、配乐、安装、一键补齐，每项一根进度条（和常驻屏同一份数据：后端 reports.tasks）；下面「等着的」：下一个提醒。
   - 刚做完：对话的事件 + 做完的活（生图一批、配音一段、配乐一首），写做了什么、交给谁、多久、花多少。
   - Agent 状态：只写几项正常，出问题的（启动中、卡住了、出错）才单独列出来，卡住的带「重启」。点「全部」看每一项。
   - 最下面是指令条（js/chat.js）：一直在，直接打字；Ctrl 空格展开对话记录，Esc 收起。 */
var NOW = { sel: null, detail: false, all: false, fast: null, fastBusy: false, sig: {}, tick: null };
var STEP_GROUP = { '语义路由': '分流', 'Kev': '分流', '决策脑打分': '分流', '按本事分': '分流', '你指定了去向': '分流', '你确认了发出本机': '分流', '记进想要的功能': '分流',
  '交给 DeepSeek': '', '不进训练集': '', '记为样本': '', '回复': '回答', '本地处理': '回答', '写提示词': '回答', '计划': '', '做好的文件': '', '你插了一句': '' };
var STEP_DOING = { '收到': '收下了', '分流': '正在决定交给谁', '联网搜索': '正在联网搜索', '读网页': '正在读网页', '读文件': '正在读文件', '查了说明书': '正在查说明书',
  '用了记忆': '正在翻记忆', '收到图片': '正在看图', '回答': '正在写回答', '排队': '排队中', '写文件': '正在写文件', '改文件': '正在改文件', '运行': '正在跑程序', '计划': '正在排计划',
  '看画面': '正在看画面', '看信息': '正在看文件信息', '看技能': '正在翻技能', '下载': '正在下载', '配音': '正在配音', '配乐': '正在出配乐', '生图': '正在出图', '交给 Claude Code': '交给 Claude Code 了',
  '看目录': '正在看文件夹', '找文件': '正在找文件', '搜内容': '正在搜内容', '收到文件': '正在看收到的文件' };
var DEMO_TASKS = [{ k: 'img', name: '生图 · 批量 · 第一期素材', phase: '第 5/8 张 · img05_紫苏_崩溃.png', pct: 56, eta: 150 },
  { k: 'tts', name: '生成配音 · 紫苏', phase: '第 3/5 句', pct: 48, eta: 40 }];
var DEMO_DONE = [{ ts: Date.now() / 1000 - 1500, name: '配音 · 白叶 · 36 句（2:41）', who: '百炼云端', sec: 52, cost: '¥0.31', tool: 'tts' },
  { ts: Date.now() / 1000 - 2400, name: '生图 · 批量 · 测试 4 · 12 张', who: 'API易', sec: 400, cost: '$0.36', tool: 'img' }];

function homeEvs() { return chatList().filter(function (e) { return e.src !== '定时任务' && e.src !== '系统'; }); }
function homeTasks() { return useLive() ? (D.state && D.state.tasks) || [] : DEMO_TASKS; }
function homeDoneJobs() { return useLive() ? (D.state && D.state.done_jobs) || [] : DEMO_DONE; }
function nowLive() {                                   // 正在处理的那条：自己刚发的（对话抽屉里）优先，其次 QQ 上来的
  var p = CHAT.pending && CHAT.pending.ev; if (p && p.status === 'running') return p;
  var l = homeEvs().filter(function (e) { return e.status === 'running'; }); return l.length ? l[l.length - 1] : null;
}
function nowView() {
  var list = homeEvs(), live = nowLive();
  if (NOW.sel != null) { var x = list.filter(function (e) { return e.id === NOW.sel; })[0]; if (x) return x; NOW.sel = null; }
  return live || list[list.length - 1] || null;
}
function secTxt(s) { if (s == null || isNaN(s)) return '—'; s = Math.max(0, s); return s < 10 ? s.toFixed(1) + ' 秒' : s < 60 ? Math.round(s) + ' 秒' : Math.floor(s / 60) + ' 分 ' + pad(Math.round(s % 60)) + ' 秒'; }
/* 每一步 → 几个大节点（语义路由、Kev、决策脑打分并成「分流」，几次联网搜索并成一个） */
function nowNodes(e) {
  var steps = e.steps || [], out = [], running = e.status === 'running';
  steps.forEach(function (s) {
    var g = STEP_GROUP.hasOwnProperty(s[0]) ? STEP_GROUP[s[0]] : s[0]; if (!g) return;
    var at = typeof s[2] === 'number' ? s[2] : null, last = out[out.length - 1];
    if (last && last.k === g) { last.n++; last.d = s[1]; return; }
    out.push({ k: g, at: at, n: 1, d: s[1] });
  });
  if (!out.length || out[0].k !== '收到') out.unshift({ k: '收到', at: 0, n: 1 });
  var hasAns = out.some(function (n) { return n.k === '回答'; });
  if (!running && !hasAns && e.status === 'done') out.push({ k: '回答', at: null, n: 1 });
  if (running && !hasAns) out.push({ k: '回答', at: null, n: 1, ghost: true });
  var age = e.ts ? Date.now() / 1000 - e.ts : null, total = e.latency != null ? +e.latency : null;
  out.forEach(function (n, i) {
    var nx = out[i + 1], end = nx && !nx.ghost && nx.at != null ? nx.at : (running ? age : total);
    n.st = n.ghost ? 'wait' : (running && (i === out.length - 1 || (out[i + 1] && out[i + 1].ghost))) ? 'act' : 'done';
    n.dur = n.at != null && end != null ? end - n.at : null;
  });
  if (out.length > 6) out = out.slice(0, 2).concat(out.slice(-4));
  return out;
}
function nowWhy(e) {
  var cap = (e.steps || []).filter(function (s) { return s[0] === '按本事分' || s[0] === '你指定了去向'; })[0];
  var why = cap ? cap[1].replace(/[（(].*$/, '').replace(/[，,；;]?\s*(→|交给|改交).*$/, '').trim() || confWord(e) : e.private ? (e.to === 'local' ? '涉及隐私，只在本地' : '涉及隐私，你确认了发出本机') : confWord(e);
  return '交给 ' + routeName(e) + (e.engine === 'cc' ? ' → Claude Code 动手' : '') + ' · ' + why;
}
/* 计划清单（v3.0）：最多放 rows 行，正在做的那步保证看得见；前后放不下的写「前面 n 步做完了」「后面还有 n 步」 */
function planHTML(e, rows) {
  var pl = e.plan || []; if (!pl.length) return '';
  rows = rows || 4;
  var cur = -1; pl.forEach(function (p, i) { if (cur < 0 && p.st === 'doing') cur = i; });
  if (cur < 0) pl.forEach(function (p, i) { if (cur < 0 && p.st !== 'done') cur = i; });
  if (cur < 0) cur = pl.length - 1;
  var a = Math.max(0, Math.min(cur - 1, pl.length - rows)), b = Math.min(pl.length, a + rows), h = '';
  if (a > 0) { a++; h += '<li class="pl-more"><i></i><span>前面 ' + a + ' 步做完了</span></li>'; }
  if (b < pl.length) b--;
  for (var i = a; i < b; i++) h += '<li class="pl-' + (pl[i].st || 'todo') + '"><i></i><span>' + esc(pl[i].text) + '</span></li>';
  if (b < pl.length) h += '<li class="pl-more"><i></i><span>后面还有 ' + (pl.length - b) + ' 步</span></li>';
  return '<ul class="hm-plan" aria-label="计划">' + h + '</ul>';
}
function planCount(e) { var pl = e.plan || [], d = pl.filter(function (p) { return p.st === 'done'; }).length; return pl.length ? d + '/' + pl.length : ''; }
function engChip(e) { return e.engine === 'cc' ? '<span class="hm-chip eng">Claude Code</span>' : ''; }
function nowHTML() {
  var e = nowView(), pinned = NOW.sel != null, live = nowLive();
  if (!e) return '<div class="hm-chiprow"><span class="label">现在</span><span class="hm-chip">闲着</span></div><div class="hm-mid"><div class="hm-title">闲着</div>' +
    '<div class="hm-sub">有事直接在下面打字，或者点一下右边的核心说话；QQ 上发也行。</div></div>';
  var running = e.status === 'running', nodes = nowNodes(e), act = nodes.filter(function (n) { return n.st === 'act'; })[0];
  var age = e.ts ? Date.now() / 1000 - e.ts : 0;
  var chip = running ? '<span class="hm-chip on"><i class="dot breathe"></i>处理中 · ' + secTxt(age) + '</span>' : pinned ? '<span class="hm-chip">停在这条</span>' : '<span class="hm-chip">闲着</span>';
  var back = pinned ? '<button class="btn mini' + (live && live.id !== e.id ? ' hot' : '') + '" data-now-follow="1">' + (live && live.id !== e.id ? '有新的一条在处理 · 回到最新' : '回到最新') + '</button>' : '';
  var title = running ? (STEP_DOING[act ? act.k : ''] || ('正在' + (act ? act.k : '处理'))) + (act && act.n > 1 ? '（第 ' + act.n + ' 次）' : '') : e.text;
  var lastStep = (e.steps || [])[(e.steps || []).length - 1], pc = planCount(e), hasPlan = !!pc;
  if (running && hasPlan) { var doing = (e.plan || []).filter(function (p) { return p.st === 'doing'; })[0]; if (doing) title = doing.text; }
  var sub = running ? (hasPlan && lastStep ? esc(lastStep[0] + ' · ' + String(lastStep[1] || '').slice(0, 60)) : '「' + esc(e.text) + '」') : esc('做完了 · 用了 ' + secTxt(e.latency) + (e.cost ? ' · ¥' + (+e.cost).toFixed(4) : e.to === 'local' ? ' · 免费' : '') + (e.status === 'queued' ? ' · 排队中' : ''));
  var steps = '<ol class="hm-steps" aria-label="做到第几步">' + nodes.map(function (n, i) {
    return '<li class="st-' + n.st + '"><i class="hm-dot' + (n.st === 'act' ? ' ping' : '') + '"></i>' + (i < nodes.length - 1 ? '<span class="hm-link' + (n.st === 'act' ? ' flow' : '') + '"></span>' : '') +
      '<b>' + esc(n.k) + (n.n > 1 ? ' ×' + n.n : '') + '</b><em class="num">' + (n.st === 'wait' ? '—' : secTxt(n.dur)) + '</em></li>'; }).join('') + '</ol>';
  return '<div class="hm-chiprow"><span class="label">现在</span>' + chip + engChip(e) + (pc ? '<span class="hm-chip num">计划 ' + pc + '</span>' : '') + back + '<span class="sp"></span><button class="btn mini ghost" data-now-detail="1" aria-expanded="' + NOW.detail + '">细节 ' + (NOW.detail ? '▴' : '▾') + '</button></div>' +
    '<div class="hm-mid' + (hasPlan ? ' has-plan' : '') + (running ? '' : ' fin') + '"><div class="hm-title' + (running ? ' caret' : '') + '">' + esc(title) + '</div><div class="hm-sub">' + sub + '</div>' + planHTML(e, 4) + '</div>' + steps +
    '<div class="hm-why"><span>' + esc(running && (!act || act.k === '收到' || act.k === '分流') ? '正在决定交给谁…' : nowWhy(e)) + '</span><span class="sp"></span>' +
      (running ? (useLive() && e.id ? '<button class="btn mini danger" data-ev-stop="' + e.id + '" title="停下这件事：正在跑的命令也停；做好的文件留着，说「继续」能接着做">停下</button>' : '')
        : nowOutBtn(e) + '<button class="btn mini" data-chat-open="1">看回答</button>') + '</div>' +
    (NOW.detail ? '<div class="hm-pop" role="dialog" aria-label="这条是怎么分的"><button class="hm-x" data-now-detail="1" aria-label="关掉细节">' + ICONS.cross + '</button>' + eventSideHTML(e) + '</div>' : '');
}
/* 这件事做出了文件（v2.3）：「现在」那块直接给一个「打开」按钮（第一个视频 / 音频 / 图片），别的在「看回答」里 */
function nowOutBtn(e) {
  var fs = (e.files || []).filter(isOut); if (!fs.length) return '';
  var f = fs.filter(function (x) { return x.kind === 'out'; })[0] || fs[0], nm = f.name.split('｜')[0];
  return '<button class="btn mini primary" data-out-open="' + f.id + '" data-how="' + (f.kind === 'out' ? 'file' : 'folder') + '" title="' + esc(f.path) + '">打开 ' + esc(nm.length > 18 ? nm.slice(0, 16) + '…' : nm) +
    (fs.length > 1 ? '（共 ' + fs.length + ' 个）' : '') + '</button>';
}
function jobsHTML() {
  var ts = homeTasks(), n = nextRem();
  var rows = ts.map(function (t) {
    var pct = t.pct != null ? Math.max(0, Math.min(100, +t.pct)) : null;
    return '<button class="hm-job" data-job="' + esc(t.k) + '"><span class="hj-top"><b>' + esc(t.name) + '</b><span class="sp"></span><em class="num">' +
      (t.eta ? '还要约 ' + rtDur(t.eta) : pct != null ? Math.round(pct) + '%' : '') + '</em></span><span class="hj-ph">' + esc(t.phase || '') + (t.speed ? ' · ' + rtSpeed(t.speed) : '') + '</span>' +
      '<i class="hj-bar' + (pct == null ? ' indet' : '') + '"><b style="transform:scaleX(' + ((pct || 0) / 100).toFixed(3) + ')"></b></i></button>';
  }).join('');
  var wait = [];
  if (n) wait.push(['提醒', (n.at || '') + ' ' + (n.title || '')]);
  var q = (D.state && D.state.asks_pending) || 0; if (useLive() && q) wait.push(['等你决定', q + ' 件（报告里点）']);
  return '<div class="hm-h"><span class="label">后台在跑</span><span class="cap">' + (ts.length ? ts.length + ' 个' : '') + '</span></div>' +
    '<div class="hm-jobs">' + (rows || '<div class="hm-none">现在没有在跑的</div>') + '</div>' +
    '<div class="hm-wait"><span class="label">等着的</span>' + (wait.length ? wait.map(function (w) { return '<div class="hw-row"><em>' + esc(w[0]) + '</em><span>' + esc(w[1]) + '</span></div>'; }).join('') : '<div class="hw-row"><span class="cap">没有</span></div>') + '</div>';
}
function doneRows() {
  var evRows = homeEvs().filter(function (e) { return e.status !== 'running'; }).map(function (e) {
    return { ts: e.ts || 0, t: e.t, title: e.text, who: routeName(e), dur: e.latency != null ? secTxt(e.latency) : '—', cost: e.cost ? '¥' + (+e.cost).toFixed(3) : e.to === 'local' ? '免费' : '', ev: e.id };
  });
  var jobRows = homeDoneJobs().map(function (j) { var d = new Date(j.ts * 1000); return { ts: j.ts, t: pad(d.getHours()) + ':' + pad(d.getMinutes()), title: j.name, who: j.who, dur: j.sec != null ? secTxt(j.sec) : '—', cost: j.cost || '', tool: j.tool }; });
  return evRows.concat(jobRows).sort(function (a, b) { return b.ts - a.ts; }).slice(0, 6);
}
function doneHTML() {
  var rows = doneRows(), st = D.state, tot = useLive() ? (st && st.today_total) || 0 : todaySplit().local + todaySplit().ds + todaySplit().neu + todaySplit().cl;
  return '<div class="hm-h"><span class="label">刚做完</span><span class="cap">今天 ' + tot + ' 件</span><span class="sp"></span><button class="linkbtn" data-open-tool="events">全部 ›</button></div>' +
    '<div class="hm-done">' + (rows.length ? rows.map(function (r) {
      return '<button class="hd-row' + (r.ev != null && NOW.sel === r.ev ? ' on' : '') + '"' + (r.ev != null ? ' data-now-pick="' + r.ev + '"' : ' data-job="' + esc(r.tool || '') + '"') + '>' +
        '<span class="num t">' + esc(r.t) + '</span><span class="x">' + esc(r.title) + '</span><span class="w">' + esc(r.who) + '</span><span class="num d">' + esc(r.dur) + '</span><span class="num c">' + esc(r.cost) + '</span></button>';
    }).join('') : '<div class="hm-none">还没做过事</div>') + '</div>';
}
var ST_WORD = { start: '启动中', stuck: '卡住了', warn: '要注意', bad: '出错', off: '没开' };
function statusHTML() {
  var a = agentData();
  if (!a) return '<div class="hm-h"><span class="label">Agent 状态</span></div><div class="hm-none">读取中…</div>';
  var items = [], c = { ok: 0, start: 0, stuck: 0, warn: 0, bad: 0, off: 0 };
  (a.groups || []).forEach(function (g) { g.items.forEach(function (it) { items.push(it); c[it.st === 'idle' ? 'ok' : it.st] = (c[it.st === 'idle' ? 'ok' : it.st] || 0) + 1; }); });
  var probs = items.filter(function (it) { return it.st === 'start' || it.st === 'stuck' || it.st === 'bad' || it.st === 'warn'; })
    .sort(function (x, y) { var o = { stuck: 0, bad: 1, warn: 2, start: 3 }; return o[x.st] - o[y.st]; });
  var K = a.kpi || {}, n = nextRem();
  var kp = [['DeepSeek 余额', K.bal ? K.bal.v : '—', K.bal ? K.bal.sub : ''], ['今天联网', K.search ? K.search.v + (K.search.unit ? ' ' + K.search.unit.replace(/\s*次$/, '') : '') : '—', K.search ? K.search.sub : ''],
    ['下一个提醒', n ? n.at : '—', n ? n.title : '没有']];
  var shown = probs.slice(0, 3);
  return '<div class="hm-h"><span class="label">Agent 状态</span><span class="sp"></span><button class="linkbtn" data-ag-all="1">全部 ' + items.length + ' 项 ›</button></div>' +
    '<div class="hs-sum"><b class="num">' + c.ok + '</b><span>项正常</span>' + ['start', 'stuck', 'warn', 'bad', 'off'].filter(function (k) { return c[k]; }).map(function (k) { return '<em class="st-' + k + '">' + c[k] + ' 项' + ST_WORD[k] + '</em>'; }).join('') + '</div>' +
    '<div class="hs-probs">' + (shown.length ? shown.map(function (it) {
      var btn = it.act ? '<button class="btn mini" ' + (it.act.do ? 'data-restart="' + esc(it.act.do) + '"' : 'data-go-sec="' + esc(it.act.sec || 'prep') + '"') + '>' + esc(it.act.label) + '</button>' : '';
      return '<div class="hs-row st-' + it.st + '"><i class="hm-sd' + (it.st === 'start' ? ' breathe' : '') + '"></i><b>' + esc(agShort(it)) + '</b><span title="' + esc(it.detail) + '">' + esc(it.detail) + '</span>' + btn + '</div>';
    }).join('') + (probs.length > shown.length ? '<div class="hs-more cap">还有 ' + (probs.length - shown.length) + ' 项，点「全部」看</div>' : '')
      : '<div class="hs-row st-ok"><i class="hm-sd"></i><b>全都正常</b></div>') + '</div>' +
    '<div class="hs-kpis">' + kp.map(function (k) { return '<div><span class="cap">' + esc(k[0]) + '</span><b class="num">' + esc(k[1]) + '</b><em>' + esc(k[2] || '') + '</em></div>'; }).join('') + '</div>' +
    (NOW.all ? agAllHTML(a) : '');
}
function agAllHTML(a) {
  return '<div class="hm-pop hm-all" role="dialog" aria-label="Agent 状态（全部）"><button class="hm-x" data-ag-all="1" aria-label="关掉">' + ICONS.cross + '</button>' +
    '<div class="label">Agent 状态 · 全部</div><div class="ha-grid">' + (a.groups || []).map(function (g) {
      return '<div class="ha-g"><span class="cap">' + esc(g.name) + '</span>' + g.items.map(function (it) {
        return '<div class="ha-row st-' + it.st + '" title="' + esc(it.name + '：' + it.detail) + '"><i class="hm-sd"></i><b>' + esc(agShort(it)) + '</b><span>' + esc(it.detail) + '</span></div>'; }).join('') + '</div>';
    }).join('') + '</div></div>';
}
function renderHome(quiet) {
  var v = $('#view-home'); if (!v) return;
  if (!$('#hmNow')) {
    v.innerHTML = '<div class="hm' + (quiet ? ' quiet' : '') + '"><section class="hm-card hm-now" id="hmNow" aria-label="现在在干什么"><div id="nwBody"></div>' +
      '<div class="nw-core" id="nwCore"><canvas id="coreCv" aria-hidden="true"></canvas><button class="core-hit" id="coreHit" aria-label="点一下开始说话；没开语音就是打开对话"></button>' +
      '<div class="core-cap"><b id="coreWord">STANDBY</b><span id="coreSub">待命</span></div></div></section><section class="hm-card" id="hmJobs" aria-label="后台在跑"></section>' +
      '<section class="hm-card" id="hmDone" aria-label="刚做完"></section><section class="hm-card" id="hmSt" aria-label="Agent 状态"></section><div class="hm-sbar" id="hmStrip" aria-hidden="true"></div></div>';
    NOW.sig = {};
    if (typeof coreMount === 'function') coreMount($('#coreCv'));
  }
  homeFill();
}
function setHTML(id, html) { if (NOW.sig[id] === html) return; NOW.sig[id] = html; var el = $('#' + id); if (el) el.innerHTML = html; }
function homeFill() {
  if (!$('#hmNow')) return;
  var e = nowView();
  setHTML('nwBody', nowHTML()); setHTML('hmJobs', jobsHTML()); setHTML('hmDone', doneHTML()); setHTML('hmSt', statusHTML());
  $('#hmNow').classList.toggle('live', !!(e && e.status === 'running'));
  if (typeof coreSync === 'function') coreSync();
  if (typeof chatBarSync === 'function') chatBarSync();
  nowFast();
}
/* 正在处理的那条：每 0.6 秒问一次后端到哪一步了（平时 5 秒才拉一次状态，太慢）；进度条上的秒数每 0.2 秒走一下 */
function nowFast() {
  var live = nowLive();
  clearInterval(NOW.tick); NOW.tick = null;
  if (live) NOW.tick = setInterval(function () { if (S.view === 'home' && root.dataset.mode === 'normal') setHTML('nwBody', nowHTML()); }, 250);
  if (!live || !useLive() || (CHAT.pending && CHAT.pending.token)) { clearTimeout(NOW.fast); NOW.fast = null; return; }
  if (NOW.fast) return;
  NOW.fast = setTimeout(function () {
    NOW.fast = null;
    var l = nowLive(); if (!l) return;
    api('GET', '/api/events/' + l.id, null, 4000).then(function (ne) {
      if (ne && ne.id) D.events = [ne].concat((D.events || []).filter(function (x) { return x.id !== ne.id; }));
      if (ne && ne.status !== 'running') poll();
      homeFill();
    }).catch(function () {});
  }, 600);
}
/* 停下一件正在做的事（主页的「停下」、指令条的「停下」都走这里） */
function evStop(id, btn) {
  if (!useLive() || !id) return;
  if (btn) { btn.disabled = true; btn.textContent = '在停…'; }
  api('POST', '/api/events/' + id + '/stop', {}, 15000).then(function (j) { toast((j && j.msg) || '让它停了：做到一半的会收个尾，做好的文件留着'); })
    .catch(function (e) { if (btn) { btn.disabled = false; btn.textContent = '停下'; } toast(/409/.test(e.message) || /不在做/.test(e.message) ? '这件事已经做完了' : '没停成：' + e.message); });
}
function homeFollow() { NOW.sel = null; NOW.detail = false; homeFill(); }
$('#view-home').addEventListener('click', function (ev) {
  var t = ev.target.closest('button, a'); if (!t) return;
  if (t.dataset.nowDetail) { NOW.detail = !NOW.detail; var e = nowView(); if (e) CHAT.sel = e.id; NOW.all = false; homeFill(); return; }
  if (t.dataset.nowFollow) { homeFollow(); return; }
  if (t.dataset.nowPick != null) { var id = +t.dataset.nowPick, l = homeEvs(); NOW.sel = (l.length && l[l.length - 1].id === id && !nowLive()) ? null : id; CHAT.sel = id; homeFill(); return; }
  if (t.dataset.chatOpen) { var ve = nowView(); chatOpen(ve && ve.id); return; }
  if (t.id === 'coreHit') { if (typeof voiceToggle === 'function' && voiceReady()) voiceToggle(); else { chatOpen(); } return; }
  if (t.dataset.evStop) { evStop(+t.dataset.evStop, t); return; }
  if (t.dataset.agAll) { NOW.all = !NOW.all; NOW.detail = false; homeFill(); return; }
  if (t.dataset.job != null) { var k = t.dataset.job; if (k === 'img') openView('img'); else if (k === 'tts') openView('tts'); else if (k === 'bgm') openView('bgm'); else if (k === 'tts_install') openSec('models'); else if (k === 'setup') openSec('prep'); return; }
  if (t.dataset.openTool) { openView(t.dataset.openTool); return; }
  if (t.dataset.restart) {
    t.disabled = true; t.textContent = '重启中…';
    api('POST', '/api/agent/restart/' + t.dataset.restart, {}, 15000).then(function (j) { toast(j.msg || '重启了，等一会儿'); poll(); }).catch(function (er) { t.disabled = false; t.textContent = '重启'; toast('没重启成：' + er.message); });
    return;
  }
  if (t.dataset.goSec) { openSec(t.dataset.goSec); return; }
  chatClick(ev);                                           // 细节里的「判错了」「换它重做」「去事件页看」，和对话里是同一套
});
document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && (NOW.detail || NOW.all) && !$('#view-chat').classList.contains('open')) { NOW.detail = false; NOW.all = false; homeFill(); } });
function updatePrepHome() { /* v2.0 起主页不再放整备的小卡（在 Agent 状态里） */ }
