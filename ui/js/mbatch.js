'use strict';
/* ================= 配音批量、配乐批量（v3.1，后端 app/media_batch.py） =================
   两页共用这一块：一份清单 → 一条一条出 → 按清单里的名字存进一个文件夹（照生图的批量）。
   - 配音页：「文案」那一栏顶上切到「批量」；音色、语气、整段 / 一句一句用中间和右边选的（清单里写了「音色：」的那段用它自己的）；
     「开始批量」在右边原来「生成配音」的位置；正在念的那一段照样在右边看进度、波形。
   - 配乐页：左边那一栏顶上切到「批量」；「开始批量」在这一栏下面；点一首出好的，中间就放它。
   清单在后端（data\batch\tts.json、bgm.json），关了再开还在；这里只画、只发请求。正在改的框不会被刷新打断。 */
var MB_CFG = {
  tts: { api: '/api/tts/batch', unit: '段', what: '配音', name: '配音清单',
    ph: '# 第 5 期 · 配音清单\n\n## 01_橘页_开场\n音色：橘页\n大家好，欢迎来到这一期……\n\n## 02_紫苏_吐槽\n音色：紫苏\n语气：激动\n[excited] 这也太离谱了吧！',
    help: '一段用「## 文件名」开头，下面是要念的字。要换音色写一行「音色：名字」（我的音色、预设音色、云端音色的名字都行），不写就用中间选的；还能写「语气：」。也能一次选几个 .txt，一个文件一段。' },
  bgm: { api: '/api/bgm/batch', unit: '首', what: '配乐', name: '配乐清单',
    ph: '# 第 5 期 · 配乐清单\n\n## bgm01_开场\n时长：30 秒\n描述：轻快的电子乐，明亮的合成器，节奏清晰\n\n## bgm02_讲解\n时长：1分30秒\n描述：安静的钢琴独奏，舒缓，留白多\n\n也能一行一首：bgm03_结尾 | 45 | 温暖的木吉他',
    help: '一首用「## 名字」开头，下面写「时长：30 秒」和描述（不写「描述：」就把这一节的字当描述）。也能一行一首「名字 | 时长 | 描述」，或者 Markdown 表格。' }
};
var MBX = { tts: { st: null, open: '', sig: '', timer: null, n: 0, busy: false, text: '' }, bgm: { st: null, open: '', sig: '', timer: null, n: 0, busy: false, text: '' },
  au: null, playing: '' };
function mbDemoItems(k) {
  if (k === 'tts') return [
    { id: 'b1', file: '01_橘页_开场', text: '大家好，欢迎来到这一期。今天聊三个最近很火的工具。', voice: '橘页', st: 'ok', dur: 7.4, chars: 24, segs: 2, ver: 1 },
    { id: 'b2', file: '02_紫苏_吐槽', text: '[excited] 这也太离谱了吧！', voice: '紫苏', tone: '激动', st: 'ok', dur: 2.1, chars: 13, segs: 1, ver: 1, warn: '1 句的开始、结束是估的' },
    { id: 'b3', file: '03_橘页_第一个', text: '第一个，是一个能把配音和字幕对齐的小工具。', voice: '橘页', st: 'run', chars: 21 },
    { id: 'b4', file: '04_紫苏_接话', text: '对齐？就是给每个字发一张火车票？', voice: '紫苏', st: 'queue', chars: 16 },
    { id: 'b5', file: '05_橘页_结尾', text: '对，几点几分上车，几点下车，写得清清楚楚。', voice: '橘页', st: 'queue', chars: 21 }];
  return [
    { id: 'b1', file: 'bgm01_开场', prompt: '轻快的电子乐，明亮的合成器，节奏清晰', seconds: 30, st: 'ok', dur: 30, ver: 1 },
    { id: 'b2', file: 'bgm02_讲解', prompt: '安静的钢琴独奏，舒缓，留白多', seconds: 90, st: 'run' },
    { id: 'b3', file: 'bgm03_吐槽', prompt: '8-bit 芯片音乐，欢快，像老游戏的关卡音乐', seconds: 20, st: 'queue' },
    { id: 'b4', file: 'bgm04_结尾', prompt: '木吉他指弹，温暖明亮，轻松的午后', seconds: 45, st: 'queue' }];
}
function mbDemo(k) {
  var items = mbDemoItems(k);
  return { demo: true, out: k === 'tts' ? 'F:\\Agent\\配音输出' : 'F:\\Agent\\配乐输出', job: { st: 'run', n: items.length - 1, done: 1, fail: 0, cur: 'b' + (k === 'tts' ? 3 : 2), msg: '第 2/' + (items.length - 1) + ' ' + MB_CFG[k].unit + '：' + items[k === 'tts' ? 2 : 1].file, elapsed: 41 },
    board: { title: '第 5 期 · ' + MB_CFG[k].name, created: '', dir: (k === 'tts' ? 'F:\\Agent\\配音输出' : 'F:\\Agent\\配乐输出') + '\\2026-11-12_第 5 期', warn: [], items: items } };
}
function mbSt(k) { return useLive() ? MBX[k].st : (MBX[k].demo || (MBX[k].demo = mbDemo(k))); }
function mbRun(k) { var s = mbSt(k); return !!(s && s.job && s.job.st === 'run'); }
function mbBoard(k) { var s = mbSt(k); return s && s.board; }
function mbClock(s) { s = Math.max(0, Math.round(+s || 0)); return Math.floor(s / 60) + ':' + pad(s % 60); }
function mbItem(k, id) { var b = mbBoard(k); return b ? b.items.filter(function (x) { return x.id === id; })[0] : null; }
function mbFetch(k) {
  if (!useLive()) { mbDraw(k); return Promise.resolve(); }
  return api('GET', MB_CFG[k].api, null, 6000).then(function (j) {
    var was = mbRun(k); MBX[k].st = j; mbDraw(k);
    if (was && j.job && j.job.st !== 'run') toast('批量' + MB_CFG[k].what + j.job.msg, 6000);
  }).catch(function () {});
}
/* 页面进来、出去时调（配音页 ttsEnter / ttsLeave，配乐页 bgmEnter / bgmLeave）：批量在跑每秒问一次，不跑每 5 秒 */
function mbEnter(k) {
  mbFetch(k); clearInterval(MBX[k].timer);
  MBX[k].timer = setInterval(function () {
    var x = MBX[k]; x.n++;
    if (!useLive() || x.busy || !document.querySelector('[data-mbk="' + k + '"]') || (!mbRun(k) && x.n % 5)) return;
    x.busy = true; mbFetch(k).then(function () { x.busy = false; });
  }, 1000);
}
function mbLeave(k) { clearInterval(MBX[k].timer); MBX[k].timer = null; if (MBX.au) MBX.au.pause(); }

/* ---------- 画 ---------- */
function mbStName(st) { return { ok: '好了', err: '没出成', run: '正在出', queue: '排着', idle: '还没出' }[st] || ''; }
function mbRowHTML(k, it, run) {
  var c = MB_CFG[k], open = MBX[k].open === it.id, playing = MBX.playing === k + it.id && MBX.au && !MBX.au.paused;
  var tag = k === 'tts' ? (it.voice ? esc(it.voice) : '<i>默认音色</i>') + (it.tone ? ' · ' + esc(it.tone) : '') : mbClock(it.seconds) + ' 长';
  var meta = it.st === 'ok' && it.dur ? mbClock(it.dur) : k === 'tts' ? (it.chars || 0) + ' 字' : '';
  var lock = it.st === 'run' || it.st === 'queue';
  var h = '<div class="mb-row st-' + esc(it.st || 'idle') + (open ? ' open' : '') + '">' +
    '<button class="mb-main" data-mba="pick" data-mbi="' + it.id + '" aria-expanded="' + open + '" title="' + esc(mbStName(it.st)) + '：点开改' + (k === 'tts' ? '要念的字、音色' : '描述、时长') + '">' +
      '<i class="mb-dot" aria-hidden="true"></i><span class="mb-n">' + esc(it.file) + '</span><span class="mb-tag">' + tag + '</span><span class="mb-m num">' + meta + '</span></button>' +
    '<button class="mb-ic" data-mba="play" data-mbi="' + it.id + '" aria-label="听' + esc(it.file) + '"' + (it.st === 'ok' ? '' : ' disabled') + '>' + (playing ? '❚❚' : '▶') + '</button>' +
    '<button class="mb-ic" data-mba="redo" data-mbi="' + it.id + '" aria-label="重新出' + esc(it.file) + '" title="重新出这一' + c.unit + '（旧的挪进「旧版」）"' + (run || lock ? ' disabled' : '') + '>↻</button></div>';
  if (it.err) h += '<div class="mb-err">' + esc(it.err) + '</div>';
  else if (it.warn) h += '<div class="mb-warn">' + esc(it.warn) + '</div>';
  if (open) {
    var dis = lock ? ' disabled' : '';
    h += '<div class="mb-ed" data-mbi="' + it.id + '">' + (k === 'tts' ?
      '<textarea class="inp" data-mbf="text" rows="4" spellcheck="false"' + dis + '>' + esc(it.text) + '</textarea>' +
      '<div class="mb-ed2"><label>音色<input class="inp" data-mbf="voice" value="' + esc(it.voice || '') + '" placeholder="不写用中间选的"' + dis + '></label>' +
        '<label>语气<input class="inp" data-mbf="tone" value="' + esc(it.tone || '') + '" placeholder="不写用中间写的"' + dis + '></label></div>' :
      '<textarea class="inp" data-mbf="prompt" rows="3" spellcheck="false"' + dis + '>' + esc(it.prompt) + '</textarea>' +
      '<div class="mb-ed2"><label>时长（秒）<input class="inp num" data-mbf="seconds" type="number" min="10" max="600" step="5" value="' + (+it.seconds || 60) + '"' + dis + '></label>' +
        (it.st === 'ok' ? '<button class="btn mini" data-mba="tows1" data-mbi="' + it.id + '">这一首放进工作区</button>' : '') + '</div>') +
      (it.edited ? '<div class="cap">改过（和清单里写的不一样）；改完点 ↻ 重新出</div>' : '') + '</div>';
  }
  return h;
}
function mbHTML(k, withGo) {
  var c = MB_CFG[k], s = mbSt(k), b = s && s.board, run = mbRun(k), live = useLive();
  if (!s) return '<div class="mb-wait">正在读取…</div>';
  if (!b) return '<div class="mb-drop" data-mbdrop="' + k + '"><b>一份' + c.name + '，一' + c.unit + '存一个文件</b><p class="cap">' + esc(c.help) + '</p>' +
    '<textarea class="inp mb-paste" data-mbpaste="' + k + '" spellcheck="false" placeholder="' + esc(c.ph) + '">' + esc(MBX[k].text) + '</textarea>' +
    '<div class="btnrow"><button class="btn primary" data-mba="load"' + (live ? '' : ' disabled') + '>认清单</button><button class="btn" data-mba="pickfile"' + (live ? '' : ' disabled') + '>选文件…</button>' +
    '<span class="cap">也能把 .md / .txt 拖进来</span></div><input type="file" data-mbfile="' + k + '" accept=".md,.markdown,.txt" multiple hidden></div>';
  var its = b.items, ok = its.filter(function (x) { return x.st === 'ok'; }).length, fail = its.filter(function (x) { return x.st === 'err'; }).length;
  var tot = k === 'tts' ? its.reduce(function (a, x) { return a + (x.chars || 0); }, 0) + ' 字' : mbClock(its.reduce(function (a, x) { return a + (+x.seconds || 0); }, 0)) + ' 长';
  var h = '<div class="mb-head"><b title="' + esc(b.dir) + '">' + esc(b.title) + '</b><span class="cap num">' + its.length + ' ' + c.unit + ' · ' + tot + ' · 好了 ' + ok + (fail ? ' · 没成 ' + fail : '') + '</span>' +
    '<button class="linkbtn" data-mba="clear"' + (run ? ' disabled' : '') + ' title="换一份清单（文件夹里出好的不动）">换一份</button></div>';
  if (b.warn && b.warn.length) h += '<div class="mb-warn">' + b.warn.map(esc).join('；') + '</div>';
  h += '<div class="mb-list" role="list">' + its.map(function (it) { return mbRowHTML(k, it, run); }).join('') + '</div>';
  h += '<div class="mb-foot"><span class="cap mb-dir" title="' + esc(b.dir) + '">存到 ' + esc(b.dir) + '</span><span class="btnrow">' +
    '<button class="btn mini ghost" data-mba="open"' + (live ? '' : ' disabled') + '>打开文件夹</button>' +
    '<button class="btn mini ghost" data-mba="zip"' + (live && ok ? '' : ' disabled') + ' title="把出好的打包成一个 zip，放在这一批的文件夹里">打包</button>' +
    '<button class="btn mini ghost" data-mba="tows"' + (live && ok ? '' : ' disabled') + ' title="复制进 工作区\\素材\\' + c.what + '\\，Agent 做视频时能用">放进工作区</button></span></div>';
  if (withGo) h += mbGoHTML(k);
  return h;
}
/* 开始 / 停下那一块：配乐在这一栏下面；配音在右边原来「生成配音」的位置（ttsSyncLocal / ttsSyncCloud 调） */
function mbGoHTML(k, extra, off) {
  var c = MB_CFG[k], s = mbSt(k), b = s && s.board, j = s && s.job, run = mbRun(k);
  if (!b) return '<div class="mb-go"><div class="tts-gorow"><button class="btn primary tts-go" disabled>开始批量</button>' + (extra || '') + '</div><span class="cap">先在' + (k === 'tts' ? '左边' : '上面') + '认一份' + c.name + '</span></div>';
  var miss = b.items.filter(function (x) { return x.st !== 'ok'; }).length, all = b.items.length;
  if (run) return '<div class="mb-go mb-going"><div class="mb-gl"><b class="num">' + (j.done + j.fail + 1 > j.n ? j.n : j.done + j.fail + 1) + '/' + j.n + '</b><span>' + esc(j.msg || '') + '</span></div>' +
    '<div class="prog-bar"><i style="transform:scaleX(' + ((j.done + j.fail) / Math.max(1, j.n)).toFixed(3) + ')"></i></div>' +
    '<div class="btnrow"><button class="btn danger" data-mba="stop" data-mbk="' + k + '">停下这一批</button><span class="cap num">已经 ' + mbClock(j.elapsed) + (j.fail ? ' · ' + j.fail + ' ' + c.unit + '没成' : '') + '</span></div></div>';
  return '<div class="mb-go"><div class="tts-gorow"><button class="btn primary tts-go" data-mba="go" data-mbk="' + k + '"' + (useLive() && all && !off ? '' : ' disabled') + '>开始批量 · ' + all + ' ' + c.unit + '</button>' +
    (miss && miss < all ? '<button class="btn" data-mba="miss" data-mbk="' + k + '"' + (off ? ' disabled' : '') + '>只补没出的 ' + miss + ' ' + c.unit + '</button>' : '') + (extra || '') + '</div>' +
    (j && j.st !== 'run' ? '<div class="tts-msg' + (j.fail || j.fatal ? ' bad' : ' ok') + '">' + esc(j.msg) + '</div>' : '') + '</div>';
}
/* 正在跑批量时，配音右边进度上面那一行 */
function mbNowLine(k) {
  var s = mbSt(k), j = s && s.job; if (!mbRun(k)) return '';
  return '<div class="mb-now"><b class="num">批量 ' + Math.min(j.n, j.done + j.fail + 1) + '/' + j.n + '</b><span>' + esc((mbItem(k, j.cur) || {}).file || '') + '</span>' +
    '<button class="btn mini danger" data-mba="stop" data-mbk="' + k + '">停下这一批</button></div>';
}
function mbDraw(k, force) {
  var el = document.querySelector('[data-mbk="' + k + '"].mb'); if (!el) return;
  var a = document.activeElement;
  if (!force && a && el.contains(a) && /INPUT|TEXTAREA/.test(a.tagName)) return;          // 正在改：等改完再刷新
  var html = mbHTML(k, k === 'bgm');
  if (!force && html === MBX[k].sig && el.innerHTML) return;
  MBX[k].sig = html; el.innerHTML = html;
  if (k === 'tts' && typeof ttsSync === 'function' && TTS.st) ttsSync();                  // 右边的「开始批量」跟着变
}

/* ---------- 动作 ---------- */
function mbKind(el) { var w = el.closest('[data-mbk]'); return w ? w.dataset.mbk : ''; }
function mbBase(k) {                    // 配音：配音页现在选的引擎、音色、语气、整段 / 一句一句
  if (k !== 'tts') return {};
  var r = ttsBody(false); delete r.text; delete r.same;
  if (!ttsCloud() && TTS.st) r.whole = TTS.st.whole !== false;
  return r;
}
function mbSet(k, j) { MBX[k].st = j; mbDraw(k, true); }
function mbLoadFiles(k, files) {
  files = [].slice.call(files || []).filter(function (f) { return /\.(md|markdown|txt)$/i.test(f.name); });
  if (!files.length) { toast('要 .md 或 .txt 文件'); return; }
  Promise.all(files.map(function (f) { return f.text().then(function (t) { return { name: f.name, text: t }; }); }))
    .then(function (fs) { return api('POST', MB_CFG[k].api + '/load', { files: fs }); })
    .then(function (j) { MBX[k].text = ''; mbSet(k, j); toast('认好了：' + j.board.items.length + ' ' + MB_CFG[k].unit); })
    .catch(function (e) { toast(e.message, 6000); });
}
function mbPlay(k, id) {
  var it = mbItem(k, id); if (!it) return;
  if (!useLive()) { toast('演示模式没有声音'); return; }
  if (!MBX.au) { MBX.au = new Audio(); ['play', 'pause', 'ended'].forEach(function (e) { MBX.au.addEventListener(e, function () { mbDraw('tts', true); mbDraw('bgm', true); }); }); }
  var a = MBX.au, key = k + id;
  if (MBX.playing === key && !a.paused) { a.pause(); return; }
  if (MBX.playing !== key) { a.src = MB_CFG[k].api + '/file/' + id + '?v=' + (it.ver || 0); MBX.playing = key; }
  var other = k === 'tts' ? $('#ttsAudio') : BGM.audio; if (other) other.pause();
  a.play().catch(function (e) { toast('放不了：' + e.message); });
}
function mbRunReq(k, body, btn) {
  if (btn) btn.disabled = true;
  body.req = mbBase(k);
  return api('POST', MB_CFG[k].api + '/run', body, 30000).then(function (j) { mbSet(k, j); if (k === 'tts') ttsLoad().then(ttsSync).catch(function () {}); })
    .catch(function (e) { toast(e.message, 7000); if (btn) btn.disabled = false; });
}
document.addEventListener('click', function (ev) {
  var t = ev.target.closest && ev.target.closest('button[data-mba]'); if (!t || t.disabled) return;
  var k = t.dataset.mbk || mbKind(t), act = t.dataset.mba, id = t.dataset.mbi, c = MB_CFG[k]; if (!c) return;
  if (act === 'pick') {
    MBX[k].open = MBX[k].open === id ? '' : id; mbDraw(k, true);
    var it = mbItem(k, id); if (k === 'bgm' && it && it.hid && typeof BGM !== 'undefined') { BGM.sel = it.hid; BGM.sig = ''; renderBgm(); }
    return;
  }
  if (act === 'play') { mbPlay(k, id); return; }
  if (!useLive()) { toast('演示模式：连上后端才能用'); return; }
  if (act === 'pickfile') { var f = document.querySelector('input[data-mbfile="' + k + '"]'); if (f) f.click(); return; }
  if (act === 'load') {
    var md = (MBX[k].text || '').trim(); if (!md) { toast('先把' + c.name + '贴进来，或者点「选文件…」'); var p = document.querySelector('[data-mbpaste="' + k + '"]'); if (p) p.focus(); return; }
    t.disabled = true;
    api('POST', c.api + '/load', { md: md }).then(function (j) { MBX[k].text = ''; mbSet(k, j); toast('认好了：' + j.board.items.length + ' ' + c.unit + (j.board.warn.length ? '（' + j.board.warn.length + ' 处要看一下）' : '')); })
      .catch(function (e) { toast(e.message, 7000); t.disabled = false; });
  }
  else if (act === 'go') mbRunReq(k, {}, t);
  else if (act === 'miss') mbRunReq(k, { only_missing: true }, t);
  else if (act === 'redo') mbRunReq(k, { ids: [id] }, t);
  else if (act === 'stop') { t.disabled = true; api('POST', c.api + '/stop', {}).then(function (j) { mbSet(k, j); toast('停下：手上这一' + c.unit + '停了就不往下出了'); }).catch(function (e) { toast(e.message); }); }
  else if (act === 'clear') api('POST', c.api + '/clear', {}).then(function (j) { MBX[k].open = ''; mbSet(k, j); }).catch(function (e) { toast(e.message); });
  else if (act === 'open') api('POST', c.api + '/open', {}).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); });
  else if (act === 'zip') { t.disabled = true; api('POST', c.api + '/zip', {}, 120000).then(function (j) { toast(j.msg, 5000); }).catch(function (e) { toast(e.message, 5000); }).then(function () { t.disabled = false; }); }
  else if (act === 'tows' || act === 'tows1') api('POST', c.api + '/tows', act === 'tows1' ? { id: id } : {}).then(function (j) { toast(j.msg || '放进工作区了', 5000); }).catch(function (e) { toast(e.message, 6000); });
});
document.addEventListener('input', function (ev) { var t = ev.target; if (t.dataset && t.dataset.mbpaste) MBX[t.dataset.mbpaste].text = t.value; });
document.addEventListener('change', function (ev) {
  var t = ev.target; if (!t.dataset) return;
  if (t.dataset.mbfile) { mbLoadFiles(t.dataset.mbfile, t.files); t.value = ''; return; }
  if (!t.dataset.mbf) return;
  var ed = t.closest('.mb-ed'), k = mbKind(t); if (!ed || !k || !useLive()) return;
  var body = {}; body[t.dataset.mbf] = t.value;
  api('PATCH', MB_CFG[k].api + '/item/' + ed.dataset.mbi, body).then(function (j) { MBX[k].st = j; MBX[k].sig = ''; toast('改好了'); setTimeout(function () { mbDraw(k); }, 0); })
    .catch(function (e) { toast(e.message, 5000); });
});
['dragover', 'dragleave', 'drop'].forEach(function (e) {
  document.addEventListener(e, function (ev) {
    var z = ev.target.closest && ev.target.closest('[data-mbdrop]'); if (!z) return;
    ev.preventDefault(); z.classList.toggle('over', e === 'dragover');
    if (e === 'drop' && useLive()) mbLoadFiles(z.dataset.mbdrop, ev.dataTransfer && ev.dataTransfer.files);
  });
});
