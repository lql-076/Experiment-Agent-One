'use strict';
/* ================= 语音对话（v3.0）=================
   说：点指令条上的话筒，或者点主页中间的核心（没在打字时按住 Alt 再按 V 也行）→ 开始听；说完停 1 秒多自动收住 → 本地听写成字（/api/voice/asr）→
       像打字一样发出去（标成「说的」，模型会回得口语一点、短一点）。
   听：这条是说出来问的，回答好了就念出来（/api/voice/speak：Breeze TTS 2；没配好就用本地配音的预设音色顶着）。一边收一边放，点核心 / 话筒打断。
   连着聊（设置 › 语音 ›「连着聊」）：它念完自动接着听，不用再点。
   麦克风只在点了以后才开，收住就关；录音不落盘，只在内存里转成 16 kHz 单声道 WAV 发给本机后端。
   核心那颗球跟着声音大小跳（coreLevel），状态字跟着变（coreOver：listen / think / speak）。 */
var VOICE = { st: null, ts: 0, mode: '', stream: null, actx: null, node: null, src: null, buf: [], n: 0, sr: 48000, loud: 0, quiet: 0, heard: false, t0: 0, peak: 0, raf: 0,
  play: null, abort: null, lv: [] };
var VOICE_MAX = 60, VOICE_HUSH = 1.25, VOICE_NOISE = .012;      // 最长听 60 秒；停 1.25 秒算说完；比这个轻的算没声音

function voiceLoad(force) {
  if (!useLive() || TOOL || (!force && Date.now() - VOICE.ts < 20000)) return Promise.resolve(VOICE.st);
  VOICE.ts = Date.now();
  return api('GET', '/api/voice', null, 6000).then(function (j) { VOICE.st = j; voiceBarSync(); if (typeof coreSync === 'function') coreSync(); return j; }).catch(function () { return VOICE.st; });
}
function voiceOn() { return !!(useLive() && VOICE.st && VOICE.st.on); }                      // 以后端说的为准：设置是在另一个窗口里改的
function voiceReady() { return voiceOn() && !!(VOICE.st && VOICE.st.asr); }
function voiceWillSpeak() { return voiceOn() && VOICE.st.auto !== false && !!(VOICE.st.engine && VOICE.st.engine !== 'none'); }
function voiceBarSync() {
  var b = $('#cMic'), bar = $('#cBar'); if (!b) return;
  b.setAttribute('aria-pressed', VOICE.mode === 'listen');
  b.classList.toggle('speak', VOICE.mode === 'speak');
  if (bar) bar.classList.toggle('rec', VOICE.mode === 'listen' || VOICE.mode === 'think');
  var tx = $('#cWaveTx'); if (tx) tx.textContent = VOICE.mode === 'think' ? '在认字……' : '在听……说完停一下就发';
  b.title = VOICE.mode === 'listen' ? '再点一下：不说了（不发）' : VOICE.mode === 'speak' ? '点一下：别念了' :
    !voiceOn() ? '语音还没开：点一下去 设置 › 语音' : '说话：点一下开始，说完停一下自动发出去';
}
function voiceMode(m) {
  VOICE.mode = m || ''; voiceBarSync();
  if (typeof coreOver === 'function') coreOver(m || null);
  if (!m && typeof coreLevel === 'function') coreLevel(0);
}
/* 话筒 / 核心点一下：在念 → 打断；在听 → 取消；闲着 → 开始听 */
function voiceToggle() {
  if (!useLive()) { toast('演示模式不能说话'); return; }
  if (VOICE.mode === 'speak') { voiceHush(); return; }
  if (VOICE.mode === 'listen') { voiceStop(false); toast('不听了（没发出去）'); return; }
  if (VOICE.mode === 'think') return;
  voiceLoad(true).then(function (st) {
    if (!st) { toast('读不到语音的状态，后端还在吗？'); return; }
    if (!st.on) { toast('语音还没开：在 设置 › 语音 里打开', 5000); openSec('voice'); return; }
    if (!st.asr) { toast('听写还没装好：' + (st.asr_why || '在 设置 › 语音 里点「安装听写」'), 6000); openSec('voice'); return; }
    if (chatBusyEv()) { toast('它正在做事：想插话就打字（或者先点「停下」）', 5000); return; }
    voiceStart();
  });
}
function voiceStart() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { toast('这个窗口拿不到麦克风（需要 WebView2 / 浏览器允许）', 6000); return; }
  voiceHush();
  navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } }).then(function (stream) {
    var AC = window.AudioContext || window.webkitAudioContext, ac = new AC();
    VOICE.stream = stream; VOICE.actx = ac; VOICE.sr = ac.sampleRate; VOICE.buf = []; VOICE.n = 0; VOICE.quiet = 0; VOICE.heard = false; VOICE.t0 = Date.now(); VOICE.peak = 0; VOICE.lv = [];
    VOICE.src = ac.createMediaStreamSource(stream);
    var node = ac.createScriptProcessor(4096, 1, 1), mute = ac.createGain(); mute.gain.value = 0;      // 接到一个静音的增益上：不然有的内核不跑回调
    node.onaudioprocess = function (ev) {
      if (VOICE.mode !== 'listen') return;
      var d = ev.inputBuffer.getChannelData(0), s = 0;
      for (var i = 0; i < d.length; i++) s += d[i] * d[i];
      var rms = Math.sqrt(s / d.length), dt = d.length / VOICE.sr;
      VOICE.buf.push(new Float32Array(d)); VOICE.n += d.length; VOICE.loud = rms; VOICE.peak = Math.max(VOICE.peak, rms);
      var gate = Math.max(VOICE_NOISE, VOICE.peak * .12);
      if (rms > gate) { VOICE.heard = true; VOICE.quiet = 0; } else VOICE.quiet += dt;
      var sec = VOICE.n / VOICE.sr;
      if ((VOICE.heard && VOICE.quiet >= VOICE_HUSH) || sec >= VOICE_MAX) voiceStop(true);
      else if (!VOICE.heard && sec >= 8) { voiceStop(false); toast('没听到声音：看看麦克风是不是选对了、有没有静音', 6000); }
    };
    VOICE.src.connect(node); node.connect(mute); mute.connect(ac.destination); VOICE.node = node;
    voiceMode('listen'); voiceMeter();
  }).catch(function (e) {
    toast(/NotAllowed|Permission/i.test(e.name + e.message) ? '麦克风没被允许：在弹出的询问里点「允许」（Windows 设置 › 隐私 › 麦克风 里也要开着）' : '打不开麦克风：' + e.message, 7000);
  });
}
function voiceMeter() {                                   // 指令条里那条波形 + 核心跟着跳
  cancelAnimationFrame(VOICE.raf);
  var cv = $('#cWaveCv');
  VOICE.raf = requestAnimationFrame(function tick() {
    if (VOICE.mode !== 'listen' && VOICE.mode !== 'think') return;
    var lv = Math.min(1, VOICE.loud * 9); if (typeof coreLevel === 'function') coreLevel(VOICE.mode === 'listen' ? lv : 0);
    VOICE.lv.push(lv); if (VOICE.lv.length > 90) VOICE.lv.shift();
    if (cv && cv.isConnected) {
      var r = cv.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (cv.width !== Math.round(r.width * dpr)) { cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr); }
      var c = cv.getContext('2d'), w = cv.width, h = cv.height, n = VOICE.lv.length, bw = w / 90;
      c.clearRect(0, 0, w, h); c.fillStyle = getComputedStyle(cv).color || '#3dffa8';
      for (var i = 0; i < n; i++) { var bh = Math.max(2 * dpr, VOICE.lv[i] * h * .92); c.globalAlpha = .35 + .65 * (i / n); c.fillRect((90 - n + i) * bw, (h - bh) / 2, Math.max(1, bw * .55), bh); }
    } else cv = $('#cWaveCv');
    VOICE.raf = requestAnimationFrame(tick);
  });
}
function voiceRelease() {
  try { if (VOICE.node) { VOICE.node.onaudioprocess = null; VOICE.node.disconnect(); } if (VOICE.src) VOICE.src.disconnect(); } catch (e) {}
  if (VOICE.stream) VOICE.stream.getTracks().forEach(function (t) { t.stop(); });
  if (VOICE.actx) { try { VOICE.actx.close(); } catch (e) {} }
  VOICE.node = VOICE.src = VOICE.stream = VOICE.actx = null;
}
/* 把录到的声音降到 16 kHz、压成 16 位单声道 WAV */
function voiceWav() {
  var all = new Float32Array(VOICE.n), o = 0; VOICE.buf.forEach(function (b) { all.set(b, o); o += b.length; });
  var ratio = VOICE.sr / 16000, n = Math.floor(all.length / ratio), out = new DataView(new ArrayBuffer(44 + n * 2));
  var W = function (off, str) { for (var i = 0; i < str.length; i++) out.setUint8(off + i, str.charCodeAt(i)); };
  W(0, 'RIFF'); out.setUint32(4, 36 + n * 2, true); W(8, 'WAVEfmt '); out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, 16000, true); out.setUint32(28, 32000, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true); W(36, 'data'); out.setUint32(40, n * 2, true);
  for (var i = 0; i < n; i++) {                           // 一段取平均再落点：比直接跳着取干净
    var a = Math.floor(i * ratio), b = Math.min(all.length, Math.floor((i + 1) * ratio)), s = 0;
    for (var k = a; k < b; k++) s += all[k];
    var v = Math.max(-1, Math.min(1, s / Math.max(1, b - a))); out.setInt16(44 + i * 2, v < 0 ? v * 32768 : v * 32767, true);
  }
  return out.buffer;
}
function voiceStop(send) {
  if (VOICE.mode !== 'listen') return;
  var sec = VOICE.n / VOICE.sr, wav = send && VOICE.heard && sec > .4 ? voiceWav() : null;
  voiceRelease(); VOICE.buf = []; VOICE.n = 0;
  if (!wav) { voiceMode(''); return; }
  voiceMode('think');
  fetchT('/api/voice/asr', { method: 'POST', headers: { 'X-Agent': '1', 'Content-Type': 'audio/wav' }, body: wav }, 60000).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.detail || ('听写出错 ' + r.status)); return j; });
  }).then(function (j) {
    voiceMode('');
    var text = String(j.text || '').trim();
    if (!text) { toast('没听清，再说一次'); return; }
    if (chatBusyEv()) { var inp = $('#cIn'); if (inp) { inp.value = text; autoGrow(inp); } toast('它正在做事：听到的话放进输入框了，回车就是插话'); return; }
    chatAsk(text, [], null, { voice: true });
  }).catch(function (e) { voiceMode(''); toast('没听成：' + e.message, 6000); });
}
/* 回答好了：是说出来问的（或者设置里开了「打字问的也念」）就念 */
function voiceReply(ev, spoke) {
  if (!ev || !ev.reply || !voiceOn()) return;
  if (!(spoke ? VOICE.st.auto !== false : VOICE.st.all)) return;
  voiceSay(ev.reply, spoke && VOICE.st.hands);
}
function voiceHush() {                                    // 别念了
  if (VOICE.abort) { try { VOICE.abort.abort(); } catch (e) {} VOICE.abort = null; }
  if (VOICE.play) { try { VOICE.play.ctx.close(); } catch (e) {} VOICE.play = null; }
  if (VOICE.mode === 'speak') voiceMode('');
}
/* 把一段话念出来：后端一块一块回 16 位 PCM，这边接一块排一块（不等整段） */
function voiceSay(text, thenListen) {
  voiceHush();
  if (!useLive() || !String(text || '').trim()) return Promise.resolve(false);
  var ab = new AbortController(); VOICE.abort = ab;
  voiceMode('speak');
  return fetch('/api/voice/speak', { method: 'POST', headers: { 'X-Agent': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text }), signal: ab.signal }).then(function (r) {
    if (!r.ok) return r.json().catch(function () { return {}; }).then(function (j) { throw new Error(j.detail || ('出错了 ' + r.status)); });
    var sr = +r.headers.get('X-Sr') || 24000, AC = window.AudioContext || window.webkitAudioContext, ctx = new AC();
    var P = { ctx: ctx, at: ctx.currentTime + .12, left: null, an: ctx.createAnalyser(), n: 0, ended: false }; VOICE.play = P;
    P.an.fftSize = 256; P.an.connect(ctx.destination);
    var data = new Uint8Array(P.an.fftSize);
    (function meter() {
      if (VOICE.play !== P) return;
      P.an.getByteTimeDomainData(data); var s = 0; for (var i = 0; i < data.length; i++) { var v = (data[i] - 128) / 128; s += v * v; }
      if (typeof coreLevel === 'function') coreLevel(Math.min(1, Math.sqrt(s / data.length) * 4));
      if (P.ended && ctx.currentTime >= P.at + .1) { VOICE.play = null; try { ctx.close(); } catch (e) {} VOICE.abort = null; voiceMode(''); if (thenListen && voiceReady() && !chatBusyEv()) voiceStart(); return; }
      requestAnimationFrame(meter);
    })();
    var push = function (bytes) {                          // 一块 PCM（可能是奇数个字节：留一个到下一块）
      if (P.left) { var m = new Uint8Array(P.left.length + bytes.length); m.set(P.left); m.set(bytes, P.left.length); bytes = m; P.left = null; }
      if (bytes.length % 2) { P.left = bytes.slice(bytes.length - 1); bytes = bytes.slice(0, bytes.length - 1); }
      var n = bytes.length / 2; if (!n) return;
      var buf = ctx.createBuffer(1, n, sr), ch = buf.getChannelData(0), dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      for (var i = 0; i < n; i++) ch[i] = dv.getInt16(i * 2, true) / 32768;
      var src = ctx.createBufferSource(); src.buffer = buf; src.connect(P.an);
      P.at = Math.max(P.at, ctx.currentTime + .03); src.start(P.at); P.at += buf.duration; P.n += n;
    };
    var rd = r.body.getReader();
    return (function pump() {
      return rd.read().then(function (x) {
        if (VOICE.play !== P) { try { rd.cancel(); } catch (e) {} return false; }
        if (x.done) { P.ended = true; return P.n > 0; }
        push(x.value); return pump();
      });
    })();
  }).catch(function (e) {
    if (e.name !== 'AbortError') toast('没念出来：' + e.message, 6000);
    if (VOICE.abort === ab) { VOICE.abort = null; VOICE.play = null; voiceMode(''); }
    return false;
  });
}
document.addEventListener('keydown', function (ev) {
  if (TOOL || !ev.altKey || ev.ctrlKey || ev.metaKey || (ev.key !== 'v' && ev.key !== 'V')) return;
  ev.preventDefault(); if (root.dataset.mode === 'resident') return; voiceToggle();
});
document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && VOICE.mode === 'speak') voiceHush(); else if (ev.key === 'Escape' && VOICE.mode === 'listen') voiceStop(false); }, true);
