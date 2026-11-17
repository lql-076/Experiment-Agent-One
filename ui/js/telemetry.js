'use strict';
/* ================= 全链路行为遥测（v3.5）=================
   主窗口和所有工具窗口都加载这一份。
   - UI：点击、开关、快捷键、窗口打开/关闭/缩放（事件委托，不改各页面的代码）
   - trace_id：每次交互生成，随后 fetch 自动带 X-Trace-Id，和后端接口日志串起来
   - 前端异常 / unhandledrejection / 长任务（longtask > 200ms）
   - 音频：所有 <audio> 的 play / waiting / stalled / error / ended
   - 批量：内存队列 500ms 或 15 条；pagehide / 隐藏时 sendBeacon
   不记录输入框里的字、聊天内容、密钥；只记录控件文字/标识、状态和耗时。 */
var TEL = (function () {
  var q = [], timer = null, current = null, curTimer = null, seq = 0;
  var PAGE = { home: '主页', chat: '对话', resident: '常驻', monitor: '后台', settings: '设置', docs: '说明',
    events: '事件', tts: '配音', bgm: '配乐', img: '生图', studio: '视频工坊', publish: '发布', brains: '大脑', reports: '报告', ccode: 'Claude Code' };

  function newTrace() { return 'tr_' + Date.now().toString(36) + '_' + (++seq).toString(36) + Math.random().toString(36).slice(2, 8); }
  function pageName() {
    try { if (typeof S !== 'undefined' && S.view) return PAGE[S.view] || S.view; } catch (e) {}
    try { if (typeof TOOL !== 'undefined' && TOOL) return '工具 · ' + (PAGE[TOOL] || TOOL); } catch (e) {}
    var t = document.documentElement.dataset.tool;
    if (t) return '工具 · ' + (PAGE[t] || t);
    return '主窗口';
  }
  function pageKey() {
    try { if (typeof S !== 'undefined' && S.view) return S.view; } catch (e) {}
    try { if (typeof TOOL !== 'undefined' && TOOL) return TOOL; } catch (e) {}
    return document.documentElement.dataset.tool || 'main';
  }
  function label(el) {
    var s = el.getAttribute('aria-label') || el.getAttribute('title') || (el.innerText || el.value || '').trim();
    return String(s || el.id || el.className || el.tagName).replace(/\s+/g, ' ').slice(0, 60);
  }
  function keyOf(el) {
    for (var i = 0; i < el.attributes.length; i++) {
      var a = el.attributes[i].name;
      if (/^data-(tool|view|action|say|force|engine|log|bgm|archive|out|ev|sec)$/.test(a)) return a + '=' + el.attributes[i].value.slice(0, 50);
    }
    return el.id || '';
  }
  function push(ev) {
    ev.ts = ev.ts || Date.now();
    ev.trace_id = ev.trace_id || newTrace();
    q.push(ev);
    if (q.length >= 15) flush(false);
    else if (!timer) timer = setTimeout(function () { flush(false); }, 500);
  }
  function flush(beacon) {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!q.length) return;
    var body = JSON.stringify({ events: q.splice(0, 200) });
    try {
      if (beacon && navigator.sendBeacon) { navigator.sendBeacon('/api/telemetry/ingest', new Blob([body], { type: 'application/json' })); return; }
      fetch('/api/telemetry/ingest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true }).catch(function () {});
    } catch (e) {}
  }
  function event(cat, action, target, status, dur_ms, metrics, msg, trace) {
    push({ cat: cat, action: action, target: target || '', status: status || 'ok', dur_ms: dur_ms == null ? null : Math.round(dur_ms * 10) / 10,
      metrics: metrics || {}, msg: msg || '', trace_id: trace || current || newTrace() });
  }
  function setTrace(tr, ms) {
    current = tr || newTrace();
    if (curTimer) clearTimeout(curTimer);
    curTimer = setTimeout(function () { current = null; }, ms || 3000);
    return current;
  }

  /* fetch 自动带 X-Trace-Id；网络错误/慢请求记一条 */
  var rawFetch = window.fetch;
  if (rawFetch) {
    window.fetch = function (input, init) {
      var path = '';
      try { path = typeof input === 'string' ? input : (input && input.url) || ''; } catch (e) {}
      var tr = current || newTrace();
      var skip = path.indexOf('/api/telemetry/ingest') >= 0;
      var opts = init || {};
      try {
        var h = new Headers(opts.headers || (typeof input !== 'string' && input.headers) || {});
        if (!h.has('X-Trace-Id')) h.set('X-Trace-Id', tr);
        opts = Object.assign({}, opts, { headers: h });
        if (typeof input !== 'string' && window.Request && input instanceof Request) input = new Request(input, { headers: h });
      } catch (e) {}
      var t0 = performance.now();
      var p = rawFetch.call(window, input, opts);
      if (!skip) {
        p.then(function (r) {
          var ms = performance.now() - t0;
          if ((!r.ok) || ms > 2000) event('api', 'front_' + ((typeof input === 'string' ? 'GET' : input.method || 'GET').toUpperCase()),
            String(path).split('?')[0], r.ok ? 'warn' : 'err', ms, { code: r.status, slow: ms > 2000 }, (r.ok ? '接口慢 ' : '接口出错 ') + String(path).split('?')[0] + ' · ' + Math.round(ms) + 'ms', tr);
        }, function (e) {
          event('api', 'front_error', String(path).split('?')[0], 'err', performance.now() - t0, { error: String(e && e.message || e).slice(0, 200) }, '接口没通：' + String(path).split('?')[0], tr);
        });
      }
      return p;
    };
  }

  /* UI 点击：捕获阶段，先于页面自己的处理 */
  document.addEventListener('click', function (ev) {
    var el = ev.target && ev.target.closest && ev.target.closest('button,a,[data-action],[data-tool],[data-view],[data-force],[data-engine],[data-say],[data-bgm-gen],[data-archive],.btn,.nav');
    if (!el) return;
    var lab = label(el), key = keyOf(el), page = pageName(), pk = pageKey();
    var tr = setTrace(newTrace(), 3000);
    var act = 'click';
    if (el.dataset && el.dataset.tool) act = 'open_tool';
    else if (el.dataset && el.dataset.view) act = 'switch_view';
    else if (el.dataset && el.dataset.say) act = 'read_aloud_click';
    else if (el.dataset && el.dataset.force) act = 'route_select';
    else if (el.dataset && el.dataset.engine) act = 'engine_select';
    else if (el.id === 'cSay') act = 'toggle_auto_speak';
    else if (el.id === 'cCC') act = 'open_claude_workbench';
    else if (el.dataset && el.dataset.archive) act = 'archive_now';
    event('ui', act, page + ' › ' + lab, 'ok', 0, { page: pk, tool: (typeof TOOL !== 'undefined' ? TOOL : ''), key: key, href: el.href ? String(el.href).slice(0, 120) : '' }, '点击「' + lab + '」', tr);
  }, true);

  document.addEventListener('change', function (ev) {
    var el = ev.target;
    if (!el || !/^(checkbox|radio|select|range)$/.test(el.type || (el.tagName === 'SELECT' ? 'select' : ''))) return;
    var lab = label(el), page = pageName();
    var val = el.type === 'checkbox' ? (el.checked ? '开' : '关') : String(el.value || '').slice(0, 60);
    event('ui', 'change', page + ' › ' + lab, 'ok', 0, { page: pageKey(), value: val, key: keyOf(el) }, '切换「' + lab + '」为 ' + val);
  }, true);

  document.addEventListener('keydown', function (ev) {
    var key = '';
    if (ev.ctrlKey && ev.code === 'Space') key = 'Ctrl+Space';
    else if ((ev.ctrlKey || ev.metaKey) && (ev.key === 'k' || ev.key === 'K')) key = 'Ctrl+K';
    else if (ev.altKey && (ev.key === 'v' || ev.key === 'V')) key = 'Alt+V';
    else if (ev.key === 'Escape') key = 'Esc';
    if (!key) return;
    event('ui', 'shortcut', pageName() + ' › ' + key, 'ok', 0, { page: pageKey(), key: key }, '快捷键 ' + key);
  }, true);

  var rz = null;
  window.addEventListener('resize', function () {
    if (rz) clearTimeout(rz);
    rz = setTimeout(function () {
      event('ui', 'window_resize', pageName(), 'ok', 0, { w: innerWidth, h: innerHeight, tool: pageKey() }, '窗口大小 ' + innerWidth + '×' + innerHeight);
    }, 600);
  });
  document.addEventListener('DOMContentLoaded', function () {
    event('ui', 'window_open', pageName(), 'ok', 0, { view: pageKey(), w: innerWidth, h: innerHeight }, '打开「' + pageName() + '」');
  });
  window.addEventListener('pagehide', function () { event('ui', 'window_close', pageName(), 'ok', 0, { view: pageKey() }, '关闭「' + pageName() + '」'); flush(true); });
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') flush(true); });

  window.addEventListener('error', function (ev) {
    event('js', 'error', (ev.filename || '').split('/').pop() || '脚本', 'err', 0,
      { line: ev.lineno || 0, col: ev.colno || 0, error: String(ev.message || '').slice(0, 300) }, '前端异常：' + String(ev.message || '').slice(0, 160));
  });
  window.addEventListener('unhandledrejection', function (ev) {
    var r = ev.reason || {};
    event('js', 'unhandledrejection', 'Promise', 'err', 0, { error: String(r.message || r).slice(0, 300) }, '未处理的 Promise 异常：' + String(r.message || r).slice(0, 160));
  });

  if (window.PerformanceObserver) {
    try {
      new PerformanceObserver(function (list) {
        list.getEntries().forEach(function (e) {
          if (e.duration > 200) event('ui', 'longtask', pageName(), e.duration > 1000 ? 'warn' : 'ok', e.duration,
            { name: e.name, attribution: (e.attribution || []).map(function (a) { return a.name || a.containerType || ''; }).slice(0, 3) },
            '长任务 ' + Math.round(e.duration) + 'ms');
        });
      }).observe({ entryTypes: ['longtask'] });
    } catch (e) {}
  }

  /* 所有 <audio>：缓冲卡顿 / 报错 / 播放结束 */
  ['play', 'waiting', 'stalled', 'error', 'ended'].forEach(function (name) {
    document.addEventListener(name, function (ev) {
      var a = ev.target;
      if (!a || !a.tagName || a.tagName.toLowerCase() !== 'audio') return;
      var src = String(a.currentSrc || a.src || '').split('/').pop().split('?')[0];
      var st = name === 'waiting' || name === 'stalled' ? 'warn' : name === 'error' ? 'err' : 'ok';
      event('audio', name, src || 'audio', st, 0, { current: +(a.currentTime || 0).toFixed(2), duration: +(a.duration || 0).toFixed(2), readyState: a.readyState, networkState: a.networkState },
        ({ play: '播放', waiting: '缓冲等待', stalled: '卡住', error: '播放出错', ended: '播放完' })[name] + (src ? '：' + src : ''));
    }, true);
  });

  return { newTrace: newTrace, setTrace: setTrace, event: event, flush: flush, get current() { return current; } };
})();
