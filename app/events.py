"""事件日志：每件事收到了什么、四个去向各自几分、最后交给谁、结果如何。界面"事件"页读这里。"""
import json
import time
from datetime import datetime

from . import db

SRC = {"qq": "QQ", "ui": "界面", "cron": "定时任务", "system": "系统"}


CH = {"qq": "QQ", "toast": "电脑弹窗", "card": "界面卡片"}


def log_system(text, channels):
    ch = channels or {}
    ok = [CH.get(k, k) for k, v in ch.items() if v.get("ok")]
    info = "；".join(CH.get(k, k) + "：" + str(v.get("info")) for k, v in ch.items())
    steps = [["收到", "定时任务触发"], ["本地处理", "提醒不经过任何模型"], ["送达", "、".join(ok) or "全部失败"]]
    return db.insert("events", {"ts": time.time(), "src": "cron", "text": text, "private": 0, "route": "local", "ui_to": "local",
                                "label": "提醒（不经过模型）", "conf": 100, "scores": {"local": 100, "neu": 0, "ds": 0, "cl": 0},
                                "why": "定时提醒由程序直接发出，不需要决策脑判断。", "steps": steps, "result": info, "status": "done"})


def to_ui(e: dict) -> dict:
    sc = db.jl(e.get("scores"), {}) or {}
    votes = db.jl(e.get("votes"), {}) or {}
    return {
        "id": e["id"], "t": datetime.fromtimestamp(e["ts"]).strftime("%H:%M"), "date": datetime.fromtimestamp(e["ts"]).strftime("%m-%d"),
        "ts": e["ts"], "src": SRC.get(e["src"], e["src"]),
        "text": e["text"], "to": e["ui_to"] or "ds", "label": e["label"] or "", "private": bool(e["private"]),
        "s": {k: int(sc.get(k, 0)) for k in ("local", "neu", "ds", "cl")}, "why": e["why"] or "", "result": e["result"] or "",
        "reply": e["reply"] or "", "steps": db.jl(e.get("steps"), []) or [], "fix": e["fix"], "teacher": e["teacher"],
        "status": e["status"], "cost": round(e["cost"] or 0, 4), "latency": e["latency"],
        "votes": {"mode": votes.get("mode"), "embed": _vote_brief(votes.get("embed")), "kev": _vote_brief(votes.get("kev")),
                  "weights": votes.get("weights")},
    }


def _vote_brief(v):
    if not v:
        return None
    p = v.get("p") or {}
    top = max(p, key=p.get) if p else None
    return {"top": top, "p": round(p.get(top, 0) * 100) if top else 0, "maxsim": v.get("maxsim"), "private_p": v.get("private_p")}


def recent(limit=60):
    return [to_ui(e) for e in db.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]


def get(eid):
    e = db.one("SELECT * FROM events WHERE id=?", (eid,))
    return to_ui(e) if e else None


def dumps(x):
    return json.dumps(x, ensure_ascii=False)
