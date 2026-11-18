r"""视频工坊 · 自由节点图（v3.9.0 / R10，阶段 B/C 的地基）。

project.json 里多一层：
  graph = {
    "nodes": [{id, type, title, x, y, w, h, params, outputs, status, error, cache_key, cache_hit}],
    "edges": [{id, from: "节点id.端口名", to: "节点id.端口名"}]
  }

节点类型：
  script  剧本与策划（固定 1 个）：输出 text
  image   生图（可多个）：输入 text / image（参考图），输出 image
  voice   配音（可多个）：输入 text，输出 audio / timeline
  bgm     背景配乐（可多个）：输入 text，输出 audio
  web     网页动效（可多个）：输入 image / text / audio，输出 video
  ppt     PPT / OnlyOffice 卡片（可多个）：输入 text / image，输出 image
  mux     FFmpeg 混流压制（固定 1 个）：输入 image / audio / video / text，输出 video
  publish 发布与排期（固定 1 个）：输入 video / image / text

端口有类型：text / image / audio / video / timeline。连线时校验类型兼容、禁止环。
固定节点 script / mux / publish 不可删除；其余五类可任意增删。
"""
import hashlib
import json
import re

NODE_NAME = {"script": "剧本与策划", "image": "生图", "voice": "配音", "bgm": "背景配乐",
             "web": "网页动效", "ppt": "PPT 卡片", "mux": "FFmpeg 混流压制", "publish": "发布与排期"}
FIXED = {"script", "mux", "publish"}
FLEX = ("image", "voice", "bgm", "web", "ppt")
PORT_NAME = {"text": "文字", "image": "图片", "audio": "音频", "video": "视频", "timeline": "时间轴"}
PORTS = {
    "script": {"in": [], "out": [("text", "text")]},
    "image": {"in": [("prompt", "text"), ("ref", "image")], "out": [("image", "image")]},
    "voice": {"in": [("text", "text")], "out": [("audio", "audio"), ("timeline", "timeline")]},
    "bgm": {"in": [("text", "text")], "out": [("audio", "audio")]},
    "web": {"in": [("image", "image"), ("text", "text"), ("audio", "audio")], "out": [("video", "video")]},
    "ppt": {"in": [("text", "text"), ("image", "image")], "out": [("image", "image")]},
    "mux": {"in": [("image", "image"), ("audio", "audio"), ("video", "video"), ("text", "text")], "out": [("video", "video")]},
    "publish": {"in": [("video", "video"), ("image", "image"), ("text", "text")], "out": []},
}
UNLIMITED = {("mux", "image"), ("mux", "audio"), ("mux", "video"), ("image", "ref"), ("ppt", "image"), ("web", "image")}
DEFAULT_SIZE = {"script": (340, 420), "image": (360, 560), "voice": (380, 460), "bgm": (320, 320),
                "web": (360, 380), "ppt": (340, 360), "mux": (360, 420), "publish": (360, 500)}
TYPE_COLOR = {"script": "text", "image": "image", "voice": "audio", "bgm": "audio", "web": "video", "ppt": "image",
              "mux": "video", "publish": "publish"}
MODEL_VERSION = "studio-graph-3.9.0"


class GraphError(ValueError):
    pass


def _new_id(nodes, typ):
    used = {n.get("id") for n in nodes}
    base = typ if typ in FIXED else typ + "-1"
    if base not in used:
        return base
    n = 2 if typ not in FIXED else 2
    while f"{typ}-{n}" in used:
        n += 1
    return f"{typ}-{n}"


def _order(nodes):
    vals = [int(n.get("params", {}).get("order") or 0) for n in nodes]
    return max(vals, default=0) + 1


def node_of(graph, nid):
    for n in graph.get("nodes") or []:
        if n.get("id") == nid:
            return n
    raise GraphError("没有这个节点：" + str(nid))


def port_type(typ, name, direction="in"):
    for p, t in PORTS.get(typ, {}).get(direction, []):
        if p == name:
            return t
    raise GraphError(f"{NODE_NAME.get(typ, typ)} 没有{'输入' if direction == 'in' else '输出'}端口「{name}」")


def split_port(ref):
    s = str(ref or "")
    if "." not in s:
        raise GraphError("端口要写成「节点id.端口名」：" + s)
    nid, port = s.rsplit(".", 1)
    if not nid or not port:
        raise GraphError("端口要写成「节点id.端口名」：" + s)
    return nid, port


def default_params(typ, index=1, project=None):
    st = (project or {}).get("settings") or {}
    ratio = (project or {}).get("ratio") or "9:16"
    if typ == "script":
        return {"topic": (project or {}).get("topic") or "", "source_text": "", "script_removed": False}
    if typ == "image":
        return {"prompt": "", "model": st.get("img_model") or "", "ratio": ratio, "resolution": st.get("img_resolution") or "2k",
                "quality": st.get("img_quality") or "high", "complexity": st.get("img_complexity") or "medium",
                "transparent": False, "output": "normal", "format": "png", "n": 1, "custom_w": 0, "custom_h": 0,
                "gif_frames": 8, "gif_delay_ms": 150, "refs": [], "order": index}
    if typ == "voice":
        role = "白页" if index % 2 else "紫苏"
        speaker = (project or {}).get("settings", {}).get("role_voices", {}).get(role) or \
                  ("local:preset:Serena" if role == "白页" else "local:preset:Dylan")
        return {"role": role, "speaker": speaker, "engine": "auto",
                "tone": "冷静吐槽" if role == "白页" else "轻松调侃",
                "lines": [{"id": "l1", "text": "", "tone": ""}], "order": index}
    if typ == "bgm":
        return {"prompt": (project or {}).get("bgm_prompt") or "", "seconds": 0, "steps": 8, "seed": 20261118, "order": index}
    if typ == "web":
        return {"bg": st.get("web_bg") or "dark", "sub_pos": st.get("web_sub_pos") or "bottom",
                "sub_size": st.get("web_sub_size") or 0, "sub_color": st.get("web_sub_color") or "",
                "gif_scale": st.get("web_gif_scale") or 1, "motion": st.get("web_motion") if st.get("web_motion") is not None else 1,
                "fps": st.get("web_fps") or 24, "duration": 6, "text": "", "order": index,
                "styleframe": {"html": "", "prompt": "", "cache_key": "", "sha256": ""}}
    if typ == "ppt":
        return {"file": st.get("ppt_file") or "", "points": [], "text": "", "order": index}
    if typ == "mux":
        return {"subtitle": st.get("subtitle", True), "bgm_volume": st.get("bgm_volume", 0.18),
                "kenburns": st.get("kenburns", True), "duck_depth": st.get("duck_depth", 0.16),
                "fade": st.get("fade", 2.0), "ratio": ratio}
    if typ == "publish":
        return {"title": (project or {}).get("title") or "", "desc": (project or {}).get("desc") or "",
                "tags": (project or {}).get("tags") or [], "schedule": "", "declaration": "内容由AI生成",
                "cover": "auto", "mode": "single", "collection": ""}
    raise GraphError("不认识的节点类型：" + str(typ))


def new_node(typ, index=1, x=40, y=40, project=None, title=None):
    if typ not in NODE_NAME:
        raise GraphError("不认识的节点类型：" + str(typ))
    w, h = DEFAULT_SIZE[typ]
    return {"id": "", "type": typ, "title": title or (NODE_NAME[typ] + ("" if typ in FIXED else f" #{index}")),
            "x": int(x), "y": int(y), "w": w, "h": h,
            "params": default_params(typ, index, project), "outputs": [], "status": "idle", "error": "",
            "cache_key": "", "cache_hit": False, "started": 0, "finished": 0}


def default_graph(project, script_title="剧本与策划"):
    """新建工程的默认画布：9 个节点，0 条连线，每个都能单独跑。"""
    nodes = []
    spec = [
        ("script", 1, 40, 40, "剧本与策划"),
        ("image", 1, 420, 40, "生图 #1"),
        ("voice", 1, 820, 40, "配音·白页"),
        ("voice", 2, 820, 530, "配音·紫苏"),
        ("bgm", 1, 1240, 40, "背景配乐 #1"),
        ("web", 1, 420, 640, "网页动效渲染 #1"),
        ("ppt", 1, 40, 500, "PPT/OnlyOffice 卡片 #1"),
        ("mux", 1, 1240, 400, "FFmpeg 混流压制"),
        ("publish", 1, 1640, 400, "发布与排期"),
    ]
    for typ, i, x, y, title in spec:
        n = new_node(typ, i, x, y, project, title)
        n["id"] = {"script": "script", "mux": "mux", "publish": "publish"}.get(typ, f"{typ}-{i}")
        if typ == "voice":
            role = "白页" if i == 1 else "紫苏"
            n["params"]["role"] = role
            n["params"]["speaker"] = "local:preset:Serena" if role == "白页" else "local:preset:Dylan"
            n["params"]["tone"] = "冷静吐槽" if role == "白页" else "轻松调侃"
            n["params"]["order"] = i
            n["params"]["lines"] = [{"id": "l1", "text": f"这是{role}的第 1 句测试台词，可以直接改成你要念的内容。", "tone": ""}]
        if typ == "image" and i == 1:
            n["params"]["prompt"] = "第 1 个测试画面：简洁、清晰、适合竖屏短视频，主体居中偏上。"
        if typ == "bgm":
            n["params"]["prompt"] = "upbeat electronic, no vocals, suitable under narration"
        if typ == "web" and i == 1:
            n["params"]["duration"] = 6
            n["params"]["text"] = "网页动效测试字幕，可以直接改。"
        if typ == "ppt" and i == 1:
            n["params"]["text"] = "PPT 卡片测试页"
        nodes.append(n)
    return {"nodes": nodes, "edges": []}


def valid_graph(g) -> bool:
    if not isinstance(g, dict) or not isinstance(g.get("nodes"), list) or not isinstance(g.get("edges"), list):
        return False
    ids = set()
    for n in g["nodes"]:
        if not isinstance(n, dict) or not n.get("id") or n.get("type") not in NODE_NAME or n["id"] in ids:
            return False
        ids.add(n["id"])
    fixed = {n["type"] for n in g["nodes"] if n["type"] in FIXED}
    return fixed == FIXED


def ensure_graph(p) -> bool:
    """没有 graph 就建/迁移；返回是否动过 project。迁移失败抛 GraphError，调用方恢复备份。"""
    if valid_graph(p.get("graph")):
        return False
    if p.get("shots"):
        p["graph"] = migrate_from_shots(p)
    else:
        p["graph"] = default_graph(p)
    p["graph_version"] = 3
    return True


def _pack(rel, kind, project_dir, extra=None):
    """项目里的一个产出 → 节点 outputs 的一项（带内容哈希）。"""
    from pathlib import Path
    q = Path(project_dir) / str(rel or "") if rel else None
    if not q or not q.is_file():
        return None
    from . import studio_cache as cache
    out = {"key": str(rel), "rel": str(rel), "kind": kind, "sha256": cache.sha_file(q), "size": q.stat().st_size}
    if extra:
        out.update({k: v for k, v in extra.items() if v not in (None, "")})
    return out


def migrate_from_shots(p) -> dict:
    """旧工程（shots[]）→ 自由节点。每张分镜图、每句配音都拆成独立节点；已有产出和缓存指纹原样保留。"""
    from pathlib import Path
    d = Path(p["dir"])
    shots = p.get("shots") or []
    nodes, edges = [], []
    script = new_node("script", 1, 40, 40, p, "剧本与策划")
    script["id"] = "script"
    script["params"].update(topic=p.get("topic") or "", title=p.get("title") or "", desc=p.get("desc") or "",
                            tags=p.get("tags") or [], bgm_prompt=p.get("bgm_prompt") or "",
                            source_text=p.get("source_text") or "")
    nodes.append(script)
    x0, y0, dx = 420, 40, 390
    imgs, voices, webs, ppts = [], [], [], []
    for i, s in enumerate(shots):
        n = new_node("image", i + 1, x0, y0 + i * 300, p, f"生图 #{i + 1}")
        n["id"] = f"image-{i + 1}"
        n["params"].update({
            "prompt": s.get("image_prompt") or "", "model": s.get("img_model") or (p.get("settings") or {}).get("img_model") or "",
            "ratio": s.get("img_ratio") or p.get("ratio") or "9:16",
            "resolution": s.get("img_resolution") or (p.get("settings") or {}).get("img_resolution") or "2k",
            "quality": s.get("img_quality") or (p.get("settings") or {}).get("img_quality") or "high",
            "complexity": s.get("img_complexity") or (p.get("settings") or {}).get("img_complexity") or "medium",
            "transparent": bool(s.get("img_transparent", (p.get("settings") or {}).get("img_transparent"))),
            "output": s.get("img_output") or "normal", "format": s.get("img_format") or "png",
            "n": int(s.get("img_n") or 1), "custom_w": int(s.get("img_custom_w") or 0),
            "custom_h": int(s.get("img_custom_h") or 0), "gif_frames": int(s.get("gif_frames") or 8),
            "gif_delay_ms": int(s.get("gif_delay_ms") or 150), "refs": s.get("img_refs") or [], "order": i + 1})
        rels = s.get("img_variants") or ([s.get("image")] if s.get("image") else [])
        fps = s.get("img_fps") or []
        for j, rel in enumerate(rels):
            o = _pack(rel, "image", d, {"index": j, "cache_fp": (fps[j] if j < len(fps) else "")})
            if o:
                n["outputs"].append(o)
        if n["outputs"]:
            n["status"] = "ok"
            n["cache_hit"] = bool(s.get("image_cache_hit"))
        nodes.append(n)
        imgs.append(n)
        v = new_node("voice", i + 1, x0 + dx, y0 + i * 300, p, f"配音 #{i + 1} · {s.get('role') or '旁白'}")
        v["id"] = f"voice-{i + 1}"
        line = {"id": f"l1", "text": s.get("text") or "", "tone": s.get("tone") or ""}
        v["params"].update({"role": s.get("role") or "旁白", "speaker": s.get("speaker") or "",
                            "engine": s.get("tts_engine") or "auto", "tone": s.get("tone") or "",
                            "lines": [line] if line["text"] else [{"id": "l1", "text": "", "tone": ""}], "order": i + 1})
        o = _pack(s.get("tts"), "audio", d, {"duration": s.get("duration")})
        if o:
            v["outputs"].append(o)
            v["status"] = "ok"
            v["cache_hit"] = bool(s.get("tts_cache_hit"))
        nodes.append(v)
        voices.append(v)
        if s.get("render") == "web":
            w = new_node("web", len(webs) + 1, x0, y0 + (len(shots) + i) * 260, p, f"网页动效 #{len(webs) + 1}")
            w["id"] = f"web-{len(webs) + 1}"
            w["params"].update({"duration": float(s.get("duration") or s.get("seconds_hint") or 5), "text": s.get("text") or "",
                                "order": i + 1})
            o = _pack(s.get("render_clip"), "video", d)
            if o:
                w["outputs"].append(o)
                w["status"] = "ok"
            nodes.append(w)
            webs.append(w)
            edges.append({"id": f"e-{n['id']}-{w['id']}", "from": n["id"] + ".image", "to": w["id"] + ".image"})
            visual = w
        elif s.get("render") == "ppt":
            q = new_node("ppt", len(ppts) + 1, x0 + dx, y0 + (len(shots) + i) * 260, p, f"PPT 卡片 #{len(ppts) + 1}")
            q["id"] = f"ppt-{len(ppts) + 1}"
            q["params"].update({"text": s.get("text") or "", "order": i + 1})
            o = _pack(s.get("render_image"), "image", d)
            if o:
                q["outputs"].append(o)
                q["status"] = "ok"
            nodes.append(q)
            ppts.append(q)
            visual = q
        else:
            visual = n
        edges.append({"id": f"e-{visual['id']}-mux", "from": visual["id"] + (".image" if visual["type"] in ("image", "ppt") else ".video"),
                      "to": "mux.image" if visual["type"] in ("image", "ppt") else "mux.video"})
        edges.append({"id": f"e-{v['id']}-mux", "from": v["id"] + ".audio", "to": "mux.audio"})
    bgm = new_node("bgm", 1, 40, 520, p, "背景配乐 #1")
    bgm["id"] = "bgm-1"
    bgm["params"].update({"prompt": p.get("bgm_prompt") or "", "seconds": int((p.get("settings") or {}).get("bgm_seconds") or 0),
                          "steps": int((p.get("settings") or {}).get("bgm_steps") or 8),
                          "seed": int((p.get("settings") or {}).get("bgm_seed") or 20261118), "order": 1})
    o = _pack((p.get("files") or {}).get("bgm"), "audio", d)
    if o:
        bgm["outputs"].append(o)
        bgm["status"] = "ok"
        bgm["cache_hit"] = bool(p.get("bgm_cache_hit"))
    nodes.append(bgm)
    edges.append({"id": "e-bgm-mux", "from": "bgm-1.audio", "to": "mux.audio"})
    mux = new_node("mux", 1, 1240, 400, p, "FFmpeg 混流压制")
    mux["id"] = "mux"
    o = _pack((p.get("files") or {}).get("video"), "video", d)
    if o:
        mux["outputs"].append(o)
        mux["status"] = "ok"
    nodes.append(mux)
    pub = new_node("publish", 1, 1640, 400, p, "发布与排期")
    pub["id"] = "publish"
    pub["params"].update({"title": p.get("title") or "", "desc": p.get("desc") or "", "tags": p.get("tags") or []})
    nodes.append(pub)
    edges.append({"id": "e-mux-publish", "from": "mux.video", "to": "publish.video"})
    # 去重、去掉缺端点的边
    seen, good = set(), []
    ids = {n["id"] for n in nodes}
    for e in edges:
        try:
            a, pa = split_port(e["from"]); b, pb = split_port(e["to"])
        except GraphError:
            continue
        if a in ids and b in ids and e["id"] not in seen:
            seen.add(e["id"]); good.append(e)
    return {"nodes": nodes, "edges": good}


def add_node(graph, typ, x=40, y=40, project=None):
    if typ in FIXED or typ not in FLEX:
        raise GraphError(("固定节点不能重复添加：" if typ in FIXED else "不认识的节点类型：") + str(typ))
    nodes = graph["nodes"]
    n = new_node(typ, _order(nodes), x, y, project)
    n["id"] = _new_id(nodes, typ)
    n["params"]["order"] = _order(nodes)
    nodes.append(n)
    return n


def delete_node(graph, nid):
    n = node_of(graph, nid)
    if n["type"] in FIXED:
        raise GraphError(f"{NODE_NAME[n['type']]} 是固定节点，不能删除")
    graph["nodes"] = [x for x in graph["nodes"] if x["id"] != nid]
    graph["edges"] = [e for e in graph["edges"] if not (e.get("from", "").startswith(nid + ".") or e.get("to", "").startswith(nid + "."))]
    return n


def _reaches(graph, start, target):
    """从 start 顺着连线往下走，能不能走到 target。"""
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        if cur == target:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        for e in graph.get("edges") or []:
            a, _pa = split_port(e.get("from"))
            b, _pb = split_port(e.get("to"))
            if a == cur:
                stack.append(b)
    return False


def connect(graph, from_ref, to_ref):
    a, pa = split_port(from_ref)
    b, pb = split_port(to_ref)
    na, nb = node_of(graph, a), node_of(graph, b)
    if a == b:
        raise GraphError("不能连自己")
    ta = port_type(na["type"], pa, "out")
    tb = port_type(nb["type"], pb, "in")
    if ta != tb:
        raise GraphError(f"端口类型不兼容：{PORT_NAME.get(ta, ta)} 不能接到 {PORT_NAME.get(tb, tb)}")
    for e in graph["edges"]:
        if e.get("from") == from_ref and e.get("to") == to_ref:
            return e
    if (nb["type"], pb) not in UNLIMITED:
        cnt = sum(1 for e in graph["edges"] if e.get("to") == to_ref)
        if cnt >= 1:
            raise GraphError(f"{NODE_NAME[nb['type']]} 的「{pb}」端口只接一条线，先断开旧的")
    if _reaches(graph, b, a):
        raise GraphError("会形成环：这条线接下去会绕回自己")
    e = {"id": f"e-{a}-{b}-{len(graph['edges']) + 1}", "from": from_ref, "to": to_ref}
    while any(x.get("id") == e["id"] for x in graph["edges"]):
        e["id"] += "_2"
    graph["edges"].append(e)
    invalidate_downstream(graph, b)
    return e


def disconnect(graph, edge_id):
    before = len(graph["edges"])
    graph["edges"] = [e for e in graph["edges"] if e.get("id") != edge_id]
    if len(graph["edges"]) == before:
        raise GraphError("没有这条连线")
    return True


def incoming(graph, nid):
    return [e for e in graph.get("edges") or [] if split_port(e.get("to"))[0] == nid]


def upstream_ids(graph, nid):
    return [split_port(e["from"])[0] for e in incoming(graph, nid)]


def invalidate_downstream(graph, nid):
    """本节点和它的下游失效；上游、平行分支不动。"""
    queue, seen = [nid], set()
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        n = node_of(graph, cur)
        n["cache_key"] = ""
        n["cache_hit"] = False
        if n.get("status") in ("ok", "warn"):
            n["status"] = "stale"
        for e in graph.get("edges") or []:
            if split_port(e.get("from"))[0] == cur:
                queue.append(split_port(e.get("to"))[0])
    return seen


def output_of(node, kind=None, rel=None):
    for o in node.get("outputs") or []:
        if rel and str(o.get("rel")) == str(rel):
            return o
        if kind and o.get("kind") == kind:
            return o
    return None


def output_hashes(graph, nid):
    seen, out = set(), []
    stack = list(upstream_ids(graph, nid))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        n = node_of(graph, cur)
        for o in n.get("outputs") or []:
            out.append([o.get("kind"), o.get("sha256") or ""])
        stack.extend(upstream_ids(graph, cur))
    return sorted(out)


def cache_key(node, graph) -> str:
    from . import studio_cache as cache
    params = {k: v for k, v in (node.get("params") or {}).items()
              if k not in ("selected", "waiting", "script_removed", "styleframe")}
    return cache.fingerprint("node", {"type": node.get("type"), "params": params,
                                      "upstream": output_hashes(graph, node["id"]),
                                      "v": MODEL_VERSION})


def topo_order(graph):
    nodes = graph.get("nodes") or []
    indeg = {n["id"]: 0 for n in nodes}
    outs = {n["id"]: [] for n in nodes}
    for e in graph.get("edges") or []:
        a, _ = split_port(e.get("from")); b, _ = split_port(e.get("to"))
        if a in indeg and b in indeg:
            indeg[b] += 1
            outs[a].append(b)
    q = [nid for nid, k in indeg.items() if k == 0]
    order = []
    while q:
        cur = q.pop(0)
        order.append(cur)
        for b in outs[cur]:
            indeg[b] -= 1
            if indeg[b] == 0:
                q.append(b)
    if len(order) != len(nodes):
        raise GraphError("图里有环，没法排顺序")
    return order


def sorted_upstream(graph, node, typ=None):
    """接到这个节点上的上游节点，按 params.order、再按位置排。"""
    out = []
    for e in incoming(graph, node["id"]):
        a, _pa = split_port(e["from"])
        n = node_of(graph, a)
        if typ and n["type"] != typ:
            continue
        out.append(n)
    out.sort(key=lambda n: (int(n.get("params", {}).get("order") or 0), int(n.get("y") or 0), int(n.get("x") or 0)))
    return out


# ---------------- 剧本 schema（阶段 C） ----------------
SHOT_RENDER = ("web", "ppt", "static")
ROLES = ("白页", "紫苏", "旁白")
FIELD_LABEL = {"image": "画面", "voice": "台词", "render": "画面轨道"}


def _err(line, msg):
    raise GraphError(f"第 {line} 行：{msg}")


def parse_script_doc(text):
    """JSON 或 Markdown 剧本 → 标准结构。出错给出具体行号和原因，不静默跳过。"""
    raw = str(text or "").strip()
    if not raw:
        raise GraphError("剧本是空的")
    m = re.search(r"```(?:json|markdown|md)?\s*(\{.*?\})\s*```", raw, re.S | re.I)
    cand = m.group(1) if m else raw
    if cand.lstrip().startswith("{"):
        return _parse_json(cand, raw)
    return _parse_md(raw)


def _parse_json(cand, raw):
    try:
        j = json.loads(cand)
    except json.JSONDecodeError as e:
        raise GraphError(f"JSON 第 {e.lineno} 行第 {e.colno} 列：{e.msg}") from None
    if not isinstance(j, dict):
        raise GraphError("剧本最外层要是一个对象 {}")
    return _norm_doc(j, lines=None)


def _parse_md(raw):
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    doc = {"title": "导入的剧本", "desc": "", "tags": [], "publish": {}, "bgm": {"segments": []}, "shots": []}
    shot = None
    bgm = None
    mode = "meta"
    n = 0
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            continue
        n = i
        if s.startswith("# ") and not s.startswith("## "):
            doc["title"] = _clean(s[2:])[:30] or doc["title"]
            continue
        if s.startswith("## "):
            head = _clean(s[3:])
            low = head.lower()
            if low.startswith("分镜") or low.startswith("shot"):
                sid = re.split(r"[\s:：]+", head, maxsplit=1)[1].strip() if re.search(r"[\s:：]", head) else ""
                shot = {"id": sid or f"s{len(doc['shots']) + 1}", "line": i, "image": {}, "voice": {}, "render": "static"}
                doc["shots"].append(shot)
                mode = "shot"
                bgm = None
            elif low.startswith("配乐") or low.startswith("bgm"):
                bid = re.split(r"[\s:：]+", head, maxsplit=1)[1].strip() if re.search(r"[\s:：]", head) else ""
                bgm = {"id": bid or f"bgm-{len(doc['bgm']['segments']) + 1}", "line": i}
                doc["bgm"]["segments"].append(bgm)
                mode = "bgm"
                shot = None
            else:
                _err(i, f"不认识的 ## 小节「{head}」，只能是「分镜 …」或「配乐 …」")
            continue
        if "：" in s or ":" in s:
            k, v = re.split(r"[:：]", s, maxsplit=1)
            k, v = _clean(k), _clean(v)
            if mode == "shot" and shot is not None:
                _md_shot_field(shot, k, v, i)
            elif mode == "bgm" and bgm is not None:
                _md_bgm_field(bgm, k, v, i)
            else:
                if k in ("简介", "描述", "desc"):
                    doc["desc"] = v
                elif k in ("话题", "标签", "tags"):
                    doc["tags"] = [re.sub(r"^[#＃]+", "", x)[:20] for x in re.split(r"[\s,，、#＃]+", v) if x][:10]
                elif k in ("定时", "发布时间", "schedule"):
                    doc["publish"]["schedule"] = v
                elif k in ("声明", "自主声明", "declaration"):
                    doc["publish"]["declaration"] = v
                else:
                    _err(i, f"剧本开头不认识的字段「{k}」")
            continue
        _err(i, "这一行既不是 # 标题 / ## 分镜，也不是「字段：值」")
    _ = n
    if not doc["shots"]:
        raise GraphError("剧本里没有「## 分镜 …」小节")
    return _norm_doc(doc, lines=lines)


def _md_shot_field(shot, k, v, line):
    im, vo = shot["image"], shot["voice"]
    if k in ("画面", "画面提示词", "prompt", "image_prompt"):
        im["prompt"] = v
    elif k in ("角色", "role"):
        vo["role"] = v
    elif k in ("音色", "speaker", "voice"):
        vo["speaker"] = v
    elif k in ("语气", "tone"):
        vo["tone"] = v
    elif k in ("台词", "口播", "text", "文案"):
        vo["text"] = v
    elif k in ("画面轨道", "轨道", "render"):
        r = {"网页": "web", "网页动效": "web", "web": "web", "ppt": "ppt", "PPT": "ppt", "卡片": "ppt", "静态": "static", "static": "static"}.get(v.lower(), v.lower())
        if r not in SHOT_RENDER:
            _err(line, f"画面轨道只能是 网页 / PPT / 静态，这里写的是「{v}」")
        shot["render"] = r
    elif k in ("时长", "seconds", "seconds_hint"):
        try:
            shot["seconds"] = float(v)
        except ValueError:
            _err(line, f"时长要写数字，这里写的是「{v}」")
    elif k in ("生图模型", "model"):
        im["model"] = v
    elif k in ("比例", "ratio"):
        im["ratio"] = v
    elif k in ("分辨率", "resolution"):
        im["resolution"] = v
    elif k in ("画质", "quality"):
        im["quality"] = v
    elif k in ("复杂度", "complexity"):
        im["complexity"] = v
    elif k in ("出图类型", "output"):
        im["output"] = v
    elif k in ("格式", "format"):
        im["format"] = v
    elif k in ("张数", "n"):
        try:
            im["n"] = int(v)
        except ValueError:
            _err(line, f"张数要写整数，这里写的是「{v}」")
    elif k in ("透明", "透明背景", "transparent"):
        im["transparent"] = v in ("开", "是", "1", "true", "True", "要")
    elif k in ("参考图", "refs"):
        im["refs"] = [x.strip() for x in re.split(r"[\s,，;；]+", v) if x.strip()][:16]
    else:
        _err(line, f"分镜里不认识的字段「{k}」")


def _md_bgm_field(bgm, k, v, line):
    if k in ("描述", "提示词", "prompt"):
        bgm["prompt"] = v
    elif k in ("时长", "seconds"):
        try:
            bgm["seconds"] = float(v)
        except ValueError:
            _err(line, f"配乐时长要写数字，这里写的是「{v}」")
    elif k in ("步数", "steps"):
        try:
            bgm["steps"] = int(v)
        except ValueError:
            _err(line, f"步数要写整数，这里写的是「{v}」")
    elif k in ("种子", "seed"):
        try:
            bgm["seed"] = int(v)
        except ValueError:
            _err(line, f"种子要写整数，这里写的是「{v}」")
    else:
        _err(line, f"配乐里不认识的字段「{k}」")


def _clean(s):
    return re.sub(r"\*\*", "", str(s or "")).strip().strip("`").strip()


def _need(cond, line, msg):
    if not cond:
        if line:
            _err(line, msg)
        raise GraphError(msg)


def _norm_doc(j, lines=None):
    out = {"version": 1, "title": str(j.get("title") or "导入的剧本")[:30], "desc": str(j.get("desc") or "")[:300],
           "tags": [], "publish": {}, "bgm": {"segments": []}, "shots": []}
    tags = j.get("tags") or []
    if isinstance(tags, str):
        tags = re.split(r"[\s,，、#＃]+", tags)
    out["tags"] = [re.sub(r"^[#＃]+", "", str(x).strip())[:20] for x in tags if str(x).strip()][:10]
    pub = j.get("publish") if isinstance(j.get("publish"), dict) else {}
    out["publish"] = {"schedule": str(pub.get("schedule") or "")[:16], "declaration": str(pub.get("declaration") or "内容由AI生成"),
                      "collection": str(pub.get("collection") or "")[:40], "mode": "batch" if pub.get("mode") == "batch" else "single"}
    # 配乐
    bg = j.get("bgm")
    segs = []
    if isinstance(bg, dict):
        segs = bg.get("segments")
        if segs is None:
            segs = [bg] if any(bg.get(k) for k in ("prompt", "描述", "提示词")) else []
    elif isinstance(bg, list):
        segs = bg
    for i, b in enumerate(segs or []):
        ln = b.get("line") if isinstance(b, dict) else None
        _need(isinstance(b, dict), ln, f"bgm.segments 第 {i + 1} 段要是一个对象")
        prompt = str(b.get("prompt") or b.get("描述") or "").strip()
        _need(bool(prompt), ln, f"bgm.segments 第 {i + 1} 段缺 prompt（英文描述）")
        seg = {"id": str(b.get("id") or f"bgm-{i + 1}")[:40], "prompt": prompt[:1000], "seconds": b.get("seconds", 0),
               "steps": b.get("steps", 8), "seed": b.get("seed", 20261118)}
        try:
            seg["seconds"] = max(0, float(seg["seconds"] or 0))
            seg["steps"] = max(1, min(32, int(seg["steps"] or 8)))
            seg["seed"] = int(seg["seed"] or 20261118)
        except (TypeError, ValueError):
            _need(False, ln, f"bgm.segments 第 {i + 1} 段的 seconds/steps/seed 要写数字")
        out["bgm"]["segments"].append(seg)
    # 分镜
    shots = j.get("shots")
    _need(isinstance(shots, list) and shots, None, "剧本里没有 shots（生图任务列表）")
    seen = set()
    for i, s in enumerate(shots):
        _need(isinstance(s, dict), None, f"shots 第 {i + 1} 项要是一个对象")
        ln = s.get("line") if isinstance(s, dict) else None
        sid = str(s.get("id") or "").strip()[:40]
        _need(bool(sid), ln, f"shots 第 {i + 1} 项缺 id（稳定的任务 key）")
        _need(sid not in seen, ln, f"shots 里有重复的 id「{sid}」")
        seen.add(sid)
        im = s.get("image") if isinstance(s.get("image"), dict) else {}
        vo = s.get("voice") if isinstance(s.get("voice"), dict) else {}
        prompt = str(im.get("prompt") or s.get("image_prompt") or "").strip()
        text = str(vo.get("text") or s.get("text") or "").strip()
        _need(bool(prompt), ln, f"分镜「{sid}」缺画面提示词（image.prompt）")
        _need(bool(text), ln, f"分镜「{sid}」缺台词（voice.text）")
        role = str(vo.get("role") or s.get("role") or ROLES[i % 2]).strip()
        _need(role in ROLES, ln, f"分镜「{sid}」的角色只能是白页 / 紫苏 / 旁白，写的是「{role}」")
        tone = str(vo.get("tone") or s.get("tone") or "").strip()
        _need(bool(tone), ln, f"分镜「{sid}」缺语气（voice.tone）")
        render = str(s.get("render") or "static").lower()
        _need(render in SHOT_RENDER, ln, f"分镜「{sid}」的画面轨道只能是 web / ppt / static，写的是「{render}」")
        try:
            seconds = max(1.0, min(120.0, float(s.get("seconds") or len(text) / 4.5)))
        except (TypeError, ValueError):
            _need(False, ln, f"分镜「{sid}」的 seconds 要写数字")
        try:
            n_img = max(1, min(4, int(im.get("n") or s.get("n") or 1)))
            gif_frames = max(2, min(16, int(im.get("gif_frames") or 8)))
            gif_delay = max(20, min(2000, int(im.get("gif_delay_ms") or 150)))
        except (TypeError, ValueError):
            _need(False, ln, f"分镜「{sid}」的 n / gif_frames / gif_delay_ms 要写整数")
        out["shots"].append({
            "id": sid, "seconds": round(seconds, 2), "render": render,
            "image": {"prompt": prompt[:1000], "model": im.get("model") or s.get("img_model") or "",
                      "ratio": im.get("ratio") or s.get("ratio") or "9:16",
                      "resolution": im.get("resolution") or "2k", "quality": im.get("quality") or "high",
                      "complexity": im.get("complexity") or "medium", "transparent": bool(im.get("transparent")),
                      "output": im.get("output") or "normal", "format": im.get("format") or "png",
                      "n": n_img,
                      "refs": [str(x)[:300] for x in (im.get("refs") or [])][:16],
                      "gif_frames": gif_frames,
                      "gif_delay_ms": gif_delay},
            "voice": {"role": role, "speaker": str(vo.get("speaker") or s.get("speaker") or "")[:80],
                      "engine": str(vo.get("engine") or s.get("tts_engine") or "auto"), "tone": tone[:60], "text": text[:500]},
            "web": s.get("web") if isinstance(s.get("web"), dict) else {},
            "ppt": s.get("ppt") if isinstance(s.get("ppt"), dict) else {},
        })
    return out


def estimate(doc):
    """导入时的预估费用（不生成，只算给人看）。"""
    from . import imagegen, tts_cloud
    imgs = 0.0
    n_img = 0
    for s in doc.get("shots") or []:
        im = s.get("image") or {}
        n_img += int(im.get("n") or 1)
        try:
            cd = imagegen.card(im.get("model") or "")
            price = cd.get("price")
            if price is not None:
                imgs += float(price) * int(im.get("n") or 1)
            else:
                imgs += float(imagegen.est_usd(cd, im.get("ratio") or "9:16", im.get("resolution") or "2k", im.get("quality") or "high") or 0)
        except Exception:
            pass
    chars = sum(len((s.get("voice") or {}).get("text") or "") for s in doc.get("shots") or [])
    cny = 0.0
    try:
        cny = float(tts_cloud.price()) * chars / 10000.0
    except Exception:
        cny = 0.0
    return {"images": n_img, "image_usd": round(imgs, 4), "tts_chars": chars, "tts_cny_cloud": round(cny, 4),
            "bgm_segments": len(doc.get("bgm", {}).get("segments") or []),
            "note": "本地配音、本地配乐不花钱；这里按 API易生图和百炼云端配音粗算，实际以账单为准"}
