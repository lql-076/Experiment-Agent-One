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
    case 'choice': return '<div class="field"><label>' + esc(f.l) + '</label><div class="seg choice" role="group" aria-label="' + esc(f.l) + '">' + f.o.map(function (o) {
      return '<button data-choice="' + f.k + '" data-v="' + (o[0] ? 1 : 0) + '" aria-pressed="' + (!!v === !!o[0]) + '">' + esc(o[1]) + '</button>'; }).join('') + '</div>' + help + '</div>';
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
  if (sec.custom === 'cloud') h += '<div class="balrow">' + balanceHTML() + searchHTML() + '</div>';
  if (sec.custom === 'osd') h += osdHTML() + '<div id="fpsSeen">' + fpsSeenHTML() + '</div>';
  if (sec.custom === 'hw') h += '<div id="hwCtl">' + hwCtlHTML() + '</div>';
  if (sec.custom === 'models') h += '<div id="ttsInst">' + ttsInstHTML() + '</div>';
  if (sec.custom === 'auto') h += '<div id="autoSt">' + autoStHTML() + '</div>';
  if (sec.custom === 'memory') { h += '<div id="wsBox">' + wsHTML() + '</div><div id="rdirs">' + rdirsHTML() + '</div>'; if (useLive() && !RDIRS.ts) fetchRdirs(); if (useLive() && !WS.ts) fetchWs(); }
  if (sec.custom === 'agent') { h += '<div id="capsBox">' + capsHTML() + '</div>'; if (useLive()) capsFetch(); }
  if (sec.custom === 'voice') { h += '<div id="voiceBox">' + voiceBoxHTML() + '</div>'; if (useLive()) voiceBoxFetch(); }
  if (sec.custom === 'bgm') { h += '<div id="bgmBox">' + bgmBoxHTML() + '</div>'; if (useLive()) bgmBoxFetch(); }
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
/* 游戏内显示：选显示哪几项 + 预览（和游戏里那个小框同一套规则，见 app/osd.py 的 lines） */
var OSD_ITEMS = [['fps', '帧数'], ['low1', '1% 低帧'], ['cpu', 'CPU'], ['gpu', '显卡'], ['vram', '显存'], ['ram', '内存'], ['power', '整机功耗'], ['time', '时间']];
var OSD_COL = { fps: '#5fe0b0', low1: '#ffd166', cpu: '#3fc6ff', gpu: '#b49bff', vram: '#ff8fc0', ram: '#8fe3a5', power: '#ffb547', time: '#e8eaf0', hot: '#ff5d5d' };
function osdItems() { return String(S.set.osdItems || DEFAULTS.osdItems).split(',').filter(Boolean); }
function osdLines() {
  var n = function (x, d) { return x == null || isNaN(x) ? null : (+x).toFixed(d || 0); };
  var fps = HW.fps || null, out = [];
  osdItems().forEach(function (k) {
    if (k === 'fps') out.push(['FPS', (fps && n(fps.fps)) || '—', OSD_COL.fps]);
    else if (k === 'low1') out.push(['1% 低', (fps && n(fps.low1)) || '—', OSD_COL.low1]);
    else if (k === 'cpu') out.push(['CPU', [(n(HW.cpu.load) || '—') + '%', n(HW.cpu.temp) && n(HW.cpu.temp) + '°C', n(HW.cpu.power) && n(HW.cpu.power) + 'W'].filter(Boolean).join('  '), (HW.cpu.temp || 0) >= 85 ? OSD_COL.hot : OSD_COL.cpu]);
    else if (k === 'gpu') out.push(['GPU', [(n(HW.gpu.load) || '—') + '%', n(HW.gpu.temp) && n(HW.gpu.temp) + '°C', n(HW.gpu.power) && n(HW.gpu.power) + 'W'].filter(Boolean).join('  '), (HW.gpu.temp || 0) >= 83 ? OSD_COL.hot : OSD_COL.gpu]);
    else if (k === 'vram') out.push(['显存', (n(HW.gpu.vram, 1) || '—') + ' / ' + (n(HW.gpu.vramTotal) || '—') + ' G', OSD_COL.vram]);
    else if (k === 'ram') out.push(['内存', (n(HW.ram && HW.ram.used, 1) || '—') + ' / ' + (n(HW.ram && HW.ram.total) || '—') + ' G', OSD_COL.ram]);
    else if (k === 'power') out.push(['整机', n(HW.sys && HW.sys.power) ? '≈' + n(HW.sys.power) + ' W' : '—', OSD_COL.power]);
    else if (k === 'time') { var d = new Date(); out.push(['时间', pad(d.getHours()) + ':' + pad(d.getMinutes()), OSD_COL.time]); }
  });
  return out;
}
function osdBoxHTML() {
  var h = S.set.osdLayout === 'h', size = ({ s: .62, m: .72, l: .88 }[S.set.osdSize] || .72) * (h ? .82 : 1);
  return '<div class="osd-box pos-' + (S.set.osdPos || 'tl') + (h ? ' lay-h' : '') + '" style="--m:' + Math.round((+S.set.osdMargin || 16) / 4) + 'px;--a:' + ((+S.set.osdOpacity || 80) / 100) + ';font-size:' + size.toFixed(3) + 'rem">' +
    osdLines().map(function (l) { var x = '<span class="ol">' + esc(l[0]) + '</span><b style="color:' + l[2] + '">' + esc(l[1]) + '</b>'; return h ? '<span class="op">' + x + '</span>' : x; }).join('') + '</div>';
}
function osdHTML() {
  var on = osdItems();
  return '<div class="osd-top"><div class="osd-prev" id="osdPrev" aria-label="预览：游戏画面一角的样子"><span class="osd-game">游戏画面（预览）</span>' + osdBoxHTML() + '</div>' +
    '<div class="osd-pick"><div class="label">显示哪几项（点一下开关）</div><div class="osd-chips">' + OSD_ITEMS.map(function (it) {
      return '<button class="chip" data-osd-item="' + it[0] + '" aria-pressed="' + (on.indexOf(it[0]) >= 0) + '">' + it[1] + '</button>';
    }).join('') + '</div><p class="help">预览里的数字是现在的真实读数' + (liveHW() ? '' : '（演示）') + '。帧数要在玩游戏、并且「硬件监控助手」开着时才有。</p></div></div>';
}
function osdPreview() { var p = $('#osdPrev'); if (!p) return; var b = p.querySelector('.osd-box'); if (b) b.outerHTML = osdBoxHTML(); osdFitPrev(); }
/* 横着一行在预览的小画面里放不下时，按比例缩小字（游戏里是一整行，预览也画成一整行） */
function osdFitPrev() {
  var p = $('#osdPrev'), b = p && p.querySelector('.osd-box.lay-h'); if (!b || !p.clientWidth) return;
  var room = p.clientWidth - 16, w = b.scrollWidth;
  if (w > room) b.style.fontSize = (parseFloat(b.style.fontSize) * room / w).toFixed(3) + 'rem';
}
setInterval(function () {
  if (S.view !== 'settings') return;
  if (S.sec === 'osd') { osdPreview(); var f = $('#fpsSeen'), x = fpsSeenHTML(); if (f && f.innerHTML !== x) f.innerHTML = x; }
  if (S.sec === 'hw') { var c = $('#hwCtl'), y = hwCtlHTML(); if (c && c.innerHTML !== y) c.innerHTML = y; }
}, 1000);

/* 游戏识别：哪个程序被当成了游戏（帧数从它读）。游戏加加、播放器这类内置就排除了；还有认错的，点「这不是游戏」 */
function fpsSkipList() { return String(S.set.fpsSkip || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean); }
var FPS_DEMO = [{ proc: 'Palworld-Win64-Shipping.exe', fps: 98, fg: true, skipped: false }, { proc: 'SomeOverlay.exe', fps: 60, fg: false, skipped: false }];
function fpsSeenHTML() {
  var live = liveHW(), seen = live ? (HW.fpsSeen || []) : FPS_DEMO, skip = fpsSkipList(), cur = live ? HW.fps && HW.fps.proc : seen[0].proc;
  var helper = !live || (HW.sources && HW.sources.sensors);
  var rows = !helper ? '<div class="help">要先打开硬件监控助手（设置 › 硬件监控），才知道哪个程序在出画面。</div>'
    : !seen.length ? '<div class="help">现在没有程序在出画面。打开游戏后，这里会显示它被认成了游戏。</div>'
    : seen.map(function (c) {
      var nm = String(c.proc || '').replace(/\.exe$/i, ''), isCur = !c.skipped && c.proc === cur;
      return '<div class="fps-row' + (isCur ? ' cur' : '') + (c.skipped ? ' skipped' : '') + '"><b>' + esc(nm) + '</b><span class="num">' + (c.fps == null ? '—' : c.fps) + ' 帧</span>' +
        '<span class="cap">' + (c.skipped ? '你说过不是游戏' : isCur ? '← 现在当作游戏' + (c.fg ? '' : '（不在最前面）') : c.fg ? '在最前面' : '在后台出画面') + '</span>' +
        (c.skipped ? '<button class="btn mini" data-fps-unskip="' + esc(c.proc) + '">其实是游戏</button>' : '<button class="btn mini" data-fps-skip="' + esc(c.proc) + '">这不是游戏</button>') + '</div>';
    }).join('');
  return '<div class="fps-seen"><div class="label">游戏识别 · 正在出画面的程序</div>' + rows +
    (skip.length ? '<div class="fps-skip"><span class="cap">你排除的：</span>' + skip.map(function (x) { return '<button class="chip" data-fps-unskip="' + esc(x) + '" title="点一下取消排除">' + esc(x.replace(/\.exe$/i, '')) + ' ×</button>'; }).join('') + '</div>' : '') +
    '<p class="help">游戏加加、视频和音乐播放器、录屏、浏览器、聊天软件本来就不算游戏。「只在玩游戏时」显示：游戏在最前面才显示，切到桌面或别的窗口就藏起来。</p></div>';
}

/* 硬件监控助手的开关：开着就跟着 Agent 一起起（app/hwctl.py） */
var HWCTL = { busy: false, msg: '' };
function hwCtlHTML() {
  var on = !!S.set.hwOn, live = useLive(), run = live ? !!(HW.sources && HW.sources.sensors) : true;
  var st = HWCTL.busy ? ['warn', '正在打开……'] : run ? ['ok', '运行中'] : on ? ['warn', '开着，但没在运行'] : ['off', '关着'];
  var detail = HWCTL.busy ? '第一次会弹一次管理员确认，点「是」。' : run ? (live && HW.sources && HW.sources.cpuTemp === false ? 'CPU 温度、功耗读不到：要装 PawnIO 驱动（pawnio.eu），装完重启电脑。显卡、硬盘、帧数照常。' : '读得到 CPU 温度、功耗、硬盘温度和游戏帧数。')
    : on ? (HWCTL.msg || '后台会自己把它拉起来，稍等。') : '关着时 CPU 温度、功耗、硬盘温度和游戏帧数读不到；显卡和内存照常（驱动自带）。';
  return '<div class="balbox hwctl"><div><span class="label">硬件监控助手</span><div class="hwc-st st-' + st[0] + '"><i></i><b>' + st[1] + '</b></div>' +
    '<div class="help">' + esc(detail) + '<br>要管理员权限才读得到。打开后跟着 Agent 一起启动、退出 Agent 时一起关；第一次弹一次管理员确认，之后不再弹，也没有黑窗口。</div></div>' +
    '<div class="btnrow"><span class="cap">' + (on ? '开着 · 跟着 Agent 起' : run ? '没设成跟着 Agent 起' : '关着') + '</span><button class="switch" role="switch" id="hwHelperSw" aria-label="硬件监控助手开关" aria-checked="' + on + '"' + (live && !HWCTL.busy ? '' : ' disabled') + '></button></div></div>';
}

/* 开机自启（app/autostart.py）：写当前用户的启动项，不要管理员；开机自启.bat 建的旧任务也认得出 */
var AUTOST = { st: null, busy: false };
function autoLoad() {
  if (!useLive()) return;
  api('GET', '/api/autostart', null, 15000).then(function (r) { AUTOST.st = r; var c = $('#autoSt'); if (c) c.innerHTML = autoStHTML(); }).catch(function () {});
}
function autoStHTML() {
  var a = AUTOST.st, live = useLive(), on = !!(a && a.on);
  var st = !live ? ['off', '演示数据'] : !a ? ['off', '正在读取…'] : !a.ok ? ['off', a.msg] : AUTOST.busy ? ['warn', '正在改…'] : on ? ['ok', '开着'] : ['off', '关着'];
  var how = a && a.ok && a.task && !a.run ? '现在用的是「开机自启.bat」建的计划任务。' : '';
  return '<div class="balbox hwctl"><div><span class="label">开机自启</span><div class="hwc-st st-' + st[0] + '"><i></i><b>' + esc(st[1]) + '</b></div>' +
    '<div class="help">' + how + '登录 Windows 后自动启动 Agent、打开界面。打开：写进你这个账号的启动项，不要管理员、不弹确认、没有黑窗口。' +
    '关掉：以前用「开机自启.bat」开过的话，删那个旧任务要弹一次管理员确认。两个 bat 都留着备用。' +
    (a && a.other ? '<br>启动项里原来指向别的文件夹（' + esc(a.other) + '），打开会改成现在这个。' : '') + '</div></div>' +
    '<div class="btnrow"><button class="switch" role="switch" id="autoSw" aria-label="开机自启开关" aria-checked="' + on + '"' + (live && a && a.ok && !AUTOST.busy ? '' : ' disabled') + '></button></div></div>';
}

/* 联网搜索：今天搜了几次 / 上限、这个月多少次花了多少；能现场测一次 */
function searchStats() {
  if (!useLive()) return { on: true, limit: 200, today: { n: 7, cny: 0.04 }, month: { n: 86, cny: 0.46 } };
  return (D.state && D.state.search) || { on: !!S.set.searchOn, limit: S.set.searchDaily, today: { n: 0, cny: 0 }, month: { n: 0, cny: 0 } };
}
function searchHTML() {
  var s = searchStats();
  return '<div class="balbox" id="searchBox"><div><span class="label">联网搜索 · DeepSeek 搜索引擎</span><div class="big num" style="margin:.35rem 0">' + s.today.n + '<small style="font-size:.5em;color:var(--text3)"> / ' + s.limit + ' 次</small></div>' +
    '<div class="help">今天搜了几次（搜索和读网页都算）' + (s.on ? '' : ' · <b style="color:var(--bad)">现在关着</b>') + '<br>这个月 ' + s.month.n + ' 次，约 ¥' + (+s.month.cny).toFixed(2) + (useLive() ? '' : '（演示）') + '</div>' +
    '<div class="help" id="searchOut" hidden></div></div>' +
    '<div class="btnrow"><button class="btn" id="searchTest"' + (useLive() ? '' : ' disabled') + '>测试一下</button></div></div>';
}
function renderSettings() {
  $('#view-settings').innerHTML = '<div class="settings"><nav class="snav" aria-label="设置分类">' +
    SECTIONS.map(function (s) { return '<button class="sitem" data-sec="' + s.id + '" aria-current="' + (s.id === S.sec) + '">' + s.name + (s.id === 'prep' ? '<em class="num" id="prepMini">' + readyCount() + '/' + LIVE_CHECKS.length + '</em>' : '') + '</button>'; }).join('') +
    '</nav><div class="sbody" id="sbody"></div></div>';
  $('#sbody').innerHTML = sectionBody(secById(S.sec));
  if (S.sec === 'remind') fetchReminders();
  if (S.sec === 'prep') setupPoll();
  if (S.sec === 'osd') requestAnimationFrame(osdFitPrev);
  secOpened(S.sec);
}
/* 打开某个分区时要现查的：配音装没装（本地模型）、开机自启开没开（自动化） */
function secOpened(id) { if (id === 'models') ttsInstLoad(); if (id === 'auto') autoLoad(); }
function goSec(id) {
  if (S.sec === id) return;
  S.sec = id; S.resetArm = false;
  $$('.sitem').forEach(function (b) { b.setAttribute('aria-current', b.dataset.sec === id); });
  var b = $('#sbody');
  var fill = function () { b.innerHTML = sectionBody(secById(id)); b.scrollTop = 0; if (id === 'remind') fetchReminders(); if (id === 'prep') setupPoll(); if (id === 'osd') requestAnimationFrame(osdFitPrev); secOpened(id); };
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
  if (k.indexOf('osd') === 0) osdPreview();
  if (k === 'strongName' || k === 'strongOn') { syncRouteNames(); renderChat(); renderEvents(); renderHome(true); }
  if (k === 'autoScale') requestAnimationFrame(function () { placeInd(true); });
  if (k === 'uiShell') toast('下次启动 Agent 时生效');
  if (k.indexOf('voice') === 0 && useLive()) setTimeout(voiceBoxFetch, 900);
  if (k.indexOf('bgm') === 0 && useLive()) setTimeout(bgmBoxFetch, 900);
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
/* Agent 自己的工作文件夹（v2.1，app/workspace.py）：在里面写、改、删、挪、运行程序都不用问你；改和删之前旧的先进备份，备份半年清一次、出清单。
   换位置、开关「能运行程序」= 给 agent 的权限，只能在这里点（记进动作日志） */
var WS = { st: null, ts: 0 };
var WS_DEMO = { dir: 'F:\\Agent\\工作区', default: true, exists: true, files: 12, size: 3456789, backup: 'F:\\Agent\\工作区备份', backup_files: 4, backup_size: 23456, run: true,
  timeout: 900, keep_days: 182, env: true, ffmpeg: true, playwright: false, last_clean: null, next_clean: Date.now() / 1000 + 150 * 86400, last_n: 0, last_list: '' };
function wsDay(t) { if (!t) return '—'; var d = new Date(t * 1000); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
function wsSize(n) { n = +n || 0; return n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n >= 1024 ? Math.round(n / 1024) + ' KB' : n + ' B'; }
function wsHTML() {
  var w = useLive() ? WS.st : WS_DEMO;
  if (!w) return '<div class="field"><label>Agent 的工作文件夹</label><div class="cap">正在读取…</div></div>';
  return '<div class="field wsbox"><label for="wsDir">Agent 的工作文件夹（能写、能删、能运行程序）</label>' +
    '<div class="help">它自己的地方：在这个文件夹里写、改、删、挪文件、运行程序（python、ffmpeg 这些）都不用问你；改和删之前旧的先放进备份，备份半年清一次、清的时候出一份清单。别的地方照旧只读。</div>' +
    '<div class="ws-row"><span class="rd-path" title="' + esc(w.dir) + '">' + esc(w.dir) + (w.default ? '<em class="ok">默认</em>' : '') + '</span><span class="num">' + w.files + ' 个文件 · ' + wsSize(w.size) + '</span>' +
      '<button class="btn mini" data-ws-open="ws">打开</button></div>' +
    '<div class="ws-row"><span>备份<b class="num">' + w.backup_files + ' 个 · ' + wsSize(w.backup_size) + '</b></span><span>上次清理<b>' + (w.last_clean ? wsDay(w.last_clean) + '（清了 ' + w.last_n + ' 个）' : '还没清过') + '</b></span>' +
      '<span>下次清理<b class="num">' + wsDay(w.next_clean) + '</b></span><span class="sp"></span><button class="btn mini" data-ws-open="backup">打开备份</button>' + (w.last_list ? '<button class="btn mini" data-ws-open="list">看清理清单</button>' : '') + '</div>' +
    '<div class="ws-row"><label class="rd-cl"><button class="switch" role="switch" data-ws-run aria-checked="' + !!w.run + '" aria-label="能运行程序"></button>能运行程序</label>' +
      '<span class="ws-env">Python 环境：' + (w.env ? '有了' : '第一次运行时自动建') + ' · ffmpeg：' + (w.ffmpeg ? '有' : '它要用时自己装') + ' · 网页录屏：' + (w.playwright ? '有' : '它要用时自己装') + '</span></div>' +
    '<div class="secret"><input class="inp" id="wsDir" spellcheck="false" placeholder="换个地方：完整路径，比如 F:\\Agent工作区（留空 = 默认）"><button class="btn" data-ws-dir' + (useLive() ? '' : ' disabled') + '>换位置</button></div></div>';
}
function fetchWs() { api('GET', '/api/ws').then(function (j) { WS.st = j; WS.ts = Date.now(); var b = $('#wsBox'); if (b) b.innerHTML = wsHTML(); }).catch(function () {}); }
function wsDo(body) { return api('PUT', '/api/ws', body).then(function (j) { WS.st = j; WS.ts = Date.now(); var b = $('#wsBox'); if (b) b.innerHTML = wsHTML(); return j; }); }
function wsOpen(what) { return api('POST', '/api/ws/open', { what: what || 'ws' }).then(function (j) { toast(j.msg, 4000); }).catch(function (e) { toast(e.message); }); }
/* 能读的文件夹（v1.8.17，app/files.py）：只读；加一个 = 给 agent 加权限，只能在这里点（或者在对话里点「允许读这个文件夹」） */
var RDIRS = { list: [], ts: 0 };
var RDIRS_DEMO = [{ path: 'E:\\gongzuochengxu\\笔记仓库', show: 'E:\\gongzuochengxu\\笔记仓库', cloud: true, exists: true }];
function rdirsHTML() {
  var list = useLive() ? RDIRS.list : RDIRS_DEMO;
  return '<div class="field rdirs"><label for="rdNew">能读的文件夹（只读）</label>' +
    '<div class="help">在对话里问它「我笔记里 XX 是怎么写的」、或者直接贴文件路径，它能翻这些文件夹（列目录、搜、读 .md .txt .docx、代码、表格、图片）；只读，不改、不删。关掉「能发给 DeepSeek」的文件夹只给本地小脑看。</div>' +
    (list.length ? '<div class="rd-list">' + list.map(function (d) {
      return '<div class="rd-row"><span class="rd-path" title="' + esc(d.show || d.path) + '">' + esc(d.show || d.path) + (d.exists ? '' : '<em>（找不到了）</em>') + '</span>' +
        '<label class="rd-cl"><button class="switch" role="switch" data-rd-cloud="' + esc(d.path) + '" aria-checked="' + !!d.cloud + '" aria-label="能发给 DeepSeek"></button>能发给 DeepSeek</label>' +
        '<button class="btn mini" data-rd-del="' + esc(d.path) + '">不让读了</button></div>';
    }).join('') + '</div>' : '<div class="cap" style="margin:.4rem 0">还没有。加了以后它才能读你电脑上的文件。</div>') +
    '<div class="secret"><input class="inp" id="rdNew" spellcheck="false" placeholder="文件夹的完整路径，比如 E:\\gongzuochengxu\\笔记仓库"><button class="btn primary" data-rd-add' + (useLive() ? '' : ' disabled') + '>允许读</button></div></div>';
}
function fetchRdirs() {
  api('GET', '/api/files/dirs').then(function (j) { RDIRS.list = j.dirs; RDIRS.ts = Date.now(); var b = $('#rdirs'); if (b) b.innerHTML = rdirsHTML(); }).catch(function () {});
}
function rdirsDo(method, body, path) {
  return api(method, '/api/files/dirs' + (path ? '?path=' + encodeURIComponent(path) : ''), body).then(function (j) {
    RDIRS.list = j.dirs; RDIRS.ts = Date.now(); var b = $('#rdirs'); if (b) b.innerHTML = rdirsHTML(); return j;
  });
}
/* ---------- Agent 能力（v3.0）：给它哪些本事。这些是权限，走自己的接口（/api/agent/caps），每次开关都记进动作日志 ---------- */
var CAPS = { st: null };
var CAPS_DEMO = { caps: { download: true, voice: true, voice_cloud: false, image: false, image_key: true, music: true, music_ready: false, voice_env: true, cc: false },
  cc: { on: false, found: true, path: 'C:\\Users\\你\\AppData\\Roaming\\npm\\claude.cmd', version: '2.1.x (Claude Code)', bash: 'python,pip,ffmpeg,ffprobe,node,npm,npx,git' },
  skills: [{ name: '做视频', use: '用网页动画 + 配音 + 配乐做一条视频（片头、讲解、口播都行）', mine: false }],
  toolbox: [{ name: '录网页.py', use: '把一个网页动画录成视频（一帧一帧截图再合成，不掉帧）' }, { name: '合成.py', use: '把画面、配音、配乐、字幕合成一个视频' }, { name: '口型.py', use: '让一张角色图跟着配音张嘴、眨眼' }] };
var CAP_ROWS = [['download', '从网上下载文件到工作区', '只下公网上的（http / https），本机和局域网的地址不碰；单个最大 500MB'],
  ['voice', '自己配音（本地）', '用「配音」页上次用的那套音色，出音频 + 每句的时间 + 字幕，直接放进工作区。不花钱'],
  ['voice_cloud', '配音可以用云端（百炼）', '要花钱，文案会发给百炼。关着就只用本地的'],
  ['music', '自己出配乐（ACE-Step）', '本地出纯音乐，不花钱。要先在 设置 › 配乐 里配好'],
  ['image', '自己生图（API易）', '要花钱：每张按「生图」页选的模型算，一件事最多出几张在上面设。提示词和参考图会发给 API易']];
function capsHTML() {
  var c = useLive() ? CAPS.st : CAPS_DEMO;
  if (!c) return '<div class="field"><div class="cap">正在读取…</div></div>';
  var cc = c.cc || {}, k = c.caps || {}, dis = useLive() ? '' : ' disabled';
  var ccLine = !cc.found ? '<em class="bad">没找到 claude 命令</em>：装了 Claude Code 的话，把 claude 在哪填在下面' : '<em class="ok">找到了</em> ' + esc(cc.version || '') + ' · ' + esc(cc.path || '');
  return '<div class="capbox"><div class="cap-h"><b>Claude Code 引擎</b><span class="sp"></span><button class="switch" role="switch" data-cap="cc" aria-checked="' + !!k.cc + '" aria-label="打开 Claude Code 引擎"' + dis + '></button></div>' +
      '<div class="help">开了以后，工作文件夹里的活（写程序、做视频、整理文件）交给你本机的 Claude Code 来动手：它的每一步、它列的待办清单都显示在主页「现在」里，能停下、能说「继续」接着同一个会话做。' +
      '用的是你自己已经登录好的 Claude Code（走它自己的额度），Agent 不读、不改它的任何设置，只是在工作文件夹里把它叫起来。它在那里只能读写文件和跑下面名单里的命令；没跑起来就退回 DeepSeek 自己做。</div>' +
      '<div class="cap-st">' + ccLine + '</div>' +
      '<div class="secret"><input class="inp" id="ccCmd" spellcheck="false" placeholder="claude 在哪（留空 = 自动找）" value="' + esc(cc.cmd || '') + '"><button class="btn" data-cap-set="cc_cmd"' + dis + '>保存</button></div>' +
      '<div class="secret"><input class="inp" id="ccBash" spellcheck="false" placeholder="它能跑哪些命令，逗号隔开" value="' + esc(cc.bash || '') + '"><button class="btn" data-cap-set="cc_bash"' + dis + '>保存</button></div>' +
      '<div class="help">能跑的命令只认名字（python、ffmpeg 这种），别的一律不让跑。' + (cc.log ? '它的原始输出记在 ' + esc(cc.log) : '') + '</div></div>' +
    '<div class="fields capsw">' + CAP_ROWS.map(function (r) {
      var warn = r[0] === 'image' && !k.image_key ? '（还没填 API易 的 Key）' : r[0] === 'music' && !k.music_ready ? '（ACE-Step 还没配好）' : r[0] === 'voice' && !k.voice_env ? '（本地配音还没装）' : '';
      return '<div class="field row"><div><label>' + r[1] + (warn ? '<em class="warn">' + warn + '</em>' : '') + '</label><div class="help">' + r[2] + '</div></div><button class="switch" role="switch" data-cap="' + r[0] + '" aria-checked="' + !!k[r[0]] + '" aria-label="' + r[1] + '"' + dis + '></button></div>'; }).join('') + '</div>' +
    '<div class="capbox"><div class="cap-h"><b>技能</b><span class="cap">' + (c.skills || []).length + ' 份 · 做某类事的成套做法，它用到时自己翻</span><span class="sp"></span><button class="btn mini" data-ws-open="ws"' + dis + '>打开工作区</button></div>' +
      (c.skills || []).map(function (x) { return '<div class="cap-row"><b>' + esc(x.name) + '</b><span>' + esc(x.use || '') + '</span><em>' + (x.mine ? '你写的' : '自带') + '</em></div>'; }).join('') +
      '<div class="help">想教它一套新做法：在 工作区\\技能\\ 里放一个 .md 文件（第一行标题，下面写「用在：一句话」「触发：正则」再写步骤），它马上就认。</div>' +
      '<div class="cap-h" style="margin-top:1rem"><b>工具箱</b><span class="cap">' + (c.toolbox || []).length + ' 个脚本 · 每次干活前同步进 工作区\\工具箱\\</span></div>' +
      (c.toolbox || []).map(function (x) { return '<div class="cap-row"><b>' + esc(x.name) + '</b><span>' + esc(x.use || '') + '</span></div>'; }).join('') + '</div>';
}
function capsFetch() { api('GET', '/api/agent/caps?deep=1').then(function (j) { CAPS.st = j; var b = $('#capsBox'); if (b) b.innerHTML = capsHTML(); }).catch(function () {}); }
function capsPut(body, msg) { return api('PUT', '/api/agent/caps', body).then(function (j) { CAPS.st = j; var b = $('#capsBox'); if (b) b.innerHTML = capsHTML(); if (msg) toast(msg, 5000); }).catch(function (e) { toast(e.message, 6000); capsFetch(); }); }
/* ---------- 语音（v3.0） ---------- */
var VBOX = { st: null, inst: null };
var VBOX_DEMO = { on: false, engine: 'local', asr: false, asr_why: '听写模型还没下（约 1.9 GB）', tts_env: true, ref: false, up: false, alive: false, can_start: false, url: 'http://127.0.0.1:8093' };
function voiceBoxHTML() {
  var v = useLive() ? VBOX.st : VBOX_DEMO, dis = useLive() ? '' : ' disabled';
  if (!v) return '<div class="field"><div class="cap">正在读取…</div></div>';
  var mouth = v.engine === 'breeze' ? '<em class="ok">Breeze TTS 2</em>' + (v.up ? ' · 连得上' : v.can_start ? ' · 用到才启动' : ' · <em class="warn">现在连不上（' + esc(v.url) + '）</em>')
    : v.engine === 'local' ? '<em class="ok">本地配音顶着</em>（Breeze 还没配好：' + (v.up ? '' : '地址连不上，') + '配好了自动换成它）' : '<em class="bad">还没有能出声的</em>：配 Breeze，或者先在 设置 › 本地模型 里把本地配音装上';
  return '<div class="capbox"><div class="cap-row"><b>听（你说的话变成字）</b><span>' + (v.asr ? '<em class="ok">装好了</em> 本地 Qwen3-ASR，跑在配音服务里（用到才启动，约多占 2GB 显存）' : '<em class="warn">还没装</em> ' + esc(v.asr_why || '')) + '</span>' +
      (v.asr ? '' : '<button class="btn mini primary" data-voice-asr="1"' + dis + (v.tts_env ? '' : ' disabled title="先在 设置 › 本地模型 里装好本地配音"') + '>安装听写（约 1.9 GB）</button>') + '</div>' +
    '<div class="cap-row"><b>说（它的回答念出来）</b><span>' + mouth + '</span><button class="btn mini" data-voice-test="1"' + dis + '>说一句试试</button>' + (v.alive ? '<button class="btn mini ghost" data-voice-off="1">关掉 Breeze</button>' : '') + '</div>' +
    '<div class="cap-row"><b>声音照谁的</b><span>' + (v.ref ? '<em class="ok">有参考音频</em>：照它的声音念（记得把音频里说的话填在下面「参考音频里念的字」）' : '没放参考音频：按下面那句「声音是什么样的」造一个') + '</span>' +
      '<label class="btn mini" for="voiceRefFile"' + (useLive() ? '' : ' aria-disabled="true"') + '>' + (v.ref ? '换一段' : '放一段参考音频') + '</label><input type="file" id="voiceRefFile" accept=".wav,audio/wav" hidden' + dis + '>' + (v.ref ? '<button class="btn mini ghost" data-voice-unref="1">去掉</button>' : '') + '</div>' +
    '<div class="help">参考音频：3~30 秒、16 位 WAV、你自己有权用的声音。麦克风只在你点了核心 / 话筒以后才开，收住就关；录音不存盘。快捷键：Alt + V 开始说，Esc 打断。</div></div>';
}
function voiceBoxFetch() { api('GET', '/api/voice').then(function (j) { VBOX.st = j; var b = $('#voiceBox'); if (b) b.innerHTML = voiceBoxHTML(); }).catch(function () {}); }
/* ---------- 配乐（v3.0） ---------- */
var BBOX = { st: null };
function bgmBoxHTML() {
  var v = useLive() ? BBOX.st : { up: false, alive: false, configured: false, can_start: false, url: 'http://127.0.0.1:8001', out: 'F:\\Agent\\配乐输出' };
  if (!v) return '<div class="field"><div class="cap">正在读取…</div></div>';
  var line = v.alive ? '<em class="ok">开着</em>（Agent 开的，闲着会自己关）' : v.up ? '<em class="ok">连得上</em>（你自己开着的）' : v.can_start ? '<em class="ok">配好了</em>：用到才启动' + (v.python ? ' · ' + esc(v.python) : '')
    : v.dir && !v.dir_ok ? '<em class="bad">这个文件夹不存在</em>：' + esc(v.dir) : '<em class="warn">还没配</em>：' + esc(v.url) + ' 连不上，也没填 ACE-Step 的文件夹';
  return '<div class="capbox"><div class="cap-row"><b>ACE-Step 1.5</b><span>' + line + '</span><button class="btn mini primary" data-open-tool="bgm">打开配乐窗口</button>' + (v.alive ? '<button class="btn mini ghost" data-bgm-off="1">现在关掉</button>' : '') + '</div>' +
    '<div class="help">没装过：到 ACE-Step 1.5 的 GitHub 发布页下 Windows 整合包解压（自带 Python 环境和 start_api_server.bat），把解压出来的文件夹填在下面就行。出的音乐放在：' + esc(v.out || '') + '</div></div>';
}
function bgmBoxFetch() { api('GET', '/api/bgm').then(function (j) { BBOX.st = j; var b = $('#bgmBox'); if (b) b.innerHTML = bgmBoxHTML(); }).catch(function () {}); }
var sv = $('#view-settings');
sv.addEventListener('click', function (ev) {
  var wb = ev.target.closest('[data-ws-open],[data-ws-run],[data-ws-dir]');
  if (wb) {
    if (!useLive()) { toast('演示模式不能改'); return; }
    if (wb.dataset.wsOpen) wsOpen(wb.dataset.wsOpen);
    else if (wb.hasAttribute('data-ws-run')) wsDo({ run: wb.getAttribute('aria-checked') !== 'true' }).then(function (j) { toast(j.run ? '能运行程序了（只在工作文件夹里）' : '不让它运行程序了：写、改、删文件还能用'); }).catch(function (e) { toast(e.message); });
    else wsDo({ dir: ($('#wsDir').value || '').trim() }).then(function (j) { toast('工作文件夹换到了：' + j.dir + '（原来那个文件夹没动）', 5000); }).catch(function (e) { toast(e.message, 5000); });
    return;
  }
  var rd = ev.target.closest('[data-rd-add],[data-rd-del],[data-rd-cloud]');
  if (rd) {
    if (!useLive()) { toast('演示模式不能改'); return; }
    if (rd.hasAttribute('data-rd-add')) {
      var v = ($('#rdNew').value || '').trim(); if (!v) { toast('填一个文件夹的路径'); return; }
      rdirsDo('POST', { path: v, cloud: true }).then(function () { toast('允许了：只读，不改不删'); }).catch(function (e) { toast(e.message, 5000); });
    } else if (rd.dataset.rdDel) rdirsDo('DELETE', null, rd.dataset.rdDel).then(function () { toast('不让读了'); }).catch(function (e) { toast(e.message); });
    else rdirsDo('PATCH', { path: rd.dataset.rdCloud, cloud: rd.getAttribute('aria-checked') !== 'true' }).catch(function (e) { toast(e.message); });
    return;
  }
  var cp = ev.target.closest('[data-cap],[data-cap-set],[data-voice-asr],[data-voice-test],[data-voice-off],[data-voice-unref],[data-bgm-off],[data-open-tool]');
  if (cp && !cp.disabled) {
    if (cp.dataset.openTool) { openView(cp.dataset.openTool); return; }
    if (!useLive()) { toast('演示模式不能改'); return; }
    var d = cp.dataset, b = {};
    if (d.cap) { var on = cp.getAttribute('aria-checked') !== 'true'; b[d.cap] = on; capsPut(b, d.cap === 'cc' ? (on ? 'Claude Code 引擎打开了：工作区的活会交给它' : 'Claude Code 引擎关了') : d.cap === 'image' && on ? '生图打开了：它出图会花钱，一件事最多出几张在上面设' : ''); }
    else if (d.capSet) { b[d.capSet] = ($(d.capSet === 'cc_cmd' ? '#ccCmd' : '#ccBash').value || '').trim(); capsPut(b, '保存了'); }
    else if (d.voiceAsr) { cp.disabled = true; cp.textContent = '在下…'; api('POST', '/api/tts/install', { asr: true }).then(function () { toast('开始下听写模型了（约 1.9 GB），进度在主页「后台在跑」里', 6000); }).catch(function (e) { cp.disabled = false; toast(e.message, 6000); }); }
    else if (d.voiceTest) { cp.disabled = true; voiceSay('你好，我在。现在听到的就是我说话的声音。').then(function (ok) { cp.disabled = false; if (ok) setTimeout(voiceBoxFetch, 500); }); }
    else if (d.voiceOff) api('POST', '/api/voice/off', {}).then(function () { toast('Breeze 关掉了，显存还回去了'); voiceBoxFetch(); }).catch(function (e) { toast(e.message); });
    else if (d.voiceUnref) api('DELETE', '/api/voice/ref').then(function (j) { VBOX.st = j; $('#voiceBox').innerHTML = voiceBoxHTML(); toast('去掉了：回到按描述造声音'); }).catch(function (e) { toast(e.message); });
    else if (d.bgmOff) api('POST', '/api/bgm/off', {}).then(function () { toast('ACE-Step 关掉了'); bgmBoxFetch(); }).catch(function (e) { toast(e.message); });
    return;
  }
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
  else if (t.dataset.choice) {
    setVal(t.dataset.choice, t.dataset.v === '1');
    $$('[data-choice="' + t.dataset.choice + '"]').forEach(function (b) { b.setAttribute('aria-pressed', b === t); });
  }
  else if (t.id === 'autoSw') {
    var wantOn = t.getAttribute('aria-checked') !== 'true';
    AUTOST.busy = true; $('#autoSt').innerHTML = autoStHTML();
    api('POST', '/api/autostart', { on: wantOn }, 60000).then(function (r) { AUTOST.st = r; toast(r.msg, 5000); })
      .catch(function (e) { toast(e.message, 6000); }).then(function () { AUTOST.busy = false; var c = $('#autoSt'); if (c) c.innerHTML = autoStHTML(); });
  }
  else if (t.id === 'hwHelperSw') {
    var want = t.getAttribute('aria-checked') !== 'true';
    HWCTL.busy = true; HWCTL.msg = ''; $('#hwCtl').innerHTML = hwCtlHTML();
    api('POST', '/api/hw/helper', { on: want }, 150000).then(function (r) { S.set.hwOn = r.on; HWCTL.msg = r.ok ? '' : r.msg; toast('硬件监控助手：' + r.msg, 5000); })
      .catch(function (e) { toast(e.message, 6000); }).then(function () { HWCTL.busy = false; sampleHW(); var c = $('#hwCtl'); if (c) c.innerHTML = hwCtlHTML(); });
  }
  else if (t.dataset.fpsSkip || t.dataset.fpsUnskip) {
    var l = fpsSkipList(), nm = t.dataset.fpsSkip || t.dataset.fpsUnskip, lo = nm.toLowerCase();
    l = l.filter(function (x) { return x.toLowerCase() !== lo; });
    if (t.dataset.fpsSkip) l.push(nm);
    setVal('fpsSkip', l.join(','));
    toast(t.dataset.fpsSkip ? '记下了：「' + nm.replace(/\.exe$/i, '') + '」不算游戏' : '取消了排除：「' + nm.replace(/\.exe$/i, '') + '」');
    var f = $('#fpsSeen'); if (f) f.innerHTML = fpsSeenHTML();
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
  else if (t.dataset.osdItem) {
    var cur = osdItems(), k = t.dataset.osdItem, i = cur.indexOf(k);
    if (i >= 0) cur.splice(i, 1); else cur.push(k);
    var order = OSD_ITEMS.map(function (x) { return x[0]; });
    cur.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); });
    setVal('osdItems', cur.join(',')); t.setAttribute('aria-pressed', i < 0); osdPreview();
  }
  else if (t.id === 'searchTest') {
    t.disabled = true; t.textContent = '在搜…';
    api('POST', '/api/actions/search_test', {}, 40000).then(function (j) {
      if (D.state) D.state.search = j.search;
      var o = $('#searchOut'); if (o) { o.hidden = false; o.innerHTML = esc(j.msg) + (j.results && j.results.length ? '<br>' + j.results.slice(0, 3).map(function (r) { return '· ' + esc((r.title || '').slice(0, 40)) + ' <span class="cap">' + esc(r.site || '') + '</span>'; }).join('<br>') : ''); }
      toast(j.msg, 5000);
    }).catch(function (e) { toast(e.message, 6000); }).then(function () { t.disabled = false; t.textContent = '测试一下'; });
  }
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

sv.addEventListener('change', function (ev) {                 // 语音：换参考音频
  if (ev.target.id !== 'voiceRefFile' || !ev.target.files[0]) return;
  var f = ev.target.files[0]; ev.target.value = '';
  f.arrayBuffer().then(function (ab) { return fetchT('/api/voice/ref', { method: 'POST', headers: { 'X-Agent': '1', 'Content-Type': 'audio/wav' }, body: ab }, 30000); })
    .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || '没传上去'); return j; }); })
    .then(function (j) { VBOX.st = j; $('#voiceBox').innerHTML = voiceBoxHTML(); toast('换好了：记得把这段音频里说的话填在「参考音频里念的字」', 6000); }).catch(function (e) { toast(e.message, 6000); });
});
