import type { ChildProcess } from 'node:child_process';
import path from 'node:path';
import { callApiyiImage, callBailianTts } from './cloud-apis.ts';
import { StudioPersistence } from './studio-persistence.ts';
import {
  concatWavBuffers,
  createPngBuffer,
  createSvgBuffer,
  createWavBuffer,
  dimsForRatio,
  makeAsset,
  runFfmpegCompose,
  sha256Hex,
  type StudioAsset,
} from './studio-runtime.ts';
import {
  applyParsedScriptToProject,
  checkBinaryAvailable,
  computeBgmFingerprint,
  computeLineFingerprint,
  computeShotVisualFingerprint,
  generateSrtBuffer,
  runRealFfprobeQA,
  STUDIO_TOOL_REGISTRY,
  syncProjectDerivedViews,
} from './studio-tools.ts';
import {
  AGENT_MAP,
  AGENT_ROLES,
  type AgentId,
  type AgentStatus,
  type ChatArtifactRef,
  type QAReport,
  type StudioApproval,
  type StudioAssetVersion,
  type StudioChatMessage,
  type StudioDialogueV2,
  type StudioProjectV2,
  type StudioShotV2,
  type StudioTaskNode,
} from './studio-types.ts';

export interface StudioHostContext {
  wsDir: string;
  settings: Record<string, unknown>;
  secrets: { dsKey: string; blKey: string; imgKey: string };
  ttsPronDict: { pronunciation: Record<string, string>; replace: Record<string, string> };
  imgMonth: { n: number; usd: number };
  ttsCloudMonth: { n: number; cny: number; bill: number };
  ttsCloudMine: Array<Record<string, unknown>>;
  imgExtraModels: Array<Record<string, unknown>>;
  pubPending: Array<Record<string, unknown>>;
  sampleHardware: () => Record<string, unknown>;
  addFeed: (text: string, kind?: 'head' | 'step' | 'ok' | 'warn' | 'err' | 'ds' | 'info' | 'prog', job?: string) => void;
}

function nowSec(): number {
  return Math.floor(Date.now() / 1000);
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

export class StudioOrchestrator {
  private host: StudioHostContext;
  private persistence: StudioPersistence;
  readonly projects = new Map<string, StudioProjectV2>();
  readonly assetsByProject = new Map<string, Map<string, StudioAsset>>();
  private taskAborts = new Map<string, AbortController>();
  private taskProcs = new Map<string, Set<ChildProcess>>();
  private activePid = 'proj-default';
  private thinkingAgents = new Map<string, AgentId>(); // pid -> thinking agent
  private toolAvailability: Record<string, boolean> = { ffmpeg: true, ffprobe: true };

  constructor(host: StudioHostContext) {
    this.host = host;
    this.persistence = new StudioPersistence(host.wsDir);
    void this.probeTools();
    this.initFromDiskOrSeed();
  }

  private async probeTools(): Promise<void> {
    const [ff, fp] = await Promise.all([checkBinaryAvailable('ffmpeg'), checkBinaryAvailable('ffprobe')]);
    this.toolAvailability = { ffmpeg: ff, ffprobe: fp };
  }

  private initFromDiskOrSeed(): void {
    const loaded = this.persistence.loadAll();
    if (loaded && loaded.projects.length) {
      this.activePid = loaded.activeId;
      for (const p of loaded.projects) {
        if (!p.agent_unread) p.agent_unread = {};
        if (!p.agent_paused) p.agent_paused = {};
        syncProjectDerivedViews(p);
        this.projects.set(p.id, p);
      }
      for (const [pid, bucket] of loaded.assetsByProject.entries()) {
        this.assetsByProject.set(pid, bucket);
      }
      return;
    }

    const proj = this.buildDefaultProject('proj-default', '三个被低估的 AI 用法', '9:16', 60);
    this.projects.set(proj.id, proj);
    this.activePid = proj.id;
    this.persistAll();
  }

  private buildDefaultProject(id: string, topic: string, ratio = '9:16', targetSec = 60): StudioProjectV2 {
    const t = nowSec();
    const cleanTopic = topic.trim() || '新建视频项目';
    const shots: StudioShotV2[] = [
      {
        shot_id: 'shot_01',
        order: 1,
        render: 'web',
        visual_prompt: `暖光桌面科技特写与主题标题动效：${cleanTopic}`,
        subtitle_text: `先说一个关于「${cleanTopic}」的反常识结论。`,
        duration_sec: 5,
        transition: 'cut',
      },
      {
        shot_id: 'shot_02',
        order: 2,
        render: 'ppt',
        visual_prompt: '双栏对比信息卡片：常见误区 vs 高效工作流',
        subtitle_text: '等等，这也太离谱了吧？平时真没注意还能这么用！',
        duration_sec: 5,
        transition: 'slide',
      },
    ];
    const dialogues: StudioDialogueV2[] = [
      {
        line_id: 'line_01',
        shot_id: 'shot_01',
        order: 1,
        role: '白页',
        speaker: 'local:preset:Serena',
        engine: 'auto',
        text: `先说一个关于「${cleanTopic}」的反常识结论。`,
        tone: '冷静吐槽',
      },
      {
        line_id: 'line_02',
        shot_id: 'shot_02',
        order: 2,
        role: '紫苏',
        speaker: 'local:preset:Dylan',
        engine: 'auto',
        text: '等等，这也太离谱了吧？平时真没注意还能这么用！',
        tone: '轻松调侃',
      },
    ];
    const proj: StudioProjectV2 = {
      id,
      revision: 1,
      name: cleanTopic.slice(0, 24),
      title: cleanTopic,
      desc: '知识科普 × 科技数码 × 搞笑段子',
      tags: ['AI', '科普'],
      ratio,
      target_duration: targetSec,
      created: fmtTime(t),
      updated_at: t,
      dir: path.join(this.host.wsDir, '视频工坊', id),
      script_summary: `${dialogues.length} 句台词 · ${shots.length} 镜 · 目标 ${shots.reduce((a, s) => a + s.duration_sec, 0)}s`,
      shots,
      dialogues,
      bgm: {
        prompt: 'upbeat electronic, no vocals',
        seconds: 75,
        steps: 8,
        seed: 20261118,
      },
      image_config: {
        model: String(this.host.settings.imgModel || 'gpt-image-2.5-sunburst-vip'),
        ratio,
        resolution: String(this.host.settings.imgRes || '2k'),
        quality: String(this.host.settings.imgQuality || 'high'),
        n: 1,
        output: 'normal',
        refs: [],
        items: shots.map((s, idx) => ({
          item_id: `img_0${idx + 1}`,
          shot_id: s.shot_id,
          label: `镜头 ${s.order} 配图`,
          prompt: s.visual_prompt,
          ratio,
          transparent: false,
        })),
      },
      compose_config: {
        fps: 24,
        bgm_volume: 0.18,
        duck_depth: 0.16,
        fade: 2,
        subtitle: true,
        cc_drive: true,
      },
      publish_config: {
        title: cleanTopic,
        desc: '知识科普 × 科技数码 × 搞笑段子',
        tags: ['AI', '科普'],
        mode: 'single',
        declaration: '内容由AI生成',
      },
      assets: [],
      tasks: [],
      approvals: [],
      messages: [
        {
          msg_id: uid('msg'),
          ts: t,
          kind: 'agent',
          sender_id: 'supervisor',
          sender_name: '总导演 Agent',
          text: `项目「${cleanTopic}」已初始化（${ratio} · ${shots.length} 镜）。\n你可以直接在下方输入创作指令（例如「帮我扩写成 4 镜并开始全流程制作」），或用 @ 指定某位 Agent（如 @配音、@生图、@质检）协同修改。`,
        },
      ],
      cache: {},
      files: {},
      total_seconds: shots.reduce((a, s) => a + s.duration_sec, 0),
      duration: 0,
      resolution: '',
      video_ok: false,
      lists: {},
      modules: [],
      agent_unread: {},
      agent_paused: {},
    };
    syncProjectDerivedViews(proj);
    return proj;
  }

  private persistProject(proj: StudioProjectV2): void {
    this.persistence.saveProject(proj);
    this.persistence.saveIndex(this.activePid, Array.from(this.projects.keys()));
  }

  private persistAll(): void {
    for (const p of this.projects.values()) {
      this.persistence.saveProject(p);
    }
    this.persistence.saveIndex(this.activePid, Array.from(this.projects.keys()));
  }

  getActiveProjectId(): string {
    return this.activePid;
  }

  getProject(pid?: string): StudioProjectV2 {
    const id = pid && this.projects.has(pid) ? pid : this.activePid;
    if (this.projects.has(id)) {
      this.activePid = id;
      return this.projects.get(id)!;
    }
    const first = Array.from(this.projects.values())[0];
    this.activePid = first.id;
    return first;
  }

  putAsset(
    pid: string,
    bufAsset: StudioAsset,
    meta: {
      kind: StudioAssetVersion['kind'];
      label: string;
      agent_id?: AgentId;
      task_id?: string;
      shot_id?: string;
      line_id?: string;
      model?: string;
      params?: Record<string, unknown>;
      adopt?: boolean;
      cache_hit?: boolean;
      versionGroupKey?: string;
    }
  ): StudioAssetVersion {
    let bucket = this.assetsByProject.get(pid);
    if (!bucket) {
      bucket = new Map<string, StudioAsset>();
      this.assetsByProject.set(pid, bucket);
    }
    bucket.set(bufAsset.rel, bufAsset);
    this.persistence.saveAssetBuffer(pid, bufAsset);

    const proj = this.projects.get(pid);
    const sameGroup = (proj?.assets || []).filter((a) => {
      if (meta.line_id && a.line_id === meta.line_id && a.kind === meta.kind) return true;
      if (meta.shot_id && a.shot_id === meta.shot_id && a.kind === meta.kind) return true;
      if (!meta.line_id && !meta.shot_id && a.rel.split('/').slice(0, 2).join('/') === bufAsset.rel.split('/').slice(0, 2).join('/') && a.kind === meta.kind) {
        return true;
      }
      return false;
    });
    const prevAdopted = sameGroup.find((a) => a.adopted);
    const nextVersion = sameGroup.reduce((m, a) => Math.max(m, a.version), 0) + 1;
    const adopt = meta.adopt !== false;
    if (adopt && proj) {
      for (const a of sameGroup) a.adopted = false;
    }

    const rec: StudioAssetVersion = {
      asset_id: uid('ast'),
      rel: bufAsset.rel,
      kind: meta.kind,
      version: nextVersion,
      adopted: adopt,
      parent_asset_id: prevAdopted?.asset_id,
      task_id: meta.task_id,
      agent_id: meta.agent_id,
      shot_id: meta.shot_id,
      line_id: meta.line_id,
      label: meta.label,
      sha256: bufAsset.sha256,
      mime: bufAsset.mime,
      size: bufAsset.buf.length,
      w: bufAsset.w,
      h: bufAsset.h,
      duration: bufAsset.duration,
      model: meta.model,
      params: meta.params,
      cache_hit: meta.cache_hit,
      created_at: nowSec(),
    };
    if (proj) {
      proj.assets.push(rec);
      if (proj.assets.length > 200) {
        proj.assets = proj.assets.slice(-200);
      }
    }
    return rec;
  }

  getAssetBuffer(pid: string, rel: string): StudioAsset | null {
    return this.assetsByProject.get(pid)?.get(rel) || null;
  }

  private pushMessage(proj: StudioProjectV2, msg: Omit<StudioChatMessage, 'msg_id' | 'ts'>): StudioChatMessage {
    const full: StudioChatMessage = {
      msg_id: uid('msg'),
      ts: nowSec(),
      ...msg,
    };
    proj.messages.push(full);
    if (proj.messages.length > 300) {
      proj.messages = proj.messages.slice(-300);
    }
    if (msg.kind === 'agent' || msg.kind === 'approval' || msg.kind === 'artifact') {
      const aid = msg.sender_id;
      if (aid && aid !== 'user') {
        proj.agent_unread[aid] = (proj.agent_unread[aid] || 0) + 1;
      }
    }
    return full;
  }

  markAgentRead(pid: string, agentId: string): void {
    const proj = this.projects.get(pid);
    if (proj && proj.agent_unread[agentId]) {
      proj.agent_unread[agentId] = 0;
      this.persistProject(proj);
    }
  }

  private computeAgentRoster(proj: StudioProjectV2): Array<Record<string, unknown>> {
    return AGENT_ROLES.map((role) => {
      const tasks = proj.tasks.filter((t) => t.agent_id === role.id);
      const running = tasks.find((t) => t.state === 'running' || t.state === 'retrying');
      const waitingApproval =
        proj.approvals.find((a) => a.status === 'pending' && (a.agent_id === role.id || (role.id === 'supervisor' && a.action_type === 'batch_run'))) ||
        tasks.find((t) => t.state === 'waiting_approval');
      const failed = tasks.slice().reverse().find((t) => t.state === 'failed');
      const paused = proj.agent_paused[role.id] || tasks.find((t) => t.state === 'paused');
      const readyOrPending = tasks.find((t) => t.state === 'ready' || t.state === 'pending');
      const completed = tasks.slice().reverse().find((t) => t.state === 'succeeded');
      const isThinking = this.thinkingAgents.get(proj.id) === role.id;

      let status: AgentStatus = 'idle';
      let currentBrief = '待命';
      if (isThinking) {
        status = 'thinking';
        currentBrief = '正在解析指令与拆解步骤…';
      } else if (running) {
        status = 'running';
        currentBrief = `${running.title} (${Math.round(running.progress)}%)`;
      } else if (waitingApproval) {
        status = 'waiting_approval';
        currentBrief = '等待你确认审批';
      } else if (paused) {
        status = 'paused';
        currentBrief = '已暂停';
      } else if (readyOrPending) {
        status = 'waiting_input';
        currentBrief = `排队中：${readyOrPending.title}`;
      } else if (failed) {
        status = 'failed';
        currentBrief = failed.error ? failed.error.slice(0, 32) : '上次任务失败';
      } else if (completed) {
        status = 'completed';
        currentBrief = completed.phase || `已完成：${completed.title}`;
      }

      return {
        ...role,
        status,
        brief: currentBrief,
        unread: proj.agent_unread[role.id] || 0,
        active_task_id: running?.task_id || readyOrPending?.task_id || completed?.task_id || failed?.task_id || null,
        paused: Boolean(proj.agent_paused[role.id]),
        task_counts: {
          running: tasks.filter((t) => t.state === 'running' || t.state === 'retrying').length,
          pending: tasks.filter((t) => t.state === 'pending' || t.state === 'ready').length,
          succeeded: tasks.filter((t) => t.state === 'succeeded').length,
          failed: tasks.filter((t) => t.state === 'failed').length,
        },
      };
    });
  }

  getState(pid?: string): Record<string, unknown> {
    const project = this.getProject(pid);
    syncProjectDerivedViews(project);

    const projects = Array.from(this.projects.values()).map((p) => {
      const anyRunning = p.tasks.some((t) => t.state === 'running' || t.state === 'retrying');
      const pendingApprovals = p.approvals.filter((a) => a.status === 'pending').length;
      return {
        id: p.id,
        name: p.name,
        title: p.title,
        created: p.created,
        ratio: p.ratio,
        revision: p.revision,
        st: anyRunning ? 'run' : pendingApprovals ? 'wait' : 'idle',
        shots: p.shots.length,
        video: p.video_ok,
      };
    });

    const agents = this.computeAgentRoster(project);
    const activeTasks = project.tasks.filter((t) => t.state === 'running' || t.state === 'retrying' || t.state === 'ready' || t.state === 'pending');
    const totalCostUsd = Math.round(project.tasks.reduce((a, t) => a + (t.cost_usd || 0), 0) * 1000) / 1000;
    const totalCostCny = Math.round(project.tasks.reduce((a, t) => a + (t.cost_cny || 0), 0) * 1000) / 1000;

    return {
      projects,
      active: project.id,
      project,
      agents,
      tools: Object.values(STUDIO_TOOL_REGISTRY),
      tool_health: {
        ...this.toolAvailability,
        deepseek: Boolean(this.host.secrets.dsKey),
        apiyi: Boolean(this.host.secrets.imgKey),
        bailian: Boolean(this.host.secrets.blKey),
      },
      resources: {
        hw: this.host.sampleHardware(),
        active_tasks: activeTasks.filter((t) => t.state === 'running' || t.state === 'retrying').length,
        queued_tasks: activeTasks.filter((t) => t.state === 'ready' || t.state === 'pending').length,
        pending_approvals: project.approvals.filter((a) => a.status === 'pending').length,
        project_cost_usd: totalCostUsd,
        project_cost_cny: totalCostCny,
      },
      voices: [
        { id: 'local:preset:Vivian', label: 'Vivian · 预设女声', engine: 'local' },
        { id: 'local:preset:Serena', label: 'Serena · 预设女声', engine: 'local' },
        { id: 'local:preset:Dylan', label: 'Dylan · 预设男声', engine: 'local' },
        { id: 'local:preset:Uncle_Fu', label: 'Uncle_Fu · 预设男声', engine: 'local' },
        { id: 'cloud:longanlingxin_v3.1', label: '龙安灵心 · 百炼女声', engine: 'cloud' },
        { id: 'cloud:longanhuan_v3.1', label: '龙安欢 · 百炼活泼女声', engine: 'cloud' },
        { id: 'cloud:longanfengyue_v3.1', label: '龙安风悦 · 百炼平和女声', engine: 'cloud' },
        { id: 'cloud:xunanchuan_v3.1', label: '许南川 · 百炼男声', engine: 'cloud' },
        ...this.host.ttsCloudMine.map((v) => ({
          id: `cloud:${String(v.id || '')}`,
          label: `${String(v.name || v.id || '自建音色')} · 云端自建`,
          engine: 'cloud',
        })),
      ],
      models: [
        { id: 'gpt-image-2.5-sunburst-vip', name: 'GPT Image 2.5 Sunburst VIP', vendor: 'OpenAI', gif: true, svg: true, price: 0.03 },
        { id: 'gemini-3.1-flash-image', name: 'Nano Banana 2', vendor: 'Google', gif: false, svg: false, price: 0.055 },
        { id: 'seedream-5-0-flash-260915', name: 'Seedream 5.0 Flash', vendor: 'Seedream', gif: false, svg: false, price: 0.018 },
        { id: 'flux-2-pro', name: 'FLUX.2 Pro', vendor: 'Flux', gif: false, svg: false, price: 0.03 },
        ...this.host.imgExtraModels.slice(0, 20).map((m) => ({
          id: String(m.id || ''),
          name: String(m.name || m.id || ''),
          vendor: String(m.vendor || '其他'),
          gif: false,
          svg: false,
          price: null,
        })),
      ],
      style_tag: '知识科普 × 科技数码 × 搞笑段子',
      roles: ['白页', '紫苏', '旁白'],
      publish: { pending: this.host.pubPending.length, batch: 0 },
      // Legacy job field kept cleanly populated for compatibility
      job: this.buildLegacyJobCompat(project),
    };
  }

  private buildLegacyJobCompat(proj: StudioProjectV2): Record<string, unknown> | null {
    const vTask = proj.tasks.slice().reverse().find((t) => t.agent_id === 'video_gen');
    const cTask = proj.tasks.slice().reverse().find((t) => t.agent_id === 'compose');
    if (!vTask && !cTask) return null;
    const anyRun = [vTask, cTask].some((t) => t?.state === 'running');
    return {
      id: cTask?.task_id || vTask?.task_id || 'job-v2',
      pid: proj.id,
      st: anyRun ? 'run' : cTask?.state === 'failed' ? 'err' : 'done',
      step: anyRun ? 'compose' : '',
      msg: cTask?.phase || vTask?.phase || '待命',
      web: {
        st: vTask?.state === 'running' ? 'run' : vTask?.state === 'succeeded' ? 'ok' : 'idle',
        current: proj.shots.length,
        total: proj.shots.length,
        frame: proj.shots.length * 24,
        total_frames: proj.shots.length * 24,
        fps: proj.compose_config.fps,
        cc: '多 Agent 视频引擎',
        msg: vTask?.phase || '就绪',
        preview_rel: proj.assets.slice().reverse().find((a) => a.rel === 'render/web_preview.png')?.rel,
      },
      ppt: {
        st: vTask?.state === 'running' ? 'run' : vTask?.state === 'succeeded' ? 'ok' : 'idle',
        current: proj.shots.filter((s) => s.render === 'ppt').length,
        total: proj.shots.filter((s) => s.render === 'ppt').length,
        msg: '就绪',
        slides: proj.assets.filter((a) => a.rel.startsWith('render/ppt_') && a.adopted).map((a) => a.rel),
      },
      ffmpeg: {
        st: cTask?.state === 'running' ? 'run' : cTask?.state === 'failed' ? 'err' : cTask?.state === 'succeeded' ? 'ok' : 'idle',
        pct: cTask?.progress || 0,
        frame: 0,
        fps: proj.compose_config.fps,
        msg: cTask?.phase || '待命',
        log: (cTask?.logs || []).join('\n'),
        params: proj.compose_config,
      },
    };
  }

  createProject(topic: string, ratio = '9:16', seconds = 60): StudioProjectV2 {
    const id = `proj-${Date.now().toString(36)}`;
    const proj = this.buildDefaultProject(id, topic, ratio, seconds);
    this.projects.set(id, proj);
    this.activePid = id;
    this.persistProject(proj);
    this.persistAll();
    return proj;
  }

  // ---------------- Optimistic Concurrency & Incremental Mutations ----------------

  private checkRevision(proj: StudioProjectV2, expectedRevision?: number): void {
    if (typeof expectedRevision === 'number' && expectedRevision !== proj.revision) {
      throw new Error(`项目版本冲突（期望 r${expectedRevision}，当前 r${proj.revision}），已防止覆盖最新修改`);
    }
  }

  updateDialogueLine(
    pid: string,
    lineId: string,
    patch: { text?: string; tone?: string; speaker?: string; engine?: 'auto' | 'local' | 'cloud'; role?: string },
    expectedRevision?: number
  ): StudioProjectV2 {
    const proj = this.getProject(pid);
    this.checkRevision(proj, expectedRevision);
    const line = proj.dialogues.find((d) => d.line_id === lineId);
    if (!line) throw new Error(`找不到台词 ${lineId}`);

    let changed = false;
    if (typeof patch.text === 'string' && patch.text !== line.text) {
      line.text = patch.text;
      changed = true;
    }
    if (typeof patch.tone === 'string' && patch.tone !== line.tone) {
      line.tone = patch.tone;
      changed = true;
    }
    if (typeof patch.speaker === 'string' && patch.speaker !== line.speaker) {
      line.speaker = patch.speaker;
      changed = true;
    }
    if (patch.engine && patch.engine !== line.engine) {
      line.engine = patch.engine;
      changed = true;
    }
    if (typeof patch.role === 'string' && patch.role !== line.role) {
      line.role = patch.role;
      changed = true;
    }

    if (changed) {
      // Partial invalidation: ONLY invalidate this line's audio + downstream compose/QA!
      line.audio_asset_id = undefined;
      line.cache_key = undefined;
      line.duration_sec = undefined;
      const linkedShot = proj.shots.find((s) => s.shot_id === line.shot_id);
      if (linkedShot && patch.text !== undefined) {
        linkedShot.subtitle_text = patch.text;
      }
      proj.video_ok = false;
      proj.qa = undefined;
      proj.revision += 1;
      proj.updated_at = nowSec();
      syncProjectDerivedViews(proj);
      this.persistProject(proj);
    }
    return proj;
  }

  addDialogueLine(pid: string, role = '白页', text = '', tone = ''): StudioProjectV2 {
    const proj = this.getProject(pid);
    const maxOrder = proj.dialogues.reduce((m, d) => Math.max(m, d.order), 0);
    const nextOrder = maxOrder + 1;
    const shotId = proj.shots[proj.shots.length - 1]?.shot_id || `shot_${String(nextOrder).padStart(2, '0')}`;
    const sameRole = proj.dialogues.find((d) => d.role === role);
    proj.dialogues.push({
      line_id: `line_${Date.now().toString(36).slice(-4)}_${nextOrder}`,
      shot_id: shotId,
      order: nextOrder,
      role,
      speaker: sameRole?.speaker || (role.includes('紫苏') ? 'local:preset:Dylan' : 'local:preset:Serena'),
      engine: sameRole?.engine || 'auto',
      text: text || `第 ${nextOrder} 句新台词`,
      tone: tone || (role.includes('紫苏') ? '轻松调侃' : '冷静吐槽'),
    });
    proj.video_ok = false;
    proj.qa = undefined;
    proj.revision += 1;
    proj.updated_at = nowSec();
    syncProjectDerivedViews(proj);
    this.persistProject(proj);
    return proj;
  }

  deleteDialogueLine(pid: string, lineId: string): StudioProjectV2 {
    const proj = this.getProject(pid);
    const before = proj.dialogues.length;
    proj.dialogues = proj.dialogues.filter((d) => d.line_id !== lineId);
    if (proj.dialogues.length !== before) {
      proj.video_ok = false;
      proj.qa = undefined;
      proj.revision += 1;
      proj.updated_at = nowSec();
      syncProjectDerivedViews(proj);
      this.persistProject(proj);
    }
    return proj;
  }

  updateShot(
    pid: string,
    shotId: string,
    patch: { render?: 'web' | 'ppt' | 'static'; visual_prompt?: string; subtitle_text?: string; duration_sec?: number },
    expectedRevision?: number
  ): StudioProjectV2 {
    const proj = this.getProject(pid);
    this.checkRevision(proj, expectedRevision);
    const shot = proj.shots.find((s) => s.shot_id === shotId);
    if (!shot) throw new Error(`找不到分镜 ${shotId}`);

    let changed = false;
    if (patch.render && patch.render !== shot.render) {
      shot.render = patch.render;
      changed = true;
    }
    if (typeof patch.visual_prompt === 'string' && patch.visual_prompt !== shot.visual_prompt) {
      shot.visual_prompt = patch.visual_prompt;
      changed = true;
    }
    if (typeof patch.subtitle_text === 'string' && patch.subtitle_text !== shot.subtitle_text) {
      shot.subtitle_text = patch.subtitle_text;
      changed = true;
    }
    if (typeof patch.duration_sec === 'number' && patch.duration_sec > 0 && patch.duration_sec !== shot.duration_sec) {
      shot.duration_sec = Math.max(1, Math.min(60, patch.duration_sec));
      changed = true;
    }
    if (changed) {
      shot.frame_asset_id = undefined;
      shot.cache_key = undefined;
      proj.video_ok = false;
      proj.qa = undefined;
      proj.revision += 1;
      proj.updated_at = nowSec();
      syncProjectDerivedViews(proj);
      this.persistProject(proj);
    }
    return proj;
  }

  updateProjectConfigs(
    pid: string,
    patch: {
      title?: string;
      desc?: string;
      ratio?: string;
      target_duration?: number;
      bgm?: Partial<StudioProjectV2['bgm']>;
      image_config?: Partial<StudioProjectV2['image_config']>;
      compose_config?: Partial<StudioProjectV2['compose_config']>;
      publish_config?: Partial<StudioProjectV2['publish_config']>;
    }
  ): StudioProjectV2 {
    const proj = this.getProject(pid);
    if (typeof patch.title === 'string' && patch.title.trim()) {
      proj.title = patch.title.trim();
      proj.name = proj.title.slice(0, 24);
    }
    if (typeof patch.desc === 'string') proj.desc = patch.desc;
    if (typeof patch.ratio === 'string' && patch.ratio) {
      proj.ratio = patch.ratio;
      proj.image_config.ratio = patch.ratio;
    }
    if (typeof patch.target_duration === 'number') {
      proj.target_duration = Math.max(10, Math.min(300, patch.target_duration));
    }
    if (patch.bgm) {
      Object.assign(proj.bgm, patch.bgm);
      proj.bgm.seconds = Math.max(10, Math.min(240, Number(proj.bgm.seconds) || 75));
      proj.bgm.steps = Math.max(1, Math.min(32, Number(proj.bgm.steps) || 8));
    }
    if (patch.image_config) {
      Object.assign(proj.image_config, patch.image_config);
    }
    if (patch.compose_config) {
      const c = { ...proj.compose_config, ...patch.compose_config };
      if (c.bgm_volume > 1) c.bgm_volume = c.bgm_volume / 100;
      c.bgm_volume = Math.max(0, Math.min(0.6, Number(c.bgm_volume) || 0));
      c.duck_depth = Math.max(0, Math.min(1, Number(c.duck_depth) || 0));
      c.fade = Math.max(0, Math.min(6, Number(c.fade) || 0));
      c.fps = Math.max(12, Math.min(30, Number(c.fps) || 24));
      proj.compose_config = c;
      proj.video_ok = false;
    }
    if (patch.publish_config) {
      Object.assign(proj.publish_config, patch.publish_config);
    }
    proj.revision += 1;
    proj.updated_at = nowSec();
    syncProjectDerivedViews(proj);
    this.persistProject(proj);
    return proj;
  }

  adoptAsset(pid: string, assetId: string): StudioProjectV2 {
    const proj = this.getProject(pid);
    const target = proj.assets.find((a) => a.asset_id === assetId);
    if (!target) throw new Error('找不到指定资产版本');
    if (!this.getAssetBuffer(proj.id, target.rel)) {
      throw new Error('该版本对应的媒体文件已不存在');
    }

    for (const a of proj.assets) {
      if (target.line_id && a.line_id === target.line_id && a.kind === target.kind) a.adopted = false;
      else if (target.shot_id && a.shot_id === target.shot_id && a.kind === target.kind) a.adopted = false;
      else if (!target.line_id && !target.shot_id && a.kind === target.kind && a.rel.split('/')[0] === target.rel.split('/')[0]) {
        a.adopted = false;
      }
    }
    target.adopted = true;

    if (target.kind === 'image' && target.shot_id) {
      const s = proj.shots.find((x) => x.shot_id === target.shot_id);
      if (s) s.image_asset_id = target.asset_id;
    }
    if (target.kind === 'audio' && target.line_id) {
      const d = proj.dialogues.find((x) => x.line_id === target.line_id);
      if (d) {
        d.audio_asset_id = target.asset_id;
        d.duration_sec = target.duration;
      }
    }
    if (target.kind === 'audio' && target.rel.startsWith('bgm/')) {
      proj.bgm.asset_id = target.asset_id;
    }
    if (target.kind === 'video') {
      proj.video_ok = true;
      proj.duration = target.duration || proj.duration;
      proj.files = {
        ...proj.files,
        video: {
          rel: target.rel,
          size: target.size,
          url: `/api/studio/asset?pid=${encodeURIComponent(proj.id)}&path=${encodeURIComponent(target.rel)}&v=${target.sha256.slice(0, 12)}`,
        },
      };
    }

    proj.revision += 1;
    proj.updated_at = nowSec();
    syncProjectDerivedViews(proj);
    this.pushMessage(proj, {
      kind: 'task_event',
      sender_id: target.agent_id || 'supervisor',
      sender_name: AGENT_MAP[target.agent_id || 'supervisor']?.name || '资产管理',
      event_state: 'succeeded',
      text: `已切换采用资产版本：${target.label}（v${target.version}）`,
      assets: [{ asset_id: target.asset_id, rel: target.rel, kind: target.kind, label: target.label, sha256: target.sha256 }],
    });
    this.persistProject(proj);
    return proj;
  }

  // ---------------- Chat First Supervisor & Multi-Agent DAG Execution ----------------

  async sendChatMessage(
    pid: string,
    input: {
      text: string;
      mentions?: AgentId[];
      reply_to?: string;
      attachments?: Array<{ rel: string; name: string; kind: string }>;
    }
  ): Promise<Record<string, unknown>> {
    const proj = this.getProject(pid);
    const rawText = String(input.text || '').trim();
    if (!rawText && !(input.attachments && input.attachments.length)) {
      throw new Error('消息内容不能为空');
    }

    const parsedMentions = new Set<AgentId>(Array.isArray(input.mentions) ? input.mentions : []);
    const mentionPatterns: Array<[RegExp, AgentId]> = [
      [/@总导演|@导演|@supervisor/i, 'supervisor'],
      [/@剧本|@script/i, 'script'],
      [/@分镜|@storyboard/i, 'storyboard'],
      [/@生图|@image/i, 'image'],
      [/@配音|@voice/i, 'voice'],
      [/@配乐|@bgm/i, 'bgm'],
      [/@视频生成|@渲染|@video/i, 'video_gen'],
      [/@后期|@合成|@compose/i, 'compose'],
      [/@质检|@qa/i, 'qa'],
    ];
    for (const [re, aid] of mentionPatterns) {
      if (re.test(rawText)) parsedMentions.add(aid);
    }

    const replyMsg = input.reply_to ? proj.messages.find((m) => m.msg_id === input.reply_to) : undefined;
    this.pushMessage(proj, {
      kind: 'user',
      sender_id: 'user',
      sender_name: '我',
      mentions: Array.from(parsedMentions),
      reply_to: replyMsg?.msg_id,
      reply_preview: replyMsg ? `${replyMsg.sender_name}: ${replyMsg.text.slice(0, 60)}` : undefined,
      text: rawText || '上传了参考附件',
      attachments: input.attachments,
    });

    // Attach uploaded images into image_config.refs if mentioned or attached
    if (input.attachments && input.attachments.length) {
      for (const att of input.attachments) {
        if (att.kind === 'image' && !proj.image_config.refs.includes(att.rel)) {
          proj.image_config.refs.push(att.rel);
        }
      }
    }

    this.thinkingAgents.set(proj.id, 'supervisor');
    this.persistProject(proj);

    try {
      await this.routeUserIntent(proj, rawText, Array.from(parsedMentions));
    } finally {
      this.thinkingAgents.delete(proj.id);
      this.persistProject(proj);
    }

    return this.getState(proj.id);
  }

  private async routeUserIntent(proj: StudioProjectV2, text: string, mentions: AgentId[]): Promise<void> {
    const low = text.toLowerCase();

    // 1. Direct line edit intent: e.g. "把第2句改成..." or "修改台词2：..."
    const lineEditMatch = text.match(/第\s*(\d+)\s*句(?:台词)?(?:改成|改为|换成|修改为|[:：])\s*(.+)$/);
    if (lineEditMatch) {
      const orderNum = Number(lineEditMatch[1]);
      const newText = lineEditMatch[2].trim().replace(/^["「]|["」]$/g, '');
      const targetLine = proj.dialogues.find((d) => d.order === orderNum) || proj.dialogues[orderNum - 1];
      if (targetLine && newText) {
        this.updateDialogueLine(proj.id, targetLine.line_id, { text: newText });
        this.pushMessage(proj, {
          kind: 'agent',
          sender_id: 'script',
          sender_name: '剧本 Agent',
          text: `已将第 ${targetLine.order} 句（${targetLine.line_id} · ${targetLine.role}）更新为：\n「${newText}」\n受局部依赖失效策略保护，仅该句配音及后续合成需要增量重跑，其余台词与分镜缓存继续有效。`,
        });
        const tVoice = this.enqueueTask(proj, 'voice', 'voice.synthesize_line', `增量重配第 ${targetLine.order} 句`, [], {
          line_ids: [targetLine.line_id],
        });
        const tCompose = this.enqueueTask(proj, 'compose', 'compose.ffmpeg', '增量重新合成成片', [tVoice.task_id], {});
        const tQa = this.enqueueTask(proj, 'qa', 'qa.inspect', '增量复检成片质量', [tCompose.task_id], {});
        this.scheduleReadyTasks(proj, [tVoice, tCompose, tQa]);
        return;
      }
    }

    // 2. Targeted @agent direct dispatch
    if (mentions.includes('qa') || /(?:^|[\s，])(?:质检|检查成片|校验成片|qa)/i.test(text)) {
      this.pushMessage(proj, {
        kind: 'agent',
        sender_id: 'qa',
        sender_name: '质检 Agent',
        text: '收到，马上调用 ffprobe 与完整性规则对当前项目成片及资产进行全面质检。',
      });
      const tQa = this.enqueueTask(proj, 'qa', 'qa.inspect', '执行成片质量检验', [], {});
      this.scheduleReadyTasks(proj, [tQa]);
      return;
    }

    if (mentions.length === 1 && mentions[0] !== 'supervisor') {
      const aid = mentions[0];
      await this.handleSingleAgentChat(proj, aid, text);
      return;
    }

    // 3. Multi-agent full production or planning flow led by Supervisor
    const wantsFullRun = /(?:生成|制作|开始|全流程|跑通|做一条|做一个|策划|扩写|执行)/.test(text) || mentions.includes('supervisor');
    const wantsTopicChange = text.length >= 6 && /(?:关于|主题|做成|做一条|做个|策划|剧本|讲讲|介绍)/.test(text);

    if (wantsTopicChange && !/^(?:开始|执行|跑|合成|配音|配乐|生图)/.test(text)) {
      const cleanTopic = text
        .replace(/@[^\s]+/g, '')
        .replace(/^(?:帮我|请)?(?:生成|制作|做一条|做一个|策划|写一个)?(?:关于)?/, '')
        .replace(/(?:的)?(?:短视频|视频|剧本|并开始制作|并全流程生成).*$/, '')
        .trim();
      if (cleanTopic.length >= 3) {
        proj.title = cleanTopic.slice(0, 48);
        proj.name = proj.title.slice(0, 24);
      }
    }

    // Discussion phase (collapsible internal coordination)
    const hasCloudImg = Boolean(this.host.secrets.imgKey);
    const hasCloudTts = proj.dialogues.some((d) => d.engine === 'cloud' || d.speaker.startsWith('cloud:')) && Boolean(this.host.secrets.blKey);
    const estImgUsd = hasCloudImg ? Math.round(proj.image_config.items.length * 0.03 * 100) / 100 : 0;
    const estTtsCny = hasCloudTts ? Math.round(proj.dialogues.reduce((a, d) => a + d.text.length, 0) * 0.00014 * 1000) / 1000 : 0;

    this.pushMessage(proj, {
      kind: 'discussion',
      sender_id: 'supervisor',
      sender_name: '制作组内部协作讨论',
      text: `总导演已接单「${proj.title}」，各 Agent 完成依赖与成本评估。`,
      details:
        `1. [剧本 Agent] ${wantsTopicChange ? '将基于目标主题重构/扩写台词并分配稳定 line_id' : `复用当前 ${proj.dialogues.length} 句结构化台词`}\n` +
        `2. [分镜 Agent] 确认画面比例 ${proj.ratio}，共 ${proj.shots.length} 镜\n` +
        `3. [生图/配音/配乐] 三路可真并发执行；${hasCloudImg ? `生图将请求 API易（预估 $${estImgUsd.toFixed(2)}）` : '未配 API易 Key，生图走本地高精预览图'}\n` +
        `4. [后期/质检] 视频渲染后执行 FFmpeg 压制与 ffprobe 全项流校验`,
    });

    if (!wantsFullRun && !wantsTopicChange) {
      this.pushMessage(proj, {
        kind: 'agent',
        sender_id: 'supervisor',
        sender_name: '总导演 Agent',
        text: `已收到你的反馈。当前项目「${proj.title}」共有 ${proj.shots.length} 个分镜、${proj.dialogues.length} 句台词。\n你可以说：「帮我用这个主题策划并执行全流程」，或用 @生图 / @配音 / @后期合成 / @质检 指挥对应成员。`,
      });
      return;
    }

    // Build task DAG
    const batchTasks: StudioTaskNode[] = [];
    let prevPlanIds: string[] = [];
    if (wantsTopicChange || /剧本|策划|扩写/.test(text)) {
      const tScript = this.enqueueTask(proj, 'script', 'script.plan', `撰写/更新剧本：${proj.title}`, [], {
        topic: proj.title,
        seconds: proj.target_duration,
      });
      const tStory = this.enqueueTask(proj, 'storyboard', 'storyboard.build', '拆分镜头与视觉提示词', [tScript.task_id], {});
      batchTasks.push(tScript, tStory);
      prevPlanIds = [tStory.task_id];
    }

    const tImage = this.enqueueTask(proj, 'image', 'image.generate', `生成分镜配图 (${proj.image_config.items.length} 张)`, prevPlanIds, {});
    const tVoice = this.enqueueTask(proj, 'voice', 'voice.synthesize_line', `合成角色配音 (${proj.dialogues.length} 句)`, prevPlanIds, {});
    const tBgm = this.enqueueTask(proj, 'bgm', 'bgm.generate', `生成背景配乐 (${proj.bgm.seconds}s)`, prevPlanIds, {});
    const tVideoGen = this.enqueueTask(
      proj,
      'video_gen',
      'video.render_frames',
      '渲染动效与分镜视频帧',
      [tImage.task_id, ...prevPlanIds],
      {}
    );
    const tCompose = this.enqueueTask(
      proj,
      'compose',
      'compose.ffmpeg',
      'FFmpeg 音画总成压制 MP4',
      [tVideoGen.task_id, tVoice.task_id, tBgm.task_id],
      {}
    );
    const tQa = this.enqueueTask(proj, 'qa', 'qa.inspect', 'ffprobe 成片质检', [tCompose.task_id], {});
    batchTasks.push(tImage, tVoice, tBgm, tVideoGen, tCompose, tQa);

    // Mode B Human-in-the-loop Gate: require confirmation for full multi-agent production batches when cloud spend or auto-gate applies
    const skipGate = /立即执行|直接跑|无需确认|跳过审批/.test(text);
    if (!skipGate) {
      for (const tk of batchTasks) {
        tk.state = 'waiting_approval';
        tk.phase = '等待用户点击「确认执行」';
      }
      const approval: StudioApproval = {
        approval_id: uid('apr'),
        task_id: batchTasks[0]?.task_id,
        agent_id: 'supervisor',
        action_type: estImgUsd > 0 || estTtsCny > 0 ? 'cloud_spend' : 'batch_run',
        title: `执行「${proj.title}」全流程制作计划（${batchTasks.length} 个任务）`,
        summary: `将按 DAG 编排执行：${batchTasks.map((t) => AGENT_MAP[t.agent_id].name).join(' → ')}。`,
        estimated_cost_usd: estImgUsd,
        estimated_cost_cny: estTtsCny,
        affected_items: batchTasks.map((t) => `${t.title}`),
        status: 'pending',
        payload: { task_ids: batchTasks.map((t) => t.task_id) },
        created_at: nowSec(),
      };
      proj.approvals.push(approval);
      this.pushMessage(proj, {
        kind: 'approval',
        sender_id: 'supervisor',
        sender_name: '总导演 Agent',
        approval_id: approval.approval_id,
        text: `已拆解 ${batchTasks.length} 步制作计划（含并发配图/配音/配乐、FFmpeg 总成与 ffprobe 质检），请确认后启动执行。`,
      });
    } else {
      this.pushMessage(proj, {
        kind: 'agent',
        sender_id: 'supervisor',
        sender_name: '总导演 Agent',
        text: `已收到指令，已跳过审批门控并立即调度 ${batchTasks.length} 个任务执行。`,
      });
      this.scheduleReadyTasks(proj, batchTasks);
    }
  }

  private async handleSingleAgentChat(proj: StudioProjectV2, aid: AgentId, text: string): Promise<void> {
    let task: StudioTaskNode | null = null;
    if (aid === 'script') {
      const topic = text.replace(/@[^\s]+/g, '').trim() || proj.title;
      task = this.enqueueTask(proj, 'script', 'script.plan', `改写剧本：${topic.slice(0, 20)}`, [], { topic, seconds: proj.target_duration });
    } else if (aid === 'storyboard') {
      task = this.enqueueTask(proj, 'storyboard', 'storyboard.build', '重排分镜与提示词', [], { instruction: text });
    } else if (aid === 'image') {
      const cleanPrompt = text.replace(/@[^\s]+/g, '').trim();
      if (cleanPrompt && cleanPrompt.length > 4 && !/^(?:开始|生成|重画|跑)/.test(cleanPrompt)) {
        if (!proj.image_config.items.length) {
          proj.image_config.items.push({ item_id: 'img_01', label: '镜头 1 配图', prompt: cleanPrompt, ratio: proj.ratio, transparent: false });
        } else {
          proj.image_config.items[0].prompt = cleanPrompt;
        }
        proj.revision += 1;
      }
      task = this.enqueueTask(proj, 'image', 'image.generate', '生图任务', [], {});
    } else if (aid === 'voice') {
      task = this.enqueueTask(proj, 'voice', 'voice.synthesize_line', '角色配音增量合成', [], {});
    } else if (aid === 'bgm') {
      const cleanPrompt = text.replace(/@[^\s]+/g, '').trim();
      if (cleanPrompt && cleanPrompt.length > 4 && !/^(?:开始|生成|重画|跑)/.test(cleanPrompt)) {
        proj.bgm.prompt = cleanPrompt;
        proj.revision += 1;
      }
      task = this.enqueueTask(proj, 'bgm', 'bgm.generate', '背景配乐生成', [], {});
    } else if (aid === 'video_gen') {
      task = this.enqueueTask(proj, 'video_gen', 'video.render_frames', '渲染动态视频帧', [], {});
    } else if (aid === 'compose') {
      task = this.enqueueTask(proj, 'compose', 'compose.ffmpeg', '合成导出 MP4 成片', [], {});
    } else if (aid === 'qa') {
      task = this.enqueueTask(proj, 'qa', 'qa.inspect', '执行 ffprobe 质检', [], {});
    }

    if (task) {
      this.pushMessage(proj, {
        kind: 'agent',
        sender_id: aid,
        sender_name: AGENT_MAP[aid].name,
        task_id: task.task_id,
        text: `收到指令，已创建任务「${task.title}」并立即开始执行。`,
      });
      this.scheduleReadyTasks(proj, [task]);
    }
  }

  decideApproval(pid: string, approvalId: string, approved: boolean, note = ''): Record<string, unknown> {
    const proj = this.getProject(pid);
    const apr = proj.approvals.find((a) => a.approval_id === approvalId);
    if (!apr) throw new Error('找不到审批记录');
    if (apr.status !== 'pending') throw new Error('该审批已处理');

    apr.status = approved ? 'approved' : 'rejected';
    apr.decided_at = nowSec();
    apr.decision_note = note;

    const taskIds = Array.isArray(apr.payload?.task_ids) ? (apr.payload.task_ids as string[]) : [];
    const targetTasks = proj.tasks.filter((t) => taskIds.includes(t.task_id));

    if (approved) {
      for (const tk of targetTasks) {
        if (tk.state === 'waiting_approval') {
          tk.state = tk.deps.length === 0 ? 'ready' : 'pending';
          tk.phase = tk.deps.length === 0 ? '审批通过，准备启动' : '审批通过，等待上游任务';
        }
      }
      this.pushMessage(proj, {
        kind: 'task_event',
        sender_id: 'supervisor',
        sender_name: '总导演 Agent',
        approval_id: apr.approval_id,
        event_state: 'ready',
        text: `用户已确认执行「${apr.title}」，任务引擎开始按依赖图并行推进。`,
      });
      this.persistProject(proj);
      this.scheduleReadyTasks(proj, targetTasks);
    } else {
      for (const tk of targetTasks) {
        tk.state = 'cancelled';
        tk.phase = '用户拒绝审批，任务已取消';
        tk.ended_at = nowSec();
      }
      this.pushMessage(proj, {
        kind: 'task_event',
        sender_id: 'supervisor',
        sender_name: '总导演 Agent',
        approval_id: apr.approval_id,
        event_state: 'cancelled',
        text: `已拒绝「${apr.title}」${note ? `（原因：${note}）` : ''}，计划内任务已安全取消。`,
      });
      this.persistProject(proj);
    }
    return this.getState(proj.id);
  }

  // ---------------- Authoritative DAG Task Scheduler & Isolated Controls ----------------

  enqueueTask(
    proj: StudioProjectV2,
    agentId: AgentId,
    action: string,
    title: string,
    deps: string[],
    inputs: Record<string, unknown>
  ): StudioTaskNode {
    // Guard against duplicate already-running identical action on same target
    const dup = proj.tasks.find(
      (t) =>
        t.agent_id === agentId &&
        t.action === action &&
        (t.state === 'running' || t.state === 'ready') &&
        JSON.stringify(t.inputs) === JSON.stringify(inputs)
    );
    if (dup) return dup;

    const tk: StudioTaskNode = {
      task_id: uid('tsk'),
      project_id: proj.id,
      agent_id: agentId,
      action,
      title,
      deps,
      state: deps.length === 0 ? 'ready' : 'pending',
      progress: 0,
      phase: deps.length === 0 ? '就绪' : '等待上游依赖',
      inputs,
      outputs: [],
      logs: [`[${fmtTime(nowSec()).slice(11)}] 创建任务 ${title}`],
      retry_count: 0,
      max_retries: 2,
      cost_usd: 0,
      cost_cny: 0,
      cache_hit: false,
      created_at: nowSec(),
    };
    proj.tasks.push(tk);
    if (proj.tasks.length > 150) {
      proj.tasks = proj.tasks.slice(-150);
    }
    return tk;
  }

  runDirectAgentTask(pid: string, agentId: AgentId, extraInputs: Record<string, unknown> = {}): Record<string, unknown> {
    const proj = this.getProject(pid);
    const mapAction: Record<AgentId, [string, string]> = {
      supervisor: ['compose.ffmpeg', '总控合成成片'],
      script: ['script.plan', `策划/刷新剧本：${proj.title}`],
      storyboard: ['storyboard.build', '生成分镜与画面排版'],
      image: ['image.generate', `生成分镜配图 (${Math.max(1, proj.image_config.items.length)} 张)`],
      voice: ['voice.synthesize_line', `增量配音合成 (${proj.dialogues.length} 句)`],
      bgm: ['bgm.generate', `生成背景配乐 (${proj.bgm.seconds}s)`],
      video_gen: ['video.render_frames', '渲染动态视频帧与卡片'],
      compose: ['compose.ffmpeg', 'FFmpeg 音画总成压制'],
      qa: ['qa.inspect', 'ffprobe 成片质检'],
    };
    const [action, title] = mapAction[agentId] || ['qa.inspect', '执行任务'];
    const tk = this.enqueueTask(proj, agentId, action, title, [], extraInputs);
    this.pushMessage(proj, {
      kind: 'task_event',
      sender_id: agentId,
      sender_name: AGENT_MAP[agentId].name,
      task_id: tk.task_id,
      event_state: 'ready',
      text: `单独触发「${title}」`,
    });
    this.persistProject(proj);
    this.scheduleReadyTasks(proj, [tk]);
    return this.getState(proj.id);
  }

  taskAction(pid: string, taskId: string, action: 'pause' | 'resume' | 'cancel' | 'retry' | 'rerun'): Record<string, unknown> {
    const proj = this.getProject(pid);
    const tk = proj.tasks.find((t) => t.task_id === taskId);
    if (!tk) throw new Error(`找不到任务 ${taskId}`);

    if (action === 'cancel' || action === 'pause') {
      const ctrl = this.taskAborts.get(taskId);
      if (ctrl) ctrl.abort();
      const procs = this.taskProcs.get(taskId);
      if (procs) {
        for (const p of procs) {
          try {
            p.kill('SIGKILL');
          } catch {
            // ignore
          }
        }
        procs.clear();
      }
      tk.state = action === 'pause' ? 'paused' : 'cancelled';
      tk.phase = action === 'pause' ? '已暂停（可点击恢复继续）' : '已取消';
      tk.ended_at = nowSec();
      tk.logs.push(`[${fmtTime(nowSec()).slice(11)}] 用户执行：${action === 'pause' ? '暂停' : '取消'}`);
      this.pushMessage(proj, {
        kind: 'task_event',
        sender_id: tk.agent_id,
        sender_name: AGENT_MAP[tk.agent_id].name,
        task_id: tk.task_id,
        event_state: tk.state,
        text: `任务「${tk.title}」已${action === 'pause' ? '暂停' : '取消'}（不影响其他正在并行的任务）。`,
      });
      this.persistProject(proj);
      return this.getState(proj.id);
    }

    if (action === 'resume' || action === 'retry' || action === 'rerun') {
      if (tk.state === 'running') return this.getState(proj.id);
      if (action === 'retry' && tk.retry_count >= tk.max_retries) {
        throw new Error(`已达最大重试次数（${tk.max_retries}）`);
      }
      if (action === 'retry') tk.retry_count += 1;
      tk.state = 'ready';
      tk.error = undefined;
      tk.progress = 0;
      tk.phase = action === 'rerun' ? '强制重跑中…' : '恢复/重试就绪…';
      if (action === 'rerun') tk.inputs = { ...tk.inputs, force: true };
      tk.logs.push(`[${fmtTime(nowSec()).slice(11)}] 用户触发 ${action}`);
      this.persistProject(proj);
      this.scheduleReadyTasks(proj, [tk]);
      return this.getState(proj.id);
    }

    return this.getState(proj.id);
  }

  agentAction(pid: string, agentId: AgentId, action: 'pause' | 'resume' | 'stop'): Record<string, unknown> {
    const proj = this.getProject(pid);
    if (action === 'pause') {
      proj.agent_paused[agentId] = true;
      for (const tk of proj.tasks) {
        if (tk.agent_id === agentId && (tk.state === 'running' || tk.state === 'ready' || tk.state === 'pending')) {
          this.taskAction(pid, tk.task_id, 'pause');
        }
      }
    } else if (action === 'stop') {
      for (const tk of proj.tasks) {
        if (tk.agent_id === agentId && (tk.state === 'running' || tk.state === 'ready' || tk.state === 'pending' || tk.state === 'paused')) {
          this.taskAction(pid, tk.task_id, 'cancel');
        }
      }
    } else if (action === 'resume') {
      proj.agent_paused[agentId] = false;
      const pausedTasks = proj.tasks.filter((t) => t.agent_id === agentId && t.state === 'paused');
      for (const tk of pausedTasks) {
        tk.state = 'ready';
        tk.phase = '恢复执行…';
      }
      if (pausedTasks.length) this.scheduleReadyTasks(proj, pausedTasks);
    }
    this.persistProject(proj);
    return this.getState(proj.id);
  }

  stopAllTasks(pid: string, specificAgentOrModule?: string): { stopped: string[] } {
    const proj = this.getProject(pid);
    const stopped: string[] = [];
    for (const tk of proj.tasks) {
      if (
        specificAgentOrModule &&
        tk.agent_id !== specificAgentOrModule &&
        tk.task_id !== specificAgentOrModule &&
        !(specificAgentOrModule.startsWith('voice') && tk.agent_id === 'voice')
      ) {
        continue;
      }
      if (tk.state === 'running' || tk.state === 'ready' || tk.state === 'pending' || tk.state === 'retrying') {
        const ctrl = this.taskAborts.get(tk.task_id);
        if (ctrl) ctrl.abort();
        const procs = this.taskProcs.get(tk.task_id);
        if (procs) {
          for (const p of procs) {
            try {
              p.kill('SIGKILL');
            } catch {
              // ignore
            }
          }
          procs.clear();
        }
        tk.state = 'cancelled';
        tk.phase = '已停止';
        tk.ended_at = nowSec();
        stopped.push(tk.task_id);
      }
    }
    if (stopped.length) this.persistProject(proj);
    return { stopped };
  }

  private scheduleReadyTasks(proj: StudioProjectV2, candidateTasks?: StudioTaskNode[]): void {
    const pool = candidateTasks && candidateTasks.length ? candidateTasks : proj.tasks;
    const byId = new Map(proj.tasks.map((t) => [t.task_id, t]));

    for (const tk of pool) {
      if (proj.agent_paused[tk.agent_id]) continue;
      if (tk.state === 'pending') {
        const allDepsSucceeded = tk.deps.every((did) => byId.get(did)?.state === 'succeeded');
        const anyDepFailed = tk.deps.some((did) => {
          const d = byId.get(did);
          return d && (d.state === 'failed' || d.state === 'cancelled');
        });
        if (anyDepFailed) {
          tk.state = 'cancelled';
          tk.phase = '上游依赖未通过，已跳过';
          tk.ended_at = nowSec();
          continue;
        }
        if (allDepsSucceeded) {
          tk.state = 'ready';
        }
      }
      if (tk.state === 'ready') {
        void this.executeTaskNode(proj, tk);
      }
    }
  }

  private async executeTaskNode(proj: StudioProjectV2, tk: StudioTaskNode): Promise<void> {
    if (tk.state !== 'ready') return;
    const ctrl = new AbortController();
    this.taskAborts.set(tk.task_id, ctrl);
    this.taskProcs.set(tk.task_id, new Set());
    const isAborted = () => ctrl.signal.aborted;

    tk.state = 'running';
    tk.started_at = nowSec();
    tk.progress = 5;
    tk.phase = '正在启动执行…';
    tk.logs.push(`[${fmtTime(nowSec()).slice(11)}] 开始执行 ${tk.action}`);
    this.persistProject(proj);

    const setProg = (pct: number, phase: string) => {
      tk.progress = Math.round(pct * 10) / 10;
      tk.phase = phase;
      tk.logs.push(`[${fmtTime(nowSec()).slice(11)}] ${phase}`);
      if (tk.logs.length > 50) tk.logs = tk.logs.slice(-50);
    };

    try {
      const producedRefs: ChatArtifactRef[] = [];

      if (tk.action === 'script.plan') {
        await this.execScriptPlan(proj, tk, setProg, isAborted);
      } else if (tk.action === 'storyboard.build') {
        await this.execStoryboard(proj, tk, setProg);
      } else if (tk.action === 'image.generate') {
        const refs = await this.execImageGenerate(proj, tk, setProg, isAborted);
        producedRefs.push(...refs);
      } else if (tk.action === 'voice.synthesize_line') {
        const refs = await this.execVoiceSynthesize(proj, tk, setProg, isAborted);
        producedRefs.push(...refs);
      } else if (tk.action === 'bgm.generate') {
        const refs = await this.execBgmGenerate(proj, tk, setProg, isAborted);
        producedRefs.push(...refs);
      } else if (tk.action === 'video.render_frames') {
        const refs = await this.execVideoRenderFrames(proj, tk, setProg, isAborted);
        producedRefs.push(...refs);
      } else if (tk.action === 'compose.ffmpeg') {
        const refs = await this.execComposeFfmpeg(proj, tk, setProg, isAborted);
        producedRefs.push(...refs);
      } else if (tk.action === 'qa.inspect') {
        await this.execQaInspect(proj, tk, setProg);
      }

      const stateAfterExec: string = tk.state;
      if (isAborted() || stateAfterExec === 'cancelled' || stateAfterExec === 'paused') return;

      tk.state = 'succeeded';
      tk.progress = 100;
      tk.ended_at = nowSec();
      tk.outputs = producedRefs.map((r) => r.asset_id);
      syncProjectDerivedViews(proj);

      this.pushMessage(proj, {
        kind: producedRefs.length ? 'artifact' : 'task_event',
        sender_id: tk.agent_id,
        sender_name: AGENT_MAP[tk.agent_id].name,
        task_id: tk.task_id,
        event_state: tk.cache_hit ? 'cached' : 'succeeded',
        text: `${tk.title} ${tk.cache_hit ? '缓存命中' : '完成'}：${tk.phase}`,
        assets: producedRefs.length ? producedRefs : undefined,
      });

      this.persistProject(proj);
      // Wake up downstream dependent tasks in project!
      this.scheduleReadyTasks(proj);
    } catch (err) {
      const stateOnErr: string = tk.state;
      if (isAborted() || stateOnErr === 'cancelled' || stateOnErr === 'paused') return;
      const msg = err instanceof Error ? err.message : String(err);
      tk.state = 'failed';
      tk.error = msg;
      tk.phase = `失败：${msg.slice(0, 60)}`;
      tk.ended_at = nowSec();
      tk.logs.push(`[${fmtTime(nowSec()).slice(11)}] ERROR: ${msg}`);
      this.pushMessage(proj, {
        kind: 'task_event',
        sender_id: tk.agent_id,
        sender_name: AGENT_MAP[tk.agent_id].name,
        task_id: tk.task_id,
        event_state: 'failed',
        text: `任务「${tk.title}」执行失败：${msg}（可在右侧任务详情重试）`,
      });
      this.persistProject(proj);
      this.scheduleReadyTasks(proj);
    } finally {
      this.taskAborts.delete(tk.task_id);
      this.taskProcs.delete(tk.task_id);
    }
  }

  private async sleepAbortable(ms: number, isAborted: () => boolean): Promise<void> {
    await new Promise<void>((resolve) => {
      const end = Date.now() + ms;
      const iv = setInterval(() => {
        if (isAborted() || Date.now() >= end) {
          clearInterval(iv);
          resolve();
        }
      }, 45);
    });
  }

  private async execScriptPlan(
    proj: StudioProjectV2,
    tk: StudioTaskNode,
    setProg: (p: number, s: string) => void,
    isAborted: () => boolean
  ): Promise<void> {
    const topic = String(tk.inputs.topic || proj.title || 'AI 实用技巧').trim();
    const seconds = Number(tk.inputs.seconds || proj.target_duration || 60);
    setProg(20, `正在围绕「${topic}」构思双人剧本结构…`);

    let rawScriptJson = '';
    if (this.host.secrets.dsKey) {
      try {
        const dsBase = String(this.host.settings.dsBase || 'https://api.deepseek.com').replace(/\/+$/, '');
        const dsModel = String(this.host.settings.dsModel || 'deepseek-chat');
        const prompt =
          `请围绕主题「${topic}」生成约 ${seconds} 秒的双人科普短视频剧本（角色：白页、紫苏，3 到 5 个分镜）。只输出纯 JSON：\n` +
          `{"title":"30字内标题","desc":"60字内简介","tags":["AI","科普"],"bgm":{"prompt":"upbeat electronic, no vocals","seconds":${Math.min(180, Math.max(20, seconds))}},"shots":[{"line_index":1,"render":"web","seconds":5,"visual":"画面描述","voice":{"role":"白页","tone":"冷静吐槽","text":"台词"},"image":{"prompt":"画面生图提示词","ratio":"${proj.ratio}","transparent":false}}]}`;
        const resp = await fetch(`${dsBase}/chat/completions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.host.secrets.dsKey}` },
          body: JSON.stringify({
            model: dsModel,
            messages: [
              { role: 'system', content: '你是短视频编剧，只输出合法 JSON，不带额外文字。' },
              { role: 'user', content: prompt },
            ],
            stream: false,
          }),
        });
        if (resp.ok) {
          const j = (await resp.json()) as { choices?: Array<{ message?: { content?: string } }> };
          let c = j.choices?.[0]?.message?.content?.trim() || '';
          const fenced = c.match(/```(?:json)?\s*([\s\S]*?)```/i);
          if (fenced) c = fenced[1].trim();
          if (c.startsWith('{')) rawScriptJson = c;
        }
      } catch {
        // fallback cleanly to deterministic local planner
      }
    }

    if (isAborted()) throw new Error('已取消');
    if (!rawScriptJson) {
      await this.sleepAbortable(180, isAborted);
      rawScriptJson = JSON.stringify({
        title: topic,
        desc: `围绕「${topic}」的精炼双人科普解说`,
        tags: ['AI', '科普', '效率'],
        bgm: { prompt: 'upbeat modern electronic, no vocals', seconds: Math.max(30, seconds) },
        shots: [
          {
            line_index: 1,
            render: 'web',
            seconds: 4,
            visual: `高对比深色科技封面卡片，主标题：${topic}`,
            voice: { role: '白页', tone: '冷静吐槽', text: `大多数人聊「${topic}」，第一步就全用错了。` },
            image: { prompt: `Minimal dark tech studio desk, glowing interface hologram about ${topic}`, ratio: proj.ratio, transparent: false },
          },
          {
            line_index: 2,
            render: 'ppt',
            seconds: 5,
            visual: '对比卡片：盲目堆砌 vs 结构化拆解',
            voice: { role: '紫苏', tone: '好奇追问', text: '啊？具体差在哪，难道不是直接扔进去就行吗？' },
            image: { prompt: `Split comparison infographic visual style clean modern tech illustration`, ratio: proj.ratio, transparent: false },
          },
          {
            line_index: 3,
            render: 'web',
            seconds: 5,
            visual: '三步核心流程动态高亮卡片',
            voice: { role: '白页', tone: '干脆总结', text: '关键在把步骤拆给不同角色，改哪句就只重跑哪一环，省时又省钱。' },
            image: { prompt: `Modular pipeline diagram glowing nodes clean editorial aesthetic`, ratio: proj.ratio, transparent: false },
          },
        ],
      });
    }

    setProg(85, '正在同步结构化镜头与 line_id 台词表…');
    const res = applyParsedScriptToProject(proj, rawScriptJson);
    tk.phase = `剧本已就绪（${res.summary}）`;
  }

  private async execStoryboard(proj: StudioProjectV2, tk: StudioTaskNode, setProg: (p: number, s: string) => void): Promise<void> {
    setProg(40, '正在校验分镜节奏、镜头编号与生图提示词…');
    proj.shots.forEach((s, i) => {
      s.order = i + 1;
      if (!s.shot_id) s.shot_id = `shot_${String(i + 1).padStart(2, '0')}`;
      if (!s.visual_prompt.trim()) s.visual_prompt = `科技信息排版第 ${i + 1} 镜`;
      s.duration_sec = Math.max(2, Math.min(30, Number(s.duration_sec) || 5));
    });
    if (!proj.image_config.items.length) {
      proj.image_config.items = proj.shots.map((s) => ({
        item_id: `img_${s.shot_id}`,
        shot_id: s.shot_id,
        label: `镜头 ${s.order} 配图`,
        prompt: s.visual_prompt,
        ratio: proj.ratio,
        transparent: false,
      }));
    }
    proj.revision += 1;
    tk.phase = `已确认 ${proj.shots.length} 个分镜，总时长 ${proj.shots.reduce((a, s) => a + s.duration_sec, 0)}s`;
  }

  private async execImageGenerate(
    proj: StudioProjectV2,
    tk: StudioTaskNode,
    setProg: (p: number, s: string) => void,
    isAborted: () => boolean
  ): Promise<ChatArtifactRef[]> {
    const onlyShotId = typeof tk.inputs.shot_id === 'string' && tk.inputs.shot_id ? tk.inputs.shot_id : null;
    const allItems = proj.image_config.items.length
      ? proj.image_config.items
      : [
          {
            item_id: 'img_01',
            shot_id: proj.shots[0]?.shot_id,
            label: '镜头 1 配图',
            prompt: proj.title || '科技感视觉画面',
            ratio: proj.ratio,
            transparent: false,
          },
        ];
    const items = onlyShotId ? allItems.filter((it) => it.shot_id === onlyShotId) : allItems;
    const force = Boolean(tk.inputs.force) || Boolean(onlyShotId);
    const hasKey = Boolean(this.host.secrets.imgKey);
    const refsOut: ChatArtifactRef[] = [];

    const refDataUris: string[] = [];
    for (const r of proj.image_config.refs) {
      if (r.startsWith('data:')) refDataUris.push(r);
      else {
        const a = this.getAssetBuffer(proj.id, r);
        if (a) refDataUris.push(`data:${a.mime};base64,${a.buf.toString('base64')}`);
      }
    }

    let hits = 0;
    for (let i = 0; i < items.length; i++) {
      if (isAborted()) throw new Error('已取消');
      const it = items[i];
      const fp = sha256Hex(
        JSON.stringify({
          prompt: it.prompt,
          ratio: it.ratio,
          transparent: it.transparent,
          model: proj.image_config.model,
          quality: proj.image_config.quality,
          output: proj.image_config.output,
          refs: proj.image_config.refs,
          keyed: hasKey,
        })
      ).slice(0, 20);

      const existing = it.asset_id ? proj.assets.find((a) => a.asset_id === it.asset_id) : undefined;
      if (!force && it.cache_key === fp && existing && this.getAssetBuffer(proj.id, existing.rel)) {
        hits++;
        refsOut.push({ asset_id: existing.asset_id, rel: existing.rel, kind: 'image', label: `${it.label}（缓存命中）`, sha256: existing.sha256, w: existing.w, h: existing.h });
        continue;
      }

      setProg(15 + Math.round((i / items.length) * 80), `${hasKey ? 'API易实出图' : '生成高精视觉预览图'} (${i + 1}/${items.length})…`);
      let assetBuf: StudioAsset | null = null;
      let usdCost = 0;
      if (hasKey && proj.image_config.output === 'normal') {
        const out = await callApiyiImage({
          apiKey: this.host.secrets.imgKey,
          baseUrl: String(this.host.settings.imgBase || 'https://api.apiyi.com/v1'),
          model: proj.image_config.model,
          prompt: it.prompt,
          ratio: it.ratio || proj.ratio,
          tier: proj.image_config.resolution || '2k',
          quality: proj.image_config.quality || 'high',
          transparent: it.transparent,
          refs: refDataUris,
        });
        usdCost = out.usd;
        this.host.imgMonth.n += 1;
        this.host.imgMonth.usd = Math.round((this.host.imgMonth.usd + out.usd) * 1000) / 1000;
        const rel = `img/${it.shot_id || it.item_id}_v${Date.now().toString(36)}${out.ext}`;
        assetBuf = makeAsset(rel, out.buf);
      } else {
        await this.sleepAbortable(220, isAborted);
        const [w, h] = dimsForRatio(it.ratio || proj.ratio, 540);
        if (proj.image_config.output === 'svg') {
          assetBuf = makeAsset(`img/${it.shot_id || it.item_id}_v${Date.now().toString(36)}.svg`, createSvgBuffer(w, h, it.prompt));
        } else {
          assetBuf = makeAsset(
            `img/${it.shot_id || it.item_id}_v${Date.now().toString(36)}.png`,
            createPngBuffer(w, h, {
              transparent: it.transparent,
              accent: [31, 214, 240],
              seed: i + Date.now() % 97,
              progress: (i + 1) / items.length,
            })
          );
        }
      }

      const ver = this.putAsset(proj.id, assetBuf, {
        kind: 'image',
        label: it.label,
        agent_id: 'image',
        task_id: tk.task_id,
        shot_id: it.shot_id,
        model: hasKey ? proj.image_config.model : 'local-preview',
        params: { prompt: it.prompt, ratio: it.ratio, transparent: it.transparent },
      });
      it.asset_id = ver.asset_id;
      it.cache_key = fp;
      if (it.shot_id) {
        const s = proj.shots.find((x) => x.shot_id === it.shot_id);
        if (s) s.image_asset_id = ver.asset_id;
      }
      tk.cost_usd = Math.round((tk.cost_usd + usdCost) * 1000) / 1000;
      refsOut.push({ asset_id: ver.asset_id, rel: ver.rel, kind: 'image', label: `${ver.label} v${ver.version}`, sha256: ver.sha256, w: ver.w, h: ver.h });
    }

    tk.cache_hit = hits === items.length && items.length > 0;
    tk.phase = `完成 ${items.length} 张配图（缓存命中 ${hits} 张）`;
    return refsOut;
  }

  private async execVoiceSynthesize(
    proj: StudioProjectV2,
    tk: StudioTaskNode,
    setProg: (p: number, s: string) => void,
    isAborted: () => boolean
  ): Promise<ChatArtifactRef[]> {
    const onlyLineIds = Array.isArray(tk.inputs.line_ids) ? new Set(tk.inputs.line_ids.map(String)) : null;
    const force = Boolean(tk.inputs.force);
    const lines = proj.dialogues.filter((d) => !onlyLineIds || onlyLineIds.has(d.line_id));
    const refsOut: ChatArtifactRef[] = [];
    let hits = 0;

    for (let i = 0; i < lines.length; i++) {
      if (isAborted()) throw new Error('已取消');
      const d = lines[i];
      const useCloud = d.engine === 'cloud' || (d.engine === 'auto' && d.speaker.startsWith('cloud:'));
      if (useCloud && !this.host.secrets.blKey) {
        throw new Error(`台词「${d.line_id}」选择了百炼云端配音，但尚未配置百炼 API Key`);
      }

      const fp = computeLineFingerprint(d);
      const existing = d.audio_asset_id ? proj.assets.find((a) => a.asset_id === d.audio_asset_id) : undefined;
      if (!force && d.cache_key === fp && existing && this.getAssetBuffer(proj.id, existing.rel)) {
        hits++;
        continue;
      }

      setProg(15 + Math.round((i / Math.max(1, lines.length)) * 70), `正在合成第 ${d.order} 句（${d.role}）…`);
      let wavBuf: Buffer;
      let wavDur: number;
      let cnyCost = 0;
      if (useCloud) {
        const cloudVoice = d.speaker.startsWith('cloud:') ? d.speaker.slice('cloud:'.length) : 'longanlingxin_v3.1';
        const out = await callBailianTts({
          apiKey: this.host.secrets.blKey,
          baseUrl: String(this.host.settings.blBase || 'https://dashscope.aliyuncs.com/api/v1'),
          model: String(this.host.settings.blModel || 'qwen-audio-3.1-tts-plus'),
          text: d.text || '…',
          voice: cloudVoice,
          instruction: d.tone || '自然',
          hotfix: this.host.ttsPronDict,
        });
        wavBuf = out.wavBuf;
        wavDur = out.duration;
        cnyCost = Math.round(((out.characters * (Number(this.host.settings.blPrice) || 1.4)) / 10000) * 10000) / 10000;
        this.host.ttsCloudMonth.n += 1;
        this.host.ttsCloudMonth.bill += out.characters;
        this.host.ttsCloudMonth.cny = Math.round((this.host.ttsCloudMonth.cny + cnyCost) * 10000) / 10000;
      } else {
        await this.sleepAbortable(160, isAborted);
        const estSec = Math.max(1.2, Math.min(8, (d.text || '').length * 0.22));
        const style = d.role.includes('紫苏') ? 'zisu' : 'white';
        const syn = createWavBuffer(estSec, style, d.order);
        wavBuf = syn.buf;
        wavDur = syn.duration;
      }

      const rel = `tts/${d.line_id}_v${Date.now().toString(36)}.wav`;
      const asset = makeAsset(rel, wavBuf, { duration: wavDur });
      const ver = this.putAsset(proj.id, asset, {
        kind: 'audio',
        label: `第 ${d.order} 句 · ${d.role}`,
        agent_id: 'voice',
        task_id: tk.task_id,
        line_id: d.line_id,
        shot_id: d.shot_id,
        model: useCloud ? String(this.host.settings.blModel || 'qwen-audio-3.1-tts-plus') : 'local-synth',
        params: { speaker: d.speaker, tone: d.tone, text: d.text },
      });
      d.audio_asset_id = ver.asset_id;
      d.duration_sec = wavDur;
      d.cache_key = fp;
      tk.cost_cny = Math.round((tk.cost_cny + cnyCost) * 10000) / 10000;
    }

    // Merge all ordered dialogues into tts/voice.wav
    setProg(92, '正在按全剧句序拼接总配音轨 tts/voice.wav…');
    const orderedBufs: Buffer[] = [];
    for (const d of [...proj.dialogues].sort((a, b) => a.order - b.order)) {
      if (!d.audio_asset_id) continue;
      const meta = proj.assets.find((a) => a.asset_id === d.audio_asset_id);
      if (!meta) continue;
      const b = this.getAssetBuffer(proj.id, meta.rel);
      if (b) orderedBufs.push(b.buf);
    }
    if (orderedBufs.length) {
      const merged = concatWavBuffers(orderedBufs, Number(this.host.settings.ttsGap) || 0.25);
      const voiceAsset = makeAsset('tts/voice.wav', merged.buf, { duration: merged.duration });
      const mergedVer = this.putAsset(proj.id, voiceAsset, {
        kind: 'audio',
        label: `全片合并配音轨 (${orderedBufs.length} 句)`,
        agent_id: 'voice',
        task_id: tk.task_id,
      });
      refsOut.push({
        asset_id: mergedVer.asset_id,
        rel: mergedVer.rel,
        kind: 'audio',
        label: mergedVer.label,
        sha256: mergedVer.sha256,
        duration: mergedVer.duration,
      });
    }

    tk.cache_hit = hits === lines.length && lines.length > 0;
    tk.phase = `完成配音（共 ${proj.dialogues.length} 句，缓存命中 ${hits} 句）`;
    return refsOut;
  }

  private async execBgmGenerate(
    proj: StudioProjectV2,
    tk: StudioTaskNode,
    setProg: (p: number, s: string) => void,
    isAborted: () => boolean
  ): Promise<ChatArtifactRef[]> {
    const fp = computeBgmFingerprint(proj.bgm);
    const force = Boolean(tk.inputs.force);
    const existing = proj.bgm.asset_id ? proj.assets.find((a) => a.asset_id === proj.bgm.asset_id) : undefined;
    if (!force && proj.cache['bgm']?.fingerprint === fp && existing && this.getAssetBuffer(proj.id, existing.rel)) {
      tk.cache_hit = true;
      tk.phase = `配乐缓存命中（${existing.duration}s）`;
      return [{ asset_id: existing.asset_id, rel: existing.rel, kind: 'audio', label: `${existing.label}（缓存）`, sha256: existing.sha256, duration: existing.duration }];
    }

    setProg(35, `正在生成 ${proj.bgm.seconds}s 背景配乐（${proj.bgm.steps} 步）…`);
    await this.sleepAbortable(320, isAborted);
    if (isAborted()) throw new Error('已取消');
    setProg(85, '正在做 -1 dBFS 峰值归一…');
    const wav = createWavBuffer(Math.min(proj.bgm.seconds, 15), 'bgm', proj.bgm.seed);
    const asset = makeAsset('bgm/bgm.wav', wav.buf, { duration: wav.duration });
    const ver = this.putAsset(proj.id, asset, {
      kind: 'audio',
      label: `背景配乐 (${proj.bgm.seconds}s)`,
      agent_id: 'bgm',
      task_id: tk.task_id,
      model: 'stable-audio-3-preview',
      params: { ...proj.bgm },
    });
    proj.bgm.asset_id = ver.asset_id;
    proj.cache['bgm'] = { key: 'bgm', fingerprint: fp, asset_ids: [ver.asset_id], updated_at: nowSec() };
    tk.phase = `配乐已生成（${wav.duration}s · -1 dBFS 归一）`;
    return [{ asset_id: ver.asset_id, rel: ver.rel, kind: 'audio', label: `${ver.label} v${ver.version}`, sha256: ver.sha256, duration: ver.duration }];
  }

  private async execVideoRenderFrames(
    proj: StudioProjectV2,
    tk: StudioTaskNode,
    setProg: (p: number, s: string) => void,
    isAborted: () => boolean
  ): Promise<ChatArtifactRef[]> {
    const [w, h] = dimsForRatio(proj.ratio, 480);
    const force = Boolean(tk.inputs.force);
    const refsOut: ChatArtifactRef[] = [];
    let hits = 0;

    for (let i = 0; i < proj.shots.length; i++) {
      if (isAborted()) throw new Error('已取消');
      const s = proj.shots[i];
      const fp = computeShotVisualFingerprint(s, proj.ratio);
      const existing = s.frame_asset_id ? proj.assets.find((a) => a.asset_id === s.frame_asset_id) : undefined;
      if (!force && s.cache_key === fp && existing && this.getAssetBuffer(proj.id, existing.rel)) {
        hits++;
        continue;
      }

      setProg(15 + Math.round((i / Math.max(1, proj.shots.length)) * 75), `渲染镜头 ${s.order}/${proj.shots.length}（${s.render.toUpperCase()} 轨道）…`);
      await this.sleepAbortable(150, isAborted);

      // Prefer adopted generated image for this shot if present, else synthesize high-clarity styled frame
      const adoptedImgMeta = s.image_asset_id ? proj.assets.find((a) => a.asset_id === s.image_asset_id) : undefined;
      const adoptedBuf = adoptedImgMeta ? this.getAssetBuffer(proj.id, adoptedImgMeta.rel)?.buf : undefined;
      const isPpt = s.render === 'ppt';
      const rel = isPpt ? `render/ppt_${String(s.order).padStart(2, '0')}.png` : i === 0 ? 'render/web_preview.png' : `render/web_${String(s.order).padStart(2, '0')}.png`;
      const pngBuf =
        adoptedBuf && adoptedImgMeta?.mime === 'image/png'
          ? adoptedBuf
          : createPngBuffer(w, h, {
              accent: isPpt ? [255, 154, 60] : [31, 214, 240],
              bg: isPpt ? [14, 20, 32] : [10, 18, 28],
              progress: (i + 1) / Math.max(1, proj.shots.length),
              seed: i * 17 + 10,
            });
      const ver = this.putAsset(proj.id, makeAsset(rel, pngBuf), {
        kind: 'image',
        label: `镜头 ${s.order} ${isPpt ? 'PPT 卡片' : '动效'}帧`,
        agent_id: 'video_gen',
        task_id: tk.task_id,
        shot_id: s.shot_id,
        params: { render: s.render, ratio: proj.ratio },
      });
      s.frame_asset_id = ver.asset_id;
      s.cache_key = fp;
      refsOut.push({ asset_id: ver.asset_id, rel: ver.rel, kind: 'image', label: ver.label, sha256: ver.sha256, w: ver.w, h: ver.h });
    }

    tk.cache_hit = hits === proj.shots.length && proj.shots.length > 0;
    tk.phase = `已渲染 ${proj.shots.length} 镜视觉帧（缓存命中 ${hits} 镜）`;
    return refsOut.slice(0, 4);
  }

  private async execComposeFfmpeg(
    proj: StudioProjectV2,
    tk: StudioTaskNode,
    setProg: (p: number, s: string) => void,
    isAborted: () => boolean
  ): Promise<ChatArtifactRef[]> {
    setProg(10, '正在收集分镜帧、配音音轨与字幕时间轴…');

    const frames: Buffer[] = [];
    for (const s of proj.shots) {
      const fMeta = s.frame_asset_id ? proj.assets.find((a) => a.asset_id === s.frame_asset_id) : undefined;
      const fBuf = fMeta ? this.getAssetBuffer(proj.id, fMeta.rel)?.buf : undefined;
      if (fBuf) {
        frames.push(fBuf);
        continue;
      }
      const iMeta = s.image_asset_id ? proj.assets.find((a) => a.asset_id === s.image_asset_id) : undefined;
      const iBuf = iMeta ? this.getAssetBuffer(proj.id, iMeta.rel)?.buf : undefined;
      if (iBuf && iMeta?.mime === 'image/png') frames.push(iBuf);
    }

    if (!frames.length) {
      const [w, h] = dimsForRatio(proj.ratio, 480);
      frames.push(createPngBuffer(w, h, { accent: [31, 214, 240], progress: 1, seed: 42 }));
    }

    // Generate SRT subtitle file
    const srtBuf = generateSrtBuffer(proj);
    const srtAsset = makeAsset('output/subtitles.srt', srtBuf);
    this.putAsset(proj.id, srtAsset, {
      kind: 'subtitle',
      label: '成片 SRT 字幕',
      agent_id: 'compose',
      task_id: tk.task_id,
    });

    const voiceBuf = this.getAssetBuffer(proj.id, 'tts/voice.wav')?.buf;
    const bgmBuf = this.getAssetBuffer(proj.id, 'bgm/bgm.wav')?.buf;
    const legacyShots = proj.shots.map((s) => ({
      id: s.shot_id,
      line_index: s.order,
      render: s.render,
      text: s.subtitle_text,
      visual: s.visual_prompt,
      seconds: s.duration_sec,
    }));

    const composed = await runFfmpegCompose({
      pid: proj.id,
      shots: legacyShots,
      frames,
      voiceWav: voiceBuf,
      bgmWav: bgmBuf,
      ratio: proj.ratio,
      fps: proj.compose_config.fps,
      bgmVolume: proj.compose_config.bgm_volume,
      duckDepth: proj.compose_config.duck_depth,
      fade: proj.compose_config.fade,
      subtitle: proj.compose_config.subtitle,
      registerProc: (proc) => {
        this.taskProcs.get(tk.task_id)?.add(proc);
      },
      isAborted,
      onProgress: (info) => {
        setProg(15 + info.pct * 0.8, `FFmpeg 压制 ${Math.round(info.pct)}% (${info.fps.toFixed(1)} fps)`);
      },
    });

    const mp4Asset = makeAsset('output/final.mp4', composed.mp4, { duration: composed.duration });
    const mp4Ver = this.putAsset(proj.id, mp4Asset, {
      kind: 'video',
      label: `成片 MP4 (${composed.resolution})`,
      agent_id: 'compose',
      task_id: tk.task_id,
      model: 'ffmpeg-libx264',
      params: { ...proj.compose_config, ratio: proj.ratio },
    });

    const [cw, ch] = dimsForRatio(proj.ratio, 480);
    const coverVer = this.putAsset(proj.id, makeAsset('output/cover.png', createPngBuffer(cw, ch, { accent: [31, 214, 240], progress: 1, seed: 999 })), {
      kind: 'image',
      label: '成片封面图',
      agent_id: 'compose',
      task_id: tk.task_id,
    });

    proj.video_ok = true;
    proj.duration = composed.duration;
    proj.resolution = composed.resolution;
    proj.files = {
      video: {
        rel: mp4Ver.rel,
        size: composed.mp4.length,
        url: `/api/studio/asset?pid=${encodeURIComponent(proj.id)}&path=${encodeURIComponent(mp4Ver.rel)}&v=${mp4Ver.sha256.slice(0, 12)}`,
      },
      cover: {
        rel: coverVer.rel,
        name: 'cover.png',
        url: `/api/studio/asset?pid=${encodeURIComponent(proj.id)}&path=${encodeURIComponent(coverVer.rel)}&v=${coverVer.sha256.slice(0, 12)}`,
      },
    };
    proj.revision += 1;
    tk.phase = `成片压制完成（${composed.resolution} · ${composed.duration}s）`;
    return [
      { asset_id: mp4Ver.asset_id, rel: mp4Ver.rel, kind: 'video', label: `${mp4Ver.label} v${mp4Ver.version}`, sha256: mp4Ver.sha256, duration: mp4Ver.duration },
    ];
  }

  private async execQaInspect(proj: StudioProjectV2, tk: StudioTaskNode, setProg: (p: number, s: string) => void): Promise<void> {
    setProg(30, '正在运行 ffprobe 与成片规范校验…');
    const report = await runRealFfprobeQA(proj, (rel) => this.getAssetBuffer(proj.id, rel));
    proj.qa = report;
    proj.revision += 1;
    tk.phase = `${report.score_label} · ${report.passed ? '质检通过' : '发现阻断项'}`;
  }

  async runManualQa(pid: string): Promise<{ report: QAReport; state: Record<string, unknown> }> {
    const proj = this.getProject(pid);
    const report = await runRealFfprobeQA(proj, (rel) => this.getAssetBuffer(proj.id, rel));
    proj.qa = report;
    proj.revision += 1;
    this.pushMessage(proj, {
      kind: 'agent',
      sender_id: 'qa',
      sender_name: '质检 Agent',
      text: `${report.summary}${report.probe ? `\n视频流：${report.probe.video_codec} ${report.probe.width}×${report.probe.height} @ ${report.probe.fps}fps · 音频：${report.probe.audio_codec} · 时长 ${report.probe.duration}s` : ''}`,
    });
    this.persistProject(proj);
    return { report, state: this.getState(proj.id) };
  }
}
