r"""全链路行为遥测（v3.5）。

一条事件的标准结构：
  {"ts": 毫秒, "time": "YYYY-MM-DD HH:MM:SS.mmm", "trace_id": "tr_...", "cat": "类别",
   "action": "动作", "target": "控件或接口", "status": "ok|warn|err", "dur_ms": 12.3,
   "metrics": {...}, "msg": "中文摘要"}

存哪：
  data\logs\telemetry\trace_YYYY-MM.jsonl       结构化，按月追加，不覆盖
  data\logs\telemetry\behavior_YYYY-MM.log      人看的镜像
  data\logs\important_backups\                  log_archive.py 提炼的重要事项永久备份
  data\logs\archive\                            log_archive.py 压缩的旧日志

隐私：入盘前统一脱敏（API Key、Token、密码、Bearer、appSecret 等），只留行为、状态、耗时和非敏感摘要。
"""
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import paths

DIR = paths.LOGS / "telemetry"
_LOCK = threading.Lock()
CAT_CN = {"ui": "按键", "api": "接口", "voice": "语音诊断", "audio": "音频", "proc": "子进程", "js": "前端异常", "vram": "显存", "app": "应用"}

# 只保留前 4 位，避免把密钥原文写进日志
SECRET_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "sk-***"),
    (re.compile(r"\bhf_[A-Za-z0-9]{12,}\b"), "hf_***"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "AIza***"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{12,}\b", re.I), "Bearer ***"),
    (re.compile(r"(?i)\b(password|passwd|token|secret|appSecret|apiKey|api_key|key)\b\s*[:=]\s*['\"]?[^'\"\s,}&]{6,}"), r"\1=***"),
]


def new_trace():
    return "tr_" + uuid.uuid4().hex[:16]


def mask_text(s):
    """给日志/报告用：API Key、Token、密码等一律打码；长文本截断。"""
    s = str(s if s is not None else "")
    for rx, rep in SECRET_PATTERNS:
        s = rx.sub(rep, s)
    return s[:1000]


def clean(v, depth=0):
    """递归脱敏。只允许 JSON 基本类型，避免把对象 repr 写进日志。"""
    if depth > 4:
        return mask_text(v)
    if isinstance(v, dict):
        return {str(k)[:60]: clean(x, depth + 1) for k, x in list(v.items())[:40]}
    if isinstance(v, (list, tuple)):
        return [clean(x, depth + 1) for x in list(v)[:60]]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return mask_text(v)


def _now():
    t = time.time()
    return t, datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S.") + f"{int((t % 1) * 1000):03d}"


def _month(ts=None):
    return time.strftime("%Y-%m", time.localtime(ts if ts is not None else time.time()))


def _paths(ts=None):
    m = _month(ts)
    return DIR / f"trace_{m}.jsonl", DIR / f"behavior_{m}.log"


def snapshot():
    """当前瞬间的显卡/显存/子进程。只在 warn/err 或语音断流时附带，平时不查。"""
    gpu = {}
    try:
        from . import hw
        d = (hw._cache.get("data") or {}).get("gpu") or {}
        for k_src, k_dst in (("load", "gpu_load"), ("vram", "vram_gb"), ("vramTotal", "vram_total_gb")):
            if d.get(k_src) is not None:
                gpu[k_dst] = round(float(d[k_src]), 2)
    except Exception:
        pass
    procs, seen = [], set()

    def add(name, proc):
        if not proc or name in seen:
            return
        seen.add(name)
        try:
            procs.append({"name": name, "pid": proc.p.pid if proc.alive() else 0, "alive": bool(proc.alive())})
        except Exception:
            procs.append({"name": name, "pid": 0, "alive": False})

    try:
        from .models import M
        add("本地模型服务", M.server)
        add("Kev", M.kevp)
        name_map = {"tts": "配音服务", "voice": "语音服务", "bgm": "配乐服务"}
        for p in getattr(M, "extra", []):
            add(name_map.get(p.name, p.name), p)
    except Exception:
        pass
    for mod, attr in (("tts", "T"), ("voice", "V"), ("bgm", "B")):
        try:
            m = __import__("app." + mod, fromlist=[attr])
            add({"tts": "配音服务", "voice": "语音服务", "bgm": "配乐服务"}[mod], getattr(m, attr).proc)
        except Exception:
            pass
    try:
        from . import ccode
        for eid, r in list(ccode.RUNNING.items()):
            p = r.get("p")
            procs.append({"name": f"Claude Code·{eid}", "pid": p.pid if p and p.poll() is None else 0, "alive": bool(p and p.poll() is None)})
    except Exception:
        pass
    return {"gpu": gpu, "procs": procs}


def log(cat="app", action="", target="", status="ok", dur_ms=None, metrics=None, msg="", trace_id="", ts=None):
    """写一条遥测。任何异常都不影响主流程。"""
    try:
        if ts is None:
            t, human = _now()
        else:
            t = float(ts) / 1000.0
            human = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S.") + f"{int(float(ts) % 1000):03d}"
        ev = {"ts": round(t * 1000) if ts is None else int(ts), "time": human, "trace_id": trace_id or new_trace(),
              "cat": str(cat or "app")[:24], "action": mask_text(str(action or "")[:80]), "target": mask_text(str(target or "")[:300]),
              "status": status if status in ("ok", "warn", "err") else "ok",
              "dur_ms": round(float(dur_ms), 1) if dur_ms is not None else None,
              "metrics": clean(metrics or {}), "msg": mask_text(msg)}
        if ev["status"] in ("warn", "err") or (ev["cat"] == "voice" and ev["action"] in ("underrun", "first_chunk")):
            snap = snapshot()
            if snap.get("gpu") or snap.get("procs"):
                ev["metrics"]["snapshot"] = clean(snap)
        DIR.mkdir(parents=True, exist_ok=True)
        jp, bp = _paths(t)
        line = json.dumps(ev, ensure_ascii=False)
        stamp = ev["time"].split(" ")[-1]
        tag = CAT_CN.get(ev["cat"], ev["cat"])
        flag = " [警告]" if ev["status"] == "warn" else " [错误]" if ev["status"] == "err" else ""
        human = f'[{stamp}] [{tag}] {ev["target"] or ev["action"]} · {ev["msg"] or ev["action"]}{f" ({ev["dur_ms"]}ms)" if ev["dur_ms"] is not None else ""}{flag} ({ev["trace_id"]})\n'
        with _LOCK:
            with open(jp, "a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
            with open(bp, "a", encoding="utf-8", errors="replace") as f:
                f.write(human)
        return ev
    except Exception:
        return None


def ingest(events):
    """前端批量上报。最多 200 条，字段只用认识的，避免前端塞任意内容。"""
    if not isinstance(events, list):
        return 0
    n = 0
    for e in events[:200]:
        if not isinstance(e, dict):
            continue
        log(cat=str(e.get("cat") or "ui")[:24], action=str(e.get("action") or "")[:80],
            target=str(e.get("target") or "")[:300], status=str(e.get("status") or "ok")[:4],
            dur_ms=e.get("dur_ms") if isinstance(e.get("dur_ms"), (int, float)) else None,
            metrics=e.get("metrics") if isinstance(e.get("metrics"), dict) else {},
            msg=str(e.get("msg") or ""), trace_id=str(e.get("trace_id") or "")[:40],
            ts=e.get("ts") if isinstance(e.get("ts"), (int, float)) else None)
        n += 1
    return n


def _tail_json(path, max_bytes=2 << 20):
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = data.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def read(limit=300, cat="", q="", bad=False, trace=""):
    """后台页用：最近的行为，按时间倒序。cat 可以是逗号分隔的多个类别。"""
    files = sorted(DIR.glob("trace_*.jsonl"), reverse=True)[:2]
    items = []
    for p in files:
        items.extend(_tail_json(p))
    cats = {x.strip() for x in str(cat or "").split(",") if x.strip()}
    q = str(q or "").strip().lower()
    trace = str(trace or "").strip().lower()
    out = []
    for e in items:
        if cats and e.get("cat") not in cats:
            continue
        if bad and e.get("status") not in ("warn", "err"):
            continue
        if trace and trace not in str(e.get("trace_id") or "").lower():
            continue
        if q:
            blob = (str(e.get("target") or "") + " " + str(e.get("msg") or "") + " " + str(e.get("action") or "") + " " + str(e.get("trace_id") or "")).lower()
            if q not in blob:
                continue
        out.append(e)
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out[:max(1, min(int(limit or 300), 2000))]


def month_files():
    return sorted(DIR.glob("trace_*.jsonl")) + sorted(DIR.glob("behavior_*.log"))


def today_count():
    try:
        return len(_tail_json(_paths()[0], max_bytes=4 << 20))
    except Exception:
        return 0
