import type { ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  applyMarkdownListToModules,
  createWavBuffer,
  type StudioAsset,
  type StudioJobState,
  type StudioShot,
  type VoiceLine,
} from './studio-runtime.ts';
import { StudioOrchestrator } from './studio-orchestrator.ts';
import { applyParsedScriptToProject, syncProjectDerivedViews } from './studio-tools.ts';
import type { AgentId, StudioAssetVersion, StudioProjectV2 } from './studio-types.ts';
import {
  callApiyiImage,
  callBailianSyncVoices,
  callBailianTts,
  fetchApiyiModels,
} from './cloud-apis.ts';

export const ROOT_DIR = process.cwd();
export const UI_DIR = path.join(ROOT_DIR, 'ui');
export const DOCS_DIR = path.join(ROOT_DIR, 'docs');
export const SKILLS_DIR = path.join(ROOT_DIR, 'skills');
export const VERSION = '4.0.1';
export const PORT = 3000;
export const STARTED_AT = Date.now() / 1000;

export const SECRET_KEYS = ['dsKey', 'qqSecret', 'blKey', 'imgKey', 'hfToken'] as const;
export type SecretKey = (typeof SECRET_KEYS)[number];

export const LOCKED_SETTINGS: Record<string, boolean> = {
  gpuOnly: true,
  privLocal: true,
};

export const PERM_SETTINGS = new Set([
  'wsDir',
  'wsRun',
  'agDownload',
  'agVoice',
  'agVoiceCloud',
  'agImage',
  'agMusic',
  'agPublish',
  'agPublishAsk',
  'ccOn',
  'ccCmd',
  'ccBash',
]);

export const SETTINGS_DEFAULTS: Record<string, unknown> = {
  theme: 'dark',
  bright: 100,
  warmth: 4,
  scale: 100,
  motion: 'smooth',
  perf: false,
  layout: 'auto',
  h24: true,
  demo: false,
  autoScale: true,
  uiShell: 'browser',
  closeAct: 'ask',
  idleRes: '5',
  startRes: false,
  bootShow: false,
  secs: false,
  hideCursor: true,
  drift: true,
  baseDir: '',
  embedDir: '',
  loraDir: '',
  kevDir: '',
  aiPython: '',
  modelPort: 8090,
  kevPort: 8091,
  baseQuant: '4bit',
  idleUnload: 15,
  kevMode: 'ondemand',
  kevRun: 'jaredpalmer/kev-0.8b',
  hfMirror: true,
  yieldAuto: true,
  yieldVram: 2.0,
  yieldCool: 3,
  gpuOnly: true,
  ttsPort: 8092,
  ttsIdle: 10,
  ttsGap: 0.35,
  ttsParaGap: 0.7,
  ttsOut: '',
  ttsPython: '',
  ttsWhole: true,
  ttsEngine: 'local',
  blBase: 'https://dashscope.aliyuncs.com/api/v1',
  blModel: 'qwen-audio-3.1-tts-plus',
  blPrice: 1.4,
  blMax: 2000,
  imgBase: 'https://api.apiyi.com/v1',
  imgModel: 'gpt-image-2.5-sunburst-vip',
  imgQuality: 'high',
  imgRes: '2k',
  imgConc: 1,
  imgOut: '',
  imgNoText: true,
  imgWithDir: false,
  dsBase: 'https://api.deepseek.com',
  dsModel: 'deepseek-chat',
  dsVision: 'deepseek-chat',
  dsLow: 2,
  usdCny: 7.2,
  priceIn: 0.15,
  priceHit: 0.003,
  priceOut: 0.6,
  peakX: 2,
  dsThinking: 'auto',
  searchOn: true,
  searchDaily: 200,
  searchRounds: 4,
  osdOn: false,
  osdWhen: 'game',
  osdItems: 'fps,low1,cpu,gpu,vram,power',
  osdPos: 'tl',
  osdMargin: 16,
  osdLayout: 'v',
  osdScreen: 0,
  osdSize: 'm',
  osdOpacity: 80,
  osdHotkey: 'ctrl+alt+f10',
  strongOn: true,
  strongName: '更强的模型',
  strongMode: 'manual',
  claudeTpl:
    '我在搭一个自己的本地 agent。下面是遇到的问题和相关背景，请帮我分析。聊完请输出一份简短的 Markdown 总结，方便我带回给 agent 学习。',
  qqEnabled: false,
  qqAppId: '',
  qqUser: '',
  qqSandbox: true,
  qqSendImg: true,
  memDir: '',
  useGit: false,
  logDays: 90,
  readDirs: [],
  wsDir: '',
  wsRun: true,
  wsTimeout: 900,
  wsRounds: 40,
  agSteps: 120,
  agBudget: 5.0,
  agImageMax: 8,
  agDownload: true,
  agVoice: true,
  agVoiceCloud: false,
  agImage: false,
  agMusic: true,
  agPublish: false,
  agPublishAsk: true,
  pubHeadless: true,
  pubBrowser: '',
  pubDecl: '内容由AI生成',
  ccOn: false,
  ccAuto: true,
  ccCmd: '',
  ccModel: '',
  ccMinutes: 60,
  ccBash: 'python,pip,ffmpeg,ffprobe,node,npm,npx,git',
  bgmUrl: 'http://127.0.0.1:8094',
  bgmDir: '',
  bgmIdle: 10,
  bgmOut: '',
  bgmSteps: 8,
  bgmFormat: 'wav',
  bgmMig: 340,
  imgMig: 1816,
  voiceOn: false,
  voiceUrl: 'http://127.0.0.1:8093',
  voiceDir: '',
  voiceModel: '',
  voicePython: '',
  voiceIdle: 10,
  voiceDesc: '二十岁出头的年轻女声，声音清亮温柔，语速自然，像朋友聊天',
  voiceCfg: 4.0,
  voiceSeed: 20261111,
  voiceRefText: '',
  voiceMax: 400,
  voiceAuto: true,
  voiceHands: false,
  voiceAll: false,
  voiceEngine: 'auto',
  voiceCmd: '',
  voiceSpeaker: 'Vivian',
  voiceFast: 'auto',
  take: 60,
  fresh: 40,
  clLine: 50,
  daily: 3,
  quiet: false,
  privLocal: true,
  privWords: '',
  voteEmbed: 50,
  voteAuto: true,
  fast: true,
  slow: true,
  samples: 200,
  pass: 85,
  trainAsk: 2,
  nightly: true,
  synthetic: true,
  realFloor: 25,
  logRetainDays: 180,
  uiState: {},
  toastFallback: true,
  resCard: true,
  renotifyMin: 30,
  renotifyMax: 2,
  hwSource: 'auto',
  hwUrl: 'http://127.0.0.1:8085/data.json',
  hwInterval: '2',
  sysOther: 45,
  psuEff: 89,
  hwOn: false,
  fpsSkip: '',
};

export interface EventItem {
  id: number;
  t: string;
  date: string;
  ts: number;
  src: string;
  text: string;
  to: 'local' | 'neu' | 'ds' | 'cl';
  label: string;
  private: boolean;
  s: { local: number; neu: number; ds: number; cl: number };
  why: string;
  result: string;
  reply: string;
  steps: [string, string, number?][];
  fix: string | null;
  teacher: string | null;
  status: 'running' | 'done' | 'queued' | 'err';
  cost: number;
  latency: number;
  plan: { text: string; st: 'todo' | 'doing' | 'done' }[];
  engine: string | null;
  votes: {
    mode: string | null;
    embed: { top: string | null; p: number; maxsim?: number; private_p?: number } | null;
    kev: { top: string | null; p: number; maxsim?: number; private_p?: number } | null;
    weights?: Record<string, number> | null;
  };
  files: Array<{ id: number; kind: string; name: string; path: string; url?: string }>;
}

export interface ReminderItem {
  id: number;
  title: string;
  kind: 'daily' | 'interval' | 'once';
  at: string;
  every_min: number;
  days: string;
  once_ts: number | null;
  text: string;
  enabled: boolean;
  next_ts: number | null;
}

export interface FeedEntry {
  ts: number;
  text: string;
  kind: 'head' | 'step' | 'ok' | 'warn' | 'err' | 'ds' | 'info' | 'prog';
  job: string;
  step?: string;
  old?: boolean;
}

export interface TelemetryEntry {
  ts: number;
  cat: string;
  action: string;
  target: string;
  status: string;
  dur_ms: number | null;
  metrics: Record<string, unknown>;
  msg: string;
  trace_id: string;
}

export interface ChatJob {
  ts: number;
  eid: number | null;
  done: boolean;
  event: EventItem | null;
  err: string | null;
  confirm: boolean;
  stopped?: boolean;
  interjections: string[];
}

export interface StudioModule {
  id: string;
  type: 'script' | 'image' | 'voice' | 'bgm' | 'compose' | 'publish';
  title: string;
  x: number;
  y: number;
  w: number;
  h: number;
  params: Record<string, unknown>;
  outputs: Array<{ kind: string; rel: string; label?: string; line?: string; sha256?: string; duration?: number }>;
  status: string;
  error: string;
  cache_key?: string;
  cache_hit: boolean;
  runtime?: {
    status: string;
    pct: number;
    phase: string;
    started_at?: number;
    last_took_s?: number;
  };
}

export interface StudioProject {
  id: string;
  name: string;
  title: string;
  desc: string;
  tags: string[];
  ratio: string;
  created: string;
  files: Record<string, unknown>;
  total_seconds: number;
  duration: number;
  resolution: string;
  video_ok: boolean;
  dir: string;
  lists: Record<string, string>;
  modules: StudioModule[];
}

function nowTimeStr(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function nowDateStr(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function formatDateTime(ts: number): string {
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function computeNextTs(r: Omit<ReminderItem, 'next_ts'>): number | null {
  if (!r.enabled) return null;
  const now = Date.now() / 1000;
  if (r.kind === 'once') {
    return r.once_ts && r.once_ts > now ? r.once_ts : null;
  }
  if (r.kind === 'interval') {
    const mins = Math.max(5, Number(r.every_min) || 90);
    return Math.round(now + mins * 60);
  }
  const [hh, mm] = (r.at || '22:00').split(':').map((x) => Number(x) || 0);
  const candidate = new Date();
  candidate.setHours(hh, mm, 0, 0);
  if (candidate.getTime() / 1000 <= now) {
    candidate.setDate(candidate.getDate() + 1);
  }
  return Math.round(candidate.getTime() / 1000);
}

const initTs = Math.floor(Date.now() / 1000);

class AppStore {
  settings: Record<string, unknown> = { ...SETTINGS_DEFAULTS };
  secrets: Record<SecretKey, string> = {
    dsKey: process.env.DEEPSEEK_API_KEY || '',
    qqSecret: '',
    blKey: process.env.BAILIAN_API_KEY || '',
    imgKey: process.env.APIYI_API_KEY || '',
    hfToken: process.env.HF_TOKEN || '',
  };
  safety: Record<string, 'auto' | 'ask'> = {
    'memory.write': 'auto',
    'reminder.create': 'auto',
    'reminder.update': 'auto',
    'brain.create': 'ask',
    'prompt.update': 'ask',
    money: 'ask',
    'file.delete': 'ask',
    'tool.add': 'ask',
  };
  events: EventItem[] = [];
  nextEventId = 1;
  memories: Array<{ id: number; text: string; ts: number }> = [];
  nextMemoryId = 1;
  reminders: ReminderItem[] = [];
  nextReminderId = 1;
  changes: Array<{ id: number; w: string; e: string; kind: string; undone: boolean; can_undo: boolean }> = [];
  asks: Array<{ id: number; w: string; e: string; kind: string; status: string }> = [];
  feed: FeedEntry[] = [];
  feedVer = 1;
  telemetry: TelemetryEntry[] = [];
  cards: Array<{ id: number; delivery_id: number; title: string; text: string; ts: number }> = [];
  checksRes: Record<string, { st: string; d: string; place?: string; heal?: boolean }> = {};
  checksTs = initTs;
  hwHistory: { cpu: number[]; gpu: number[]; ram: number[]; vram: number[]; pw: number[]; fps: number[] } = {
    cpu: [],
    gpu: [],
    ram: [],
    vram: [],
    pw: [],
    fps: [],
  };
  prevCpuTimes: { idle: number; total: number } | null = null;
  chatJobs = new Map<string, ChatJob>();
  readDirs: Array<{ path: string; cloud: boolean }> = [];
  wsDir = path.join(ROOT_DIR, 'workspace');
  wsRun = true;
  dsModels: { models: string[]; ts: number } | null = null;
  dsBalance: { total: number; currency: string; ts: number; err?: string } | null = null;
  searchToday = 0;
  searchMonth = 0;
  costMonthCny = 0;
  wishes: Array<{ ts: number; text: string }> = [];
  claudePrompts: Array<{ ts: number; prompt: string; done: boolean }> = [];
  summaries: Array<{ rel: string; ts: number }> = [];
  studioOrch!: StudioOrchestrator;
  studioTasks = new Map<string, { aborted: boolean; procs: Set<ChildProcess> }>();
  studioJobs = new Map<string, StudioJobState>();
  private gpuLockOwner: string | null = null;
  private gpuWaiters: Array<() => void> = [];
  get studioProjects(): Map<string, StudioProjectV2> {
    return this.studioOrch.projects;
  }
  get activeStudioId(): string {
    return this.studioOrch.getActiveProjectId();
  }
  ttsVoices: Array<{ id: number; name: string; desc: string; seed: number }> = [
    { id: 1, name: '解说男声', desc: '三十岁左右的男声，声音低沉温和，吐字清楚，语速平稳，像科技频道的解说', seed: 20261028 },
  ];
  nextVoiceId = 2;
  ttsPronDict: { pronunciation: Record<string, string>; replace: Record<string, string> } = {
    pronunciation: { 重庆: 'chong2 qing4' },
    replace: {},
  };
  imgBoard: Record<string, unknown> | null = null;
  imgJob: Record<string, unknown> | null = null;
  imgStopFlag = false;
  imgRecent: Array<Record<string, unknown>> = [];
  imgBuffers = new Map<string, { buf: Buffer; mime: string }>();
  imgMonth = { n: 0, usd: 0 };
  imgExtraModels: Array<Record<string, unknown>> = [];
  imgModelsTs: number | null = null;
  nextImgHistId = 1;

  ttsJob: Record<string, unknown> | null = null;
  ttsStopFlag = false;
  ttsDraft: Record<string, unknown> | null = null;
  ttsDraftWav: Buffer | null = null;
  ttsTryCache = new Map<string, Buffer>();
  ttsCloudMine: Array<Record<string, unknown>> = [];
  ttsCloudMonth = { n: 0, cny: 0, bill: 0 };

  ttsBatchBoard: Record<string, unknown> | null = null;
  bgmBatchBoard: Record<string, unknown> | null = null;
  pubPending: Array<Record<string, unknown>> = [];
  ccodeJob: Record<string, unknown> | null = null;
  trainAsk: { cat: string; count: number; msg: string } | null = null;

  constructor() {
    this.studioOrch = new StudioOrchestrator({
      wsDir: this.wsDir,
      settings: this.settings,
      secrets: this.secrets,
      ttsPronDict: this.ttsPronDict,
      imgMonth: this.imgMonth,
      ttsCloudMonth: this.ttsCloudMonth,
      ttsCloudMine: this.ttsCloudMine,
      imgExtraModels: this.imgExtraModels,
      pubPending: this.pubPending,
      sampleHardware: () => this.sampleHardware(),
      addFeed: (t, k, j) => this.addFeed(t, k, j),
    });
    this.seedInitialState();
    this.refreshChecks();
    this.sampleHardware();
  }

  private seedInitialState(): void {
    const t0 = initTs - 3600;
    this.events.push({
      id: this.nextEventId++,
      t: nowTimeStr(t0),
      date: nowDateStr(t0),
      ts: t0,
      src: '界面',
      text: '系统已就绪：查看当前运行环境与说明文档',
      to: 'local',
      label: '系统就绪（Node.js 22）',
      private: false,
      s: { local: 92, neu: 5, ds: 3, cl: 0 },
      why: '已迁移至 Node.js 22 + Express 运行时，前端控制台可直接交互。',
      result: 'Node.js 运行时服务正常',
      reply:
        '已启动 Experiment Agent One Web 控制台。你可以直接查看系统监控、浏览说明文档、编辑提醒、配置 DeepSeek API Key 进行实时对话，或在视频工坊中策划与管理剧本清单。',
      steps: [
        ['收到', '系统初始化', 0.01],
        ['本地处理', '加载内置配置与内存状态', 0.05],
        ['回答', '控制台就绪', 0.08],
      ],
      fix: null,
      teacher: null,
      status: 'done',
      cost: 0,
      latency: 0.08,
      plan: [
        { text: '挂载静态资源与主题引擎', st: 'done' },
        { text: '初始化内存状态存储与容器硬件采样', st: 'done' },
        { text: '对外开放 0.0.0.0:3000 服务', st: 'done' },
      ],
      engine: null,
      votes: { mode: 'rule', embed: { top: 'local', p: 92, maxsim: 0.91 }, kev: null, weights: { embed: 0.5, kev: 0.5 } },
      files: [],
    });

    const remBase: Omit<ReminderItem, 'next_ts'> = {
      id: this.nextReminderId++,
      title: '喝水与起身活动',
      kind: 'interval',
      at: '22:00',
      every_min: 90,
      days: '1234567',
      once_ts: null,
      text: '已经连续工作一个半小时啦，起来活动一下吧。',
      enabled: false,
    };
    this.reminders.push({ ...remBase, next_ts: computeNextTs(remBase) });

    this.addFeed('Experiment Agent One Node.js 后端已启动（0.0.0.0:' + PORT + '）', 'head', '后端');
    this.addFeed('已加载 /ui 前端界面与 /docs 中文架构文档', 'ok', '后端');
  }

  addFeed(text: string, kind: FeedEntry['kind'] = 'info', job = '后端', step?: string): void {
    this.feed.push({ ts: Date.now() / 1000, text, kind, job, step });
    if (this.feed.length > 600) {
      this.feed = this.feed.slice(-600);
    }
    this.feedVer++;
  }

  addTelemetry(items: Partial<TelemetryEntry>[]): number {
    for (const raw of items) {
      this.telemetry.push({
        ts: typeof raw.ts === 'number' ? raw.ts : Date.now(),
        cat: String(raw.cat || 'ui'),
        action: String(raw.action || 'event'),
        target: String(raw.target || ''),
        status: String(raw.status || 'ok'),
        dur_ms: typeof raw.dur_ms === 'number' ? raw.dur_ms : null,
        metrics: raw.metrics && typeof raw.metrics === 'object' ? (raw.metrics as Record<string, unknown>) : {},
        msg: String(raw.msg || ''),
        trace_id: String(raw.trace_id || ''),
      });
    }
    if (this.telemetry.length > 1000) {
      this.telemetry = this.telemetry.slice(-1000);
    }
    return items.length;
  }

  secretHints(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const k of SECRET_KEYS) {
      const v = this.secrets[k] || '';
      out[k] = v ? `••••${v.slice(-4)}` : '';
    }
    return out;
  }

  updateSettings(changes: Record<string, unknown>): Record<string, unknown> {
    const applied: Record<string, unknown> = {};
    for (const [k, raw] of Object.entries(changes || {})) {
      if (!(k in SETTINGS_DEFAULTS) || k in LOCKED_SETTINGS || PERM_SETTINGS.has(k)) continue;
      const def = SETTINGS_DEFAULTS[k];
      let val: unknown = raw;
      if (typeof def === 'boolean') {
        val = Boolean(raw);
      } else if (typeof def === 'number') {
        const parsed = Number(raw);
        if (Number.isNaN(parsed)) continue;
        val = Number.isInteger(def) ? Math.trunc(parsed) : parsed;
      } else if (typeof def === 'object' && def !== null && !Array.isArray(def)) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue;
        const cur = (this.settings[k] as Record<string, unknown>) || {};
        val = { ...cur, ...(raw as Record<string, unknown>) };
      } else if (Array.isArray(def)) {
        continue;
      } else {
        val = raw == null ? '' : String(raw);
      }
      if (JSON.stringify(this.settings[k]) !== JSON.stringify(val)) {
        this.settings[k] = val;
        applied[k] = val;
      }
    }
    return applied;
  }

  sampleHardware(): Record<string, unknown> {
    const cpus = os.cpus();
    let idle = 0;
    let total = 0;
    for (const c of cpus) {
      idle += c.times.idle;
      total += c.times.user + c.times.nice + c.times.sys + c.times.idle + c.times.irq;
    }
    let cpuLoad = Math.min(100, Math.round((os.loadavg()[0] / Math.max(1, cpus.length)) * 1000) / 10);
    if (this.prevCpuTimes) {
      const dIdle = idle - this.prevCpuTimes.idle;
      const dTotal = total - this.prevCpuTimes.total;
      if (dTotal > 0) {
        cpuLoad = Math.round((1 - dIdle / dTotal) * 1000) / 10;
      }
    }
    this.prevCpuTimes = { idle, total };

    const totalMemGb = os.totalmem() / 1024 ** 3;
    const freeMemGb = os.freemem() / 1024 ** 3;
    const usedMemGb = Math.max(0, totalMemGb - freeMemGb);
    const ramLoad = totalMemGb > 0 ? Math.round((usedMemGb / totalMemGb) * 1000) / 10 : 0;

    const rawCpuName = (cpus[0]?.model || 'Linux x64 CPU')
      .replace(/\((R|TM)\)/gi, '')
      .replace(/\s+\d+-Core.*$/i, '')
      .trim();
    const clockGhz = cpus[0]?.speed ? Math.round((cpus[0].speed / 1000) * 100) / 100 : null;
    const cpuPower = Math.round((15 + cpuLoad * 0.45) * 10) / 10;
    const other = Number(this.settings.sysOther) || 45;
    const eff = (Number(this.settings.psuEff) || 89) / 100;
    const sysPower = Math.round(((cpuPower + other) / eff) * 10) / 10;

    const pushHist = (arr: number[], v: number) => {
      arr.push(v);
      if (arr.length > 60) arr.shift();
    };
    pushHist(this.hwHistory.cpu, cpuLoad);
    pushHist(this.hwHistory.gpu, 0);
    pushHist(this.hwHistory.ram, ramLoad);
    pushHist(this.hwHistory.vram, 0);
    pushHist(this.hwHistory.pw, sysPower);

    return {
      src: 'linux-os',
      ok: true,
      sources: { sensors: false, cpuTemp: false },
      cpu: {
        name: rawCpuName || 'Container CPU',
        load: cpuLoad,
        clock: clockGhz,
        temp: null,
        power: cpuPower,
      },
      gpu: {
        name: '无独立 GPU（容器环境）',
        load: null,
        clock: null,
        temp: null,
        power: null,
        vram: null,
        vramTotal: null,
        vramPct: null,
      },
      ram: {
        load: ramLoad,
        used: Math.round(usedMemGb * 10) / 10,
        total: Math.round(totalMemGb * 10) / 10,
        freq: null,
        desc: `${Math.round(totalMemGb)} GB · ${cpus.length} vCPU`,
      },
      sys: { power: sysPower },
      disks: [],
      fps: null,
      fpsSeen: [],
    };
  }

  places(): Record<string, string> {
    return {
      root: ROOT_DIR,
      models: path.join(ROOT_DIR, 'models'),
      aienv: path.join(ROOT_DIR, 'ai-env'),
      ttsenv: path.join(ROOT_DIR, 'tts-env'),
      memory: path.join(ROOT_DIR, 'memory'),
      training: path.join(ROOT_DIR, 'training'),
      logs: path.join(ROOT_DIR, 'logs'),
      ws: this.wsDir,
      ttsOut: path.join(ROOT_DIR, '配音输出'),
      imgOut: path.join(ROOT_DIR, '生图输出'),
      bgmOut: path.join(ROOT_DIR, '配乐输出'),
    };
  }

  checkOne(k: string): { st: string; d: string; place?: string } {
    const p = this.places();
    switch (k) {
      case 'driver':
        return { st: 'miss', d: 'Linux 无显卡容器环境：不支持本地 NVIDIA 驱动', place: '容器环境' };
      case 'python':
        return { st: 'ok', d: `Node.js ${process.version}（服务端运行中）`, place: process.execPath };
      case 'git':
        return { st: 'ok', d: 'Git 工具可按需使用', place: '系统环境' };
      case 'aienv':
        return { st: 'miss', d: '本地 PyTorch/CUDA 环境未接入（容器环境无 GPU）', place: p.aienv };
      case 'base':
        return { st: 'miss', d: '本地底座模型未安装（云端模式下可用 DeepSeek）', place: p.models };
      case 'embed':
        return { st: 'miss', d: '本地嵌入模型未安装（使用关键词与规则分流）', place: p.models };
      case 'models':
        return { st: 'miss', d: '本地模型服务未启动（无 GPU 容器）', place: '127.0.0.1:8090' };
      case 'kev':
        return { st: 'miss', d: 'Kev 决策模型未下载', place: p.models };
      case 'hwmon':
        return { st: 'ok', d: `Node os 模块实时采样（${os.cpus().length} vCPU）`, place: 'linux-os' };
      case 'ds':
        return this.secrets.dsKey
          ? { st: 'ok', d: `已配置 DeepSeek Key（••••${this.secrets.dsKey.slice(-4)}）`, place: '设置 › 云端' }
          : { st: 'miss', d: '还没填 DeepSeek Key：到 设置 › 云端 填写后即可调用对话与检索', place: '设置 › 云端' };
      case 'qq':
        return { st: 'miss', d: 'QQ 官方机器人未配置 AppID / Secret', place: '设置 › QQ' };
      case 'qqbind':
        return { st: 'wait', d: '未绑定 QQ 账号（网页控制台可直接对话）', place: '设置 › QQ' };
      case 'qqpush':
        return { st: 'ok', d: '网页端弹窗与卡片提醒可用', place: '控制台' };
      case 'memory':
        return {
          st: 'ok',
          d: `已加载说明文档 ${this.listDocs().length} 篇 · 记忆 ${this.memories.length} 条`,
          place: DOCS_DIR,
        };
      default:
        return { st: 'miss', d: '未知检查项' };
    }
  }

  refreshChecks(): void {
    const keys = [
      'driver',
      'python',
      'git',
      'aienv',
      'base',
      'embed',
      'models',
      'kev',
      'hwmon',
      'ds',
      'qq',
      'qqbind',
      'qqpush',
      'memory',
    ];
    for (const k of keys) {
      this.checksRes[k] = this.checkOne(k);
    }
    this.checksTs = Date.now() / 1000;
  }

  listDocs(): Array<{ rel: string; title: string; group: string; mtime: number }> {
    if (!fs.existsSync(DOCS_DIR)) return [];
    const results: Array<{ rel: string; title: string; group: string; mtime: number; order: number }> = [];
    const walk = (dir: string) => {
      for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, ent.name);
        if (ent.isDirectory()) {
          walk(full);
        } else if (ent.isFile() && ent.name.endsWith('.md')) {
          const rel = path.relative(DOCS_DIR, full).split(path.sep).join('/');
          if (rel.includes('/') && !rel.startsWith('AI文档/')) continue;
          const group = rel.startsWith('AI文档/架构/')
            ? '架构图'
            : rel.startsWith('AI文档/')
              ? 'AI 文档'
              : '说明';
          let title = ent.name.replace(/\.md$/, '');
          try {
            const firstLines = fs.readFileSync(full, 'utf8').split(/\r?\n/);
            const h1 = firstLines.find((l) => l.startsWith('# '));
            if (h1) title = h1.slice(2).trim();
          } catch {
            // ignore read error
          }
          const stat = fs.statSync(full);
          const customOrder: Record<string, number> = {
            '操作手册.md': 0,
            '更新记录.md': 1,
            'README.md': 2,
            'AI文档/README.md': 0,
            'AI文档/当前结构.md': 1,
          };
          results.push({
            rel,
            title,
            group,
            mtime: stat.mtimeMs / 1000,
            order: customOrder[rel] ?? 5,
          });
        }
      }
    };
    walk(DOCS_DIR);
    results.sort((a, b) => {
      const ga = a.group === '架构图' ? 0 : a.group === '说明' ? 1 : 2;
      const gb = b.group === '架构图' ? 0 : b.group === '说明' ? 1 : 2;
      if (ga !== gb) return ga - gb;
      if (a.order !== b.order) return a.order - b.order;
      return a.rel.localeCompare(b.rel);
    });
    return results.map(({ order: _o, ...rest }) => rest);
  }

  readDoc(rel: string): { rel: string; title: string; text: string; mtime: number; path: string } | null {
    const resolved = path.resolve(DOCS_DIR, rel);
    const docsRoot = path.resolve(DOCS_DIR) + path.sep;
    if (!resolved.startsWith(docsRoot) || !resolved.endsWith('.md') || !fs.existsSync(resolved)) {
      return null;
    }
    const text = fs.readFileSync(resolved, 'utf8');
    const h1 = text.split(/\r?\n/).find((l) => l.startsWith('# '));
    const title = h1 ? h1.slice(2).trim() : path.basename(resolved, '.md');
    const stat = fs.statSync(resolved);
    return { rel, title, text, mtime: stat.mtimeMs / 1000, path: resolved };
  }

  splitSince(sinceTs: number, untilTs = Date.now() / 1000 + 1): Record<'local' | 'neu' | 'ds' | 'cl', number> {
    const c = { local: 0, neu: 0, ds: 0, cl: 0 };
    for (const ev of this.events) {
      if (ev.ts >= sinceTs && ev.ts < untilTs && ev.src !== '定时任务') {
        c[ev.to] = (c[ev.to] || 0) + 1;
      }
    }
    return c;
  }

  dayStart(daysAgo = 0): number {
    const d = new Date();
    d.setDate(d.getDate() - daysAgo);
    d.setHours(0, 0, 0, 0);
    return d.getTime() / 1000;
  }

  weekBars(): Array<[string, number, number]> {
    const out: Array<[string, number, number]> = [];
    for (let d = 6; d >= 0; d--) {
      const a = this.dayStart(d);
      const b = d > 0 ? this.dayStart(d - 1) : Date.now() / 1000 + 1;
      const s = this.splitSince(a, b);
      const tot = s.local + s.neu + s.ds + s.cl;
      const dt = new Date(a * 1000);
      const label = `${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
      out.push([label, tot ? Math.round((s.local / tot) * 100) : 0, tot]);
    }
    return out;
  }

  getAgentView(): Record<string, unknown> {
    const hasDs = Boolean(this.secrets.dsKey);
    const rems = this.reminders.filter((r) => r.enabled);
    const nxt = rems
      .filter((r) => r.next_ts)
      .sort((a, b) => (a.next_ts || 0) - (b.next_ts || 0))[0];
    const docsCount = this.listDocs().length;
    const readyChecks = Object.values(this.checksRes).filter((c) => c.st === 'ok').length;
    const totalChecks = Object.keys(this.checksRes).length || 14;

    const brain = [
      {
        k: 'embed',
        name: '语义路由（嵌入模型）',
        st: 'off',
        detail: '无 GPU 容器环境：使用规则与关键词快速分流',
        act: { label: '去整备', sec: 'prep' },
      },
      {
        k: 'kev',
        name: 'Kev（决策脑第二票）',
        st: 'off',
        detail: '本地轻量模型未部署，已自动切换规则路由',
        act: { label: '去设置', sec: 'models' },
      },
      {
        k: 'base',
        name: '本地通用（底座 MiniCPM5-2B）',
        st: 'off',
        detail: '需本地 CUDA 显卡环境',
        act: { label: '去整备', sec: 'prep' },
      },
    ];

    const balVal = this.dsBalance?.total;
    const cloud = [
      hasDs
        ? {
            k: 'ds',
            name: 'DeepSeek',
            st: 'ok',
            detail: `Key 正常 · 模型 ${String(this.settings.dsModel || 'deepseek-chat')}`,
            m: balVal != null ? { txt: `¥${balVal.toFixed(2)}` } : undefined,
          }
        : {
            k: 'ds',
            name: 'DeepSeek',
            st: 'warn',
            detail: '还没填 Key：长对话请到 设置 › 云端 填写 DeepSeek Key',
            act: { label: '去填 Key', sec: 'cloud' },
          },
      {
        k: 'search',
        name: '联网搜索',
        st: this.settings.searchOn && hasDs ? 'ok' : 'off',
        detail: hasDs ? `开着 · 今天 ${this.searchToday} / ${String(this.settings.searchDaily || 200)} 次` : '需配置 DeepSeek Key',
        act: hasDs ? undefined : { label: '去填 Key', sec: 'cloud' },
      },
      {
        k: 'claude',
        name: String(this.settings.strongName || '更强的模型'),
        st: this.settings.strongOn ? 'ok' : 'off',
        detail: this.settings.strongOn ? '支持导出提示词与导入 Markdown 总结' : '已关闭',
      },
    ];

    const hands = [
      {
        k: 'ws',
        name: '工作文件夹',
        st: 'ok',
        detail: `Node.js 内存工作区 · 技能 ${this.listSkills().length} 份`,
      },
      {
        k: 'cc',
        name: 'Claude Code 引擎',
        st: 'off',
        detail: '独立终端工具在容器内未启用',
        act: { label: '去设置', sec: 'agent' },
      },
      {
        k: 'voice',
        name: '语音',
        st: 'off',
        detail: '本地 Breeze TTS 2 / Qwen3-ASR 需 GPU',
        act: { label: '去看看', sec: 'voice' },
      },
      {
        k: 'bgm',
        name: '配乐（Stable Audio 3）',
        st: 'off',
        detail: '本地音频生成服务需 GPU',
        act: { label: '去看看', sec: 'prep' },
      },
    ];

    const chan = [
      { k: 'qq', name: 'QQ', st: 'off', detail: '未开启（网页控制台可直接对话）', act: { label: '去设置', sec: 'qq' } },
      {
        k: 'remind',
        name: '提醒',
        st: rems.length ? 'ok' : 'off',
        detail: nxt ? `开着 ${rems.length} 条 · 下一个 ${nowTimeStr(nxt.next_ts || 0)} ${nxt.title}` : '暂无开启的定时提醒',
        act: rems.length ? undefined : { label: '去设', sec: 'remind' },
      },
    ];

    const back = [
      { k: 'backend', name: '后端', st: 'ok', detail: `0.0.0.0:${PORT} · Node.js ${process.version}` },
      { k: 'hw', name: '硬件采样', st: 'ok', detail: `Node os 采样 · ${os.cpus().length} vCPU` },
      {
        k: 'memory',
        name: '记忆和说明书',
        st: 'ok',
        detail: `记忆 ${this.memories.length} 条 · 说明书 ${docsCount} 篇`,
        m: { txt: `${this.memories.length} · ${docsCount}` },
      },
    ];

    const groups = [
      { name: '大脑', items: brain },
      { name: '云端', items: cloud },
      { name: '手脚', items: hands },
      { name: '通道', items: chan },
      { name: '后台', items: back },
    ];
    const count: Record<string, number> = { ok: 0, idle: 0, warn: 0, bad: 0, off: 0, start: 0, stuck: 0 };
    for (const g of groups) {
      for (const it of g.items) {
        count[it.st] = (count[it.st] || 0) + 1;
      }
    }

    const kpi = {
      bal: hasDs
        ? { st: 'ok', v: balVal != null ? `¥${balVal.toFixed(2)}` : '已配 Key', sub: `本月花了 ¥${this.costMonthCny.toFixed(2)}` }
        : { st: 'warn', v: '未填 Key', sub: '设置 › 云端' },
      search: hasDs
        ? { st: 'ok', v: String(this.searchToday), unit: `/ ${String(this.settings.searchDaily || 200)} 次`, p: 0, sub: '可用' }
        : { st: 'off', v: '0', unit: '次', sub: '需 DeepSeek Key' },
      remind: nxt
        ? { st: 'ok', v: nowTimeStr(nxt.next_ts || 0), ts: nxt.next_ts, sub: `${nxt.title} · 共开着 ${rems.length} 条` }
        : { st: 'off', v: '--:--', sub: '暂无开启的提醒' },
      prep: {
        st: readyChecks >= totalChecks ? 'ok' : 'warn',
        v: String(readyChecks),
        unit: `/ ${totalChecks} 项`,
        p: Math.round((readyChecks / totalChecks) * 1000) / 1000,
        sub: `${readyChecks}/${totalChecks} 项就绪`,
      },
      mem: { st: 'ok', v: String(this.memories.length), unit: '条', sub: `说明书 ${docsCount} 篇` },
    };

    return {
      ts: Date.now() / 1000,
      count,
      head: hasDs ? '网页端服务正常' : '网页端服务正常（未填 DeepSeek Key）',
      groups,
      kpi,
      prep: { ready: readyChecks, total: totalChecks },
    };
  }

  getStateView(): Record<string, unknown> {
    const sp = this.splitSince(this.dayStart());
    const tot = sp.local + sp.neu + sp.ds + sp.cl;
    const ready = Object.values(this.checksRes).filter((c) => c.st === 'ok').length;
    const miss = Object.values(this.checksRes).filter((c) => c.st === 'miss').length;
    const nxt = this.reminders
      .filter((r) => r.enabled && r.next_ts)
      .sort((a, b) => (a.next_ts || 0) - (b.next_ts || 0))[0];

    return {
      ts: Date.now() / 1000,
      today: sp,
      today_total: tot,
      local_pct: tot ? Math.round((sp.local / tot) * 100) : 0,
      cost_month: Math.round(this.costMonthCny * 100) / 100,
      balance: this.secrets.dsKey
        ? {
            key: true,
            total: this.dsBalance?.total ?? null,
            currency: this.dsBalance?.currency || 'CNY',
            ts: this.dsBalance?.ts ?? null,
            err: this.dsBalance?.err ?? null,
            low: false,
          }
        : { key: false },
      search: {
        on: Boolean(this.settings.searchOn),
        limit: Number(this.settings.searchDaily) || 200,
        today: { n: this.searchToday },
        month: { n: this.searchMonth, cny: 0 },
      },
      agent: this.getAgentView(),
      setup: null,
      asks_pending: this.asks.filter((a) => a.status === 'pending').length,
      next: nxt ? { id: nxt.id, title: nxt.title, at: nowTimeStr(nxt.next_ts || 0), ts: nxt.next_ts } : null,
      cards: this.cards,
      train_ask: this.trainAsk,
      prep: {
        ready,
        total: Object.keys(this.checksRes).length || 14,
        miss,
        ts: this.checksTs,
      },
      qq: { status: 'off', detail: '未启用', candidate: null },
      models: { server: false, kev: false, yielding: false, yield_reason: '', embed: false, base: false },
      tasks: [],
      done_jobs: [],
      events: [...this.events].reverse().slice(0, 40),
    };
  }

  getBrainsView(): Array<Record<string, unknown>> {
    const today = this.splitSince(this.dayStart());
    const todaySum = today.local + today.neu + today.ds + today.cl;
    const trend = [100, 100, 100, 100, 100, 100, 100];
    const hasDs = Boolean(this.secrets.dsKey);
    const bal = this.dsBalance?.total;

    return [
      {
        kind: '决策脑',
        name: '决策脑',
        sub: `规则路由 + ${hasDs ? 'DeepSeek 云端' : '本地快捷指令'}`,
        st: '运行中',
        c: 'var(--accent)',
        note: '先根据消息内容判断是否属于本地快捷指令（记住、提醒、查文档），其余交由云端模型处理。',
        ring: [100, '100', '%', '规则就绪'],
        trend,
        tmax: 100,
        tl: '没被纠正的比例',
        stats: [
          ['今日判断', String(todaySum), '次'],
          ['本周被纠正', String(this.events.filter((e) => e.fix).length), '次'],
          ['已存事件', String(this.events.length), '条'],
        ],
        acts: [],
      },
      {
        kind: '本地小脑',
        name: '本地通用',
        sub: 'Node.js 本地命令 & 文档检索',
        c: 'var(--c-local)',
        st: '在线',
        note: '处理记忆保存、定时提醒管理与 /docs 中文说明检索，不消耗云端额度。',
        ring: [100, '开', '', '本地'],
        trend: this.weekBars().map((r) => r[1]),
        tmax: 100,
        tl: '本地处理比例',
        stats: [
          ['今日接手', String(today.local), '次'],
          ['记忆条数', String(this.memories.length), '条'],
          ['说明文档', String(this.listDocs().length), '篇'],
        ],
        acts: [],
      },
      {
        kind: '云端',
        name: 'DeepSeek',
        sub: `${String(this.settings.dsModel || 'deepseek-chat')} · API`,
        c: 'var(--c-ds)',
        st: hasDs ? '有 Key' : '没填 Key',
        note: '长对话和复杂分析。可在 设置 › 云端 填写 DeepSeek API Key 启用实时调用。',
        ring: [hasDs ? 100 : 0, bal != null ? `¥${bal.toFixed(2)}` : hasDs ? '已配置' : '未配置', '', '状态'],
        trend: [0, 0, 0, 0, 0, 0, today.ds],
        tmax: Math.max(5, today.ds),
        tl: '每日调用',
        stats: [
          ['余额', bal != null ? `¥${bal.toFixed(2)}` : hasDs ? '点刷新查询' : '未填 Key', ''],
          ['本月花了（估算）', `¥${this.costMonthCny.toFixed(2)}`, ''],
          ['今日调用', String(today.ds), '次'],
        ],
        acts: [
          { label: '刷新余额', act: 'ds_balance' },
          { label: '去填 Key', act: 'go_cloud' },
        ],
      },
      {
        kind: '云端',
        name: String(this.settings.strongName || '更强的模型'),
        sub: '你本人带提示词去聊',
        c: 'var(--c-cl)',
        st: '等你',
        note: '遇到特别复杂的难题，可导出提示词并用网页端强模型分析，再将总结 .md 导入。',
        ring: [this.summaries.length ? 100 : 0, String(this.summaries.length), `/${Math.max(1, this.claudePrompts.length)}`, '总结已带回'],
        trend: [0, 0, 0, 0, 0, 0, this.summaries.length],
        tmax: Math.max(2, this.summaries.length),
        tl: '导入总结',
        stats: [
          ['待处理提示词', String(this.claudePrompts.filter((p) => !p.done).length), '份'],
          ['已带回总结', String(this.summaries.length), '份'],
        ],
        acts: [{ label: '导入总结', act: 'import_summary' }],
      },
    ];
  }

  getReportView(): Record<string, unknown> {
    const since = Date.now() / 1000 - 7 * 86400;
    const sp = this.splitSince(since);
    const tot = sp.local + sp.neu + sp.ds + sp.cl;
    const fixes = this.events.filter((e) => e.fix && e.ts > since).length;
    return {
      split: sp,
      total: tot,
      local_pct: tot ? Math.round((sp.local / tot) * 100) : 0,
      fixes,
      cost_month: Math.round(this.costMonthCny * 100) / 100,
      balance: this.secrets.dsKey ? { key: true, total: this.dsBalance?.total ?? null, currency: 'CNY' } : { key: false },
      week: this.weekBars(),
      changes: this.changes,
      asks: this.asks,
      draft: null,
      nightly: null,
      new_brains: 0,
    };
  }

  getSetupView(): Record<string, unknown> {
    return {
      running: false,
      group: 'core',
      cur: null,
      started: 0,
      finished: 0,
      line: '',
      say: '',
      ds_key: Boolean(this.secrets.dsKey),
      tts_busy: false,
      steps: [
        { k: 'git', g: 'core', t: 'Git（便携版）', d: '系统 Git 检查', st: 'ready', info: '已就绪' },
        { k: 'aienv', g: 'core', t: '本地模型环境', d: 'Linux 无 GPU 容器不支持 CUDA PyTorch', st: 'skip', info: '容器跳过' },
        { k: 'models', g: 'core', t: '底座和嵌入模型', d: '需本地显卡下载模型', st: 'skip', info: '容器跳过' },
        { k: 'start', g: 'core', t: '启动本地模型服务', d: '需本地 GPU', st: 'skip', info: '容器跳过' },
        { k: 'kev', g: 'core', t: 'Kev 的权重', d: '需本地 GPU', st: 'skip', info: '容器跳过' },
        { k: 'hwmon', g: 'core', t: '硬件监控助手', d: '使用 Node os 实时采集容器 CPU/内存', st: 'ready', info: '已就绪' },
        { k: 'tts', g: 'media', t: '本地配音（Qwen3-TTS）', d: '需本地 CUDA GPU', st: 'wait', info: '容器无 GPU' },
        { k: 'asr', g: 'media', t: '听写（Qwen3-ASR）', d: '需本地 CUDA GPU', st: 'wait', info: '容器无 GPU' },
        { k: 'breeze', g: 'media', t: '说话的声音（Breeze TTS 2）', d: '需本地 CUDA GPU', st: 'wait', info: '容器无 GPU' },
        { k: 'bgm', g: 'media', t: '配乐（Stable Audio 3 Medium）', d: '需本地 CUDA GPU', st: 'wait', info: '容器无 GPU' },
      ],
    };
  }

  getMonitorView(): Record<string, unknown> {
    return {
      setup: this.getSetupView(),
      services: [
        { k: 'backend', name: 'Node.js 后端', st: 'ok', detail: `0.0.0.0:${PORT} · Express`, pid: process.pid, mem: Math.round(process.memoryUsage().rss / 1048576), up: Math.round(Date.now() / 1000 - STARTED_AT), log: 'backend.log' },
        { k: 'ds', name: 'DeepSeek 云端', st: this.secrets.dsKey ? 'ok' : 'off', detail: this.secrets.dsKey ? 'Key 已配置' : '未填 Key' },
        { k: 'model', name: '本地模型服务', st: 'off', detail: 'Linux 容器无 GPU，已禁用' },
        { k: 'tts', name: '配音服务', st: 'off', detail: 'Linux 容器无 GPU，已禁用' },
        { k: 'bgm', name: '配乐服务', st: 'off', detail: 'Linux 容器无 GPU，已禁用' },
      ],
      logs: [{ name: 'backend.log', label: '后端', size: 1024, mtime: Date.now() / 1000 }],
    };
  }

  listSkills(): string[] {
    if (!fs.existsSync(SKILLS_DIR)) return [];
    return fs
      .readdirSync(SKILLS_DIR)
      .filter((n) => n.endsWith('.md'))
      .map((n) => n.replace(/\.md$/, ''));
  }

  async chatHandle(
    text: string,
    opts: { force?: string | null; allow_private?: boolean; engine?: string | null; src?: string; redo_of?: number; job?: ChatJob }
  ): Promise<EventItem> {
    const t0 = performance.now();
    const ts = Date.now() / 1000;
    const eid = this.nextEventId++;
    const lower = text.trim();
    const steps: [string, string, number?][] = [['收到', `${opts.src === 'voice' ? '语音' : '界面'}收到：${lower.slice(0, 40)}`, 0.01]];

    const privWords = String(this.settings.privWords || '')
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const isPrivate = privWords.some((w) => lower.includes(w)) || /密码|身份证|银行卡|私钥/.test(lower);

    let route: 'local' | 'neu' | 'ds' | 'cl' =
      opts.force === 'local' || opts.force === 'neu' || opts.force === 'ds' || opts.force === 'cl'
        ? opts.force
        : 'ds';

    const isRemember = /^(记住|记一下|记下来|帮我记)[:：\s]*/.test(lower);
    const isRemind = /(提醒我|定时提醒|每天提醒|每隔.+提醒)/.test(lower);
    const isDocQuery = /(说明书|文档|操作手册|更新记录|视频工坊剧本格式)/.test(lower) && !opts.force;

    if (!opts.force && (isRemember || isRemind || isDocQuery || lower === '帮助' || lower === 'help')) {
      route = 'local';
    }

    const ev: EventItem = {
      id: eid,
      t: nowTimeStr(ts),
      date: nowDateStr(ts),
      ts,
      src: opts.src === 'voice' ? '语音' : '界面',
      text: lower,
      to: route,
      label: route === 'local' ? '本地指令处理' : 'DeepSeek 对话',
      private: isPrivate,
      s: route === 'local' ? { local: 95, neu: 3, ds: 2, cl: 0 } : { local: 15, neu: 10, ds: 75, cl: 0 },
      why: opts.force ? `你指定交给 ${opts.force}` : route === 'local' ? '匹配本地快捷指令或文档检索' : '交由云端对话引擎处理',
      result: '',
      reply: '',
      steps,
      fix: null,
      teacher: null,
      status: 'running',
      cost: 0,
      latency: 0,
      plan: [],
      engine: opts.engine || null,
      votes: { mode: 'rule', embed: { top: route, p: route === 'local' ? 95 : 75 }, kev: null, weights: null },
      files: [],
    };
    this.events.push(ev);
    if (opts.job) opts.job.eid = eid;

    let reply = '';
    let result = '完成';
    let cost = 0;

    if (route === 'local') {
      if (isRemember) {
        const content = lower.replace(/^(记住|记一下|记下来|帮我记)[:：\s]*/, '').trim() || lower;
        this.memories.push({ id: this.nextMemoryId++, text: content, ts });
        steps.push(['本地处理', '写入内存记忆列表', (performance.now() - t0) / 1000]);
        reply = `已记住：「${content}」（当前共 ${this.memories.length} 条记忆）。`;
      } else if (isRemind) {
        const remBase: Omit<ReminderItem, 'next_ts'> = {
          id: this.nextReminderId++,
          title: lower.slice(0, 24),
          kind: 'interval',
          at: '22:00',
          every_min: 60,
          days: '1234567',
          once_ts: null,
          text: lower,
          enabled: true,
        };
        const created: ReminderItem = { ...remBase, next_ts: computeNextTs(remBase) };
        this.reminders.push(created);
        steps.push(['本地处理', '新建定时提醒', (performance.now() - t0) / 1000]);
        reply = `已为你创建提醒「${created.title}」，可在「设置 › 提醒」中随时调整时间与频率。`;
      } else if (isDocQuery) {
        const docs = this.listDocs();
        steps.push(['查了说明书', `检索 ${docs.length} 篇中文说明`, (performance.now() - t0) / 1000]);
        const hits = docs.filter((d) => lower.includes(d.title) || d.title.includes('手册') || d.rel.includes('操作手册')).slice(0, 5);
        reply =
          `当前共有 ${docs.length} 篇说明文档，可在侧栏或 设置 › 说明 中直接阅读：\n` +
          (hits.length ? hits : docs.slice(0, 5)).map((d) => `- **${d.title}**（\`${d.rel}\`）`).join('\n');
      } else {
        steps.push(['本地处理', '返回内置功能说明', (performance.now() - t0) / 1000]);
        reply =
          '你可以：\n1. 说「记住 ……」记录便签\n2. 说「提醒我 ……」创建提醒\n3. 在「设置 › 云端」填入 DeepSeek Key 开启完整对话\n4. 打开「视频工坊」导入或编辑剧本与 5 份清单';
      }
    } else if (isPrivate && !opts.allow_private) {
      ev.status = 'err';
      ev.reply = '检测到可能包含敏感信息，未发送至云端。如确认发送请在界面确认。';
      ev.result = '隐私拦截';
      throw new Error('PRIVACY_CONFIRM_REQUIRED');
    } else if (this.secrets.dsKey) {
      const dsBase = String(this.settings.dsBase || 'https://api.deepseek.com').replace(/\/+$/, '');
      const dsModel = String(this.settings.dsModel || 'deepseek-chat');
      steps.push(['交给 DeepSeek', `调用 ${dsModel}`, (performance.now() - t0) / 1000]);
      try {
        const resp = await fetch(`${dsBase}/chat/completions`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${this.secrets.dsKey}`,
          },
          body: JSON.stringify({
            model: dsModel,
            messages: [
              { role: 'system', content: '你是 Experiment Agent One 的中文智能助手，回答清晰、简明、实用。' },
              { role: 'user', content: lower },
            ],
            stream: false,
          }),
        });
        const data = (await resp.json()) as {
          choices?: Array<{ message?: { content?: string } }>;
          usage?: { prompt_tokens?: number; completion_tokens?: number };
          error?: { message?: string };
        };
        if (!resp.ok) {
          throw new Error(data.error?.message || `DeepSeek HTTP ${resp.status}`);
        }
        reply = data.choices?.[0]?.message?.content?.trim() || '（DeepSeek 返回空内容）';
        const pt = data.usage?.prompt_tokens || 0;
        const ct = data.usage?.completion_tokens || 0;
        cost = Math.round(((pt * 0.15 + ct * 0.6) / 1e6) * (Number(this.settings.usdCny) || 7.2) * 10000) / 10000;
        this.costMonthCny += cost;
        result = `DeepSeek 回复（${pt + ct} tokens）`;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        ev.status = 'err';
        ev.result = msg;
        ev.reply = `调用 DeepSeek 失败：${msg}`;
        ev.latency = Math.round(((performance.now() - t0) / 1000) * 100) / 100;
        steps.push(['回答', '调用出错', ev.latency]);
        return ev;
      }
    } else {
      steps.push(['分流', '未配置 DeepSeek Key，返回提示', (performance.now() - t0) / 1000]);
      reply =
        '当前尚未配置 DeepSeek API Key，因此未发出云端请求。你可以：\n- 前往 **设置 › 云端** 填入 DeepSeek Key 以启用在线对话；\n- 或使用本地指令，如「记住 今天完成迁移」「提醒我 喝水」「查看操作手册」。';
      result = '未配置 Key';
    }

    ev.latency = Math.round(((performance.now() - t0) / 1000) * 100) / 100;
    ev.cost = cost;
    ev.reply = reply;
    ev.result = result;
    ev.status = 'done';
    steps.push(['回答', result, ev.latency]);
    this.addFeed(`对话完成：${lower.slice(0, 30)}`, 'ok', route === 'local' ? '本地处理' : 'DeepSeek');
    return ev;
  }

  getImgModels(): Record<string, unknown> {
    const defModel = {
      id: 'gpt-image-2.5-sunburst-vip',
      name: 'GPT Image 2.5 Sunburst VIP',
      route: '逆向',
      price: 0.03,
      sec: 80,
      d: '高质量 2.5 Adobe 线路，画质与编辑精度优先；30 档尺寸（1K/2K/4K）、4 档画质、透明背景',
      warn: '',
      known: true,
      listed: null,
      proto: 'openai',
      refs: 8,
      trans: 'api',
      size: 'preset',
      v: 'openai',
      q: ['auto', 'low', 'medium', 'high'],
      tiers: ['1k', '2k', '4k'],
      vendor: 'OpenAI',
    };
    const extraByVendor: Record<string, Array<Record<string, unknown>>> = {};
    for (const m of this.imgExtraModels) {
      const v = String(m.v || 'other');
      extraByVendor[v] = extraByVendor[v] || [];
      extraByVendor[v].push(m);
    }
    const baseGroups = [
      { v: 'openai', name: 'OpenAI', models: [defModel, ...(extraByVendor.openai || [])] },
      {
        v: 'google',
        name: 'Google',
        models: [
          {
            id: 'gemini-3.1-flash-image',
            name: 'Nano Banana 2',
            route: '',
            price: 0.055,
            sec: 15,
            d: 'Google，0.5K~4K、14 种比例、最多 14 张参考图',
            known: true,
            listed: null,
            proto: 'gemini',
            size: 'gemini',
            refs: 14,
            trans: 'prompt',
            q: ['auto', 'low', 'medium', 'high'],
            tiers: ['1k', '2k', '4k'],
            vendor: 'Google',
          },
          ...(extraByVendor.google || []),
        ],
      },
      ...(extraByVendor.other?.length ? [{ v: 'other', name: '其他厂商', models: extraByVendor.other }] : []),
    ];
    return {
      ts: this.imgModelsTs,
      n: baseGroups.reduce((a, g) => a + g.models.length, 0),
      err: '',
      default: 'gpt-image-2.5-sunburst-vip',
      groups: baseGroups,
    };
  }

  getImgState(): Record<string, unknown> {
    const R = ['16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3', '5:4', '4:5', '21:9'];
    const Z: Record<string, number[][]> = {
      '1k': [[1280, 720], [720, 1280], [1280, 1280], [1280, 960], [960, 1280], [1280, 848], [848, 1280], [1280, 1024], [1024, 1280], [1280, 544]],
      '2k': [[2048, 1152], [1152, 2048], [2048, 2048], [2048, 1536], [1536, 2048], [2048, 1360], [1360, 2048], [2048, 1632], [1632, 2048], [2048, 864]],
      '4k': [[3840, 2160], [2160, 3840], [2880, 2880], [3312, 2480], [2480, 3312], [3520, 2336], [2336, 3520], [3216, 2560], [2560, 3216], [3840, 1632]],
    };
    const sizes: Record<string, Record<string, string>> = {};
    for (const t of Object.keys(Z)) {
      sizes[t] = {};
      R.forEach((r, i) => {
        sizes[t][r] = `${Z[t][i][0]}×${Z[t][i][1]}`;
      });
    }
    const groups = this.getImgModels().groups as Array<{ models: Array<Record<string, unknown>> }>;
    const allModels = groups.flatMap((g) => g.models);
    const curId = String(this.settings.imgModel || 'gpt-image-2.5-sunburst-vip');
    const curModel = allModels.find((m) => m.id === curId) || {
      id: curId,
      name: curId,
      route: '',
      price: null,
      sec: 30,
      d: '自定义生图模型',
      known: false,
      listed: true,
      proto: /gemini|nano-banana/i.test(curId) ? 'gemini' : 'openai',
      refs: 4,
      trans: 'api',
      size: 'preset',
      q: ['auto', 'low', 'medium', 'high'],
      tiers: ['1k', '2k', '4k'],
      vendor: '自定义',
    };

    return {
      demo: false,
      ratios: R,
      tiers: ['1k', '2k', '4k'],
      sizes,
      quality: { auto: '自动', low: '低', medium: '中', high: '高', xhigh: '更高', max: '最高' },
      tokens: { low: 196, medium: 439, high: 1756, xhigh: 3122, max: 7024, auto: 439 },
      usd_out: 0.00003,
      usdCny: Number(this.settings.usdCny) || 7.2,
      model: curModel,
      cfg: {
        model: curId,
        quality: String(this.settings.imgQuality || 'high'),
        tier: String(this.settings.imgRes || '2k'),
        notext: Boolean(this.settings.imgNoText),
        withdir: Boolean(this.settings.imgWithDir),
        key: Boolean(this.secrets.imgKey),
        hint: this.secrets.imgKey ? `••••${this.secrets.imgKey.slice(-4)}` : '',
        base: String(this.settings.imgBase || 'https://api.apiyi.com/v1'),
      },
      month: this.imgMonth,
      out: this.places().imgOut,
      recent: this.imgRecent.slice(0, 12),
      board: this.imgBoard,
      job: this.imgJob,
    };
  }

  getTtsState(): Record<string, unknown> {
    return {
      demo: false,
      env: false,
      models: { custom: false, design: false },
      server: false,
      proc: false,
      yield: '',
      job: this.ttsJob,
      draft: this.ttsDraft,
      speakers: [
        { id: 'Vivian', name: 'Vivian', d: '女声 · 明亮、略带锐气的年轻女声', lang: '中文' },
        { id: 'Serena', name: 'Serena', d: '女声 · 温柔、温暖的年轻女声', lang: '中文' },
        { id: 'Uncle_Fu', name: 'Uncle_Fu', d: '男声 · 低沉醇厚的成熟男声', lang: '中文' },
        { id: 'Dylan', name: 'Dylan', d: '男声 · 清亮自然的北京青年', lang: '中文 · 北京话' },
        { id: 'Eric', name: 'Eric', d: '男声 · 活泼、略带沙哑的成都男声', lang: '中文 · 四川话' },
        { id: 'Ryan', name: 'Ryan', d: '男声 · 节奏感强', lang: '英文' },
      ],
      langs: [['Chinese', '中文'], ['English', '英文'], ['Auto', '自动']],
      voices: this.ttsVoices,
      out: this.places().ttsOut,
      saved: null,
      speed: null,
      gap: Number(this.settings.ttsGap) || 0.35,
      para: Number(this.settings.ttsParaGap) || 0.7,
      sizes: { custom: 0, design: 0, align: 0 },
      align: false,
      inst: { st: 'idle' },
      engine: String(this.settings.ttsEngine || 'local'),
      cloud: {
        key: Boolean(this.secrets.blKey),
        model: String(this.settings.blModel || 'qwen-audio-3.1-tts-plus'),
        known: true,
        price: Number(this.settings.blPrice) || 1.4,
        max: Number(this.settings.blMax) || 2000,
        ratio: null,
        month: this.ttsCloudMonth,
        count: this.ttsCloudMine.length,
        quota: 1000,
        design_text: '大家好，欢迎来到这一期的 AI 工具实测，今天我们聊三个最近很火的新工具。',
        hotfix: this.ttsPronDict,
        langs: [['', '自动'], ['zh', '中文'], ['en', '英文'], ['ja', '日语'], ['ko', '韩语']],
        voices: [
          { id: 'longanlingxin_v3.1', name: '龙安灵心', g: '女', d: '温柔知心，娓娓道来', kind: 'system' },
          { id: 'longanhuan_v3.1', name: '龙安欢', g: '女', d: '活泼有感染力，带气氛', kind: 'system' },
          { id: 'longanfengyue_v3.1', name: '龙安风悦', g: '女', d: '平和自然，播报、叙述', kind: 'system' },
          { id: 'xunanchuan_v3.1', name: '许南川', g: '男', d: '磁性沉稳，解说、旁白', kind: 'system' },
        ],
        mine: this.ttsCloudMine,
      },
    };
  }

  async refreshImgModels(): Promise<Record<string, unknown>> {
    if (!this.secrets.imgKey) throw new Error('请先到 设置 › 云端 填写 API易 Key');
    const raw = await fetchApiyiModels(String(this.settings.imgBase || 'https://api.apiyi.com/v1'), this.secrets.imgKey);
    const knownIds = new Set(['gpt-image-2.5-sunburst-vip', 'gemini-3.1-flash-image']);
    this.imgExtraModels = raw
      .filter((m) => !knownIds.has(m.id))
      .map((m) => ({
        id: m.id,
        name: m.id,
        route: '',
        price: null,
        sec: 30,
        d: `API易 · ${m.owned_by || '模型'}`,
        known: false,
        listed: true,
        proto: /gemini|nano-banana|imagen/i.test(m.id) ? 'gemini' : /seedream/i.test(m.id) ? 'seedream' : /flux/i.test(m.id) ? 'flux' : 'openai',
        refs: 4,
        trans: 'api',
        size: 'preset',
        v: /gemini|google/i.test(m.id) ? 'google' : /gpt|openai/i.test(m.id) ? 'openai' : 'other',
        q: ['auto', 'low', 'medium', 'high'],
        tiers: ['1k', '2k', '4k'],
        vendor: /gemini|google/i.test(m.id) ? 'Google' : /gpt|openai/i.test(m.id) ? 'OpenAI' : m.owned_by || '其他',
      }));
    this.imgModelsTs = Date.now() / 1000;
    return this.getImgModels();
  }

  startImgSingle(opts: { prompt: string; ratio: string; n: number; transparent: boolean; refs: string[] }): Record<string, unknown> {
    if (!this.secrets.imgKey) throw new Error('还没填 API易 Key，请先到 设置 › 云端 填写');
    if (this.imgJob && this.imgJob.st === 'run') throw new Error('生图任务正在跑，等它出完或先点停下');

    const prompt = String(opts.prompt || '').trim();
    if (!prompt) throw new Error('提示词不能为空');
    const n = Math.max(1, Math.min(4, Number(opts.n) || 1));
    const ratio = String(opts.ratio || '9:16');
    const tier = String(this.settings.imgRes || '2k');
    const quality = String(this.settings.imgQuality || 'high');
    const model = String(this.settings.imgModel || 'gpt-image-2.5-sunburst-vip');
    const base = String(this.settings.imgBase || 'https://api.apiyi.com/v1');

    this.imgStopFlag = false;
    const job: Record<string, unknown> = {
      id: Date.now(),
      st: 'run',
      kind: 'single',
      n,
      done: 0,
      fail: 0,
      msg: '正在请求 API易…',
      est: Math.round(n * 0.03 * 100) / 100,
      model,
      mname: model,
      quality,
      tier,
      conc: 1,
      fatal: '',
      usd: 0,
      elapsed: 0,
      results: [] as Array<Record<string, unknown>>,
      cur: {
        label: `单张 #1`,
        prompt,
        ratio,
        transparent: opts.transparent,
        use: '单张生成',
        t0: Date.now() / 1000,
        sec: 30,
        refs: opts.refs?.length || 0,
        size: ratio,
        run_s: 0,
      },
    };
    this.imgJob = job;

    void (async () => {
      const tStart = Date.now();
      for (let i = 0; i < n; i++) {
        if (this.imgStopFlag) break;
        const tItem = Date.now();
        (job.cur as Record<string, unknown>).label = `单张 #${i + 1}`;
        try {
          const out = await callApiyiImage({
            apiKey: this.secrets.imgKey,
            baseUrl: base,
            model,
            prompt,
            ratio,
            tier,
            quality,
            transparent: opts.transparent,
            refs: opts.refs || [],
          });
          const hid = this.nextImgHistId++;
          const mime = out.ext === '.jpg' ? 'image/jpeg' : out.ext === '.webp' ? 'image/webp' : 'image/png';
          this.imgBuffers.set(`h:${hid}`, { buf: out.buf, mime });
          const sec = Math.round((Date.now() - tItem) / 100) / 10;
          const fileName = `${Date.now()}_${i + 1}${out.ext}`;
          this.imgRecent.unshift({
            id: hid,
            ts: Date.now() / 1000,
            kind: 'single',
            title: '单张',
            file: fileName,
            model,
            prompt,
            ratio,
            tier,
            quality,
            transparent: opts.transparent,
            w: 0,
            h: 0,
            alpha: opts.transparent,
            usd: out.usd,
            sec,
            refs: opts.refs?.length || 0,
            exists: true,
          });
          job.done = Number(job.done) + 1;
          job.usd = Math.round((Number(job.usd) + out.usd) * 1000) / 1000;
          this.imgMonth.n += 1;
          this.imgMonth.usd = Math.round((this.imgMonth.usd + out.usd) * 1000) / 1000;
          (job.results as Array<Record<string, unknown>>).push({ label: fileName, ok: true, sec, hid, ratio, transparent: opts.transparent });
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          job.fail = Number(job.fail) + 1;
          (job.results as Array<Record<string, unknown>>).push({ label: `单张 #${i + 1}`, ok: false, err: msg });
          if (/Key 无效|余额不足|限流/.test(msg)) {
            job.fatal = msg;
            break;
          }
        }
        job.elapsed = Math.round((Date.now() - tStart) / 100) / 10;
      }
      job.st = this.imgStopFlag ? 'done' : Number(job.fail) && !Number(job.done) ? 'err' : 'done';
      job.cur = null;
      job.msg = job.fatal ? String(job.fatal) : `完成 ${job.done}/${n}`;
    })();

    return job;
  }

  loadImgBoard(md: string, name = ''): Record<string, unknown> {
    const raw = String(md || '').trim();
    if (!raw) throw new Error('生图清单内容为空');
    const titleMatch = raw.match(/^#\s+(.+)$/m);
    const title = (titleMatch ? titleMatch[1].trim() : '') || (name ? path.basename(name, path.extname(name)) : '批量生图清单');
    let direction = '';
    const dirMatch = raw.match(/##\s*[^\n]*视觉方向[^\n]*\n([\s\S]*?)(?=\n##|\n###|$)/);
    if (dirMatch) direction = dirMatch[1].trim();

    const blocks = raw.split(/\n(?=###\s+|##\s*\d+\b)/).filter((b) => /^#{2,3}\s+/.test(b.trim()));
    const items: Array<Record<string, unknown>> = [];
    for (const blk of blocks) {
      if (/视觉方向/.test(blk.split('\n')[0])) continue;
      const lines = blk.trim().split(/\r?\n/);
      const head = lines[0].replace(/^#{2,3}\s+/, '').trim();
      const body = lines.slice(1).join('\n');
      const pm = body.match(/提示词\s*[：:]\s*([\s\S]+?)(?=\n-\s*(?:比例|透明|用在哪|参考)|$)/);
      const prompt = (pm ? pm[1].trim() : '').replace(/^\s*[-*]\s*/, '').trim();
      const rm = body.match(/比例\s*[：:]\s*(\d+:\d+)/);
      const ratio = rm ? rm[1] : '9:16';
      const tm = body.match(/透明(?:背景)?\s*[：:]\s*([^\n]+)/);
      const transparent = tm ? /开|true|yes|是/i.test(tm[1]) : false;
      const um = head.match(/（用在[：:]\s*([^）]+)）/) || body.match(/用在哪\s*[：:]\s*([^\n]+)/);
      const use = um ? um[1].trim() : '';
      let file = head.replace(/（[^）]*）/g, '').trim() || `img_${String(items.length + 1).padStart(2, '0')}.png`;
      if (!/\.(png|jpg|webp)$/i.test(file)) file = `${file.replace(/[^\w\u4e00-\u9fa5.-]/g, '_')}.png`;
      if (!prompt && !/^\d+$/.test(head)) continue;
      items.push({
        id: String(items.length + 1),
        file,
        use,
        ratio,
        transparent,
        st: 'idle',
        prompt: prompt || head,
        ver: 1,
        w: 0,
        h: 0,
        refs: 0,
        _refs: [] as string[],
      });
    }
    if (!items.length) {
      throw new Error('没有从清单里识别出生图条目（请使用 ### 文件名.png + 提示词：... 格式）');
    }
    this.imgBoard = {
      id: Date.now(),
      title,
      md_name: name || `${title}.md`,
      warn: [],
      dir: path.join(this.places().imgOut, title),
      exists: true,
      direction,
      items,
    };
    return this.getImgState();
  }

  patchImgItem(id: string, patch: Record<string, unknown>): Record<string, unknown> {
    const board = this.imgBoard as { items?: Array<Record<string, unknown>> } | null;
    const item = board?.items?.find((x) => String(x.id) === String(id));
    if (!item) throw new Error('找不到这条清单项目');
    if (typeof patch.prompt === 'string') item.prompt = patch.prompt;
    if (typeof patch.ratio === 'string') item.ratio = patch.ratio;
    if (typeof patch.transparent === 'boolean') item.transparent = patch.transparent;
    if (Array.isArray(patch.refs)) {
      item._refs = patch.refs.filter((r): r is string => typeof r === 'string');
      item.refs = (item._refs as string[]).length;
    }
    item.edited = true;
    return item;
  }

  startImgBatch(body: Record<string, unknown>): Record<string, unknown> {
    if (!this.secrets.imgKey) throw new Error('还没填 API易 Key，请先到 设置 › 云端 填写');
    if (this.imgJob && this.imgJob.st === 'run') throw new Error('生图任务正在跑，等它出完或先点停下');
    const board = this.imgBoard as { title?: string; direction?: string; items?: Array<Record<string, unknown>> } | null;
    if (!board?.items?.length) throw new Error('还没有加载生图清单');

    const ids = Array.isArray(body.ids) ? new Set(body.ids.map((x) => String(x))) : null;
    const missingOnly = Boolean(body.missing);
    const todo = board.items.filter((it) => {
      if (ids && !ids.has(String(it.id))) return false;
      if (missingOnly && it.st === 'ok') return false;
      return true;
    });
    if (!todo.length) throw new Error('没有需要生成的项目');

    const tier = String(this.settings.imgRes || '2k');
    const quality = String(this.settings.imgQuality || 'high');
    const model = String(this.settings.imgModel || 'gpt-image-2.5-sunburst-vip');
    const base = String(this.settings.imgBase || 'https://api.apiyi.com/v1');
    const noText = this.settings.imgNoText !== false;
    const withDir = Boolean(this.settings.imgWithDir);

    this.imgStopFlag = false;
    for (const it of todo) {
      it.st = 'queue';
      it.err = '';
    }

    const job: Record<string, unknown> = {
      id: Date.now(),
      st: 'run',
      kind: 'batch',
      n: todo.length,
      done: 0,
      fail: 0,
      msg: '正在逐张请求 API易…',
      est: Math.round(todo.length * 0.03 * 100) / 100,
      model,
      mname: model,
      quality,
      tier,
      conc: 1,
      fatal: '',
      usd: 0,
      elapsed: 0,
      results: [] as Array<Record<string, unknown>>,
      cur: null,
    };
    this.imgJob = job;

    void (async () => {
      const tStart = Date.now();
      for (const it of todo) {
        if (this.imgStopFlag) {
          it.st = 'idle';
          continue;
        }
        it.st = 'run';
        const tItem = Date.now();
        let prompt = String(it.prompt || '').trim();
        if (withDir && board.direction) prompt = `${board.direction}\n${prompt}`;
        if (it.transparent) prompt += '；只画主体本身，背景完全透明，不要背景颜色或阴影。';
        if (noText) prompt += '；画面里不要出现任何文字、字母、数字、水印或 logo。';

        job.cur = {
          label: String(it.file || it.id),
          prompt,
          ratio: String(it.ratio || '16:9'),
          transparent: Boolean(it.transparent),
          use: String(it.use || ''),
          t0: Date.now() / 1000,
          sec: 30,
          refs: Number(it.refs) || 0,
          size: String(it.ratio || '16:9'),
          run_s: 0,
        };
        try {
          const out = await callApiyiImage({
            apiKey: this.secrets.imgKey,
            baseUrl: base,
            model,
            prompt,
            ratio: String(it.ratio || '16:9'),
            tier,
            quality,
            transparent: Boolean(it.transparent),
            refs: Array.isArray(it._refs) ? (it._refs as string[]) : [],
          });
          const mime = out.ext === '.jpg' ? 'image/jpeg' : out.ext === '.webp' ? 'image/webp' : 'image/png';
          this.imgBuffers.set(`i:${it.id}`, { buf: out.buf, mime });
          const hid = this.nextImgHistId++;
          this.imgBuffers.set(`h:${hid}`, { buf: out.buf, mime });
          const sec = Math.round((Date.now() - tItem) / 100) / 10;
          it.st = 'ok';
          it.ver = Number(it.ver || 0) + 1;
          it.sec = sec;
          it.usd = out.usd;
          it.alpha = Boolean(it.transparent);
          this.imgRecent.unshift({
            id: hid,
            ts: Date.now() / 1000,
            kind: 'batch',
            title: String(board.title || '批量'),
            file: String(it.file || 'image.png'),
            model,
            prompt: String(it.prompt || ''),
            ratio: String(it.ratio || '16:9'),
            tier,
            quality,
            transparent: Boolean(it.transparent),
            w: 0,
            h: 0,
            alpha: Boolean(it.transparent),
            usd: out.usd,
            sec,
            refs: Number(it.refs) || 0,
            exists: true,
          });
          job.done = Number(job.done) + 1;
          job.usd = Math.round((Number(job.usd) + out.usd) * 1000) / 1000;
          this.imgMonth.n += 1;
          this.imgMonth.usd = Math.round((this.imgMonth.usd + out.usd) * 1000) / 1000;
          (job.results as Array<Record<string, unknown>>).push({
            item: it.id,
            label: String(it.file || it.id),
            ok: true,
            sec,
            usd: out.usd,
            ratio: it.ratio,
            transparent: it.transparent,
          });
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          it.st = 'err';
          it.err = msg;
          job.fail = Number(job.fail) + 1;
          (job.results as Array<Record<string, unknown>>).push({
            item: it.id,
            label: String(it.file || it.id),
            ok: false,
            err: msg,
            ratio: it.ratio,
          });
          if (/Key 无效|余额不足|限流|找不到模型|没有该模型/.test(msg)) {
            job.fatal = msg;
            for (const rem of todo) {
              if (rem.st === 'queue') rem.st = 'idle';
            }
            break;
          }
        }
        job.elapsed = Math.round((Date.now() - tStart) / 100) / 10;
      }
      job.st = this.imgStopFlag ? 'stop' : Number(job.fail) && !Number(job.done) ? 'err' : 'done';
      job.cur = null;
      job.msg = job.fatal ? String(job.fatal) : `完成 ${job.done}/${todo.length}`;
    })();

    return job;
  }

  startTtsGen(body: Record<string, unknown>): Record<string, unknown> {
    const engine = String(body.engine || this.settings.ttsEngine || 'local');
    const text = String(body.text || '').trim();
    if (!text) throw new Error('先把要配音的文案贴进来');
    if (engine === 'cloud' && !this.secrets.blKey) {
      throw new Error('还没填百炼 API Key，请到 设置 › 云端 填写');
    }
    if (this.ttsJob && (this.ttsJob as Record<string, unknown>).st === 'run') {
      throw new Error('正在生成配音，请等待完成或先点停下');
    }

    this.ttsStopFlag = false;
    const job: Record<string, unknown> = {
      id: Date.now(),
      st: 'run',
      pct: 10,
      msg: engine === 'cloud' ? '正在调用阿里云百炼合成…' : '容器无本地 Qwen3-TTS GPU，使用预览音轨…',
    };
    this.ttsJob = job;

    void (async () => {
      try {
        let wavBuf: Buffer;
        let duration: number;
        let characters = text.length;
        if (engine === 'cloud') {
          const out = await callBailianTts({
            apiKey: this.secrets.blKey,
            baseUrl: String(this.settings.blBase || 'https://dashscope.aliyuncs.com/api/v1'),
            model: String(this.settings.blModel || 'qwen-audio-3.1-tts-plus'),
            text,
            voice: String(body.voice || 'longanlingxin_v3.1'),
            instruction: typeof body.tone === 'string' ? body.tone : undefined,
            rate: typeof body.rate === 'number' ? body.rate : undefined,
            pitch: typeof body.pitch === 'number' ? body.pitch : undefined,
            volume: typeof body.volume === 'number' ? body.volume : undefined,
            lang: typeof body.lang === 'string' ? body.lang : undefined,
            hotfix: this.ttsPronDict,
          });
          wavBuf = out.wavBuf;
          duration = out.duration;
          characters = out.characters;
          const cny = Math.round((characters * (Number(this.settings.blPrice) || 1.4) / 10000) * 10000) / 10000;
          this.ttsCloudMonth.n += 1;
          this.ttsCloudMonth.bill += characters;
          this.ttsCloudMonth.cny = Math.round((this.ttsCloudMonth.cny + cny) * 10000) / 10000;
        } else {
          const est = Math.max(1.5, Math.min(15, text.length * 0.22));
          const syn = createWavBuffer(est, 'white', text.length);
          wavBuf = syn.buf;
          duration = syn.duration;
        }
        if (this.ttsStopFlag) {
          job.st = 'done';
          job.msg = '已停止';
          return;
        }
        this.ttsDraftWav = wavBuf;
        const lines = text.split(/[。！？!?\r\n]+/).map((x) => x.trim()).filter(Boolean);
        const segList = lines.length ? lines : [text];
        let cursor = 0;
        const totalChars = Math.max(1, segList.reduce((a, s) => a + s.length, 0));
        const segments = segList.map((s) => {
          const sdur = Math.max(0.2, (s.length / totalChars) * duration);
          const item = { text: s, start: Math.round(cursor * 100) / 100, end: Math.round((cursor + sdur) * 100) / 100, est: engine !== 'cloud' };
          cursor += sdur;
          return item;
        });
        this.ttsDraft = {
          ver: Date.now(),
          created: formatDateTime(Date.now() / 1000),
          duration,
          voice: engine === 'cloud'
            ? { mode: 'cloud', voice: String(body.voice || 'longanlingxin_v3.1'), name: String(body.voice || '龙安灵心') }
            : { mode: 'preset', speaker: String(body.speaker || 'Vivian') },
          segments,
          check: {
            method: engine === 'cloud' ? '百炼流式合成' : '预览波形',
            how: engine === 'cloud' ? ['words'] : ['pause'],
            sure: engine === 'cloud',
            sentences: segments.length,
            exact: engine === 'cloud' ? segments.length : 0,
            estimated: engine === 'cloud' ? 0 : segments.length,
          },
          same_test: Boolean(body.same),
        };
        job.st = 'done';
        job.pct = 100;
        job.msg = engine === 'cloud' ? `百炼合成完成（${duration.toFixed(1)}s · ${characters} 计费字符）` : `已生成预览音频（${duration.toFixed(1)}s）`;
      } catch (err) {
        job.st = 'err';
        job.pct = 0;
        job.msg = err instanceof Error ? err.message : String(err);
      }
    })();

    return job;
  }

  getBgmState(): Record<string, unknown> {
    return {
      up: false,
      alive: false,
      configured: false,
      can_start: false,
      yielding: false,
      yield_reason: '',
      url: String(this.settings.bgmUrl || 'http://127.0.0.1:8094'),
      out: this.places().bgmOut,
      job: null,
      idle: Number(this.settings.bgmIdle) || 10,
      recent: [],
    };
  }

  getPublishState(): Record<string, unknown> {
    return {
      demo: false,
      ready: { deps: false, browser: '', vendor: false },
      account: { has: false, ok: false, at: null, msg: '未登录（容器环境不支持浏览器自动化扫码）' },
      job: null,
      pending: this.pubPending,
      decls: ['内容由AI生成', '内容自行拍摄', '内容取材网络', '虚构演绎，仅供娱乐', '可能引人不适', '危险行为，请勿模仿'],
      opts: { headless: Boolean(this.settings.pubHeadless), decl: String(this.settings.pubDecl || '内容由AI生成') },
      agent: { on: Boolean(this.settings.agPublish), ask: Boolean(this.settings.agPublishAsk) },
      videos: [],
      hist: [],
      batch: null,
    };
  }

  getCcodeState(): Record<string, unknown> {
    return {
      status: {
        on: Boolean(this.settings.ccOn),
        found: false,
        version: '',
        path: String(this.settings.ccCmd || ''),
        minutes: Number(this.settings.ccMinutes) || 60,
        bash: String(this.settings.ccBash || ''),
        model: String(this.settings.ccModel || ''),
      },
      job: this.ccodeJob,
    };
  }

  putStudioAsset(pid: string, asset: StudioAsset): StudioAsset {
    const kind: StudioAssetVersion['kind'] = asset.mime.startsWith('image/')
      ? 'image'
      : asset.mime.startsWith('audio/')
        ? 'audio'
        : asset.mime.startsWith('video/')
          ? 'video'
          : 'script';
    this.studioOrch.putAsset(pid, asset, { kind, label: asset.name, adopt: true });
    return asset;
  }

  getStudioAsset(pid: string, rel: string): StudioAsset | null {
    return this.studioOrch.getAssetBuffer(pid, rel);
  }

  getStudioState(pid?: string): Record<string, unknown> {
    return this.studioOrch.getState(pid);
  }

  createStudioProject(topic: string, ratio = '9:16', seconds = 75): StudioProjectV2 {
    return this.studioOrch.createProject(topic, ratio, seconds);
  }

  updateStudioModule(
    pid: string,
    id: string,
    patch: { title?: string; x?: number; y?: number; w?: number; h?: number; params?: Record<string, unknown> }
  ): StudioModule | null {
    const proj = this.studioOrch.getProject(pid);
    if (patch.params && typeof patch.params === 'object') {
      const prm = patch.params;
      if (id === 'compose') {
        this.studioOrch.updateProjectConfigs(proj.id, {
          ratio: typeof prm.ratio === 'string' ? prm.ratio : undefined,
          compose_config: {
            fps: prm.fps != null ? Number(prm.fps) : proj.compose_config.fps,
            bgm_volume: prm.bgm_volume != null ? Number(prm.bgm_volume) : proj.compose_config.bgm_volume,
            duck_depth: prm.duck_depth != null ? Number(prm.duck_depth) : proj.compose_config.duck_depth,
            fade: prm.fade != null ? Number(prm.fade) : proj.compose_config.fade,
            subtitle: prm.subtitle !== undefined ? Boolean(prm.subtitle) : proj.compose_config.subtitle,
            cc_drive: prm.cc_drive !== undefined ? Boolean(prm.cc_drive) : proj.compose_config.cc_drive,
          },
        });
      } else if (id === 'bgm') {
        this.studioOrch.updateProjectConfigs(proj.id, {
          bgm: {
            prompt: typeof prm.prompt === 'string' ? prm.prompt : undefined,
            seconds: prm.seconds != null ? Number(prm.seconds) : undefined,
            steps: prm.steps != null ? Number(prm.steps) : undefined,
            seed: prm.seed != null ? Number(prm.seed) : undefined,
          },
        });
      } else if (id === 'image') {
        this.studioOrch.updateProjectConfigs(proj.id, {
          image_config: {
            model: typeof prm.model === 'string' ? prm.model : undefined,
            ratio: typeof prm.ratio === 'string' ? prm.ratio : undefined,
            resolution: typeof prm.resolution === 'string' ? prm.resolution : undefined,
            quality: typeof prm.quality === 'string' ? prm.quality : undefined,
            n: prm.n != null ? Number(prm.n) : undefined,
            output: prm.output === 'svg' ? 'svg' : prm.output === 'normal' ? 'normal' : undefined,
            refs: Array.isArray(prm.refs) ? (prm.refs as string[]) : undefined,
          },
        });
      } else if (id === 'script') {
        this.studioOrch.updateProjectConfigs(proj.id, {
          title: typeof prm.title === 'string' ? prm.title : undefined,
          desc: typeof prm.desc === 'string' ? prm.desc : undefined,
        });
      }
    }
    syncProjectDerivedViews(proj);
    return (proj.modules.find((m) => m.id === id) as StudioModule | undefined) || null;
  }

  updateStudioList(pid: string, name: string, text: string): { ok: boolean; error?: string; project?: StudioProjectV2 } {
    const proj = this.studioOrch.getProject(pid);
    proj.lists[name] = text;
    const err = applyMarkdownListToModules(name, text, proj.modules);
    if (err) {
      return { ok: false, error: err, project: proj };
    }
    if (name === '配音清单_白页.md' || name === '配音清单_紫苏.md') {
      const targetRole = name.includes('紫苏') ? '紫苏' : '白页';
      const mod = proj.modules.find((m) => m.id === (targetRole === '紫苏' ? 'voice-zisu' : 'voice-white'));
      const lines = Array.isArray(mod?.params.lines) ? (mod!.params.lines as VoiceLine[]) : [];
      const speaker = String(mod?.params.speaker || (targetRole === '紫苏' ? 'local:preset:Dylan' : 'local:preset:Serena'));
      const others = proj.dialogues.filter((d) => d.role !== targetRole);
      const replaced = lines.map((l, idx) => ({
        line_id: `line_${targetRole === '紫苏' ? 'z' : 'w'}_${l.line_index || idx + 1}`,
        shot_id: proj.shots[idx]?.shot_id || proj.shots[0]?.shot_id || 'shot_01',
        order: l.line_index || idx + 1,
        role: targetRole,
        speaker,
        engine: 'auto' as const,
        text: l.text,
        tone: l.tone || (targetRole === '紫苏' ? '轻松调侃' : '冷静吐槽'),
      }));
      proj.dialogues = [...others, ...replaced].sort((a, b) => a.order - b.order);
    } else if (name === '配乐清单.md') {
      const mod = proj.modules.find((m) => m.id === 'bgm');
      if (mod) {
        proj.bgm.prompt = String(mod.params.prompt || proj.bgm.prompt);
        proj.bgm.seconds = Number(mod.params.seconds || proj.bgm.seconds);
        proj.bgm.steps = Number(mod.params.steps || proj.bgm.steps);
        proj.bgm.seed = Number(mod.params.seed || proj.bgm.seed);
      }
    } else if (name === '视频渲染清单.md') {
      const mod = proj.modules.find((m) => m.id === 'compose');
      const shots = Array.isArray(mod?.params.shots) ? (mod!.params.shots as StudioShot[]) : [];
      proj.shots = shots.map((s, idx) => ({
        shot_id: s.id || `shot_${String(idx + 1).padStart(2, '0')}`,
        order: s.line_index || idx + 1,
        render: s.render,
        visual_prompt: s.visual,
        subtitle_text: s.text,
        duration_sec: s.seconds,
      }));
    } else if (name === '生图清单.md') {
      const mod = proj.modules.find((m) => m.id === 'image');
      const items = Array.isArray(mod?.params.items) ? (mod!.params.items as Array<Record<string, unknown>>) : [];
      proj.image_config.items = items.map((it, idx) => ({
        item_id: `img_${String(idx + 1).padStart(2, '0')}`,
        shot_id: proj.shots[idx]?.shot_id,
        label: `镜头 ${idx + 1} 配图`,
        prompt: String(it.prompt || ''),
        ratio: String(it.ratio || proj.ratio),
        transparent: Boolean(it.transparent),
      }));
    }
    proj.revision += 1;
    syncProjectDerivedViews(proj);
    return { ok: true, project: proj };
  }

  importStudioScript(pid: string, rawText: string): { project: StudioProjectV2; summary: string; estimate: { image_usd: number } } | null {
    const proj = this.studioOrch.getProject(pid);
    if (!proj) return null;
    const res = applyParsedScriptToProject(proj, rawText);
    return { project: proj, summary: res.summary, estimate: { image_usd: res.estimateUsd } };
  }

  async planStudioScript(pid: string, topic: string, seconds = 75): Promise<{ project: StudioProjectV2; summary: string; estimate: { image_usd: number } }> {
    const proj = this.studioOrch.getProject(pid);
    await this.studioOrch.runDirectAgentTask(proj.id, 'script', { topic: topic || proj.title, seconds });
    return {
      project: proj,
      summary: proj.script_summary,
      estimate: { image_usd: Math.round(proj.image_config.items.length * 0.03 * 100) / 100 },
    };
  }

  startStudioRun(pid: string, opts: { id?: string; part?: 'web' | 'ppt' | 'ffmpeg'; force?: boolean }): StudioProjectV2 {
    const proj = this.studioOrch.getProject(pid);
    if (!opts.id) {
      void this.studioOrch.sendChatMessage(proj.id, { text: '请立即执行全流程生成，跳过审批' });
      return proj;
    }
    const mapModToAgent: Record<string, AgentId> = {
      script: 'script',
      image: 'image',
      'voice-white': 'voice',
      'voice-zisu': 'voice',
      bgm: 'bgm',
      compose: opts.part === 'web' || opts.part === 'ppt' ? 'video_gen' : 'compose',
      publish: 'qa',
    };
    const aid = mapModToAgent[opts.id] || 'compose';
    this.studioOrch.runDirectAgentTask(proj.id, aid, { force: Boolean(opts.force) });
    return proj;
  }

  stopStudio(pid?: string, moduleId?: string): { stopped: string[] } {
    return this.studioOrch.stopAllTasks(pid || this.activeStudioId, moduleId);
  }
}

export const store = new AppStore();

