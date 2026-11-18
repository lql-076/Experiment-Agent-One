'use strict';
/* ================= 视频工坊 · 七模块零连线画布（v4.0.0 / R11）=================
   没有端口、没有连线、没有 DAG、没有「缺上游」。
   7 个模块：剧本与策划 / 生图测试台 / 配音·白页 / 配音·紫苏 / 背景配乐 /
             视频制作总成（网页动效 + PPT + FFmpeg 三窗）/ 成片预览与发布。
   模块之间靠项目 Lists/ 下的 Markdown 清单协作。每个模块都能单独点运行。 */
var ST_STYLE = '知识科普 × 科技数码 × 搞笑段子';
var ST_ROLES = ['白页', '紫苏', '旁白'];
var ST_RATIOS = ['9:16', '16:9', '1:1', '3:4', '4:3', '2:3', '3:2'];
var ST_LISTS = ['配音清单_白页.md', '配音清单_紫苏.md', '配乐清单.md', '视频渲染清单.md', '生图清单.md'];
var ST_TYPE_LABEL = { script: '剧本', image: '生图测试', voice: '配音', bgm: '配乐', compose: '视频总成', publish: '发布' };
var ST_IDS = ['script', 'image', 'voice-white', 'voice-zisu', 'bgm', 'compose', 'publish'];
var ST_DEFAULT = { script: [350, 470], image: [380, 620], voice: [400, 500], bgm: [360, 360], compose: [1610, 720], publish: [360, 600] };
var STUDIO = {
  st: null, t: null, hwT: null, hwBusy: false, pid: '', sig: {}, nodeSig: {}, editing: false, dragging: false,
  saveT: {}, layoutT: null, layoutPending: false, saving: null, audio: null, fitted: false,
  canvas: { x: 20, y: 20, s: 1, auto: true }, drag: null, resize: null, pan: null, fetching: null, lastPid: '', autoPlay: ''
};
try {
  if (U.studioView4 && typeof U.studioView4 === 'object') {
    STUDIO.canvas.x = +U.studioView4.x || 20; STUDIO.canvas.y = +U.studioView4.y || 20;
    STUDIO.canvas.s = Math.max(.25, Math.min(2, +U.studioView4.s || 1)); STUDIO.canvas.auto = false;
  }
} catch (e) {}

function studioSt() { return useLive() ? STUDIO.st : stDemo(); }
function studioProj() { var s = studioSt(); return s && s.project; }
function studioJob() { var s = studioSt(); return s && s.job; }
function studioRunning() { var j = studioJob(); return !!(j && j.st === 'run'); }
function stMods() { var p = studioProj(); return (p && p.modules) || []; }
function stModMap() { var m = {}; stMods().forEach(function (x) { m[x.id] = x; }); return m; }
function stSize(b) { b = +b || 0; return b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' KB'; }
function stMedia(pid, rel, ver) { return '/api/studio/media?pid=' + encodeURIComponent(pid || '') + '&path=' + encodeURIComponent(rel || '') + '&v=' + (ver || Date.now()); }
function stAsset(pid, rel) { return '/api/studio/asset?pid=' + encodeURIComponent(pid || '') + '&path=' + encodeURIComponent(rel || ''); }
function stSet(id, v) { var e = $('#' + id); if (e && e.textContent !== v) e.textContent = v; }
function stPut(id, html) { var e = $('#' + id); if (!e || STUDIO.sig[id] === html) return; STUDIO.sig[id] = html; e.innerHTML = html; }

/* ---------- 演示 ---------- */
function stDemo() {
  var p = { id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', desc: '', tags: ['AI'], ratio: '9:16',
    files: {}, total_seconds: 12, duration: 0, resolution: '', video_ok: false, dir: 'F:\\Agent\\工作区\\视频工坊\\演示项目',
    lists: { '配音清单_白页.md': '# 配音清单 · 白页\n\n## 01\n台词：先说一个反常识的结论。\n语气：冷静吐槽',
             '配音清单_紫苏.md': '# 配音清单 · 紫苏\n\n## 02\n台词：等等，这也太离谱了吧？\n语气：轻松调侃',
             '配乐清单.md': '# 配乐清单\n\n## 01\n描述：upbeat electronic, no vocals',
             '视频渲染清单.md': '# 视频渲染清单\n\n## 01\n方式：网页动效\n字幕：先说一个反常识的结论。\n画面：深色科技感排版',
             '生图清单.md': '# 生图清单（可选）\n\n## 01\n提示词：暖光书桌前的年轻人' } };
  var defs = [['script', 'script', '剧本与策划', 40, 40, 350, 470], ['image', 'image', '生图测试台（独立）', 430, 40, 380, 620],
    ['voice-white', 'voice', '角色配音 · 白页', 850, 40, 400, 500], ['voice-zisu', 'voice', '角色配音 · 紫苏', 850, 570, 400, 500],
    ['bgm', 'bgm', '背景配乐（Stable Audio 3）', 1290, 40, 360, 360], ['compose', 'compose', '视频制作总成（Claude Code 驱动）', 40, 1120, 1610, 720],
    ['publish', 'publish', '成片预览与抖音发布', 1290, 430, 360, 600]];
  var prms = {
    script: { topic: '三个被低估的 AI 用法', title: '三个被低估的 AI 用法', desc: '', tags: ['AI'] },
    image: { prompt: '暖光书桌前的年轻人，竖屏中景', model: 'gpt-image-2.5-sunburst-vip', ratio: '9:16', resolution: '2k', quality: 'high', complexity: 'medium', n: 1, output: 'normal', format: 'png', refs: [] },
    'voice-white': { role: '白页', speaker: 'local:preset:Serena', engine: 'auto', tone: '冷静吐槽', lines: [{ id: 'l1', line_index: 1, text: '先说一个反常识的结论。', tone: '' }] },
    'voice-zisu': { role: '紫苏', speaker: 'local:preset:Dylan', engine: 'auto', tone: '轻松调侃', lines: [{ id: 'l1', line_index: 2, text: '等等，这也太离谱了吧？', tone: '' }] },
    bgm: { prompt: 'upbeat electronic, no vocals', seconds: 75, steps: 8, seed: 20261118 },
    compose: { subtitle: true, ratio: '9:16', bgm_volume: .18, duck_depth: .16, fade: 2, fps: 24, cc_drive: true,
      shots: [{ id: 's01', line_index: 1, render: 'web', text: '先说一个反常识的结论。', visual: '深色科技感排版', seconds: 6 },
              { id: 's02', line_index: 2, render: 'ppt', text: '等等，这也太离谱了吧？', visual: '两个要点', seconds: 6 }] },
    publish: { title: '三个被低估的 AI 用法', desc: '', tags: ['AI'], mode: 'single', declaration: '内容由AI生成' }
  };
  p.modules = defs.map(function (d) {
    return { id: d[0], type: d[1], title: d[2], x: d[3], y: d[4], w: d[5], h: d[6], params: JSON.parse(JSON.stringify(prms[d[0]])),
      outputs: [], status: 'idle', error: '', cache_hit: false };
  });
  return { projects: [{ id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', created: '2026-11-18 02:00:00', ratio: '9:16', st: 'idle', shots: 7, video: false }],
    active: 'demo', project: p, job: null,
    voices: [{ id: 'local:preset:Vivian', label: 'Vivian · 女声', engine: 'local' }, { id: 'local:preset:Serena', label: 'Serena · 女声', engine: 'local' },
      { id: 'local:preset:Dylan', label: 'Dylan · 男声', engine: 'local' }, { id: 'local:preset:Uncle_Fu', label: 'Uncle_Fu · 男声', engine: 'local' }],
    models: [{ id: 'gpt-image-2.5-sunburst-vip', name: 'GPT Image 2.5 Sunburst VIP', vendor: 'OpenAI', gif: true, svg: true, price: .03 }],
    style_tag: ST_STYLE, roles: ST_ROLES, publish: { pending: 0, batch: 0 } };
}

/* ---------- 外壳 ---------- */
function studioShell() {
  return '<div class="st"><div class="st-top" id="stTop"></div>' +
    '<div class="st-hw" id="stHw">' +
    '<span class="st-hw-g"><i>CPU</i><b id="stHwCpu">—</b><em>% · <span id="stHwCpuF">—</span> GHz</em><u><s id="stHwCpuBar"></s></u></span>' +
    '<span class="st-hw-g"><i>内存</i><b id="stHwRam">—</b><em>/ <span id="stHwRamT">—</span> GB · <span id="stHwRamP">—</span>%</em><u><s id="stHwRamBar"></s></u></span>' +
    '<span class="st-hw-g"><i>GPU</i><b id="stHwGpu">—</b><em>% · <span id="stHwTemp">—</span>°C</em><u><s id="stHwGpuBar"></s></u></span>' +
    '<span class="st-hw-g"><i>显存</i><b id="stHwVram">—</b><em>/ <span id="stHwVramT">—</span> GB · <span id="stHwVramP">—</span>%</em><u><s id="stHwVramBar"></s></u></span>' +
    '<span class="st-hw-src" id="stHwSrc">2 秒刷新</span></div>' +
    '<div class="st-canvas" id="stCanvas"><div class="st-world" id="stWorld"></div>' +
    '<div class="st-canvas-tip">拖动空白平移 · 滚轮缩放 · 模块可拖动、右下角缩放</div></div></div>';
}

function renderStudio(force) {
  var v = $('#view-studio'); if (!v) return;
  if (!v.querySelector('.st')) { v.innerHTML = studioShell(); STUDIO.sig = {}; STUDIO.nodeSig = {}; bindCanvas(); }
  if ((STUDIO.editing || STUDIO.dragging) && !force) { syncMeta(); return; }
  if (force) STUDIO.nodeSig = {};
  renderTop(); renderCanvas(); syncMeta();
  if (!STUDIO.fitted && STUDIO.canvas.auto) { STUDIO.fitted = true; fitCanvas(); }
}

function renderTop() {
  var s = studioSt() || {}, ps = s.projects || [], p = s.project, run = studioRunning();
  var sel = '<select class="inp st-projsel" id="stProj" aria-label="切换项目">' + (ps.length ? ps.map(function (x) {
    return '<option value="' + esc(x.id) + '"' + (p && x.id === p.id ? ' selected' : '') + '>' + esc(x.title || x.name) + ' · ' + esc((x.created || '').slice(5, 16)) + '</option>';
  }).join('') : '<option value="">还没有项目</option>') + '</select>';
  var html = '<div class="st-brand"><b>视频工坊</b><span class="st-style">' + esc(ST_STYLE) + ' · 零连线独立模块</span></div>' +
    '<div class="st-proj"><label for="stProj">项目</label>' + sel + '<button class="btn mini ghost" data-st="new">新建</button></div>' +
    '<div class="st-acts"><button class="btn mini ghost" data-st="fit">适应窗口</button>' +
    '<button class="btn primary st-runall" data-st="run"' + (run ? ' disabled' : '') + '>▶ 从头跑通全流程</button>' +
    '<button class="btn mini danger" data-st="stop"' + (run ? '' : ' disabled') + '>■ 停下</button></div>';
  stPut('stTop', html);
}

/* ---------- 硬件条 ---------- */
function stHWBar(id, v, max) { var e = $('#' + id); if (e) e.style.width = Math.max(0, Math.min(100, (+v || 0) / (max || 100) * 100)).toFixed(1) + '%'; }
function renderStHW(h) {
  h = h || (window.HW || {}); var cpu = h.cpu || {}, gpu = h.gpu || {}, ram = h.ram || {};
  stSet('stHwCpu', cpu.load == null ? '—' : (+cpu.load).toFixed(0)); stSet('stHwCpuF', cpu.clock == null ? '—' : (+cpu.clock).toFixed(2));
  stSet('stHwRam', ram.used == null ? '—' : (+ram.used).toFixed(1)); stSet('stHwRamT', ram.total == null ? '—' : (+ram.total).toFixed(0));
  stSet('stHwRamP', ram.load == null ? '—' : (+ram.load).toFixed(0)); stSet('stHwGpu', gpu.load == null ? '—' : (+gpu.load).toFixed(0));
  stSet('stHwTemp', !gpu.temp ? '—' : (+gpu.temp).toFixed(0)); stSet('stHwVram', gpu.vram == null ? '—' : (+gpu.vram).toFixed(1));
  stSet('stHwVramT', gpu.vramTotal == null ? '—' : (+gpu.vramTotal).toFixed(0)); stSet('stHwVramP', gpu.vramPct == null ? '—' : (+gpu.vramPct).toFixed(0));
  stHWBar('stHwCpuBar', cpu.load, 100); stHWBar('stHwRamBar', ram.load, 100); stHWBar('stHwGpuBar', gpu.load, 100); stHWBar('stHwVramBar', gpu.vramPct, 100);
  stSet('stHwSrc', useLive() ? '2 秒刷新' : '演示数据');
}
function stHWTick() {
  if (document.visibilityState === 'hidden' || STUDIO.hwBusy) return;
  if (!useLive()) { renderStHW(window.HW); return; }
  STUDIO.hwBusy = true;
  api('GET', '/api/hw', null, 6000).then(renderStHW).catch(function () { renderStHW({}); }).then(function () { STUDIO.hwBusy = false; });
}
function stHWStart() { stHWStop(); if (document.visibilityState === 'hidden') return; stHWTick(); STUDIO.hwT = setInterval(stHWTick, 2000); }
function stHWStop() { if (STUDIO.hwT) clearInterval(STUDIO.hwT); STUDIO.hwT = null; }
document.addEventListener('visibilitychange', function () {
  if (!STUDIO.hwT && S.view === 'studio' && !document.hidden) stHWStart(); else if (STUDIO.hwT && document.hidden) stHWStop();
});

/* ---------- 模块骨架 ---------- */
function stStatus(m) {
  var j = studioJob(), p = studioProj();
  if (j && j.st === 'run' && j.pid === (p && p.id) && j.step === m.id && m.status === 'run') return 'run';
  if (m.status === 'ok' || m.status === 'warn') return 'done';
  if (m.status === 'err') return 'bad';
  if (m.status === 'stale') return 'stale';
  if (m.status === 'run') return 'run';
  return 'idle';
}
function stLamp(m, id) { return '<span class="st-lamp st-' + stStatus(m) + '"' + (id ? ' data-lamp="' + esc(m.id) + '"' : '') + '></span>'; }
function stHeader(m) {
  return '<header class="st-node-h" data-drag="' + esc(m.id) + '"><span class="st-node-n st-t-' + esc(m.type) + '">' + esc(ST_TYPE_LABEL[m.type] || m.type) + '</span>' +
    '<b title="' + esc(m.title || '') + '">' + esc(m.title || m.id) + '</b>' + stLamp(m, true) +
    '<button class="st-nrun" data-run="' + esc(m.id) + '" title="只跑这个模块">▶ 只跑</button></header>';
}
function stFooter(m) {
  var j = studioJob(), p = studioProj(), cur = j && j.st === 'run' && j.pid === (p && p.id) && j.step === m.id;
  var msg = (cur && j.msg) || m.error || (m.status === 'ok' ? '已完成' : m.status === 'stale' ? '要重做' : m.status === 'err' ? '出错' : '待命');
  return '<footer class="st-node-f">' + (m.cache_hit ? '<em class="st-tag ok">缓存命中</em>' : '') +
    '<span data-pmsg="' + esc(m.id) + '">' + esc(String(msg).slice(0, 60)) + '</span></footer>';
}
function stModule(m, body, cls) {
  return '<section class="hud st-node ' + (cls || '') + ' st-m-' + esc(m.id) + '" data-node="' + esc(m.id) + '" data-type="' + esc(m.type) + '" style="left:' + m.x + 'px;top:' + m.y + 'px;width:' + m.w + 'px;height:' + m.h + 'px">' +
    stHeader(m) + '<div class="st-node-body" id="stNode-' + esc(m.id) + '">' + body + '</div>' + stFooter(m) +
    '<span class="st-rs" data-rs="' + esc(m.id) + '" title="拖动改变模块大小"></span></section>';
}

/* ---------- 小控件 ---------- */
function stSelect(opts, cur) { return opts.map(function (x) { return '<option value="' + esc(x[0]) + '"' + (String(cur) === String(x[0]) ? ' selected' : '') + '>' + esc(x[1]) + '</option>'; }).join(''); }
function stModelOptions(cur) {
  var ms = (studioSt() && studioSt().models) || [], out = [];
  if (cur && !ms.some(function (m) { return m.id === cur; })) out.push('<option value="' + esc(cur) + '" selected>' + esc(cur) + '</option>');
  ms.forEach(function (m) { out.push('<option value="' + esc(m.id) + '"' + (m.id === cur ? ' selected' : '') + '>' + esc((m.vendor ? m.vendor + ' · ' : '') + m.name + (m.gif ? ' · GIF' : '')) + '</option>'); });
  return out.join('') || '<option value="">用设置里的默认模型</option>';
}
function stVoiceOptions(cur) {
  var vs = (studioSt() && studioSt().voices) || [], groups = {};
  vs.forEach(function (v) { var g = v.engine === 'cloud' ? '百炼云端' : '本地'; (groups[g] = groups[g] || []).push(v); });
  var out = [], found = vs.some(function (v) { return v.id === cur; });
  if (cur && !found) out.push('<option value="' + esc(cur) + '" selected>' + esc(cur) + '</option>');
  Object.keys(groups).forEach(function (g) { out.push('<optgroup label="' + esc(g) + '">' + groups[g].map(function (v) {
    return '<option value="' + esc(v.id) + '"' + (v.id === cur ? ' selected' : '') + '>' + esc(v.label) + '</option>'; }).join('') + '</optgroup>'); });
  return out.join('') || '<option value="">还没有音色</option>';
}
function stLbOuts(p, m, kind) {
  return (m.outputs || []).filter(function (o) { return !kind || o.kind === kind; }).map(function (o) {
    return { url: stAsset(p.id, o.rel), name: o.rel, rel: o.rel, pid: p.id, cacheHit: !!m.cache_hit };
  });
}
function stLbOpen(p, m, kind, i) {
  var items = stLbOuts(p, m, kind); if (!items.length) { toast('这个模块还没有图'); return; }
  if (window.Lightbox) Lightbox.open(items, Math.max(0, Math.min(items.length - 1, +i || 0)));
}
function stThumbs(p, m, kind) {
  var outs = (m.outputs || []).filter(function (o) { return o.kind === kind; });
  if (!outs.length) return '<div class="st-nohint">还没有产出</div>';
  return '<div class="st-outgrid">' + outs.map(function (o, i) {
    return '<button class="st-outthumb" data-lb="' + esc(m.id) + ':' + (kind || 'image') + ':' + i + '"><img src="' + esc(stAsset(p.id, o.rel)) + '" alt=""><span>' + esc(String(o.rel).split('/').pop()) + '</span></button>';
  }).join('') + '</div>';
}
function stVideos(p, m) {
  var outs = (m.outputs || []).filter(function (o) { return o.kind === 'video'; });
  return outs.map(function (o) { return '<video class="st-video" controls preload="metadata" src="' + esc(stAsset(p.id, o.rel)) + '"></video>'; }).join('') || '<div class="st-nohint">还没有视频</div>';
}
function stAudios(p, m) {
  var outs = (m.outputs || []).filter(function (o) { return o.kind === 'audio'; });
  return '<div class="st-audios">' + (outs.map(function (o, i) {
    return '<div class="st-audio"><button class="btn mini ghost" data-play="' + esc(m.id) + ':' + i + '">▶ 听</button><span>' + esc(String(o.rel).split('/').pop()) + (o.duration ? ' · ' + (+o.duration).toFixed(1) + ' 秒' : '') + '</span></div>';
  }).join('') || '<div class="st-nohint">还没有音频</div>') + '</div>';
}
function stListBox(p, name) {
  var text = (p.lists || {})[name] || '';
  return '<details class="st-listbox"><summary>📄 ' + esc(name) + '</summary><textarea class="inp" data-list="' + esc(name) + '" rows="4" spellcheck="false">' + esc(text) + '</textarea>' +
    '<div class="st-row2"><button class="btn mini" data-listsave="' + esc(name) + '">保存清单并重新载入</button><span class="st-hint">改完清单，对应模块按新内容重做</span></div></details>';
}

/* ---------- 模块 1 ---------- */
function stScriptBody(p, m) {
  var prm = m.params || {}, l = p.lists || {};
  return '<textarea class="inp st-topic" data-p="topic" rows="2" spellcheck="false" placeholder="写主题，或者把完整口播文案贴进来">' + esc(prm.source_text || prm.topic || '') + '</textarea>' +
    '<div class="st-row"><input class="inp" data-p="title" maxlength="30" placeholder="发布标题" value="' + esc(prm.title || p.title || '') + '"><input class="inp" data-p="tags" placeholder="话题 空格隔开" value="' + esc((prm.tags || p.tags || []).join ? (prm.tags || p.tags || []).join(' ') : (prm.tags || '')) + '"></div>' +
    '<textarea class="inp" data-p="desc" rows="2" spellcheck="false" placeholder="发布简介">' + esc(prm.desc || p.desc || '') + '</textarea>' +
    '<div class="st-row2"><button class="btn mini primary" data-act="plan">DeepSeek 拆解</button><button class="btn mini ghost" data-act="importToggle">导入剧本</button></div>' +
    '<div class="st-import" id="stImportBox" hidden><textarea class="inp" id="stImport" rows="4" spellcheck="false" placeholder="贴 JSON 或 Markdown 剧本；格式见 说明 › 视频工坊剧本格式"></textarea>' +
    '<div class="st-row"><label class="btn mini ghost st-file">选文件<input type="file" id="stImportFile" accept=".md,.markdown,.txt,.json" hidden></label><button class="btn mini primary" data-act="import">导入并生成清单</button><button class="linkbtn" data-act="importCancel">取消</button></div></div>' +
    '<button class="btn mini st-wide" data-act="lists">重新生成 5 份 Markdown 清单</button>' +
    '<div class="st-liststat">清单：' + ST_LISTS.map(function (n) { return '<em class="' + (l[n] ? 'ok' : '') + '">' + esc(n.replace('.md', '')) + '</em>'; }).join('') + '</div>' +
    '<div class="st-hint">导入只建清单和模块参数，不会自动花钱；DeepSeek 拆解会消耗一点额度。</div>';
}

/* ---------- 模块 2 ---------- */
function stImageBody(p, m) {
  var prm = m.params || {}, res = prm.resolution || '2k', out = prm.output || 'normal', fmt = prm.format || 'png';
  var frames = +prm.gif_frames || 8, delay = +prm.gif_delay_ms || 150, cw = +prm.custom_w || 1024, ch = +prm.custom_h || 1024;
  var items = prm.items || [];
  return '<div class="st-badgenote">独立测试工具 · 不参与视频主流程</div>' +
    (items.length ? '<div class="st-subrow"><label class="st-lab">清单</label><select data-p="selected">' + items.map(function (x, i) {
      return '<option value="' + i + '"' + (+prm.selected === i ? ' selected' : '') + '>' + esc(x.prompt.slice(0, 28)) + '</option>'; }).join('') + '</select></div>' : '') +
    '<textarea class="inp" data-p="prompt" rows="3" spellcheck="false" placeholder="这一张的画面提示词">' + esc(prm.prompt || '') + '</textarea>' +
    '<div class="st-subrow"><select data-p="model">' + stModelOptions(prm.model) + '</select><select data-p="ratio">' + stSelect(ST_RATIOS.map(function (x) { return [x, x]; }), prm.ratio || p.ratio) + '</select></div>' +
    '<div class="st-subrow"><select data-p="resolution">' + stSelect([['1k', '1K'], ['2k', '2K'], ['4k', '4K'], ['custom', '自定义']], res) + '</select>' +
    '<select data-p="n">' + stSelect([[1, '1 张'], [2, '2 张'], [3, '3 张'], [4, '4 张']], prm.n || 1) + '</select></div>' +
    '<div class="st-subrow"><select data-p="quality">' + stSelect([['auto', 'quality auto'], ['low', 'low'], ['medium', 'medium'], ['high', 'high'], ['xhigh', 'xhigh'], ['max', 'max']], prm.quality || 'high') + '</select>' +
    '<select data-p="complexity">' + stSelect([['low', 'complexity low'], ['medium', 'medium'], ['high', 'high']], prm.complexity || 'medium') + '</select></div>' +
    (res === 'custom' ? '<div class="st-subrow"><label class="st-lab">宽</label><input class="inp st-num2" data-p="custom_w" type="number" min="16" max="3840" step="16" value="' + cw + '"><label class="st-lab">高</label><input class="inp st-num2" data-p="custom_h" type="number" min="16" max="3840" step="16" value="' + ch + '"><span class="st-hint" data-sizeerr="' + esc(m.id) + '"></span></div>' : '') +
    '<div class="seg st-outtype">' + [['normal', '普通'], ['gif', 'GIF'], ['svg', 'SVG']].map(function (x) {
      return '<button data-out="' + esc(m.id) + ':' + x[0] + '" aria-pressed="' + (out === x[0]) + '">' + x[1] + '</button>'; }).join('') + '</div>' +
    (out === 'gif' ? '<div class="st-subrow"><label class="st-lab">帧数</label><input class="inp st-num2" data-p="gif_frames" type="number" min="2" max="16" value="' + frames + '"><label class="st-lab">每帧 ms</label><input class="inp st-num2" data-p="gif_delay_ms" type="number" min="20" max="2000" value="' + delay + '"></div>'
      : out === 'svg' ? '<div class="st-hint">SVG 矢量图，背景透明。</div>'
        : '<div class="st-subrow"><select data-p="format">' + stSelect([['png', 'PNG'], ['jpeg', 'JPEG'], ['webp', 'WebP']], fmt) + '</select><label class="st-chk"><input type="checkbox" data-p="transparent"' + (prm.transparent ? ' checked' : '') + '>透明 alpha</label></div>') +
    '<div class="st-refs">' + (prm.refs || []).map(function (r, i) {
      return '<span class="st-ref" title="' + esc(r) + '"><img src="' + esc(stMedia(p.id, r)) + '" alt=""><button data-refdel="' + esc(m.id) + ':' + i + '">×</button></span>'; }).join('') +
      '<label class="btn mini ghost st-file">+ 参考图<input type="file" accept="image/png,image/jpeg" multiple data-ref-file="' + esc(m.id) + '" hidden></label></div>' +
    '<button class="btn primary st-wide" data-run="' + esc(m.id) + '">▶ 立即生成测试</button>' +
    '<div class="st-outlabel">测试产出</div>' + stThumbs(p, m, 'image') + stListBox(p, '生图清单.md');
}

/* ---------- 模块 3/4 ---------- */
function stVoiceBody(p, m) {
  var prm = m.params || {}, lines = prm.lines || [];
  var listName = m.id === 'voice-white' ? '配音清单_白页.md' : '配音清单_紫苏.md';
  return '<div class="st-subrow"><select data-p="role">' + stSelect(ST_ROLES.map(function (x) { return [x, x]; }), prm.role || (m.id === 'voice-white' ? '白页' : '紫苏')) + '</select>' +
    '<select data-p="engine">' + stSelect([['auto', '自动选引擎'], ['local', '本地 Qwen3-TTS'], ['cloud', '百炼云端']], prm.engine || 'auto') + '</select></div>' +
    '<div class="st-subrow"><select data-p="speaker">' + stVoiceOptions(prm.speaker || '') + '</select></div>' +
    '<input class="inp" data-p="tone" value="' + esc(prm.tone || '') + '" placeholder="默认语气：冷静吐槽 / 轻松调侃">' +
    '<div class="st-lines">' + lines.map(function (ln, i) {
      return '<div class="st-line" data-line="' + i + '"><div class="st-line-h"><b>#' + (ln.line_index || i + 1) + '</b><span class="sp"></span>' +
        '<button class="linkbtn" data-lineplay="' + esc(m.id) + ':' + i + '">▶ 试听/重配</button><button class="linkbtn" data-linedel="' + esc(m.id) + ':' + i + '">删除</button></div>' +
        '<textarea class="inp" data-line-text rows="1" spellcheck="false">' + esc(ln.text || '') + '</textarea>' +
        '<input class="inp" data-line-tone value="' + esc(ln.tone || '') + '" placeholder="这一句的语气（可空）"></div>';
    }).join('') + '</div>' +
    '<div class="st-row2"><button class="btn mini ghost" data-lineadd="' + esc(m.id) + '">+ 加一句</button><button class="btn mini ghost" data-bulk="' + esc(m.id) + '">批量贴台词</button></div>' +
    '<details class="st-bulk" id="stBulk-' + esc(m.id) + '"><summary>批量贴台词（一行一句）</summary><textarea class="inp" data-bulk-text rows="3" spellcheck="false"></textarea><button class="btn mini primary" data-bulkgo="' + esc(m.id) + '">替换成这些句</button></details>' +
    '<button class="btn primary st-wide" data-run="' + esc(m.id) + '">▶ 单独运行本角色配音</button>' +
    '<div class="st-outlabel">本角色音频</div>' + stAudios(p, m) +
    '<div class="st-hint">白页/紫苏按全局句序写 tts/shotNN.wav，最后汇总 voice.wav + .srt + timeline.json。</div>' +
    stListBox(p, listName);
}

/* ---------- 模块 5 ---------- */
function stBgmBody(p, m) {
  var prm = m.params || {};
  return '<textarea class="inp" data-p="prompt" rows="3" spellcheck="false" placeholder="英文描述最好：风格、情绪、乐器、速度；不要人声">' + esc(prm.prompt || '') + '</textarea>' +
    '<div class="st-row"><label class="st-lab">时长</label><input class="inp st-num" data-p="seconds" type="number" min="10" max="380" value="' + (+prm.seconds || 75) + '"><span class="st-hint">秒</span></div>' +
    '<div class="st-row2"><label class="st-f"><span class="st-lab">步数</span><input class="inp" data-p="steps" type="number" min="1" max="32" value="' + (+prm.steps || 8) + '"></label>' +
    '<label class="st-f"><span class="st-lab">种子</span><input class="inp" data-p="seed" type="number" value="' + (+prm.seed || 20261118) + '"></label></div>' +
    '<button class="btn primary st-wide" data-run="' + esc(m.id) + '">▶ 单独生成配乐</button>' +
    '<div class="st-outlabel">试听</div>' + stAudios(p, m) + stListBox(p, '配乐清单.md');
}

/* ---------- 模块 6 ---------- */
function stMonA(j) {
  var w = (j && j.web) || {}, p = studioProj();
  var img = w.preview_rel ? '<img class="st-mon-img" data-lbmon="web" src="' + esc(stMedia(p.id, w.preview_rel)) + '" alt="" title="点开看大图">' : '<div class="st-mon-empty">等网页动效渲染…</div>';
  return '<div class="st-mon st-mon-a"><div class="st-mon-h"><b>监控 A · 网页动效渲染</b>' + (w.st === 'run' ? '<em class="st-tag run">渲染中</em>' : w.st === 'ok' ? '<em class="st-tag ok">完成</em>' : w.st === 'err' ? '<em class="st-tag bad">出错</em>' : '<em class="st-tag">待命</em>') + '</div>' +
    '<div class="st-mon-body">' + img + '<div class="st-mon-meta"><span>镜头 ' + (w.current || 0) + '/' + (w.total || 0) + '</span><span>FPS ' + (w.fps || 0) + '</span><span>Claude Code：' + esc(w.cc || '没开') + '</span></div>' +
    '<div class="st-mon-msg">' + esc(w.msg || '等合成') + '</div></div>' +
    '<button class="btn mini ghost st-mon-run" data-runpart="web">▶ 仅重跑网页动效</button></div>';
}
function stMonB(j) {
  var w = (j && j.ppt) || {}, p = studioProj();
  var slides = (w.slides || []).map(function (rel, i) {
    return '<button class="st-slide" data-lbslide="' + i + '"><img src="' + esc(stAsset(p.id, rel)) + '" alt=""><span>' + (i + 1) + '</span></button>'; }).join('');
  return '<div class="st-mon st-mon-b"><div class="st-mon-h"><b>监控 B · PPT 卡片</b>' + (w.st === 'run' ? '<em class="st-tag run">渲染中</em>' : w.st === 'ok' ? '<em class="st-tag ok">完成</em>' : w.st === 'err' ? '<em class="st-tag bad">出错</em>' : '<em class="st-tag">待命</em>') + '</div>' +
    '<div class="st-mon-body"><div class="st-slides">' + (slides || '<div class="st-mon-empty">等 PPT 卡片…</div>') + '</div>' +
    '<div class="st-mon-meta"><span>' + (w.current || 0) + '/' + (w.total || 0) + ' 页</span><span>' + esc(w.msg || '') + '</span></div></div>' +
    '<button class="btn mini ghost st-mon-run" data-runpart="ppt">▶ 仅重跑 PPT 卡片</button></div>';
}
function stMonC(j, m) {
  var w = (j && j.ffmpeg) || {}, prm = m.params || {}, pa = w.params || {};
  var vol = Math.round((pa.bgm_volume != null ? +pa.bgm_volume : (+prm.bgm_volume || .18)) * 100);
  return '<div class="st-mon st-mon-c"><div class="st-mon-h"><b>监控 C · FFmpeg 混流压制</b>' + (w.st === 'run' ? '<em class="st-tag run">压制中</em>' : w.st === 'ok' ? '<em class="st-tag ok">完成</em>' : w.st === 'err' ? '<em class="st-tag bad">出错</em>' : '<em class="st-tag">待命</em>') + '</div>' +
    '<div class="st-mon-body"><div class="st-pbar big"><b style="width:' + Math.max(0, Math.min(100, +w.pct || 0)) + '%"></b></div>' +
    '<div class="st-mon-meta"><span>' + (+w.pct || 0).toFixed(0) + '%</span><span>编码 ' + (pa.fps || 30) + ' fps</span><span>' + esc(pa.ratio || prm.ratio || '9:16') + '</span><span>字幕 ' + (pa.subtitle !== false ? '开' : '关') + '</span><span>配乐 ' + vol + '%</span><span>闪避 ' + (pa.duck_depth != null ? pa.duck_depth : prm.duck_depth) + '</span></div>' +
    '<pre class="st-fflog">' + esc(w.log || '等压制…') + '</pre></div>' +
    '<button class="btn mini ghost st-mon-run" data-runpart="ffmpeg">▶ 仅重跑 FFmpeg 压制</button></div>';
}
function stComposeBody(p, m) {
  var prm = m.params || {}, j = studioJob();
  return '<div class="st-badgenote">Claude Code + 网页动效 + PPT + FFmpeg · 不依赖生图模块</div>' +
    '<div class="st-comp-top"><div class="st-comp-opts">' +
    '<label class="st-check"><input type="checkbox" data-p="subtitle"' + (prm.subtitle !== false ? ' checked' : '') + '> 硬字幕</label>' +
    '<label class="st-check"><input type="checkbox" data-p="cc_drive"' + (prm.cc_drive !== false ? ' checked' : '') + '> 用 Claude Code 写网页动效（会消耗额度）</label>' +
    '<span class="st-lab">画幅</span><div class="seg st-seg"><button data-muxratio="9:16" aria-pressed="' + ((prm.ratio || p.ratio) !== '16:9') + '">9:16</button><button data-muxratio="16:9" aria-pressed="' + ((prm.ratio || p.ratio) === '16:9') + '">16:9</button></div>' +
    '<label class="st-f"><span class="st-lab">配乐音量</span><input class="inp" data-p="bgm_volume" type="number" min="0" max="60" step="5" value="' + Math.round((+prm.bgm_volume || .18) * 100) + '"></label>' +
    '<label class="st-f"><span class="st-lab">闪避</span><input class="inp" data-p="duck_depth" type="number" min="0" max="1" step="0.05" value="' + (+prm.duck_depth || .16) + '"></label>' +
    '<label class="st-f"><span class="st-lab">淡出秒</span><input class="inp" data-p="fade" type="number" min="0" max="6" step="0.5" value="' + (+prm.fade || 2) + '"></label>' +
    '<label class="st-f"><span class="st-lab">FPS</span><input class="inp" data-p="fps" type="number" min="12" max="30" value="' + (+prm.fps || 24) + '"></label></div>' +
    '<div class="st-row2"><button class="btn primary" data-run="' + esc(m.id) + '">▶ 一键合成（三窗同时开工）</button><button class="btn mini ghost" data-act="openout">打开输出文件夹</button></div></div>' +
    '<div class="st-monitor">' + stMonA(j) + stMonB(j) + stMonC(j, m) + '</div>' +
    '<div class="st-outlabel">成片</div>' + stVideos(p, m) + stListBox(p, '视频渲染清单.md');
}

/* ---------- 模块 7 ---------- */
function stPublishBody(p, m) {
  var prm = m.params || {}, files = p.files || {}, video = files.video, cover = files.cover;
  var tags = (prm.tags || p.tags || []).join ? (prm.tags || p.tags || []).join(' ') : (prm.tags || '');
  var pub = (studioSt() && studioSt().publish) || {};
  return (p.video_ok && video ? '<video class="st-video" controls preload="metadata" src="' + esc(video.url || stMedia(p.id, video.rel)) + '"></video><div class="st-vinfo"><span>' + esc(p.resolution || '') + ' · ' + (+p.duration || 0).toFixed(1) + ' 秒</span><span>' + stSize(video.size) + '</span></div>' : '<div class="st-vempty"><b>成片会在这里</b><span>先在模块 6 一键合成</span></div>') +
    (cover ? '<button class="st-cover" data-lbpublish="1"><img src="' + esc(cover.url || stAsset(p.id, cover.rel)) + '" alt=""><span>封面 · 点开看大图</span></button>' : '') +
    '<div class="st-row"><label class="st-lab">标题</label><input class="inp" data-p="title" maxlength="30" value="' + esc(prm.title || p.title || '') + '"></div>' +
    '<textarea class="inp" data-p="desc" rows="2" spellcheck="false" placeholder="简介">' + esc(prm.desc || p.desc || '') + '</textarea>' +
    '<input class="inp" data-p="tags" value="' + esc(tags) + '" placeholder="话题 空格隔开">' +
    '<div class="st-subrow"><select data-p="mode">' + stSelect([['single', '单条送审'], ['batch', '加入批量清单']], prm.mode || 'single') + '</select>' +
    '<select data-p="cover"><option value="auto">封面自动</option></select></div>' +
    '<div class="st-row2"><label class="st-f"><span class="st-lab">定时发布</span><input class="inp" data-p="schedule" type="datetime-local" value="' + esc(prm.schedule || '') + '"></label>' +
    '<select data-p="declaration">' + ['内容由AI生成', '内容自行拍摄', '内容取材网络', '虚构演绎，仅供娱乐', '可能引人不适', '危险行为，请勿模仿'].map(function (x) {
      return '<option' + ((prm.declaration || '内容由AI生成') === x ? ' selected' : '') + '>' + x + '</option>'; }).join('') + '</select></div>' +
    '<input class="inp" data-p="collection" value="' + esc(prm.collection || '') + '" placeholder="合集（可空）">' +
    '<button class="btn primary st-wide" data-act="publish">送去发布（进待确认队列）</button>' +
    '<div class="st-hint">待确认 ' + (pub.pending || 0) + ' 条 · 批量 ' + (pub.batch || 0) + ' 条。绝不会自动点发送。</div>';
}

function stBody(p, m) {
  if (m.id === 'script') return stScriptBody(p, m);
  if (m.id === 'image') return stImageBody(p, m);
  if (m.id === 'voice-white' || m.id === 'voice-zisu') return stVoiceBody(p, m);
  if (m.id === 'bgm') return stBgmBody(p, m);
  if (m.id === 'compose') return stComposeBody(p, m);
  if (m.id === 'publish') return stPublishBody(p, m);
  return '';
}
function stModuleHTML(p, m) { return stModule(m, stBody(p, m)); }

/* ---------- 画布 ---------- */
function renderCanvas(force) {
  var p = studioProj(); if (!p) return;
  var w = $('#stWorld'); if (!w) return;
  var mods = stMods(), seen = {};
  var mx = 1900, my = 1900;
  mods.forEach(function (m) { mx = Math.max(mx, +m.x + +m.w + 200); my = Math.max(my, +m.y + +m.h + 200); });
  w.style.width = mx + 'px'; w.style.height = my + 'px';
  mods.forEach(function (m) {
    seen[m.id] = 1;
    var el = w.querySelector('[data-node="' + m.id + '"]');
    var html = stModuleHTML(p, m);
    if (!el) { w.insertAdjacentHTML('beforeend', html); STUDIO.nodeSig[m.id] = html; return; }
    if (force || STUDIO.nodeSig[m.id] !== html) {
      var ae = document.activeElement;
      var inside = !!(ae && el.contains(ae) && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName));
      if (inside && !force) { syncOne(el, m); return; }
      el.outerHTML = html; STUDIO.nodeSig[m.id] = html;
    } else syncOne(el, m);
  });
  w.querySelectorAll('[data-node]').forEach(function (el) { if (!seen[el.getAttribute('data-node')]) el.remove(); });
  applyCanvas();
}
function syncOne(el, m) {
  var lamp = el.querySelector('[data-lamp]'); if (lamp) lamp.className = 'st-lamp st-' + stStatus(m);
  var f = el.querySelector('[data-pmsg]'); if (f) f.textContent = String(m.error || (m.status === 'ok' ? '已完成' : m.status === 'stale' ? '要重做' : '待命')).slice(0, 60);
}
function applyCanvas() {
  var w = $('#stWorld'); if (!w) return;
  w.style.transform = 'translate(' + STUDIO.canvas.x + 'px,' + STUDIO.canvas.y + 'px) scale(' + STUDIO.canvas.s + ')';
  var tip = $('.st-canvas-tip'); if (tip) tip.textContent = Math.round(STUDIO.canvas.s * 100) + '% · 空白拖动平移 · 滚轮缩放 · 模块可拖动、右下角缩放';
}
function stBounds() {
  var ns = stMods(); if (!ns.length) return { x: 0, y: 0, w: 1800, h: 1900 };
  var x1 = 1e9, y1 = 1e9, x2 = -1e9, y2 = -1e9;
  ns.forEach(function (n) { x1 = Math.min(x1, +n.x); y1 = Math.min(y1, +n.y); x2 = Math.max(x2, +n.x + +n.w); y2 = Math.max(y2, +n.y + +n.h); });
  return { x: x1, y: y1, w: Math.max(200, x2 - x1), h: Math.max(200, y2 - y1) };
}
function fitCanvas() {
  var c = $('#stCanvas'); if (!c) return;
  var b = stBounds(), vw = c.clientWidth, vh = c.clientHeight;
  var s = Math.min((vw - 36) / b.w, (vh - 36) / b.h);
  s = Math.max(.22, Math.min(1.1, s));
  STUDIO.canvas.s = s;
  STUDIO.canvas.x = Math.round((vw - b.w * s) / 2 - b.x * s);
  STUDIO.canvas.y = Math.round((vh - b.h * s) / 2 - b.y * s);
  STUDIO.canvas.auto = true; applyCanvas(); saveView();
}
function saveView() { if (typeof saveUI === 'function') saveUI({ studioView4: { x: STUDIO.canvas.x, y: STUDIO.canvas.y, s: STUDIO.canvas.s } }); }

/* ---------- 数据 ---------- */
function stApi(path, body, timeout) {
  if (!useLive()) { toast('演示模式：连上后端才能用'); return Promise.reject(new Error('demo')); }
  return api('POST', '/api/studio/' + path, body || {}, timeout || 120000);
}
function stSaveModule(mid, patch, quiet) {
  var p = studioProj(); if (!p) return Promise.resolve();
  clearTimeout(STUDIO.saveT[mid]);
  function go() {
    var pr = stApi('module/update', { pid: p.id, id: mid, params: patch }, 30000).then(function (j) {
      if (j.project && STUDIO.st) STUDIO.st.project = j.project;
      if (!quiet) { STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }
      return j;
    }).catch(function (e) { toast(e.message, 8000); throw e; });
    STUDIO.saving = pr;
    pr.then(function () { if (STUDIO.saving === pr) STUDIO.saving = null; }, function () { if (STUDIO.saving === pr) STUDIO.saving = null; });
    return pr;
  }
  if (quiet === 'debounce') return new Promise(function (r) { STUDIO.saveT[mid] = setTimeout(function () { go().then(r, r); }, 550); });
  return go();
}
function stCollect(mid) {
  var el = document.querySelector('[data-node="' + mid + '"]'); if (!el) return {};
  var o = {};
  el.querySelectorAll('[data-p]').forEach(function (x) {
    var k = x.getAttribute('data-p');
    if (x.type === 'checkbox') o[k] = !!x.checked;
    else if (x.type === 'range') o[k] = (+x.value || 0) / 100;
    else o[k] = x.value;
  });
  var m = stModMap()[mid];
  if (m && (mid === 'voice-white' || mid === 'voice-zisu')) {
    var lines = [];
    el.querySelectorAll('[data-line]').forEach(function (row) {
      var old = (m.params.lines || [])[+row.getAttribute('data-line')] || {};
      lines.push({ id: old.id || ('l' + (lines.length + 1)), line_index: old.line_index || lines.length + 1,
        text: (row.querySelector('[data-line-text]') || {}).value || '', tone: (row.querySelector('[data-line-tone]') || {}).value || '',
        speaker: old.speaker || '', engine: old.engine || 'auto' });
    });
    o.lines = lines;
  }
  if (mid === 'image') ['n', 'gif_frames', 'gif_delay_ms', 'custom_w', 'custom_h', 'selected'].forEach(function (k) { if (o[k] != null) o[k] = +o[k] || 0; });
  if (mid === 'bgm') ['seconds', 'steps', 'seed'].forEach(function (k) { if (o[k] != null) o[k] = +o[k] || 0; });
  if (mid === 'compose') ['duck_depth', 'fade', 'fps'].forEach(function (k) { if (o[k] != null) o[k] = +o[k] || 0; });
  if (mid === 'compose' && o.bgm_volume != null) o.bgm_volume = (+o.bgm_volume || 0) / 100;
  return o;
}
function stSizeCheck(w, h) {
  w = +w; h = +h;
  if (!w || !h) return '宽和高都要填';
  if (w % 16 || h % 16) return '宽高必须是 16 的倍数';
  if (Math.max(w, h) > 3840) return '长边不能超过 3840';
  if (Math.max(w, h) / Math.min(w, h) > 3) return '长宽比不能超过 3:1';
  var px = w * h;
  if (px < 655360 || px > 8294400) return '总像素要在 655,360 – 8,294,400 之间';
  return '';
}
function stSizeHint(mid) {
  var el = document.querySelector('[data-node="' + mid + '"]'); if (!el) return;
  var w = el.querySelector('[data-p="custom_w"]'), h = el.querySelector('[data-p="custom_h"]');
  var o = el.querySelector('[data-sizeerr]'); if (o && w && h) { var msg = stSizeCheck(w.value, h.value); o.textContent = msg; o.style.color = msg ? 'var(--bad)' : 'var(--text3)'; }
}

/* ---------- 拖动/缩放/平移 ---------- */
function bindCanvas() {
  var cv = $('#stCanvas'); if (!cv || cv.dataset.bound === '1') return;
  cv.dataset.bound = '1';
  var space = false;
  document.addEventListener('keydown', function (e) { if (e.code === 'Space' && S.view === 'studio') space = true; });
  document.addEventListener('keyup', function (e) { if (e.code === 'Space') space = false; });
  cv.addEventListener('pointerdown', function (ev) {
    var rs = ev.target.closest('[data-rs]');
    if (rs && ev.button === 0) {
      var rm = stModMap()[rs.getAttribute('data-rs')];
      if (rm) { STUDIO.resize = { id: rm.id, x: ev.clientX, y: ev.clientY, w: +rm.w, h: +rm.h }; STUDIO.dragging = true; var rz = cv.querySelector('[data-node="' + rm.id + '"]'); if (rz) rz.style.zIndex = 9; cv.setPointerCapture(ev.pointerId); ev.preventDefault(); }
      return;
    }
    var hd = ev.target.closest('[data-drag]');
    if (hd && ev.button === 0) {
      var id = hd.getAttribute('data-drag'), m = stModMap()[id];
      if (m) { STUDIO.drag = { id: id, x: ev.clientX, y: ev.clientY, ox: +m.x, oy: +m.y }; STUDIO.dragging = true; var dz = cv.querySelector('[data-node="' + id + '"]'); if (dz) dz.style.zIndex = 9; cv.setPointerCapture(ev.pointerId); ev.preventDefault(); }
      return;
    }
    if (ev.target.closest('.st-node') || ev.target.closest('button,input,textarea,select,label,summary')) return;
    if (ev.button === 0 || ev.button === 1 || space) {
      STUDIO.pan = { x: ev.clientX, y: ev.clientY, ox: STUDIO.canvas.x, oy: STUDIO.canvas.y };
      STUDIO.canvas.auto = false; cv.setPointerCapture(ev.pointerId); ev.preventDefault();
    }
  });
  cv.addEventListener('pointermove', function (ev) {
    if (STUDIO.resize) {
      var m = stModMap()[STUDIO.resize.id]; if (!m) return;
      m.w = Math.max(300, Math.round(STUDIO.resize.w + (ev.clientX - STUDIO.resize.x) / STUDIO.canvas.s));
      m.h = Math.max(180, Math.round(STUDIO.resize.h + (ev.clientY - STUDIO.resize.y) / STUDIO.canvas.s));
      var el = cv.querySelector('[data-node="' + m.id + '"]'); if (el) { el.style.width = m.w + 'px'; el.style.height = m.h + 'px'; }
      return;
    }
    if (STUDIO.drag) {
      var m2 = stModMap()[STUDIO.drag.id]; if (!m2) return;
      m2.x = Math.round(STUDIO.drag.ox + (ev.clientX - STUDIO.drag.x) / STUDIO.canvas.s);
      m2.y = Math.round(STUDIO.drag.oy + (ev.clientY - STUDIO.drag.y) / STUDIO.canvas.s);
      var el2 = cv.querySelector('[data-node="' + m2.id + '"]'); if (el2) { el2.style.left = m2.x + 'px'; el2.style.top = m2.y + 'px'; }
      return;
    }
    if (STUDIO.pan) {
      STUDIO.canvas.x = Math.round(STUDIO.pan.ox + ev.clientX - STUDIO.pan.x);
      STUDIO.canvas.y = Math.round(STUDIO.pan.oy + ev.clientY - STUDIO.pan.y);
      applyCanvas();
    }
  });
  function up() {
    if (STUDIO.drag || STUDIO.resize) saveLayout(true);
    if (STUDIO.pan) saveView();
    STUDIO.dragging = false; STUDIO.drag = STUDIO.resize = STUDIO.pan = null;
  }
  cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
  cv.addEventListener('wheel', function (ev) {
    ev.preventDefault();
    var r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
    var wx = (mx - STUDIO.canvas.x) / STUDIO.canvas.s, wy = (my - STUDIO.canvas.y) / STUDIO.canvas.s;
    var f = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
    STUDIO.canvas.s = Math.max(.22, Math.min(2, STUDIO.canvas.s * f));
    STUDIO.canvas.x = mx - wx * STUDIO.canvas.s; STUDIO.canvas.y = my - wy * STUDIO.canvas.s;
    STUDIO.canvas.auto = false; applyCanvas(); saveView();
  }, { passive: false });
}
function saveLayout(now) {
  var p = studioProj(); if (!p) return;
  clearTimeout(STUDIO.layoutT);
  var snap = stMods().map(function (m) { return { id: m.id, x: m.x, y: m.y, w: m.w, h: m.h }; });
  function send() {
    if (!useLive()) return;
    STUDIO.layoutPending = true;
    stApi('module/layout', { pid: p.id, modules: snap }, 15000).catch(function () {}).then(function () { STUDIO.layoutPending = false; }, function () { STUDIO.layoutPending = false; });
  }
  if (now) send(); else STUDIO.layoutT = setTimeout(send, 450);
}
function syncMeta() {
  stMods().forEach(function (m) {
    var el = document.querySelector('[data-node="' + m.id + '"]'); if (!el) return;
    var lamp = el.querySelector('[data-lamp]'); if (lamp) lamp.className = 'st-lamp st-' + stStatus(m);
    var msg = el.querySelector('[data-pmsg]');
    if (msg) {
      var j = studioJob(), p = studioProj(), cur = j && j.st === 'run' && j.pid === (p && p.id) && j.step === m.id;
      msg.textContent = String((cur && j.msg) || m.error || (m.status === 'ok' ? '已完成' : m.status === 'stale' ? '要重做' : m.status === 'err' ? '出错' : '待命')).slice(0, 60);
    }
  });
  var nav = $('.nav[data-tool="studio"]'); if (nav) nav.classList.toggle('on-busy', studioRunning());
}

/* ---------- 动作 ---------- */
function stRun(mid, part) {
  var p = studioProj(); if (!p) { toast('还没有项目'); return; }
  var body = { pid: p.id };
  if (mid) body.id = mid;
  if (part) { body.id = 'compose'; body.part = part; }
  stApi('module/run', body, 180000).then(function (j) {
    if (j.project && STUDIO.st) STUDIO.st.project = j.project;
    toast(mid ? (part ? '开始仅重跑这一步' : '开始跑这个模块') : '白页 + 紫苏 + 配乐三路并行，随后进视频总成', 5000);
    studioFetch();
  }).catch(function (e) { toast(e.message, 9000); });
}
function stImport() {
  var t = $('#stImport'), f = $('#stImportFile'), p = studioProj(); if (!p) return;
  var text = t ? t.value : '';
  if (!text.trim() && f && f.files && f.files[0]) {
    var r = new FileReader(); r.onload = function () { if (t) t.value = r.result || ''; stImport(); };
    r.readAsText(f.files[0], 'utf-8'); return;
  }
  if (!text.trim()) { toast('把剧本贴进来，或者选一个 .md / .json 文件'); return; }
  stApi('script/import', { pid: p.id, text: text }, 60000).then(function (j) {
    if (j.state) STUDIO.st = j.state;
    var e = j.estimate || {};
    toast('导入好了：' + (j.summary || '') + ' · 5 份清单已生成 · 预估 $' + (e.image_usd || 0).toFixed(2), 9000);
    STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true);
  }).catch(function (e) { toast(e.message, 9000); });
}
function stPlan() {
  var p = studioProj(); if (!p) return;
  var m = stModMap()['script'], prm = m.params || {};
  stApi('script/plan', { pid: p.id, topic: prm.topic || prm.source_text || '', seconds: p.target_seconds || 75 }, 180000).then(function (j) {
    if (j.state) STUDIO.st = j.state;
    toast('拆好了：' + (j.summary || '') + ' · 5 份清单已生成', 9000);
    STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true);
  }).catch(function (e) { toast(e.message, 9000); });
}
function stSaveList(name) {
  var p = studioProj(); if (!p) return;
  var ta = document.querySelector('[data-list="' + name + '"]'); if (!ta) return;
  api('PUT', '/api/studio/list', { pid: p.id, name: name, text: ta.value }, 30000).then(function (j) {
    if (j.state) STUDIO.st = j.state;
    toast('清单保存了，对应模块按新内容重做', 5000);
    STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true);
  }).catch(function (e) { toast(e.message, 9000); });
}
function stRegenLists() {
  var p = studioProj(); if (!p) return;
  stApi('module/run', { pid: p.id, id: 'script' }, 60000).then(function () { toast('5 份清单已按当前内容重新生成', 5000); studioFetch(); }).catch(function (e) { toast(e.message, 8000); });
}
function stPublish() {
  var p = studioProj(); if (!p) return;
  var m = stModMap()['publish'], prm = m.params || {};
  var ta = document.querySelector('[data-node="publish"] [data-p="tags"]');
  var tags = ta ? ta.value : '';
  api('POST', '/api/studio/to_publish', { pid: p.id, mode: prm.mode || 'single', title: prm.title || p.title, desc: prm.desc || p.desc,
    tags: tags, schedule: prm.schedule || '', cover: prm.cover || 'auto', declaration: prm.declaration || '内容由AI生成', collection: prm.collection || '' }, 30000)
    .then(function (j) { toast(j.msg || '已送去发布队列', 9000); studioFetch(); }).catch(function (e) { toast(e.message, 9000); });
}
function studioPlay(url) {
  if (!url) { toast('还没有可听的音频'); return; }
  if (STUDIO.audio) { try { STUDIO.audio.pause(); } catch (e) {} }
  STUDIO.audio = new Audio(url);
  STUDIO.audio.play().catch(function (e) { toast('放不了：' + e.message); });
}
function studioDo(path, body, ok) {
  if (!useLive()) { toast('演示模式：连上后端才能用'); return Promise.reject(); }
  return api('POST', '/api/studio/' + path, body || {}, 30000).then(function (j) {
    if (j && j.project) { STUDIO.st.project = j.project; STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }
    if (ok) toast(ok, 5000);
    return j;
  }).catch(function (e) { toast(e.message, 8000); throw e; });
}
function studioFetch() {
  if (!useLive()) { renderStudio(); return Promise.resolve(); }
  if (STUDIO.fetching) return STUDIO.fetching;
  if (STUDIO.dragging || STUDIO.layoutPending || STUDIO.saving) return Promise.resolve();
  STUDIO.fetching = fetch('/api/studio/state', { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('state ' + r.status); return r.json(); }).then(function (j) {
    var was = STUDIO.st && STUDIO.st.job && STUDIO.st.job.st === 'run' ? STUDIO.st.job : null;
    var oldPid = STUDIO.lastPid;
    STUDIO.st = j;
    if (j.project && j.project.id !== oldPid) {
      STUDIO.lastPid = j.project.id; STUDIO.canvas.auto = true; STUDIO.fitted = false; STUDIO.nodeSig = {}; STUDIO.sig = {};
      setTimeout(function () { if (S.view === 'studio') fitCanvas(); }, 30);
    }
    if (was && j.job && j.job.id === was.id && j.job.st !== 'run') toast('视频工坊：' + (j.job.msg || j.job.st), 7000);
    renderStudio();
  }).catch(function () { if (S.view === 'studio' && !STUDIO.st) setTimeout(studioFetch, 1200); })
    .then(function () { STUDIO.fetching = null; }, function () { STUDIO.fetching = null; });
  return STUDIO.fetching;
}
function studioEnter() {
  studioFetch(); stHWStart(); clearInterval(STUDIO.t);
  STUDIO.t = setInterval(function () { if (S.view === 'studio') studioFetch(); }, 1300);
  setTimeout(function () { if (S.view === 'studio' && !STUDIO.st) studioFetch(); }, 700);
}
function studioLeave() {
  clearInterval(STUDIO.t); STUDIO.t = null; stHWStop();
  if (STUDIO.audio) { try { STUDIO.audio.pause(); } catch (e) {} }
  $$('#view-studio video').forEach(function (m) { try { m.pause(); } catch (e) {} });
}

/* ---------- 事件 ---------- */
function stUploadRefs(files, mid) {
  var p = studioProj(), m = stModMap()[mid]; if (!p || !m) return;
  var cur = (m.params.refs || []).slice();
  var list = [].slice.call(files || []).slice(0, Math.max(0, 16 - cur.length));
  function one(file) {
    return new Promise(function (resolve) {
      var r = new FileReader();
      r.onload = function () {
        api('POST', '/api/studio/ref', { pid: p.id, name: file.name, data: r.result }, 30000)
          .then(function (j) { if (j.rel) cur.push(j.rel); resolve(); })
          .catch(function (e) { toast('「' + file.name + '」没放进去：' + e.message, 7000); resolve(); });
      };
      r.onerror = function () { resolve(); }; r.readAsDataURL(file);
    });
  }
  list.reduce(function (pr, f) { return pr.then(function () { return one(f); }); }, Promise.resolve()).then(function () {
    stSaveModule(mid, { refs: cur }).then(function () { toast('参考图放好了（' + cur.length + '/16）'); }).catch(function () {});
  });
}

(function () {
  var v = $('#view-studio'); if (!v) return;
  v.addEventListener('focusin', function (ev) { if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) STUDIO.editing = true; });
  v.addEventListener('focusout', function (ev) {
    if (!/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    setTimeout(function () {
      var a = document.activeElement;
      STUDIO.editing = !!(a && a.closest && a.closest('#view-studio') && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
      if (STUDIO.editing || STUDIO.dragging) return;
      var node = ev.target.closest && ev.target.closest('[data-node]');
      if (node) {
        var mid = node.getAttribute('data-node'), m = stModMap()[mid];
        if (m) stSaveModule(mid, stCollect(mid), true);
      }
      STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true);
    }, 160);
  });
  v.addEventListener('input', function (ev) {
    var t = ev.target, node = t.closest && t.closest('[data-node]');
    if (!node) return;
    var mid = node.getAttribute('data-node');
    if (t.hasAttribute('data-list')) return;
    if (t.hasAttribute('data-line-text') || t.hasAttribute('data-line-tone')) { stSaveModule(mid, { lines: stCollect(mid).lines }, 'debounce'); return; }
    if (!t.hasAttribute('data-p')) return;
    var k = t.getAttribute('data-p');
    if (k === 'custom_w' || k === 'custom_h') stSizeHint(mid);
    var patch = {}; patch[k] = t.type === 'checkbox' ? !!t.checked : t.value;
    stSaveModule(mid, patch, 'debounce');
  });
  v.addEventListener('change', function (ev) {
    var t = ev.target, node = t.closest && t.closest('[data-node]');
    if (t.id === 'stProj') { if (t.value) studioDo('select', { pid: t.value }).then(function (j) { STUDIO.st = j; STUDIO.lastPid = j.project && j.project.id; STUDIO.canvas.auto = true; STUDIO.fitted = false; STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {}); return; }
    if (t.id === 'stImportFile') { stImport(); return; }
    if (t.getAttribute('data-ref-file')) { stUploadRefs(t.files, t.getAttribute('data-ref-file')); t.value = ''; return; }
    if (!node) return;
    var mid = node.getAttribute('data-node');
    if (t.hasAttribute('data-p')) {
      var k = t.getAttribute('data-p');
      var patch = {}; patch[k] = t.type === 'checkbox' ? !!t.checked : t.value;
      if (mid === 'image') ['n', 'gif_frames', 'gif_delay_ms', 'custom_w', 'custom_h', 'selected'].forEach(function (x) { if (patch[x] != null) patch[x] = +patch[x] || 0; });
      if (mid === 'compose' && k === 'bgm_volume') patch[k] = (+t.value || 0) / 100;
      stSaveModule(mid, patch).then(function () { if (k === 'resolution' || k === 'selected') { STUDIO.nodeSig = {}; renderStudio(true); } }).catch(function () {});
    }
  });
  v.addEventListener('click', function (ev) {
    var b = ev.target.closest('button'); if (!b || b.disabled) return;
    var d = b.dataset, p = studioProj(), m = p && stModMap();
    if (d.st) {
      if (d.st === 'fit') { fitCanvas(); return; }
      if (d.st === 'new') { studioDo('new', { topic: '', ratio: '9:16', seconds: 75, voice_id: 'local:preset:Vivian' }, '新建了空白项目').then(function (j) { STUDIO.st = j; STUDIO.lastPid = j.project && j.project.id; STUDIO.canvas.auto = true; STUDIO.fitted = false; STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {}); return; }
      if (d.st === 'run') { stRun(); return; }
      if (d.st === 'stop') { studioDo('stop', {}, '停下中：当前这一步收尾后不再往下做').then(studioFetch).catch(function () {}); return; }
      return;
    }
    if (d.run) { stRun(d.run); return; }
    if (d.runpart) { stRun('compose', d.runpart); return; }
    if (d.out) { var z = String(d.out).split(':'); stSaveModule(z[0], { output: z[1] }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {}); return; }
    if (d.muxratio) { var nn = b.closest('[data-node]'); stSaveModule(nn.getAttribute('data-node'), { ratio: d.muxratio }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }); return; }
    if (d.act === 'plan') { stPlan(); return; }
    if (d.act === 'importToggle') { var box = $('#stImportBox'); if (box) box.hidden = !box.hidden; return; }
    if (d.act === 'importCancel') { var b2 = $('#stImportBox'); if (b2) b2.hidden = true; return; }
    if (d.act === 'import') { stImport(); return; }
    if (d.act === 'lists') { stRegenLists(); return; }
    if (d.act === 'publish') { stPublish(); return; }
    if (d.act === 'openout') { studioDo('open', { what: 'output' }, '打开输出文件夹').catch(function () {}); return; }
    if (d.listsave) { stSaveList(d.listsave); return; }
    if (d.lb) { var q = String(d.lb).split(':'); var mm = m[q[0]]; if (mm) stLbOpen(p, mm, q[1], +q[2] || 0); return; }
    if (d.lbmon) { var w = (studioJob() || {}).web || {}; if (w.preview_rel) Lightbox.open([{ url: stMedia(p.id, w.preview_rel), name: '网页动效预览', rel: w.preview_rel, pid: p.id }], 0); return; }
    if (d.lbslide) { var pw = (studioJob() || {}).ppt || {}; var rel = (pw.slides || [])[+d.lbslide]; if (rel) Lightbox.open([{ url: stAsset(p.id, rel), name: rel, rel: rel, pid: p.id }], 0); return; }
    if (d.lbpublish) { var cv = (p.files || {}).cover; if (cv) Lightbox.open([{ url: stAsset(p.id, cv.rel), name: cv.name, rel: cv.rel, pid: p.id }], 0); return; }
    if (d.play) { var pz = String(d.play).split(':'), ma = m[pz[0]], aus = ma ? (ma.outputs || []).filter(function (x) { return x.kind === 'audio'; }) : []; var ao = aus[+pz[1] || 0]; if (ao) studioPlay(stAsset(p.id, ao.rel)); else toast('还没有音频'); return; }
    if (d.lineplay) { var lz = String(d.lineplay).split(':'), lm = m[lz[0]], la = lm ? (lm.outputs || []).filter(function (x) { return x.kind === 'audio'; }) : []; var lo = la[+lz[1]]; if (lo) studioPlay(stAsset(p.id, lo.rel)); else toast('这一句还没配音：点上面的「单独运行本角色配音」'); return; }
    if (d.lineadd) { var lm2 = m[d.lineadd], ls = (lm2.params.lines || []).slice(); ls.push({ id: 'l' + (ls.length + 1), line_index: (ls.length ? Math.max.apply(null, ls.map(function (x) { return +x.line_index || 0; })) + 1 : 1), text: '', tone: '' }); stSaveModule(d.lineadd, { lines: ls }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }); return; }
    if (d.linedel) { var dz = String(d.linedel).split(':'), dm = m[dz[0]], dl = (dm.params.lines || []).slice(); dl.splice(+dz[1], 1); stSaveModule(dz[0], { lines: dl }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }); return; }
    if (d.bulk) { var bx = $('#stBulk-' + d.bulk); if (bx) bx.open = !bx.open; return; }
    if (d.bulkgo) {
      var ta = document.querySelector('#stBulk-' + d.bulkgo + ' [data-bulk-text]');
      var raw = ta ? String(ta.value || '').split(/\r?\n/) : [];
      var ls2 = raw.map(function (x) { return x.trim(); }).filter(Boolean).map(function (x, i) { return { id: 'l' + (i + 1), line_index: i + 1, text: x, tone: '' }; });
      if (!ls2.length) { toast('先把台词一行一句贴进来'); return; }
      stSaveModule(d.bulkgo, { lines: ls2 }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); toast('台词换了 ' + ls2.length + ' 句'); }); return;
    }
    if (d.refdel) { var rz = String(d.refdel).split(':'), rm = m[rz[0]], refs = (rm.params.refs || []).slice(); refs.splice(+rz[1], 1); stSaveModule(rz[0], { refs: refs }).catch(function () {}); return; }
  });
})();
