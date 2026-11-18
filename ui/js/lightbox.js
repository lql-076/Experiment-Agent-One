'use strict';
/* ================= 通用高清灯箱（v3.9.0 / R10）=================
   画布节点产出的 PNG / JPEG / WebP / GIF / SVG、PPT 幻灯片、封面，点一下就在这里看：
   - 滚轮缩放、双击复位、拖动平移；Esc / 点遮罩关闭。
   - 底衬三档：棋盘格（看 Alpha）/ 深色 / 浅色。
   - GIF 原速循环；SVG 用 <img> 内嵌，不执行脚本。
   - 同一节点多张产出时左右切换。
   - 信息栏：真实分辨率、文件大小、GIF 帧数/时长、缓存命中、打开所在文件夹。
   用法：Lightbox.open([{url, name, rel, pid, cache, cacheHit}], 0) */
(function () {
  var LB = window.Lightbox = window.Lightbox || {};
  var S = { items: [], i: 0, open: false, bg: 'checker', scale: 1, x: 0, y: 0, fit: 1, drag: null, seq: 0, info: {} };
  var root = null, stage, frame, imgEl, svgNote, infoBox, counter, prevB, nextB, zoomV, bgBtns = {};

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function fmtSize(n) {
    n = +n || 0;
    return n >= 1 << 20 ? (n / (1 << 20)).toFixed(2) + ' MB' : n >= 1024 ? (n / 1024).toFixed(1) + ' KB' : n + ' B';
  }
  function fmtDur(ms) {
    ms = +ms || 0;
    return (ms / 1000).toFixed(ms >= 10000 ? 0 : 1) + ' 秒';
  }
  function safeName(s) { return String(s || '图片').replace(/[\\/:*?"<>|]/g, '_'); }

  function build() {
    if (root) return;
    root = el('div', 'lb', '');
    root.id = 'lbRoot';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-label', '看大图');
    root.hidden = true;
    root.innerHTML =
      '<div class="lb-mask" data-lb="close"></div>' +
      '<div class="lb-top">' +
        '<div class="lb-name" id="lbName"></div>' +
        '<div class="lb-count" id="lbCount"></div>' +
        '<div class="sp"></div>' +
        '<div class="lb-bgs" role="group" aria-label="底衬">' +
          '<button data-lb-bg="checker" title="棋盘格：看透明通道和抠像">棋盘格</button>' +
          '<button data-lb-bg="dark" title="深色底">深色</button>' +
          '<button data-lb-bg="light" title="浅色底">浅色</button>' +
        '</div>' +
        '<span class="lb-zoom" id="lbZoom">100%</span>' +
        '<button class="lb-x" data-lb="close" title="关闭（Esc）" aria-label="关闭">×</button>' +
      '</div>' +
      '<div class="lb-stage" id="lbStage">' +
        '<button class="lb-nav prev" data-lb="prev" title="上一张（←）" aria-label="上一张">‹</button>' +
        '<div class="lb-frame" id="lbFrame"><img id="lbImg" alt=""></div>' +
        '<div class="lb-svgnote" id="lbSvgNote" hidden>SVG 以图片方式显示，脚本不会执行</div>' +
        '<button class="lb-nav next" data-lb="next" title="下一张（→）" aria-label="下一张">›</button>' +
      '</div>' +
      '<div class="lb-info" id="lbInfo"></div>';
    document.body.appendChild(root);
    stage = root.querySelector('#lbStage');
    frame = root.querySelector('#lbFrame');
    imgEl = root.querySelector('#lbImg');
    svgNote = root.querySelector('#lbSvgNote');
    infoBox = root.querySelector('#lbInfo');
    counter = root.querySelector('#lbCount');
    prevB = root.querySelector('.lb-nav.prev');
    nextB = root.querySelector('.lb-nav.next');
    zoomV = root.querySelector('#lbZoom');
    root.querySelectorAll('[data-lb-bg]').forEach(function (b) { bgBtns[b.getAttribute('data-lb-bg')] = b; });

    root.addEventListener('click', function (ev) {
      var a = ev.target.closest('[data-lb]');
      if (a) {
        var k = a.getAttribute('data-lb');
        if (k === 'close') return close();
        if (k === 'prev') return go(-1);
        if (k === 'next') return go(1);
      }
      var bg = ev.target.closest('[data-lb-bg]');
      if (bg) return setBg(bg.getAttribute('data-lb-bg'));
    });
    imgEl.addEventListener('load', function () { fit(); });
    imgEl.addEventListener('error', function () { infoBox.innerHTML = '<b class="bad">这张图打不开</b>'; });
    stage.addEventListener('wheel', function (ev) {
      ev.preventDefault();
      var r = stage.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
      var wx = (mx - S.x) / S.scale, wy = (my - S.y) / S.scale;
      var f = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
      S.scale = Math.max(.08, Math.min(16, S.scale * f));
      S.x = mx - wx * S.scale; S.y = my - wy * S.scale;
      apply();
    }, { passive: false });
    imgEl.addEventListener('dblclick', function (ev) { ev.preventDefault(); ev.stopPropagation(); fit(); });
    stage.addEventListener('dblclick', function (ev) { ev.preventDefault(); fit(); });
    stage.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0 || ev.target.closest('button')) return;
      S.drag = { x: ev.clientX, y: ev.clientY, ox: S.x, oy: S.y };
      stage.setPointerCapture(ev.pointerId); ev.preventDefault();
    });
    stage.addEventListener('pointermove', function (ev) {
      if (!S.drag) return;
      S.x = S.drag.ox + ev.clientX - S.drag.x;
      S.y = S.drag.oy + ev.clientY - S.drag.y;
      apply();
    });
    function up() { S.drag = null; }
    stage.addEventListener('pointerup', up);
    stage.addEventListener('pointercancel', up);
    document.addEventListener('keydown', onKey);
  }

  function onKey(ev) {
    if (!S.open) return;
    if (ev.key === 'Escape') { ev.preventDefault(); close(); }
    else if (ev.key === 'ArrowLeft') { ev.preventDefault(); go(-1); }
    else if (ev.key === 'ArrowRight') { ev.preventDefault(); go(1); }
    else if (ev.key === '0') { ev.preventDefault(); fit(); }
    else if (ev.key === '+' || ev.key === '=') { ev.preventDefault(); zoom(1.2); }
    else if (ev.key === '-') { ev.preventDefault(); zoom(1 / 1.2); }
  }

  function setBg(k) {
    S.bg = (k === 'dark' || k === 'light') ? k : 'checker';
    root.setAttribute('data-bg', S.bg);
    Object.keys(bgBtns).forEach(function (x) { bgBtns[x].setAttribute('aria-pressed', String(x === S.bg)); });
  }

  function apply() {
    imgEl.style.transform = 'translate(' + S.x + 'px,' + S.y + 'px) scale(' + S.scale + ')';
    zoomV.textContent = Math.round(S.scale * 100) + '%';
  }

  function fit() {
    var vw = stage.clientWidth, vh = stage.clientHeight;
    var nw = imgEl.naturalWidth || (S.info && S.info.w) || 0, nh = imgEl.naturalHeight || (S.info && S.info.h) || 0;
    if (!nw || !nh) { S.scale = 1; S.x = vw / 2; S.y = vh / 2; return apply(); }
    S.fit = Math.max(.02, Math.min(1, Math.min((vw - 80) / nw, (vh - 70) / nh)));
    S.scale = S.fit;
    S.x = (vw - nw * S.scale) / 2;
    S.y = (vh - nh * S.scale) / 2;
    apply();
  }

  function zoom(f) {
    var vw = stage.clientWidth, vh = stage.clientHeight, cx = vw / 2, cy = vh / 2;
    var wx = (cx - S.x) / S.scale, wy = (cy - S.y) / S.scale;
    S.scale = Math.max(.08, Math.min(16, S.scale * f));
    S.x = cx - wx * S.scale; S.y = cy - wy * S.scale;
    apply();
  }

  function urls(it) {
    if (it.url) return it.url;
    if (it.rel) return '/api/studio/asset?pid=' + encodeURIComponent(it.pid || '') + '&path=' + encodeURIComponent(it.rel) + (it.cache ? '&cache=1' : '');
    return '';
  }

  function loadInfo(it, token) {
    infoBox.innerHTML = '<span class="lb-muted">读图片信息……</span>';
    var u = urls(it);
    var infoUrl = '/api/studio/asset/info?pid=' + encodeURIComponent(it.pid || '') + '&path=' + encodeURIComponent(it.rel || '') + (it.cache ? '&cache=1' : '');
    fetch(infoUrl, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('info ' + r.status);
      return r.json();
    }).then(function (j) {
      if (token !== S.seq) return;
      S.info = j;
      var bits = [];
      bits.push('<b>' + (j.w || '?') + ' × ' + (j.h || '?') + ' px</b>');
      bits.push('<span>' + fmtSize(j.size) + '</span>');
      if (j.fmt === 'gif') bits.push('<span>GIF · ' + (j.frames || 0) + ' 帧 · ' + fmtDur(j.duration_ms) + '</span>');
      bits.push('<span class="lb-type">' + String(j.fmt || '').toUpperCase() + '</span>');
      bits.push('<span class="lb-cache ' + (it.cacheHit ? 'ok' : '') + '">' + (it.cacheHit ? '缓存命中（没有重新花钱）' : '本次生成') + '</span>');
      bits.push('<button class="linkbtn" data-reveal="1">打开所在文件夹</button>');
      bits.push('<span class="lb-muted lb-sha">sha256 ' + String(j.sha256 || '').slice(0, 12) + '…</span>');
      infoBox.innerHTML = bits.join('');
      svgNote.hidden = j.fmt !== 'svg';
      imgEl.alt = it.name || j.name || '';
      if (imgEl.complete) fit();
    }).catch(function (e) {
      if (token !== S.seq) return;
      infoBox.innerHTML = '<span class="lb-muted">信息读不出来：' + String(e.message || e) + '</span>';
    });
  }

  function show(i) {
    if (!S.items.length) return;
    S.i = (i + S.items.length) % S.items.length;
    var it = S.items[S.i], token = ++S.seq;
    root.querySelector('#lbName').textContent = it.name || it.rel || '图片';
    counter.textContent = S.items.length > 1 ? (S.i + 1) + ' / ' + S.items.length : '';
    prevB.hidden = nextB.hidden = S.items.length < 2;
    var u = urls(it);
    imgEl.onload = function () { fit(); };
    imgEl.src = u;
    S.scale = 1; S.x = 0; S.y = 0;
    apply();
    setBg(S.bg);
    loadInfo(it, token);
    if (imgEl.complete) fit();
  }

  function go(d) { if (!S.open) return; show(S.i + d); }

  function open(items, index) {
    if (!items || !items.length) return;
    build();
    S.items = items.slice();
    S.open = true;
    root.hidden = false;
    document.body.classList.add('lb-on');
    show(index || 0);
    setTimeout(function () { try { imgEl.focus(); } catch (e) {} }, 30);
  }

  function close() {
    if (!root) return;
    S.open = false;
    root.hidden = true;
    document.body.classList.remove('lb-on');
    imgEl.removeAttribute('src');
  }

  root = null;
  document.addEventListener('click', function (ev) {
    if (!S.open) return;
    var b = ev.target.closest('[data-reveal]');
    if (!b) return;
    var it = S.items[S.i] || {};
    if (typeof api !== 'function') return;
    api('POST', '/api/studio/reveal', { pid: it.pid || '', path: it.rel || '', cache: !!it.cache }, 8000)
      .then(function (j) { if (typeof toast === 'function') toast(j.msg || '打开了', 4000); })
      .catch(function (e) { if (typeof toast === 'function') toast(e.message, 6000); });
  });

  LB.open = open;
  LB.close = close;
  LB.isOpen = function () { return S.open; };
  LB._state = S;
})();
