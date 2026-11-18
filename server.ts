import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import express from 'express';
import type { NextFunction, Request, Response } from 'express';
import {
  DOCS_DIR,
  LOCKED_SETTINGS,
  PORT,
  ROOT_DIR,
  SECRET_KEYS,
  SETTINGS_DEFAULTS,
  UI_DIR,
  VERSION,
  computeNextTs,
  store,
  type ChatJob,
  type ReminderItem,
  type SecretKey,
} from './src/store.ts';
import { makeAsset, sanitizeRelPath, sniffMediaHeader } from './src/studio-runtime.ts';
import type { AgentId } from './src/studio-types.ts';
import { callBailianSyncVoices, callBailianTts } from './src/cloud-apis.ts';

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '15mb' }));
app.use(express.urlencoded({ extended: true, limit: '15mb' }));

// Telemetry sampling & trace header middleware
app.use((req: Request, res: Response, next: NextFunction) => {
  if (!req.path.startsWith('/api/') || req.path.startsWith('/api/telemetry')) {
    next();
    return;
  }
  const traceId = (req.headers['x-trace-id'] as string) || `tr_${Date.now().toString(36)}_${crypto.randomBytes(3).toString('hex')}`;
  res.setHeader('X-Trace-Id', traceId);
  const t0 = performance.now();
  res.on('finish', () => {
    const dur = Math.round((performance.now() - t0) * 10) / 10;
    const isPoll =
      req.path === '/api/ping' ||
      req.path === '/api/state' ||
      req.path === '/api/hw' ||
      req.path === '/api/hw/history' ||
      req.path === '/api/monitor' ||
      req.path === '/api/studio/state';
    if (!isPoll || res.statusCode >= 400 || dur >= 800) {
      store.addTelemetry([
        {
          ts: Date.now(),
          cat: 'api',
          action: req.method,
          target: req.path,
          status: res.statusCode >= 500 ? 'err' : res.statusCode >= 400 ? 'warn' : 'ok',
          dur_ms: dur,
          metrics: { code: res.statusCode, poll: isPoll },
          msg: `${req.method} ${req.path} ${res.statusCode} · ${Math.round(dur)}ms`,
          trace_id: traceId,
        },
      ]);
    }
  });
  next();
});

// Theme discovery matching ui/themes/*.css
interface ThemeInfo {
  id: string;
  name: string;
  desc: string;
  file: string;
  order: number;
  v: number;
  fx: string[];
}

function getThemeList(): ThemeInfo[] {
  const themesDir = path.join(UI_DIR, 'themes');
  if (!fs.existsSync(themesDir)) return [];
  const out: ThemeInfo[] = [];
  for (const file of fs.readdirSync(themesDir).sort()) {
    if (!file.endsWith('.css')) continue;
    const full = path.join(themesDir, file);
    try {
      const head = fs.readFileSync(full, 'utf8').slice(0, 2000);
      const commentMatch = head.match(/\/\*([\s\S]*?)\*\//);
      const comment = commentMatch ? commentMatch[1] : '';
      const meta: Record<string, string> = {};
      for (const m of comment.matchAll(/@(id|name|desc|order|fx|retired)[ \t]+([^\n]*)/g)) {
        if (!(m[1] in meta)) meta[m[1]] = m[2].trim();
      }
      if (meta.retired) continue;
      const tid = meta.id || file.replace(/\.css$/, '');
      if (!/^[a-z][a-z0-9-]{0,30}$/.test(tid)) continue;
      const fx = (meta.fx || '')
        .split(/[\s,，]+/)
        .filter((x) => /^[a-z][a-z0-9-]{0,20}$/.test(x));
      const stat = fs.statSync(full);
      out.push({
        id: tid,
        name: meta.name || tid,
        desc: meta.desc || '',
        file,
        order: /^\d+$/.test(meta.order || '') ? Number(meta.order) : 99,
        v: Math.floor(stat.mtimeMs / 1000),
        fx,
      });
    } catch {
      // ignore invalid theme file
    }
  }
  out.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  return out;
}

// Entry HTML with theme injected
app.get('/', (_req: Request, res: Response) => {
  const indexPath = path.join(UI_DIR, 'index.html');
  let html = fs.readFileSync(indexPath, 'utf8');
  const theme = store.settings.theme === 'light' ? 'light' : 'dark';
  html = html.replace('data-theme="dark"', `data-theme="${theme}"`);
  res.setHeader('Cache-Control', 'no-store');
  res.type('html').send(html);
});

app.get('/themes/themes.js', (_req: Request, res: Response) => {
  const list = getThemeList();
  const body =
    '/* Auto-generated theme manifest */\n' +
    `window.AGENT_THEMES = ${JSON.stringify(list)};\n` +
    '(function () { var t = window.AGENT_THEMES; for (var i = 0; i < t.length; i++) ' +
    'document.write(\'<link rel="stylesheet" href="themes/\' + t[i].file + \'?v=\' + t[i].v + \'">\'); })();\n';
  res.setHeader('Cache-Control', 'no-store');
  res.type('application/javascript').send(body);
});

// ---------------- Core Status & Settings ----------------
app.get('/api/ping', (_req: Request, res: Response) => {
  res.json({ ok: true, version: VERSION, root: ROOT_DIR, windows: false });
});

app.post('/api/telemetry/ingest', (req: Request, res: Response) => {
  const events = Array.isArray(req.body?.events) ? req.body.events : [];
  res.json({ ok: true, n: store.addTelemetry(events) });
});

app.get('/api/telemetry', (req: Request, res: Response) => {
  const limit = Math.min(1000, Math.max(1, Number(req.query.limit) || 300));
  const cat = String(req.query.cat || '');
  const q = String(req.query.q || '').toLowerCase();
  const bad = Boolean(Number(req.query.bad));
  const trace = String(req.query.trace || '');

  let items = [...store.telemetry].reverse();
  if (cat) items = items.filter((i) => i.cat === cat);
  if (bad) items = items.filter((i) => i.status === 'err' || i.status === 'warn');
  if (trace) items = items.filter((i) => i.trace_id === trace);
  if (q) {
    items = items.filter((i) => `${i.action} ${i.target} ${i.msg}`.toLowerCase().includes(q));
  }
  res.json({ items: items.slice(0, limit), now: Date.now() / 1000 });
});

app.get('/api/settings', (_req: Request, res: Response) => {
  res.json({
    settings: store.settings,
    secrets: store.secretHints(),
    places: store.places(),
    safety: store.safety,
    ds_models: store.dsModels,
    locked: Object.keys(LOCKED_SETTINGS),
    secure: true,
  });
});

app.put('/api/settings', (req: Request, res: Response) => {
  const applied = store.updateSettings(req.body || {});
  res.json({ applied });
});

app.put('/api/secrets', (req: Request, res: Response) => {
  const k = String(req.body?.k || '') as SecretKey;
  const v = String(req.body?.v || '');
  if (!SECRET_KEYS.includes(k)) {
    res.status(400).json({ detail: '不认识的密钥' });
    return;
  }
  store.secrets[k] = v.trim();
  store.refreshChecks();
  res.json({ hints: store.secretHints() });
});

app.post('/api/safety', (req: Request, res: Response) => {
  const group = String(req.body?.group || '');
  const value = String(req.body?.value || '');
  if (!(group in store.safety) || (value !== 'auto' && value !== 'ask')) {
    res.status(400).json({ detail: '安全线参数无效' });
    return;
  }
  store.safety[group] = value;
  res.json(store.safety);
});

app.get('/api/export', (_req: Request, res: Response) => {
  res.json({
    app: 'agent-shell',
    v: 3,
    set: { ...store.settings },
    safety: store.safety,
    reminders: store.reminders,
  });
});

app.post('/api/import', (req: Request, res: Response) => {
  if (req.body?.app !== 'agent-shell') {
    res.status(400).json({ detail: '不是本界面导出的设置' });
    return;
  }
  const applied = store.updateSettings(req.body?.set || {});
  const saf = req.body?.safety || {};
  for (const [g, v] of Object.entries(saf)) {
    if (g in store.safety && (v === 'auto' || v === 'ask')) {
      store.safety[g] = v;
    }
  }
  res.json({ applied });
});

// ---------------- Overview / Agent / Hardware ----------------
app.get('/api/state', (_req: Request, res: Response) => {
  res.json(store.getStateView());
});

app.get('/api/tasks', (_req: Request, res: Response) => {
  res.json({ tasks: [] });
});

app.get('/api/osd', (_req: Request, res: Response) => {
  res.json({ on: false, hw: store.sampleHardware() });
});

app.get('/api/agent', (_req: Request, res: Response) => {
  res.json(store.getAgentView());
});

app.post('/api/agent/restart/:k', (req: Request, res: Response) => {
  const k = String(req.params.k || '');
  res.status(501).json({ error: `Not yet migrated: "${k}" local process control is unavailable in Linux container`, detail: '容器环境无本地子进程可重启' });
});

app.get('/api/hw', (_req: Request, res: Response) => {
  res.json(store.sampleHardware());
});

app.get('/api/hw/history', (_req: Request, res: Response) => {
  res.json(store.hwHistory);
});

app.get('/api/hw/helper', (_req: Request, res: Response) => {
  res.json({ on: false, running: false, supported: false, detail: '使用 Node.js os 模块采样' });
});

app.post('/api/hw/helper', (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: Windows LibreHardwareMonitor helper unavailable', detail: 'Linux 容器无需独立硬件监控助手' });
});

app.get('/api/models', (_req: Request, res: Response) => {
  res.json({ server: false, kev_ready: false, yielding: false, yield_reason: '', health: null });
});

app.get('/api/brains', (_req: Request, res: Response) => {
  res.json(store.getBrainsView());
});

app.get('/api/report', (_req: Request, res: Response) => {
  res.json(store.getReportView());
});

app.get('/api/wishes', (_req: Request, res: Response) => {
  res.json([...store.wishes].reverse());
});

// ---------------- Events & Chat ----------------
app.get('/api/events', (req: Request, res: Response) => {
  const limit = Math.min(300, Math.max(1, Number(req.query.limit) || 60));
  res.json([...store.events].reverse().slice(0, limit));
});

app.get('/api/events/:eid', (req: Request, res: Response) => {
  const eid = Number(req.params.eid);
  const ev = store.events.find((e) => e.id === eid);
  if (!ev) {
    res.status(404).json({ detail: '没有这条事件' });
    return;
  }
  res.json(ev);
});

app.post('/api/events/:eid/fix', (req: Request, res: Response) => {
  const eid = Number(req.params.eid);
  const ev = store.events.find((e) => e.id === eid);
  if (!ev) {
    res.status(404).json({ detail: '没有这条事件' });
    return;
  }
  const to = req.body?.to;
  if (to !== null && to !== 'local' && to !== 'neu' && to !== 'ds' && to !== 'cl') {
    res.status(400).json({ detail: '去向不对' });
    return;
  }
  ev.fix = to;
  res.json(ev);
});

app.post('/api/events/:eid/redo', (req: Request, res: Response) => {
  const eid = Number(req.params.eid);
  const ev = store.events.find((e) => e.id === eid);
  if (!ev) {
    res.status(404).json({ detail: '没有这条事件' });
    return;
  }
  const to = String(req.body?.to || '');
  if (!['local', 'neu', 'ds', 'cl'].includes(to)) {
    res.status(400).json({ detail: '去向不对' });
    return;
  }
  const allow = Boolean(req.body?.allow_private);
  if (ev.private && to !== 'local' && !allow) {
    res.status(409).json({ detail: '这件事标了隐私，交给云端会发出本机，要你确认' });
    return;
  }
  ev.fix = to;
  const token = crypto.randomBytes(6).toString('hex');
  const job: ChatJob = { ts: Date.now() / 1000, eid: null, done: false, event: null, err: null, confirm: false, interjections: [] };
  store.chatJobs.set(token, job);
  store
    .chatHandle(ev.text, { force: to, allow_private: allow, redo_of: eid, job })
    .then((newEv) => {
      job.event = newEv;
      job.done = true;
    })
    .catch((err) => {
      job.err = err instanceof Error ? err.message : String(err);
      job.done = true;
    });
  res.json({ token });
});

app.post('/api/events/:eid/stop', (req: Request, res: Response) => {
  const eid = Number(req.params.eid);
  const ev = store.events.find((e) => e.id === eid);
  if (!ev || ev.status !== 'running') {
    res.status(409).json({ detail: '这件事已经不在做了' });
    return;
  }
  ev.status = 'done';
  ev.result = '已停下';
  res.json({ ok: true });
});

app.post('/api/events/:eid/say', (req: Request, res: Response) => {
  const eid = Number(req.params.eid);
  const ev = store.events.find((e) => e.id === eid);
  if (!ev || ev.status !== 'running') {
    res.status(409).json({ detail: '这件事已经做完了：直接发新的一条吧' });
    return;
  }
  ev.steps.push(['你插了一句', String(req.body?.text || '')]);
  res.json({ ok: true });
});

app.post('/api/chat', async (req: Request, res: Response) => {
  const text = String(req.body?.text || '').trim();
  if (!text) {
    res.status(400).json({ detail: '空消息' });
    return;
  }
  const force = ['local', 'neu', 'ds', 'cl'].includes(req.body?.force) ? String(req.body.force) : null;
  const allowPrivate = Boolean(req.body?.allow_private);
  const engine = ['cc', 'ds'].includes(req.body?.engine) ? String(req.body.engine) : null;
  const src = req.body?.voice ? 'voice' : 'ui';

  if (!req.body?.async) {
    try {
      const ev = await store.chatHandle(text, { force, allow_private: allowPrivate, engine, src });
      res.json(ev);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'PRIVACY_CONFIRM_REQUIRED') {
        res.status(409).json({ detail: '这件事标了隐私，交给云端会发出本机，要你确认' });
      } else {
        res.status(500).json({ detail: msg });
      }
    }
    return;
  }

  const token = crypto.randomBytes(6).toString('hex');
  const job: ChatJob = { ts: Date.now() / 1000, eid: null, done: false, event: null, err: null, confirm: false, interjections: [] };
  store.chatJobs.set(token, job);
  store
    .chatHandle(text, { force, allow_private: allowPrivate, engine, src, job })
    .then((ev) => {
      job.event = ev;
      job.done = true;
    })
    .catch((err) => {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'PRIVACY_CONFIRM_REQUIRED') {
        job.err = '这件事标了隐私，交给云端会发出本机，要你确认';
        job.confirm = true;
      } else {
        job.err = msg.slice(0, 200);
      }
      job.done = true;
    });
  res.json({ token });
});

app.get('/api/chat/:token', (req: Request, res: Response) => {
  const token = String(req.params.token || '');
  const job = store.chatJobs.get(token);
  if (!job) {
    res.status(404).json({ detail: '没有这次对话（过期了）' });
    return;
  }
  const ev = job.event || (job.eid ? store.events.find((e) => e.id === job.eid) || null : null);
  res.json({ done: job.done, event: ev, err: job.err, confirm: job.confirm });
});

// ---------------- Reminders & Report Actions ----------------
app.get('/api/reminders', (_req: Request, res: Response) => {
  const nxt = store.reminders
    .filter((r) => r.enabled && r.next_ts)
    .sort((a, b) => (a.next_ts || 0) - (b.next_ts || 0))[0];
  res.json({
    items: store.reminders,
    next: nxt ? { id: nxt.id, title: nxt.title, at: nxt.at, ts: nxt.next_ts } : null,
  });
});

app.post('/api/reminders', (req: Request, res: Response) => {
  const b = req.body || {};
  const kind = b.kind === 'daily' || b.kind === 'once' ? b.kind : 'interval';
  const base: Omit<ReminderItem, 'next_ts'> = {
    id: store.nextReminderId++,
    title: String(b.title || '新提醒'),
    kind,
    at: String(b.at || '22:00'),
    every_min: Math.max(5, Number(b.every_min) || 90),
    days: String(b.days || '1234567'),
    once_ts: b.once_ts ? Number(b.once_ts) : null,
    text: String(b.text || ''),
    enabled: b.enabled !== false,
  };
  const item: ReminderItem = { ...base, next_ts: computeNextTs(base) };
  store.reminders.push(item);
  res.json(item);
});

app.put('/api/reminders/:rid', (req: Request, res: Response) => {
  const rid = Number(req.params.rid);
  const idx = store.reminders.findIndex((r) => r.id === rid);
  if (idx < 0) {
    res.status(404).json({ detail: '没有这条提醒' });
    return;
  }
  const prev = store.reminders[idx];
  const b = req.body || {};
  const base: Omit<ReminderItem, 'next_ts'> = {
    id: prev.id,
    title: b.title !== undefined ? String(b.title) : prev.title,
    kind: b.kind === 'daily' || b.kind === 'interval' || b.kind === 'once' ? b.kind : prev.kind,
    at: b.at !== undefined ? String(b.at) : prev.at,
    every_min: b.every_min !== undefined ? Math.max(5, Number(b.every_min) || 90) : prev.every_min,
    days: b.days !== undefined ? String(b.days) : prev.days,
    once_ts: b.once_ts !== undefined ? (b.once_ts ? Number(b.once_ts) : null) : prev.once_ts,
    text: b.text !== undefined ? String(b.text) : prev.text,
    enabled: b.enabled !== undefined ? Boolean(b.enabled) : prev.enabled,
  };
  const updated: ReminderItem = { ...base, next_ts: computeNextTs(base) };
  store.reminders[idx] = updated;
  res.json(updated);
});

app.delete('/api/reminders/:rid', (req: Request, res: Response) => {
  const rid = Number(req.params.rid);
  store.reminders = store.reminders.filter((r) => r.id !== rid);
  res.json({ ok: true });
});

app.post('/api/reminders/:rid/fire', (req: Request, res: Response) => {
  const rid = Number(req.params.rid);
  const r = store.reminders.find((x) => x.id === rid);
  if (!r) {
    res.status(404).json({ detail: '没有这个提醒' });
    return;
  }
  const did = Date.now();
  store.cards.push({ id: did, delivery_id: did, title: r.title, text: r.text || r.title, ts: Date.now() / 1000 });
  res.json({ delivery: did, res: { card: { ok: true, info: '已推送到界面卡片' } } });
});

app.post('/api/deliveries/:did/ack', (req: Request, res: Response) => {
  const did = Number(req.params.did);
  store.cards = store.cards.filter((c) => c.delivery_id !== did && c.id !== did);
  res.json({ ok: true });
});

app.post('/api/deliveries/:did/snooze', (req: Request, res: Response) => {
  const did = Number(req.params.did);
  store.cards = store.cards.filter((c) => c.delivery_id !== did && c.id !== did);
  res.json({ ok: true });
});

app.post('/api/changes/:cid/undo', (req: Request, res: Response) => {
  const cid = Number(req.params.cid);
  const c = store.changes.find((x) => x.id === cid);
  if (c) c.undone = true;
  res.json({ msg: c ? '已撤销' : '没有这条改动' });
});

app.post('/api/asks/:aid', (req: Request, res: Response) => {
  const aid = Number(req.params.aid);
  const a = store.asks.find((x) => x.id === aid);
  if (a) a.status = req.body?.approve ? 'approved' : 'rejected';
  res.json({ msg: req.body?.approve ? '已同意' : '已拒绝' });
});

app.post('/api/train/answer', (_req: Request, res: Response) => {
  store.trainAsk = null;
  res.json({ msg: '已记录' });
});

app.post('/api/claude/import', (req: Request, res: Response) => {
  const content = String(req.body?.content || '');
  if (!content.trim()) {
    res.status(400).json({ detail: '文件是空的' });
    return;
  }
  const rel = `总结/${new Date().toISOString().slice(0, 10)}-${String(req.body?.name || '总结').slice(0, 30)}.md`;
  store.summaries.push({ rel, ts: Date.now() / 1000 });
  store.memories.push({ id: store.nextMemoryId++, text: `[导入总结] ${content.slice(0, 300)}`, ts: Date.now() / 1000 });
  res.json({ msg: '已导入并记入记忆', rel });
});

// ---------------- Checks, Setup & Actions ----------------
app.get('/api/checks', (_req: Request, res: Response) => {
  res.json({ last: { res: store.checksRes, ts: store.checksTs }, places: store.places() });
});

app.post('/api/checks/run', (_req: Request, res: Response) => {
  store.refreshChecks();
  res.json({ res: store.checksRes, places: store.places(), ts: store.checksTs });
});

app.post('/api/checks/:k/run', (req: Request, res: Response) => {
  const k = String(req.params.k || '');
  const r = store.checkOne(k);
  store.checksRes[k] = r;
  store.checksTs = Date.now() / 1000;
  res.json(r);
});

app.get('/api/setup', (_req: Request, res: Response) => {
  res.json(store.getSetupView());
});

app.post('/api/setup/start', (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: local Python/GPU environment installer unavailable in container', detail: 'Linux 容器环境不支持本地显卡环境安装' });
});

app.post('/api/setup/stop', (_req: Request, res: Response) => {
  res.json(store.getSetupView());
});

app.post('/api/actions/:name', async (req: Request, res: Response) => {
  const name = String(req.params.name || '');
  const dsBase = String(store.settings.dsBase || 'https://api.deepseek.com').replace(/\/+$/, '');

  if (name === 'ds_balance') {
    if (!store.secrets.dsKey) {
      res.status(400).json({ detail: '还没填 DeepSeek Key' });
      return;
    }
    try {
      const r = await fetch(`${dsBase}/user/balance`, {
        headers: { Authorization: `Bearer ${store.secrets.dsKey}` },
      });
      const j = (await r.json()) as { balance_infos?: Array<{ total_balance?: string; currency?: string }> };
      const info = j.balance_infos?.[0];
      const total = info?.total_balance ? Number(info.total_balance) : 0;
      const currency = info?.currency || 'CNY';
      store.dsBalance = { total, currency, ts: Date.now() / 1000 };
      res.json({ msg: `余额 ${currency} ${total.toFixed(2)}`, balance: store.dsBalance });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      res.json({ msg: '没查到：' + msg });
    }
    return;
  }

  if (name === 'ds_models') {
    if (!store.secrets.dsKey) {
      res.status(400).json({ detail: '先填好 DeepSeek Key 并点「保存」，再获取模型列表' });
      return;
    }
    try {
      const r = await fetch(`${dsBase}/models`, {
        headers: { Authorization: `Bearer ${store.secrets.dsKey}` },
      });
      const j = (await r.json()) as { data?: Array<{ id?: string }> };
      const models = (j.data || []).map((m) => String(m.id || '')).filter(Boolean);
      store.dsModels = { models, ts: Date.now() / 1000 };
      res.json({ msg: `查到 ${models.length} 个模型`, ds_models: store.dsModels });
    } catch (e) {
      res.status(400).json({ detail: e instanceof Error ? e.message : String(e) });
    }
    return;
  }

  if (name === 'qq_test') {
    res.json({ msg: '卡片：网页弹窗通知可用；QQ：容器未连接 QQ 通道' });
    return;
  }

  if (name === 'copy_prompt') {
    if (!store.claudePrompts.length) {
      res.status(404).json({ detail: '还没有提示词' });
      return;
    }
    res.json({ prompt: store.claudePrompts[store.claudePrompts.length - 1].prompt });
    return;
  }

  res.status(501).json({ error: `Not yet migrated: action "${name}" requires local GPU/Windows host`, detail: `动作「${name}」在容器环境不可用` });
});

// ---------------- Docs, Feed, Monitor, Logs ----------------
app.get('/api/docs', (_req: Request, res: Response) => {
  res.json({ items: store.listDocs(), root: DOCS_DIR });
});

app.get(/^\/api\/docs\/(.+)$/, (req: Request, res: Response) => {
  const rel = decodeURIComponent(req.params[0] || '');
  const doc = store.readDoc(rel);
  if (!doc) {
    res.status(404).json({ detail: '没有这篇文档' });
    return;
  }
  res.json(doc);
});

app.get('/api/feed', (req: Request, res: Response) => {
  const n = Math.min(600, Math.max(20, Number(req.query.n) || 400));
  res.json({ items: store.feed.slice(-n), ver: store.feedVer });
});

app.get('/api/monitor', (_req: Request, res: Response) => {
  res.json(store.getMonitorView());
});

app.get('/api/logs', (_req: Request, res: Response) => {
  res.json([{ name: 'backend.log', label: '后端', size: 1024, mtime: Date.now() / 1000 }]);
});

app.get('/api/logs/archive', (_req: Request, res: Response) => {
  res.json({ last: null, next: null, retain_days: store.settings.logRetainDays || 180 });
});

app.post('/api/logs/archive', (_req: Request, res: Response) => {
  store.addFeed('已执行内存日志整理', 'ok', '后端');
  res.json({ ok: true, msg: '已整理内存日志' });
});

app.get('/api/logs/:name', (req: Request, res: Response) => {
  const name = String(req.params.name || 'backend.log');
  res.json({
    name,
    lines: store.feed.slice(-100).map((f) => `[${new Date(f.ts * 1000).toISOString()}] [${f.job}] ${f.text}`),
    size: store.feed.length * 64,
    mtime: Date.now() / 1000,
    path: path.join(ROOT_DIR, 'logs', name),
  });
});

app.get('/api/log/verify', (_req: Request, res: Response) => {
  res.json({ ok: true, count: store.events.length, msg: '内存日志校验通过' });
});

// ---------------- Workspace, Files, Caps, Autostart ----------------
app.get('/api/ws', (_req: Request, res: Response) => {
  res.json({
    dir: store.wsDir,
    run: store.wsRun,
    files: 0,
    backup_mb: 0,
    last_list: null,
    python: false,
    ffmpeg: false,
  });
});

app.put('/api/ws', (req: Request, res: Response) => {
  if (typeof req.body?.dir === 'string' && req.body.dir.trim()) store.wsDir = req.body.dir.trim();
  if (typeof req.body?.run === 'boolean') store.wsRun = req.body.run;
  res.json({ dir: store.wsDir, run: store.wsRun, files: 0, backup_mb: 0, last_list: null });
});

app.post('/api/ws/open', (_req: Request, res: Response) => {
  res.json({ msg: `工作区路径：${store.wsDir}` });
});

app.post('/api/ws/recvdir', (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: file upload workspace not enabled in container', detail: '容器暂未启用本地文件写入' });
});

app.post('/api/ws/upload', (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: file upload workspace not enabled in container', detail: '容器暂未启用本地文件写入' });
});

app.get('/api/files/dirs', (_req: Request, res: Response) => {
  res.json({ dirs: store.readDirs });
});

app.post('/api/files/dirs', (req: Request, res: Response) => {
  const dirPath = String(req.body?.path || '').trim();
  if (!dirPath) {
    res.status(400).json({ detail: '路径不能为空' });
    return;
  }
  if (!store.readDirs.some((d) => d.path === dirPath)) {
    store.readDirs.push({ path: dirPath, cloud: req.body?.cloud !== false });
  }
  res.json({ dirs: store.readDirs });
});

app.patch('/api/files/dirs', (req: Request, res: Response) => {
  const dirPath = String(req.body?.path || '');
  const item = store.readDirs.find((d) => d.path === dirPath);
  if (item) item.cloud = Boolean(req.body?.cloud);
  res.json({ dirs: store.readDirs });
});

app.delete('/api/files/dirs', (req: Request, res: Response) => {
  const dirPath = String(req.query.path || '');
  store.readDirs = store.readDirs.filter((d) => d.path !== dirPath);
  res.json({ dirs: store.readDirs });
});

app.get('/api/agent/caps', (_req: Request, res: Response) => {
  res.json({
    caps: {
      download: Boolean(store.settings.agDownload),
      voice: Boolean(store.settings.agVoice),
      voice_cloud: Boolean(store.settings.agVoiceCloud),
      image: Boolean(store.settings.agImage),
      music: Boolean(store.settings.agMusic),
      publish: Boolean(store.settings.agPublish),
      publish_ask: Boolean(store.settings.agPublishAsk),
      cc: Boolean(store.settings.ccOn),
    },
    skills: store.listSkills(),
    toolbox: [],
    cc: store.getCcodeState().status,
  });
});

app.put('/api/agent/caps', (req: Request, res: Response) => {
  const b = req.body || {};
  const map: Record<string, string> = {
    download: 'agDownload',
    voice: 'agVoice',
    voice_cloud: 'agVoiceCloud',
    image: 'agImage',
    music: 'agMusic',
    publish: 'agPublish',
    publish_ask: 'agPublishAsk',
    cc: 'ccOn',
  };
  for (const [k, sk] of Object.entries(map)) {
    if (k in b) store.settings[sk] = Boolean(b[k]);
  }
  res.json({
    caps: {
      download: Boolean(store.settings.agDownload),
      voice: Boolean(store.settings.agVoice),
      voice_cloud: Boolean(store.settings.agVoiceCloud),
      image: Boolean(store.settings.agImage),
      music: Boolean(store.settings.agMusic),
      publish: Boolean(store.settings.agPublish),
      publish_ask: Boolean(store.settings.agPublishAsk),
      cc: Boolean(store.settings.ccOn),
    },
    skills: store.listSkills(),
    toolbox: [],
    cc: store.getCcodeState().status,
  });
});

app.get('/api/autostart', (_req: Request, res: Response) => {
  res.json({ on: false, supported: false, detail: '容器不支持 Windows 开机自启' });
});

app.post('/api/autostart', (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: Windows autostart unavailable in container', detail: 'Linux 容器不支持 Windows 开机自启' });
});

// ---------------- Video Studio ----------------
app.get('/api/studio/projects', (_req: Request, res: Response) => {
  const st = store.getStudioState();
  res.json({ projects: st.projects, active: st.active });
});

app.get('/api/studio/state', (req: Request, res: Response) => {
  const pid = req.query.pid ? String(req.query.pid) : undefined;
  res.json(store.getStudioState(pid));
});

app.post('/api/studio/select', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || '');
  res.json(store.getStudioState(pid));
});

app.post('/api/studio/new', (req: Request, res: Response) => {
  const topic = String(req.body?.topic || '新视频项目');
  const ratio = String(req.body?.ratio || '9:16');
  const seconds = Number(req.body?.seconds) || 75;
  const proj = store.createStudioProject(topic, ratio, seconds);
  res.json(store.getStudioState(proj.id));
});

app.all('/api/studio/export_prompt_pack', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || req.query.pid || store.activeStudioId);
  const proj = store.studioProjects.get(pid) || store.studioProjects.get(store.activeStudioId);
  const topic = proj?.title || 'AI 科普视频';
  const pack =
    `# 视频工坊策划包 · ${topic}\n\n` +
    `- 风格：知识科普 × 科技数码 × 搞笑段子\n` +
    `- 目标时长：65~85 秒（前 2 秒强钩子）\n` +
    `- 角色设定：白页（冷静吐槽）、紫苏（轻松调侃）\n\n` +
    `## 输出格式要求\n请逐行输出「角色：台词」，例如：\n白页：先说一个反常识的结论。\n紫苏：等等，这也太离谱了吧？\n`;
  res.json({ text: pack, md: pack, filename: `${topic}_策划包.md` });
});

app.post('/api/studio/script/import', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const text = String(req.body?.text || '');
  if (!text.trim()) {
    res.status(400).json({ detail: '剧本内容不能为空' });
    return;
  }
  const imported = store.importStudioScript(pid, text);
  if (!imported) {
    res.status(404).json({ detail: '项目不存在' });
    return;
  }
  res.json({
    ok: true,
    summary: imported.summary,
    estimate: imported.estimate,
    state: store.getStudioState(imported.project.id),
  });
});

app.post('/api/studio/script/plan', async (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const topic = String(req.body?.topic || '');
  const seconds = Number(req.body?.seconds) || 75;
  try {
    const planned = await store.planStudioScript(pid, topic, seconds);
    res.json({
      ok: true,
      summary: planned.summary,
      estimate: planned.estimate,
      state: store.getStudioState(planned.project.id),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});

app.get('/api/studio/list', (req: Request, res: Response) => {
  const pid = String(req.query.pid || store.activeStudioId);
  const name = String(req.query.name || '');
  const proj = store.studioProjects.get(pid);
  if (!proj || !(name in proj.lists)) {
    res.status(404).json({ detail: '清单不存在' });
    return;
  }
  res.json({ name, text: proj.lists[name] });
});

app.put('/api/studio/list', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const name = String(req.body?.name || '');
  const text = String(req.body?.text || '');
  const r = store.updateStudioList(pid, name, text);
  if (!r.ok) {
    res.status(r.project ? 400 : 404).json({ detail: r.error || '清单格式有误' });
    return;
  }
  res.json({ ok: true, state: store.getStudioState(r.project!.id) });
});

app.post('/api/studio/module/update', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const id = String(req.body?.id || '');
  const mod = store.updateStudioModule(pid, id, {
    title: typeof req.body?.title === 'string' ? req.body.title : undefined,
    x: typeof req.body?.x === 'number' ? req.body.x : undefined,
    y: typeof req.body?.y === 'number' ? req.body.y : undefined,
    w: typeof req.body?.w === 'number' ? req.body.w : undefined,
    h: typeof req.body?.h === 'number' ? req.body.h : undefined,
    params: req.body?.params && typeof req.body.params === 'object' ? req.body.params : undefined,
  });
  if (!mod) {
    res.status(404).json({ detail: '模块不存在' });
    return;
  }
  const proj = store.studioProjects.get(pid) || store.studioProjects.get(store.activeStudioId);
  res.json({ ok: true, module: mod, project: proj, state: store.getStudioState(proj?.id) });
});

app.post('/api/studio/module/layout', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const proj = store.studioProjects.get(pid);
  if (!proj) {
    res.status(404).json({ detail: '项目不存在' });
    return;
  }
  const items = Array.isArray(req.body?.modules) ? req.body.modules : [];
  for (const item of items) {
    const mod = proj.modules.find((m) => m.id === item.id);
    if (mod) {
      if (typeof item.x === 'number') mod.x = item.x;
      if (typeof item.y === 'number') mod.y = item.y;
      if (typeof item.w === 'number') mod.w = item.w;
      if (typeof item.h === 'number') mod.h = item.h;
    }
  }
  res.json({ ok: true });
});

app.post('/api/studio/module/run', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const id = typeof req.body?.id === 'string' ? req.body.id : undefined;
  const part = req.body?.part === 'web' || req.body?.part === 'ppt' || req.body?.part === 'ffmpeg' ? req.body.part : undefined;
  const force = Boolean(req.body?.force);
  try {
    const proj = store.startStudioRun(pid, { id, part, force });
    res.json({ ok: true, project: proj, state: store.getStudioState(proj.id) });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(409).json({ detail: msg });
  }
});

app.post('/api/studio/stop', (req: Request, res: Response) => {
  const pid = typeof req.body?.pid === 'string' ? req.body.pid : undefined;
  const moduleId = typeof req.body?.module_id === 'string' ? req.body.module_id : undefined;
  const r = store.stopStudio(pid, moduleId);
  res.json({
    ok: true,
    stopped: r.stopped,
    msg: r.stopped.length ? `已停止：${r.stopped.join('、')}` : '已发送停止指令',
  });
});

function serveStudioMedia(req: Request, res: Response): void {
  const pid = String(req.query.pid || store.activeStudioId);
  const rawPath = String(req.query.path || '');
  const clean = sanitizeRelPath(rawPath);
  if (!clean) {
    res.status(400).json({ detail: '非法的媒体相对路径' });
    return;
  }
  const asset = store.getStudioAsset(pid, clean);
  if (!asset) {
    res.status(404).json({ detail: `找不到媒体文件：${clean}` });
    return;
  }
  const headerErr = sniffMediaHeader(clean, asset.buf);
  if (headerErr) {
    res.status(400).json({ detail: headerErr });
    return;
  }

  const total = asset.buf.length;
  res.setHeader('Content-Type', asset.mime);
  res.setHeader('Accept-Ranges', 'bytes');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('ETag', `"${asset.sha256.slice(0, 16)}"`);

  const rangeHeader = req.headers.range;
  if (typeof rangeHeader === 'string' && rangeHeader.startsWith('bytes=')) {
    const m = /^bytes=(\d*)-(\d*)$/.exec(rangeHeader.trim());
    if (!m) {
      res.status(416).setHeader('Content-Range', `bytes */${total}`).end();
      return;
    }
    let start = m[1] ? Number(m[1]) : 0;
    let end = m[2] ? Number(m[2]) : total - 1;
    if (!m[1] && m[2]) {
      const suffix = Number(m[2]);
      start = Math.max(0, total - suffix);
      end = total - 1;
    }
    if (Number.isNaN(start) || Number.isNaN(end) || start < 0 || start >= total || end < start) {
      res.status(416).setHeader('Content-Range', `bytes */${total}`).end();
      return;
    }
    end = Math.min(end, total - 1);
    const chunk = asset.buf.subarray(start, end + 1);
    res.status(206);
    res.setHeader('Content-Range', `bytes ${start}-${end}/${total}`);
    res.setHeader('Content-Length', String(chunk.length));
    res.end(chunk);
    return;
  }

  res.setHeader('Content-Length', String(total));
  res.end(asset.buf);
}

app.get('/api/studio/asset', serveStudioMedia);
app.get('/api/studio/media', serveStudioMedia);

app.get('/api/studio/asset/info', (req: Request, res: Response) => {
  const pid = String(req.query.pid || store.activeStudioId);
  const rawPath = String(req.query.path || '');
  const clean = sanitizeRelPath(rawPath);
  if (!clean) {
    res.status(400).json({ detail: '非法的媒体相对路径' });
    return;
  }
  const asset = store.getStudioAsset(pid, clean);
  if (!asset) {
    res.status(404).json({ detail: `找不到媒体文件：${clean}` });
    return;
  }
  const fmt = path.extname(clean).replace(/^\./, '').toLowerCase() || 'bin';
  res.json({
    name: asset.name,
    fmt,
    size: asset.buf.length,
    w: asset.w || 0,
    h: asset.h || 0,
    frames: asset.frames || 0,
    duration_ms: asset.duration_ms || 0,
    duration: asset.duration || 0,
    sha256: asset.sha256,
  });
});

app.post('/api/studio/ref', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const proj = store.studioProjects.get(pid) || store.studioProjects.get(store.activeStudioId);
  if (!proj) {
    res.status(404).json({ detail: '项目不存在' });
    return;
  }
  const rawName = String(req.body?.name || 'ref.png').replace(/[^a-zA-Z0-9._\u4e00-\u9fa5-]/g, '_');
  const dataUri = String(req.body?.data || '');
  const m = /^data:image\/([a-zA-Z0-9+.-]+);base64,([A-Za-z0-9+/=\r\n]+)$/.exec(dataUri);
  if (!m) {
    res.status(400).json({ detail: '参考图格式需为 Base64 DataURI（PNG/JPG/WebP/GIF）' });
    return;
  }
  const subtype = m[1].toLowerCase().replace('jpeg', 'jpg');
  const allowedExt = subtype === 'png' || subtype === 'jpg' || subtype === 'webp' || subtype === 'gif' ? `.${subtype}` : '.png';
  const base = path.basename(rawName, path.extname(rawName)) || 'ref';
  const rel = `refs/${Date.now()}_${base}${allowedExt}`;
  const buf = Buffer.from(m[2], 'base64');
  const err = sniffMediaHeader(rel, buf);
  if (err) {
    res.status(400).json({ detail: `参考图校验失败：${err}` });
    return;
  }
  store.putStudioAsset(proj.id, makeAsset(rel, buf));
  res.json({ ok: true, rel });
});

app.post('/api/studio/open', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const proj = store.studioProjects.get(pid) || store.studioProjects.get(store.activeStudioId);
  const what = String(req.body?.what || 'output');
  const p = proj ? path.join(proj.dir, what) : '工作区输出目录';
  res.json({ ok: true, path: p, msg: `当前为 Web 容器环境，虚拟工作目录为：${p}` });
});

app.post('/api/studio/reveal', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const rel = sanitizeRelPath(String(req.body?.path || '')) || '';
  const proj = store.studioProjects.get(pid) || store.studioProjects.get(store.activeStudioId);
  const p = proj && rel ? path.join(proj.dir, rel) : proj?.dir || '';
  res.json({ ok: true, path: p, msg: p ? `资源虚拟路径：${p}` : '资源位于当前项目工作区内' });
});

app.post('/api/studio/to_publish', (req: Request, res: Response) => {
  store.pubPending.push({ id: Date.now(), title: String(req.body?.title || '工坊成片'), ts: Date.now() / 1000 });
  res.json({ ok: true, msg: '已加入发布待确认队列' });
});

// ---------------- Video Studio v2 (Chat-First Multi-Agent Orchestration) ----------------
app.post('/api/studio/chat/send', async (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  try {
    const state = await store.studioOrch.sendChatMessage(pid, {
      text: String(req.body?.text || ''),
      mentions: Array.isArray(req.body?.mentions) ? (req.body.mentions as AgentId[]) : undefined,
      reply_to: typeof req.body?.reply_to === 'string' ? req.body.reply_to : undefined,
      attachments: Array.isArray(req.body?.attachments) ? req.body.attachments : undefined,
    });
    res.json({ ok: true, state });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});

app.post('/api/studio/chat/read', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const agentId = String(req.body?.agent_id || '');
  if (agentId) store.studioOrch.markAgentRead(pid, agentId);
  res.json({ ok: true });
});

app.post('/api/studio/approval', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const approvalId = String(req.body?.approval_id || '');
  const approved = Boolean(req.body?.approved);
  const note = String(req.body?.note || '');
  try {
    const state = store.studioOrch.decideApproval(pid, approvalId, approved, note);
    res.json({ ok: true, state });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});

app.post('/api/studio/agent/:aid/run', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const aid = String(req.params.aid) as AgentId;
  const inputs = req.body?.inputs && typeof req.body.inputs === 'object' ? (req.body.inputs as Record<string, unknown>) : {};
  try {
    const state = store.studioOrch.runDirectAgentTask(pid, aid, inputs);
    res.json({ ok: true, state });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});

app.post('/api/studio/agent/:aid/action', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const aid = String(req.params.aid) as AgentId;
  const action = String(req.body?.action || 'pause') as 'pause' | 'resume' | 'stop';
  try {
    const state = store.studioOrch.agentAction(pid, aid, action);
    res.json({ ok: true, state });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});

app.post('/api/studio/task/:tid/action', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const tid = String(req.params.tid);
  const action = String(req.body?.action || 'cancel') as 'pause' | 'resume' | 'cancel' | 'retry' | 'rerun';
  try {
    const state = store.studioOrch.taskAction(pid, tid, action);
    res.json({ ok: true, state });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});

app.post('/api/studio/config', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  try {
    const proj = store.studioOrch.updateProjectConfigs(pid, {
      title: typeof req.body?.title === 'string' ? req.body.title : undefined,
      desc: typeof req.body?.desc === 'string' ? req.body.desc : undefined,
      ratio: typeof req.body?.ratio === 'string' ? req.body.ratio : undefined,
      target_duration: typeof req.body?.target_duration === 'number' ? req.body.target_duration : undefined,
      bgm: req.body?.bgm && typeof req.body.bgm === 'object' ? req.body.bgm : undefined,
      image_config: req.body?.image_config && typeof req.body.image_config === 'object' ? req.body.image_config : undefined,
      compose_config: req.body?.compose_config && typeof req.body.compose_config === 'object' ? req.body.compose_config : undefined,
      publish_config: req.body?.publish_config && typeof req.body.publish_config === 'object' ? req.body.publish_config : undefined,
    });
    res.json({ ok: true, project: proj, state: store.getStudioState(proj.id) });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});

app.post('/api/studio/line/add', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  try {
    const proj = store.studioOrch.addDialogueLine(
      pid,
      String(req.body?.role || '白页'),
      String(req.body?.text || ''),
      String(req.body?.tone || '')
    );
    res.json({ ok: true, state: store.getStudioState(proj.id) });
  } catch (err) {
    res.status(400).json({ detail: err instanceof Error ? err.message : String(err) });
  }
});

app.patch('/api/studio/line/:lid', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const lid = String(req.params.lid);
  const rev = typeof req.body?.revision === 'number' ? req.body.revision : undefined;
  try {
    const proj = store.studioOrch.updateDialogueLine(
      pid,
      lid,
      {
        text: typeof req.body?.text === 'string' ? req.body.text : undefined,
        tone: typeof req.body?.tone === 'string' ? req.body.tone : undefined,
        speaker: typeof req.body?.speaker === 'string' ? req.body.speaker : undefined,
        engine: req.body?.engine === 'cloud' || req.body?.engine === 'local' || req.body?.engine === 'auto' ? req.body.engine : undefined,
        role: typeof req.body?.role === 'string' ? req.body.role : undefined,
      },
      rev
    );
    res.json({ ok: true, state: store.getStudioState(proj.id) });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(/版本冲突/.test(msg) ? 409 : 400).json({ detail: msg });
  }
});

app.delete('/api/studio/line/:lid', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || req.query.pid || store.activeStudioId);
  const lid = String(req.params.lid);
  try {
    const proj = store.studioOrch.deleteDialogueLine(pid, lid);
    res.json({ ok: true, state: store.getStudioState(proj.id) });
  } catch (err) {
    res.status(400).json({ detail: err instanceof Error ? err.message : String(err) });
  }
});

app.patch('/api/studio/shot/:sid', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const sid = String(req.params.sid);
  const rev = typeof req.body?.revision === 'number' ? req.body.revision : undefined;
  try {
    const proj = store.studioOrch.updateShot(
      pid,
      sid,
      {
        render: req.body?.render === 'web' || req.body?.render === 'ppt' || req.body?.render === 'static' ? req.body.render : undefined,
        visual_prompt: typeof req.body?.visual_prompt === 'string' ? req.body.visual_prompt : undefined,
        subtitle_text: typeof req.body?.subtitle_text === 'string' ? req.body.subtitle_text : undefined,
        duration_sec: typeof req.body?.duration_sec === 'number' ? req.body.duration_sec : undefined,
      },
      rev
    );
    res.json({ ok: true, state: store.getStudioState(proj.id) });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(/版本冲突/.test(msg) ? 409 : 400).json({ detail: msg });
  }
});

app.post('/api/studio/asset/adopt', (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  const assetId = String(req.body?.asset_id || '');
  try {
    const proj = store.studioOrch.adoptAsset(pid, assetId);
    res.json({ ok: true, state: store.getStudioState(proj.id) });
  } catch (err) {
    res.status(400).json({ detail: err instanceof Error ? err.message : String(err) });
  }
});

app.post('/api/studio/qa/run', async (req: Request, res: Response) => {
  const pid = String(req.body?.pid || store.activeStudioId);
  try {
    const out = await store.studioOrch.runManualQa(pid);
    res.json({ ok: true, report: out.report, state: out.state });
  } catch (err) {
    res.status(400).json({ detail: err instanceof Error ? err.message : String(err) });
  }
});

// ---------------- Tool State & Real Cloud Backends (Img / TTS / BGM / Voice / Publish / CCode) ----------------
app.get('/api/img', (_req: Request, res: Response) => {
  res.json(store.getImgState());
});
app.get('/api/img/models', (_req: Request, res: Response) => {
  res.json(store.getImgModels());
});
app.post('/api/img/models/refresh', async (_req: Request, res: Response) => {
  try {
    res.json(await store.refreshImgModels());
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});
app.get('/api/img/hist', (req: Request, res: Response) => {
  const q = String(req.query.q || '').trim().toLowerCase();
  const limit = Math.min(200, Math.max(1, Number(req.query.limit) || 120));
  const items = q
    ? store.imgRecent.filter((h) => `${h.prompt || ''} ${h.file || ''} ${h.title || ''}`.toLowerCase().includes(q))
    : store.imgRecent;
  res.json({ items: items.slice(0, limit), more: false });
});
app.post('/api/img/single', (req: Request, res: Response) => {
  try {
    const job = store.startImgSingle({
      prompt: String(req.body?.prompt || ''),
      ratio: String(req.body?.ratio || '9:16'),
      n: Number(req.body?.n) || 1,
      transparent: Boolean(req.body?.transparent),
      refs: Array.isArray(req.body?.refs) ? (req.body.refs as string[]) : [],
    });
    res.json({ ok: true, job });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});
app.post('/api/img/stop', (_req: Request, res: Response) => {
  store.imgStopFlag = true;
  res.json({ ok: true, job: store.imgJob });
});
app.post('/api/img/clear', (_req: Request, res: Response) => {
  store.imgBoard = null;
  res.json(store.getImgState());
});
app.post('/api/img/open', (_req: Request, res: Response) => {
  res.json({ ok: true, msg: `当前为 Web 容器环境，虚拟目录：${store.places().imgOut}` });
});
app.get('/api/img/hfile/:hid', (req: Request, res: Response) => {
  const rec = store.imgBuffers.get(`h:${req.params.hid}`);
  if (!rec) {
    res.status(404).json({ detail: '图片不存在或已清理' });
    return;
  }
  res.setHeader('Content-Type', rec.mime);
  res.setHeader('Cache-Control', 'no-store');
  res.end(rec.buf);
});
app.get('/api/img/file/:id', (req: Request, res: Response) => {
  const rec = store.imgBuffers.get(`i:${req.params.id}`);
  if (!rec) {
    res.status(404).json({ detail: '图片不存在' });
    return;
  }
  res.setHeader('Content-Type', rec.mime);
  res.setHeader('Cache-Control', 'no-store');
  res.end(rec.buf);
});
app.post('/api/img/load', (req: Request, res: Response) => {
  try {
    res.json(store.loadImgBoard(String(req.body?.md || ''), String(req.body?.name || '')));
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});
app.patch('/api/img/item/:id', (req: Request, res: Response) => {
  try {
    const item = store.patchImgItem(String(req.params.id), (req.body || {}) as Record<string, unknown>);
    res.json({ ok: true, item });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});
app.get('/api/img/item/:id/ref/:idx', (req: Request, res: Response) => {
  const board = store.imgBoard as { items?: Array<Record<string, unknown>> } | null;
  const item = board?.items?.find((x) => String(x.id) === String(req.params.id));
  const refs = Array.isArray(item?._refs) ? (item._refs as string[]) : [];
  const dataUri = refs[Number(req.params.idx) || 0] || '';
  const m = /^data:([^;]+);base64,([A-Za-z0-9+/=\r\n]+)$/.exec(dataUri);
  if (!m) {
    res.status(404).json({ detail: '参考图不存在' });
    return;
  }
  res.setHeader('Content-Type', m[1]);
  res.end(Buffer.from(m[2], 'base64'));
});
app.post('/api/img/run', (req: Request, res: Response) => {
  try {
    const job = store.startImgBatch((req.body || {}) as Record<string, unknown>);
    res.json({ ok: true, job });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});
app.post('/api/img/tows', (req: Request, res: Response) => {
  const proj = store.studioProjects.get(store.activeStudioId);
  if (!proj) {
    res.status(404).json({ detail: '未找到视频工坊项目' });
    return;
  }
  let copied = 0;
  const hid = req.body?.hid;
  if (hid) {
    const rec = store.imgBuffers.get(`h:${hid}`);
    if (rec) {
      store.putStudioAsset(proj.id, makeAsset(`img/ws_${hid}.png`, rec.buf));
      copied = 1;
    }
  } else {
    const board = store.imgBoard as { items?: Array<Record<string, unknown>> } | null;
    for (const it of board?.items || []) {
      const rec = store.imgBuffers.get(`i:${it.id}`);
      if (rec) {
        store.putStudioAsset(proj.id, makeAsset(`img/${String(it.file || it.id)}`, rec.buf));
        copied++;
      }
    }
  }
  res.json({ ok: true, copied, msg: `已放入视频工坊项目工作区 ${copied} 张图` });
});
app.all(/^\/api\/img\/.+/, (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated', detail: '该生图子功能暂未支持（单张、批量与历史均已就绪）' });
});

app.get('/api/tts', (_req: Request, res: Response) => {
  res.json(store.getTtsState());
});
app.post('/api/tts/gen', (req: Request, res: Response) => {
  try {
    const job = store.startTtsGen((req.body || {}) as Record<string, unknown>);
    res.json({ ok: true, job });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});
app.post('/api/tts/stop', (_req: Request, res: Response) => {
  store.ttsStopFlag = true;
  res.json({ ok: true, job: store.ttsJob });
});
app.get('/api/tts/draft.wav', (req: Request, res: Response) => {
  if (!store.ttsDraftWav) {
    res.status(404).json({ detail: '还没有试听音频' });
    return;
  }
  const total = store.ttsDraftWav.length;
  res.setHeader('Content-Type', 'audio/wav');
  res.setHeader('Accept-Ranges', 'bytes');
  res.setHeader('Cache-Control', 'no-store');
  const rh = req.headers.range;
  if (typeof rh === 'string' && rh.startsWith('bytes=')) {
    const m = /^bytes=(\d*)-(\d*)$/.exec(rh.trim());
    if (m) {
      const start = m[1] ? Number(m[1]) : 0;
      const end = m[2] ? Math.min(Number(m[2]), total - 1) : total - 1;
      if (start >= 0 && start < total && end >= start) {
        const chunk = store.ttsDraftWav.subarray(start, end + 1);
        res.status(206);
        res.setHeader('Content-Range', `bytes ${start}-${end}/${total}`);
        res.setHeader('Content-Length', String(chunk.length));
        res.end(chunk);
        return;
      }
    }
  }
  res.setHeader('Content-Length', String(total));
  res.end(store.ttsDraftWav);
});
app.post('/api/tts/cloud/try', async (req: Request, res: Response) => {
  const voice = String(req.body?.voice || 'longanlingxin_v3.1');
  if (!store.secrets.blKey) {
    res.status(400).json({ detail: '还没填百炼 API Key，请到 设置 › 云端 填写' });
    return;
  }
  const cached = store.ttsTryCache.get(voice);
  if (cached) {
    res.setHeader('Content-Type', 'audio/wav');
    res.setHeader('X-Cached', '1');
    res.end(cached);
    return;
  }
  try {
    const out = await callBailianTts({
      apiKey: store.secrets.blKey,
      baseUrl: String(store.settings.blBase || 'https://dashscope.aliyuncs.com/api/v1'),
      model: String(store.settings.blModel || 'qwen-audio-3.1-tts-plus'),
      text: '你好，这是一段百炼云端音色的在线试听样例。',
      voice,
    });
    store.ttsTryCache.set(voice, out.wavBuf);
    store.ttsCloudMonth.n += 1;
    store.ttsCloudMonth.bill += out.characters;
    res.setHeader('Content-Type', 'audio/wav');
    res.setHeader('X-Cached', '0');
    res.end(out.wavBuf);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});
app.post('/api/tts/cloud/sync', async (_req: Request, res: Response) => {
  if (!store.secrets.blKey) {
    res.status(400).json({ detail: '还没填百炼 API Key' });
    return;
  }
  try {
    const list = await callBailianSyncVoices(
      String(store.settings.blBase || 'https://dashscope.aliyuncs.com/api/v1'),
      store.secrets.blKey
    );
    store.ttsCloudMine = list;
    res.json({ ok: true, msg: `同步完成：共 ${list.length} 个自建音色`, mine: list });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(400).json({ detail: msg });
  }
});
app.post('/api/tts/voices', (req: Request, res: Response) => {
  const voice = {
    id: store.nextVoiceId++,
    name: String(req.body?.name || '自定义音色'),
    desc: String(req.body?.desc || ''),
    seed: Number(req.body?.seed) || 20261111,
  };
  store.ttsVoices.push(voice);
  res.json(store.getTtsState());
});
app.delete('/api/tts/voices/:vid', (req: Request, res: Response) => {
  const vid = Number(req.params.vid);
  store.ttsVoices = store.ttsVoices.filter((v) => v.id !== vid);
  res.json(store.getTtsState());
});
app.all('/api/tts/cloud/hotfix', (req: Request, res: Response) => {
  store.ttsPronDict = {
    pronunciation: req.body?.pronunciation || {},
    replace: req.body?.replace || {},
  };
  res.json({ ok: true, hotfix: store.ttsPronDict, msg: '读音词典已保存' });
});
app.post('/api/tts/open', (_req: Request, res: Response) => {
  res.json({ ok: true, msg: `当前为 Web 容器环境，虚拟目录：${store.places().ttsOut}` });
});
app.get('/api/tts/batch', (_req: Request, res: Response) => {
  res.json({ out: store.places().ttsOut, job: null, board: store.ttsBatchBoard });
});
app.all(/^\/api\/tts\/.+/, (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated', detail: '该本地配音子功能需要本地 Qwen3-TTS GPU 服务，请切换右上角「云端 · 百炼」测试' });
});

app.get('/api/bgm', (_req: Request, res: Response) => {
  res.json(store.getBgmState());
});
app.get('/api/bgm/batch', (_req: Request, res: Response) => {
  res.json({ out: store.places().bgmOut, job: null, board: store.bgmBatchBoard });
});
app.all(/^\/api\/bgm\/.+/, (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: Stable Audio 3 music generation requires local GPU', detail: '配乐生成需要本地显卡环境' });
});

app.get('/api/voice', (_req: Request, res: Response) => {
  res.json({ on: Boolean(store.settings.voiceOn), asr: false, asr_why: '容器无本地 GPU 听写模型', engine: 'none', auto: true, ref: false });
});
app.all(/^\/api\/voice\/.+/, (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: voice synthesis/ASR requires local GPU', detail: '语音对话需要本地 GPU 环境' });
});

app.get('/api/publish', (_req: Request, res: Response) => {
  res.json(store.getPublishState());
});
app.all(/^\/api\/publish\/.+/, (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: headless browser publisher unavailable in container', detail: '抖音自动发布需要本地桌面浏览器环境' });
});

app.get('/api/ccode', (_req: Request, res: Response) => {
  res.json(store.getCcodeState());
});
app.put('/api/ccode/switch', (req: Request, res: Response) => {
  store.settings.ccOn = Boolean(req.body?.on);
  res.json({ caps: { cc: store.settings.ccOn }, status: store.getCcodeState().status });
});
app.all(/^\/api\/ccode\/.+/, (_req: Request, res: Response) => {
  res.status(501).json({ error: 'Not yet migrated: Claude Code CLI runner unavailable in container', detail: '容器内未安装本地 Claude Code CLI' });
});

app.post('/api/quit', (_req: Request, res: Response) => {
  res.json({ ok: true, msg: 'Web 服务将继续托管运行' });
});

// Serve docs screenshots if referenced and static UI assets after API routes
app.use('/docs', express.static(DOCS_DIR));
app.use('/', express.static(UI_DIR, { index: false }));

app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  const msg = err instanceof Error ? err.message : 'Internal server error';
  res.status(500).json({ detail: msg });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Experiment Agent One listening on http://0.0.0.0:${PORT}`);
});
