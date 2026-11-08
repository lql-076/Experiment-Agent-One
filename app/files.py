"""读本地文件（v1.8.17）：只读你在 设置 › 记忆与文件 ›「能读的文件夹」里加的文件夹；v2.1 起 Agent 自己的工作文件夹（app/workspace.py）也能读。

- 只读：列目录、搜文件（文件名 + 文本内容）、读文件（文本、Word、图片）。不写、不删、不改、不运行。
- 每个文件夹一个开关「能发给 DeepSeek」：关着的只给本地小脑看（程序读出来塞进提示词），DeepSeek 的工具看不到它。
- 加文件夹 = 给 agent 加新权限，只能你在界面上点（安全线：给自己加新工具或新权限必须由你决定，模型自己加不了），记进动作日志。
- 路径都先 resolve（快捷方式、符号链接走到真的位置）再判断在不在允许的文件夹里，用 .. 绕不出去。
- 不管加了哪个文件夹，Agent 自己的 data（设置、密钥、数据库）和看着像密钥的文件（.env、*.key、id_rsa……）一律不读。
- 消息里贴了路径（E:\\笔记仓库\\xx.md）：程序直接读，不靠模型（mentioned / attach）。
"""
import base64
import os
import re
import time
from pathlib import Path

from . import db, paths, safety, settings

TEXT_EXT = {".md", ".markdown", ".txt", ".text", ".json", ".jsonl", ".csv", ".tsv", ".log", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml",
            ".xml", ".html", ".htm", ".css", ".js", ".ts", ".py", ".bat", ".cmd", ".ps1", ".sh", ".srt", ".vtt", ".ass", ".canvas", ".rtf"}
IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
DOC_EXT = {".docx"}
SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode"}
SECRET_RE = re.compile(r"^(\.env(\..*)?|secrets?(\..*)?|.*\.(pem|key|pfx|p12|kdbx|ppk)|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|credentials(\..*)?)$", re.I)
MAX_CHARS = 20000            # 一次最多读多少字（后面的用 offset 接着读）
MAX_TEXT_BYTES = 8 << 20     # 文本文件只读前 8MB
MAX_IMG = 10 << 20           # 图片一张最多 10MB
MAX_LIST = 200
MAX_HITS = 30
SCAN_FILES = 6000            # 搜一次最多看多少个文件
SCAN_SEC = 6.0


class Denied(Exception):
    """不在能读的文件夹里，或者是不让读的文件。"""


# ---------------- 能读的文件夹 ----------------
def clean(v):
    """设置里的 readDirs：[{path, cloud}]，去掉不像样的。"""
    out, seen = [], set()
    for x in v if isinstance(v, list) else []:
        if isinstance(x, str):
            x = {"path": x, "cloud": True}
        if not isinstance(x, dict) or not str(x.get("path") or "").strip():
            continue
        p = str(x["path"]).strip().strip('"')
        k = os.path.normcase(p)
        if k in seen:
            continue
        seen.add(k)
        out.append({"path": p, "cloud": bool(x.get("cloud", True))})
    return out[:30]


def dirs(cloud_only=False):
    out = clean(settings.S.get("readDirs"))
    return [d for d in out if d["cloud"]] if cloud_only else out


def _real(p) -> Path:
    return Path(os.path.expanduser(str(p).strip().strip('"'))).resolve(strict=False)


def _inside(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def _ws():
    """Agent 自己的工作文件夹（v2.1，app/workspace.py）：也能读，算「能发给 DeepSeek」的。"""
    try:
        from . import workspace
        return workspace.root_entry()
    except Exception:
        return None


def roots(cloud=False):
    """能读的文件夹 + 工作文件夹。"""
    w = _ws()
    return dirs(cloud) + ([w] if w else [])


def owner(p, cloud=False):
    """这个路径属于哪个能读的文件夹（最长的那个）；不属于返回 None。cloud=True 只看「能发给 DeepSeek」的。工作文件夹也算。"""
    rp = _real(p)
    best = None
    for d in roots(cloud):
        root = _real(d["path"])
        if _inside(rp, root) and (best is None or len(str(root)) > len(str(_real(best["path"])))):
            best = d
    return best


def _blocked(rp: Path) -> str:
    if _inside(rp, paths.DATA.resolve()):
        return "这是 Agent 自己的数据（设置、密钥、数据库），不读"
    if SECRET_RE.match(rp.name):
        return "看着像密钥、密码库这类文件，不读"
    return ""


def check(p, cloud=False) -> Path:
    """能不能读：在能读的文件夹里、不是密钥文件。返回真实路径，不能读抛 Denied。"""
    if not str(p or "").strip():
        raise Denied("没给路径")
    rp = _real(p)
    if not owner(rp, cloud):
        if cloud and owner(rp, False):
            raise Denied(f"「{p}」所在的文件夹设成了只给本地小脑看，不发给 DeepSeek")
        raise Denied(f"「{p}」不在能读的文件夹里（设置 › 记忆与文件 › 能读的文件夹）")
    why = _blocked(rp)
    if why:
        raise Denied(why)
    return rp


def add_dir(path, cloud=True, who="user"):
    """加一个能读的文件夹（只读）。只有界面上你点的才会走到这里。"""
    p = str(path or "").strip().strip('"')
    if not p:
        raise ValueError("填一个文件夹的路径")
    rp = _real(p)
    if not rp.exists():
        raise ValueError(f"找不到这个文件夹：{p}")
    if not rp.is_dir():
        rp = rp.parent
    if rp.parent == rp:
        raise ValueError("整个盘太大了，选一个具体的文件夹（比如 E:\\笔记仓库）")
    if _inside(rp, paths.DATA.resolve()):
        raise ValueError("这是 Agent 自己的数据文件夹（设置、密钥、数据库），不能加")
    cur = dirs()
    if any(os.path.normcase(str(_real(d["path"]))) == os.path.normcase(str(rp)) for d in cur):
        return set_cloud(str(rp), cloud)
    cur.append({"path": str(rp), "cloud": bool(cloud)})
    _save(cur)
    safety.log("tool.add", {"perm": "read", "path": str(rp), "cloud": bool(cloud)}, who)
    return dirs()


def remove_dir(path):
    k = os.path.normcase(str(_real(path)))
    cur = [d for d in dirs() if os.path.normcase(str(_real(d["path"]))) != k]
    _save(cur)
    safety.log("tool.remove", {"perm": "read", "path": str(path)}, "user")
    return dirs()


def set_cloud(path, cloud):
    k = os.path.normcase(str(_real(path)))
    cur = dirs()
    for d in cur:
        if os.path.normcase(str(_real(d["path"]))) == k:
            d["cloud"] = bool(cloud)
    _save(cur)
    return dirs()


def _save(v):
    settings.S["readDirs"] = clean(v)
    settings.save()


def public():
    out = []
    for d in dirs():
        rp = _real(d["path"])
        out.append(dict(d, exists=rp.is_dir(), show=paths.show(rp)))
    return out


# ---------------- 读 ----------------
def _decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def _docx(rp: Path) -> str:
    import zipfile
    try:
        with zipfile.ZipFile(rp) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (KeyError, zipfile.BadZipFile, OSError) as e:
        raise Denied(f"这个 Word 文件打不开：{type(e).__name__}") from None
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return re.sub(r"<[^>]+>", "", xml).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')


def kind_of(rp: Path) -> str:
    ext = rp.suffix.lower()
    if ext in IMG_EXT:
        return "image"
    if ext in DOC_EXT:
        return "docx"
    if ext in TEXT_EXT or not ext:
        return "text"
    return "other"


def read(path, offset=0, cloud=False, limit=MAX_CHARS):
    """读一个文件：文本 / Word 给文字（从 offset 字开始，最多 limit 字）；图片给 data URI。"""
    rp = check(path, cloud)
    if not rp.exists():
        raise Denied(f"找不到这个文件：{path}")
    if rp.is_dir():
        raise Denied(f"「{path}」是文件夹，用 list_dir 看里面有什么")
    k = kind_of(rp)
    size = rp.stat().st_size
    if k == "image":
        if size > MAX_IMG:
            raise Denied(f"图片太大了（{size >> 20}MB，最多 10MB）")
        b = rp.read_bytes()
        return {"kind": "image", "path": str(rp), "name": rp.name, "size": size, "mime": IMG_EXT[rp.suffix.lower()],
                "uri": f"data:{IMG_EXT[rp.suffix.lower()]};base64," + base64.b64encode(b).decode()}
    if k == "other":
        raise Denied(f"「{rp.name}」不是文字文件（{rp.suffix or '没有扩展名'}），读不了；能读 .md .txt .docx、代码、表格（.csv）和图片")
    if k == "docx":
        txt = _docx(rp)
    else:
        with open(rp, "rb") as f:
            b = f.read(MAX_TEXT_BYTES)
        if b"\x00" in b[:4096]:
            raise Denied(f"「{rp.name}」看着不是文字文件，读不了")
        txt = _decode(b)
    offset = max(0, int(offset or 0))
    part = txt[offset:offset + limit]
    return {"kind": "text", "path": str(rp), "name": rp.name, "size": size, "total": len(txt), "offset": offset, "text": part,
            "more": offset + len(part) < len(txt)}


def _walk(root: Path):
    t0, n = time.time(), 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            n += 1
            if n > SCAN_FILES or time.time() - t0 > SCAN_SEC:
                return
            yield Path(dp) / fn


def list_dir(path, cloud=False):
    rp = check(path, cloud)
    if not rp.is_dir():
        raise Denied(f"「{path}」不是文件夹")
    items = []
    try:
        ents = sorted(rp.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError as e:
        raise Denied(f"打不开这个文件夹：{type(e).__name__}") from None
    for x in ents:
        if x.name in SKIP_DIRS or x.name.startswith(".") or _blocked(x.resolve()):
            continue
        if x.is_dir():
            try:
                cnt = sum(1 for _ in x.iterdir())
            except OSError:
                cnt = 0
            items.append(f"[文件夹] {x.name}\\（{cnt} 项）")
        else:
            st = x.stat()
            items.append(f"{x.name}（{_size(st.st_size)} · {time.strftime('%Y-%m-%d', time.localtime(st.st_mtime))}）")
        if len(items) >= MAX_LIST:
            items.append(f"……还有，只列前 {MAX_LIST} 项")
            break
    return {"path": str(rp), "text": f"{rp}\n" + ("\n".join(items) if items else "（空文件夹）"), "n": len(items)}


def find(query, path=None, cloud=False):
    """按文件名和文字内容搜（不分大小写）。没给 path 就搜所有能读的文件夹。"""
    q = str(query or "").strip()
    if not q:
        raise Denied("没给要搜的词")
    words = [w for w in re.split(r"\s+", q.lower()) if w][:5]
    rts = [check(path, cloud)] if path else [_real(d["path"]) for d in roots(cloud)]
    if not rts:
        raise Denied("还没有能读的文件夹（设置 › 记忆与文件 › 能读的文件夹）")
    hits = []
    for root in rts:
        if not root.is_dir():
            continue
        for f in _walk(root):
            if len(hits) >= MAX_HITS:
                break
            if _blocked(f.resolve()):
                continue
            name_hit = all(w in f.name.lower() for w in words)
            line = ""
            if kind_of(f) in ("text", "docx") and f.stat().st_size <= MAX_TEXT_BYTES:
                try:
                    txt = _docx(f) if kind_of(f) == "docx" else _decode(f.read_bytes())
                except (Denied, OSError):
                    txt = ""
                low = txt.lower()
                if all(w in low for w in words):
                    i = low.find(words[0])
                    line = re.sub(r"\s+", " ", txt[max(0, i - 40):i + 80]).strip()
            if name_hit or line:
                hits.append(f"{f}" + (f"\n    …{line}…" if line else "（文件名对上了）"))
    return {"query": q, "text": (f"搜「{q}」：{len(hits)} 处\n" + "\n".join(hits)) if hits else f"搜「{q}」：没找到", "n": len(hits)}


def _size(n):
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1 << 20 else f"{n / (1 << 20):.1f} MB"


# ---------------- 给 DeepSeek 的工具 ----------------
TOOLS = [
    {"type": "function", "function": {
        "name": "list_dir", "description": "列出他电脑上一个文件夹里有什么（只读）。只能看他允许的文件夹和它们的子文件夹。",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "文件夹的完整路径"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "find_files", "description": "在他允许的文件夹里按文件名和文字内容搜（不分大小写，几个词用空格隔开表示都要有）。返回文件路径和命中的那一句。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要搜的词"},
            "path": {"type": "string", "description": "只在这个文件夹里搜（可以不填，不填就搜所有允许的文件夹）"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "读一个文件：文字（.md .txt .docx、代码、表格）一次最多 2 万字，没读完用 offset 接着读；图片会附在下一条消息里给你看。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件的完整路径"},
            "offset": {"type": "integer", "description": "从第几个字开始读，默认 0"}}, "required": ["path"]}}},
]
NAMES = {"list_dir", "find_files", "read_file"}


def _tool_path(p):
    """工具里给的相对路径：按工作文件夹算（v2.1）。"""
    s = str(p or "").strip().strip('"')
    w = _ws()
    if s and w and not Path(s).is_absolute():
        try:
            from . import workspace
            return str(workspace.real(s))
        except Exception:
            return s
    return s


def hint() -> str:
    ds = dirs(True)
    if not ds:
        return ""
    return ("他允许你读他电脑上的这些文件夹（只读，不能改、不能删）：\n" + "\n".join(f"- {d['path']}" for d in ds) +
            "\n要用里面的资料：先用 find_files 搜关键词（或 list_dir 看目录），再用 read_file 读。路径写完整。"
            "回答时说清楚出自哪个文件。没找到就直说没找到，不要编。")


def run_tool(name, args):
    """执行一个文件工具（只给能发给 DeepSeek 的文件夹）。返回 (给模型的文字, 步骤 [名, 说明], 图片 dict 或 None, 读到的路径)。"""
    args = dict(args or {})
    for k in ("path",):
        if args.get(k):
            args[k] = _tool_path(args[k])
    if name == "list_dir":
        r = list_dir(args.get("path") or _tool_path("."), cloud=True)
        return r["text"], ["列目录", f"{_short(r['path'])} · {r['n']} 项"], None, None
    if name == "find_files":
        r = find(args.get("query"), args.get("path") or None, cloud=True)
        return r["text"], ["搜文件", f"「{r['query'][:30]}」· {r['n']} 处"], None, None
    if name == "read_file":
        r = read(args.get("path"), args.get("offset") or 0, cloud=True)
        if r["kind"] == "image":
            return f"图片 {r['name']}（{_size(r['size'])}）附在下一条消息里。", ["读文件", f"{_short(r['path'])} · 图片"], r, r["path"]
        more = f"\n\n（没读完：一共 {r['total']} 字，这次读到第 {r['offset'] + len(r['text'])} 字，要接着读就 offset={r['offset'] + len(r['text'])}）" if r["more"] else ""
        return (f"文件：{r['path']}\n\n{r['text']}{more}", ["读文件", f"{_short(r['path'])} · {len(r['text'])} 字" + ("（没读完）" if r["more"] else "")],
                None, r["path"])
    raise Denied(f"没有这个工具：{name}")


def _short(p):
    p = str(p)
    for d in roots():
        root = str(_real(d["path"]))
        if p.startswith(root):
            base = Path(root).name
            rest = p[len(root):].lstrip("\\/")
            return base + ("\\" + rest if rest else "")
    return p[-50:]


# ---------------- 消息里贴的路径 ----------------
PATH_RE = re.compile(r'(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\[^\\\s]') if paths.IS_WIN else re.compile(r'(?<![\w.:/])/(?=[^\s/])')
STOP = " \t。，,；;：:！!？?）)】]》>'\"“”「」"


def _exists(c):
    try:
        return Path(c).exists()
    except (OSError, ValueError):
        return False


def _probe(s):
    """s 里最长的那个真的存在的路径：只在最后一段里往回缩（路径后面紧跟着中文也认得出），不往上一级退（不存在的路径不会被当成它的上级文件夹）。"""
    s = s.rstrip(STOP)
    cut = max(s.rfind("/"), s.rfind("\\"))
    if cut == len(s) - 1:                                   # 以分隔符结尾：就是这个文件夹
        return s[:cut] if cut >= 2 and _exists(s[:cut]) else None
    for end in range(len(s), cut + 1, -1):
        c = s[:end].rstrip(STOP)
        if len(c) > cut + 1 and _exists(c):
            return c
    return None


def mentioned(text):
    """消息里贴的路径（E:\\笔记仓库\\xx.md、E:\\笔记仓库）：先按空格切开试，不存在再连上后面几个词试（路径里带空格的）。返回每个路径的情况。"""
    out, seen, pos, text = [], set(), 0, text or ""
    while len(out) < 5:
        m = PATH_RE.search(text, pos)
        if not m:
            break
        words = re.split(r"(\s+)", text[m.start():m.start() + 400].split("\n")[0])
        hit, tok = None, words[0].strip(STOP) if words else ""
        for k in range(0, min(len(words), 9), 2):              # 第一个词，再连上后面 1~4 个词
            hit = _probe("".join(words[:k + 1]))
            if hit:
                break
        p = hit or tok
        pos = m.start() + max(1, len(p))                        # 同一行里后面还有别的路径：接着往后找
        if len(p) < 3:
            continue
        key = os.path.normcase(str(_real(p)))
        if key in seen:
            continue
        seen.add(key)
        rp = _real(p)
        d = owner(rp) if hit else None
        out.append({"raw": p, "path": str(rp), "exists": hit is not None, "is_dir": bool(hit and rp.is_dir()), "allowed": bool(d and not _blocked(rp)),
                    "cloud": bool(d and d["cloud"]), "why": _blocked(rp) if hit else ""})
    return out[:5]


def attach(items, local=False):
    """把消息里贴的、能读的路径读出来：返回 (加在消息后面的文字, 图片列表, 读了哪些 [(kind, path, name, size)])。
    local=True：给本地小脑（只放前 3000 字，看不了图）。"""
    lim = 3000 if local else 12000
    parts, images, used = [], [], []
    for it in items:
        if not (it["exists"] and it["allowed"]):
            continue
        try:
            if it["is_dir"]:
                r = list_dir(it["path"])
                parts.append(f"【他贴的文件夹 {it['path']} 里有：】\n{r['text']}")
                used.append(("dir", r["path"], Path(r["path"]).name, 0))
                continue
            r = read(it["path"], 0, limit=lim)
        except Denied as e:
            parts.append(f"【{it['path']} 没读成：{e}】")
            continue
        if r["kind"] == "image":
            if local:
                parts.append(f"【他贴的是一张图片 {r['name']}，本地小脑看不了图】")
            else:
                images.append(r)
            used.append(("fimg", r["path"], r["name"], r["size"]))
            continue
        more = f"\n（只放了前 {len(r['text'])} 字，一共 {r['total']} 字" + ("；要看后面的用 read_file 接着读）" if not local else "）") if r["more"] else ""
        parts.append(f"【他贴的文件 {r['path']} 的内容：】\n{r['text']}{more}")
        used.append(("file", r["path"], r["name"], r["size"]))
    return "\n\n".join(parts), images, used


WANT_RE = re.compile(r"笔记|文件|文档|仓库|资料|档案|设定|世界观|文件夹|目录|obsidian|\.md\b|\.docx?\b|本地.{0,4}(找|查|看|读)", re.I)


def wants(text) -> bool:
    """看着像要查他电脑上的资料（本地小脑不会用工具，这类交给 DeepSeek 带着读文件的工具）。"""
    return bool(roots(True)) and bool(WANT_RE.search(text or ""))


# ---------------- 对话里发的图片、读过的文件（记在 chat_files，聊天记录里显示） ----------------
MAGIC = [(b"\x89PNG\r\n\x1a\n", "png", "image/png"), (b"\xff\xd8\xff", "jpg", "image/jpeg"), (b"GIF8", "gif", "image/gif")]
MAX_UPLOADS = 6


def _sniff(b: bytes):
    for sig, ext, mime in MAGIC:
        if b.startswith(sig):
            return ext, mime
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def save_upload(uri: str, k=0) -> dict:
    """界面上粘贴 / 选 / 拖进来的图片（data:image/...;base64,...）：认文件头，只收 PNG / JPEG / WEBP / GIF、10MB 以内，存进 data\\chat\\日期\\。"""
    m = re.match(r"data:image/[\w.+-]+;base64,(.+)$", str(uri or ""), re.S)
    if not m:
        raise ValueError("图片格式不对（要 PNG / JPEG / WEBP / GIF）")
    try:
        b = base64.b64decode(m.group(1), validate=False)
    except ValueError:
        raise ValueError("图片读不出来") from None
    if len(b) > MAX_IMG:
        raise ValueError(f"图片太大了（{len(b) >> 20}MB，最多 10MB）")
    sn = _sniff(b)
    if not sn:
        raise ValueError("只认 PNG / JPEG / WEBP / GIF 图片")
    d = paths.CHAT_FILES / time.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{time.strftime('%H%M%S')}_{int(time.time() * 1000) % 1000:03d}_{k + 1}.{sn[0]}"
    f.write_bytes(b)
    return {"path": str(f), "name": f.name, "size": len(b), "mime": sn[1]}


def uri_of(path) -> str:
    """存好的图片 → data URI（发给 DeepSeek 看）。"""
    b = Path(path).read_bytes()
    sn = _sniff(b) or ("png", "image/png")
    return f"data:{sn[1]};base64," + base64.b64encode(b).decode()


def note(event_id, kind, path, name=None, size=None):
    """记一笔：这条事件带了 / 读了哪个文件（kind：img 你发的图片、fimg 读到的图片文件、file 读的文件、dir 列的文件夹）。"""
    if not event_id:
        return
    p = Path(path)
    if size is None:
        try:
            size = p.stat().st_size if p.is_file() else 0
        except OSError:
            size = 0
    db.insert("chat_files", {"ts": time.time(), "event_id": int(event_id), "kind": kind, "name": name or p.name, "path": str(p), "size": int(size or 0)})


def of_events(ids):
    """一批事件各带了哪些文件（给界面：只给编号、种类、名字，不给完整路径以外的东西）。"""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    out = {}
    q = "SELECT id,event_id,kind,name,path,size FROM chat_files WHERE event_id IN (" + ",".join("?" * len(ids)) + ") ORDER BY id"
    for r in db.q(q, tuple(ids)):
        out.setdefault(r["event_id"], []).append({"id": r["id"], "kind": r["kind"], "name": r["name"], "path": paths.show(Path(r["path"])), "size": r["size"]})
    return out


def file_row(fid):
    """界面要看一张图：只给 data\\chat 里的（你发的）和还在能读的文件夹里的图片。"""
    r = db.one("SELECT * FROM chat_files WHERE id=?", (int(fid),))
    if not r or r["kind"] not in ("img", "fimg"):
        return None
    p = Path(r["path"])
    if r["kind"] == "img" and not _inside(p.resolve(), paths.CHAT_FILES.resolve()):
        return None
    if r["kind"] == "fimg":
        try:
            check(p)
        except Denied:
            return None
    return p if p.is_file() else None
