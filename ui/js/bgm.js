'use strict';
/* ================= 配乐（v3.0，工具窗口）=================
   本地的 Stable Audio 3 Medium 出纯音乐（不花钱、不出本机）。一屏三块：
   - 左：要什么样的（一句描述 + 几个现成的风格 + 多长）→「出一首」；下面一行写服务现在什么样（没配 / 用到才启动 / 开着），能手动关掉腾显存。
   - 中：正在听的这一首：波形（真的从音频里算出来的）、播放、名字、多长、当时的描述；正在出的时候这里是进度。
   - 右：最近出的，点一首就在中间听；每首能「放进工作区」（给 Agent 做视频用）、打开所在的文件夹。
   - 批量（v3.1，ui/js/mbatch.js）：左边顶上切到「批量」，一份配乐清单一首存一个文件（配乐输出\日期_清单名\名字.wav）；点一首出好的，中间就放它。
   Agent 自己做视频时也会用同一个服务（make_music 工具），出的也在这份历史里。 */
var BGM_MAX_SECONDS = 120;                 // 临时上限（v4.0.2）：更长容易出杂音，等长曲排查结果再定要不要放开
var BGM = { st: null, sel: null, t: null, audio: null, peaks: {}, prompt: (U.bgmPrompt || ''), seconds: (+U.bgmSeconds || 60), sig: '', busyBtn: false, raf: 0, wv: null, lastT: 0, mode: (U.bgmMode === 'batch' ? 'batch' : 'one'), preset: (typeof U.bgmPreset === 'number' ? U.bgmPreset : -1) };
try { if (!U.bgmMode && localStorage.getItem('agentBgm.mode') === 'batch') BGM.mode = 'batch'; } catch (e) {}
var BGM_PRESET = [['轻快电子', '轻快的电子乐，明亮的合成器，节奏清晰，适合科技类视频开场'], ['安静钢琴', '安静的钢琴独奏，舒缓，留白多，适合讲解时垫在下面'],
  ['Lo-fi', 'lo-fi hip hop，松弛的鼓点，温暖的电钢琴，带一点黑胶底噪'], ['科技感', '冷色调的氛围电子，脉冲贝斯，未来感，中速'],
  ['悬疑', '低沉的弦乐铺底，缓慢推进，带一点紧张感'], ['热血', '史诗感管弦乐，鼓点有力，逐渐推向高潮'], ['8-bit', '8-bit 芯片音乐，欢快，像老游戏的关卡音乐'], ['温暖吉他', '木吉他指弹，温暖明亮，轻松的午后']];
if (BGM.preset >= 0 && BGM_PRESET[BGM.preset] && !BGM.prompt) BGM.prompt = BGM_PRESET[BGM.preset][1];
if (!(BGM.seconds >= 10)) BGM.seconds = 60;
if (BGM.seconds > BGM_MAX_SECONDS) BGM.seconds = BGM_MAX_SECONDS;
var BGM_DEMO = { up: false, alive: false, configured: true, can_start: true, url: 'http://127.0.0.1:8001', out: 'F:\\Agent\\配乐输出', job: null, idle: 10,
  recent: [{ id: 3, ts: Date.now() / 1000 - 600, name: '143012_轻快的电子乐.wav', prompt: '轻快的电子乐，明亮的合成器，节奏清晰', seconds: 60, duration: 60, took: 21, exists: true },
    { id: 2, ts: Date.now() / 1000 - 4200, name: '131544_安静的钢琴独奏.wav', prompt: '安静的钢琴独奏，舒缓，留白多', seconds: 90, duration: 90, took: 30, exists: true },
    { id: 1, ts: Date.now() / 1000 - 90000, name: '204455_lo-fi.wav', prompt: 'lo-fi hip hop，松弛的鼓点，温暖的电钢琴', seconds: 45, duration: 45, took: 17, exists: true }] };

function bgmSt() { return useLive() ? BGM.st : BGM_DEMO; }
function bgmClock(s) { s = Math.max(0, Math.round(+s || 0)); return Math.floor(s / 60) + ':' + pad(s % 60); }
function bgmWhen(ts) { var d = new Date(ts * 1000), n = new Date(), same = d.toDateString() === n.toDateString(); return (same ? '' : pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ') + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
function bgmCur() { var st = bgmSt(), l = (st && st.recent) || []; return l.filter(function (h) { return h.id === BGM.sel; })[0] || l[0] || null; }
function bgmSvcLine(st) {
  if (!st) return ['warn', '正在连接后台' + (BGM.err ? '（' + BGM.err.slice(0, 40) + '）' : '…'), ''];
  if (st.job && st.job.st === 'run') return ['run', '正在出：' + (st.job.msg || '等它出完'), ''];
  if (st.yielding) return ['warn', '在让路（' + (st.yield_reason || '别的程序要显存') + '）：现在不启动', ''];
  if (st.alive) return ['ok', 'Stable Audio 3 开着 · 闲 ' + (st.idle || 10) + ' 分钟自己关', '<button class="btn mini ghost" data-bgm-off="1">现在关掉</button>'];
  if (st.up) return ['ok', 'Stable Audio 3 开着（不是 Agent 开的，不归它关）', ''];
  if (st.can_start) return ['idle', '用到才启动：点「出一首」会先把 Stable Audio 3 开起来（第一次要加载模型）', ''];
  return ['off', '还没装：到 设置 › 整备 一键装好（Stable Audio 3 Medium 和它的模型）', '<button class="btn mini" data-go-sec="prep">去装</button>'];
}
function bgmHTML() {
  var st = bgmSt(), job = st && st.job, run = job && job.st === 'run', cur = bgmCur(), sv = bgmSvcLine(st), list = (st && st.recent) || [];
  var mode = '<div class="seg bg-mode" role="group" aria-label="一首还是批量"><button data-bgm-mode="one" aria-pressed="' + (BGM.mode !== 'batch') + '">一首</button><button data-bgm-mode="batch" aria-pressed="' + (BGM.mode === 'batch') + '" title="一份配乐清单，一首存一个文件（v3.1）">批量</button></div>';
  var left = BGM.mode === 'batch' ? '<section class="hud bg-pn bg-make bg-batch"><div class="bg-h"><b>批量配乐</b><span>一首一个文件</span><span class="sp"></span>' + mode + '</div>' +
    '<div class="mb" data-mbk="bgm"></div><div class="bg-svc st-' + sv[0] + '"><i></i><span>' + esc(sv[1]) + '</span>' + sv[2] + '</div></section>' :
    '<section class="hud bg-pn bg-make"><div class="bg-h"><b>要什么样的</b><span>纯音乐，不带人声</span><span class="sp"></span>' + mode + '</div>' +
    '<textarea class="bg-in" id="bgPrompt" spellcheck="false" placeholder="一句话写清楚：风格、情绪、乐器、快慢。英文效果最好；中文也行（配了 DeepSeek Key 会自动转成英文标签）。比如：轻快的电子乐，明亮的合成器，适合科技类视频开场"' + (run ? ' disabled' : '') + '>' + esc(BGM.prompt) + '</textarea>' +
    '<div class="bg-pre" role="group" aria-label="现成的风格">' + BGM_PRESET.map(function (p, i) { return '<button class="chip" data-bgm-pre="' + i + '"' + (run ? ' disabled' : '') + '>' + p[0] + '</button>'; }).join('') + '</div>' +
    '<div class="bg-len"><label for="bgSec">多长</label><input type="range" id="bgSec" min="10" max="' + BGM_MAX_SECONDS + '" step="5" value="' + BGM.seconds + '"' + (run ? ' disabled' : '') + '><output class="num" id="bgSecO">' + bgmClock(BGM.seconds) + '</output></div>' +
    '<div class="bg-go">' + (run ? '<button class="btn danger bg-big" data-bgm-stop="1">不等了</button>' : '<button class="btn primary bg-big" data-bgm-gen="1"' + (useLive() && st ? '' : ' disabled') + '>出一首</button>') + '</div>' +
    '<div class="bg-svc st-' + sv[0] + '"><i></i><span>' + esc(sv[1]) + '</span>' + sv[2] + '</div></section>';
  var mid;
  if (run) mid = '<div class="bg-now">' + (BGM.mode === 'batch' ? mbNowLine('bgm') : '') + '<div class="bg-run"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="bg-t">正在出这一首</div>' +
    '<div class="bg-m num">已经 ' + bgmClock(job.elapsed) + ' · 要 ' + bgmClock(job.seconds) + ' 长的</div><div class="bg-p">' + esc(job.prompt || '') + '</div></div>';
  else if (job && job.st === 'err') mid = '<div class="bg-now"><div class="bg-t bad">这一首没出成</div><div class="bg-p">' + esc(job.err || '') + '</div></div>';
  else if (cur) mid = '<div class="bg-now"><div class="bg-wavewrap" style="position:relative;display:block"><canvas class="bg-wave" id="bgWave" data-id="' + cur.id + '" aria-label="波形，点一下跳到那里"></canvas><i id="bgHead" aria-hidden="true" style="position:absolute;top:0;bottom:0;left:0;width:2px;margin-left:-1px;background:var(--hot,#ffb02e);pointer-events:none;opacity:.9;transform:translateX(0)"></i></div>' +
    '<div class="bg-ctl"><button class="btn primary bg-play" data-bgm-play="' + cur.id + '" aria-label="播放 / 暂停"' + (cur.exists ? '' : ' disabled') + '>' + (BGM.audio && !BGM.audio.paused && BGM.playing === cur.id ? '暂停' : '播放') + '</button>' +
    '<span class="num bg-time" id="bgTime">0:00 / ' + bgmClock(cur.duration || cur.seconds) + '</span><span class="sp"></span>' +
    '<button class="btn" data-bgm-tows="' + cur.id + '"' + (useLive() && cur.exists ? '' : ' disabled') + ' title="复制一份到 工作区\\素材\\配乐\\，Agent 做视频时能用">放进工作区</button>' +
    '<button class="btn ghost" data-bgm-open="' + cur.id + '"' + (useLive() ? '' : ' disabled') + '>打开文件夹</button></div>' +
    '<div class="bg-t">' + esc(cur.name) + (cur.exists ? '' : '<em>（文件被挪走或删了）</em>') + '</div><div class="bg-p">' + esc(cur.prompt || '') + '</div></div>';
  else mid = '<div class="bg-now"><div class="bg-t">还没出过</div><div class="bg-p">左边写一句描述，点「出一首」。8 步蒸馏模型，通常几十秒（看显卡和时长，最长 2 分钟；更长容易出杂音）。</div></div>';
  var right = '<section class="hud bg-pn bg-list"><div class="bg-h"><b>最近出的</b><span>' + list.length + ' 首</span><span class="sp"></span><button class="linkbtn" data-bgm-open=""' + (useLive() ? '' : ' disabled') + '>打开文件夹 ›</button></div><div class="bg-rows">' +
    (list.length ? list.map(function (h) {
      return '<button class="bg-row' + (cur && cur.id === h.id ? ' on' : '') + (h.exists ? '' : ' gone') + '" data-bgm-sel="' + h.id + '"><span class="num t">' + bgmWhen(h.ts) + '</span><span class="x">' + esc(h.prompt || h.name) + '</span><span class="num d">' + bgmClock(h.duration || h.seconds) + '</span></button>';
    }).join('') : '<div class="hm-none">还没有</div>') + '</div></section>';
  return '<div class="bg">' + left + '<section class="hud bg-pn bg-mid">' + mid + '</section>' + right + '</div>';
}
function renderBgm() {
  var v = $('#view-bgm'); if (!v) return;
  var a = document.activeElement, keep = a && a.id === 'bgPrompt' ? [a.selectionStart, a.selectionEnd] : null;
  var html = bgmHTML(); if (html === BGM.sig) return; BGM.sig = html;
  v.innerHTML = html;
  if (keep) { var p = $('#bgPrompt'); if (p && !p.disabled) { p.focus(); p.setSelectionRange(keep[0], keep[1]); } }
  if (BGM.mode === 'batch') mbDraw('bgm', true);
  bgmWave();
}
function bgmFetch() {
  if (!useLive()) { renderBgm(); return; }
  api('GET', '/api/bgm', null, 8000).then(function (j) {
    var was = BGM.st && BGM.st.job && BGM.st.job.st === 'run';
    BGM.st = j; BGM.err = '';
    if (was && j.job && j.job.st === 'done' && j.recent[0]) { BGM.sel = j.recent[0].id; toast('出好了：' + j.recent[0].name); }
    renderBgm();
  }).catch(function (e) {
    BGM.err = e && e.message ? e.message : '后台没响应';
    renderBgm();
  });
}
function bgmEnter() { renderBgm(); bgmFetch(); mbEnter('bgm'); clearInterval(BGM.t); BGM.t = setInterval(function () { if (S.view === 'bgm') bgmFetch(); }, 1500); }
function bgmQuit() {
  /* 页面离开 / 窗口关闭：动画帧、轮询定时器都停掉，声音暂停并把 src 清掉（v4.0.2） */
  cancelAnimationFrame(BGM.raf); BGM.raf = 0; BGM.lastT = 0;
  clearInterval(BGM.t); BGM.t = null;
  if (BGM.audio) { try { BGM.audio.pause(); } catch (e) {} BGM.audio.removeAttribute('src'); try { BGM.audio.load(); } catch (e2) {} }
}
function bgmLeave() { mbLeave('bgm'); bgmQuit(); BGM.playing = null; }
window.addEventListener('beforeunload', bgmQuit);
/* 波形：把这一首读进来算 200 个峰值（算过的记着）；演示数据画一条假的 */
function bgmWavPeaks(ab) {
  /* 手工解析 WAV：只认 16-bit PCM，直接按样本取 200 个峰值，不解码成 float（v4.0.2）；
     不是 PCM16（mp3/flac/24bit/float）返回 null，退回 decodeAudioData。 */
  try {
    var dv = new DataView(ab);
    if (dv.getUint32(0, false) !== 0x52494646 || dv.getUint32(8, false) !== 0x57415645) return null;
    var pos = 12, fmt = null, dataOff = -1, dataLen = 0;
    while (pos + 8 <= ab.byteLength) {
      var id = dv.getUint32(pos, false), sz = dv.getUint32(pos + 4, true);
      if (id === 0x666d7420) fmt = { f: dv.getUint16(pos + 8, true), ch: dv.getUint16(pos + 10, true), bits: dv.getUint16(pos + 22, true) };
      else if (id === 0x64617461) { dataOff = pos + 8; dataLen = Math.min(sz, ab.byteLength - dataOff); break; }
      pos += 8 + sz + (sz & 1);
    }
    if (!fmt || fmt.f !== 1 || fmt.bits !== 16 || !fmt.ch || dataOff < 0) return null;
    var frames = Math.floor(dataLen / (2 * fmt.ch));
    if (frames < 1) return null;
    var n = 200, per = Math.max(1, Math.floor(frames / n)), step = Math.max(1, Math.floor(frames / 400000));
    var end = dataOff + frames * 2 * fmt.ch, out = [], mx = .001;
    for (var b = 0; b < n; b++) {
      var s = dataOff + b * per * 2 * fmt.ch, e = Math.min(end, s + per * 2 * fmt.ch), m = 0;
      for (var p = s; p + 2 * fmt.ch <= e; p += 2 * fmt.ch * step) {
        for (var ch = 0; ch < fmt.ch; ch++) { var v = dv.getInt16(p + ch * 2, true); if (v < 0) v = -v; if (v > m) m = v; }
      }
      m /= 32768; out.push(m); if (m > mx) mx = m;
    }
    return out.map(function (x) { return x / mx; });
  } catch (e) { return null; }
}
function bgmPeaks(id) {
  if (BGM.peaks[id]) return Promise.resolve(BGM.peaks[id]);
  if (!useLive()) { var f = []; for (var i = 0; i < 200; i++) f.push(.25 + .6 * Math.abs(Math.sin(i * .21 + id) * Math.cos(i * .053 + id * 2))); BGM.peaks[id] = f; return Promise.resolve(f); }
  return fetch('/api/bgm/file/' + id).then(function (r) { if (!r.ok) throw new Error('x'); return r.arrayBuffer(); }).then(function (ab) {
    var pk = bgmWavPeaks(ab);
    if (pk) { ab = null; BGM.peaks[id] = pk; return pk; }       // 算完就把 ArrayBuffer 丢掉
    var AC = window.AudioContext || window.webkitAudioContext, ac = new AC();
    return ac.decodeAudioData(ab).then(function (buf) {
      var d = buf.getChannelData(0), n = 200, step = Math.floor(d.length / n) || 1, out = [], mx = .001;
      for (var i = 0; i < n; i++) { var m = 0; for (var k = i * step, e = Math.min(d.length, k + step); k < e; k += 16) { var v = Math.abs(d[k]); if (v > m) m = v; } out.push(m); if (m > mx) mx = m; }
      try { ac.close(); } catch (e2) {}
      BGM.peaks[id] = out.map(function (x) { return x / mx; }); return BGM.peaks[id];
    }, function (e2) { try { ac.close(); } catch (e3) {} throw e2; });
  });
}
function bgmHead() {
  var h = $('#bgHead'), cv = $('#bgWave'); if (!h || !cv) return;
  var a = BGM.audio, d = a && a.duration, pos = 0;
  if (a && isFinite(d) && d > 0) pos = Math.max(0, Math.min(1, a.currentTime / d));
  h.style.transform = 'translateX(' + Math.round(pos * (cv.clientWidth || 0)) + 'px)';
}
function bgmWave(force) {
  /* 静态波形画一次缓存在离屏 canvas；只有这一首换了或尺寸真的变了才重画（v4.0.2） */
  var cv = $('#bgWave'); if (!cv) return;
  var id = +cv.dataset.id;
  if (force) BGM.wv = null;
  bgmPeaks(id).then(function (pk) {
    if (!cv.isConnected) return;
    var r = cv.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (!r.width || !r.height) return;
    var w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    var wv = BGM.wv;
    if (!wv || wv.id !== id || wv.w !== w || wv.h !== h) {
      var off = document.createElement('canvas'); off.width = w; off.height = h;
      var c = off.getContext('2d'), cs = getComputedStyle(cv), n = pk.length, bw = w / n;
      c.clearRect(0, 0, w, h); c.fillStyle = cs.color || '#ccc'; c.globalAlpha = .55;
      for (var i = 0; i < n; i++) {
        var bh = Math.max(2, pk[i] * h * .9);
        c.fillRect(i * bw, (h - bh) / 2, Math.max(1, bw * .6), bh);
      }
      wv = BGM.wv = { id: id, w: w, h: h, off: off };
    }
    cv.getContext('2d').drawImage(wv.off, 0, 0);
    bgmHead();
  }).catch(function () {});
}
(function () {
  var last = '';
  window.addEventListener('resize', function () {
    if (typeof S === 'undefined' || S.view !== 'bgm') return;
    var cv = $('#bgWave'); if (!cv) return;
    var r = cv.getBoundingClientRect();
    var k = Math.round(r.width) + 'x' + Math.round(r.height) + '@' + Math.round((window.devicePixelRatio || 1) * 100);
    if (k === last) return;
    last = k; bgmWave(true);
  });
})();
function bgmTick() {
  /* 播放时每帧只挪播放位置线，不重画 canvas；时间文字最多每 100ms 更新一次（v4.0.2） */
  cancelAnimationFrame(BGM.raf);
  BGM.raf = requestAnimationFrame(function tick(ts) {
    var a = BGM.audio;
    if (!a || a.paused) { bgmHead(); BGM.raf = 0; return; }
    bgmHead();
    var now = typeof ts === 'number' ? ts : (window.performance && performance.now ? performance.now() : Date.now());
    if (now - (BGM.lastT || 0) >= 100) {
      BGM.lastT = now;
      var t = $('#bgTime'); if (t) t.textContent = bgmClock(a.currentTime) + ' / ' + bgmClock(a.duration || 0);
    }
    BGM.raf = requestAnimationFrame(tick);
  });
}
function bgmPlay(id, at) {
  if (!useLive()) { toast('演示模式没有声音'); return; }
  if (!BGM.audio) { BGM.audio = new Audio(); BGM.audio.addEventListener('ended', function () { cancelAnimationFrame(BGM.raf); BGM.raf = 0; BGM.sig = ''; renderBgm(); }); }
  var a = BGM.audio;
  if (BGM.playing === id && at == null) { if (a.paused) a.play(); else a.pause(); }
  else { if (BGM.playing !== id) a.src = '/api/bgm/file/' + id; BGM.playing = id; if (at != null) { var go = function () { a.currentTime = at * (a.duration || 0); }; if (a.readyState >= 1) go(); else a.addEventListener('loadedmetadata', go, { once: true }); } a.play().catch(function (e) { toast('放不了：' + e.message); }); }
  BGM.lastT = 0;
  setTimeout(function () { BGM.sig = ''; renderBgm(); bgmTick(); }, 60);
}
$('#view-bgm').addEventListener('input', function (ev) {
  if (ev.target.id === 'bgPrompt') { BGM.prompt = ev.target.value; BGM.preset = -1; if (typeof saveUI === 'function') saveUI({ bgmPrompt: BGM.prompt.slice(0, 300), bgmPreset: -1 }); }
  if (ev.target.id === 'bgSec') { BGM.seconds = +ev.target.value; var o = $('#bgSecO'); if (o) o.textContent = bgmClock(BGM.seconds); if (typeof saveUI === 'function') saveUI({ bgmSeconds: BGM.seconds }); }
});
$('#view-bgm').addEventListener('click', function (ev) {
  var cv = ev.target.closest('#bgWave');
  if (cv) { var r = cv.getBoundingClientRect(); bgmPlay(+cv.dataset.id, Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width))); return; }
  var t = ev.target.closest('button'); if (!t) return;
  var d = t.dataset;
  if (d.bgmMode) { BGM.mode = d.bgmMode; try { localStorage.setItem('agentBgm.mode', BGM.mode); } catch (e) {} if (typeof saveUI === 'function') saveUI({ bgmMode: BGM.mode }); BGM.sig = ''; renderBgm(); if (BGM.mode === 'batch') mbFetch('bgm'); return; }
  if (d.bgmPre != null) { BGM.preset = +d.bgmPre; BGM.prompt = BGM_PRESET[BGM.preset][1]; if (typeof saveUI === 'function') saveUI({ bgmPreset: BGM.preset, bgmPrompt: BGM.prompt.slice(0, 300) }); BGM.sig = ''; renderBgm(); return; }
  if (d.bgmSel) { BGM.sel = +d.bgmSel; if (BGM.audio && BGM.playing !== BGM.sel) BGM.audio.pause(); renderBgm(); return; }
  if (d.bgmPlay) { bgmPlay(+d.bgmPlay); return; }
  if (d.goSec) { openSec(d.goSec); return; }
  if (!useLive()) return;
  if (d.bgmGen) {
    var p = (BGM.prompt || '').trim(); if (!p) { toast('先写一句描述，或者点一个现成的风格'); var pi = $('#bgPrompt'); if (pi) pi.focus(); return; }
    t.disabled = true; t.textContent = '在启动…';
    api('POST', '/api/bgm/gen', { prompt: p, seconds: BGM.seconds }, 30000).then(function () { bgmFetch(); }).catch(function (e) { t.disabled = false; t.textContent = '出一首'; toast(e.message, 7000); });
  }
  else if (d.bgmStop) api('POST', '/api/bgm/stop', {}).then(bgmFetch).catch(function (e) { toast(e.message); });
  else if (d.bgmOff) api('POST', '/api/bgm/off', {}).then(function () { toast('关掉了，显存还回去了'); bgmFetch(); }).catch(function (e) { toast(e.message); });
  else if (d.bgmTows) api('POST', '/api/bgm/tows', { id: +d.bgmTows }).then(function (j) { toast(j.msg || '放进工作区了', 5000); }).catch(function (e) { toast(e.message, 6000); });
  else if (d.bgmOpen != null) api('POST', '/api/bgm/open', d.bgmOpen ? { id: +d.bgmOpen } : {}).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); });
});
