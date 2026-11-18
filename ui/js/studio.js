'use strict';
/* ================= 视频工坊 · 自由节点画布（v3.9.0 / R10）=================
   节点不是固定 8 张卡片：工程里存 graph.nodes + graph.edges。左边输入口、右边输出口；
   从输出口拖到兼容的输入口就连上，点连线断开。画布可平移缩放，「适应窗口」一键看全。
   节点：剧本/生图/配音/配乐/网页动效/PPT/混流/发布；前三个固定节点不能删。
   数据都在后端 /api/studio/graph/*，这里只画和收集参数。 */
var ST_STYLE = '知识科普 × 科技数码 × 搞笑段子';
var ST_ROLES = ['白页', '紫苏', '旁白'];
var ST_RATIOS = ['9:16', '16:9', '1:1', '3:4', '4:3', '2:3', '3:2'];
var ST_TYPES = ['image', 'voice', 'bgm', 'web', 'ppt'];
var ST_TYPE_LABEL = { script: '剧本', image: '生图', voice: '配音', bgm: '配乐', web: '网页动效', ppt: 'PPT', mux: '混流', publish: '发布' };
var ST_PORTS = {
  script: { in: [], out: [['text', 'text']] },
  image: { in: [['prompt', 'text'], ['ref', 'image']], out: [['image', 'image']] },
  voice: { in: [['text', 'text']], out: [['audio', 'audio'], ['timeline', 'timeline']] },
  bgm: { in: [['text', 'text']], out: [['audio', 'audio']] },
  web: { in: [['image', 'image'], ['text', 'text'], ['audio', 'audio']], out: [['video', 'video']] },
  ppt: { in: [['text', 'text'], ['image', 'image']], out: [['image', 'image']] },
  mux: { in: [['image', 'image'], ['audio', 'audio'], ['video', 'video'], ['text', 'text']], out: [['video', 'video']] },
  publish: { in: [['video', 'video'], ['image', 'image'], ['text', 'text']], out: [] }
};
var ST_FIXED = { script: 1, mux: 1, publish: 1 };
var ST_DEFAULT_SIZE = { script: [340, 430], image: [360, 580], voice: [390, 500], bgm: [330, 340], web: [370, 470], ppt: [350, 420], mux: [370, 440], publish: [380, 520] };
var STUDIO = {
  st: null, t: null, hwT: null, hwBusy: false, pid: '', busy: false, editing: false, dragging: false,
  topic: '', sig: {}, saveT: {}, layoutT: null, saving: null, audio: null, fitted: false,
  canvas: { x: 20, y: 20, s: 1, auto: true }, link: null, drag: null, resize: null, pan: null,
  edgeSig: '', nodeSig: {}, fetching: null, autoPlay: '', lastPid: '', addAt: null
};
try {
  if (U.studioGraphView && typeof U.studioGraphView === 'object') {
    STUDIO.canvas.x = +U.studioGraphView.x || 20; STUDIO.canvas.y = +U.studioGraphView.y || 20;
    STUDIO.canvas.s = Math.max(.3, Math.min(2, +U.studioGraphView.s || 1));
    STUDIO.canvas.auto = false;
  }
} catch (e) {}

function studioSt() { return useLive() ? STUDIO.st : stDemo(); }
function studioProj() { var s = studioSt(); return s && s.project; }
function studioJob() { var s = studioSt(); return s && s.job; }
function studioRunning() { var j = studioJob(); return !!(j && j.st === 'run'); }
function stGraph() { var p = studioProj(); return (p && p.graph) || { nodes: [], edges: [] }; }
function stNodeMap() { var m = {}; (stGraph().nodes || []).forEach(function (n) { m[n.id] = n; }); return m; }
function stSize(b) { b = +b || 0; return b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' KB'; }
function stMediaUrl(pid, rel, ver) {
  if (!rel) return '';
  return '/api/studio/media?pid=' + encodeURIComponent(pid) + '&path=' + encodeURIComponent(rel) + '&v=' + (ver || 0);
}
function stOutUrl(p, rel) { return '/api/studio/asset?pid=' + encodeURIComponent((p && p.id) || '') + '&path=' + encodeURIComponent(rel || ''); }
function stPut(id, html) { if (STUDIO.sig[id] === html) return; var el = $('#' + id); if (!el) return; STUDIO.sig[id] = html; el.innerHTML = html; }
function stSet(id, v) { var e = $('#' + id); if (e && e.textContent !== v) e.textContent = v; }

/* ---------- 演示数据 ---------- */
function stDemo() {
  var p = {
    id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', desc: '这一期讲讲普通人马上能用的三个 AI 用法。',
    tags: ['AI', '效率工具'], ratio: '9:16', target_seconds: 75, topic: '', bgm_prompt: 'upbeat electronic, no vocals',
    settings: { img_model: 'gpt-image-2.5-sunburst-vip', role_voices: { 白页: 'local:preset:Serena', 紫苏: 'local:preset:Dylan' } },
    files: {}, shots: [], duration: 0, resolution: '', video_ok: false, dir: 'F:\\Agent\\工作区\\视频工坊\\演示项目'
  };
  var g = { nodes: [], edges: [] };
  function n(id, type, x, y, params, title) {
    var s = ST_DEFAULT_SIZE[type] || [340, 400];
    g.nodes.push({ id: id, type: type, title: title, x: x, y: y, w: s[0], h: s[1], params: params, outputs: [], status: 'idle', error: '', cache_hit: false });
  }
  n('script', 'script', 40, 40, { topic: '三个被低估的 AI 用法' }, '剧本与策划');
  n('image-1', 'image', 420, 40, { prompt: '暖光书桌前的年轻人，竖屏中景', model: 'gpt-image-2.5-sunburst-vip', ratio: '9:16', resolution: '2k', quality: 'high', complexity: 'medium', n: 1, output: 'normal', format: 'png', refs: [] }, '生图 #1');
  n('voice-1', 'voice', 820, 40, { role: '白页', speaker: 'local:preset:Serena', engine: 'auto', tone: '冷静吐槽', lines: [{ id: 'l1', text: '先说一个反常识的结论。', tone: '' }] }, '配音·白页');
  n('voice-2', 'voice', 820, 570, { role: '紫苏', speaker: 'local:preset:Dylan', engine: 'auto', tone: '轻松调侃', lines: [{ id: 'l1', text: '等等，这也太离谱了吧？', tone: '' }] }, '配音·紫苏');
  n('bgm-1', 'bgm', 1240, 40, { prompt: 'upbeat electronic, no vocals', seconds: 75, steps: 8, seed: 20261118 }, '背景配乐 #1');
  n('web-1', 'web', 420, 640, { bg: 'dark', sub_pos: 'bottom', fps: 24, duration: 6, text: '', motion: 1 }, '网页动效渲染 #1');
  n('ppt-1', 'ppt', 40, 500, { file: '', text: '', points: [] }, 'PPT/OnlyOffice 卡片 #1');
  n('mux', 'mux', 1240, 400, { subtitle: true, ratio: '9:16', bgm_volume: .18, duck_depth: .16, fade: 2, kenburns: true }, 'FFmpeg 混流压制');
  n('publish', 'publish', 1640, 400, { title: '三个被低估的 AI 用法', desc: '', tags: ['AI'], mode: 'single', declaration: '内容由AI生成' }, '发布与排期');
  p.graph = g;
  return { projects: [{ id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', created: '2026-11-18 02:00:00', ratio: '9:16', st: 'idle', shots: 3, video: false }],
    active: 'demo', project: p, job: null, voices: [
      { id: 'local:preset:Vivian', label: 'Vivian · 女声 · 明亮', engine: 'local' },
      { id: 'local:preset:Serena', label: 'Serena · 女声 · 温柔', engine: 'local' },
      { id: 'local:preset:Dylan', label: 'Dylan · 男声 · 北京青年', engine: 'local' },
      { id: 'local:preset:Uncle_Fu', label: 'Uncle_Fu · 男声 · 低沉', engine: 'local' }],
    models: [{ id: 'gpt-image-2.5-sunburst-vip', name: 'GPT Image 2.5 Sunburst VIP', vendor: 'OpenAI', gif: true, svg: true, price: .03 }],
    style_tag: ST_STYLE, roles: ST_ROLES, publish: { pending: 0, batch: 0 }, node_name: ST_TYPE_LABEL };
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
    '<div class="st-addmenu" id="stAddMenu" hidden></div>' +
    '<div class="st-canvas-tip">空白拖动平移 · 滚轮缩放 · 拖输出口到输入口连线 · 点线断开</div></div></div>';
}

function renderStudio(force) {
  var v = $('#view-studio'); if (!v) return;
  if (!v.querySelector('.st')) { v.innerHTML = studioShell(); STUDIO.sig = {}; STUDIO.nodeSig = {}; bindCanvas(); }
  if ((STUDIO.editing || STUDIO.dragging) && !force) { syncStudioMeta(); return; }
  if (force) { STUDIO.nodeSig = {}; }
  renderStTop();
  renderStCanvas();
  syncStudioMeta();
  if (!STUDIO.fitted && STUDIO.canvas.auto) { STUDIO.fitted = true; fitCanvas(); }
}

/* ---------- 顶部 ---------- */
function renderStTop() {
  var s = studioSt() || {}, ps = (s.projects) || [], p = s.project, run = studioRunning();
  var sel = '<select class="inp st-projsel" id="stProj" aria-label="切换项目">' + (ps.length ? ps.map(function (x) {
    return '<option value="' + esc(x.id) + '"' + (p && x.id === p.id ? ' selected' : '') + '>' + esc(x.title || x.name) + ' · ' + esc((x.created || '').slice(5, 16)) + '</option>';
  }).join('') : '<option value="">还没有项目</option>') + '</select>';
  var html = '<div class="st-brand"><b>视频工坊</b><span class="st-style">' + esc(ST_STYLE) + '</span></div>' +
    '<div class="st-proj"><label for="stProj">项目</label>' + sel + '<button class="btn mini ghost" data-st="new">新建</button></div>' +
    '<div class="st-acts"><button class="btn mini ghost" data-st="add" aria-haspopup="true">+ 添加节点</button>' +
    '<button class="btn mini ghost" data-st="fit">适应窗口</button>' +
    '<button class="btn primary st-runall" data-st="run"' + (run ? ' disabled' : '') + '>▶ 从头跑通全流程</button>' +
    '<button class="btn mini danger" data-st="stop"' + (run ? '' : ' disabled') + '>■ 停下</button></div>';
  stPut('stTop', html);
}

function stAddMenuHTML() {
  var labels = { image: '生图', voice: '配音', bgm: '背景配乐', web: '网页动效', ppt: 'PPT 卡片' };
  return '<div class="st-addtitle">加一个节点</div>' + ST_TYPES.map(function (t) {
    return '<button data-add="' + t + '"><b>' + labels[t] + '</b><span>' + (t === 'voice' ? '白页 / 紫苏音色可改' : t === 'image' ? '普通 / GIF / SVG' : '可单独运行') + '</span></button>';
  }).join('');
}

/* ---------- 硬件条 ---------- */
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
function stHWStart() { stHWStop(); if (document.visibilityState === 'hidden') return; stHWTick(); STUDIO.hwT = setInterval(stHWTick, 2000); }
function stHWStop() { if (STUDIO.hwT) clearInterval(STUDIO.hwT); STUDIO.hwT = null; }
document.addEventListener('visibilitychange', function () {
  if (!STUDIO.hwT && S.view === 'studio' && !document.hidden) stHWStart();
  else if (STUDIO.hwT && document.hidden) stHWStop();
});

/* ---------- 节点 ---------- */
function stPorts(type) { return ST_PORTS[type] || { in: [], out: [] }; }
function stStatus(n) {
  var j = studioJob(), p = studioProj();
  if (j && j.st === 'run' && j.pid === (p && p.id) && j.step === n.id) return 'run';
  if (n.status === 'ok' || n.status === 'warn') return 'done';
  if (n.status === 'err') return 'bad';
  if (n.status === 'stale') return 'stale';
  if (n.status === 'run') return 'run';
  return 'idle';
}
function stLamp(n) { return '<span class="st-lamp st-' + stStatus(n) + '" data-lamp="' + esc(n.id) + '"></span>'; }
function stOutList(n, kind) { return (n.outputs || []).filter(function (o) { return !kind || o.kind === kind; }); }
function stOutFirst(n, kind) { return stOutList(n, kind)[0] || null; }
function stLbOuts(p, n, kind) {
  return stOutList(n, kind).map(function (o) {
    return { url: stOutUrl(p, o.rel), name: o.rel, rel: o.rel, pid: p && p.id, cacheHit: !!n.cache_hit };
  });
}
function stOpenOuts(p, n, kind, i) {
  var items = stLbOuts(p, n, kind);
  if (!items.length) { toast('这个节点还没有' + (kind === 'image' ? '图' : '产出')); return; }
  if (window.Lightbox) Lightbox.open(items, Math.max(0, Math.min(items.length - 1, +i || 0)));
}
function stUpstream(n, port, type) {
  var g = stGraph(), m = stNodeMap(), out = [];
  (g.edges || []).forEach(function (e) {
    if (e.to !== n.id + '.' + port) return;
    var a = String(e.from).split('.'), up = m[a[0]];
    if (up) out.push(up);
  });
  return out;
}
function stUpImage(n) {
  var ups = stUpstream(n, 'image');
  for (var i = 0; i < ups.length; i++) {
    var o = stOutFirst(ups[i], 'image');
    if (o) return { node: ups[i], out: o };
  }
  return null;
}

function stNodeHeader(n) {
  var fixed = !!ST_FIXED[n.type], removed = !!(n.params && n.params.script_removed);
  return '<header class="st-node-h" data-drag="' + esc(n.id) + '"><span class="st-node-n st-t-' + esc(n.type) + '">' + esc(ST_TYPE_LABEL[n.type] || n.type) + '</span>' +
    '<b title="' + esc(n.title || '') + '">' + esc(n.title || n.id) + (removed ? ' · 剧本里已移除' : '') + '</b>' + stLamp(n) +
    '<button class="st-nrun" data-nrun="' + esc(n.id) + '" title="只跑这个节点">▶ 只跑</button>' +
    '<button class="st-del" data-ndel="' + esc(n.id) + '" title="' + (fixed ? '固定节点不能删' : '删除这个节点') + '"' + (fixed ? ' disabled' : '') + '>×</button></header>';
}
function stPortBar(n) {
  var p = stPorts(n.type), left = '', right = '';
  p.in.forEach(function (x, i) {
    left += '<span class="st-port in" data-inport="' + esc(n.id) + '.' + x[0] + '" data-pt="' + x[1] + '" style="top:' + (i * 20) + 'px" title="' + esc(x[1]) + '"><i></i>' + esc(x[1]) + '</span>';
  });
  p.out.forEach(function (x, i) {
    right += '<span class="st-port out" data-port="' + esc(n.id) + '.' + x[0] + '" data-pt="' + x[1] + '" style="top:' + (i * 20) + 'px" title="拖到兼容的输入口"><i></i>' + esc(x[1]) + '</span>';
  });
  var rows = Math.max(1, p.in.length, p.out.length);
  return '<div class="st-portbar" style="height:' + (rows * 20 + 8) + 'px">' + left + '<span class="sp"></span>' + right + '</div>';
}
function stNodeFooter(n) {
  var j = studioJob(), p = studioProj(), cur = j && j.st === 'run' && j.pid === (p && p.id) && j.step === n.id;
  var msg = (cur && j.msg) || n.error || (n.status === 'ok' ? '已完成' : n.status === 'stale' ? '要重做' : n.status === 'err' ? '出错' : '待命');
  return '<footer class="st-node-f">' + (n.cache_hit ? '<em class="st-tag ok">缓存命中</em>' : '') +
    '<span data-pmsg="' + esc(n.id) + '">' + esc(String(msg).slice(0, 46)) + '</span></footer>';
}

/* ---------- 各节点编辑器 ---------- */
function stModelOptions(cur) {
  var ms = (studioSt() && studioSt().models) || [], out = [];
  if (cur && !ms.some(function (m) { return m.id === cur; })) out.push('<option value="' + esc(cur) + '" selected>' + esc(cur) + '</option>');
  ms.forEach(function (m) {
    var price = m.price == null ? '' : ' · $' + (+m.price).toFixed(3) + '/张';
    out.push('<option value="' + esc(m.id) + '"' + (m.id === cur ? ' selected' : '') + '>' + esc((m.vendor ? m.vendor + ' · ' : '') + m.name + price + (m.gif ? ' · GIF' : '')) + '</option>');
  });
  return out.join('') || '<option value="">用设置里的默认模型</option>';
}
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
function stSelect(options, cur) {
  return options.map(function (x) { return '<option value="' + esc(x[0]) + '"' + (String(cur) === x[0] ? ' selected' : '') + '>' + esc(x[1]) + '</option>'; }).join('');
}
function stOutType(n) {
  var cur = n.params.output || 'normal';
  return '<div class="seg st-outtype" role="group" aria-label="出图类型">' + [['normal', '普通'], ['gif', 'GIF'], ['svg', 'SVG']].map(function (x) {
    return '<button data-out="' + esc(n.id) + ':' + x[0] + '" aria-pressed="' + (cur === x[0]) + '">' + x[1] + '</button>';
  }).join('') + '</div>';
}
function stRefsHTML(p, n) {
  var refs = n.params.refs || [];
  return '<div class="st-refs">' + refs.map(function (r, i) {
    var u = /^shot:/.test(String(r)) ? '' : stMediaUrl(p.id, r, 0);
    return '<span class="st-ref" title="' + esc(r) + '">' + (u ? '<img src="' + esc(u) + '" alt="">' : '<b>' + esc(r) + '</b>') +
      '<button data-refdel="' + esc(n.id) + ':' + i + '" title="移除">×</button></span>';
  }).join('') + '<label class="btn mini ghost st-file">+ 参考图<input type="file" accept="image/png,image/jpeg" multiple data-ref-file="' + esc(n.id) + '" hidden></label></div>';
}
function stOutputsHTML(p, n, kind, cls) {
  var outs = stOutList(n, kind);
  if (!outs.length) return '<div class="st-nohint">还没有产出</div>';
  return '<div class="st-outgrid ' + (cls || '') + '">' + outs.map(function (o, i) {
    if (kind === 'image') return '<button class="st-outthumb" data-lbout="' + esc(n.id) + ':image:' + i + '"><img src="' + esc(stOutUrl(p, o.rel)) + '" alt=""><span>' + esc(String(o.rel).split('/').pop()) + '</span></button>';
    if (kind === 'video') return '<video class="st-video" controls preload="metadata" src="' + esc(stOutUrl(p, o.rel)) + '"></video>';
    return '';
  }).join('') + '</div>';
}
function stAudioRow(p, n) {
  var outs = stOutList(n, 'audio');
  if (!outs.length) return '<div class="st-nohint">还没有音频</div>';
  return '<div class="st-audios">' + outs.map(function (o, i) {
    return '<div class="st-audio"><button class="btn mini ghost" data-playout="' + esc(n.id) + ':' + i + '">▶ 听</button><span>' + esc(String(o.rel).split('/').pop()) + (o.duration ? ' · ' + (+o.duration).toFixed(1) + ' 秒' : '') + '</span></div>';
  }).join('') + '</div>';
}

function stScriptHTML(p, n) {
  var prm = n.params || {};
  return '<textarea class="inp st-topic" data-p="source_text" rows="3" spellcheck="false" placeholder="写主题，或者把完整口播文案贴进来（这里只存文字，拆成节点用下面的按钮）">' + esc(prm.source_text || prm.topic || '') + '</textarea>' +
    '<div class="st-row"><input class="inp" data-p="title" maxlength="30" placeholder="发布标题" value="' + esc(p.title || prm.title || '') + '"><input class="inp" data-p="tags" placeholder="话题 空格隔开" value="' + esc(((p.tags || prm.tags || []).join ? (p.tags || prm.tags).join(' ') : (p.tags || prm.tags || ''))) + '"></div>' +
    '<textarea class="inp" data-p="desc" rows="2" spellcheck="false" placeholder="发布简介">' + esc(p.desc || prm.desc || '') + '</textarea>' +
    '<div class="st-row2"><button class="btn mini primary" data-act="graphImport">按剧本导入节点</button><button class="btn mini ghost" data-act="graphPlan">DeepSeek 拆解</button></div>' +
    '<div class="st-import" id="stImportBox" hidden><textarea class="inp" id="stImport" rows="5" spellcheck="false" placeholder="贴 JSON 或 Markdown 剧本；格式见 说明 › 视频工坊剧本格式"></textarea>' +
    '<div class="st-row"><label class="btn mini ghost st-file">选文件<input type="file" id="stImportFile" accept=".md,.markdown,.txt,.json" hidden></label><button class="btn mini primary" data-act="graphImportGo">导入</button><button class="linkbtn" data-act="graphImportCancel">取消</button></div></div>' +
    '<div class="st-row2"><button class="btn mini ghost" data-act="export">导出 Gemini 策划包</button><span class="st-hint" id="stEstimate">导入前会显示预估费用</span></div>' +
    '<div class="st-hint">固定风格：' + esc(ST_STYLE) + '。导入只建节点和连线，不会自动花钱。</div>';
}

function stImageHTML(p, n) {
  var prm = n.params || {}, res = prm.resolution || '2k', out = prm.output || 'normal', fmt = prm.format || 'png';
  var frames = +prm.gif_frames || 8, delay = +prm.gif_delay_ms || 150;
  var cw = +prm.custom_w || 1024, ch = +prm.custom_h || 1024;
  var gifSec = Math.round(frames * delay / 100) / 10;
  return '<textarea class="inp" data-p="prompt" rows="3" spellcheck="false" placeholder="这一镜的画面提示词">' + esc(prm.prompt || '') + '</textarea>' +
    '<div class="st-subrow"><select data-p="model">' + stModelOptions(prm.model) + '</select><select data-p="ratio">' + stSelect(ST_RATIOS.map(function (x) { return [x, x]; }), prm.ratio || p.ratio || '9:16') + '</select></div>' +
    '<div class="st-subrow"><select data-p="resolution">' + stSelect([['1k', '1K 标准'], ['2k', '2K 高清'], ['4k', '4K 超清'], ['custom', '自定义']], res) + '</select>' +
    '<select data-p="n">' + stSelect([[1, '1 张'], [2, '2 张'], [3, '3 张'], [4, '4 张']], prm.n || 1) + '</select></div>' +
    '<div class="st-subrow"><select data-p="quality">' + stSelect([['auto', 'quality auto'], ['low', 'low 草图'], ['medium', 'medium 均衡'], ['high', 'high 精细'], ['xhigh', 'xhigh 更精细'], ['max', 'max 最高']], prm.quality || 'high') + '</select>' +
    '<select data-p="complexity">' + stSelect([['low', 'complexity low 简单'], ['medium', 'medium 常规'], ['high', 'high 复杂']], prm.complexity || 'medium') + '</select></div>' +
    (res === 'custom' ? '<div class="st-subrow"><label class="st-lab">宽</label><input class="inp st-num2" data-p="custom_w" type="number" min="16" max="3840" step="16" value="' + cw + '"><label class="st-lab">高</label><input class="inp st-num2" data-p="custom_h" type="number" min="16" max="3840" step="16" value="' + ch + '"><span class="st-hint" data-sizeerr="' + esc(n.id) + '"></span></div>' : '') +
    stOutType(n) +
    (out === 'gif' ? '<div class="st-subrow"><label class="st-lab">帧数</label><input class="inp st-num2" data-p="gif_frames" type="number" min="2" max="16" value="' + frames + '"><label class="st-lab">每帧 ms</label><input class="inp st-num2" data-p="gif_delay_ms" type="number" min="20" max="2000" value="' + delay + '"><span class="st-hint" data-gifcalc="' + esc(n.id) + '">共 ' + frames + ' 帧，约 ' + gifSec + ' 秒</span></div>'
      : out === 'svg' ? '<div class="st-hint">SVG 矢量图：适合图标/贴纸素材，背景透明。</div>'
        : '<div class="st-subrow"><label class="st-lab">格式</label><select data-p="format">' + stSelect([['png', 'PNG 无损'], ['jpeg', 'JPEG 高效'], ['webp', 'WebP 更小']], fmt) + '</select>' +
          '<label class="st-chk"><input type="checkbox" data-p="transparent"' + (prm.transparent ? ' checked' : '') + '>透明 alpha</label></div>') +
    stRefsHTML(p, n) +
    '<div class="st-outlabel">产出</div>' + stOutputsHTML(p, n, 'image');
}

function stVoiceHTML(p, n) {
  var prm = n.params || {}, lines = prm.lines || [];
  if (!lines.length) lines = [{ id: 'l1', text: '', tone: '' }];
  return '<div class="st-subrow"><select data-p="role">' + stSelect(ST_ROLES.map(function (x) { return [x, x]; }), prm.role || '白页') + '</select>' +
    '<select data-p="engine">' + stSelect([['auto', '自动选引擎'], ['local', '本地 Qwen3-TTS'], ['cloud', '百炼云端']], prm.engine || 'auto') + '</select></div>' +
    '<div class="st-subrow"><select data-p="speaker">' + stVoiceOptions(prm.speaker || '') + '</select></div>' +
    '<input class="inp" data-p="tone" value="' + esc(prm.tone || '') + '" placeholder="默认语气：冷静吐槽 / 轻松调侃">' +
    '<div class="st-lines">' + lines.map(function (ln, i) {
      return '<div class="st-line" data-line="' + i + '"><div class="st-line-h"><b>第 ' + (i + 1) + ' 句</b><span class="sp"></span><button class="linkbtn" data-linedel="' + esc(n.id) + ':' + i + '">删除</button></div>' +
        '<textarea class="inp" data-line-text rows="1" spellcheck="false" placeholder="这一句要念的台词">' + esc(ln.text || '') + '</textarea>' +
        '<input class="inp" data-line-tone value="' + esc(ln.tone || '') + '" placeholder="这一句的语气（可空，用上面的默认）"></div>';
    }).join('') + '</div>' +
    '<div class="st-row2"><button class="btn mini ghost" data-lineadd="' + esc(n.id) + '">+ 加一句</button><button class="btn mini ghost" data-bulk="' + esc(n.id) + '">批量贴台词</button><span class="st-hint">逐句语气传给百炼，不写 [笑] 标签</span></div>' +
    '<details class="st-bulk" id="stBulk-' + esc(n.id) + '"><summary>批量贴台词（一行一句）</summary><textarea class="inp" data-bulk-text rows="4" spellcheck="false" placeholder="一行一句；空行忽略"></textarea><button class="btn mini primary" data-bulkgo="' + esc(n.id) + '">替换成这些句</button></details>' +
    '<div class="st-outlabel">产出</div>' + stAudioRow(p, n) +
    '<div class="st-hint">同时写 .srt 字幕和时间轴 .json。</div>';
}

function stBgmHTML(p, n) {
  var prm = n.params || {};
  var sec = +prm.seconds || Math.round(p.total_seconds || p.target_seconds || 75);
  return '<textarea class="inp" data-p="prompt" rows="3" spellcheck="false" placeholder="英文描述最好：风格、情绪、乐器、速度；不要人声">' + esc(prm.prompt || p.bgm_prompt || '') + '</textarea>' +
    '<div class="st-row"><label class="st-lab">时长</label><input class="inp st-num" data-p="seconds" type="number" min="10" max="380" value="' + sec + '"><span class="st-hint">秒</span></div>' +
    '<div class="st-row2"><label class="st-f"><span class="st-lab">步数</span><input class="inp" data-p="steps" type="number" min="1" max="32" value="' + (+prm.steps || 8) + '"></label>' +
    '<label class="st-f"><span class="st-lab">种子</span><input class="inp" data-p="seed" type="number" value="' + (+prm.seed || 20261118) + '"></label></div>' +
    '<div class="st-outlabel">产出</div>' + stAudioRow(p, n);
}

function stWebHTML(p, n) {
  var prm = n.params || {}, sf = prm.styleframe || {}, up = stUpImage(n);
  return '<div class="st-row"><label class="st-lab">背景</label><select class="inp" data-p="bg">' + stSelect([['dark', '深色毛玻璃'], ['tech', '科技蓝'], ['warm', '暖色'], ['light', '浅色']], prm.bg || 'dark') + '</select></div>' +
    '<div class="st-row2"><label class="st-f"><span class="st-lab">字幕位置</span><select class="inp" data-p="sub_pos">' + stSelect([['bottom', '靠下'], ['center', '中间'], ['top', '靠上']], prm.sub_pos || 'bottom') + '</select></label>' +
    '<label class="st-f"><span class="st-lab">字号</span><input class="inp" data-p="sub_size" type="number" min="0" max="120" value="' + (+prm.sub_size || 0) + '"></label></div>' +
    '<div class="st-row2"><label class="st-f"><span class="st-lab">字幕颜色</span><input class="inp" data-p="sub_color" value="' + esc(prm.sub_color || '') + '" placeholder="#ffffff"></label>' +
    '<label class="st-f"><span class="st-lab">GIF 缩放</span><input class="inp" data-p="gif_scale" type="number" min="0.4" max="2.2" step="0.1" value="' + (+prm.gif_scale || 1) + '"></label></div>' +
    '<div class="st-row2"><label class="st-f"><span class="st-lab">动效强度</span><input class="inp" data-p="motion" type="number" min="0" max="2" step="0.1" value="' + (+prm.motion || 1) + '"></label>' +
    '<label class="st-f"><span class="st-lab">FPS</span><input class="inp" data-p="fps" type="number" min="12" max="30" value="' + (+prm.fps || 24) + '"></label></div>' +
    '<label class="st-f"><span class="st-lab">这一镜时长（秒）</span><input class="inp" data-p="duration" type="number" min="1" max="120" step="0.5" value="' + (+prm.duration || 6) + '"></label>' +
    '<input class="inp" data-p="text" value="' + esc(prm.text || '') + '" placeholder="字幕文字（不填就用接进来的配音/剧本）">' +
    '<div class="st-up">参考图：' + (up ? '<img src="' + esc(stOutUrl(p, up.out.rel)) + '" alt=""><span>' + esc(String(up.out.rel).split('/').pop()) + '</span>' : '<em>没接（可从生图节点的 image 输出拖过来）</em>') + '</div>' +
    '<button class="btn mini" data-act="styleframe" data-nid="' + esc(n.id) + '">交给 Claude Code 看图复刻并录制</button>' +
    '<div class="st-hint">会消耗 Claude Code 额度；只在你点的时候调用。' + (sf.html ? ' 已生成：' + esc(sf.html) : '') + '</div>' +
    '<div class="st-outlabel">产出</div>' + stOutputsHTML(p, n, 'video');
}

function stPptHTML(p, n) {
  var prm = n.params || {};
  return '<div class="st-row"><label class="st-lab">PPT 文件</label><input class="inp" data-p="file" value="' + esc(prm.file || '') + '" placeholder="项目里的 .pptx（留空自动生成）"></div>' +
    '<textarea class="inp" data-p="text" rows="2" spellcheck="false" placeholder="这一页的文字（不填就用接进来的配音/剧本）">' + esc(prm.text || '') + '</textarea>' +
    '<textarea class="inp" data-p="points" rows="2" spellcheck="false" placeholder="要点，一行一条（最多 5 条）">' + esc((prm.points || []).join ? (prm.points || []).join('\n') : (prm.points || '')) + '</textarea>' +
    '<div class="st-outlabel">产出</div>' + stOutputsHTML(p, n, 'image');
}

function stMuxHTML(p, n) {
  var prm = n.params || {}, vol = Math.round((+prm.bgm_volume != null ? +prm.bgm_volume : .18) * 100);
  var imgs = stUpstream(n, 'image').length + stUpstream(n, 'video').length;
  var auds = stUpstream(n, 'audio').length;
  return '<label class="st-check"><input type="checkbox" data-p="subtitle"' + (prm.subtitle !== false ? ' checked' : '') + '> 烧录硬字幕（白字黑边）</label>' +
    '<div class="st-row"><span class="st-lab">画幅</span><div class="seg st-seg"><button data-muxratio="9:16" aria-pressed="' + ((prm.ratio || p.ratio) !== '16:9') + '">9:16</button><button data-muxratio="16:9" aria-pressed="' + ((prm.ratio || p.ratio) === '16:9') + '">16:9</button></div></div>' +
    '<div class="st-vol"><label class="st-lab">配乐基础音量 <em>' + vol + '%</em></label><input type="range" data-p="bgm_volume" min="0" max="60" step="5" value="' + vol + '"></div>' +
    '<div class="st-row2"><label class="st-f"><span class="st-lab">闪避深度</span><input class="inp" data-p="duck_depth" type="number" min="0" max="1" step="0.05" value="' + (+prm.duck_depth || .16) + '"></label>' +
    '<label class="st-f"><span class="st-lab">淡出秒</span><input class="inp" data-p="fade" type="number" min="0" max="6" step="0.5" value="' + (+prm.fade || 2) + '"></label></div>' +
    '<div class="st-hint">接进来：画面 ' + imgs + ' 条 · 音频 ' + auds + ' 条。按节点的 order / 位置配对。</div>' +
    '<div class="st-outlabel">产出</div>' + stOutputsHTML(p, n, 'video') +
    (stOutFirst(n, 'image') ? '<button class="st-cover" data-lbout="' + esc(n.id) + ':image:0"><img src="' + esc(stOutUrl(p, stOutFirst(n, 'image').rel)) + '" alt=""><span>封面 · 点开看大图</span></button>' : '');
}

function stPublishHTML(p, n) {
  var prm = n.params || {};
  var imgs = [];
  (stGraph().nodes || []).forEach(function (x) { if (x.type === 'image') stOutList(x, 'image').forEach(function (o) { imgs.push({ rel: o.rel, id: x.id }); }); });
  var coverOpts = '<option value="auto">自动（成片封面 / 选中分镜）</option>' + imgs.map(function (o) { return '<option value="' + esc(o.rel) + '"' + (prm.cover === o.rel ? ' selected' : '') + '>' + esc(o.id + ' · ' + String(o.rel).split('/').pop()) + '</option>'; }).join('');
  var tags = (prm.tags || p.tags || []).join ? (prm.tags || p.tags || []).join(' ') : (prm.tags || '');
  var pub = (studioSt() && studioSt().publish) || {};
  return '<div class="st-row"><label class="st-lab">标题</label><input class="inp" data-p="title" maxlength="30" value="' + esc(prm.title || p.title || '') + '"></div>' +
    '<textarea class="inp" data-p="desc" rows="2" spellcheck="false" placeholder="简介">' + esc(prm.desc || p.desc || '') + '</textarea>' +
    '<input class="inp" data-p="tags" value="' + esc(tags) + '" placeholder="话题 空格隔开">' +
    '<div class="st-subrow"><select data-p="mode">' + stSelect([['single', '单条送审'], ['batch', '加入批量清单']], prm.mode || 'single') + '</select>' +
    '<select data-p="cover">' + coverOpts + '</select></div>' +
    '<div class="st-row2"><label class="st-f"><span class="st-lab">定时发布</span><input class="inp" data-p="schedule" type="datetime-local" value="' + esc(prm.schedule || '') + '"></label>' +
    '<select data-p="declaration">' + ['内容由AI生成', '内容自行拍摄', '内容取材网络', '虚构演绎，仅供娱乐', '可能引人不适', '危险行为，请勿模仿'].map(function (x) { return '<option' + ((prm.declaration || '内容由AI生成') === x ? ' selected' : '') + '>' + x + '</option>'; }).join('') + '</select></div>' +
    '<input class="inp" data-p="collection" value="' + esc(prm.collection || '') + '" placeholder="合集（可空）">' +
    '<button class="btn mini primary" data-act="pubgraph" data-nid="' + esc(n.id) + '">送去发布（进待确认队列）</button>' +
    '<div class="st-hint">待确认 ' + ((pub.pending) || 0) + ' 条 · 批量 ' + ((pub.batch) || 0) + ' 条。绝不会自动点发送，仍要在「发布」窗口人工确认。</div>';
}

function stNodeBody(p, n) {
  if (n.type === 'script') return stScriptHTML(p, n);
  if (n.type === 'image') return stImageHTML(p, n);
  if (n.type === 'voice') return stVoiceHTML(p, n);
  if (n.type === 'bgm') return stBgmHTML(p, n);
  if (n.type === 'web') return stWebHTML(p, n);
  if (n.type === 'ppt') return stPptHTML(p, n);
  if (n.type === 'mux') return stMuxHTML(p, n);
  if (n.type === 'publish') return stPublishHTML(p, n);
  return '';
}
function stNodeHTML(p, n) {
  var cls = 'st-node st-nt-' + n.type;
  return '<section class="' + cls + '" data-node="' + esc(n.id) + '" data-type="' + esc(n.type) + '" style="left:' + n.x + 'px;top:' + n.y + 'px;width:' + n.w + 'px;height:' + n.h + 'px">' +
    stNodeHeader(n) + stPortBar(n) + '<div class="st-node-body" id="stNode-' + esc(n.id) + '">' + stNodeBody(p, n) + '</div>' + stNodeFooter(n) +
    '<span class="st-rs" data-rs="' + esc(n.id) + '" title="拖动改变节点大小"></span></section>';
}

/* ---------- 画布 ---------- */
function stWorldSize() {
  var mx = 1800, my = 1100;
  (stGraph().nodes || []).forEach(function (n) { mx = Math.max(mx, +n.x + +n.w + 200); my = Math.max(my, +n.y + +n.h + 200); });
  return { w: mx, h: my };
}
function stPortY(n, i) { return (+n.y || 0) + 36 + 8 + i * 20 + 10; }
function stPortPoint(m, ref, dir) {
  var a = String(ref).split('.'), n = m[a[0]]; if (!n) return null;
  var defs = stPorts(n.type)[dir === 'out' ? 'out' : 'in'];
  var i = defs.findIndex(function (x) { return x[0] === a[1]; });
  if (i < 0) return null;
  return { x: dir === 'out' ? (+n.x + +n.w) : +n.x, y: stPortY(n, i) };
}
function stEdgePath(a, b) {
  var dx = Math.max(36, Math.abs(b.x - a.x) * .5);
  return 'M' + a.x + ' ' + a.y + ' C' + (a.x + dx) + ' ' + a.y + ',' + (b.x - dx) + ' ' + b.y + ',' + b.x + ' ' + b.y;
}
function stEdgesHTML(m, temp) {
  var out = [], g = stGraph();
  (g.edges || []).forEach(function (e) {
    var a = stPortPoint(m, e.from, 'out'), b = stPortPoint(m, e.to, 'in');
    if (!a || !b) return;
    var up = m[String(e.from).split('.')[0]], dn = m[String(e.to).split('.')[0]];
    var cls = (up && dn && (stStatus(up) === 'done' || stStatus(dn) === 'done')) ? ' on' : '';
    var d = stEdgePath(a, b);
    out.push('<path class="st-edge' + cls + '" d="' + d + '"/>');
    out.push('<path class="st-edge-hit" data-edge="' + esc(e.id) + '" d="' + d + '"/>');
  });
  if (temp) out.push('<path class="st-edge temp" d="' + temp.d + '"/>');
  return out.join('');
}
function renderEdges(m, temp) {
  var e = $('#stEdges'); if (!e) return;
  var html = stEdgesHTML(m || stNodeMap(), temp);
  if (html === STUDIO.edgeSig && !temp) return;
  STUDIO.edgeSig = html;
  e.innerHTML = html;
}
function renderStCanvas(force) {
  var p = studioProj(); if (!p) return;
  var m = stNodeMap(), g = stGraph();
  var w = $('#stWorld'); if (!w) return;
  var sz = stWorldSize();
  w.style.width = sz.w + 'px'; w.style.height = sz.h + 'px';
  if (!$('#stEdges')) {
    w.insertAdjacentHTML('afterbegin', '<svg class="st-edges" id="stEdges" width="' + sz.w + '" height="' + sz.h + '" aria-hidden="true"></svg>');
  }
  var seen = {};
  (g.nodes || []).forEach(function (n) {
    seen[n.id] = 1;
    var el = w.querySelector('[data-node="' + n.id + '"]');
    var html = stNodeHTML(p, n);
    if (!el) { w.insertAdjacentHTML('beforeend', html); STUDIO.nodeSig[n.id] = html; return; }
    if (force || STUDIO.nodeSig[n.id] !== html) {
      var ae = document.activeElement;
      var inside = !!(ae && el.contains(ae) && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName));
      if (inside && !force) { syncOneNode(el, n); return; }
      el.outerHTML = html;
      STUDIO.nodeSig[n.id] = html;
    } else {
      syncOneNode(el, n);
    }
  });
  w.querySelectorAll('[data-node]').forEach(function (el) { if (!seen[el.getAttribute('data-node')]) el.remove(); });
  var svg = $('#stEdges'); if (svg) { svg.setAttribute('width', sz.w); svg.setAttribute('height', sz.h); }
  STUDIO.edgeSig = '';
  renderEdges(m);
  applyCanvas();
  $$('[data-sizeerr]').forEach(function (el) { var nid = el.getAttribute('data-sizeerr'); if (nid) stUpdateSizeHint(nid); });
}
function syncOneNode(el, n) {
  var lamp = el.querySelector('[data-lamp]'); if (lamp) lamp.className = 'st-lamp st-' + stStatus(n);
  var f = el.querySelector('[data-pmsg]'); if (f) f.textContent = n.error || (n.status === 'ok' ? '已完成' : n.status === 'stale' ? '要重做' : '待命');
}
function applyCanvas() {
  var w = $('#stWorld'); if (!w) return;
  w.style.transform = 'translate(' + STUDIO.canvas.x + 'px,' + STUDIO.canvas.y + 'px) scale(' + STUDIO.canvas.s + ')';
  var tip = $('.st-canvas-tip'); if (tip) tip.textContent = Math.round(STUDIO.canvas.s * 100) + '% · 空白拖动平移 · 滚轮缩放 · 拖输出口到输入口连线';
}
function stBounds() {
  var ns = stGraph().nodes || []; if (!ns.length) return { x: 0, y: 0, w: 1800, h: 1100 };
  var x1 = 1e9, y1 = 1e9, x2 = -1e9, y2 = -1e9;
  ns.forEach(function (n) { x1 = Math.min(x1, +n.x); y1 = Math.min(y1, +n.y); x2 = Math.max(x2, +n.x + +n.w); y2 = Math.max(y2, +n.y + +n.h); });
  return { x: x1, y: y1, w: Math.max(200, x2 - x1), h: Math.max(200, y2 - y1) };
}
function fitCanvas() {
  var c = $('#stCanvas'); if (!c) return;
  var b = stBounds(), vw = c.clientWidth, vh = c.clientHeight;
  var s = Math.min((vw - 40) / b.w, (vh - 40) / b.h);
  s = Math.max(.3, Math.min(1.15, s));
  STUDIO.canvas.s = s;
  STUDIO.canvas.x = Math.round((vw - b.w * s) / 2 - b.x * s);
  STUDIO.canvas.y = Math.round((vh - b.h * s) / 2 - b.y * s);
  STUDIO.canvas.auto = true;
  applyCanvas(); saveCanvasView();
}
function saveCanvasView() { if (typeof saveUI === 'function') saveUI({ studioGraphView: { x: STUDIO.canvas.x, y: STUDIO.canvas.y, s: STUDIO.canvas.s } }); }

/* ---------- 数据 ---------- */
function stApi(path, body, timeout) {
  if (!useLive()) { toast('演示模式：连上后端才能用'); return Promise.reject(new Error('demo')); }
  return api('POST', '/api/studio/graph/' + path, body || {}, timeout || 60000);
}
function stSaving(pr) {
  STUDIO.saving = pr;
  var clear = function () { if (STUDIO.saving === pr) STUDIO.saving = null; };
  pr.then(clear, clear);
  return pr;
}
function stRefreshProject(j) {
  if (!j) return;
  if (j.project && STUDIO.st) { STUDIO.st.project = j.project; STUDIO.st.active = j.project.id; }
  STUDIO.sig = {}; STUDIO.nodeSig = {};
  renderStudio(true);
}
function stSaveParams(nid, patch, quiet) {
  var p = studioProj(); if (!p) return Promise.resolve();
  clearTimeout(STUDIO.saveT[nid]);
  var go = function () {
    return stSaving(stApi('update', { pid: p.id, id: nid, params: patch }, 20000).then(function (j) {
      if (j.project && STUDIO.st) STUDIO.st.project = j.project;
      if (!quiet) { STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }
    }).catch(function (e) { toast(e.message, 7000); }));
  };
  if (quiet === 'debounce') {
    return new Promise(function (resolve) {
      STUDIO.saveT[nid] = setTimeout(function () { go().then(resolve, resolve); }, 550);
    });
  }
  return go();
}
function stCollectLines(nodeEl) {
  var out = [];
  nodeEl.querySelectorAll('[data-line]').forEach(function (row, i) {
    var t = row.querySelector('[data-line-text]'), to = row.querySelector('[data-line-tone]');
    out.push({ id: 'l' + (i + 1), text: t ? t.value : '', tone: to ? to.value : '' });
  });
  return out;
}
function stCollectParams(nodeEl) {
  var o = {};
  nodeEl.querySelectorAll('[data-p]').forEach(function (el) {
    var k = el.getAttribute('data-p');
    if (el.type === 'checkbox') o[k] = !!el.checked;
    else if (el.type === 'range') o[k] = (+el.value || 0) / 100;
    else o[k] = el.value;
  });
  var nid = nodeEl.getAttribute('data-node');
  var n = stNodeMap()[nid];
  if (n && n.type === 'voice') o.lines = stCollectLines(nodeEl);
  if (n && n.type === 'image') {
    ['n', 'gif_frames', 'gif_delay_ms', 'custom_w', 'custom_h'].forEach(function (k) { if (o[k] != null) o[k] = +o[k] || 0; });
    if (o.transparent == null) o.transparent = false;
  }
  if (n && n.type === 'bgm') ['seconds', 'steps', 'seed'].forEach(function (k) { if (o[k] != null) o[k] = +o[k] || 0; });
  if (n && n.type === 'web') ['sub_size', 'gif_scale', 'motion', 'fps', 'duration'].forEach(function (k) { if (o[k] != null) o[k] = +o[k] || 0; });
  if (n && n.type === 'mux') ['duck_depth', 'fade'].forEach(function (k) { if (o[k] != null) o[k] = +o[k] || 0; });
  if (n && n.type === 'ppt') o.points = String(o.points || '').split(/\n+/).map(function (x) { return x.trim(); }).filter(Boolean).slice(0, 5);
  return o;
}
function stSizeCheck(w, h) {
  w = +w; h = +h;
  if (!w || !h) return '宽和高都要填';
  if (w % 16 || h % 16) return '宽高必须是 16 的倍数';
  if (Math.max(w, h) > 3840) return '长边不能超过 3840';
  if (Math.max(w, h) / Math.min(w, h) > 3) return '长宽比不能超过 3:1';
  var px = w * h;
  if (px < 655360 || px > 8294400) return '总像素要在 655,360 – 8,294,400 之间（现在 ' + px.toLocaleString() + '）';
  return '';
}
function stUpdateSizeHint(nid) {
  var el = document.querySelector('[data-node="' + nid + '"]'); if (!el) return;
  var w = el.querySelector('[data-p="custom_w"]'), h = el.querySelector('[data-p="custom_h"]');
  var msg = w && h ? stSizeCheck(w.value, h.value) : '';
  var o = el.querySelector('[data-sizeerr]');
  if (o) { o.textContent = msg; o.style.color = msg ? 'var(--bad)' : 'var(--text3)'; }
}

/* ---------- 事件 ---------- */
function stAddAt(type) {
  var c = $('#stCanvas');
  var sz = ST_DEFAULT_SIZE[type] || [340, 400];
  var x = Math.round((c.clientWidth / 2 - STUDIO.canvas.x) / STUDIO.canvas.s - sz[0] / 2);
  var y = Math.round((c.clientHeight / 2 - STUDIO.canvas.y) / STUDIO.canvas.s - sz[1] / 2);
  var ns = stGraph().nodes || [];
  function hit(px, py) {
    return ns.some(function (n) { return px < (+n.x + +n.w + 24) && px + sz[0] + 24 > +n.x && py < (+n.y + +n.h + 24) && py + sz[1] + 24 > +n.y; });
  }
  var x0 = x;
  for (var i = 0; i < 200; i++) {
    if (!hit(x, y)) break;
    x += 48; y += 36;
    if (i % 10 === 9) { x = x0; y += 120; }
  }
  return { x: Math.round(x), y: Math.round(y) };
}
function bindCanvas() {
  var cv = $('#stCanvas'); if (!cv || cv.dataset.bound === '1') return;
  cv.dataset.bound = '1';
  var space = false;
  document.addEventListener('keydown', function (e) { if (e.code === 'Space' && S.view === 'studio') { space = true; } });
  document.addEventListener('keyup', function (e) { if (e.code === 'Space') space = false; });
  cv.addEventListener('pointerdown', function (ev) {
    if (ev.target.closest('[data-edge]')) {
      var eid = ev.target.getAttribute('data-edge');
      if (eid && confirm('断开这条连线？')) stApi('disconnect', { pid: (studioProj() || {}).id, edge: eid }).then(function (j) { stRefreshProject(j); toast('线断开了'); }).catch(function () {});
      ev.preventDefault(); return;
    }
    var rs = ev.target.closest('[data-rs]');
    if (rs && ev.button === 0) {
      var rn = stNodeMap()[rs.getAttribute('data-rs')];
      if (rn) { STUDIO.resize = { id: rn.id, x: ev.clientX, y: ev.clientY, w: +rn.w, h: +rn.h }; STUDIO.dragging = true; cv.setPointerCapture(ev.pointerId); ev.preventDefault(); return; }
    }
    var op = ev.target.closest('[data-port]');
    if (op && ev.button === 0) {
      var ref = op.getAttribute('data-port');
      STUDIO.link = { from: ref, pt: op.getAttribute('data-pt'), x: ev.clientX, y: ev.clientY, d: '' };
      STUDIO.dragging = true; cv.setPointerCapture(ev.pointerId); ev.preventDefault(); return;
    }
    var hd = ev.target.closest('[data-drag]');
    if (hd && ev.button === 0) {
      var nid = hd.getAttribute('data-drag'), n = stNodeMap()[nid];
      if (n) { STUDIO.drag = { id: nid, x: ev.clientX, y: ev.clientY, ox: +n.x, oy: +n.y }; STUDIO.dragging = true; cv.setPointerCapture(ev.pointerId); ev.preventDefault(); return; }
    }
    if (ev.target.closest('.st-node') || ev.target.closest('button,input,textarea,select,label')) return;
    if (ev.button === 0 || ev.button === 1 || space) {
      STUDIO.pan = { x: ev.clientX, y: ev.clientY, ox: STUDIO.canvas.x, oy: STUDIO.canvas.y };
      STUDIO.canvas.auto = false; cv.setPointerCapture(ev.pointerId); ev.preventDefault();
    }
  });
  cv.addEventListener('pointermove', function (ev) {
    if (STUDIO.link) {
      var m = stNodeMap(), a = stPortPoint(m, STUDIO.link.from, 'out');
      if (!a) return;
      var r = cv.getBoundingClientRect();
      var wx = (ev.clientX - r.left - STUDIO.canvas.x) / STUDIO.canvas.s, wy = (ev.clientY - r.top - STUDIO.canvas.y) / STUDIO.canvas.s;
      STUDIO.link.d = stEdgePath(a, { x: wx, y: wy });
      renderEdges(m, { d: STUDIO.link.d });
      return;
    }
    if (STUDIO.resize) {
      var n = stNodeMap()[STUDIO.resize.id]; if (!n) return;
      n.w = Math.max(240, Math.round(STUDIO.resize.w + (ev.clientX - STUDIO.resize.x) / STUDIO.canvas.s));
      n.h = Math.max(160, Math.round(STUDIO.resize.h + (ev.clientY - STUDIO.resize.y) / STUDIO.canvas.s));
      var el = cv.querySelector('[data-node="' + n.id + '"]');
      if (el) { el.style.width = n.w + 'px'; el.style.height = n.h + 'px'; }
      renderEdges(stNodeMap()); return;
    }
    if (STUDIO.drag) {
      var n2 = stNodeMap()[STUDIO.drag.id]; if (!n2) return;
      n2.x = Math.round(STUDIO.drag.ox + (ev.clientX - STUDIO.drag.x) / STUDIO.canvas.s);
      n2.y = Math.round(STUDIO.drag.oy + (ev.clientY - STUDIO.drag.y) / STUDIO.canvas.s);
      var el2 = cv.querySelector('[data-node="' + n2.id + '"]');
      if (el2) { el2.style.left = n2.x + 'px'; el2.style.top = n2.y + 'px'; }
      renderEdges(stNodeMap()); return;
    }
    if (STUDIO.pan) {
      STUDIO.canvas.x = Math.round(STUDIO.pan.ox + ev.clientX - STUDIO.pan.x);
      STUDIO.canvas.y = Math.round(STUDIO.pan.oy + ev.clientY - STUDIO.pan.y);
      applyCanvas();
    }
  });
  function up(ev) {
    if (STUDIO.link) {
      var lk = STUDIO.link; STUDIO.link = null;
      var hit = document.elementFromPoint(ev.clientX, ev.clientY);
      var ip = hit && hit.closest ? hit.closest('[data-inport]') : null;
      if (ip) {
        var to = ip.getAttribute('data-inport');
        if (ip.getAttribute('data-pt') !== lk.pt) toast('端口类型不兼容：' + lk.pt + ' 不能接到 ' + ip.getAttribute('data-pt'), 7000);
        else stApi('connect', { pid: (studioProj() || {}).id, from: lk.from, to: to }).then(function (j) { stRefreshProject(j); toast('连上了'); }).catch(function (e) { toast(e.message, 8000); });
      }
      STUDIO.edgeSig = ''; renderEdges();
    }
    if (STUDIO.drag || STUDIO.resize) { saveNodeLayout(true); }
    if (STUDIO.pan) saveCanvasView();
    STUDIO.dragging = false; STUDIO.drag = null; STUDIO.resize = null; STUDIO.pan = null;
  }
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);
  cv.addEventListener('wheel', function (ev) {
    ev.preventDefault();
    var r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
    var wx = (mx - STUDIO.canvas.x) / STUDIO.canvas.s, wy = (my - STUDIO.canvas.y) / STUDIO.canvas.s;
    var f = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
    STUDIO.canvas.s = Math.max(.3, Math.min(2, STUDIO.canvas.s * f));
    STUDIO.canvas.x = mx - wx * STUDIO.canvas.s; STUDIO.canvas.y = my - wy * STUDIO.canvas.s;
    STUDIO.canvas.auto = false; applyCanvas(); saveCanvasView();
  }, { passive: false });
}
function saveNodeLayout(now) {
  var p = studioProj(); if (!p) return;
  clearTimeout(STUDIO.layoutT);
  var ns = stGraph().nodes || [];
  var snap = ns.map(function (n) { return { id: n.id, x: n.x, y: n.y, w: n.w, h: n.h }; });
  var send = function () {
    if (!useLive()) return;
    STUDIO.layoutPending = true;
    stApi('layout', { pid: p.id, nodes: snap }, 15000).catch(function () {}).then(function () {
      STUDIO.layoutPending = false;
    }, function () { STUDIO.layoutPending = false; });
  };
  if (now) send(); else STUDIO.layoutT = setTimeout(send, 450);
}
function syncStudioMeta() {
  (stGraph().nodes || []).forEach(function (n) {
    var el = document.querySelector('[data-node="' + n.id + '"]'); if (!el) return;
    var lamp = el.querySelector('[data-lamp]'); if (lamp) lamp.className = 'st-lamp st-' + stStatus(n);
    var msg = el.querySelector('[data-pmsg]');
    if (msg) {
      var j = studioJob(), p = studioProj(), cur = j && j.st === 'run' && j.pid === (p && p.id) && j.step === n.id;
      msg.textContent = String((cur && j.msg) || n.error || (n.status === 'ok' ? '已完成' : n.status === 'stale' ? '要重做' : n.status === 'err' ? '出错' : '待命')).slice(0, 46);
    }
  });
  var nav = $('.nav[data-tool="studio"]'); if (nav) nav.classList.toggle('on-busy', studioRunning());
}

/* ---------- 动作 ---------- */
function studioDoAction(act, nid) {
  var p = studioProj(); if (!p) { toast('还没有项目'); return; }
  if (act === 'run') { stRunAll(); return; }
  if (act === 'stop') { studioDo('stop', {}, '停下中：当前这一步收尾后不再往下做').then(studioFetch).catch(function () {}); return; }
  if (act === 'styleframe') { stStyleframe(nid); return; }
  if (act === 'pubgraph') { stPublishNode(nid); return; }
  if (act === 'export') { studioExport(); return; }
  if (act === 'graphImport') { var b = $('#stImportBox'); if (b) b.hidden = !b.hidden; return; }
  if (act === 'graphImportCancel') { var b2 = $('#stImportBox'); if (b2) b2.hidden = true; return; }
  if (act === 'graphImportGo') { stImportGraph(); return; }
  if (act === 'graphPlan') { stPlanGraph(); return; }
}
function stRunAll() {
  var p = studioProj(); if (!p) { toast('还没有项目'); return; }
  stApi('run', { pid: p.id }, 120000).then(function (j) {
    if (j.project && STUDIO.st) STUDIO.st.project = j.project;
    toast('开跑：按连线拓扑，独立分支并行', 5000); studioFetch();
  }).catch(function (e) { toast(e.message, 8000); });
}
function stRunNode(nid) {
  var p = studioProj(); if (!p) return;
  stApi('run', { pid: p.id, id: nid }, 120000).then(function (j) {
    if (j.project && STUDIO.st) STUDIO.st.project = j.project;
    if (nid === 'publish') toast('发布节点检查过了：真正发送仍要「发布」窗口人工确认');
    studioFetch();
  }).catch(function (e) { toast(e.message, 9000); });
}
function stStyleframe(nid) {
  if (!confirm('这一步会消耗 Claude Code 额度：先看图，再写动效 HTML，然后录成视频轨。\n\n现在调用吗？')) return;
  stApi('styleframe', { pid: (studioProj() || {}).id, id: nid }, 120000).then(function (j) {
    if (j.project && STUDIO.st) STUDIO.st.project = j.project;
    toast('交给 Claude Code 了：进度看这个节点的状态', 6000); studioFetch();
  }).catch(function (e) { toast(e.message, 9000); });
}
function stPublishNode(nid) {
  var p = studioProj(); if (!p) return;
  stApi('publish', { pid: p.id, id: nid }, 30000).then(function (j) {
    toast(j.msg || '放进待确认队列了', 8000); studioFetch();
  }).catch(function (e) { toast(e.message, 8000); });
}
function stImportGraph() {
  var t = $('#stImport'), f = $('#stImportFile'), p = studioProj(); if (!p) return;
  var text = t ? t.value : '';
  if (!text.trim() && f && f.files && f.files[0]) {
    var r = new FileReader();
    r.onload = function () { if (t) t.value = r.result || ''; stImportGraph(); };
    r.readAsText(f.files[0], 'utf-8'); return;
  }
  if (!text.trim()) { toast('把剧本贴进来，或者选一个 .md / .json 文件'); return; }
  stApi('import', { pid: p.id, text: text }, 60000).then(function (j) {
    if (j.state) STUDIO.st = j.state;
    var est = j.estimate || {};
    toast('剧本导入好了：' + (j.summary || '') + ' · 预估 $' + (est.image_usd || 0).toFixed(2) + ' / ¥' + (est.tts_cny_cloud || 0).toFixed(2), 9000);
    STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); studioFetch();
  }).catch(function (e) { toast(e.message, 9000); });
}
function stPlanGraph() {
  var p = studioProj(); if (!p) return;
  var n = (stGraph().nodes || []).filter(function (x) { return x.type === 'script'; })[0] || {};
  var prm = n.params || {};
  stApi('plan', { pid: p.id, id: n.id, topic: prm.topic || prm.source_text || '', seconds: p.target_seconds || 75 }, 180000).then(function (j) {
    if (j.state) { STUDIO.st = j.state; STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }
    var est = j.estimate || {};
    toast('拆好了：' + (j.summary || '') + ' · 预估 $' + (est.image_usd || 0).toFixed(2), 9000);
  }).catch(function (e) { toast(e.message, 9000); });
}
function studioExport() {
  var p = studioProj(), a = document.createElement('a');
  a.href = '/api/studio/export_prompt_pack' + (p ? '?pid=' + encodeURIComponent(p.id) : '');
  a.download = 'gemini_prompt_pack.md';
  document.body.appendChild(a); a.click(); a.remove();
  toast('策划包已下载：交给 Gemini 写剧本，回来点「按剧本导入节点」', 6000);
}
function studioPlay(url) {
  if (!url) { toast('还没有可听的音频'); return; }
  if (STUDIO.audio) { try { STUDIO.audio.pause(); } catch (e) {} }
  STUDIO.audio = new Audio(url);
  STUDIO.audio.play().catch(function (e) { toast('放不了：' + e.message); });
}
function studioPatch(body) {                       // 兼容旧入口：更新工程级字段
  var p = studioProj(); if (!p || !useLive()) return Promise.resolve();
  body.pid = p.id;
  return api('PUT', '/api/studio/project', body, 20000).then(function (j) {
    if (STUDIO.st) STUDIO.st.project = j.project;
    return j.project;
  }).catch(function (e) { toast(e.message, 6000); throw e; });
}
function studioDo(path, body, okMsg) {
  if (!useLive()) { toast('演示模式：连上后端才能用'); return Promise.reject(); }
  return api('POST', '/api/studio/' + path, body || {}, 60000).then(function (j) {
    if (j && j.project) { if (!STUDIO.st) STUDIO.st = {}; STUDIO.st.project = j.project; STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }
    if (okMsg) toast(okMsg, 5000);
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
      STUDIO.lastPid = j.project.id;
      STUDIO.canvas.auto = true; STUDIO.fitted = false; STUDIO.nodeSig = {}; STUDIO.edgeSig = '';
      setTimeout(function () { if (S.view === 'studio') fitCanvas(); }, 30);
    }
    if (was && j.job && j.job.id === was.id && j.job.st !== 'run') toast('视频工坊：' + (j.job.msg || j.job.st), 7000);
    if (STUDIO.autoPlay && !studioRunning()) {
      var ap = ((j.project || {}).graph || {}).nodes || [], s = ap.filter(function (x) { return x.id === STUDIO.autoPlay; })[0];
      var o = s && (s.outputs || []).filter(function (x) { return x.kind === 'audio'; })[0];
      if (o) studioPlay(stOutUrl(j.project, o.rel));
      STUDIO.autoPlay = '';
    }
    renderStudio();
  }).catch(function () { if (S.view === 'studio' && !STUDIO.st) setTimeout(studioFetch, 1200); })
    .then(function () { STUDIO.fetching = null; }, function () { STUDIO.fetching = null; });
  return STUDIO.fetching;
}
function studioEnter() {
  studioFetch(); stHWStart(); clearInterval(STUDIO.t);
  STUDIO.t = setInterval(function () { if (S.view === 'studio') studioFetch(); }, 1500);
  setTimeout(function () { if (S.view === 'studio' && !STUDIO.st) studioFetch(); }, 700);
}
function studioLeave() {
  clearInterval(STUDIO.t); STUDIO.t = null; stHWStop();
  if (STUDIO.audio) { try { STUDIO.audio.pause(); } catch (e) {} }
  $$('#view-studio video').forEach(function (m) { try { m.pause(); } catch (e) {} });
}

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
      var node = ev.target.closest && ev.target.closest('[data-node]');
      if (node) {
        var n = stNodeMap()[node.getAttribute('data-node')];
        if (n) stSaveParams(n.id, stCollectParams(node), true);
      }
      STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true);
    }, 160);
  });
  v.addEventListener('input', function (ev) {
    var t = ev.target, node = t.closest && t.closest('[data-node]'), n = node && stNodeMap()[node.getAttribute('data-node')];
    if (!node || !n) return;
    if (t.hasAttribute('data-line-text') || t.hasAttribute('data-line-tone')) {
      stSaveParams(n.id, { lines: stCollectLines(node) }, 'debounce'); return;
    }
    if (!t.hasAttribute('data-p')) return;
    var k = t.getAttribute('data-p');
    if (k === 'custom_w' || k === 'custom_h') stUpdateSizeHint(n.id);
    if (k === 'gif_frames' || k === 'gif_delay_ms') {
      var fr = node.querySelector('[data-p="gif_frames"]'), de = node.querySelector('[data-p="gif_delay_ms"]'), gc = node.querySelector('[data-gifcalc]');
      if (fr && de && gc) gc.textContent = '共 ' + fr.value + ' 帧，约 ' + (Math.round(fr.value * de.value / 100) / 10) + ' 秒';
    }
    var patch = {}; patch[k] = t.type === 'checkbox' ? !!t.checked : t.value;
    if (t.type === 'range') patch[k] = (+t.value || 0) / 100;
    stSaveParams(n.id, patch, 'debounce');
  });
  v.addEventListener('change', function (ev) {
    var t = ev.target, p = studioProj(), node = t.closest && t.closest('[data-node]'), n = node && stNodeMap()[node.getAttribute('data-node')];
    if (t.id === 'stProj') { if (t.value) studioDo('select', { pid: t.value }).then(function (j) { STUDIO.st = j; STUDIO.lastPid = j.project && j.project.id; STUDIO.canvas.auto = true; STUDIO.fitted = false; STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {}); return; }
    if (t.id === 'stImportFile') { stImportGraph(); return; }
    if (t.getAttribute('data-ref-file')) { stUploadRefs(t.files, t.getAttribute('data-ref-file')); t.value = ''; return; }
    if (!node || !n) return;
    if (t.hasAttribute('data-p')) {
      var patch = {}; patch[t.getAttribute('data-p')] = t.type === 'checkbox' ? !!t.checked : (t.type === 'range' ? (+t.value || 0) / 100 : t.value);
      if (n.type === 'image') ['n', 'gif_frames', 'gif_delay_ms', 'custom_w', 'custom_h'].forEach(function (k) { if (patch[k] != null) patch[k] = +patch[k] || 0; });
      stSaveParams(n.id, patch).then(function () { if (t.getAttribute('data-p') === 'resolution') { STUDIO.nodeSig = {}; renderStudio(true); } });
    }
  });
  v.addEventListener('click', function (ev) {
    var b = ev.target.closest('button'); if (!b || b.disabled) return;
    var d = b.dataset, p = studioProj();
    if (d.st) {
      if (d.st === 'add') { var menu = $('#stAddMenu'); if (menu) { menu.hidden = !menu.hidden; if (!menu.hidden) menu.innerHTML = stAddMenuHTML(); } return; }
      if (d.st === 'fit') { fitCanvas(); return; }
      if (d.st === 'new') { studioDo('new', { topic: '', ratio: '9:16', seconds: 75, voice_id: 'local:preset:Vivian' }, '新建了空白项目').then(function (j) { STUDIO.st = j; STUDIO.lastPid = j.project && j.project.id; STUDIO.canvas.auto = true; STUDIO.fitted = false; STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {}); return; }
      if (d.st === 'run') { stRunAll(); return; }
      if (d.st === 'stop') { studioDoAction('stop'); return; }
      return;
    }
    if (d.add) {
      var at = stAddAt(d.add);
      stApi('add', { pid: p.id, type: d.add, x: at.x, y: at.y }).then(function (j) {
        var m = $('#stAddMenu'); if (m) m.hidden = true;
        if (j.project && STUDIO.st) STUDIO.st.project = j.project;
        STUDIO.sig = {}; STUDIO.nodeSig = {}; renderStudio(true); toast('加了一个' + (ST_TYPE_LABEL[d.add] || d.add) + '节点');
      }).catch(function (e) { toast(e.message, 8000); });
      return;
    }
    if (d.nrun) { stRunNode(d.nrun); return; }
    if (d.ndel) {
      var n = stNodeMap()[d.ndel];
      if (!n) return;
      if (ST_FIXED[n.type]) { toast('固定节点不能删'); return; }
      if (!confirm('删除节点「' + (n.title || n.id) + '」？它的产出文件留在项目里，但连线会一起断掉。')) return;
      stApi('delete', { pid: p.id, id: d.ndel }).then(function (j) { stRefreshProject(j); toast('删掉了这个节点'); }).catch(function (e) { toast(e.message, 8000); });
      return;
    }
    if (d.out) {
      var z = String(d.out).split(':');
      stSaveParams(z[0], { output: z[1] }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {});
      return;
    }
    if (d.muxratio && p) {
      var node = b.closest('[data-node]');
      stSaveParams(node.getAttribute('data-node'), { ratio: d.muxratio }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {});
      return;
    }
    if (d.refdel) { var q = String(d.refdel).split(':'); stRemoveRef(q[0], +q[1]); return; }
    if (d.lineadd) { var ln = stNodeMap()[d.lineadd]; if (!ln) return; var lines = (ln.params.lines || []).slice(); lines.push({ id: 'l' + (lines.length + 1), text: '', tone: '' }); stSaveParams(d.lineadd, { lines: lines }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }); return; }
    if (d.linedel) { var z2 = String(d.linedel).split(':'); var nn = stNodeMap()[z2[0]]; if (!nn) return; var ls = (nn.params.lines || []).slice(); ls.splice(+z2[1], 1); stSaveParams(z2[0], { lines: ls }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }); return; }
    if (d.lbout) { var z3 = String(d.lbout).split(':'); var no = stNodeMap()[z3[0]]; if (no) stOpenOuts(p, no, z3[1], +z3[2] || 0); return; }
    if (d.playout) {
      var pz = String(d.playout).split(':'), na = stNodeMap()[pz[0]], aouts = (na && na.outputs || []).filter(function (x) { return x.kind === 'audio'; });
      var ao = aouts[+pz[1] || 0];
      if (ao) studioPlay(stOutUrl(p, ao.rel)); else toast('还没有音频');
      return;
    }
    if (d.bulk) { var bx = $('#stBulk-' + d.bulk); if (bx) bx.open = !bx.open; return; }
    if (d.bulkgo) {
      var bn = stNodeMap()[d.bulkgo], ta = document.querySelector('#stBulk-' + d.bulkgo + ' [data-bulk-text]');
      var raw = ta ? String(ta.value || '').split(/\r?\n/) : [];
      var lines = raw.map(function (x) { return x.trim(); }).filter(Boolean).map(function (x, i) { return { id: 'l' + (i + 1), text: x, tone: '' }; });
      if (!lines.length) { toast('先把台词一行一句贴进来'); return; }
      stSaveParams(d.bulkgo, { lines: lines }).then(function () { STUDIO.nodeSig = {}; STUDIO.sig = {}; renderStudio(true); toast('台词换了 ' + lines.length + ' 句'); }).catch(function () {});
      return;
    }
    if (d.act) {
      if (d.act === 'pubgraph' || d.act === 'styleframe') { studioDoAction(d.act, d.nid); return; }
      studioDoAction(d.act, null); return;
    }
  });
})();

function stUploadRefs(files, nid) {
  var p = studioProj(), n = stNodeMap()[nid]; if (!p || !n) return;
  var cur = (n.params.refs || []).slice();
  var list = [].slice.call(files || []).slice(0, Math.max(0, 16 - cur.length));
  if (!list.length) { toast('参考图最多 16 张'); return; }
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
    stSaveParams(nid, { refs: cur }).then(function () { toast('参考图放好了（' + cur.length + '/16）'); STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {});
  });
}
function stRemoveRef(nid, i) {
  var n = stNodeMap()[nid]; if (!n) return;
  var refs = (n.params.refs || []).slice(); refs.splice(i, 1);
  stSaveParams(nid, { refs: refs }).then(function () { STUDIO.nodeSig = {}; renderStudio(true); }).catch(function () {});
}

/* 新建/打开空项目时：没有 graph 就用一份演示骨架兜底（真数据以后端为准） */
function stDemoGraph() { return stDemo().project.graph; }
