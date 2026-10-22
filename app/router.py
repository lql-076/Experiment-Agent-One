"""决策脑：两票打分。

第一票：语义路由。拿新消息的向量和"判例"（初始例子 + 你的纠正 + DeepSeek 打的标签）比相似度，
       越像哪一类就越可能交给谁。离所有判例都远，说明是新类型的事。
第二票：Kev-0.8B。按说明做选择题，给每个去向一个概率。
两票按权重合并（设置里可调，实测后自动定）。两票都没有时，退回到简单规则。
"为什么这么判"直接用真实分数套模板生成，不让模型编理由。
"""
import json
import time

import numpy as np

from . import db, privacy, settings
from .models import M
from .seeds import SEEDS

ROUTE_DESC = {
    "local": "local: everyday small things, reminders, notes, casual chat, anything about health, mood or private info (日常小事、提醒、记笔记、闲聊、健康和隐私)",
    "ds": "deepseek: needs web search, knowledge questions, writing, translation, code, ordinary hard questions (联网查资料、知识问答、写作翻译、写代码、一般难题)",
    "cl": "strong: very complex problems that need long careful discussion with the strongest AI available, like whole-system architecture, long-term planning, deep research (非常复杂、需要深入讨论的难题，交给更强的模型：整体架构、长期规划、深度研究)",
    "neu": "new: a new kind of task that none of the above fits well (以上都不太合适的新类型的事)",
}
UI_KEYS = ("local", "neu", "ds", "cl")


class NeedConfirm(Exception):
    """你指定把隐私的事交给云端：按安全线（隐私内容发出本机）要先问你，确认了再发。"""


def strong_on() -> bool:
    """第三条路「更强的模型」开着没有。关着时，判给它的分数并进 DeepSeek。"""
    return bool(settings.S.get("strongOn", True))


def strong_name() -> str:
    return str(settings.S.get("strongName") or "").strip() or "更强的模型"


class Memory:
    """判例库（带向量）。"""

    def __init__(self):
        self.ids, self.labels, self.priv, self.mat = [], [], [], None
        self.ts = 0

    def load(self):
        rows = db.q("SELECT id,label,private,vec FROM examples WHERE vec IS NOT NULL")
        if not rows:
            self.ids, self.labels, self.priv, self.mat = [], [], [], None
            return
        self.ids = [r["id"] for r in rows]
        self.labels = [r["label"] for r in rows]
        self.priv = [bool(r["private"]) for r in rows]
        self.mat = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
        self.ts = time.time()

    def knn(self, v, k=7):
        if self.mat is None or not len(self.ids):
            return []
        if self.mat.shape[1] != len(v):     # 换了嵌入模型：旧向量作废，全部重算
            reset_vectors()
            return []
        sims = self.mat @ np.asarray(v, dtype=np.float32)
        idx = np.argsort(-sims)[:k]
        return [(self.ids[i], self.labels[i], float(sims[i]), self.priv[i]) for i in idx]


MEM = Memory()


def reset_vectors():
    """嵌入模型换了（向量维度变了）：清掉所有旧向量，后台会用新模型重算。"""
    db.run("UPDATE examples SET vec=NULL")
    db.run("DELETE FROM chunks")
    MEM.load()


def seed_examples():
    if db.one("SELECT id FROM examples WHERE source='seed' LIMIT 1"):
        return
    for text, label, priv in SEEDS:
        db.insert("examples", {"text": text, "label": label, "source": "seed", "private": int(priv), "ts": time.time()})


async def embed_missing():
    """把还没算向量的判例补上（模型服务起来后调用）。"""
    rows = db.q("SELECT id,text FROM examples WHERE vec IS NULL LIMIT 256")
    if not rows:
        return 0
    vecs = await M.embed([r["text"] for r in rows])
    if not vecs:
        return 0
    for r, v in zip(rows, vecs):
        db.run("UPDATE examples SET vec=? WHERE id=?", (np.asarray(v, dtype=np.float32).tobytes(), r["id"]))
    MEM.load()
    return len(rows)


def add_example(text, label, source, private=False, event_id=None, vec=None):
    if event_id is not None:
        old = db.one("SELECT id,source FROM examples WHERE event_id=?", (event_id,))
        # 你的纠正优先：老师的标签不覆盖你的纠正
        if old and old["source"] == "fix" and source != "fix":
            return
        if old:
            db.run("DELETE FROM examples WHERE id=?", (old["id"],))
    db.insert("examples", {"text": text, "label": label, "source": source, "private": int(private), "event_id": event_id,
                           "vec": np.asarray(vec, dtype=np.float32).tobytes() if vec is not None else None, "ts": time.time()})
    MEM.load()


def brains():
    """本地小脑列表：本地通用（只用底座）+ models/brains 下的每个 LoRA。"""
    out = [{"key": "local", "name": "本地通用", "lora": None,
            "desc": "日常小事、提醒、记笔记、闲聊、健康和隐私"}]
    for b in db.kv_get("brains", []) or []:
        out.append({"key": "brain:" + b["name"], "name": b["name"], "lora": b["name"], "desc": b.get("desc", "")})
    return out


def embed_vote(vec, labels_all):
    nn = MEM.knn(vec)
    if not nn:
        return None
    tau = 0.05
    agg = {k: 0.0 for k in labels_all}
    for _, lab, sim, _ in nn:
        if lab in agg:
            agg[lab] += float(np.exp(sim / tau))
    tot = sum(agg.values()) or 1.0
    p = {k: v / tot for k, v in agg.items()}
    maxsim = nn[0][2]
    # 离判例都远 → 把不确定的部分放进"新类别"
    c = min(1.0, max(0.0, (maxsim - 0.45) / (0.80 - 0.45)))
    out = {k: c * v for k, v in p.items()}
    out["neu"] = out.get("neu", 0.0) + (1 - c)
    priv_sim = max([s for _, _, s, pv in nn if pv] or [0.0])
    return {"p": out, "maxsim": round(maxsim, 3), "certainty": round(c, 3), "private_sim": round(priv_sim, 3),
            "nearest": [{"id": i, "label": l, "sim": round(s, 3)} for i, l, s, _ in nn[:3]]}


async def kev_vote(text, bl):
    crit = {}
    for b in bl:
        crit[b["key"]] = ROUTE_DESC["local"] if b["key"] == "local" else f"{b['key']}: {b['desc']}"
    for k in ("ds", "cl", "neu"):
        crit[k] = ROUTE_DESC[k]
    qs = {
        "route": {"type": "choice", "instructions": "Who should handle this message to a personal assistant? 这条消息应该交给谁处理？", "criteria": crit},
        "private": {"type": "noul", "instructions": "Does this message involve health, body, mood, money, passwords or other private information? 是否涉及健康、身体、情绪、钱、密码等隐私？"},
    }
    ans = await M.kev(text, qs)
    if not ans:
        return None
    r = ans.get("route", {})
    return {"p": {k: float(v) for k, v in (r.get("probabilities") or {}).items()}, "confidence": r.get("confidence"),
            "private_p": float(ans.get("private", {}).get("noul", 0.0))}


def weights():
    w = float(settings.S["voteEmbed"]) / 100.0
    return max(0.0, min(1.0, w)), max(0.0, min(1.0, 1 - w))


async def decide(text: str, vec=None, force=None, allow_private=False):
    """force：你指定交给谁（local / neu / ds / cl），分数照样算出来给你看，但按你说的走。
    隐私的事指定给云端，要 allow_private=True（界面上你点了确认）才行，不然抛 NeedConfirm。"""
    s = settings.S
    bl = brains()
    keys = [b["key"] for b in bl] + ["ds", "cl", "neu"]
    t0 = time.time()
    kw_priv, kw = privacy.check(text)
    safe = vec is False     # 出错后的保底：两票都不用，只按简单规则
    if safe:
        vec = None
    elif vec is None:
        vv = await M.embed([text])
        vec = vv[0] if vv else None
    ev = embed_vote(vec, keys) if vec is not None else None
    kv = None if safe else await kev_vote(text, bl)
    we, wk = weights()
    if ev and not kv:
        we, wk = 1.0, 0.0
    elif kv and not ev:
        we, wk = 0.0, 1.0
    p = {k: 0.0 for k in keys}
    if ev or kv:
        for k in keys:
            p[k] = we * (ev["p"].get(k, 0.0) if ev else 0.0) + wk * (kv["p"].get(k, 0.0) if kv else 0.0)
        tot = sum(p.values()) or 1.0
        p = {k: v / tot for k, v in p.items()}
        mode = "two" if (ev and kv) else ("embed" if ev else "kev")
    else:
        # 两票都没有：模型还没装好。隐私走本地，其他交 DeepSeek
        p.update({"local": 0.7 if kw_priv else 0.2, "ds": 0.3 if kw_priv else 0.7, "cl": 0.0, "neu": 0.1})
        mode = "rules"
    hard = p.get("cl", 0.0)           # "很难"的程度：不用更强的模型时，DeepSeek 靠它决定开不开思考模式
    if not strong_on():               # 你选了不用更强的模型：它那份并进 DeepSeek
        p["ds"] = p.get("ds", 0.0) + p.get("cl", 0.0)
        p["cl"] = 0.0

    priv_reasons = []
    if kw_priv:
        priv_reasons.append(f"包含隐私关键词「{kw}」")
    if ev and ev["private_sim"] >= 0.85:
        priv_reasons.append("和以前的隐私判例很像")
    if kv and kv["private_p"] >= 0.6:
        priv_reasons.append(f"Kev 判断涉及隐私（{kv['private_p']:.0%}）")
    private = bool(priv_reasons)

    local_keys = [b["key"] for b in bl]
    best_local = max(local_keys, key=lambda k: p[k])
    pl = p[best_local]
    take, fresh, cl_line = s["take"] / 100, s["fresh"] / 100, s["clLine"] / 100
    name = {b["key"]: b["name"] for b in bl}
    neu = False
    if private:
        route = best_local
        why = "，".join(priv_reasons) + "。按规则只在本地处理，不发给任何云端。"
    elif pl >= take:
        route = best_local
        why = f"{name[best_local]}的把握 {pl:.0%}，高于接手线 {take:.0%}，交给本地。"
    else:
        cloud = "cl" if (strong_on() and p["cl"] >= cl_line and p["cl"] > p["ds"]) else "ds"
        route = cloud
        if cloud == "cl":
            why = f"「{strong_name()}」得分 {p['cl']:.0%}，超过 {cl_line:.0%}，属于很复杂的难题，建议你带着提示词亲自去和{strong_name()}深聊。"
        else:
            neu = pl < fresh and p["neu"] >= max(p["ds"], p["cl"])
            if neu:
                why = f"所有本地小脑都低于新类别线 {fresh:.0%}（最高 {pl:.0%}），像是一类新事情：先交给 DeepSeek，同时记为样本。"
            else:
                why = f"本地的把握只有 {pl:.0%}，低于接手线 {take:.0%}，交给 DeepSeek。"
    vote_line = []
    if ev:
        top = max((k for k in keys), key=lambda k: ev["p"].get(k, 0))
        vote_line.append(f"语义路由 → {label_of(top, name)} {ev['p'].get(top, 0):.0%}")
    if kv:
        top = max(kv["p"], key=kv["p"].get) if kv["p"] else "ds"
        vote_line.append(f"Kev → {label_of(top, name)} {kv['p'].get(top, 0):.0%}")
    if not vote_line:
        vote_line.append("本地模型还没准备好，按简单规则判断")
    ui_to = "local" if route in local_keys else ("neu" if neu else route)
    ui = {"local": pl, "neu": p["neu"], "ds": p["ds"], "cl": p["cl"]}
    tot = sum(ui.values()) or 1.0
    ui = {k: int(round(v / tot * 100)) for k, v in ui.items()}
    conf = ui[ui_to]
    forced = None
    if force in UI_KEYS and force != ui_to:
        # 你说了算：决策脑原本的判断写进"为什么"，按你指定的去向走
        if force != "local" and private and not allow_private:
            raise NeedConfirm("这件事涉及隐私（" + "，".join(priv_reasons) + "），交给云端要你先确认")
        forced = {"to": force, "natural": ui_to, "natural_conf": conf}
        nat = name.get(route, label_of(ui_to, name)) if ui_to == "local" else label_of(ui_to, name)
        if force == "local":
            route = best_local
        else:
            route = "cl" if force == "cl" else "ds"
        neu = force == "neu"
        why = f"你指定交给「{label_of(force, name) if force != 'local' else name[best_local]}」。决策脑原本判给「{nat}」（{conf}%）：{why}"
        ui_to = force
        conf = ui[ui_to]
        if force != "local" and private:
            why += " 这件事涉及隐私，你确认了发给云端。"
    return {"route": route, "ui_to": ui_to, "brain": route if route in local_keys else None,
            "brain_name": name.get(route), "lora": next((b["lora"] for b in bl if b["key"] == route), None),
            "private": private, "neu": neu, "conf": conf, "scores": ui, "p": {k: round(v, 4) for k, v in p.items()}, "hard": round(hard, 4),
            "votes": {"mode": mode, "weights": [round(we, 2), round(wk, 2)],
                      "embed": ev, "kev": kv, "forced": forced},
            "thresholds": {"take": s["take"], "fresh": s["fresh"], "clLine": s["clLine"]},
            "why": why, "vote_line": "；".join(vote_line), "vec": vec, "ms": int((time.time() - t0) * 1000)}


def label_of(k, name):
    return {"ds": "DeepSeek", "cl": strong_name(), "neu": "新类别"}.get(k) or name.get(k, k)


def dumps(d):
    return json.dumps(d, ensure_ascii=False)
