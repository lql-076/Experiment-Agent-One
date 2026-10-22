'use strict';
/* ================= 演示数据（直接打开文件、没接后端时用） ================= */
var ROUTES = {
  local: { name: '本地小脑', color: 'var(--c-local)' },
  neu:   { name: '新类别', color: 'var(--c-neu)' },
  ds:    { name: 'DeepSeek', color: 'var(--c-ds)' },
  cl:    { name: '网页 Claude', color: 'var(--c-cl)' }
};
var ORDER = ['local', 'neu', 'ds', 'cl'];
var EVENTS = [
  { id: 1042, t: '22:00', src: '定时任务', text: '吃药提醒', to: 'local', label: '提醒（不经过模型）', s: { local: 100, neu: 0, ds: 0, cl: 0 },
    why: '定时提醒由程序直接发出，不需要决策脑判断。', result: 'QQ：已发出；界面卡片：已挂上。你回复了"吃了"，已打卡。',
    steps: [['收到', '定时任务触发'], ['本地处理', '提醒不经过任何模型'], ['送达', 'QQ、界面卡片']] },
  { id: 1041, t: '21:47', src: 'QQ', text: '帮我看看帕鲁最近更新了啥', to: 'ds', label: '', s: { local: 21, neu: 9, ds: 66, cl: 4 },
    why: '本地的把握只有 21%，低于接手线 60%，交给 DeepSeek。 语义路由 → DeepSeek 71%；Kev → DeepSeek 62%。', result: 'DeepSeek 整理了 3 条要点发给你。这次记录会成为以后的训练样本。',
    steps: [['收到', 'QQ 私聊'], ['决策脑打分', 'DeepSeek 66%'], ['交给 DeepSeek', '快速模式 · ¥0.0011'], ['回复', '已回复']] },
  { id: 1040, t: '21:30', src: 'QQ', text: '记住灵感：基地放在河边', to: 'local', label: '记住', s: { local: 100, neu: 0, ds: 0, cl: 0 },
    why: '你明确说了记住，直接写进记忆收件箱（本地文件，先斩后奏，可撤销）。', result: '记下了。',
    steps: [['收到', 'QQ 私聊'], ['认出「记住」', '不经过模型'], ['写记忆', '记忆/收件箱.md'], ['回复', '已回复']] },
  { id: 1039, t: '20:12', src: 'QQ', text: '我想改成多个 agent 协作，可行吗', to: 'cl', label: '', s: { local: 6, neu: 5, ds: 31, cl: 58 },
    why: '「找 Claude」得分 58%，超过 50%，属于很复杂的难题，建议你亲自去和 Claude 深聊。 语义路由 → 网页 Claude 64%；Kev → 网页 Claude 52%。', result: 'DeepSeek 已写好提示词，等你带去。聊完把总结 .md 带回来，会存进记忆。',
    steps: [['收到', 'QQ 私聊'], ['决策脑打分', '网页 Claude 58%'], ['写提示词', 'DeepSeek 附上背景'], ['回复', '已回复']] },
  { id: 1038, t: '19:05', src: 'QQ', text: '猫粮还能吃几天？', to: 'neu', label: '', s: { local: 22, neu: 48, ds: 26, cl: 4 },
    why: '所有本地小脑都低于新类别线 40%（最高 22%），像是一类新事情：先交给 DeepSeek，同时记为样本。 语义路由 → 新类别 55%；Kev → DeepSeek 40%。', result: '先由 DeepSeek 回答；每日差事会给这一类起名，攒够了训练新小脑。',
    steps: [['收到', 'QQ 私聊'], ['决策脑打分', '新类别 48%'], ['交给 DeepSeek', '快速模式 · ¥0.0009'], ['记为样本', '新类别']] },
  { id: 1037, t: '18:30', src: 'QQ', text: '最近老是睡不着', to: 'local', label: '本地通用', s: { local: 88, neu: 3, ds: 7, cl: 2 },
    why: '包含隐私关键词「睡不着」。按规则只在本地处理，不发给任何云端。', result: '本地小脑回复了几条睡前建议。',
    steps: [['收到', 'QQ 私聊'], ['决策脑打分', '本地通用 88%'], ['本地处理', '本地通用 · 96 个 token'], ['回复', '已回复']] }
];
var BRAINS = [
  { kind: '决策脑', name: '决策脑', sub: '两票：语义路由 50% · Kev 50%', st: '运行中', c: 'var(--accent)', note: '每件事先过它，只打分不说话。',
    ring: [91, '91', '%', '准确率'], trend: [84, 86, 85, 88, 89, 90, 91], tmax: 100, tl: '没被纠正的比例',
    stats: [['今日判断', '6', '次'], ['本周被纠正', '2', '次'], ['判例', '214', '条'], ['语义路由 / Kev 实测', '88 / 79', '%']], acts: ['运行中文实测', '现在启动 Kev'] },
  { kind: '本地小脑', name: '本地通用', sub: 'MiniCPM5-2B 底座 · 不加 LoRA', st: '闲置', c: 'var(--c-local)', note: '还没有专门的小脑时，本地的活都由它做，包括所有隐私内容。',
    ring: [0, '关', '', '底座'], trend: [0, 12, 25, 31, 36, 38, 50], tmax: 100, tl: '本地处理比例',
    stats: [['今日接手', '3', '次'], ['精度', '4bit', ''], ['闲置卸载', '15', '分钟'], ['显存', '—', 'GB']], acts: ['现在加载', '卸载'] },
  { kind: '新类别', name: '宠物', sub: '还没有小脑，暂交 DeepSeek', st: '攒样本中', c: 'var(--c-neu)', note: '攒够 200 条（真实 + 造的样本）就能训练专属小脑。',
    ring: [18.5, '37', '/200', '样本'], trend: [5, 9, 14, 20, 26, 31, 37], tmax: 200, tl: '累计样本',
    stats: [['还差', '163', '条'], ['第一次出现', '10-09', '']], acts: [] },
  { kind: '云端', name: 'DeepSeek', sub: 'deepseek-flash · API', st: '有 Key', c: 'var(--c-ds)', note: '长对话和一般难题；它的处理记录也是小脑的教材。每日差事里还负责打标签、整理记忆。余额来自官方接口；花费是本机按 token 估算的。',
    ring: [95.5, '¥8.59', '', '余额'], trend: [9, 12, 8, 11, 7, 10, 6], tmax: 15, tl: '每日调用',
    stats: [['余额', '¥8.59', ''], ['本月花了（估算）', '¥0.41', ''], ['今日花了（估算）', '¥0.030', ''], ['本月调用', '63', '次'], ['贡献样本', '58', '条']], acts: ['刷新余额', '去充值'] },
  { kind: '云端', name: '网页 Claude', sub: '你本人带提示词去聊', st: '有提示词等你', c: 'var(--c-cl)', note: '非常复杂的难题；聊完把总结 .md 带回来，只当参考资料读，不进训练集。',
    ring: [75, '3', '/4', '总结已带回'], trend: [0, 1, 0, 1, 1, 0, 1], tmax: 2, tl: '每日求助',
    stats: [['待处理提示词', '1', '份'], ['已带回总结', '3', '份']], acts: ['复制最新提示词', '导入总结'] }
];
var WEEK = [['10-12', 8], ['10-13', 12], ['10-14', 25], ['10-15', 31], ['10-16', 36], ['10-17', 38], ['10-18', 50]];
var WEEK_SPLIT = { local: 16, neu: 6, ds: 15, cl: 4 };
var CHANGES = [
  { id: 1, w: '新增提醒「吃药」（每天 22:00）', e: '你在对话里说的 · 10-18 20:02', can_undo: true },
  { id: 2, w: '修改「记忆/关于我.md」', e: '每日整理：合并收件箱里的 4 条 · 10-18 14:20', can_undo: true },
  { id: 3, w: '追加「记忆/收件箱.md」', e: '你让我记住的内容 · 10-17 21:30', can_undo: true }
];
var ASKS = [
  { id: 1, w: '想给自己加一个"读网页"的新工具', e: '属于"加新工具或新权限"，必须先问你' },
  { id: 2, w: '想删除 7 天前的临时文件 42 个', e: '属于"删除文件"' }
];
var DEMO_REM = [{ id: 1, title: '吃药', text: '该吃药了，吃完回我一句"吃了"', kind: 'daily', at: '22:00', every_min: 90, days: '1234567', enabled: 1 }];
var SAFETY = [
  { k: 'brain', n: '新建、更新小脑', h: '删掉适配器文件即可恢复', d: 'auto' },
  { k: 'skill', n: '新增、修改技能和记忆文件', h: '用 git 可一键退回', d: 'auto' },
  { k: 'cron', n: '新增、修改定时任务', h: '', d: 'auto' },
  { k: 'prompt', n: '调整自己的提示词', h: '会影响它的性格和说话方式，可以改成先问你', d: 'auto' },
  { k: 'del', n: '删除任何文件', lock: true },
  { k: 'perm', n: '给自己加新工具或新权限', lock: true },
  { k: 'money', n: '花钱：充值、换更贵的模型、提高额度', lock: true },
  { k: 'priv', n: '把隐私内容发出本机', lock: true },
  { k: 'claude', n: '把 Claude 的回答、总结或聊天记录拿去训练模型', h: 'Anthropic 的用户条款不允许用 Claude 的服务训练 AI 模型。这些内容只当参考资料读', lock: true, lockText: '固定不做' }
];

/* 主题清单来自 themes/themes.js（Agent 启动时扫描 themes 文件夹自动生成）。一个 .css 文件就是一套主题。 */
var THEMES = (window.AGENT_THEMES && window.AGENT_THEMES.length) ? window.AGENT_THEMES : [{ id: 'abyss', name: '深海', desc: '' }];
function themeVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function hasTheme(id) { return THEMES.some(function (t) { return t.id === id; }); }

/* ================= 放到哪：路径 ================= */
var DEMO_PLACES = { root: 'D:\\Agent', base: 'D:\\Agent\\models\\base\\MiniCPM5-2B', embed: 'D:\\Agent\\models\\embed\\Qwen3-Embedding-0.6B',
  brains: 'D:\\Agent\\models\\brains', kev: 'D:\\Agent\\kev', aienv: 'D:\\Agent\\ai-env', memory: 'D:\\Agent\\memory',
  hfcache: 'D:\\Agent\\models\\hf-cache', training: 'D:\\Agent\\training', logs: 'D:\\Agent\\data\\logs' };
var PLACES = null;
var DS_MODELS = null, DS_MANUAL = false;   // 用 Key 查到的模型列表（设置 › 云端 的下拉框）
function P(k) { return (PLACES || DEMO_PLACES)[k] || ''; }
function fillPlace(s) { return String(s || '').replace(/\{(\w+)\}/g, function (_, k) { return P(k); }); }

/* ================= 整备清单 ================= */
var CHECKS = [
  { k: 'driver', t: '显卡驱动', how: '运行 nvidia-smi，读取显卡和驱动版本', place: '直接安装，不用放文件', demo: ['ok', 'RTX 5060 Ti · 驱动 581.57 · 16311 MiB'],
    why: '显卡版 PyTorch 需要支持 CUDA 12.8 的驱动。去 NVIDIA 中国官网选 RTX 5060 Ti，下载 Game Ready 或 Studio 驱动，直接安装。', links: [['NVIDIA 驱动下载（中国）', 'https://www.nvidia.cn/drivers/lookup/']] },
  { k: 'python', t: 'Python 3.12', how: '后端就是用它运行的，读版本号', place: '直接安装（安装第一页勾选 Add python.exe to PATH）', demo: ['ok', 'Python 3.12.7（后端正在用它运行）'],
    why: '装 3.12.x 的 64 位版本。官网慢就用国内镜像，进 3.12 开头的文件夹，下载 python-3.12.x-amd64.exe。', links: [['Python 官网', 'https://www.python.org/downloads/windows/'], ['国内镜像（npmmirror）', 'https://registry.npmmirror.com/binary.html?path=python/']] },
  { k: 'git', t: 'Git', auto: 1, how: '运行 git --version', place: '{root}\\tools\\git（一键补齐装的便携版，不装进系统）', demo: ['ok', 'git version 2.51.0.windows.1'], go: 'memory',
    why: '记录 agent 的每次改动，报告里的"撤销"靠它。一键补齐会从国内镜像下一个便携版 MinGit 放进 tools\\git，只给 agent 用。想自己装完整版也行：用国内镜像下载 Git-x.xx-64-bit.exe。', links: [['Git 国内镜像（npmmirror）', 'https://registry.npmmirror.com/binary.html?path=git-for-windows/']] },
  { k: 'aienv', auto: 1, t: '本地模型环境（显卡版 PyTorch）', how: '用 ai-env 里的 Python 导入 torch，看能不能用显卡', place: '{aienv}（自动生成，不用手动放）', demo: ['ok', 'PyTorch 2.8.0+cu128 · CUDA 12.8 · Transformers 5.20.1 · PEFT 0.21.2'],
    why: '双击 Agent 文件夹里的「安装本地模型环境.bat」：它会建 ai-env 文件夹，从阿里云镜像装 PyTorch 2.8（cu128），再从 PyPI 装 Transformers、PEFT 和 Kev。约 3GB，第一次要等一会。', links: [['阿里云 PyTorch 镜像（cu128）', 'https://mirrors.aliyun.com/pytorch-wheels/cu128/']] },
  { k: 'base', auto: 1, t: '底座 MiniCPM5-2B', how: '检查文件夹里有没有 config.json 和 .safetensors', place: '{base}', demo: ['ok', '模型文件在 · 4.7 GB'], go: 'models',
    why: '从魔搭下载整个模型文件夹（原始精度约 5GB，加载时自动压成 4bit，约占 2GB 显存）。双击「下载模型.bat」会自动下好放对位置；手动下载就把所有文件放进上面这个文件夹，打开文件夹直接能看到 config.json。', links: [['魔搭 OpenBMB/MiniCPM5-2B', 'https://www.modelscope.cn/models/OpenBMB/MiniCPM5-2B/files']] },
  { k: 'embed', auto: 1, t: '嵌入模型 Qwen3-Embedding-0.6B', how: '检查文件夹里有没有 config.json 和 .safetensors', place: '{embed}', demo: ['ok', '模型文件在 · 1.1 GB'], go: 'models',
    why: '决策脑的第一票（语义路由）和找记忆都靠它，常驻约 1.2GB 显存。「下载模型.bat」会一起下；手动下载同样整个文件夹放进去。', links: [['魔搭 Qwen/Qwen3-Embedding-0.6B', 'https://www.modelscope.cn/models/Qwen/Qwen3-Embedding-0.6B/files']] },
  { k: 'models', auto: 1, t: '本地模型服务', how: '连接 127.0.0.1:8090，看嵌入模型有没有加载', place: '日志在 {logs}\\model_server.log', demo: ['ok', '显卡 RTX 5060 Ti · 嵌入模型已加载 · 底座闲置（用到才加载） · 占显存 1.2 GB'], act: ['start_models', '现在启动'],
    why: '装好环境和两个模型后，启动 Agent 时会自动拉起它。启动失败就看上面的日志文件最后几行。' , links: [] },
  { k: 'kev', auto: 1, t: '决策脑 Kev-0.8B', how: '连接 127.0.0.1:8091，看 Kev 服务在不在线', place: '源码在 {kev}（已打包）；权重下载到 {hfcache}', demo: ['wait', '按需启动：用到时自动启动；第一次启动会下载约 2GB 权重'], act: ['start_kev', '现在启动 Kev'], go: 'models',
    why: '决策脑的第二票。源码已经随项目打包（Apache-2.0 许可），装环境时一起装好。第一次启动会经 hf-mirror 下载权重（Kev 适配器 + Qwen3.5-0.8B 底座）。下载不动就在 设置 › 本地模型 把 Kev 先关掉，决策脑只用语义路由一票也能工作。', links: [['hf-mirror 上的 Kev 权重', 'https://hf-mirror.com/jaredpalmer/kev-0.8b']] },
  { k: 'hwmon', auto: 1, t: '硬件监控', how: '读取 127.0.0.1:8085/data.json，看有没有 CPU 温度', place: '不用放文件，双击「硬件监控.bat」', demo: ['ok', '传感器可读 · CPU 47°C'], go: 'hw',
    why: '一键补齐会帮你启动它（弹一次管理员确认）。显卡占用、显存、显卡功耗不用它也能读（驱动自带）。CPU 温度、功耗和硬盘温度要靠它：双击「硬件监控.bat」，会请求管理员权限。CPU 温度还要装一次 PawnIO 驱动。', links: [['PawnIO 驱动', 'https://pawnio.eu']] },
  { k: 'ds', t: 'DeepSeek API Key', how: '用 Key 查一次账户余额', place: '填在 设置 › 云端（加密保存在本机）', demo: ['miss', '还没有填 Key'], go: 'cloud',
    why: '长对话和一般难题交给它，每日差事里还负责打标签和整理记忆；一键补齐某一步失败时，也是它看日志选修法。不设每月上限，界面上直接显示官方查到的余额。', links: [['DeepSeek 开放平台 · API Keys', 'https://platform.deepseek.com/api_keys']] },
  { k: 'qq', t: 'QQ 官方机器人', how: '用 AppID 和 AppSecret 换一次访问凭证，再连 WebSocket', place: '填在 设置 › QQ 通道', demo: ['miss', '还没有填 AppID 和 AppSecret'], go: 'qq',
    why: '在 QQ 开放平台创建机器人，拿到 AppID 和 AppSecret。先开沙箱，把你自己的 QQ 加进沙箱成员；在功能配置里打开单聊（C2C）消息。用 WebSocket 接入，不需要公网地址。', links: [['QQ 开放平台', 'https://q.qq.com']] },
  { k: 'qqbind', t: '绑定你的 QQ', how: '看机器人有没有收到你的消息', place: '用你的 QQ 给机器人发一句话', demo: ['wait', '收到一条消息「你好」，是你发的就点「是我」'], act: ['qq_bind', '是我'],
    why: '绑定后它只回复你这一个 QQ，别人发来的消息一律不理。', links: [] },
  { k: 'qqpush', t: '测试主动提醒', how: '主动发一条测试消息，看 QQ 收不收得到', place: '不用放文件', demo: ['wait', '还没测过：点按钮发一条测试提醒'], act: ['qq_test', '发测试提醒'],
    why: '提醒靠主动消息。你在 QQ 里关掉了"允许主动发送"就会失败，这时会自动改成电脑弹窗 + 界面卡片。', links: [] },
  { k: 'memory', t: '记忆文件夹', how: '看文件夹在不在、有没有 git 记录', place: '{memory}', demo: ['ok', '文件夹在 · git 记录中'], go: 'memory',
    why: '启动时自动创建，记忆、技能、提示词全是中文 Markdown。想放进 Obsidian：在 设置 › 记忆与文件 填库里的一个子文件夹。', links: [['Obsidian 官网', 'https://obsidian.md']] },
  { k: 'search', t: '联网搜索', later: true, why: '让 DeepSeek 能查最新资料。需要一个国内能用的搜索接口，下一步再接。', links: [] },
  { k: 'train', t: '小脑训练（Unsloth / PEFT）', later: true, why: '慢成长：样本攒够后先问你，你说开始才训练新小脑。训练用的就是现在这套本地模型环境。', links: [['Unsloth', 'https://unsloth.ai']] },
  { k: 'voice', t: '语音（听写 + 说话）', later: true, why: '以后接：本地听写和说话，QQ 语音消息也能直接发给它。', links: [] },
  { k: 'rea', t: 'REA 逆向工具', later: true, why: '只认官方仓库 morluto/rea，网上有带木马的假冒版本。', links: [['REA 官方仓库', 'https://github.com/morluto/rea']] }
];
var LIVE_CHECKS = CHECKS.filter(function (c) { return !c.later; });

/* ================= 设置 ================= */
var SECTIONS = [
  { id: 'prep', name: '整备', desc: '这里只放"能不能在这台电脑上跑起来"的项，每次启动自动自检。能自动装的点「一键补齐」；剩下的 DeepSeek Key、QQ 机器人要你自己填。', custom: 'prep' },
  { id: 'remind', name: '提醒', fields: [{ k: 'quiet', l: '免打扰', t: 'toggle', d: false, h: '开着时只发提醒（吃药这类照常准时）；别的主动消息先攒着，关掉后一起发给你。不设时段，什么时候开关由你' }], desc: '提醒不经过任何模型，显卡被游戏占满也照样准时。先发 QQ；QQ 发不出去就弹电脑通知；同时在界面上挂一张卡片，直到你点"好了"或"晚点"。也可以直接在 QQ 里说"每天晚上十点提醒我吃药"。', custom: 'remind' },
  { id: 'models', name: '本地模型', desc: '只用显卡，不用 CPU。路径留空就用默认位置（Agent 文件夹里），一般不用改。', fields: [
    { k: 'baseDir', l: '底座文件夹（MiniCPM5-2B）', place: 'base', h: '放魔搭下载的整个模型文件夹，里面直接能看到 config.json' },
    { k: 'embedDir', l: '嵌入模型文件夹（Qwen3-Embedding-0.6B）', place: 'embed' },
    { k: 'loraDir', l: '小脑（LoRA）存放文件夹', place: 'brains', h: '每个小脑一个子文件夹，训练出来会自动放这里' },
    { k: 'kevDir', l: 'Kev 源码文件夹', place: 'kev', h: '已随项目打包，一般不用改' },
    { k: 'baseQuant', l: '底座精度', t: 'select', d: '4bit', o: [['4bit', '4bit（约 2GB 显存，默认）'], ['8bit', '8bit（约 3GB）'], ['bf16', '原始精度（约 5GB）']] },
    { k: 'idleUnload', l: '底座和 Kev 闲置多久卸载', t: 'number', u: '分钟', d: 15, h: '常驻的只有嵌入模型，其余用到才加载' },
    { k: 'kevMode', l: 'Kev（决策脑第二票）', t: 'select', d: 'ondemand', o: [['ondemand', '用到才启动（默认）'], ['resident', '一直开着（约多占 2GB）'], ['off', '关闭，只用语义路由']] },
    { k: 'hfMirror', l: '下载 Kev 权重走国内镜像 hf-mirror', t: 'toggle', d: true },
    { k: 'yieldAuto', l: '让路模式：玩游戏、画图时自动让出显卡', t: 'toggle', d: true, h: '显卡占用持续很高时卸载底座，非隐私的活交 DeepSeek，隐私的活排队' },
    { k: 'yieldGpuLoad', l: '让路的显卡占用线', t: 'range', min: 30, max: 95, step: 5, u: '%', d: 60 },
    { k: 'modelPort', l: '模型服务端口', t: 'number', d: 8090, h: '和别的程序撞端口了就改这里' },
    { k: 'kevPort', l: 'Kev 端口', t: 'number', d: 8091 },
    { note: '只用显卡跑模型：检测不到显卡时模型服务直接拒绝工作，不会偷偷用 CPU。这一条固定，改不了。' }
  ] },
  { id: 'cloud', name: '云端', desc: 'DeepSeek 负责长对话和一般难题；非常复杂的难题建议你带提示词去找网页端 Claude。', custom: 'cloud', fields: [
    { k: 'dsKey', l: 'DeepSeek API Key', t: 'secret', h: '加密保存在本机（Windows DPAPI），只有你这个 Windows 账号能解开；导出设置时不包含' },
    { k: 'dsModel', l: '模型', t: 'model', d: 'deepseek-flash', h: '点「获取模型列表」，用你的 Key 查官方现在能用哪些模型，再从下拉框里选；列表里没有的也可以手动填' },
    { k: 'dsLow', l: '余额低于多少时提醒你', t: 'number', u: '元', d: 2, h: '只是提醒，不会停用。余额不够时 DeepSeek 自己会拒绝调用' },
    { k: 'dsThinking', l: '思考模式', t: 'select', d: 'auto', o: [['auto', '自动：难题才开（默认）'], ['off', '一直关（最省钱）'], ['on', '一直开']] },
    { k: 'dsBase', l: '接口地址', d: 'https://api.deepseek.com' },
    { note: '花了多少钱是按官方价格自动估算的（闲时、忙时自动区分），不用你填。准确的数字以上面的余额为准。' },
    { k: 'claudeTpl', l: '找 Claude 时的提示词开头', t: 'textarea', d: '我在搭一个自己的本地 agent。下面是遇到的问题和相关背景，请帮我分析。聊完请输出一份简短的 Markdown 总结，方便我带回给 agent 学习。' }
  ] },
  { id: 'qq', name: 'QQ 通道', desc: '用 QQ 官方机器人和你说话，WebSocket 接入，不需要公网地址，不用非官方接口，没有封号风险。', fields: [
    { k: 'qqEnabled', l: '启用 QQ 通道', t: 'toggle', d: true },
    { k: 'qqAppId', l: 'AppID' },
    { k: 'qqSecret', l: 'AppSecret', t: 'secret', h: '加密保存在本机' },
    { k: 'qqSandbox', l: '沙箱模式（测试期间打开）', t: 'toggle', d: true, h: '沙箱里只有你加进去的成员能和它说话' },
    { k: 'qqUser', l: '只回复这个用户（openid）', ph: '不用手填：给机器人发一句话后，在 整备 › 绑定你的 QQ 点「是我」', h: '其他人发来的消息一律不处理' },
    { note: '单聊主动消息官方允许，每人每天上限 1000 条；但你在 QQ 里可以关掉"允许主动发送"，这时提醒会改成电脑弹窗 + 界面卡片。你 55 分钟内说过话的话，提醒会用被动回复，最稳。' }
  ] },
  { id: 'memory', name: '记忆与文件', desc: '记忆、技能、提示词都是中文 Markdown，你随时能打开看、改。agent 只能读写这个文件夹。', fields: [
    { k: 'memDir', l: 'agent 自己的文件夹', place: 'memory', h: '想放进 Obsidian 库就填库里的一个子文件夹，比如 D:\\Obsidian\\我的库\\agent' },
    { k: 'useGit', l: '用 git 记录每次改动（可一键撤销）', t: 'toggle', d: true },
    { k: 'logDays', l: '日志保留天数', t: 'number', u: '天', d: 90 }
  ] },
  { id: 'routing', name: '分流旋钮', desc: '决策脑每次给四个去向打分，这几条线决定交给谁。', fields: [
    { k: 'take', l: '本地小脑接手线', t: 'range', min: 5, max: 95, step: 5, u: '%', d: 60, h: '本地小脑的把握低于这条线，就交给 DeepSeek' },
    { k: 'fresh', l: '新类别线', t: 'range', min: 5, max: 95, step: 5, u: '%', d: 40, h: '所有小脑都低于这条线、又不像已知的事，记为新类别并开始攒样本' },
    { k: 'clLine', l: '建议找 Claude 的线', t: 'range', min: 20, max: 95, step: 5, u: '%', d: 50 },
    { k: 'voteEmbed', l: '语义路由这一票的权重', t: 'range', min: 0, max: 100, step: 5, u: '%', d: 50, h: 'Kev 的权重 = 100% 减去它' },
    { k: 'voteAuto', l: '实测后自动定权重', t: 'toggle', d: true },
    { k: 'privWords', l: '额外隐私关键词', ph: '逗号分隔，比如：前任, 某某医院', h: '出现任何一个词，这件事就只在本地处理。内置名单已经包含药、医院、病、密码、银行卡等' },
    { note: '隐私内容只在本地处理：这一条固定，改不了。关键词名单和决策脑判断两道关，任何一道认为是隐私就不发给云端。' }
  ] },
  { id: 'growth', name: '成长与训练', desc: '快成长是改文件夹，当场生效；慢成长是训练模型，开始前一定先问你。DeepSeek 每天帮忙打标签、整理记忆、造样本。', custom: 'growth', fields: [
    { k: 'fast', l: '快成长：允许自动写技能和记忆', t: 'toggle', d: true },
    { k: 'nightly', l: '每日差事（打标签、给新类别起名、整理记忆、造样本）', t: 'toggle', d: true, h: '不按钟点：电脑开着、你 20 分钟没找它时跑，一天一次。只用 DeepSeek 和很少的显卡' },
    { k: 'synthetic', l: '出题造样本（新小脑不用干等真实记录）', t: 'toggle', d: true },
    { k: 'realFloor', l: '真实样本至少占', t: 'range', min: 20, max: 80, step: 5, u: '%', d: 25, h: '防止越训越偏' },
    { k: 'samples', l: '新建一个小脑需要的样本数', t: 'number', u: '条', d: 200 },
    { k: 'slow', l: '慢成长：攒够样本后问我要不要训练', t: 'toggle', d: true, h: '不按时段、不限显存：攒够了就用 QQ 和电脑通知问你「现在开始训练吗」。回「开始」才开始；回「等等」或者没回，过一阵再问。训练本身下一步再接上，现在先攒样本' },
    { k: 'trainAsk', l: '没回的话，隔多久再问', t: 'number', u: '小时', d: 2 },
    { k: 'pass', l: '新小脑上线的及格线', t: 'range', min: 60, max: 99, step: 1, u: ' 分', d: 85 },
  ] },
  { id: 'safety', name: '安全线', desc: '能撤销的事可以先斩后奏，事后写进报告；撤销不了的事必须先问你。分级写死在代码里，不让模型自己判断；没登记的新动作默认先问。', custom: 'safety' },
  { id: 'hw', name: '硬件监控', desc: '常驻模式里的占用、频率、温度、功耗从这里来。显卡数据由驱动直接提供；CPU 温度、功耗和硬盘温度要靠「硬件监控.bat」。', fields: [
    { k: 'hwSource', l: '数据来源', t: 'select', d: 'auto', o: [['auto', '真实数据（后端读取）'], ['demo', '演示数据']] },
    { k: 'hwUrl', l: '硬件监控助手地址', d: 'http://127.0.0.1:8085/data.json', h: '「硬件监控.bat」默认就是这个；用 LibreHardwareMonitor 程序自带的网页服务也行' },
    { k: 'hwInterval', l: '刷新间隔', t: 'select', d: '2', o: [['1', '1 秒'], ['2', '2 秒'], ['5', '5 秒']] },
    { k: 'sysOther', l: '其他部件功耗估计', t: 'number', u: 'W', d: 45, h: '主板、内存、硬盘、7 把风扇等，读不到，只能估' },
    { k: 'psuEff', l: '电源转换效率', t: 'range', min: 80, max: 95, step: 1, u: '%', d: 89, h: '金牌电源在常见负载下大约 87% 到 90%' },
    { note: '整机功耗是估算值：CPU 和显卡功耗读传感器，加上其他部件的估计，再按电源效率折算到插座端。普通电源没法用软件读出真实整机功耗；要准确数字，需要能联机的智能电源，或者插座上的电量计。' }
  ] },
  { id: 'look', name: '外观', desc: '所有改动立即生效。', custom: 'look', fields: [
    { k: 'bright', l: '整体亮度', t: 'range', min: 50, max: 100, step: 5, u: '%', d: 100, h: '默认 100% 就是不调暗' },
    { k: 'warmth', l: '暖色护眼', t: 'range', min: 0, max: 30, step: 2, u: '%', d: 4, h: '减少蓝光，晚上可以调高' },
    { k: 'autoScale', l: '界面随窗口放大', t: 'toggle', d: true, h: '窗口越大，字和图越大，铺满屏幕；关掉就一直是原始大小' },
    { k: 'scale', l: '文字大小（在上面的基础上再调）', t: 'range', min: 80, max: 130, step: 5, u: '%', d: 100 },
    { k: 'uiShell', l: '打开方式', t: 'select', d: 'desk', o: [['desk', '无边框窗口（默认，支持 Windows 贴靠）'], ['desk-basic', '无边框窗口（简易拖动，贴靠出问题时用）'], ['edge', 'Edge 应用窗口（带系统标题栏）']], h: '下次启动生效。无边框窗口打不开时会自动改用 Edge' },
    { k: 'closeAct', l: '点侧栏「关闭」时', t: 'select', d: 'ask', o: [['ask', '每次问我（默认）'], ['window', '只关窗口，后台继续运行'], ['quit', '退出 Agent，全部停掉']], h: '只关窗口时提醒、QQ 照常，再双击 启动.bat 就能打开' },
    { k: 'motion', l: '动效', t: 'select', d: 'smooth', o: [['smooth', '丝滑'], ['reduced', '减弱'], ['off', '关闭']], h: '每套风格有自己的滚动和鼠标手感。减弱：去掉视差、倾斜、惯性、磁吸，只留简短的出场；关闭：什么都不动，吸顶、吸附、横条照常' },
    { k: 'perf', l: '性能优先', t: 'toggle', d: false, h: '关掉背景光晕动画和模糊过渡，手感按「减弱」来（玩游戏时省点显卡）' },
    { k: 'layout', l: '布局', t: 'select', d: 'auto', o: [['auto', '自动（按窗口比例）'], ['landscape', '固定横屏'], ['portrait', '固定竖屏']] },
    { k: 'h24', l: '24 小时制', t: 'toggle', d: true }
  ] },
  { id: 'auto', name: '自动化', desc: '让界面自己照顾自己：没人用时进入常驻，启动时自动自检。', fields: [
    { k: 'idleRes', l: '无操作多久自动进入常驻', t: 'select', d: '5', o: [['0', '关闭'], ['1', '1 分钟（测试用）'], ['5', '5 分钟'], ['10', '10 分钟'], ['15', '15 分钟'], ['30', '30 分钟'], ['60', '60 分钟']] },
    { k: 'startRes', l: '打开时直接进入常驻', t: 'toggle', d: false },
    { k: 'bootShow', l: '启动时显示自检过程', t: 'toggle', d: true, h: '关掉后在后台静默自检，有缺失才提醒' },
    { k: 'secs', l: '常驻时钟显示秒', t: 'toggle', d: false },
    { k: 'hideCursor', l: '常驻时自动隐藏鼠标', t: 'toggle', d: true },
    { k: 'drift', l: '常驻时内容缓慢移动，防止屏幕烙印', t: 'toggle', d: true },
    { k: 'toastFallback', l: 'QQ 发不出去时弹电脑通知', t: 'toggle', d: true },
    { k: 'resCard', l: '提醒在界面上挂卡片，直到你确认', t: 'toggle', d: true },
    { k: 'renotifyMin', l: '没确认的话，过多久再提醒', t: 'number', u: '分钟', d: 30 },
    { k: 'renotifyMax', l: '最多再提醒几次', t: 'number', u: '次', d: 2 }
  ] },
  { id: 'data', name: '数据', desc: '设置、记录、记忆都只在这台电脑上。', custom: 'data' }
];
var DEFAULTS = { theme: 'abyss', demo: true };
SECTIONS.forEach(function (sec) { (sec.fields || []).forEach(function (f) { if (f.k && f.t !== 'secret') DEFAULTS[f.k] = f.d === undefined ? '' : f.d; }); });

/* ================= 状态 ================= */
var KEY = 'agentShell.v3';
function loadStore() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
var stored = loadStore();
var S = {
  set: Object.assign({}, DEFAULTS, stored.set || {}),
  manual: stored.manual || {}, safety: stored.safety || {}, secret: {},
  check: {}, lastCheck: null, checking: false,
  view: 'home', sec: 'prep', selId: null, filter: 'all', fix: {}, bsel: -1, done: {}, resetArm: false
};
var LIVE = false, SECRETS = {};
var D = { state: null, events: [], brains: null, report: null, reminders: [], sig: {} };
function useLive() { return LIVE && !S.set.demo; }
function save() { try { localStorage.setItem(KEY, JSON.stringify({ set: S.set, manual: S.manual, safety: S.safety })); } catch (e) {} }
function smooth() { return !!document.startViewTransition && S.set.motion === 'smooth'; }       // 完整动效
function moving() { return !!document.startViewTransition && S.set.motion !== 'off'; }          // 丝滑或减弱：有过渡
function vt(fn) { if (moving()) { try { return document.startViewTransition(fn); } catch (e) {} } fn(); return null; }
function replay(el) { if (!el) return; el.classList.remove('anim-in'); void el.offsetWidth; el.classList.add('anim-in'); }
