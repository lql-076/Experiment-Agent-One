'use strict';
/* ================= 发布（v3.2，后端 app/publish.py） =================
   发到抖音：左边选要发的视频（工作区里最近的、选文件、填路径），中间写标题、简介、话题、封面、什么时候发，右边是抖音账号、正在做的、最近发的。
   - 扫码登录：二维码显示在右边，用抖音 App 扫。抖音要短信验证码时右边弹一个框。
   - 「发布到抖音」点两下才发（第一下变成「再点一下就发」，4 秒内不点就回去）：发出去是公开的，防手滑。
   - Agent 交来的（它的 publish_douyin，默认要你确认）：中间顶上一条一条列着，「填进来」看一眼、改一改再发，「不发」就扔掉。
   - 写到一半的标题、简介、话题存在浏览器里（关了窗口再开还在）。表单只画一次，刷新只动右边、左边列表和顶上那条。
   - v3.3 中间可以切到「批量」：填放视频和封面的文件夹 + 一份清单（.md / .txt，不选就用文件夹里的）→「认这一批」→ 一条一条定时发。
     开着「DeepSeek 帮我认」清单随便写；关着按固定格式（## 标题 / 视频： / 封面： / 简介： / 话题： / 定时： / 合集：）。 */
var PUB = { st: null, t: null, n: 0, busy: false, arm: 0, armT: null, up: null, f: null, sig: {}, lists: [], barm: 0 };
var PUB_KEY = 'agentPub.v1';
var PUB_DEMO = {
  demo: true, ready: { deps: true, browser: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', vendor: true },
  account: { has: true, ok: true, at: Date.now() / 1000 - 3600, msg: '登录还有效' }, job: null, pending: [],
  decls: ['内容由AI生成', '内容自行拍摄', '内容取材网络', '虚构演绎，仅供娱乐', '可能引人不适', '危险行为，请勿模仿'],
  opts: { headless: true, decl: '内容由AI生成' }, agent: { on: false, ask: true },
  videos: [
    { path: 'F:\\Agent\\工作区\\第5期\\成片_竖屏.mp4', rel: '第5期\\成片_竖屏.mp4', name: '成片_竖屏.mp4', size: 48e6, mtime: Date.now() / 1000 - 600 },
    { path: 'F:\\Agent\\工作区\\片头\\片头_10秒.mp4', rel: '片头\\片头_10秒.mp4', name: '片头_10秒.mp4', size: 6e6, mtime: Date.now() / 1000 - 86400 }],
  hist: [
    { id: 2, ts: Date.now() / 1000 - 86400, title: '本周 GitHub 最火的 5 个 AI 项目', file: '成片.mp4', st: 'done', msg: '发出去了', by: 'you', sec: 96 },
    { id: 1, ts: Date.now() / 1000 - 3 * 86400, title: '时间轴对齐：给每个字发一张火车票', file: '第4期.mp4', st: 'err', msg: '登录失效了，要重新扫码', by: 'agent', sec: 12 }]
};
function pubSt() { return useLive() ? PUB.st : PUB_DEMO; }
function pubForm() {
  if (PUB.f) return PUB.f;
  var f = null; try { f = JSON.parse(localStorage.getItem(PUB_KEY) || 'null'); } catch (e) { f = null; }
  PUB.f = Object.assign({ sel: null, title: '', desc: '', tags: '', timed: false, when: '', cover: null, decl: '', coll: '', pid: 0, mode: 'one', dir: '' }, f || {});
  return PUB.f;
}
function pubKeep() { try { localStorage.setItem(PUB_KEY, JSON.stringify(PUB.f)); } catch (e) { /* 存不了就算了 */ } }
function pubTime(ts) { var d = new Date(ts * 1000), n = new Date(); return (d.toDateString() === n.toDateString() ? '' : (d.getMonth() + 1) + '/' + d.getDate() + ' ') + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
function pubSize(b) { return b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : Math.max(1, Math.round(b / 1e6)) + ' MB'; }
function pubMinWhen() { var d = new Date(Date.now() + 2 * 3600e3 + 5 * 60e3); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
function pubTags(s) { return String(s || '').split(/[\s,，、#＃]+/).map(function (x) { return x.trim().slice(0, 20); }).filter(function (x, i, a) { return x && a.indexOf(x) === i; }).slice(0, 10); }

/* ---------- 画：架子只画一次 ---------- */
function pubShellHTML() {
  var f = pubForm(), s = pubSt() || PUB_DEMO, dis = useLive() ? '' : ' disabled';
  var decls = (s.decls || PUB_DEMO.decls), decl = f.decl || (s.opts && s.opts.decl) || decls[0];
  return '<div class="pb' + (f.mode === 'bat' ? ' bat' : '') + '">' +
    '<section class="hud pb-pn pb-vid"><div class="bg-h"><b>要发的视频</b><span>竖屏 9:16 最好</span></div>' +
      '<div class="pb-prev" id="pbPrev"></div>' +
      '<div class="pb-cap">工作区里最近的</div><div class="pb-vl" id="pbVl" role="list"></div>' +
      '<div class="pb-path"><input class="inp" id="pbPath" spellcheck="false" placeholder="或者填视频的完整路径"><button class="btn mini" data-pb="path"' + dis + '>用这个</button>' +
      '<label class="btn mini" for="pbFile"' + (useLive() ? '' : ' aria-disabled="true"') + '>选文件…</label><input type="file" id="pbFile" accept="video/*,.mp4,.mov,.webm,.mkv" hidden' + dis + '></div></section>' +
    '<section class="hud pb-pn pb-form"><div id="pbPend"></div><div class="bg-h"><b>写什么</b><div class="seg pb-mode" role="group" aria-label="一条还是批量">' +
      '<button data-pbmode="one" aria-pressed="' + (f.mode !== 'bat') + '">一条</button><button data-pbmode="bat" aria-pressed="' + (f.mode === 'bat') + '">批量</button></div><span>发出去就是公开的</span></div>' +
      '<div class="pb-one">' +
      '<div class="pb-f"><label class="pb-l" for="pbTitle">标题<em class="num" id="pbTn"></em></label><input class="inp" id="pbTitle" maxlength="30" placeholder="最多 30 字" value="' + esc(f.title) + '"></div>' +
      '<div class="pb-f pb-grow"><label class="pb-l" for="pbDesc">简介<em>可以不写</em></label><textarea class="inp" id="pbDesc" placeholder="说两句这条视频讲什么">' + esc(f.desc) + '</textarea></div>' +
      '<div class="pb-f"><label class="pb-l" for="pbTags">话题<em>空格隔开，不用打 #，最多 10 个</em></label><input class="inp" id="pbTags" spellcheck="false" placeholder="AI 开源 GitHub" value="' + esc(f.tags) + '"><div class="pb-tags" id="pbTagv"></div></div>' +
      '<div class="pb-2">' +
        '<div class="pb-f"><span class="pb-l">封面<em>可以不放</em></span><div class="pb-cover" id="pbCover"></div></div>' +
        '<div class="pb-f"><span class="pb-l">什么时候发</span><div class="seg" role="group" aria-label="什么时候发"><button data-pbwhen="0" aria-pressed="' + !f.timed + '">马上</button><button data-pbwhen="1" aria-pressed="' + !!f.timed + '">定时</button></div>' +
          '<input class="inp num" type="datetime-local" id="pbWhen" value="' + esc(f.when) + '"' + (f.timed ? '' : ' hidden') + '></div></div>' +
      '<div class="pb-2">' +
        '<div class="pb-f"><label class="pb-l" for="pbDecl">自主声明</label><select class="inp" id="pbDecl">' + decls.map(function (d) { return '<option' + (d === decl ? ' selected' : '') + '>' + esc(d) + '</option>'; }).join('') + '</select></div>' +
        '<div class="pb-f"><label class="pb-l" for="pbColl">合集<em>可以不填</em></label><input class="inp" id="pbColl" placeholder="已经建好的合集名" value="' + esc(f.coll) + '"></div></div>' +
      '<div class="pb-msg" id="pbMsg" role="status"></div>' +
      '<button class="btn primary bg-big pb-go" id="pbGo" data-pb="go"' + dis + '>发布到抖音</button></div>' + pubBatShellHTML(f, dis) + '</section>' +
    '<section class="hud pb-pn pb-side"><div class="bg-h"><b>抖音账号</b><span id="pbAcctSt"></span></div><div id="pbAcct"></div>' +
      '<div class="bg-h pb-h2"><b>正在做</b><span id="pbJobSt"></span></div><div class="pb-job" id="pbJob"></div>' +
      '<div class="bg-h pb-h2"><b>最近发的</b></div><div class="pb-hist" id="pbHist" role="list"></div></section></div>';
}
function pubBatShellHTML(f, dis) {
  return '<div class="pb-bat">' +
    '<div class="pb-f"><label class="pb-l" for="pbDir">视频和封面放在哪个文件夹<em>完整路径，或者工作区里的（比如 第5期\\成片）</em></label>' +
      '<div class="pb-path"><input class="inp" id="pbDir" spellcheck="false" placeholder="F:\\视频\\第5期" value="' + esc(f.dir) + '"><button class="btn mini primary" data-pb="bload"' + dis + '>认这一批</button></div></div>' +
    '<div class="pb-bopt"><label class="btn mini" for="pbListFile"' + (useLive() ? '' : ' aria-disabled="true"') + '>选清单…</label><input type="file" id="pbListFile" accept=".md,.markdown,.txt" multiple hidden' + dis + '>' +
      '<span class="cap" id="pbListN"></span>' + smartBtn() + '</div>' +
    '<div id="pbBw"></div><div class="pb-bl" id="pbBl" role="list"></div><div class="pb-msg" id="pbBm" role="status"></div>' +
    '<div class="pb-bfoot" id="pbBf"></div></div>';
}
function pubBatSync(s, run, live) {
  var b = s.batch, f = pubForm(), dis = live ? '' : ' disabled';
  pubPut('pbListN', PUB.lists.length ? '清单：' + esc(PUB.lists.map(function (x) { return x.name; }).join('、')) + ' <button class="linkbtn" data-pb="unlist">不用了</button>' : '不选就用文件夹里的 .md / .txt');
  if (!b) {
    pubPut('pbBw', '');
    pubPut('pbBl', '<div class="pb-none pb-bhelp"><b>一期好几条，一次定时发完</b><br>1. 视频和封面放进同一个文件夹（名字对得上就行，比如 01_成片.mp4、01_封面.png）<br>2. 写一份清单：每条的标题、简介、话题、定时发布的时间、合集<br>3. 填上面的文件夹，点「认这一批」，看一眼每一条，再点「全部定时发出去」</div>');
    pubPut('pbBm', ''); pubPut('pbBf', ''); return;
  }
  var its = b.items, ok = its.filter(function (x) { return x.st === 'ok'; }).length, bad = its.filter(function (x) { return x.st === 'err'; }).length;
  var can = its.filter(function (x) { return x.st === 'idle'; }).length;
  pubPut('pbBw', '<div class="pb-bh"><b title="' + esc(b.folder_show) + '">' + esc(b.title) + '</b><span class="cap num">' + its.length + ' 条 · 能发 ' + can + (ok ? ' · 发了 ' + ok : '') + (bad ? ' · 有问题 ' + bad : '') + '</span>' +
    '<button class="linkbtn" data-pb="bclear"' + (b.running ? ' disabled' : '') + '>换一批</button></div>' +
    (b.warn && b.warn.length ? '<div class="mb-warn">' + b.warn.map(esc).join('；') + '</div>' : '') + (b.halt ? '<div class="mb-warn">' + esc(b.halt) + '</div>' : ''));
  pubPut('pbBl', its.map(function (it, i) {
    var st = { idle: '待发', queue: '排着', run: '正在发', ok: it.schedule ? '定时好了' : '发了', err: '有问题' }[it.st] || it.st;
    var meta = [it.video_show ? '▶ ' + esc(it.video_show) : '<em class="bad">没找到视频' + (it.video_raw ? '「' + esc(it.video_raw) + '」' : '') + '</em>',
      it.cover_show ? '封面 ' + esc(it.cover_show) : '没封面', it.schedule ? '定时 ' + esc(it.schedule) : '<em class="bad">没写定时</em>'].concat(it.collection ? ['合集 ' + esc(it.collection)] : []);
    return '<div class="pb-br ' + it.st + '" role="listitem"><span class="n num">' + pad(i + 1) + '</span><div class="x"><b title="' + esc(it.desc || '') + '">' + esc(it.title || '（没写标题）') + '</b>' +
      '<span>' + meta.join(' · ') + '</span>' + ((it.tags || []).length ? '<span class="tg">' + it.tags.map(function (t) { return '#' + esc(t); }).join(' ') + '</span>' : '') +
      (it.err ? '<span class="bad">' + esc(it.err) + '</span>' : it.st === 'run' && it.msg ? '<span>' + esc(it.msg) + '</span>' : '') + '</div><span class="r">' + st + '</span></div>';
  }).join(''));
  var acct = s.account || {}, why = !live ? '演示模式' : b.running ? '' : run ? '正在' + ((s.job || {}).name || '做别的') : !s.ready.deps ? '先在右边装发布用的组件' : !acct.has ? '先在右边扫码登录' : !can ? '没有能发的：标红的看一下哪里不对，改好清单再认一次' : '';
  pubPut('pbBm', why ? '<span class="cap">' + esc(why) + '</span>' : '');
  pubPut('pbBf', b.running ? '<button class="btn danger bg-big" data-pb="bstop">停下（正在发的这条发完前会断掉）</button>' :
    '<button class="btn primary bg-big pb-go' + (PUB.barm ? ' armed' : '') + '" data-pb="bgo"' + (why ? ' disabled' : '') + '>' + (PUB.barm ? '再点一下：' + can + ' 条全部发出去' : (ok ? '接着发剩下的 ' : '全部定时发出去 · ') + can + ' 条') + '</button>');
}
function renderPub() {
  var v = $('#view-publish'); if (!v) return;
  if (!v.querySelector('.pb')) { v.innerHTML = pubShellHTML(); PUB.sig = {}; }
  pubSync();
}
function pubPut(id, html) { if (PUB.sig[id] === html) return; var el = $('#' + id); if (!el) return; PUB.sig[id] = html; el.innerHTML = html; }

/* ---------- 画：会变的那几块 ---------- */
function pubSync() {
  var s = pubSt(); if (!s || !$('#view-publish .pb')) return;
  var f = pubForm(), j = s.job, run = !!(j && j.st === 'run'), live = useLive(), dis = live ? '' : ' disabled';
  /* 左边：预览 + 最近的视频 */
  var sel = f.sel;
  pubPut('pbPrev', PUB.up ? '<div class="pb-empty"><b class="num">' + PUB.up.pct + '%</b><span>正在放进工作区：' + esc(PUB.up.name) + '</span></div>' :
    sel ? (live ? '<video id="pbVideo" src="/api/publish/media?path=' + encodeURIComponent(sel.path) + '" controls preload="metadata"></video>' : '<div class="pb-empty pb-fake"><b>▶</b><span>演示：这里放视频预览</span></div>') +
      '<div class="pb-sel"><b title="' + esc(sel.path) + '">' + esc(sel.name) + '</b><span class="num">' + (sel.size ? pubSize(sel.size) : '') + '</span><button class="linkbtn" data-pb="unsel">换一个</button></div>' :
    '<div class="pb-empty pb-drop" data-pbdrop="video"><b>把视频拖进来</b><span>或者点下面工作区里的一个</span></div>');
  pubPut('pbVl', (s.videos || []).length ? s.videos.map(function (x) {
    var on = sel && sel.path === x.path;
    return '<button class="bg-row pb-v' + (on ? ' on' : '') + '" role="listitem" data-pbv="' + esc(x.path) + '"><span class="t">' + pubTime(x.mtime) + '</span><span class="x" title="' + esc(x.rel) + '">' + esc(x.rel) + '</span><span class="d">' + pubSize(x.size) + '</span></button>';
  }).join('') : '<div class="pb-none">工作区里还没有视频。让 Agent 做一条，或者把视频拖进来</div>');
  /* 中间：Agent 交来的、话题、封面、字数、按钮 */
  pubPut('pbPend', (s.pending || []).map(function (p) {
    var it = p.item, cur = f.pid === p.id;
    return '<div class="pb-pend' + (cur ? ' on' : '') + '"><div><b>Agent 想发：' + esc(it.title) + '</b><span>' + esc(it.name) + (it.schedule ? ' · 定时 ' + esc(it.schedule) : '') + ' · ' + pubTime(p.ts) + '</span></div>' +
      '<button class="btn mini" data-pbpend="' + p.id + '" data-act="fill"' + dis + '>' + (cur ? '已填进来' : '填进来看看') + '</button><button class="btn mini ghost" data-pbpend="' + p.id + '" data-act="drop"' + dis + '>不发</button></div>';
  }).join(''));
  var tags = pubTags(f.tags);
  pubPut('pbTagv', tags.map(function (t) { return '<span>#' + esc(t) + '</span>'; }).join(''));
  pubPut('pbCover', f.cover ? '<span class="pb-cv" title="' + esc(f.cover.path) + '">' + (live ? '<img src="/api/publish/media?path=' + encodeURIComponent(f.cover.path) + '" alt="">' : '') + '<b>' + esc(f.cover.name) + '</b></span><button class="linkbtn" data-pb="uncover">去掉</button>' :
    '<label class="btn mini" for="pbCoverFile"' + (live ? '' : ' aria-disabled="true"') + '>选一张图…</label><input type="file" id="pbCoverFile" accept="image/*" hidden' + dis + '><span class="pb-hint">竖的 3:4 或横的 4:3</span>');
  var tn = $('#pbTn'); if (tn) { var n = (f.title || '').length; tn.textContent = n + ' / 30'; tn.classList.toggle('bad', n > 30); }
  var w = $('#pbWhen'); if (w) { w.hidden = !f.timed; w.min = pubMinWhen(); }
  var go = $('#pbGo');
  if (go) {
    var acct = s.account || {};
    var why = !live ? '演示模式' : run ? '正在' + (j.name || '做别的') : !s.ready.deps ? '先在右边装发布用的组件' : !s.ready.browser ? '没找到 Chrome / Edge' : !acct.has ? '先在右边扫码登录' : !sel ? '先选一个视频' : !(f.title || '').trim() ? '标题还没写' : f.timed && !f.when ? '定时的话选个时间' : '';
    go.disabled = !!why;
    go.textContent = PUB.arm ? '再点一下就发' : f.pid ? '确认，发 Agent 这一条' : '发布到抖音';
    go.classList.toggle('armed', !!PUB.arm);
    pubPut('pbMsg', why && live ? '<span class="cap">' + esc(why) + '</span>' : PUB.msg ? PUB.msg : '');
  }
  if (s.batch !== undefined || f.mode === 'bat') pubBatSync(s, run, live);
  /* 右边：账号 */
  var a = s.account || {}, r = s.ready || {};
  var acctSt = !r.deps ? '<em class="warn">组件没装</em>' : !r.browser ? '<em class="bad">没有浏览器</em>' : !a.has ? '<em class="warn">没登录</em>' : a.ok === false ? '<em class="bad">登录失效了</em>' : '<em class="ok">登录了</em>';
  pubPut('pbAcctSt', acctSt);
  pubPut('pbAcct', !r.deps ? '<p class="pb-p">发布用的组件（patchright、loguru，约 40MB）还没装上。一般解压后第一次启动会自己装；没装上点这里。</p><div class="btnrow"><button class="btn primary" data-pb="install"' + dis + (run ? ' disabled' : '') + '>装一下</button></div>' :
    !r.browser ? '<p class="pb-p">没找到 Chrome 或 Edge。到 设置 › 发布 填浏览器在哪（chrome.exe / msedge.exe）。</p><div class="btnrow"><button class="btn" data-go-sec="publish">去设置</button></div>' :
    !a.has ? '<p class="pb-p">点「扫码登录」，二维码会出现在下面，用抖音 App 扫一下（App 首页左上角 ≡ › 扫一扫）。登录信息加密存在这台电脑上。</p><div class="btnrow"><button class="btn primary" data-pb="login"' + dis + (run ? ' disabled' : '') + '>扫码登录</button></div>' :
    '<p class="pb-p">' + (a.ok === false ? '抖音那边的登录失效了，重新扫一下码。' : '上次确认：' + (a.at ? pubTime(a.at) : '还没确认过') + (a.msg ? ' · ' + esc(a.msg) : '')) + '</p>' +
      '<div class="btnrow"><button class="btn' + (a.ok === false ? ' primary' : '') + '" data-pb="login"' + dis + (run ? ' disabled' : '') + '>' + (a.ok === false ? '重新扫码' : '换个号 / 重扫') + '</button>' +
      '<button class="btn ghost" data-pb="check"' + dis + (run ? ' disabled' : '') + '>看看还在不在</button><button class="btn ghost" data-pb="logout"' + dis + (run ? ' disabled' : '') + '>退出</button></div>');
  /* 右边：正在做 */
  pubPut('pbJobSt', run ? '<span class="num">' + mbClock(j.elapsed) + '</span>' : '');
  var jh = '';
  if (run) {
    jh += '<div class="pb-now"><i class="pb-spin" aria-hidden="true"></i><b>' + esc(j.name) + (j.title ? '：' + esc(j.title) : '') + '</b></div>';
    if (j.qr) jh += '<div class="pb-qr"><img src="' + esc(j.qr) + '" alt="抖音登录二维码"><span>用抖音 App 扫这个码<br>App 首页左上角 ≡ › 扫一扫</span></div>';
    if (j.sms) jh += '<div class="pb-sms"><label for="pbCode">抖音要短信验证码</label><input class="inp num" id="pbCode" inputmode="numeric" maxlength="8" placeholder="手机收到的几位数字"><button class="btn primary" data-pb="code">交过去</button></div>';
    jh += '<div class="pb-log">' + (j.log || []).slice(-8).map(function (x) { return '<div>' + esc(x) + '</div>'; }).join('') + '</div>';
    jh += '<div class="btnrow"><button class="btn danger" data-pb="stop">停下</button></div>';
  } else if (j) jh = '<div class="tts-msg ' + (j.st === 'done' ? 'ok' : 'bad') + '">' + esc(j.name) + '：' + esc(j.msg) + '</div>';
  else jh = '<div class="pb-none">没在做什么</div>';
  if (!(run && $('#pbCode') && document.activeElement === $('#pbCode'))) pubPut('pbJob', jh);
  /* 右边：最近发的 */
  pubPut('pbHist', (s.hist || []).length ? s.hist.map(function (h) {
    var ok = h.st === 'done';
    return '<div class="pb-hr" role="listitem"><span class="t num">' + pubTime(h.ts) + '</span><span class="x" title="' + esc(h.msg || '') + '">' + esc(h.title) + (h.by === 'agent' ? '<em>Agent</em>' : h.by === 'batch' ? '<em>批量</em>' : '') + '</span>' +
      '<span class="r ' + (ok ? 'ok' : 'bad') + '">' + (ok ? (h.schedule ? '定时' : '发了') : h.st === 'stop' ? '停了' : '没成') + '</span></div>';
  }).join('') : '<div class="pb-none">还没发过</div>');
}

/* ---------- 读 ---------- */
function pubFetch() {
  if (!useLive()) { pubSync(); return Promise.resolve(); }
  return api('GET', '/api/publish', null, 8000).then(function (j) {
    var was = PUB.st && PUB.st.job && PUB.st.job.st === 'run' ? PUB.st.job : null;
    PUB.st = j; pubSync();
    if (was && j.job && j.job.id === was.id && j.job.st !== 'run') toast(j.job.name + '：' + j.job.msg, 7000);
  }).catch(function () {});
}
function pubEnter() {
  pubFetch(); clearInterval(PUB.t);
  PUB.t = setInterval(function () {
    PUB.n++;
    var run = PUB.st && ((PUB.st.job && PUB.st.job.st === 'run') || (PUB.st.batch && PUB.st.batch.running));
    if (PUB.busy || (!run && PUB.n % 5)) return;
    PUB.busy = true; pubFetch().then(function () { PUB.busy = false; });
  }, 1000);
}
function pubLeave() { clearInterval(PUB.t); PUB.t = null; var v = $('#pbVideo'); if (v) v.pause(); }
function pubDo(path, body, okMsg) {
  return api('POST', '/api/publish/' + path, body || {}, 30000).then(function (j) { PUB.st = j; pubSync(); if (okMsg) toast(okMsg, 5000); return j; })
    .catch(function (e) { toast(e.message, 7000); throw e; });
}
function pubBody() {
  var f = pubForm();
  return { file: f.sel && f.sel.path, title: (f.title || '').trim(), desc: f.desc || '', tags: pubTags(f.tags), schedule: f.timed && f.when ? f.when.replace('T', ' ') : '',
    cover: f.cover && f.cover.path, declaration: f.decl || (pubSt().opts || {}).decl || '内容由AI生成', collection: (f.coll || '').trim() };
}
function pubUpload(file, kind) {
  if (!file) return;
  if (kind === 'video' && !/^video\//.test(file.type) && !/\.(mp4|mov|webm|mkv|m4v|flv|avi|wmv)$/i.test(file.name)) { toast('要视频文件（mp4 这类）'); return; }
  if (kind === 'cover' && !/^image\//.test(file.type)) { toast('封面要图片'); return; }
  PUB.up = { name: file.name, pct: 0 }; pubSync();
  upOne(file, file.name, '', '', function (l, t) { PUB.up.pct = Math.floor(l * 100 / t); PUB.sig.pbPrev = ''; pubSync(); }, function (err, j) {
    PUB.up = null;
    if (err) { toast('没放进去：' + err, 6000); pubSync(); return; }
    var f = pubForm();
    if (kind === 'video') f.sel = { path: j.rel, name: j.name, size: j.size }; else f.cover = { path: j.rel, name: j.name };
    pubKeep(); pubSync(); pubFetch();
    toast((kind === 'video' ? '视频' : '封面') + '放进工作区了：' + j.rel);
  });
}

/* ---------- 动作 ---------- */
(function () {
  var v = $('#view-publish'); if (!v) return;
  v.addEventListener('input', function (ev) {
    var t = ev.target, f = pubForm(), map = { pbTitle: 'title', pbDesc: 'desc', pbTags: 'tags', pbWhen: 'when', pbColl: 'coll', pbDir: 'dir' };
    if (map[t.id]) { f[map[t.id]] = t.value; pubKeep(); PUB.msg = ''; pubSync(); }
  });
  v.addEventListener('change', function (ev) {
    var t = ev.target, f = pubForm();
    if (t.id === 'pbDecl') { f.decl = t.value; pubKeep(); }
    if (t.id === 'pbFile') { pubUpload(t.files && t.files[0], 'video'); t.value = ''; }
    if (t.id === 'pbCoverFile') { pubUpload(t.files && t.files[0], 'cover'); t.value = ''; }
    if (t.id === 'pbListFile') {
      var fs = [].slice.call(t.files || []); t.value = '';
      Promise.all(fs.map(function (x) { return x.text().then(function (tx) { return { name: x.name, text: tx }; }); })).then(function (l) { PUB.lists = l; pubSync(); });
    }
  });
  v.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && ev.target.id === 'pbCode') { ev.preventDefault(); var b = v.querySelector('[data-pb="code"]'); if (b) b.click(); } });
  ['dragover', 'dragleave', 'drop'].forEach(function (k) {
    v.addEventListener(k, function (ev) {
      var z = ev.target.closest && ev.target.closest('.pb-vid, .pb-cover'); if (!z || !ev.dataTransfer || [].indexOf.call(ev.dataTransfer.types || [], 'Files') < 0) return;
      ev.preventDefault(); z.classList.toggle('over', k === 'dragover');
      if (k === 'drop' && useLive()) pubUpload(ev.dataTransfer.files[0], z.classList.contains('pb-cover') ? 'cover' : 'video');
    });
  });
  v.addEventListener('click', function (ev) {
    var t = ev.target.closest('button'); if (!t || t.disabled) return;
    var f = pubForm(), d = t.dataset, s = pubSt();
    if (d.goSec) { openSec(d.goSec); return; }
    if (d.pbwhen != null) {
      f.timed = d.pbwhen === '1'; if (f.timed && !f.when) f.when = pubMinWhen();
      $$('[data-pbwhen]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.pbwhen === d.pbwhen); });
      var w = $('#pbWhen'); if (w) w.value = f.when;
      pubKeep(); pubSync(); return;
    }
    if (d.pbmode) {
      f.mode = d.pbmode; pubKeep(); $('#view-publish .pb').classList.toggle('bat', f.mode === 'bat');
      $$('[data-pbmode]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.pbmode === f.mode); }); pubSync(); return;
    }
    if (d.pbv) { var x = (s.videos || []).filter(function (y) { return y.path === d.pbv; })[0]; if (x) { f.sel = { path: x.path, name: x.name, size: x.size }; pubKeep(); pubSync(); } return; }
    if (!useLive()) { toast('演示模式：连上后端才能用'); return; }
    if (d.pbpend) {
      var p = (s.pending || []).filter(function (y) { return String(y.id) === d.pbpend; })[0]; if (!p) return;
      if (d.act === 'drop') { pubDo('pending/' + p.id, { act: 'drop' }, '扔掉了：这条不发').then(function () { if (f.pid === p.id) { f.pid = 0; pubKeep(); pubSync(); } }).catch(function () {}); return; }
      var it = p.item;
      Object.assign(f, { pid: p.id, sel: { path: it.file, name: it.name, size: it.size }, title: it.title, desc: it.desc || '', tags: (it.tags || []).join(' '), timed: !!it.schedule,
        when: it.schedule ? it.schedule.replace(' ', 'T') : '', cover: it.cover ? { path: it.cover, name: it.cover.split(/[\\/]/).pop() } : null, decl: it.declaration || f.decl, coll: it.collection || '' });
      pubKeep(); $('#view-publish').innerHTML = ''; renderPub(); toast('Agent 那条填进来了：看一眼，改一改，再点发布');
      return;
    }
    var a = d.pb;
    if (a === 'unsel') { f.sel = null; pubKeep(); pubSync(); }
    else if (a === 'uncover') { f.cover = null; pubKeep(); pubSync(); }
    else if (a === 'path') { var pv = ($('#pbPath').value || '').trim().replace(/^"|"$/g, ''); if (!pv) { toast('填视频的完整路径'); return; } f.sel = { path: pv, name: pv.split(/[\\/]/).pop(), size: 0 }; pubKeep(); $('#pbPath').value = ''; pubSync(); }
    else if (a === 'unlist') { PUB.lists = []; pubSync(); }
    else if (a === 'bload') {
      var dir = ($('#pbDir').value || '').trim().replace(/^"|"$/g, ''); if (!dir) { toast('填放视频和封面的文件夹'); $('#pbDir').focus(); return; }
      f.dir = dir; pubKeep(); t.disabled = true;
      var bb = smartBody('pub', { folder: dir, files: PUB.lists });
      api('POST', '/api/publish/batch/load', bb, 200000).then(function (j) {
        PUB.st = j; PUB.barm = 0; t.disabled = false; pubSync();
        var b = j.batch; toast('认好了：' + b.items.length + ' 条，能发 ' + b.items.filter(function (x) { return x.st === 'idle'; }).length + ' 条', 6000);
      }).catch(function (e) { t.disabled = false; toast(e.message, 8000); });
    }
    else if (a === 'bgo') {
      if (!PUB.barm) { PUB.barm = 1; pubSync(); clearTimeout(PUB.armT); PUB.armT = setTimeout(function () { PUB.barm = 0; pubSync(); }, 4000); return; }
      PUB.barm = 0; clearTimeout(PUB.armT); pubDo('batch/run', {}, '开始一条一条发了：进展在右边').catch(function () { pubSync(); });
    }
    else if (a === 'bstop') { t.disabled = true; pubDo('batch/stop', {}).catch(function () {}); }
    else if (a === 'bclear') pubDo('batch/clear', {}).catch(function () {});
    else if (a === 'install') pubDo('install', {}, '开始装了（约 40MB），一两分钟').catch(function () {});
    else if (a === 'login') pubDo('login', {}, '二维码一会儿出现在右边，用抖音 App 扫').catch(function () {});
    else if (a === 'check') pubDo('check', {}).catch(function () {});
    else if (a === 'logout') { if (!t.classList.contains('armed')) { t.classList.add('armed'); t.textContent = '再点一下退出'; setTimeout(function () { t.classList.remove('armed'); t.textContent = '退出'; }, 3500); return; } pubDo('logout', {}, '退出了：本机存的登录信息删掉了').catch(function () {}); }
    else if (a === 'stop') { t.disabled = true; pubDo('stop', {}).catch(function () {}); }
    else if (a === 'code') { var c = ($('#pbCode').value || '').trim(); if (!c) { toast('填手机收到的验证码'); return; } pubDo('code', { code: c }, '验证码交过去了').catch(function () {}); }
    else if (a === 'go') {
      if (!PUB.arm) {
        api('POST', '/api/publish/preview', pubBody()).then(function () {
          PUB.arm = 1; PUB.msg = ''; pubSync(); clearTimeout(PUB.armT);
          PUB.armT = setTimeout(function () { PUB.arm = 0; pubSync(); }, 4000);
        }).catch(function (e) { PUB.msg = '<span class="bad">' + esc(e.message) + '</span>'; PUB.sig.pbMsg = ''; pubSync(); });
        return;
      }
      PUB.arm = 0; clearTimeout(PUB.armT);
      var body = pubBody(), done = function () { f.pid = 0; f.sel = null; f.title = ''; f.desc = ''; f.cover = null; f.timed = false; f.when = ''; pubKeep(); $('#view-publish').innerHTML = ''; renderPub(); };
      (f.pid ? pubDo('pending/' + f.pid, { act: 'ok', edits: body }, '开始发了：进展在右边') : pubDo('go', body, '开始发了：进展在右边')).then(done).catch(function () { pubSync(); });
    }
  });
})();
