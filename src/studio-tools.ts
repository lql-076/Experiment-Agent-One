import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  buildStudioListsFromModules,
  dimsForRatio,
  parseImportedScript,
  sha256Hex,
  type StudioAsset,
  type StudioModuleLike,
  type StudioShot,
  type VoiceLine,
} from './studio-runtime.ts';
import type {
  AgentId,
  QACheckItem,
  QAReport,
  StudioAssetVersion,
  StudioDialogueV2,
  StudioProjectV2,
  StudioShotV2,
} from './studio-types.ts';

export interface ToolRegistryEntry {
  name: string;
  agent_id: AgentId;
  description: string;
  timeout_ms: number;
  concurrency_limit: number;
  mutates_assets: boolean;
  requires_approval_on_cloud: boolean;
}

export const STUDIO_TOOL_REGISTRY: Record<string, ToolRegistryEntry> = {
  'script.plan': {
    name: 'script.plan',
    agent_id: 'script',
    description: '生成或改写结构化短视频剧本、双人对话台词与镜头节拍',
    timeout_ms: 45000,
    concurrency_limit: 1,
    mutates_assets: false,
    requires_approval_on_cloud: false,
  },
  'storyboard.build': {
    name: 'storyboard.build',
    agent_id: 'storyboard',
    description: '根据剧本拆分镜头 shot_id、画面提示词、渲染方式与时长',
    timeout_ms: 20000,
    concurrency_limit: 1,
    mutates_assets: false,
    requires_approval_on_cloud: false,
  },
  'image.generate': {
    name: 'image.generate',
    agent_id: 'image',
    description: '调用 API易 或本地预览渲染分镜配图并登记版本化视觉资产',
    timeout_ms: 120000,
    concurrency_limit: 2,
    mutates_assets: true,
    requires_approval_on_cloud: true,
  },
  'voice.synthesize_line': {
    name: 'voice.synthesize_line',
    agent_id: 'voice',
    description: '按句级 line_id 增量生成阿里云百炼或本地预览配音并合并总音轨',
    timeout_ms: 90000,
    concurrency_limit: 2,
    mutates_assets: true,
    requires_approval_on_cloud: true,
  },
  'bgm.generate': {
    name: 'bgm.generate',
    agent_id: 'bgm',
    description: '生成匹配时长并峰值归一至 -1 dBFS 的背景配乐 WAV',
    timeout_ms: 45000,
    concurrency_limit: 1,
    mutates_assets: true,
    requires_approval_on_cloud: false,
  },
  'video.render_frames': {
    name: 'video.render_frames',
    agent_id: 'video_gen',
    description: '并发渲染网页动效帧、PPT 卡片帧与镜头视觉预览图',
    timeout_ms: 60000,
    concurrency_limit: 2,
    mutates_assets: true,
    requires_approval_on_cloud: false,
  },
  'compose.ffmpeg': {
    name: 'compose.ffmpeg',
    agent_id: 'compose',
    description: '调用 FFmpeg 合成视频流、配音轨、配乐闪避混音与 SRT 字幕',
    timeout_ms: 120000,
    concurrency_limit: 1,
    mutates_assets: true,
    requires_approval_on_cloud: false,
  },
  'qa.inspect': {
    name: 'qa.inspect',
    agent_id: 'qa',
    description: '调用 ffprobe 对成片流编码、分辨率、帧率、时长、字幕与资产完整性做结构化质检',
    timeout_ms: 30000,
    concurrency_limit: 1,
    mutates_assets: false,
    requires_approval_on_cloud: false,
  },
};

export function checkBinaryAvailable(bin: string): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      const p = spawn(bin, ['-version'], { stdio: 'ignore' });
      p.on('error', () => resolve(false));
      p.on('close', (code) => resolve(code === 0));
    } catch {
      resolve(false);
    }
  });
}

export function generateSrtBuffer(proj: StudioProjectV2): Buffer {
  const fmtSrtTime = (sec: number): string => {
    const msTotal = Math.max(0, Math.round(sec * 1000));
    const h = Math.floor(msTotal / 3600000);
    const m = Math.floor((msTotal % 3600000) / 60000);
    const s = Math.floor((msTotal % 60000) / 1000);
    const ms = msTotal % 1000;
    const pad = (n: number, len = 2) => String(n).padStart(len, '0');
    return `${pad(h)}:${pad(m)}:${pad(s)},${pad(ms, 3)}`;
  };

  let cursor = 0;
  const blocks: string[] = [];
  const shotsById = new Map(proj.shots.map((s) => [s.shot_id, s]));
  const items = proj.dialogues.length
    ? proj.dialogues.map((d, i) => ({
        idx: i + 1,
        text: d.text,
        dur: Math.max(1.2, d.duration_sec || shotsById.get(d.shot_id)?.duration_sec || Math.ceil(d.text.length / 4.5)),
      }))
    : proj.shots.map((s, i) => ({
        idx: i + 1,
        text: s.subtitle_text || s.visual_prompt,
        dur: Math.max(1.5, s.duration_sec || 4),
      }));

  for (const it of items) {
    const txt = String(it.text || '').trim();
    if (!txt) continue;
    const start = cursor;
    const end = cursor + it.dur;
    blocks.push(`${it.idx}\n${fmtSrtTime(start)} --> ${fmtSrtTime(end)}\n${txt}`);
    cursor = end + 0.15;
  }
  return Buffer.from(blocks.join('\n\n') + '\n', 'utf8');
}

export interface FfprobeJson {
  format?: {
    format_name?: string;
    duration?: string;
    size?: string;
  };
  streams?: Array<{
    codec_type?: string;
    codec_name?: string;
    width?: number;
    height?: number;
    avg_frame_rate?: string;
    r_frame_rate?: string;
    sample_rate?: string;
    channels?: number;
  }>;
}

export async function runFfprobeOnBuffer(mp4Buf: Buffer): Promise<FfprobeJson> {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'eao-qa-'));
  const file = path.join(tmpDir, 'probe.mp4');
  try {
    fs.writeFileSync(file, mp4Buf);
    const raw = await new Promise<string>((resolve, reject) => {
      const p = spawn(
        'ffprobe',
        ['-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', file],
        { stdio: ['ignore', 'pipe', 'pipe'] }
      );
      let out = '';
      let err = '';
      p.stdout.on('data', (c: Buffer) => {
        out += c.toString('utf8');
      });
      p.stderr.on('data', (c: Buffer) => {
        err += c.toString('utf8');
      });
      p.on('error', (e) => reject(e));
      p.on('close', (code) => {
        if (code !== 0) reject(new Error(err || `ffprobe 退出码 ${code}`));
        else resolve(out);
      });
    });
    return JSON.parse(raw) as FfprobeJson;
  } finally {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  }
}

export async function runRealFfprobeQA(
  proj: StudioProjectV2,
  getAssetBuf: (rel: string) => StudioAsset | null
): Promise<QAReport> {
  const checks: QACheckItem[] = [];
  const mp4Asset = getAssetBuf('output/final.mp4');
  const srtAsset = getAssetBuf('output/subtitles.srt');
  const voiceAsset = getAssetBuf('tts/voice.wav');
  const bgmAsset = getAssetBuf('bgm/bgm.wav');

  // 1. Check adopted assets exist
  const missingAssets: string[] = [];
  for (const a of proj.assets.filter((x) => x.adopted)) {
    if (!getAssetBuf(a.rel)) missingAssets.push(a.rel);
  }
  checks.push({
    key: 'assets_exist',
    name: '已采用资产引用完整性',
    passed: missingAssets.length === 0,
    severity: 'error',
    detail:
      missingAssets.length === 0
        ? `全部 ${proj.assets.filter((x) => x.adopted).length} 份已采用资产均可正常读取`
        : `缺失资源：${missingAssets.slice(0, 3).join('、')}`,
    target_agent: 'compose',
    fix_action: '重新生成缺失资产并合成',
  });

  // 2. Check dialogues & shots consistency
  const emptyShots = proj.shots.filter((s) => !s.visual_prompt.trim() || s.duration_sec <= 0);
  checks.push({
    key: 'storyboard_valid',
    name: '分镜结构与时长校验',
    passed: proj.shots.length > 0 && emptyShots.length === 0,
    severity: 'error',
    detail:
      proj.shots.length === 0
        ? '项目中没有任何分镜'
        : emptyShots.length === 0
          ? `共 ${proj.shots.length} 镜，计划总时长 ${proj.total_seconds}s`
          : `第 ${emptyShots.map((s) => s.order).join(', ')} 镜缺少画面描述或时长不合法`,
    target_agent: 'storyboard',
    fix_action: '补全分镜描述并重跑分镜',
  });

  // 3. Check voice synthesis coverage
  const unvoiced = proj.dialogues.filter((d) => !d.audio_asset_id);
  checks.push({
    key: 'voice_coverage',
    name: '台词配音覆盖率',
    passed: proj.dialogues.length === 0 || (unvoiced.length === 0 && Boolean(voiceAsset)),
    severity: 'error',
    detail:
      proj.dialogues.length === 0
        ? '无台词条目（纯视觉模式）'
        : unvoiced.length === 0 && voiceAsset
          ? `${proj.dialogues.length}/${proj.dialogues.length} 句已合成，总音轨 ${voiceAsset.duration?.toFixed(1) || '?'}s`
          : `还有 ${unvoiced.length} 句未生成配音（${unvoiced.map((u) => u.line_id).slice(0, 3).join(', ')}）`,
    target_agent: 'voice',
    fix_action: '补全缺失句配音并合并音轨',
  });

  // 4. Subtitle SRT check
  const srtText = srtAsset ? srtAsset.buf.toString('utf8') : '';
  const hasSrtTimestamp = /\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}/.test(srtText);
  checks.push({
    key: 'subtitle_srt',
    name: 'SRT 字幕文件校验',
    passed: !proj.compose_config.subtitle || hasSrtTimestamp,
    severity: 'warn',
    detail: proj.compose_config.subtitle
      ? hasSrtTimestamp
        ? `已生成规范 SRT 字幕（${srtText.split(/\n\n+/).filter(Boolean).length} 条时间轴）`
        : '开启了字幕但缺少有效 output/subtitles.srt 时间轴'
      : '项目未开启字幕输出',
    target_agent: 'compose',
    fix_action: '重新生成字幕并合成',
  });

  // 5. MP4 & ffprobe verification
  let probeSummary: QAReport['probe'] | undefined;
  if (!mp4Asset || mp4Asset.buf.length < 1024) {
    checks.push({
      key: 'mp4_exists',
      name: '成片 MP4 存在与非空校验',
      passed: false,
      severity: 'error',
      detail: '尚未生成 output/final.mp4 成片，或文件体积异常过小',
      target_agent: 'compose',
      fix_action: '执行后期合成压制成片',
    });
  } else {
    checks.push({
      key: 'mp4_exists',
      name: '成片 MP4 存在与非空校验',
      passed: true,
      severity: 'error',
      detail: `output/final.mp4 已就绪（${(mp4Asset.buf.length / 1024).toFixed(1)} KB）`,
    });

    try {
      const probe = await runFfprobeOnBuffer(mp4Asset.buf);
      const vStream = (probe.streams || []).find((s) => s.codec_type === 'video');
      const aStream = (probe.streams || []).find((s) => s.codec_type === 'audio');
      const dur = Number(probe.format?.duration || 0);
      let fpsVal = 0;
      const rateStr = vStream?.avg_frame_rate || vStream?.r_frame_rate || '0/1';
      if (rateStr.includes('/')) {
        const [num, den] = rateStr.split('/').map(Number);
        fpsVal = den ? Math.round((num / den) * 10) / 10 : 0;
      } else {
        fpsVal = Number(rateStr) || 0;
      }

      probeSummary = {
        format: probe.format?.format_name || 'mp4',
        duration: Math.round(dur * 100) / 100,
        size: Number(probe.format?.size || mp4Asset.buf.length),
        video_codec: vStream?.codec_name || 'unknown',
        width: vStream?.width || 0,
        height: vStream?.height || 0,
        fps: fpsVal,
        audio_codec: aStream?.codec_name || 'none',
        sample_rate: aStream?.sample_rate ? Number(aStream.sample_rate) : 0,
        channels: aStream?.channels || 0,
      };

      const [expW, expH] = dimsForRatio(proj.ratio, 720);
      const resMatch =
        Boolean(vStream?.width && vStream?.height) &&
        Math.abs((vStream!.width || 0) - expW) <= 4 &&
        Math.abs((vStream!.height || 0) - expH) <= 4;

      checks.push({
        key: 'ffprobe_video_stream',
        name: 'ffprobe 视频流与分辨率比例校验',
        passed: Boolean(vStream && vStream.codec_name === 'h264' && resMatch),
        severity: 'error',
        detail: vStream
          ? `编码 ${vStream.codec_name} · 实际 ${vStream.width}×${vStream.height} @ ${fpsVal}fps（目标 ${proj.ratio} ≈ ${expW}×${expH}）`
          : '未检测到有效视频轨',
        target_agent: 'compose',
        fix_action: '按目标比例重跑后期合成',
      });

      checks.push({
        key: 'ffprobe_audio_stream',
        name: 'ffprobe 音频流与音画时长校验',
        passed: Boolean(aStream && dur > 0.5),
        severity: 'error',
        detail: aStream
          ? `音频 ${aStream.codec_name} · ${probeSummary.sample_rate || 0}Hz · 成片时长 ${dur.toFixed(2)}s${bgmAsset ? '（含 BGM 混音）' : ''}`
          : '成片缺少音频轨（AAC）',
        target_agent: 'compose',
        fix_action: '检查配音轨并重跑混流',
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      checks.push({
        key: 'ffprobe_exec',
        name: 'ffprobe 容器结构探测',
        passed: false,
        severity: 'error',
        detail: `ffprobe 执行异常：${msg}`,
        target_agent: 'compose',
        fix_action: '重新压制标准 MP4',
      });
    }
  }

  const errorCount = checks.filter((c) => !c.passed && c.severity === 'error').length;
  const warnCount = checks.filter((c) => !c.passed && c.severity === 'warn').length;
  const passedCount = checks.filter((c) => c.passed).length;
  const passed = errorCount === 0;

  return {
    report_id: `qa-${Date.now().toString(36)}`,
    project_id: proj.id,
    created_at: Math.floor(Date.now() / 1000),
    passed,
    score_label: `${passedCount}/${checks.length} 项通过`,
    summary: passed
      ? `质检通过（${passedCount}/${checks.length} 项校验正常${warnCount ? `，${warnCount} 项提醒` : ''}），可直接用于预览或发布。`
      : `质检发现 ${errorCount} 项阻断问题：${checks
          .filter((c) => !c.passed && c.severity === 'error')
          .map((c) => c.name)
          .join('、')}。`,
    probe: probeSummary,
    checks,
  };
}

/**
 * Keeps structured Project V2 <-> legacy 5 Markdown Lists & 7 Modules synced seamlessly.
 */
export function syncProjectDerivedViews(proj: StudioProjectV2): void {
  const whiteLines: VoiceLine[] = proj.dialogues
    .filter((d) => !d.role.includes('紫苏'))
    .map((d) => ({
      id: d.line_id,
      line_index: d.order,
      text: d.text,
      tone: d.tone,
      speaker: d.speaker,
      engine: d.engine,
    }));
  const zisuLines: VoiceLine[] = proj.dialogues
    .filter((d) => d.role.includes('紫苏'))
    .map((d) => ({
      id: d.line_id,
      line_index: d.order,
      text: d.text,
      tone: d.tone,
      speaker: d.speaker,
      engine: d.engine,
    }));
  const shots: StudioShot[] = proj.shots.map((s) => ({
    id: s.shot_id,
    line_index: s.order,
    render: s.render,
    text: s.subtitle_text,
    visual: s.visual_prompt,
    seconds: s.duration_sec,
    transition: s.transition,
  }));

  const adoptedByKind = (kind: StudioAssetVersion['kind']) =>
    proj.assets.filter((a) => a.adopted && a.kind === kind);

  const imgOutputs = adoptedByKind('image').map((a) => ({
    kind: 'image',
    rel: a.rel,
    label: a.label,
    sha256: a.sha256,
  }));
  const whiteAudioOuts = proj.dialogues
    .filter((d) => !d.role.includes('紫苏') && d.audio_asset_id)
    .map((d) => {
      const a = proj.assets.find((x) => x.asset_id === d.audio_asset_id);
      return a ? { kind: 'audio', rel: a.rel, line: String(d.order), sha256: a.sha256, duration: a.duration } : null;
    })
    .filter(Boolean) as StudioModuleLike['outputs'];
  const zisuAudioOuts = proj.dialogues
    .filter((d) => d.role.includes('紫苏') && d.audio_asset_id)
    .map((d) => {
      const a = proj.assets.find((x) => x.asset_id === d.audio_asset_id);
      return a ? { kind: 'audio', rel: a.rel, line: String(d.order), sha256: a.sha256, duration: a.duration } : null;
    })
    .filter(Boolean) as StudioModuleLike['outputs'];
  const bgmAsset = proj.bgm.asset_id
    ? proj.assets.find((x) => x.asset_id === proj.bgm.asset_id)
    : adoptedByKind('audio').find((x) => x.rel === 'bgm/bgm.wav');
  const videoAsset = adoptedByKind('video')[0];

  const mods: StudioModuleLike[] = [
    {
      id: 'script',
      type: 'script',
      title: '剧本与策划',
      x: 40,
      y: 40,
      w: 350,
      h: 470,
      params: { topic: proj.title, title: proj.title, desc: proj.desc, tags: proj.tags },
      outputs: [],
      status: proj.shots.length ? 'ok' : 'idle',
      error: '',
      cache_hit: false,
    },
    {
      id: 'image',
      type: 'image',
      title: '生图引擎',
      x: 430,
      y: 40,
      w: 380,
      h: 620,
      params: {
        prompt: proj.image_config.items[0]?.prompt || '暖光书桌前的年轻人，竖屏中景',
        model: proj.image_config.model,
        ratio: proj.image_config.ratio,
        resolution: proj.image_config.resolution,
        quality: proj.image_config.quality,
        n: proj.image_config.n,
        output: proj.image_config.output,
        refs: proj.image_config.refs,
        items: proj.image_config.items,
      },
      outputs: imgOutputs,
      status: imgOutputs.length ? 'ok' : 'idle',
      error: '',
      cache_hit: false,
    },
    {
      id: 'voice-white',
      type: 'voice',
      title: '角色配音 · 白页',
      x: 850,
      y: 40,
      w: 400,
      h: 500,
      params: {
        role: '白页',
        speaker: proj.dialogues.find((d) => !d.role.includes('紫苏'))?.speaker || 'local:preset:Serena',
        engine: proj.dialogues.find((d) => !d.role.includes('紫苏'))?.engine || 'auto',
        tone: '冷静吐槽',
        lines: whiteLines,
      },
      outputs: whiteAudioOuts,
      status: whiteAudioOuts.length ? 'ok' : 'idle',
      error: '',
      cache_hit: false,
    },
    {
      id: 'voice-zisu',
      type: 'voice',
      title: '角色配音 · 紫苏',
      x: 850,
      y: 570,
      w: 400,
      h: 500,
      params: {
        role: '紫苏',
        speaker: proj.dialogues.find((d) => d.role.includes('紫苏'))?.speaker || 'local:preset:Dylan',
        engine: proj.dialogues.find((d) => d.role.includes('紫苏'))?.engine || 'auto',
        tone: '轻松调侃',
        lines: zisuLines,
      },
      outputs: zisuAudioOuts,
      status: zisuAudioOuts.length ? 'ok' : 'idle',
      error: '',
      cache_hit: false,
    },
    {
      id: 'bgm',
      type: 'bgm',
      title: '背景配乐',
      x: 1290,
      y: 40,
      w: 360,
      h: 360,
      params: { ...proj.bgm },
      outputs: bgmAsset
        ? [{ kind: 'audio', rel: bgmAsset.rel, label: bgmAsset.label, sha256: bgmAsset.sha256, duration: bgmAsset.duration }]
        : [],
      status: bgmAsset ? 'ok' : 'idle',
      error: '',
      cache_hit: false,
    },
    {
      id: 'compose',
      type: 'compose',
      title: '后期总成',
      x: 40,
      y: 1120,
      w: 1610,
      h: 720,
      params: { ...proj.compose_config, ratio: proj.ratio, shots },
      outputs: videoAsset
        ? [{ kind: 'video', rel: videoAsset.rel, label: videoAsset.label, sha256: videoAsset.sha256, duration: videoAsset.duration }]
        : [],
      status: videoAsset ? 'ok' : 'idle',
      error: '',
      cache_hit: false,
    },
    {
      id: 'publish',
      type: 'publish',
      title: '成片发布',
      x: 1290,
      y: 430,
      w: 360,
      h: 600,
      params: { ...proj.publish_config },
      outputs: [],
      status: 'idle',
      error: '',
      cache_hit: false,
    },
  ];

  proj.modules = mods;
  proj.lists = buildStudioListsFromModules(mods);
  proj.total_seconds = proj.shots.reduce((acc, s) => acc + (Number(s.duration_sec) || 4), 0);
}

export function applyParsedScriptToProject(proj: StudioProjectV2, rawText: string): { summary: string; estimateUsd: number } {
  const parsed = parseImportedScript(rawText);
  if (parsed.title) proj.title = parsed.title;
  if (parsed.desc) proj.desc = parsed.desc;
  if (parsed.tags) proj.tags = parsed.tags;
  if (parsed.bgmPrompt) proj.bgm.prompt = parsed.bgmPrompt;
  if (parsed.bgmSeconds) proj.bgm.seconds = parsed.bgmSeconds;

  const newShots: StudioShotV2[] = parsed.shots.map((s, idx) => ({
    shot_id: s.id || `shot_${String(idx + 1).padStart(2, '0')}`,
    order: s.line_index || idx + 1,
    render: s.render,
    visual_prompt: s.visual || '现代感科技排版画面',
    subtitle_text: s.text || s.visual,
    duration_sec: s.seconds || 5,
    transition: s.transition || 'cut',
  }));

  const defaultWhiteSpeaker = proj.dialogues.find((d) => !d.role.includes('紫苏'))?.speaker || 'local:preset:Serena';
  const defaultZisuSpeaker = proj.dialogues.find((d) => d.role.includes('紫苏'))?.speaker || 'local:preset:Dylan';
  const allLines: Array<VoiceLine & { role: string }> = [
    ...parsed.whiteLines.map((l) => ({ ...l, role: '白页' })),
    ...parsed.zisuLines.map((l) => ({ ...l, role: '紫苏' })),
  ].sort((a, b) => a.line_index - b.line_index);

  const oldById = new Map(proj.dialogues.map((d) => [d.line_id, d]));
  const newDialogues: StudioDialogueV2[] = allLines.map((l, idx) => {
    const lineId = `line_${String(l.line_index || idx + 1).padStart(2, '0')}`;
    const prev = oldById.get(lineId);
    const matchingShot = newShots.find((s) => s.order === l.line_index) || newShots[idx] || newShots[0];
    const unchanged = prev && prev.text === l.text && prev.tone === (l.tone || prev.tone);
    return {
      line_id: lineId,
      shot_id: matchingShot ? matchingShot.shot_id : `shot_${String(idx + 1).padStart(2, '0')}`,
      order: l.line_index || idx + 1,
      role: l.role,
      speaker: prev?.speaker || (l.role.includes('紫苏') ? defaultZisuSpeaker : defaultWhiteSpeaker),
      engine: prev?.engine || 'auto',
      text: l.text,
      tone: l.tone || (l.role.includes('紫苏') ? '轻松调侃' : '冷静吐槽'),
      audio_asset_id: unchanged ? prev?.audio_asset_id : undefined,
      duration_sec: unchanged ? prev?.duration_sec : undefined,
      cache_key: unchanged ? prev?.cache_key : undefined,
    };
  });

  proj.shots = newShots;
  proj.dialogues = newDialogues;

  if (parsed.imageItems.length) {
    proj.image_config.items = parsed.imageItems.map((it, idx) => ({
      item_id: `img_${String(idx + 1).padStart(2, '0')}`,
      shot_id: newShots[idx]?.shot_id,
      label: `镜头 ${idx + 1} 配图`,
      prompt: it.prompt,
      ratio: it.ratio || proj.ratio,
      transparent: Boolean(it.transparent),
    }));
  } else {
    proj.image_config.items = newShots.map((s, idx) => ({
      item_id: `img_${String(idx + 1).padStart(2, '0')}`,
      shot_id: s.shot_id,
      label: `镜头 ${s.order} 配图`,
      prompt: s.visual_prompt,
      ratio: proj.ratio,
      transparent: false,
    }));
  }

  proj.script_summary = `${newDialogues.length} 句台词 · ${newShots.length} 镜 · 目标约 ${newShots.reduce((a, s) => a + s.duration_sec, 0)}s`;
  proj.updated_at = Math.floor(Date.now() / 1000);
  proj.revision += 1;
  syncProjectDerivedViews(proj);

  return {
    summary: proj.script_summary,
    estimateUsd: Math.round(proj.image_config.items.length * 0.03 * 100) / 100,
  };
}

export function computeLineFingerprint(d: StudioDialogueV2): string {
  return sha256Hex(JSON.stringify({ text: d.text, tone: d.tone, speaker: d.speaker, engine: d.engine })).slice(0, 20);
}

export function computeShotVisualFingerprint(s: StudioShotV2, ratio: string): string {
  return sha256Hex(JSON.stringify({ render: s.render, visual: s.visual_prompt, text: s.subtitle_text, ratio })).slice(0, 20);
}

export function computeBgmFingerprint(bgm: StudioProjectV2['bgm']): string {
  return sha256Hex(JSON.stringify({ prompt: bgm.prompt, seconds: bgm.seconds, steps: bgm.steps, seed: bgm.seed })).slice(0, 20);
}
