import path from 'node:path';
import { sniffMediaHeader } from './studio-runtime.ts';

export interface CloudImageOptions {
  apiKey: string;
  baseUrl: string;
  model: string;
  prompt: string;
  ratio?: string;
  tier?: string;
  quality?: string;
  sizePx?: string;
  transparent?: boolean;
  refs?: string[]; // data URIs or http URLs
}

export interface CloudImageResult {
  buf: Buffer;
  ext: '.png' | '.jpg' | '.webp' | '.gif' | '.svg';
  usd: number;
}

export interface BailianTtsOptions {
  apiKey: string;
  baseUrl: string;
  model: string;
  text: string;
  voice: string;
  instruction?: string;
  rate?: number;
  pitch?: number;
  volume?: number;
  lang?: string;
  hotfix?: { pronunciation?: Record<string, string>; replace?: Record<string, string> };
}

export interface BailianTtsResult {
  wavBuf: Buffer;
  duration: number;
  characters: number;
  words: Array<{ text: string; begin_time: number; end_time: number }>;
}

const VIP_SIZES: Record<string, Record<string, string>> = {
  '1k': {
    '16:9': '1280x720', '9:16': '720x1280', '1:1': '1280x1280', '4:3': '1280x960', '3:4': '960x1280',
    '3:2': '1280x848', '2:3': '848x1280', '5:4': '1280x1024', '4:5': '1024x1280', '21:9': '1280x544',
  },
  '2k': {
    '16:9': '2048x1152', '9:16': '1152x2048', '1:1': '2048x2048', '4:3': '2048x1536', '3:4': '1536x2048',
    '3:2': '2048x1360', '2:3': '1360x2048', '5:4': '2048x1632', '4:5': '1632x2048', '21:9': '2048x864',
  },
  '4k': {
    '16:9': '3840x2160', '9:16': '2160x3840', '1:1': '2880x2880', '4:3': '3312x2480', '3:4': '2480x3312',
    '3:2': '3520x2336', '2:3': '2336x3520', '5:4': '3216x2560', '4:5': '2560x3216', '21:9': '3840x1632',
  },
};

function sanitizeErr(msg: string, secret?: string): string {
  let s = String(msg || '');
  if (secret && secret.length > 6) {
    s = s.split(secret).join('***');
  }
  return s.replace(/sk-[a-zA-Z0-9_-]{6,}/g, 'sk-***').slice(0, 300);
}

function explainApiError(status: number, bodyText: string, secret: string): string {
  let raw = bodyText;
  try {
    const j = JSON.parse(bodyText) as { error?: { message?: string; code?: string }; message?: string; code?: string; detail?: string };
    raw = j.error?.message || j.message || j.detail || bodyText;
  } catch {
    // keep raw text
  }
  const clean = sanitizeErr(raw, secret);
  if (status === 401 || /invalid.?api.?key|unauthorized/i.test(clean)) return `API Key 无效或未授权（401）：${clean}`;
  if (status === 402 || /insufficient|quota|arrearage|balance/i.test(clean)) return `账户余额不足或已欠费（${status}）：${clean}`;
  if (status === 403 || /access.?denied/i.test(clean)) return `没有该模型或接口权限（403）：${clean}`;
  if (status === 429 || /rate|throttl|limit/i.test(clean)) return `请求太快触发限流（429）：${clean}`;
  if (status === 404) return `找不到模型或接口地址不对（404）：${clean}`;
  return `云端返回错误（HTTP ${status}）：${clean}`;
}

function detectImageExt(buf: Buffer): '.png' | '.jpg' | '.webp' | '.gif' | '.svg' {
  if (buf.length >= 4 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) return '.png';
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return '.jpg';
  if (buf.length >= 12 && buf.subarray(0, 4).toString('ascii') === 'RIFF' && buf.subarray(8, 12).toString('ascii') === 'WEBP') return '.webp';
  if (buf.length >= 6 && buf.subarray(0, 3).toString('ascii') === 'GIF') return '.gif';
  if (buf.subarray(0, 256).toString('utf8').toLowerCase().includes('<svg')) return '.svg';
  return '.png';
}

function parseDataUri(uri: string): { mime: string; buf: Buffer } | null {
  const m = /^data:([^;]+);base64,([A-Za-z0-9+/=\r\n]+)$/.exec(uri.trim());
  if (!m) return null;
  return { mime: m[1], buf: Buffer.from(m[2], 'base64') };
}

export async function fetchApiyiModels(baseUrl: string, apiKey: string): Promise<Array<{ id: string; owned_by?: string }>> {
  const base = (baseUrl || 'https://api.apiyi.com/v1').replace(/\/+$/, '');
  const resp = await fetch(`${base}/models`, {
    headers: { Authorization: `Bearer ${apiKey}` },
    signal: AbortSignal.timeout(15000),
  });
  const text = await resp.text();
  if (!resp.ok) throw new Error(explainApiError(resp.status, text, apiKey));
  const j = JSON.parse(text) as { data?: Array<{ id: string; owned_by?: string }> };
  const imgRe = /(gpt-image|dall-e|gemini.*image|nano-banana|seedream|flux|grok.*image|ideogram|recraft|midjourney|imagen)/i;
  return (j.data || []).filter((m) => imgRe.test(m.id));
}

export async function callApiyiImage(opts: CloudImageOptions): Promise<CloudImageResult> {
  const apiKey = opts.apiKey.trim();
  if (!apiKey) throw new Error('还没填 API易 Key，请先到 设置 › 云端 填写');
  const base = (opts.baseUrl || 'https://api.apiyi.com/v1').replace(/\/+$/, '');
  const rootBase = base.replace(/\/v1\/?$/, '');
  const model = (opts.model || 'gpt-image-2.5-sunburst-vip').trim();
  const ratio = opts.ratio || '9:16';
  const tier = (opts.tier || '2k').toLowerCase();
  const sizePx = opts.sizePx || (VIP_SIZES[tier] || VIP_SIZES['2k'])[ratio] || '1152x2048';
  const refs = (opts.refs || []).filter(Boolean);

  // 1. Gemini / Nano Banana native protocol
  if (/gemini|nano-banana|imagen/i.test(model)) {
    const parts: Array<Record<string, unknown>> = [];
    for (const r of refs.slice(0, 14)) {
      const parsed = parseDataUri(r);
      if (parsed) {
        parts.push({ inlineData: { mimeType: parsed.mime, data: parsed.buf.toString('base64') } });
      }
    }
    parts.push({ text: opts.prompt });
    const imgSize = tier === '4k' ? '4K' : tier === '1k' ? '1K' : '2K';
    const resp = await fetch(`${rootBase}/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
        'x-goog-api-key': apiKey,
      },
      body: JSON.stringify({
        contents: [{ role: 'user', parts }],
        generationConfig: {
          responseModalities: ['IMAGE'],
          imageConfig: { aspectRatio: ratio, imageSize: imgSize },
        },
      }),
      signal: AbortSignal.timeout(180000),
    });
    const text = await resp.text();
    if (!resp.ok) throw new Error(explainApiError(resp.status, text, apiKey));
    const j = JSON.parse(text) as {
      candidates?: Array<{
        finishReason?: string;
        content?: { parts?: Array<{ inlineData?: { data?: string }; inline_data?: { data?: string } }> };
      }>;
    };
    const cand = j.candidates?.[0];
    if (cand?.finishReason === 'IMAGE_SAFETY') {
      throw new Error('内容安全审核未通过（IMAGE_SAFETY），请修改提示词后再试');
    }
    const imgParts = (cand?.content?.parts || []).filter((p) => p.inlineData?.data || p.inline_data?.data);
    const last = imgParts[imgParts.length - 1];
    const b64 = last?.inlineData?.data || last?.inline_data?.data;
    if (!b64) throw new Error('Gemini 接口返回成功，但未包含图片数据');
    const buf = Buffer.from(b64, 'base64');
    return { buf, ext: detectImageExt(buf), usd: 0.055 };
  }

  // 2. Seedream / Flux / OpenAI-compatible protocol
  const isSeedream = /seedream|doubao/i.test(model);
  const isFlux = /flux/i.test(model);
  const isSunburstOrReverse = /sunburst|vip|-all$/i.test(model);
  const isOfficialGpt = /^gpt-image-1(\.\d+)?$/i.test(model);

  let resp: Response;
  if (!isSeedream && !isFlux && refs.length > 0) {
    // OpenAI /images/edits multipart with reference image(s)
    const fd = new FormData();
    fd.append('model', model);
    fd.append('prompt', opts.prompt);
    fd.append('size', sizePx);
    if (!isOfficialGpt) fd.append('response_format', 'b64_json');
    if (opts.quality && opts.quality !== 'auto') fd.append('quality', opts.quality);
    if (opts.transparent) fd.append('background', 'transparent');
    const fieldName = refs.length === 1 ? 'image' : 'image[]';
    for (let i = 0; i < refs.length; i++) {
      const parsed = parseDataUri(refs[i]);
      if (parsed) {
        const ext = parsed.mime.includes('jpeg') ? 'jpg' : 'png';
        fd.append(fieldName, new Blob([new Uint8Array(parsed.buf)], { type: parsed.mime }), `ref_${i}.${ext}`);
      }
    }
    resp = await fetch(`${base}/images/edits`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}` },
      body: fd,
      signal: AbortSignal.timeout(180000),
    });
  } else {
    const payload: Record<string, unknown> = {
      model,
      prompt: /all$/i.test(model) ? `Aspect ratio ${ratio}. ${opts.prompt}` : opts.prompt,
    };
    if (!/all$/i.test(model)) payload.size = sizePx;
    if (isSeedream) {
      payload.watermark = false;
      if (/seedream-5/i.test(model)) payload.output_format = 'png';
      if (refs.length) {
        payload.image = refs;
        if (/(?:^|[-_.])(4|lite)\b/i.test(model)) payload.sequential_image_generation = 'disabled';
      }
    } else if (isFlux) {
      refs.slice(0, 8).forEach((r, idx) => {
        payload[idx === 0 ? 'input_image' : `input_image_${idx + 1}`] = r;
      });
    } else {
      // OpenAI / Sunburst VIP: do NOT send n for VIP or reverse models
      if (!isSunburstOrReverse && !isOfficialGpt) payload.n = 1;
      if (isOfficialGpt) payload.output_format = 'png';
      else payload.response_format = 'b64_json';
      if (opts.quality && ['auto', 'low', 'medium', 'high'].includes(opts.quality)) {
        payload.quality = opts.quality;
      }
      if (opts.transparent) payload.background = 'transparent';
    }
    resp = await fetch(`${base}/images/generations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(180000),
    });
  }

  const text = await resp.text();
  if (!resp.ok) throw new Error(explainApiError(resp.status, text, apiKey));
  let j: { data?: Array<{ b64_json?: string; url?: string }>; error?: { message?: string } };
  try {
    j = JSON.parse(text) as { data?: Array<{ b64_json?: string; url?: string }>; error?: { message?: string } };
  } catch {
    throw new Error(`生图接口返回了非 JSON 响应：${sanitizeErr(text, apiKey)}`);
  }
  const item = j.data?.[0];
  if (!item) throw new Error(j.error?.message ? sanitizeErr(j.error.message, apiKey) : '生图返回空结果');

  let buf: Buffer;
  if (item.b64_json) {
    buf = Buffer.from(item.b64_json, 'base64');
  } else if (item.url) {
    const imgResp = await fetch(item.url, { signal: AbortSignal.timeout(60000) });
    if (!imgResp.ok) throw new Error(`下载生成图失败（HTTP ${imgResp.status}）`);
    buf = Buffer.from(await imgResp.arrayBuffer());
  } else {
    throw new Error('接口未返回图片内容（无 b64_json 也无 url）');
  }

  const ext = detectImageExt(buf);
  const bad = sniffMediaHeader(`out${ext}`, buf);
  if (bad) throw new Error(`返回图片数据校验失败：${bad}`);
  return { buf, ext, usd: isSunburstOrReverse ? 0.03 : 0.04 };
}

function wrapMono24kWav(pcmBuf: Buffer): Buffer {
  const wav = Buffer.alloc(44 + pcmBuf.length);
  wav.write('RIFF', 0);
  wav.writeUInt32LE(36 + pcmBuf.length, 4);
  wav.write('WAVE', 8);
  wav.write('fmt ', 12);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(24000, 24);
  wav.writeUInt32LE(48000, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write('data', 36);
  wav.writeUInt32LE(pcmBuf.length, 40);
  pcmBuf.copy(wav, 44);
  return wav;
}

export async function callBailianTts(opts: BailianTtsOptions): Promise<BailianTtsResult> {
  const apiKey = opts.apiKey.trim();
  if (!apiKey) throw new Error('还没填百炼 API Key，请先到 设置 › 云端 填写');
  const base = (opts.baseUrl || 'https://dashscope.aliyuncs.com/api/v1').replace(/\/+$/, '');
  const model = (opts.model || 'qwen-audio-3.1-tts-plus').trim();
  const voice = (opts.voice || 'longanlingxin_v3.1').trim();

  const attempt = async (withTimestamps: boolean): Promise<BailianTtsResult> => {
    const input: Record<string, unknown> = {
      text: opts.text,
      voice,
      format: 'pcm',
      sample_rate: 24000,
    };
    if (withTimestamps) input.word_timestamp_enabled = true;
    if (opts.instruction && opts.instruction.trim()) input.instruction = opts.instruction.trim().slice(0, 100);
    if (typeof opts.rate === 'number' && opts.rate !== 1) input.rate = opts.rate;
    if (typeof opts.pitch === 'number' && opts.pitch !== 1) input.pitch = opts.pitch;
    if (typeof opts.volume === 'number' && opts.volume !== 50) input.volume = opts.volume;
    if (opts.lang) input.language_hints = [opts.lang];

    const hotArr: Array<Record<string, string>> = [];
    if (opts.hotfix?.pronunciation) {
      for (const [w, p] of Object.entries(opts.hotfix.pronunciation)) {
        if (w && p && opts.text.includes(w)) hotArr.push({ [w]: p });
      }
    }
    if (opts.hotfix?.replace) {
      for (const [w, rep] of Object.entries(opts.hotfix.replace)) {
        if (w && rep && opts.text.includes(w)) hotArr.push({ [w]: rep });
      }
    }
    if (hotArr.length) input.hot_fix = hotArr.slice(0, 200);

    const resp = await fetch(`${base}/services/audio/tts/SpeechSynthesizer`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'X-DashScope-SSE': 'enable',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({ model, input }),
      signal: AbortSignal.timeout(120000),
    });

    const raw = await resp.text();
    if (!resp.ok) {
      if (withTimestamps && /word_timestamp|InvalidParameter/i.test(raw)) {
        return attempt(false);
      }
      throw new Error(explainApiError(resp.status, raw, apiKey));
    }

    const pcmChunks: Buffer[] = [];
    const words: Array<{ text: string; begin_time: number; end_time: number }> = [];
    let characters = 0;

    // Parse SSE lines or single JSON payload
    const lines = raw.split(/\r?\n/);
    for (const ln of lines) {
      const t = ln.trim();
      if (!t) continue;
      const jsonStr = t.startsWith('data:') ? t.slice(5).trim() : t.startsWith('{') ? t : '';
      if (!jsonStr) continue;
      try {
        const evt = JSON.parse(jsonStr) as {
          code?: string;
          message?: string;
          output?: {
            audio?: { data?: string; url?: string };
            sentence?: { words?: Array<{ text?: string; begin_time?: number; end_time?: number }> };
          };
          usage?: { characters?: number };
        };
        if (evt.code && evt.code !== 'Success') {
          if (withTimestamps && /word_timestamp|InvalidParameter/i.test(evt.message || evt.code)) {
            return attempt(false);
          }
          throw new Error(`百炼合成失败（${evt.code}）：${sanitizeErr(evt.message || '', apiKey)}`);
        }
        if (evt.output?.audio?.data) {
          pcmChunks.push(Buffer.from(evt.output.audio.data, 'base64'));
        } else if (evt.output?.audio?.url && !pcmChunks.length) {
          const dl = await fetch(evt.output.audio.url, { signal: AbortSignal.timeout(45000) });
          if (dl.ok) {
            const b = Buffer.from(await dl.arrayBuffer());
            if (b.subarray(0, 4).toString('ascii') === 'RIFF') {
              const dur = Math.max(0.2, (b.length - 44) / 48000);
              return { wavBuf: b, duration: Math.round(dur * 100) / 100, characters: evt.usage?.characters || opts.text.length, words };
            }
            pcmChunks.push(b);
          }
        }
        if (Array.isArray(evt.output?.sentence?.words)) {
          for (const w of evt.output!.sentence!.words!) {
            if (w.text && w.begin_time != null && w.end_time != null) {
              words.push({ text: w.text, begin_time: w.begin_time, end_time: w.end_time });
            }
          }
        }
        if (evt.usage?.characters) characters = evt.usage.characters;
      } catch (parseErr) {
        if (parseErr instanceof Error && parseErr.message.startsWith('百炼合成失败')) throw parseErr;
      }
    }

    if (!pcmChunks.length) {
      throw new Error('百炼未返回音频数据，请确认音色与模型是否匹配');
    }
    const pcmAll = Buffer.concat(pcmChunks);
    const wavBuf = wrapMono24kWav(pcmAll);
    const duration = Math.round((pcmAll.length / 48000) * 100) / 100;
    return { wavBuf, duration, characters: characters || opts.text.length, words };
  };

  return attempt(true);
}

export async function callBailianSyncVoices(baseUrl: string, apiKey: string): Promise<Array<{ id: string; name: string; kind: string; status: string }>> {
  const base = (baseUrl || 'https://dashscope.aliyuncs.com/api/v1').replace(/\/+$/, '');
  const resp = await fetch(`${base}/services/audio/tts/customization`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'voice-enrollment', input: { action: 'list_voice', page_index: 0, page_size: 50 } }),
    signal: AbortSignal.timeout(20000),
  });
  const text = await resp.text();
  if (!resp.ok) throw new Error(explainApiError(resp.status, text, apiKey));
  const j = JSON.parse(text) as { output?: { voice_list?: Array<{ voice?: string; status?: string; voice_type?: string }> } };
  return (j.output?.voice_list || []).map((v) => ({
    id: String(v.voice || ''),
    name: String(v.voice || '').slice(-10),
    kind: v.voice_type === 'clone' ? 'clone' : 'design',
    status: String(v.status || 'OK'),
  }));
}

export function guessSafeName(raw: string): string {
  return path.basename(raw).replace(/[^a-zA-Z0-9._\u4e00-\u9fa5-]/g, '_') || 'output.png';
}
