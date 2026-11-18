import { spawn, type ChildProcess } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';

export interface StudioAsset {
  rel: string;
  buf: Buffer;
  mime: string;
  sha256: string;
  name: string;
  w?: number;
  h?: number;
  duration?: number;
  frames?: number;
  duration_ms?: number;
}

export interface StudioShot {
  id: string;
  line_index: number;
  render: 'web' | 'ppt' | 'static';
  text: string;
  visual: string;
  seconds: number;
  transition?: string;
}

export interface VoiceLine {
  id: string;
  line_index: number;
  text: string;
  tone: string;
  speaker?: string;
  engine?: string;
}

export interface StudioModuleLike {
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

export interface StudioJobState {
  id: string;
  pid: string;
  st: 'run' | 'done' | 'err' | 'stopped';
  step: string;
  msg: string;
  web: {
    st: 'idle' | 'run' | 'ok' | 'err';
    current: number;
    total: number;
    frame: number;
    total_frames: number;
    fps: number;
    cc: string;
    msg: string;
    preview_rel?: string;
  };
  ppt: {
    st: 'idle' | 'run' | 'ok' | 'err';
    current: number;
    total: number;
    msg: string;
    slides: string[];
  };
  ffmpeg: {
    st: 'idle' | 'run' | 'ok' | 'err';
    pct: number;
    frame: number;
    fps: number;
    msg: string;
    log: string;
    params: Record<string, unknown>;
  };
}

const MIME_BY_EXT: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.wav': 'audio/wav',
  '.mp3': 'audio/mpeg',
  '.flac': 'audio/flac',
  '.ogg': 'audio/ogg',
  '.m4a': 'audio/mp4',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mov': 'video/quicktime',
};

export function sanitizeRelPath(rel: string): string | null {
  const clean = String(rel || '').replace(/\\/g, '/').trim();
  if (!clean || clean.startsWith('/') || clean.includes('\0')) return null;
  const parts = clean.split('/').filter(Boolean);
  if (!parts.length || parts.some((p) => p === '.' || p === '..')) return null;
  return parts.join('/');
}

export function mimeForRel(rel: string): string {
  const ext = path.extname(rel).toLowerCase();
  return MIME_BY_EXT[ext] || 'application/octet-stream';
}

export function sniffMediaHeader(rel: string, buf: Buffer): string | null {
  if (!buf || buf.length < 4) return '媒体文件为空或已损坏';
  const ext = path.extname(rel).toLowerCase();
  if (ext === '.png') {
    if (!(buf.length >= 8 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47)) {
      return 'PNG 文件头不合法';
    }
    return null;
  }
  if (ext === '.jpg' || ext === '.jpeg') {
    if (!(buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff)) return 'JPEG 文件头不合法';
    return null;
  }
  if (ext === '.gif') {
    const h = buf.subarray(0, 6).toString('ascii');
    if (h !== 'GIF87a' && h !== 'GIF89a') return 'GIF 文件头不合法';
    return null;
  }
  if (ext === '.webp') {
    if (!(buf.length >= 12 && buf.subarray(0, 4).toString('ascii') === 'RIFF' && buf.subarray(8, 12).toString('ascii') === 'WEBP')) {
      return 'WebP 文件头不合法';
    }
    return null;
  }
  if (ext === '.svg') {
    const head = buf.subarray(0, 512).toString('utf8').toLowerCase();
    if (!head.includes('<svg')) return 'SVG 文件缺少 <svg> 标签';
    return null;
  }
  if (ext === '.wav') {
    if (!(buf.length >= 12 && buf.subarray(0, 4).toString('ascii') === 'RIFF' && buf.subarray(8, 12).toString('ascii') === 'WAVE')) {
      return 'WAV 文件头损坏（缺少 RIFF/WAVE）';
    }
    return null;
  }
  if (ext === '.mp3') {
    const isId3 = buf.subarray(0, 3).toString('ascii') === 'ID3';
    const isSync = buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0;
    if (!isId3 && !isSync) return 'MP3 文件头不合法';
    return null;
  }
  if (ext === '.flac') {
    if (buf.subarray(0, 4).toString('ascii') !== 'fLaC') return 'FLAC 文件头不合法';
    return null;
  }
  if (ext === '.ogg') {
    if (buf.subarray(0, 4).toString('ascii') !== 'OggS') return 'OGG 文件头不合法';
    return null;
  }
  if (ext === '.mp4' || ext === '.mov' || ext === '.m4a') {
    if (!(buf.length >= 8 && buf.subarray(4, 8).toString('ascii') === 'ftyp')) return `${ext.toUpperCase()} 缺少 ftyp Box`;
    return null;
  }
  if (ext === '.webm') {
    if (!(buf[0] === 0x1a && buf[1] === 0x45 && buf[2] === 0xdf && buf[3] === 0xa3)) return 'WebM 缺少 EBML 头';
    return null;
  }
  return `不支持的媒体扩展名：${ext || '(无)'}`;
}

export function sha256Hex(buf: Buffer | string): string {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

export function makeAsset(rel: string, buf: Buffer, extra?: Partial<StudioAsset>): StudioAsset {
  const mime = mimeForRel(rel);
  const info = inspectAssetBuffer(rel, buf);
  return {
    rel,
    buf,
    mime,
    sha256: sha256Hex(buf),
    name: path.basename(rel),
    ...info,
    ...extra,
  };
}

export function inspectAssetBuffer(rel: string, buf: Buffer): { w?: number; h?: number; duration?: number; frames?: number; duration_ms?: number } {
  const ext = path.extname(rel).toLowerCase();
  if (ext === '.png' && buf.length >= 24 && buf.subarray(12, 16).toString('ascii') === 'IHDR') {
    return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
  }
  if (ext === '.gif' && buf.length >= 10) {
    return { w: buf.readUInt16LE(6), h: buf.readUInt16LE(8), frames: 1, duration_ms: 100 };
  }
  if (ext === '.svg') {
    const txt = buf.subarray(0, 1024).toString('utf8');
    const vb = txt.match(/viewBox=["'][\d.\s-]+?([\d.]+)\s+([\d.]+)["']/i);
    if (vb) return { w: Math.round(Number(vb[1]) || 720), h: Math.round(Number(vb[2]) || 1280) };
    return { w: 720, h: 1280 };
  }
  if (ext === '.wav' && buf.length >= 44) {
    const sampleRate = buf.readUInt32LE(24) || 24000;
    const byteRate = buf.readUInt32LE(28) || sampleRate * 2;
    const dataSize = Math.max(0, buf.length - 44);
    return { duration: Math.round((dataSize / byteRate) * 100) / 100 };
  }
  return {};
}

// ---------------- WAV Synthesis & Concatenation (-1 dBFS normalized) ----------------

export function createWavBuffer(
  durationSec: number,
  style: 'white' | 'zisu' | 'bgm' | 'silence',
  seed = 1
): { buf: Buffer; duration: number } {
  const sr = 24000;
  const dur = Math.max(0.4, Math.min(20, durationSec));
  const numSamples = Math.floor(sr * dur);
  const pcm = new Int16Array(numSamples);

  if (style !== 'silence') {
    const notes =
      style === 'white'
        ? [330, 392, 440, 392]
        : style === 'zisu'
          ? [523.25, 587.33, 659.25, 587.33]
          : [220, 277.18, 329.63, 440, 329.63, 277.18];
    const targetPeak = 0.89125 * 32767; // -1 dBFS
    let maxVal = 0.0001;
    const floats = new Float32Array(numSamples);
    const stepSamples = Math.max(2400, Math.floor(numSamples / notes.length));
    for (let i = 0; i < numSamples; i++) {
      const t = i / sr;
      const segIdx = Math.min(notes.length - 1, Math.floor(i / stepSamples));
      const freq = notes[(segIdx + (seed % notes.length)) % notes.length];
      const localPos = (i % stepSamples) / stepSamples;
      const env = Math.min(1, localPos * 12) * Math.min(1, (1 - localPos) * 10) * Math.min(1, (numSamples - i) / (sr * 0.08));
      const val =
        style === 'bgm'
          ? (Math.sin(2 * Math.PI * freq * t) * 0.55 +
              Math.sin(2 * Math.PI * (freq * 0.5) * t) * 0.3 +
              Math.sin(2 * Math.PI * (freq * 1.5) * t) * 0.15) *
            env
          : (Math.sin(2 * Math.PI * freq * t) * 0.7 + Math.sin(2 * Math.PI * freq * 2 * t) * 0.25) * env;
      floats[i] = val;
      const a = Math.abs(val);
      if (a > maxVal) maxVal = a;
    }
    const gain = targetPeak / maxVal;
    for (let i = 0; i < numSamples; i++) {
      pcm[i] = Math.max(-32767, Math.min(32767, Math.round(floats[i] * gain)));
    }
  }

  return { buf: wrapPcm16Wav(pcm, sr), duration: dur };
}

export function wrapPcm16Wav(pcm: Int16Array, sampleRate = 24000): Buffer {
  const dataSize = pcm.byteLength;
  const buf = Buffer.alloc(44 + dataSize);
  buf.write('RIFF', 0, 'ascii');
  buf.writeUInt32LE(36 + dataSize, 4);
  buf.write('WAVE', 8, 'ascii');
  buf.write('fmt ', 12, 'ascii');
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); // PCM
  buf.writeUInt16LE(1, 22); // mono
  buf.writeUInt32LE(sampleRate, 24);
  buf.writeUInt32LE(sampleRate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36, 'ascii');
  buf.writeUInt32LE(dataSize, 40);
  Buffer.from(pcm.buffer, pcm.byteOffset, pcm.byteLength).copy(buf, 44);
  return buf;
}

export function concatWavBuffers(wavs: Buffer[], gapSec = 0.25): { buf: Buffer; duration: number } {
  const sr = 24000;
  const gapSamples = Math.floor(sr * gapSec);
  const chunks: Int16Array[] = [];
  let total = 0;
  for (let i = 0; i < wavs.length; i++) {
    const b = wavs[i];
    if (b.length <= 44) continue;
    const pcmLen = Math.floor((b.length - 44) / 2);
    const slice = new Int16Array(b.buffer, b.byteOffset + 44, pcmLen);
    chunks.push(slice);
    total += slice.length;
    if (i < wavs.length - 1 && gapSamples > 0) {
      chunks.push(new Int16Array(gapSamples));
      total += gapSamples;
    }
  }
  if (!total) {
    return createWavBuffer(2.0, 'silence');
  }
  const merged = new Int16Array(total);
  let off = 0;
  for (const c of chunks) {
    merged.set(c, off);
    off += c.length;
  }
  return { buf: wrapPcm16Wav(merged, sr), duration: Math.round((total / sr) * 100) / 100 };
}

// ---------------- Pure-Node PNG & SVG Generator ----------------

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function pngChunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, 'ascii');
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crcBuf]);
}

export function createPngBuffer(
  width: number,
  height: number,
  opts: { accent?: [number, number, number]; bg?: [number, number, number]; transparent?: boolean; progress?: number; seed?: number } = {}
): Buffer {
  const w = Math.max(16, Math.min(1280, Math.round(width)));
  const h = Math.max(16, Math.min(1280, Math.round(height)));
  const [ar, ag, ab] = opts.accent || [31, 214, 240];
  const [br, bg, bb] = opts.bg || [10, 18, 28];
  const transparent = Boolean(opts.transparent);
  const progress = Math.max(0, Math.min(1, opts.progress ?? 0.65));
  const seed = opts.seed || 1;

  const stride = w * 4 + 1;
  const raw = Buffer.alloc(stride * h);
  const cx = w * 0.5;
  const cy = h * 0.44;
  const maxR = Math.min(w, h) * 0.28;

  for (let y = 0; y < h; y++) {
    const rowOff = y * stride;
    raw[rowOff] = 0; // filter none
    const gridY = y % 32 === 0;
    for (let x = 0; x < w; x++) {
      const px = rowOff + 1 + x * 4;
      const dx = x - cx;
      const dy = y - cy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const border = x < 4 || x >= w - 4 || y < 4 || y >= h - 4;
      const barY = y >= Math.floor(h * 0.78) && y <= Math.floor(h * 0.82) && x >= Math.floor(w * 0.14) && x <= Math.floor(w * 0.86);
      const barFill = barY && x <= Math.floor(w * (0.14 + 0.72 * progress));
      const inRing = Math.abs(dist - maxR) < Math.max(2, w * 0.008);
      const inOrb = dist < maxR * (0.52 + 0.08 * Math.sin(seed + y * 0.05));
      const onGrid = gridY || x % 32 === 0;

      if (transparent) {
        if (inOrb || inRing || barFill) {
          raw[px] = ar;
          raw[px + 1] = ag;
          raw[px + 2] = ab;
          raw[px + 3] = inRing ? 245 : 210;
        } else {
          raw[px] = 0;
          raw[px + 1] = 0;
          raw[px + 2] = 0;
          raw[px + 3] = 0;
        }
      } else {
        let r = br;
        let g = bg;
        let b = bb;
        if (onGrid) {
          r += 8;
          g += 14;
          b += 20;
        }
        if (border || inRing || barFill) {
          r = ar;
          g = ag;
          b = ab;
        } else if (barY) {
          r = 28;
          g = 48;
          b = 64;
        } else if (inOrb) {
          const k = 1 - dist / (maxR * 0.65);
          r = Math.min(255, Math.round(br + ar * 0.55 * k));
          g = Math.min(255, Math.round(bg + ag * 0.55 * k));
          b = Math.min(255, Math.round(bb + ab * 0.55 * k));
        }
        raw[px] = r;
        raw[px + 1] = g;
        raw[px + 2] = b;
        raw[px + 3] = 255;
      }
    }
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const compressed = zlib.deflateSync(raw, { level: 3 });
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', compressed),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

export function createSvgBuffer(w: number, h: number, title: string, accentHex = '#1fd6f0'): Buffer {
  const safeTitle = title.replace(/[<>&"']/g, '').slice(0, 60) || 'Preview';
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="${accentHex}" stop-opacity="0.28"/><stop offset="100%" stop-color="#ff9a3c" stop-opacity="0.2"/></linearGradient></defs>` +
    `<rect x="12" y="12" width="${w - 24}" height="${h - 24}" rx="18" fill="url(#g)" stroke="${accentHex}" stroke-width="3"/>` +
    `<circle cx="${Math.round(w / 2)}" cy="${Math.round(h * 0.42)}" r="${Math.round(Math.min(w, h) * 0.22)}" fill="none" stroke="${accentHex}" stroke-width="4" stroke-dasharray="12 8"/>` +
    `<text x="${Math.round(w / 2)}" y="${Math.round(h * 0.74)}" fill="${accentHex}" font-family="sans-serif" font-size="24" font-weight="700" text-anchor="middle">${safeTitle}</text>` +
    `</svg>`;
  return Buffer.from(svg, 'utf8');
}

export function dimsForRatio(ratio: string, maxSide = 480): [number, number] {
  const [rw, rh] = String(ratio || '9:16')
    .split(':')
    .map((x) => Number(x) || 9);
  if (rw >= rh) {
    const w = maxSide;
    const h = Math.max(64, Math.round((w * rh) / rw));
    return [w - (w % 2), h - (h % 2)];
  }
  const h = maxSide;
  const w = Math.max(64, Math.round((h * rw) / rh));
  return [w - (w % 2), h - (h % 2)];
}

// ---------------- Bidirectional Markdown Lists & Script Parsing ----------------

export function buildStudioListsFromModules(mods: StudioModuleLike[]): Record<string, string> {
  const white = mods.find((m) => m.id === 'voice-white');
  const zisu = mods.find((m) => m.id === 'voice-zisu');
  const bgm = mods.find((m) => m.id === 'bgm');
  const comp = mods.find((m) => m.id === 'compose');
  const img = mods.find((m) => m.id === 'image');

  const fmtVoice = (title: string, m?: StudioModuleLike): string => {
    const prm = (m?.params || {}) as Record<string, unknown>;
    const speaker = String(prm.speaker || 'local:preset:Serena');
    const tone = String(prm.tone || '');
    const lines = Array.isArray(prm.lines) ? (prm.lines as VoiceLine[]) : [];
    const blocks = lines.map((ln) => {
      const idx = String(ln.line_index || 1).padStart(2, '0');
      return `## ${idx}\n台词：${ln.text || ''}${ln.tone ? `\n语气：${ln.tone}` : ''}`;
    });
    return `# ${title}\n\n音色：${speaker}\n默认语气：${tone}\n\n${blocks.join('\n\n')}`.trim();
  };

  const bgmPrm = (bgm?.params || {}) as Record<string, unknown>;
  const bgmMd =
    `# 配乐清单\n\n## 01\n描述：${String(bgmPrm.prompt || 'upbeat electronic, no vocals')}\n` +
    `时长：${Number(bgmPrm.seconds) || 75}\n步数：${Number(bgmPrm.steps) || 8}\n种子：${Number(bgmPrm.seed) || 20261118}`;

  const shots = Array.isArray(comp?.params.shots) ? (comp!.params.shots as StudioShot[]) : [];
  const renderMd =
    `# 视频渲染清单\n\n` +
    shots
      .map((s) => {
        const idx = String(s.line_index || 1).padStart(2, '0');
        const way = s.render === 'ppt' ? 'PPT卡片' : s.render === 'static' ? '静态' : '网页动效';
        return `## ${idx}\n方式：${way}\n时长：${Number(s.seconds) || 5}\n画面：${s.visual || '科技感排版'}\n字幕：${s.text || ''}`;
      })
      .join('\n\n');

  const imgPrm = (img?.params || {}) as Record<string, unknown>;
  const imgItems = Array.isArray(imgPrm.items) ? (imgPrm.items as Array<Record<string, unknown>>) : [];
  const imgMd =
    `# 生图清单（可选）\n\n` +
    (imgItems.length
      ? imgItems
          .map((it, i) => `## ${String(i + 1).padStart(2, '0')}\n提示词：${String(it.prompt || '')}\n比例：${String(it.ratio || imgPrm.ratio || '9:16')}\n透明：${it.transparent ? '是' : '否'}`)
          .join('\n\n')
      : `## 01\n提示词：${String(imgPrm.prompt || '暖光书桌前的年轻人，竖屏中景')}\n比例：${String(imgPrm.ratio || '9:16')}\n透明：${imgPrm.transparent ? '是' : '否'}`);

  return {
    '配音清单_白页.md': fmtVoice('配音清单 · 白页', white),
    '配音清单_紫苏.md': fmtVoice('配音清单 · 紫苏', zisu),
    '配乐清单.md': bgmMd,
    '视频渲染清单.md': renderMd,
    '生图清单.md': imgMd,
  };
}

function splitMarkdownSections(md: string): Array<{ key: string; body: string[] }> {
  const out: Array<{ key: string; body: string[] }> = [];
  let cur: { key: string; body: string[] } | null = null;
  for (const raw of String(md || '').split(/\r?\n/)) {
    const ln = raw.trim();
    const h = ln.match(/^##\s+(.+)$/);
    if (h) {
      cur = { key: h[1].trim(), body: [] };
      out.push(cur);
    } else if (cur && ln) {
      cur.body.push(ln);
    }
  }
  return out;
}

export function applyMarkdownListToModules(name: string, text: string, mods: StudioModuleLike[]): string | null {
  const sections = splitMarkdownSections(text);
  const topLines = String(text || '')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#') && !l.startsWith('##'));

  if (name === '配音清单_白页.md' || name === '配音清单_紫苏.md') {
    const targetId = name === '配音清单_白页.md' ? 'voice-white' : 'voice-zisu';
    const mod = mods.find((m) => m.id === targetId);
    if (!mod) return '找不到对应配音模块';
    for (const ln of topLines.slice(0, 6)) {
      const mSpk = ln.match(/^音色[:：]\s*(.+)$/);
      if (mSpk) mod.params.speaker = mSpk[1].trim();
      const mTone = ln.match(/^默认语气[:：]\s*(.+)$/);
      if (mTone) mod.params.tone = mTone[1].trim();
    }
    const parsed: VoiceLine[] = [];
    sections.forEach((sec, idx) => {
      const numMatch = sec.key.match(/\d+/);
      const lineIdx = numMatch ? Number(numMatch[0]) : idx + 1;
      let lineText = '';
      let tone = '';
      for (const b of sec.body) {
        const mt = b.match(/^台词[:：]\s*(.+)$/);
        if (mt) lineText = mt[1].trim();
        const mo = b.match(/^语气[:：]\s*(.+)$/);
        if (mo) tone = mo[1].trim();
      }
      if (!lineText && sec.body.length) lineText = sec.body.join(' ');
      if (lineText) {
        parsed.push({ id: `l${idx + 1}`, line_index: lineIdx, text: lineText, tone });
      }
    });
    if (!parsed.length && text.trim()) {
      return `清单「${name}」没有解析出任何「## 01 / 台词：...」段落`;
    }
    mod.params.lines = parsed;
    mod.status = 'stale';
    return null;
  }

  if (name === '配乐清单.md') {
    const mod = mods.find((m) => m.id === 'bgm');
    if (!mod) return null;
    for (const raw of String(text || '').split(/\r?\n/)) {
      const ln = raw.trim();
      const mp = ln.match(/^(?:描述|提示词|prompt)[:：]\s*(.+)$/i);
      if (mp) mod.params.prompt = mp[1].trim();
      const ms = ln.match(/^(?:时长|seconds)[:：]\s*(\d+)/i);
      if (ms) mod.params.seconds = Math.max(10, Math.min(240, Number(ms[1]) || 75));
      const mt = ln.match(/^(?:步数|steps)[:：]\s*(\d+)/i);
      if (mt) mod.params.steps = Math.max(1, Math.min(32, Number(mt[1]) || 8));
      const md = ln.match(/^(?:种子|seed)[:：]\s*(\d+)/i);
      if (md) mod.params.seed = Number(md[1]) || 20261118;
    }
    mod.status = 'stale';
    return null;
  }

  if (name === '视频渲染清单.md') {
    const mod = mods.find((m) => m.id === 'compose');
    if (!mod) return null;
    const shots: StudioShot[] = [];
    sections.forEach((sec, idx) => {
      const numMatch = sec.key.match(/\d+/);
      const lineIdx = numMatch ? Number(numMatch[0]) : idx + 1;
      let render: 'web' | 'ppt' | 'static' = idx % 2 === 0 ? 'web' : 'ppt';
      let visual = '';
      let sub = '';
      let seconds = 5;
      for (const b of sec.body) {
        const mw = b.match(/^(?:方式|画面轨道|render)[:：]\s*(.+)$/i);
        if (mw) {
          const val = mw[1].toLowerCase();
          if (val.includes('ppt') || val.includes('卡片')) render = 'ppt';
          else if (val.includes('static') || val.includes('静')) render = 'static';
          else render = 'web';
        }
        const mDur = b.match(/^(?:时长|seconds)[:：]\s*(\d+(?:\.\d+)?)/i);
        if (mDur) seconds = Math.max(2, Math.min(30, Number(mDur[1]) || 5));
        const mv = b.match(/^(?:画面|visual)[:：]\s*(.+)$/i);
        if (mv) visual = mv[1].trim();
        const ms = b.match(/^(?:字幕|台词|text)[:：]\s*(.+)$/i);
        if (ms) sub = ms[1].trim();
      }
      shots.push({
        id: `s${String(lineIdx).padStart(2, '0')}`,
        line_index: lineIdx,
        render,
        text: sub || visual || `第 ${lineIdx} 镜`,
        visual: visual || '科技感动态排版',
        seconds,
      });
    });
    if (!shots.length && text.trim()) {
      return `清单「${name}」没有解析出任何「## 01」分镜段`;
    }
    mod.params.shots = shots;
    mod.status = 'stale';
    return null;
  }

  if (name === '生图清单.md') {
    const mod = mods.find((m) => m.id === 'image');
    if (!mod) return null;
    const items: Array<{ prompt: string; ratio: string; transparent: boolean }> = [];
    sections.forEach((sec) => {
      let prompt = '';
      let ratio = String(mod.params.ratio || '9:16');
      let transparent = false;
      for (const b of sec.body) {
        const mp = b.match(/^(?:提示词|prompt)[:：]\s*(.+)$/i);
        if (mp) prompt = mp[1].trim();
        const mr = b.match(/^(?:比例|ratio)[:：]\s*([\d:]+)/i);
        if (mr) ratio = mr[1].trim();
        const mt = b.match(/^(?:透明|transparent)[:：]\s*(.+)$/i);
        if (mt) transparent = /^(是|true|1|yes|开)/i.test(mt[1].trim());
      }
      if (prompt) items.push({ prompt, ratio, transparent });
    });
    mod.params.items = items;
    if (items.length) {
      mod.params.selected = 0;
      mod.params.prompt = items[0].prompt;
      mod.params.ratio = items[0].ratio;
      mod.params.transparent = items[0].transparent;
    }
    return null;
  }

  return null;
}

export interface ParsedScriptData {
  title?: string;
  desc?: string;
  tags?: string[];
  bgmPrompt?: string;
  bgmSeconds?: number;
  whiteLines: VoiceLine[];
  zisuLines: VoiceLine[];
  shots: StudioShot[];
  imageItems: Array<{ prompt: string; ratio: string; transparent: boolean }>;
}

export function parseImportedScript(rawText: string): ParsedScriptData {
  const trimmed = rawText.trim();
  const whiteLines: VoiceLine[] = [];
  const zisuLines: VoiceLine[] = [];
  const shots: StudioShot[] = [];
  const imageItems: Array<{ prompt: string; ratio: string; transparent: boolean }> = [];

  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    const data = JSON.parse(trimmed) as Record<string, unknown>;
    const rawShots = Array.isArray(data.shots) ? (data.shots as Array<Record<string, unknown>>) : [];
    const bgmObj = (data.bgm || {}) as Record<string, unknown>;
    const bgmSegs = Array.isArray(bgmObj.segments) ? (bgmObj.segments as Array<Record<string, unknown>>) : [];
    const bgmPrompt = String(bgmObj.prompt || bgmSegs[0]?.prompt || 'upbeat electronic, no vocals');
    const bgmSeconds = Math.max(10, Math.min(240, Number(bgmObj.seconds || bgmSegs[0]?.seconds || 75)));

    rawShots.forEach((s, i) => {
      const idx = Number(s.line_index) || i + 1;
      const v = (s.voice && typeof s.voice === 'object' ? (s.voice as Record<string, unknown>) : {}) || {};
      const img = (s.image && typeof s.image === 'object' ? (s.image as Record<string, unknown>) : {}) || {};
      const role = String(v.role || s.role || (idx % 2 === 1 ? '白页' : '紫苏'));
      const text = String(v.text || s.text || '');
      const tone = String(v.tone || s.tone || '');
      const renderRaw = String(s.render || (idx % 2 === 1 ? 'web' : 'ppt')).toLowerCase();
      const render: 'web' | 'ppt' | 'static' = renderRaw === 'ppt' ? 'ppt' : renderRaw === 'static' ? 'static' : 'web';
      const sec = Math.max(2, Math.min(25, Number(s.seconds) || Math.ceil(Math.max(4, text.length) / 4.5)));
      const visual = String(s.visual || img.prompt || '现代感数据卡片排版');
      if (text) {
        const lineObj: VoiceLine = { id: `l${idx}`, line_index: idx, text, tone };
        if (role.includes('紫苏')) zisuLines.push(lineObj);
        else whiteLines.push(lineObj);
      }
      shots.push({ id: String(s.id || `s${String(idx).padStart(2, '0')}`), line_index: idx, render, text: text || visual, visual, seconds: sec });
      if (img.prompt) {
        imageItems.push({ prompt: String(img.prompt), ratio: String(img.ratio || '9:16'), transparent: Boolean(img.transparent) });
      }
    });

    return {
      title: typeof data.title === 'string' ? data.title : undefined,
      desc: typeof data.desc === 'string' ? data.desc : undefined,
      tags: Array.isArray(data.tags) ? data.tags.map(String) : undefined,
      bgmPrompt,
      bgmSeconds,
      whiteLines,
      zisuLines,
      shots,
      imageItems,
    };
  }

  // Check Markdown "## 分镜" blocks vs simple dialogue lines
  if (/^##\s+分镜/m.test(trimmed)) {
    let title: string | undefined;
    let desc: string | undefined;
    let tags: string[] | undefined;
    let bgmPrompt: string | undefined;
    let bgmSeconds: number | undefined;
    const headerLines = trimmed.split(/^##\s+/m)[0].split(/\r?\n/);
    for (const h of headerLines) {
      const mTitle = h.match(/^#\s+(.+)$/);
      if (mTitle && !title) title = mTitle[1].trim();
      const mDesc = h.match(/^简介[:：]\s*(.+)$/);
      if (mDesc) desc = mDesc[1].trim();
      const mTags = h.match(/^话题[:：]\s*(.+)$/);
      if (mTags) tags = mTags[1].trim().split(/[\s,，]+/).filter(Boolean);
    }
    const sections = splitMarkdownSections(trimmed);
    let idx = 1;
    for (const sec of sections) {
      if (sec.key.startsWith('配乐')) {
        for (const b of sec.body) {
          const mp = b.match(/^(?:描述|提示词)[:：]\s*(.+)$/);
          if (mp) bgmPrompt = mp[1].trim();
          const ms = b.match(/^时长[:：]\s*(\d+)/);
          if (ms) bgmSeconds = Math.max(10, Math.min(240, Number(ms[1]) || 75));
        }
        continue;
      }
      if (sec.key.startsWith('分镜')) {
        let render: 'web' | 'ppt' | 'static' = idx % 2 === 1 ? 'web' : 'ppt';
        let secDur = 5;
        let visual = '';
        let role = '白页';
        let tone = '';
        let text = '';
        for (const b of sec.body) {
          const mr = b.match(/^(?:画面轨道|方式)[:：]\s*(.+)$/);
          if (mr) render = /ppt|卡片/i.test(mr[1]) ? 'ppt' : /静|static/i.test(mr[1]) ? 'static' : 'web';
          const md = b.match(/^时长[:：]\s*(\d+)/);
          if (md) secDur = Math.max(2, Math.min(25, Number(md[1]) || 5));
          const mv = b.match(/^画面[:：]\s*(.+)$/);
          if (mv) visual = mv[1].trim();
          const mRole = b.match(/^角色[:：]\s*(.+)$/);
          if (mRole) role = mRole[1].trim();
          const mTone = b.match(/^语气[:：]\s*(.+)$/);
          if (mTone) tone = mTone[1].trim();
          const mTxt = b.match(/^台词[:：]\s*(.+)$/);
          if (mTxt) text = mTxt[1].trim();
        }
        if (text) {
          const obj: VoiceLine = { id: `l${idx}`, line_index: idx, text, tone };
          if (role.includes('紫苏')) zisuLines.push(obj);
          else whiteLines.push(obj);
        }
        shots.push({ id: `s${String(idx).padStart(2, '0')}`, line_index: idx, render, text: text || visual, visual: visual || '信息排版', seconds: secDur });
        if (visual) imageItems.push({ prompt: visual, ratio: '9:16', transparent: false });
        idx++;
      }
    }
    return { title, desc, tags, bgmPrompt, bgmSeconds, whiteLines, zisuLines, shots, imageItems };
  }

  // Plain line-by-line format
  let title: string | undefined;
  let idx = 1;
  for (const raw of trimmed.split(/\r?\n/)) {
    const ln = raw.trim();
    if (!ln) continue;
    if (ln.startsWith('#')) {
      const t = ln.replace(/^#+\s*/, '').trim();
      if (t && !title && idx === 1) title = t;
      continue;
    }
    const clean = ln.replace(/^[-*]\s*/, '');
    const isZisu = /^(紫苏|B)[:：]/.test(clean);
    const body = clean.replace(/^(白页|紫苏|旁白|A|B)[:：]\s*/, '').trim();
    if (!body) continue;
    const obj: VoiceLine = { id: `l${idx}`, line_index: idx, text: body, tone: isZisu ? '轻松调侃' : '冷静吐槽' };
    if (isZisu) zisuLines.push(obj);
    else whiteLines.push(obj);
    shots.push({
      id: `s${String(idx).padStart(2, '0')}`,
      line_index: idx,
      render: idx % 2 === 1 ? 'web' : 'ppt',
      text: body,
      visual: '自动分镜排版',
      seconds: Math.max(3, Math.min(12, Math.ceil(body.length / 4.5))),
    });
    idx++;
  }

  if (!whiteLines.length && !zisuLines.length) {
    const fallback = trimmed.slice(0, 120) || '示例台词';
    whiteLines.push({ id: 'l1', line_index: 1, text: fallback, tone: '冷静吐槽' });
    shots.push({ id: 's01', line_index: 1, render: 'web', text: fallback, visual: '文字排版', seconds: 5 });
  }

  return { title, whiteLines, zisuLines, shots, imageItems };
}

// ---------------- Real FFmpeg Composition Helper ----------------

export interface FfmpegComposeInput {
  pid: string;
  shots: StudioShot[];
  frames: Buffer[];
  voiceWav?: Buffer;
  bgmWav?: Buffer;
  ratio: string;
  fps: number;
  bgmVolume: number;
  duckDepth: number;
  fade: number;
  subtitle: boolean;
  onProgress: (info: { pct: number; frame: number; fps: number; logLine?: string }) => void;
  registerProc: (proc: ChildProcess) => void;
  isAborted: () => boolean;
}

export async function runFfmpegCompose(input: FfmpegComposeInput): Promise<{ mp4: Buffer; duration: number; resolution: string; log: string }> {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), `eao-st-${input.pid.replace(/[^a-zA-Z0-9_-]/g, '')}-`));
  const logs: string[] = [];
  const log = (s: string) => {
    logs.push(s);
    if (logs.length > 40) logs.shift();
  };

  try {
    const [w, h] = dimsForRatio(input.ratio, 720);
    const fps = Math.max(12, Math.min(30, Math.round(input.fps) || 24));
    const totalShotDur = Math.max(2, Math.min(20, input.shots.reduce((a, s) => a + (Number(s.seconds) || 4), 0) || 6));
    const totalFrames = Math.max(1, Math.round(totalShotDur * fps));

    // Write image frames + concat file
    const concatLines: string[] = [];
    const usableFrames = input.frames.length ? input.frames : [createPngBuffer(w, h)];
    const perFrameDur = Math.max(0.5, totalShotDur / usableFrames.length);

    for (let i = 0; i < usableFrames.length; i++) {
      const fPath = path.join(tmpDir, `frame_${i}.png`);
      fs.writeFileSync(fPath, usableFrames[i]);
      const escaped = fPath.replace(/\\/g, '/').replace(/'/g, "\\'");
      concatLines.push(`file '${escaped}'`);
      concatLines.push(`duration ${perFrameDur.toFixed(3)}`);
    }
    const lastEsc = path.join(tmpDir, `frame_${usableFrames.length - 1}.png`).replace(/\\/g, '/').replace(/'/g, "\\'");
    concatLines.push(`file '${lastEsc}'`);
    const concatPath = path.join(tmpDir, 'frames.txt');
    fs.writeFileSync(concatPath, concatLines.join('\n'), 'utf8');

    const voicePath = path.join(tmpDir, 'voice.wav');
    fs.writeFileSync(voicePath, input.voiceWav || createWavBuffer(totalShotDur, 'silence').buf);

    const hasBgm = Boolean(input.bgmWav && input.bgmWav.length > 44 && input.bgmVolume > 0.001);
    const bgmPath = path.join(tmpDir, 'bgm.wav');
    if (hasBgm && input.bgmWav) {
      fs.writeFileSync(bgmPath, input.bgmWav);
    }

    const outPath = path.join(tmpDir, 'out.mp4');
    const bgmVol = Math.max(0, Math.min(1, Number(input.bgmVolume) || 0));
    const fadeSec = Math.max(0, Math.min(totalShotDur * 0.5, Number(input.fade) || 0));

    const args: string[] = [
      '-y',
      '-f',
      'concat',
      '-safe',
      '0',
      '-i',
      concatPath,
      '-i',
      voicePath,
    ];
    if (hasBgm) {
      args.push('-stream_loop', '-1', '-i', bgmPath);
    }

    const vf = `scale=${w}:${h}:force_original_aspect_ratio=decrease,pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2:color=#0a121c,fps=${fps},format=yuv420p`;
    if (hasBgm) {
      const fadeFilter = fadeSec > 0.1 ? `,afade=t=out:st=${Math.max(0, totalShotDur - fadeSec).toFixed(2)}:d=${fadeSec.toFixed(2)}` : '';
      const af = `[1:a]aresample=24000,apad[v];[2:a]aresample=24000,volume=${bgmVol.toFixed(3)}${fadeFilter}[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[a]`;
      args.push('-filter_complex', `[0:v]${vf}[v];${af}`, '-map', '[v]', '-map', '[a]');
    } else {
      args.push('-vf', vf, '-map', '0:v:0', '-map', '1:a:0');
    }

    args.push(
      '-t',
      totalShotDur.toFixed(2),
      '-c:v',
      'libx264',
      '-preset',
      'ultrafast',
      '-pix_fmt',
      'yuv420p',
      '-c:a',
      'aac',
      '-b:a',
      '128k',
      '-movflags',
      '+faststart',
      '-progress',
      'pipe:1',
      '-nostats',
      outPath
    );

    log(`ffmpeg ${w}x${h} @ ${fps}fps, bgmVol=${Math.round(bgmVol * 100)}%, fade=${fadeSec}s`);
    input.onProgress({ pct: 10, frame: 0, fps, logLine: logs.join('\n') });

    await new Promise<void>((resolve, reject) => {
      const proc = spawn('ffmpeg', args, { stdio: ['ignore', 'pipe', 'pipe'] });
      input.registerProc(proc);

      let outBuf = '';
      let curFrame = 0;
      let curFps = fps;

      proc.stdout.on('data', (chunk: Buffer) => {
        outBuf += chunk.toString('utf8');
        const lines = outBuf.split(/\r?\n/);
        outBuf = lines.pop() || '';
        for (const l of lines) {
          const kv = l.split('=');
          if (kv.length !== 2) continue;
          const [k, v] = kv;
          if (k === 'frame') curFrame = Number(v) || curFrame;
          else if (k === 'fps') curFps = Number(v) || curFps;
          else if (k === 'progress') {
            const pct = v.trim() === 'end' ? 98 : Math.min(96, Math.max(12, Math.round((curFrame / totalFrames) * 100)));
            input.onProgress({ pct, frame: curFrame, fps: curFps, logLine: `${logs.join('\n')}\nframe=${curFrame}/${totalFrames} fps=${curFps.toFixed(1)}` });
          }
        }
      });

      proc.stderr.on('data', (chunk: Buffer) => {
        const s = chunk.toString('utf8').trim();
        if (s) {
          const tail = s.split(/\r?\n/).slice(-3);
          for (const tl of tail) log(tl.slice(0, 140));
        }
      });

      proc.on('error', (err) => reject(err));
      proc.on('close', (code) => {
        if (input.isAborted()) reject(new Error('用户已停止合成'));
        else if (code !== 0) reject(new Error(`FFmpeg 退出码 ${code}: ${logs.slice(-2).join(' | ')}`));
        else resolve();
      });
    });

    const mp4 = fs.readFileSync(outPath);
    return { mp4, duration: totalShotDur, resolution: `${w}x${h}`, log: logs.join('\n') };
  } finally {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // ignore temp cleanup errors
    }
  }
}
