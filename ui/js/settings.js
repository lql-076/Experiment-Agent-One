'use strict';
/* ================= 设置 ================= */
function secById(id) { return SECTIONS.filter(function (s) { return s.id === id; })[0]; }
function fieldDef(k) { var out = null; SECTIONS.forEach(function (s) { (s.fields || []).forEach(function (f) { if (f.k === k) out = f; }); }); return out; }
function fieldHTML(f) {
  if (f.note) return '<div class="note">' + esc(f.note) + '</div>';
  var id = 'f-' + f.k, v = f.t === 'secret' ? (S.secret[f.k] || '') : S.set[f.k];
  var help = f.h ? '<div class="help">' + esc(f.h) + '</div>' : '';
  switch (f.t) {
    case 'toggle': return '<div class="field row"><div><label for="' + id + '">' + esc(f.l) + '</label>' + help + '</div><button class="switch" role="switch" id="' + id + '" data-k="' + f.k + '" aria-checked="' + !!v + '"></button></div>';
    case 'range': return '<div class="field"><div class="fl"><label for="' + id + '">' + esc(f.l) + '</label><output id="o-' + f.k + '" class="num">' + v + f.u + '</output></div><input type="range" id="' + id + '" data-k="' + f.k + '" min="' + f.min + '" max="' + f.max + '" step="' + f.step + '" value="' + v + '">' + help + '</div>';
    case 'select': return '<div class="field"><label for="' + id + '">' + esc(f.l) + '</label><select class="inp" id="' + id + '" data-k="' + f.k + '">' + f.o.map(function (o) { return '<option value="' + o[0] + '"' + (String(v) === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select>' + help + '</div>';
    case 'secret':
      var hint = SECRETS[f.k];
      return '<div class="field"><label for="' + id + '">' + esc(f.l) + '</label><div class="secret"><input class="inp" type="password" autocomplete="off" spellcheck="false" id="' + id + '" data-secret="' + f.k + '" value="' + esc(v) + '" placeholder="' + (hint ? '已保存 ' + esc(hint) + '（要换就重新填）' : '还没有填') + '"><button class="btn" data-reveal="' + id + '" aria-label="显示或隐藏">' + ICONS.eye + '</button>' +
        (LIVE ? '<button class="btn primary" data-secret-save="' + f.k + '">保存</button>' + (hint ? '<button class="btn" data-secret-clear="' + f.k + '">清除</button>' : '') : '') + '</div>' + help + (LIVE ? '' : '<div class="help">演示模式不保存密钥</div>') + '</div>';
    case 'model':
      var ml = (DS_MODELS && DS_MODELS.models) || [], box;
      if (ml.length && !DS_MANUAL) {
        var opts = ml.slice(); if (v && opts.indexOf(v) < 0) opts.unshift(v);
        box = '<select class="inp" id="' + id + '" data-k="' + f.k + '">' + opts.map(function (m) { return '<option value="' + esc(m) + '"' + (m === v ? ' selected' : '') + '>' + esc(m) + (ml.indexOf(m) < 0 ? '（现在用的，不在列表里）' : '') + '</option>'; }).join('') + '<option value="__manual">手动填写…</option></select>';
      } else box = '<input class="inp" spellcheck="false" id="' + id + '" data-k="' + f.k + '" value="' + esc(v) + '" placeholder="模型名，例如 deepseek-chat">';
      var when = DS_MODELS && DS_MODELS.ts ? new Date(DS_MODELS.ts * 1000) : null;
      return '<div class="field"><label for="' + id + '">' + esc(f.l) + '</label><div class="secret">' + box + '<button class="btn" data-fetch-models>' + (ml.length ? '刷新列表' : '获取模型列表') + '</button></div>' +
        '<div class="help">' + (ml.length ? '用你的 Key 查到 ' + ml.length + ' 个模型（' + pad(when.getMonth() + 1) + '-' + pad(when.getDate()) + ' ' + pad(when.getHours()) + ':' + pad(when.getMinutes()) + '）。官方出了新模型，点「刷新列表」就有' + (DS_MANUAL ? '；现在是手动填写，点「刷新列表」回到下拉框' : '') : esc(f.h)) + '</div></div>';
    case 'textarea': return '<div class="field"><label for="' + id + '">' + esc(f.l) + '</label><textarea class="inp" id="' + id + '" data-k="' + f.k + '">' + esc(v) + '</textarea>' + help + '</div>';
    case 'number': return '<div class="field"><div class="fl"><label for="' + id + '">' + esc(f.l) + '</label><span class="help">' + (f.u || '') + '</span></div><input class="inp num" type="number" min="0" step="any" id="' + id + '" data-k="' + f.k + '" value="' + esc(v) + '">' + help + '</div>';
    case 'time': return '<div class="field"><label for="' + id + '">' + esc(f.l) + '</label><input class="inp num" type="time" id="' + id + '" data-k="' + f.k + '" value="' + esc(v) + '">' + help + '</div>';
    default:
      var ph = f.place ? '留空 = ' + P(f.place) : (f.ph || '');
      return '<div class="field"><label for="' + id + '">' + esc(f.l) + '</label><input class="inp" spellcheck="false" id="' + id + '" data-k="' + f.k + '" placeholder="' + esc(ph) + '" value="' + esc(v) + '">' + help + '</div>';
  }
}
function remList() { return useLive() ? D.reminders : DEMO_REM; }
var KIND_NAME = { daily: '每天', interval: '每隔', once: '一次' }, DAY = '一二三四五六日';
function remRow(r) {
  var once = r.once_ts ? new Date(r.once_ts * 1000) : new Date(Date.now() + 3600e3);
  var onceV = once.getFullYear() + '-' + pad(once.getMonth() + 1) + '-' + pad(once.getDate()) + 'T' + pad(once.getHours()) + ':' + pad(once.getMinutes());
  return '<div class="rem" data-rid="' + r.id + '"><button class="switch" role="switch" data-rem-on aria-checked="' + !!r.enabled + '" aria-label="打开或关闭"></button><div class="col">' +
    '<div class="line"><input class="inp" data-rem="title" value="' + esc(r.title) + '" placeholder="提醒什么"><select class="inp" data-rem="kind">' + ['daily', 'interval', 'once'].map(function (k) { return '<option value="' + k + '"' + (r.kind === k ? ' selected' : '') + '>' + KIND_NAME[k] + '</option>'; }).join('') + '</select>' +
      (r.kind === 'daily' ? '<input class="inp num" type="time" data-rem="at" value="' + esc(r.at || '22:00') + '">' : r.kind === 'interval' ? '<input class="inp num" type="number" min="5" data-rem="every_min" value="' + (r.every_min || 90) + '"><span class="help">分钟</span>' : '<input class="inp num" type="datetime-local" data-rem="once" value="' + onceV + '" style="flex:none;width:14rem">') + '</div>' +
    (r.kind === 'daily' ? '<div class="days">' + DAY.split('').map(function (d, i) { return '<button data-day="' + (i + 1) + '" aria-pressed="' + ((r.days || '1234567').indexOf(String(i + 1)) >= 0) + '">' + d + '</button>'; }).join('') + '</div>' : '') +
    '<div class="line"><input class="inp" data-rem="text" value="' + esc(r.text || '') + '" placeholder="提醒时附带的话（会通过 QQ 发出，写你愿意让 QQ 看到的字）"></div>' +
    '<div class="line"><span class="help" style="flex:1">' + (r.next_ts && r.enabled ? '下一次：' + new Date(r.next_ts * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : r.enabled ? '' : '关着') + '</span><button class="btn mini" data-rem-fire>现在试发</button><button class="btn mini danger" data-rem-del>删除</button></div>' +
  '</div></div>';
}
function remHTML() {
  var list = remList();
  return (list.length ? list.map(remRow).join('') : '<div class="cap" style="margin-bottom:1rem">还没有提醒。</div>') + '<div class="btnrow"><button class="btn primary" id="remAdd">新建提醒</button></div>';
}
function sectionBody(sec) {
  var h = '<h2>' + sec.name + '</h2><p class="desc">' + sec.desc + '</p>';
  if (sec.custom === 'prep') return h + prepHTML();
  if (sec.custom === 'remind') return h + '<div class="fields" style="margin-bottom:1.5rem">' + sec.fields.map(fieldHTML).join('') + '</div><div id="remBox">' + remHTML() + '</div>';
  if (sec.custom === 'safety') {
    return h + '<div class="fields">' + SAFETY.map(function (s) {
      var cur = S.safety[s.k] || s.d;
      return '<div class="field row"><div><label>' + esc(s.n) + '</label>' + (s.h ? '<div class="help">' + esc(s.h) + '</div>' : '') + '</div>' +
        (s.lock ? '<span class="lock">' + (s.lockText || '固定先问你') + '</span>' : '<div class="seg" role="group" aria-label="' + esc(s.n) + '"><button data-sf="' + s.k + '" data-v="auto" aria-pressed="' + (cur === 'auto') + '">先斩后奏</button><button data-sf="' + s.k + '" data-v="ask" aria-pressed="' + (cur === 'ask') + '">先问我</button></div>') + '</div>';
    }).join('') + '</div>';
  }
  if (sec.custom === 'data') {
    return h + '<div class="fields">' +
      '<div class="field row"><div><label for="f-demo">显示演示数据</label><div class="help">' + (LIVE ? '看看界面效果用，不影响真实数据' : '没接后端时只能看演示数据') + '</div></div><button class="switch" role="switch" id="f-demo" data-k="demo" aria-checked="' + !!S.set.demo + '"' + (LIVE ? '' : ' disabled') + '></button></div>' +
      '<div class="field"><label>备份设置</label><div class="btnrow"><button class="btn" id="exp">导出为文件</button><label class="btn" style="display:inline-flex;align-items:center" for="imp">从文件导入</label><input type="file" id="imp" accept=".json,application/json" class="sr"></div><div class="help">导出的文件不包含 API Key 和 AppSecret</div></div>' +
      '<div class="field"><label>恢复默认</label><div class="btnrow"><button class="btn danger" id="reset">恢复所有默认设置</button></div><div class="help">不会删除事件、记忆和提醒</div></div>' +
      '<div class="field"><label>文件夹</label><div class="help">数据库和日志：' + esc(P('logs').replace(/[\\/]logs$/, '')) + '<br>记忆文件：' + esc(P('memory')) + '<br>训练样本：' + esc(P('training')) + '</div></div>' +
      '<div class="field"><label>快捷键</label><div class="help">R 进入或退出常驻 · F 全屏或回到窗口 · T 切换风格 · Esc 退出常驻或关闭详情</div></div></div>';
  }
  if (sec.custom === 'look') {
    h += '<div class="label" style="margin-bottom:.75rem">风格 · 点一下实时切换</div><div class="tpick">' + THEMES.map(function (t) {
      return '<button class="tcard" data-theme-pick="' + t.id + '" aria-pressed="' + (S.set.theme === t.id) + '"><span class="tprev" data-theme="' + t.id + '"><i class="tp-bg"></i><i class="tp-ring"></i><i class="tp-time num">21:47</i><i class="tp-bar"></i></span><b>' + esc(t.name) + '</b><span class="tdesc">' + esc(t.desc) + '</span></button>';
    }).join('') + '</div><p class="help" style="margin:-1rem 0 1.75rem">主题都在 ' + esc(P('root')) + '\\ui\\themes 里，一个 .css 文件就是一套。想加新的：复制一个改名、改颜色，刷新界面就会出现在这里。</p>';
  }
  if (sec.custom === 'cloud') h += balanceHTML();
  if (sec.custom === 'growth') h += '<div class="btnrow" style="margin-bottom:1.5rem"><button class="btn" id="nightNow"' + (useLive() ? '' : ' disabled') + '>现在跑一次每日差事</button></div>';
  return h + '<div class="fields">' + sec.fields.map(fieldHTML).join('') + '</div>';
}
function balanceHTML() {
  var b = budget(), t = b.ts ? new Date(b.ts * 1000) : null;
  var sub = !b.key ? '填了 Key 并保存后，这里显示官方查到的余额' : b.err ? '这次没查到：' + esc(b.err) : '官方接口查询' + (t ? ' · ' + pad(t.getHours()) + ':' + pad(t.getMinutes()) : '') + (useLive() ? '' : '（演示）');
  return '<div class="balbox"><div><span class="label">DeepSeek 余额</span><div class="big num" style="margin:.35rem 0;' + (b.low ? 'color:var(--bad)' : '') + '">' + (b.key ? money(b.total) : '—') + '</div>' +
    '<div class="help">' + sub + '<br>本月估计花了 ¥' + (+b.cost).toFixed(2) + '（本机按 token 算的，和官方账单可能差一点）</div></div>' +
    '<div class="btnrow"><button class="btn" id="balRefresh"' + (useLive() && b.key ? '' : ' disabled') + '>刷新</button><a class="btn" style="display:inline-flex;align-items:center;text-decoration:none;color:var(--text)" href="https://platform.deepseek.com/top_up" target="_blank" rel="noopener noreferrer">去充值</a></div></div>';
}
function renderSettings() {
  $('#view-settings').innerHTML = '<div class="settings"><nav class="snav" aria-label="设置分类">' +
    SECTIONS.map(function (s) { return '<button class="sitem" data-sec="' + s.id + '" aria-current="' + (s.id === S.sec) + '">' + s.name + (s.id === 'prep' ? '<em class="num" id="prepMini">' + readyCount() + '/' + LIVE_CHECKS.length + '</em>' : '') + '</button>'; }).join('') +
    '</nav><div class="sbody" id="sbody"></div></div>';
  $('#sbody').innerHTML = sectionBody(secById(S.sec));
  if (S.sec === 'remind') fetchReminders();
  if (S.sec === 'prep') setupPoll();
}
function goSec(id) {
  if (S.sec === id) return;
  S.sec = id; S.resetArm = false;
  $$('.sitem').forEach(function (b) { b.setAttribute('aria-current', b.dataset.sec === id); });
  var b = $('#sbody');
  var fill = function () { b.innerHTML = sectionBody(secById(id)); b.scrollTop = 0; if (id === 'remind') fetchReminders(); if (id === 'prep') setupPoll(); };
  if (S.set.motion === 'off') { fill(); return; }
  b.style.transition = 'opacity .14s ease'; b.style.opacity = '0';
  setTimeout(function () { fill(); replay(b); b.style.opacity = ''; }, 140);
}
var pending = {}, pendT = null;
function pushSet(ch) {
  if (!LIVE) return;
  Object.assign(pending, ch); clearTimeout(pendT);
  pendT = setTimeout(function () { var c = pending; pending = {}; api('PUT', '/api/settings', c).catch(function (e) { toast('设置没存上：' + e.message); }); }, 400);
}
function setVal(k, val) {
  S.set[k] = val; save();
  if (k !== 'demo') pushSet((function () { var o = {}; o[k] = val; return o; })());
  var f = fieldDef(k);
  var o = $('#o-' + k); if (o && f) o.textContent = val + f.u;
  var inp = $('#f-' + k);
  if (inp && inp.type === 'range' && +inp.value !== +val) inp.value = val;
  if (inp && inp.tagName === 'SELECT' && inp.value !== String(val)) inp.value = val;
  if (inp && inp.classList.contains('switch')) inp.setAttribute('aria-checked', !!val);
  if (k === 'take') syncTh();
  if (['bright', 'warmth', 'scale', 'autoScale', 'motion', 'perf', 'demo'].indexOf(k) >= 0) applyLook();
  if (k === 'scale') requestAnimationFrame(function () { placeInd(true); });
  if (k === 'layout') applyOrient(true);
  if (k === 'h24' || k === 'secs') renderClock();
  if (k === 'idleRes') resetIdle();
  if (k === 'hwSource' || k === 'hwInterval' || k === 'demo') startHW();
  if (k === 'sysOther' || k === 'psuEff') { if (!liveHW()) { calcSys(); renderHW(); } }
  if (k === 'dsLow') renderHome(true);
  if (k === 'autoScale') requestAnimationFrame(function () { placeInd(true); });
  if (k === 'uiShell') toast('下次启动 Agent 时生效');
  if (k === 'demo') { cardSig = ''; renderAll(); runChecks(false); if (!val) { fetchReport(); fetchBrains(); poll(); } }
}
function fetchReminders() {
  if (!useLive()) return;
  api('GET', '/api/reminders').then(function (j) { D.reminders = j.items; var box = $('#remBox'); if (box && !box.contains(document.activeElement)) box.innerHTML = remHTML(); });
}
var remT = {};
function remPayload(row) {
  var r = { title: $('[data-rem="title"]', row).value.trim() || '提醒', kind: $('[data-rem="kind"]', row).value, text: $('[data-rem="text"]', row).value, enabled: $('[data-rem-on]', row).getAttribute('aria-checked') === 'true' ? 1 : 0 };
  var at = $('[data-rem="at"]', row), ev = $('[data-rem="every_min"]', row), on = $('[data-rem="once"]', row);
  if (at) r.at = at.value || '22:00';
  if (ev) r.every_min = Math.max(5, +ev.value || 90);
  if (on && on.value) r.once_ts = new Date(on.value).getTime() / 1000;
  var days = $$('.days button', row); if (days.length) r.days = days.filter(function (b) { return b.getAttribute('aria-pressed') === 'true'; }).map(function (b) { return b.dataset.day; }).join('') || '1234567';
  return r;
}
function saveRem(row, rerender) {
  var id = +row.dataset.rid, r = remPayload(row);
  if (!useLive()) { var d = DEMO_REM.filter(function (x) { return x.id === id; })[0]; Object.assign(d, r); if (rerender) $('#remBox').innerHTML = remHTML(); return; }
  clearTimeout(remT[id]);
  remT[id] = setTimeout(function () {
    api('PUT', '/api/reminders/' + id, r).then(function (nr) {
      D.reminders = D.reminders.map(function (x) { return x.id === id ? nr : x; });
      if (rerender) $('#remBox').innerHTML = remHTML();
      poll();
    }).catch(function (e) { toast('没存上：' + e.message); });
  }, rerender ? 0 : 500);
}
var sv = $('#view-settings');
sv.addEventListener('click', function (ev) {
  var t = ev.target.closest('button'); if (!t || t.disabled) return;
  var row = t.closest('.rem');
  if (t.dataset.sec) goSec(t.dataset.sec);
  else if (t.dataset.themePick) { var r = t.getBoundingClientRect(); setTheme(t.dataset.themePick, r.left + r.width / 2, r.top + r.height / 2); }
  else if (row && t.hasAttribute('data-rem-on')) { t.setAttribute('aria-checked', t.getAttribute('aria-checked') !== 'true'); saveRem(row, true); }
  else if (row && t.dataset.day) { t.setAttribute('aria-pressed', t.getAttribute('aria-pressed') !== 'true'); saveRem(row); }
  else if (row && t.hasAttribute('data-rem-fire')) {
    if (!useLive()) { toast('演示模式不能发'); return; }
    api('POST', '/api/reminders/' + row.dataset.rid + '/fire', {}).then(function (j) { toast(Object.keys(j.res).map(function (k) { return ({ qq: 'QQ', toast: '弹窗', card: '卡片' })[k] + '：' + j.res[k].info; }).join('；'), 5000); poll(); }).catch(function (e) { toast(e.message); });
  }
  else if (row && t.hasAttribute('data-rem-del')) {
    if (!t.dataset.arm) { t.dataset.arm = 1; t.textContent = '再点一次删除'; setTimeout(function () { delete t.dataset.arm; t.textContent = '删除'; }, 3000); return; }
    if (!useLive()) { DEMO_REM = DEMO_REM.filter(function (x) { return x.id !== +row.dataset.rid; }); $('#remBox').innerHTML = remHTML(); return; }
    api('DELETE', '/api/reminders/' + row.dataset.rid).then(function () { fetchReminders(); poll(); toast('已删除'); });
  }
  else if (t.id === 'remAdd') {
    var nr = { title: '新提醒', kind: 'daily', at: '21:00', days: '1234567', text: '', enabled: 0 };
    if (!useLive()) { nr.id = Date.now(); DEMO_REM.push(nr); $('#remBox').innerHTML = remHTML(); return; }
    api('POST', '/api/reminders', nr).then(function () { fetchReminders(); });
  }
  else if (t.classList.contains('switch')) setVal(t.dataset.k, t.getAttribute('aria-checked') !== 'true');
  else if (t.dataset.man) {
    var k = t.dataset.man, c = CHECKS.filter(function (x) { return x.k === k; })[0];
    if (S.check[k] && S.check[k].st === 'ok') { toast('自检已经确认就绪，不用手动打勾'); return; }
    if (S.manual[k]) delete S.manual[k]; else S.manual[k] = 1;
    save(); updatePrepUI(k);
    if (S.manual[k]) toast('「' + c.t + '」已手动确认');
  }
  else if (t.dataset.act) {
    var kk = t.dataset.k, body = {};
    if (t.dataset.act === 'qq_bind' && S.check.qqbind && S.check.qqbind.extra) body = S.check.qqbind.extra;
    var old = t.textContent; t.disabled = true; t.textContent = '处理中…';
    api('POST', '/api/actions/' + t.dataset.act, body, 900000).then(function (j) { toast(j.msg || '好了', 5000); })
      .catch(function (e) { toast(e.message, 6000); })
      .then(function () { return api('POST', '/api/checks/' + kk + '/run', {}, 60000).then(function (r) { S.check[kk] = r; updatePrepUI(kk); }).catch(function () { t.disabled = false; t.textContent = old; }); });
  }
  else if (t.dataset.diag) {
    var dk = t.dataset.diag, box = $('#diag-' + dk); t.disabled = true; t.textContent = '在问…';
    api('POST', '/api/actions/diagnose', { k: dk }, 120000).then(function (j) { box.hidden = false; box.textContent = j.msg; })
      .catch(function (e) { box.hidden = false; box.textContent = '没问成：' + e.message; }).then(function () { t.disabled = false; t.textContent = '问 DeepSeek 怎么修'; });
  }
  else if (t.dataset.copy) copyText(t.dataset.copy);
  else if (t.id === 'balRefresh') {
    t.disabled = true; t.textContent = '在查…';
    api('POST', '/api/actions/ds_balance', {}).then(function (j) { toast(j.msg); poll(); }).catch(function (e) { toast(e.message); })
      .then(function () { setTimeout(function () { if (S.sec === 'cloud') $('#sbody').innerHTML = sectionBody(secById('cloud')); }, 900); });
  }

  else if (t.id === 'setupGo') setupStart(t);
  else if (t.id === 'setupStop') setupStop();
  else if (t.id === 'recheck') checkPanel(true);
  else if (t.id === 'nightNow') { t.disabled = true; t.textContent = '在跑…'; api('POST', '/api/actions/nightly_run', {}, 600000).then(function (j) { var e = j.res.errs || {}; toast(Object.keys(e).length ? '跑完了，有问题：' + Object.values(e).join('；') : '每日差事跑完了', 6000); }).catch(function (e) { toast(e.message); }).then(function () { t.disabled = false; t.textContent = '现在跑一次每日差事'; }); }
  else if (t.dataset.go) goSec(t.dataset.go);
  else if (t.dataset.reveal) { var i = $('#' + t.dataset.reveal); i.type = i.type === 'password' ? 'text' : 'password'; }
  else if (t.hasAttribute('data-fetch-models')) {
    var redraw = function () { $('#sbody').innerHTML = sectionBody(secById(S.sec)); };
    if (!useLive()) { DS_MODELS = { ts: Date.now() / 1000, models: ['deepseek-chat', 'deepseek-reasoner'] }; DS_MANUAL = false; redraw(); toast('演示模式：假装查到 2 个模型'); return; }
    var typed = (($('#f-dsKey') || {}).value || '').trim();
    t.disabled = true; t.textContent = '查询中…';
    // 刚填的 Key 还没点保存：先帮你存上；接口地址也先存好，再去问官方
    (typed ? api('PUT', '/api/secrets', { k: 'dsKey', v: typed }).then(function (j) { SECRETS = j.hints; S.secret.dsKey = ''; }) : Promise.resolve())
      .then(function () { return api('PUT', '/api/settings', { dsBase: S.set.dsBase }); })
      .then(function () { return api('POST', '/api/actions/ds_models', {}, 20000); })
      .then(function (j) { DS_MODELS = j.ds_models; DS_MANUAL = false; redraw(); toast(j.msg, 5000); })
      .catch(function (e) { t.disabled = false; t.textContent = (DS_MODELS ? '刷新列表' : '获取模型列表'); toast(e.message, 6000); });
  }
  else if (t.dataset.secretSave || t.dataset.secretClear) {
    var sk = t.dataset.secretSave || t.dataset.secretClear, val = t.dataset.secretSave ? ($('#f-' + sk).value || '').trim() : '';
    if (t.dataset.secretSave && !val) { toast('先填上再保存'); return; }
    api('PUT', '/api/secrets', { k: sk, v: val }).then(function (j) {
      SECRETS = j.hints; S.secret[sk] = ''; $('#sbody').innerHTML = sectionBody(secById(S.sec)); toast(val ? '已加密保存' : '已清除'); setTimeout(function () { runChecks(false); }, 1500);
      // 存好 DeepSeek Key：顺手查一次这个 Key 能用哪些模型，模型那一栏就变成下拉框
      if (sk === 'dsKey' && val) api('POST', '/api/actions/ds_models', {}, 20000).then(function (r) { DS_MODELS = r.ds_models; DS_MANUAL = false; if (S.sec === 'cloud') $('#sbody').innerHTML = sectionBody(secById(S.sec)); toast('已加密保存 · ' + r.msg, 5000); }).catch(function () {});
    }).catch(function (e) { toast(e.message); });
  }
  else if (t.dataset.sf) {
    var g = t.dataset.sf, v = t.dataset.v;
    var apply = function () { S.safety[g] = v; save(); $$('[data-sf="' + g + '"]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.v === v); }); toast(v === 'ask' ? '改为：先问你' : '改为：先斩后奏，事后写进报告'); };
    if (LIVE) api('POST', '/api/safety', { group: g, value: v }).then(apply).catch(function (e) { toast(e.message); }); else apply();
  }
  else if (t.id === 'exp') {
    var dl = function (obj) {
      var blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
      var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'agent-设置备份.json'; document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500); toast('已导出');
    };
    if (LIVE) api('GET', '/api/export').then(dl).catch(function (e) { toast(e.message); });
    else dl({ app: 'agent-shell', v: 3, set: S.set, manual: S.manual, safety: S.safety });
  }
  else if (t.id === 'reset') {
    if (!S.resetArm) { S.resetArm = true; t.textContent = '再点一次确认'; setTimeout(function () { S.resetArm = false; var r2 = $('#reset'); if (r2) r2.textContent = '恢复所有默认设置'; }, 4000); }
    else {
      S.resetArm = false; var keepDemo = LIVE ? false : true;
      S.set = Object.assign({}, DEFAULTS, { demo: keepDemo }); S.manual = {}; S.safety = {}; save();
      if (LIVE) { var c2 = Object.assign({}, DEFAULTS); delete c2.demo; api('PUT', '/api/settings', c2); ['brain', 'skill', 'cron', 'prompt'].forEach(function (g) { api('POST', '/api/safety', { group: g, value: 'auto' }); }); }
      root.dataset.theme = S.set.theme; applyLook(); applyOrient(true); renderAll(); startHW(); toast('已恢复默认');
    }
  }
});
sv.addEventListener('toggle', function (ev) { var d = ev.target; if (d.classList && d.classList.contains('su-more')) prepOpen[d.dataset.k] = d.open; }, true);
sv.addEventListener('input', function (ev) {
  var t = ev.target;
  if (t.closest('.rem')) { if (t.tagName !== 'SELECT' && t.type !== 'datetime-local') saveRem(t.closest('.rem')); return; }
  if (t.dataset.secret) { S.secret[t.dataset.secret] = t.value; return; }
  if (!t.dataset.k || t.tagName === 'SELECT') return;
  if (t.type === 'range') setVal(t.dataset.k, parseFloat(t.value));
  else if (t.type === 'number') setVal(t.dataset.k, t.value === '' ? '' : parseFloat(t.value));
  else setVal(t.dataset.k, t.value);
});
sv.addEventListener('change', function (ev) {
  var t = ev.target;
  if (t.closest('.rem')) { if (t.tagName === 'SELECT' || t.type === 'datetime-local') saveRem(t.closest('.rem'), t.tagName === 'SELECT'); return; }
  if (t.tagName === 'SELECT' && t.dataset.k === 'dsModel' && t.value === '__manual') { DS_MANUAL = true; $('#sbody').innerHTML = sectionBody(secById(S.sec)); var mi = $('#f-dsModel'); if (mi) { mi.focus(); mi.select(); } return; }
  if (t.tagName === 'SELECT' && t.dataset.k) setVal(t.dataset.k, t.value);
  if (t.id === 'imp' && t.files && t.files[0]) {
    var r = new FileReader();
    r.onload = function () {
      try {
        var d = JSON.parse(r.result); if (!d || d.app !== 'agent-shell') throw new Error('bad');
        if (LIVE) { api('POST', '/api/import', d).then(function () { return loadServer(); }).then(function () { renderAll(); toast('已导入'); }).catch(function (e) { toast(e.message); }); return; }
        S.set = Object.assign({}, DEFAULTS, d.set || {}); S.manual = d.manual || {}; S.safety = d.safety || {}; save();
        root.dataset.theme = S.set.theme; applyLook(); applyOrient(true); renderAll(); startHW(); toast('已导入');
      } catch (e) { toast('这个文件不是本界面导出的设置'); }
    };
    r.readAsText(t.files[0]);
  }
});
