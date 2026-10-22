'use strict';
/* 树状图：把说明文档里的 mermaid mindmap 段画成从左往右展开的树（「说明」页用）。
   - 点节点：收起 / 展开它下面的；带 go-NN 标记的节点右边有箭头，点了跳到那一篇的图。
   - 带 svc-xxx 标记的节点有一个状态灯，颜色和「后台」页一样（绿正常、黄进行中、红出错、灰没在运行）。
   - 名字像路径的（app/qq.py）用等宽字。
   - 太宽就整体缩小（最小 0.62 倍），再宽就在框里左右滚。
   写法见 docs/AI文档/README.md。 */
var TREES = {}, TREE_N = 0;

function parseMindmap(code) {
  var root = null, stack = [], last = null, id = 0;
  code.replace(/\r/g, '').split('\n').forEach(function (ln) {
    if (!ln.trim() || /^\s*mindmap\s*$/.test(ln) || /^\s*%%/.test(ln)) return;
    var ind = ln.match(/^\s*/)[0].length, s = ln.trim(), cls = [];
    if (/^:::/.test(s)) { if (last) last.cls = last.cls.concat(s.slice(3).trim().split(/\s+/)); return; }
    var m = s.match(/^(.*?):::(.+)$/); if (m) { s = m[1].trim(); cls = m[2].trim().split(/\s+/); }
    var sh = s.match(/^[^\s(\[{)]*?(\(\(|\{\{|\)\)|\(|\[|\))(.+?)(\)\)|\}\}|\(\(|\)|\]|\()$/);
    if (sh) s = sh[2];
    var node = { id: 'n' + (id++), t: s.replace(/^"(.*)"$/, '$1'), cls: cls, kids: [], ind: ind, parent: null };
    while (stack.length && stack[stack.length - 1].ind >= ind) stack.pop();
    if (stack.length) { node.parent = stack[stack.length - 1]; node.parent.kids.push(node); }
    else if (!root) root = node;
    else { node.parent = root; root.kids.push(node); }
    stack.push(node); last = node;
  });
  if (!root) return null;
  (function walk(n, d, b) {
    n.d = d; n.b = d === 1 ? b : (n.parent ? n.parent.b : 0);
    n.svc = (n.cls.filter(function (c) { return /^svc-/.test(c); })[0] || '').slice(4);
    n.go = (n.cls.filter(function (c) { return /^go-\d+$/.test(c); })[0] || '').slice(3);
    n.file = /^[\w.-]+\/[\w./-]*\.\w+$|^[\w.-]+\.(py|js|css|md|bat|json|jsonl)$/.test(n.t);
    n.kids.forEach(function (k, i) { walk(k, d + 1, d === 0 ? i : n.b); });
  })(root, 0, 0);
  return root;
}

/* mdHTML 遇到 mermaid 段时调用：登记一棵树，先放一个空壳，等插进页面后 drawTrees 再画 */
function treeSlot(code) {
  var root = parseMindmap(code); if (!root) return '';
  var key = 't' + (++TREE_N);
  TREES[key] = { root: root, shut: {} };
  return '<div class="tree-wrap" data-tree="' + key + '"><div class="tree-tools"><button class="btn mini" data-tree-all="1">全部展开</button><button class="btn mini" data-tree-top="1">只看第一层</button>' +
    '<span class="cap">点节点收起或展开' + (treeHas(root, 'go') ? '；→ 跳到那一篇' : '') + (treeHas(root, 'svc') ? '；亮灯的是实时状态' : '') + '</span></div>' +
    '<div class="tree-box"><div class="tree-size"><div class="tree"></div></div></div></div>';
}
function treeHas(n, k) { return !!n[k] || n.kids.some(function (c) { return treeHas(c, k); }); }
function treeEach(n, fn) { fn(n); n.kids.forEach(function (k) { treeEach(k, fn); }); }

function drawTrees(scope) {
  $$('.tree-wrap[data-tree]', scope).forEach(function (w) {
    var T = TREES[w.dataset.tree]; if (!T || w.dataset.drawn) return;
    w.dataset.drawn = '1';
    var box = w.querySelector('.tree'), h = '<svg class="tree-e" aria-hidden="true"></svg>';
    treeEach(T.root, function (n) {
      h += '<div class="tn d' + Math.min(n.d, 3) + ' b' + (n.b % 5) + (n.kids.length ? ' has' : '') + (n.file ? ' file' : '') + '" data-n="' + n.id + '" style="--dly:' + (n.d * 70) + 'ms">' +
        (n.svc ? '<i class="tn-dot" data-svc="' + esc(n.svc) + '"></i>' : '') + '<span class="tn-t">' + esc(n.t) + '</span>' +
        (n.kids.length ? '<em class="tn-n">' + n.kids.length + '</em>' : '') +
        (n.go ? '<button class="tn-go" data-go-doc="' + n.go + '" title="打开这一篇的图" aria-label="打开这一篇的图">→</button>' : '') + '</div>';
    });
    box.innerHTML = h;
    treeEach(T.root, function (n) { var el = box.querySelector('[data-n="' + n.id + '"]'); n.el = el; n.w = el.offsetWidth; n.h = el.offsetHeight; });
    var paths = '';
    treeEach(T.root, function (n) { if (n.parent) paths += '<path class="b' + (n.b % 5) + '" data-e="' + n.id + '"/>'; });
    box.querySelector('svg').innerHTML = paths;
    treeEach(T.root, function (n) { if (n.parent) n.pe = box.querySelector('[data-e="' + n.id + '"]'); });
    T.wrap = w; T.box = box;
    layoutTree(T, true);
    treeLive();
  });
}

function treeShown(T, n) { for (var p = n.parent; p; p = p.parent) if (T.shut[p.id]) return false; return true; }
/* 排版：从左往右一列一层。地方够宽、第一层分支又多时，分成左右两边（像思维导图），高度差不多减半；
   两边各算各的列宽。哪些分支放左边，第一次排版时定下来，之后收起展开不换边，免得跳来跳去。 */
function layoutTree(T, first) {
  var rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  var gy = 0.45 * rem, gyTop = 1.1 * rem, R = T.root;
  var top = function (n) { var a = n; while (a.d > 1) a = a.parent; return a; };
  var sideOf = function (n) { return n.d === 0 ? 0 : T.left[top(n).id] ? -1 : 1; };
  var cols = function (side, gx) {                      // 这一侧每一层多宽、离根的右边（或左边）多远
    var w = [];
    treeEach(R, function (n) { if (treeShown(T, n) && n.d > 0 && sideOf(n) === side) w[n.d] = Math.max(w[n.d] || 0, n.w); });
    var x = [0, gx]; for (var d = 2; d < w.length; d++) x[d] = x[d - 1] + (w[d - 1] || 0) + gx;
    return { w: w, x: x, reach: w.length > 1 ? x[w.length - 1] + w[w.length - 1] : 0 };
  };
  var avail = T.wrap.querySelector('.tree-box').clientWidth - 2;
  if (first || T.availW !== Math.round(avail)) {
    T.availW = Math.round(avail); T.left = {}; T.gx = 2.75 * rem;
    if (R.kids.length >= 4) {                          // 按高度把第一层分支切成两半：前一半放右边，后一半放左边
      var hs = R.kids.map(function (k) { var h = 0; treeEach(k, function (n) { if (treeShown(T, n) && (!n.kids.length || T.shut[n.id])) h += n.h + gy; }); return h; });
      var tot = hs.reduce(function (a, b) { return a + b; }, 0), acc = 0;
      R.kids.forEach(function (k, i) { if (acc >= tot / 2 && i > 0) T.left[k.id] = true; acc += hs[i]; });
      var g2 = 2.25 * rem, w2 = cols(1, g2).reach + cols(-1, g2).reach + R.w;
      if (w2 * 0.9 <= avail) T.gx = g2; else T.left = {};   // 缩到 0.9 倍还放不下，就还是单边
    }
  }
  var cr = cols(1, T.gx), cl = cols(-1, T.gx);
  var shift = function (n, dy) { n.y += dy; if (!T.shut[n.id]) n.kids.forEach(function (k) { shift(k, dy); }); };
  var place = function (n, y0) {
    if (T.shut[n.id] || !n.kids.length) { n.y = y0; return y0 + n.h; }
    var y = y0;
    n.kids.forEach(function (k, i) { if (i) y += gy; y = place(k, y); });
    var a = n.kids[0], z = n.kids[n.kids.length - 1];
    n.y = (a.y + a.h / 2 + z.y + z.h / 2) / 2 - n.h / 2;
    if (n.y < y0) { var dy = y0 - n.y; n.kids.forEach(function (k) { shift(k, dy); }); n.y = y0; y += dy; }
    return Math.max(y, n.y + n.h);
  };
  var stack = function (kids) {                         // 一侧的分支从上往下排，返回 [第一个中心, 最后一个中心, 总高]
    var y = 0; kids.forEach(function (k, i) { if (i) y += gyTop; y = place(k, y); });
    return kids.length ? [kids[0].y + kids[0].h / 2, kids[kids.length - 1].y + kids[kids.length - 1].h / 2, y] : [0, 0, 0];
  };
  var right = R.kids.filter(function (k) { return !T.left[k.id]; }), left = R.kids.filter(function (k) { return T.left[k.id]; });
  var sr = stack(right), sl = stack(left), H = Math.max(sr[2], sl[2], R.h);
  var ofs = function (kids, s) { var dy = (H - s[2]) / 2; kids.forEach(function (k) { shift(k, dy); }); s[0] += dy; s[1] += dy; };
  ofs(right, sr); ofs(left, sl);
  R.y = (left.length ? (sr[0] + sr[1] + sl[0] + sl[1]) / 4 : (sr[0] + sr[1]) / 2) - R.h / 2;
  if (R.y < 0) { R.kids.forEach(function (k) { shift(k, -R.y); }); H -= R.y; R.y = 0; }
  if (R.y + R.h > H) H = R.y + R.h;
  var rootX = cl.reach, W = rootX + R.w + cr.reach;
  treeEach(R, function (n) {
    n.side = sideOf(n) < 0 ? -1 : 1;
    n.x = n.d === 0 ? rootX : n.side < 0 ? rootX - cl.x[n.d] - n.w : rootX + R.w + cr.x[n.d];      // 左边那一侧靠近根的一端对齐
  });
  treeEach(R, function (n) {
    var vis = treeShown(T, n), a = vis ? n : (function () { var p = n.parent; while (!treeShown(T, p)) p = p.parent; return p; })();
    n.el.classList.toggle('gone', !vis);
    n.el.classList.toggle('shut', !!T.shut[n.id]);
    n.el.classList.toggle('lft', n.side < 0);
    n.el.style.transform = 'translate(' + Math.round(vis ? n.x : a.x + (a.w - n.w) / 2) + 'px,' + Math.round(vis ? n.y : a.y + (a.h - n.h) / 2) + 'px)';
    if (n.pe) {
      var p = n.parent, s = n.side;
      var x1 = s > 0 ? p.x + p.w : p.x, y1 = p.y + p.h / 2, x2 = vis ? (s > 0 ? n.x : n.x + n.w) : x1, y2 = vis ? n.y + n.h / 2 : y1;
      if (!treeShown(T, p)) { x1 = x2 = s > 0 ? a.x + a.w : a.x; y1 = y2 = a.y + a.h / 2; }
      var mx = (x1 + x2) / 2;
      var dd = 'M' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' C' + mx.toFixed(1) + ' ' + y1.toFixed(1) + ' ' + mx.toFixed(1) + ' ' + y2.toFixed(1) + ' ' + x2.toFixed(1) + ' ' + y2.toFixed(1);
      n.pe.setAttribute('d', dd); n.pe.style.d = 'path("' + dd + '")';      // 用 CSS 的 d 属性，收起展开时线条跟着动
      n.pe.classList.toggle('gone', !vis);
    }
  });
  var box = T.box, svg = box.querySelector('svg');
  box.style.width = W + 'px'; box.style.height = H + 'px';
  svg.setAttribute('width', W); svg.setAttribute('height', H); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  T.W = W; T.H = H;
  treeFit(T);
  if (first) { T.wrap.classList.add('in'); setTimeout(function () { T.wrap.classList.add('settled'); }, 1400); }
}
function treeFit(T) {
  var avail = T.wrap.querySelector('.tree-box').clientWidth - 2;
  var s = T.W > avail ? Math.max(0.62, avail / T.W) : 1;
  T.box.style.transform = s < 1 ? 'scale(' + s.toFixed(3) + ')' : '';
  var sz = T.wrap.querySelector('.tree-size'); sz.style.width = Math.ceil(T.W * s) + 'px'; sz.style.height = Math.ceil(T.H * s) + 'px';
}
function treeOf(el) { var w = el.closest('.tree-wrap'); return w && TREES[w.dataset.tree]; }
function treeFind(T, id) { var hit = null; treeEach(T.root, function (n) { if (n.id === id) hit = n; }); return hit; }

/* 状态灯：用「后台」页同一份数据（/api/monitor 的 services） */
function treeLive() {
  var svcs = (MON.data && MON.data.services) || [], st = {};
  svcs.forEach(function (s) { st[s.k] = s; });
  $$('.tn-dot[data-svc]').forEach(function (d) {
    var s = st[d.dataset.svc];
    d.className = 'tn-dot ' + (s ? (s.st === 'ok' ? 'ok' : s.st === 'warn' ? 'warn' : s.st === 'bad' ? 'bad' : 'off') : 'off');
    d.title = s ? s.name + '：' + ({ ok: '正常', warn: '进行中', bad: '出错', off: '没在运行' }[s.st] || s.st) + (s.detail ? ' · ' + s.detail : '') : (useLive() ? '读不到状态' : '演示模式没有实时状态');
  });
}

document.addEventListener('click', function (ev) {
  var t = ev.target;
  if (!t.closest || !t.closest('.tree-wrap')) return;
  var T = treeOf(t); if (!T) return;
  if (t.closest('[data-tree-all]')) { T.shut = {}; layoutTree(T); return; }
  if (t.closest('[data-tree-top]')) { T.shut = {}; T.root.kids.forEach(function (k) { if (k.kids.length) T.shut[k.id] = true; }); layoutTree(T); return; }
  if (t.closest('.tn-go')) return;                       // 跳转由 docs.js 处理
  var el = t.closest('.tn.has'); if (!el) return;
  var n = treeFind(T, el.dataset.n); if (!n || !n.parent) return;      // 根不收
  T.shut[n.id] = !T.shut[n.id]; layoutTree(T);
});
/* 鼠标停在节点上：从根到它的那条线亮起来 */
document.addEventListener('pointerover', function (ev) {
  var el = ev.target.closest && ev.target.closest('.tn'); if (!el) return;
  var T = treeOf(el); if (!T) return;
  $$('path.hl', T.box).forEach(function (p) { p.classList.remove('hl'); });
  for (var n = treeFind(T, el.dataset.n); n && n.pe; n = n.parent) n.pe.classList.add('hl');
});
document.addEventListener('pointerout', function (ev) {
  var el = ev.target.closest && ev.target.closest('.tn'); if (!el || (ev.relatedTarget && el.contains(ev.relatedTarget))) return;
  var T = treeOf(el); if (T) $$('path.hl', T.box).forEach(function (p) { p.classList.remove('hl'); });
});
/* 窗口大小变了（界面按窗口等比缩放，节点尺寸也变），重新量一遍再排 */
var treeRT = 0;
window.addEventListener('resize', function () {
  clearTimeout(treeRT);
  treeRT = setTimeout(function () {
    Object.keys(TREES).forEach(function (k) {
      var T = TREES[k]; if (!T.box || !document.body.contains(T.box)) return;
      treeEach(T.root, function (n) { n.w = n.el.offsetWidth; n.h = n.el.offsetHeight; });
      layoutTree(T);
    });
  }, 150);
});
