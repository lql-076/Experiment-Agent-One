'use strict';
/* ================= 配音（Qwen3-TTS，后端 app/tts.py） =================
   贴文案 → 选预设音色（或写一段音色描述）→ 可选语气 → 生成 → 当场试听 → 保存。
   页面只整页画一次；之后每秒（生成中）/ 每 5 秒只刷新右边的「生成」「结果」和右上角的服务状态，打字不会被打断。
   输入框里的内容存在这台电脑的浏览器里（只是方便，丢了也没事）。 */
var TTS = { st: null, timer: null, n: 0, form: null, resVer: null, busy: false };
var TTS_KEY = 'agentTTS.v1';
var TTS_DEMO = {
  demo: true, env: true, models: { custom: true, design: true }, server: false, proc: false, yield: '', job: null, draft: null,
  speakers: [
    { id: 'Vivian', name: 'Vivian', d: '女声 · 明亮、略带锐气的年轻女声', lang: '中文' }, { id: 'Serena', name: 'Serena', d: '女声 · 温柔、温暖的年轻女声', lang: '中文' },
    { id: 'Uncle_Fu', name: 'Uncle_Fu', d: '男声 · 低沉醇厚的成熟男声', lang: '中文' }, { id: 'Dylan', name: 'Dylan', d: '男声 · 清亮自然的北京青年', lang: '中文 · 北京话' },
    { id: 'Eric', name: 'Eric', d: '男声 · 活泼、略带沙哑的成都男声', lang: '中文 · 四川话' }, { id: 'Ryan', name: 'Ryan', d: '男声 · 节奏感强', lang: '英文' },
    { id: 'Aiden', name: 'Aiden', d: '男声 · 阳光的美式男声', lang: '英文' }, { id: 'Ono_Anna', name: 'Ono_Anna', d: '女声 · 俏皮轻快', lang: '日语' },
    { id: 'Sohee', name: 'Sohee', d: '女声 · 温暖、情感丰富', lang: '韩语' }],
  langs: [['Chinese', '中文'], ['English', '英文'], ['Auto', '自动']],
  voices: [{ id: 1, name: '解说男声', desc: '三十岁左右的男声，声音低沉温和，吐字清楚，语速平稳，像科技频道的解说', seed: 20261028 }],
  out: 'F:\\Agent\\配音输出', saved: null, speed: null, gap: 0.35, para: 0.7,
  sizes: { custom: 4.5e9, design: 4.5e9 }, inst: { st: 'idle' }
};
function ttsSeed() { return 1 + Math.floor(Math.random() * 2147483646); }
function ttsForm() {
  if (TTS.form) return TTS.form;
  var f = { mode: 'preset', speaker: 'Vivian', tone: '', desc: '', seed: ttsSeed(), name: '', lang: 'Chinese', text: '' };
  try { Object.assign(f, JSON.parse(localStorage.getItem(TTS_KEY)) || {}); } catch (e) {}
  TTS.form = f; return f;
}
var ttsKeepT = null;
function ttsKeep() { clearTimeout(ttsKeepT); ttsKeepT = setTimeout(function () { try { localStorage.setItem(TTS_KEY, JSON.stringify(TTS.form)); } catch (e) {} }, 300); }
function ttsTime(t, ms) { t = Math.max(0, t || 0); var m = Math.floor(t / 60), s = t - m * 60; return pad(m) + ':' + (ms ? (s < 10 ? '0' : '') + s.toFixed(1) : pad(Math.floor(s))); }
function ttsDur(sec) { sec = Math.round(sec || 0); return sec >= 60 ? Math.floor(sec / 60) + ' 分 ' + pad(sec % 60) + ' 秒' : sec + ' 秒'; }

function ttsLoad() {
  if (!useLive()) { TTS.st = TTS_DEMO; return Promise.resolve(TTS_DEMO); }
  return api('GET', '/api/tts', null, 6000).then(function (j) { TTS.st = j; return j; });
}
function ttsEnter() {
  ttsLoad().then(function () { if (S.view === 'tts') { if ($('#ttsGen')) ttsSync(); else renderTTS(); } }).catch(function () { if (!TTS.st) { TTS.st = TTS_DEMO; renderTTS(); } });
  clearInterval(TTS.timer);
  TTS.timer = setInterval(function () {
    TTS.n++;
    var run = TTS.st && TTS.st.job && TTS.st.job.st === 'run';
    if (!useLive() || TTS.busy || (!run && TTS.n % 5)) return;
    TTS.busy = true;
    ttsLoad().then(function () { if (S.view === 'tts') ttsSync(); }).catch(function () {}).then(function () { TTS.busy = false; });
  }, 1000);
}
function ttsLeave() { clearInterval(TTS.timer); TTS.timer = null; }

function renderTTS() {
  var v = $('#view-tts'), s = TTS.st, f = ttsForm();
  if (!s) { v.innerHTML = '<div class="empty">正在读取…</div>'; ttsEnter(); return; }
  var langs = (s.langs || TTS_DEMO.langs).map(function (l) { return '<option value="' + l[0] + '"' + (f.lang === l[0] ? ' selected' : '') + '>' + l[1] + '</option>'; }).join('');
  v.innerHTML = '<div class="page fill tts"><div class="ph"><h1>配音</h1><span class="sub">Qwen3-TTS 1.7B · 在这台电脑上生成，不联网 · Apache 2.0，可以商用 · 不克隆任何真人的声音</span><span class="tts-svc" id="ttsSvc"></span></div>' +
    '<div class="tts-grid">' +
      '<div class="hc tts-text stag" style="--i:0"><div class="hc-h"><span class="label">文案</span><span class="cap num" id="ttsCount"></span></div>' +
        '<textarea class="inp" id="ttsText" spellcheck="false" placeholder="把要念的文案贴在这里。会按句子切开，一句一句生成再拼起来；空一行算换段，停得久一点。">' + esc(f.text) + '</textarea>' +
        '<div class="tts-gaps"><label>句子之间停<input class="inp num" type="number" id="ttsGap" min="0" max="3" step="0.05" value="' + (+s.gap || 0.35) + '">秒</label>' +
          '<label>换段停<input class="inp num" type="number" id="ttsPara" min="0" max="5" step="0.05" value="' + (+s.para || 0.7) + '">秒</label></div></div>' +
      '<div class="hc tts-voice stag" style="--i:1"><div class="hc-h"><span class="label">音色</span><div class="seg" id="ttsMode"><button data-mode="preset">预设音色</button><button data-mode="design">描述音色</button></div></div>' +
        '<div class="tts-vb" id="ttsVoice"></div>' +
        '<div class="tts-row"><label class="tts-lab" for="ttsTone">语气（可选）</label><input class="inp" id="ttsTone" maxlength="200" placeholder="比如：语速稍快，带点兴奋；或者：像在跟朋友聊天" value="' + esc(f.tone) + '"></div>' +
        '<div class="tts-row tts-lang"><label class="tts-lab" for="ttsLang">语言</label><select class="inp" id="ttsLang">' + langs + '</select></div></div>' +
      '<div class="tts-side"><div class="hc tts-gen stag" style="--i:2" id="ttsGen"></div><div class="hc tts-res stag" style="--i:3" id="ttsRes"></div></div>' +
    '</div></div>';
  TTS.resVer = null;
  ttsVoice(); ttsSync(); ttsCount();
}
function ttsVoice() {
  var s = TTS.st, f = ttsForm(), b = $('#ttsVoice'); if (!b) return;
  $$('#ttsMode button').forEach(function (x) { x.setAttribute('aria-pressed', x.dataset.mode === f.mode); });
  if (f.mode === 'preset') {
    b.innerHTML = '<div class="tts-spk">' + (s.speakers || []).map(function (p) {
      return '<button class="tts-sp" data-spk="' + esc(p.id) + '" aria-pressed="' + (f.speaker === p.id) + '"><b>' + esc(p.name) + '<span class="tag">' + esc(p.lang) + '</span></b><small>' + esc(p.d) + '</small></button>';
    }).join('') + '</div>';
    return;
  }
  var vs = s.voices || [];
  b.innerHTML = '<div class="tts-mine"><span class="tts-lab">我的音色</span>' + (vs.length ? vs.map(function (v) {
      var on = f.desc === v.desc && +f.seed === +v.seed;
      return '<span class="tts-mv"><button class="chip" data-voice="' + v.id + '" aria-pressed="' + on + '" title="' + esc(v.desc) + ' · 种子 ' + v.seed + '">' + esc(v.name) + '</button><button class="tts-x" data-delvoice="' + v.id + '" aria-label="删掉「' + esc(v.name) + '」">' + ICONS.cross + '</button></span>';
    }).join('') : '<span class="cap">还没有。写好描述、听着满意，点下面「存成我的音色」。</span>') + '</div>' +
    '<textarea class="inp" id="ttsDesc" rows="3" maxlength="500" placeholder="描述想要的声音：性别、年龄、音色、语速、情绪。比如：三十岁左右的男声，声音低沉温和，吐字清楚，语速平稳，像科技频道的解说">' + esc(f.desc) + '</textarea>' +
    '<div class="tts-row2"><label class="tts-lab" for="ttsSeed">随机种子</label><input class="inp num" id="ttsSeed" type="number" min="1" value="' + esc(f.seed) + '"><button class="btn" data-act="reseed">换一个</button><button class="btn" data-act="same">试同一个人</button></div>' +
    '<div class="tts-row2"><input class="inp" id="ttsName" maxlength="40" placeholder="给这个音色起个名字" value="' + esc(f.name) + '"><button class="btn" data-act="savevoice">存成我的音色</button></div>' +
    '<p class="cap tts-note">同一段描述 + 同一个种子，换一段文字念，尽量还是同一个人。「试同一个人」用这个音色念两段完全不相干的话，听前后像不像一个人。</p>';
}
function ttsCount() {
  var el = $('#ttsCount'); if (!el) return;
  var t = (ttsForm().text || '').replace(/\s+/g, ''), n = t.length;
  if (!n) { el.textContent = '还没有字'; return; }
  var sec = n / 4.2, sp = TTS.st && TTS.st.speed;      // 中文大约一秒 4 个字
  el.textContent = n + ' 字 · 念出来约 ' + ttsDur(sec) + (sp && sp.per_min ? ' · 生成约 ' + ttsDur(sec / 60 * sp.per_min) : '');
}
function ttsKind() { return ttsForm().mode === 'design' ? 'design' : 'custom'; }
function ttsSync() {
  var s = TTS.st; if (!s || !$('#ttsGen')) return;
  var j = s.job, run = j && j.st === 'run';
  var svc = s.demo ? '<span class="pill">演示数据</span>' :
    s.server ? '<span class="pill" style="--c:var(--ok)">配音服务在线' + (s.loaded ? ' · 装着' + (s.loaded === 'custom' ? '预设音色' : '描述音色') + '模型' : '') + '</span>' + (run ? '' : '<button class="btn" data-act="off" title="关掉配音服务，显存还回去（闲置 ' + (s.idle || 10) + ' 分钟也会自己关）">关掉</button>') :
    s.proc ? '<span class="pill" style="--c:var(--c-neu)">配音服务启动中</span>' : '<span class="pill">配音服务没开 · 用到才启动</span>';
  $('#ttsSvc').innerHTML = svc;
  var kind = ttsKind(), miss = !s.env ? 'env' : !(s.models || {})[kind] ? 'model' : '';
  var g = '<div class="hc-h"><span class="label">生成</span>' + (s.speed ? '<span class="cap">上次实测：每分钟音频要生成 ' + ttsDur(s.speed.per_min) + '</span>' : '') + '</div>';
  var ins = s.inst || {};
  if (miss) g += '<div class="tts-warn"><b>' + (ins.st === 'run' ? '正在安装配音' + (ins.pct != null ? ' · ' + Math.round(ins.pct) + '%' : '') : miss === 'env' ? '还没装配音' : '还没下' + (kind === 'custom' ? '预设音色' : '描述音色') + '的模型') + '</b>' +
    '<span>' + (ins.st === 'run' ? esc(ins.phase || ins.line || '准备中') + '。装好了这里自己变。' : '到 设置 › 本地模型 点「安装配音」：装配音环境，再从魔搭下两个模型（每个 4~5 GB）。') + '</span>' +
    '<span class="btnrow"><button class="btn" data-act="goinst">去 设置 › 本地模型</button></span></div>';
  else if (s.yield && !run) g += '<div class="tts-warn"><b>现在在让路</b><span>' + esc(s.yield) + '。配音要 5~6 GB 显存，游戏关了再生成。</span></div>';
  if (run) {
    var pct = j.chars ? Math.round(j.done_chars / j.chars * 100) : 0;
    g += '<div class="prog"><div class="prog-h"><span>' + esc(j.msg) + '</span><b>' + pct + '%</b></div><div class="prog-bar"><i style="transform:scaleX(' + (pct / 100) + ')"></i></div>' +
      '<div class="prog-f">' + (j.cur ? '正在念：' + esc(j.cur.slice(0, 40)) + (j.cur.length > 40 ? '…' : '') : '准备中') + '</div>' +
      '<div class="prog-f">已生成 ' + ttsDur(j.audio_s) + ' 音频 · 用了 ' + ttsDur(j.elapsed) + (j.eta ? ' · 还要约 ' + ttsDur(j.eta) : '') + '</div></div>' +
      '<div class="btnrow"><button class="btn" data-act="stop">停下</button></div>';
  } else {
    if (j && j.st !== 'done') g += '<div class="tts-msg' + (j.st === 'err' ? ' bad' : '') + '">' + esc(j.msg) + '</div>';
    else if (j) g += '<div class="tts-msg ok">' + esc(j.msg) + '</div>';
    g += '<div class="btnrow"><button class="btn primary tts-go" data-act="gen"' + (miss || s.yield ? ' disabled' : '') + '>生成配音</button></div>';
  }
  $('#ttsGen').innerHTML = g;
  var d = s.draft, ver = d ? d.ver + '|' + (s.saved ? s.saved.name : '') : 'none';
  if (ver === TTS.resVer) return;
  TTS.resVer = ver;
  var r = '<div class="hc-h"><span class="label">试听</span>' + (d ? '<span class="cap num">' + esc(d.created.slice(5, 16)) + ' · ' + esc(ttsVoiceName(d)) + ' · ' + ttsDur(d.duration) + ' · ' + d.segments.length + ' 句</span>' : '') + '</div>';
  if (!d) r += '<div class="cap tts-empty">生成好的配音在这里试听，满意了点「保存」。<br>保存到：' + esc(s.out) + '（一次一个文件夹：WAV、时间轴 JSON、字幕 SRT、文案）</div>';
  else {
    r += (d.same_test ? '<div class="tts-msg">试同一个人：两段完全不相干的话，听前后像不像一个人。</div>' : '') +
      '<audio id="ttsAudio" controls preload="metadata" src="' + (s.demo ? '' : '/api/tts/draft.wav?v=' + d.ver) + '"></audio>' +
      '<div class="btnrow"><button class="btn primary" data-act="save">保存</button><button class="btn" data-act="open">打开配音输出</button></div>' +
      (s.saved ? '<div class="cap tts-saved">最近存的：<button class="tts-link" data-act="openlast">' + esc(s.saved.name) + '</button></div>' : '') +
      '<div class="tts-tl" id="ttsTl">' + d.segments.map(function (g, i) { return '<button class="tts-seg" data-i="' + i + '" data-t="' + g.start + '"><span class="num">' + ttsTime(g.start, true) + '</span><span>' + esc(g.text) + '</span></button>'; }).join('') + '</div>';
  }
  $('#ttsRes').innerHTML = r;
  var a = $('#ttsAudio'); if (a) a.addEventListener('timeupdate', ttsFollow);
}
function ttsVoiceName(d) { var v = d.voice || {}; return v.mode === 'design' ? (v.name || '描述音色') + ' · 种子 ' + v.seed : (v.speaker || ''); }
function ttsFollow() {
  var a = $('#ttsAudio'), d = TTS.st && TTS.st.draft; if (!a || !d) return;
  var t = a.currentTime, i = -1;
  d.segments.forEach(function (g, k) { if (t >= g.start - 0.05) i = k; });
  $$('#ttsTl .tts-seg').forEach(function (b) {
    var on = +b.dataset.i === i; if (b.classList.contains('on') === on) return;
    b.classList.toggle('on', on);
    if (on) { var l = $('#ttsTl'); if (b.offsetTop < l.scrollTop || b.offsetTop + b.offsetHeight > l.scrollTop + l.clientHeight) l.scrollTop = b.offsetTop - l.clientHeight / 3; }
  });
}
function ttsBody(same) {
  var f = ttsForm();
  return { mode: f.mode, speaker: f.speaker, tone: f.tone, lang: f.lang, text: f.text, desc: f.desc, seed: f.mode === 'design' ? f.seed : null, name: f.name, same: !!same };
}
function ttsGo(same) {
  var f = ttsForm();
  if (TTS.st.demo) { toast('演示模式：连上后端才能生成配音'); return; }
  if (!same && !(f.text || '').trim()) { toast('先把文案贴进来'); $('#ttsText').focus(); return; }
  if (f.mode === 'design' && !(f.desc || '').trim()) { toast('先写一段音色描述'); $('#ttsDesc').focus(); return; }
  api('POST', '/api/tts/gen', ttsBody(same)).then(function (j) { TTS.st.job = j.job; ttsSync(); }).catch(function (e) { toast(e.message, 4500); });
}
$('#view-tts').addEventListener('click', function (ev) {
  var t = ev.target.closest('button'); if (!t || t.disabled) return;
  var f = ttsForm(), live = useLive();
  if (t.dataset.mode) { f.mode = t.dataset.mode; ttsKeep(); ttsVoice(); ttsSync(); return; }
  if (t.dataset.spk) { f.speaker = t.dataset.spk; ttsKeep(); $$('#ttsVoice .tts-sp').forEach(function (b) { b.setAttribute('aria-pressed', b === t); }); return; }
  if (t.dataset.voice) {
    var v = (TTS.st.voices || []).filter(function (x) { return String(x.id) === t.dataset.voice; })[0]; if (!v) return;
    f.desc = v.desc; f.seed = v.seed; f.name = v.name; if (v.lang) f.lang = v.lang; ttsKeep(); ttsVoice(); var l = $('#ttsLang'); if (l) l.value = f.lang; toast('用「' + v.name + '」'); return;
  }
  if (t.dataset.delvoice) {
    if (!live) { toast('演示模式：连上后端才能删'); return; }
    api('DELETE', '/api/tts/voices/' + t.dataset.delvoice).then(function (j) { TTS.st.voices = j.voices; ttsVoice(); toast('删掉了'); }).catch(function (e) { toast(e.message); });
    return;
  }
  if (t.dataset.t !== undefined) { var a = $('#ttsAudio'); if (a) { a.currentTime = +t.dataset.t; a.play().catch(function () {}); } return; }
  var act = t.dataset.act; if (!act) return;
  if (act === 'gen') ttsGo(false);
  else if (act === 'same') ttsGo(true);
  else if (act === 'goinst') { S.sec = 'models'; renderSettings(); goView('settings'); }
  else if (act === 'reseed') { f.seed = ttsSeed(); ttsKeep(); $('#ttsSeed').value = f.seed; $$('#ttsVoice [data-voice]').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); }); }
  else if (act === 'savevoice') {
    if (!f.name.trim() || !f.desc.trim()) { toast('起个名字、写好描述再存'); return; }
    if (!live) { toast('演示模式：连上后端才能存'); return; }
    api('POST', '/api/tts/voices', { name: f.name, desc: f.desc, seed: f.seed, lang: f.lang }).then(function (j) { TTS.st.voices = j.voices; ttsVoice(); toast(j.msg); }).catch(function (e) { toast(e.message); });
  } else if (!live) toast('演示模式：连上后端才能用');
  else if (act === 'stop') api('POST', '/api/tts/stop', {}).then(function (j) { TTS.st.job = j.job; ttsSync(); });
  else if (act === 'off') api('POST', '/api/tts/off', {}).then(function () { toast('配音服务关了，显存还回去了'); return ttsLoad(); }).then(ttsSync).catch(function (e) { toast(e.message); });
  else if (act === 'save') api('POST', '/api/tts/save', {}).then(function (j) { toast(j.msg, 4500); return ttsLoad(); }).then(ttsSync).catch(function (e) { toast(e.message); });
  else if (act === 'open' || act === 'openlast') api('POST', '/api/tts/open', { last: act === 'openlast' }).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); });
});
$('#view-tts').addEventListener('input', function (ev) {
  var t = ev.target, f = ttsForm();
  var map = { ttsText: 'text', ttsTone: 'tone', ttsDesc: 'desc', ttsName: 'name', ttsSeed: 'seed', ttsLang: 'lang' };
  if (map[t.id]) {
    f[map[t.id]] = t.id === 'ttsSeed' ? (parseInt(t.value, 10) || 1) : t.value; ttsKeep();
    if (t.id === 'ttsText') ttsCount();
    if (t.id === 'ttsDesc' || t.id === 'ttsSeed') $$('#ttsVoice [data-voice]').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
  }
});
$('#view-tts').addEventListener('change', function (ev) {
  var t = ev.target;
  if (t.id === 'ttsGap' || t.id === 'ttsPara') {
    var v = Math.max(0, Math.min(t.id === 'ttsGap' ? 3 : 5, parseFloat(t.value) || 0)); t.value = v;
    setVal(t.id === 'ttsGap' ? 'ttsGap' : 'ttsParaGap', v);
    if (TTS.st) TTS.st[t.id === 'ttsGap' ? 'gap' : 'para'] = v;
    toast(t.id === 'ttsGap' ? '句子之间停 ' + v + ' 秒（下次生成起作用）' : '换段停 ' + v + ' 秒（下次生成起作用）');
  }
});

/* ================= 安装配音（设置 › 本地模型 里那一块，后端 app/tts_install.py） ================= */
function ttsGB(b) { return b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b >= 1e6 ? Math.round(b / 1e6) + ' MB' : '0'; }
function ttsInstLoad() {
  return ttsLoad().then(function () { var c = $('#ttsInst'), x = ttsInstHTML(); if (c && c.innerHTML !== x) c.innerHTML = x; }).catch(function () {});
}
function ttsInstHTML() {
  var s = TTS.st;
  if (!s) return '<div class="balbox ttsinst"><div><span class="label">配音 · Qwen3-TTS 1.7B</span><div class="help">正在读取…</div></div></div>';
  var i = s.inst || {}, run = i.st === 'run', m = s.models || {}, z = s.sizes || {}, live = useLive();
  var all = s.env && m.custom && m.design, some = s.env || m.custom || m.design || z.custom || z.design;
  var st = run ? ['warn', '正在安装'] : all ? ['ok', '装好了'] : some ? ['warn', '没装全'] : ['off', '还没装'];
  var row = function (ok, name, extra) { return '<li class="' + (ok ? 'ok' : '') + '"><i></i><span>' + name + '</span><em>' + extra + '</em></li>'; };   // 一行三项，横着排
  var mod = function (k, name) { var g = (z[k] || 0) >= 1e6 ? ' · ' + ttsGB(z[k]) : ''; return row(m[k], name, m[k] ? '已下' + g : g ? '下了一半' + g : '没下'); };
  var h = '<div class="balbox ttsinst"><div class="ttsi-main"><span class="label">配音 · Qwen3-TTS 1.7B（左边「配音」页用）</span><div class="hwc-st st-' + st[0] + '"><i></i><b>' + st[1] + '</b></div>' +
    '<ul class="ttsi-list">' + row(s.env, '配音环境', s.env ? '已装' : '没装') + mod('custom', '预设音色模型', '') + mod('design', '描述音色模型') + '</ul>';
  if (run) {
    var pct = i.pct == null ? null : Math.round(i.pct);
    h += '<div class="prog' + (pct == null ? ' busy' : '') + '"><div class="prog-h"><span>' + esc(i.phase || '准备中') + '</span><b>' + (pct == null ? '' : pct + '%') + '</b></div>' +
      '<div class="prog-bar"><i style="transform:scaleX(' + (pct == null ? 1 : pct / 100) + ')"></i></div>' +
      '<div class="prog-f">' + (i.speed ? (i.speed / 1e6).toFixed(1) + ' MB/s' : '') + (i.eta ? ' · 还要约 ' + ttsDur(i.eta) : '') + (i.line ? ' · ' + esc(i.line.slice(0, 60)) : '') + '</div></div>';
  } else if (i.st === 'fail') h += '<div class="tts-msg bad">上次没装完（退出码 ' + esc(i.code) + '）。再点一次会接着装；魔搭下不动就点「改从 hf-mirror 下」。原始输出：' + esc(i.log || '') + '</div>';
  else if (i.st === 'stop') h += '<div class="tts-msg">上次停下了，再点一次接着装。</div>';
  else if (i.st === 'ok') h += '<div class="tts-msg ok">装好了，左边点「配音」就能用。</div>';
  h += '<div class="help">约 14 GB：配音环境 5 GB + 两个模型各 4~5 GB（魔搭）。装过的跳过、断了接着下，关掉界面也接着装，每一步在 后台 › 进展报告。备用：双击「安装配音.bat」。</div></div>' +
    '<div class="btnrow">' + (run ? '<button class="btn" data-tti="stop">停下</button>'
      : '<button class="btn primary" data-tti="go"' + (live ? '' : ' disabled') + '>' + (all ? '重新检查一遍' : i.st === 'fail' || i.st === 'stop' || some ? '接着装' : '安装配音') + '</button>' +
        (i.st === 'fail' ? '<button class="btn" data-tti="hf">改从 hf-mirror 下</button>' : '')) + '</div></div>';
  return h;
}
$('#view-settings').addEventListener('click', function (ev) {
  var t = ev.target.closest('[data-tti]'); if (!t || t.disabled) return;
  if (!useLive()) { toast('演示模式：连上后端才能装'); return; }
  var go = t.dataset.tti === 'stop' ? api('POST', '/api/tts/install/stop', {}) : api('POST', '/api/tts/install', { hf: t.dataset.tti === 'hf' });
  t.disabled = true;
  go.then(function () { if (t.dataset.tti !== 'stop') toast('开始安装配音，可以关掉界面，它在后台接着装'); return ttsInstLoad(); }).catch(function (e) { toast(e.message, 5000); t.disabled = false; });
});
var ttsInstN = 0;
setInterval(function () {
  if (S.view !== 'settings' || S.sec !== 'models' || !useLive()) return;
  ttsInstN++;
  var run = TTS.st && TTS.st.inst && TTS.st.inst.st === 'run';
  if (run || ttsInstN % 5 === 0) ttsInstLoad();
}, 1000);
