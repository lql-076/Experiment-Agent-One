'use strict';
/* ================= 工具窗口（v2.0）=================
   主窗口只放「主页」（现在在干什么、后台在跑什么、刚做完、Agent 状态）和「常驻」；生图、配音、事件、后台、大脑、报告、设置、说明
   都是左边的按钮，点了弹出一个独立窗口。工具窗口打开的是同一个界面，地址带 ?tool=img 这种：只显示那一个工具，自己的标题栏
   （拖动、置顶、收起、关掉），桌面窗口那边见 app/window.py 的 open_tool。不在桌面窗口里（用浏览器打开）时，用 window.open 开新窗口。
   Ctrl K：命令面板，打开工具、跳到设置的哪一块、切深浅色。 */
var TOOL_KEYS = ['img', 'tts', 'events', 'monitor', 'brains', 'reports', 'settings', 'docs'];
var TOOL_NAME = { img: '生图', tts: '配音', events: '事件', monitor: '后台', brains: '大脑', reports: '报告', settings: '设置', docs: '说明' };
var TOOL = TOOL_KEYS.indexOf(root.dataset.tool) >= 0 ? root.dataset.tool : '';
if (root.dataset.tool && !TOOL) delete root.dataset.tool;
var TOOL_ARG = (function () { try { var a = new URLSearchParams(location.search).get('arg'); return a ? JSON.parse(a) : null; } catch (e) { return null; } })();

function toolUrl(key, arg) { return '/?tool=' + key + (arg ? '&arg=' + encodeURIComponent(JSON.stringify(arg)) : ''); }
/* 打开一个工具窗口（已经开着就拿到前面，并把要跳到哪一块告诉它） */
function openTool(key, arg) {
  var a = deskApi();
  if (a && a.open_tool) { a.open_tool(key, arg ? JSON.stringify(arg) : '').catch(function () { toast('窗口没打开，再点一次试试'); }); return; }
  if (!isHttp) { goView(key); applyToolArg(key, arg); return; }        // 双击 index.html 的演示模式：开不了新窗口，就在这里看
  var w = window.open(toolUrl(key, arg), 'agent-' + key, 'width=1440,height=880');
  if (!w) { toast('浏览器拦住了新窗口：允许弹出窗口，或者在桌面窗口里用'); return; }
  try { w.focus(); } catch (e) { /* 拿不到就算了 */ }
}
/* 去某一页：主窗口里点工具 → 开工具窗口；工具窗口里去另一个工具 → 开那个工具的窗口；就是自己 → 直接跳 */
function openView(v, arg) {
  if (v === 'chat' || v === 'home') { if (TOOL) openMain(v === 'chat' ? { chat: 1 } : null); else { goView('home'); if (v === 'chat') chatOpen(); } return; }
  if (TOOL_KEYS.indexOf(v) < 0) { goView(v); return; }
  if (TOOL === v || (!TOOL && !isHttp)) { goView(v); applyToolArg(v, arg); return; }
  openTool(v, arg);
}
function openSec(sec, act) { openView('settings', { sec: sec, act: act || '' }); }
/* 工具窗口里点「去对话」这类：回到主窗口 */
function openMain(arg) {
  var a = deskApi();
  if (a && a.open_main) { a.open_main(arg ? JSON.stringify(arg) : '').catch(function () {}); return; }
  var w = window.open('/' + (arg && arg.chat ? '?chat=1' : ''), 'agent-main'); if (w) try { w.focus(); } catch (e) { /* 算了 */ }
}
/* 工具窗口收到「跳到哪一块」：设置的某个分区、事件的某一条、重新自检…… */
function applyToolArg(v, arg) {
  if (!arg) return;
  if (v === 'settings' && arg.sec) {
    S.sec = arg.sec; renderSettings();
    if (arg.act === 'recheck') setTimeout(function () { checkPanel(true); }, 450);
    if (arg.act === 'todo') setTimeout(gotoTodo, 450);
  }
  if (v === 'events' && arg.ev) { S.selId = +arg.ev; renderEvents(); }
}
/* 桌面窗口那边调：已经开着的工具窗口又被点了一次，带着新的「跳到哪」 */
function toolArg(s) { var a = null; try { a = typeof s === 'string' ? JSON.parse(s) : s; } catch (e) { return; } if (TOOL) applyToolArg(TOOL, a); }
function mainArg(s) { var a = null; try { a = typeof s === 'string' ? JSON.parse(s) : s; } catch (e) { return; } if (!TOOL && a && a.chat) { if (root.dataset.mode === 'resident') exitResident(); goView('home'); chatOpen(); } }

/* ---------- 工具窗口的标题栏：名字、置顶、收起、关掉 ---------- */
function toolBoot() {
  if (!TOOL) return;
  document.title = TOOL_NAME[TOOL] + ' · Agent';
  $('#tbTool').innerHTML = $('.nav[data-tool="' + TOOL + '"] svg').outerHTML + '<b>' + TOOL_NAME[TOOL] + '</b>';
  S.view = '';
  $$('.view').forEach(function (el) { el.classList.toggle('active', el.id === 'view-' + TOOL); });
  goView(TOOL);
  applyToolArg(TOOL, TOOL_ARG);
}
$('#twPin').addEventListener('click', function () {
  var a = deskApi(), b = $('#twPin'), on = b.getAttribute('aria-pressed') !== 'true';
  if (!a || !a.set_top) { toast('置顶只在桌面窗口里能用'); return; }
  a.set_top(on).then(function (st) { b.setAttribute('aria-pressed', !!(st && st.top)); toast(st && st.top ? '置顶了：一直在别的窗口上面' : '不置顶了'); }).catch(function () {});
});
$('#twMin').addEventListener('click', function () { var a = deskApi(); if (a) a.minimize(); });
$('#twClose').addEventListener('click', function () { var a = deskApi(); if (a && a.close_window) a.close_window(); else window.close(); });
window.addEventListener('pywebviewready', function () { var a = deskApi(); if (TOOL && a && a.state) a.state().then(function (st) { $('#twPin').setAttribute('aria-pressed', !!(st && st.top)); }).catch(function () {}); });

/* 左边的工具按钮 */
$$('.nav[data-tool]').forEach(function (b) { b.addEventListener('click', function () { openView(b.dataset.tool); }); });
/* 正在干活的工具，按钮上一个小点（生图、配音在跑） */
function syncToolBusy(tasks) {
  var busy = {};
  (tasks || []).forEach(function (t) { if (t.k === 'img') busy.img = 1; if (t.k === 'tts' || t.k === 'tts_install') busy.tts = 1; });
  $$('.nav[data-tool]').forEach(function (b) { b.classList.toggle('on-busy', !!busy[b.dataset.tool]); });
}

/* ---------- Ctrl K：命令面板 ---------- */
var PAL = { sel: 0, list: [] };
function palItems() {
  var out = [{ t: '和 Agent 说话', s: 'Ctrl 空格', go: function () { openView('chat'); } }];
  TOOL_KEYS.forEach(function (k) { out.push({ t: '打开 ' + TOOL_NAME[k], s: '新窗口', go: function () { openView(k); } }); });
  (typeof SECTIONS !== 'undefined' ? SECTIONS : []).forEach(function (sc) { if (sc.id && sc.name) out.push({ t: '设置 › ' + sc.name, s: '', go: function () { openSec(sc.id); } }); });
  out.push({ t: '重新自检', s: '整备', go: function () { openSec('prep', 'recheck'); } });
  out.push({ t: '打开 Agent 的工作文件夹', s: '资源管理器', go: function () { if (useLive()) wsOpen('ws'); else toast('演示模式'); } });
  out.push({ t: S.set.theme === 'light' ? '切到深色' : '切到浅色', s: '', go: function () { toggleTone(innerWidth / 2, 60); } });
  if (!TOOL) out.push({ t: '进入常驻屏', s: 'R', go: function () { enterResident(); } });
  return out;
}
function palDraw() {
  var q = ($('#palIn').value || '').trim().toLowerCase();
  PAL.list = palItems().filter(function (x) { return !q || (x.t + x.s).toLowerCase().indexOf(q) >= 0; }).slice(0, 9);
  PAL.sel = Math.min(PAL.sel, Math.max(0, PAL.list.length - 1));
  $('#palList').innerHTML = PAL.list.length ? PAL.list.map(function (x, i) { return '<button class="pal-it" role="option" data-i="' + i + '" aria-selected="' + (i === PAL.sel) + '"><span>' + esc(x.t) + '</span><em>' + esc(x.s) + '</em></button>'; }).join('')
    : '<div class="pal-none">没有对得上的</div>';
}
function palOpen() { var p = $('#pal'); p.hidden = false; $('#palIn').value = ''; PAL.sel = 0; palDraw(); setTimeout(function () { $('#palIn').focus(); }, 0); }
function palClose() { $('#pal').hidden = true; }
function palGo(i) { var x = PAL.list[i]; palClose(); if (x) x.go(); }
$('#btnPal').addEventListener('click', palOpen);
$('#pal').addEventListener('click', function (ev) { if (ev.target.dataset.palClose) { palClose(); return; } var b = ev.target.closest('.pal-it'); if (b) palGo(+b.dataset.i); });
$('#palIn').addEventListener('input', function () { PAL.sel = 0; palDraw(); });
$('#palIn').addEventListener('keydown', function (ev) {
  if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); PAL.sel = (PAL.sel + (ev.key === 'ArrowDown' ? 1 : -1) + PAL.list.length) % Math.max(1, PAL.list.length); palDraw(); }
  else if (ev.key === 'Enter') { ev.preventDefault(); palGo(PAL.sel); }
  else if (ev.key === 'Escape') { ev.preventDefault(); palClose(); }
});
document.addEventListener('keydown', function (ev) {
  if ((ev.ctrlKey || ev.metaKey) && (ev.key === 'k' || ev.key === 'K')) { ev.preventDefault(); if ($('#pal').hidden) palOpen(); else palClose(); return; }
  if (!TOOL && ev.ctrlKey && ev.code === 'Space') { ev.preventDefault(); if (root.dataset.mode === 'resident') exitResident(); if (S.view !== 'home') goView('home'); chatToggle(); }
});

/* ---------- 深色 / 浅色 ---------- */
function toggleTone(x, y) { setTheme(S.set.theme === 'light' ? 'dark' : 'light', x, y); syncTone(); }
function syncTone() { var l = $('#themeLabel'); if (l) l.textContent = S.set.theme === 'light' ? '深色' : '浅色'; }
