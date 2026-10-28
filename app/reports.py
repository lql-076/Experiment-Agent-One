"""给界面用的汇总：总览、大脑、报告。全部从本地数据库算出来，每个数都能追到事件。"""
import time
from datetime import datetime, timedelta

from . import checks, db, deepseek, growth, notify, reminders, router, settings, setup, websearch
from .events import recent
from .models import M
from .qq import BOT


def day_start(d=0):
    return (datetime.now() - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def split(since, until=None):
    until = until or time.time() + 1
    c = {"local": 0, "neu": 0, "ds": 0, "cl": 0}
    for r in db.q("SELECT ui_to, COUNT(*) n FROM events WHERE ts>=? AND ts<? AND src!='cron' GROUP BY ui_to", (since, until)):
        if r["ui_to"] in c:
            c[r["ui_to"]] = r["n"]
    return c


def week():
    out = []
    for d in range(6, -1, -1):
        a, b = day_start(d), day_start(d - 1) if d else time.time() + 1
        s = split(a, b)
        tot = sum(s.values())
        out.append([datetime.fromtimestamp(a).strftime("%m-%d"), round(s["local"] / tot * 100) if tot else 0, tot])
    return out


async def _agent():
    """Agent 状态跟着 /api/state 一起给界面（每 5 秒一次），总览和对话页右边都用它。"""
    try:
        from . import agentstate
        return await agentstate.view()
    except Exception as e:
        return {"err": str(e)[:120], "groups": [], "count": {}, "head": "读不到状态"}


def brains_view():
    ex = db.kv_get("exam") or {}
    today = split(day_start())
    fixes_w = db.one("SELECT COUNT(*) n FROM events WHERE fix IS NOT NULL AND ts>?", (time.time() - 7 * 86400,))["n"]
    judged_w = db.one("SELECT COUNT(*) n FROM events WHERE ts>? AND src!='cron'", (time.time() - 7 * 86400,))["n"]
    acc = ex.get("two") or ex.get("embed") or ex.get("kev")
    trend = []
    for d in range(6, -1, -1):
        a, b = day_start(d), day_start(d - 1) if d else time.time() + 1
        n = db.one("SELECT COUNT(*) n FROM events WHERE ts>=? AND ts<? AND src!='cron'", (a, b))["n"]
        f = db.one("SELECT COUNT(*) n FROM events WHERE ts>=? AND ts<? AND fix IS NOT NULL", (a, b))["n"]
        trend.append(round((1 - f / n) * 100) if n else (acc or 0))
    nex = db.one("SELECT COUNT(*) n FROM examples")["n"]
    out = [{
        "kind": "决策脑", "name": "决策脑", "sub": f"两票：语义路由 {settings.S['voteEmbed']}% · Kev {100 - settings.S['voteEmbed']}%",
        "st": "运行中" if M._health else "等模型服务", "c": "var(--accent)",
        "note": "每件事先过它，只打分不说话。准确率来自 40 道中文实测；没实测时显示近 7 天没被你纠正的比例。",
        "ring": [acc or (trend[-1] if judged_w else 0), str(acc if acc is not None else (trend[-1] if judged_w else "—")), "%" if (acc or judged_w) else "", "准确率" if acc else "未实测"],
        "trend": trend, "tmax": 100, "tl": "没被纠正的比例",
        "stats": [["今日判断", str(sum(today.values())), "次"], ["本周被纠正", str(fixes_w), "次"],
                  ["判例", str(nex), "条"], ["语义路由 / Kev 实测", f"{ex.get('embed', '—')} / {ex.get('kev', '—')}", "%" if ex else ""]],
        "acts": [{"label": "运行中文实测", "act": "run_exam"}, {"label": "现在启动 Kev", "act": "start_kev"}]}]
    h = M._health or {}
    out.append({"kind": "本地小脑", "name": "本地通用", "sub": "MiniCPM5-2B 底座 · 不加 LoRA", "c": "var(--c-local)",
                "st": "已加载" if h.get("base_loaded") else ("闲置" if h else "未启动"),
                "note": "还没有专门的小脑时，本地的活都由它做，包括所有隐私内容。",
                "ring": [100 if h.get("base_loaded") else 0, "开" if h.get("base_loaded") else "关", "", "底座"],
                "trend": [r[1] for r in week()], "tmax": 100, "tl": "本地处理比例",
                "stats": [["今日接手", str(today["local"]), "次"], ["精度", settings.S["baseQuant"], ""],
                          ["闲置卸载", str(settings.S["idleUnload"]), "分钟"], ["显存", str((h.get("vram") or {}).get("alloc_gb", "—")), "GB"]],
                "acts": [{"label": "现在加载", "act": "load_base"}, {"label": "卸载", "act": "unload_base"}]})
    for b in router.brains()[1:]:
        out.append({"kind": "本地小脑", "name": b["name"], "sub": "LoRA · 共享底座", "c": "var(--c-local)", "st": "已上线",
                    "note": b["desc"], "ring": [100, "✓", "", "已上线"], "trend": [0] * 7, "tmax": 1, "tl": "接手次数",
                    "stats": [], "acts": []})
    need = int(settings.S["samples"])
    for c in db.q("SELECT * FROM categories ORDER BY count DESC LIMIT 4"):
        out.append({"kind": "新类别", "name": c["name"], "sub": "还没有小脑，暂交 DeepSeek", "c": "var(--c-neu)",
                    "st": "样本够了" if c["status"] == "ready" else "攒样本中",
                    "note": f"攒够 {need} 条（真实 + 造的样本）就能训练专属小脑。",
                    "ring": [min(100, c["count"] / need * 100), str(c["count"]), f"/{need}", "样本"], "trend": [c["count"]] * 7, "tmax": need, "tl": "累计样本",
                    "stats": [["还差", str(max(0, need - c["count"])), "条"], ["第一次出现", datetime.fromtimestamp(c["created"]).strftime("%m-%d"), ""]],
                    "acts": []})
    mc = deepseek.month_cost_cny()
    bal = deepseek.balance_cached() or {}
    total = bal.get("total")
    calls = []
    for d in range(6, -1, -1):
        a, b = day_start(d), day_start(d - 1) if d else time.time() + 1
        calls.append(db.one("SELECT COUNT(*) n FROM costs WHERE ts>=? AND ts<?", (a, b))["n"])
    low = total is not None and total < float(settings.S["dsLow"])
    out.append({"kind": "云端", "name": "DeepSeek", "sub": f"{settings.S['dsModel']} · API", "c": "var(--c-ds)",
                "st": ("余额快用完了" if low else "有 Key") if settings.get_secret("dsKey") else "没填 Key",
                "note": "长对话和一般难题；它的处理记录也是小脑的教材。每日差事里还负责打标签、整理记忆。余额来自官方接口；花费是本机按 token 估算的。",
                "ring": [total / (total + mc) * 100 if total else 0, deepseek.money(total, bal.get("currency", "CNY")), "", "余额"],
                "trend": calls, "tmax": max(5, max(calls)), "tl": "每日调用",
                "stats": [["余额", deepseek.money(total, bal.get("currency", "CNY")), ""], ["本月花了（估算）", f"¥{mc:.2f}", ""],
                          ["今日花了（估算）", f"¥{deepseek.day_cost_cny(day_start()):.3f}", ""],
                          ["本月调用", str(db.one("SELECT COUNT(*) n FROM costs WHERE ts>=?", (datetime.now().replace(day=1, hour=0, minute=0, second=0).timestamp(),))["n"]), "次"],
                          ["贡献样本", str(db.one("SELECT COUNT(*) n FROM events WHERE ui_to IN ('ds','neu') AND private=0")["n"]), "条"]],
                "acts": [{"label": "刷新余额", "act": "ds_balance"}, {"label": "去充值", "act": "topup"}]})
    cps = db.kv_get("claude_prompts", []) or []
    sums = len(db.kv_get("summaries", []) or [])
    out.append({"kind": "云端", "name": router.strong_name(), "sub": "你本人带提示词去聊" if router.strong_on() else "没开：难的事也交给 DeepSeek", "c": "var(--c-cl)",
                "st": "有提示词等你" if any(not c.get("done") for c in cps) else "等你",
                "note": "非常复杂的难题，带提示词去问你能用的最强的 AI（网页 Claude、ChatGPT……）；聊完把总结 .md 带回来，只当参考资料读，不发给 DeepSeek 加工，不进训练集。",
                "ring": [min(100, sums / max(1, len(cps)) * 100) if cps else 0, str(sums), f"/{len(cps)}", "总结已带回"],
                "trend": [0] * 7, "tmax": 2, "tl": "每日求助",
                "stats": [["待处理提示词", str(sum(1 for c in cps if not c.get("done"))), "份"], ["已带回总结", str(sums), "份"]],
                "acts": [{"label": "复制最新提示词", "act": "copy_prompt"}, {"label": "导入总结", "act": "import_summary"}]})
    return out


def changes(limit=12):
    return [{"id": c["id"], "w": c["what"], "e": f"{c['evidence']} · {datetime.fromtimestamp(c['ts']).strftime('%m-%d %H:%M')}",
             "kind": c["kind"], "undone": bool(c["undone"]), "can_undo": bool(c["commit_id"])}
            for c in db.q("SELECT * FROM changes ORDER BY id DESC LIMIT ?", (limit,))]


def asks():
    return [{"id": a["id"], "w": a["what"], "e": a["why"], "kind": a["kind"], "status": a["status"]}
            for a in db.q("SELECT * FROM asks WHERE status='pending' OR decided_ts>? ORDER BY id DESC LIMIT 12", (time.time() - 86400,))]


def report():
    since = time.time() - 7 * 86400
    sp = split(since)
    tot = sum(sp.values())
    fixes = db.one("SELECT COUNT(*) n FROM events WHERE fix IS NOT NULL AND ts>?", (since,))["n"]
    return {"split": sp, "total": tot, "local_pct": round(sp["local"] / tot * 100) if tot else 0, "fixes": fixes,
            "cost_month": round(deepseek.month_cost_cny(), 2), "balance": _bal(), "week": week(),
            "changes": changes(), "asks": asks(), "draft": db.kv_get("weekly_draft"),
            "nightly": db.kv_get("nightly_last"), "new_brains": db.one("SELECT COUNT(*) n FROM categories WHERE status='ready'")["n"]}


def _bal():
    b = deepseek.balance_cached()
    if not settings.get_secret("dsKey"):
        return {"key": False}
    b = b or {}
    return {"key": True, "total": b.get("total"), "currency": b.get("currency", "CNY"), "ts": b.get("ts"), "err": b.get("err"),
            "low": b.get("total") is not None and b["total"] < float(settings.S["dsLow"])}


def tasks():
    """后台正在跑、有进度的活（常驻屏的进度条用，v1.8.8）：安装配音、一键补齐、生成配音。没有就是空列表。"""
    from . import tts, tts_install
    out = []
    i = tts_install.public()
    if i["st"] == "run":
        out.append({"k": "tts_install", "name": "安装配音", "phase": i["phase"] or i["line"] or "准备中", "pct": i["pct"],
                    "speed": i["speed"], "eta": i["eta"]})
    b = setup.brief()
    if b:
        out.append({"k": "setup", "name": f"一键补齐 · 第 {b['n']}/{b['total']} 步 · {b['t']}", "phase": b["phase"] or b["t"], "pct": b["pct"],
                    "speed": b["speed"], "eta": b["eta"]})
    j = tts.T.public()
    if j and j["st"] == "run":
        out.append({"k": "tts", "name": f"生成配音 · {j['voice']}", "phase": f"第 {min(j['i'] + 1, j['n'])}/{j['n']} 句",
                    "pct": round(j["done_chars"] / j["chars"] * 100, 1) if j["chars"] else None, "speed": None, "eta": j["eta"]})
    return out


async def state():
    sp = split(day_start())
    tot = sum(sp.values())
    ck = db.kv_get("checks") or {}
    res = ck.get("res") or {}
    live = [k for k in checks.CHECKS]
    ready = sum(1 for k in live if (res.get(k) or {}).get("st") == "ok")
    ms = await M.status()
    return {"ts": time.time(), "today": sp, "today_total": tot, "local_pct": round(sp["local"] / tot * 100) if tot else 0,
            "cost_month": round(deepseek.month_cost_cny(), 2), "balance": _bal(), "search": websearch.stats(), "agent": await _agent(), "setup": setup.brief(),
            "asks_pending": db.one("SELECT COUNT(*) n FROM asks WHERE status='pending'")["n"],
            "next": reminders.next_info(), "cards": notify.cards(), "train_ask": growth.pending(),
            "prep": {"ready": ready, "total": len(live), "miss": sum(1 for k in live if (res.get(k) or {}).get("st") == "miss"), "ts": ck.get("ts")},
            "qq": {"status": BOT.status, "detail": BOT.detail, "candidate": db.kv_get("qq_candidate") if not settings.S["qqUser"] else None},
            "models": {"server": ms["server"], "kev": ms["kev_ready"], "yielding": ms["yielding"], "yield_reason": ms["yield_reason"],
                       "embed": bool((ms["health"] or {}).get("embed_loaded")), "base": bool((ms["health"] or {}).get("base_loaded"))},
            "tasks": tasks(), "events": recent(40)}
