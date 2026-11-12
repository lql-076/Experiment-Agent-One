r"""批量清单先让 DeepSeek 看一遍（v3.3）：作者 11-13「上传的 TXT、Markdown 随便怎么写，让大模型从头到尾过一遍，按批量要的格式认出来」。
生图、配音、配乐、发布四个批量都用：把上传的文件（可以几个）加上行号发给 DeepSeek（json 模式），它回一份结构化的清单，
这里再整理成各自原来认得的标准格式（生图、配音、配乐还是交给原来的 parse；发布直接用）。

- 原文不让它改写：提示词、配音的字都用「第几行到第几行」指回原文，这里照原样切出来（它只负责分条、认字段）。
- 配音：告诉它现在能用的音色（我的音色、预设、云端的名字），它按文件名或文中的说法把每段配给角色、角色配给音色。
- 发布：告诉它文件夹里有哪些视频、图片和今天的日期，它按名字配视频和封面、把「周五晚上 8 点」这种换成 2026-11-14 20:00。
- 只发上传的这几个文件的文字（和音色名、文件名）；一次最多 6 万字。DeepSeek 的钱照常记账（purpose = 批量清单）。"""
import json
import re
from datetime import datetime

from fastapi import HTTPException

from . import deepseek

MAX_IN = 60000
SYS = {
    "img": """你是生图批量清单整理员。用户给你一份或几份写法不固定的生图清单（行首是行号）。找出每一张要出的图：
- file：文件名（清单里写了就用原样，不写就按顺序 img01_简短描述.png；必须 .png 结尾，不能有 \\ / : * ? " < > |）
- ratio：比例，只能是 16:9、9:16、1:1、4:3、3:4、3:2、2:3、5:4、4:5、21:9 之一（写的是「竖屏」= 9:16、「横屏」= 16:9、「方图」= 1:1；没写就 16:9）
- transparent：要不要透明背景（写了透明、抠图、PNG 透明、无背景 = true；写了要背景、不透明 = false；没说就 false）
- lines：提示词在原文的行号范围 [开始行, 结束行]（含两头）。提示词必须用原文，只给行号，不要自己改写、翻译、补充。
- 要是提示词和文件名、比例这些挤在同一行，再加一个 prompt：从那一行里原样摘出提示词那一段（一个字不改）。
- 如果清单开头有整体的「视觉方向 / 画风说明」，用 direction_lines 给它的行号范围，没有就不给。
只回 JSON：{"title": "清单标题", "direction_lines": [a, b] 或 null, "items": [{"file", "ratio", "transparent", "lines": [a, b]}], "notes": ["你没把握、需要用户看一眼的地方"]}""",
    "tts": """你是配音批量清单整理员。用户给你一份或几份配音稿（行首是行号，每个文件前面有一行「===== 文件 N：文件名 =====」）。把它分成一段一段要念的：
- 一个文件就是一个人的整篇配音稿（比如「白页配音稿.txt」）→ 整篇一段，角色从文件名看。
- 剧本那种（每句前面标了说话人，比如「03 白页：……」「紫苏：……」）→ 同一个人连着说的句子合成一段，按出场顺序一段一段排。
- file：文件名，不带扩展名。原文写了就用原文的；不然按顺序「01_角色_几个字」。
- role：这一段是谁说的（角色名）。
- voice：用哪个音色。只能从下面「能用的音色」里选一个名字原样写上；文中写了「白页用 xxx 音色」「紫苏的声音：xxx」这类就照着配；角色名和某个音色名一样就用它；实在看不出来就写空字符串（用页面上选的）。
- tone：语气（文中写了才填，比如「激动」「平静」），没写就空。
- lines：要念的字在原文的行号范围 [开始行, 结束行]（含两头）。只框要念出来的字：不要框进文件名那行、标题、「音色：」这种说明行。行首的「03 白页：」这种说话人标签可以框进来，程序会去掉。
只回 JSON：{"title": "这一期的名字", "roles": {"角色": "音色名"}, "items": [{"file", "role", "voice", "tone", "lines": [a, b]}], "notes": ["没把握的地方"]}""",
    "bgm": """你是配乐批量清单整理员。用户给你一份或几份写法不固定的配乐需求（行首是行号）。列出要出的每一首纯音乐：
- name：文件名（不带扩展名）。写了就用原样，不然按顺序 bgm01_用途。
- seconds：多长（秒，10~600）。写的是 1:30、1分30秒 就换成 90；没写就 60。
- prompt：给 ACE-Step 的描述（风格、情绪、乐器、速度），尽量用原文的说法，可以把原文里分散的要求合成一句。
- 要是写了「同一个描述出 3 首」「来几版挑一下」，就拆成几首：name 后面加 _1、_2、_3，prompt 一样。
只回 JSON：{"title": "清单标题", "items": [{"name", "seconds", "prompt"}], "notes": ["没把握的地方"]}""",
    "pub": """你是抖音批量发布清单整理员。用户给你一份或几份发布清单（行首是行号），还有一个文件夹里的文件名列表。每一条要发的视频整理成：
- video：视频文件名，必须是「文件夹里的文件」里的一个，原样写。清单里写的名字对不上时按最像的配（同一个序号、同一个标题）；配不上就写空字符串。
- cover：封面图文件名，同样必须是文件夹里的；清单没写就找和视频同名或同序号的图片；没有就空字符串。
- title：标题（30 字以内，用原文；超了就照原意缩短并写进 notes）。
- desc：简介（原文，没有就空）。
- tags：话题列表，不带 #。
- schedule：定时发布时间，格式 YYYY-MM-DD HH:MM（今天是 {today}，按这个换算「明天 20:00」「周五晚上 8 点」）；没写就空字符串。
- collection：合集名（写了才填）。
- declaration：自主声明（写了才填，只能是：内容由AI生成、内容自行拍摄、内容取材网络、虚构演绎，仅供娱乐、可能引人不适、危险行为，请勿模仿）。
只回 JSON：{"title": "这一批的名字", "items": [{"video", "cover", "title", "desc", "tags", "schedule", "collection", "declaration"}], "notes": ["没把握的地方"]}""",
}


def numbered(files):
    """几个文件拼成一份带行号的文字；返回 (发给它的文字, 每行原文)。"""
    lines, out = [], []
    for i, f in enumerate(files, 1):
        head = f"===== 文件 {i}：{f.get('name') or '粘贴的'} ====="
        lines.append(None)
        out.append(f"{len(lines)}| {head}")
        for x in str(f.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            lines.append(x)
            out.append(f"{len(lines)}| {x}")
    return "\n".join(out), lines


def cut(lines, rng):
    """按行号范围切原文（1 开始、含两头）；文件头那几行跳过。"""
    try:
        a, b = int(rng[0]), int(rng[1])
    except (TypeError, ValueError, IndexError):
        return ""
    a, b = max(1, a), min(len(lines), b)
    return "\n".join(x for x in lines[a - 1:b] if x is not None).strip()


async def ask(kind, files, ctx=""):
    """发给 DeepSeek，回 (它整理的 JSON, 带行号前的每行原文, 花了多少钱)。"""
    if not deepseek._key():
        raise HTTPException(400, "没填 DeepSeek Key：到 设置 › 云端 填好；或者把「DeepSeek 帮我认」关掉，按固定格式写清单")
    files = [f for f in files if str(f.get("text") or "").strip()]
    if not files:
        raise HTTPException(400, "清单是空的")
    text, lines = numbered(files)
    if len(text) > MAX_IN:
        raise HTTPException(400, f"清单太长了（{len(text)} 字，一次最多 {MAX_IN} 字）：拆成几份分开认")
    sys_ = SYS[kind].replace("{today}", datetime.now().strftime("%Y-%m-%d %A"))
    msgs = [{"role": "system", "content": sys_ + (("\n\n" + ctx) if ctx else "")}, {"role": "user", "content": text}]
    try:
        r = await deepseek.chat(msgs, json_mode=True, max_tokens=8000, purpose="批量清单", temperature=0.1, timeout=180)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"DeepSeek 没整理出来：{type(e).__name__} {str(e)[:160]}（可以关掉「DeepSeek 帮我认」按固定格式写）") from None
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", r["text"].strip())
    try:
        j = json.loads(t)
    except ValueError:
        raise HTTPException(502, "DeepSeek 回的不是能用的清单（可能太长被截断了）：拆成几份再认，或者关掉「DeepSeek 帮我认」") from None
    if isinstance(j, dict) and isinstance(j.get("items"), list):
        j["items"] = [x for x in j["items"] if isinstance(x, dict)]
    if not isinstance(j, dict) or not isinstance(j.get("items"), list) or not j["items"]:
        raise HTTPException(400, "DeepSeek 看完没找到要做的条目：看看是不是传错文件了")
    return j, lines, float(r.get("cny") or 0)


def _cell(s):
    return str(s or "").replace("|", "／").replace("\n", "<br>").strip()


def to_img_md(j, lines):
    """生图：整理成原来认得的表格（文件名 | 比例 | 透明背景 | 提示词）。"""
    out = [f"# {j.get('title') or '生图清单'}", ""]
    d = cut(lines, j.get("direction_lines")) if j.get("direction_lines") else ""
    if d:
        out += ["视觉方向：" + d.replace("\n", " "), ""]
    out += ["| 文件名 | 比例 | 透明背景 | 提示词 |", "|---|---|---|---|"]
    for it in j["items"]:
        raw = cut(lines, it.get("lines")) if it.get("lines") else ""
        pp = str(it.get("prompt") or "").strip()
        p = pp if pp and (not raw or pp in raw) else (raw or pp)          # 它摘的那段必须是原文里的，不然用整行
        p = re.sub(r"^\s*(提示词|prompt)\s*[:：]\s*", "", p, flags=re.I)
        f = str(it.get("file") or "").strip() or f"img{len(out):02d}.png"
        if not f.lower().endswith(".png"):
            f += ".png"
        out.append(f"| {_cell(f)} | {_cell(it.get('ratio') or '16:9')} | {'开' if it.get('transparent') else '关'} | {_cell(p)} |")
    return "\n".join(out) + "\n"


def to_tts_md(j, lines):
    """配音：整理成「## 文件名 / 音色： / 语气： / 正文」。行首的「03 白页：」这种说话人标签去掉。"""
    roles = set((j.get("roles") or {}).keys()) | {str(it.get("role") or "") for it in j["items"]}
    roles = {r for r in roles if r}
    tag = re.compile(r"^\s*(?:\d+\s*[.、)）]?\s*)?(?:" + "|".join(re.escape(r) for r in sorted(roles, key=len, reverse=True)) + r")\s*[:：]\s*") if roles else None
    out = [f"# {j.get('title') or '配音批量'}", ""]
    for it in j["items"]:
        body = cut(lines, it.get("lines")) if it.get("lines") else str(it.get("text") or "")
        if tag:
            body = "\n".join(tag.sub("", x) for x in body.split("\n"))
        body = body.strip()
        if not body:
            continue
        voice = str(it.get("voice") or (j.get("roles") or {}).get(it.get("role") or "", "") or "").strip()
        out += [f"## {it.get('file') or it.get('role') or '配音'}"]
        if voice:
            out.append(f"音色：{voice}")
        if it.get("tone"):
            out.append(f"语气：{it['tone']}")
        out += [body, ""]
    return "\n".join(out)


def to_bgm_md(j):
    out = [f"# {j.get('title') or '配乐清单'}", ""]
    for it in j["items"]:
        p = re.sub(r"\s+", " ", str(it.get("prompt") or "")).strip()
        if not p:
            continue
        out += [f"## {it.get('name') or 'bgm'}", f"时长：{it.get('seconds') or 60}", f"描述：{p}", ""]
    return "\n".join(out)


def voice_list(engine):
    """配音现在能用的音色：[(名字, 说明)]。"""
    from . import tts, tts_cloud
    try:
        if engine == "cloud":
            return [(str(v.get("name") or v["id"]), str(v.get("d") or "")[:50]) for v in tts_cloud.voices()]
        return [(str(v["name"]), "我的音色：" + str(v.get("desc") or "")[:50]) for v in tts.T.voices()] + [(x["id"], "预设：" + x["d"]) for x in tts.SPEAKERS]
    except Exception:
        return []


async def media_md(kind, body):
    """生图、配音、配乐：让它认完，整理成原来认得的格式。回 (md, 原文件名, 提示)。"""
    files = body.get("files") or [{"name": body.get("name") or "粘贴的", "text": body.get("md") or ""}]
    ctx, vs = "", []
    if kind == "tts":
        vs = voice_list(body.get("engine") or "local")
        ctx = "能用的音色（名字原样写）：\n" + ("\n".join(f"- {n}（{d}）" for n, d in vs) or "（还没有，voice 都写空）")
    j, lines, cny = await ask(kind, files, ctx)
    notes = [f"DeepSeek 帮你认的（¥{cny:.3f}）：出之前看一眼每一条对不对"]
    if kind == "tts":
        ok = {n.lower() for n, _ in vs}
        if body.get("engine") == "cloud":
            from . import tts_cloud
            ok |= {str(v["id"]).lower() for v in tts_cloud.voices()}
        for it in j["items"]:
            v = str(it.get("voice") or (j.get("roles") or {}).get(it.get("role") or "", "") or "").strip()
            if v and v.lower() not in ok:
                notes.append(f"「{it.get('file')}」它配的音色「{v}」不在能用的里，先用页面上选的")
                v = ""
            it["voice"] = v
        j["roles"] = {}
        md = to_tts_md(j, lines)
    elif kind == "img":
        md = to_img_md(j, lines)
    else:
        md = to_bgm_md(j)
    notes += [str(x)[:200] for x in (j.get("notes") or []) if str(x).strip()][:8]
    return md, ", ".join(str(f.get("name") or "") for f in files)[:80], notes
