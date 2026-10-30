/* ================= 生图（v1.8.15，后端 app/imagegen.py） =================
   一张像 ComfyUI 的工作流：清单 → 视觉方向 → 模型 → 出图 → 输出文件夹，五个节点连成一条线，出图时线上有东西在流。
   下面一格一张图：文件名、用在哪、比例、透明背景、提示词（能改），出好的图直接显示（透明的垫棋盘格），点开看大图、重生成。
   清单拖进这页或者点「选文件」「粘贴」；只把提示词发给 API易，按清单里的文件名存进「生图输出」。 */
var IMG = { st: null, timer: null, n: 0, busy: false, sig: '', bid: null, box: null, typing: {} };
var IMG_RATIO_NAME = { '16:9': '横', '9:16': '竖', '1:1': '方', '4:3': '横', '3:4': '竖', '3:2': '横', '2:3': '竖', '5:4': '横', '4:5': '竖', '21:9': '宽' };
var IMG_DEMO = {
  demo: true, job: null, ratios: ['16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3', '5:4', '4:5', '21:9'],
  models: [{ id: 'gpt-image-2.5-flare', name: 'GPT Image 2.5 Flare', d: '最快 · 按量计费 · 比例、画质、透明背景都能定', kind: 'official' },
    { id: 'gpt-image-2.5-sunburst', name: 'GPT Image 2.5 Sunburst', d: '细节更好、慢一点 · 按量计费', kind: 'official' },
    { id: 'gpt-image-2.5-all', name: 'GPT Image 2.5 All', d: '按次 $0.025 · 不认比例和画质（比例写进提示词）· 透明背景不稳', kind: 'reverse', per: 0.025 }],
  sizes: { '2k': { '16:9': '2048×1152', '9:16': '1152×2048', '1:1': '1536×1536', '4:3': '1792×1344', '3:4': '1344×1792', '3:2': '1920×1280', '2:3': '1280×1920', '5:4': '1600×1280', '4:5': '1280×1600', '21:9': '2240×960' },
    '1k': { '16:9': '1536×864', '9:16': '864×1536', '1:1': '1024×1024', '4:3': '1280×960', '3:4': '960×1280', '3:2': '1536×1024', '2:3': '1024×1536', '5:4': '1280×1024', '4:5': '1024×1280', '21:9': '1680×720' } },
  quality: [['low', '草稿'], ['medium', '标准'], ['high', '精细'], ['xhigh', '更精细'], ['max', '最高']],
  tokens: { low: 196, medium: 439, high: 1756, xhigh: 3122, max: 7024, auto: 439 }, usd_out: 0.00003, usdCny: 7.2,
  cfg: { model: 'gpt-image-2.5-flare', quality: 'medium', res: '2k', conc: 3, notext: true, withdir: false, key: true, hint: '••••0000' },
  month: { n: 18, usd: 0.61 }, out: 'F:\\Agent\\生图输出',
  board: { id: 1, title: 'GitHub AI 周榜 · 测试 3 · 生图清单', md_name: '测试3_生图清单.md', warn: [], dir: 'F:\\Agent\\生图输出\\2026-10-30_GitHub AI 周榜 · 测试 3', exists: true,
    direction: '深夜地铁导视风：深蓝近黑的底，荧光黄和青色的细线条，扁平的等距插画，像城市交通图。和测试 1 的玻璃拟态、测试 2 的纸张拼贴都不一样。',
    items: [
      { id: '1', file: 'img01_重点_地铁站.png', use: '本周重点 · Orca 类比开场', ratio: '16:9', transparent: false, st: 'ok', w: 2048, h: 1152, sec: 31, usd: 0.026, ver: 1,
        prompt: '等距视角的深夜地铁站台，深蓝近黑的背景，荧光黄的导视线条沿着地面延伸，五个空的灶台整齐排开，扁平插画，干净的几何形状，柔和的青色辉光。' },
      { id: '2', file: 'img02_道具_灶台.png', use: '本周重点 · 五个灶台', ratio: '1:1', transparent: true, st: 'ok', w: 1536, h: 1536, alpha: true, sec: 24, usd: 0.028, ver: 1,
        prompt: '一个独立的小灶台，等距视角，扁平插画，荧光黄描边，青色火焰，干净的几何形状。' },
      { id: '3', file: 'img03_第五名_图谱.png', use: '第五名 Graphify', ratio: '21:9', transparent: false, st: 'run', run_s: 12,
        prompt: '一张发光的关系图谱，节点是小圆点，连线是细的荧光黄线条，深蓝近黑背景，像地铁线路图。' },
      { id: '4', file: 'img04_第四名_调色板.png', use: '第四名 Impeccable', ratio: '1:1', transparent: true, st: 'queue',
        prompt: '一块扁平的调色板，几个荧光色的色块，等距视角，干净的描边。' },
      { id: '5', file: 'img05_第三名_剪刀.png', use: '第三名 Ponytail', ratio: '4:5', transparent: true, st: 'err', err: '内容审核没过：改一改这条提示词再重生成',
        prompt: '一把把长代码剪短的剪刀，扁平插画，荧光黄和青色。' },
      { id: '6', file: 'img06_封面.png', use: '封面主图', ratio: '16:9', transparent: false, st: 'idle',
        prompt: '深夜城市地铁线路图的抽象俯视，五条发光的线路在中心交汇，深蓝近黑背景，荧光黄、青色、品红的线条，留出左侧大片空白。' }] }
};

function imgLoad() {
  if (!useLive()) { IMG.st = IMG_DEMO; return Promise.resolve(IMG_DEMO); }
  return api('GET', '/api/img', null, 8000).then(function (j) { IMG.st = j; return j; });
}
function imgEnter() {
  imgLoad().then(renderImg).catch(function () { if (!IMG.st) { IMG.st = IMG_DEMO; renderImg(); } });
  clearInterval(IMG.timer);
  IMG.timer = setInterval(function () {
    IMG.n++;
    var run = IMG.st && IMG.st.job && IMG.st.job.st === 'run';
    if (!useLive() || IMG.busy || (!run && IMG.n % 5)) return;
    IMG.busy = true;
    imgLoad().then(imgSync).catch(function () {}).then(function () { IMG.busy = false; });
  }, 1000);
}
function imgLeave() { clearInterval(IMG.timer); IMG.timer = null; imgBoxClose(); }

/* ---------- 小工具 ---------- */
function imgModel() { var s = IMG.st; return s.models.filter(function (m) { return m.id === s.cfg.model; })[0] || { id: s.cfg.model, name: s.cfg.model, kind: 'official', d: '自己填的模型' }; }
function imgPx(it) { var z = (IMG.st.sizes[IMG.st.cfg.res] || IMG.st.sizes['2k'])[it.ratio] || '1024×1024'; return z; }
function imgUsd(it) {
  var s = IMG.st, m = imgModel();
  if (m.per) return m.per;
  var p = imgPx(it).split('×'), q = s.cfg.quality || 'medium';
  return (s.tokens[q] || 439) * (+p[0] * +p[1] / 1048576) * s.usd_out;
}
function imgMoney(usd) { return '$' + (usd < 0.01 && usd > 0 ? usd.toFixed(3) : usd.toFixed(2)) + '（≈¥' + (usd * (IMG.st.usdCny || 7.2)).toFixed(2) + '）'; }
function imgCount() {
  var b = IMG.st.board, c = { n: 0, ok: 0, err: 0, run: 0, queue: 0, idle: 0 };
  if (!b) return c;
  b.items.forEach(function (it) { c.n++; c[it.st] = (c[it.st] || 0) + 1; });
  return c;
}
function imgFrame(r) {   /* 还没出图时：按比例画一个虚线框，标上比例 */
  var p = r.split(':'), w = +p[0], h = +p[1], k = 100 / Math.max(w, h);
  return '<svg class="ig-ph" viewBox="-4 -4 ' + (w * k + 8) + ' ' + (h * k + 8) + '" preserveAspectRatio="xMidYMid meet" aria-hidden="true"><rect x="0" y="0" width="' + (w * k) + '" height="' + (h * k) + '" rx="2"/>' +
    '<text x="' + (w * k / 2) + '" y="' + (h * k / 2) + '" font-size="' + (Math.min(w, h) * k * 0.2).toFixed(1) + '">' + esc(r) + '</text></svg>';
}

/* ---------- 整页 ---------- */
function renderImg() {
  var v = $('#view-img'), s = IMG.st;
  if (!s) { v.innerHTML = '<div class="empty">正在读取…</div>'; imgEnter(); return; }
  var m = s.month || { n: 0, usd: 0 };
  v.innerHTML = '<div class="page fill ig">' +
    '<div class="ph ig-top"><h1>生图</h1><span class="sub">API易 · GPT Image 2.5 · 只把生图清单里的提示词发过去 · 按清单里的文件名存进「生图输出」</span>' +
      '<span class="ig-pills"><span class="pill" id="igKey"></span><span class="pill num" title="本月在这里出的图（按 API易 返回的用量估的，以 API易 账单为准）">本月 $' + (+m.usd || 0).toFixed(2) + ' · ' + (m.n || 0) + ' 张</span></span></div>' +
    '<div class="ig-flow" id="igFlow"></div>' +
    '<div class="ig-grid" id="igGrid"></div>' +
    '<input type="file" id="igFile" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden>' +
    '<div class="ig-drop" id="igDrop" aria-hidden="true"><b>松开就认这份清单</b></div></div>';
  IMG.bid = null; IMG.sig = '';
  imgSync();
}
function imgSync() {
  if (S.view !== 'img' || !$('#igFlow')) return;
  var s = IMG.st, k = $('#igKey');
  if (k) { k.textContent = s.cfg.key ? 'API易 Key 已填' : '还没填 API易 Key'; k.style.setProperty('--c', s.cfg.key ? 'var(--ok)' : 'var(--c-neu)'); }
  var f = imgFlowHTML(), fl = $('#igFlow');
  if (fl.dataset.sig !== f) { fl.innerHTML = f; fl.dataset.sig = f; }
  fl.classList.toggle('run', !!(s.job && s.job.st === 'run'));
  imgGrid();
  if (IMG.box && IMG.box.id) imgBoxOpen(IMG.box.id, true);
}

/* ---------- 工作流：五个节点 ---------- */
function imgNode(cls, kind, name, body, live) {
  return '<section class="ig-node ' + cls + (live ? ' live' : '') + '"><div class="ig-nh"><i></i><span class="ig-nk">' + kind + '</span><b>' + name + '</b></div><div class="ig-nb">' + body + '</div></section>';
}
function imgFlowHTML() {
  var s = IMG.st, b = s.board, j = s.job, run = !!(j && j.st === 'run'), c = imgCount(), m = imgModel();
  var n1 = b ? '<div class="ig-kpi"><b class="num">' + b.items.length + '</b><span>张</span></div><div class="ig-src" title="' + esc(b.title) + '">' + esc(b.md_name || b.title) + '</div>' +
      (b.warn && b.warn.length ? '<div class="ig-warn" title="' + esc(b.warn.join('\n')) + '">' + b.warn.length + ' 处没认全（鼠标放上来看）</div>' : '<div class="cap">每条都认出来了</div>')
    : '<div class="cap">把视频窗口出的生图清单（.md）拖到这页上</div>';
  n1 += '<div class="ig-btns"><button class="btn" data-act="pick"' + (run ? ' disabled' : '') + '>' + (b ? '换一份' : '选文件') + '</button><button class="btn" data-act="paste"' + (run ? ' disabled' : '') + '>粘贴</button>' +
    (b ? '<button class="btn ig-x" data-act="clear" title="清掉这份清单（文件夹里的图不动）"' + (run ? ' disabled' : '') + '>' + ICONS.cross + '</button>' : '') + '</div>';
  var n2 = (b && b.direction ? '<p class="ig-dir" title="' + esc(b.direction) + '">' + esc(b.direction) + '</p>' : '<p class="ig-dir cap">' + (b ? '清单里没写视觉方向' : '上传清单后，这期的视觉方向显示在这里') + '</p>') +
    '<div class="ig-sws"><button class="ig-sw" data-cfg="withdir" aria-pressed="' + !!s.cfg.withdir + '" title="正本要求每条提示词里已经写了统一画风，所以默认不拼">拼进每条提示词</button>' +
    '<button class="ig-sw" data-cfg="notext" aria-pressed="' + !!s.cfg.notext + '" title="正本规矩 6：图里不放文字（AI 画的字容易乱码）">加一句「不要文字」</button></div>';
  var qs = s.quality.filter(function (q) { return ['low', 'medium', 'high'].indexOf(q[0]) >= 0 || q[0] === s.cfg.quality; });
  var n3 = '<select class="inp ig-model" id="igModel"' + (run ? ' disabled' : '') + '>' + s.models.map(function (x) { return '<option value="' + esc(x.id) + '"' + (x.id === m.id ? ' selected' : '') + '>' + esc(x.name) + '</option>'; }).join('') +
      (s.models.some(function (x) { return x.id === m.id; }) ? '' : '<option selected>' + esc(m.id) + '</option>') + '</select>' +
    '<div class="ig-md">' + esc(m.d || '') + '</div>' +
    (m.kind === 'reverse' ? '<div class="ig-warn">这个模型不认比例和画质：比例写进提示词，透明背景不一定透</div>'
      : '<div class="ig-segs"><div class="seg ig-seg" role="group" aria-label="画质">' + qs.map(function (q) { return '<button data-q="' + q[0] + '" aria-pressed="' + (s.cfg.quality === q[0]) + '"' + (run ? ' disabled' : '') + '>' + q[1] + '</button>'; }).join('') + '</div>' +
        '<div class="seg ig-seg" role="group" aria-label="尺寸">' + [['2k', '2K'], ['1k', '1K']].map(function (r) { return '<button data-res="' + r[0] + '" aria-pressed="' + (s.cfg.res === r[0]) + '"' + (run ? ' disabled' : '') + '>' + r[1] + '</button>'; }).join('') + '</div></div>');
  var todo = b ? b.items.filter(function (it) { return it.st !== 'ok'; }) : [], all = b ? b.items : [];
  var sum = function (xs) { return xs.reduce(function (a, it) { return a + imgUsd(it); }, 0); };
  var n4;
  if (run) {
    var pct = j.n ? Math.round((j.done + j.fail) / j.n * 100) : 0;
    n4 = '<div class="ig-kpi"><b class="num">' + (j.done + j.fail) + '</b><span>/ ' + j.n + ' 张 · ' + ttsDur(j.elapsed || 0) + '</span></div>' +
      '<div class="bar1 ig-bar"><i style="transform:scaleX(' + (pct / 100) + ')"></i></div>' +
      '<div class="cap num">同时出 ' + j.conc + ' 张 · 已花约 ' + imgMoney(j.usd || 0) + '</div>' +
      (j.msg ? '<div class="ig-warn">' + esc(j.msg) + '</div>' : '') +
      '<div class="ig-btns"><button class="btn" data-act="stop">停下</button></div>';
  } else {
    n4 = '<div class="ig-kpi"><b class="num">' + c.ok + '</b><span>/ ' + c.n + ' 张出好了</span></div>' +
      (j && j.msg ? '<div class="ig-jmsg' + (j.fail || j.fatal ? ' bad' : ' ok') + '">' + esc(j.msg) + '</div>' : '<div class="cap">' + (b ? '全部出一遍约 ' + imgMoney(sum(all)) : '一张约 $0.01~0.03') + '</div>') +
      '<div class="ig-btns"><button class="btn primary" data-act="run"' + (!b || !s.cfg.key ? ' disabled' : '') + '>全部生成</button>' +
      '<button class="btn" data-act="missing"' + (!todo.length || !s.cfg.key || todo.length === all.length ? ' disabled' : '') + ' title="只出还没出好的' + (todo.length ? '（' + todo.length + ' 张，约 ' + imgMoney(sum(todo)) + '）' : '') + '">只补没出的' + (todo.length && todo.length < all.length ? ' ' + todo.length : '') + '</button></div>' +
      (!s.cfg.key && !s.demo ? '<button class="tts-link" data-act="gokey">去 设置 › 云端 填 API易 Key</button>' : '');
  }
  var n5 = '<div class="ig-path" title="' + esc(b && b.dir ? b.dir : s.out) + '">' + esc((b && b.dir ? b.dir : s.out).split(/[\\/]/).pop()) + '</div>' +
    '<div class="cap">' + (b ? (c.ok ? c.ok + ' 张按清单的文件名存好了；重生成的旧图挪进「旧版」' : '出好的图按清单里的文件名存在这里') : '一份清单一个文件夹，名字带日期') + '</div>' +
    '<div class="ig-btns"><button class="btn" data-act="open">打开文件夹</button><button class="btn" data-act="zip"' + (c.ok ? '' : ' disabled') + ' title="把出好的图打成一个 zip（不含旧版），发给视频窗口">打包 zip</button></div>';
  return imgNode('n-src', '输入', '生图清单', n1, false) + '<i class="ig-link"></i>' +
    imgNode('n-dir', '风格', '视觉方向', n2, false) + '<i class="ig-link"></i>' +
    imgNode('n-model', 'API易', esc(m.name.replace('GPT Image ', 'GPT Image ')), n3, run) + '<i class="ig-link"></i>' +
    imgNode('n-run', '队列', run ? '出图中' : '出图', n4, run) + '<i class="ig-link"></i>' +
    imgNode('n-out', '输出', '生图输出', n5, false);
}

/* ---------- 一格一张图 ---------- */
function imgCardSig(it) { return [it.st, it.ver, it.err, it.warn, it.run_s, it.ratio, it.transparent, it.edited, IMG.st.cfg.res, IMG.st.cfg.model, IMG.st.cfg.quality].join('|'); }
function imgPv(it) {
  var s = IMG.st;
  if (it.st === 'ok') {
    var src = s.demo ? '' : '/api/img/file/' + encodeURIComponent(it.id) + '?v=' + (it.ver || 0);
    return (s.demo ? '<span class="ig-demo" style="--h:' + (it.id * 47 % 360) + '"></span>' : '<img src="' + src + '" alt="' + esc(it.file) + '" loading="lazy" decoding="async">') +
      (it.transparent ? '<span class="ig-tag' + (it.alpha ? '' : ' bad') + '">' + (it.alpha ? '透明 ✓' : '没透明') + '</span>' : '');
  }
  if (it.st === 'err') return '<span class="ig-errx">' + esc(it.err || '没出来') + '</span>';
  return imgFrame(it.ratio) + (it.st === 'run' ? '<span class="ig-runx num">出图中 · ' + (it.run_s || 0) + ' 秒</span>' : it.st === 'queue' ? '<span class="ig-runx">排队中</span>' : '');
}
function imgStx(it) {
  if (it.st === 'ok') return '<span class="num">' + (it.w ? it.w + '×' + it.h : '') + (it.sec != null ? ' · ' + Math.round(it.sec) + ' 秒' : '') + (it.usd != null ? ' · $' + (+it.usd).toFixed(3) : '') + '</span>' + (it.old ? '<span class="cap"> · 文件夹里原来就有</span>' : '');
  if (it.st === 'run' || it.st === 'queue') return '<span class="cap">约 ' + imgMoney(imgUsd(it)) + '</span>';
  if (it.st === 'err') return '<span class="ig-bad">没出来</span>';
  return '<span class="cap num">' + (imgModel().kind === 'reverse' ? '比例写进提示词' : imgPx(it)) + ' · 约 $' + imgUsd(it).toFixed(3) + '</span>';
}
function imgCard(it, i) {
  var s = IMG.st, run = it.st === 'run' || it.st === 'queue', busy = s.job && s.job.st === 'run';
  return '<article class="ig-card st-' + it.st + '" data-id="' + esc(it.id) + '" data-sig="' + esc(imgCardSig(it)) + '" style="--i:' + Math.min(i, 12) + '">' +
    '<div class="ig-ch"><span class="ig-no num">' + pad(+it.id || i + 1) + '</span><span class="ig-fn" title="' + esc(it.file) + '">' + esc(it.file) + '</span><i class="ig-dot" title="' + ({ ok: '出好了', run: '出图中', queue: '排队中', err: '没出来', idle: '还没出' }[it.st] || '') + '"></i></div>' +
    '<div class="ig-use" title="' + esc(it.use || '') + '">' + esc(it.use || '（清单里没写用在哪）') + '</div>' +
    '<button class="ig-pv' + (it.transparent ? ' t-on' : '') + '" data-act="view" aria-label="看大图：' + esc(it.file) + '"' + (it.st === 'ok' ? '' : ' tabindex="-1"') + '>' + imgPv(it) + '</button>' +
    (it.warn ? '<div class="ig-warn">' + esc(it.warn) + '</div>' : '') +
    '<div class="ig-ctl"><select class="inp ig-ratio" data-k="ratio" aria-label="比例"' + (run ? ' disabled' : '') + '>' + s.ratios.map(function (r) { return '<option value="' + r + '"' + (r === it.ratio ? ' selected' : '') + '>' + r + ' ' + IMG_RATIO_NAME[r] + '</option>'; }).join('') + '</select>' +
      '<button class="ig-tp" data-k="transparent" aria-pressed="' + !!it.transparent + '"' + (run ? ' disabled' : '') + ' title="透明背景：道具、图标开；背景图不开">透明背景 ' + (it.transparent ? '开' : '不开') + '</button>' +
      (it.edited ? '<span class="ig-ed">改过</span>' : '') + '</div>' +
    '<textarea class="inp ig-pr" data-k="prompt" spellcheck="false" rows="3"' + (run ? ' disabled' : '') + ' aria-label="提示词">' + esc(it.prompt || '') + '</textarea>' +
    '<div class="ig-cf"><span class="ig-stx">' + imgStx(it) + '</span><button class="btn ig-go" data-act="one"' + (busy || !s.cfg.key || !(it.prompt || '').trim() ? ' disabled' : '') + '>' + (it.st === 'ok' || it.st === 'err' ? '重生成' : '生成') + '</button></div></article>';
}
function imgGrid() {
  var s = IMG.st, b = s.board, g = $('#igGrid'); if (!g) return;
  if (!b) {
    IMG.bid = null;
    g.classList.add('empty');
    g.innerHTML = '<div class="ig-empty"><div class="ig-eic" aria-hidden="true">' + imgFrame('16:9') + '</div><b>把生图清单拖到这里</b>' +
      '<span>视频窗口按《自媒体正本》出的 .md：这期的视觉方向 + 每条的文件名（img01_重点_地铁站.png）、用在哪、比例、透明背景开不开、提示词。表格、标题加列表、编号列表几种写法都认。</span>' +
      '<span class="ig-btns"><button class="btn primary" data-act="pick">选文件</button><button class="btn" data-act="paste">粘贴</button></span></div>';
    return;
  }
  g.classList.remove('empty');
  if (IMG.bid !== b.id || g.children.length !== b.items.length) {
    IMG.bid = b.id;
    g.innerHTML = b.items.map(imgCard).join('');
    return;
  }
  b.items.forEach(function (it, i) {
    var el = g.children[i]; if (!el || el.dataset.id !== it.id) return;
    var sig = imgCardSig(it);
    if (el.dataset.sig === sig && !(s.job && s.job.st === 'run')) return;
    var foc = document.activeElement && el.contains(document.activeElement) ? document.activeElement : null;
    if (foc && foc.classList.contains('ig-pr')) {           /* 正在改提示词：别的地方照样更新，输入框不动 */
      el.className = 'ig-card st-' + it.st;
      el.querySelector('.ig-pv').innerHTML = imgPv(it);
      el.querySelector('.ig-stx').innerHTML = imgStx(it);
      return;
    }
    if (el.dataset.sig === sig) { var sx = el.querySelector('.ig-stx'), h = imgStx(it); if (sx.innerHTML !== h) sx.innerHTML = h; var pv = el.querySelector('.ig-pv'), ph = imgPv(it); if (it.st === 'run' && pv.innerHTML !== ph) pv.innerHTML = ph; return; }
    var t = document.createElement('div'); t.innerHTML = imgCard(it, i);
    var nw = t.firstChild;
    if (el.dataset.sig.split('|')[1] === String(it.ver) && it.st === 'ok') {   /* 图没换：别重新加载图片 */
      var oi = el.querySelector('.ig-pv img'), ni = nw.querySelector('.ig-pv img');
      if (oi && ni) ni.parentNode.replaceChild(oi, ni);
    }
    nw.style.animation = 'none';
    el.replaceWith(nw);
  });
}

/* ---------- 看大图 / 粘贴清单 ---------- */
function imgBoxClose() { var x = $('#igBox'); if (x) x.remove(); IMG.box = null; }
function imgBox(html, wide) {
  var x = $('#igBox');
  if (!x) { x = document.createElement('div'); x.id = 'igBox'; x.className = 'ig-box'; x.setAttribute('role', 'dialog'); x.setAttribute('aria-modal', 'true'); document.body.appendChild(x); }
  x.innerHTML = '<div class="ig-bbg" data-act="boxclose"></div><div class="ig-bp' + (wide ? ' wide' : '') + '">' + html + '</div>';
  return x;
}
function imgBoxOpen(id, refresh) {
  var b = IMG.st.board, it = b && b.items.filter(function (x) { return x.id === id; })[0];
  if (!it || it.st !== 'ok') { if (!refresh) return; imgBoxClose(); return; }
  var sig = id + '|' + it.ver;
  if (refresh && IMG.box && IMG.box.sig === sig) return;
  IMG.box = { id: id, sig: sig };
  var src = IMG.st.demo ? '' : '/api/img/file/' + encodeURIComponent(it.id) + '?v=' + (it.ver || 0);
  imgBox('<div class="ig-big' + (it.transparent ? ' t-on' : '') + '">' + (src ? '<img src="' + src + '" alt="' + esc(it.file) + '">' : '<span class="ig-demo" style="--h:' + (it.id * 47 % 360) + '"></span>') + '</div>' +
    '<div class="ig-bi"><b>' + esc(it.file) + '</b><span class="cap num">' + esc(it.use || '') + ' · ' + it.ratio + ' · ' + (it.w ? it.w + '×' + it.h : '') + (it.transparent ? ' · ' + (it.alpha ? '透明背景' : '要透明但没透明') : '') + '</span>' +
    '<p class="ig-bpr">' + esc(it.prompt) + '</p>' +
    '<span class="ig-btns"><button class="btn" data-act="one" data-id="' + esc(it.id) + '"' + (IMG.st.job && IMG.st.job.st === 'run' ? ' disabled' : '') + '>重生成</button><button class="btn" data-act="boxclose">关闭（Esc）</button></span></div>', true);
}
function imgPaste() {
  IMG.box = { paste: true };
  imgBox('<div class="ig-bi"><b>把生图清单粘贴进来</b><span class="cap">视频窗口出的那份 Markdown，整份复制过来就行</span>' +
    '<textarea class="inp ig-ptx" id="igPaste" spellcheck="false" placeholder="# 这期的生图清单&#10;&#10;## 这期的视觉方向&#10;……&#10;&#10;### img01_重点_地铁站.png（用在：本周重点）&#10;- 比例：16:9&#10;- 透明背景：不开&#10;- 提示词：……"></textarea>' +
    '<span class="ig-btns"><button class="btn primary" data-act="pasteok">认这份清单</button><button class="btn" data-act="boxclose">取消</button></span></div>');
  setTimeout(function () { var t = $('#igPaste'); if (t) t.focus(); }, 30);
}

/* ---------- 动作 ---------- */
function imgLoadMd(md, name) {
  if (!useLive()) { toast('演示模式：连上后端才能认清单'); return; }
  api('POST', '/api/img/load', { md: md, name: name || '' }, 20000).then(function (j) {
    IMG.st = j; imgBoxClose(); IMG.bid = null; imgSync();
    var b = j.board, ok = b.items.filter(function (it) { return it.st === 'ok'; }).length;
    toast('认出 ' + b.items.length + ' 张' + (ok ? '，文件夹里已经有 ' + ok + ' 张' : '') + (b.warn.length ? '；' + b.warn.length + ' 处没认全，看卡片' : ''), 5000);
  }).catch(function (e) { toast(e.message, 7000); });
}
function imgReadFile(file) {
  if (!file) return;
  if (file.size > 2e6) { toast('这个文件太大了，是不是选错了（清单一般几十 KB）'); return; }
  var r = new FileReader();
  r.onload = function () { imgLoadMd(String(r.result || ''), file.name); };
  r.readAsText(file, 'utf-8');
}
function imgSet(k, v) {
  IMG.st.cfg[{ imgModel: 'model', imgQuality: 'quality', imgRes: 'res', imgWithDir: 'withdir', imgNoText: 'notext' }[k]] = v;
  imgSync();
  if (!useLive()) return;
  var o = {}; o[k] = v;
  api('PUT', '/api/settings', o).catch(function (e) { toast(e.message); });
}
var imgEditT = {};
function imgEdit(id, patch, now) {
  var b = IMG.st.board, it = b && b.items.filter(function (x) { return x.id === id; })[0]; if (!it) return;
  Object.keys(patch).forEach(function (k) { it[k] = patch[k]; });
  if (!useLive()) { imgGrid(); return; }
  var send = function () {   /* 回来的只拿「改过」：别的以本地为准（回来之前可能又改了别的） */
    api('PATCH', '/api/img/item/' + encodeURIComponent(id), patch).then(function (j) { it.edited = j.item.edited; imgGrid(); }).catch(function (e) { toast(e.message); });
  };
  if (now) { if (!patch.prompt) imgGrid(); send(); return; }
  clearTimeout(imgEditT[id]);                 /* 提示词：停手 0.6 秒再存 */
  imgEditT[id] = setTimeout(send, 600);
}
function imgRun(body) {
  if (!useLive()) { toast('演示模式：连上后端才能出图'); return; }
  api('POST', '/api/img/run', body, 15000).then(function (j) { IMG.st.job = j.job; return imgLoad(); }).then(imgSync).catch(function (e) { toast(e.message, 6000); });
}

$('#view-img').addEventListener('click', function (ev) {
  var t = ev.target.closest('[data-act],[data-cfg],[data-q],[data-res],[data-k="transparent"]'); if (!t || t.disabled) return;
  var live = useLive(), card = t.closest('.ig-card'), act = t.dataset.act;
  if (t.dataset.cfg) imgSet(t.dataset.cfg === 'withdir' ? 'imgWithDir' : 'imgNoText', t.getAttribute('aria-pressed') !== 'true');
  else if (t.dataset.q) imgSet('imgQuality', t.dataset.q);
  else if (t.dataset.res) imgSet('imgRes', t.dataset.res);
  else if (t.dataset.k === 'transparent' && card) imgEdit(card.dataset.id, { transparent: t.getAttribute('aria-pressed') !== 'true' }, true);
  else if (act === 'pick') $('#igFile').click();
  else if (act === 'paste') imgPaste();
  else if (act === 'view' && card) imgBoxOpen(card.dataset.id);
  else if (act === 'gokey') { S.sec = 'cloud'; renderSettings(); goView('settings'); }
  else if (!live) toast('演示模式：连上后端才能用');
  else if (act === 'clear') api('POST', '/api/img/clear', {}).then(function (j) { IMG.st = j; imgSync(); toast('清掉了（文件夹里的图没动）'); }).catch(function (e) { toast(e.message); });
  else if (act === 'run') imgRun({});
  else if (act === 'missing') imgRun({ missing: true });
  else if (act === 'one' && card) imgRun({ ids: [card.dataset.id] });
  else if (act === 'stop') api('POST', '/api/img/stop', {}).then(function (j) { IMG.st.job = j.job; imgSync(); toast('没开始的不出了，正在出的出完就停'); });
  else if (act === 'open') api('POST', '/api/img/open', {}).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); });
  else if (act === 'zip') { t.disabled = true; api('POST', '/api/img/zip', {}, 60000).then(function (j) { toast(j.msg, 5000); t.disabled = false; }).catch(function (e) { toast(e.message); t.disabled = false; }); }
});
document.addEventListener('click', function (ev) {   /* 弹出的那一层（看大图、粘贴）在 body 上 */
  var t = ev.target.closest('#igBox [data-act]'); if (!t || t.disabled) return;
  var act = t.dataset.act;
  if (act === 'boxclose') imgBoxClose();
  else if (act === 'pasteok') { var v = ($('#igPaste') || {}).value || ''; if (!v.trim()) { toast('先把清单粘贴进来'); return; } imgLoadMd(v, ''); }
  else if (act === 'one') { imgBoxClose(); imgRun({ ids: [t.dataset.id] }); }
});
document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && $('#igBox')) { imgBoxClose(); ev.stopPropagation(); } }, true);
$('#view-img').addEventListener('change', function (ev) {
  var t = ev.target, card = t.closest('.ig-card');
  if (t.id === 'igFile') { imgReadFile(t.files[0]); t.value = ''; }
  else if (t.id === 'igModel') imgSet('imgModel', t.value);
  else if (t.dataset.k === 'ratio' && card) imgEdit(card.dataset.id, { ratio: t.value }, true);
});
$('#view-img').addEventListener('input', function (ev) {
  var t = ev.target, card = t.closest('.ig-card');
  if (t.dataset.k === 'prompt' && card) imgEdit(card.dataset.id, { prompt: t.value });
});
['dragenter', 'dragover'].forEach(function (k) {
  $('#view-img').addEventListener(k, function (ev) {
    if (!ev.dataTransfer || [].indexOf.call(ev.dataTransfer.types || [], 'Files') < 0) return;
    ev.preventDefault(); var d = $('#igDrop'); if (d) d.classList.add('on');
  });
});
$('#view-img').addEventListener('dragleave', function (ev) { if (ev.target.id === 'igDrop' || !ev.relatedTarget || !$('#view-img').contains(ev.relatedTarget)) { var d = $('#igDrop'); if (d) d.classList.remove('on'); } });
$('#view-img').addEventListener('drop', function (ev) {
  var d = $('#igDrop'); if (d) d.classList.remove('on');
  if (!ev.dataTransfer || !ev.dataTransfer.files.length) return;
  ev.preventDefault();
  if (IMG.st && IMG.st.job && IMG.st.job.st === 'run') { toast('正在出图，等这批出完再换清单'); return; }
  imgReadFile(ev.dataTransfer.files[0]);
});
