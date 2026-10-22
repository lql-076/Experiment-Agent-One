'use strict';
/* ================= 和后端同步 ================= */
function fetchBrains() { if (!useLive()) return; api('GET', '/api/brains').then(function (b) { var changed = JSON.stringify(b) !== JSON.stringify(D.brains); D.brains = b; if (S.view === 'brains' && !$('#ov').classList.contains('on') && (changed || $('#view-brains .empty'))) renderBrains(); }).catch(function () {}); }
function fetchReport() { if (!useLive()) return; api('GET', '/api/report').then(function (r) { var first = !D.report; D.report = r; if (S.view === 'reports') renderReports(); if (first || S.view === 'home') renderHome(true); }).catch(function () {}); }
var pollBusy = false;
function poll() {
  if (!LIVE || pollBusy) return;
  pollBusy = true;
  api('GET', '/api/state', null, 8000).then(function (st) {
    D.offline = false; D.state = st;
    if (S.set.demo) { syncStatus(); return; }
    var sig = st.events.map(function (e) { return e.id + e.status + (e.fix || ''); }).join(',');
    if (sig !== D.sig.ev) { D.sig.ev = sig; D.events = st.events; if (S.view === 'events') refreshEventList(); }
    var hs = JSON.stringify([st.today, st.next && st.next.id, st.next && st.next.ts, st.asks_pending, st.prep.ready, st.cost_month, st.balance, st.setup, sig.slice(0, 60)]);
    if (hs !== D.sig.home) { D.sig.home = hs; if (S.view === 'home') renderHome(true); else D.homeDirty = true; }
    renderCards(st.cards); syncStatus(); syncBadges(); fillResidentText();
    var cand = st.qq.candidate; if (cand && S.check.qqbind && S.check.qqbind.st === 'miss') { S.check.qqbind = { st: 'wait', d: '收到一条消息「' + cand.text.slice(0, 16) + '」，是你发的就点「是我」', action: 'qq_bind', extra: { openid: cand.openid } }; updatePrepUI('qqbind'); }
  }).catch(function () { D.offline = true; D.state = null; syncStatus(); }).then(function () { pollBusy = false; });
}
function loadServer() {
  return api('GET', '/api/settings', null, 4000).then(function (j) {
    var keepDemo = S.set.demo && stored.liveSeen ? S.set.demo : false;
    S.set = Object.assign({}, DEFAULTS, j.settings, { demo: keepDemo });
    SECRETS = j.secrets || {}; PLACES = j.places || null; DS_MODELS = j.ds_models || null;
    var sf = j.safety || {}; S.safety = sf;
    try { var st = loadStore(); st.liveSeen = true; st.set = S.set; localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {}
  });
}

function renderAll() { renderHome(); renderEvents(); renderBrains(); renderReports(); renderSettings(); renderResident(); syncBadges(); }

/* ================= 启动 ================= */
function start() {
  if (!hasTheme(S.set.theme)) S.set.theme = THEMES[0].id;
  root.dataset.theme = S.set.theme;
  applyLook();
  applyOrient(false);
  syncFull();
  renderAll();
  tickClock();
  startHW();
  requestAnimationFrame(function () { placeInd(true); });
  boot();
  if (S.set.startRes) setMode('resident'); else resetIdle();
  if (LIVE) {
    poll(); fetchReport(); fetchBrains();
    setTimeout(prefetchMonitor, 1500);     // 先拿一次后台数据：第一次点开「后台」不用等
    setInterval(poll, 5000);
    setInterval(function () { if (S.view === 'brains') fetchBrains(); if (S.view === 'reports' || S.view === 'home') fetchReport(); }, 20000);
  }
}
var isHttp = location.protocol === 'http:' || location.protocol === 'https:';
(isHttp ? api('GET', '/api/ping', null, 1500) : Promise.reject())
  .then(function () { LIVE = true; return loadServer(); })
  .catch(function () { if (LIVE) return; LIVE = false; })
  .then(start);
