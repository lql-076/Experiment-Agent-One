r"""日志定期归档（v3.5）：半年 / 一年一次，先提炼重要事项永久备份，再压缩/清理过期原始日志。

流程：
1. 扫 telemetry/*.jsonl、crash.log、window.log、backend.log、setup_*.log、report.jsonl、actions.jsonl；
2. 提炼《重要事项永久备份报告》（Markdown + JSON），放
   data\logs\important_backups\ 和 工作区\备份\日志重要事项\；
3. 把超过保留周期（logRetainDays：180 或 365 天）的原始分片压成
   data\logs\archive\logs_before_YYYY-MM-DD.zip，并删除已压缩的过期分片；
   最近 30 天热日志和永久备份永远不动。

触发：每日差事（nightly）和启动自检调用 maybe_run()；设置 › 数据 有「立即执行一次归档整理」。
隐私：报告只放聚合统计、错误类别、接口路径、子进程名；不写聊天/提醒原文、密钥、账号。
"""
import json
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import db, feed, paths, settings, telemetry

LOGS = paths.LOGS
BACKUP = LOGS / "important_backups"
ARCHIVE = LOGS / "archive"
WS_BACKUP = paths.ROOT / "工作区" / "备份" / "日志重要事项"
RETAIN = (180, 365)
CRASH_RE = re.compile(r"Windows fatal exception|Fatal Python error|启动出错|CRITICAL|崩溃|闪退", re.I)
SAFE_DELETE = ("trace_*.jsonl", "behavior_*.log", "*.old.log", "setup_*.log")


def _retain():
    try:
        n = int(settings.S.get("logRetainDays") or 180)
    except (TypeError, ValueError):
        n = 180
    return n if n in RETAIN else 180


def _last():
    try:
        return float(db.kv_get("logArchiveLast", 0) or 0)
    except Exception:
        return 0.0


def due(now=None):
    now = now or time.time()
    return not _last() or now - _last() >= _retain() * 86400


def status():
    last = _last()
    retain = _retain()
    return {"last": last, "retain_days": retain, "due": due(),
            "next_due": (last + retain * 86400) if last else 0,
            "backups": sorted([p.name for p in BACKUP.glob("重要事项备份_*")], reverse=True)[:12] if BACKUP.exists() else [],
            "archives": sorted([p.name for p in ARCHIVE.glob("logs_before_*.zip")], reverse=True)[:12] if ARCHIVE.exists() else []}


def _iter_jsonl(p, cap=300000):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= cap:
                    return
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _scan_text(p, cap=400000):
    hits = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= cap:
                    break
                if CRASH_RE.search(line):
                    hits.append(telemetry.mask_text(line.strip())[:220])
                    if len(hits) >= 40:
                        break
    except OSError:
        pass
    return hits


def _collect():
    """返回 (崩溃片段, 卡顿统计, 慢接口 Top10, 任务统计, 显存统计, 安全事件计数)。"""
    crashes, under, slow, tasks, vram, safety = [], {}, [], {"bgm": 0, "tts": 0, "ccode": 0, "setup": 0}, {"peak_gb": 0.0, "yield": 0}, {"拦截": 0}
    for p in sorted(telemetry.DIR.glob("trace_*.jsonl")):
        for e in _iter_jsonl(p):
            cat, act, st = e.get("cat"), e.get("action") or "", e.get("status")
            m = e.get("metrics") or {}
            if cat == "voice" and st in ("warn", "err"):
                under["count"] = under.get("count", 0) + 1
                under["stall_ms"] = under.get("stall_ms", 0) + float(m.get("total_stall_ms") or 0)
                under["max_ttfa_ms"] = max(under.get("max_ttfa_ms", 0), float(m.get("ttfa_ms") or 0))
                under["max_rtf"] = max(under.get("max_rtf", 0), float(m.get("rtf") or 0))
            if cat == "api" and (e.get("dur_ms") or 0) > 200:
                slow.append((float(e.get("dur_ms") or 0), str(e.get("target") or ""), int(m.get("code") or 0), str(e.get("time") or "")))
            if cat == "proc" and act == "crash":
                crashes.append(f"{e.get('time')} 子进程 {e.get('target')} 意外退出：{telemetry.mask_text(e.get('msg') or '')[:160]}")
            if cat == "ccode" and act == "done":
                tasks["ccode"] += 1
            if cat == "bgm" and act == "done":
                tasks["bgm"] += 1
            if cat == "tts" and act == "done":
                tasks["tts"] += 1
            if cat == "vram":
                if act == "yield":
                    vram["yield"] += 1
                if m.get("vram_gb") is not None:
                    vram["peak_gb"] = max(vram["peak_gb"], float(m["vram_gb"]))
    for name in ("crash.log", "window.log", "backend.log"):
        p = LOGS / name
        if p.exists():
            hits = _scan_text(p)
            crashes += [f"{name}: {x}" for x in hits]
    for p in LOGS.glob("setup_*.log"):
        hits = _scan_text(p, cap=100000)
        crashes += [f"{p.name}: {x}" for x in hits]
        if p.stat().st_size < 8 << 20 and any("装好了" in line for line in open(p, "r", encoding="utf-8", errors="replace")):
            tasks["setup"] += 1
    # report.jsonl：只数次数，不复制文案（里面可能有用户描述）
    rp = LOGS / "report.jsonl"
    if rp.exists():
        for e in _iter_jsonl(rp, cap=200000):
            text = str(e.get("text") or "")
            job = str(e.get("job") or "")
            if "配乐好了" in text:
                tasks["bgm"] += 1
            elif "配音好了" in text or "这一段好了" in text:
                tasks["tts"] += 1
            elif job in ("一键补齐", "整备") and e.get("kind") == "head" and str(e.get("text") or "").startswith("开始"):
                tasks["setup"] += 1
    ap = LOGS / "actions.jsonl"
    if ap.exists():
        for e in _iter_jsonl(ap, cap=200000):
            if str(e.get("action") or "") in ("tool.remove", "privacy.send") or "拦截" in str(e.get("action") or ""):
                safety["拦截"] += 1
    slow.sort(reverse=True)
    return crashes[-40:], under, slow[:10], tasks, vram, safety


def _md(crashes, under, slow, tasks, vram, safety, retain, now):
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")
    L = [f"# 重要事项永久备份 · {day}", "",
         f"> 保留周期：{retain} 天。原始日志清理后，这份报告永久保留。只放聚合统计和错误类别，不含聊天/提醒原文、密钥或账号。", "",
         "## 1. 崩溃与严重故障档案", ""]
    if crashes:
        L += [f"- {telemetry.mask_text(x)}" for x in crashes[-30:]]
    else:
        L.append("- 没有发现致命崩溃或子进程异常退出。")
    L += ["", f"- 安全拦截/隐私相关动作：{safety.get('拦截', 0)} 次。", "",
          "## 2. 性能与卡顿体检", "",
          f"- 语音朗读异常（underrun / 首包慢）：{under.get('count', 0)} 次；总停顿 {int(under.get('stall_ms', 0))}ms；最大首包 {int(under.get('max_ttfa_ms', 0))}ms；最大 RTF {under.get('max_rtf', 0):.2f}。",
          f"- 显存峰值：{vram.get('peak_gb', 0):.1f} GB；显存让路：{vram.get('yield', 0)} 次。", ""]
    if slow:
        L += ["| 耗时 | 接口 | 状态码 | 时间 |", "|---:|---|---:|---|"]
        L += [f"| {int(d)}ms | `{t}` | {c} | {tm} |" for d, t, c, tm in slow]
    else:
        L.append("- 没有超过 200ms 的慢接口记录。")
    L += ["", "## 3. 重要任务与里程碑记录", "",
          f"- 配音完成：{tasks.get('tts', 0)} 次；配乐完成：{tasks.get('bgm', 0)} 次；Claude Code 任务：{tasks.get('ccode', 0)} 次；整备/一键补齐：{tasks.get('setup', 0)} 次。", "",
          "## 4. 说明", "",
          "- 本报告由 `app/log_archive.py` 自动生成；原始日志在 `data/logs/archive/` 里按日期压缩，最近 30 天热日志保留。"]
    return "\n".join(L) + "\n"


def _expired(now, retain):
    cutoff = now - retain * 86400
    out = []
    for p in telemetry.DIR.glob("trace_*.jsonl"):
        m = re.match(r"trace_(\d{4})-(\d{2})\.jsonl$", p.name)
        if m:
            month_end = datetime(int(m.group(1)), int(m.group(2)) + 1, 1).timestamp() if int(m.group(2)) < 12 else datetime(int(m.group(1)) + 1, 1, 1).timestamp()
            if month_end < cutoff:
                out.append(p)
    for p in telemetry.DIR.glob("behavior_*.log"):
        m = re.match(r"behavior_(\d{4})-(\d{2})\.log$", p.name)
        if m:
            month_end = datetime(int(m.group(1)), int(m.group(2)) + 1, 1).timestamp() if int(m.group(2)) < 12 else datetime(int(m.group(1)) + 1, 1, 1).timestamp()
            if month_end < cutoff:
                out.append(p)
    for pat in ("*.old.log", "setup_*.log"):
        for p in LOGS.glob(pat):
            try:
                if p.stat().st_mtime < cutoff:
                    out.append(p)
            except OSError:
                pass
    return out


def _zip(files, now):
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    zp = ARCHIVE / f"logs_before_{stamp}.zip"
    if zp.exists():
        zp = ARCHIVE / f"logs_before_{stamp}_{datetime.fromtimestamp(now):%H%M%S}.zip"
    total = 0
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            try:
                z.write(p, p.relative_to(LOGS).as_posix())
                total += p.stat().st_size
            except OSError:
                pass
    return zp, total


def run(force=False, now=None):
    """执行一次。force=True：忽略周期，立即做（设置里的按钮）。"""
    now = now or time.time()
    if not force and not due(now):
        return {"ok": True, "skipped": True, **status()}
    retain = _retain()
    crashes, under, slow, tasks, vram, safety = _collect()
    md = _md(crashes, under, slow, tasks, vram, safety, retain, now)
    report = {"generated_at": now, "time": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"), "retain_days": retain,
              "crashes": crashes[-40:], "underrun": under, "slow_api": slow, "tasks": tasks, "vram": vram, "safety": safety}
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    BACKUP.mkdir(parents=True, exist_ok=True)
    WS_BACKUP.mkdir(parents=True, exist_ok=True)
    md_name = f"重要事项备份_{day}.md"
    js_name = f"重要事项备份_{day}.json"
    for d in (BACKUP, WS_BACKUP):
        (d / md_name).write_text(md, "utf-8")
        (d / js_name).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    old = _expired(now, retain)
    zp, total = _zip(old, now) if old else (None, 0)
    manifest = ARCHIVE / f"清理清单_{day}.md"
    if old:
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        manifest.write_text("\n".join([f"# 日志清理清单 · {day}", "", f"- 保留周期：{retain} 天", f"- 压缩包：{zp.name}", f"- 文件数：{len(old)}", f"- 原始大小：{total / 2**20:.1f} MB", "",
                                       "| 文件 | 字节 |", "|---|---:|"] + [f"| {p.relative_to(LOGS).as_posix()} | {p.stat().st_size} |" for p in old]) + "\n", "utf-8")
        for p in old:
            try:
                p.unlink()
            except OSError:
                pass
    db.kv_set("logArchiveLast", now)
    msg = f"日志归档：重要事项备份 {md_name}；" + (f"压缩 {len(old)} 个过期日志（{total / 2**20:.1f} MB）→ {zp.name}" if zp else "没有到期的原始日志需要压缩")
    feed.add(msg, "ok", job="日志归档")
    return {"ok": True, "skipped": False, "report": str(BACKUP / md_name), "report_ws": str(WS_BACKUP / md_name),
            "zip": str(zp) if zp else "", "files": len(old), "bytes": total, "retain_days": retain, "last": now, "msg": msg}


def maybe_run():
    try:
        if due():
            return run(False)
    except Exception as e:
        print("日志归档出错：", e)
    return None
