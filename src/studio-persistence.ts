import fs from 'node:fs';
import path from 'node:path';
import { makeAsset, sanitizeRelPath, type StudioAsset } from './studio-runtime.ts';
import type { StudioProjectV2 } from './studio-types.ts';

export interface PersistedStudioState {
  activeId: string;
  projects: StudioProjectV2[];
  assetsByProject: Map<string, Map<string, StudioAsset>>;
}

function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function atomicWriteFile(filePath: string, data: Buffer | string): void {
  const dir = path.dirname(filePath);
  ensureDir(dir);
  const tmp = `${filePath}.tmp.${process.pid}.${Date.now().toString(36)}.${Math.random().toString(36).slice(2, 6)}`;
  fs.writeFileSync(tmp, data);
  fs.renameSync(tmp, filePath);
}

export class StudioPersistence {
  readonly baseDir: string;

  constructor(wsDir: string) {
    this.baseDir = path.join(wsDir, '.studio_data');
  }

  private indexFile(): string {
    return path.join(this.baseDir, 'index.json');
  }

  private projDir(pid: string): string {
    const safe = pid.replace(/[^a-zA-Z0-9_-]/g, '_');
    return path.join(this.baseDir, safe);
  }

  private projFile(pid: string): string {
    return path.join(this.projDir(pid), 'project.json');
  }

  private filesRoot(pid: string): string {
    return path.join(this.projDir(pid), 'files');
  }

  saveIndex(activeId: string, projectIds: string[]): void {
    try {
      ensureDir(this.baseDir);
      atomicWriteFile(
        this.indexFile(),
        JSON.stringify({ activeId, projectIds, updatedAt: Date.now() }, null, 2)
      );
    } catch {
      // ignore persistence write error in restricted environments
    }
  }

  saveProject(proj: StudioProjectV2): void {
    try {
      const pFile = this.projFile(proj.id);
      atomicWriteFile(pFile, JSON.stringify(proj, null, 2));
    } catch {
      // ignore disk write error
    }
  }

  saveAssetBuffer(pid: string, asset: StudioAsset): void {
    try {
      const rel = sanitizeRelPath(asset.rel);
      if (!rel) return;
      const target = path.join(this.filesRoot(pid), rel);
      const resolvedRoot = path.resolve(this.filesRoot(pid)) + path.sep;
      const resolvedTarget = path.resolve(target);
      if (!resolvedTarget.startsWith(resolvedRoot)) return;
      atomicWriteFile(resolvedTarget, asset.buf);
    } catch {
      // ignore disk write error
    }
  }

  loadAll(): PersistedStudioState | null {
    try {
      if (!fs.existsSync(this.indexFile())) return null;
      const idxRaw = JSON.parse(fs.readFileSync(this.indexFile(), 'utf8')) as {
        activeId?: string;
        projectIds?: string[];
      };
      const ids = Array.isArray(idxRaw.projectIds) ? idxRaw.projectIds : [];
      if (!ids.length) return null;

      const projects: StudioProjectV2[] = [];
      const assetsByProject = new Map<string, Map<string, StudioAsset>>();

      for (const pid of ids) {
        const pf = this.projFile(pid);
        if (!fs.existsSync(pf)) continue;
        try {
          const proj = JSON.parse(fs.readFileSync(pf, 'utf8')) as StudioProjectV2;
          if (!proj || !proj.id) continue;

          // Recover interrupted running tasks safely after restart (Spec §8.3 / §15.9)
          let recoveredCount = 0;
          if (Array.isArray(proj.tasks)) {
            for (const t of proj.tasks) {
              if (t.state === 'running' || t.state === 'retrying') {
                t.state = 'paused';
                t.phase = '服务重启前正在执行，已自动暂停，可点击「恢复/重跑」';
                t.logs = [...(t.logs || []), `[${new Date().toLocaleTimeString()}] 服务重启恢复：任务从运行态切换为已暂停`].slice(-40);
                recoveredCount++;
              }
            }
          }
          if (Array.isArray(proj.modules)) {
            for (const m of proj.modules) {
              if (m.runtime && (m.runtime.status === 'running' || m.runtime.status === 'queued')) {
                m.status = 'idle';
                m.runtime = { status: 'idle', pct: 0, phase: '服务重启恢复待命' };
              }
            }
          }
          if (recoveredCount > 0 && Array.isArray(proj.messages)) {
            proj.messages.push({
              msg_id: `msg-rec-${Date.now()}`,
              ts: Math.floor(Date.now() / 1000),
              kind: 'task_event',
              sender_id: 'supervisor',
              sender_name: '系统恢复',
              event_state: 'paused',
              text: `服务重启后已恢复项目状态：${recoveredCount} 个中断任务已标记为「已暂停」，保留此前全部产物与版本。`,
            });
          }

          const bucket = new Map<string, StudioAsset>();
          const fRoot = this.filesRoot(proj.id);
          if (fs.existsSync(fRoot)) {
            const walk = (dir: string) => {
              for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
                const full = path.join(dir, ent.name);
                if (ent.isDirectory()) {
                  walk(full);
                } else if (ent.isFile()) {
                  const rel = path.relative(fRoot, full).split(path.sep).join('/');
                  const clean = sanitizeRelPath(rel);
                  if (!clean) continue;
                  try {
                    const buf = fs.readFileSync(full);
                    const meta = (proj.assets || []).find((a) => a.rel === clean);
                    bucket.set(
                      clean,
                      makeAsset(clean, buf, meta ? { duration: meta.duration, w: meta.w, h: meta.h } : undefined)
                    );
                  } catch {
                    // ignore broken asset read
                  }
                }
              }
            };
            walk(fRoot);
          }

          projects.push(proj);
          assetsByProject.set(proj.id, bucket);
        } catch {
          // ignore malformed project JSON
        }
      }

      if (!projects.length) return null;
      return {
        activeId: idxRaw.activeId && projects.some((p) => p.id === idxRaw.activeId) ? idxRaw.activeId : projects[0].id,
        projects,
        assetsByProject,
      };
    } catch {
      return null;
    }
  }
}
