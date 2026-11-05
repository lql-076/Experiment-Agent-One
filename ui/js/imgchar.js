'use strict';
/* ================= 生图 · 角色（v2.0，后端 app/imagegen.py 的 char_*）=================
   作者 11-05：看板娘白叶、紫苏这种固定的角色，先用 A-Pose / T-Pose 出三视图，挑一张定稿存成角色；
   以后只写动作、表情，就让这个角色做出来。批量清单里写到角色的名字（或别名），出图时也自动带上她的三视图和外形描述。
   三块：左边角色列表；中间这个角色的三视图（定稿 / 候选）、外形描述、自己放的参考图；右边「让她做」：动作、表情、立绘 / Q 版、和谁一起出场。
   出图用顶上那个大按钮（和单张、批量一样），进度在顶上和「后台在跑」里看。 */
var ICH = { sel: null, nw: false, pose: 'A', act: '', face: '正常', kind: 'Q版', ratio: '1:1', trans: false, with: [], pick: null, sig: {}, draft: null, delArm: null };
var ICH_FACES = ['正常', '开心', '得意', '无语', '震惊', '崩溃', '大哭', '丑萌（高光）'];
var ICH_DEMO = [{ id: 'c1', name: '紫苏', aliases: ['技术宅'], desc: '男，深蓝黑色头发三七分，圆框细眼镜；宽大的紫色卫衣（白色抽绳）、黑裤子、白球鞋；脖子上挂着耳机，胳膊下夹着笔记本电脑。', pose: 'A', sheet: '定稿_三视图.png', sheet_v: 1, refs: [], cands: [], made_n: 23, made: ['a', 'b', 'c', 'd'], ready: true, dir: 'F:\\Agent\\生图输出\\角色\\紫苏' },
  { id: 'c2', name: '白叶', aliases: ['看板娘'], desc: '女，（从十个候选里挑中后写全：发型、眼睛、衣服、配色、手里拿什么）', pose: 'A', sheet: '', refs: [], cands: ['1', '2', '3', '4'], made_n: 0, made: [], ready: false, dir: 'F:\\Agent\\生图输出\\角色\\白叶' }];
function ichList() { var s = IMG.st || {}; return s.demo ? ICH_DEMO : (s.chars || []); }
function ichCur() {
  if (ICH.nw) return null;
  var l = ichList(), c = l.filter(function (x) { return x.id === ICH.sel; })[0];
  if (!c && l.length) { c = l[0]; ICH.sel = c.id; }
  return c || null;
}
function ichImg(c, f, kind) { return useLive() ? '/api/img/chars/' + encodeURIComponent(c.id) + '/' + (kind || 'f') + '/' + encodeURIComponent(f) + (kind === 'made' ? '' : '?v=' + (c.sheet_v || Date.now() % 1e6)) : ''; }
/* 演示模式、图还没出：画一个占位的小人（正面、侧面、背面） */
function ichFig(pose, n) {
  var arms = pose === 'T' ? ['M39 48L9 48M61 48L91 48', 'M50 49L58 53', 'M39 48L9 48M61 48L91 48'] : ['M39 49L23 98M61 49L77 98', 'M50 50L55 98', 'M39 49L23 98M61 49L77 98'];
  var body = ['M38 44h24l3 52h-30z', 'M43 44h14l2 52h-18z', 'M38 44h24l3 52h-30z'];
  return '<span class="ch-fig" aria-hidden="true">' + [0, 1, 2].slice(0, n || 3).map(function (k) {
    return '<svg viewBox="0 0 100 190"><path d="' + arms[k] + '" stroke="currentColor" stroke-width="7" stroke-linecap="round" fill="none" opacity=".55"/><path d="M44 98L42 178M56 98L58 178" stroke="currentColor" stroke-width="8" stroke-linecap="round" fill="none" opacity=".55"/>' +
      '<path d="' + body[k] + '" fill="currentColor" opacity=".8"/><circle cx="50" cy="24" r="13" fill="currentColor"/></svg>'; }).join('') + '</span>';
}
function imgCharHTML() {
  return '<section class="fp fg-col"><div class="fh"><i></i>CAST<em>· 角色</em><span id="chN"></span></div><div class="ch-list fg-scroll" id="chList"></div>' +
      '<div class="fg-of"><button class="fb" data-ch="new">＋ 新角色</button></div><div class="ch-note fg-cap">批量清单里写到角色的名字或别名（标题、提示词都行），出图时自动带上她的三视图和外形描述，提示词只写动作就行。</div></section>' +
    '<section class="fp fg-col"><div class="fh"><i></i>SHEET<em id="chMt">· 三视图</em><span id="chFlow"></span></div><div class="ch-body fg-scroll" id="chBody"></div></section>' +
    '<section class="fp fg-col"><div class="fh"><i></i>ACT<em id="chAt">· 让她做</em></div><div class="ch-act" id="chAct"></div>' +
      '<div class="fh ch-mh"><i></i>MADE<em>· 画过的</em><span id="chMn"></span></div><div class="ch-made fg-scroll" id="chMade"></div></section>' +
    '<input type="file" id="chFile" accept="image/png,image/jpeg,image/webp" hidden>';
}
function ichSet(id, html) {
  if (ICH.sig[id] === html) return;
  var el = $('#' + id); if (!el) return;
  var a = document.activeElement;                          // 正在打字的框不重画（不然光标会跳）
  if (!ICH.force && a && el.contains(a) && /^(INPUT|TEXTAREA)$/.test(a.tagName)) return;
  ICH.sig[id] = html; el.innerHTML = html;
}
function imgChar(first) {
  if (!$('#chList')) return;
  if (first) ICH.sig = {};
  var l = ichList(), c = ichCur(), run = imgRun(), live = useLive();
  $('#chN').textContent = l.length ? l.length + ' 个' : '';
  ichSet('chList', l.map(function (x) {
    return '<button class="ch-it" data-ch="sel" data-id="' + esc(x.id) + '" aria-pressed="' + (!ICH.nw && x.id === ICH.sel) + '"><span class="ch-av' + (x.ready ? ' ok' : '') + '">' +
      (x.ready && x.sheet && live ? '<img src="' + ichImg(x, x.sheet) + '" alt="" loading="lazy">' : esc(x.name.slice(0, 1))) + '</span><span class="ch-nm"><b>' + esc(x.name) + '</b><small>' +
      esc(x.ready ? (x.sheet ? '已定稿' : '用自己的参考图') + (x.made_n ? ' · 画过 ' + x.made_n + ' 张' : '') : x.cands.length ? '出了 ' + x.cands.length + ' 张候选，挑一张定稿' : '还没定稿') + '</small></span></button>';
  }).join('') + (ICH.nw ? '<div class="ch-it on"><span class="ch-av">＋</span><span class="ch-nm"><b>新角色</b><small>写好名字和外形，点「保存」</small></span></div>' : '') +
    (!l.length && !ICH.nw ? '<div class="fg-cap" style="padding:.75rem .9rem">还没有角色。点下面「新角色」：写名字（白叶、紫苏……）和外形，出三视图，挑一张定稿。</div>' : ''));
  /* 中间：三视图 */
  var d = ICH.draft || {}, editing = ICH.nw || !!ICH.draft;
  var name = ICH.nw ? (d.name || '') : c ? (d.name != null ? d.name : c.name) : '';
  var al = ICH.nw ? (d.al || '') : c ? (d.al != null ? d.al : (c.aliases || []).join('、')) : '';
  var desc = ICH.nw ? (d.desc || '') : c ? (d.desc != null ? d.desc : c.desc) : '';
  var step = !c ? 1 : c.sheet ? 3 : c.cands.length ? 2 : (c.desc || c.refs.length) ? 2 : 1;
  ichSet('chFlow', !c && !ICH.nw ? '' : ['写外形', '出三视图', '定稿'].map(function (x, i) { var k = i + 1; return '<b class="' + (step > k || (c && c.sheet) ? 'ok' : step === k ? 'cur' : '') + '">' + (step > k || (c && c.sheet) ? '✓' : k) + ' ' + x + '</b>'; }).join('<i></i>'));
  $('#chMt').textContent = c ? '· ' + c.name + (c.sheet ? ' · 已定稿' : '') : ICH.nw ? '· 新角色' : '· 三视图';
  var body;
  if (!c && !ICH.nw) body = '<div class="ch-empty">' + ichFig('A') + '<b>先建一个角色</b><span>写外形 → 用 A-Pose 或 T-Pose 出三视图（一次 4 张候选）→ 挑一张定稿。以后只写动作、表情就能出图。</span></div>';
  else {
    var pic;
    if (c && c.sheet && ICH.pick == null) pic = '<div class="ch-sheet">' + (live ? '<img src="' + ichImg(c, c.sheet) + '" alt="' + esc(c.name) + ' 的三视图">' : ichFig(c.pose)) + '<span class="ch-tag">定稿 · ' + (c.pose === 'T' ? 'T-Pose' : 'A-Pose') + '</span>' +
      (c.cands.length ? '<button class="fb sm ch-re" data-ch="repick">换一张候选</button>' : '') + '</div>';
    else if (c && c.cands.length) pic = '<div class="ch-cands">' + c.cands.slice(0, 4).map(function (f, i) {
      var on = (ICH.pick == null ? 0 : ICH.pick) === i;
      return '<button class="ch-cand" data-ch="pick" data-i="' + i + '" aria-pressed="' + on + '">' + (live ? '<img src="' + ichImg(c, f) + '" alt="候选 ' + (i + 1) + '" loading="lazy">' : ichFig(c.pose)) + '<span class="n">' + (i + 1) + '</span></button>'; }).join('') + '</div>';
    else pic = '<div class="ch-sheet ch-none">' + ichFig(ICH.pose) + '<span class="fg-cap">' + (ICH.nw ? '保存以后就能出三视图' : '还没出三视图：写好外形描述，点下面「出三视图」') + '</span></div>';
    var refs = c ? c.refs : [];
    body = pic +
      '<div class="ch-row"><label class="fg-lb" for="chName">NAME<em>名字</em></label><input class="fi" id="chName" maxlength="12" value="' + esc(name) + '" placeholder="白叶"><label class="fg-lb" for="chAl">ALSO<em>别名</em></label><input class="fi" id="chAl" value="' + esc(al) + '" placeholder="看板娘（几个用顿号隔开）"></div>' +
      '<div class="fg-lb">LOOK<em>外形描述 · 每次出图都带上这段（写全：发型、眼睛、脸、衣服、配色、手里拿什么）</em></div>' +
      '<textarea class="fi ch-desc" id="chDesc" rows="3" spellcheck="false" placeholder="女，银白色短发、琥珀色眼睛；薄荷绿开衫、白色百褶裙；总抱着一本深棕色硬皮书。">' + esc(desc) + '</textarea>' +
      (c ? '<div class="fg-lb">REFS<em>自己的参考图（可以不放；放了，出三视图时照着画，没定稿也能先用）</em></div><div class="ch-refs">' + refs.map(function (f) {
        return '<span class="ch-ref">' + (live ? '<img src="' + ichImg(c, f) + '" alt="">' : '') + '<button class="fb x" data-ch="unref" data-f="' + esc(f) + '" aria-label="去掉这张">' + ICONS.cross + '</button></span>'; }).join('') +
        (refs.length < 4 ? '<button class="ch-add" data-ch="addref"' + (run ? ' disabled' : '') + '>＋ 放一张</button>' : '') + '</div>' : '') +
      '<div class="ch-ops"><span class="fseg" role="group" aria-label="三视图用的姿势">' + [['A', 'A-Pose'], ['T', 'T-Pose']].map(function (p) { return '<button data-ch="pose" data-v="' + p[0] + '" aria-pressed="' + (ICH.pose === p[0]) + '">' + p[1] + '</button>'; }).join('') + '</span>' +
        (editing ? '<button class="fb pri" data-ch="save">' + (ICH.nw ? '保存这个角色' : '保存改动') + '</button>' + (ICH.nw ? '<button class="fb" data-ch="cancel">不建了</button>' : '<button class="fb" data-ch="cancel">不改了</button>') : '') +
        (c && !editing ? '<button class="fb' + (c.sheet ? '' : ' pri') + '" data-ch="sheet"' + (run || !IMG.st.cfg.key && live ? ' disabled' : '') + '>' + (c.sheet ? '重出三视图' : '出三视图') + ' · 4 张 · ' + imgMoney(imgUsd('16:9') == null ? null : imgUsd('16:9') * 4) + '</button>' : '') +
        (c && c.cands.length && (!c.sheet || ICH.pick != null) && !editing ? '<button class="fb pri" data-ch="final">用第 ' + ((ICH.pick || 0) + 1) + ' 张定稿</button>' : '') +
        '<span class="sp"></span>' + (c ? '<button class="fb sm" data-ch="open">打开文件夹</button><button class="fb sm' + (ICH.delArm === c.id ? ' bad' : '') + '" data-ch="del">' + (ICH.delArm === c.id ? '再点一次：从列表去掉（图不删）' : '去掉') + '</button>' : '') + '</div>';
  }
  ichSet('chBody', body);
  /* 右边：让她做 */
  var others = ichList().filter(function (x) { return c && x.id !== c.id; });
  ICH.with = ICH.with.filter(function (id) { return others.some(function (x) { return x.id === id && x.ready; }); });
  $('#chAt').textContent = c ? '· 让' + c.name + '做' : '· 让她做';
  var act = !c ? '<div class="fg-cap" style="padding:1rem">先在左边选一个角色。</div>' : !c.ready ? '<div class="ch-wait"><b>' + esc(c.name) + ' 还没定稿</b><span class="fg-cap">挑一张三视图定稿（或者放一张自己的参考图），就能在这里写动作、选表情出图了。</span></div>' :
    '<div class="fg-lb">ACTION<em>动作 · 要她做什么</em><span>Ctrl+Enter 生成</span></div><textarea class="fi ch-do" id="chDo" rows="3" spellcheck="false" placeholder="双手抱头往后仰，笔记本电脑从胳膊下面滑出去">' + esc(ICH.act) + '</textarea>' +
    '<div class="fg-lb">FACE<em>表情</em></div><div class="ch-faces">' + ICH_FACES.map(function (f) { return '<button class="fb sm" data-ch="face" data-v="' + esc(f) + '" aria-pressed="' + (ICH.face === f) + '">' + esc(f) + '</button>'; }).join('') + '</div>' +
    '<div class="ch-row2"><span class="fg-lb">KIND<em>版本</em></span><span class="fseg">' + ['立绘', 'Q版'].map(function (k) { return '<button data-ch="kind" data-v="' + k + '" aria-pressed="' + (ICH.kind === k) + '">' + (k === 'Q版' ? 'Q 版' : k) + '</button>'; }).join('') + '</span>' +
      '<span class="fg-lb">RATIO<em>比例</em></span><span class="fseg">' + ['1:1', '16:9', '9:16', '4:5'].map(function (r) { return '<button data-ch="ratio" data-v="' + r + '" aria-pressed="' + (ICH.ratio === r) + '">' + r + '</button>'; }).join('') + '</span></div>' +
    '<div class="ch-row2"><span class="fg-lb">WITH<em>一起出场</em></span>' + (others.length ? others.map(function (x) {
      return '<button class="fb sm" data-ch="with" data-id="' + esc(x.id) + '" aria-pressed="' + (ICH.with.indexOf(x.id) >= 0) + '"' + (x.ready ? '' : ' disabled title="' + esc(x.name) + ' 还没定稿"') + '>＋ ' + esc(x.name) + (x.ready ? '' : '（没定稿）') + '</button>'; }).join('') : '<span class="fg-cap">只有她一个</span>') +
      '<span class="sp"></span><button class="fg-sw" data-ch="trans" aria-pressed="' + ICH.trans + '">透明背景</button></div>' +
    '<div class="ch-auto fg-cap">自动带上：' + esc([c].concat(others.filter(function (x) { return ICH.with.indexOf(x.id) >= 0; })).map(function (x) { return x.name; }).join('、')) + ' 的' + (c.sheet ? '三视图' : '参考图') + ' + 外形描述 + 画风（日系平涂、干净线稿、两阶阴影）。点顶上的大按钮生成。</div>';
  ichSet('chAct', act);
  $('#chMn').textContent = c ? (c.made_n || 0) + ' 张' : '';
  ichSet('chMade', c && c.made.length ? c.made.map(function (f) {
    return '<button class="ch-mi" data-ch="view" data-f="' + esc(f) + '" title="' + esc(f) + '">' + (live ? '<img src="' + ichImg(c, f, 'made') + '" alt="" loading="lazy">' : ichFig('A', 1)) + '</button>'; }).join('') :
    '<div class="fg-cap" style="padding:.6rem .2rem;grid-column:1/-1">' + (c ? '还没画过。出的图存在 ' + esc(c.dir) + '\\出图' : '') + '</div>');
}
function imgCharGo() {
  var c = ichCur(), s = IMG.st, u = imgUsd(ICH.ratio);
  if (!c) return { t: '先建角色<small>左边「新角色」</small>', dis: true };
  if (!c.ready) return { t: '先定稿<small>' + esc(c.name) + ' 还没有三视图</small>', dis: true };
  return { t: '让' + esc(c.name) + '做' + '<small>' + esc(ICH.face) + ' · ' + (ICH.kind === 'Q版' ? 'Q 版' : '立绘') + ' · ' + ICH.ratio + ' · ' + (u == null ? '价格看 API易' : '约 ' + imgMoney(u)) + '</small>', dis: !s.cfg.key && !s.demo };
}
function ichJob(p, label) {
  return p.then(function (j) { IMG.st.job = j.job; imgSync(); imgLog('▶ ' + esc(label), 'c'); }).catch(function (e) { toast(e.message, 5000); });
}
function imgCharMake() {
  var c = ichCur(); if (!c || !c.ready) return;
  if (!useLive()) { toast('演示模式：连上后端才能出图'); return; }
  var a = ($('#chDo') ? $('#chDo').value : ICH.act).trim(); ICH.act = a;
  if (!a) { toast('写一句要她做什么动作'); var x = $('#chDo'); if (x) x.focus(); return; }
  ichJob(api('POST', '/api/img/chars/' + encodeURIComponent(c.id) + '/make', { action: a, face: ICH.face, kind: ICH.kind, ratio: ICH.ratio, transparent: ICH.trans, with: ICH.with }, 20000),
    '让' + c.name + '做：' + a.slice(0, 20) + '（' + ICH.face + ' · ' + ICH.kind + '）');
}
function ichDone(j, msg) { if (j && j.chars) IMG.st.chars = j.chars; ICH.sig = {}; imgChar(); imgGo(); imgTabsDot(); if (msg) toast(msg); }
function ichSave() {
  var d = ICH.draft || {}, c = ichCur();
  var body = { name: ($('#chName') || {}).value || d.name || '', aliases: ($('#chAl') || {}).value || '', desc: ($('#chDesc') || {}).value || '' };
  if (!body.name.trim()) { toast('给角色起个名字'); return Promise.resolve(false); }
  var p = ICH.nw ? api('POST', '/api/img/chars', body) : api('PATCH', '/api/img/chars/' + encodeURIComponent(c.id), body);
  return p.then(function (j) { if (j.id) ICH.sel = j.id; ICH.nw = false; ICH.draft = null; ichDone(j, '存好了'); return true; }).catch(function (e) { toast(e.message, 5000); return false; });
}
$('#view-img').addEventListener('click', function (ev) {
  var t = ev.target.closest('[data-ch]'); if (!t || t.disabled) return;
  var k = t.dataset.ch, c = ichCur(), live = useLive();
  if (k === 'sel') { ICH.sel = t.dataset.id; ICH.nw = false; ICH.draft = null; ICH.pick = null; ICH.delArm = null; ICH.with = []; ichDone(); return; }
  if (k === 'new') { ICH.nw = true; ICH.draft = { name: '', al: '', desc: '' }; ICH.pick = null; ichDone(); setTimeout(function () { var n = $('#chName'); if (n) n.focus(); }, 30); return; }
  if (k === 'cancel') { ICH.nw = false; ICH.draft = null; ichDone(); return; }
  if (k === 'pose') { ICH.pose = t.dataset.v; ichDone(); return; }
  if (k === 'pick') { ICH.pick = +t.dataset.i; ichDone(); return; }
  if (k === 'repick') { ICH.pick = 0; ichDone(); return; }
  if (k === 'face') { ICH.face = t.dataset.v; ichDone(); return; }
  if (k === 'kind') { ICH.kind = t.dataset.v; ichDone(); return; }
  if (k === 'ratio') { ICH.ratio = t.dataset.v; ichDone(); return; }
  if (k === 'trans') { ICH.trans = !ICH.trans; ichDone(); return; }
  if (k === 'with') { var i = ICH.with.indexOf(t.dataset.id); if (i >= 0) ICH.with.splice(i, 1); else ICH.with.push(t.dataset.id); ichDone(); return; }
  if (k === 'view' && c) { if (live) imgBox('<img src="' + ichImg(c, t.dataset.f, 'made') + '" alt=""><div class="fg-cap">' + esc(t.dataset.f) + '</div>', 'ch-box'); return; }
  if (!live) { toast('演示模式：连上后端才能用'); return; }
  if (k === 'save') ichSave();
  else if (k === 'sheet' && c) ichJob(api('POST', '/api/img/chars/' + encodeURIComponent(c.id) + '/sheet', { pose: ICH.pose, n: 4 }, 20000), '出 ' + c.name + ' 的三视图（' + (ICH.pose === 'T' ? 'T' : 'A') + '-Pose，4 张候选）');
  else if (k === 'final' && c) {
    var f = c.cands[ICH.pick || 0]; if (!f) return;
    api('POST', '/api/img/chars/' + encodeURIComponent(c.id) + '/final', { file: f }).then(function (j) { ICH.pick = null; ichDone(j, c.name + ' 定稿了：以后出图都带上这张三视图'); }).catch(function (e) { toast(e.message); });
  }
  else if (k === 'addref') $('#chFile').click();
  else if (k === 'unref' && c) api('DELETE', '/api/img/chars/' + encodeURIComponent(c.id) + '/ref/' + encodeURIComponent(t.dataset.f)).then(function (j) { ichDone(j, '去掉了（挪进了「旧版」，没删）'); }).catch(function (e) { toast(e.message); });
  else if (k === 'open' && c) api('POST', '/api/img/open', { char: c.id }).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); });
  else if (k === 'del' && c) {
    if (ICH.delArm !== c.id) { ICH.delArm = c.id; ichDone(); setTimeout(function () { if (ICH.delArm === c.id) { ICH.delArm = null; ichDone(); } }, 3000); return; }
    ICH.delArm = null;
    api('DELETE', '/api/img/chars/' + encodeURIComponent(c.id)).then(function (j) { ICH.sel = null; ichDone(j, '从列表去掉了（文件夹里的图还在）'); }).catch(function (e) { toast(e.message); });
  }
});
$('#view-img').addEventListener('input', function (ev) {
  var id = ev.target.id;
  if (id === 'chName' || id === 'chAl' || id === 'chDesc') {
    var c = ichCur(); ICH.draft = ICH.draft || (c ? { name: c.name, al: (c.aliases || []).join('、'), desc: c.desc } : { name: '', al: '', desc: '' });
    ICH.draft[id === 'chName' ? 'name' : id === 'chAl' ? 'al' : 'desc'] = ev.target.value;
    var ops = $('.ch-ops'); if (ops && !ops.querySelector('[data-ch="save"]')) { ICH.sig.chBody = ''; var pos = ev.target.selectionStart; ICH.force = true; imgChar(); ICH.force = false; var el = $('#' + id); if (el) { el.focus(); try { el.setSelectionRange(pos, pos); } catch (e) { /* 不是文本框 */ } } }
  }
  if (id === 'chDo') { ICH.act = ev.target.value; }
});
$('#view-img').addEventListener('keydown', function (ev) { if (ev.target.id === 'chDo' && ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); imgCharMake(); } });
$('#view-img').addEventListener('change', function (ev) {
  if (ev.target.id !== 'chFile') return;
  var f = ev.target.files && ev.target.files[0], c = ichCur(); ev.target.value = '';
  if (!f || !c) return;
  if (f.size > 10 * 1024 * 1024) { toast('一张最多 10MB'); return; }
  var r = new FileReader();
  r.onload = function () { api('POST', '/api/img/chars/' + encodeURIComponent(c.id) + '/ref', { img: String(r.result) }, 20000).then(function (j) { ichDone(j, '放好了：出三视图时照着它画'); }).catch(function (e) { toast(e.message, 5000); }); };
  r.readAsDataURL(f);
});
