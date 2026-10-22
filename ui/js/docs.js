'use strict';
/* 「说明」页：docs 文件夹里的操作手册、架构说明（Markdown），加上一张按实时状态上色的架构图。
   文档是后端从 docs 文件夹读的；「自动生成 › 当前结构」每次启动按代码重写，不会过时。 */
var DOCS = { list: null, cur: null, doc: null };
try { DOCS.cur = localStorage.getItem('agentDocs.cur') || null; } catch (e) {}

/* ---------- 一个够用的 Markdown 渲染：标题、段落、列表、表格、代码、引用、链接、粗体 ---------- */
function mdInline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, t, u) {
    if (/^https?:/.test(u)) return '<a href="' + u + '" target="_blank" rel="noopener">' + t + '</a>';
    if (/\.md(#.*)?$/.test(u)) return '<a href="#" data-doclink="' + u + '">' + t + '</a>';
    return t;
  });
  return s;
}
function mdHTML(src) {
  var L = src.replace(/\r/g, '').split('\n'), out = [], i = 0, skipCode = false;
  function list(start) {
    var items = [], kind = null;
    while (i < L.length) {
      var m = L[i].match(/^(\s*)([-*]|\d+\.)\s+(.*)$/);
      if (!m) { if (L[i].trim() === '' && L[i + 1] && /^\s*([-*]|\d+\.)\s+/.test(L[i + 1]) && L[i + 1].match(/^\s*/)[0].length >= start) { i++; continue; } break; }
      var ind = m[1].length;
      if (ind < start) break;
      if (ind > start) { var sub = list(ind); if (items.length) items[items.length - 1] += sub; continue; }
      kind = kind || (/\d/.test(m[2]) ? 'ol' : 'ul');
      items.push(mdInline(m[3])); i++;
      while (i < L.length && /^\s+\S/.test(L[i]) && !/^\s*([-*]|\d+\.)\s+/.test(L[i]) && L[i].match(/^\s*/)[0].length > start) { items[items.length - 1] += ' ' + mdInline(L[i].trim()); i++; }
    }
    return '<' + kind + '>' + items.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</' + kind + '>';
  }
  while (i < L.length) {
    var ln = L[i];
    if (/^\s*$/.test(ln)) { i++; continue; }
    if (/^<!--\s*live:arch\s*-->$/.test(ln.trim())) { out.push('<div class="live-arch" id="liveArch">读取实时状态…</div>'); i++; skipCode = true; continue; }
    if (/^```/.test(ln)) {
      var code = []; i++; while (i < L.length && !/^```/.test(L[i])) code.push(L[i++]); i++;
      if (skipCode) { skipCode = false; continue; }          // 紧跟在实时架构图后面的文字版，是给记事本看的，界面里不重复显示
      out.push('<pre class="md-code">' + esc(code.join('\n')) + '</pre>'); continue;
    }
    skipCode = false;
    var h = ln.match(/^(#{1,4})\s+(.*)$/);
    if (h) { var n = h[1].length; out.push('<h' + n + ' id="' + esc(h[2]) + '">' + mdInline(h[2]) + '</h' + n + '>'); i++; continue; }
    if (/^---+\s*$/.test(ln)) { out.push('<hr>'); i++; continue; }
    if (/^>/.test(ln)) { var q = []; while (i < L.length && /^>/.test(L[i])) q.push(L[i++].replace(/^>\s?/, '')); out.push('<blockquote>' + q.map(mdInline).join('<br>') + '</blockquote>'); continue; }
    if (/^\|/.test(ln)) {
      var rows = []; while (i < L.length && /^\|/.test(L[i])) rows.push(L[i++]);
      var cells = function (r) { return r.replace(/^\|/, '').replace(/\|\s*$/, '').split('|').map(function (c) { return c.trim(); }); };
      var head = cells(rows[0]), body = rows.slice(/^\|\s*:?-+/.test(rows[1] || '') ? 2 : 1);
      out.push('<div class="md-table"><table><thead><tr>' + head.map(function (c) { return '<th>' + mdInline(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
        body.map(function (r) { return '<tr>' + cells(r).map(function (c) { return '<td>' + mdInline(c) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>');
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(ln)) { out.push(list(ln.match(/^\s*/)[0].length)); continue; }
    var p = []; while (i < L.length && L[i].trim() && !/^(#{1,4}\s|```|>|\||---+\s*$|\s*([-*]|\d+\.)\s+)/.test(L[i])) p.push(L[i++].trim());
    if (p.length) out.push('<p>' + p.map(mdInline).join('<br>') + '</p>'); else i++;
  }
  return out.join('');
}

/* ---------- 实时架构图：各部分按现在的状态上色（绿色正常、黄色进行中、红色出错、灰色没在运行） ---------- */
function archSVG(svcs) {
  var st = {}; (svcs || []).forEach(function (s) { st[s.k] = s; });
  var col = function (k) { var s = (st[k] || {}).st; return s === 'ok' ? 'var(--ok)' : s === 'warn' ? 'var(--c-neu)' : s === 'bad' ? 'var(--bad)' : 'var(--text3)'; };
  var N = [
    { id: 'you', x: 500, y: 50, w: 220, t: '你', s: 'QQ 私聊 · 界面输入' },
    { id: 'win', x: 160, y: 175, w: 230, t: '桌面窗口', s: 'app/window.py · WebView2', k: 'backend' },
    { id: 'be', x: 500, y: 175, w: 280, t: '后端 :8765', s: '决策脑 · 安全闸 · 提醒 · 每日差事', k: 'backend', big: true },
    { id: 'qq', x: 840, y: 175, w: 230, t: 'QQ 通道', s: '官方机器人 · WebSocket', k: 'qq' },
    { id: 'lm', x: 130, y: 320, w: 220, t: '本地模型服务 :8090', s: '嵌入 + 底座 + 小脑', k: 'model' },
    { id: 'kev', x: 375, y: 320, w: 200, t: 'Kev :8091', s: '决策脑第二票', k: 'kev' },
    { id: 'hw', x: 615, y: 320, w: 220, t: '硬件监控助手 :8085', s: '传感器 · 游戏帧数', k: 'hw' },
    { id: 'ds', x: 860, y: 320, w: 200, t: 'DeepSeek', s: '云端 · 长对话和难题', k: 'ds' },
    { id: 'db', x: 200, y: 455, w: 250, t: 'data\\', s: '设置 · 数据库 · 日志 · 密钥' },
    { id: 'mem', x: 500, y: 455, w: 250, t: 'memory\\', s: '记忆 · 技能 · 提示词（git）' },
    { id: 'tr', x: 800, y: 455, w: 250, t: 'training\\ · models\\', s: '样本 · 底座 · 小脑' }
  ];
  var by = {}; N.forEach(function (n) { by[n.id] = n; });
  var E = [['you', 'win'], ['you', 'qq'], ['win', 'be'], ['qq', 'be'], ['be', 'lm'], ['be', 'kev'], ['be', 'hw'], ['be', 'ds'], ['be', 'db'], ['be', 'mem'], ['be', 'tr']];
  var h = '<svg viewBox="0 0 1000 510" role="img" aria-label="现在的整体架构">';
  E.forEach(function (e) {
    var a = by[e[0]], b = by[e[1]];
    if (Math.abs(a.y - b.y) < 10) {          // 同一行：从侧边连过去
      var l = a.x < b.x ? a : b, r = a.x < b.x ? b : a;
      h += '<path d="M' + (l.x + l.w / 2) + ' ' + l.y + ' L' + (r.x - r.w / 2) + ' ' + r.y + '" class="la-e"/>';
    } else h += '<path d="M' + a.x + ' ' + (a.y + 26) + ' C' + a.x + ' ' + ((a.y + b.y) / 2) + ' ' + b.x + ' ' + ((a.y + b.y) / 2) + ' ' + b.x + ' ' + (b.y - 26) + '" class="la-e"/>';
  });
  N.forEach(function (n) {
    var c = n.k ? col(n.k) : 'var(--line2)';
    h += '<g class="la-n' + (n.big ? ' big' : '') + '"><rect x="' + (n.x - n.w / 2) + '" y="' + (n.y - 26) + '" width="' + n.w + '" height="52" rx="10" style="stroke:' + (n.k ? c : 'var(--line2)') + '"/>' +
      (n.k ? '<circle cx="' + (n.x - n.w / 2 + 16) + '" cy="' + (n.y - 6) + '" r="5" style="fill:' + c + '"/>' : '') +
      '<text x="' + n.x + '" y="' + (n.y - 2) + '" class="la-t">' + esc(n.t) + '</text><text x="' + n.x + '" y="' + (n.y + 16) + '" class="la-s">' + esc(n.s) + '</text></g>';
  });
  return h + '</svg><div class="la-legend"><span><i style="background:var(--ok)"></i>正常</span><span><i style="background:var(--c-neu)"></i>进行中</span><span><i style="background:var(--bad)"></i>出错</span><span><i style="background:var(--text3)"></i>没在运行</span><span class="cap">颜色是现在的实时状态，和「后台」页一样</span></div>';
}
function fillLiveArch() {
  var el = $('#liveArch'); if (!el) return;
  if (!useLive()) { el.innerHTML = archSVG([]); return; }
  var draw = function () { var e = $('#liveArch'); if (e) e.innerHTML = archSVG((MON.data && MON.data.services) || []); };
  if (MON.data) draw();
  api('GET', '/api/monitor', null, 8000).then(function (j) { MON.data = j; draw(); }).catch(draw);
}

/* ---------- 页面 ---------- */
function docsNav() {
  var groups = {}, order = [];
  (DOCS.list || []).forEach(function (d) { if (!groups[d.group]) { groups[d.group] = []; order.push(d.group); } groups[d.group].push(d); });
  return order.map(function (g) {
    return '<div class="dn-g"><div class="label">' + esc(g) + '</div>' + groups[g].map(function (d) {
      return '<button class="sitem" data-doc="' + esc(d.rel) + '" aria-current="' + (d.rel === DOCS.cur ? 'page' : 'false') + '">' + esc(d.title.replace(/^架构\s*·\s*/, '')) + '</button>';
    }).join('') + '</div>';
  }).join('');
}
function renderDocs() {
  var v = $('#view-docs');
  if (!useLive()) {
    v.innerHTML = '<div class="page"><div class="ph"><h1>说明</h1><span class="sub">操作手册、架构说明</span></div><div class="empty">演示模式读不到说明文档：用 启动.bat 打开 Agent 后这里能看。文档就在 Agent 文件夹的 docs 里，用记事本也能直接打开。</div>' +
      '<div class="hc" style="margin-top:1rem;min-height:0"><div class="hc-h"><span class="label">整体架构（演示）</span></div><div class="live-arch">' + archSVG([]) + '</div></div></div>';
    return;
  }
  v.innerHTML = '<div class="settings docs"><nav class="snav" id="docNav">' + (DOCS.list ? docsNav() : '<div class="cap">读取中…</div>') + '</nav>' +
    '<article class="sbody md" id="docBody">' + (DOCS.doc ? docBodyHTML() : '<div class="cap">读取中…</div>') + '</article></div>';
  if (DOCS.doc) fillLiveArch();
  api('GET', '/api/docs', null, 8000).then(function (j) {
    DOCS.list = j.items || []; DOCS.root = j.root;
    if (!DOCS.cur || !DOCS.list.some(function (d) { return d.rel === DOCS.cur; })) DOCS.cur = (DOCS.list[0] || {}).rel;
    var nav = $('#docNav'); if (nav) nav.innerHTML = docsNav();
    if (!DOCS.doc || DOCS.doc.rel !== DOCS.cur) openDoc(DOCS.cur);
  }).catch(function (e) { var b = $('#docBody'); if (b) b.innerHTML = '<div class="empty">读不了说明文档：' + esc(e.message) + '</div>'; });
}
function docBodyHTML() {
  var d = DOCS.doc, t = new Date(d.mtime * 1000);
  return '<div class="doc-meta cap num">' + esc(d.path) + ' · 改于 ' + (t.getMonth() + 1) + '-' + t.getDate() + ' ' + pad(t.getHours()) + ':' + pad(t.getMinutes()) + '</div>' + mdHTML(d.text);
}
function openDoc(rel, hash) {
  if (!rel) return;
  DOCS.cur = rel; try { localStorage.setItem('agentDocs.cur', rel); } catch (e) {}
  $$('#docNav [data-doc]').forEach(function (b) { b.setAttribute('aria-current', b.dataset.doc === rel ? 'page' : 'false'); });
  api('GET', '/api/docs/' + rel.split('/').map(encodeURIComponent).join('/'), null, 8000).then(function (d) {
    DOCS.doc = d;
    var b = $('#docBody'); if (!b) return;
    b.innerHTML = docBodyHTML(); b.scrollTop = 0;
    fillLiveArch();
    if (hash) { var h = document.getElementById(decodeURIComponent(hash)); if (h) h.scrollIntoView(); }
  }).catch(function (e) { toast('打不开：' + e.message); });
}
$('#view-docs').addEventListener('click', function (ev) {
  var b = ev.target.closest('[data-doc]');
  if (b) { openDoc(b.dataset.doc); return; }
  var a = ev.target.closest('[data-doclink]');
  if (a) {
    ev.preventDefault();
    var href = a.dataset.doclink, hash = href.split('#')[1], file = href.split('#')[0];
    var base = (DOCS.cur || '').split('/').slice(0, -1);
    file.split('/').forEach(function (p) { if (p === '..') base.pop(); else if (p && p !== '.') base.push(p); });
    openDoc(base.join('/'), hash);
  }
});
