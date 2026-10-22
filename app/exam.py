"""决策脑中文实测：40 道题，看语义路由和 Kev 各自判对多少，隐私认出多少。
设置里开了"按实测自动定权重"的话，跑完会按两票的准确率分配权重。"""
import time

from . import db, privacy, router, settings
from .models import M
from .seeds import EXAM


def _top3(p, local_keys):
    agg = {"local": sum(p.get(k, 0) for k in local_keys), "ds": p.get("ds", 0), "cl": p.get("cl", 0)}
    return max(agg, key=agg.get)


async def run():
    await router.embed_missing()
    bl = router.brains()
    local_keys = [b["key"] for b in bl]
    keys = local_keys + ["ds", "cl", "neu"]
    texts = [t for t, _, _ in EXAM]
    vecs = await M.embed(texts)
    kev_on = await M.ensure_kev(wait=False) or await M.kev_ready()
    res = {"n": len(EXAM), "embed": None, "kev": None, "two": None, "privacy_kw": 0, "privacy_kev": None, "ts": time.time(), "detail": []}
    ce = ck = c2 = 0
    pk = pk_n = 0
    priv_total = sum(1 for _, _, pv in EXAM if pv)
    kw_hit = 0
    for i, (text, want, pv) in enumerate(EXAM):
        row = {"text": text, "want": want}
        if privacy.check(text)[0] and pv:
            kw_hit += 1
        ev = router.embed_vote(vecs[i], keys) if vecs else None
        if ev:
            row["embed"] = _top3(ev["p"], local_keys)
            ce += row["embed"] == want
        kv = await router.kev_vote(text, bl) if kev_on else None
        if kv:
            row["kev"] = _top3(kv["p"], local_keys)
            ck += row["kev"] == want
            if pv:
                pk_n += 1
                pk += kv["private_p"] >= 0.6
        if ev and kv:
            we, wk = router.weights()
            p = {k: we * ev["p"].get(k, 0) + wk * kv["p"].get(k, 0) for k in keys}
            row["two"] = _top3(p, local_keys)
            c2 += row["two"] == want
        res["detail"].append(row)
    n = len(EXAM)
    if vecs:
        res["embed"] = round(ce / n * 100)
    if any("kev" in r for r in res["detail"]):
        res["kev"] = round(ck / n * 100)
        res["privacy_kev"] = round(pk / pk_n * 100) if pk_n else None
    if res["embed"] is not None and res["kev"] is not None:
        res["two"] = round(c2 / n * 100)
        if settings.S["voteAuto"] and (res["embed"] + res["kev"]) > 0:
            settings.update({"voteEmbed": round(res["embed"] / (res["embed"] + res["kev"]) * 100)})
    res["privacy_kw"] = round(kw_hit / priv_total * 100) if priv_total else None
    if res["embed"] is None and res["kev"] is None:
        raise RuntimeError("两票都没法实测：模型服务还没起来，Kev 也没准备好")
    db.kv_set("exam", res)
    hist = db.kv_get("exam_hist", []) or []
    hist.append({"ts": res["ts"], "embed": res["embed"], "kev": res["kev"], "two": res["two"]})
    db.kv_set("exam_hist", hist[-30:])
    return res
