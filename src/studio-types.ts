import type { StudioModuleLike } from './studio-runtime.ts';

export type AgentId =
  | 'supervisor'
  | 'script'
  | 'storyboard'
  | 'image'
  | 'voice'
  | 'bgm'
  | 'video_gen'
  | 'compose'
  | 'qa';

export type AgentStatus =
  | 'idle'
  | 'thinking'
  | 'running'
  | 'waiting_input'
  | 'waiting_approval'
  | 'failed'
  | 'completed'
  | 'paused';

export interface AgentProfile {
  id: AgentId;
  name: string;
  role: string;
  responsibility: string;
  tools: string[];
  color_token: string;
}

export type TaskState =
  | 'pending'
  | 'ready'
  | 'running'
  | 'waiting_approval'
  | 'succeeded'
  | 'failed'
  | 'retrying'
  | 'cancelled'
  | 'paused';

export interface StudioShotV2 {
  shot_id: string;
  order: number;
  render: 'web' | 'ppt' | 'static';
  visual_prompt: string;
  subtitle_text: string;
  duration_sec: number;
  transition?: string;
  image_asset_id?: string;
  frame_asset_id?: string;
  cache_key?: string;
}

export interface StudioDialogueV2 {
  line_id: string;
  shot_id: string;
  order: number;
  role: string;
  speaker: string;
  engine: 'auto' | 'local' | 'cloud';
  text: string;
  tone: string;
  audio_asset_id?: string;
  duration_sec?: number;
  cache_key?: string;
}

export interface StudioImageItemV2 {
  item_id: string;
  shot_id?: string;
  label: string;
  prompt: string;
  ratio: string;
  transparent: boolean;
  asset_id?: string;
  cache_key?: string;
}

export interface StudioAssetVersion {
  asset_id: string;
  rel: string;
  kind: 'image' | 'audio' | 'video' | 'subtitle' | 'script';
  version: number;
  adopted: boolean;
  parent_asset_id?: string;
  task_id?: string;
  agent_id?: AgentId;
  shot_id?: string;
  line_id?: string;
  label: string;
  sha256: string;
  mime: string;
  size: number;
  w?: number;
  h?: number;
  duration?: number;
  model?: string;
  params?: Record<string, unknown>;
  cache_hit?: boolean;
  created_at: number;
}

export interface StudioTaskNode {
  task_id: string;
  project_id: string;
  agent_id: AgentId;
  action: string;
  title: string;
  deps: string[];
  state: TaskState;
  progress: number;
  phase: string;
  inputs: Record<string, unknown>;
  outputs: string[];
  logs: string[];
  error?: string;
  retry_count: number;
  max_retries: number;
  cost_usd: number;
  cost_cny: number;
  cache_hit: boolean;
  created_at: number;
  started_at?: number;
  ended_at?: number;
}

export interface StudioApproval {
  approval_id: string;
  task_id?: string;
  agent_id: AgentId;
  action_type: 'batch_run' | 'cloud_spend' | 'overwrite_asset' | 'publish' | 'qa_fix';
  title: string;
  summary: string;
  estimated_cost_usd: number;
  estimated_cost_cny: number;
  affected_items: string[];
  status: 'pending' | 'approved' | 'rejected';
  payload: Record<string, unknown>;
  created_at: number;
  decided_at?: number;
  decision_note?: string;
}

export interface ChatArtifactRef {
  asset_id: string;
  rel: string;
  kind: 'image' | 'audio' | 'video' | 'subtitle' | 'script';
  label: string;
  sha256?: string;
  duration?: number;
  w?: number;
  h?: number;
}

export interface StudioChatMessage {
  msg_id: string;
  ts: number;
  kind: 'user' | 'agent' | 'discussion' | 'task_event' | 'approval' | 'artifact';
  sender_id: string;
  sender_name: string;
  mentions?: AgentId[];
  reply_to?: string;
  reply_preview?: string;
  text: string;
  details?: string;
  task_id?: string;
  approval_id?: string;
  event_state?: TaskState | 'cached';
  assets?: ChatArtifactRef[];
  attachments?: Array<{ rel: string; name: string; kind: string }>;
}

export interface QACheckItem {
  key: string;
  name: string;
  passed: boolean;
  severity: 'error' | 'warn' | 'info';
  detail: string;
  target_agent?: AgentId;
  target_shot_id?: string;
  fix_action?: string;
}

export interface QAReport {
  report_id: string;
  project_id: string;
  created_at: number;
  passed: boolean;
  score_label: string;
  summary: string;
  probe?: {
    format?: string;
    duration?: number;
    size?: number;
    video_codec?: string;
    width?: number;
    height?: number;
    fps?: number;
    audio_codec?: string;
    sample_rate?: number;
    channels?: number;
  };
  checks: QACheckItem[];
}

export interface StudioCacheEntry {
  key: string;
  fingerprint: string;
  asset_ids: string[];
  updated_at: number;
}

export interface StudioProjectV2 {
  id: string;
  revision: number;
  name: string;
  title: string;
  desc: string;
  tags: string[];
  ratio: string;
  target_duration: number;
  created: string;
  updated_at: number;
  dir: string;
  script_summary: string;
  shots: StudioShotV2[];
  dialogues: StudioDialogueV2[];
  bgm: {
    prompt: string;
    seconds: number;
    steps: number;
    seed: number;
    asset_id?: string;
  };
  image_config: {
    model: string;
    ratio: string;
    resolution: string;
    quality: string;
    n: number;
    output: 'normal' | 'svg';
    refs: string[];
    items: StudioImageItemV2[];
  };
  compose_config: {
    fps: number;
    bgm_volume: number;
    duck_depth: number;
    fade: number;
    subtitle: boolean;
    cc_drive: boolean;
  };
  publish_config: {
    title: string;
    desc: string;
    tags: string[];
    mode: 'single' | 'batch';
    declaration: string;
  };
  assets: StudioAssetVersion[];
  tasks: StudioTaskNode[];
  approvals: StudioApproval[];
  messages: StudioChatMessage[];
  cache: Record<string, StudioCacheEntry>;
  qa?: QAReport;
  files: Record<string, unknown>;
  total_seconds: number;
  duration: number;
  resolution: string;
  video_ok: boolean;
  lists: Record<string, string>;
  modules: StudioModuleLike[];
  agent_unread: Record<string, number>;
  agent_paused: Record<string, boolean>;
}

export const AGENT_ROLES: AgentProfile[] = [
  {
    id: 'supervisor',
    name: '总导演 Agent',
    role: 'Supervisor',
    responsibility: '拆解制作目标、调度任务 DAG、估算成本与人类审批门控',
    tools: ['plan.decompose', 'task.schedule', 'approval.gate'],
    color_token: 'var(--hud)',
  },
  {
    id: 'script',
    name: '剧本 Agent',
    role: 'Script',
    responsibility: '提炼钩子、编写双角色台词（白页 / 紫苏）并分配 line_id',
    tools: ['script.plan', 'script.import', 'markdown.sync'],
    color_token: 'var(--text2)',
  },
  {
    id: 'storyboard',
    name: '分镜 Agent',
    role: 'Storyboard',
    responsibility: '划分镜头 shot_id、画面排版风格（网页动效/PPT/静态）与时长节奏',
    tools: ['storyboard.build', 'shot.timing'],
    color_token: 'var(--accent)',
  },
  {
    id: 'image',
    name: '生图 Agent',
    role: 'Image',
    responsibility: '调用 API易/生图模型生成场景与角色视觉资产，管理版本与参考图',
    tools: ['image.generate', 'image.adopt'],
    color_token: 'var(--ok)',
  },
  {
    id: 'voice',
    name: '配音 Agent',
    role: 'Voice',
    responsibility: '按句级 line_id 并行或增量合成阿里云百炼/本地配音并拼接音轨',
    tools: ['voice.synthesize_line', 'voice.merge_track'],
    color_token: 'var(--warn)',
  },
  {
    id: 'bgm',
    name: '配乐 Agent',
    role: 'BGM',
    responsibility: '生成匹配视频情绪与时长的 -1 dBFS 归一背景音轨',
    tools: ['bgm.generate'],
    color_token: 'var(--warn)',
  },
  {
    id: 'video_gen',
    name: '视频生成 Agent',
    role: 'Video Gen',
    responsibility: '渲染网页动效帧、PPT 卡片帧与镜头动态片段，支持局部重渲染',
    tools: ['video.render_frames'],
    color_token: 'var(--hud)',
  },
  {
    id: 'compose',
    name: '后期合成 Agent',
    role: 'Compose',
    responsibility: '执行 FFmpeg 音画混流、BGM 闪避压低、字幕与 MP4 成片压制',
    tools: ['compose.ffmpeg', 'subtitle.srt'],
    color_token: 'var(--hot, var(--accent))',
  },
  {
    id: 'qa',
    name: '质检 Agent',
    role: 'QA',
    responsibility: '调用 ffprobe 检验分辨率、帧率、音画同步、资源引用与可播放性',
    tools: ['qa.inspect', 'qa.fix_plan'],
    color_token: 'var(--ok)',
  },
];

export const AGENT_MAP: Record<AgentId, AgentProfile> = Object.fromEntries(
  AGENT_ROLES.map((a) => [a.id, a])
) as Record<AgentId, AgentProfile>;
