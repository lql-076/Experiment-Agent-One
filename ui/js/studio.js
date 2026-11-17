'use strict';
/* ================= 视频工坊（v3.6，工具窗口 ?tool=studio）=================
   一条流水线：① 创意与拆解 → ② 素材生成（图 / 音 / 乐）→ ③ 视频合成 → ④ 预览与发布。
   - 左边：主题或完整口播、画幅、风格、时长、音色、配乐；点「AI 拆解分镜」新建一个项目。
   - 中间：分镜列表。每镜的台词、语气、画面提示词都能直接改（改完自动存）；能只重出这一张图、只重配这一段。
   - 右边：成片 <video>、配音 / 配乐试听、打开输出文件夹、送去抖音发布（只放进「发布」的待确认队列，绝不直接发）。
   - 顶部流程条：四步状态一眼看清；「一键全自动生产」按 生图 + 配音 → 配乐 → 合成 跑完；「停下」随时中断。
   操作偏好（画幅、风格、时长、音色、配乐、字幕、配乐音量）存进 uiState（U.studio），深浅色全用主题变量。 */
var STUDIO = { st: null, t: null, pid: '', busy: false, editing: false, topic: (U.studioTopic || ''), sig: {}, saveT: null,
  pref: { ratio: '9:16', style: '知识科普', seconds: 60, voice: 'local:preset:Vivian', bgm: 'auto', bgmVol: 0.18, subtitle: true } };
try { if (U.studio && typeof U.studio === 'object') Object.assign(STUDIO.pref, U.studio); } catch (e) {}

var ST_STYLES = ['知识科普', '科技数码', '情感故事', '搞笑段子', '生活记录', '影视解说', '职场干货', '历史人文'];
var ST_SECS = [30, 45, 60, 90, 120];
var ST_BGM = [['auto', '按脚本自动'],
  ['轻快电子', 'upbeat electronic pop, bright synths, clean beat, energetic, no vocals'],
  ['安静钢琴', 'gentle solo piano, warm and calm, sparse, no vocals'],
  ['Lo-fi', 'lo-fi hip hop, mellow drums, warm electric piano, vinyl texture, no vocals'],
  ['科技感', 'cinematic electronic ambient, pulsing bass, futuristic, mid tempo, no vocals'],
  ['悬疑', 'tense low strings, slow build, subtle pulse, mysterious, no vocals'],
  ['热血', 'epic orchestral, driving drums, rising energy, heroic, no vocals'],
  ['8-bit', '8-bit chiptune, playful, retro game music, no vocals'],
  ['温暖吉他', 'warm acoustic guitar fingerstyle, bright and relaxed, no vocals']];

function stDemo() {
  var shots = [1, 2, 3].map(function (i) {
    return { id: 's' + i, n: i, text: ['开场先抛出一个反常识的问题。', '第二个分镜解释为什么大家都误会了。', '最后给出一个马上能用的办法。'][i - 1],
      tone: ['好奇', '平静', '轻快'][i - 1], image_prompt: ['暖光书桌前的年轻人，竖屏中景', '屏幕上出现对比图表，冷色调', '一只手在手机上点下按钮，特写'][i - 1],
      seconds_hint: 6, duration: 5.8, start: (i - 1) * 6, end: i * 6 - 0.2, image_ok: false, tts_ok: false, image_st: 'idle', tts_st: 'idle', image_url: '', tts_url: '' };
  });
  return { projects: [{ id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', created: '2026-11-18 02:00:00', ratio: '9:16', st: 'idle', shots: 3, video: false }], active: 'demo',
    project: { id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', desc: '这一期讲讲普通人马上能用的三个 AI 用法。', tags: ['AI', '效率工具'],
      created: '2026-11-18 02:00:00', ratio: '9:16', style: '知识科普', target_seconds: 60, topic: '', bgm_prompt: 'upbeat electronic, no vocals',
      settings: { subtitle: true, bgm_volume: 0.18, kenburns: true, voice: { label: 'Vivian', id: 'local:preset:Vivian' } },
      steps: { plan: { st: 'ok', msg: '3 个分镜' }, images: { st: 'idle', msg: '' }, tts: { st: 'idle', msg: '' }, bgm: { st: 'idle', msg: '' }, video: { st: 'idle', msg: '' } },
      files: {}, shots: shots, total_seconds: 17.5, st: 'idle', error: '', cost: {}, dir: 'F:\\Agent\\工作区\\视频工坊\\演示项目', video_ok: false },
    job: null, voices: [{ id: 'local:preset:Vivian', label: 'Vivian · 女声 · 明亮', engine: 'local' }, { id: 'local:preset:Serena', label: 'Serena · 女声 · 温柔', engine: 'local' },
      { id: 'local:preset:Uncle_Fu', label: 'Uncle_Fu · 男声 · 低沉', engine: 'local' }],
    ratios: [{ id: '9:16', label: '竖屏 9:16（抖音）' }, { id: '16:9', label: '横屏 16:9' }], styles: ST_STYLES };
}
function studioSt() { return useLive() ? STUDIO.st : stDemo(); }
function studioProj() { var s = studioSt(); return s && s.project; }
function studioJob() { var s = studioSt(); return s && s.job; }
function studioRunning() { var j = studioJob(); return !!(j && j.st === 'run'); }
function stClock(s) { s = Math.max(0, Math.round(+s || 0)); return Math.floor(s / 60) + ':' + pad(s % 60); }
function stSize(b) { return b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' KB'; }
function stEsc(s) { return esc(s); }

function stPut(id, html) { if (STUDIO.sig[id] === html) return; var el = $('#' + id); if (!el) return; STUDIO.sig[id] = html; el.innerHTML = html; }
function studioShell() {
  return '<div class="st"><section class="hud st-flow" id="stFlow"></section><div class="st-grid">' +
    '<section class="hud st-panel st-in"><div id="stIn"></div></section>' +
    '<section class="hud st-panel st-board"><div id="stBoard"></div></section>' +
    '<section class="hud st-panel st-out"><div id="stOut"></div></section></div></div>';
}
function renderStudio(force) {
  var v = $('#view-studio'); if (!v) return;
  if (!v.querySelector('.st')) { v.innerHTML = studioShell(); STUDIO.sig = {}; }
  if (STUDIO.editing && !force) { renderStFlow(); return; }
  renderStFlow(); renderStIn(); renderStBoard(); renderStOut();
}

/* ---------- 顶部流程条 ---------- */
function stStepCls(p, k) {
  var s = p && p.steps && p.steps[k];
  if (!s) return 'idle';
  if (s.st === 'run') return 'run';
  if (s.st === 'ok') return 'done';
  if (s.st === 'warn') return 'warn';
  if (s.st === 'err' || s.st === 'stop') return 'bad';
  if (s.st === 'stale') return 'stale';
  return 'idle';
}
function stStepText(p, k) {
  var s = p && p.steps && p.steps[k];
  if (s && s.msg) return s.msg.length > 32 ? s.msg.slice(0, 32) + '…' : s.msg;
  return { plan: '等主题', images: '等拆解', tts: '等拆解', bgm: '可选', video: '等素材' }[k] || '';
}
function renderStFlow() {
  var p = studioProj(), j = studioJob(), run = studioRunning();
  var shots = (p && p.shots) || [], donePlan = shots.length > 0;
  var imgOk = shots.filter(function (s) { return s.image_ok; }).length, ttsOk = shots.filter(function (s) { return s.tts_ok; }).length;
  var bgmOk = !!(p && p.files && p.files.bgm), vidOk = !!(p && p.video_ok);
  var steps = [
    ['1', '创意与拆解', donePlan ? shots.length + ' 镜 · 约 ' + stClock(p.total_seconds || p.target_seconds) : '写主题，AI 拆', donePlan ? 'done' : (j && j.stage === 1 ? 'run' : 'idle')],
    ['2', '素材生成', donePlan ? ('图 ' + imgOk + '/' + shots.length + ' · 音 ' + ttsOk + '/' + shots.length + (bgmOk ? ' · 乐 ✓' : ' · 乐 —')) : '等拆解',
      (j && j.stage === 2) ? 'run' : (imgOk && ttsOk && imgOk === shots.length && ttsOk === shots.length ? 'done' : (donePlan ? 'idle' : 'idle'))],
    ['3', '视频合成', vidOk ? ('成片 ' + stClock(p.duration || p.total_seconds)) : '等素材', (j && j.stage === 3) ? 'run' : (vidOk ? 'done' : 'idle')],
    ['4', '预览与发布', vidOk ? '可以送去发布' : '等成片', vidOk ? 'done' : 'idle']];
  var html = '<div class="st-flowbar"><div class="st-steps">' + steps.map(function (x, i) {
    return '<div class="st-step st-' + x[3] + '"><span class="st-num">' + x[0] + '</span><div><b>' + x[1] + '</b><em>' + esc(x[2]) + '</em></div></div>' +
      (i < 3 ? '<i class="st-link' + (x[3] === 'done' ? ' on' : '') + '"></i>' : '');
  }).join('') + '</div><div class="st-acts">' +
    '<button class="btn mini ghost" data-st="refresh">刷新</button>' +
    '<button class="btn mini danger" data-st="stop"' + (run ? '' : ' disabled') + '>停下</button>' +
    '<button class="btn primary st-go" data-st="run"' + (run || (!shots.length && !(STUDIO.topic || '').trim()) ? ' disabled' : '') + '>' +
    (run ? '正在跑…' : '一键全自动生产') + '</button></div></div>';
  stPut('stFlow', html);
}

/* ---------- 左边：输入与参数 ---------- */
function stVoiceOptions(p) {
  var vs = (studioSt() && studioSt().voices) || [];
  var cur = (p && p.settings && p.settings.voice && p.settings.voice.id) || STUDIO.pref.voice;
  if (!vs.some(function (v) { return v.id === cur; }) && vs.length) cur = vs[0].id;
  return vs.map(function (v) { return '<option value="' + esc(v.id) + '"' + (v.id === cur ? ' selected' : '') + '>' + esc(v.label) + '</option>'; }).join('');
}
function renderStIn() {
  var s = studioSt() || {}, p = s.project, ps = (studioSt() && studioSt().projects) || [], prefs = STUDIO.pref;
  var projSel = '<select class="inp" id="stProj" aria-label="选择项目">' + (ps.length ? ps.map(function (x) {
    return '<option value="' + esc(x.id) + '"' + (p && x.id === p.id ? ' selected' : '') + '>' + esc(x.title || x.name) + ' · ' + esc((x.created || '').slice(5, 16)) + '</option>';
  }).join('') : '<option value="">还没有项目</option>') + '</select>';
  var curRatio = (p && p.ratio) || prefs.ratio, curStyle = (p && p.style) || prefs.style, curSec = (p && p.target_seconds) || prefs.seconds;
  var styles = ST_STYLES.slice(); if (styles.indexOf(curStyle) < 0) styles.unshift(curStyle);
  var secs = ST_SECS.slice(); if (secs.indexOf(+curSec) < 0) { secs.push(+curSec); secs.sort(function (a, b) { return a - b; }); }
  var bgmCur = (p && p.bgm_prompt) ? prefs.bgm : 'auto';
  var subOn = p && p.settings && p.settings.subtitle !== undefined ? !!p.settings.subtitle : !!prefs.subtitle;
  var html = '<div class="bg-h"><b>创意与参数</b><span>新建或一键全自动用</span></div>' +
    '<div class="st-proj"><label for="stProj">项目</label>' + projSel + '</div>' +
    '<label class="st-l" for="stTopic">主题或完整口播文案<em>短的是主题，长的 / 多行按口播原文分段</em></label>' +
    '<textarea class="st-topic inp" id="stTopic" rows="4" spellcheck="false" placeholder="比如：三个被低估的 AI 用法。或者把整篇口播文案直接贴进来（原文不改，只分段）。">' + esc(STUDIO.topic) + '</textarea>' +
    (p ? '<label class="st-l" for="stTitle">发布标题<em>最多 30 字</em></label><input class="inp st-title" id="stTitle" maxlength="30" value="' + esc(p.title || p.name || '') + '">' +
      '<div class="st-2col"><div class="st-f"><label class="st-l" for="stDesc">简介</label><textarea class="inp st-desc" id="stDesc" rows="2" spellcheck="false">' + esc(p.desc || '') + '</textarea></div>' +
      '<div class="st-f"><label class="st-l" for="stTags">话题<em>空格隔开</em></label><input class="inp" id="stTags" spellcheck="false" value="' + esc((p.tags || []).join(' ')) + '"></div></div>' : '') +
    '<div class="st-2col"><div class="st-f"><span class="st-l">画幅</span><div class="seg st-ratio" role="group" aria-label="画幅">' +
    '<button data-st-ratio="9:16" aria-pressed="' + (curRatio === '9:16') + '">竖屏 9:16</button><button data-st-ratio="16:9" aria-pressed="' + (curRatio === '16:9') + '">横屏 16:9</button></div></div>' +
    '<div class="st-f"><label class="st-l" for="stSec">目标时长</label><select class="inp" id="stSec">' +
    secs.map(function (x) { return '<option value="' + x + '"' + (+x === +curSec ? ' selected' : '') + '>' + x + ' 秒</option>'; }).join('') + '</select></div></div>' +
    '<div class="st-2col"><div class="st-f"><label class="st-l" for="stStyle">风格</label><select class="inp" id="stStyle">' +
    styles.map(function (x) { return '<option' + (x === curStyle ? ' selected' : '') + '>' + esc(x) + '</option>'; }).join('') + '</select></div>' +
    '<div class="st-f"><label class="st-l" for="stVoice">配音音色</label><select class="inp" id="stVoice">' + stVoiceOptions(p) + '</select></div></div>' +
    '<div class="st-2col"><div class="st-f"><label class="st-l" for="stBgmStyle">配乐</label><select class="inp" id="stBgmStyle">' +
    ST_BGM.map(function (x) { return '<option value="' + esc(x[0]) + '"' + (bgmCur === x[0] ? ' selected' : '') + '>' + esc(x[0] === 'auto' ? x[1] : x[0]) + '</option>'; }).join('') + '</select></div>' +
    '<div class="st-f"><span class="st-l">字幕</span><button class="btn mini st-sub" data-st-sub="1" aria-pressed="' + subOn + '">烧录硬字幕</button></div></div>' +
    '<div class="st-vol"><label class="st-l" for="stBgmVol">配乐音量<em id="stBgmVolV">' + Math.round((p && p.settings && p.settings.bgm_volume != null ? p.settings.bgm_volume : prefs.bgmVol) * 100) + '%</em></label>' +
    '<input type="range" id="stBgmVol" min="0" max="60" step="5" value="' + Math.round((p && p.settings && p.settings.bgm_volume != null ? p.settings.bgm_volume : prefs.bgmVol) * 100) + '"></div>' +
    '<button class="btn primary st-plan" data-st="plan">AI 拆解分镜</button>' +
    '<div class="st-hint">先拆解看分镜，改好台词和画面再「一键全自动」；也可以直接一键全自动，用上面的主题现场拆。</div>';
  stPut('stIn', html);
}

/* ---------- 中间：分镜 ---------- */
function stTag(txt, st) {
  var cls = st === 'ok' ? 'ok' : st === 'run' ? 'run' : (st === 'err' || st === 'missing' || st === 'bad') ? 'bad' : st === 'stale' ? 'warn' : '';
  return '<span class="st-tag ' + cls + '">' + esc(txt) + '</span>';
}
function renderStBoard() {
  var p = studioProj(), j = studioJob(), run = studioRunning(), shots = (p && p.shots) || [];
  var head = '<div class="st-bh"><b>分镜</b><span class="num">' + shots.length + ' 镜 · ' + stClock(p && (p.total_seconds || p.target_seconds) || 0) + '</span><span class="sp"></span>' +
    '<button class="btn mini ghost" data-st="images"' + (run || !shots.length ? ' disabled' : '') + '>补图</button>' +
    '<button class="btn mini ghost" data-st="tts"' + (run || !shots.length ? ' disabled' : '') + '>补配音</button>' +
    '<button class="btn mini ghost" data-st="bgm"' + (run || !shots.length ? ' disabled' : '') + '>重做配乐</button>' +
    '<button class="btn mini ghost" data-st="video"' + (run || !shots.length ? ' disabled' : '') + '>重新合成</button></div>';
  var body;
  if (!shots.length) {
    body = '<div class="hm-none st-empty"><b>还没有分镜</b><span>在左边写主题，点「AI 拆解分镜」；或者直接点顶上「一键全自动生产」，让它现场拆。</span></div>';
  } else {
    body = '<div class="st-shots" id="stShots" role="list">' + shots.map(function (s) {
      var img = s.image_ok ? '<img src="' + esc(s.image_url) + '" alt="" loading="lazy">' : '<span>' + (s.image_st === 'run' ? '生图中…' : '待出图') + '</span>';
      var ist = s.image_st === 'ok' || s.image_ok ? 'ok' : s.image_st === 'run' ? 'run' : s.image_st === 'err' || s.image_st === 'missing' ? 'bad' : s.image_st === 'stale' ? 'stale' : 'idle';
      var tst = s.tts_st === 'ok' || s.tts_ok ? 'ok' : s.tts_st === 'run' ? 'run' : s.tts_st === 'err' || s.tts_st === 'missing' ? 'bad' : s.tts_st === 'stale' ? 'stale' : 'idle';
      return '<div class="st-shot' + (j && j.shot === s.id ? ' on' : '') + '" role="listitem" data-sid="' + esc(s.id) + '">' +
        '<div class="st-thumb"><i class="st-num">' + pad(s.n) + '</i>' + img + '</div>' +
        '<div class="st-sbody"><textarea class="st-text" data-st-text="' + esc(s.id) + '" rows="2" spellcheck="false" aria-label="第 ' + s.n + ' 镜台词">' + esc(s.text || '') + '</textarea>' +
        '<input class="st-prompt" data-st-prompt="' + esc(s.id) + '" value="' + esc(s.image_prompt || '') + '" spellcheck="false" aria-label="第 ' + s.n + ' 镜画面提示词">' +
        '<div class="st-smeta"><input class="st-tone" data-st-tone="' + esc(s.id) + '" value="' + esc(s.tone || '') + '" placeholder="语气" aria-label="语气">' +
        '<span class="num st-dur">' + (s.duration ? stClock(s.duration) : (s.seconds_hint ? Math.round(s.seconds_hint) + 's' : '—')) + '</span>' +
        stTag('图 ' + (ist === 'ok' ? '✓' : ist === 'run' ? '…' : ist === 'stale' ? '旧' : '×'), ist) +
        stTag('音 ' + (tst === 'ok' ? '✓' : tst === 'run' ? '…' : tst === 'stale' ? '旧' : '×'), tst) +
        '<span class="sp"></span><button class="linkbtn" data-st-img="' + esc(s.id) + '"' + (run ? ' disabled' : '') + '>重出这张图</button>' +
        '<button class="linkbtn" data-st-voice="' + esc(s.id) + '"' + (run ? ' disabled' : '') + '>重配这段</button></div>' +
        (s.image_err || s.tts_err ? '<div class="st-err">' + esc((s.image_err || s.tts_err || '').slice(0, 160)) + '</div>' : '') + '</div></div>';
    }).join('') + '</div>';
  }
  stPut('stBoard', head + body);
}

/* ---------- 右边：成片预览 ---------- */
function renderStOut() {
  var p = studioProj(), j = studioJob(), run = studioRunning(), files = (p && p.files) || {};
  var video = files.video, cover = files.cover, voice = files.voice, bgm = files.bgm;
  var html = '<div class="st-oh"><b>成片预览</b><span class="num" id="stJobPct">' + (run ? (j.pct || 0) + '%' : (p && p.video_ok ? '已就绪' : '')) + '</span></div>';
  if (run) {
    html += '<div class="st-runbar"><i style="transform:scaleX(' + Math.max(0.01, Math.min(1, (j.pct || 0) / 100)) + ')"></i></div>' +
      '<div class="st-runmsg">' + esc(j.msg || '正在跑…') + '</div>';
  } else if (j && j.st === 'err') {
    html += '<div class="st-runmsg bad">' + esc(j.err || j.msg || '出错了') + '</div>';
  } else if (p && p.error) {
    html += '<div class="st-runmsg bad">' + esc(p.error) + '</div>';
  }
  if (p && p.video_ok && video) {
    html += '<video class="st-video" controls preload="metadata" src="' + esc(video.url) + '"></video>' +
      '<div class="st-vinfo"><span>' + esc((p.resolution || '') + (p.duration ? ' · ' + p.duration.toFixed(1) + ' 秒' : '')) + '</span><span class="num">' + (video ? stSize(video.size) : '') + '</span></div>';
  } else {
    html += '<div class="st-vempty"><b>成片会在这里</b><span>' + (p && p.shots.length ? '素材齐了以后点「重新合成」或一键全自动' : '先拆解分镜') + '</span></div>';
  }
  if (video || cover) {
    html += '<div class="st-audios">' + (voice ? '<div class="st-audio"><span>配音</span><audio controls preload="metadata" src="' + esc(voice.url) + '"></audio></div>' : '') +
      (bgm ? '<div class="st-audio"><span>配乐</span><audio controls preload="metadata" src="' + esc(bgm.url) + '"></audio></div>' : '') + '</div>';
  }
  if (cover) html += '<div class="st-cover"><img src="' + esc(cover.url) + '" alt="封面"><span>封面</span></div>';
  var cost = [];
  if (p && p.cost) {
    if (p.cost.plan_cny) cost.push('拆解 ¥' + (+p.cost.plan_cny).toFixed(3));
    if (p.cost.images_usd) cost.push('生图 $' + (+p.cost.images_usd).toFixed(2));
    if (p.cost.tts_cny) cost.push('配音 ¥' + (+p.cost.tts_cny).toFixed(2));
  }
  if (cost.length) html += '<div class="st-cost">这一轮：' + esc(cost.join(' · ')) + '</div>';
  html += '<div class="st-obtns"><button class="btn mini ghost" data-st="open">打开输出文件夹</button>' +
    '<button class="btn mini primary" data-st="pub"' + (p && p.video_ok && useLive() ? '' : ' disabled') + '>送去抖音发布</button></div>' +
    '<button class="btn mini ghost st-goto" data-st="goto-pub">去「发布」窗口确认 ›</button>' +
    '<div class="st-hint">送去发布只是放进待确认队列，不会直接发；到「发布」看一眼、点两下才发。</div>';
  stPut('stOut', html);
}

/* ---------- 动作 ---------- */
function studioPrefsSave() { if (typeof saveUI === 'function') saveUI({ studio: STUDIO.pref }); }
function studioPatch(body) {
  var p = studioProj(); if (!p || !useLive()) return Promise.resolve();
  body.pid = p.id;
  return api('PUT', '/api/studio/project', body, 20000).then(function (j) {
    if (STUDIO.st) STUDIO.st.project = j.project;
    return j.project;
  }).catch(function (e) { toast(e.message, 6000); throw e; });
}
function studioCollectShots() {
  var out = [], rows = $$('#stBoard .st-shot');
  rows.forEach(function (row) {
    var id = row.dataset.sid, t = row.querySelector('[data-st-text]'), pr = row.querySelector('[data-st-prompt]'), tn = row.querySelector('[data-st-tone]');
    out.push({ id: id, text: t ? t.value : '', image_prompt: pr ? pr.value : '', tone: tn ? tn.value : '' });
  });
  return out;
}
function studioSaving(pr) {
  STUDIO.saving = pr;
  var clear = function () { if (STUDIO.saving === pr) STUDIO.saving = null; };
  pr.then(clear, clear);
  return pr;
}
function studioSaveShots() {
  var p = studioProj(); if (!p || !useLive()) return Promise.resolve();
  clearTimeout(STUDIO.saveT);
  return studioSaving(studioPatch({ shots: studioCollectShots() }).then(function () { STUDIO.sig.stBoard = ''; }).catch(function () {}));
}
function studioSaveMeta() {
  var p = studioProj(); if (!p || !useLive()) return Promise.resolve();
  clearTimeout(STUDIO.metaT);
  var title = ($('#stTitle') || {}).value, desc = ($('#stDesc') || {}).value, tags = ($('#stTags') || {}).value;
  if (title == null && desc == null && tags == null) return Promise.resolve();
  return studioSaving(studioPatch({ title: title || '', desc: desc || '', tags: tags || '' }).then(function () { STUDIO.sig.stIn = ''; }).catch(function () {}));
}
function studioWaitSaved() { return STUDIO.saving ? STUDIO.saving.catch(function () {}) : Promise.resolve(); }
function studioDo(path, body, okMsg) {
  if (!useLive()) { toast('演示模式：连上后端才能用'); return Promise.reject(); }
  return api('POST', '/api/studio/' + path, body || {}, 30000).then(function (j) {
    if (j && j.project) { if (!STUDIO.st) STUDIO.st = {}; STUDIO.st.project = j.project; STUDIO.sig = {}; renderStudio(true); }
    if (okMsg) toast(okMsg, 5000);
    return j;
  }).catch(function (e) { toast(e.message, 8000); throw e; });
}
function studioPlan() {
  if (STUDIO.saving) return studioWaitSaved().then(studioPlan);
  var s = (STUDIO.topic || '').trim();
  if (!s) { toast('先写一个主题，或者把完整口播文案贴进来'); var t = $('#stTopic'); if (t) t.focus(); return Promise.reject(); }
  if (studioProj() && !confirm('这会新建一个项目，原来的项目留着不删。继续？')) return Promise.resolve();
  var isScript = /\n/.test(s) || s.length > 60;
  var p = studioProj(), ratio = (p && p.ratio) || STUDIO.pref.ratio, style = (p && p.style) || STUDIO.pref.style;
  var sec = (p && p.target_seconds) || STUDIO.pref.seconds, voice = (p && p.settings && p.settings.voice && p.settings.voice.id) || STUDIO.pref.voice;
  var b = $('#stIn .st-plan'); if (b) { b.disabled = true; b.textContent = '正在拆解…'; }
  return studioDo('plan', { topic: isScript ? '' : s, text: isScript ? s : '', ratio: ratio, style: style, seconds: sec, voice_id: voice })
    .then(function (j) { STUDIO.st = j; STUDIO.sig = {}; renderStudio(true); toast('拆好了：' + j.project.shots.length + ' 个分镜', 5000); })
    .catch(function () {}).then(function () { if (b) { b.disabled = false; b.textContent = 'AI 拆解分镜'; } });
}
function studioRun(step, ids) {
  if (STUDIO.saving) return studioWaitSaved().then(function () { return studioRun(step, ids); });
  var p = studioProj(), topic = (STUDIO.topic || '').trim();
  var body = {};
  if (p) body.pid = p.id;
  else if (!topic) { toast('先在左边写主题，再一键全自动'); return Promise.reject(); }
  if (!p) {
    var s = topic, isScript = /\n/.test(s) || s.length > 60;
    body.topic = isScript ? '' : s; body.text = isScript ? s : '';
    body.ratio = STUDIO.pref.ratio; body.style = STUDIO.pref.style; body.seconds = STUDIO.pref.seconds;
    body.voice_id = STUDIO.pref.voice;
  }
  if (step) { body.mode = 'step'; body.step = step; }
  if (ids) body.ids = ids;
  return studioDo('run', body, step ? '' : '开始跑：图 → 配音 → 配乐 → 合成').then(function () { studioFetch(); });
}
function studioFetch() {
  if (!useLive()) { renderStudio(); return Promise.resolve(); }
  return api('GET', '/api/studio/state', null, 8000).then(function (j) {
    var was = STUDIO.st && STUDIO.st.job && STUDIO.st.job.st === 'run' ? STUDIO.st.job : null;
    STUDIO.st = j;
    var nav = $('.nav[data-tool="studio"]'); if (nav) nav.classList.toggle('on-busy', !!(j.job && j.job.st === 'run'));
    if (was && j.job && j.job.id === was.id && j.job.st !== 'run') toast('视频工坊：' + (j.job.msg || j.job.st), 7000);
    renderStudio();
  }).catch(function () {
    var v = $('#view-studio'); if (v && !STUDIO.st) { STUDIO.st = stDemo(); renderStudio(true); }
  });
}
function studioEnter() { studioFetch(); clearInterval(STUDIO.t); STUDIO.t = setInterval(function () { if (S.view === 'studio') studioFetch(); }, 1500); }
function studioLeave() { clearInterval(STUDIO.t); STUDIO.t = null; $$('#view-studio video, #view-studio audio').forEach(function (m) { try { m.pause(); } catch (e) {} }); }

/* ---------- 事件 ---------- */
(function () {
  var v = $('#view-studio'); if (!v) return;
  v.addEventListener('focusin', function (ev) { if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) STUDIO.editing = true; });
  v.addEventListener('focusout', function (ev) {
    if (!/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    setTimeout(function () {
      var a = document.activeElement;
      STUDIO.editing = !!(a && a.closest && a.closest('#view-studio') && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
      if (STUDIO.editing) return;
      var inShots = !!(ev.target.closest && ev.target.closest('#stShots'));
      var inMeta = ev.target.id === 'stTitle' || ev.target.id === 'stDesc' || ev.target.id === 'stTags';
      if (inShots) { studioSaveShots(); return; }          // 等这次保存回来，下一次轮询再重画，别把刚改的字冲掉
      if (inMeta) { studioSaveMeta(); return; }
      renderStudio(true);
    }, 160);
  });
  v.addEventListener('input', function (ev) {
    var t = ev.target;
    if (t.id === 'stTopic') { STUDIO.topic = t.value; if (typeof saveUI === 'function') saveUI({ studioTopic: t.value.slice(0, 4000) }); return; }
    if (t.id === 'stBgmVol') {
      var pct = +t.value; STUDIO.pref.bgmVol = pct / 100; var o = $('#stBgmVolV'); if (o) o.textContent = pct + '%';
      studioPrefsSave(); clearTimeout(STUDIO.saveT);
      STUDIO.saveT = setTimeout(function () { studioPatch({ settings: { bgm_volume: pct / 100 } }).catch(function () {}); }, 450);
      return;
    }
    if (t.id === 'stTitle' || t.id === 'stDesc' || t.id === 'stTags') {
      clearTimeout(STUDIO.metaT); STUDIO.metaT = setTimeout(studioSaveMeta, 600); return;
    }
    if (t.hasAttribute('data-st-text') || t.hasAttribute('data-st-prompt') || t.hasAttribute('data-st-tone')) {
      clearTimeout(STUDIO.saveT); STUDIO.saveT = setTimeout(studioSaveShots, 700);
    }
  });
  v.addEventListener('change', function (ev) {
    var t = ev.target, p = studioProj();
    if (t.id === 'stProj') { if (t.value) studioDo('select', { pid: t.value }).then(function (j) { STUDIO.st = j; STUDIO.sig = {}; renderStudio(true); }).catch(function () {}); return; }
    if (t.id === 'stTitle' || t.id === 'stDesc' || t.id === 'stTags') { studioSaveMeta(); return; }
    if (t.id === 'stSec') { STUDIO.pref.seconds = +t.value; studioPrefsSave(); if (p) studioPatch({ target_seconds: +t.value }).then(function () { renderStudio(true); }).catch(function () {}); return; }
    if (t.id === 'stStyle') { STUDIO.pref.style = t.value; studioPrefsSave(); if (p) studioPatch({ style: t.value }).then(function () { renderStudio(true); }).catch(function () {}); return; }
    if (t.id === 'stVoice') { STUDIO.pref.voice = t.value; studioPrefsSave(); if (p) studioPatch({ settings: { voice_id: t.value } }).then(function () { renderStudio(true); }).catch(function () {}); return; }
    if (t.id === 'stBgmStyle') {
      STUDIO.pref.bgm = t.value; studioPrefsSave();
      var preset = ST_BGM.filter(function (x) { return x[0] === t.value; })[0];
      if (p && preset && preset[0] !== 'auto') studioPatch({ bgm_prompt: preset[1] }).then(function () { renderStudio(true); }).catch(function () {});
      return;
    }
  });
  v.addEventListener('keydown', function (ev) {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter' && ev.target.id === 'stTopic') { ev.preventDefault(); studioPlan(); }
  });
  v.addEventListener('click', function (ev) {
    var b = ev.target.closest('button'); if (!b || b.disabled) return;
    var d = b.dataset, p = studioProj(), run = studioRunning();
    if (d.stRatio) {
      var r = d.stRatio; STUDIO.pref.ratio = r; studioPrefsSave();
      $$('#stIn [data-st-ratio]').forEach(function (x) { x.setAttribute('aria-pressed', String(x.dataset.stRatio === r)); });
      if (p) studioPatch({ ratio: r }).then(function () { renderStudio(true); toast('画幅改成 ' + r + '：图要重出，配音不用'); }).catch(function () {});
      return;
    }
    if (d.stSub) {
      var on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', String(on)); STUDIO.pref.subtitle = on; studioPrefsSave();
      if (p) studioPatch({ settings: { subtitle: on } }).then(function () { renderStudio(true); }).catch(function () {});
      return;
    }
    if (!d.st) return;
    if (run && d.st !== 'stop' && d.st !== 'refresh') { toast('正在跑，等它好了或者先点「停下」'); return; }
    if (d.st === 'refresh') { studioFetch(); return; }
    if (d.st === 'plan') { studioPlan(); return; }
    if (d.st === 'run') { studioRun(); return; }
    if (d.st === 'stop') { studioDo('stop', {}, '停下中：当前这一步收尾后不再往下做').then(function () { studioFetch(); }).catch(function () {}); return; }
    if (d.st === 'images' || d.st === 'tts' || d.st === 'bgm' || d.st === 'video') { studioRun(d.st).then(function () { studioFetch(); }); return; }
    if (d.stImg) { studioRun('images', [d.stImg]).then(function () { studioFetch(); }); return; }
    if (d.stVoice) { studioRun('tts', [d.stVoice]).then(function () { studioFetch(); }); return; }
    if (d.st === 'open') { studioDo('open', { what: 'output' }, '打开输出文件夹').catch(function () {}); return; }
    if (d.st === 'pub') {
      studioDo('to_publish', {}, '').then(function (j) { toast(j.msg || '放进发布窗口了', 7000); STUDIO.sig.stOut = ''; renderStudio(true); }).catch(function () {});
      return;
    }
    if (d.st === 'goto-pub') { openView('publish'); return; }
  });
})();
