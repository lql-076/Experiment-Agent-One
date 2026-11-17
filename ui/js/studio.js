'use strict';
/* ================= 视频工坊（v3.7，工具窗口 ?tool=studio）=================
   ComfyUI 风格节点工作流：
     ① 剧本与策划 → ② 分镜生图 → ③ 角色配音 → ④ 背景配乐 → ⑤ 视频合成 → ⑥ 成片预览与发布
   - 画布可拖空白平移、滚轮缩放、节点可拖；「居中复位」回到默认布局。画布/节点内部滚，不撑破外层窗口。
   - 每个节点右上角有状态灯、进度、当前动作和「▶ 只跑本节点」。
   - 顶部总控：从头跑通全流程、停下、新建/切换历史项目；下面一条实时硬件状态条（/api/hw，2 秒，窗口隐藏暂停）。
   - 固定风格：知识科普 × 科技数码 × 搞笑段子；白页/紫苏双角色逐句配音。
   操作偏好（画幅、生图模型、音色、字幕、配乐音量、画布布局）存 uiState 的 U.studio / U.studioCanvas。 */
var ST_STYLE = '知识科普 × 科技数码 × 搞笑段子';
var ST_ROLES = ['白页', '紫苏', '旁白'];
var ST_W = 1200, ST_H = 760;
var ST_LAYOUT = {
  1: { x: 20, y: 20, w: 330, h: 330 },
  2: { x: 390, y: 20, w: 360, h: 350 },
  3: { x: 780, y: 20, w: 390, h: 380 },
  4: { x: 780, y: 420, w: 390, h: 320 },
  5: { x: 390, y: 440, w: 360, h: 300 },
  6: { x: 20, y: 420, w: 330, h: 320 }
};
var STUDIO = {
  st: null, t: null, hwT: null, hwBusy: false, pid: '', busy: false, editing: false, dragging: false, topic: (U.studioTopic || ''),
  sig: {}, saveT: null, metaT: null, saving: null, audio: null, fitted: false,
  pref: { ratio: '9:16', seconds: 75, voice: 'local:preset:Vivian', imgModel: '', bgmVol: 0.18, subtitle: true, bgmSteps: 8 },
  canvas: { x: 0, y: 0, s: 1, auto: true, nodes: null }
};
try {
  if (U.studio && typeof U.studio === 'object') Object.assign(STUDIO.pref, U.studio);
  if (U.studioCanvas && typeof U.studioCanvas === 'object') {
    STUDIO.canvas.x = +U.studioCanvas.x || 0; STUDIO.canvas.y = +U.studioCanvas.y || 0;
    STUDIO.canvas.s = Math.max(.4, Math.min(2, +U.studioCanvas.s || 1));
    STUDIO.canvas.nodes = U.studioCanvas.nodes && typeof U.studioCanvas.nodes === 'object' ? U.studioCanvas.nodes : null;
    STUDIO.canvas.auto = false;
  }
} catch (e) {}
STUDIO.nodes = stNodes();

function stNodes() {
  var out = {};
  for (var k in ST_LAYOUT) out[k] = Object.assign({}, ST_LAYOUT[k]);
  var saved = STUDIO.canvas.nodes;
  if (saved) for (var n in saved) if (out[n] && saved[n]) {
    var q = saved[n];
    out[n].x = Math.max(-200, Math.min(1400, +q.x || out[n].x));
    out[n].y = Math.max(-200, Math.min(1200, +q.y || out[n].y));
  }
  return out;
}
function studioSt() { return useLive() ? STUDIO.st : stDemo(); }
function studioProj() { var s = studioSt(); return s && s.project; }
function studioJob() { var s = studioSt(); return s && s.job; }
function studioRunning() { var j = studioJob(); return !!(j && j.st === 'run'); }
function stClock(s) { s = Math.max(0, Math.round(+s || 0)); return Math.floor(s / 60) + ':' + pad(s % 60); }
function stSize(b) { return b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' KB'; }
function stPut(id, html) { if (STUDIO.sig[id] === html) return; var el = $('#' + id); if (!el) return; STUDIO.sig[id] = html; el.innerHTML = html; }
function stSet(id, v) { var e = $('#' + id); if (e && e.textContent !== v) e.textContent = v; }

/* ---------- 演示数据 ---------- */
function stDemo() {
  var shots = [1, 2, 3, 4].map(function (i) {
    var roles = ['白页', '紫苏', '白页', '紫苏'];
    return { id: 's' + i, n: i, role: roles[i - 1], tone: i % 2 ? '冷静吐槽' : '夸张惊呼',
      text: ['先说一个反常识的结论。', '等等，这也太离谱了吧？', '原理其实很简单。', '所以结论是——下期暗号：白页紫苏。'][i - 1],
      speaker: i % 2 ? 'local:preset:Vivian' : 'local:preset:Serena',
      image_prompt: ['暖光书桌前的年轻人，竖屏中景', '屏幕上出现对比图表，冷色调', '一只手在手机上点按钮，特写', '两个人对着镜头笑，暖色'][i - 1],
      seconds_hint: 6, duration: 5.8, start: (i - 1) * 6, end: i * 6 - 0.2,
      image_ok: false, tts_ok: false, image_st: 'idle', tts_st: 'idle', image_url: '', tts_url: '' };
  });
  return { projects: [{ id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', created: '2026-11-18 02:00:00', ratio: '9:16', st: 'idle', shots: 4, video: false }], active: 'demo',
    project: { id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', desc: '这一期讲讲普通人马上能用的三个 AI 用法。', tags: ['AI', '效率工具'],
      created: '2026-11-18 02:00:00', ratio: '9:16', style_tag: ST_STYLE, target_seconds: 75, topic: '',
      bgm_prompt: 'upbeat electronic, no vocals', img_model: 'gpt-image-2.5-sunburst-vip',
      settings: { subtitle: true, bgm_volume: 0.18, kenburns: true, bgm_seconds: 0, bgm_steps: 8,
        voice: { label: 'Vivian', id: 'local:preset:Vivian' }, role_voices: { 白页: 'local:preset:Vivian', 紫苏: 'local:preset:Serena', 旁白: 'local:preset:Uncle_Fu' } },
      steps: { plan: { st: 'ok', msg: '4 个分镜' }, images: { st: 'idle', msg: '' }, tts: { st: 'idle', msg: '' }, bgm: { st: 'idle', msg: '' }, video: { st: 'idle', msg: '' } },
      files: {}, shots: shots, total_seconds: 23.5, duration: 0, resolution: '', st: 'idle', error: '', cost: {}, dir: 'F:\\Agent\\工作区\\视频工坊\\演示项目', video_ok: false },
    job: null, voices: [{ id: 'local:preset:Vivian', label: 'Vivian · 女声 · 明亮', engine: 'local' }, { id: 'local:preset:Serena', label: 'Serena · 女声 · 温柔', engine: 'local' },
      { id: 'local:preset:Uncle_Fu', label: 'Uncle_Fu · 男声 · 低沉', engine: 'local' }],
    models: [{ id: 'gpt-image-2.5-sunburst-vip', name: 'GPT Image 2.5 Sunburst VIP', vendor: 'OpenAI' }, { id: 'gemini-3.1-flash-image', name: 'Nano Banana 2', vendor: 'Google' }],
    style_tag: ST_STYLE, roles: ST_ROLES, ratios: [{ id: '9:16', label: '竖屏 9:16' }, { id: '16:9', label: '横屏 16:9' }] };
}

/* ---------- 外壳 ---------- */
function studioShell() {
  return '<div class="st"><div class="st-top" id="stTop"></div><div class="st-hw" id="stHw">' +
    '<span class="st-hw-g"><i>CPU</i><b id="stHwCpu">—</b><em>% · <span id="stHwCpuF">—</span> GHz</em><u><s id="stHwCpuBar"></s></u></span>' +
    '<span class="st-hw-g"><i>内存</i><b id="stHwRam">—</b><em>/ <span id="stHwRamT">—</span> GB · <span id="stHwRamP">—</span>%</em><u><s id="stHwRamBar"></s></u></span>' +
    '<span class="st-hw-g"><i>GPU</i><b id="stHwGpu">—</b><em>% · <span id="stHwTemp">—</span>°C</em><u><s id="stHwGpuBar"></s></u></span>' +
    '<span class="st-hw-g"><i>显存</i><b id="stHwVram">—</b><em>/ <span id="stHwVramT">—</span> GB · <span id="stHwVramP">—</span>%</em><u><s id="stHwVramBar"></s></u></span>' +
    '<span class="st-hw-src" id="stHwSrc">2 秒刷新</span></div>' +
    '<div class="st-canvas" id="stCanvas"><div class="st-world" id="stWorld"></div>' +
    '<div class="st-canvas-tip">拖动空白平移 · 滚轮缩放 · 拖动节点标题移动</div></div></div>';
}
function renderStudio(force) {
  var v = $('#view-studio'); if (!v) return;
  if (!v.querySelector('.st')) { v.innerHTML = studioShell(); STUDIO.sig = {}; bindCanvas(); }
  if ((STUDIO.editing || STUDIO.dragging) && !force) { syncNodeMeta(); return; }
  renderStTop();
  renderStCanvas();
  syncNodeMeta();
  if (!STUDIO.fitted && STUDIO.canvas.auto) { STUDIO.fitted = true; fitCanvas(); }
}

/* ---------- 顶部总控 ---------- */
function renderStTop() {
  var s = studioSt() || {}, ps = (studioSt() && studioSt().projects) || [], p = s.project, run = studioRunning();
  var sel = '<select class="inp st-projsel" id="stProj" aria-label="切换项目">' + (ps.length ? ps.map(function (x) {
    return '<option value="' + esc(x.id) + '"' + (p && x.id === p.id ? ' selected' : '') + '>' + esc(x.title || x.name) + ' · ' + esc((x.created || '').slice(5, 16)) + '</option>';
  }).join('') : '<option value="">还没有项目</option>') + '</select>';
  var html = '<div class="st-brand"><b>视频工坊</b><span class="st-style">' + esc(ST_STYLE) + '</span></div>' +
    '<div class="st-proj"><label for="stProj">项目</label>' + sel + '<button class="btn mini ghost" data-st="new">新建</button></div>' +
    '<div class="st-acts"><button class="btn mini ghost" data-st="reset">居中复位</button>' +
    '<button class="btn primary st-runall" data-st="run"' + (run ? ' disabled' : '') + '>▶ 从头跑通全流程</button>' +
    '<button class="btn mini danger" data-st="stop"' + (run ? '' : ' disabled') + '>■ 停下</button></div>';
  stPut('stTop', html);
}

/* ---------- 硬件状态条 ---------- */
function stHWBar(id, v, max) { var e = $('#' + id); if (e) e.style.width = Math.max(0, Math.min(100, (+v || 0) / (max || 100) * 100)).toFixed(1) + '%'; }
function renderStHW(h) {
  h = h || (window.HW || {});
  var cpu = h.cpu || {}, gpu = h.gpu || {}, ram = h.ram || {};
  stSet('stHwCpu', (cpu.load == null ? '—' : (+cpu.load).toFixed(0)));
  stSet('stHwCpuF', (cpu.clock == null ? '—' : (+cpu.clock).toFixed(2)));
  stSet('stHwRam', (ram.used == null ? '—' : (+ram.used).toFixed(1)));
  stSet('stHwRamT', (ram.total == null ? '—' : (+ram.total).toFixed(0)));
  stSet('stHwRamP', (ram.load == null ? '—' : (+ram.load).toFixed(0)));
  stSet('stHwGpu', (gpu.load == null ? '—' : (+gpu.load).toFixed(0)));
  stSet('stHwTemp', (gpu.temp == null || !gpu.temp ? '—' : (+gpu.temp).toFixed(0)));
  stSet('stHwVram', (gpu.vram == null ? '—' : (+gpu.vram).toFixed(1)));
  stSet('stHwVramT', (gpu.vramTotal == null ? '—' : (+gpu.vramTotal).toFixed(0)));
  stSet('stHwVramP', (gpu.vramPct == null ? '—' : (+gpu.vramPct).toFixed(0)));
  stHWBar('stHwCpuBar', cpu.load, 100); stHWBar('stHwRamBar', ram.load, 100);
  stHWBar('stHwGpuBar', gpu.load, 100); stHWBar('stHwVramBar', gpu.vramPct, 100);
  stSet('stHwSrc', useLive() ? '2 秒刷新' : '演示数据');
}
function stHWTick() {
  if (document.visibilityState === 'hidden' || STUDIO.hwBusy) return;
  if (!useLive()) { renderStHW(window.HW); return; }
  STUDIO.hwBusy = true;
  api('GET', '/api/hw', null, 6000).then(renderStHW).catch(function () { renderStHW({}); })
    .then(function () { STUDIO.hwBusy = false; });
}
function stHWStart() {
  stHWStop();
  if (document.visibilityState === 'hidden') return;
  stHWTick(); STUDIO.hwT = setInterval(stHWTick, 2000);
}
function stHWStop() { if (STUDIO.hwT) clearInterval(STUDIO.hwT); STUDIO.hwT = null; }
document.addEventListener('visibilitychange', function () {
  if (!STUDIO.hwT && S.view === 'studio' && !document.hidden) stHWStart();
  else if (STUDIO.hwT && document.hidden) stHWStop();
});

/* ---------- 节点骨架 ---------- */
function nodeHeader(n, title) {
  return '<header class="st-node-h" data-drag="' + n + '"><span class="st-node-n">' + n + '</span><b>' + esc(title) + '</b>' +
    '<span class="st-lamp" data-lamp="' + n + '"></span><button class="st-nrun" data-nrun="' + n + '" title="只跑这个节点">▶ 只跑本节点</button></header>';
}
function nodeFooter(n) {
  return '<footer class="st-node-f"><i class="st-pbar"><b data-pbar="' + n + '"></b></i><span data-pmsg="' + n + '">待命</span></footer>';
}
function nodeWrap(n, title, body, cls) {
  var q = STUDIO.nodes[n];
  return '<section class="hud st-node ' + (cls || '') + '" data-node="' + n + '" style="left:' + q.x + 'px;top:' + q.y + 'px;width:' + q.w + 'px;height:' + q.h + 'px">' +
    nodeHeader(n, title) + '<div class="st-node-body" id="stNode' + n + '">' + body + '</div>' + nodeFooter(n) + '</section>';
}

/* ---------- 节点 1：剧本与策划 ---------- */
function node1HTML(p) {
  var topic = STUDIO.topic || '';
  if (!topic && p && p.topic) topic = '';
  var body = '<textarea class="inp st-topic" id="stTopic" rows="3" spellcheck="false" placeholder="写主题，或者把完整口播文案贴进来；也可以从 Gemini 策划包导入">' + esc(topic) + '</textarea>' +
    '<div class="st-row"><input class="inp" id="stTitle" maxlength="30" placeholder="发布标题" value="' + esc((p && p.title) || '') + '"><input class="inp" id="stTags" placeholder="话题 空格隔开" value="' + esc(((p && p.tags) || []).join(' ')) + '"></div>' +
    '<div class="st-row2"><button class="btn mini" data-act="export">导出 Gemini 策划包</button><button class="btn mini ghost" data-act="importToggle">导入剧本</button></div>' +
    '<div class="st-import" id="stImportBox" hidden><textarea class="inp" id="stImport" rows="3" spellcheck="false" placeholder="把 Gemini 输出的 Markdown / JSON 贴在这里"></textarea>' +
    '<div class="st-row"><label class="btn mini ghost st-file">选文件<input type="file" id="stImportFile" accept=".md,.markdown,.txt,.json" hidden></label><button class="btn mini primary" data-act="import">导入这段</button></div></div>' +
    '<button class="btn primary st-wide" data-act="plan">DeepSeek 一键拆解</button>' +
    '<details class="st-details"><summary>简介 / 发布描述</summary><textarea class="inp" id="stDesc" rows="2" spellcheck="false">' + esc((p && p.desc) || '') + '</textarea></details>' +
    '<div class="st-hint">固定风格：' + esc(ST_STYLE) + '。导出策划包给 Gemini 写剧本，回来直接导入。</div>';
  return nodeWrap(1, '剧本与策划', body, 'st-n1');
}

/* ---------- 节点 2：分镜生图 ---------- */
function stVoiceOptions(cur) {
  var vs = (studioSt() && studioSt().voices) || [], groups = {};
  vs.forEach(function (v) { var g = v.engine === 'cloud' ? '百炼云端' : '本地'; (groups[g] = groups[g] || []).push(v); });
  var out = [], found = vs.some(function (v) { return v.id === cur; });
  if (cur && !found) out.push('<option value="' + esc(cur) + '" selected>' + esc(cur) + '</option>');
  Object.keys(groups).forEach(function (g) {
    out.push('<optgroup label="' + esc(g) + '">' + groups[g].map(function (v) {
      return '<option value="' + esc(v.id) + '"' + (v.id === cur ? ' selected' : '') + '>' + esc(v.label) + '</option>';
    }).join('') + '</optgroup>');
  });
  return out.join('') || '<option value="">还没有音色</option>';
}
function stModelOptions(cur) {
  var ms = (studioSt() && studioSt().models) || [], out = [];
  if (cur && !ms.some(function (m) { return m.id === cur; })) out.push('<option value="' + esc(cur) + '" selected>' + esc(cur) + '</option>');
  ms.forEach(function (m) {
    var price = m.price == null ? '' : ' · $' + (+m.price).toFixed(3) + '/张';
    out.push('<option value="' + esc(m.id) + '"' + (m.id === cur ? ' selected' : '') + '>' + esc((m.vendor ? m.vendor + ' · ' : '') + m.name + price) + '</option>');
  });
  return out.join('') || '<option value="">用设置里的默认模型</option>';
}
function stRoleOptions(cur) {
  var rs = ST_ROLES.slice(); if (cur && rs.indexOf(cur) < 0) rs.push(cur);
  return rs.map(function (r) { return '<option' + (r === cur ? ' selected' : '') + '>' + esc(r) + '</option>'; }).join('');
}
function node2HTML(p) {
  var mid = (p && p.img_model) || STUDIO.pref.imgModel || (studioSt() && studioSt().default_model) || '';
  var body = '<div class="st-row"><label class="st-lab">模型</label><select class="inp" id="stImgModel">' + stModelOptions(mid) + '</select></div>' +
    '<div class="st-row"><div class="seg st-seg" role="group" aria-label="画幅"><button data-st-ratio="9:16" aria-pressed="' + ((p && p.ratio) !== '16:9') + '">9:16</button><button data-st-ratio="16:9" aria-pressed="' + ((p && p.ratio) === '16:9') + '">16:9</button></div>' +
    '<button class="btn mini" data-act="imgs">生成缺的图</button><button class="linkbtn" data-act="imgsAll">全部重出</button></div>';
  var ss = (p && p.shots) || [];
  body += '<div class="st-node-list">' + (ss.length ? ss.map(function (s) {
    var ok = s.image_ok, st = s.image_st === 'run' ? 'run' : ok ? 'ok' : s.image_st === 'err' || s.image_st === 'missing' ? 'bad' : s.image_st === 'stale' ? 'stale' : 'idle';
    return '<div class="st-mini"><span class="st-mini-img">' + (ok ? '<img src="' + esc(s.image_url) + '" alt="" loading="lazy">' : (st === 'run' ? '…' : '待出')) + '</span>' +
      '<span class="st-mini-x"><b>' + pad(s.n) + ' ' + esc(s.role || '') + '</b><em class="st-tag ' + st + '">图 ' + (ok ? '✓' : st === 'run' ? '…' : st === 'bad' ? '×' : st === 'stale' ? '旧' : '—') + '</em></span>' +
      '<button class="linkbtn" data-shot-img="' + esc(s.id) + '">重出</button>' +
      '<input class="inp st-mini-prompt" data-shot-prompt="' + esc(s.id) + '" value="' + esc(s.image_prompt || '') + '" spellcheck="false" placeholder="这一镜的画面提示词"></div>';
  }).join('') : '<div class="st-nohint">先在节点 1 拆解或导入剧本</div>') + '</div>';
  return nodeWrap(2, '分镜生图', body, 'st-n2');
}

/* ---------- 节点 3：角色配音 ---------- */
function node3HTML(p) {
  var rv = (p && p.settings && p.settings.role_voices) || {};
  var body = '<div class="st-rv">' + ST_ROLES.map(function (r) {
    return '<label><span>' + esc(r) + '</span><select class="inp" data-role-voice="' + esc(r) + '">' + stVoiceOptions(rv[r] || '') + '</select></label>';
  }).join('') + '</div>' +
    '<div class="st-row"><button class="btn mini" data-act="tts">全部重配</button><span class="st-hint">逐句可改角色 / 音色 / 语气</span></div>';
  var ss = (p && p.shots) || [];
  body += '<div class="st-node-list">' + (ss.length ? ss.map(function (s) {
    var ok = s.tts_ok, st = s.tts_st === 'run' ? 'run' : ok ? 'ok' : s.tts_st === 'err' || s.tts_st === 'missing' ? 'bad' : s.tts_st === 'stale' ? 'stale' : 'idle';
    return '<div class="st-vrow"><div class="st-vhead"><b>' + pad(s.n) + '</b><select class="st-mini-sel" data-shot-role="' + esc(s.id) + '">' + stRoleOptions(s.role) + '</select>' +
      '<em class="st-tag ' + st + '">音 ' + (ok ? '✓' : st === 'run' ? '…' : st === 'bad' ? '×' : st === 'stale' ? '旧' : '—') + '</em><span class="sp"></span>' +
      '<button class="linkbtn" data-shot-play="' + esc(s.id) + '"' + (ok ? '' : ' disabled') + '>听</button><button class="linkbtn" data-shot-voice="' + esc(s.id) + '">重配</button></div>' +
      '<textarea class="inp st-vtext" data-shot-text="' + esc(s.id) + '" rows="1" spellcheck="false">' + esc(s.text || '') + '</textarea>' +
      '<div class="st-vopts"><select class="st-mini-sel" data-shot-speaker="' + esc(s.id) + '">' + stVoiceOptions(s.speaker || '') + '</select>' +
      '<input class="inp st-vtone" data-shot-tone="' + esc(s.id) + '" value="' + esc(s.tone || '') + '" placeholder="语气：冷静吐槽"></div></div>';
  }).join('') : '<div class="st-nohint">还没有台词</div>') + '</div>';
  return nodeWrap(3, '角色配音', body, 'st-n3');
}

/* ---------- 节点 4：背景配乐 ---------- */
function node4HTML(p) {
  var st = (p && p.settings) || {};
  var sec = +st.bgm_seconds || Math.round((p && (p.files && p.files.voice ? p.total_seconds : p.target_seconds)) || 75);
  var steps = +st.bgm_steps || 8;
  var bgm = p && p.files && p.files.bgm;
  var body = '<textarea class="inp st-bgmp" id="stBgmPrompt" rows="3" spellcheck="false" placeholder="英文描述最好：风格、情绪、乐器、速度；不要人声">' + esc((p && p.bgm_prompt) || '') + '</textarea>' +
    '<div class="st-row"><label class="st-lab">时长</label><input class="inp st-num" id="stBgmSec" type="number" min="10" max="380" value="' + sec + '"><span class="st-hint">秒</span>' +
    '<label class="st-lab">步数</label><input class="inp st-num" id="stBgmSteps" type="number" min="1" max="32" value="' + steps + '"></div>' +
    '<div class="st-row2"><button class="btn mini" data-act="bgm">生成配乐</button><button class="btn mini ghost" data-act="bgmPlay"' + (bgm ? '' : ' disabled') + '>试听</button></div>' +
    '<div class="st-hint">' + (bgm ? '配乐在：' + esc(bgm.name) : 'Stable Audio 3 Medium · 8 步最稳') + '</div>';
  return nodeWrap(4, '背景配乐', body, 'st-n4');
}

/* ---------- 节点 5：视频合成 ---------- */
function node5HTML(p) {
  var st = (p && p.settings) || {}, sub = st.subtitle !== undefined ? !!st.subtitle : !!STUDIO.pref.subtitle;
  var vol = Math.round((st.bgm_volume != null ? +st.bgm_volume : +STUDIO.pref.bgmVol) * 100);
  var body = '<label class="st-check"><input type="checkbox" id="stSub"' + (sub ? ' checked' : '') + '> 烧录硬字幕（白字黑边，避开抖音底部）</label>' +
    '<div class="st-row"><span class="st-lab">画幅</span><div class="seg st-seg"><button data-st-ratio="9:16" aria-pressed="' + ((p && p.ratio) !== '16:9') + '">9:16</button><button data-st-ratio="16:9" aria-pressed="' + ((p && p.ratio) === '16:9') + '">16:9</button></div></div>' +
    '<div class="st-vol"><label class="st-lab" for="stBgmVol">配乐闪避音量 <em id="stBgmVolV">' + vol + '%</em></label><input type="range" id="stBgmVol" min="0" max="60" step="5" value="' + vol + '"></div>' +
    '<button class="btn primary st-wide" data-act="video">合成视频</button>' +
    '<div class="st-hint">有人说话时配乐自动压低，无旁白间隙抬升；结尾 2 秒淡出。</div>';
  return nodeWrap(5, '视频合成', body, 'st-n5');
}

/* ---------- 节点 6：成片预览与发布 ---------- */
function node6HTML(p) {
  var files = (p && p.files) || {}, video = files.video, cover = files.cover;
  var body = '';
  if (p && p.video_ok && video) {
    body += '<video class="st-video" controls preload="metadata" src="' + esc(video.url) + '"></video>' +
      '<div class="st-vinfo"><span>' + esc((p.resolution || '') + (p.duration ? ' · ' + (+p.duration).toFixed(1) + ' 秒' : '')) + '</span><span>' + (video ? stSize(video.size) : '') + '</span></div>';
  } else {
    body += '<div class="st-vempty"><b>成片会在这里</b><span>' + (p && p.shots && p.shots.length ? '素材齐了以后点「合成视频」' : '先拆解或导入剧本') + '</span></div>';
  }
  if (cover) body += '<div class="st-cover"><img src="' + esc(cover.url) + '" alt="封面"><span>封面</span></div>';
  body += '<div class="st-row2"><button class="btn mini primary" data-act="pub"' + (p && p.video_ok && useLive() ? '' : ' disabled') + '>送去抖音发布</button>' +
    '<button class="btn mini ghost" data-act="open">打开输出文件夹</button></div>' +
    '<button class="linkbtn" data-act="gotoPub">去「发布」窗口确认 ›</button>' +
    '<div class="st-hint">只进发布待确认队列，点两下才发。</div>';
  return nodeWrap(6, '成片预览与发布', body, 'st-n6');
}

/* ---------- 画布 ---------- */
function edgePath(a, b) {
  if (b.y >= a.y + a.h * 0.55) {                       // 目标在下方：从上往下
    var cx1 = a.x + a.w / 2, cy1 = a.y + a.h, cx2 = b.x + b.w / 2, cy2 = b.y;
    return 'M' + cx1 + ' ' + cy1 + ' C' + cx1 + ' ' + (cy1 + 50) + ',' + cx2 + ' ' + (cy2 - 50) + ',' + cx2 + ' ' + cy2;
  }
  var x1, y1, x2, y2;
  if (b.x >= a.x + a.w * 0.5) {                        // 同行往右
    x1 = a.x + a.w; y1 = a.y + 34; x2 = b.x; y2 = b.y + 34;
  } else {                                             // 同行往左（蛇形回折）
    x1 = a.x; y1 = a.y + 34; x2 = b.x + b.w; y2 = b.y + 34;
  }
  var dx = Math.max(30, Math.abs(x2 - x1) * .55);
  return 'M' + x1 + ' ' + y1 + ' C' + (x1 + (x2 > x1 ? dx : -dx)) + ' ' + y1 + ',' + (x2 + (x2 > x1 ? -dx : dx)) + ' ' + y2 + ',' + x2 + ' ' + y2;
}
function stNodeStatus(n) {
  var p = studioProj(), j = studioJob();
  if (n === 6) {
    if (j && j.st === 'run' && j.step === 'video') return 'run';
    if (p && p.video_ok) return 'done';
    return 'idle';
  }
  var key = { 1: 'plan', 2: 'images', 3: 'tts', 4: 'bgm', 5: 'video' }[n];
  var s = (p && p.steps && p.steps[key]) || {};
  if (j && j.st === 'run' && j.pid === (p && p.id) && j.step === key) return 'run';
  if (j && j.st === 'run' && j.pid === (p && p.id) && s.st !== 'ok' && s.st !== 'warn') return 'queue';
  if (s.st === 'ok' || s.st === 'warn') return 'done';
  if (s.st === 'err' || s.st === 'stop') return 'bad';
  if (s.st === 'stale') return 'stale';
  return 'idle';
}
function edgeHTML() {
  var out = [];
  for (var i = 1; i < 6; i++) {
    var a = STUDIO.nodes[i], b = STUDIO.nodes[i + 1];
    var sa = stNodeStatus(i), sb = stNodeStatus(i + 1);
    var cls = (sa === 'run' || sb === 'run') ? 'run' : (sa === 'done' || sb === 'done') ? 'on' : '';
    out.push('<path class="st-edge ' + cls + '" d="' + edgePath(a, b) + '"/>');
  }
  return out.join('');
}
function renderStCanvas() {
  var p = studioProj();
  var html = '<svg class="st-edges" id="stEdges" viewBox="0 0 ' + ST_W + ' ' + ST_H + '" preserveAspectRatio="none" aria-hidden="true">' + edgeHTML() + '</svg>' +
    node1HTML(p) + node2HTML(p) + node3HTML(p) + node4HTML(p) + node5HTML(p) + node6HTML(p);
  if (STUDIO.sig.canvas === html) { applyCanvas(); return; }
  STUDIO.sig.canvas = html;
  var w = $('#stWorld'); if (!w) return;
  w.innerHTML = html;
  applyCanvas();
}
function applyCanvas() {
  var w = $('#stWorld'); if (!w) return;
  w.style.width = ST_W + 'px'; w.style.height = ST_H + 'px';
  w.style.transform = 'translate(' + STUDIO.canvas.x + 'px,' + STUDIO.canvas.y + 'px) scale(' + STUDIO.canvas.s + ')';
}
function fitCanvas() {
  var c = $('#stCanvas'); if (!c) return;
  var vw = c.clientWidth, vh = c.clientHeight;
  var s = Math.min((vw - 24) / ST_W, (vh - 24) / ST_H);
  s = Math.max(.45, Math.min(1.5, s));
  STUDIO.canvas.s = s;
  STUDIO.canvas.x = Math.round((vw - ST_W * s) / 2);
  STUDIO.canvas.y = Math.round((vh - ST_H * s) / 2);
  STUDIO.canvas.auto = true;
  applyCanvas(); saveCanvas();
}
function saveCanvas() {
  if (typeof saveUI === 'function') saveUI({ studioCanvas: { x: STUDIO.canvas.x, y: STUDIO.canvas.y, s: STUDIO.canvas.s, nodes: STUDIO.nodes } });
}

function syncNodeMeta() {
  for (var n = 1; n <= 6; n++) {
    var lamp = document.querySelector('[data-lamp="' + n + '"]');
    var st = stNodeStatus(n);
    if (lamp) lamp.className = 'st-lamp st-' + st;
    var p = studioProj(), j = studioJob(), key = { 1: 'plan', 2: 'images', 3: 'tts', 4: 'bgm', 5: 'video', 6: 'video' }[n];
    var step = p && p.steps && p.steps[key];
    var cur = j && j.st === 'run' && j.pid === (p && p.id) && j.step === key;
    var msg = cur ? (j.msg || '运行中…') : (n === 6 ? (p && p.video_ok ? '成片已就绪' : '等成片') : (step && step.msg)) || '待命';
    var pct = cur ? (j.pct || 0) : (n === 6 ? (p && p.video_ok ? 100 : 0) : (step && step.pct) || (st === 'done' ? 100 : 0));
    var pm = document.querySelector('[data-pmsg="' + n + '"]'); if (pm) pm.textContent = String(msg).slice(0, 30);
    var pb = document.querySelector('[data-pbar="' + n + '"]'); if (pb) pb.style.width = Math.max(0, Math.min(100, pct)) + '%';
    var run = document.querySelector('[data-nrun="' + n + '"]');
    if (run) {
      var busy = studioRunning();
      var noProj = !p;
      var noShots = !p || !(p.shots && p.shots.length);
      run.disabled = busy || (n > 1 && n < 5 && noShots) || (n === 2 && noShots) || (n === 5 && noShots) || (n === 4 && noShots) || n === 6;
      if (n === 6) run.style.display = 'none';
    }
  }
}

/* ---------- 事件：画布缩放 / 平移 / 拖节点 ---------- */
function bindCanvas() {
  var cv = $('#stCanvas'); if (!cv || cv.dataset.bound === '1') return;
  cv.dataset.bound = '1';
  var drag = null, pan = null;
  cv.addEventListener('pointerdown', function (ev) {
    if (ev.button !== 0) return;
    if (ev.target.closest('button,input,textarea,select')) return;
    var h = ev.target.closest('[data-drag]');
    if (h) {
      var n = +h.dataset.drag, q = STUDIO.nodes[n];
      drag = { n: n, x: ev.clientX, y: ev.clientY, ox: q.x, oy: q.y };
      STUDIO.dragging = true; cv.setPointerCapture(ev.pointerId); ev.preventDefault(); return;
    }
    if (ev.target.closest('.st-node') || ev.target.closest('button') || ev.target.closest('input') || ev.target.closest('textarea') || ev.target.closest('select')) return;
    pan = { x: ev.clientX, y: ev.clientY, ox: STUDIO.canvas.x, oy: STUDIO.canvas.y };
    STUDIO.canvas.auto = false; cv.setPointerCapture(ev.pointerId); ev.preventDefault();
  });
  cv.addEventListener('pointermove', function (ev) {
    if (drag) {
      var q = STUDIO.nodes[drag.n];
      q.x = Math.round(drag.ox + (ev.clientX - drag.x) / STUDIO.canvas.s);
      q.y = Math.round(drag.oy + (ev.clientY - drag.y) / STUDIO.canvas.s);
      var el = cv.querySelector('[data-node="' + drag.n + '"]');
      if (el) { el.style.left = q.x + 'px'; el.style.top = q.y + 'px'; }
      var e = $('#stEdges'); if (e) e.innerHTML = edgeHTML();
      return;
    }
    if (pan) {
      STUDIO.canvas.x = Math.round(pan.ox + ev.clientX - pan.x);
      STUDIO.canvas.y = Math.round(pan.oy + ev.clientY - pan.y);
      applyCanvas();
    }
  });
  function up() {
    if (drag || pan) { STUDIO.dragging = false; saveCanvas(); }
    drag = null; pan = null;
  }
  cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
  cv.addEventListener('wheel', function (ev) {
    ev.preventDefault();
    var r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
    var wx = (mx - STUDIO.canvas.x) / STUDIO.canvas.s, wy = (my - STUDIO.canvas.y) / STUDIO.canvas.s;
    var f = ev.deltaY < 0 ? 1.08 : 1 / 1.08;
    STUDIO.canvas.s = Math.max(.4, Math.min(1.8, STUDIO.canvas.s * f));
    STUDIO.canvas.x = mx - wx * STUDIO.canvas.s; STUDIO.canvas.y = my - wy * STUDIO.canvas.s;
    STUDIO.canvas.auto = false; applyCanvas(); saveCanvas();
  }, { passive: false });
}

/* ---------- 数据 / 动作 ---------- */
function studioPrefsSave() { if (typeof saveUI === 'function') saveUI({ studio: STUDIO.pref }); }
function studioPatch(body) {
  var p = studioProj(); if (!p || !useLive()) return Promise.resolve();
  body.pid = p.id;
  return api('PUT', '/api/studio/project', body, 20000).then(function (j) {
    if (STUDIO.st) STUDIO.st.project = j.project;
    return j.project;
  }).catch(function (e) { toast(e.message, 6000); throw e; });
}
function studioSaving(pr) {
  STUDIO.saving = pr;
  var clear = function () { if (STUDIO.saving === pr) STUDIO.saving = null; };
  pr.then(clear, clear);
  return pr;
}
function studioCollectShots() {
  var prompts = {};
  $$('#stNode2 [data-shot-prompt]').forEach(function (x) { prompts[x.getAttribute('data-shot-prompt')] = x.value; });
  var out = [];
  $$('#stNode3 [data-shot-text]').forEach(function (t) {
    var id = t.getAttribute('data-shot-text');
    var role = $('#stNode3 [data-shot-role="' + id + '"]'), sp = $('#stNode3 [data-shot-speaker="' + id + '"]'), tn = $('#stNode3 [data-shot-tone="' + id + '"]');
    out.push({ id: id, text: t.value, role: role ? role.value : '', speaker: sp ? sp.value : '', tone: tn ? tn.value : '',
      image_prompt: prompts[id] != null ? prompts[id] : undefined });
  });
  return out;
}
function studioSaveShots() {
  var p = studioProj(); if (!p || !useLive()) return Promise.resolve();
  clearTimeout(STUDIO.saveT);
  return studioSaving(studioPatch({ shots: studioCollectShots() }).then(function () { STUDIO.sig.canvas = ''; }).catch(function () {}));
}
function studioSaveMeta() {
  var p = studioProj(); if (!p || !useLive()) return Promise.resolve();
  clearTimeout(STUDIO.metaT);
  var t = $('#stTitle'), d = $('#stDesc'), g = $('#stTags');
  if (!t && !d && !g) return Promise.resolve();
  return studioSaving(studioPatch({ title: t ? t.value : p.title || '', desc: d ? d.value : p.desc || '', tags: g ? g.value : (p.tags || []).join(' ') })
    .then(function () { STUDIO.sig.canvas = ''; }).catch(function () {}));
}
function studioWaitSaved() { return STUDIO.saving ? STUDIO.saving.catch(function () {}) : Promise.resolve(); }
function studioDo(path, body, okMsg) {
  if (!useLive()) { toast('演示模式：连上后端才能用'); return Promise.reject(); }
  return api('POST', '/api/studio/' + path, body || {}, 60000).then(function (j) {
    if (j && j.project) { if (!STUDIO.st) STUDIO.st = {}; STUDIO.st.project = j.project; STUDIO.sig = {}; renderStudio(true); }
    if (okMsg) toast(okMsg, 5000);
    return j;
  }).catch(function (e) { toast(e.message, 8000); throw e; });
}
function studioTopicBody() {
  var s = (STUDIO.topic || '').trim(), isScript = /\n/.test(s) || s.length > 60;
  return { topic: isScript ? '' : s, text: isScript ? s : '' };
}
function studioPlan() {
  if (STUDIO.saving) return studioWaitSaved().then(studioPlan);
  var b = studioTopicBody();
  if (!b.topic && !b.text && !studioProj()) { toast('先写一个主题，或者导入 Gemini 剧本'); return Promise.reject(); }
  var p = studioProj(), body = b;
  if (p) body.pid = p.id;
  body.ratio = (p && p.ratio) || STUDIO.pref.ratio;
  body.seconds = (p && p.target_seconds) || STUDIO.pref.seconds;
  body.voice_id = (p && p.settings && p.settings.voice && p.settings.voice.id) || STUDIO.pref.voice;
  body.img_model = (p && p.img_model) || STUDIO.pref.imgModel || '';
  return studioDo('plan', body, '拆解好了：分镜已回填').then(function (j) { STUDIO.st = j; STUDIO.sig = {}; renderStudio(true); }).catch(function () {});
}
function studioRun(step, ids) {
  if (STUDIO.saving) return studioWaitSaved().then(function () { return studioRun(step, ids); });
  var p = studioProj(), topic = (STUDIO.topic || '').trim(), body = {};
  if (p) body.pid = p.id;
  else if (!topic) { toast('还没有项目：先写主题或导入剧本'); return Promise.reject(); }
  if (!p) { var b = studioTopicBody(); body.topic = b.topic; body.text = b.text; body.ratio = STUDIO.pref.ratio; body.seconds = STUDIO.pref.seconds; body.voice_id = STUDIO.pref.voice; body.img_model = STUDIO.pref.imgModel; }
  if (step) { body.mode = 'step'; body.step = step; }
  if (ids) body.ids = ids;
  return studioDo('run', body, step ? '' : '开始跑：拆解 → 生图 → 配音 → 配乐 → 合成').then(function () { studioFetch(); });
}
function studioImport() {
  var p = studioProj(), t = $('#stImport'), f = $('#stImportFile');
  var text = t ? t.value : '';
  if (!text.trim() && f && f.files && f.files[0]) {
    var reader = new FileReader();
    reader.onload = function () { if (t) t.value = reader.result || ''; studioImport(); };
    reader.readAsText(f.files[0], 'utf-8'); return;
  }
  if (!text.trim()) { toast('把 Gemini 输出的剧本贴进来，或者选一个文件'); return; }
  var body = { text: text };
  if (p) body.pid = p.id;
  else { body.ratio = STUDIO.pref.ratio; body.voice_id = STUDIO.pref.voice; body.img_model = STUDIO.pref.imgModel; }
  studioDo('import_script', body, '剧本导入好了：可以直接跑').then(function (j) {
    STUDIO.st = j; STUDIO.sig = {}; if (t) t.value = ''; renderStudio(true);
  }).catch(function () {});
}
function studioPlay(url) {
  if (!url) { toast('还没有可听的音频'); return; }
  if (STUDIO.audio) { try { STUDIO.audio.pause(); } catch (e) {} }
  STUDIO.audio = new Audio(url);
  STUDIO.audio.play().catch(function (e) { toast('放不了：' + e.message); });
}
function studioExport() {
  var p = studioProj(), a = document.createElement('a');
  a.href = '/api/studio/export_prompt_pack' + (p ? '?pid=' + encodeURIComponent(p.id) : '');
  a.download = 'gemini_prompt_pack.md';
  document.body.appendChild(a); a.click(); a.remove();
  toast('策划包已下载：交给 Gemini 写剧本，回来点「导入剧本」', 6000);
}
function studioFetch() {
  if (!useLive()) { renderStudio(); return Promise.resolve(); }
  return api('GET', '/api/studio/state', null, 8000).then(function (j) {
    var was = STUDIO.st && STUDIO.st.job && STUDIO.st.job.st === 'run' ? STUDIO.st.job : null;
    STUDIO.st = j;
    var nav = $('.nav[data-tool="studio"]'); if (nav) nav.classList.toggle('on-busy', !!(j.job && j.job.st === 'run'));
    if (was && j.job && j.job.id === was.id && j.job.st !== 'run') toast('视频工坊：' + (j.job.msg || j.job.st), 7000);
    renderStudio();
  }).catch(function () {});
}
function studioEnter() { studioFetch(); stHWStart(); clearInterval(STUDIO.t); STUDIO.t = setInterval(function () { if (S.view === 'studio') studioFetch(); }, 1500); }
function studioLeave() { clearInterval(STUDIO.t); STUDIO.t = null; stHWStop(); if (STUDIO.audio) { try { STUDIO.audio.pause(); } catch (e) {} } $$('#view-studio video').forEach(function (m) { try { m.pause(); } catch (e) {} }); }

/* ---------- 事件委托 ---------- */
(function () {
  var v = $('#view-studio'); if (!v) return;
  v.addEventListener('focusin', function (ev) { if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) STUDIO.editing = true; });
  v.addEventListener('focusout', function (ev) {
    if (!/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    setTimeout(function () {
      var a = document.activeElement;
      STUDIO.editing = !!(a && a.closest && a.closest('#view-studio') && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
      if (STUDIO.editing || STUDIO.dragging) return;
      var inShots = !!(ev.target.closest && ev.target.closest('#stNode3'));
      var inMeta = ev.target.id === 'stTitle' || ev.target.id === 'stDesc' || ev.target.id === 'stTags';
      if (inShots) { studioSaveShots(); return; }
      if (inMeta) { studioSaveMeta(); return; }
      renderStudio(true);
    }, 160);
  });
  v.addEventListener('input', function (ev) {
    var t = ev.target;
    if (t.id === 'stTopic') { STUDIO.topic = t.value; if (typeof saveUI === 'function') saveUI({ studioTopic: t.value.slice(0, 60000) }); return; }
    if (t.id === 'stBgmVol') { var pct = +t.value; var o = $('#stBgmVolV'); if (o) o.textContent = pct + '%'; STUDIO.pref.bgmVol = pct / 100; studioPrefsSave(); clearTimeout(STUDIO.saveT); STUDIO.saveT = setTimeout(function () { studioPatch({ settings: { bgm_volume: pct / 100 } }).catch(function () {}); }, 450); return; }
    if (t.id === 'stTitle' || t.id === 'stDesc' || t.id === 'stTags') { clearTimeout(STUDIO.metaT); STUDIO.metaT = setTimeout(studioSaveMeta, 650); return; }
    if (t.hasAttribute('data-shot-text') || t.hasAttribute('data-shot-tone') || t.hasAttribute('data-shot-prompt')) { clearTimeout(STUDIO.saveT); STUDIO.saveT = setTimeout(studioSaveShots, 700); return; }
    if (t.id === 'stBgmPrompt' || t.id === 'stBgmSec' || t.id === 'stBgmSteps') {
      clearTimeout(STUDIO.saveT);
      STUDIO.saveT = setTimeout(function () {
        var p = studioProj(); if (!p) return;
        if (t.id === 'stBgmPrompt') studioPatch({ bgm_prompt: t.value }).catch(function () {});
        else studioPatch({ settings: t.id === 'stBgmSec' ? { bgm_seconds: +t.value } : { bgm_steps: +t.value } }).catch(function () {});
      }, 550);
    }
  });
  v.addEventListener('change', function (ev) {
    var t = ev.target, p = studioProj();
    if (t.id === 'stProj') { if (t.value) studioDo('select', { pid: t.value }).then(function (j) { STUDIO.st = j; STUDIO.sig = {}; renderStudio(true); }).catch(function () {}); return; }
    if (t.id === 'stTitle' || t.id === 'stDesc' || t.id === 'stTags') { studioSaveMeta(); return; }
    if (t.id === 'stBgmSec' || t.id === 'stBgmSteps') {
      if (!p) return; studioPatch({ settings: t.id === 'stBgmSec' ? { bgm_seconds: +t.value } : { bgm_steps: +t.value } }).then(function () { STUDIO.sig.canvas = ''; }).catch(function () {}); return;
    }
    if (t.hasAttribute('data-shot-role') || t.hasAttribute('data-shot-speaker')) { studioSaveShots(); return; }
    if (t.getAttribute('data-role-voice')) {
      if (!p) return;
      var role = t.getAttribute('data-role-voice'), rv = {};
      rv[role] = t.value;
      studioPatch({ settings: { role_voices: rv } }).then(function () { STUDIO.sig.canvas = ''; renderStudio(true); }).catch(function () {});
      return;
    }
    if (t.id === 'stImgModel') {
      STUDIO.pref.imgModel = t.value; studioPrefsSave();
      if (p) studioPatch({ settings: { img_model: t.value } }).then(function () { STUDIO.sig.canvas = ''; renderStudio(true); }).catch(function () {});
      return;
    }
    if (t.id === 'stSub' && p) { studioPatch({ settings: { subtitle: t.checked } }).catch(function () {}); return; }
    if (t.id === 'stImportFile') { studioImport(); return; }
  });
  v.addEventListener('click', function (ev) {
    var b = ev.target.closest('button'); if (!b || b.disabled) return;
    var d = b.dataset, p = studioProj(), run = studioRunning();
    if (d.stRatio) {
      var r = d.stRatio; STUDIO.pref.ratio = r; studioPrefsSave();
      if (p) studioPatch({ ratio: r }).then(function () { STUDIO.sig.canvas = ''; renderStudio(true); toast('画幅改成 ' + r + '：图要重出，配音不用'); }).catch(function () {});
      return;
    }
    if (d.st) {
      if (run && d.st !== 'stop') { toast('正在跑，等它好了或者先点「停下」'); return; }
      if (d.st === 'new') {
        var body = { topic: (STUDIO.topic || '').trim(), ratio: STUDIO.pref.ratio, seconds: STUDIO.pref.seconds,
          voice_id: STUDIO.pref.voice, img_model: STUDIO.pref.imgModel };
        studioDo('new', body, '新建了空白项目').then(function (j) { STUDIO.st = j; STUDIO.sig = {}; renderStudio(true); }).catch(function () {});
        return;
      }
      if (d.st === 'reset') { STUDIO.nodes = stNodesDefault(); STUDIO.canvas.auto = true; fitCanvas(); renderStudio(true); return; }
      if (d.st === 'run') { studioRun(); return; }
      if (d.st === 'stop') { studioDo('stop', {}, '停下中：当前这一步收尾后不再往下做').then(function () { studioFetch(); }).catch(function () {}); return; }
      return;
    }
    if (d.nrun) {
      var n = +d.nrun;
      if (n === 1) studioPlan();
      else if (n === 2) studioRun('images');
      else if (n === 3) studioRun('tts');
      else if (n === 4) studioRun('bgm');
      else if (n === 5) studioRun('video');
      return;
    }
    if (run) { toast('正在跑，先停下或者等它完成'); return; }
    if (d.act === 'export') { studioExport(); return; }
    if (d.act === 'importToggle') { var box = $('#stImportBox'); if (box) box.hidden = !box.hidden; return; }
    if (d.act === 'import') { studioImport(); return; }
    if (d.act === 'plan') { studioPlan(); return; }
    if (d.act === 'imgs') { studioRun('images'); return; }
    if (d.act === 'imgsAll') { studioRun('images', (p && p.shots || []).map(function (s) { return s.id; })); return; }
    if (d.act === 'tts') { studioRun('tts'); return; }
    if (d.act === 'bgm') { studioRun('bgm'); return; }
    if (d.act === 'bgmPlay') { if (p && p.files && p.files.bgm) studioPlay(p.files.bgm.url); return; }
    if (d.act === 'video') { studioRun('video'); return; }
    if (d.act === 'pub') { studioDo('to_publish', {}, '').then(function (j) { toast(j.msg || '放进发布窗口了', 7000); }).catch(function () {}); return; }
    if (d.act === 'open') { studioDo('open', { what: 'output' }, '打开输出文件夹').catch(function () {}); return; }
    if (d.act === 'gotoPub') { openView('publish'); return; }
    if (d.shotImg) { studioRun('images', [d.shotImg]); return; }
    if (d.shotVoice) { studioRun('tts', [d.shotVoice]); return; }
    if (d.shotPlay) {
      var s = (p && p.shots || []).filter(function (x) { return x.id === d.shotPlay; })[0];
      if (s && s.tts_url) studioPlay(s.tts_url); else toast('这一句还没配音');
      return;
    }
  });
})();

function stNodesDefault() { var o = {}; for (var k in ST_LAYOUT) o[k] = Object.assign({}, ST_LAYOUT[k]); return o; }
