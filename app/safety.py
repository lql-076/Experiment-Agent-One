"""安全闸：先斩后奏还是先问你，由这里的分级决定，不让模型自己判断。

- auto：能撤销的事，直接做，事后写进报告（changes 表 + 哈希链日志）
- ask：撤销不了的事，先放进"等你决定"，你点同意才执行
- 没登记的动作一律按 ask 处理（宁严勿松）
每一次动作都写进 data/logs/actions.jsonl，每行带上一行的哈希，事后改不了。
"""
import hashlib
import json
import threading
import time

from . import db, paths, settings

# 动作 -> (默认分级, 能否在界面上改, 中文名)
TIERS = {
    "brain.create":    ("auto", True,  "新建、更新小脑"),
    "memory.write":    ("auto", True,  "新增、修改技能和记忆文件"),
    "reminder.create": ("auto", True,  "新增、修改定时任务"),
    "reminder.update": ("auto", True,  "新增、修改定时任务"),
    "prompt.update":   ("auto", True,  "调整自己的提示词"),
    "file.delete":     ("ask",  False, "删除任何文件"),
    "reminder.delete": ("ask",  False, "删除任何文件"),
    "tool.add":        ("ask",  False, "给自己加新工具或新权限"),
    "money":           ("ask",  False, "花钱：充值、换更贵的模型、提高额度"),
    "privacy.send":    ("ask",  False, "把隐私内容发出本机"),
}
# 界面"安全线"页面的分组键 -> 动作
GROUPS = {"brain": ["brain.create"], "skill": ["memory.write"], "cron": ["reminder.create", "reminder.update"],
          "prompt": ["prompt.update"]}

_lock = threading.Lock()
_LOG = paths.LOGS / "actions.jsonl"
_handlers = {}


def tier(action: str) -> str:
    base = TIERS.get(action)
    if not base:
        return "ask"
    t, changeable, _ = base
    if changeable:
        over = db.kv_get("safety", {}) or {}
        for g, acts in GROUPS.items():
            if action in acts and over.get(g) in ("auto", "ask"):
                return over[g]
    return t


def set_group(group: str, value: str):
    if group not in GROUPS or value not in ("auto", "ask"):
        raise ValueError("这一项不能改")
    over = db.kv_get("safety", {}) or {}
    over[group] = value
    db.kv_set("safety", over)


def log(action: str, detail: dict, decision: str):
    """哈希链日志：每行包含上一行的哈希。"""
    with _lock:
        prev = "0" * 64
        try:
            with open(_LOG, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                last = f.read().strip().split(b"\n")[-1]
                if last:
                    prev = json.loads(last)["hash"]
        except (FileNotFoundError, ValueError, KeyError):
            pass
        rec = {"ts": time.time(), "action": action, "tier": tier(action), "decision": decision, "detail": detail, "prev": prev}
        rec["hash"] = hashlib.sha256(json.dumps(rec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def verify_log() -> dict:
    """检查日志有没有被改过。"""
    prev, n = "0" * 64, 0
    try:
        with open(_LOG, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                h = rec.pop("hash")
                if rec["prev"] != prev or hashlib.sha256(json.dumps(rec, ensure_ascii=False, sort_keys=True).encode()).hexdigest() != h:
                    return {"ok": False, "bad_line": n + 1}
                prev, n = h, n + 1
    except FileNotFoundError:
        pass
    return {"ok": True, "lines": n}


def handler(kind):
    def deco(fn):
        _handlers[kind] = fn
        return fn
    return deco


async def request(action: str, what: str, why: str, payload: dict, run):
    """agent 想做一件事时调用。auto 就直接 run()，ask 就排队等你。返回 (done, result_or_ask_id)。"""
    t = tier(action)
    if t == "auto":
        res = await run()
        log(action, {"what": what, "why": why}, "auto")
        return True, res
    ask_id = db.insert("asks", {"ts": time.time(), "kind": action, "what": what, "why": why,
                                "payload": json.dumps(payload, ensure_ascii=False)})
    log(action, {"what": what, "why": why, "ask": ask_id}, "queued")
    return False, ask_id


async def decide(ask_id: int, approve: bool) -> str:
    a = db.one("SELECT * FROM asks WHERE id=?", (ask_id,))
    if not a or a["status"] != "pending":
        return "这件事已经处理过了"
    if approve:
        fn = _handlers.get(a["kind"])
        msg = "已同意"
        if fn:
            try:
                msg = await fn(db.jl(a["payload"], {})) or msg
            except Exception as e:
                msg = f"同意了，但执行失败：{e}"
        db.update("asks", ask_id, {"status": "approved", "decided_ts": time.time()})
        log(a["kind"], {"ask": ask_id}, "approved")
        return msg
    db.update("asks", ask_id, {"status": "denied", "decided_ts": time.time()})
    log(a["kind"], {"ask": ask_id}, "denied")
    return "已拒绝，它不会再提同样的请求"


def record_change(kind: str, what: str, evidence: str, commit_id: str = "") -> int:
    return db.insert("changes", {"ts": time.time(), "kind": kind, "what": what, "evidence": evidence, "commit_id": commit_id})


def safety_view():
    over = db.kv_get("safety", {}) or {}
    out = {}
    for g, acts in GROUPS.items():
        out[g] = over.get(g) or TIERS[acts[0]][0]
    return out


_ = settings  # 预留：以后按设置调整分级
