/* ================= 生图「渲染舱」（v1.8.16，后端 app/imagegen.py） =================
   作者定的界面档次标准（Project 里 UI标准_生图渲染舱草图.html）：整页底下一块画布——点阵球、刻度环、雷达、频谱、卫星、电线、粒子，
   上面一层切角面板。四个标签：
   - 单张：文生图，或者带参考图生图（拖进来 / 选 / Ctrl+V 粘贴），一次 1~4 张
   - 批量：上传生图清单（.md），左边一行一张，一张一张出；点一行能改提示词、比例、透明背景、重生成
   - 历史：出过的每一张，能再来一张、当参考图、打开文件夹
   - 模板：存起来的提示词 + 参考图 + 比例，一点就填好
   模型在右上角换（按厂商分好的列表，能用 Key 向 API易 拉最新的）。出图时：中间的球转快、进度环走、粒子拼成画面；
   图回来了就用真图的颜色把粒子染上，图浮出来、缩小、沿线飞进右边的格子。动效「关闭」时只画一帧不动。 */
var IMG = { st: null, timer: null, n: 0, busy: false, tab: null, sel: null, prompt: '', refs: [], ratio: '1:1', cnt: 1, trans: false,
  hist: null, hq: '', hsel: null, cat: null, vend: null, log: [], wait: {}, mine: null, booted: false, box: null, sig: {} };
var IMG_RNAME = { '16:9': '横', '9:16': '竖', '1:1': '方', '4:3': '横', '3:4': '竖', '3:2': '横', '2:3': '竖', '5:4': '横', '4:5': '竖', '21:9': '宽' };
var IMG_TABS = [['single', 'SINGLE', '单张'], ['batch', 'BATCH', '批量'], ['hist', 'HISTORY', '历史'], ['tpl', 'PRESET', '模板']];
var IMG_DEMO = (function () {
  var R = ['16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3', '5:4', '4:5', '21:9'];
  var Z = { '1k': [[1280, 720], [720, 1280], [1280, 1280], [1280, 960], [960, 1280], [1280, 848], [848, 1280], [1280, 1024], [1024, 1280], [1280, 544]],
    '2k': [[2048, 1152], [1152, 2048], [2048, 2048], [2048, 1536], [1536, 2048], [2048, 1360], [1360, 2048], [2048, 1632], [1632, 2048], [2048, 864]],
    '4k': [[3840, 2160], [2160, 3840], [2880, 2880], [3312, 2480], [2480, 3312], [3520, 2336], [2336, 3520], [3216, 2560], [2560, 3216], [3840, 1632]] };
  var sizes = {}; Object.keys(Z).forEach(function (t) { sizes[t] = {}; R.forEach(function (r, i) { sizes[t][r] = Z[t][i][0] + '×' + Z[t][i][1]; }); });
  var it = function (id, file, use, ratio, tr, st, prompt, x) { return Object.assign({ id: id, file: file, use: use, ratio: ratio, transparent: tr, st: st, prompt: prompt, ver: 1, w: 0, h: 0 }, x || {}); };
  var now = Date.now() / 1000;
  return {
    demo: true, ratios: R, tiers: ['1k', '2k', '4k'], sizes: sizes, quality: { auto: '自动', low: '低', medium: '中', high: '高', xhigh: '更高', max: '最高' },
    tokens: { low: 196, medium: 439, high: 1756, xhigh: 3122, max: 7024, auto: 439 }, usd_out: 0.00003, usdCny: 7.2,
    model: { id: 'gpt-image-2.5-sunburst-vip', name: 'GPT Image 2.5 Sunburst VIP', route: '逆向', price: 0.03, sec: 80, d: '高质量 2.5 Adobe 线路，画质与编辑精度优先；30 档尺寸（1K/2K/4K）、4 档画质、透明背景',
      warn: '当前不稳定', known: true, proto: 'openai', refs: 8, trans: 'api', size: 'preset', v: 'openai', q: ['auto', 'low', 'medium', 'high'], tiers: ['1k', '2k', '4k'], vendor: 'OpenAI' },
    cfg: { model: 'gpt-image-2.5-sunburst-vip', quality: 'high', tier: '2k', notext: true, withdir: false, key: true, hint: '••••0000', base: 'https://api.apiyi.com/v1' },
    month: { n: 18, usd: 0.54 }, out: 'F:\\Agent\\生图输出', templates: [
      { id: 't1', name: '封面 · 深夜地铁风', prompt: '深夜城市地铁线路图的抽象俯视，五条发光的线路在中心交汇，深蓝近黑背景，荧光黄、青色、品红的线条，留出左侧大片空白。', model: 'gpt-image-2.5-sunburst-vip', ratio: '16:9', tier: '2k', quality: 'high', transparent: false, n: 2, refs: 0 },
      { id: 't2', name: '道具 · 透明小图标', prompt: '一个独立的小物件，等距视角，扁平插画，荧光黄描边，青色高光，干净的几何形状。', model: 'gpt-image-2.5-sunburst-vip', ratio: '1:1', tier: '2k', quality: 'high', transparent: true, n: 1, refs: 0 }],
    recent: [{ id: 3, ts: now - 600, kind: 'single', title: '单张', file: '221830_一只发光的水母.png', model: 'gpt-image-2.5-sunburst-vip', prompt: '一只发光的水母漂在深蓝的海里，触须像光纤。', ratio: '3:4', tier: '2k', quality: 'high', transparent: false, w: 1536, h: 2048, alpha: false, usd: 0.03, sec: 84, refs: 0, exists: true },
      { id: 2, ts: now - 900, kind: 'batch', title: 'GitHub AI 周榜 · 测试 3', file: 'img02_道具_灶台.png', model: 'gpt-image-2.5-sunburst-vip', prompt: '一个独立的小灶台，等距视角，扁平插画。', ratio: '1:1', tier: '2k', quality: 'high', transparent: true, w: 2048, h: 2048, alpha: true, usd: 0.03, sec: 77, refs: 0, exists: true },
      { id: 1, ts: now - 1000, kind: 'batch', title: 'GitHub AI 周榜 · 测试 3', file: 'img01_重点_地铁站.png', model: 'gpt-image-2.5-sunburst-vip', prompt: '等距视角的深夜地铁站台，荧光黄的导视线条。', ratio: '16:9', tier: '2k', quality: 'high', transparent: false, w: 2048, h: 1152, alpha: false, usd: 0.03, sec: 91, refs: 0, exists: true }],
    board: { id: 1, title: 'GitHub AI 周榜 · 测试 3 · 生图清单', md_name: '测试3_生图清单.md', warn: [], dir: 'F:\\Agent\\生图输出\\2026-10-30_GitHub AI 周榜 · 测试 3', exists: true,
      direction: '深夜地铁导视风：深蓝近黑的底，荧光黄和青色的细线条，扁平的等距插画，像城市交通图。', items: [
        it('1', 'img01_重点_地铁站.png', '本周重点 · Orca 类比开场', '16:9', false, 'ok', '等距视角的深夜地铁站台，深蓝近黑的背景，荧光黄的导视线条沿着地面延伸，五个空的灶台整齐排开。', { w: 2048, h: 1152, sec: 91, usd: 0.03 }),
        it('2', 'img02_道具_灶台.png', '本周重点 · 五个灶台', '1:1', true, 'ok', '一个独立的小灶台，等距视角，扁平插画，荧光黄描边，青色火焰。', { w: 2048, h: 2048, alpha: true, sec: 77, usd: 0.03 }),
        it('3', 'img03_第五名_图谱.png', '第五名 Graphify', '21:9', false, 'run', '一张发光的关系图谱，节点是小圆点，连线是细的荧光黄线条，深蓝近黑背景，像地铁线路图。'),
        it('4', 'img04_第四名_调色板.png', '第四名 Impeccable', '1:1', true, 'queue', '一块扁平的调色板，几个荧光色的色块，等距视角，干净的描边。'),
        it('5', 'img05_第三名_剪刀.png', '第三名 Ponytail', '4:5', true, 'err', '一把把长代码剪短的剪刀，扁平插画，荧光黄和青色。', { err: '内容审核没过：改一改提示词再重生成' }),
        it('6', 'img06_封面.png', '封面主图', '16:9', false, 'idle', '深夜城市地铁线路图的抽象俯视，五条发光的线路在中心交汇，留出左侧大片空白。')] },
    job: { id: 9, st: 'run', kind: 'batch', n: 4, done: 2, fail: 1, msg: '', est: 0.12, model: 'gpt-image-2.5-sunburst-vip', mname: 'GPT Image 2.5 Sunburst VIP', quality: 'high', tier: '2k', conc: 1, fatal: '',
      usd: 0.06, elapsed: 190, results: [{ label: 'img01_重点_地铁站.png', ok: true, sec: 91 }, { label: 'img02_道具_灶台.png', ok: true, sec: 77 }, { label: 'img05_第三名_剪刀.png', ok: false, err: '内容审核没过' }],
      cur: { label: 'img03_第五名_图谱.png', prompt: '一张发光的关系图谱，节点是小圆点，连线是细的荧光黄线条，深蓝近黑背景，像地铁线路图。', ratio: '21:9', transparent: false, use: '第五名 Graphify', t0: now - 22, sec: 80, refs: 0, size: '2048×864', run_s: 22 } }
  };
})();

/* ---------- 读状态、进出这页 ---------- */
function imgLoad() {
  if (!useLive()) { IMG.st = IMG_DEMO; return Promise.resolve(IMG_DEMO); }
  return api('GET', '/api/img', null, 8000).then(function (j) { IMG.st = j; return j; });
}
function imgEnter() {
  imgLoad().then(function () { if (!$('#fg')) renderImg(); else imgSync(); }).catch(function () { if (!IMG.st) { IMG.st = IMG_DEMO; renderImg(); } });
  clearInterval(IMG.timer);
  IMG.timer = setInterval(function () {
    IMG.n++;
    var run = IMG.st && IMG.st.job && IMG.st.job.st === 'run';
    if (!useLive() || IMG.busy || (!run && IMG.n % 5)) return;
    IMG.busy = true;
    imgLoad().then(imgSync).catch(function () {}).then(function () { IMG.busy = false; });
  }, 1000);
  fgRun();
}
function imgLeave() { clearInterval(IMG.timer); IMG.timer = null; fgHalt(); imgBoxClose(); }

/* ---------- 小工具 ---------- */
function imgM() { return IMG.st.model; }
function imgRun() { var j = IMG.st && IMG.st.job; return !!(j && j.st === 'run'); }
function imgSize(r) {
  var s = IMG.st, m = s.model, t = s.cfg.tier || '2k';
  if (m.size === 'preset') return (s.sizes[t] || s.sizes['2k'])[r] || '';
  if (m.size === 'seedream') return s.sizes['2k'][r] || '';
  if (m.size === 'flux') return s.sizes['1k'][r] || '';
  if (m.size === 'gemini') return r + ' · ' + t.toUpperCase();
  return '比例写进提示词';
}
function imgUsd(r) {
  var s = IMG.st, m = s.model;
  if (m.price != null) return m.price;
  if (m.route === '官转' && m.proto === 'openai') { var p = (imgSize(r) || '1024×1024').split('×'); return (s.tokens[s.cfg.quality] || 439) * (+p[0] * +p[1] / 1048576) * s.usd_out; }
  return null;
}
function imgMoney(u) { return u == null ? '价格看 API易' : '$' + u.toFixed(u > 0 && (u < 0.01 || Math.abs(u * 100 - Math.round(u * 100)) > 1e-6) && u < 1 ? 3 : 2); }
function imgSum(rs) { var t = 0; for (var i = 0; i < rs.length; i++) { var u = imgUsd(rs[i]); if (u == null) return null; t += u; } return t; }
function imgDur(s) { s = Math.max(0, Math.round(s || 0)); return s >= 60 ? Math.floor(s / 60) + ':' + pad(s % 60) : s + 's'; }
function imgAgo(ts) { var d = Date.now() / 1000 - ts; return d < 60 ? '刚刚' : d < 3600 ? Math.floor(d / 60) + ' 分钟前' : d < 86400 ? Math.floor(d / 3600) + ' 小时前' : new Date(ts * 1000).toLocaleDateString(); }
function imgTags(m, rec) {
  var h = [];
  if (rec) h.push('<em class="rcm">推荐</em>');
  if (m.route) h.push('<em class="c">' + esc(m.route) + '</em>');
  if (m.price != null) h.push('<em class="ok">按次 · $' + m.price + '/张</em>');
  else h.push(m.known ? '<em class="amb">按量 · 按 token 计费</em>' : '<em>价格看 API易</em>');
  if (m.sec) h.push('<em>⏱ ' + m.sec + 's</em>');
  if (m.warn) h.push('<em class="bad">' + esc(m.warn) + '</em>');
  if (m.known === false) h.push('<em class="mag">没收录</em>');
  if (m.listed === false) h.push('<em>你的 Key 列表里没有</em>');
  return '<span class="ftg">' + h.join('') + '</span>';
}
function imgRatioIcon(r) { var p = r.split(':'), k = 0.95 / Math.max(+p[0], +p[1]); return '<i style="width:' + (+p[0] * k).toFixed(2) + 'rem;height:' + (+p[1] * k).toFixed(2) + 'rem"></i>'; }
function imgCur() { var b = IMG.st.board; return b && IMG.sel ? b.items.filter(function (x) { return x.id === IMG.sel; })[0] : null; }
function imgThumb(kind, x) {
  if (IMG.st.demo) return fgArt(kind + (x.id || x.hid), x.ratio, x.transparent);
  return kind === 'i' ? '/api/img/file/' + encodeURIComponent(x.id) + '?v=' + (x.ver || 0) : '/api/img/hfile/' + x.id;
}
function imgLog(html, cls) {      /* 底下的日志：只记这一页上发生的事，最多 5 行；新的一行滑进来，旧的不重画 */
  var row = function (l) { return '<div><span>[' + l.t + ']</span> <b class="' + l.c + '">' + l.h + '</b></div>'; }, el = $('#fgLog');
  if (html == null) { if (el) el.innerHTML = IMG.log.map(row).join(''); return; }
  var d = new Date(), l = { t: pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()), h: html, c: cls || '' };
  IMG.log.push(l); while (IMG.log.length > 5) IMG.log.shift();
  if (!el) return;
  el.insertAdjacentHTML('beforeend', row(l));
  while (el.children.length > 5) el.firstChild.remove();
}

/* ---------- 整页 ---------- */
function renderImg() {
  var v = $('#view-img'), s = IMG.st;
  if (!s) { v.innerHTML = '<div class="empty">正在读取…</div>'; return; }
  if (!IMG.tab) { var t0 = null; try { t0 = localStorage.getItem('igTab'); } catch (e) { /* 没有就算了 */ } IMG.tab = t0 || (s.board ? 'batch' : 'single'); }
  if (s.demo && IMG.tab === 'single' && !IMG.prompt) IMG.prompt = '一只发光的水母漂在深蓝的海里，触须像光纤，电影感的冷光。';
  var tab = IMG.tab, host = (s.cfg.base || '').replace(/^https?:\/\//, '').split('/')[0];
  var main;
  if (tab === 'hist') main = '<section class="fp fg-col"><div class="fh"><i></i>HISTORY<em>· 出过的每一张</em><span id="fgHn"></span></div>' +
      '<div class="fg-hq"><input class="fi" id="fgHq" placeholder="搜提示词、文件名、清单名" value="' + esc(IMG.hq) + '"><button class="fb sm" data-act="hreload">刷新</button><span class="fg-cap">单张、批量出的都在这；点一张看详情</span></div>' +
      '<div class="fg-hg fg-scroll" id="fgHg"></div></section><section class="fp fg-col fg-hd" id="fgHd"></section>';
  else if (tab === 'tpl') main = '<section class="fp fg-col"><div class="fh"><i></i>PRESETS<em>· 素材模板：提示词 + 参考图 + 比例，一点就填好</em><span><button class="fb sm" data-act="tab" data-tab="single">去单张存一个</button></span></div>' +
      '<div class="fg-tg fg-scroll" id="fgTg"></div></section>';
  else {
    var left = tab === 'single'
      ? '<section class="fp fg-col" id="fgLeft"><div class="fh"><i></i>COMPOSE<em>· 文生图 / 参考图生图</em><span id="fgCmpS"></span></div><div class="fg-cmp">' +
        '<div class="fg-lb">REFS<em>参考图</em><span id="fgRn"></span></div><div class="fg-refs" id="fgRefs"></div>' +
        '<div class="fg-lb">PROMPT<em>提示词</em><span>Ctrl+Enter 生成</span></div><textarea class="fi fg-ta fg-scroll" id="fgPrompt" spellcheck="false" placeholder="想要一张什么样的图？写清楚主体、画风、构图、光线。只有这段字和参考图会发给 API易。">' + esc(IMG.prompt) + '</textarea>' +
        '<div class="fg-lb">RATIO<em>比例</em><span id="fgSz"></span></div><div class="fg-chips" id="fgChips"></div>' +
        '<div class="fg-row"><span class="fg-lb">COUNT<em>张数</em></span><div class="fseg" id="fgCnt"></div><span class="sp"></span><button class="fg-sw" id="fgTr" aria-pressed="' + IMG.trans + '" title="道具、图标开；背景图不开">透明背景</button></div>' +
        '<div class="fg-row"><select class="fi" id="fgTpl" aria-label="套用模板" style="flex:1;width:auto"></select><button class="fb sm" data-act="tplsave">存为模板</button></div></div></section>'
      : '<section class="fp fg-col" id="fgLeft"><div class="fh"><i></i>QUEUE<em id="fgQn"></em><span id="fgQc"></span></div><div class="fg-ql fg-scroll" id="fgQl"></div><div class="fg-ed" id="fgEd" hidden></div><div class="fg-of" id="fgQb" hidden></div></section>';
    main = left + '<section class="fg-core" id="fgCore"><div class="fg-lab" id="fgLab"></div><div class="fg-side" id="fgSide"></div>' +
      '<div class="fg-pct"><b id="fgPct">0</b><small>PERCENT · 进度</small><i id="fgEl"></i></div>' +
      '<div class="fg-info"><div class="fn" id="fgFn"></div><div class="meta" id="fgMeta"></div><div class="pr" id="fgPr"></div></div></section>' +
      '<section class="fp fg-col"><div class="fh"><i></i>OUTPUT<em>· 生图输出</em><span id="fgOn"></span></div><div class="fg-og fg-scroll" id="fgOg"></div>' +
      '<div class="fg-of"><button class="fb" data-act="open">打开文件夹</button>' + (tab === 'batch' ? '<button class="fb" data-act="zip" id="fgZip">打包 ZIP</button>' : '<button class="fb" data-act="tab" data-tab="hist">看全部历史</button>') + '</div></section>';
  }
  v.innerHTML = '<div class="fg" id="fg"><canvas class="fg-fx" id="fgFx"></canvas><div class="fg-flash" id="fgFlash"></div>' +
    '<div class="fg-top"><div class="fp fg-brand"><small id="fgBs"></small><b data-t="IMAGE FORGE">IMAGE FORGE</b></div>' +
      '<button class="fp fg-mdl" id="fgMdl" data-act="pick" title="换模型（按厂商分好的列表）"></button>' +
      '<div class="fp fg-kpis">' + [['kQ', 'QUEUE', '队列', ''], ['kD', 'DONE', '已出', 'ok'], ['kF', 'FAIL', '没出来', 'bad'], ['kA', 'AVG', '平均', ''], ['kS', 'SPENT', '已花', 'amb'], ['kE', 'ETA', '还要', '']].map(function (k) {
        return '<div class="fk"><small>' + k[1] + '<em>' + k[2] + '</em></small><b class="num ' + k[3] + '" id="' + k[0] + '">--</b>' + (k[0] === 'kA' ? '<svg id="fgSpark" viewBox="0 0 64 26" aria-hidden="true"></svg>' : '') + (k[0] === 'kS' ? '<i id="kM"></i>' : '') + '</div>'; }).join('') + '</div>' +
      '<button class="fg-go start" id="fgGo"><i></i><span id="fgGoT"></span></button></div>' +
    '<div class="fg-bar"><div class="fg-tabs" role="tablist">' + IMG_TABS.map(function (t) { return '<button class="fg-tab" role="tab" data-act="tab" data-tab="' + t[0] + '" aria-selected="' + (t[0] === tab) + '">' + t[1] + '<em>' + t[2] + '</em><b id="fgT_' + t[0] + '"></b></button>'; }).join('') + '</div>' +
      '<div class="fg-par" id="fgPar"></div></div>' +
    '<div class="fg-main ' + (tab === 'hist' ? 'hist' : tab === 'tpl' ? 'tpl' : '') + '" id="fgMain">' + main + '</div>' +
    '<div class="fg-bot"><section class="fp fg-log" id="fgLog"></section><section class="fp fg-scope"><div class="fh"><i></i>API LINK<em>· ' + esc(host || 'api.apiyi.com') + '</em><span id="fgLat">IDLE</span></div><canvas id="fgSc"></canvas></section></div>' +
    '<input type="file" id="fgMd" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden><input type="file" id="fgImgs" accept="image/png,image/jpeg,image/webp" multiple hidden>' +
    '<div class="fg-drag" id="fgDrag">松开：清单（.md）认成批量，图片当参考图</div></div>';
  IMG.sig = {};
  if (!IMG.log.length) imgLog('◆ ' + (s.demo ? '演示模式（连上后端才能出图）' : '渲染舱就绪 · ' + esc(s.model.name)), 'c'); else imgLog(null);
  if (tab === 'single') imgCmp(true);
  if (tab === 'hist') imgHist();
  if (tab === 'tpl') imgTpl();
  fgMount();
  imgSync();
  imgBoot();
}
function imgSync() {
  if (S.view !== 'img' || !$('#fg') || !IMG.st) return;
  var s = IMG.st, m = s.model, j = s.job, run = imgRun();
  $('#fgBs').textContent = 'APIYI // ' + m.id.toUpperCase() + ' · ' + imgMoney(m.price) + (m.tiers.length ? ' · ' + (s.cfg.tier || '2k').toUpperCase() : '');
  var mh = '<small>MODEL <b>' + esc(m.vendor) + '</b> · 点这里换</small><strong>' + esc(m.name) + '</strong>' + imgTags(m, m.id === 'gpt-image-2.5-sunburst-vip');
  if (IMG.sig.mdl !== mh) { $('#fgMdl').innerHTML = mh; IMG.sig.mdl = mh; }
  fgFeed();
  imgPar(); imgKpis(); imgGo(); imgTabsDot();
  if (IMG.tab === 'batch') imgQueue();
  if (IMG.tab === 'single') imgCmp();
  if (IMG.tab === 'single' || IMG.tab === 'batch') imgOut();
  if (IMG.tab === 'tpl') imgTpl();
  fgPorts();
  if (!FG.anim) fgDraw(0);
  if (IMG.box && IMG.box.kind === 'item') imgViewItem(IMG.box.id, true);
}
function imgTabsDot() {
  var j = IMG.st.job, k = j && j.st === 'run' ? j.kind : '';
  ['single', 'batch'].forEach(function (t) { var el = $('#fgT_' + t); if (el) el.innerHTML = k === t ? '<i class="dot"></i>' : t === 'batch' && IMG.st.board ? IMG.st.board.items.length : ''; });
}
function imgPar() {
  var s = IMG.st, m = s.model, run = imgRun(), h = '';
  if (IMG.tab === 'single' || IMG.tab === 'batch') {
    if (m.tiers.length > 1) h += '<span class="pl">TIER<span class="fseg">' + m.tiers.map(function (t) { return '<button data-tier="' + t + '" aria-pressed="' + (s.cfg.tier === t) + '"' + (run ? ' disabled' : '') + '>' + t.toUpperCase() + '</button>'; }).join('') + '</span></span>';
    else if (m.tiers.length) h += '<span class="pl">TIER<span class="fg-cap">' + m.tiers[0].toUpperCase() + '（这个模型固定）</span></span>';
    if (m.q) h += '<span class="pl" title="' + (m.price == null ? '按量计费：画质越高越贵（最高档一张能到几毛钱美元）' : '按次计费：画质高低一个价') + '">QUALITY<span class="fseg">' + m.q.map(function (q) { return '<button data-q="' + q + '" aria-pressed="' + (s.cfg.quality === q) + '"' + (run ? ' disabled' : '') + '>' + esc(s.quality[q] || q) + '</button>'; }).join('') + '</span></span>';
    else h += '<span class="pl">QUALITY<span class="fg-cap">这个模型不认画质</span></span>';
    if (IMG.tab === 'batch') h += '<button class="fg-sw" data-cfg="notext" aria-pressed="' + !!s.cfg.notext + '" title="正本规矩 6：图里不放文字（AI 画的字容易乱码）">不要文字</button>' +
      '<button class="fg-sw" data-cfg="withdir" aria-pressed="' + !!s.cfg.withdir + '" title="正本要求每条提示词里已经写了统一画风，所以默认不拼">拼视觉方向</button>';
  } else h = '<span class="pl">MONTH<span class="fg-cap num">本月在这里出了 ' + (s.month.n || 0) + ' 张 · 约 $' + (+s.month.usd || 0).toFixed(2) + '（以 API易 账单为准）</span></span>';
  if (IMG.sig.par !== h) { $('#fgPar').innerHTML = h; IMG.sig.par = h; }
}
function imgKpis() {
  var s = IMG.st, j = s.job, b = s.board, m = s.model;
  var tabJob = j && (j.kind === IMG.tab || j.st === 'run') ? j : null;
  var rs = tabJob ? tabJob.results.filter(function (r) { return r.ok && r.sec != null; }).map(function (r) { return r.sec; }) : [];
  var avg = rs.length ? rs.reduce(function (a, x) { return a + x; }, 0) / rs.length : 0;
  var q, d, f, usd, eta;
  if (tabJob) {
    q = tabJob.n; d = tabJob.done; f = tabJob.fail; usd = tabJob.usd || 0;
    var left = tabJob.n - tabJob.done - tabJob.fail, per = avg || m.sec || 60, cur = tabJob.cur ? tabJob.cur.run_s || 0 : 0;
    eta = tabJob.st === 'run' ? Math.max(0, left * per - cur) : 0;
  } else if (IMG.tab === 'batch' && b) {
    q = b.items.length; d = b.items.filter(function (x) { return x.st === 'ok'; }).length; f = b.items.filter(function (x) { return x.st === 'err'; }).length; usd = 0; eta = null;
  } else { q = 0; d = 0; f = 0; usd = 0; eta = null; }
  fgNum('kQ', q, function (v) { return pad(Math.round(v)); });
  fgNum('kD', d, function (v) { return pad(Math.round(v)); });
  fgNum('kF', f, function (v) { return pad(Math.round(v)); });
  fgNum('kS', usd, function (v) { return '$' + v.toFixed(2); });
  if (avg) fgNum('kA', avg, function (v) { return v.toFixed(0) + 's'; }); else { delete FG.shown.kA; $('#kA').textContent = '--'; }
  $('#kE').textContent = eta == null ? '--:--' : pad(Math.floor(eta / 60)) + ':' + pad(Math.round(eta) % 60);
  $('#kM').textContent = '本月 $' + (+s.month.usd || 0).toFixed(2);
  var t = rs.slice(-12), mx = Math.max(m.sec || 40, 1, Math.max.apply(null, t.concat([0]))), sg = t.join(',');
  if (IMG.sig.spark !== sg) { IMG.sig.spark = sg; $('#fgSpark').innerHTML = t.map(function (v, k) { return '<rect x="' + (k * 5.3) + '" y="' + (26 - v / mx * 24) + '" width="3.4" height="' + (v / mx * 24) + '" fill="' + (v > (m.sec || 60) * 1.2 ? 'var(--c-neu)' : 'var(--accent)') + '" opacity=".85"/>'; }).join(''); }
}
function imgGo() {
  var s = IMG.st, b = s.board, run = imgRun(), cls = 'start', t = '', dis = false;
  if (run) { cls = ''; t = '停下<small>没开始的不出了，正在出的出完</small>'; }
  else if (IMG.tab === 'single') { var n = IMG.cnt, u = imgUsd(IMG.ratio); t = '生成' + '<small>' + n + ' 张 · ' + (u == null ? '价格看 API易' : '约 ' + imgMoney(u * n)) + (IMG.refs.length ? ' · ' + IMG.refs.length + ' 张参考图' : '') + '</small>'; dis = !s.cfg.key && !s.demo; }
  else if (IMG.tab === 'batch') {
    if (!b) t = '选清单<small>视频窗口出的生图清单 .md</small>';
    else {
      var todo = b.items.filter(function (x) { return x.st !== 'ok'; });
      if (!todo.length) { cls = 'done'; t = '全部出好了<small>点这里打开文件夹</small>'; }
      else { var sum = imgSum(todo.map(function (x) { return x.ratio; })); t = (todo.length === b.items.length ? '批量生成' : '补齐没出的') + '<small>' + todo.length + ' 张 · ' + (sum == null ? '价格看 API易' : '约 ' + imgMoney(sum)) + ' · 一张一张来</small>'; dis = !s.cfg.key && !s.demo; }
    }
  } else t = '去出图<small>回到单张</small>';
  var go = $('#fgGo'), h = cls + '|' + t + '|' + dis;
  if (IMG.sig.go === h) return; IMG.sig.go = h;
  go.className = 'fg-go ' + cls; go.disabled = dis; $('#fgGoT').innerHTML = t;
  go.title = dis ? '还没填 API易 Key：到 设置 › 云端 填' : '';
}

/* ---------- 单张：参考图、提示词、比例、张数 ---------- */
function imgCmp(first) {
  if (!$('#fgChips')) return;
  var s = IMG.st, m = s.model, max = Math.max(1, m.refs || 1), run = imgRun();
  if (IMG.refs.length > max) { IMG.refs = IMG.refs.slice(0, max); toast('这个模型最多 ' + max + ' 张参考图，多的去掉了'); }
  var rh = IMG.refs.map(function (r, i) { return '<span class="fg-ref"><img src="' + r.url + '" alt=""><button data-act="unref" data-i="' + i + '" aria-label="去掉这张参考图">' + ICONS.cross + '</button></span>'; }).join('') +
    (IMG.refs.length < max ? '<button class="fg-add" data-act="addref">' + (IMG.refs.length ? '+ 再加' : '拖图片进来 / 点这里选 / Ctrl+V 粘贴（可以不放）') + '</button>' : '');
  if (first || IMG.sig.refs !== rh) { $('#fgRefs').innerHTML = rh; IMG.sig.refs = rh; }
  $('#fgRn').textContent = IMG.refs.length + ' / ' + max;
  var ch = s.ratios.map(function (r) { return '<button class="fg-chip" data-ratio="' + r + '" aria-pressed="' + (r === IMG.ratio) + '" title="' + IMG_RNAME[r] + ' · ' + esc(imgSize(r)) + '">' + imgRatioIcon(r) + r + '</button>'; }).join('');
  if (IMG.sig.chips !== ch) { $('#fgChips').innerHTML = ch; IMG.sig.chips = ch; }
  $('#fgSz').textContent = imgSize(IMG.ratio);
  var cn = [1, 2, 3, 4].map(function (n) { return '<button data-cnt="' + n + '" aria-pressed="' + (n === IMG.cnt) + '">' + n + '</button>'; }).join('');
  if (IMG.sig.cnt !== cn) { $('#fgCnt').innerHTML = cn; IMG.sig.cnt = cn; }
  var tr = $('#fgTr'); tr.setAttribute('aria-pressed', IMG.trans); tr.textContent = '透明背景' + (IMG.trans && m.trans !== 'api' ? '（这个模型只能在提示词里要）' : '');
  var th = '<option value="">套用模板…（' + s.templates.length + ' 个）</option>' + s.templates.map(function (t) { return '<option value="' + esc(t.id) + '">' + esc(t.name) + '</option>'; }).join('');
  if (IMG.sig.tpl !== th) { $('#fgTpl').innerHTML = th; IMG.sig.tpl = th; }
  $('#fgCmpS').textContent = run ? '出图中' : (m.refs ? '参考图最多 ' + max + ' 张' : '');
}
function imgAddFiles(files) {
  var s = IMG.st, max = Math.max(1, s.model.refs || 1), list = [].slice.call(files || []).filter(function (f) { return /^image\/(png|jpeg|webp)$/.test(f.type); });
  if (!list.length) { toast('参考图只认 PNG / JPEG / WEBP'); return; }
  list.forEach(function (f) {
    if (f.size > 10 * 1024 * 1024) { toast(f.name + ' 太大了：一张最多 10MB'); return; }
    if (IMG.refs.length >= max) { toast(s.model.name + ' 最多 ' + max + ' 张参考图'); return; }
    var r = new FileReader(), slot = { url: '', name: f.name };
    IMG.refs.push(slot);
    r.onload = function () { slot.url = String(r.result); imgCmp(); imgGo(); fgPorts(); };
    r.readAsDataURL(f);
  });
  if (IMG.tab !== 'single') imgTab('single');
}
function imgUrlToRef(url, name) {
  return fetch(url).then(function (r) { if (!r.ok) throw new Error('图找不到了'); return r.blob(); }).then(function (b) {
    return new Promise(function (ok) { var fr = new FileReader(); fr.onload = function () { ok({ url: String(fr.result), name: name || '' }); }; fr.readAsDataURL(b); });
  });
}
function imgGen() {
  var s = IMG.st;
  if (!useLive()) { toast('演示模式：连上后端才能出图'); return; }
  if (!s.cfg.key) { toast('还没填 API易 Key：到 设置 › 云端 填', 5000); return; }
  var p = ($('#fgPrompt') ? $('#fgPrompt').value : IMG.prompt).trim();
  if (!p) { toast('写一句提示词'); var ta = $('#fgPrompt'); if (ta) ta.focus(); return; }
  if (IMG.refs.some(function (r) { return !r.url; })) { toast('参考图还在读，等一下'); return; }
  api('POST', '/api/img/single', { prompt: p, ratio: IMG.ratio, n: IMG.cnt, transparent: IMG.trans, refs: IMG.refs.map(function (r) { return r.url; }) }, 60000).then(function (j) {
    IMG.st.job = j.job; IMG.mine = j.job.id;
    imgLog('▶ 开始：' + IMG.cnt + ' 张 · ' + esc(j.job.mname) + ' · ' + IMG.ratio + (IMG.refs.length ? ' · ' + IMG.refs.length + ' 张参考图' : ''), 'c');
    return imgLoad();
  }).then(imgSync).catch(function (e) { toast(e.message, 6000); imgLog('✕ ' + esc(e.message), 'bad'); });
}

/* ---------- 批量：清单 ---------- */
function imgQueue() {
  var s = IMG.st, b = s.board, ql = $('#fgQl'); if (!ql) return;
  var run = imgRun();
  $('#fgQn').textContent = b ? '· ' + (b.md_name || b.title) : '· 生图清单';
  var qb = b ? '<button class="fb sm" data-act="pickmd"' + (run ? ' disabled' : '') + '>换一份</button><button class="fb sm" data-act="paste"' + (run ? ' disabled' : '') + '>粘贴</button>' +
    '<button class="fb sm" data-act="rerunall"' + (run || !s.cfg.key ? ' disabled' : '') + ' title="每一张都重出一遍（旧的挪进「旧版」）">全部重出</button><button class="fb sm" data-act="clear" title="清掉这份清单（文件夹里的图不动）"' + (run ? ' disabled' : '') + '>清掉</button>' : '';
  if (IMG.sig.qb !== qb) { $('#fgQb').innerHTML = qb; $('#fgQb').hidden = !qb; IMG.sig.qb = qb; }
  $('#fgQc').textContent = b ? b.items.length + ' 张' + (b.warn.length ? ' · ' + b.warn.length + ' 处没认全' : '') : '';
  if (!b) {
    if (IMG.sig.ql !== 'none') {
      IMG.sig.ql = 'none'; IMG.sel = null; $('#fgEd').hidden = true;
      ql.innerHTML = '<div class="fg-drop"><svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4M7.5 8.5L12 4l4.5 4.5"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/></svg><b>把生图清单拖进来</b>' +
        '<span>视频窗口按《自媒体正本》出的 .md：视觉方向 + 每条的文件名、用在哪、比例、透明背景、提示词。认出来就一行一张排好，点「批量生成」一张一张出。</span>' +
        '<span class="bt"><button class="fb pri" data-act="pickmd">选文件</button><button class="fb" data-act="paste">粘贴</button></span></div>';
    }
    return;
  }
  var key = b.id + '|' + b.items.length;
  if (IMG.sig.ql !== key) {
    IMG.sig.ql = key;
    if (!imgCur()) IMG.sel = null;
    ql.innerHTML = b.items.map(function (it, i) {
      return '<button class="fg-r" data-act="sel" data-id="' + esc(it.id) + '"><span class="n">' + pad(i + 1) + '</span><span class="f" title="' + esc(it.file + (it.use ? ' · ' + it.use : '')) + '">' + esc(it.file) + '</span>' +
        '<span class="ftg"><em>' + it.ratio + '</em>' + (it.transparent ? '<em class="c">透明</em>' : '') + '</span><span class="st"></span><i class="port"></i></button>';
    }).join('');
    ql.onscroll = fgPorts;
  }
  b.items.forEach(function (it, i) {
    var r = ql.children[i]; if (!r) return;
    var c = 'fg-r' + (it.st === 'idle' ? '' : ' ' + it.st), g = { ok: '✓', err: '✕', run: '◉', queue: '…', idle: '·' }[it.st] || '·';
    if (r.className !== c) r.className = c;
    var st = r.querySelector('.st'); if (st.textContent !== g) st.textContent = g;
    r.setAttribute('aria-current', IMG.sel === it.id ? 'true' : 'false');
    var tg = '<em>' + it.ratio + '</em>' + (it.transparent ? '<em class="c">透明</em>' : '') + (it.edited ? '<em class="amb">改过</em>' : ''), te = r.querySelector('.ftg');
    if (te.innerHTML !== tg) te.innerHTML = tg;
  });
  imgEditor();
}
function imgEditor() {
  var ed = $('#fgEd'), it = imgCur(); if (!ed) return;
  if (!it) { ed.hidden = true; IMG.sig.ed = ''; return; }
  ed.hidden = false;
  var s = IMG.st, busy = it.st === 'run' || it.st === 'queue', run = imgRun();
  var sig = [it.id, it.st, it.ratio, it.transparent, it.err, it.warn, run, s.cfg.key].join('|');
  var ta = $('#fgEdPr'), typing = ta && document.activeElement === ta;
  if (IMG.sig.ed === sig) return;
  if (typing && IMG.sig.ed && IMG.sig.ed.split('|')[0] === it.id) {           /* 正在改提示词：只更新别的 */
    IMG.sig.ed = sig; ta.disabled = busy; return;
  }
  IMG.sig.ed = sig;
  ed.innerHTML = '<div class="hd"><b title="' + esc(it.file) + '">' + esc(it.file) + '</b><span class="fg-cap">' + esc(it.use || '') + '</span><button class="fb x" data-act="unsel" aria-label="收起">' + ICONS.cross + '</button></div>' +
    (it.err ? '<div class="er">' + esc(it.err) + '</div>' : '') + (it.warn ? '<div class="wn">' + esc(it.warn) + '</div>' : '') +
    '<textarea class="fi fg-ta" id="fgEdPr" rows="4" spellcheck="false"' + (busy ? ' disabled' : '') + ' aria-label="提示词">' + esc(it.prompt || '') + '</textarea>' +
    '<div class="ft"><select class="fi" id="fgEdR" style="width:auto"' + (busy ? ' disabled' : '') + ' aria-label="比例">' + s.ratios.map(function (r) { return '<option value="' + r + '"' + (r === it.ratio ? ' selected' : '') + '>' + r + ' ' + IMG_RNAME[r] + '</option>'; }).join('') + '</select>' +
    '<button class="fg-sw" id="fgEdT" aria-pressed="' + !!it.transparent + '"' + (busy ? ' disabled' : '') + '>透明背景</button>' +
    (it.st === 'ok' ? '<button class="fb sm" data-act="viewi" data-id="' + esc(it.id) + '">看大图</button>' : '') +
    '<button class="fb sm pri" data-act="one" data-id="' + esc(it.id) + '"' + (run || !s.cfg.key ? ' disabled' : '') + '>' + (it.st === 'ok' || it.st === 'err' ? '重生成' : '只出这张') + '</button></div>';
}
var imgEditT = {};
function imgEdit(id, patch, now) {
  var b = IMG.st.board, it = b && b.items.filter(function (x) { return x.id === id; })[0]; if (!it) return;
  Object.keys(patch).forEach(function (k) { it[k] = patch[k]; });
  if (!useLive()) { imgQueue(); return; }
  var send = function () {   /* 回来的只拿「改过」：别的以本地为准（回来之前可能又改了别的） */
    api('PATCH', '/api/img/item/' + encodeURIComponent(id), patch).then(function (j) { it.edited = j.item.edited; imgQueue(); }).catch(function (e) { toast(e.message); });
  };
  if (now) { imgQueue(); imgGo(); send(); return; }
  clearTimeout(imgEditT[id]);                 /* 提示词：停手 0.6 秒再存 */
  imgEditT[id] = setTimeout(send, 600);
}
function imgBatch(body) {
  if (!useLive()) { toast('演示模式：连上后端才能出图'); return; }
  api('POST', '/api/img/run', body, 15000).then(function (j) {
    IMG.st.job = j.job; IMG.mine = j.job.id;
    imgLog('▶ 开始批量：' + j.job.n + ' 张 · ' + esc(j.job.mname) + ' · ' + (j.job.tier || '').toUpperCase() + (j.job.est != null ? ' · 预估 $' + j.job.est.toFixed(2) : '') + ' · 一张一张来', 'c');
    return imgLoad();
  }).then(imgSync).catch(function (e) { toast(e.message, 6000); imgLog('✕ ' + esc(e.message), 'bad'); });
}
function imgLoadMd(md, name) {
  if (!useLive()) { toast('演示模式：连上后端才能认清单'); return; }
  api('POST', '/api/img/load', { md: md, name: name || '' }, 20000).then(function (j) {
    IMG.st = j; imgBoxClose(); IMG.sel = null;
    var b = j.board, ok = b.items.filter(function (it) { return it.st === 'ok'; }).length;
    imgLog('◆ 认出「' + esc(b.title) + '」' + b.items.length + ' 张' + (ok ? ' · 文件夹里已经有 ' + ok + ' 张' : '') + (b.warn.length ? ' · ' + b.warn.length + ' 处没认全' : ''), b.warn.length ? 'amb' : 'c');
    if (b.warn.length) toast(b.warn.slice(0, 3).join('\n'), 8000);
    imgTab('batch', true);
  }).catch(function (e) { toast(e.message, 7000); });
}
function imgReadMd(file) {
  if (!file) return;
  if (file.size > 2e6) { toast('这个文件太大了，是不是选错了（清单一般几十 KB）'); return; }
  var r = new FileReader();
  r.onload = function () { imgLoadMd(String(r.result || ''), file.name); };
  r.readAsText(file, 'utf-8');
}

/* ---------- 右边：出好的图 ---------- */
function imgOutList() {
  var s = IMG.st, j = s.job, out = [];
  if (IMG.tab === 'batch') {
    (s.board ? s.board.items : []).forEach(function (it) {
      if (it.st === 'ok') out.push({ k: 'i' + it.id, sig: it.ver + '|' + (it.warn || ''), src: imgThumb('i', it), t: it.transparent, name: it.file, sub: it.sec != null ? Math.round(it.sec) + 's' : '', warn: it.warn, act: 'viewi', id: it.id });
      else if (it.st === 'err') out.push({ k: 'i' + it.id, sig: 'e|' + it.err, err: it.err, name: it.file, act: 'sel', id: it.id });
    });
  } else {
    if (j && j.kind === 'single') j.results.forEach(function (r, i) { if (!r.ok) out.push({ k: 'e' + j.id + '_' + i, sig: 'e', err: r.err, name: r.label, act: '', id: '' }); });
    (s.recent || []).forEach(function (h) { out.push({ k: 'h' + h.id, sig: String(h.exists), src: h.exists ? imgThumb('h', h) : '', t: h.transparent, name: h.file, sub: h.sec != null ? Math.round(h.sec) + 's' : '', act: 'viewh', id: String(h.id), gone: !h.exists }); });
  }
  return out;
}
function imgOut() {
  var og = $('#fgOg'); if (!og) return;
  var list = imgOutList(), s = IMG.st;
  $('#fgOn').textContent = list.filter(function (x) { return !x.err; }).length + ' 张';
  var z = $('#fgZip'); if (z) z.disabled = !(s.board && s.board.items.some(function (x) { return x.st === 'ok'; }));
  var key = list.map(function (x) { return x.k + ':' + x.sig + (IMG.wait[x.k] ? ':w' : ''); }).join(',');
  if (IMG.sig.og === key) return; IMG.sig.og = key;
  if (!list.length) {
    og.innerHTML = '<div class="fg-empty">' + (IMG.tab === 'batch' ? '出好的图按清单里的文件名存在「生图输出」里一份清单一个文件夹（名字带日期），重生成的旧图挪进「旧版」，不删。' : '出好的图存在「生图输出\\单张\\日期」里，这里显示最近的 12 张；全部的在「历史」。') + '</div>';
    og.classList.remove('dense'); return;
  }
  var old = {}; [].forEach.call(og.querySelectorAll('[data-k]'), function (el) { old[el.dataset.k] = el; });
  var frag = document.createDocumentFragment();
  list.forEach(function (x) {
    var el = old[x.k];
    if (el && el.dataset.sig === x.sig) { if (!IMG.wait[x.k]) el.classList.remove('wait'); frag.appendChild(el); return; }
    el = document.createElement('button');
    el.className = 'fg-tile' + (x.err ? ' err' : '') + (x.t ? ' t' : '') + (x.warn ? ' wn' : '') + (IMG.wait[x.k] ? ' wait' : ' in');
    el.dataset.k = x.k; el.dataset.sig = x.sig; if (x.act) el.dataset.act = x.act; if (x.id) el.dataset.id = x.id;
    el.title = x.name + (x.warn ? '\n' + x.warn : '') + (x.err ? '\n' + x.err : '');
    el.innerHTML = '<i class="pt"></i>' + (x.err ? esc(x.err.split('：')[0]) + '<br>' + (IMG.tab === 'batch' ? '点一下改提示词' : '') :
      (x.src ? '<img src="' + x.src + '" alt="" loading="lazy" decoding="async">' : '<span class="fg-cap">文件不在了</span>') + '<small>' + esc(x.name) + (x.sub ? ' <i>✓ ' + x.sub + '</i>' : '') + '</small>');
    frag.appendChild(el);
  });
  og.innerHTML = ''; og.appendChild(frag);
  og.classList.toggle('dense', list.length > 8);
  og.onscroll = fgPorts;
}

/* ---------- 历史 ---------- */
function imgHist(reload) {
  var g = $('#fgHg'); if (!g) return;
  if (IMG.hist && !reload) { imgHistDraw(); return; }
  if (!useLive()) { IMG.hist = IMG_DEMO.recent; imgHistDraw(); return; }
  g.innerHTML = '<div class="fg-none">正在读…</div>';
  api('GET', '/api/img/hist?limit=120&q=' + encodeURIComponent(IMG.hq || ''), null, 10000).then(function (j) { IMG.hist = j.items; imgHistDraw(); })
    .catch(function (e) { g.innerHTML = '<div class="fg-none">' + esc(e.message) + '</div>'; });
}
function imgHistDraw() {
  var g = $('#fgHg'); if (!g) return;
  var hs = IMG.hist || [];
  $('#fgHn').textContent = hs.length + ' 张' + (IMG.hq ? ' · 搜「' + IMG.hq + '」' : '');
  if (!hs.length) { g.innerHTML = '<div class="fg-none"><b>' + (IMG.hq ? '没搜到' : '还没出过图') + '</b>' + (IMG.hq ? '换个词试试' : '在「单张」写一句提示词，或者在「批量」上传生图清单') + '</div>'; imgHistSel(); return; }
  if (!IMG.hsel || !hs.some(function (h) { return h.id === IMG.hsel; })) IMG.hsel = hs[0].id;
  g.innerHTML = hs.map(function (h) {
    return '<button class="fg-ht' + (h.transparent ? ' t' : '') + '" data-act="hsel" data-id="' + h.id + '" aria-current="' + (h.id === IMG.hsel) + '"><span class="im">' +
      (h.exists ? '<img src="' + imgThumb('h', h) + '" alt="" loading="lazy" decoding="async">' : '<span class="gone">文件不在了</span>') + '</span>' +
      '<span class="cp" title="' + esc(h.prompt) + '"><b>' + esc(h.ratio) + '</b>' + esc(h.kind === 'batch' ? h.file : h.prompt) + '</span></button>';
  }).join('');
  imgHistSel();
}
function imgHistSel() {
  var d = $('#fgHd'); if (!d) return;
  var h = (IMG.hist || []).filter(function (x) { return x.id === IMG.hsel; })[0];
  [].forEach.call(document.querySelectorAll('#fgHg .fg-ht'), function (el) { el.setAttribute('aria-current', String(+el.dataset.id === IMG.hsel)); });
  if (!h) { d.innerHTML = '<div class="fh"><i></i>DETAIL<em>· 详情</em></div><div class="fg-none">点左边一张看详情</div>'; return; }
  d.innerHTML = '<div class="pv' + (h.transparent ? ' t' : '') + '">' + (h.exists ? '<img src="' + imgThumb('h', h) + '" alt="">' : '<span class="fg-cap">文件被挪走或删了</span>') + '</div>' +
    '<div class="nm" title="' + esc(h.file) + '">' + esc(h.file) + '</div>' + imgKv(h) +
    '<div class="pr fg-scroll">' + esc(h.prompt) + '</div>' +
    '<div class="bt"><button class="fb pri" data-act="again" data-id="' + h.id + '">再来一张</button><button class="fb" data-act="asref" data-id="' + h.id + '"' + (h.exists ? '' : ' disabled') + '>当参考图</button>' +
    '<button class="fb" data-act="hopen" data-id="' + h.id + '"' + (h.exists ? '' : ' disabled') + '>打开文件夹</button><button class="fb" data-act="copy" data-id="' + h.id + '">复制提示词</button></div>';
}
function imgKv(h) {
  var kv = [['MODEL', h.model], ['SIZE', (h.w ? h.w + '×' + h.h : '') + ' · ' + h.ratio + ' · ' + String(h.tier || '').toUpperCase()], ['ALPHA', h.transparent ? (h.alpha ? '透明背景 ✓' : '要透明但没透明') : '不透明'],
    ['COST', '$' + (+h.usd || 0).toFixed(3) + (h.sec != null ? ' · ' + Math.round(h.sec) + ' 秒' : '')], ['FROM', (h.kind === 'batch' ? '批量 · ' + (h.title || '') : '单张') + (h.refs ? ' · ' + h.refs + ' 张参考图' : '')], ['WHEN', imgAgo(h.ts)]];
  return '<dl class="fg-kv">' + kv.map(function (x) { return '<dt>' + x[0] + '</dt><dd title="' + esc(x[1]) + '">' + esc(x[1]) + '</dd>'; }).join('') + '</dl>';
}
function imgAgain(h) {
  IMG.prompt = h.prompt; IMG.ratio = h.ratio; IMG.trans = !!h.transparent; IMG.cnt = 1;
  imgTab('single', true); toast('填好了：改一改，点「生成」');
}

/* ---------- 模板 ---------- */
function imgTpl() {
  var g = $('#fgTg'); if (!g) return;
  var ts = IMG.st.templates, sig = JSON.stringify(ts) + (IMG.delArm || '');
  if (IMG.sig.tg === sig) return; IMG.sig.tg = sig;
  if (!ts.length) { g.innerHTML = '<div class="fg-none"><b>还没有模板</b>在「单张」里写好提示词、放好参考图、选好比例，点「存为模板」；下次在这里一点就填好</div>'; return; }
  g.innerHTML = ts.map(function (t) {
    var rf = ''; for (var k = 0; k < (t.refs || 0); k++) rf += '<img src="' + (IMG.st.demo ? '' : '/api/img/tplref/' + encodeURIComponent(t.id) + '/' + k) + '" alt="" loading="lazy">';
    return '<article class="fg-tc"><div class="nm"><b title="' + esc(t.name) + '">' + esc(t.name) + '</b><button class="fb x" data-act="tpldel" data-id="' + esc(t.id) + '" title="删掉这个模板">' + (IMG.delArm === t.id ? '再点一次删除' : ICONS.cross) + '</button></div>' +
      '<p title="' + esc(t.prompt) + '">' + esc(t.prompt || '（只有参考图）') + '</p><div class="rf">' + (rf || '<span class="fg-cap">没有参考图</span>') + '</div>' +
      '<div class="ft"><span class="ftg"><em>' + t.ratio + '</em><em>' + t.n + ' 张</em>' + (t.transparent ? '<em class="c">透明</em>' : '') + '<em title="' + esc(t.model) + '">' + esc(t.model.replace(/^gpt-image-/, 'GPT ')) + '</em></span>' +
      '<button class="fb sm pri" data-act="tpluse" data-id="' + esc(t.id) + '">套用</button></div></article>';
  }).join('');
}
function imgTplUse(id) {
  var t = IMG.st.templates.filter(function (x) { return x.id === id; })[0]; if (!t) return;
  IMG.prompt = t.prompt; IMG.ratio = t.ratio; IMG.trans = !!t.transparent; IMG.cnt = t.n || 1; IMG.refs = [];
  var jobs = [];
  for (var k = 0; k < (t.refs || 0); k++) jobs.push(imgUrlToRef('/api/img/tplref/' + encodeURIComponent(t.id) + '/' + k, ''));
  var swap = useLive() && (t.model !== IMG.st.cfg.model || t.tier !== IMG.st.cfg.tier || t.quality !== IMG.st.cfg.quality)
    ? api('PUT', '/api/settings', { imgModel: t.model, imgRes: t.tier, imgQuality: t.quality }).then(imgLoad) : Promise.resolve();
  Promise.all([swap].concat(jobs.map(function (p) { return p.catch(function () { return null; }); }))).then(function (rs) {
    IMG.refs = rs.slice(1).filter(Boolean);
    imgTab('single', true);
    imgLog('◆ 套用模板「' + esc(t.name) + '」' + (t.model !== IMG_DEMO.cfg.model || swap ? ' · 模型 ' + esc(IMG.st.model.name) : ''), 'c');
  });
}
function imgTplSave() {
  var p = ($('#fgPrompt') ? $('#fgPrompt').value : IMG.prompt).trim();
  if (!p && !IMG.refs.length) { toast('先写提示词或者放参考图，再存成模板'); return; }
  IMG.box = { kind: 'tplsave' };
  imgBox('<h3>SAVE PRESET<em>存为模板</em></h3><input class="fi" id="fgTn" maxlength="40" placeholder="起个名字，比如：封面 · 深夜地铁风">' +
    '<div class="fg-cap">会存：提示词（' + p.length + ' 字）、' + IMG.refs.length + ' 张参考图、' + IMG.ratio + '、' + IMG.cnt + ' 张、' + (IMG.trans ? '透明背景、' : '') + '模型 ' + esc(IMG.st.model.name) + '、' +
    String(IMG.st.cfg.tier).toUpperCase() + '、画质' + esc(IMG.st.quality[IMG.st.cfg.quality] || '') + '。同名的会被替换。</div>' +
    '<div class="bt"><button class="fb" data-act="boxclose">取消</button><button class="fb pri" data-act="tplok">存</button></div>');
  setTimeout(function () { var t = $('#fgTn'); if (t) t.focus(); }, 30);
}

/* ---------- 弹出层 ---------- */
function imgBoxClose() { var x = $('#fgBox'); if (x) x.remove(); IMG.box = null; }
function imgBox(html, cls) {
  var x = $('#fgBox');
  if (!x) { x = document.createElement('div'); x.id = 'fgBox'; x.className = 'fg-box'; x.setAttribute('role', 'dialog'); x.setAttribute('aria-modal', 'true'); document.body.appendChild(x); }
  x.innerHTML = '<div class="fg-bbg" data-act="boxclose"></div><div class="fp fg-bp ' + (cls || '') + '">' + html + '</div>';
  return x;
}
function imgViewItem(id, refresh) {
  var b = IMG.st.board, it = b && b.items.filter(function (x) { return x.id === id; })[0];
  if (!it || it.st !== 'ok') { if (refresh) imgBoxClose(); return; }
  var sig = id + '|' + it.ver;
  if (refresh && IMG.box && IMG.box.sig === sig) return;
  IMG.box = { kind: 'item', id: id, sig: sig };
  var h = { model: IMG.st.job && IMG.st.job.model || IMG.st.cfg.model, w: it.w, h: it.h, ratio: it.ratio, tier: IMG.st.cfg.tier, transparent: it.transparent, alpha: it.alpha, usd: it.usd, sec: it.sec, kind: 'batch', title: b.title, refs: 0, ts: Date.now() / 1000 };
  imgBox('<div class="fg-big' + (it.transparent ? ' t' : '') + '"><img src="' + imgThumb('i', it) + '" alt="' + esc(it.file) + '"></div>' +
    '<div class="fg-bi"><h3>IMAGE<em>' + esc(it.file) + '</em></h3><span class="fg-cap">' + esc(it.use || '') + '</span>' + imgKv(h).replace(/<dt>WHEN<\/dt><dd[^>]*>[^<]*<\/dd>/, '') +
    (it.warn ? '<div class="fg-cap" style="color:var(--c-neu)">' + esc(it.warn) + '</div>' : '') + '<div class="pr fg-scroll">' + esc(it.prompt) + '</div>' +
    '<div class="bt"><button class="fb pri" data-act="one" data-id="' + esc(it.id) + '"' + (imgRun() ? ' disabled' : '') + '>重生成</button><button class="fb" data-act="asrefi" data-id="' + esc(it.id) + '">当参考图</button>' +
    '<button class="fb" data-act="open">打开文件夹</button><button class="fb" data-act="boxclose">关闭（Esc）</button></div></div>', 'big');
}
function imgViewHist(id) {
  var h = (IMG.st.recent || []).concat(IMG.hist || []).filter(function (x) { return String(x.id) === String(id); })[0]; if (!h) return;
  IMG.box = { kind: 'hist', id: id };
  imgBox('<div class="fg-big' + (h.transparent ? ' t' : '') + '">' + (h.exists ? '<img src="' + imgThumb('h', h) + '" alt="">' : '<span class="fg-cap">文件被挪走或删了</span>') + '</div>' +
    '<div class="fg-bi"><h3>IMAGE<em>' + esc(h.file) + '</em></h3>' + imgKv(h) + '<div class="pr fg-scroll">' + esc(h.prompt) + '</div>' +
    '<div class="bt"><button class="fb pri" data-act="again" data-id="' + h.id + '">再来一张</button><button class="fb" data-act="asref" data-id="' + h.id + '"' + (h.exists ? '' : ' disabled') + '>当参考图</button>' +
    '<button class="fb" data-act="hopen" data-id="' + h.id + '"' + (h.exists ? '' : ' disabled') + '>打开文件夹</button><button class="fb" data-act="boxclose">关闭（Esc）</button></div></div>', 'big');
}
function imgPaste() {
  IMG.box = { kind: 'paste' };
  imgBox('<h3>PASTE LIST<em>把生图清单粘贴进来</em></h3><span class="fg-cap">视频窗口出的那份 Markdown，整份复制过来就行</span>' +
    '<textarea class="fi fg-ta fg-ptx" id="fgPaste" spellcheck="false" placeholder="# 这期的生图清单&#10;&#10;## 这期的视觉方向&#10;……&#10;&#10;### img01_重点_地铁站.png（用在：本周重点）&#10;- 比例：16:9&#10;- 透明背景：不开&#10;- 提示词：……"></textarea>' +
    '<div class="bt"><button class="fb" data-act="boxclose">取消</button><button class="fb pri" data-act="pasteok">认这份清单</button></div>', 'paste');
  setTimeout(function () { var t = $('#fgPaste'); if (t) t.focus(); }, 30);
}

/* ---------- 换模型：按厂商分好的列表 ---------- */
function imgPick() {
  IMG.box = { kind: 'pick' };
  imgBox('<h3>MODEL SELECT<em>换模型</em><button class="fb sm" data-act="mrefresh" id="fgMr">刷新模型列表</button><button class="fb x" data-act="boxclose" aria-label="关闭">' + ICONS.cross + '</button></h3>' +
    '<div class="fg-cap" id="fgMs">正在读…</div><div class="fg-pick"><div class="fg-vd" id="fgVd"></div><div class="fg-ml fg-scroll" id="fgMl"></div></div>', 'wide');
  if (!useLive()) { IMG.cat = imgDemoCat(); imgPickDraw(); return; }
  api('GET', '/api/img/models', null, 8000).then(function (j) { IMG.cat = j; imgPickDraw(); }).catch(function (e) { $('#fgMs').textContent = e.message; });
}
function imgDemoCat() {
  var m = IMG_DEMO.model, g = function (v, name, ms) { return { v: v, name: name, models: ms }; };
  var x = function (id, name, route, price, sec, d, warn) { return { id: id, name: name, route: route, price: price, sec: sec, d: d, warn: warn || '', known: true, listed: null, q: ['auto', 'low', 'medium', 'high'], tiers: ['1k', '2k', '4k'] }; };
  return { ts: null, n: 0, err: '', default: m.id, groups: [g('google', 'Google', [x('gemini-3.1-flash-image', 'Nano Banana 2', '', 0.055, 15, 'Google，0.5K~4K、14 种比例、最多 14 张参考图')]),
    g('openai', 'OpenAI', [Object.assign({}, m, { listed: null }), x('gpt-image-2.5-flare-vip', 'GPT Image 2.5 Flare VIP', '逆向', 0.03, 60, '速度优先、画面偏软', '当前不稳定'), x('gpt-image-2.5-sunburst', 'GPT Image 2.5 Sunburst', '官转', null, 40, '画质优先，按 token 计费')]),
    g('seedream', 'Seedream', [x('seedream-5-0-flash-260915', 'Seedream 5.0 Flash', '', 0.018, 15, '字节，快、便宜')]), g('flux', 'Flux', [x('flux-2-pro', 'FLUX.2 Pro', '', 0.03, 10, 'BFL，最多 8 张参考图')])] };
}
function imgPickDraw() {
  var c = IMG.cat, cur = IMG.st.cfg.model; if (!c || !$('#fgVd')) return;
  if (!IMG.vend || !c.groups.some(function (g) { return g.v === IMG.vend; })) {
    var hit = c.groups.filter(function (g) { return g.models.some(function (m) { return m.id === cur; }); })[0];
    IMG.vend = (hit || c.groups[0] || {}).v;
  }
  $('#fgMs').textContent = c.ts ? '上次拉列表：' + imgAgo(c.ts) + ' · 你的 Key 在 API易 能用 ' + c.n + ' 个生图模型（带「你的 Key 列表里没有」的用不了）' :
    '还没拉过列表：下面是认识的模型（线路、价格、大概多久都标好了）。点「刷新模型列表」用你的 Key 问 API易 现在有哪些，新出的也会出现在这里。' + (c.err ? ' 上次出错：' + c.err : '');
  $('#fgVd').innerHTML = c.groups.map(function (g) { return '<button data-act="vend" data-v="' + g.v + '" aria-selected="' + (g.v === IMG.vend) + '">' + esc(g.name) + '<b>' + g.models.length + '</b></button>'; }).join('') +
    '<div class="cap">没列出来的模型：<div class="fg-mid" style="margin-top:.4rem"><input class="fi" id="fgMid" placeholder="模型 ID，比如 gpt-image-3"><button class="fb sm" data-act="mid">用</button></div>价格、尺寸按厂商猜，先试一张看看</div>';
  var g = c.groups.filter(function (x) { return x.v === IMG.vend; })[0] || { models: [] };
  $('#fgMl').innerHTML = g.models.map(function (m) {
    return '<button class="fg-mc' + (m.listed === false ? ' off' : '') + '" data-act="usem" data-id="' + esc(m.id) + '" aria-pressed="' + (m.id === cur) + '"><span class="nm">' + esc(m.name) + '</span><code>' + esc(m.id) + '</code>' +
      imgTags(m, m.id === (c.default || 'gpt-image-2.5-sunburst-vip')) + '<p>' + esc(m.d || '') + '</p></button>';
  }).join('') || '<div class="fg-none">这一类没有模型</div>';
}
function imgUseModel(id) {
  if (!useLive()) { toast('演示模式：连上后端才能换'); return; }
  if (imgRun()) { toast('正在出图，等这批出完再换'); return; }
  var all = []; (IMG.cat ? IMG.cat.groups : []).forEach(function (g) { all = all.concat(g.models); });
  var m = all.filter(function (x) { return x.id === id; })[0] || { q: null, tiers: ['1k', '2k', '4k'] }, cfg = IMG.st.cfg, ch = { imgModel: id };
  if (m.q && m.q.indexOf(cfg.quality) < 0) ch.imgQuality = m.q.indexOf('high') >= 0 ? 'high' : m.q[m.q.length - 1];
  if (m.tiers && m.tiers.length && m.tiers.indexOf(cfg.tier) < 0) ch.imgRes = m.tiers.indexOf('2k') >= 0 ? '2k' : m.tiers[0];
  api('PUT', '/api/settings', ch).then(imgLoad).then(function () {
    imgBoxClose(); IMG.sig = {}; renderImg();
    var mm = IMG.st.model;
    imgLog('⇄ 换成 ' + esc(mm.name) + ' · ' + imgMoney(mm.price) + (mm.price == null && mm.known ? '（按量计费，画质开高很贵）' : ''), mm.price == null ? 'amb' : 'c');
    if (mm.price == null && mm.known) toast(mm.name + ' 按 token 计费：2K 高画质一张大概 $0.2，比 VIP 贵 7 倍', 7000);
  }).catch(function (e) { toast(e.message); });
}

/* ---------- 切标签、开机 ---------- */
function imgTab(t, force) {
  if (IMG.tab === t && !force) return;
  IMG.tab = t; try { localStorage.setItem('igTab', t); } catch (e) { /* 存不了就算了 */ }
  if (t === 'hist') IMG.hist = null;
  renderImg();
}
function imgBoot() {
  if (IMG.booted || !FG.anim) { IMG.booted = true; return; }
  IMG.booted = true;
  var s = IMG.st, m = s.model, b = s.board, el = document.createElement('div');
  el.className = 'fg-boot'; el.innerHTML = '<pre id="fgBootT"></pre>'; $('#fg').appendChild(el);
  var L = ['> FORGE BOOT SEQUENCE ............ <span class="ok">OK</span>', '> LINK ' + esc((s.cfg.base || '').replace(/^https?:\/\//, '')) + ' ... <span class="ok">' + (s.cfg.key ? 'KEY ' + esc(s.cfg.hint || '') : '没填 KEY') + '</span>',
    '> MODEL ' + esc(m.id) + ' . <span class="ok">' + esc(imgMoney(m.price)) + (m.price != null ? '/IMG' : '') + '</span>',
    '> ' + (b ? 'LIST ' + esc(b.md_name || b.title) + ' ... <span class="ok">' + b.items.length + ' ITEMS</span>' : 'TEMPLATES ............. <span class="ok">' + s.templates.length + '</span>'),
    '> OUTPUT ' + esc(s.out) + ' ... <span class="ok">READY</span>', '> IGNITION'];
  var i = 0, end = function () { if (!document.contains(el)) return; el.classList.add('off'); setTimeout(function () { el.remove(); }, 520); fgFlash(false); FG.WAVES.push({ t: FG.now, c: FG.col.c }); };
  el.onclick = end;
  (function step() { if (!document.contains(el) || el.classList.contains('off')) return; if (i < L.length) { el.firstChild.innerHTML += L[i++] + '\n'; setTimeout(step, 130); } else setTimeout(end, 220); })();
}

/* ================= 画布：点阵球、环、电线、粒子 ================= */
var FG = { on: false, raf: 0, anim: true, cv: null, ctx: null, sc: null, sx: null, W: 0, H: 0, DPR: 1, C: { x: 0, y: 0, R: 80 }, IN: null, OUT: null, ports: [], tiles: [], col: {}, now: 0, last: 0,
  rot: 0, rs: .25, mx: .6, my: .3, px: 0, py: 0, A: null, RV: [], BURST: [], WAVES: [], FLY: [], PACK: [], FLOAT: [], ARCS: [], arcT: 0, scope: [], hover: -1, pctV: 0, shown: {}, SPH: null, DUST: null,
  jid: null, seen: 0, wasRun: false, txt: {}, ro: null };
function fgRnd(a, b) { return a + Math.random() * (b - a); }
function fgClamp(x, a, b) { return Math.max(a, Math.min(b, x)); }
function fgEase(t) { return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
function fgBez(p0, p1, p2, p3, t) { var u = 1 - t; return { x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x, y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y }; }
function fgNum(id, v, fmt) {
  var el = $('#' + id); if (!el) return;
  if (!FG.anim) { el.textContent = fmt(v); delete FG.shown[id]; return; }
  var o = FG.shown[id] || (FG.shown[id] = { v: v, to: v, fmt: fmt }); o.to = v; o.fmt = fmt; if (el.textContent === '--') el.textContent = fmt(o.v);
}
function fgColors() {
  var fg = $('#fg'); if (!fg) return;
  var probe = document.createElement('i'); probe.style.display = 'none'; fg.appendChild(probe);
  var rd = function (v, def) { probe.style.color = ''; probe.style.color = 'var(' + v + ')'; var m = getComputedStyle(probe).color.match(/[\d.]+/g); return m && m.length >= 3 ? m.slice(0, 3).map(function (x) { return Math.round(+x); }).join(',') : def; };
  FG.col = { c: rd('--c', '46,242,255'), ok: rd('--ok', '61,255,168'), bad: rd('--bad', '255,59,92'), amb: rd('--amb', '255,176,46'), mag: rd('--mag', '255,79,216'), t: rd('--text', '214,244,255') };
  probe.remove();
  var C = FG.col; FG.FILL = [[], []]; FG.AMBF = [];
  for (var a = 0; a < 6; a++) { FG.FILL[0].push('rgba(' + C.c + ',' + (.12 + a * .16) + ')'); FG.FILL[1].push('rgba(' + C.mag + ',' + (.1 + a * .14) + ')'); FG.AMBF.push('rgba(' + C.amb + ',' + (.12 + a * .16) + ')'); }
  FG.mono = getComputedStyle(fg).fontFamily; FG.sans = getComputedStyle(document.body).fontFamily;
}
function fgBuild() {
  var lite = root.dataset.perf === 'on' || root.dataset.motion === 'reduced', N = lite ? 2200 : 4600, out = [];
  if (FG.SPH && FG.SPH.n === N) return;
  for (var k = 0; k < N; k++) {
    var y = 1 - 2 * (k + .5) / N, rr = Math.sqrt(1 - y * y), ph = k * 2.399963, x = Math.cos(ph) * rr, z = Math.sin(ph) * rr;
    if (Math.sin(5.1 * x + 1.3) * Math.sin(4.7 * y + 2.1) * Math.sin(5.3 * z + .7) > .32) continue;     /* 坑洞 */
    out.push({ x: x, y: y, z: z, fam: Math.sin(2.2 * x + 3 * y) + Math.cos(2.6 * z - y) > .2 ? 0 : 1, j: Math.random() * 6.28 });
  }
  out.n = N; FG.SPH = out;
  FG.DUST = []; for (var d = 0; d < (lite ? 160 : 380); d++) FG.DUST.push({ x: Math.random(), y: Math.random(), z: fgRnd(.2, 1), v: fgRnd(.002, .012) });
  FG.scope = []; for (var q = 0; q < 160; q++) FG.scope.push(0);
}
function fgMount() {
  FG.cv = $('#fgFx'); FG.ctx = FG.cv.getContext('2d'); FG.sc = $('#fgSc'); FG.sx = FG.sc.getContext('2d');
  FG.anim = S.set.motion !== 'off'; FG.hover = -1; FG.txt = {};
  fgBuild(); fgColors(); fgLayout();
  if (FG.ro) FG.ro.disconnect();
  if (window.ResizeObserver) { FG.ro = new ResizeObserver(function () { fgLayout(); if (!FG.anim) fgDraw(0); }); FG.ro.observe($('#fg')); }
  if (FG.A && FG.A.key) FG.A.frame = fgFrameN(FG.A.ratio);
  fgRun();
}
function fgLayout() {
  var fg = $('#fg'); if (!fg || !FG.cv) return;
  var o = fg.getBoundingClientRect(); FG.o = o; FG.port = root.dataset.orient === 'portrait';      /* 竖屏：清单、出图在核心下面，不画电线 */
  FG.DPR = Math.min(window.devicePixelRatio || 1, root.dataset.perf === 'on' ? 1 : 1.5); FG.W = o.width; FG.H = o.height;
  FG.cv.width = Math.round(FG.W * FG.DPR); FG.cv.height = Math.round(FG.H * FG.DPR); FG.ctx.setTransform(FG.DPR, 0, 0, FG.DPR, 0, 0);
  var core = $('#fgCore');
  if (core) { var r = core.getBoundingClientRect(); FG.C = { x: r.left - o.left + r.width / 2, y: r.top - o.top + r.height * .45, R: Math.max(40, Math.min(r.width * .22, r.height * .235)) }; FG.IN = { x: r.left - o.left + 4, y: FG.C.y }; FG.OUT = { x: r.right - o.left - 4, y: FG.C.y }; FG.core = true; }
  else { FG.C = { x: FG.W / 2, y: FG.H / 2, R: Math.min(FG.W, FG.H) * .3 }; FG.IN = FG.OUT = null; FG.core = false; }
  var s = FG.sc.getBoundingClientRect(); FG.sc.width = Math.max(1, Math.round(s.width * FG.DPR)); FG.sc.height = Math.max(1, Math.round(s.height * FG.DPR)); FG.sx.setTransform(FG.DPR, 0, 0, FG.DPR, 0, 0);
  fgPorts();
}
function fgPorts() {
  var o = FG.o; if (!o || !$('#fg')) return;
  var rel = function (b) { return { x: b.left - o.left, y: b.top - o.top, w: b.width, h: b.height }; };
  var vis = function (b, box) { return b.top + b.height / 2 >= box.top && b.top + b.height / 2 <= box.bottom; };
  FG.ports = [];
  var ql = $('#fgQl');
  if (ql && IMG.tab === 'batch' && IMG.st.board) {
    var qb = ql.getBoundingClientRect(), items = IMG.st.board.items;
    [].forEach.call(ql.querySelectorAll('.fg-r'), function (row, i) { var p = row.querySelector('.port').getBoundingClientRect(); if (vis(p, qb) && items[i]) FG.ports.push({ x: p.left - o.left + p.width / 2, y: p.top - o.top + p.height / 2, st: items[i].st, i: i }); });
  } else if (IMG.tab === 'single' && $('#fgLeft')) {
    var lb = $('#fgLeft').getBoundingClientRect(), run = imgRun() && IMG.st.job.kind === 'single' ? 'run' : 'idle';
    [].forEach.call(document.querySelectorAll('#fgRefs .fg-ref'), function (el) { var b = el.getBoundingClientRect(); FG.ports.push({ x: lb.right - o.left, y: b.top - o.top + b.height / 2, st: run, i: -1, ref: 1 }); });
    var ta = $('#fgPrompt'); if (ta) { var tb = ta.getBoundingClientRect(); FG.ports.push({ x: lb.right - o.left, y: tb.top - o.top + tb.height / 2, st: run, i: -2 }); }
  }
  FG.tiles = [];
  var og = $('#fgOg');
  if (og) { var gb = og.getBoundingClientRect(); [].forEach.call(og.querySelectorAll('.fg-tile'), function (el) { var b = el.getBoundingClientRect(); if (vis(b, gb)) FG.tiles.push({ x: b.left - o.left, y: b.top - o.top + b.height / 2, w: b.width, h: b.height, el: el }); }); }
}
function fgFrameN(ratio) {      /* 画面的框：以球心为原点、球半径为单位 */
  var p = String(ratio || '1:1').split(':'), w = +p[0] || 1, h = +p[1] || 1, k = 1.25 / Math.max(w, h);
  return { x: -w * k / 2, y: -h * k / 2, w: w * k, h: h * k };
}
function fgParts(fr) {
  var lite = root.dataset.perf === 'on' || root.dataset.motion === 'reduced', N = lite ? 700 : 1800;
  var cols = Math.max(4, Math.round(Math.sqrt(N * fr.w / fr.h))), rows = Math.max(4, Math.round(N / cols)), out = [], C = FG.col, pal = [C.c, C.mag, C.amb, C.c];
  for (var y = 0; y < rows; y++) for (var x = 0; x < cols; x++) {
    var a = Math.random() * 6.283, r = fgRnd(.8, 1.05);
    out.push({ tx: fr.x + (x + .5) / cols * fr.w, ty: fr.y + (y + .5) / rows * fr.h, sx: Math.cos(a) * r, sy: Math.sin(a) * r, dl: Math.random() * .45, c0: pal[(x * 7 + y * 3) % 4], col: null, v: (y + .5) / rows, cx: x, cy: y });
  }
  out.cols = cols; out.rows = rows; out.s = fr.w / cols * .82;
  return out;
}
function fgPct(A) { if (!A) return 0; var el = FG.now - A.base; return Math.min(.97, 1 - Math.exp(-1.6 * el / Math.max(5, A.sec))); }
function fgStart(cur, key, job) {
  var fr = fgFrameN(cur.ratio);
  FG.A = { key: key, label: cur.label, cur: cur, base: FG.now - (cur.run_s || 0), sec: cur.sec || 60, ratio: cur.ratio, frame: fr, parts: fgParts(fr), slot: job.done + job.fail + 1, n: job.n, typed: -1 };
  imgLog('→ 发给 ' + esc(job.mname) + ' · <span class="c">' + esc(cur.label) + '</span> · ' + esc(cur.ratio) + (cur.transparent ? ' · 透明' : '') + (cur.refs ? ' · ' + cur.refs + ' 张参考图' : ''), 'amb');
}
function fgFeed() {
  var j = IMG.st.job;
  if (!j) { FG.A = null; FG.jid = null; FG.wasRun = false; return; }
  if (FG.jid !== j.id) { FG.jid = j.id; FG.seen = IMG.mine === j.id ? 0 : j.results.length; FG.wasRun = j.st === 'run' && IMG.mine === j.id; FG.A = null; }
  while (FG.seen < j.results.length) fgResult(j.results[FG.seen++], j);
  var cur = j.st === 'run' ? j.cur : null, key = cur ? j.id + '|' + cur.label + '|' + cur.t0 : '';
  if (key !== (FG.A ? FG.A.key : '')) { if (cur) fgStart(cur, key, j); else FG.A = null; }
  else if (cur && FG.A) { var b = FG.now - (cur.run_s || 0); if (Math.abs(b - FG.A.base) > 2.5) FG.A.base = b; FG.A.slot = j.done + j.fail + 1; }
  if (j.st !== 'run' && FG.wasRun) fgAllDone(j);
  FG.wasRun = j.st === 'run';
}
function fgResult(res, job) {
  var A = FG.A && FG.A.label === res.label ? FG.A : null;
  if (A) FG.A = null;
  var k = job.kind === 'batch' && res.item ? 'i' + res.item : res.ok ? 'h' + res.hid : 'e' + job.id + '_' + job.results.indexOf(res);
  if (!FG.anim || !FG.core) { fgDoneLog(res); return; }
  if (!A) { var fr = fgFrameN(res.ratio); A = { label: res.label, ratio: res.ratio, frame: fr, parts: fgParts(fr), base: FG.now - 9, sec: 10 }; }
  var R = { A: A, res: res, k: k, t: FG.now, ph: res.ok ? 'load' : 'glitch', img: null };
  IMG.wait[k] = true;
  while (FG.RV.length > 2) fgEnd(FG.RV[0], true);
  FG.RV.push(R);
  if (res.ok) {
    var im = new Image(); im.decoding = 'async';
    im.onload = function () { fgPaint(R, im); };
    im.onerror = function () { R.ph = 'reveal'; R.t = FG.now; };
    im.src = IMG.st.demo ? fgArt('r' + res.label, res.ratio, res.transparent) : (job.kind === 'batch' && res.item ? '/api/img/file/' + encodeURIComponent(res.item) + '?v=' + Date.now() : '/api/img/hfile/' + res.hid);
    setTimeout(function () { if (R.ph === 'load') { R.ph = 'reveal'; R.t = FG.now; } }, 8000);
  }
}
function fgPaint(R, im) {       /* 用真图的颜色给粒子上色 */
  var P = R.A.parts, c = document.createElement('canvas'); c.width = P.cols; c.height = P.rows;
  var g = c.getContext('2d'); g.drawImage(im, 0, 0, P.cols, P.rows);
  try {
    var d = g.getImageData(0, 0, P.cols, P.rows).data;
    P.forEach(function (q) { var o = (q.cy * P.cols + q.cx) * 4; q.col = d[o + 3] < 40 ? 'x' : d[o] + ',' + d[o + 1] + ',' + d[o + 2]; });
  } catch (e) { /* 读不了像素就用原来的颜色 */ }
  R.img = im; R.ph = 'reveal'; R.t = FG.now;
}
function fgDoneLog(res) {
  if (res.ok) imgLog('✓ ' + esc(res.label) + ' · ' + (res.sec != null ? Math.round(res.sec) + 's' : '') + ' · $' + (+res.usd || 0).toFixed(3) + ' · 存好了' + (res.warn ? ' · <span class="amb">' + esc(res.warn) + '</span>' : ''), 'ok');
  else imgLog('✕ ' + esc(res.label) + ' · ' + esc(res.err || '没出来'), 'bad');
}
function fgEnd(R, quick) {
  FG.RV.splice(FG.RV.indexOf(R), 1);
  delete IMG.wait[R.k];
  var el = $('#fgOg [data-k="' + R.k + '"]'); if (el) { el.classList.remove('wait'); el.classList.add('in'); }
  IMG.sig.og = '';
  if (quick) fgDoneLog(R.res);
  if (!FG.RV.length && FG.pend) fgAllDone(FG.pend);
}
function fgFlash(red) { var f = $('#fgFlash'); if (!f) return; f.className = 'fg-flash' + (red ? ' red' : ''); void f.offsetWidth; f.classList.add('on'); }
function fgBurst(n, vmin, vmax, lmin, lmax, cs) { var C = FG.C; for (var k = 0; k < n; k++) { var a = Math.random() * 6.28, v = fgRnd(vmin, vmax); FG.BURST.push({ x: C.x, y: C.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: fgRnd(lmin, lmax), t: FG.now, c: cs[k % cs.length] }); } }
function fgAllDone(j) {
  if (FG.RV.length) { FG.pend = j; return; }          /* 还有图在显形：等最后一张落进格子再收尾 */
  FG.pend = null;
  imgLog('◆ ' + esc(j.msg || '好了'), j.fail || j.fatal ? 'amb' : 'c');
  if (!FG.anim || !FG.core) return;
  var C = FG.col; fgBurst(root.dataset.perf === 'on' ? 240 : 560, 120, 900, 1, 2.2, [C.c, C.ok, C.amb, C.mag]);
  FG.WAVES.push({ t: FG.now + .9, c: C.c }, { t: FG.now + 1.15, c: C.amb });
}
function fgWire(p) { var I = FG.IN, d = Math.max(60, Math.abs(I.x - p.x) * .45); return [p, { x: p.x + d, y: p.y }, { x: I.x - d, y: I.y }, I]; }
function fgWireOut(t) { var O = FG.OUT, d = Math.max(60, Math.abs(t.x - O.x) * .45); return [O, { x: O.x + d, y: O.y }, { x: t.x - d, y: t.y }, { x: t.x, y: t.y }]; }

function fgRun() {
  if (FG.raf || !FG.cv || S.view !== 'img') return;
  if (!FG.anim) { fgDraw(0); return; }
  FG.last = performance.now();
  var step = function (ts) {
    FG.raf = 0;
    if (S.view !== 'img' || !$('#fg') || document.hidden || !FG.anim) return;
    var lite = root.dataset.perf === 'on' || root.dataset.motion === 'reduced';
    if (lite && ts - FG.last < 30) { FG.raf = requestAnimationFrame(step); return; }      /* 省电 / 减弱：30 帧 */
    var dt = Math.min(.05, (ts - FG.last) / 1000); FG.last = ts; FG.now += dt;
    fgDraw(dt);
    FG.raf = requestAnimationFrame(step);
  };
  FG.raf = requestAnimationFrame(step);
}
function fgHalt() { if (FG.raf) cancelAnimationFrame(FG.raf); FG.raf = 0; if (FG.ro) { FG.ro.disconnect(); FG.ro = null; } }
document.addEventListener('visibilitychange', function () { if (!document.hidden && S.view === 'img') fgRun(); });
window.addEventListener('mousemove', function (e) { if (S.view !== 'img' || !FG.o) return; FG.mx = (e.clientX - FG.o.left) / (FG.W || 1); FG.my = (e.clientY - FG.o.top) / (FG.H || 1); });

function fgText(id, v, html) { if (FG.txt[id] === v) return; FG.txt[id] = v; var el = $('#' + id); if (el) el[html ? 'innerHTML' : 'textContent'] = v; }
function fgInfo(p) {
  if (!$('#fgFn')) return;
  var s = IMG.st, m = s.model, j = s.job, A = FG.A, b = s.board;
  if (A && imgRun()) {
    var c = A.cur;
    fgText('fgLab', 'RENDER CORE · ' + pad(A.slot) + ' / ' + pad(A.n));
    fgText('fgFn', A.label);
    fgText('fgMeta', 'RENDERING · ' + c.ratio + ' · ' + (c.size || '') + ' · ' + (c.transparent ? '透明背景' : '不透明') + (c.use ? ' · ' + c.use : ''));
    var n = FG.anim ? Math.floor(fgClamp(p * 1.35, 0, 1) * c.prompt.length) : c.prompt.length;
    if (n !== A.typed) { A.typed = n; var pr = $('#fgPr'); pr.className = 'pr' + (n < c.prompt.length ? ' type' : ''); pr.textContent = c.prompt.slice(0, n); FG.txt.fgPr = null; }
    fgText('fgSide', 'MODEL <b>' + esc(j.mname.replace(/^GPT Image /, 'GPT ')) + '</b><br>SIZE <b>' + esc(c.ratio) + ' · ' + esc(String(j.tier).toUpperCase()) + '</b><br>ALPHA <b>' + (c.transparent ? 'ON' : 'OFF') + '</b><br>COST <b>' + esc(imgMoney(m.price)) + '</b><br>REFS <b>' + (c.refs || 0) + '</b>', true);
    fgText('fgEl', imgDur(FG.now - A.base) + ' / 约 ' + imgDur(A.sec));
    return;
  }
  var pr2 = $('#fgPr'); if (pr2.classList.contains('type')) pr2.className = 'pr';
  fgText('fgEl', '');
  fgText('fgSide', 'MODEL <b>' + esc(m.name.replace(/^GPT Image /, 'GPT ')) + '</b><br>TIER <b>' + esc(m.tiers.length ? String(s.cfg.tier).toUpperCase() : '—') + '</b><br>QUALITY <b>' + esc(m.q ? s.quality[s.cfg.quality] || '' : '—') + '</b><br>COST <b>' + esc(imgMoney(m.price)) + '</b><br>KEY <b>' + (s.cfg.key ? esc(s.cfg.hint) : '没填') + '</b>', true);
  if (j && j.st !== 'run' && j.kind === IMG.tab) {
    fgText('fgLab', 'RENDER CORE · COMPLETE');
    fgText('fgFn', (j.st === 'stop' ? '停了' : '出完了') + ' · ' + j.done + ' 张存好' + (j.fail ? ' · ' + j.fail + ' 张没出来' : ''));
    fgText('fgMeta', '用时 ' + imgDur(j.elapsed) + ' · 花了 $' + (+j.usd || 0).toFixed(2) + ' · ' + j.mname);
    fgText('fgPr', '<span class="' + (j.fail || j.fatal ? 'bad' : 'ok') + '">' + esc(j.msg) + '</span>', true);
    return;
  }
  fgText('fgLab', 'RENDER CORE · STANDBY');
  if (IMG.tab === 'batch') {
    fgText('fgFn', b ? '认出 ' + b.items.length + ' 张 · 点右上角「' + (b.items.every(function (x) { return x.st === 'ok'; }) ? '打开文件夹' : '批量生成') + '」' : '把生图清单拖进来');
    fgText('fgMeta', b ? (b.title + ' · ' + (b.direction ? '视觉方向已认' : '没写视觉方向')) : 'MARKDOWN · 文件名 · 比例 · 透明背景 · 提示词');
    fgText('fgPr', esc(b && b.direction ? b.direction : '一张一张出，按清单里的文件名存进「生图输出」；Key 不对、余额不够、被限流会整批停，不白花钱。'), true);
  } else {
    fgText('fgFn', s.cfg.key || s.demo ? '写一句提示词，点「生成」' : '先到 设置 › 云端 填 API易 Key');
    fgText('fgMeta', m.name + ' · ' + imgMoney(m.price) + (m.sec ? ' · 大概 ' + m.sec + ' 秒一张' : ''));
    fgText('fgPr', esc(m.d || ''), true);
  }
}
function fgDraw(dt) {
  var ctx = FG.ctx; if (!ctx || !$('#fg')) return;
  var C = FG.col, W = FG.W, H = FG.H, run = imgRun() && !!FG.A, A = FG.A, p = fgPct(A), ox = (FG.px) * 18, oy = (FG.py) * 12;
  FG.px += ((FG.mx - .5) - FG.px) * Math.min(1, dt * 3); FG.py += ((FG.my - .5) - FG.py) * Math.min(1, dt * 3);
  for (var id in FG.shown) { var o = FG.shown[id], el = $('#' + id); o.v += (o.to - o.v) * Math.min(1, dt * 8); if (Math.abs(o.to - o.v) < .001) o.v = o.to; if (el) { var t = o.fmt(o.v); if (el.textContent !== t) el.textContent = t; } }
  FG.pctV += ((run ? p * 100 : 0) - FG.pctV) * (FG.anim ? Math.min(1, dt * 10) : 1);
  var pe = $('#fgPct'); if (pe) { var pt = String(Math.round(FG.pctV)); if (pe.textContent !== pt) pe.textContent = pt; }
  FG.rs += ((run ? 1.15 : .25) - FG.rs) * Math.min(1, dt * 2); FG.rot += FG.rs * dt;
  fgInfo(p);
  ctx.clearRect(0, 0, W, H);
  ctx.globalCompositeOperation = 'lighter';
  FG.DUST.forEach(function (d) {
    d.y -= d.v * dt * (run ? 2.2 : 1); if (d.y < 0) { d.y = 1; d.x = Math.random(); }
    ctx.fillStyle = 'rgba(' + C.c + ',' + (.06 + d.z * .2) + ')'; ctx.fillRect(d.x * W + ox * d.z, d.y * H + oy * d.z, d.z * 1.8, d.z * 1.8);
  });
  if (!FG.core) { ctx.globalCompositeOperation = 'source-over'; fgScope(run, dt); return; }
  var X = FG.C, R0 = X.R;
  var gl = ctx.createRadialGradient(X.x, X.y, R0 * .2, X.x, X.y, R0 * 2.1);
  gl.addColorStop(0, 'rgba(' + (run ? C.amb : C.c) + ',' + (run ? .12 : .08) + ')'); gl.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = gl; ctx.fillRect(X.x - R0 * 2.2, X.y - R0 * 2.2, R0 * 4.4, R0 * 4.4);
  ctx.globalCompositeOperation = 'source-over';
  /* 进来的线 */
  if (FG.IN && !FG.port) FG.ports.forEach(function (pt) {
    var w = fgWire(pt), r = pt.st === 'run', hv = FG.hover === pt.i;
    ctx.beginPath(); ctx.moveTo(w[0].x, w[0].y); ctx.bezierCurveTo(w[1].x, w[1].y, w[2].x, w[2].y, w[3].x, w[3].y);
    ctx.lineWidth = r ? 2.4 : hv ? 2 : 1;
    ctx.strokeStyle = r ? 'rgb(' + C.amb + ')' : pt.st === 'ok' ? 'rgba(' + C.ok + ',.45)' : pt.st === 'err' ? 'rgba(' + C.bad + ',.55)' : pt.st === 'queue' ? 'rgba(' + C.c + ',.4)' : hv ? 'rgba(' + C.c + ',.8)' : 'rgba(' + C.c + ',.15)';
    if (r) { ctx.setLineDash([10, 7]); ctx.lineDashOffset = -FG.now * 60; ctx.shadowColor = 'rgb(' + C.amb + ')'; ctx.shadowBlur = 12; }
    ctx.stroke(); ctx.setLineDash([]); ctx.shadowBlur = 0;
    if (r && FG.anim) for (var q = 0; q < 6; q++) { var b = fgBez(w[0], w[1], w[2], w[3], (FG.now * .7 + q / 6) % 1); ctx.fillStyle = '#fff6d8'; ctx.beginPath(); ctx.arc(b.x, b.y, 2.2, 0, 7); ctx.fill(); }
  });
  /* 出去的线 */
  if (FG.OUT && !FG.port) FG.tiles.forEach(function (t) {
    var w = fgWireOut(t), bad = t.el.classList.contains('err'), wt = t.el.classList.contains('wait');
    if (wt) return;
    ctx.beginPath(); ctx.moveTo(w[0].x, w[0].y); ctx.bezierCurveTo(w[1].x, w[1].y, w[2].x, w[2].y, w[3].x, w[3].y);
    ctx.lineWidth = 1.1; ctx.strokeStyle = 'rgba(' + (bad ? C.bad : C.ok) + ',' + (bad ? .5 : .38) + ')'; ctx.stroke();
  });
  /* 球 */
  ctx.globalCompositeOperation = 'lighter';
  var cr = Math.cos(FG.rot), sr = Math.sin(FG.rot), tilt = .38 + Math.sin(FG.now * .23) * .12, ct = Math.cos(tilt), st = Math.sin(tilt);
  var R = R0 * .92, cam = R * 3.2, ag = run ? 1 : 0, cx = X.x + ox * .4, cy = X.y + oy * .4, now = FG.now;
  for (var i = 0; i < FG.SPH.length; i++) {
    var s = FG.SPH[i], n = 1 + .07 * Math.sin(3 * s.x + now * 1.3) * Math.cos(3 * s.y + now * .9) + ag * .035 * Math.sin(9 * s.z + now * 7 + s.j);
    var x = s.x * n, y = s.y * n, z = s.z * n, x1 = x * cr - z * sr, z1 = x * sr + z * cr, y1 = y * ct - z1 * st, z2 = y * st + z1 * ct;
    var f = cam / (cam + z2 * R), dep = (1 - z2) / 2, a = Math.min(5, Math.floor(dep * 6)), sz = .7 + dep * 2.1;
    ctx.fillStyle = run && s.fam === 1 && dep > .5 ? FG.AMBF[a] : FG.FILL[s.fam][a];
    ctx.fillRect(cx + x1 * R * f, cy + y1 * R * f, sz, sz);
  }
  ctx.globalCompositeOperation = 'source-over';
  fgRing(cx, cy, p, run);
  if (A && run && !FG.RV.length) fgMat(A, p, false, 1);        /* 上一张还在显形 / 飞出去：等它走了再画这一张 */
  FG.RV.slice().forEach(function (Rv) { fgReveal(Rv); });
  fgFx(dt);
  [[FG.IN, C.amb], [FG.OUT, C.ok]].forEach(function (q) {
    if (!q[0] || FG.port) return; var pu = 1 + Math.sin(FG.now * 4) * .25;
    ctx.beginPath(); ctx.arc(q[0].x, q[0].y, 5, 0, 7); ctx.fillStyle = 'rgb(' + q[1] + ')'; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 12; ctx.fill(); ctx.shadowBlur = 0;
    ctx.beginPath(); ctx.arc(q[0].x, q[0].y, 11 * pu, 0, 7); ctx.strokeStyle = 'rgba(' + q[1] + ',.5)'; ctx.lineWidth = 1; ctx.stroke();
  });
  fgScope(run, dt);
}
function fgBox(A) { var X = FG.C, f = A.frame; return { x: X.x + f.x * X.R, y: X.y + f.y * X.R, w: f.w * X.R, h: f.h * X.R }; }
function fgMat(A, p, colored, alpha, sweep, glitch) {     /* 粒子从球上飞过来拼成画面 */
  var ctx = FG.ctx, X = FG.C, F = fgBox(A), C = FG.col, cur = A.cur || {};
  ctx.fillStyle = 'rgba(2,8,14,' + (.7 * alpha) + ')'; ctx.fillRect(F.x, F.y, F.w, F.h);
  if (cur.transparent) { ctx.save(); ctx.beginPath(); ctx.rect(F.x, F.y, F.w, F.h); ctx.clip(); ctx.fillStyle = 'rgba(' + C.t + ',.06)'; for (var yy = F.y; yy < F.y + F.h; yy += 12) for (var xx = F.x + ((yy - F.y) / 12 % 2) * 12; xx < F.x + F.w; xx += 24) ctx.fillRect(xx, yy, 12, 12); ctx.restore(); }
  ctx.globalCompositeOperation = 'lighter';
  var P = A.parts, sz = P.s * X.R;
  for (var i = 0; i < P.length; i++) {
    var q = P[i], t = fgClamp((p - q.dl) / .5, 0, 1), e = fgEase(t), j = (1 - e) * 6;
    var px = X.x + (q.sx + (q.tx - q.sx) * e) * X.R + Math.sin(FG.now * 9 + q.dl * 40) * j, py = X.y + (q.sy + (q.ty - q.sy) * e) * X.R + Math.cos(FG.now * 8 + q.dl * 30) * j;
    var useCol = colored && q.col && q.v <= sweep;
    if (useCol && q.col === 'x') continue;
    ctx.globalAlpha = (.18 + .82 * t) * alpha * (useCol ? 1 : .8);
    ctx.fillStyle = 'rgb(' + (glitch ? (Math.random() < .5 ? C.bad : C.t) : useCol ? q.col : q.c0) + ')';
    ctx.fillRect(px, py, sz, sz);
  }
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
  var sy = F.y + F.h * ((FG.now * .9) % 1), sg = ctx.createLinearGradient(0, sy - 26, 0, sy);
  sg.addColorStop(0, 'rgba(0,0,0,0)'); sg.addColorStop(1, 'rgba(' + (glitch ? C.bad : C.amb) + ',.35)');
  ctx.fillStyle = sg; ctx.fillRect(F.x, sy - 26, F.w, 26); ctx.fillStyle = 'rgb(' + (glitch ? C.bad : C.amb) + ')'; ctx.fillRect(F.x, sy, F.w, 1.5);
  fgCorners(F, glitch ? C.bad : C.amb);
}
function fgCorners(F, c) {
  var ctx = FG.ctx, L = 16;
  ctx.strokeStyle = 'rgb(' + c + ')'; ctx.lineWidth = 1; ctx.shadowColor = ctx.strokeStyle; ctx.shadowBlur = 14; ctx.strokeRect(F.x, F.y, F.w, F.h); ctx.shadowBlur = 0; ctx.lineWidth = 3;
  [[F.x, F.y, 1, 1], [F.x + F.w, F.y, -1, 1], [F.x, F.y + F.h, 1, -1], [F.x + F.w, F.y + F.h, -1, -1]].forEach(function (q) { ctx.beginPath(); ctx.moveTo(q[0] + q[2] * L, q[1]); ctx.lineTo(q[0], q[1]); ctx.lineTo(q[0], q[1] + q[3] * L); ctx.stroke(); });
}
function fgReveal(R) {
  var ctx = FG.ctx, C = FG.col, A = R.A, age = FG.now - R.t, F = fgBox(A);
  if (R.ph === 'load') { fgMat(A, 1, false, 1); return; }
  if (R.ph === 'glitch') {
    fgMat(A, 1, false, 1, 0, true);
    for (var k = 0; k < 12; k++) { ctx.fillStyle = 'rgba(' + C.bad + ',' + fgRnd(.15, .5) + ')'; ctx.fillRect(F.x + fgRnd(-20, 20), F.y + Math.random() * F.h, F.w, fgRnd(3, 16)); }
    ctx.save(); ctx.translate(FG.C.x, FG.C.y); ctx.rotate(-.12); ctx.strokeStyle = 'rgb(' + C.bad + ')'; ctx.lineWidth = 3; ctx.strokeRect(-160, -26, 320, 52);
    ctx.fillStyle = 'rgb(' + C.bad + ')'; ctx.font = '700 19px ' + FG.sans; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(/审核/.test(R.res.err || '') ? 'MODERATION · 审核没过' : 'FAILED · 没出来', 0, 1); ctx.restore();
    if (age > .7) {
      fgBurst(140, 60, 360, .4, 1, [C.bad]); FG.WAVES.push({ t: FG.now, c: C.bad }); FG.FLOAT.push({ t: FG.now, txt: /审核|拦/.test(R.res.err || '') ? 'BLOCKED · $0.00' : 'FAILED', c: C.bad }); fgFlash(true);
      if (root.dataset.motion !== 'reduced') { var fg = $('#fg'); fg.classList.remove('shake'); void fg.offsetWidth; fg.classList.add('shake'); }
      fgDoneLog(R.res); fgEnd(R, false);
    }
    return;
  }
  if (R.ph === 'reveal') {
    var t = fgClamp(age / .85, 0, 1);
    fgMat(A, 1, true, 1 - fgClamp((t - .6) / .4, 0, 1) * .6, t * 1.15);
    if (R.img && t > .45) { ctx.globalAlpha = fgClamp((t - .45) / .55, 0, 1); fgImg(R.img, F); ctx.globalAlpha = 1; }
    if (t >= 1) {
      R.ph = 'fly'; R.t = FG.now; R.F = F;
      var tile = $('#fgOg [data-k="' + R.k + '"]'), gb = $('#fgOg') && $('#fgOg').getBoundingClientRect(), o = FG.o;
      if (tile && gb) { var b = tile.getBoundingClientRect(); if (b.top + b.height / 2 >= gb.top && b.top + b.height / 2 <= gb.bottom) R.to = { x: b.left - o.left, y: b.top - o.top, w: b.width, h: b.height }; }
      if (!R.to && FG.OUT) R.to = { x: FG.OUT.x + 30, y: FG.OUT.y - 20, w: 40, h: 40 };
      fgBurst(root.dataset.perf === 'on' ? 90 : 220, 80, 520, .6, 1.4, [C.ok, C.c]); FG.WAVES.push({ t: FG.now, c: C.ok }); fgFlash(false);
      FG.FLOAT.push({ t: FG.now, txt: '+' + imgMoney(R.res.usd != null ? +R.res.usd : null) + ' · SAVED', c: C.ok });
      fgDoneLog(R.res);
    }
    return;
  }
  if (R.ph === 'fly') {
    var u = fgClamp(age / .6, 0, 1), e = fgEase(u), T = R.to || R.F, F0 = R.F;
    var fit = Math.min(T.w / F0.w, T.h / F0.h), w = F0.w + (F0.w * fit - F0.w) * e, h = F0.h + (F0.h * fit - F0.h) * e;
    var x = F0.x + (T.x + (T.w - F0.w * fit) / 2 - F0.x) * e, y = F0.y + (T.y + (T.h - F0.h * fit) / 2 - F0.y) * e;
    ctx.globalAlpha = 1 - u * .2; if (R.img) fgImg(R.img, { x: x, y: y, w: w, h: h }); else { ctx.fillStyle = 'rgba(' + C.ok + ',.4)'; ctx.fillRect(x, y, w, h); } ctx.globalAlpha = 1;
    if (u >= 1) {
      if (R.to && FG.OUT && !FG.port) for (var k2 = 0; k2 < 30; k2++) FG.PACK.push({ w: fgWireOut({ x: R.to.x, y: R.to.y + R.to.h / 2 }), t: FG.now - .5 + k2 * .012, dur: fgRnd(.4, .6), c: C.ok });
      fgEnd(R, false); fgPorts();
    }
  }
}
function fgImg(im, F) { var k = Math.min(F.w / im.naturalWidth, F.h / im.naturalHeight), w = im.naturalWidth * k, h = im.naturalHeight * k; FG.ctx.drawImage(im, F.x + (F.w - w) / 2, F.y + (F.h - h) / 2, w, h); }
function fgFx(dt) {
  var ctx = FG.ctx, X = FG.C;
  ctx.globalCompositeOperation = 'lighter';
  FG.BURST = FG.BURST.filter(function (b) { var age = FG.now - b.t; if (age > b.life) return false; b.vx *= 1 - dt * 1.6; b.vy *= 1 - dt * 1.6; b.x += b.vx * dt; b.y += b.vy * dt; ctx.fillStyle = 'rgba(' + b.c + ',' + (1 - age / b.life) + ')'; ctx.fillRect(b.x, b.y, 2.2, 2.2); return true; });
  FG.WAVES = FG.WAVES.filter(function (w) { var age = FG.now - w.t; if (age < 0) return true; if (age > 1.1) return false; ctx.beginPath(); ctx.arc(X.x, X.y, X.R * (1 + age * 1.6), 0, 7); ctx.lineWidth = 3 * (1 - age / 1.1); ctx.strokeStyle = 'rgba(' + w.c + ',' + (.8 * (1 - age / 1.1)) + ')'; ctx.stroke(); return true; });
  FG.PACK = FG.PACK.filter(function (k) { var t = (FG.now - k.t) / k.dur; if (t < 0) return true; if (t > 1) return false; var pt = fgBez(k.w[0], k.w[1], k.w[2], k.w[3], t); ctx.fillStyle = 'rgba(' + k.c + ',.95)'; ctx.fillRect(pt.x - 1.5, pt.y - 1.5, 3, 3); return true; });
  ctx.globalCompositeOperation = 'source-over';
  FG.FLOAT = FG.FLOAT.filter(function (f) {
    var age = FG.now - f.t; if (age > 1.6) return false;
    ctx.save(); ctx.globalAlpha = 1 - age / 1.6; ctx.fillStyle = 'rgb(' + f.c + ')'; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 6; ctx.font = '700 24px ' + FG.mono; ctx.textAlign = 'center';
    ctx.fillText(f.txt, X.x, X.y - X.R * .6 - age * 70); ctx.restore(); return true;
  });
}
function fgArcText(txt, cx, cy, r, a0, col) {
  var ctx = FG.ctx; ctx.save(); ctx.fillStyle = col; ctx.font = '10px ' + FG.mono; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  var st = 10.5 / r, a = a0 - (txt.length - 1) * st / 2;
  for (var i = 0; i < txt.length; i++) { ctx.save(); ctx.translate(cx + Math.cos(a) * r, cy + Math.sin(a) * r); ctx.rotate(a + Math.PI / 2); ctx.fillText(txt[i], 0, 0); ctx.restore(); a += st; }
  ctx.restore();
}
function fgRing(cx, cy, p, run) {
  var ctx = FG.ctx, C = FG.col, R = FG.C.R, now = FG.now, gl = FG.RV.some(function (r) { return r.ph === 'glitch'; });
  ctx.save(); ctx.translate(cx, cy);
  if (ctx.createConicGradient) {
    var g = ctx.createConicGradient(now * 1.4, 0, 0); g.addColorStop(0, 'rgba(' + (run ? C.amb : C.c) + ',' + (run ? .22 : .16) + ')'); g.addColorStop(.12, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, R * 1.38, 0, 7); ctx.arc(0, 0, R * 1.08, 0, 7, true); ctx.fill();
  }
  ctx.rotate(-now * .05);
  for (var k = 0; k < 120; k++) { var a = k / 120 * 6.283, l = k % 10 === 0 ? 14 : k % 5 === 0 ? 8 : 4; ctx.strokeStyle = 'rgba(' + C.c + ',' + (k % 10 === 0 ? .8 : .35) + ')'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(Math.cos(a) * R * 1.42, Math.sin(a) * R * 1.42); ctx.lineTo(Math.cos(a) * (R * 1.42 - l), Math.sin(a) * (R * 1.42 - l)); ctx.stroke(); }
  ctx.rotate(now * .05);
  ctx.lineWidth = 1.2; ctx.strokeStyle = 'rgba(' + C.c + ',.45)'; ctx.setLineDash([R * .09, R * .05]); ctx.lineDashOffset = now * 40; ctx.beginPath(); ctx.arc(0, 0, R * 1.12, 0, 7); ctx.stroke();
  ctx.strokeStyle = 'rgba(' + C.mag + ',.35)'; ctx.setLineDash([3, 9]); ctx.lineDashOffset = -now * 25; ctx.beginPath(); ctx.arc(0, 0, R * 1.5, 0, 7); ctx.stroke(); ctx.setLineDash([]);
  ctx.lineWidth = 7; ctx.strokeStyle = 'rgba(' + C.amb + ',.12)'; ctx.beginPath(); ctx.arc(0, 0, R * 1.25, 0, 7); ctx.stroke();
  if (p > 0 && run) {
    ctx.strokeStyle = 'rgb(' + (gl ? C.bad : C.amb) + ')'; ctx.shadowColor = ctx.strokeStyle; ctx.shadowBlur = 16; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.arc(0, 0, R * 1.25, -Math.PI / 2, -Math.PI / 2 + p * 6.283); ctx.stroke(); ctx.shadowBlur = 0; ctx.lineCap = 'butt';
    var ha = -Math.PI / 2 + p * 6.283; ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(Math.cos(ha) * R * 1.25, Math.sin(ha) * R * 1.25, 4.5, 0, 7); ctx.fill();
  }
  for (var q = 0; q < 144; q++) {
    var b = q / 144 * 6.283, n = Math.abs(Math.sin(q * .37 + now * (run ? 6 : 1.4)) * Math.cos(q * .11 - now * (run ? 3.3 : .8))), len = R * (.02 + n * (run ? .13 : .04)), r0 = R * 1.31;
    ctx.strokeStyle = 'rgba(' + (run ? C.amb : C.c) + ',' + ((run ? .25 : .15) + n * (run ? .7 : .5)) + ')'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(Math.cos(b) * r0, Math.sin(b) * r0); ctx.lineTo(Math.cos(b) * (r0 + len), Math.sin(b) * (r0 + len)); ctx.stroke();
  }
  [[1.12, 1.1, C.c], [1.5, -.55, C.mag], [1.25, 1.9, C.amb], [1.42, .8, C.ok]].forEach(function (sat, k) {
    var a = now * sat[1] * (run ? 1.8 : 1) + k * 1.7;
    for (var t = 0; t < 14; t++) { var bb = a - t * .045 * Math.sign(sat[1]); ctx.fillStyle = 'rgba(' + sat[2] + ',' + ((1 - t / 14) * .9) + ')'; ctx.fillRect(Math.cos(bb) * R * sat[0] - 1.5, Math.sin(bb) * R * sat[0] - 1.5, 3, 3); }
    ctx.fillStyle = '#fff'; ctx.shadowColor = 'rgb(' + sat[2] + ')'; ctx.shadowBlur = 12; ctx.beginPath(); ctx.arc(Math.cos(a) * R * sat[0], Math.sin(a) * R * sat[0], 3.2, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
  });
  if (run && FG.A && FG.anim) {          /* 电弧：出图时从环上打到画框 */
    FG.arcT -= 1 / 60; if (FG.arcT <= 0) { FG.arcT = fgRnd(.04, .14); FG.ARCS.push({ a: Math.random() * 6.283, t: now, life: fgRnd(.08, .18) }); }
    var F = fgBox(FG.A);
    FG.ARCS = FG.ARCS.filter(function (ac) {
      var age = now - ac.t; if (age > ac.life) return false;
      var sx = Math.cos(ac.a) * R * 1.1, sy = Math.sin(ac.a) * R * 1.1, ex = fgClamp(Math.cos(ac.a) * R, F.x - cx, F.x + F.w - cx), ey = fgClamp(Math.sin(ac.a) * R, F.y - cy, F.y + F.h - cy);
      ctx.beginPath(); ctx.moveTo(sx, sy);
      for (var z = 1; z <= 8; z++) { var t = z / 8; ctx.lineTo(sx + (ex - sx) * t + (z < 8 ? fgRnd(-9, 9) : 0), sy + (ey - sy) * t + (z < 8 ? fgRnd(-9, 9) : 0)); }
      ctx.strokeStyle = 'rgba(255,236,190,' + (1 - age / ac.life) + ')'; ctx.lineWidth = 1.5; ctx.shadowColor = 'rgb(' + C.amb + ')'; ctx.shadowBlur = 14; ctx.stroke(); ctx.shadowBlur = 0; return true;
    });
  }
  var cg = ctx.createRadialGradient(0, 0, 0, 0, 0, R * .9), pu = .5 + Math.sin(now * (run ? 7 : 2)) * .15;
  cg.addColorStop(0, 'rgba(' + (run ? C.amb : C.c) + ',' + ((run ? .22 : .14) * pu) + ')'); cg.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.globalCompositeOperation = 'lighter'; ctx.fillStyle = cg; ctx.beginPath(); ctx.arc(0, 0, R * .9, 0, 7); ctx.fill(); ctx.globalCompositeOperation = 'source-over';
  ctx.strokeStyle = 'rgba(' + C.c + ',.7)'; ctx.lineWidth = 1.5;
  [[0, -1], [0, 1], [-1, 0], [1, 0]].forEach(function (d) { ctx.beginPath(); ctx.moveTo(d[0] * R * 1.55, d[1] * R * 1.55); ctx.lineTo(d[0] * R * 1.66, d[1] * R * 1.66); ctx.stroke(); });
  ctx.restore();
  var m = IMG.st.model;
  fgArcText(('APIYI // ' + m.id).toUpperCase().slice(0, 34), cx, cy, R * 1.6, -Math.PI / 2 - .9 + Math.sin(now * .2) * .05, 'rgba(' + C.c + ',.75)');
  fgArcText(run ? 'RENDERING · 出图中' : 'STANDBY', cx, cy, R * 1.6, -Math.PI / 2 + .95, run ? 'rgba(' + C.amb + ',.9)' : 'rgba(' + C.c + ',.6)');
}
function fgScope(run, dt) {
  var sx = FG.sx; if (!sx) return;
  var w = FG.sc.width / FG.DPR, h = FG.sc.height / FG.DPR, C = FG.col, amp = run ? 1 : .15, now = FG.now;
  if (dt) { FG.scope.shift(); FG.scope.push((Math.sin(now * 23) * .5 + Math.sin(now * 51) * .3 + (Math.random() - .5) * .9) * amp); }
  sx.clearRect(0, 0, w, h);
  sx.strokeStyle = 'rgba(' + C.c + ',.12)'; sx.lineWidth = 1;
  for (var y = 0; y <= 4; y++) { sx.beginPath(); sx.moveTo(0, y * h / 4); sx.lineTo(w, y * h / 4); sx.stroke(); }
  sx.beginPath(); FG.scope.forEach(function (v, k) { var x = k / (FG.scope.length - 1) * w, yy = h / 2 - v * h * .42; if (k) sx.lineTo(x, yy); else sx.moveTo(x, yy); });
  sx.strokeStyle = 'rgb(' + (run ? C.amb : C.c) + ')'; sx.lineWidth = 1.6; sx.shadowColor = sx.strokeStyle; sx.shadowBlur = 8; sx.stroke(); sx.shadowBlur = 0;
  var s = IMG.st, A = FG.A;
  fgText('fgLat', run && A ? 'TX · 等回图 · ' + imgDur(now - A.base) : s.cfg.key || s.demo ? 'IDLE · KEY ' + (s.cfg.hint || '') : 'IDLE · 没填 KEY');
}
var FG_ART = {};
function fgArt(id, ratio, tr) {      /* 演示模式的「图」：程序画的 */
  if (FG_ART[id]) return FG_ART[id];
  var p = String(ratio).split(':'), k = Math.min(320 / +p[0], 320 / +p[1]), w = Math.round(+p[0] * k), h = Math.round(+p[1] * k), c = document.createElement('canvas');
  c.width = w; c.height = h;
  var g = c.getContext('2d'), sd = 0; for (var i = 0; i < id.length; i++) sd = (sd * 31 + id.charCodeAt(i)) % 9973;
  var Rn = function (n) { var x = Math.sin(sd + n * 12.9898) * 43758.5453; return x - Math.floor(x); }, neon = ['#ffd23f', '#2ef2ff', '#ff4fd8', '#3dffa8'];
  if (!tr) {
    var bg = g.createLinearGradient(0, 0, w, h); bg.addColorStop(0, '#071630'); bg.addColorStop(1, '#14082a'); g.fillStyle = bg; g.fillRect(0, 0, w, h);
    for (var b = 0; b < 9; b++) { var bw = 14 + Rn(b + 3) * 34, bh = h * (.18 + Rn(b + 9) * .45), bx = (b / 9) * w + Rn(b) * 10; g.fillStyle = 'rgba(10,30,70,.95)'; g.fillRect(bx, h - bh, bw, bh); }
    for (var l = 0; l < 4; l++) { g.strokeStyle = neon[(l + sd) % 4]; g.lineWidth = 2.5; g.shadowColor = g.strokeStyle; g.shadowBlur = 12; g.beginPath(); var y0 = h * (.3 + Rn(l + 20) * .4); g.moveTo(0, y0); g.bezierCurveTo(w * .3, y0 - 40 + Rn(l) * 80, w * .6, y0 + 40 - Rn(l + 1) * 80, w, h * (.2 + Rn(l + 30) * .6)); g.stroke(); }
    g.shadowBlur = 0; var sun = g.createRadialGradient(w * .7, h * .38, 2, w * .7, h * .38, h * .3); sun.addColorStop(0, 'rgba(255,210,63,.95)'); sun.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = sun; g.fillRect(0, 0, w, h);
  } else {
    var cx = w / 2, cy = h / 2, mm = Math.min(w, h), col = neon[sd % 4];
    g.lineWidth = 3; g.strokeStyle = col; g.shadowColor = col; g.shadowBlur = 16; g.beginPath(); g.arc(cx, cy, mm * .26, 0, 7); g.fillStyle = col; g.fill(); g.beginPath(); g.arc(cx, cy, mm * .36, 0, 7); g.stroke();
  }
  return (FG_ART[id] = c.toDataURL());
}

/* ---------- 点、拖、粘贴 ---------- */
$('#view-img').addEventListener('click', function (ev) {
  var t = ev.target.closest('[data-act],[data-tier],[data-q],[data-cfg],[data-ratio],[data-cnt],#fgGo,#fgTr,#fgEdT'); if (!t || t.disabled) return;
  var act = t.dataset.act, s = IMG.st, live = useLive(), id = t.dataset.id;
  if (t.id === 'fgGo') {
    if (imgRun()) { if (!live) { toast('演示模式'); return; } api('POST', '/api/img/stop', {}).then(function (j) { IMG.st.job = j.job; imgSync(); imgLog('■ 停下：没开始的不出了，正在出的这张出完', 'bad'); }); return; }
    if (IMG.tab === 'single') imgGen();
    else if (IMG.tab === 'batch') { var b = s.board; if (!b) $('#fgMd').click(); else if (b.items.every(function (x) { return x.st === 'ok'; })) { if (live) api('POST', '/api/img/open', {}).then(function (j) { toast(j.msg, 4000); }); } else imgBatch(b.items.some(function (x) { return x.st === 'ok'; }) ? { missing: true } : {}); }
    else imgTab('single');
    return;
  }
  if (t.dataset.tier) { imgSet('imgRes', t.dataset.tier); return; }
  if (t.dataset.q) { imgSet('imgQuality', t.dataset.q); return; }
  if (t.dataset.cfg) { imgSet(t.dataset.cfg === 'withdir' ? 'imgWithDir' : 'imgNoText', t.getAttribute('aria-pressed') !== 'true'); return; }
  if (t.dataset.ratio) { IMG.ratio = t.dataset.ratio; imgCmp(); imgGo(); return; }
  if (t.dataset.cnt) { IMG.cnt = +t.dataset.cnt; imgCmp(); imgGo(); return; }
  if (t.id === 'fgTr') { IMG.trans = !IMG.trans; imgCmp(); return; }
  if (t.id === 'fgEdT') { var it0 = imgCur(); if (it0) imgEdit(it0.id, { transparent: !it0.transparent }, true); return; }
  if (act === 'tab') imgTab(t.dataset.tab);
  else if (act === 'pick') imgPick();
  else if (act === 'addref') $('#fgImgs').click();
  else if (act === 'unref') { IMG.refs.splice(+t.dataset.i, 1); imgCmp(); imgGo(); fgPorts(); }
  else if (act === 'pickmd') $('#fgMd').click();
  else if (act === 'paste') imgPaste();
  else if (act === 'sel') { IMG.sel = IMG.sel === id ? null : id; IMG.sig.ed = ''; imgQueue(); fgPorts(); }
  else if (act === 'unsel') { IMG.sel = null; imgQueue(); fgPorts(); }
  else if (act === 'viewi') imgViewItem(id);
  else if (act === 'viewh') imgViewHist(id);
  else if (act === 'hsel') { IMG.hsel = +id; imgHistSel(); }
  else if (act === 'hreload') imgHist(true);
  else if (act === 'again') { var h = (IMG.hist || []).concat(s.recent || []).filter(function (x) { return String(x.id) === id; })[0]; if (h) imgAgain(h); }
  else if (act === 'copy') { var h2 = (IMG.hist || []).filter(function (x) { return String(x.id) === id; })[0]; if (h2 && navigator.clipboard) navigator.clipboard.writeText(h2.prompt).then(function () { toast('提示词复制好了'); }, function () { toast('复制不了'); }); }
  else if (act === 'tpluse') imgTplUse(id);
  else if (act === 'tplsave') imgTplSave();
  else if (!live) toast('演示模式：连上后端才能用');
  else if (act === 'asref') imgUrlToRef('/api/img/hfile/' + id).then(function (r) { IMG.refs.push(r); imgTab('single', true); toast('当参考图了'); }).catch(function (e) { toast(e.message); });
  else if (act === 'hopen') api('POST', '/api/img/open', { hid: +id }).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); });
  else if (act === 'tpldel') {
    if (IMG.delArm !== id) { IMG.delArm = id; imgTpl(); setTimeout(function () { if (IMG.delArm === id) { IMG.delArm = null; imgTpl(); } }, 3000); return; }
    IMG.delArm = null;
    api('DELETE', '/api/img/templates/' + encodeURIComponent(id)).then(function (j) { IMG.st.templates = j.templates; imgTpl(); toast('删掉了'); }).catch(function (e) { toast(e.message); });
  }
  else if (act === 'clear') api('POST', '/api/img/clear', {}).then(function (j) { IMG.st = j; IMG.sel = null; imgSync(); imgLog('◆ 清掉了这份清单（文件夹里的图没动）', 'c'); }).catch(function (e) { toast(e.message); });
  else if (act === 'rerunall') imgBatch({});
  else if (act === 'one') imgBatch({ ids: [id] });
  else if (act === 'open') api('POST', '/api/img/open', IMG.tab === 'single' ? { single: true } : {}).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); });
  else if (act === 'zip') { t.disabled = true; api('POST', '/api/img/zip', {}, 60000).then(function (j) { toast(j.msg, 5000); imgLog('◆ ' + esc(j.msg), 'c'); t.disabled = false; }).catch(function (e) { toast(e.message); t.disabled = false; }); }
});
function imgSet(k, v) {
  if (!useLive()) { toast('演示模式：连上后端才能改'); return; }
  var o = {}; o[k] = v;
  api('PUT', '/api/settings', o).then(imgLoad).then(function () { IMG.sig.par = ''; imgSync(); if (IMG.tab === 'single') imgCmp(); }).catch(function (e) { toast(e.message); });
}
document.addEventListener('click', function (ev) {   /* 弹出的那一层在 body 上 */
  var t = ev.target.closest('#fgBox [data-act]'); if (!t || t.disabled) return;
  var act = t.dataset.act, id = t.dataset.id;
  if (act === 'boxclose') imgBoxClose();
  else if (act === 'pasteok') { var v = ($('#fgPaste') || {}).value || ''; if (!v.trim()) { toast('先把清单粘贴进来'); return; } imgLoadMd(v, ''); }
  else if (act === 'one') { imgBoxClose(); imgBatch({ ids: [id] }); }
  else if (act === 'vend') { IMG.vend = t.dataset.v; imgPickDraw(); }
  else if (act === 'usem') imgUseModel(id);
  else if (act === 'mid') { var mv = ($('#fgMid').value || '').trim(); if (!/^[\w.\-:/]{2,80}$/.test(mv)) { toast('模型 ID 只能有字母、数字和 - _ . : /'); return; } imgUseModel(mv); }
  else if (act === 'mrefresh') {
    if (!useLive()) { toast('演示模式'); return; }
    t.disabled = true; t.textContent = '正在问 API易…';
    api('POST', '/api/img/models/refresh', {}, 30000).then(function (j) { IMG.cat = j; imgPickDraw(); toast('拉好了：你的 Key 能用 ' + j.n + ' 个生图模型'); imgLog('◆ 拉了一遍模型列表：' + j.n + ' 个生图模型', 'c'); })
      .catch(function (e) { toast(e.message, 6000); }).then(function () { var b = $('#fgMr'); if (b) { b.disabled = false; b.textContent = '刷新模型列表'; } });
  }
  else if (act === 'again') { var h = (IMG.st.recent || []).concat(IMG.hist || []).filter(function (x) { return String(x.id) === id; })[0]; imgBoxClose(); if (h) imgAgain(h); }
  else if (act === 'asref' || act === 'asrefi') {
    if (!useLive()) { toast('演示模式'); return; }
    imgUrlToRef(act === 'asref' ? '/api/img/hfile/' + id : '/api/img/file/' + encodeURIComponent(id) + '?v=' + Date.now()).then(function (r) { IMG.refs.push(r); imgBoxClose(); imgTab('single', true); toast('当参考图了'); }).catch(function (e) { toast(e.message); });
  }
  else if (act === 'hopen') api('POST', '/api/img/open', { hid: +id }).then(function (j) { toast(j.msg, 4000); });
  else if (act === 'open') api('POST', '/api/img/open', {}).then(function (j) { toast(j.msg, 4000); });
  else if (act === 'tplok') {
    var name = ($('#fgTn').value || '').trim(); if (!name) { toast('起个名字'); return; }
    if (!useLive()) { toast('演示模式'); return; }
    var p = ($('#fgPrompt') ? $('#fgPrompt').value : IMG.prompt).trim(), cf = IMG.st.cfg;
    api('POST', '/api/img/templates', { name: name, prompt: p, ratio: IMG.ratio, n: IMG.cnt, transparent: IMG.trans, model: cf.model, tier: cf.tier, quality: cf.quality, refs: IMG.refs.map(function (r) { return r.url; }) }, 30000)
      .then(function (j) { IMG.st.templates = j.templates; IMG.sig.tpl = ''; imgBoxClose(); imgCmp(); toast('存好了：模板「' + name + '」'); imgLog('◆ 存了模板「' + esc(name) + '」', 'c'); }).catch(function (e) { toast(e.message); });
  }
});
document.addEventListener('keydown', function (ev) {
  if (ev.key === 'Escape' && $('#fgBox')) { imgBoxClose(); ev.stopPropagation(); return; }
  if (ev.key === 'Enter' && $('#fgBox') && ev.target.id === 'fgTn') { ev.preventDefault(); var b = $('#fgBox [data-act="tplok"]'); if (b) b.click(); }
}, true);
$('#view-img').addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey) && ev.target.id === 'fgPrompt') { ev.preventDefault(); imgGen(); } });
$('#view-img').addEventListener('change', function (ev) {
  var t = ev.target;
  if (t.id === 'fgMd') { imgReadMd(t.files[0]); t.value = ''; }
  else if (t.id === 'fgImgs') { imgAddFiles(t.files); t.value = ''; }
  else if (t.id === 'fgEdR') { var it = imgCur(); if (it) imgEdit(it.id, { ratio: t.value }, true); }
  else if (t.id === 'fgTpl') { if (t.value) imgTplUse(t.value); t.value = ''; }
});
$('#view-img').addEventListener('input', function (ev) {
  var t = ev.target;
  if (t.id === 'fgPrompt') IMG.prompt = t.value;
  else if (t.id === 'fgEdPr') { var it = imgCur(); if (it) imgEdit(it.id, { prompt: t.value }); }
  else if (t.id === 'fgHq') { clearTimeout(IMG.hqT); IMG.hqT = setTimeout(function () { IMG.hq = t.value.trim(); imgHist(true); }, 400); }
});
$('#view-img').addEventListener('mouseover', function (ev) { var r = ev.target.closest('.fg-r'); FG.hover = r ? [].indexOf.call(r.parentNode.children, r) : -1; });
document.addEventListener('paste', function (ev) {
  if (S.view !== 'img' || $('#fgBox') || !ev.clipboardData) return;
  var fs = [].slice.call(ev.clipboardData.files || []).filter(function (f) { return /^image\//.test(f.type); });
  if (!fs.length) return;
  ev.preventDefault(); imgAddFiles(fs);
});
['dragenter', 'dragover'].forEach(function (k) {
  $('#view-img').addEventListener(k, function (ev) {
    if (!ev.dataTransfer || [].indexOf.call(ev.dataTransfer.types || [], 'Files') < 0) return;
    ev.preventDefault(); var d = $('#fgDrag'); if (d) d.classList.add('on');
  });
});
$('#view-img').addEventListener('dragleave', function (ev) { if (!ev.relatedTarget || !$('#view-img').contains(ev.relatedTarget)) { var d = $('#fgDrag'); if (d) d.classList.remove('on'); } });
$('#view-img').addEventListener('drop', function (ev) {
  var d = $('#fgDrag'); if (d) d.classList.remove('on');
  if (!ev.dataTransfer || !ev.dataTransfer.files.length) return;
  ev.preventDefault();
  var fs = [].slice.call(ev.dataTransfer.files), md = fs.filter(function (f) { return /\.(md|markdown|txt)$/i.test(f.name); })[0], ims = fs.filter(function (f) { return /^image\//.test(f.type); });
  if (md) { if (imgRun()) { toast('正在出图，等这批出完再换清单'); return; } imgReadMd(md); }
  else if (ims.length) imgAddFiles(ims);
  else toast('只认生图清单（.md）和图片（PNG / JPEG / WEBP）');
});
