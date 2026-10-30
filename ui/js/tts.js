'use strict';
/* ================= 配音（后端 app/tts.py；百炼云端 app/tts_cloud.py） =================
   v1.8.12 重做成一张「控制台」：左边文案（云端能点一下插情绪标签），中间音色和表达，右边生成和波形。
   - 引擎：本地 Qwen3-TTS / 百炼云端，标题旁边的开关。
   - 音色：本地是预设 / 描述；云端是 音色库（现成的 + 我造的，都能试听）/ 设计（写描述造一个）/ 复刻（传一段录音）/ 读音（读音词典）。
   - 表达：语气；云端还有语速、音调、音量、语言。
   - 波形：生成好的配音画成波形，每句一段；点哪听哪，空格键播放 / 暂停，下面的时间轴跟着走。
   页面只整页画一次；之后每秒（生成中、音色审核中）/ 每 5 秒只刷新服务状态、「生成」、波形和音色列表，打字不会被打断。
   输入框里的内容存在这台电脑的浏览器里（只是方便，丢了也没事）。 */
var TTS = { st: null, timer: null, n: 0, form: null, resVer: null, busy: false, tryAu: null, tryUrl: null, tryId: '', eng: '', drawn: '',
  wave: null, hover: -1, raf: 0, clone: null, dict: null, armDel: '', vsig: '' };
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
  sizes: { custom: 4.5e9, design: 4.5e9, align: 1.84e9 }, align: true, inst: { st: 'idle' }, engine: 'local',
  cloud: { key: false, model: 'qwen-audio-3.1-tts-plus', known: true, price: 1.4, max: 2000, ratio: null, month: { n: 0, cny: 0, bill: 0 }, count: 1, quota: 1000,
    design_text: '大家好，欢迎来到这一期的 AI 工具实测，今天我们聊三个最近很火的新工具。', hotfix: { pronunciation: { '重庆': 'chong2 qing4' }, replace: {} },
    langs: [['', '自动'], ['zh', '中文'], ['en', '英文'], ['ja', '日语'], ['ko', '韩语']],
    voices: [
      { id: 'longanlingxin_v3.1', name: '龙安灵心', g: '女', d: '温柔知心，娓娓道来', kind: 'system' }, { id: 'longanhuan_v3.1', name: '龙安欢', g: '女', d: '活泼有感染力，带气氛', kind: 'system' },
      { id: 'longanfengyue_v3.1', name: '龙安风悦', g: '女', d: '平和自然，播报、叙述', kind: 'system' }, { id: 'xunanchuan_v3.1', name: '许南川', g: '男', d: '磁性沉稳，解说、旁白', kind: 'system' }],
    mine: [{ id: 'qwen-audio-3.1-tts-plus-vd-demo-000001', name: '科技解说', kind: 'design', status: 'OK', prompt: '三十岁左右的男声，低沉温和，语速平稳，适合科技解说' }] }
};
var TTS_TAGS = [['excited', '兴奋'], ['serious', '严肃'], ['sad', '难过'], ['whispers', '耳语'], ['very slowly', '很慢'], ['very fast', '很快'],
  ['laughing', '笑'], ['sighing', '叹气']];
var TTS_HINTS = ['男声', '女声', '二十多岁', '三十岁左右', '中年', '低沉', '清亮', '温柔', '磁性', '沉稳', '活泼', '语速平稳', '语速稍快', '吐字清楚', '像科技频道的解说', '像在讲故事', '像跟朋友聊天'];
var TTS_IC = {
  play: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 5.8v12.4L18.5 12z" fill="currentColor" stroke="none"/></svg>',
  pause: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><rect x="6.8" y="5.5" width="3.6" height="13" rx="1" fill="currentColor" stroke="none"/><rect x="13.6" y="5.5" width="3.6" height="13" rx="1" fill="currentColor" stroke="none"/></svg>',
  sync: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 8.5A7.5 7.5 0 0 0 5.4 7M5 15.5A7.5 7.5 0 0 0 18.6 17M5 3.5V7h3.5M19 20.5V17h-3.5"/></svg>',
  up: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15.5V4.5M7.5 9 12 4.5 16.5 9M5 15v3.5h14V15"/></svg>'
};
function ttsSeed() { return 1 + Math.floor(Math.random() * 2147483646); }
function ttsForm() {
  if (TTS.form) return TTS.form;
  var f = { mode: 'preset', speaker: 'Vivian', tone: '', desc: '', seed: ttsSeed(), name: '', lang: 'Chinese', text: '', cvoice: '', ctab: 'lib',
    rate: 1, pitch: 1, volume: 50, blang: '', dprompt: '', dname: '', dtext: '', dlang: 'zh', cname: '', clang: 'zh', csrc: 'upload', cden: false };
  try { Object.assign(f, JSON.parse(localStorage.getItem(TTS_KEY)) || {}); } catch (e) {}
  TTS.form = f; return f;
}
var ttsKeepT = null;
function ttsKeep() { clearTimeout(ttsKeepT); ttsKeepT = setTimeout(function () { try { localStorage.setItem(TTS_KEY, JSON.stringify(TTS.form)); } catch (e) {} }, 300); }
function ttsTime(t, ms) { t = Math.max(0, t || 0); var m = Math.floor(t / 60), s = t - m * 60; return pad(m) + ':' + (ms ? (s < 10 ? '0' : '') + s.toFixed(1) : pad(Math.floor(s))); }
function ttsDur(sec) { sec = Math.round(sec || 0); return sec >= 60 ? Math.floor(sec / 60) + ' 分 ' + pad(sec % 60) + ' 秒' : sec + ' 秒'; }
function ttsCloud() { return !!(TTS.st && TTS.st.engine === 'cloud'); }
function ttsCS() { return (TTS.st && TTS.st.cloud) || TTS_DEMO.cloud; }
function ttsModelName(m) { return { 'qwen-audio-3.1-tts-plus': 'Qwen-Audio-3.1-TTS-Plus', 'qwen-audio-3.1-tts-flash': 'Qwen-Audio-3.1-TTS-Flash' }[m] || m; }
/* 预估花费：和后端 tts_cloud.estimate 一样。没实测过按汉字算 2 个计费字符（偏高一点）；生成过一次按百炼实际的比例 */
function ttsEst(text) {
  var c = ttsCS(), t = (text || '').replace(/\s+/g, ''), raw = t.length, cjk = (t.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || []).length;
  var bill = c.ratio ? Math.round(raw * c.ratio) : raw + cjk;
  return { raw: raw, bill: bill, cny: bill * (+c.price || 0) / 1e4 };
}
function ttsYuan(x) { return x > 0 && x < 0.005 ? '不到 1 分钱' : '¥' + (+x || 0).toFixed(2); }
function ttsHash(s) { var h = 2166136261; s = String(s); for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; } return h; }
/* 声纹小图：按音色 ID 算出来的一排竖条，每个音色长得不一样；试听时跳动 */
function ttsGlyph(id) {
  var h = ttsHash(id), out = '';
  for (var i = 0; i < 11; i++) { h = (Math.imul(h, 1103515245) + 12345) >>> 0; out += '<i style="--h:' + (0.22 + ((h >>> 16) % 1000) / 1300).toFixed(2) + ';--d:' + (i * 63) + 'ms"></i>'; }
  return '<span class="vp" aria-hidden="true">' + out + '</span>';
}

function ttsLoad() {
  if (!useLive()) { TTS.st = TTS_DEMO; return Promise.resolve(TTS_DEMO); }
  return api('GET', '/api/tts', null, 6000).then(function (j) { if (TTS.eng) j.engine = TTS.eng; TTS.st = j; return j; });   // 刚点过的引擎为准（设置晚 0.4 秒才存进后端）
}
function ttsRefresh() { if (S.view !== 'tts') return; if ($('#ttsGen') && TTS.drawn === TTS.st.engine) ttsSync(); else renderTTS(); }
function ttsEnter() {
  ttsLoad().then(ttsRefresh).catch(function () { if (!TTS.st) { TTS.st = TTS_DEMO; renderTTS(); } });
  clearInterval(TTS.timer);
  TTS.timer = setInterval(function () {
    TTS.n++;
    var s = TTS.st, run = s && s.job && s.job.st === 'run', dep = s && s.cloud && (s.cloud.mine || []).some(function (v) { return v.status === 'DEPLOYING'; });
    if (!useLive() || TTS.busy || (!run && !dep && TTS.n % 5)) return;
    TTS.busy = true;
    ttsLoad().then(ttsRefresh).catch(function () {}).then(function () { TTS.busy = false; });
  }, 1000);
}
function ttsLeave() { clearInterval(TTS.timer); TTS.timer = null; if (TTS.tryAu) TTS.tryAu.pause(); var a = $('#ttsAudio'); if (a) a.pause(); }

/* ---------- 整页 ---------- */
function renderTTS() {
  var v = $('#view-tts'), s = TTS.st, f = ttsForm();
  if (!s) { v.innerHTML = '<div class="empty">正在读取…</div>'; ttsEnter(); return; }
  var cloud = ttsCloud(), cs = ttsCS();
  TTS.drawn = s.engine;
  v.innerHTML = '<div class="page fill tts" data-eng="' + (cloud ? 'cloud' : 'local') + '">' +
    '<div class="ph tts-top"><h1>配音</h1>' +
      '<div class="tts-eng" id="ttsEng" role="group" aria-label="用哪个引擎" data-on="' + (cloud ? 'cloud' : 'local') + '">' +
        '<button data-eng="local" aria-pressed="' + !cloud + '"><b>本地</b><small>Qwen3-TTS · 不联网</small></button>' +
        '<button data-eng="cloud" aria-pressed="' + cloud + '"><b>云端</b><small>百炼 · ' + esc(ttsModelName(cs.model)) + '</small></button></div>' +
      '<span class="sub">' + (cloud ? '阿里云百炼（北京）· 只把这页的文案和语气发过去 · 按字计费 · 生成的内容归你' : '在这台电脑上生成，不联网 · Apache 2.0，可以商用 · 不克隆任何真人的声音') + '</span>' +
      '<span class="tts-svc" id="ttsSvc"></span></div>' +
    '<div class="tts-grid">' +
      '<section class="hc tts-text stag" style="--i:0"><div class="hc-h"><span class="label">文案</span><span class="cap num" id="ttsCount"></span></div>' +
        (cloud ? '<div class="tts-tags" id="ttsTags"><span class="tts-lab">插标签</span>' + TTS_TAGS.map(function (t) { return '<button class="tts-tag" data-tag="' + t[0] + '" title="在光标处插 [' + t[0] + ']：从这里开始' + (/laughing|sighing|clears/.test(t[0]) ? '加一声' : '用这种语气') + '">' + t[1] + '</button>'; }).join('') + '</div>' : '') +
        '<textarea class="inp" id="ttsText" spellcheck="false" placeholder="把要念的文案贴在这里。默认整段一次念完，语气前后连贯；空一行算换段，停得久一点。">' + esc(f.text) + '</textarea>' +
        '<div class="tts-gaps"><label>句子之间停<input class="inp num" type="number" id="ttsGap" min="0" max="3" step="0.05" value="' + (+s.gap || 0.35) + '">秒</label>' +
          '<label>换段停<input class="inp num" type="number" id="ttsPara" min="0" max="5" step="0.05" value="' + (+s.para || 0.7) + '">秒</label></div></section>' +
      '<section class="hc tts-voice stag" style="--i:1"><div class="hc-h"><span class="label">音色</span><span class="cap" id="ttsVcap"></span></div>' +
        (cloud ? '<div class="tts-tabs" id="ttsTabs" role="group" aria-label="音色">' + [['lib', '音色库'], ['design', '设计'], ['clone', '复刻'], ['dict', '读音']].map(function (t) {
            return '<button data-tab="' + t[0] + '" aria-pressed="' + (f.ctab === t[0]) + '">' + t[1] + '</button>'; }).join('') + '</div>'
          : '<div class="tts-tabs" id="ttsMode" role="group" aria-label="音色"><button data-mode="preset">预设音色</button><button data-mode="design">描述音色</button></div>') +
        '<div class="tts-vb" id="ttsVoice"></div><div class="tts-expr" id="ttsExpr"></div></section>' +
      '<section class="hc tts-out stag" style="--i:2"><div class="tts-gen" id="ttsGen"></div><div class="tts-res" id="ttsRes"></div></section>' +
    '</div></div>';
  TTS.resVer = null; TTS.vsig = '';
  ttsVoice(); ttsExpr(); ttsSync(); ttsCount();
}

/* ---------- 音色 ---------- */
function ttsVRow(o) {   // o: {id, name, tag, d, sel, attr, play, st}
  var stx = o.st === 'DEPLOYING' ? '<span class="vst dep">审核中</span>' : o.st === 'UNDEPLOYED' ? '<span class="vst bad">没通过审核</span>' : o.st === 'GONE' ? '<span class="vst bad">百炼上已删</span>' : '';
  var off = o.st && o.st !== 'OK';
  return '<div class="vrow' + (TTS.tryId === o.id && TTS.tryAu && !TTS.tryAu.paused ? ' playing' : '') + (off ? ' off' : '') + (o.play ? ' hasplay' : '') + '" data-row="' + esc(o.id) + '">' +
    '<button class="tts-sp" ' + o.attr + ' aria-pressed="' + !!o.sel + '"' + (off ? ' disabled' : '') + '>' + ttsGlyph(o.id) +
      '<span class="vt"><b><span class="vn">' + esc(o.name) + '</span>' + (o.tag ? '<span class="tag">' + esc(o.tag) + '</span>' : '') + stx + '</b><small>' + esc(o.d || '') + '</small></span></button>' +
    (o.play ? '<button class="vplay" data-cvtry="' + esc(o.id) + '" aria-label="试听「' + esc(o.name) + '」" title="试听：念一句固定的短句（念过的再听不花钱）">' + (TTS.tryId === o.id && TTS.tryAu && !TTS.tryAu.paused ? TTS_IC.pause : TTS_IC.play) + '</button>' : '') +
    (o.del ? '<button class="vdel" data-bdel="' + esc(o.id) + '" aria-label="删掉「' + esc(o.name) + '」" title="删掉（百炼那边也删）">' + (TTS.armDel === o.id ? '再点一次删除' : ICONS.cross) + '</button>' : '') + '</div>';
}
function ttsMineRow(v) {
  var cur = ttsCVoice();
  return ttsVRow({ id: v.id, name: v.name, tag: (v.kind === 'clone' ? '复刻' : '设计') + (v.g ? ' · ' + v.g + '声' : ''), d: v.kind === 'clone' ? (v.src || '') + (v.dur ? ' · ' + v.dur + ' 秒' : '') : v.prompt,
    sel: cur === v.id, attr: 'data-cv="' + esc(v.id) + '"', play: v.status === 'OK' || v.kind === 'design', st: v.status, del: true });
}
function ttsVoice() {
  var s = TTS.st, f = ttsForm(), b = $('#ttsVoice'); if (!b) return;
  var cap = $('#ttsVcap');
  if (ttsCloud()) {
    var cs = ttsCS(), mine = cs.mine || [];
    TTS.vsig = mine.map(function (v) { return v.id + v.status + v.name; }).join('|');
    $$('#ttsTabs button').forEach(function (x) { x.setAttribute('aria-pressed', x.dataset.tab === f.ctab); });
    if (cap) cap.textContent = cs.model + (mine.length ? ' · 自己造的 ' + mine.length + ' 个' : '');
    b.innerHTML = f.ctab === 'design' ? ttsDesignHTML() : f.ctab === 'clone' ? ttsCloneHTML() : f.ctab === 'dict' ? ttsDictHTML() : ttsLibHTML();
    if (f.ctab === 'clone') ttsCloneWave();
    return;
  }
  $$('#ttsMode button').forEach(function (x) { x.setAttribute('aria-pressed', x.dataset.mode === f.mode); });
  if (cap) cap.textContent = f.mode === 'preset' ? (s.speakers || []).length + ' 个预设音色' : '一段文字描述 + 随机种子';
  if (f.mode === 'preset') {
    b.innerHTML = '<div class="tts-vl">' + (s.speakers || []).map(function (p) {
      return ttsVRow({ id: p.id, name: p.name, tag: p.lang, d: p.d, sel: f.speaker === p.id, attr: 'data-spk="' + esc(p.id) + '"' });
    }).join('') + '</div>';
    return;
  }
  var vs = s.voices || [];
  b.innerHTML = '<div class="tts-form"><div class="tts-mine"><span class="tts-lab">我的音色</span>' + (vs.length ? vs.map(function (v) {
      var on = f.desc === v.desc && +f.seed === +v.seed;
      return '<span class="tts-mv"><button class="chip" data-voice="' + v.id + '" aria-pressed="' + on + '" title="' + esc(v.desc) + ' · 种子 ' + v.seed + '">' + esc(v.name) + '</button><button class="tts-x" data-delvoice="' + v.id + '" aria-label="删掉「' + esc(v.name) + '」">' + ICONS.cross + '</button></span>';
    }).join('') : '<span class="cap">还没有。写好描述、听着满意，点下面「存成我的音色」。</span>') + '</div>' +
    '<label class="tts-lab" for="ttsDesc">描述这个声音</label><textarea class="inp" id="ttsDesc" rows="3" maxlength="500" placeholder="性别、年龄、音色、语速、情绪。比如：三十岁左右的男声，声音低沉温和，吐字清楚，语速平稳，像科技频道的解说">' + esc(f.desc) + '</textarea>' +
    '<div class="tts-row2"><label class="tts-lab" for="ttsSeed">随机种子</label><input class="inp num" id="ttsSeed" type="number" min="1" value="' + esc(f.seed) + '"><button class="btn" data-act="reseed">换一个</button><button class="btn" data-act="same">试同一个人</button></div>' +
    '<div class="tts-row2"><input class="inp" id="ttsName" maxlength="40" placeholder="给这个音色起个名字" value="' + esc(f.name) + '"><button class="btn" data-act="savevoice">存成我的音色</button></div>' +
    '<p class="cap tts-note">同一段描述 + 同一个种子，换一段文字念，尽量还是同一个人。「试同一个人」用这个音色念两段完全不相干的话，听前后像不像一个人。</p></div>';
}
function ttsLibHTML() {
  var cs = ttsCS(), cur = ttsCVoice(), mine = cs.mine || [];
  return '<div class="tts-vh"><span>百炼现成的</span><span class="num">' + (cs.voices || []).length + ' 个</span></div><div class="tts-vl">' +
    (cs.voices || []).map(function (p) { return ttsVRow({ id: p.id, name: p.name, tag: p.g ? p.g + '声' : '', d: p.d, sel: cur === p.id, attr: 'data-cv="' + esc(p.id) + '"', play: true }); }).join('') + '</div>' +
    (cs.known ? '' : '<p class="cap tts-note">设置里的模型「' + esc(cs.model) + '」没收录音色表，先列 Plus 的；报音色不对就换回 qwen-audio-3.1-tts-plus。</p>') +
    '<div class="tts-vh"><span>我造的</span><span class="tts-vha"><span class="num" title="一个百炼账号最多 ' + cs.quota + ' 个（设计和复刻共用）">' + (cs.count || 0) + '/' + (cs.quota || 1000) + '</span>' +
      '<button class="btn mini" data-act="sync" title="拿百炼上的音色列表对一遍：在百炼控制台造的也加进来，更新审核状态">' + TTS_IC.sync + '同步</button></span></div>' +
    (mine.length ? '<div class="tts-vl">' + mine.slice().reverse().map(ttsMineRow).join('') + '</div>'
      : '<div class="tts-none">还没有自己造的。到「设计」写一段描述造一个，或者到「复刻」传一段录音。创建不要钱。</div>') +
    '<p class="cap tts-note">现成音色的风格是按官方音色表写的，以试听为准。自己造的音色和模型绑定，一年没用过会被百炼删掉。</p>';
}
function ttsDesignHTML() {
  var f = ttsForm(), cs = ttsCS(), recent = (cs.mine || []).filter(function (v) { return v.kind === 'design'; }).slice(-4).reverse();
  return '<div class="tts-form">' +
    '<label class="tts-lab" for="bdPrompt">描述这个声音（最多 500 字）</label>' +
    '<textarea class="inp" id="bdPrompt" rows="4" maxlength="500" placeholder="具体一点：性别、年龄、音色、语速、情绪、用在哪。比如：三十岁左右的男声，低沉有磁性，吐字清楚，语速平稳，适合科技解说。不要写「像某某明星」。">' + esc(f.dprompt) + '</textarea>' +
    '<div class="tts-chips" aria-label="点一下加进描述">' + TTS_HINTS.map(function (w) { return '<button class="chip" data-hint="' + esc(w) + '">' + esc(w) + '</button>'; }).join('') + '</div>' +
    '<div class="tts-2c"><div class="tts-row"><label class="tts-lab" for="bdName">名字</label><input class="inp" id="bdName" maxlength="20" placeholder="比如：科技解说" value="' + esc(f.dname) + '"></div>' +
      '<div class="tts-row"><span class="tts-lab">语言</span><div class="seg" id="bdLang">' + [['zh', '中文'], ['en', '英文']].map(function (l) { return '<button data-dlang="' + l[0] + '" aria-pressed="' + (f.dlang === l[0]) + '">' + l[1] + '</button>'; }).join('') + '</div></div></div>' +
    '<div class="tts-row"><label class="tts-lab" for="bdText">试听念这句（15~200 字）</label><input class="inp" id="bdText" maxlength="200" placeholder="' + esc(cs.design_text || '') + '" value="' + esc(f.dtext) + '"></div>' +
    '<div class="tts-gorow"><button class="btn primary" data-act="design">设计一个音色</button><span class="cap">不要钱，造好马上能听</span></div>' +
    (recent.length ? '<div class="tts-vh"><span>最近设计的</span><span>不满意就改描述再设计一个，比着听</span></div><div class="tts-vl">' + recent.map(ttsMineRow).join('') + '</div>' : '') + '</div>';
}
function ttsCloneHTML() {
  var f = ttsForm(), s = TTS.st, d = s.draft, c = TTS.clone, cs = ttsCS(), recent = (cs.mine || []).filter(function (v) { return v.kind === 'clone'; }).slice(-3).reverse();
  var src = f.csrc === 'draft' ? 'draft' : 'upload', ready = src === 'draft' ? !!d : !!c;
  var box;
  if (src === 'upload') {
    var warn = c && c.dur != null ? (c.dur < 5 ? '太短了：至少 5 秒连续清楚的说话' : c.dur > 60 ? '太长了：最长 60 秒（会被拒）' : c.dur > 25 ? '长了点：推荐 10~20 秒' : '') : '';
    box = '<label class="tts-drop' + (c ? ' has' : '') + '" id="bcDrop" for="bcFile"><input type="file" id="bcFile" class="sr" accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4,audio/x-m4a">' +
      (c ? '<canvas id="bcWave" aria-hidden="true"></canvas><span class="tts-dropf"><b>' + esc(c.name) + '</b><span class="num">' + (c.size / 1048576).toFixed(1) + ' MB' + (c.dur != null ? ' · ' + c.dur.toFixed(1) + ' 秒' : '') + '</span></span>' +
          (warn ? '<span class="tts-dropw">' + warn + '</span>' : '<span class="cap">换一个：再点这里，或者把文件拖进来</span>')
        : TTS_IC.up + '<b>把录音拖到这里，或者点这里选文件</b><span class="cap">WAV / MP3 / M4A · 10~20 秒最好，最长 60 秒 · 10 MB 以内</span>') + '</label>';
  } else {
    box = '<div class="tts-drop has fromdraft">' + (d ? '<b>' + esc(ttsVoiceName(d)) + ' · ' + ttsDur(d.duration) + '</b><span class="cap">最近一次生成的配音。' + (d.duration > 20 ? '取前 20 秒左右，在停顿处截断。' : '整段拿去复刻。') +
      '先用本地的「描述音色」或者云端的设计音色念一段，再拿来复刻，就是一个 AI 造的、固定下来的声音。</span>' : '<b>还没有生成过配音</b><span class="cap">先生成一段（比如用本地的描述音色），再回来拿它复刻。</span>') + '</div>';
  }
  return '<div class="tts-form">' +
    '<div class="seg tts-src" id="bcSrc">' + [['upload', '上传录音'], ['draft', '用最近生成的配音']].map(function (x) { return '<button data-csrc="' + x[0] + '" aria-pressed="' + (src === x[0]) + '">' + x[1] + '</button>'; }).join('') + '</div>' +
    box +
    '<div class="tts-2c"><div class="tts-row"><label class="tts-lab" for="bcName">名字</label><input class="inp" id="bcName" maxlength="20" placeholder="比如：我的解说" value="' + esc(f.cname) + '"></div>' +
      '<div class="tts-row"><label class="tts-lab" for="bcLang">录音的语言</label><select class="inp" id="bcLang">' + (cs.langs || []).filter(function (l) { return l[0]; }).map(function (l) { return '<option value="' + l[0] + '"' + (f.clang === l[0] ? ' selected' : '') + '>' + l[1] + '</option>'; }).join('') + '</select></div></div>' +
    '<div class="field row tts-den"><div><label for="bcDen">降噪、增强、音量规整</label><div class="help">录音有点杂音时打开</div></div><button class="switch" role="switch" id="bcDen" aria-checked="' + !!f.cden + '"></button></div>' +
    '<label class="tts-ok"><input type="checkbox" id="bcOk"><span>这段声音是我自己的，或者是 AI 生成的。不复刻别人的声音（没有授权会侵权）。</span></label>' +
    '<div class="tts-gorow"><button class="btn primary" data-act="clone"' + (ready ? '' : ' disabled') + '>复刻这个声音</button><span class="cap">不要钱，只发这段录音</span></div>' +
    '<details class="tts-tips"><summary>怎么录好</summary><p class="cap">安静的小房间，关掉风扇空调；离麦克风一拳左右；10~20 秒完整的句子，语速平常，中间别停太久；不要背景音乐、别人的声音、唱歌。</p></details>' +
    (recent.length ? '<div class="tts-vh"><span>最近复刻的</span></div><div class="tts-vl">' + recent.map(ttsMineRow).join('') + '</div>' : '') + '</div>';
}
function ttsDictInit() {
  if (TTS.dict) return TTS.dict;
  var h = ttsCS().hotfix || { pronunciation: {}, replace: {} }, toRows = function (o) { return Object.keys(o).map(function (k) { return { w: k, t: o[k] }; }); };
  TTS.dict = { p: toRows(h.pronunciation || {}), r: toRows(h.replace || {}) };
  return TTS.dict;
}
function ttsDictHTML() {
  var d = ttsDictInit();
  var rows = function (k, ph1, ph2) {
    return d[k].map(function (r, i) {
      return '<div class="tts-drow"><input class="inp" data-dk="' + k + '" data-di="' + i + '" data-df="w" maxlength="20" placeholder="' + ph1 + '" value="' + esc(r.w) + '">' +
        '<input class="inp' + (k === 'p' ? ' num' : '') + '" data-dk="' + k + '" data-di="' + i + '" data-df="t" maxlength="40" placeholder="' + ph2 + '" value="' + esc(r.t) + '">' +
        '<button class="tts-x" data-dictdel="' + k + ':' + i + '" aria-label="删掉这一条">' + ICONS.cross + '</button></div>';
    }).join('') + '<button class="btn mini" data-dictadd="' + k + '">加一条</button>';
  };
  return '<div class="tts-form"><p class="cap tts-note">多音字念错了、缩写想换个念法，加在这里。生成时只把这次文案里出现的词发给百炼。</p>' +
    '<div class="tts-vh"><span>读音（拼音后面跟声调数字，轻声写 5）</span><span class="num">' + d.p.length + '</span></div><div class="tts-dict">' + rows('p', '重庆', 'chong2 qing4') + '</div>' +
    '<div class="tts-vh"><span>替换（念的时候换成这几个字）</span><span class="num">' + d.r.length + '</span></div><div class="tts-dict">' + rows('r', 'LHY', 'L H Y') + '</div>' +
    '<div class="tts-gorow"><button class="btn primary" data-act="dictsave">存读音词典</button><span class="cap">最多 200 条</span></div></div>';
}
function ttsExpr() {
  var e = $('#ttsExpr'), f = ttsForm(), s = TTS.st; if (!e) return;
  var tone = '<div class="tts-row"><label class="tts-lab" for="ttsTone">语气' + (ttsCloud() ? '指令' : '') + '（可选）</label><input class="inp" id="ttsTone" maxlength="' + (ttsCloud() ? 100 : 200) + '" placeholder="' +
    (ttsCloud() ? '比如：请用轻松、带点兴奋的语气，语速稍快' : '比如：语速稍快，带点兴奋；或者：像在跟朋友聊天') + '" value="' + esc(f.tone) + '"></div>';
  if (!ttsCloud()) {
    var langs = (s.langs || TTS_DEMO.langs).map(function (l) { return '<option value="' + l[0] + '"' + (f.lang === l[0] ? ' selected' : '') + '>' + l[1] + '</option>'; }).join('');
    e.innerHTML = tone + '<div class="tts-row tts-lang"><label class="tts-lab" for="ttsLang">语言</label><select class="inp" id="ttsLang">' + langs + '</select></div>';
    return;
  }
  var knob = function (id, k, l, min, max, step, def, fmt) {
    var v = f[k] == null ? def : +f[k];
    return '<label for="' + id + '">' + l + '</label><input type="range" id="' + id + '" data-knob="' + k + '" data-def="' + def + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + v + '" title="双击回到默认">' +
      '<output id="o' + id + '" class="' + (v !== def ? 'mod' : '') + '">' + fmt(v) + '</output>';
  };
  var x = function (v) { return '×' + (+v).toFixed(2).replace(/0$/, ''); };
  e.innerHTML = tone + '<div class="tts-knobs">' + knob('ttsRate', 'rate', '语速', 0.5, 2, 0.05, 1, x) + knob('ttsPitch', 'pitch', '音调', 0.5, 2, 0.05, 1, x) + knob('ttsVol', 'volume', '音量', 0, 100, 1, 50, function (v) { return String(v); }) +
    '<label for="ttsBLang">语言</label><select class="inp" id="ttsBLang">' + (ttsCS().langs || []).map(function (l) { return '<option value="' + l[0] + '"' + (f.blang === l[0] ? ' selected' : '') + '>' + l[1] + '</option>'; }).join('') + '</select><span></span></div>';
}
function ttsCVoice() {
  var cs = ttsCS(), f = ttsForm(), ok = (cs.voices || []).concat((cs.mine || []).filter(function (v) { return v.status === 'OK'; }));
  return ok.some(function (v) { return v.id === f.cvoice; }) ? f.cvoice : ((cs.voices || [])[0] || {}).id || '';
}
function ttsCVName() { var id = ttsCVoice(), cs = ttsCS(), v = (cs.voices || []).concat(cs.mine || []).filter(function (x) { return x.id === id; })[0]; return v ? v.name : ''; }

/* ---------- 字数和预估 ---------- */
function ttsCount() {
  var el = $('#ttsCount'); if (!el) return;
  var t = (ttsForm().text || '').replace(/\s+/g, ''), n = t.length;
  if (!n) { el.textContent = '还没有字'; ttsEstShow(); return; }
  var sec = n / 4.2, sp = TTS.st && TTS.st.speed;      // 中文大约一秒 4 个字
  el.textContent = n + ' 字 · 念出来约 ' + ttsDur(sec) + (ttsCloud() ? ' · 预估 ' + ttsYuan(ttsEst(ttsForm().text).cny) : sp && sp.per_min ? ' · 生成约 ' + ttsDur(sec / 60 * sp.per_min) : '');
  ttsEstShow();
}
function ttsEstHTML() {
  var c = ttsCS(), e = ttsEst(ttsForm().text), n = (ttsForm().text || '').replace(/\s+/g, '').length, parts = Math.ceil(n / Math.max(200, +c.max || 2000));
  if (!e.raw) return '<b>预估花费</b><span>贴了文案就显示：多少计费字符、大概多少钱。</span>';
  return '<b>预估：约 ' + e.bill + ' 计费字符 · ' + ttsYuan(e.cny) + '</b><span>' + (c.ratio ? '按上次百炼实际的计费比例估' : '没实测过，汉字按 2 个字符估（偏高一点）') + '；单价 ' + c.price + ' 元/万字符，设置 › 云端 能改' +
    (parts > 1 ? '。超过 ' + c.max + ' 字，按段落分 ' + parts + ' 块左右念，同一个音色和语气' : '') + '</span>';
}
function ttsEstShow() { var b = $('#ttsEst'); if (b) b.innerHTML = ttsEstHTML(); }

/* ---------- 刷新：服务状态、生成、波形、音色列表 ---------- */
function ttsKind() { return ttsForm().mode === 'design' ? 'design' : 'custom'; }
function ttsProg(j) {
  var pct = j.pct != null ? Math.floor(j.pct) : j.chars ? Math.round(j.done_chars / j.chars * 100) : 0;
  return '<div class="prog"><div class="prog-h"><span>' + esc(j.msg) + '</span><b>' + pct + '%</b></div><div class="prog-bar"><i style="transform:scaleX(' + (pct / 100) + ')"></i></div>' +
    '<div class="prog-f">' + (j.cur ? (j.whole && j.engine !== 'cloud' ? '这一段从这里开始：' : '正在念：') + esc(j.cur.slice(0, 40)) + (j.cur.length > 40 ? '…' : '') : '准备中') + '</div>' +
    '<div class="prog-f">已生成 ' + ttsDur(j.audio_s) + ' 音频 · 用了 ' + ttsDur(j.elapsed) + (j.eta ? ' · 还要约 ' + ttsDur(j.eta) : '') + '</div></div>' +
    '<div class="btnrow"><button class="btn" data-act="stop">停下</button></div>';
}
function ttsSync() {
  var s = TTS.st; if (!s || !$('#ttsGen')) return;
  var j = s.job, run = j && j.st === 'run';
  var stage = $('#ttsStage'); if (stage) stage.classList.toggle('busy', !!run);
  if (ttsCloud()) {
    ttsSyncCloud(s, j, run);
    var mine = ttsCS().mine || [], sig = mine.map(function (v) { return v.id + v.status + v.name; }).join('|'), ae = document.activeElement;
    if (sig !== TTS.vsig && !(ae && $('#ttsVoice') && $('#ttsVoice').contains(ae) && /INPUT|TEXTAREA|SELECT/.test(ae.tagName))) ttsVoice();
  } else ttsSyncLocal(s, j, run);
  ttsSyncRes(s);
}
function ttsSyncLocal(s, j, run) {
  $('#ttsSvc').innerHTML = s.demo ? '<span class="pill">演示数据</span>' :
    s.server ? '<span class="pill" style="--c:var(--ok)">配音服务在线' + (s.loaded ? ' · 装着' + (s.loaded === 'custom' ? '预设音色' : '描述音色') + '模型' : '') + '</span>' + (run ? '' : '<button class="btn" data-act="off" title="关掉配音服务，显存还回去（闲置 ' + (s.idle || 10) + ' 分钟也会自己关）">关掉</button>') :
    s.proc ? '<span class="pill" style="--c:var(--c-neu)">配音服务启动中</span>' : '<span class="pill">配音服务没开 · 用到才启动</span>';
  var kind = ttsKind(), miss = !s.env ? 'env' : !(s.models || {})[kind] ? 'model' : '', ins = s.inst || {}, g = '';
  if (miss) g += '<div class="tts-warn"><b>' + (ins.st === 'run' ? '正在安装配音' + (ins.pct != null ? ' · ' + Math.round(ins.pct) + '%' : '') : miss === 'env' ? '还没装配音' : '还没下' + (kind === 'custom' ? '预设音色' : '描述音色') + '的模型') + '</b>' +
    '<span>' + (ins.st === 'run' ? esc(ins.phase || ins.line || '准备中') + '。装好了这里自己变。' : '到 设置 › 本地模型 点「安装配音」：装配音环境，再从魔搭下两个模型（每个 4~5 GB）。') + '</span>' +
    '<span class="btnrow"><button class="btn" data-act="goinst">去 设置 › 本地模型</button></span></div>';
  else if (s.yield && !run) g += '<div class="tts-warn"><b>现在在让路</b><span>' + esc(s.yield) + '。配音要 5~6 GB 显存，游戏关了再生成（或者换「云端」，不用显卡）。</span></div>';
  if (run) g += ttsProg(j);
  else {
    var whole = s.whole !== false;
    g += '<div class="tts-gorow"><button class="btn primary tts-go" data-act="gen"' + (miss || s.yield ? ' disabled' : '') + '>生成配音</button>' +
      '<div class="seg" id="ttsWay" role="group" aria-label="怎么生成"><button data-way="1" aria-pressed="' + whole + '" title="一次念完，语气前后连贯；念完才出声音，进度是估的">整段一次生成</button>' +
      '<button data-way="0" aria-pressed="' + !whole + '" title="一句一句念，进度准，但每句语气可能不一样">一句一句</button></div></div>' +
      '<div class="cap tts-wayhint">' + (whole ? '整段一次念完，语气前后连贯；念完才出声音，进度是按上次的速度估的。' : '一句一句念，进度准，但每句是分开念的，语气可能不一样。') +
      (s.speed ? ' 上次实测：生成 1 分钟音频要 ' + ttsDur(s.speed.per_min) + '。' : '') + '</div>';
    if (j) g += '<div class="tts-msg' + (j.st === 'done' ? ' ok' : j.st === 'err' ? ' bad' : '') + '">' + esc(j.msg) + '</div>';
  }
  $('#ttsGen').innerHTML = g;
}
function ttsSyncCloud(s, j, run) {
  var c = ttsCS(), m = c.month || {};
  $('#ttsSvc').innerHTML = (s.demo ? '<span class="pill">演示数据</span>' : c.key ? '<span class="pill" style="--c:var(--ok)">百炼 Key 已填 · 不用显卡</span>' : '<span class="pill" style="--c:var(--c-neu)">还没填百炼 Key</span>') +
    '<span class="pill" title="本月云端配音：生成和第一次试听都算">本月 ' + ttsYuan(+m.cny || 0) + ' · ' + (m.n || 0) + ' 次</span>';
  var g = '';
  if (!c.key && !s.demo) g += '<div class="tts-warn"><b>还没填百炼 API Key</b><span>到 设置 › 云端 填北京地域的 Key（加密保存在本机，不写日志、不进导出）。</span>' +
    '<span class="btnrow"><button class="btn" data-act="gokey">去 设置 › 云端</button></span></div>';
  if (run) g += ttsProg(j);
  else {
    g += '<div class="tts-gorow"><button class="btn primary tts-go" data-act="gen"' + (!c.key && !s.demo ? ' disabled' : '') + '>生成配音</button>' +
      '<span class="tts-using">用 <b>' + esc(ttsCVName()) + '</b> 念</span></div>' +
      '<div class="tts-warn tts-est" id="ttsEst">' + ttsEstHTML() + '</div>';
    if (j) g += '<div class="tts-msg' + (j.st === 'done' ? ' ok' : j.st === 'err' ? ' bad' : '') + '">' + esc(j.msg) + '</div>';
  }
  $('#ttsGen').innerHTML = g;
}
function ttsVoiceName(d) { var v = d.voice || {}; return v.mode === 'design' ? (v.name || '描述音色') + ' · 种子 ' + v.seed : v.mode === 'cloud' ? (v.name || v.voice) + ' · 百炼' : (v.speaker || ''); }
function ttsSyncRes(s) {
  var d = s.draft, ver = d ? d.ver + '|' + (d.realigned || '') + '|' + (s.saved ? s.saved.name : '') + '|' + !!s.align : 'none';
  if (ver === TTS.resVer) return;
  TTS.resVer = ver;
  var r = '<div class="hc-h"><span class="label">试听</span>' + (d ? '<span class="cap num">' + esc(d.created.slice(5, 16)) + ' · ' + esc(ttsVoiceName(d)) + ' · ' + ttsDur(d.duration) + ' · ' + d.segments.length + ' 句</span>' : '') + '</div>' +
    '<div class="tts-stage' + (s.job && s.job.st === 'run' ? ' busy' : '') + '" id="ttsStage"><canvas id="ttsWave" aria-label="波形：点哪听哪"></canvas>' +
      (d ? '' : '<div class="tts-empty">生成好的配音画在这里：波形上一段是一句，点哪听哪。<br>满意了点「保存」，存到 ' + esc(s.out) + '（一次一个文件夹：WAV、时间轴、字幕、文案）</div>') + '</div>' +
    (d && d.check ? ttsChkHTML(d.check) : '');
  if (d) {
    r += (d.same_test ? '<div class="tts-msg">试同一个人：两段完全不相干的话，听前后像不像一个人。</div>' : '') +
      '<div class="tts-transport"><button class="tts-play" id="ttsPlay" data-act="play" aria-label="播放 / 暂停（空格键）">' + TTS_IC.play + '</button>' +
        '<span class="tts-tc num" id="ttsTc">00:00.0<i> / ' + ttsTime(d.duration, true) + '</i></span>' +
        '<span class="tts-tsp"></span><button class="btn primary" data-act="save">保存</button><button class="btn" data-act="open" title="打开「配音输出」文件夹">打开文件夹</button></div>' +
      (s.saved ? '<div class="cap tts-saved">最近存的：<button class="tts-link" data-act="openlast">' + esc(s.saved.name) + '</button></div>' : '') +
      '<audio id="ttsAudio" preload="auto" src="' + (s.demo ? '' : '/api/tts/draft.wav?v=' + d.ver) + '"></audio>' +
      '<div class="tts-tl" id="ttsTl">' + d.segments.map(function (g, i) { return '<button class="tts-seg' + (g.est ? ' est' : '') + '" data-i="' + i + '" data-t="' + g.start + '"' + (g.est ? ' title="这句的开始、结束没对上，是估的"' : '') + '><span class="num">' + (g.est ? '≈' : '') + ttsTime(g.start, true) + '</span><span>' + esc(g.text) + '</span></button>'; }).join('') + '</div>';
  }
  $('#ttsRes').innerHTML = r;
  var a = $('#ttsAudio');
  if (a) {
    a.addEventListener('timeupdate', ttsFollow);
    a.addEventListener('play', ttsPlayState); a.addEventListener('pause', ttsPlayState); a.addEventListener('ended', ttsPlayState);
  }
  ttsStageWatch();
  if (d && !s.demo) ttsWaveLoad(d); else { TTS.wave = null; ttsDraw(); }
}

/* 时间轴准不准（v1.8.13）：用的哪种办法、几句是准的、句子边界是不是都落在停顿上 */
function ttsChkHTML(c) {
  /* 时间轴准不准（v1.8.14）：本地对齐 / 百炼逐字时间戳是准的（绿）；按停顿猜的标红，能对齐就给「重新对齐」，没装对齐模型就说去哪装 */
  var s = TTS.st || {}, how = c.how || [];
  var guess = how.indexOf('pause') >= 0 || (c.sure === undefined && /停顿/.test(c.method || ''));
  var off = c.bounds ? c.bounds - (c.bounds_in_silence || 0) : 0, warn = c.estimated || off, t;
  if (guess) t = '时间轴：没对齐，是按停顿猜的，可能对不上' + (c.why_not_aligned && s.align ? '（' + esc(c.why_not_aligned) + '）' : '');
  else t = '时间轴：' + esc(c.method) + '，' + (c.estimated ? c.exact + '/' + c.sentences + ' 句对上了，' + c.estimated + ' 句是估的（时间前面带 ≈）' : c.sentences + ' 句都对上了') +
    (off ? '；' + off + ' 处句子边界没落在停顿上，那里可能偏了' : '');
  var tail = '';
  if ((guess || warn) && s.align && !s.demo) tail = ' <button class="tts-link" data-act="realign"' + (s.aligning ? ' disabled' : '') + '>重新对齐</button><span class="cap">（声音不动、不花钱）</span>';
  else if (guess && !s.align) tail = '。<span class="cap">装上对齐模型就准了：设置 › 本地模型 点「接着装」（约 1.8 GB）</span>';
  return '<div class="tts-chk ' + (guess ? 'bad' : warn ? 'warn' : 'ok') + '" id="ttsChk"><span>' + t + tail + '</span></div>';
}

/* ---------- 波形 ---------- */
function ttsPeaks(buf, n) {
  var dv = new DataView(buf), p = 12, sr = 24000, off = 0, len = 0;
  while (p + 8 <= buf.byteLength) {
    var id = String.fromCharCode(dv.getUint8(p), dv.getUint8(p + 1), dv.getUint8(p + 2), dv.getUint8(p + 3)), sz = dv.getUint32(p + 4, true);
    if (id === 'fmt ') sr = dv.getUint32(p + 12, true);
    if (id === 'data') { off = p + 8; len = Math.min(sz, buf.byteLength - off); break; }
    p += 8 + sz + (sz & 1);
  }
  var cnt = Math.floor(len / 2), a = new Int16Array(buf, off, cnt), out = new Float32Array(n), step = Math.max(1, cnt / n), mx = 1;
  for (var i = 0; i < n; i++) {
    var s0 = Math.floor(i * step), s1 = Math.min(cnt, Math.floor((i + 1) * step)), m = 0;
    for (var k = s0; k < s1; k += 4) { var v = a[k] < 0 ? -a[k] : a[k]; if (v > m) m = v; }
    out[i] = m; if (m > mx) mx = m;
  }
  for (i = 0; i < n; i++) out[i] = Math.pow(out[i] / mx, 0.7);
  return { peaks: out, dur: cnt / sr };
}
function ttsWaveLoad(d) {
  if (TTS.wave && TTS.wave.ver === d.ver) { ttsDraw(); return; }
  TTS.wave = { ver: d.ver, peaks: null, dur: d.duration };
  ttsDraw();
  fetch('/api/tts/draft.wav?v=' + d.ver, { cache: 'no-store' }).then(function (r) { return r.arrayBuffer(); }).then(function (b) {
    if (!TTS.wave || TTS.wave.ver !== d.ver) return;
    var p = ttsPeaks(b, 1200); TTS.wave.peaks = p.peaks; TTS.wave.dur = p.dur || d.duration; ttsDraw();
  }).catch(function () {});
}
function ttsCol() {
  var cs = getComputedStyle($('#view-tts')), g = function (k, d) { return (cs.getPropertyValue(k) || '').trim() || d; };
  return { acc: g('--accent', '#1fd6f0'), acc2: g('--accent2', '#ff9a3c'), t2: g('--text2', '#96c4ce'), t3: g('--text3', '#6b9ca8'), line: g('--line2', '#1b4757'), neu: g('--c-neu', '#ffb020') };
}
function ttsDraw() {
  var cv = $('#ttsWave'); if (!cv) return;
  var dpr = Math.min(2, window.devicePixelRatio || 1), W = Math.max(1, cv.clientWidth), H = Math.max(1, cv.clientHeight);
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  var x = cv.getContext('2d'); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, W, H);
  var c = ttsCol(), d = TTS.st && TTS.st.draft, w = TTS.wave, mid = H / 2 + 6, amp = H / 2 - 18;
  x.globalAlpha = 0.5; x.strokeStyle = c.line; x.lineWidth = 1; x.beginPath(); x.moveTo(0, mid + 0.5); x.lineTo(W, mid + 0.5); x.stroke(); x.globalAlpha = 1;
  if (!d || !w) return;
  var dur = w.dur || d.duration || 1, a = $('#ttsAudio'), now = a ? a.currentTime : 0, X = function (t) { return t / dur * W; };
  // 秒刻度
  var tick = dur > 240 ? 30 : dur > 90 ? 10 : dur > 30 ? 5 : 1;
  x.font = '10px ' + (getComputedStyle(document.body).getPropertyValue('--fn') || 'monospace'); x.fillStyle = c.t3; x.globalAlpha = 0.55;
  for (var t = 0; t <= dur; t += tick) { var tx = Math.round(X(t)) + 0.5; x.fillRect(tx, 0, 1, 5); if (t % (tick * 2) === 0 && tx < W - 30) x.fillText(ttsTime(t), tx + 3, 11); }
  x.globalAlpha = 1;
  // 每句一段：底下一条，正在放的那句亮
  var cur = -1; d.segments.forEach(function (g, i) { if (now >= g.start - 0.05) cur = i; });
  d.segments.forEach(function (g, i) {
    var s0 = X(g.start), s1 = Math.max(s0 + 2, X(g.end));
    x.fillStyle = i === cur ? c.acc : g.est ? c.neu : c.t3; x.globalAlpha = i === cur ? 0.9 : g.est ? 0.55 : 0.28;
    x.fillRect(s0, H - 5, s1 - s0, 3);
    if (i === TTS.hover || i === cur) { x.globalAlpha = i === cur ? 0.10 : 0.07; x.fillStyle = c.acc; x.fillRect(s0, 16, s1 - s0, H - 24); }
  });
  x.globalAlpha = 1;
  if (!w.peaks) { x.fillStyle = c.t3; x.font = '12px ' + (getComputedStyle(document.body).getPropertyValue('--sans') || 'sans-serif'); x.fillText('正在读波形…', 12, mid - 6); return; }
  // 波形：放过的部分亮
  var bw = 3, gap = 1, n = Math.floor(W / (bw + gap)), pk = w.peaks, px = X(now);
  for (var i = 0; i < n; i++) {
    var v = pk[Math.min(pk.length - 1, Math.floor(i / n * pk.length))], h = Math.max(1.5, v * amp), bx = i * (bw + gap);
    x.fillStyle = bx < px ? c.acc : c.t2; x.globalAlpha = bx < px ? 0.95 : 0.42;
    x.fillRect(bx, mid - h, bw, h * 2);
  }
  x.globalAlpha = 1;
  if (now > 0 || (a && !a.paused)) { x.fillStyle = c.acc; x.shadowColor = c.acc; x.shadowBlur = 10; x.fillRect(Math.round(px) - 1, 12, 2, H - 16); x.shadowBlur = 0; }
}
var ttsRO = window.ResizeObserver ? new ResizeObserver(function () { ttsDraw(); }) : null;
function ttsStageWatch() { var st = $('#ttsStage'); if (st && ttsRO) { ttsRO.disconnect(); ttsRO.observe(st); } }
function ttsLoop() { cancelAnimationFrame(TTS.raf); var a = $('#ttsAudio'); ttsDraw(); ttsTc(); if (a && !a.paused) TTS.raf = requestAnimationFrame(ttsLoop); }
function ttsTc() { var a = $('#ttsAudio'), el = $('#ttsTc'), d = TTS.st && TTS.st.draft; if (el && a && d) el.innerHTML = ttsTime(a.currentTime, true) + '<i> / ' + ttsTime(d.duration, true) + '</i>'; }
function ttsPlayState() { var a = $('#ttsAudio'), b = $('#ttsPlay'); if (b && a) { b.innerHTML = a.paused ? TTS_IC.play : TTS_IC.pause; b.classList.toggle('on', !a.paused); } ttsLoop(); }
function ttsSeek(t, play) { var a = $('#ttsAudio'); if (!a) return; a.currentTime = Math.max(0, t); if (play) { if (TTS.tryAu) TTS.tryAu.pause(); a.play().catch(function () {}); } ttsDraw(); ttsTc(); ttsFollow(); }
function ttsFollow() {
  var a = $('#ttsAudio'), d = TTS.st && TTS.st.draft; if (!a || !d) return;
  var t = a.currentTime, i = -1;
  d.segments.forEach(function (g, k) { if (t >= g.start - 0.05) i = k; });
  $$('#ttsTl .tts-seg').forEach(function (b) {
    var on = +b.dataset.i === i; if (b.classList.contains('on') === on) return;
    b.classList.toggle('on', on);
    if (on) { var l = $('#ttsTl'); if (b.offsetTop < l.scrollTop || b.offsetTop + b.offsetHeight > l.scrollTop + l.clientHeight) l.scrollTop = b.offsetTop - l.clientHeight / 3; }
  });
  if (a.paused) { ttsDraw(); ttsTc(); }
}
function ttsStageAt(ev) { var cv = $('#ttsWave'), d = TTS.st && TTS.st.draft, w = TTS.wave; if (!cv || !d) return null; var r = cv.getBoundingClientRect(); return Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)) * ((w && w.dur) || d.duration); }

/* ---------- 复刻：选的录音画个小波形 ---------- */
function ttsCloneFile(file) {
  if (!file) return;
  if (!/\.(wav|mp3|m4a)$/i.test(file.name) && !/^audio\//.test(file.type)) { toast('录音要是 WAV、MP3 或 M4A'); return; }
  if (file.size > 10 * 1024 * 1024) { toast('录音最大 10 MB（推荐 10~20 秒）'); return; }
  var rd = new FileReader();
  rd.onload = function () {
    TTS.clone = { name: file.name, size: file.size, data: rd.result, dur: null, peaks: null };
    if (!ttsForm().cname) { ttsForm().cname = file.name.replace(/\.[^.]+$/, '').slice(0, 20); ttsKeep(); }
    ttsVoice();
    try {
      var AC = window.AudioContext || window.webkitAudioContext, ac = new AC();
      fetch(rd.result).then(function (r) { return r.arrayBuffer(); }).then(function (b) { return ac.decodeAudioData(b); }).then(function (ab) {
        var ch = ab.getChannelData(0), n = 160, step = Math.max(1, Math.floor(ch.length / n)), pk = [], mx = 0.0001;
        for (var i = 0; i < n; i++) { var m = 0; for (var k = i * step; k < Math.min(ch.length, (i + 1) * step); k += 8) { var v = Math.abs(ch[k]); if (v > m) m = v; } pk.push(m); if (m > mx) mx = m; }
        if (TTS.clone && TTS.clone.data === rd.result) { TTS.clone.dur = ab.duration; TTS.clone.peaks = pk.map(function (v) { return v / mx; }); if (ttsForm().ctab === 'clone') ttsVoice(); }
        ac.close();
      }).catch(function () { try { ac.close(); } catch (e) {} });
    } catch (e) {}
  };
  rd.readAsDataURL(file);
}
function ttsCloneWave() {
  var cv = $('#bcWave'), c = TTS.clone; if (!cv || !c || !c.peaks) return;
  var dpr = Math.min(2, window.devicePixelRatio || 1), W = cv.clientWidth, H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr;
  var x = cv.getContext('2d'), col = ttsCol(); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.fillStyle = col.acc; x.globalAlpha = 0.8;
  var n = c.peaks.length, bw = W / n;
  c.peaks.forEach(function (v, i) { var h = Math.max(1, v * (H / 2 - 2)); x.fillRect(i * bw, H / 2 - h, Math.max(1, bw - 1), h * 2); });
}

/* ---------- 试听一个云端音色（后端念一句固定的短句；念过的、设计时给的不花钱）。再点一下停 ---------- */
function ttsTryMark() {
  $$('#ttsVoice .vrow').forEach(function (r) {
    var on = r.dataset.row === TTS.tryId && TTS.tryAu && !TTS.tryAu.paused, b = r.querySelector('.vplay');
    r.classList.toggle('playing', !!on); if (b) b.innerHTML = on ? TTS_IC.pause : TTS_IC.play;
  });
}
function ttsTry(id, btn) {
  if (!useLive()) { toast('演示模式：连上后端才能试听'); return; }
  if (TTS.tryAu && TTS.tryId === id && !TTS.tryAu.paused) { TTS.tryAu.pause(); return; }
  if (btn) { btn.disabled = true; btn.classList.add('wait'); }
  fetchT('/api/tts/cloud/try', { method: 'POST', headers: { 'X-Agent': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ voice: id }) }, 90000)
    .then(function (r) {
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (j) { throw new Error(j.detail || ('试听没成：' + r.status)); });
      return r.blob().then(function (b) { return { b: b, cached: r.headers.get('X-Cached') === '1' }; });
    })
    .then(function (x) {
      if (TTS.tryAu) TTS.tryAu.pause();
      if (TTS.tryUrl) URL.revokeObjectURL(TTS.tryUrl);
      var main = $('#ttsAudio'); if (main) main.pause();
      TTS.tryUrl = URL.createObjectURL(x.b); TTS.tryAu = new Audio(TTS.tryUrl); TTS.tryId = id;
      ['play', 'pause', 'ended'].forEach(function (e) { TTS.tryAu.addEventListener(e, ttsTryMark); });
      TTS.tryAu.play().catch(function () {});
      if (!x.cached) { toast('试听：第一次念这个音色，花了不到一分钱'); ttsLoad().then(ttsRefresh).catch(function () {}); }
      ttsTryMark();
    })
    .catch(function (e) { toast(e.message, 6000); })
    .then(function () { if (btn) { btn.disabled = false; btn.classList.remove('wait'); } });
}

/* ---------- 动作 ---------- */
function ttsBody(same) {
  var f = ttsForm();
  if (ttsCloud()) return { engine: 'cloud', voice: ttsCVoice(), tone: f.tone, text: f.text, rate: f.rate, pitch: f.pitch, volume: f.volume, lang: f.blang };
  return { mode: f.mode, speaker: f.speaker, tone: f.tone, lang: f.lang, text: f.text, desc: f.desc, seed: f.mode === 'design' ? f.seed : null, name: f.name, same: !!same };
}
function ttsGo(same) {
  var f = ttsForm();
  if (TTS.st.demo) { toast('演示模式：连上后端才能生成配音'); return; }
  if (!same && !(f.text || '').trim()) { toast('先把文案贴进来'); $('#ttsText').focus(); return; }
  if (!ttsCloud() && f.mode === 'design' && !(f.desc || '').trim()) { toast('先写一段音色描述'); $('#ttsDesc').focus(); return; }
  api('POST', '/api/tts/gen', ttsBody(same)).then(function (j) { TTS.st.job = j.job; ttsSync(); }).catch(function (e) { toast(e.message, 4500); });
}
function ttsMineSet(list) { if (TTS.st && TTS.st.cloud) { TTS.st.cloud.mine = list; TTS.st.cloud.count = list.length; } ttsVoice(); }
function ttsInsertTag(tag) {
  var t = $('#ttsText'), f = ttsForm(); if (!t) return;
  var a = t.selectionStart == null ? t.value.length : t.selectionStart, b = t.selectionEnd == null ? a : t.selectionEnd, ins = '[' + tag + ']';
  t.value = t.value.slice(0, a) + ins + t.value.slice(b); f.text = t.value; ttsKeep(); ttsCount();
  t.focus(); t.setSelectionRange(a + ins.length, a + ins.length);
}
function ttsDesign(btn) {
  var f = ttsForm();
  if (!useLive()) { toast('演示模式：连上后端才能设计音色'); return; }
  if (!(f.dprompt || '').trim()) { toast('先写一段声音描述'); $('#bdPrompt').focus(); return; }
  btn.disabled = true; btn.textContent = '百炼在设计…';
  api('POST', '/api/tts/cloud/design', { name: f.dname, prompt: f.dprompt, text: f.dtext, lang: f.dlang }, 150000).then(function (j) {
    var mine = (ttsCS().mine || []).concat([j.voice]); ttsMineSet(mine); toast(j.msg, 5000);
    ttsTry(j.voice.id, null);
  }).catch(function (e) { toast(e.message, 6000); btn.disabled = false; btn.textContent = '设计一个音色'; });
}
function ttsClone(btn) {
  var f = ttsForm(), ok = $('#bcOk');
  if (!useLive()) { toast('演示模式：连上后端才能复刻'); return; }
  if (!ok || !ok.checked) { toast('先勾选：这段声音是你自己的，或者是 AI 生成的'); if (ok) ok.focus(); return; }
  var src = f.csrc === 'draft' ? 'draft' : 'upload';
  if (src === 'upload' && !TTS.clone) { toast('先选一段录音'); return; }
  btn.disabled = true; btn.textContent = '正在传给百炼…';
  api('POST', '/api/tts/cloud/clone', { source: src, data: src === 'upload' ? TTS.clone.data : '', file: src === 'upload' ? TTS.clone.name : '', name: f.cname, lang: f.clang, denoise: !!f.cden, consent: true }, 200000)
    .then(function (j) { TTS.clone = null; ttsMineSet((ttsCS().mine || []).concat([j.voice])); toast(j.msg, 5000); })
    .catch(function (e) { toast(e.message, 6000); btn.disabled = false; btn.textContent = '复刻这个声音'; });
}
function ttsDictCollect() {
  var d = ttsDictInit(), o = { pronunciation: {}, replace: {} };
  d.p.forEach(function (r) { if (r.w.trim() && r.t.trim()) o.pronunciation[r.w.trim()] = r.t.trim(); });
  d.r.forEach(function (r) { if (r.w.trim() && r.t.trim()) o.replace[r.w.trim()] = r.t.trim(); });
  return o;
}
$('#view-tts').addEventListener('click', function (ev) {
  var t = ev.target.closest('button'); if (!t || t.disabled) return;
  var f = ttsForm(), live = useLive();
  if (t.dataset.mode) { f.mode = t.dataset.mode; ttsKeep(); ttsVoice(); ttsSync(); return; }
  if (t.dataset.tab) { f.ctab = t.dataset.tab; ttsKeep(); ttsVoice(); return; }
  if (t.dataset.eng) {
    if (!TTS.st || TTS.st.engine === t.dataset.eng) return;
    if (TTS.st.job && TTS.st.job.st === 'run') { toast('正在生成，等它好了或者先点「停下」再换'); return; }
    var sw = $('#ttsEng'); if (sw) sw.dataset.on = t.dataset.eng;      // 先让滑块滑过去，再换整页
    TTS.st.engine = TTS.eng = t.dataset.eng; setVal('ttsEngine', t.dataset.eng);
    setTimeout(function () { if (S.view === 'tts') renderTTS(); }, 160);
    toast(t.dataset.eng === 'cloud' ? '换成云端：百炼，不用显卡，按字计费' : '换成本地 Qwen3-TTS：在这台电脑上生成，不联网'); return;
  }
  if (t.dataset.way) {
    var on = t.dataset.way === '1'; if (TTS.st) TTS.st.whole = on; setVal('ttsWhole', on); ttsSync();
    toast(on ? '整段一次生成：语气前后连贯，念完才出声音' : '一句一句生成：进度准，但每句语气可能不一样'); return;
  }
  if (t.dataset.spk) { f.speaker = t.dataset.spk; ttsKeep(); $$('#ttsVoice [data-spk]').forEach(function (b) { b.setAttribute('aria-pressed', b === t); }); return; }
  if (t.dataset.cv) { f.cvoice = t.dataset.cv; ttsKeep(); $$('#ttsVoice [data-cv]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.cv === t.dataset.cv); }); var u = $('.tts-using b'); if (u) u.textContent = ttsCVName(); return; }
  if (t.dataset.cvtry) { ttsTry(t.dataset.cvtry, t); return; }
  if (t.dataset.tag) { ttsInsertTag(t.dataset.tag); return; }
  if (t.dataset.hint) { var p = $('#bdPrompt'), w = t.dataset.hint; f.dprompt = (f.dprompt || '').replace(/[，,。\s]+$/, ''); f.dprompt += (f.dprompt ? '，' : '') + w; if (p) { p.value = f.dprompt; p.focus(); } ttsKeep(); return; }
  if (t.dataset.dlang) { f.dlang = t.dataset.dlang; ttsKeep(); $$('#bdLang button').forEach(function (b) { b.setAttribute('aria-pressed', b === t); }); return; }
  if (t.dataset.csrc) { f.csrc = t.dataset.csrc; ttsKeep(); ttsVoice(); return; }
  if (t.id === 'bcDen') { f.cden = !f.cden; ttsKeep(); t.setAttribute('aria-checked', f.cden); return; }
  if (t.dataset.bdel) {
    var id = t.dataset.bdel;
    if (TTS.armDel !== id) { TTS.armDel = id; ttsVoice(); setTimeout(function () { if (TTS.armDel === id) { TTS.armDel = ''; ttsVoice(); } }, 3500); return; }
    TTS.armDel = '';
    if (!live) { toast('演示模式：连上后端才能删'); return; }
    api('DELETE', '/api/tts/cloud/voices/' + encodeURIComponent(id), undefined, 30000).then(function (j) { ttsMineSet(j.mine); toast(j.msg); }).catch(function (e) { toast(e.message, 5000); });
    return;
  }
  if (t.dataset.dictadd) { ttsDictInit()[t.dataset.dictadd].push({ w: '', t: '' }); ttsVoice(); var ins = $$('#ttsVoice [data-dk="' + t.dataset.dictadd + '"][data-df="w"]'); if (ins.length) ins[ins.length - 1].focus(); return; }
  if (t.dataset.dictdel) { var kk = t.dataset.dictdel.split(':'); ttsDictInit()[kk[0]].splice(+kk[1], 1); ttsVoice(); return; }
  if (t.dataset.voice) {
    var v = (TTS.st.voices || []).filter(function (x) { return String(x.id) === t.dataset.voice; })[0]; if (!v) return;
    f.desc = v.desc; f.seed = v.seed; f.name = v.name; if (v.lang) f.lang = v.lang; ttsKeep(); ttsVoice(); ttsExpr(); toast('用「' + v.name + '」'); return;
  }
  if (t.dataset.delvoice) {
    if (!live) { toast('演示模式：连上后端才能删'); return; }
    api('DELETE', '/api/tts/voices/' + t.dataset.delvoice).then(function (j) { TTS.st.voices = j.voices; ttsVoice(); toast('删掉了'); }).catch(function (e) { toast(e.message); });
    return;
  }
  if (t.dataset.t !== undefined) { ttsSeek(+t.dataset.t, true); return; }
  var act = t.dataset.act; if (!act) return;
  if (act === 'gen') ttsGo(false);
  else if (act === 'same') ttsGo(true);
  else if (act === 'play') { var a = $('#ttsAudio'); if (a) { if (a.paused) { if (TTS.tryAu) TTS.tryAu.pause(); a.play().catch(function () {}); } else a.pause(); } }
  else if (act === 'goinst') { S.sec = 'models'; renderSettings(); goView('settings'); }
  else if (act === 'gokey') { S.sec = 'cloud'; renderSettings(); goView('settings'); }
  else if (act === 'reseed') { f.seed = ttsSeed(); ttsKeep(); $('#ttsSeed').value = f.seed; $$('#ttsVoice [data-voice]').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); }); }
  else if (act === 'savevoice') {
    if (!f.name.trim() || !f.desc.trim()) { toast('起个名字、写好描述再存'); return; }
    if (!live) { toast('演示模式：连上后端才能存'); return; }
    api('POST', '/api/tts/voices', { name: f.name, desc: f.desc, seed: f.seed, lang: f.lang }).then(function (j) { TTS.st.voices = j.voices; ttsVoice(); toast(j.msg); }).catch(function (e) { toast(e.message); });
  }
  else if (act === 'design') ttsDesign(t);
  else if (act === 'clone') ttsClone(t);
  else if (!live) toast('演示模式：连上后端才能用');
  else if (act === 'sync') { t.disabled = true; api('POST', '/api/tts/cloud/sync', {}, 60000).then(function (j) { toast(j.msg, 5000); return ttsLoad(); }).then(function () { ttsVoice(); }).catch(function (e) { toast(e.message, 5000); t.disabled = false; }); }
  else if (act === 'dictsave') api('PUT', '/api/tts/cloud/hotfix', ttsDictCollect()).then(function (j) { if (TTS.st.cloud) TTS.st.cloud.hotfix = j.hotfix; TTS.dict = null; ttsVoice(); toast(j.msg); }).catch(function (e) { toast(e.message, 6000); });
  else if (act === 'stop') api('POST', '/api/tts/stop', {}).then(function (j) { TTS.st.job = j.job; ttsSync(); });
  else if (act === 'off') api('POST', '/api/tts/off', {}).then(function () { toast('配音服务关了，显存还回去了'); return ttsLoad(); }).then(ttsSync).catch(function (e) { toast(e.message); });
  else if (act === 'realign') {
    t.disabled = true; t.textContent = '对齐中…';
    api('POST', '/api/tts/realign', {}, 300000).then(function (j) { toast(j.msg, 6000); return ttsLoad(); }).then(ttsSync)
      .catch(function (e) { toast(e.message, 6000); t.disabled = false; t.textContent = '重新对齐'; });
  }
  else if (act === 'save') api('POST', '/api/tts/save', {}).then(function (j) { toast(j.msg, 4500); return ttsLoad(); }).then(ttsSync).catch(function (e) { toast(e.message); });
  else if (act === 'open' || act === 'openlast') api('POST', '/api/tts/open', { last: act === 'openlast' }).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); });
});
$('#view-tts').addEventListener('input', function (ev) {
  var t = ev.target, f = ttsForm();
  var map = { ttsText: 'text', ttsTone: 'tone', ttsDesc: 'desc', ttsName: 'name', ttsSeed: 'seed', ttsLang: 'lang', ttsBLang: 'blang', bdPrompt: 'dprompt', bdName: 'dname', bdText: 'dtext', bcName: 'cname', bcLang: 'clang' };
  if (map[t.id]) {
    f[map[t.id]] = t.id === 'ttsSeed' ? (parseInt(t.value, 10) || 1) : t.value; ttsKeep();
    if (t.id === 'ttsText') ttsCount();
    if (t.id === 'ttsDesc' || t.id === 'ttsSeed') $$('#ttsVoice [data-voice]').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
  } else if (t.dataset.knob) {
    var k = t.dataset.knob, v = +t.value, o = $('#o' + t.id);
    f[k] = v; ttsKeep();
    if (o) { o.textContent = k === 'volume' ? String(v) : '×' + v.toFixed(2).replace(/0$/, ''); o.classList.toggle('mod', v !== +t.dataset.def); }
  } else if (t.dataset.dk) { ttsDictInit()[t.dataset.dk][+t.dataset.di][t.dataset.df] = t.value; }
});
$('#view-tts').addEventListener('dblclick', function (ev) {
  var t = ev.target; if (!t.dataset || !t.dataset.knob) return;
  t.value = t.dataset.def; t.dispatchEvent(new Event('input', { bubbles: true }));
});
$('#view-tts').addEventListener('change', function (ev) {
  var t = ev.target;
  if (t.id === 'ttsGap' || t.id === 'ttsPara') {
    var v = Math.max(0, Math.min(t.id === 'ttsGap' ? 3 : 5, parseFloat(t.value) || 0)); t.value = v;
    setVal(t.id === 'ttsGap' ? 'ttsGap' : 'ttsParaGap', v);
    if (TTS.st) TTS.st[t.id === 'ttsGap' ? 'gap' : 'para'] = v;
    toast(t.id === 'ttsGap' ? '句子之间停 ' + v + ' 秒（下次生成起作用）' : '换段停 ' + v + ' 秒（下次生成起作用）');
  } else if (t.id === 'bcFile') ttsCloneFile(t.files && t.files[0]);
  else if (t.id === 'bcOk') { var b = $('[data-act="clone"]'); if (b && t.checked && (ttsForm().csrc !== 'draft' ? TTS.clone : TTS.st.draft)) b.disabled = false; }
});
/* 把录音拖到复刻的框里 */
['dragover', 'dragleave', 'drop'].forEach(function (k) {
  $('#view-tts').addEventListener(k, function (ev) {
    var z = ev.target.closest && ev.target.closest('#bcDrop'); if (!z) return;
    ev.preventDefault();
    z.classList.toggle('over', k === 'dragover');
    if (k === 'drop') ttsCloneFile(ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0]);
  });
});
/* 波形：点哪听哪，鼠标移上去亮那一句 */
$('#view-tts').addEventListener('pointerdown', function (ev) {
  if (!ev.target.closest || !ev.target.closest('#ttsStage')) return;
  var t = ttsStageAt(ev); if (t != null) ttsSeek(t, true);
});
$('#view-tts').addEventListener('pointermove', function (ev) {
  if (!ev.target.closest || !ev.target.closest('#ttsStage')) { if (TTS.hover !== -1) { TTS.hover = -1; ttsDraw(); } return; }
  var t = ttsStageAt(ev), d = TTS.st && TTS.st.draft, i = -1;
  if (t != null && d) d.segments.forEach(function (g, k) { if (t >= g.start - 0.05) i = k; });
  if (i !== TTS.hover) { TTS.hover = i; ttsDraw(); var st = $('#ttsStage'), g = d && d.segments[i]; if (st) st.title = g ? ttsTime(g.start, true) + '  ' + g.text : ''; }
});
document.addEventListener('keydown', function (ev) {
  if (S.view !== 'tts' || ev.key !== ' ' || ev.ctrlKey || ev.altKey || ev.metaKey) return;
  var tag = (ev.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'button' || document.documentElement.dataset.mode === 'resident') return;
  var a = $('#ttsAudio'); if (!a) return;
  ev.preventDefault(); if (a.paused) a.play().catch(function () {}); else a.pause();
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
  var all = s.env && m.custom && m.design && s.align, some = s.env || m.custom || m.design || z.custom || z.design;
  var st = run ? ['warn', '正在安装'] : all ? ['ok', '装好了'] : some ? ['warn', '没装全'] : ['off', '还没装'];
  var row = function (ok, name, extra) { return '<li class="' + (ok ? 'ok' : '') + '"><i></i><span>' + name + '</span><em>' + extra + '</em></li>'; };   // 一行三项，横着排
  var mod = function (k, name) { var ok = k === 'align' ? s.align : m[k], g = (z[k] || 0) >= 1e6 ? ' · ' + ttsGB(z[k]) : ''; return row(ok, name, ok ? '已下' + g : g ? '下了一半' + g : '没下'); };
  var h = '<div class="balbox ttsinst"><div class="ttsi-main"><span class="label">配音 · Qwen3-TTS 1.7B（左边「配音」页用）</span><div class="hwc-st st-' + st[0] + '"><i></i><b>' + st[1] + '</b></div>' +
    '<ul class="ttsi-list">' + row(s.env, '配音环境', s.env ? '已装' : '没装') + mod('custom', '预设音色模型', '') + mod('design', '描述音色模型') + mod('align', '时间轴对齐模型') + '</ul>';
  if (run) {
    var pct = i.pct == null ? null : Math.round(i.pct);
    h += '<div class="prog' + (pct == null ? ' busy' : '') + '"><div class="prog-h"><span>' + esc(i.phase || '准备中') + '</span><b>' + (pct == null ? '' : pct + '%') + '</b></div>' +
      '<div class="prog-bar"><i style="transform:scaleX(' + (pct == null ? 1 : pct / 100) + ')"></i></div>' +
      '<div class="prog-f">' + (i.speed ? (i.speed / 1e6).toFixed(1) + ' MB/s' : '') + (i.eta ? ' · 还要约 ' + ttsDur(i.eta) : '') + (i.line ? ' · ' + esc(i.line.slice(0, 60)) : '') + '</div></div>';
  } else if (i.st === 'fail') h += '<div class="tts-msg bad">上次没装完（退出码 ' + esc(i.code) + '）。再点一次会接着装；魔搭下不动就点「改从 hf-mirror 下」。原始输出：' + esc(i.log || '') + '</div>';
  else if (i.st === 'stop') h += '<div class="tts-msg">上次停下了，再点一次接着装。</div>';
  else if (i.st === 'ok') h += '<div class="tts-msg ok">装好了，左边点「配音」就能用。</div>';
  h += '<div class="help">约 16 GB：配音环境 5 GB + 两个配音模型各 4~5 GB + 时间轴对齐模型 1.8 GB（魔搭；云端配音也用它对时间轴）。装过的跳过、断了接着下，关掉界面也接着装，每一步在 后台 › 进展报告。备用：双击「安装配音.bat」。</div></div>' +
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
