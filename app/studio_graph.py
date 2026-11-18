r"""视频工坊 · 七个独立模块 + Markdown 清单（v4.0.1 / R12）。

没有端口、没有连线、没有 DAG、没有缺上游。画布固定 7 个模块，每个都能单独点运行：
  script / image / voice-white / voice-zisu / bgm / compose / publish
模块之间靠 工作区\视频工坊\<项目>\Lists\ 下的 Markdown 清单协作。
"""
import hashlib
import json
import re
from pathlib import Path

MODULE_DEFS = [
    ("script", "script", "剧本与策划", 40, 40, 350, 470),
    ("image", "image", "生图测试台（独立）", 430, 40, 380, 620),
    ("voice-white", "voice", "角色配音 · 白页", 850, 40, 400, 500),
    ("voice-zisu", "voice", "角色配音 · 紫苏", 850, 570, 400, 500),
    ("bgm", "bgm", "背景配乐（Stable Audio 3）", 1290, 40, 360, 360),
    ("compose", "compose", "视频制作总成（Claude Code 驱动）", 40, 1120, 1610, 720),
    ("publish", "publish", "成片预览与抖音发布", 1290, 430, 360, 600),
]
FIXED_IDS = [x[0] for x in MODULE_DEFS]
TYPE_LABEL = {"script": "剧本", "image": "生图测试", "voice": "配音", "bgm": "配乐", "compose": "视频总成", "publish": "发布"}
LISTS = ("配音清单_白页.md", "配音清单_紫苏.md", "配乐清单.md", "视频渲染清单.md", "生图清单.md")
LIST_VOICE = {"voice-white": "配音清单_白页.md", "voice-zisu": "配音清单_紫苏.md"}
ROLES = ("白页", "紫苏", "旁白")
RENDER_KIND = {"网页": "web", "网页动效": "web", "web": "web", "PPT": "ppt", "PPT 卡片": "ppt", "ppt": "ppt",
               "卡片": "ppt", "静态": "static", "静态画面": "static", "static": "static"}
MODEL_VERSION = "studio-modules-4.0.0"


class GraphError(ValueError):
    pass


def _module(mid, typ, title, x, y, w, h, params):
    return {"id": mid, "type": typ, "title": title, "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            "params": params, "outputs": [], "status": "idle", "error": "", "cache_key": "", "cache_hit": False,
            "started": 0, "finished": 0}


def default_params(mid, project=None):
    st = (project or {}).get("settings") or {}
    ratio = (project or {}).get("ratio") or "9:16"
    if mid == "script":
        return {"topic": "三个被低估的 AI 用法", "source_text": "", "title": (project or {}).get("title") or "测试视频",
                "desc": "这一期讲讲普通人马上能用的 AI 用法。", "tags": ["AI", "效率工具"], "script_doc": {}}
    if mid == "image":
        return {"prompt": "第 1 张测试画面：简洁、清晰、适合竖屏短视频，主体居中偏上。",
                "model": st.get("img_model") or "", "ratio": ratio, "resolution": st.get("img_resolution") or "2k",
                "quality": st.get("img_quality") or "high", "complexity": st.get("img_complexity") or "medium",
                "transparent": False, "output": "normal", "format": "png", "n": 1, "custom_w": 0, "custom_h": 0,
                "gif_frames": 8, "gif_delay_ms": 150, "refs": [], "selected": 0, "items": []}
    if mid == "voice-white":
        return {"role": "白页", "speaker": "local:preset:Serena", "engine": "auto", "tone": "冷静吐槽",
                "lines": [{"id": "l1", "line_index": 1, "text": "这是白页的第 1 句测试台词，可以直接改成你要念的内容。", "tone": ""}]}
    if mid == "voice-zisu":
        return {"role": "紫苏", "speaker": "local:preset:Dylan", "engine": "auto", "tone": "轻松调侃",
                "lines": [{"id": "l1", "line_index": 2, "text": "这是紫苏的第 1 句测试台词，可以直接改成你要念的内容。", "tone": ""}]}
    if mid == "bgm":
        return {"prompt": "upbeat electronic, no vocals, suitable under narration", "seconds": 75, "steps": 8, "seed": 20261118}
    if mid == "compose":
        return {"subtitle": True, "ratio": ratio, "bgm_volume": 0.18, "duck_depth": 0.16, "fade": 2.0, "kenburns": True,
                "cc_drive": True, "fps": 24, "web_bg": "dark", "web_sub_pos": "bottom", "web_sub_size": 0,
                "web_sub_color": "", "web_gif_scale": 1, "web_motion": 1, "ppt_file": "",
                "shots": [{"id": "s1", "line_index": 1, "render": "web", "text": "这是白页的第 1 句测试台词，可以直接改成你要念的内容。",
                           "visual": "深色科技感排版，主标题和动态字幕", "seconds": 6, "transition": "淡入"},
                          {"id": "s2", "line_index": 2, "render": "ppt", "text": "这是紫苏的第 1 句测试台词，可以直接改成你要念的内容。",
                           "visual": "对比卡片，两个要点", "seconds": 6, "transition": "推近"}]}
    if mid == "publish":
        return {"title": (project or {}).get("title") or "测试视频", "desc": (project or {}).get("desc") or "",
                "tags": (project or {}).get("tags") or ["AI", "搞笑"], "schedule": "", "declaration": "内容由AI生成",
                "cover": "auto", "mode": "single", "collection": ""}
    raise GraphError("不认识的模块：" + str(mid))


def default_modules(project=None):
    return [_module(mid, typ, title, x, y, w, h, default_params(mid, project)) for mid, typ, title, x, y, w, h in MODULE_DEFS]


def valid_modules(p) -> bool:
    mods = p.get("modules")
    if not isinstance(mods, list):
        return False
    ids = sorted(m.get("id") for m in mods if isinstance(m, dict))
    return ids == sorted(FIXED_IDS)


def module_of(p, mid):
    for m in p.get("modules") or []:
        if m.get("id") == mid:
            return m
    raise GraphError("没有这个模块：" + str(mid))


def ensure_modules(p) -> bool:
    if valid_modules(p):
        return False
    p["modules"] = migrate_modules(p, p.get("graph") or {}, p.get("shots") or [])
    p["modules_version"] = 4
    for k in ("graph", "shots", "node_layout"):
        p.pop(k, None)
    ensure_lists(p, force=True)
    return True


def _pack(rel, kind, project_dir, extra=None):
    q = Path(project_dir) / str(rel or "") if rel else None
    if not q or not q.is_file():
        return None
    from . import studio_cache as cache
    out = {"key": str(rel), "rel": str(rel), "kind": kind, "sha256": cache.sha_file(q), "size": q.stat().st_size}
    if extra:
        out.update({k: v for k, v in extra.items() if v not in (None, "")})
    return out


def migrate_modules(p, old_graph, old_shots) -> list:
    mods = default_modules(p)
    byid = {m["id"]: m for m in mods}
    nodes = old_graph.get("nodes") or []
    sn = next((n for n in nodes if n.get("type") == "script"), None)
    if sn:
        prm = sn.get("params") or {}
        for k in ("topic", "source_text", "title", "desc", "tags", "script_doc"):
            if prm.get(k) is not None:
                byid["script"]["params"][k] = prm[k]
    inode = next((n for n in nodes if n.get("type") == "image"), None)
    if inode:
        prm = inode.get("params") or {}
        for k in ("prompt", "model", "ratio", "resolution", "quality", "complexity", "transparent", "output", "format",
                  "n", "custom_w", "custom_h", "gif_frames", "gif_delay_ms", "refs", "selected"):
            if k in prm:
                byid["image"]["params"][k] = prm[k]
        byid["image"]["outputs"] = [o for o in (inode.get("outputs") or []) if o.get("kind") == "image"]
        byid["image"]["status"] = inode.get("status") or ("ok" if byid["image"]["outputs"] else "idle")
        byid["image"]["cache_hit"] = bool(inode.get("cache_hit"))
    elif old_shots and old_shots[0].get("image_prompt"):
        byid["image"]["params"]["prompt"] = old_shots[0]["image_prompt"]
        o = _pack(old_shots[0].get("image"), "image", p["dir"])
        if o:
            byid["image"]["outputs"].append(o)
    rows = []
    for i, n in enumerate(nodes):
        if n.get("type") != "voice":
            continue
        prm = n.get("params") or {}
        order = int(prm.get("order") or i + 1)
        lines = [x for x in prm.get("lines") or [] if str(x.get("text") or "").strip()]
        for j, ln in enumerate(lines):
            rows.append({"order": order, "sub": j, "role": prm.get("role") or "旁白",
                         "speaker": ln.get("speaker") or prm.get("speaker") or "", "engine": prm.get("engine") or "auto",
                         "tone": ln.get("tone") or prm.get("tone") or "", "text": ln.get("text") or "", "output": ""})
        for o in n.get("outputs") or []:
            if o.get("kind") == "audio" and o.get("line"):
                lid = int(re.sub(r"\D", "", str(o.get("line"))) or 0)
                for r in rows:
                    if r["order"] == order and r["sub"] + 1 == lid and not r["output"]:
                        r["output"] = o.get("rel") or ""
    if not rows and old_shots:
        for i, s in enumerate(old_shots, 1):
            rows.append({"order": i, "sub": 0, "role": s.get("role") or "旁白", "speaker": s.get("speaker") or "",
                         "engine": s.get("tts_engine") or "auto", "tone": s.get("tone") or "", "text": s.get("text") or "",
                         "output": s.get("tts") or ""})
    for idx, r in enumerate(sorted(rows, key=lambda x: (x["order"], x["sub"])), 1):
        mid = "voice-white" if r["role"] in ("白页", "旁白") else "voice-zisu"
        m = byid[mid]
        m["params"]["lines"].append({"id": f"l{len(m['params']['lines']) + 1}", "line_index": idx, "text": r["text"],
                                     "tone": r["tone"], "speaker": r["speaker"], "engine": r["engine"], "output": r["output"]})
        o = _pack(r["output"], "audio", p["dir"], {"line": str(idx)})
        if o:
            m["outputs"].append(o)
    for mid in ("voice-white", "voice-zisu"):
        m = byid[mid]
        if len(m["params"]["lines"]) > 1:
            m["params"]["lines"] = [x for x in m["params"]["lines"] if str(x.get("text") or "").strip() and not str(x.get("id", "")).startswith("l1")] or m["params"]["lines"]
        m["status"] = "ok" if m["outputs"] else "idle"
    bn = next((n for n in nodes if n.get("type") == "bgm"), None)
    if bn:
        for k in ("prompt", "seconds", "steps", "seed"):
            if k in (bn.get("params") or {}):
                byid["bgm"]["params"][k] = bn["params"][k]
        byid["bgm"]["outputs"] = [o for o in (bn.get("outputs") or []) if o.get("kind") == "audio"]
        byid["bgm"]["status"] = bn.get("status") or ("ok" if byid["bgm"]["outputs"] else "idle")
        byid["bgm"]["cache_hit"] = bool(bn.get("cache_hit"))
    elif (p.get("files") or {}).get("bgm"):
        o = _pack(p["files"]["bgm"], "audio", p["dir"])
        if o:
            byid["bgm"]["outputs"].append(o)
            byid["bgm"]["status"] = "ok"
    mux = next((n for n in nodes if n.get("type") == "mux"), None)
    if mux:
        for k in ("subtitle", "ratio", "bgm_volume", "duck_depth", "fade", "kenburns"):
            if k in (mux.get("params") or {}):
                byid["compose"]["params"][k] = mux["params"][k]
        byid["compose"]["outputs"] = [o for o in (mux.get("outputs") or []) if o.get("kind") in ("video", "image")]
        byid["compose"]["status"] = mux.get("status") or ("ok" if byid["compose"]["outputs"] else "idle")
        byid["compose"]["cache_hit"] = bool(mux.get("cache_hit"))
    elif (p.get("files") or {}).get("video"):
        o = _pack(p["files"]["video"], "video", p["dir"])
        if o:
            byid["compose"]["outputs"].append(o)
            byid["compose"]["status"] = "ok"
    st = p.get("settings") or {}
    byid["compose"]["params"].update({"web_bg": st.get("web_bg") or "dark", "web_sub_pos": st.get("web_sub_pos") or "bottom",
                                      "web_sub_size": st.get("web_sub_size") or 0, "web_sub_color": st.get("web_sub_color") or "",
                                      "web_gif_scale": st.get("web_gif_scale") or 1,
                                      "web_motion": st.get("web_motion") if st.get("web_motion") is not None else 1,
                                      "ppt_file": st.get("ppt_file") or ""})
    shots = []
    for w in nodes:
        if w.get("type") in ("web", "ppt"):
            wp = w.get("params") or {}
            shots.append({"id": w["id"], "line_index": int(wp.get("order") or len(shots) + 1),
                          "render": "web" if w["type"] == "web" else "ppt", "text": wp.get("text") or "",
                          "visual": wp.get("text") or ("、".join(wp.get("points") or [])),
                          "seconds": float(wp.get("duration") or 5), "transition": "淡入" if w["type"] == "web" else "推近"})
    if not shots and old_shots:
        for i, s in enumerate(old_shots, 1):
            shots.append({"id": f"s{i}", "line_index": i, "render": s.get("render") or "static", "text": s.get("text") or "",
                          "visual": s.get("image_prompt") or s.get("text") or "", "seconds": float(s.get("duration") or s.get("seconds_hint") or 5),
                          "transition": "淡入"})
    if shots:
        byid["compose"]["params"]["shots"] = sorted(shots, key=lambda x: x["line_index"])
    pub = next((n for n in nodes if n.get("type") == "publish"), None)
    if pub:
        for k in ("title", "desc", "tags", "schedule", "declaration", "cover", "mode", "collection"):
            if k in (pub.get("params") or {}):
                byid["publish"]["params"][k] = pub["params"][k]
    else:
        byid["publish"]["params"].update({"title": p.get("title") or "测试视频", "desc": p.get("desc") or "",
                                          "tags": p.get("tags") or ["AI", "搞笑"]})
    return mods


# ---------------- Markdown 清单 ----------------
def lists_dir(p) -> Path:
    d = Path(p["dir"]) / "Lists"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_path(p, name) -> Path:
    if name not in LISTS:
        raise GraphError("没有这份清单：" + str(name))
    return lists_dir(p) / name


def read_list(p, name) -> str:
    q = list_path(p, name)
    return q.read_text("utf-8") if q.is_file() else ""


def write_list(p, name, text):
    list_path(p, name).write_text(str(text or "").replace("\r\n", "\n"), "utf-8")


def all_lists(p) -> dict:
    return {name: read_list(p, name) for name in LISTS}


def _default_doc(project=None):
    p = project or {}
    return {"title": p.get("title") or "测试视频", "desc": p.get("desc") or "这一期讲讲普通人马上能用的 AI 用法。",
            "tags": p.get("tags") or ["AI", "效率工具"],
            "bgm": {"segments": [{"id": "bgm-1", "prompt": "upbeat electronic, no vocals, suitable under narration",
                                  "seconds": 75, "steps": 8, "seed": 20261118}]},
            "shots": [
                {"id": "s1", "seconds": 6, "render": "web", "image": {"prompt": "深色科技感排版，主标题和动态字幕"},
                 "voice": {"role": "白页", "speaker": "local:preset:Serena", "tone": "冷静吐槽", "text": "这是白页的第 1 句测试台词，可以直接改成你要念的内容。"}},
                {"id": "s2", "seconds": 6, "render": "ppt", "image": {"prompt": "对比卡片，两个要点"},
                 "voice": {"role": "紫苏", "speaker": "local:preset:Dylan", "tone": "轻松调侃", "text": "这是紫苏的第 1 句测试台词，可以直接改成你要念的内容。"}}]}


def doc_from_modules(p):
    doc = _default_doc(p)
    s = module_of(p, "script")
    prm = s.get("params") or {}
    doc.update({"title": prm.get("title") or doc["title"], "desc": prm.get("desc") or doc["desc"], "tags": prm.get("tags") or doc["tags"]})
    if isinstance(prm.get("script_doc"), dict) and prm["script_doc"].get("shots"):
        d = prm["script_doc"]
        doc.update({"title": d.get("title") or doc["title"], "desc": d.get("desc") or doc["desc"], "tags": d.get("tags") or doc["tags"]})
        doc["bgm"] = d.get("bgm") or doc["bgm"]
        doc["shots"] = d.get("shots") or doc["shots"]
        return doc
    lines = []
    for mid in ("voice-white", "voice-zisu"):
        m = module_of(p, mid)
        for ln in (m.get("params") or {}).get("lines") or []:
            if not str(ln.get("text") or "").strip():
                continue
            lines.append({"idx": int(ln.get("line_index") or 0), "role": (m.get("params") or {}).get("role") or ("白页" if mid == "voice-white" else "紫苏"),
                          "speaker": ln.get("speaker") or (m.get("params") or {}).get("speaker") or "",
                          "tone": ln.get("tone") or (m.get("params") or {}).get("tone") or "", "text": ln.get("text") or ""})
    lines.sort(key=lambda x: x["idx"] or 9999)
    cshots = (module_of(p, "compose").get("params") or {}).get("shots") or []
    by_idx = {int(x.get("line_index") or 0): x for x in cshots if isinstance(x, dict)}
    shots = []
    for i, ln in enumerate(lines or [{"idx": 1, "role": "白页", "speaker": "", "tone": "", "text": ""},
                                     {"idx": 2, "role": "紫苏", "speaker": "", "tone": "", "text": ""}], 1):
        cs = by_idx.get(ln["idx"]) or (cshots[i - 1] if i - 1 < len(cshots) else {})
        shots.append({"id": f"s{i}", "seconds": float(cs.get("seconds") or 6),
                      "render": cs.get("render") or ("web" if i % 3 == 1 else "ppt" if i % 3 == 0 else "static"),
                      "image": {"prompt": cs.get("visual") or ln["text"] or "简洁排版画面"},
                      "voice": {"role": ln["role"] if ln["role"] in ROLES else "白页", "speaker": ln["speaker"],
                                "tone": ln["tone"] or "冷静吐槽", "text": ln["text"]}})
    doc["shots"] = shots
    b = module_of(p, "bgm").get("params") or {}
    doc["bgm"] = {"segments": [{"id": "bgm-1", "prompt": b.get("prompt") or "upbeat electronic, no vocals",
                                "seconds": b.get("seconds") or 75, "steps": b.get("steps") or 8, "seed": b.get("seed") or 20261118}]}
    return doc


def lists_from_doc(doc):
    title = doc.get("title") or "测试视频"
    rows = {"白页": [], "紫苏": []}
    for i, s in enumerate(doc.get("shots") or [], 1):
        v = s.get("voice") or {}
        role = v.get("role") or ("白页" if i % 2 else "紫苏")
        rows["白页" if role in ("白页", "旁白") else "紫苏"].append(
            {"idx": i, "text": v.get("text") or s.get("text") or "", "tone": v.get("tone") or "", "speaker": v.get("speaker") or ""})
    def voice_md(name, rs, tone):
        out = [f"# 配音清单 · {name}", ""]
        if rs:
            out += [f"- 音色：{rs[0].get('speaker') or ''}", f"- 默认语气：{tone}", "- 引擎：auto", ""]
        for r in rs:
            out += [f"## {r['idx']:02d}", f"台词：{r['text']}", f"语气：{r['tone'] or tone}", ""]
        return "\n".join(out)
    lines = ["# 视频渲染清单", "", f"- 标题：{title}", f"- 画幅：{doc.get('ratio') or '9:16'}",
             f"- 总时长：{sum(float(s.get('seconds') or 5) for s in doc.get('shots') or []):.0f}", ""]
    for i, s in enumerate(doc.get("shots") or [], 1):
        kind = {"web": "网页动效", "ppt": "PPT 卡片", "static": "静态画面"}.get(s.get("render") or "static", "静态画面")
        text = (s.get("voice") or {}).get("text") or s.get("text") or ""
        visual = (s.get("image") or {}).get("prompt") or text
        lines += [f"## {i:02d}", "时间：按配音时间轴自动对齐", f"时长：{float(s.get('seconds') or 6):.1f}",
                  f"方式：{kind}", f"画面：{visual}", f"字幕：{text}",
                  f"转场：{'推近' if kind == 'PPT 卡片' else '淡入'}", ""]
    b = ((doc.get("bgm") or {}).get("segments") or [{}])[0]
    bgm_md = "\n".join(["# 配乐清单", "", f"- 时长：{b.get('seconds') or 75}", f"- 步数：{b.get('steps') or 8}",
                        f"- 种子：{b.get('seed') or 20261118}", "", "## 01",
                        f"描述：{b.get('prompt') or 'upbeat electronic, no vocals'}", f"时长：{b.get('seconds') or 75}", ""])
    img = ["# 生图清单（可选，主流程不依赖）", "", "> 只给「生图测试台」按需手动测图；视频制作总成用网页动效和 PPT，不用这里的图。", ""]
    for i, s in enumerate(doc.get("shots") or [], 1):
        im = s.get("image") or {}
        img += [f"## {i:02d}", f"提示词：{im.get('prompt') or (s.get('voice') or {}).get('text') or ''}",
                f"比例：{im.get('ratio') or doc.get('ratio') or '9:16'}", f"透明：{'开' if im.get('transparent') else '否'}", ""]
    return {LISTS[0]: voice_md("白页", rows["白页"], "冷静吐槽"), LISTS[1]: voice_md("紫苏", rows["紫苏"], "轻松调侃"),
            LISTS[2]: bgm_md, LISTS[3]: "\n".join(lines), LISTS[4]: "\n".join(img)}


def write_lists(p, doc=None):
    doc = doc or doc_from_modules(p)
    data = lists_from_doc(doc)
    for name, text in data.items():
        write_list(p, name, text)
    apply_lists(p)
    return data


def ensure_lists(p, force=False):
    d = lists_dir(p)
    missing = [x for x in LISTS if force or not (d / x).is_file()]
    if not missing:
        return False
    data = lists_from_doc(doc_from_modules(p))
    for name in missing:
        write_list(p, name, data[name])
    apply_lists(p)
    return True


def _field(text, *names, default=""):
    for n in names:
        m = re.search(r"(?m)^\s*(?:[-*]\s*)?" + re.escape(n) + r"\s*[:：]\s*(.*)$", text)
        if m:
            return m.group(1).strip()
    return default


def _blocks(text):
    out, cur = [], None
    for line in str(text or "").replace("\r\n", "\n").split("\n"):
        if line.startswith("## "):
            if cur is not None:
                out.append(cur)
            cur = {"head": line[3:].strip(), "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
    if cur is not None:
        out.append(cur)
    return out


def parse_voice_list(text, role):
    speaker = _field(text, "音色", "speaker")
    tone = _field(text, "默认语气", "语气", "tone")
    engine = _field(text, "引擎", "engine", default="auto")
    lines = []
    for b in _blocks(text):
        body = "\n".join(b["lines"])
        tx = _field(body, "台词", "口播", "text", "文案")
        if not tx:
            continue
        try:
            idx = int(re.sub(r"\D", "", b["head"]) or len(lines) + 1)
        except ValueError:
            idx = len(lines) + 1
        lines.append({"id": f"l{len(lines) + 1}", "line_index": idx, "text": tx[:500],
                      "tone": _field(body, "语气", "tone", default=tone), "speaker": _field(body, "音色", "speaker", default=speaker),
                      "engine": _field(body, "引擎", "engine", default=engine)})
    return {"role": role, "speaker": speaker, "tone": tone, "engine": engine, "lines": lines}


def parse_bgm_list(text):
    b = _blocks(text)
    body = "\n".join(b[0]["lines"]) if b else text
    try:
        sec = int(float(_field(text, "时长", "seconds", default="75") or 75))
    except ValueError:
        sec = 75
    try:
        steps = int(float(_field(text, "步数", "steps", default="8") or 8))
    except ValueError:
        steps = 8
    try:
        seed = int(float(_field(text, "种子", "seed", default="20261118") or 20261118))
    except ValueError:
        seed = 20261118
    return {"prompt": _field(body, "描述", "提示词", "prompt", default="upbeat electronic, no vocals")[:1000],
            "seconds": max(10, min(380, sec)), "steps": max(1, min(32, steps)), "seed": seed}


def parse_render_list(text):
    shots = []
    for b in _blocks(text):
        body = "\n".join(b["lines"])
        try:
            idx = int(re.sub(r"\D", "", b["head"]) or len(shots) + 1)
        except ValueError:
            idx = len(shots) + 1
        kind = _field(body, "方式", "轨道", "render", default="静态画面")
        render = RENDER_KIND.get(kind, RENDER_KIND.get(kind.lower(), "static"))
        tx = _field(body, "字幕", "台词", "text", default="")
        visual = _field(body, "画面", "排版要点", "visual", default=tx or "简洁排版画面")
        try:
            sec = max(1.0, min(120.0, float(_field(body, "时长", "seconds", default="6") or 6)))
        except ValueError:
            sec = 6.0
        shots.append({"id": f"s{idx:02d}", "line_index": idx, "render": render, "text": tx[:500], "visual": visual[:1000],
                      "seconds": sec, "transition": _field(body, "转场", "transition", default="淡入")[:20]})
    return shots


def parse_image_list(text):
    items = []
    for b in _blocks(text):
        body = "\n".join(b["lines"])
        prompt = _field(body, "提示词", "画面", "prompt")
        if prompt:
            items.append({"id": f"i{len(items) + 1}", "prompt": prompt[:1000], "ratio": _field(body, "比例", "ratio", default="9:16"),
                          "transparent": _field(body, "透明", "transparent", default="否") in ("开", "是", "true", "1")})
    return items


def apply_lists(p):
    for mid, name in LIST_VOICE.items():
        text = read_list(p, name)
        if not text.strip():
            continue
        parsed = parse_voice_list(text, "白页" if mid == "voice-white" else "紫苏")
        m = module_of(p, mid)
        if parsed["lines"]:
            m["params"].update({"role": parsed["role"], "speaker": parsed["speaker"] or m["params"].get("speaker"),
                                "tone": parsed["tone"] or m["params"].get("tone"), "engine": parsed["engine"] or "auto",
                                "lines": parsed["lines"]})
        else:
            m["params"].update({"speaker": parsed["speaker"] or m["params"].get("speaker"),
                                "tone": parsed["tone"] or m["params"].get("tone"), "engine": parsed["engine"] or "auto"})
    text = read_list(p, LISTS[2])
    if text.strip():
        module_of(p, "bgm")["params"].update(parse_bgm_list(text))
    text = read_list(p, LISTS[3])
    if text.strip():
        shots = parse_render_list(text)
        if shots:
            module_of(p, "compose")["params"]["shots"] = shots
    text = read_list(p, LISTS[4])
    if text.strip():
        items = parse_image_list(text)
        if items:
            module_of(p, "image")["params"]["items"] = items
    invalidate_dependents(p, "lists")


def invalidate_dependents(p, mid):
    targets = []
    if mid in ("voice-white", "voice-zisu", "bgm", "lists", "script", "image"):
        targets.append("compose")
    if mid == "compose":
        targets.append("publish")
    for t in targets:
        m = module_of(p, t)
        m["cache_key"] = ""
        m["cache_hit"] = False
        if m.get("status") in ("ok", "warn"):
            m["status"] = "stale"


def cache_key(p, m):
    from . import studio_cache as cache
    deps = {}
    if m["id"] == "compose":
        for mid in ("voice-white", "voice-zisu", "bgm"):
            deps[mid] = [[o.get("kind"), o.get("sha256") or ""] for o in (module_of(p, mid).get("outputs") or [])]
        deps["render_list"] = hashlib.sha256(read_list(p, LISTS[3]).encode("utf-8")).hexdigest() if read_list(p, LISTS[3]) else ""
    if m["id"] == "publish":
        deps["video"] = (module_of(p, "compose").get("outputs") or [{}])[0].get("sha256") or ""
    params = {k: v for k, v in (m.get("params") or {}).items() if k not in ("selected",)}
    return cache.fingerprint("module", {"id": m["id"], "type": m["type"], "params": params, "deps": deps, "v": MODEL_VERSION})


# ---------------- 剧本 schema（沿用 v3.9，用于模块 1 导入/DeepSeek 拆解） ----------------
SHOT_RENDER = ("web", "ppt", "static")


def _need(cond, line, msg):
    if not cond:
        raise GraphError(f"第 {line} 行：{msg}" if line else msg)


def parse_script_doc(text):
    raw = str(text or "").strip()
    if not raw:
        raise GraphError("剧本是空的")
    m = re.search(r"```(?:json|markdown|md)?\s*(\{.*\})\s*```", raw, re.S | re.I)
    cand = m.group(1) if m else raw
    if cand.lstrip().startswith("{"):
        try:
            j = json.loads(cand)
        except json.JSONDecodeError as e:
            raise GraphError(f"JSON 第 {e.lineno} 行第 {e.colno} 列：{e.msg}") from None
        if not isinstance(j, dict):
            raise GraphError("剧本最外层要是一个对象 {}")
        return _norm_doc(j)
    return _parse_md(raw)


def _parse_md(raw):
    lines = raw.replace("\r\n", "\n").split("\n")
    doc = {"title": "导入的剧本", "desc": "", "tags": [], "bgm": {"segments": []}, "shots": []}
    shot = bgm = None
    mode = "meta"
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            continue
        if s.startswith("## "):
            head = s[3:].strip()
            low = head.lower()
            if low.startswith("分镜") or low.startswith("shot"):
                sid = re.split(r"[\s:：]+", head, maxsplit=1)[1].strip() if re.search(r"[\s:：]", head) else ""
                shot = {"id": sid or f"s{len(doc['shots']) + 1}", "line": i, "image": {}, "voice": {}, "render": "static"}
                doc["shots"].append(shot); mode = "shot"; bgm = None
            elif low.startswith("配乐") or low.startswith("bgm"):
                bid = re.split(r"[\s:：]+", head, maxsplit=1)[1].strip() if re.search(r"[\s:：]", head) else ""
                bgm = {"id": bid or f"bgm-{len(doc['bgm']['segments']) + 1}", "line": i}
                doc["bgm"]["segments"].append(bgm); mode = "bgm"; shot = None
            else:
                _need(False, i, f"不认识的 ## 小节「{head}」")
            continue
        if s.startswith("# ") and not s.startswith("## "):
            doc["title"] = s[2:].strip()[:30] or doc["title"]; continue
        if "：" in s or ":" in s:
            k, v = re.split(r"[:：]", s, maxsplit=1)
            k, v = k.strip().replace("**", ""), v.strip().replace("**", "")
            if mode == "shot" and shot is not None:
                if k in ("画面", "画面提示词", "prompt", "image_prompt"):
                    shot["image"]["prompt"] = v
                elif k in ("角色", "role"):
                    shot["voice"]["role"] = v
                elif k in ("音色", "speaker", "voice"):
                    shot["voice"]["speaker"] = v
                elif k in ("语气", "tone"):
                    shot["voice"]["tone"] = v
                elif k in ("台词", "口播", "text", "文案"):
                    shot["voice"]["text"] = v
                elif k in ("画面轨道", "轨道", "render"):
                    r = RENDER_KIND.get(v, RENDER_KIND.get(v.lower(), v.lower()))
                    _need(r in SHOT_RENDER, i, f"画面轨道只能是 网页 / PPT / 静态，写的是「{v}」")
                    shot["render"] = r
                elif k in ("时长", "seconds", "seconds_hint"):
                    try:
                        shot["seconds"] = float(v)
                    except ValueError:
                        _need(False, i, f"时长要写数字，这里写的是「{v}」")
                elif k in ("生图模型", "model"):
                    shot["image"]["model"] = v
                elif k in ("比例", "ratio"):
                    shot["image"]["ratio"] = v
                elif k in ("分辨率", "resolution"):
                    shot["image"]["resolution"] = v
                elif k in ("画质", "quality"):
                    shot["image"]["quality"] = v
                elif k in ("复杂度", "complexity"):
                    shot["image"]["complexity"] = v
                elif k in ("透明", "透明背景", "transparent"):
                    shot["image"]["transparent"] = v in ("开", "是", "1", "true", "要")
                elif k in ("张数", "n"):
                    try:
                        shot["image"]["n"] = int(v)
                    except ValueError:
                        _need(False, i, f"张数要写整数，这里写的是「{v}」")
                else:
                    _need(False, i, f"分镜里不认识的字段「{k}」")
            elif mode == "bgm" and bgm is not None:
                if k in ("描述", "提示词", "prompt"):
                    bgm["prompt"] = v
                elif k in ("时长", "seconds"):
                    try:
                        bgm["seconds"] = float(v)
                    except ValueError:
                        _need(False, i, f"配乐时长要写数字，这里写的是「{v}」")
                elif k in ("步数", "steps"):
                    try:
                        bgm["steps"] = int(v)
                    except ValueError:
                        _need(False, i, f"步数要写整数，这里写的是「{v}」")
                elif k in ("种子", "seed"):
                    try:
                        bgm["seed"] = int(v)
                    except ValueError:
                        _need(False, i, f"种子要写整数，这里写的是「{v}」")
                else:
                    _need(False, i, f"配乐里不认识的字段「{k}」")
            else:
                if k in ("简介", "描述", "desc"):
                    doc["desc"] = v
                elif k in ("话题", "标签", "tags"):
                    doc["tags"] = [re.sub(r"^[#＃]+", "", x)[:20] for x in re.split(r"[\s,，、#＃]+", v) if x][:10]
                else:
                    _need(False, i, f"剧本开头不认识的字段「{k}」")
            continue
        _need(False, i, "这一行既不是 # 标题 / ## 分镜，也不是「字段：值」")
    if not doc["shots"]:
        raise GraphError("剧本里没有「## 分镜 …」小节")
    return _norm_doc(doc)


def _norm_doc(j):
    out = {"version": 1, "title": str(j.get("title") or "导入的剧本")[:30], "desc": str(j.get("desc") or "")[:300],
           "tags": [], "bgm": {"segments": []}, "shots": []}
    tags = j.get("tags") or []
    if isinstance(tags, str):
        tags = re.split(r"[\s,，、#＃]+", tags)
    out["tags"] = [re.sub(r"^[#＃]+", "", str(x).strip())[:20] for x in tags if str(x).strip()][:10]
    bg = j.get("bgm")
    segs = []
    if isinstance(bg, dict):
        segs = bg.get("segments") or ([bg] if any(bg.get(k) for k in ("prompt", "描述", "提示词")) else [])
    elif isinstance(bg, list):
        segs = bg
    for i, b in enumerate(segs or []):
        _need(isinstance(b, dict), None, f"bgm.segments 第 {i + 1} 段要是一个对象")
        prompt = str(b.get("prompt") or b.get("描述") or "").strip()
        _need(bool(prompt), None, f"bgm.segments 第 {i + 1} 段缺 prompt（英文描述）")
        try:
            sec, steps, seed = float(b.get("seconds") or 0), int(b.get("steps") or 8), int(b.get("seed") or 20261118)
        except (TypeError, ValueError):
            raise GraphError(f"bgm.segments 第 {i + 1} 段的 seconds/steps/seed 要写数字") from None
        out["bgm"]["segments"].append({"id": str(b.get("id") or f"bgm-{i + 1}")[:40], "prompt": prompt[:1000],
                                       "seconds": max(0, sec), "steps": max(1, min(32, steps)), "seed": seed})
    shots = j.get("shots")
    _need(isinstance(shots, list) and shots, None, "剧本里没有 shots（生图任务列表）")
    seen = set()
    for i, s in enumerate(shots):
        _need(isinstance(s, dict), None, f"shots 第 {i + 1} 项要是一个对象")
        sid = str(s.get("id") or "").strip()[:40]
        _need(bool(sid), None, f"shots 第 {i + 1} 项缺 id（稳定的任务 key）")
        _need(sid not in seen, None, f"shots 里有重复的 id「{sid}」")
        seen.add(sid)
        im = s.get("image") if isinstance(s.get("image"), dict) else {}
        vo = s.get("voice") if isinstance(s.get("voice"), dict) else {}
        prompt = str(im.get("prompt") or s.get("image_prompt") or "").strip()
        text = str(vo.get("text") or s.get("text") or "").strip()
        _need(bool(prompt), None, f"分镜「{sid}」缺画面提示词（image.prompt）")
        _need(bool(text), None, f"分镜「{sid}」缺台词（voice.text）")
        role = str(vo.get("role") or s.get("role") or ROLES[i % 2]).strip()
        _need(role in ROLES, None, f"分镜「{sid}」的角色只能是白页 / 紫苏 / 旁白，写的是「{role}」")
        tone = str(vo.get("tone") or s.get("tone") or "").strip()
        _need(bool(tone), None, f"分镜「{sid}」缺语气（voice.tone）")
        render = str(s.get("render") or "static").lower()
        _need(render in SHOT_RENDER, None, f"分镜「{sid}」的画面轨道只能是 web / ppt / static，写的是「{render}」")
        try:
            seconds = max(1.0, min(120.0, float(s.get("seconds") or len(text) / 4.5)))
            n_img = max(1, min(4, int(im.get("n") or 1)))
        except (TypeError, ValueError):
            raise GraphError(f"分镜「{sid}」的 seconds / n 要写数字") from None
        out["shots"].append({"id": sid, "seconds": round(seconds, 2), "render": render,
                             "image": {"prompt": prompt[:1000], "model": im.get("model") or "", "ratio": im.get("ratio") or "9:16",
                                       "resolution": im.get("resolution") or "2k", "quality": im.get("quality") or "high",
                                       "complexity": im.get("complexity") or "medium", "transparent": bool(im.get("transparent")),
                                       "output": im.get("output") or "normal", "format": im.get("format") or "png", "n": n_img,
                                       "refs": [str(x)[:300] for x in (im.get("refs") or [])][:16],
                                       "gif_frames": max(2, min(16, int(im.get("gif_frames") or 8))),
                                       "gif_delay_ms": max(20, min(2000, int(im.get("gif_delay_ms") or 150)))},
                             "voice": {"role": role, "speaker": str(vo.get("speaker") or s.get("speaker") or "")[:80],
                                       "engine": str(vo.get("engine") or s.get("tts_engine") or "auto"), "tone": tone[:60], "text": text[:500]}})
    return out


def estimate(doc):
    from . import imagegen, tts_cloud
    imgs, n_img = 0.0, 0
    for s in doc.get("shots") or []:
        im = s.get("image") or {}
        n = int(im.get("n") or 1)
        n_img += n
        try:
            cd = imagegen.card(im.get("model") or "")
            price = cd.get("price")
            imgs += float(price) * n if price is not None else float(imagegen.est_usd(cd, im.get("ratio") or "9:16", im.get("resolution") or "2k", im.get("quality") or "high") or 0)
        except Exception:
            pass
    chars = sum(len((s.get("voice") or {}).get("text") or "") for s in doc.get("shots") or [])
    try:
        cny = float(tts_cloud.price()) * chars / 10000.0
    except Exception:
        cny = 0.0
    return {"images": n_img, "image_usd": round(imgs, 4), "tts_chars": chars, "tts_cny_cloud": round(cny, 4),
            "bgm_segments": len(doc.get("bgm", {}).get("segments") or []),
            "note": "生图模块不参与成片；这里只是参考价。本地配音/配乐不花钱"}
