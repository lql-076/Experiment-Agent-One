'use strict';
/* ================= 事件 ================= */
function evRow(e) {
  var today = new Date(), md = pad(today.getMonth() + 1) + '-' + pad(today.getDate());
  return '<button class="ev" data-id="' + e.id + '" data-to="' + e.to + '" style="--c:' + ROUTES[e.to].color + '" aria-pressed="' + (e.id === S.selId) + '"><span class="ev-dot"></span>' +
    '<span class="ev-main"><span class="ev-text">' + esc(e.text) + '</span><span class="ev-meta">' + (e.date && e.date !== md ? e.date + ' ' : '') + esc(e.t) + ' · ' + esc(e.src) +
    (e.status === 'queued' ? ' · 排队中' : '') + (e.private ? ' · 隐私' : '') + '</span></span><span class="pill">' + e.s[e.to] + '%</span></button>';
}
function renderEvents() {
  var v = $('#view-events'), list = evs();
  if (S.selId == null || !findEv(S.selId)) S.selId = list.length ? list[0].id : null;
  var filters = [['all', '全部']].concat(ORDER.map(function (k) { return [k, ROUTES[k].name]; }));
  var chat = '<div class="chatbar"><span class="cap" style="flex:1">这里是每件事的完整记录。和它聊天在「对话」页。</span><button class="btn" data-go-chat="1">去对话 →</button></div>';
  v.innerHTML = '<div class="events"><div class="evpane"><div class="pane-head"><span class="label">事件流</span>' + chat + '<div class="filters">' +
      filters.map(function (f) { return '<button class="chip" data-filter="' + f[0] + '" aria-pressed="' + (S.filter === f[0]) + '">' + f[1] + '</button>'; }).join('') +
    '</div></div><div class="evlist" id="evlist">' + (list.length ? list.map(evRow).join('') : '<div class="evempty">还没有事件。<br>去「对话」发一句话，或者用 QQ 给机器人发消息。</div>') + '</div></div>' +
    (list.length ? '<div class="detail" id="detail">' +
      '<div class="swap"><span class="label num" id="dMeta"></span><div class="d-text" id="dText"></div></div>' +
      '<div class="dec"><div class="dwrap" style="width:100%">' + donutHTML(80, 14, 4) + '<div class="dc"><b class="num"><span id="dConf">0</span><small>%</small></b><span id="dRoute"></span></div></div>' +
        '<div class="scores">' + ORDER.map(function (k) {
          return '<div class="sc" id="sc-' + k + '" style="--c:' + ROUTES[k].color + '"><i></i><span>' + ROUTES[k].name + '</span><div class="tr"><div class="fl"></div>' + (k === 'local' ? '<div class="th" id="scTh"></div>' : '') + '</div><b class="num">0%</b></div>';
        }).join('') +
        '<div class="stepper"><span>接手线</span><button class="sbtn" id="thDown" aria-label="降低接手线">−</button><b class="num" id="thVal" style="min-width:2.75rem;text-align:center;color:var(--text)"></b><button class="sbtn" id="thUp" aria-label="提高接手线">+</button><span>本地把握低于它，就交给 DeepSeek</span></div>' +
      '</div></div>' +
      '<div><div class="label" style="margin-bottom:.75rem">处理过程</div><div class="tl" id="dTl"></div></div>' +
      '<div class="cards2 swap"><div class="card"><div class="label">为什么这么判</div><p id="dWhy"></p></div><div class="card"><div class="label">回复和结果</div><div id="dResult" class="bubble md res-md"></div><p class="cap" id="dLog"></p></div></div>' +
      '<div class="fixrow"><span style="color:var(--text2)">判错了？应该交给：</span>' +
        ORDER.map(function (k) { return '<button class="chip" data-fix="' + k + '" aria-pressed="false">' + ROUTES[k].name + '</button>'; }).join('') +
        '<span class="fixed-note" id="fixNote"></span></div>' +
    '</div>' : '<div class="detail"><div class="empty">发一句话试试，比如"每天晚上十点提醒我吃药"或"帮我解释一下什么是 LoRA"。</div></div>') + '</div>';
  applyFilter();
  if (list.length) requestAnimationFrame(function () { showEvent(S.selId, true); syncTh(); });
}
function refreshEventList() {
  var el = $('#evlist'); if (!el) { renderEvents(); return; }
  var list = evs();
  if (!$('#detail') && list.length) { renderEvents(); return; }
  var top = el.scrollTop;
  el.innerHTML = list.map(evRow).join('');
  el.scrollTop = top;
  applyFilter();
  var e = findEv(S.selId); if (e) showEvent(S.selId, true);
}
function applyFilter() {
  $$('#evlist .ev').forEach(function (b) { b.classList.toggle('hide', S.filter !== 'all' && b.dataset.to !== S.filter); });
  $$('[data-filter]').forEach(function (c) { c.setAttribute('aria-pressed', c.dataset.filter === S.filter); });
}
function showEvent(id, first) {
  if (!$('#detail') || !$('#dTl')) return;
  var e = findEv(id); if (!e) return;
  var changed = S.selId !== id; S.selId = id;
  $$('#evlist .ev').forEach(function (b) { b.setAttribute('aria-pressed', +b.dataset.id === id); });
  var fill = function () {
    $('#dMeta').textContent = (e.date ? e.date + ' ' : '') + e.t + ' · ' + e.src + ' · 事件 #' + e.id;
    $('#dText').textContent = e.text; $('#dText').title = e.text;
    $('#dWhy').textContent = e.why; $('#dResult').innerHTML = e.reply ? mdHTML(e.reply) : '<p>' + esc(e.result || '（还没有结果）') + '</p>';
    $('#dLog').textContent = (e.cost ? 'DeepSeek 花费 ¥' + e.cost.toFixed(4) + ' · ' : '') + (e.latency ? '用时 ' + e.latency.toFixed(1) + ' 秒' : '') + (e.teacher ? ' · 老师标签：' + ROUTES[e.teacher].name : '');
  };
  var swaps = $$('#detail .swap');
  if (first || !changed || S.set.motion === 'off') fill();
  else { swaps.forEach(function (s) { s.classList.add('out'); }); setTimeout(function () { fill(); swaps.forEach(function (s) { s.classList.remove('out'); }); }, 170); }
  var steps = e.steps && e.steps.length ? e.steps : [['收到', e.src]];
  $('#dTl').style.gridTemplateColumns = 'repeat(' + steps.length + ',minmax(0,1fr))';
  if (first || changed) $('#dTl').innerHTML = '<div class="tl-line" style="--c:' + ROUTES[e.to].color + ';right:calc(' + (100 / steps.length) + '% - .5rem)"><i></i></div>' + steps.map(function (s, j) { return '<div class="tl-step" style="--i:' + j + ';--c:' + ROUTES[e.to].color + '"><b>' + esc(s[0]) + '</b><span>' + esc(s[1]) + '</span></div>'; }).join('');
  var r = $('#dRoute'); r.textContent = e.to === 'local' ? (e.label || '本地') : ROUTES[e.to].name; r.style.color = ROUTES[e.to].color;
  tweenTo($('#dConf'), e.s[e.to], 0);
  setDonut($('#detail .dec .donut'), ORDER.map(function (k) { return { v: Math.max(e.s[k], .5), color: ROUTES[k].color, w: k === e.to ? 18 : 10, dim: k !== e.to }; }), 3);
  ORDER.forEach(function (k) {
    var row = $('#sc-' + k); row.classList.toggle('win', k === e.to);
    row.querySelector('.fl').style.transform = 'scaleX(' + (e.s[k] / 100) + ')';
    row.querySelector('b').textContent = e.s[k] + '%';
  });
  syncFix();
}
function syncTh() { if (!$('#scTh')) return; $('#scTh').style.left = S.set.take + '%'; $('#thVal').textContent = S.set.take + '%'; }
function curFix() { var e = findEv(S.selId); if (!e) return null; return useLive() ? e.fix : S.fix[e.id]; }
function syncFix() {
  var k = curFix(), n = $('#fixNote'); if (!n) return;
  $$('[data-fix]').forEach(function (c) { c.setAttribute('aria-pressed', c.dataset.fix === k); });
  if (k) { n.textContent = '已记下「' + ROUTES[k].name + '」，成了语义路由的新判例'; n.classList.add('on'); } else n.classList.remove('on');
}
$('#view-events').addEventListener('click', function (ev) {
  var t = ev.target.closest('button'); if (!t) return;
  if (t.dataset.goChat) { goView('chat'); return; }
  if (t.classList.contains('ev')) showEvent(+t.dataset.id);
  else if (t.dataset.filter) { S.filter = t.dataset.filter; applyFilter(); }
  else if (t.dataset.fix) {
    var e = findEv(S.selId), k = t.dataset.fix; if (!e) return;
    var to = curFix() === k ? null : k;
    if (useLive()) {
      api('POST', '/api/events/' + e.id + '/fix', { to: to }).then(function (ne) { Object.assign(e, ne); syncFix(); if (to && to === e.to) toast('选的和原来的判断一样，记为"判得对"'); }).catch(function (er) { toast(er.message); });
    } else { if (to) S.fix[e.id] = to; else delete S.fix[e.id]; syncFix(); if (to && to === e.to) toast('选的和原来的判断一样，记为"判得对"'); }
  }
  else if (t.id === 'thDown') setVal('take', Math.max(5, S.set.take - 5));
  else if (t.id === 'thUp') setVal('take', Math.min(95, S.set.take + 5));
});
