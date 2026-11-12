'use strict';
/* 一键补齐：整备页最上面那张卡。后端 app\setup.py 按固定顺序装，界面每 1.5 秒看一次进度。 */
var SETUP = { st: null, timer: null };
/* ready：启动自检查过，已经好了，不用补；auto：正在自动启动（本地模型服务、开关开着的硬件监控助手），也不用你点 */
var SU_LABEL = { wait: '要补', run: '进行中', ok: '好了', ready: '已就绪', auto: '自动启动中', fail: '失败', skip: '跳过了', blocked: '等前面', manual: '要你处理' };
var SU_DEMO = [
  { k: 'git', t: 'Git（便携版）', d: '放进 tools\\git，不装进系统，只给 agent 自己用', st: 'ok', info: 'git version 2.51.0.windows.1（便携版）' },
  { k: 'aienv', t: '本地模型环境', d: '显卡版 PyTorch、Transformers、PEFT、Kev，约 3GB', st: 'ok', info: 'PyTorch 2.8.0+cu128 · CUDA 12.8' },
  { k: 'models', t: '底座和嵌入模型', d: '从魔搭下载，约 6GB，断了会接着下', st: 'run', info: '进行中', prog: { phase: '下载 model.safetensors', pct: 63, done: 2.96e9, total: 4.7e9, speed: 31.5e6, eta: 55, src: '魔搭' } },
  { k: 'start', t: '启动本地模型服务', d: '加载嵌入模型，约占 1.2GB 显存', st: 'wait', info: '' },
  { k: 'kev', t: 'Kev 的权重', d: '经 hf-mirror 下载约 2GB', st: 'wait', info: '' },
  { k: 'hwmon', t: '硬件监控助手', d: '会弹一次管理员确认，点「是」', st: 'wait', info: '' }
];
var SU_MEDIA_DEMO = [
  { k: 'tts', g: 'media', t: '本地配音（Qwen3-TTS）', d: '配音环境 + 两个配音模型 + 时间轴对齐，约 14GB；视频配音、批量配音、Agent 自己配音都用它', st: 'ready', info: '配音环境和三个模型都在' },
  { k: 'asr', g: 'media', t: '听写（Qwen3-ASR）', d: '你说的话变成字，约 1.9GB，装在配音环境里', st: 'wait', info: '' },
  { k: 'breeze', g: 'media', t: '说话的声音（Breeze TTS 2）', d: '和它聊天时念回答（约 8GB 显存）；代码随包带着，只下权重；只许自己用、非商用', st: 'wait', info: '' },
  { k: 'bgm', g: 'media', t: '配乐（ACE-Step 1.5）', d: '官方 Windows 便携包 + 模型，约 15GB；出纯音乐，能商用', st: 'wait', info: '' }
];
var SU_TEXT = {
  core: { title: '一键补齐', all: '6 样都齐了：每次启动自动查一遍，好了的标「已就绪」，本地模型服务和硬件监控助手自己会起来，不用点。',
    help: '按固定顺序装好下面 6 样，已经好了的跳过；某一步失败时 DeepSeek 看日志选修法。一共下载约 11GB，可以关掉界面，它在后台接着装。启动时查过已经好了的标「已就绪」，不用再补。', go: '开始一键补齐' },
  media: { title: '配音、语音、配乐', all: '4 样都装好了：配音页、配乐窗口、和它说话都能直接用；用到才启动，闲着自己关，打游戏让路。',
    help: '做视频和语音对话要的 4 样，一键装好（已经好了的跳过），也能一项一项装。全装大约下载 30GB，放在 Agent 文件夹里，不装进系统；可以关掉界面，它在后台接着装。', go: '一键装好这 4 样' }
};
function setupHTML(g) {
  g = g || 'core';
  var live = useLive(), st = live ? SETUP.st : (g === 'core' ? { running: true, group: 'core', cur: 'models', steps: SU_DEMO } : { running: false, steps: SU_MEDIA_DEMO });
  var steps = st ? st.steps.filter(function (s) { return (s.g || 'core') === g; }) : [], running = !!(st && st.running && (st.group || 'core') === g);
  var other = !!(st && st.running && !running), tx = SU_TEXT[g];
  var done = steps.filter(function (s) { return s.st === 'ok' || s.st === 'ready'; }).length;
  var need = steps.filter(function (s) { return s.st !== 'ok' && s.st !== 'ready' && s.st !== 'auto'; }).length;
  var noKey = live && st && st.ds_key === false;
  var busy = g === 'media' && st && st.tts_busy;
  var btn = running ? '<button class="btn danger" data-setup-stop="' + g + '">停下</button>' :
    other || busy ? '<button class="btn" disabled title="' + (busy ? '设置 › 本地模型 里「安装配音」正在跑' : '另一张卡片正在装') + '">等' + (busy ? '「安装配音」' : '那边') + '装完</button>' :
    live && steps.length && !need ? '<button class="btn" data-setup-go="' + g + '" title="都齐了，不用装；想从头再查一遍也可以点">都齐了 · 再跑一遍</button>' :
    '<button class="btn primary" data-setup-go="' + g + '"' + (live ? '' : ' disabled') + '>' + (done ? '装缺的 ' + need + ' 项' : tx.go) + '</button>';
  return '<div class="sucard' + (running ? ' running' : '') + '" id="' + (g === 'core' ? 'setupCard' : 'setupCard-' + g) + '"><div class="su1-top"><div>' +
    '<h3>' + tx.title + (steps.length ? '<span class="num" style="font-weight:400;color:var(--text3);margin-left:.6rem">' + done + ' / ' + steps.length + '</span>' : '') + '</h3>' +
    '<p class="help">' + (live && !running && steps.length && !need ? tx.all : tx.help) +
    (noKey && g === 'core' ? '<br><b style="color:var(--c-neu)">还没填 DeepSeek Key：失败时只会按简单规则重试一次。</b>' : '') + '</p></div>' +
    '<div class="btnrow">' + btn + '</div></div>' +
    (steps.length ? '<ol class="susteps">' + steps.map(function (s, i) {
      var cur = running && st.cur === s.k, line = cur ? (st.line || s.line || '') : '', took = s.t0 && s.t1 ? fmtSecs(s.t1 - s.t0) : '';
      var one = g === 'media' && live && !st.running && !busy && s.st !== 'ok' && s.st !== 'ready' ? '<button class="btn mini" data-setup-one="' + s.k + '">只装这一项</button>' : '';
      return '<li class="sus st-' + s.st + (cur ? ' cur' : '') + '"><span class="sus-n num">' + (i + 1) + '</span><div class="sus-b"><div class="sus-h"><b>' + esc(s.t) + '</b><span class="pill">' + (SU_LABEL[s.st] || s.st) + '</span>' + one + '</div>' +
        '<span class="help">' + esc(s.d) + '</span>' +
        (s.info && s.st !== 'run' ? '<p>' + esc(s.info) + (took ? '<span class="cap"> · 用了 ' + took + '</span>' : '') + '</p>' : '') +
        (cur ? progHTML(s.prog, line) : '') +
        (s.why ? '<p class="sus-why">DeepSeek 看了日志：' + esc(s.why) + '</p>' : '') +
        (s.tell ? '<p class="sus-tell">要你做：' + esc(s.tell) + '</p>' : '') +
        ((s.st === 'fail' || s.st === 'manual') && s.log ? '<p class="help">完整日志：<code>' + esc(s.log) + '</code></p>' : '') +
        '</div></li>';
    }).join('') + '</ol>' : '') + '</div>';
}
function setupRender() { ['core', 'media'].forEach(function (g) { var c = $(g === 'core' ? '#setupCard' : '#setupCard-' + g); if (c) c.outerHTML = setupHTML(g); }); }
function setupPoll() {
  clearTimeout(SETUP.timer);
  if (!useLive()) return;
  var was = SETUP.st && SETUP.st.running;
  api('GET', '/api/setup', null, 8000).then(function (j) {
    SETUP.st = j; setupRender();
    if (j.running) SETUP.timer = setTimeout(setupPoll, 1500);
    else if (was) { toast((j.group === 'media' ? '配音、语音、配乐' : '一键补齐') + '跑完了，重新自检一遍', 4000); runChecks(false); poll(); }
  }).catch(function () { SETUP.timer = setTimeout(setupPoll, 5000); });
}
function setupStart(btn, g, keys) {
  g = g || 'core'; btn.disabled = true; var was = btn.textContent; btn.textContent = '开始…';
  api('POST', '/api/setup/start', { group: g, keys: keys || null }).then(function (j) {
    SETUP.st = j; setupRender(); setupPoll();
    toast(g === 'core' ? '开始补齐，进度就在这里看' : '开始装了，进度就在这张卡片上看（可以关掉界面，它在后台接着装）', 5000);
  }).catch(function (e) { toast(e.message, 6000); btn.disabled = false; btn.textContent = was; });
}
function setupStop() { api('POST', '/api/setup/stop', {}).then(function () { toast('正在停下（当前这一步会中断，下次接着装）'); setupPoll(); }); }
