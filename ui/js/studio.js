'use strict';
/* ================= 视频工坊 · 四核心生产板块 + 居中窄聊 + 右下角全员 Agent 头像灯区 =================
   左栏（宽栏）：生图 Agent、配乐 Agent 独立板块同屏展开
   中栏（收窄）：唯一项目群聊、Mode B 审批卡片、产物内嵌预览与 @ 指令输入框（全局底栏已隐藏）
   右栏（宽栏）：上方同屏展示 配音 Agent、视频生成 Agent（含分镜帧预览与 FFmpeg MP4 合成/播放）；
                 右下角固定专属团队头像灯区，展示全部 9 个真实 Agent，谁在工作谁亮起，点击可快捷 @ 或查看状态与质检详情 */

var ST_RATIOS = ['9:16', '16:9', '1:1', '3:4', '4:3', '2:3', '3:2'];
var ST_ROLES = ['白页', '紫苏', '旁白'];

var ST_STATUS_LABEL = {
  idle: '待命',
  thinking: '思考中',
  running: '工作中',
  waiting_input: '排队中',
  waiting_approval: '待审批',
  failed: '失败',
  completed: '完成',
  paused: '已暂停',
};

var ST_TASK_LABEL = {
  pending: '等待上游',
  ready: '就绪',
  running: '执行中',
  waiting_approval: '待审批',
  succeeded: '已完成',
  failed: '失败',
  retrying: '重试中',
  cancelled: '已取消',
  paused: '已暂停',
  cached: '缓存命中',
};

var ST_AGENT_ORDER = [
  ['supervisor', '总导演', '全局拆解与调度'],
  ['script', '剧本', '台词编写与导入'],
  ['storyboard', '分镜', '镜头切分与节奏'],
  ['image', '生图', '分镜插图与参考图'],
  ['voice', '配音', '逐句语音与混音轨'],
  ['bgm', '配乐', '背景音乐生成'],
  ['video_gen', '视频', '动态/PPT视觉帧'],
  ['compose', '合成', 'FFmpeg MP4 压制'],
  ['qa', '质检', 'FFprobe 实时验收'],
];

var ST_AGENT_ICONS = {
  supervisor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.2"/><path d="M5.5 19.5c.8-3.3 3.4-5 6.5-5s5.7 1.7 6.5 5"/><path d="M18 4l2 2-2 2M4 6h3"/></svg>',
  script: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h9l4 4v12H6z"/><path d="M15 4v4h4"/><path d="M9.5 12h6M9.5 15.5h4.5"/></svg>',
  storyboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4.5" width="7.5" height="6"/><rect x="13" y="4.5" width="7.5" height="6"/><rect x="3.5" y="13.5" width="7.5" height="6"/><rect x="13" y="13.5" width="7.5" height="6"/></svg>',
  image: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4.5" width="17" height="15"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M4.5 17.5l4.8-4.5 3.6 3.2 2.8-2.4 3.8 3.7"/></svg>',
  voice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3.5" width="6" height="10" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><path d="M12 18v3M8.5 21h7"/></svg>',
  bgm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 17.5V6l10-2v11.5"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="16.5" cy="15.5" r="2.5"/></svg>',
  video_gen: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5.5" width="17" height="13"/><path d="M10 9.5l5 2.5-5 2.5z"/></svg>',
  compose: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h10M18 7h2M4 12h4M12 12h8M4 17h12M20 17h0"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="17" r="2"/></svg>',
  qa: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5l7 3v5.5c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6.5z"/><path d="M9 12.2l2 2 4.2-4.2"/></svg>',
};

var STUDIO = {
  st: null,
  t: null,
  fetchBusy: false,
  pid: '',
  lastPid: '',
  sig: {},
  pref: {},
  topic: '',
  chatWide: false,
  collapsedPanes: {},
  inspectAgentId: '',
  chatFilter: 'all', // 'all' | 'chat' | 'events'
  replyTo: null, // { msg_id, sender_name, text }
  pendingAttachments: [],
  newProjOpen: false,
  importOpen: false,
};

function studioSt() { return useLive() ? STUDIO.st : stDemo(); }
function studioProj() { var s = studioSt(); return s && s.project; }
function studioAgents() { var s = studioSt(); return (s && s.agents) || []; }
function studioAgentMap() {
  var m = {};
  studioAgents().forEach(function (a) { m[a.id] = a; });
  return m;
}

function stAsset(pid, rel, ver) {
  var s = String(rel || '');
  if (/^(data:|blob:|https?:\/\/|\/api\/)/i.test(s)) return s;
  return '/api/studio/asset?pid=' + encodeURIComponent(pid || '') + '&path=' + encodeURIComponent(s) + (ver ? '&v=' + encodeURIComponent(ver) : '');
}

function stSize(b) {
  b = +b || 0;
  return b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB'
    : b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB'
    : Math.max(1, Math.round(b / 1e3)) + ' KB';
}

function stFmtClock(ts) {
  if (!ts) return '';
  var d = new Date(ts * 1000);
  var p = function (n) { return String(n).padStart(2, '0'); };
  return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
}

function stPut(id, html) {
  var e = $('#' + id);
  if (!e || STUDIO.sig[id] === html) return false;
  STUDIO.sig[id] = html;
  e.innerHTML = html;
  return true;
}

function stSetText(id, v) {
  var e = $('#' + id);
  if (e && e.textContent !== String(v)) e.textContent = String(v);
}

function stPaneBusyInteraction(paneId) {
  var body = $('#stPaneBody-' + paneId);
  if (!body) return false;
  var a = document.activeElement;
  if (a && body.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return true;
  var playing = [].slice.call(body.querySelectorAll('audio, video')).some(function (m) {
    return !m.paused && !m.ended;
  });
  return playing;
}

function stVoiceOptions(cur) {
  var vs = (studioSt() && studioSt().voices) || [];
  var groups = {};
  vs.forEach(function (v) {
    var g = v.engine === 'cloud' ? '百炼云端' : '本地预设';
    (groups[g] = groups[g] || []).push(v);
  });
  var out = [];
  if (cur && !vs.some(function (v) { return v.id === cur; })) {
    out.push('<option value="' + esc(cur) + '" selected>' + esc(cur) + '</option>');
  }
  Object.keys(groups).forEach(function (g) {
    out.push('<optgroup label="' + esc(g) + '">' + groups[g].map(function (v) {
      return '<option value="' + esc(v.id) + '"' + (v.id === cur ? ' selected' : '') + '>' + esc(v.label) + '</option>';
    }).join('') + '</optgroup>');
  });
  return out.join('') || '<option value="local:preset:Serena">Serena · 预设女声</option>';
}

function stModelOptions(cur) {
  var ms = (studioSt() && studioSt().models) || [];
  var out = [];
  if (cur && !ms.some(function (m) { return m.id === cur; })) {
    out.push('<option value="' + esc(cur) + '" selected>' + esc(cur) + '</option>');
  }
  ms.forEach(function (m) {
    out.push('<option value="' + esc(m.id) + '"' + (m.id === cur ? ' selected' : '') + '>' +
      esc((m.vendor ? m.vendor + ' · ' : '') + m.name + (m.price ? ' ($' + m.price + ')' : '')) + '</option>');
  });
  return out.join('') || '<option value="gpt-image-2.5-sunburst-vip">GPT Image 2.5 Sunburst VIP</option>';
}

/* ---------- 演示数据 ---------- */
function stDemo() {
  var now = Math.floor(Date.now() / 1000);
  var p = {
    id: 'demo',
    revision: 1,
    name: '演示项目',
    title: '三个被低估的 AI 用法',
    desc: '知识科普 × 科技数码 × 搞笑段子',
    tags: ['AI', '科普'],
    ratio: '9:16',
    target_duration: 60,
    created: '2026-11-18 10:00:00',
    updated_at: now,
    dir: 'workspace/.studio_data/demo',
    script_summary: '2 句台词 · 2 镜 · 目标 10s',
    shots: [
      { shot_id: 'shot_01', order: 1, render: 'web', visual_prompt: '暖光桌面科技特写与主题标题动效', subtitle_text: '先说一个反常识的结论。', duration_sec: 5 },
      { shot_id: 'shot_02', order: 2, render: 'ppt', visual_prompt: '双栏对比信息卡片：常见误区 vs 高效工作流', subtitle_text: '等等，这也太离谱了吧？', duration_sec: 5 },
    ],
    dialogues: [
      { line_id: 'line_01', shot_id: 'shot_01', order: 1, role: '白页', speaker: 'local:preset:Serena', engine: 'auto', text: '先说一个反常识的结论。', tone: '冷静吐槽' },
      { line_id: 'line_02', shot_id: 'shot_02', order: 2, role: '紫苏', speaker: 'local:preset:Dylan', engine: 'auto', text: '等等，这也太离谱了吧？', tone: '轻松调侃' },
    ],
    bgm: { prompt: 'upbeat electronic, no vocals', seconds: 75, steps: 8, seed: 20261118 },
    image_config: {
      model: 'gpt-image-2.5-sunburst-vip', ratio: '9:16', resolution: '2k', quality: 'high', n: 1, output: 'normal', refs: [],
      items: [
        { item_id: 'img_01', shot_id: 'shot_01', label: '镜头 1 配图', prompt: '暖光桌面科技特写', ratio: '9:16', transparent: false },
        { item_id: 'img_02', shot_id: 'shot_02', label: '镜头 2 配图', prompt: '信息对比卡片插图', ratio: '9:16', transparent: false },
      ],
    },
    compose_config: { fps: 24, bgm_volume: 0.18, duck_depth: 0.16, fade: 2, subtitle: true, cc_drive: true },
    publish_config: { title: '三个被低估的 AI 用法', desc: '知识科普 × 科技数码 × 搞笑段子', tags: ['AI', '科普'], mode: 'single', declaration: '内容由AI生成' },
    assets: [],
    tasks: [],
    approvals: [],
    messages: [
      {
        msg_id: 'demo-1', ts: now - 30, kind: 'agent', sender_id: 'supervisor', sender_name: '总导演 Agent',
        text: '当前处于演示模式。界面仅保留生图、配乐、配音、视频生成四块工作区；总导演/剧本/分镜/质检等全部 9 个 Agent 均在右下角实时在线，工作时头像会自动亮起。',
      },
    ],
    qa: null,
    video_ok: false,
    lists: {},
  };
  var agents = [
    { id: 'supervisor', name: '总导演 Agent', role: 'Supervisor', responsibility: '拆解目标、调度 DAG、审批门控', tools: ['plan.decompose', 'task.schedule'], status: 'idle', brief: '待命', unread: 0 },
    { id: 'script', name: '剧本 Agent', role: 'Script', responsibility: '编写双角色台词并分配 line_id', tools: ['script.plan', 'script.import'], status: 'idle', brief: '已就绪 (2 句)', unread: 0 },
    { id: 'storyboard', name: '分镜 Agent', role: 'Storyboard', responsibility: '划分 shot_id 与画面节奏', tools: ['storyboard.build'], status: 'idle', brief: '2 镜 · 10s', unread: 0 },
    { id: 'image', name: '生图 Agent', role: 'Image', responsibility: '调用 API易/生图模型并管理版本', tools: ['image.generate'], status: 'idle', brief: '待命', unread: 0 },
    { id: 'voice', name: '配音 Agent', role: 'Voice', responsibility: '按 line_id 增量合成百炼/本地配音', tools: ['voice.synthesize_line'], status: 'idle', brief: '待命', unread: 0 },
    { id: 'bgm', name: '配乐 Agent', role: 'BGM', responsibility: '生成 -1 dBFS 归一背景音乐', tools: ['bgm.generate'], status: 'idle', brief: '待命', unread: 0 },
    { id: 'video_gen', name: '视频生成 Agent', role: 'Video Gen', responsibility: '渲染网页动效与 PPT 卡片帧', tools: ['video.render_frames'], status: 'idle', brief: '待命', unread: 0 },
    { id: 'compose', name: '后期合成 Agent', role: 'Compose', responsibility: 'FFmpeg 音画混流与 MP4 压制', tools: ['compose.ffmpeg', 'subtitle.srt'], status: 'idle', brief: '待命', unread: 0 },
    { id: 'qa', name: '质检 Agent', role: 'QA', responsibility: 'FFprobe 成片与资源一致性验收', tools: ['qa.inspect'], status: 'idle', brief: '待命', unread: 0 },
  ];
  return {
    projects: [{ id: 'demo', name: '演示项目', title: '三个被低估的 AI 用法', created: '2026-11-18 10:00:00', ratio: '9:16', revision: 1, st: 'idle', shots: 2, video: false }],
    active: 'demo',
    project: p,
    agents: agents,
    tools: [],
    tool_health: { ffmpeg: true, ffprobe: true, deepseek: false, apiyi: false, bailian: false },
    resources: { active_tasks: 0, queued_tasks: 0, pending_approvals: 0, project_cost_usd: 0, project_cost_cny: 0 },
    voices: [
      { id: 'local:preset:Serena', label: 'Serena · 预设女声', engine: 'local' },
      { id: 'local:preset:Dylan', label: 'Dylan · 预设男声', engine: 'local' },
      { id: 'cloud:longanlingxin_v3.1', label: '龙安灵心 · 百炼女声', engine: 'cloud' },
    ],
    models: [{ id: 'gpt-image-2.5-sunburst-vip', name: 'GPT Image 2.5 Sunburst VIP', vendor: 'OpenAI', price: 0.03 }],
  };
}

/* ---------- 仅保留 4 个生产板块：左栏 生图+配乐；右栏 配音+视频生成 ---------- */
var LEFT_PANES = [
  ['image', '生图 Agent', true],
  ['bgm', '配乐 Agent', true],
];

var RIGHT_PANES = [
  ['voice', '配音 Agent', true],
  ['video_gen', '视频生成 Agent', true],
];

function stPaneShell(id, title, isAgent) {
  return '<section class="st-pane' + (STUDIO.collapsedPanes[id] ? ' collapsed' : '') + '" id="stPane-' + esc(id) + '">' +
    '<header class="st-pane-h">' +
      '<div class="st-pane-title">' +
        (isAgent ? '<span class="st-ag-dot idle" id="stDot-' + esc(id) + '"></span>' : '') +
        '<b>' + esc(title) + '</b>' +
        '<span class="st-pane-stat" id="stStat-' + esc(id) + '">待命</span>' +
      '</div>' +
      '<div class="st-pane-ops">' +
        (isAgent ? '<button type="button" class="btn mini ghost" data-at-agent="' + esc(id) + '" title="在聊天框 @ 提到此 Agent">@</button>' +
          '<button type="button" class="btn mini primary" data-agent-run="' + esc(id) + '">▶ 跑</button>' +
          '<button type="button" class="btn mini ghost" id="stPauseBtn-' + esc(id) + '" data-agent-act="' + esc(id) + ':pause">暂停</button>' +
          '<button type="button" class="btn mini danger" data-agent-act="' + esc(id) + ':stop">停</button>' : '') +
        '<button type="button" class="btn mini ghost" data-fold-pane="' + esc(id) + '">' + (STUDIO.collapsedPanes[id] ? '展开' : '收起') + '</button>' +
      '</div>' +
    '</header>' +
    '<div class="st-pane-body" id="stPaneBody-' + esc(id) + '"></div>' +
  '</section>';
}

function studioShell() {
  return '<div class="st' + (STUDIO.chatWide ? ' chat-wide' : '') + '">' +
    '<div class="st-top" id="stTop"></div>' +
    '<div class="st-work">' +
      '<section class="st-col-left" aria-label="生图与配乐面板">' +
        '<div class="st-col-h">' +
          '<b>画面与配乐</b>' +
          '<div class="st-anchors">' +
            '<button type="button" data-jump-pane="image">生图</button>' +
            '<button type="button" data-jump-pane="bgm">配乐</button>' +
          '</div>' +
        '</div>' +
        '<div class="st-panes" id="stLeftPanes">' +
          LEFT_PANES.map(function (p) { return stPaneShell(p[0], p[1], p[2]); }).join('') +
        '</div>' +
      '</section>' +
      '<section class="st-col-center" aria-label="项目群聊">' +
        '<div class="st-chat-head" id="stChatHead"></div>' +
        '<div class="st-msgs" id="stMsgs"></div>' +
        '<div class="st-comp" id="stComp">' +
          '<div class="st-comp-reply" id="stReplyBar" hidden></div>' +
          '<div class="st-row" id="stAttachBar" hidden></div>' +
          '<div class="st-comp-atbar" id="stAtBar">' +
            '<button type="button" data-at-insert="@总导演 ">@总导演</button>' +
            '<button type="button" data-at-insert="@剧本 ">@剧本</button>' +
            '<button type="button" data-at-insert="@分镜 ">@分镜</button>' +
            '<button type="button" data-at-insert="@生图 ">@生图</button>' +
            '<button type="button" data-at-insert="@配音 ">@配音</button>' +
            '<button type="button" data-at-insert="@配乐 ">@配乐</button>' +
            '<button type="button" data-at-insert="@视频 ">@视频</button>' +
            '<button type="button" data-at-insert="@合成 ">@合成</button>' +
            '<button type="button" data-at-insert="@质检 ">@质检</button>' +
          '</div>' +
          '<div class="st-comp-row">' +
            '<textarea class="inp st-comp-in" id="stChatInput" rows="2" placeholder="输入创作要求或 @Agent 指令（Enter 发送）"></textarea>' +
            '<div class="st-comp-side">' +
              '<button type="button" class="btn mini primary" id="stBtnSend">发送</button>' +
              '<label class="btn mini ghost st-filebtn" title="上传参考图或导入剧本">附件<input type="file" id="stChatFile" accept="image/*,.md,.markdown,.txt,.json" multiple></label>' +
            '</div>' +
          '</div>' +
          '<div class="st-comp-foot">' +
            '<button type="button" class="linkbtn" data-quick-cmd="从头制作一版完整短视频并做质检">全流程策划</button>' +
            '<button type="button" class="linkbtn" data-quick-cmd="@配音 重新合成全部配音">@配音</button>' +
            '<button type="button" class="linkbtn" data-quick-cmd="@合成 重新压制 MP4 成片">@合成</button>' +
            '<button type="button" class="linkbtn" data-quick-cmd="@质检 检查成片质量">@质检</button>' +
          '</div>' +
        '</div>' +
      '</section>' +
      '<section class="st-col-right" aria-label="配音视频生成与团队状态">' +
        '<div class="st-col-h">' +
          '<b>配音与视频生成</b>' +
          '<div class="st-anchors">' +
            '<button type="button" data-jump-pane="voice">配音</button>' +
            '<button type="button" data-jump-pane="video_gen">视频生成</button>' +
          '</div>' +
        '</div>' +
        '<div class="st-panes" id="stRightPanes">' +
          RIGHT_PANES.map(function (p) { return stPaneShell(p[0], p[1], p[2]); }).join('') +
        '</div>' +
        '<div class="st-avpop" id="stAvInspect" hidden></div>' +
        '<div class="st-avdock" id="stAvatarDock" aria-label="Agent 团队实时状态灯"></div>' +
      '</section>' +
    '</div>' +
  '</div>';
}

function renderStudio(force) {
  var v = $('#view-studio');
  if (!v) return;
  if (!v.querySelector('.st')) {
    v.innerHTML = studioShell();
    STUDIO.sig = {};
  }
  var rootEl = v.querySelector('.st');
  if (rootEl) rootEl.classList.toggle('chat-wide', !!STUDIO.chatWide);

  renderTop();
  renderPaneHeaders();
  renderAllPanes(force);
  renderChatHead();
  renderMessages();
  renderComposerMeta();
  renderAvatarDock();
}

/* ---------- 顶栏 ---------- */
function renderTop() {
  var s = studioSt() || {}, ps = s.projects || [], p = s.project || {}, res = s.resources || {};
  var runningCount = +(res.active_tasks || 0);
  var queuedCount = +(res.queued_tasks || 0);
  var pendingApr = +(res.pending_approvals || 0);
  var anyRun = runningCount > 0 || queuedCount > 0;

  var sel = '<select class="inp st-projsel" id="stProj" aria-label="切换项目">' + (ps.length ? ps.map(function (x) {
    return '<option value="' + esc(x.id) + '"' + (p.id === x.id ? ' selected' : '') + '>' +
      esc(x.title || x.name) + ' · ' + esc(x.ratio || '9:16') + '</option>';
  }).join('') : '<option value="">无项目</option>') + '</select>';

  var newBar = STUDIO.newProjOpen
    ? '<div class="st-row" style="width:100%;padding-top:.32rem;border-top:1px solid var(--ln)">' +
        '<input class="inp" id="stNewTopic" style="flex:1;min-width:12rem" placeholder="输入新项目主题，例如：AI 编程提效的 3 个技巧">' +
        '<select class="inp" id="stNewRatio" style="width:5.2rem">' + ST_RATIOS.map(function (r) { return '<option value="' + r + '">' + r + '</option>'; }).join('') + '</select>' +
        '<input class="inp" id="stNewSec" type="number" min="15" max="300" value="60" style="width:4.5rem" title="目标时长（秒）">' +
        '<button type="button" class="btn mini primary" data-act="createProj">创建</button>' +
        '<button type="button" class="btn mini ghost" data-act="cancelNewProj">取消</button>' +
      '</div>'
    : '';

  var importBar = STUDIO.importOpen
    ? '<div class="st-field" style="width:100%;padding-top:.32rem;border-top:1px solid var(--ln)">' +
        '<div class="st-row"><label style="font-size:.72rem;color:var(--text3)">粘贴台词或剧本 JSON（支持「白页：xxx」）：</label><span class="sp" style="flex:1"></span>' +
          '<button type="button" class="btn mini primary" data-act="doImport">导入并同步分镜</button>' +
          '<button type="button" class="btn mini ghost" data-act="toggleImport">关闭</button></div>' +
        '<textarea class="inp" id="stImportText" rows="3" placeholder="白页：先说一个反常识的结论。\n紫苏：这也太离谱了吧？"></textarea>' +
      '</div>'
    : '';

  var html = '<div class="st-brand"><b>视频工坊</b><span>生图 · 配乐 · 配音 · 视频生成</span></div>' +
    '<div class="st-proj">' + sel + '<button type="button" class="btn mini ghost" data-act="toggleNewProj">新建</button></div>' +
    '<div class="st-top-meta">' +
      '<span>版本 <b class="st-num">r' + (p.revision || 1) + '</b></span>' +
      '<span>分镜 <b class="st-num">' + ((p.shots || []).length) + '</b></span>' +
      '<span>台词 <b class="st-num">' + ((p.dialogues || []).length) + '</b></span>' +
      (anyRun ? '<span style="color:var(--hud)">运行 <b class="st-num">' + runningCount + '</b> · 排队 <b class="st-num">' + queuedCount + '</b></span>' : '') +
      (pendingApr ? '<span style="color:var(--warn)">待审批 <b class="st-num">' + pendingApr + '</b></span>' : '') +
      '<span>成片 ' + (p.video_ok ? '<b style="color:var(--ok)">已就绪</b>' : '<b>未生成</b>') + '</span>' +
    '</div>' +
    '<div class="st-top-acts">' +
      '<button type="button" class="btn mini ghost" data-act="toggleImport">导入剧本</button>' +
      '<button type="button" class="btn mini primary" data-act="runFull">▶ 全流程制作</button>' +
      '<button type="button" class="btn mini danger" data-act="stopAll"' + (anyRun ? '' : ' disabled') + '>■ 全部停下</button>' +
      '<button type="button" class="btn mini ghost" data-act="toggleChatWidth">' + (STUDIO.chatWide ? '收窄聊天' : '略宽聊天') + '</button>' +
    '</div>' + newBar + importBar;

  stPut('stTop', html);
}

/* ---------- 更新保留的 4 个核心板块头部实时状态（不破坏输入框与媒体播放） ---------- */
function renderPaneHeaders() {
  var am = studioAgentMap();
  LEFT_PANES.concat(RIGHT_PANES).forEach(function (cfg) {
    var id = cfg[0], isAgent = cfg[2];
    var pane = $('#stPane-' + id);
    if (pane) pane.classList.toggle('collapsed', !!STUDIO.collapsedPanes[id]);
    var foldBtn = pane ? pane.querySelector('[data-fold-pane]') : null;
    if (foldBtn) foldBtn.textContent = STUDIO.collapsedPanes[id] ? '展开' : '收起';

    if (isAgent) {
      var ag = am[id] || { status: 'idle', brief: '待命', paused: false };
      var st = ag.status || 'idle';
      // 视频生成面板兼看 compose 状态，让成片压制时视频生成头部也给出提示
      if (id === 'video_gen') {
        var cmp = am.compose;
        if (st === 'idle' && cmp && (cmp.status === 'running' || cmp.status === 'thinking')) {
          st = cmp.status;
          ag = cmp;
        }
      }
      var dot = $('#stDot-' + id);
      if (dot) dot.className = 'st-ag-dot ' + st;
      var stEl = $('#stStat-' + id);
      if (stEl) {
        stEl.className = 'st-pane-stat ' + st;
        var label = ST_STATUS_LABEL[st] || st;
        stEl.textContent = ag.brief && ag.brief !== '待命' ? (label + ' · ' + ag.brief) : label;
      }
      var pbtn = $('#stPauseBtn-' + id);
      if (pbtn) {
        pbtn.textContent = ag.paused ? '恢复' : '暂停';
        pbtn.setAttribute('data-agent-act', id + ':' + (ag.paused ? 'resume' : 'pause'));
      }
    }
  });
}

function renderAllPanes(force) {
  var p = studioProj() || {};
  var builders = {
    image: buildImagePane,
    bgm: buildBgmPane,
    voice: buildVoicePane,
    video_gen: buildVideoGenPane,
  };

  Object.keys(builders).forEach(function (id) {
    if (!force && stPaneBusyInteraction(id)) return;
    var html = builders[id](p);
    if (force) STUDIO.sig['stPaneBody-' + id] = null;
    stPut('stPaneBody-' + id, html);
  });
}

/* ---------- 左栏：生图 + 配乐 ---------- */
function buildImagePane(p) {
  var ic = p.image_config || {}, items = ic.items || [], refs = ic.refs || [];
  return '<div class="st-field"><label>生图模型</label><select class="inp" id="stImgModel">' + stModelOptions(ic.model) + '</select></div>' +
    '<div class="st-row2">' +
      '<div class="st-field"><label>分辨率</label><select class="inp" id="stImgRes">' +
        ['1k', '2k', '4k'].map(function (r) { return '<option value="' + r + '"' + (ic.resolution === r ? ' selected' : '') + '>' + r.toUpperCase() + '</option>'; }).join('') +
      '</select></div>' +
      '<div class="st-field"><label>输出格式</label><select class="inp" id="stImgOut">' +
        '<option value="normal"' + (ic.output !== 'svg' ? ' selected' : '') + '>位图 PNG</option>' +
        '<option value="svg"' + (ic.output === 'svg' ? ' selected' : '') + '>矢量 SVG</option>' +
      '</select></div>' +
    '</div>' +
    '<div class="st-row">' +
      '<button type="button" class="btn mini primary" data-act="saveImgCfg">保存生图参数</button>' +
      '<label class="btn mini ghost st-filebtn">上传参考图<input type="file" id="stRefUpload" accept="image/*" multiple></label>' +
      '<span style="font-size:.7rem;color:var(--text3)">参考图 ' + refs.length + '/16</span>' +
    '</div>' +
    (refs.length ? '<div class="st-artgrid">' + refs.map(function (r, idx) {
      return '<div class="st-art-img" style="max-width:5rem"><img src="' + esc(stAsset(p.id, r)) + '" style="width:4.5rem;height:3.5rem" alt=""><button type="button" class="linkbtn" data-del-ref="' + idx + '">移除</button></div>';
    }).join('') + '</div>' : '') +
    '<div class="st-cardgrid">' + (items.length ? items.map(function (it) {
      var shot = (p.shots || []).filter(function (s) { return s.shot_id === it.shot_id; })[0];
      var ast = shot && shot.image_asset_id ? (p.assets || []).filter(function (a) { return a.asset_id === shot.image_asset_id; })[0] : null;
      var vers = (p.assets || []).filter(function (a) { return a.kind === 'image' && it.shot_id && a.shot_id === it.shot_id; }).slice(-4);
      return '<div class="st-cardrow">' +
        '<div class="st-cardrow-h"><b>' + esc(it.shot_id || it.item_id) + '</b><span>' + esc(it.label) + '</span><span class="sp"></span>' +
          '<button type="button" class="btn mini" data-agent-run="image" data-shot-id="' + esc(it.shot_id || '') + '">▶ 重绘此镜</button>' +
        '</div>' +
        '<div style="font-size:.72rem;color:var(--text2)">' + esc(it.prompt) + '</div>' +
        (ast ? '<img class="st-thumb" src="' + esc(stAsset(p.id, ast.rel, ast.sha256)) + '" data-open-img="' + esc(ast.asset_id) + '" data-rel="' + esc(ast.rel) + '" data-sha="' + esc(ast.sha256 || '') + '" data-label="' + esc(ast.label || '') + '">' : '') +
        (vers.length > 1 ? '<div class="st-row">' + vers.map(function (v) {
          return '<button type="button" class="btn mini ' + (v.adopted ? 'primary' : 'ghost') + '" data-adopt-asset="' + esc(v.asset_id) + '">v' + v.version + (v.adopted ? ' 当前' : ' 回滚') + '</button>';
        }).join('') + '</div>' : '') +
      '</div>';
    }).join('') : '<div style="font-size:.74rem;color:var(--text3)">暂无分镜生图条目，可通过聊天或「导入剧本」生成。</div>') + '</div>';
}

function buildBgmPane(p) {
  var b = p.bgm || {};
  var bgmAst = b.asset_id ? (p.assets || []).filter(function (a) { return a.asset_id === b.asset_id; })[0] : null;
  return '<div class="st-field"><label>音乐风格 Prompt</label><textarea class="inp" id="stBgmPrompt" rows="2">' + esc(b.prompt || '') + '</textarea></div>' +
    '<div class="st-row2">' +
      '<div class="st-field"><label>时长（秒）</label><input class="inp st-num" id="stBgmSec" type="number" min="10" max="240" value="' + (b.seconds || 75) + '"></div>' +
      '<div class="st-field"><label>采样步数 / Seed</label>' +
        '<div class="st-row2"><input class="inp st-num" id="stBgmSteps" type="number" min="4" max="32" value="' + (b.steps || 8) + '">' +
        '<input class="inp st-num" id="stBgmSeed" type="number" value="' + (b.seed || 20261118) + '"></div>' +
      '</div>' +
    '</div>' +
    '<div class="st-row"><button type="button" class="btn mini primary" data-act="saveBgmCfg">保存配乐参数</button></div>' +
    (bgmAst ? '<audio controls preload="metadata" style="width:100%" src="' + esc(stAsset(p.id, bgmAst.rel, bgmAst.sha256)) + '"></audio>'
      : '<div style="font-size:.72rem;color:var(--text3)">尚未生成配乐文件 bgm/bgm.wav</div>');
}

/* ---------- 右栏：配音 + 视频生成（含分镜帧预览与 MP4 合成输出） ---------- */
function buildVoicePane(p) {
  var lines = (p.dialogues || []).slice().sort(function (a, b) { return a.order - b.order; });
  var merged = (p.assets || []).slice().reverse().filter(function (a) { return a.rel === 'tts/voice.wav'; })[0];
  return (merged ? '<div class="st-field"><label>全片合并音轨（tts/voice.wav）</label><audio controls preload="metadata" style="width:100%" src="' + esc(stAsset(p.id, merged.rel, merged.sha256)) + '"></audio></div>' : '') +
    '<div class="st-row"><button type="button" class="btn mini ghost" data-act="addLine">+ 新增一句台词</button></div>' +
    '<div class="st-cardgrid">' + (lines.length ? lines.map(function (d) {
      var ast = d.audio_asset_id ? (p.assets || []).filter(function (a) { return a.asset_id === d.audio_asset_id; })[0] : null;
      var vers = (p.assets || []).filter(function (a) { return a.kind === 'audio' && a.line_id === d.line_id; }).slice(-3);
      return '<div class="st-cardrow" data-line-card="' + esc(d.line_id) + '">' +
        '<div class="st-cardrow-h"><b>' + esc(d.line_id) + '</b><span>' + esc(d.shot_id) + '</span>' +
          '<select class="inp" data-line-role="' + esc(d.line_id) + '" style="min-height:1.5rem;width:4.2rem;font-size:.7rem">' +
            ST_ROLES.map(function (r) { return '<option value="' + r + '"' + (d.role === r ? ' selected' : '') + '>' + r + '</option>'; }).join('') +
          '</select>' +
          '<select class="inp" data-line-eng="' + esc(d.line_id) + '" style="min-height:1.5rem;width:4.5rem;font-size:.7rem">' +
            '<option value="auto"' + (d.engine === 'auto' ? ' selected' : '') + '>自动</option>' +
            '<option value="cloud"' + (d.engine === 'cloud' ? ' selected' : '') + '>百炼云</option>' +
            '<option value="local"' + (d.engine === 'local' ? ' selected' : '') + '>本地</option>' +
          '</select>' +
        '</div>' +
        '<div class="st-row2">' +
          '<select class="inp" data-line-spk="' + esc(d.line_id) + '">' + stVoiceOptions(d.speaker) + '</select>' +
          '<input class="inp" data-line-tone="' + esc(d.line_id) + '" placeholder="语气" value="' + esc(d.tone || '') + '">' +
        '</div>' +
        '<textarea class="inp" data-line-text="' + esc(d.line_id) + '" rows="2">' + esc(d.text || '') + '</textarea>' +
        (ast ? '<audio controls preload="metadata" style="width:100%;height:1.8rem" src="' + esc(stAsset(p.id, ast.rel, ast.sha256)) + '"></audio>' : '') +
        '<div class="st-row">' +
          '<button type="button" class="btn mini primary" data-line-save="' + esc(d.line_id) + '">保存</button>' +
          '<button type="button" class="btn mini" data-agent-run="voice" data-line-id="' + esc(d.line_id) + '">▶ 仅重配此句</button>' +
          '<button type="button" class="btn mini danger" data-line-del="' + esc(d.line_id) + '">删除</button>' +
        '</div>' +
        (vers.length > 1 ? '<div class="st-row">' + vers.map(function (v) {
          return '<button type="button" class="btn mini ' + (v.adopted ? 'primary' : 'ghost') + '" data-adopt-asset="' + esc(v.asset_id) + '">v' + v.version + (v.adopted ? ' 当前' : ' 回滚') + '</button>';
        }).join('') + '</div>' : '') +
      '</div>';
    }).join('') : '<div style="font-size:.74rem;color:var(--text3)">暂无台词，请先「导入剧本」或在中间群聊描述主题。</div>') + '</div>';
}

function buildVideoGenPane(p) {
  var shots = p.shots || [], cc = p.compose_config || {}, vFile = p.files && p.files.video;
  var framesHtml = shots.length ? '<div class="st-cardgrid">' + shots.map(function (s) {
    var ast = s.frame_asset_id ? (p.assets || []).filter(function (a) { return a.asset_id === s.frame_asset_id; })[0] : null;
    return '<div class="st-cardrow">' +
      '<div class="st-cardrow-h"><b>' + esc(s.shot_id) + '</b><span>' + esc(String(s.render || 'web').toUpperCase()) + ' · ' + s.duration_sec + 's</span></div>' +
      (ast ? '<img class="st-thumb" src="' + esc(stAsset(p.id, ast.rel, ast.sha256)) + '" data-open-img="' + esc(ast.asset_id) + '" data-rel="' + esc(ast.rel) + '" data-sha="' + esc(ast.sha256 || '') + '" data-label="' + esc(ast.label || '') + '">'
        : '<span style="font-size:.72rem;color:var(--text3)">尚未渲染视觉帧</span>') +
    '</div>';
  }).join('') + '</div>' : '<div style="font-size:.74rem;color:var(--text3)">暂无分镜视觉帧</div>';

  var composeHtml = '<div style="border-top:1px solid var(--ln);padding-top:.5rem;margin-top:.1rem;display:flex;flex-direction:column;gap:.45rem">' +
    '<div class="st-row2">' +
      '<div class="st-field"><label>成片帧率 FPS</label><select class="inp" id="stCmpFps">' +
        [24, 30, 60].map(function (f) { return '<option value="' + f + '"' + (+cc.fps === f ? ' selected' : '') + '>' + f + ' fps</option>'; }).join('') +
      '</select></div>' +
      '<div class="st-field"><label>淡入淡出（秒）</label><input class="inp st-num" id="stCmpFade" type="number" min="0" max="10" step="0.5" value="' + (cc.fade != null ? cc.fade : 2) + '"></div>' +
    '</div>' +
    '<div class="st-row2">' +
      '<div class="st-field"><label>配乐音量 <span id="stCmpVolVal" class="st-num">' + Math.round((+cc.bgm_volume || 0.18) * 100) + '%</span></label>' +
        '<input type="range" id="stCmpVol" min="0" max="100" value="' + Math.round((+cc.bgm_volume || 0.18) * 100) + '"></div>' +
      '<div class="st-field"><label>人声闪避 <span id="stCmpDuckVal" class="st-num">' + Math.round((+cc.duck_depth || 0.16) * 100) + '%</span></label>' +
        '<input type="range" id="stCmpDuck" min="0" max="80" value="' + Math.round((+cc.duck_depth || 0.16) * 100) + '"></div>' +
    '</div>' +
    '<div class="st-row">' +
      '<label style="font-size:.74rem;display:flex;align-items:center;gap:.3rem"><input type="checkbox" id="stCmpSub"' + (cc.subtitle !== false ? ' checked' : '') + '> 挂载 SRT 字幕</label>' +
      '<button type="button" class="btn mini ghost" data-act="saveComposeCfg">保存参数</button>' +
      '<button type="button" class="btn mini primary" data-agent-run="compose">▶ 合成 MP4 成片</button>' +
    '</div>' +
    (vFile && vFile.url
      ? '<video class="st-video" controls preload="metadata" src="' + esc(vFile.url) + '"></video>' +
        '<div class="st-row"><a class="btn mini ghost" href="' + esc(vFile.url) + '" download="' + esc((p.title || 'final') + '.mp4') + '">下载 MP4 成片</a>' +
          '<button type="button" class="btn mini primary" data-act="publishProject">提交到发布队列</button></div>'
      : '<div style="font-size:.72rem;color:var(--text3)">尚未压制 output/final.mp4，就绪后点击「▶ 合成 MP4 成片」即可输出</div>') +
  '</div>';

  return framesHtml + composeHtml;
}

/* ---------- 右下角专属 Agent 团队头像灯区 & 轻浮层 ---------- */
function renderAvatarDock() {
  var am = studioAgentMap(), p = studioProj() || {};
  var workingCount = 0;

  var tiles = ST_AGENT_ORDER.map(function (item) {
    var id = item[0], shortName = item[1], titleHint = item[2];
    var ag = am[id] || { id: id, name: shortName + ' Agent', status: 'idle', brief: '待命' };
    var st = ag.status || 'idle';
    var isWorking = st === 'running' || st === 'thinking';
    if (isWorking) workingCount++;

    var cls = 'st-av' +
      (isWorking ? ' working' : '') +
      (st === 'waiting_approval' || st === 'waiting_input' ? ' ' + st : '') +
      (st === 'completed' ? ' completed' : '') +
      (st === 'failed' ? ' failed' : '') +
      (STUDIO.inspectAgentId === id ? ' sel' : '');

    var stTxt = ST_STATUS_LABEL[st] || st;
    return '<button type="button" class="' + cls + '" data-av-click="' + esc(id) + '" title="' + esc(ag.name + ' · ' + titleHint + (ag.brief ? ' · ' + ag.brief : '')) + '">' +
      '<span class="st-av-face">' + (ST_AGENT_ICONS[id] || '') + '<i class="st-av-led" aria-hidden="true"></i></span>' +
      '<span class="st-av-name">' + esc(shortName) + '</span>' +
      '<span class="st-av-st">' + esc(stTxt) + '</span>' +
    '</button>';
  }).join('');

  var dockHtml = '<div class="st-avdock-h">' +
      '<b>Agent 团队实时灯区</b>' +
      '<span class="st-num" style="color:' + (workingCount ? 'var(--hot,var(--hud))' : 'var(--text3)') + '">' +
        (workingCount ? (workingCount + ' 个工作中 · 已亮起') : '全员待命 · 点击头像查看/调度') +
      '</span>' +
    '</div>' +
    '<div class="st-avgrid">' + tiles + '</div>';

  stPut('stAvatarDock', dockHtml);
  renderAgentInspect(p, am);
}

function renderAgentInspect(p, am) {
  var pop = $('#stAvInspect');
  if (!pop) return;
  var aid = STUDIO.inspectAgentId;
  if (!aid) {
    if (!pop.hidden) pop.hidden = true;
    stPut('stAvInspect', '');
    return;
  }
  var cfg = ST_AGENT_ORDER.filter(function (x) { return x[0] === aid; })[0];
  var ag = am[aid] || { id: aid, name: (cfg ? cfg[1] + ' Agent' : aid), responsibility: (cfg ? cfg[2] : ''), status: 'idle', brief: '待命' };
  var tasks = (p.tasks || []).filter(function (t) { return t.agent_id === aid; }).slice(-3).reverse();
  var stLabel = ST_STATUS_LABEL[ag.status] || ag.status;

  var qaHtml = '';
  if (aid === 'qa') {
    var qa = p.qa;
    qaHtml = '<div style="border-top:1px solid var(--ln);padding-top:.35rem;display:flex;flex-direction:column;gap:.25rem">' +
      '<div class="st-row"><button type="button" class="btn mini primary" data-act="runQa">运行 FFprobe 实时质检</button></div>' +
      (qa ? '<div style="font-size:.72rem;color:' + (qa.passed ? 'var(--ok)' : 'var(--bad)') + ';font-weight:600">' + esc(qa.score_label) + ' · ' + esc(qa.summary) + '</div>' +
        (qa.checks || []).map(function (c) {
          return '<div class="st-qacheck"><b class="' + (c.passed ? 'ok' : (c.severity === 'warn' ? 'warn' : 'bad')) + '">' + (c.passed ? 'PASS' : 'FAIL') + '</b>' +
            '<div><div>' + esc(c.name) + '</div><span>' + esc(c.detail) + '</span></div></div>';
        }).join('') : '<div style="font-size:.7rem;color:var(--text3)">尚未执行 FFprobe 质检</div>') +
    '</div>';
  }

  var extraScriptHtml = '';
  if (aid === 'supervisor' || aid === 'script' || aid === 'storyboard') {
    extraScriptHtml = '<div class="st-row">' +
      '<button type="button" class="btn mini ghost" data-act="planScript">DeepSeek 智能策划</button>' +
      '<button type="button" class="btn mini ghost" data-act="toggleImport">导入文本/JSON</button>' +
    '</div>';
  }

  var taskHtml = tasks.length ? tasks.map(function (tk) {
    return '<div class="st-cardrow">' +
      '<div class="st-cardrow-h"><b>' + esc(tk.title) + '</b><span class="sp"></span><span class="st-num">' + esc(ST_TASK_LABEL[tk.state] || tk.state) + ' · ' + Math.round(tk.progress || 0) + '%</span></div>' +
      '<div class="st-pbar"><b style="width:' + Math.max(0, Math.min(100, +tk.progress || 0)) + '%"></b></div>' +
      (tk.error ? '<div style="font-size:.7rem;color:var(--bad)">' + esc(tk.error) + '</div>' : '') +
      ((tk.state === 'running' || tk.state === 'ready' || tk.state === 'pending')
        ? '<div class="st-row"><button type="button" class="btn mini danger" data-task-act="' + esc(tk.task_id) + ':cancel">仅取消此任务</button></div>' : '') +
    '</div>';
  }).join('') : '';

  var html = '<div class="st-avpop-h">' +
      '<b>' + esc(ag.name) + '</b>' +
      '<span>' + esc(stLabel) + (ag.brief && ag.brief !== '待命' ? (' · ' + esc(ag.brief)) : '') + '</span>' +
      '<span class="sp"></span>' +
      '<button type="button" class="btn mini ghost" data-act="closeInspect">×</button>' +
    '</div>' +
    '<div style="font-size:.72rem;color:var(--text2)">职责：' + esc(ag.responsibility || (cfg ? cfg[2] : '')) + '</div>' +
    '<div class="st-row">' +
      '<button type="button" class="btn mini ghost" data-at-agent="' + esc(aid) + '">@ 提到聊天框</button>' +
      '<button type="button" class="btn mini primary" data-agent-run="' + esc(aid) + '">▶ 跑</button>' +
      '<button type="button" class="btn mini ghost" data-agent-act="' + esc(aid) + ':' + (ag.paused ? 'resume' : 'pause') + '">' + (ag.paused ? '恢复' : '暂停') + '</button>' +
      '<button type="button" class="btn mini danger" data-agent-act="' + esc(aid) + ':stop">停</button>' +
    '</div>' +
    extraScriptHtml +
    taskHtml +
    qaHtml;

  pop.hidden = false;
  stPut('stAvInspect', html);
}

/* ---------- 中栏：项目群聊与协同消息 ---------- */
function renderChatHead() {
  var p = studioProj() || {};
  var html = '<b>群聊协调</b>' +
    '<span class="st-num">' + esc(p.ratio || '9:16') + ' · ' + (p.target_duration || 60) + 's</span>' +
    '<button type="button" class="linkbtn" data-act="exportPack">导出策划包</button>' +
    '<div class="st-chat-filters">' +
      '<button type="button" data-cfilter="all" class="' + (STUDIO.chatFilter === 'all' ? 'on' : '') + '">全部</button>' +
      '<button type="button" data-cfilter="chat" class="' + (STUDIO.chatFilter === 'chat' ? 'on' : '') + '">对话</button>' +
      '<button type="button" data-cfilter="events" class="' + (STUDIO.chatFilter === 'events' ? 'on' : '') + '">事件</button>' +
    '</div>';
  stPut('stChatHead', html);
}

function stRenderInlineAssets(p, msg) {
  var assets = msg.assets || [];
  if (!assets.length) return '';
  var imgs = assets.filter(function (a) { return a.kind === 'image'; });
  var others = assets.filter(function (a) { return a.kind !== 'image'; });
  var out = '';

  if (imgs.length) {
    out += '<div class="st-artgrid">' + imgs.map(function (a) {
      var src = stAsset(p.id, a.rel, a.sha256);
      return '<div class="st-art-img" data-open-img="' + esc(a.asset_id) + '" data-rel="' + esc(a.rel) + '" data-sha="' + esc(a.sha256 || '') + '" data-label="' + esc(a.label || a.rel) + '">' +
        '<img src="' + esc(src) + '" alt="' + esc(a.label || '') + '">' +
        '<span title="' + esc(a.label || a.rel) + '">' + esc(a.label || a.rel) + '</span>' +
      '</div>';
    }).join('') + '</div>';
  }

  if (others.length) {
    out += '<div class="st-artgrid">' + others.map(function (a) {
      var src = stAsset(p.id, a.rel, a.sha256);
      if (a.kind === 'audio') {
        return '<div class="st-art-media">' +
          '<div class="st-art-media-h"><b>' + esc(a.label || a.rel) + '</b>' +
            '<span>' + (a.duration ? a.duration.toFixed(1) + 's' : '') + '</span></div>' +
          '<audio controls preload="metadata" src="' + esc(src) + '"></audio>' +
        '</div>';
      }
      if (a.kind === 'video') {
        return '<div class="st-art-media">' +
          '<div class="st-art-media-h"><b>' + esc(a.label || a.rel) + '</b>' +
            '<span><a class="linkbtn" href="' + esc(src) + '" download="' + esc((p.title || 'final') + '.mp4') + '">下载</a></span></div>' +
          '<video controls preload="metadata" src="' + esc(src) + '"></video>' +
        '</div>';
      }
      return '<div class="st-art-media"><div class="st-art-media-h"><b>' + esc(a.label || a.rel) + '</b></div></div>';
    }).join('') + '</div>';
  }

  return out;
}

function stRenderApprovalCard(p, msg) {
  var apr = (p.approvals || []).filter(function (a) { return a.approval_id === msg.approval_id; })[0];
  if (!apr) return '<div class="st-msg-bubble">' + esc(msg.text || '') + '</div>';
  var stMap = { pending: '待你确认', approved: '已批准执行', rejected: '已拒绝' };
  var items = (apr.affected_items || []).slice(0, 6);
  return '<div class="st-apr ' + esc(apr.status) + '">' +
    '<div class="st-apr-h"><b>' + esc(apr.title) + '</b><span class="st-apr-st">' + esc(stMap[apr.status] || apr.status) + '</span></div>' +
    '<div class="st-apr-sum">' + esc(apr.summary) + '</div>' +
    (items.length ? '<ul class="st-apr-list">' + items.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '') +
    '<div class="st-apr-foot">' +
      '<span class="st-apr-cost">预估 ¥' + (+apr.estimated_cost_cny || 0).toFixed(2) + ' / $' + (+apr.estimated_cost_usd || 0).toFixed(3) + '</span>' +
      (apr.status === 'pending'
        ? '<button type="button" class="btn mini primary" data-approve="' + esc(apr.approval_id) + '">批准并执行</button>' +
          '<button type="button" class="btn mini danger" data-reject="' + esc(apr.approval_id) + '">拒绝</button>'
        : (apr.decision_note ? '<span style="font-size:.68rem;color:var(--text3)">' + esc(apr.decision_note) + '</span>' : '')) +
    '</div>' +
  '</div>';
}

function renderMessages() {
  var p = studioProj() || {};
  var box = $('#stMsgs');
  if (!box) return;
  var nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 80;

  var msgs = (p.messages || []).filter(function (m) {
    if (STUDIO.chatFilter === 'chat') return m.kind !== 'task_event';
    if (STUDIO.chatFilter === 'events') return m.kind === 'task_event' || m.kind === 'discussion';
    return true;
  });

  var html = msgs.length ? msgs.map(function (m) {
    if (m.kind === 'task_event') {
      var es = esc(m.event_state || 'running');
      return '<div class="st-tevent">' +
        '<span class="st-tevent-dot ' + es + '"></span>' +
        '<time>' + esc(stFmtClock(m.ts)) + '</time>' +
        '<span title="' + esc(m.text) + '"><b>' + esc(m.sender_name) + '</b>：' + esc(m.text) + '</span>' +
      '</div>';
    }

    if (m.kind === 'discussion') {
      return '<details class="st-disc">' +
        '<summary>协作 · <b>' + esc(m.sender_name) + '</b> · ' + esc(stFmtClock(m.ts)) + '</summary>' +
        '<pre>' + esc(m.details || m.text) + '</pre>' +
      '</details>';
    }

    var isUser = m.kind === 'user';
    var quoteHtml = m.reply_preview ? '<div class="st-quote">回复：' + esc(m.reply_preview) + '</div>' : '';
    var mentionHtml = (m.mentions && m.mentions.length)
      ? '<span class="st-mentions">' + m.mentions.map(function (x) { return '@' + esc(x); }).join(' ') + '</span>' : '';
    var attachHtml = (m.attachments && m.attachments.length)
      ? '<div style="font-size:.68rem;color:var(--text3);margin-top:.18rem">附件：' + m.attachments.map(function (a) { return esc(a.name || a.rel); }).join('、') + '</div>' : '';

    var bodyHtml = m.kind === 'approval'
      ? stRenderApprovalCard(p, m)
      : ('<div class="st-msg-bubble">' + quoteHtml + esc(m.text || '') + attachHtml + '</div>' + stRenderInlineAssets(p, m));

    var jumpAttr = !isUser && m.sender_id && (m.sender_id === 'image' || m.sender_id === 'bgm' || m.sender_id === 'voice' || m.sender_id === 'video_gen')
      ? '<button type="button" class="linkbtn" data-jump-pane="' + esc(m.sender_id) + '">定位面板</button>' : '';

    return '<div class="st-msg ' + esc(m.kind) + '">' +
      '<div class="st-msg-meta">' +
        '<b>' + esc(m.sender_name || (isUser ? '你' : 'Agent')) + '</b>' +
        mentionHtml +
        '<time>' + esc(stFmtClock(m.ts)) + '</time>' +
        '<span class="st-msg-acts">' +
          '<button type="button" class="linkbtn" data-reply-msg="' + esc(m.msg_id) + '">引用</button>' +
          jumpAttr +
        '</span>' +
      '</div>' +
      bodyHtml +
    '</div>';
  }).join('') : '<div style="color:var(--text3);font-size:.76rem;padding:.75rem 0">暂无匹配消息。</div>';

  if (stPut('stMsgs', html) && nearBottom) {
    requestAnimationFrame(function () { box.scrollTop = box.scrollHeight; });
  }
}

function renderComposerMeta() {
  var rb = $('#stReplyBar');
  if (rb) {
    if (STUDIO.replyTo) {
      rb.hidden = false;
      rb.innerHTML = '<span>引用 <b>' + esc(STUDIO.replyTo.sender_name) + '</b>：' + esc(String(STUDIO.replyTo.text || '').slice(0, 48)) + '</span>' +
        '<button type="button" class="linkbtn" data-act="clearReply">取消</button>';
    } else {
      rb.hidden = true;
      rb.innerHTML = '';
    }
  }
  var ab = $('#stAttachBar');
  if (ab) {
    if (STUDIO.pendingAttachments.length) {
      ab.hidden = false;
      ab.innerHTML = '<span style="font-size:.68rem;color:var(--text3)">附件：</span>' +
        STUDIO.pendingAttachments.map(function (a, i) {
          return '<span style="font-size:.68rem;border:1px solid var(--line2);padding:.05rem .3rem">' +
            esc(a.name) + ' <button type="button" class="linkbtn" data-del-attach="' + i + '">×</button></span>';
        }).join('');
    } else {
      ab.hidden = true;
      ab.innerHTML = '';
    }
  }
}

/* ---------- 滚动定位并高亮指定板块 ---------- */
function stJumpToPane(paneId) {
  var id = paneId === 'compose' ? 'video_gen' : paneId;
  var el = $('#stPane-' + id);
  if (!el) return;
  if (STUDIO.collapsedPanes[id]) {
    STUDIO.collapsedPanes[id] = false;
    renderPaneHeaders();
  }
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  el.classList.add('flash');
  setTimeout(function () { el.classList.remove('flash'); }, 1200);
}

/* ---------- 保留全局兼容空钩子 ---------- */
function stHWStart() {}
function stHWStop() {}

/* ---------- 后端同步与生命周期 ---------- */
function studioFetch() {
  if (!useLive() || STUDIO.fetchBusy) { renderStudio(); return Promise.resolve(); }
  STUDIO.fetchBusy = true;
  var url = '/api/studio/state' + (STUDIO.pid ? '?pid=' + encodeURIComponent(STUDIO.pid) : '');
  return api('GET', url, null, 8000).then(function (j) {
    STUDIO.st = j;
    if (j && j.project && j.project.id) {
      STUDIO.pid = j.project.id;
      STUDIO.lastPid = j.project.id;
    }
    renderStudio();
  }).catch(function () {
    renderStudio();
  }).then(function () {
    STUDIO.fetchBusy = false;
  });
}

function studioPost(path, body, msg) {
  if (!useLive()) { toast('演示模式下只支持本地浏览，请切回实时后端', 3500); return Promise.resolve(null); }
  var p = studioProj();
  var payload = Object.assign({ pid: STUDIO.pid || (p && p.id) || '' }, body || {});
  return api('POST', '/api/studio/' + path, payload, 45000).then(function (j) {
    if (j && j.state) STUDIO.st = j.state;
    else if (j && j.project) STUDIO.st = j;
    if (msg) toast(msg);
    renderStudio(true);
    return j;
  }).catch(function (e) {
    toast(e.message || '操作失败', 6000);
    throw e;
  });
}

function studioReq(method, path, body, msg) {
  if (!useLive()) { toast('演示模式下不支持修改后端数据', 3500); return Promise.resolve(null); }
  var p = studioProj();
  var payload = Object.assign({ pid: STUDIO.pid || (p && p.id) || '' }, body || {});
  return api(method, '/api/studio/' + path, payload, 45000).then(function (j) {
    if (j && j.state) STUDIO.st = j.state;
    if (msg) toast(msg);
    renderStudio(true);
    return j;
  }).catch(function (e) {
    toast(e.message || '请求失败', 6000);
    throw e;
  });
}

function studioEnter() {
  studioLeave();
  studioFetch();
  STUDIO.t = setInterval(function () {
    if (S.view !== 'studio' || document.hidden || !useLive()) return;
    studioFetch();
  }, 1500);
}

function studioLeave() {
  if (STUDIO.t) clearInterval(STUDIO.t);
  STUDIO.t = null;
  $$('#view-studio audio, #view-studio video').forEach(function (m) {
    try { m.pause(); } catch (e) {}
  });
}

document.addEventListener('visibilitychange', function () {
  if (S.view !== 'studio') return;
  if (!document.hidden) studioFetch();
});

/* ---------- 发送聊天指令与附件 ---------- */
function stSendChat(overrideText) {
  var inp = $('#stChatInput');
  var text = typeof overrideText === 'string' ? overrideText : String(inp ? inp.value : '').trim();
  if (!text && !STUDIO.pendingAttachments.length) { toast('先输入指令或附上参考图/剧本'); return; }
  if (!overrideText && inp) inp.value = '';
  var replyId = STUDIO.replyTo ? STUDIO.replyTo.msg_id : undefined;
  var attachments = STUDIO.pendingAttachments.slice();
  STUDIO.replyTo = null;
  STUDIO.pendingAttachments = [];
  renderComposerMeta();

  studioPost('chat/send', {
    text: text || '请查看我上传的参考附件并给出下一步建议',
    reply_to: replyId,
    attachments: attachments,
  }).then(function () {
    var box = $('#stMsgs');
    if (box) box.scrollTop = box.scrollHeight;
  }).catch(function () {});
}

function stHandleChatFiles(files) {
  var p = studioProj();
  if (!p || !files || !files.length) return;
  [].slice.call(files).forEach(function (file) {
    var name = file.name || 'file';
    if (/\.(md|markdown|txt|json)$/i.test(name)) {
      var tr = new FileReader();
      tr.onload = function () {
        var content = String(tr.result || '');
        if (!content.trim()) return;
        studioPost('script/import', { text: content }, '已导入剧本文件：' + name).catch(function () {});
      };
      tr.readAsText(file);
    } else if (/^image\//i.test(file.type)) {
      var ir = new FileReader();
      ir.onload = function () {
        studioPost('ref', { name: name, data: ir.result }, '已上传参考图：' + name).then(function (j) {
          if (j && j.rel) {
            STUDIO.pendingAttachments.push({ rel: j.rel, name: name, kind: 'image' });
            renderComposerMeta();
          }
        }).catch(function () {});
      };
      ir.readAsDataURL(file);
    }
  });
}

function stUploadImageRefs(files) {
  var p = studioProj();
  if (!p || !files || !files.length) return;
  var cur = ((p.image_config && p.image_config.refs) || []).slice();
  var list = [].slice.call(files).slice(0, Math.max(0, 16 - cur.length));
  list.reduce(function (pr, f) {
    return pr.then(function () {
      return new Promise(function (resolve) {
        var r = new FileReader();
        r.onload = function () {
          api('POST', '/api/studio/ref', { pid: p.id, name: f.name, data: r.result }, 30000)
            .then(function (j) { if (j && j.rel) cur.push(j.rel); resolve(); })
            .catch(function (e) { toast(f.name + ' 上传失败：' + e.message); resolve(); });
        };
        r.readAsDataURL(f);
      });
    });
  }, Promise.resolve()).then(function () {
    studioPost('config', { image_config: { refs: cur } }, '已更新参考图 (' + cur.length + '/16)').catch(function () {});
  });
}

/* ---------- 事件代理 ---------- */
(function () {
  var v = $('#view-studio');
  if (!v) return;

  v.addEventListener('keydown', function (ev) {
    if (ev.target && ev.target.id === 'stChatInput' && ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      stSendChat();
    }
  });

  v.addEventListener('input', function (ev) {
    var t = ev.target;
    if (t.id === 'stCmpVol') stSetText('stCmpVolVal', t.value + '%');
    if (t.id === 'stCmpDuck') stSetText('stCmpDuckVal', t.value + '%');
  });

  v.addEventListener('change', function (ev) {
    var t = ev.target;
    if (t.id === 'stProj' && t.value) {
      STUDIO.pid = t.value;
      studioPost('select', { pid: t.value }).catch(function () {});
      return;
    }
    if (t.id === 'stChatFile') {
      stHandleChatFiles(t.files);
      t.value = '';
      return;
    }
    if (t.id === 'stRefUpload') {
      stUploadImageRefs(t.files);
      t.value = '';
      return;
    }
  });

  v.addEventListener('click', function (ev) {
    var p = studioProj();
    var t = ev.target;

    var avBtn = t.closest('[data-av-click]');
    if (avBtn) {
      var aid = avBtn.getAttribute('data-av-click');
      STUDIO.inspectAgentId = STUDIO.inspectAgentId === aid ? '' : aid;
      renderAvatarDock();
      return;
    }

    var atBtn = t.closest('[data-at-agent]');
    if (atBtn) {
      var aidAt = atBtn.getAttribute('data-at-agent');
      var agAt = studioAgents().filter(function (a) { return a.id === aidAt; })[0];
      var tag = '@' + ((agAt && agAt.name.replace(' Agent', '')) || aidAt) + ' ';
      var cin = $('#stChatInput');
      if (cin) {
        cin.value = (cin.value ? cin.value + ' ' : '') + tag;
        cin.focus();
      }
      return;
    }

    var foldBtn = t.closest('[data-fold-pane]');
    if (foldBtn) {
      var fid = foldBtn.getAttribute('data-fold-pane');
      STUDIO.collapsedPanes[fid] = !STUDIO.collapsedPanes[fid];
      renderPaneHeaders();
      return;
    }

    var jumpBtn = t.closest('[data-jump-pane]');
    if (jumpBtn) {
      stJumpToPane(jumpBtn.getAttribute('data-jump-pane'));
      return;
    }

    var imgBox = t.closest('[data-open-img]');
    if (imgBox && p) {
      var imgs = (p.assets || []).filter(function (a) { return a.kind === 'image'; });
      var rel = imgBox.getAttribute('data-rel');
      var items = imgs.map(function (a) {
        return { url: stAsset(p.id, a.rel, a.sha256), name: a.label || a.rel, rel: a.rel, pid: p.id, cacheHit: !!a.cache_hit };
      });
      var idx = Math.max(0, imgs.findIndex(function (a) { return a.rel === rel; }));
      if (!items.length && rel) {
        items = [{ url: stAsset(p.id, rel, imgBox.getAttribute('data-sha') || ''), name: imgBox.getAttribute('data-label') || rel, rel: rel, pid: p.id }];
        idx = 0;
      }
      if (window.Lightbox && items.length) Lightbox.open(items, idx);
      return;
    }

    var b = t.closest('button');
    if (!b || b.disabled) return;
    var d = b.dataset || {};

    if (b.id === 'stBtnSend') { stSendChat(); return; }
    if (d.atInsert) {
      var ci = $('#stChatInput');
      if (ci) { ci.value = (ci.value ? ci.value + ' ' : '') + d.atInsert; ci.focus(); }
      return;
    }
    if (d.quickCmd) { stSendChat(d.quickCmd); return; }
    if (d.cfilter) { STUDIO.chatFilter = d.cfilter; renderChatHead(); renderMessages(); return; }

    if (d.replyMsg && p) {
      var msg = (p.messages || []).filter(function (m) { return m.msg_id === d.replyMsg; })[0];
      if (msg) {
        STUDIO.replyTo = { msg_id: msg.msg_id, sender_name: msg.sender_name, text: msg.text };
        renderComposerMeta();
        var c2 = $('#stChatInput');
        if (c2) c2.focus();
      }
      return;
    }
    if (d.delAttach != null) { STUDIO.pendingAttachments.splice(+d.delAttach, 1); renderComposerMeta(); return; }

    if (d.approve) { studioPost('approval', { approval_id: d.approve, approved: true }, '已批准并开始调度执行').catch(function () {}); return; }
    if (d.reject) { studioPost('approval', { approval_id: d.reject, approved: false, note: '用户暂缓执行' }, '已拒绝本次审批').catch(function () {}); return; }

    if (d.agentRun) {
      var extra = {};
      if (d.shotId) extra.shot_id = d.shotId;
      if (d.lineId) extra.line_id = d.lineId;
      studioPost('agent/' + encodeURIComponent(d.agentRun) + '/run', { inputs: extra }, '已启动 Agent 任务').catch(function () {});
      return;
    }
    if (d.agentAct) {
      var ap = d.agentAct.split(':');
      studioPost('agent/' + encodeURIComponent(ap[0]) + '/action', { action: ap[1] }).catch(function () {});
      return;
    }
    if (d.taskAct) {
      var tp = d.taskAct.split(':');
      studioPost('task/' + encodeURIComponent(tp[0]) + '/action', { action: tp[1] }).catch(function () {});
      return;
    }
    if (d.adoptAsset) {
      studioPost('asset/adopt', { asset_id: d.adoptAsset }, '已切换采用资产版本').catch(function () {});
      return;
    }

    if (d.lineSave && p) {
      var lid = d.lineSave;
      var lc = v.querySelector('[data-line-card="' + lid + '"]');
      if (!lc) return;
      var lBody = {
        revision: p.revision,
        role: lc.querySelector('[data-line-role]').value,
        engine: lc.querySelector('[data-line-eng]').value,
        speaker: lc.querySelector('[data-line-spk]').value,
        tone: lc.querySelector('[data-line-tone]').value,
        text: lc.querySelector('[data-line-text]').value,
      };
      studioReq('PATCH', 'line/' + encodeURIComponent(lid), lBody, '已保存台词（仅此句配音缓存失效）').catch(function () {});
      return;
    }

    if (d.lineDel) {
      studioReq('DELETE', 'line/' + encodeURIComponent(d.lineDel), {}, '已删除该句台词').catch(function () {});
      return;
    }

    if (d.delRef != null && p) {
      var nr = ((p.image_config && p.image_config.refs) || []).slice();
      nr.splice(+d.delRef, 1);
      studioPost('config', { image_config: { refs: nr } }, '已移除参考图').catch(function () {});
      return;
    }

    if (d.act) {
      if (d.act === 'closeInspect') { STUDIO.inspectAgentId = ''; renderAvatarDock(); return; }
      if (d.act === 'toggleChatWidth') { STUDIO.chatWide = !STUDIO.chatWide; renderStudio(); return; }
      if (d.act === 'toggleNewProj') { STUDIO.newProjOpen = true; STUDIO.importOpen = false; renderTop(); var nt = $('#stNewTopic'); if (nt) nt.focus(); return; }
      if (d.act === 'cancelNewProj') { STUDIO.newProjOpen = false; renderTop(); return; }
      if (d.act === 'createProj') {
        var topEl = $('#stNewTopic'), ratEl = $('#stNewRatio'), secEl = $('#stNewSec');
        var topicVal = topEl ? topEl.value.trim() : '';
        STUDIO.newProjOpen = false;
        studioPost('new', { topic: topicVal || '新视频项目', ratio: ratEl ? ratEl.value : '9:16', seconds: secEl ? +secEl.value || 60 : 60 }, '已创建新项目').then(function (j) {
          if (j && j.project) STUDIO.pid = j.project.id;
        }).catch(function () {});
        return;
      }
      if (d.act === 'runFull') { stSendChat('开始从头跑通全流程制作并完成后期合成与质检'); return; }
      if (d.act === 'stopAll') { studioPost('stop', {}, '已停止全部正在运行的任务').catch(function () {}); return; }
      if (d.act === 'clearReply') { STUDIO.replyTo = null; renderComposerMeta(); return; }
      if (d.act === 'exportPack') {
        studioPost('export_prompt_pack', {}).then(function (j) {
          if (j && j.md) {
            var ci2 = $('#stChatInput');
            if (ci2) { ci2.value = j.md; ci2.focus(); toast('策划包模版已填入输入框'); }
          }
        }).catch(function () {});
        return;
      }
      if (d.act === 'planScript') {
        studioPost('script/plan', {
          topic: (p && p.title) || 'AI 效率工具',
          seconds: (p && p.target_duration) || 60,
        }, '剧本与分镜策划已更新').catch(function () {});
        return;
      }
      if (d.act === 'toggleImport') { STUDIO.importOpen = !STUDIO.importOpen; STUDIO.newProjOpen = false; renderTop(); var imp = $('#stImportText'); if (imp) imp.focus(); return; }
      if (d.act === 'doImport') {
        var it = $('#stImportText');
        if (!it || !it.value.trim()) { toast('请先贴入剧本内容'); return; }
        studioPost('script/import', { text: it.value }, '已导入剧本并生成结构化分镜').then(function () {
          STUDIO.importOpen = false;
          renderTop();
          renderAllPanes(true);
        }).catch(function () {});
        return;
      }
      if (d.act === 'addLine') {
        studioPost('line/add', { role: '白页', text: '补充一句新台词。', tone: '自然' }, '已新增台词').catch(function () {});
        return;
      }
      if (d.act === 'saveImgCfg') {
        studioPost('config', {
          image_config: {
            model: ($('#stImgModel') || {}).value,
            resolution: ($('#stImgRes') || {}).value,
            output: ($('#stImgOut') || {}).value,
          },
        }, '已保存生图参数').catch(function () {});
        return;
      }
      if (d.act === 'saveBgmCfg') {
        studioPost('config', {
          bgm: {
            prompt: ($('#stBgmPrompt') || {}).value,
            seconds: +($('#stBgmSec') || {}).value || 75,
            steps: +($('#stBgmSteps') || {}).value || 8,
            seed: +($('#stBgmSeed') || {}).value || 20261118,
          },
        }, '已保存配乐参数').catch(function () {});
        return;
      }
      if (d.act === 'saveComposeCfg') {
        var vol = +($('#stCmpVol') || {}).value;
        var duck = +($('#stCmpDuck') || {}).value;
        studioPost('config', {
          compose_config: {
            fps: +($('#stCmpFps') || {}).value || 24,
            fade: +($('#stCmpFade') || {}).value || 2,
            bgm_volume: isNaN(vol) ? 0.18 : vol / 100,
            duck_depth: isNaN(duck) ? 0.16 : duck / 100,
            subtitle: Boolean(($('#stCmpSub') || {}).checked),
          },
        }, '已保存视频合成参数').catch(function () {});
        return;
      }
      if (d.act === 'runQa') {
        studioPost('qa/run', {}, '已完成 FFprobe 实时质检').catch(function () {});
        return;
      }
      if (d.act === 'publishProject') {
        studioPost('to_publish', { title: (p && p.title) || '视频工坊成片' }, '已加入发布待确认队列').catch(function () {});
        return;
      }
    }
  });
})();
