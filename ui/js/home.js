'use strict';
/* ================= 总览 ================= */
function renderHome(quiet) {
  var v = $('#view-home');
  var sp = todaySplit(), tot = sp.local + sp.neu + sp.ds + sp.cl, localPct = tot ? Math.round(sp.local / tot * 100) : 0, asks = pendingAsks(), rd = readyCount(), bud = budget();
  var n = nextRem(), list = evs().slice(0, 8);
  var bal = bud.total == null ? null : +bud.total, ratio = bal == null ? 0 : (bal + bud.cost > 0 ? bal / (bal + bud.cost) : 0);
  var foot = !bud.key ? '<span>DeepSeek 还没填 Key</span><span style="flex:1"></span><button class="linkbtn" data-go-sec="cloud">去填 →</button>'
    : '<span>DeepSeek 余额 <b class="num" style="color:' + (bud.low ? 'var(--bad)' : 'var(--text)') + '">' + money(bal) + '</b>' + (bud.low ? ' · 快用完了' : '') + '</span>' +
      '<div class="bar1" style="--tc:' + (bud.low ? 'var(--bad)' : 'var(--c-ds)') + '" title="余额 / (余额 + 本月花费)"><i style="transform:scaleX(' + ratio.toFixed(3) + ')"></i></div><span class="num">本月花了 ¥' + (+bud.cost).toFixed(2) + '</span>';
  v.innerHTML = '<div class="page fill' + (quiet ? ' quiet' : '') + '"><div class="bento">' +
    '<div class="hc stag lift" style="grid-area:hero;--i:0"><div class="hc-h"><span class="label">今日分流</span><span class="cap">谁接了今天的活</span></div>' +
      '<div class="hero-body"><div class="dwrap" style="width:min(15rem,100%)">' + donutHTML(78, 18, 4) + '<div class="dc"><b class="big num">' + tot + '<small>件</small></b><span class="cap">' + (tot ? '本地处理 ' + localPct + '%' : '今天还没有事') + '</span></div></div>' +
      '<div class="legend">' + ORDER.map(function (k) { return '<div class="lg" style="--c:' + ROUTES[k].color + '"><i></i><span>' + ROUTES[k].name + '</span><span><b class="num">' + sp[k] + '</b><span class="p">' + (tot ? Math.round(sp[k] / tot * 100) : 0) + '%</span></span></div>'; }).join('') + '</div></div>' +
      '<div class="hero-foot">' + foot + '</div></div>' +
    '<div class="hc stag lift agcard" style="grid-area:agent;--i:1"><div class="hc-h"><span class="label">Agent 状态</span><button class="linkbtn" data-go-view="chat">在对话页看 →</button></div><div class="ag-list">' + agentMiniHTML() + '</div></div>' +
    '<button class="hc stag" data-go-view="reports" style="grid-area:asks;--i:2"><div class="hc-h"><span class="label">等你决定</span><span class="hc-go">去处理 →</span></div><div class="big num" style="' + (asks ? 'color:var(--c-cl)' : '') + '">' + asks + '<small>件</small></div><div class="cap">' + (asks ? '撤销不了的事，要你点头' : '没有待办') + '</div></button>' +
    '<button class="hc stag" data-go-sec="remind" style="grid-area:remind;--i:3"><div class="hc-h"><span class="label">下一个提醒</span><span class="hc-go">管理 →</span></div><div class="kpi-row"><div><div class="big num" id="remAt">' + (n ? esc(n.at) : '--:--') + '</div><div class="cap" style="margin-top:.4rem"><span id="remLeft"></span></div></div><div class="mini-ring">' + donutHTML(80, 14, 1, '', 'remRing') + '</div></div></button>' +
    '<button class="hc stag" data-go-res="1" style="grid-area:hw;--i:5"><div class="hc-h"><span class="label">电脑状态</span><span class="hc-go">进入常驻 →</span></div><div class="hwmini">' +
      '<div class="hwm" style="--tc:var(--h1)"><span class="cap">CPU</span><div class="big num">' + hw('cpu.load') + '<small>%</small></div>' + sparkHTML('cpu', 100) + '</div>' +
      '<div class="hwm" style="--tc:var(--h2)"><span class="cap">GPU<span data-hwtxt="gpu.topTxt"></span></span><div class="big num">' + hw('gpu.load') + '<small>%</small></div>' + sparkHTML('gpu', 100) + '</div>' +
      '<div class="hwm" style="--tc:var(--h5)"><span class="cap">整机（估算）</span><div class="big num">' + hw('sys.power') + '<small>W</small></div>' + sparkHTML('pw', 350) + '</div>' +
    '</div></button>' +
    '<div class="hc stag lift" style="grid-area:recent;--i:6"><div class="hc-h"><span class="label">最近事件</span><button class="linkbtn" data-go-view="events">全部 →</button></div><div class="rec">' +
      (list.length ? list.map(function (e) { return '<button class="rrow" data-open-ev="' + e.id + '" style="--c:' + ROUTES[e.to].color + '"><span class="t">' + esc(e.t) + '</span><span class="x">' + esc(e.text) + '</span><span class="pill">' + ROUTES[e.to].name + ' ' + e.s[e.to] + '%</span></button>'; }).join('')
        : '<div class="cap" style="padding:.75rem .5rem">还没有事件。在 事件 页可以直接发消息试试，或者用 QQ 给它发一句话。</div>') +
    '</div></div>' +
  '</div></div>';
  requestAnimationFrame(function () {
    setDonut($('#view-home .hero-body .donut'), ORDER.map(function (k) { return { v: sp[k] || 0, color: ROUTES[k].color }; }), 4);
    updateReminder(); updatePrepHome(); renderHW();
  });
  $('#mToday').textContent = tot; $('#mLocal').textContent = localPct + '%';
}
function updatePrepHome() {
  var n = readyCount(), tot = LIVE_CHECKS.length, m = missingCount();
  var a = $('#homePrep'); if (a) a.textContent = n;
  var su = useLive() && D.state && D.state.setup;
  var c = $('#homePrepCap'); if (c) c.textContent = su ? '一键补齐中 · 第 ' + su.n + '/' + su.total + ' 步' + (su.pct != null ? ' · ' + Math.round(su.pct) + '%' : '') : S.checking ? '自检中…' : m ? '缺 ' + m + ' 项' : '全部就绪';
  setRing($('#prepRing'), n / tot * 100, m ? 'var(--c-neu)' : 'var(--ok)');
}
$('#view-home').addEventListener('click', function (ev) {
  var t = ev.target.closest('button'); if (!t) return;
  if (t.dataset.goView) goView(t.dataset.goView);
  else if (t.dataset.goSec) { S.sec = t.dataset.goSec; renderSettings(); goView('settings'); }
  else if (t.dataset.goRes) enterResident();
  else if (t.dataset.recheck) { S.sec = 'prep'; renderSettings(); goView('settings'); setTimeout(function () { checkPanel(true); }, 450); }
  else if (t.dataset.openEv !== undefined) { S.selId = +t.dataset.openEv; renderEvents(); goView('events'); }
});
