"""进展报告：正在做的事，一步一步写成人话。后台页「进展报告」标签里一条一条显示。

每条：{id, ts, job, step, kind, text, prog?}
  kind：head 开始/结束一件事 · step 开始一步 · info 普通 · ok 好了 · warn 要注意 · err 出错
        ds DeepSeek 的判断 · prog 进度（同一个 key 原地更新，不刷屏）
内存里留最近 600 条；除了进度行，每条也写进 data\\logs\\report.jsonl，后端重启后还能看到之前的。
"""
import json
import threading
import time
from collections import deque

from . import paths

FEED = deque(maxlen=600)
_lock = threading.Lock()
_st = {"seq": 0, "ver": 0}
FILE = paths.LOGS / "report.jsonl"


def _save(e):
    try:
        if FILE.exists() and FILE.stat().st_size > 2 << 20:
            FILE.replace(FILE.with_suffix(".old.jsonl"))
        with open(FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in e.items() if k not in ("key", "prog")}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def add(text, kind="info", job="", step="", key=None, prog=None):
    """加一条。给了 key 就是"同一件事的最新状态"：最近有同 key 的就原地更新。"""
    text = str(text).strip()
    if not text:
        return None
    with _lock:
        _st["ver"] += 1
        if key:
            for i, e in enumerate(reversed(FEED)):
                if i > 80:
                    break
                if e.get("key") == key:
                    e.update(text=text, kind=kind, ts=time.time(), prog=prog)
                    if kind != "prog":
                        e.pop("key", None)        # 定下来了，后面同 key 的另起一行
                        _save(e)
                    return e
        _st["seq"] += 1
        e = {"id": _st["seq"], "ts": time.time(), "job": job, "step": step, "kind": kind, "text": text[:400]}
        if key and kind == "prog":
            e["key"] = key
        if prog:
            e["prog"] = prog
        FEED.append(e)
        if kind != "prog":
            _save(e)
        return e


def finish(key, text, kind="ok"):
    """把一条进度行定下来（比如"下载 PyTorch 完成 · 3.4 GB · 用时 2 分"）。没有这一行就什么都不做。"""
    with _lock:
        for e in reversed(FEED):
            if e.get("key") == key:
                _st["ver"] += 1
                e.update(text=text, kind=kind, ts=time.time())
                e.pop("key", None)
                e.pop("prog", None)
                _save(e)
                return True
    return False


def drop(key):
    """删掉一条还没定下来的进度行（"测哪个源最快"这种只是转圈的，结束后不用留）。"""
    with _lock:
        for e in reversed(FEED):
            if e.get("key") == key:
                FEED.remove(e)
                _st["ver"] += 1
                return True
    return False


def has(key):
    with _lock:
        return any(e.get("key") == key for e in FEED)


def last(job):
    """某件事最近一句话（不算进度行），给"正在做"卡片用。"""
    with _lock:
        for e in reversed(FEED):
            if e.get("job") == job and e.get("kind") != "prog" and not e.get("old"):
                return e["text"]
    return ""


def view(n=400):
    with _lock:
        items = list(FEED)[-n:]
        return {"ver": _st["ver"], "items": [{k: v for k, v in e.items() if k != "key"} for e in items]}


def load():
    """后端启动时，把上次的最后 200 条读回来，再加一行"重新启动"。"""
    try:
        lines = FILE.read_text("utf-8", errors="replace").splitlines()[-200:]
    except Exception:
        lines = []
    with _lock:
        for ln in lines:
            try:
                e = json.loads(ln)
            except Exception:
                continue
            _st["seq"] += 1
            e["id"] = _st["seq"]
            e["old"] = True
            FEED.append(e)
    add("后端启动了", "head", job="后端")


# ---------- 小工具：把数字写成人话 ----------
def size(b):
    if not b:
        return "0"
    return f"{b / 2**30:.2f} GB" if b >= 2**30 else f"{b / 2**20:.1f} MB" if b >= 2**20 else f"{b / 1024:.0f} KB"


def dur(s):
    s = int(max(0, s or 0))
    return f"{s // 3600} 小时 {s % 3600 // 60} 分" if s >= 3600 else f"{s // 60} 分 {s % 60} 秒" if s >= 60 else f"{s} 秒"
