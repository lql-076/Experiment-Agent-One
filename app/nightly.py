"""每日差事（电脑开着、你没在用时整理）：DeepSeek 当老师和整理员，花钱很少。健康类内容不交出去。

1. 给白天的判断打标签：DeepSeek 看消息和结果，说该交给谁 → 变成语义路由的新判例（你的纠正永远优先）
2. 给新类别分组、起名：嵌入模型按相似度分组，DeepSeek 起名 → 攒够数量就提议训练新小脑
3. 整理记忆：收件箱里的内容合并进记忆文件（隐私内容留在收件箱，等本地小脑整理）
4. 周日起草周报：每条结论必须带事件编号，程序核对编号存在才保留
5. 出题造样本：给攒样本中的新类别生成相似的变体，真实样本至少占 25%
6. 整理 Obsidian 笔记（app/obsidian.py）：今天聊了什么、可能矛盾的地方、可以加的链接，写进库里的「Agent 收件箱/每日」，不改你的笔记
"""
import asyncio
import json
import re
import time
from datetime import datetime

import numpy as np

from . import db, deepseek, memory, paths, privacy, router, safety, settings
from .models import M

LABELS = {"local": "本地处理（日常、提醒、笔记、闲聊、隐私）", "ds": "DeepSeek（查资料、知识、写作、代码、一般难题）",
          "cl": "更强的模型（非常复杂、需要深入讨论，用户自己带提示词去问）", "neu": "新类型的事（以上都不太合适）"}


async def teacher_labels(limit=40):
    rows = db.q("SELECT id,text,ui_to,reply FROM events WHERE private=0 AND fix IS NULL AND teacher IS NULL AND src!='cron' "
                "AND label NOT IN ('回应提醒','设提醒','记住') AND ts>? ORDER BY id DESC LIMIT ?", (time.time() - 3 * 86400, limit))
    if not rows:
        return 0
    items = [{"id": r["id"], "msg": r["text"][:200], "ai": (r["reply"] or "")[:150]} for r in rows]
    prompt = ("你在给一个私人助手的分流器当老师。每条消息应该交给谁处理？可选：" + json.dumps(LABELS, ensure_ascii=False) +
              "\n只按消息本身判断。输出 JSON：{\"labels\":[{\"id\":数字,\"label\":\"local|ds|cl|neu\"}]}\n\n" + json.dumps(items, ensure_ascii=False))
    out = await deepseek.chat([{"role": "user", "content": prompt}], json_mode=True, purpose="teacher", max_tokens=1500)
    got = json.loads(out["text"]).get("labels", [])
    n = 0
    for g in got:
        eid, lab = int(g.get("id", 0)), g.get("label")
        if lab not in LABELS:
            continue
        e = db.one("SELECT text FROM events WHERE id=? AND fix IS NULL", (eid,))
        if not e:
            continue
        db.update("events", eid, {"teacher": lab})
        vec = await M.embed([e["text"]])
        router.add_example(e["text"], lab, "teacher", False, eid, vec[0] if vec else None)
        n += 1
    return n


async def name_categories():
    rows = db.q("SELECT id,text FROM events WHERE ui_to='neu' AND private=0 AND category IS NULL ORDER BY id LIMIT 200")
    if not rows:
        return 0
    vecs = await M.embed([r["text"] for r in rows])
    if not vecs:
        return 0
    V = np.asarray(vecs, dtype=np.float32)
    groups = []
    for i in range(len(rows)):
        for g in groups:
            if float(V[i] @ V[g[0]]) >= 0.72:
                g.append(i)
                break
        else:
            groups.append([i])
    named = 0
    for g in groups:
        texts = [rows[i]["text"][:80] for i in g[:12]]
        out = await deepseek.chat([{"role": "user", "content": "下面这些消息属于同一类事情，用 2 到 4 个中文字给这一类起名，只输出名字：\n" + "\n".join(texts)}],
                                  purpose="category", max_tokens=20)
        name = re.sub(r"[^\w一-鿿]", "", out["text"])[:8] or "未命名"
        cat = db.one("SELECT * FROM categories WHERE name=?", (name,))
        if cat:
            db.update("categories", cat["id"], {"count": cat["count"] + len(g), "updated": time.time()})
        else:
            db.insert("categories", {"name": name, "count": len(g), "created": time.time(), "updated": time.time()})
        for i in g:
            db.update("events", rows[i]["id"], {"category": name})
        named += 1
    need = int(settings.S["samples"])
    for c in db.q("SELECT * FROM categories WHERE status='collecting'"):
        if c["count"] >= need:
            db.update("categories", c["id"], {"status": "ready"})
            safety.record_change("brain.create", f"「{c['name']}」样本攒够 {c['count']} 条，可以训练新小脑", "每日分组统计")
    return named


async def consolidate_memory():
    inbox = memory.root() / "记忆/收件箱.md"
    try:
        text = inbox.read_text("utf-8")
    except FileNotFoundError:
        return 0
    lines = [l for l in text.splitlines() if l.startswith("- ")]
    if not lines:
        return 0
    public = [l for l in lines if not privacy.check(l)[0]]
    private = [l for l in lines if privacy.check(l)[0]]
    if not public:
        return 0
    about = (memory.root() / "记忆/关于我.md").read_text("utf-8") if (memory.root() / "记忆/关于我.md").exists() else "# 关于我\n"
    out = await deepseek.chat([{"role": "system", "content": "你在整理一个私人助手的长期记忆。把新内容合并进已有的记忆文件：去重、合并同类、过时的改掉。保持 Markdown 列表，每条一行，简短。只输出整理后的完整文件内容。"},
                               {"role": "user", "content": f"已有文件：\n{about}\n\n新内容：\n" + "\n".join(public)}],
                              purpose="memory", max_tokens=2000)
    new_about = out["text"].strip()
    if not new_about.startswith("#"):
        new_about = "# 关于我\n\n" + new_about
    await memory.write("记忆/关于我.md", new_about + "\n", f"每日整理：合并收件箱里的 {len(public)} 条")
    keep = "# 收件箱\n\n你说\"记住……\"的内容先放这里，每日差事整理到对应的文件。（涉及隐私的留在这里，不交给云端）\n\n" + "\n".join(private) + ("\n" if private else "")
    await memory.write("记忆/收件箱.md", keep, "每日整理：清空已合并的内容")
    return len(public)


async def weekly_draft():
    since = time.time() - 7 * 86400
    evs = db.q("SELECT id,text,ui_to,fix FROM events WHERE ts>? AND private=0 ORDER BY id", (since,))
    if len(evs) < 5:
        return None
    brief = [{"id": e["id"], "to": e["ui_to"], "fix": e["fix"], "msg": e["text"][:60]} for e in evs[-120:]]
    out = await deepseek.chat([{"role": "system", "content": "根据一周的事件记录，写 3 到 6 条简短的周报要点（中文）。每条结尾必须用 [#编号] 标出依据的事件编号，没有依据的结论不准写。"},
                               {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}], purpose="weekly", max_tokens=800)
    valid = {e["id"] for e in evs}
    kept = []
    for line in out["text"].splitlines():
        ids = [int(x) for x in re.findall(r"#(\d+)", line)]
        if line.strip() and ids and all(i in valid for i in ids):
            kept.append(line.strip())
    draft = {"ts": time.time(), "lines": kept, "dropped": max(0, len([l for l in out["text"].splitlines() if l.strip()]) - len(kept))}
    db.kv_set("weekly_draft", draft)
    return draft


async def synthesize():
    if not settings.S["synthetic"]:
        return 0
    made = 0
    for c in db.q("SELECT * FROM categories WHERE status='collecting' AND count>=20"):
        real = [r["text"] for r in db.q("SELECT text FROM events WHERE category=? AND private=0 ORDER BY id DESC LIMIT 30", (c["name"],))]
        if not real:
            continue
        floor = max(0.2, float(settings.S["realFloor"]) / 100)
        target = int(len(real) * (1 - floor) / floor)
        f = paths.TRAINING / "synthetic" / f"{c['name']}.jsonl"
        have = sum(1 for _ in open(f, encoding="utf-8")) if f.exists() else 0
        n = min(40, target - have)
        if n <= 0:
            continue
        out = await deepseek.chat([{"role": "user", "content": f"下面是同一类用户消息的真实例子。仿照它们再写 {n} 条不同的、自然的中文消息（换说法、换细节，不要照抄）。输出 JSON：{{\"items\":[\"...\"]}}\n" + "\n".join(real)}],
                                  json_mode=True, purpose="synthetic", max_tokens=2000)
        items = [x for x in json.loads(out["text"]).get("items", []) if isinstance(x, str) and x not in real]
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            for x in items:
                fh.write(json.dumps({"input": x, "category": c["name"], "synthetic": True, "ts": time.time()}, ensure_ascii=False) + "\n")
        made += len(items)
    return made


async def ingest_summary(rel: str):
    """从更强的模型（网页 Claude、ChatGPT……）带回的总结：原样保存，只在本地建检索索引，当参考资料用。
    不交给 DeepSeek 加工，不进任何训练数据（Anthropic、OpenAI 等的条款都不允许用它们的输出训练模型，一律不进最省事）。"""
    n = await memory.index()
    return "已保存为参考资料（只在本地检索，不进训练集）" + (f"，新增 {n} 段索引" if n else "")


NAMES = {"teacher": ("给判断打标签", "条"), "categories": ("给新类别分组起名", "组"), "memory": ("整理记忆", "条"), "synthetic": ("出题造样本", "条"),
         "obsidian": ("整理 Obsidian 笔记", "条建议")}


async def obsidian_tidy():
    """每日整理笔记：今天聊了什么、可能矛盾的地方、可以加的链接，写进收件箱「每日」文件夹（不改你的笔记）。"""
    from . import obsidian
    if not obsidian.on():
        return 0
    r = await obsidian.tidy()
    return r.get("links", 0) + r.get("conflicts", 0) or (1 if r.get("written") else 0)


async def run_all():
    from . import feed
    res, errs = {}, {}
    t0 = time.time()
    feed.add("开始每日差事：打标签、给新类别起名、整理记忆、造样本、整理笔记（用 DeepSeek，花钱很少）", "head", job="每日差事")
    for name, fn in (("teacher", teacher_labels), ("categories", name_categories), ("memory", consolidate_memory), ("synthetic", synthesize),
                     ("obsidian", obsidian_tidy)):
        label, unit = NAMES[name]
        feed.add(label + "……", "info", job="每日差事", step=label)
        try:
            res[name] = await fn()
            feed.add(f"{label}：{res[name] or 0} {unit}" if res[name] else f"{label}：今天没有要做的", "ok", job="每日差事", step=label)
        except deepseek.NoKey:
            errs[name] = "没填 DeepSeek Key"
        except deepseek.NoBalance as e:
            errs[name] = str(e)
            feed.add(f"{label}：{e}，后面的先不做了", "err", job="每日差事", step=label)
            break
        except Exception as e:
            errs[name] = str(e)[:160]
        if name in errs:
            feed.add(f"{label}：没做成（{errs[name]}）", "err", job="每日差事", step=label)
    if datetime.now().weekday() == 6:
        try:
            res["weekly"] = bool(await weekly_draft())
        except Exception as e:
            errs["weekly"] = str(e)[:160]
    try:
        await memory.index()
    except Exception:
        pass
    db.kv_set("nightly_last", {"ts": time.time(), "res": res, "errs": errs})
    feed.add(f"每日差事做完了 · 用时 {feed.dur(time.time() - t0)}" + (f" · {len(errs)} 项有问题" if errs else ""), "head", job="每日差事")
    return {"res": res, "errs": errs}


async def loop():
    """不定时间：电脑开着、你 20 分钟没找它、离上次超过 20 小时就跑一次；隔了 36 小时还没机会，就不等空闲直接跑。
    （你的作息不固定，夜里电脑也常常关着，所以不按钟点。这些活只用 DeepSeek 和很少的显卡，不影响你用电脑。）"""
    await asyncio.sleep(120)
    while True:
        try:
            if settings.S["nightly"]:
                last = (db.kv_get("nightly_last", {}) or {}).get("ts", 0)
                since = time.time() - last
                busy = db.one("SELECT MAX(ts) t FROM events WHERE src IN ('qq','ui')")["t"] or 0
                idle = time.time() - busy >= 20 * 60
                if (since >= 20 * 3600 and idle) or since >= 36 * 3600:
                    await run_all()
        except Exception as e:
            print("每日差事出错：", e)
        await asyncio.sleep(120)
