'use strict';
/* ================= 设置 › Obsidian 笔记（后端 app/obsidian.py） =================
   几个库：名字、路径、只读（E 盘锁死只读）、私人文件夹（点文件夹名切换，私人的只给本地小脑）。
   下面是：加一个库、重新扫一遍 / 全部重建索引 / 现在整理一次、记忆搬进库里、上次整理的结果。 */
var OBS = { st: null, add: { path: '', name: '', ro: false, chk: null }, busy: '', msg: '' };
var OBS_DEMO = { on: true, inbox: 'Agent 收件箱', inboxVault: '资料库', memIn: '', memDir: 'D:\\Agent\\memory', embedOn: true, scan: { ts: Date.now() / 1000 },
  tidy: { ts: Date.now() / 1000 - 3600 * 5, links: [{ from: '元素体系', to: '主角' }], conflicts: [{ a: '小说库/人物/主角.md', b: '小说库/大纲/第二卷.md', why: '主角的等级一处写三阶、一处写四阶' }], checked: 12 },
  vaults: [
    { id: 'novel', name: '小说库', path: 'E:\\Notes\\小说库', ro: true, roDrive: true, exists: true, notes: 120, privNotes: 0, chunks: 1300, waiting: 0, private: [], folders: ['世界观', '人物', '大纲', '灵感'] },
    { id: 'data', name: '资料库', path: 'D:\\Notes\\资料库', ro: false, roDrive: false, exists: true, notes: 30, privNotes: 6, chunks: 210, waiting: 0, private: ['日记'], folders: ['日记', '计划', '收藏'] }] };
function obsSt() { return useLive() ? OBS.st : OBS_DEMO; }
function obsLoad() {
  if (!useLive()) { obsRender(); return Promise.resolve(); }
  return api('GET', '/api/obsidian', null, 15000).then(function (j) { OBS.st = j; obsRender(); }, function () {});
}
function obsRender() { var b = $('#obsBox'); if (b) b.innerHTML = obsInner(); }
function obsHTML() { if (useLive() && !OBS.st) setTimeout(obsLoad, 0); return '<div id="obsBox">' + obsInner() + '</div>'; }

function obsVaultCard(v) {
  var stat = !v.exists ? '<b style="color:var(--bad)">找不到这个文件夹</b>' :
    v.notes + ' 篇' + (v.privNotes ? ' · 私人 ' + v.privNotes + ' 篇只在本地' : '') + ' · ' + (v.waiting ? '还有 ' + v.waiting + ' 段等嵌入模型算向量（先按字面找）' : v.chunks + ' 段都能找');
  var extra = v.private.filter(function (p) { return v.folders.indexOf(p) < 0; });
  return '<div class="obs-card' + (v.ro ? ' ro' : '') + '" data-vid="' + esc(v.id) + '">' +
    '<div class="obs-top"><input class="inp obs-name" data-obs-name="' + esc(v.id) + '" value="' + esc(v.name) + '" aria-label="库的名字">' +
      '<span class="obs-tag ' + (v.ro ? 'ro' : 'rw') + '">' + (v.ro ? '只读' : '能写收件箱') + '</span></div>' +
    '<input class="inp mono" data-obs-path="' + esc(v.id) + '" value="' + esc(v.path) + '" spellcheck="false" aria-label="库的路径">' +
    '<div class="help">' + stat + '</div>' +
    '<div class="field row obs-ro"><div><label>只读（一个字都不写）</label><div class="help">' + (v.roDrive ? 'E 盘的库锁死只读' : '关掉后「Agent 收件箱」会放在这个库里') + '</div></div>' +
      '<button class="switch" role="switch" data-obs="ro" data-vid="' + esc(v.id) + '" aria-checked="' + v.ro + '"' + (v.roDrive ? ' disabled' : '') + ' aria-label="只读"></button></div>' +
    '<div class="label" style="margin:.5rem 0 .4rem">私人文件夹 · 点一下切换（私人的只给本地小脑，不发出本机）</div>' +
    '<div class="obs-chips">' + (v.folders.length ? v.folders.map(function (f) {
      return '<button class="chip" data-obs="priv" data-vid="' + esc(v.id) + '" data-f="' + esc(f) + '" aria-pressed="' + (v.private.indexOf(f) >= 0) + '">' + esc(f) + '</button>'; }).join('') : '<span class="cap">第一层没有文件夹</span>') +
      extra.map(function (f) { return '<button class="chip" data-obs="priv" data-vid="' + esc(v.id) + '" data-f="' + esc(f) + '" aria-pressed="true">' + esc(f) + '</button>'; }).join('') + '</div>' +
    '<div class="help">另外：笔记顶部写了 <code>私人: true</code>，或者带 <code>#私人</code> 标签的，也只在本地。</div>' +
    '<div class="btnrow"><button class="btn mini danger" data-obs="del" data-vid="' + esc(v.id) + '">不接这个库了</button></div></div>';
}
function obsInner() {
  var st = obsSt();
  if (!st) return '<div class="cap">读取中……</div>';
  var vs = st.vaults || [], n = 0, p = 0;
  vs.forEach(function (v) { n += v.notes; p += v.privNotes; });
  var a = OBS.add, chk = a.chk, live = useLive();
  var sum = vs.length ? vs.length + ' 个库 · ' + n + ' 篇笔记' + (p ? ' · 私人 ' + p + ' 篇只在本地' : '') + ' · ' + (st.inboxVault ? 'Agent 写的东西放在「' + esc(st.inboxVault) + '/' + esc(st.inbox) + '」' : '都是只读，Agent 不往库里写') : '还没接库。下面填库的文件夹路径，点「检查」。';
  var t = st.tidy || {};
  var tidy = t.ts ? '<div class="balbox obs-tidy"><div><span class="label">上次每日整理 · ' + new Date(t.ts * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) + '</span>' +
      '<div class="help">可能前后矛盾 ' + (t.conflicts || []).length + ' 处（查了 ' + (t.checked || 0) + ' 对相似的段落）· 可以加的链接 ' + (t.links || []).length + ' 条。全文在收件箱「每日」里，你的笔记一个字没改。</div>' +
      ((t.conflicts || []).slice(0, 3).map(function (c) { return '<div class="obs-line"><b>' + esc(c.a.split('/').pop().replace(/\.md$/, '')) + '</b> ↔ <b>' + esc(c.b.split('/').pop().replace(/\.md$/, '')) + '</b>：' + esc(c.why) + '</div>'; }).join('')) + '</div></div>' : '';
  var w = vs.filter(function (v) { return !v.ro && v.exists; })[0];
  var mem = st.memIn ? '记忆在「' + esc(st.memIn) + '/Agent 记忆」里，Obsidian 里能直接看、改。' : '记忆现在在 ' + esc(st.memDir) + '。';
  return '<div class="balbox obs-sum"><div><span class="label">Obsidian 笔记</span><div class="help" style="margin-top:.35rem">' + sum + '</div>' +
      (OBS.msg ? '<div class="help" style="color:var(--accent)">' + esc(OBS.msg) + '</div>' : '') + '</div>' +
    '<div class="btnrow"><button class="btn" data-obs="refresh"' + (live && vs.length && !OBS.busy ? '' : ' disabled') + '>' + (OBS.busy === 'refresh' ? '扫描中…' : '重新扫一遍') + '</button>' +
      '<button class="btn" data-obs="reindex"' + (live && vs.length && !OBS.busy ? '' : ' disabled') + '>' + (OBS.busy === 'reindex' ? '重建中…' : '全部重建索引') + '</button>' +
      '<button class="btn" data-obs="tidy"' + (live && vs.length && !OBS.busy ? '' : ' disabled') + '>' + (OBS.busy === 'tidy' ? '整理中…' : '现在整理一次') + '</button></div></div>' +
    (vs.length ? '<div class="obs-grid">' + vs.map(obsVaultCard).join('') + '</div>' : '') +
    '<div class="obs-card obs-add"><div class="label">加一个库</div>' +
      '<div class="secret"><input class="inp mono" id="obsAddPath" value="' + esc(a.path) + '" spellcheck="false" placeholder="库的文件夹路径，比如 D:\\Notes\\我的库"><button class="btn" data-obs="check"' + (live ? '' : ' disabled') + '>检查</button></div>' +
      '<div class="help">在资源管理器里打开库的文件夹，点地址栏复制路径。E 盘的库会锁成只读。</div>' +
      (chk ? '<div class="help" style="color:' + (chk.ok ? 'var(--ok)' : 'var(--bad)') + '">' + esc(chk.msg) + (chk.ro ? ' · 在 E 盘：只读' : '') + '</div>' : '') +
      (chk && chk.ok ? '<div class="secret"><input class="inp" id="obsAddName" value="' + esc(a.name) + '" placeholder="给它起个名字，比如 小说库"><button class="btn primary" data-obs="add">加进来</button></div>' : '') + '</div>' +
    '<div class="balbox obs-mem"><div><span class="label">记忆放在哪</span><div class="help" style="margin-top:.35rem">' + mem + '</div></div>' +
      (!st.memIn && w ? '<div class="btnrow"><button class="btn" data-obs="movemem" data-vid="' + esc(w.id) + '"' + (live && !OBS.busy ? '' : ' disabled') + '>把记忆搬进「' + esc(w.name) + '」</button></div>' : '') + '</div>' +
    '<div class="help obs-mem-note">搬的时候是复制过去，原来的文件夹改名留着，不删。只读的库不能放记忆。</div>' + tidy;
}

function obsVaultsNow() {
  return ((obsSt() || {}).vaults || []).map(function (v) { return { id: v.id, name: v.name, path: v.path, ro: v.ro, private: v.private.slice() }; });
}
function obsSave(list, msg) {
  if (!useLive()) { toast('演示模式不保存'); return; }
  OBS.msg = '';
  api('PUT', '/api/settings', { obsVaults: list }).then(function () { S.set.obsVaults = list; if (msg) toast(msg); return api('POST', '/api/obsidian/refresh', {}, 120000); })
    .then(function (j) { if (j && j.status) OBS.st = j.status; obsRender(); }, function (e) { toast(e.message, 5000); obsLoad(); });
}
function obsRun(kind) {
  var path = { refresh: '/api/obsidian/refresh', reindex: '/api/obsidian/reindex', tidy: '/api/obsidian/tidy' }[kind];
  OBS.busy = kind; obsRender();
  api('POST', path, {}, 600000).then(function (j) {
    if (kind === 'tidy') OBS.msg = j.skipped ? j.skipped : '整理好了：' + j.conflicts + ' 处可能矛盾、' + j.links + ' 条链接建议' + (j.written ? ' · 写进了 ' + j.written : '');
    else OBS.msg = '扫好了：' + (j.changed || 0) + ' 篇有改动' + (j.embedded ? '，算了 ' + j.embedded + ' 段向量' : '');
  }, function (e) { OBS.msg = '没成：' + e.message; }).then(function () { OBS.busy = ''; obsLoad(); });
}
document.addEventListener('click', function (e) {
  var t = e.target.closest('[data-obs]'); if (!t || !$('#obsBox') || !$('#obsBox').contains(t)) return;
  e.stopPropagation(); e.preventDefault();
  var act = t.dataset.obs, vid = t.dataset.vid, list = obsVaultsNow(), v = list.filter(function (x) { return x.id === vid; })[0];
  if (act === 'check') {
    OBS.add.path = ($('#obsAddPath') || {}).value || '';
    api('POST', '/api/obsidian/check', { path: OBS.add.path }).then(function (j) {
      OBS.add.chk = j; if (j.ok && !OBS.add.name) OBS.add.name = OBS.add.path.replace(/[\\/]+$/, '').split(/[\\/]/).pop(); obsRender(); });
  } else if (act === 'add') {
    var name = ($('#obsAddName') || {}).value || OBS.add.name, id = 'v' + Date.now().toString(36);
    list.push({ id: id, name: name, path: OBS.add.path, ro: !!(OBS.add.chk && OBS.add.chk.ro), private: [] });
    OBS.add = { path: '', name: '', ro: false, chk: null };
    obsSave(list, '加好了，正在扫描笔记');
  } else if (act === 'del' && v) {
    if (t.dataset.armed !== '1') { t.dataset.armed = '1'; t.textContent = '再点一次确认（只是不接了，库里的文件不动）'; return; }
    obsSave(list.filter(function (x) { return x.id !== vid; }), '不接「' + v.name + '」了，库里的文件没动');
  } else if (act === 'ro' && v) {
    v.ro = t.getAttribute('aria-checked') !== 'true'; obsSave(list);
  } else if (act === 'priv' && v) {
    var f = t.dataset.f, i = v.private.indexOf(f);
    if (i >= 0) v.private.splice(i, 1); else v.private.push(f);
    obsSave(list, (i >= 0 ? '「' + f + '」不再算私人' : '「' + f + '」里的笔记只给本地小脑'));
  } else if (act === 'refresh' || act === 'reindex' || act === 'tidy') obsRun(act);
  else if (act === 'movemem') {
    if (t.dataset.armed !== '1') { t.dataset.armed = '1'; t.textContent = '再点一次确认搬家'; return; }
    OBS.busy = 'movemem'; obsRender();
    api('POST', '/api/obsidian/move-memory', { vault: vid }, 120000).then(function (j) { OBS.msg = j.msg; toast(j.msg, 6000); }, function (e) { toast(e.message, 6000); })
      .then(function () { OBS.busy = ''; obsLoad(); });
  }
}, true);
document.addEventListener('change', function (e) {
  var t = e.target; if (!t.closest || !t.closest('#obsBox')) return;
  if (!t.dataset.obsName && !t.dataset.obsPath) return;
  e.stopPropagation();
  var list = obsVaultsNow(), v = list.filter(function (x) { return x.id === (t.dataset.obsName || t.dataset.obsPath); })[0]; if (!v) return;
  if (t.dataset.obsName) v.name = t.value.trim() || v.name; else v.path = t.value.trim() || v.path;
  obsSave(list, '改好了');
}, true);
