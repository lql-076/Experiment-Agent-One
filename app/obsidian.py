r"""Obsidian 笔记：读你的笔记回答问题、往「Agent 收件箱」写东西、每天帮你整理、记忆搬进库里。

库在 设置 › Obsidian 笔记 里加（obsVaults），每个库：名字、路径、只读、私人文件夹。

规矩（写死在这里，界面上改不了）：
- **只读的库一个字都不写。E 盘的库一律只读**（作者的铁律）。索引、状态全存在 data\agent.db，不往任何库里放文件。
- 能写的库也只写「Agent 收件箱」（obsInbox）这一个文件夹，**不改你自己的笔记**；同名文件不覆盖，另起名字。
- **私人笔记只给本地小脑**：在私人文件夹里，或者顶部属性写了 私人: true / private: true，或者带 #私人 / #隐私 标签。
  它们不发给 DeepSeek、不给 DeepSeek 的查笔记工具、不进训练数据。
- 跳过 .obsidian、.trash、.git 这些点开头的文件夹，只读 .md；记忆文件夹搬进库以后，那个子文件夹不算笔记（它单独当记忆索引）。

怎么找：笔记切成小段（按标题和段落，每段不超过 500 字），用本地嵌入模型算向量；嵌入模型没开时按字面重合找。
后台每分钟看一眼文件有没有改过（只比修改时间和大小），改了的笔记重新切段、算向量。
"""
import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from . import db, paths, safety, settings
from .models import M

RO_DRIVES = ("E:",)                    # 作者的铁律：E 盘只读
SKIP_DIRS = {"node_modules", "__pycache__"}
PRIV_TAGS = ("私人", "隐私", "private")
STOP = {"你的", "怎么", "什么", "一下", "可以", "我的", "现在", "一个", "这个", "那个", "是什", "么是", "里写", "写的", "笔记", "记里", "按笔", "里的"}
NOTE_INSTRUCT = "Given a user message, retrieve passages from the user's personal notes that help answer it"
MAX_PIECE = 500


# ---------------- 库的配置 ----------------
def _ro_drive(path: str) -> bool:
    p = str(path or "").strip().replace("/", "\\").upper()
    return any(p.startswith(d) for d in RO_DRIVES)


def clean_vaults(lst) -> list:
    """界面传来的库列表：只留认识的字段；E 盘强制只读；私人文件夹统一成 a/b 的写法。"""
    out, seen = [], set()
    for i, v in enumerate(lst or []):
        if not isinstance(v, dict):
            continue
        path = str(v.get("path") or "").strip().strip('"')
        if not path:
            continue
        vid = re.sub(r"[^\w-]", "", str(v.get("id") or "")) or f"v{i + 1}"
        while vid in seen:
            vid += "x"
        seen.add(vid)
        priv = v.get("private") or []
        if isinstance(priv, str):
            priv = re.split(r"[,，、\n]+", priv)
        priv = sorted({p.strip().strip("/\\").replace("\\", "/") for p in priv if str(p).strip().strip("/\\")})
        out.append({"id": vid, "name": str(v.get("name") or Path(path).name or vid)[:30], "path": path,
                    "ro": bool(v.get("ro")) or _ro_drive(path), "private": priv})
    return out


def vaults() -> list:
    return clean_vaults(settings.S.get("obsVaults") or [])


def vault(vid):
    return next((v for v in vaults() if v["id"] == vid), None)


def on() -> bool:
    return bool(settings.S.get("obsOn", True)) and bool(vaults())


def writable():
    """能写的第一个库（收件箱放这里）。没有就返回 None。"""
    if not settings.S.get("obsWrite", True):
        return None
    return next((v for v in vaults() if not v["ro"] and Path(v["path"]).is_dir()), None)


def inbox_name() -> str:
    n = str(settings.S.get("obsInbox") or "Agent 收件箱").strip().strip("/\\")
    return re.sub(r'[<>:"|?*]', "", n) or "Agent 收件箱"


# ---------------- 读文件 ----------------
def _memory_root():
    try:
        from . import memory
        return memory.root().resolve()
    except Exception:
        return None


def _scan(v):
    """库里所有 .md：(相对路径 a/b.md, 绝对路径, 修改时间, 大小)。"""
    root = Path(v["path"])
    if not root.is_dir():
        return []
    mem = _memory_root()
    out = []
    for dp, dns, fns in os.walk(root):
        d = Path(dp)
        if mem is not None and (d.resolve() == mem or mem in d.resolve().parents):
            dns[:] = []
            continue
        dns[:] = [n for n in dns if not n.startswith(".") and n not in SKIP_DIRS]
        for fn in fns:
            if not fn.lower().endswith(".md") or fn.startswith("."):
                continue
            p = d / fn
            try:
                st = p.stat()
            except OSError:
                continue
            out.append((p.relative_to(root).as_posix(), p, st.st_mtime, st.st_size))
    return out


FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
LINK = re.compile(r"\[\[([^\]|#\n]+)(?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\]")
TAG = re.compile(r"(?:^|\s)#([\w一-鿿/-]+)")


def parse(text: str):
    """→ (正文, 顶部属性 dict, 标签 set, 链接到的笔记名 set)"""
    fm, body = {}, text or ""
    m = FM.match(body)
    if m:
        body = body[m.end():]
        key = None
        for line in m.group(1).splitlines():
            if re.match(r"^\s+-\s+", line) and key:                     # tags:\n  - a
                fm.setdefault(key, [])
                if isinstance(fm[key], list):
                    fm[key].append(line.split("-", 1)[1].strip().strip("'\""))
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key, val = key.strip(), val.strip().strip("'\"")
                if val.startswith("[") and val.endswith("]"):
                    val = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
                fm[key] = val if val != "" else []
    tags = {t.lower() for t in TAG.findall(body)}
    ft = fm.get("tags") or fm.get("tag") or []
    if isinstance(ft, str):
        ft = re.split(r"[,\s]+", ft)
    tags |= {str(t).lstrip("#").lower() for t in ft if t}
    links = {x.strip() for x in LINK.findall(body)}
    return body, fm, tags, links


def _truthy(x) -> bool:
    return str(x).strip().lower() in ("true", "yes", "1", "是", "对")


def fm_private(fm, tags) -> bool:
    if any(_truthy(fm.get(k, "")) for k in ("私人", "隐私", "private")):
        return True
    return any(t in tags for t in PRIV_TAGS)


def in_private_folder(v, rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel == p or rel.startswith(p + "/") for p in v["private"])


def chunk(body: str):
    """按标题和段落切成小段：[(所在标题, 文字)]，每段不超过 500 字。"""
    out, heading, buf = [], "", []

    def flush():
        t = "\n".join(buf).strip()
        buf.clear()
        while t:
            out.append((heading, t[:MAX_PIECE]))
            t = t[MAX_PIECE:].strip()

    for line in (body or "").splitlines():
        h = re.match(r"^(#{1,6})\s+(.+)$", line)
        if h:
            flush()
            heading = h.group(2).strip()[:60]
            continue
        if not line.strip():
            if sum(len(x) for x in buf) >= 120:
                flush()
            continue
        buf.append(line)
        if sum(len(x) for x in buf) >= MAX_PIECE:
            flush()
    flush()
    return [(hd, t) for hd, t in out if len(t) >= 6]


# ---------------- 索引 ----------------
_busy = {"on": False}
DIRTY = {"on": True}          # 设置里改了库：后台照看下一轮马上重新扫一遍


def _changed(ch):
    if any(k in ch for k in ("obsVaults", "obsOn", "obsInbox", "memDir")):
        DIRTY["on"] = True


settings.on_change(_changed)


async def refresh(embed=True) -> dict:
    """看每个库有没有改过的笔记：改了的重新切段，删了的去掉，然后给还没向量的段落算向量（每批 64 段）。"""
    if _busy["on"]:
        return {"busy": True}
    _busy["on"] = True
    try:
        stats = {"changed": 0, "removed": 0, "embedded": 0}
        vs = vaults() if settings.S.get("obsOn", True) else []
        ids = {v["id"] for v in vs}
        for r in db.q("SELECT DISTINCT vault FROM notes"):
            if r["vault"] not in ids:                       # 库被删掉了
                db.run("DELETE FROM notes WHERE vault=?", (r["vault"],))
                db.run("DELETE FROM note_chunks WHERE vault=?", (r["vault"],))
        for v in vs:
            have = {(r["path"]): r for r in db.q("SELECT path,mtime,size FROM notes WHERE vault=?", (v["id"],))}
            seen = set()
            for rel, p, mt, sz in _scan(v):
                seen.add(rel)
                h = have.get(rel)
                if h and abs((h["mtime"] or 0) - mt) < 1e-3 and h["size"] == sz:
                    continue
                try:
                    text = p.read_text("utf-8", errors="replace")
                except OSError:
                    continue
                body, fm, tags, links = parse(text)
                fp = int(fm_private(fm, tags))
                priv = int(fp or in_private_folder(v, rel))
                db.run("INSERT OR REPLACE INTO notes(vault,path,mtime,size,title,fmpriv,private,links) VALUES(?,?,?,?,?,?,?,?)",
                       (v["id"], rel, mt, sz, Path(rel).stem, fp, priv, json.dumps(sorted(links), ensure_ascii=False)))
                db.run("DELETE FROM note_chunks WHERE vault=? AND path=?", (v["id"], rel))
                for hd, t in chunk(body):
                    hsh = hashlib.sha1(f"{v['id']}|{rel}|{hd}|{t}".encode()).hexdigest()
                    db.run("INSERT OR REPLACE INTO note_chunks(hash,vault,path,heading,text,private,vec) VALUES(?,?,?,?,?,?,NULL)",
                           (hsh, v["id"], rel, hd, t, priv))
                stats["changed"] += 1
            for rel in set(have) - seen:
                db.run("DELETE FROM notes WHERE vault=? AND path=?", (v["id"], rel))
                db.run("DELETE FROM note_chunks WHERE vault=? AND path=?", (v["id"], rel))
                stats["removed"] += 1
            # 私人文件夹在设置里改了：按现在的设置重新标一遍（不用重新切段）
            for r in db.q("SELECT path,fmpriv,private FROM notes WHERE vault=?", (v["id"],)):
                want = int(bool(r["fmpriv"]) or in_private_folder(v, r["path"]))
                if want != r["private"]:
                    db.run("UPDATE notes SET private=? WHERE vault=? AND path=?", (want, v["id"], r["path"]))
                    db.run("UPDATE note_chunks SET private=? WHERE vault=? AND path=?", (want, v["id"], r["path"]))
        if embed:
            stats["embedded"] = await _embed_pending()
        db.kv_set("obs_scan", {"ts": time.time(), **stats})
        return stats
    finally:
        _busy["on"] = False


async def _embed_pending(limit=2048) -> int:
    rows = db.q("SELECT hash,heading,text FROM note_chunks WHERE vec IS NULL LIMIT ?", (limit,))
    done = 0
    for i in range(0, len(rows), 64):
        part = rows[i:i + 64]
        vecs = await M.embed([(r["heading"] + "：" if r["heading"] else "") + r["text"] for r in part], instruct=False)
        if not vecs:
            break
        for r, vv in zip(part, vecs):
            db.run("UPDATE note_chunks SET vec=? WHERE hash=?", (np.asarray(vv, dtype=np.float32).tobytes(), r["hash"]))
        done += len(part)
    return done


async def reindex() -> dict:
    db.run("DELETE FROM notes")
    db.run("DELETE FROM note_chunks")
    return await refresh()


# ---------------- 找 ----------------
def _vname(vid):
    v = vault(vid)
    return v["name"] if v else vid


def _hit(r, sim):
    return {"vault": r["vault"], "vname": _vname(r["vault"]), "path": r["path"], "title": Path(r["path"]).stem,
            "heading": r["heading"], "text": r["text"], "private": bool(r["private"]), "sim": float(sim)}


async def search(qvec=None, text="", k=4, allow_private=True, floor=0.42):
    """找和这句话最相关的几段笔记。allow_private=False 时私人笔记一段都不给。
    嵌入模型没开（qvec 是 None）或者还没算向量时，按两个字两个字的重合找。"""
    if not on() or not settings.S.get("obsRead", True):
        return []
    where = "" if allow_private else " AND private=0"
    out = []
    if qvec is not None:
        rows = db.q("SELECT vault,path,heading,text,private,vec FROM note_chunks WHERE vec IS NOT NULL" + where)
        if rows:
            mat = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
            if mat.shape[1] == len(qvec):
                sims = mat @ np.asarray(qvec, dtype=np.float32)
                for i in np.argsort(-sims)[: k * 3]:
                    if sims[i] < floor:
                        break
                    out.append(_hit(rows[i], sims[i]))
                    if len(out) >= k:
                        break
                if out:
                    return out
    # 没有向量、或者向量没找到够像的：按两个字两个字的重合找（标题也算）
    grams = {text[i:i + 2] for i in range(len(text or "") - 1)} - STOP
    grams = {g for g in grams if not re.search(r"[\s，。？！、：；,.?!:;]", g)}
    if not grams:
        return []
    rows = db.q("SELECT vault,path,heading,text,private FROM note_chunks WHERE 1=1" + where)
    scored = sorted(((sum(g in (Path(r["path"]).stem + r["heading"] + r["text"]) for g in grams), r) for r in rows), key=lambda x: -x[0])
    need = 2 if len(grams) <= 10 else 3
    return [_hit(r, n / max(1, len(grams))) for n, r in scored[:k] if n >= need]


def note_path(vid, rel) -> Path:
    v = vault(vid)
    if not v:
        raise ValueError("没有这个库")
    root = Path(v["path"]).resolve()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise PermissionError("只能读库里的笔记")
    return p


def read_note(ref: str, allow_private=False, limit=12000) -> str:
    """读一整篇笔记：ref 是「库名/路径」或者只写笔记名。私人笔记在 allow_private=False 时不给。"""
    ref = (ref or "").strip().strip("《》[]")
    rows = db.q("SELECT vault,path,private FROM notes")
    hit = None
    for r in rows:
        full = f"{_vname(r['vault'])}/{r['path']}"
        if ref in (full, r["path"], r["path"][:-3], Path(r["path"]).stem):
            hit = r
            break
    if not hit:
        return "没找到这篇笔记（写「库名/路径」或者笔记名）。"
    if hit["private"] and not allow_private:
        return "这是私人笔记，只给本地小脑看，不发出本机。"
    try:
        body, _, _, _ = parse(note_path(hit["vault"], hit["path"]).read_text("utf-8", errors="replace"))
    except Exception as e:
        return f"读不了：{e}"
    return f"《{Path(hit['path']).stem}》（{_vname(hit['vault'])}/{hit['path']}）\n\n{body[:limit]}"


TOOLS = [
    {"type": "function", "function": {
        "name": "search_notes",
        "description": "在用户自己的 Obsidian 笔记里找相关段落（他的小说设定、人物、大纲、灵感、收件箱……）。问到他写过、记过的东西时先用它。返回笔记名、路径和段落。",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "要找什么，一句话或几个关键词"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read_note",
        "description": "读一整篇笔记。search_notes 的段落不够时用，ref 填它给的「库名/路径」。",
        "parameters": {"type": "object", "properties": {"ref": {"type": "string", "description": "库名/路径，比如 小说库/人物/主角.md"}},
                       "required": ["ref"]}}},
]


def tools_on() -> bool:
    return on() and settings.S.get("obsRead", True) and bool(db.one("SELECT 1 x FROM notes WHERE private=0 LIMIT 1"))


def fmt_hits(hits) -> str:
    if not hits:
        return "笔记里没找到相关的内容。"
    return "\n\n".join(f"〔{h['vname']}/{h['path']}" + (f" · {h['heading']}" if h["heading"] else "") + f"〕\n{h['text']}" for h in hits)


async def tool_call(name, args, qvec_fn):
    """DeepSeek 调的两个工具。只给非私人的笔记。"""
    if name == "search_notes":
        q = str(args.get("query") or "")[:200]
        qv = await qvec_fn(q)
        hits = await search(qv, q, k=5, allow_private=False, floor=0.35)
        return fmt_hits(hits), hits
    if name == "read_note":
        return read_note(str(args.get("ref") or ""), allow_private=False), []
    return f"没有这个工具：{name}", []


def titles(hits) -> str:
    return "、".join(dict.fromkeys(f"《{h['title']}》" for h in hits))


# ---------------- 写（只写收件箱） ----------------
def _safe_name(s: str) -> str:
    s = re.sub(r'[\\/<>:"|?*\n\r\t#^\[\]]', " ", s or "").strip()
    return re.sub(r"\s+", " ", s)[:40] or "笔记"


def inbox_path(sub: str, name: str) -> Path:
    v = writable()
    if not v:
        raise PermissionError("没有能写的库（库都是只读的，或者 设置 › Obsidian 笔记 里关掉了「往库里写」）")
    if v["ro"] or _ro_drive(v["path"]):
        raise PermissionError("这个库是只读的，一个字都不写")
    root = Path(v["path"]).resolve()
    box = (root / inbox_name()).resolve()
    p = (box / sub / name).resolve() if sub else (box / name).resolve()
    if box != p and box not in p.parents:
        raise PermissionError("只往「Agent 收件箱」里写")
    return p


def _do_write(sub, name, content, why, overwrite=False) -> str:
    p = inbox_path(sub, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not overwrite:
        stem, n = p.stem, 2
        while p.exists():
            p = p.with_name(f"{stem} ({n}).md")
            n += 1
    p.write_text(content, "utf-8")
    v = writable()
    rel = p.relative_to(Path(v["path"]).resolve()).as_posix()
    safety.record_change("note.write", f"写了笔记「{rel}」", why, f"note:{v['id']}:{rel}")
    return rel


async def write(sub: str, title: str, content: str, why: str, overwrite=False):
    """往 Agent 收件箱写一篇笔记（先斩后奏，写进报告，能撤销）。返回 (写了没有, 相对路径或等你决定的编号)。"""
    name = _safe_name(title) + ".md"
    inbox_path(sub, name)                                   # 先检查能不能写，不能就直接报错

    async def run():
        return _do_write(sub, name, content, why, overwrite)
    return await safety.request("note.write", f"往 Obsidian 写「{inbox_name()}/{sub + '/' if sub else ''}{name}」", why,
                                {"sub": sub, "name": name, "content": content, "why": why, "overwrite": overwrite}, run)


@safety.handler("note.write")
async def _approved(payload):
    return "已写入 " + _do_write(payload.get("sub", ""), payload["name"], payload["content"], payload.get("why", "你同意的"), payload.get("overwrite", False))


def undo(commit_id: str) -> str:
    """撤销 Agent 写的笔记：不删，挪进收件箱里的「已撤销」文件夹。"""
    _, vid, rel = commit_id.split(":", 2)
    v = vault(vid)
    if not v or v["ro"]:
        return "找不到这个库，没法撤销"
    root = Path(v["path"]).resolve()
    p = (root / rel).resolve()
    box = (root / inbox_name()).resolve()
    if box not in p.parents or not p.exists():
        return "这篇笔记已经不在了"
    dest = box / "已撤销" / p.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 2
    while dest.exists():
        dest = dest.with_name(f"{p.stem} ({n}).md")
        n += 1
    p.replace(dest)
    return f"已撤销：挪进了「{inbox_name()}/已撤销」"


SAVE = re.compile(r"^(请)?(帮我)?(把)?(?P<what>这个|这些|这段|刚才的?(回答|回复|内容|话)?|你刚才说的|上面的?|下面的?)?"
                  r"(存|记|写|放|保存)(一下)?(到|进|在)(我的)?\s*(obsidian|Obsidian|OB|ob|笔记|笔记库|库|收件箱)(里|中)?[：:，,。 ]*(?P<body>.*)$", re.S)


def save_command(text: str):
    """「存到笔记：……」「把刚才的回答存到 Obsidian」→ (要存的话, 是不是要存上一条回复)。不是就返回 None。"""
    m = SAVE.match((text or "").strip())
    if not m:
        return None
    body = (m.group("body") or "").strip()
    what = m.group("what") or ""
    return body, bool(not body or re.search(r"刚才|上面|你刚才", what))


def note_text(title: str, body: str, src: str) -> str:
    return (f"---\n来源: Agent（{src}）\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n---\n\n# {title}\n\n{body.strip()}\n")


# ---------------- 记忆搬进库里 ----------------
MEM_FOLDER = "Agent 记忆"


def move_memory(vid: str) -> str:
    """把 Agent 的记忆文件夹复制进这个库的「Agent 记忆」子文件夹，以后记忆就在库里（Obsidian 里能看、能改）。
    原来的文件夹不删，改名成「…已搬走-日期」留着。"""
    from . import memory
    v = vault(vid)
    if not v:
        raise ValueError("没有这个库")
    if v["ro"] or _ro_drive(v["path"]):
        raise PermissionError("只读的库不能放记忆")
    root = Path(v["path"])
    if not root.is_dir():
        raise FileNotFoundError(f"库的文件夹不在：{root}")
    old = memory.root().resolve()
    dest = (root / MEM_FOLDER).resolve()
    if old == dest:
        return "记忆已经在这个库里了"
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"「{MEM_FOLDER}」文件夹已经有东西了，先挪开再搬")
    shutil.copytree(old, dest, dirs_exist_ok=True)
    settings.update({"memDir": str(dest)})
    memory.init()
    moved = ""
    if old == paths.MEMORY.resolve():
        try:
            tgt = old.with_name(f"{old.name}.已搬走-{datetime.now().strftime('%Y%m%d')}")
            old.rename(tgt)
            moved = f"，原来的文件夹改名成「{tgt.name}」留着"
        except OSError:
            moved = "，原来的文件夹还在（改名没成功，可以自己删）"
    safety.record_change("memory.move", f"记忆搬进了 Obsidian 库「{v['name']}/{MEM_FOLDER}」", "你在设置里点的", "")
    return f"搬好了：记忆现在在「{v['name']}/{MEM_FOLDER}」{moved}"


# ---------------- 每天整理（只列出来，不改你的笔记） ----------------
SKIP_TITLES = {"readme", "index", "首页", "目录", "说明", "模板"}


def link_suggestions(limit=30):
    """笔记 A 的正文里提到了笔记 B 的名字，却没写 [[B]]：建议加链接。"""
    notes = db.q("SELECT vault,path,title,links,private FROM notes")
    box = inbox_name() + "/"
    names = {}
    for n in notes:
        t = n["title"]
        if len(t) >= 2 and t.lower() not in SKIP_TITLES and not n["path"].startswith(box):
            names.setdefault(t, n)
    out = []
    for n in notes:
        if n["path"].startswith(box):
            continue
        linked = set(json.loads(n["links"] or "[]"))
        txt = " ".join(r["text"] for r in db.q("SELECT text FROM note_chunks WHERE vault=? AND path=?", (n["vault"], n["path"])))
        for t, target in names.items():
            if t == n["title"] or t in linked or Path(target["path"]).with_suffix("").as_posix() in linked:
                continue
            if t in txt:
                out.append({"from": n["title"], "from_path": f"{_vname(n['vault'])}/{n['path']}", "to": t, "private": bool(n["private"] or target["private"])})
                if len(out) >= limit:
                    return out
    return out


def _pairs(limit=12, lo=0.80, hi=0.985):
    """不同笔记里讲同一件事的段落（向量很像），拿去查有没有前后矛盾。改得最近的笔记优先。"""
    box = inbox_name() + "/"
    rows = db.q("SELECT c.vault,c.path,c.heading,c.text,c.private,c.vec,n.mtime FROM note_chunks c JOIN notes n "
                "ON n.vault=c.vault AND n.path=c.path WHERE c.vec IS NOT NULL")
    rows = [r for r in rows if not r["path"].startswith(box)]
    if len(rows) < 2:
        return []
    mat = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
    sims = mat @ mat.T
    order = np.argsort([-r["mtime"] for r in rows])[:200]
    out, used = [], set()
    for i in order:
        for j in np.argsort(-sims[i]):
            if j == i or (rows[j]["vault"], rows[j]["path"]) == (rows[i]["vault"], rows[i]["path"]):
                continue
            s = sims[i][j]
            if s < lo:
                break
            if s > hi or (min(i, j), max(i, j)) in used:
                continue
            used.add((min(i, j), max(i, j)))
            out.append((rows[i], rows[j], float(s)))
            break
        if len(out) >= limit:
            break
    return out


async def check_conflicts(limit=12):
    """像的两段交给模型看有没有矛盾：两段都不是私人的交 DeepSeek（花钱很少）；有私人的交本地小脑（本地没开就跳过）。"""
    from . import deepseek
    found, checked = [], 0
    for a, b, s in _pairs(limit):
        q = ("下面是同一个人笔记里的两段（可能是小说设定）。它们说的事有没有前后矛盾（数字、等级、关系、时间、名字对不上）？"
             "只输出 JSON：{\"conflict\": true 或 false, \"why\": \"一句话，没矛盾就留空\"}\n\n"
             f"甲〔{a['path']}〕：{a['text'][:600]}\n\n乙〔{b['path']}〕：{b['text'][:600]}")
        try:
            if a["private"] or b["private"]:
                if not M.ai_ready():
                    continue
                out = await M.chat([{"role": "user", "content": q}], max_new_tokens=120)
                txt = out["text"]
            else:
                out = await deepseek.chat([{"role": "user", "content": q}], json_mode=True, purpose="obs_tidy", max_tokens=200)
                txt = out["text"]
            m = re.search(r"\{.*\}", txt, re.S)
            j = json.loads(m.group(0)) if m else {}
        except (deepseek.NoKey, deepseek.NoBalance):
            break
        except Exception:
            continue
        checked += 1
        if j.get("conflict"):
            found.append({"a": f"{_vname(a['vault'])}/{a['path']}", "b": f"{_vname(b['vault'])}/{b['path']}",
                          "why": str(j.get("why") or "")[:200], "private": bool(a["private"] or b["private"])})
    return found, checked


def _today_chats():
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows = db.q("SELECT id,ts,text,reply,ui_to,private,src FROM events WHERE ts>=? AND src IN ('ui','qq') ORDER BY id", (start,))
    return [r for r in rows if not r["private"]], sum(1 for r in rows if r["private"])


async def tidy() -> dict:
    """每日整理：今天聊了什么 + 建议加的链接 + 可能矛盾的地方，写成一篇笔记放进收件箱「每日」文件夹。不改你的任何笔记。"""
    if not on():
        return {"skipped": "还没有接 Obsidian 库"}
    await refresh()
    links = link_suggestions()
    conflicts, checked = [], 0
    if settings.S.get("obsTidy", True):
        conflicts, checked = await check_conflicts()
    chats, priv_n = _today_chats()
    day = datetime.now().strftime("%Y-%m-%d")
    lines = [f"# {day} 每日整理", "", "Agent 写的，只是建议，你的笔记一个字没改。", ""]
    lines += ["## 今天聊了什么", ""]
    names = {"local": "本地小脑", "neu": "新类别", "ds": "DeepSeek", "cl": "更强的模型"}
    for r in chats[:40]:
        lines.append(f"- {time.strftime('%H:%M', time.localtime(r['ts']))} {r['text'][:60]} → {names.get(r['ui_to'], r['ui_to'])}："
                     f"{(r['reply'] or '').replace(chr(10), ' ')[:80]}")
    if not chats:
        lines.append("- （今天没有）")
    if priv_n:
        lines.append(f"- 另外 {priv_n} 条涉及隐私，不写进笔记。")
    lines += ["", "## 可能前后矛盾的地方", ""]
    lines += [f"- [[{c['a'].split('/', 1)[1][:-3]}]] 和 [[{c['b'].split('/', 1)[1][:-3]}]]：{c['why']}" for c in conflicts] or [f"- 没发现（查了 {checked} 对相似的段落）"]
    lines += ["", "## 可以加的链接", ""]
    lines += [f"- 《{x['from']}》里提到了「{x['to']}」，可以写成 [[{x['to']}]]" for x in links] or ["- 没有"]
    content = "\n".join(lines) + "\n"
    res = {"links": len(links), "conflicts": len(conflicts), "checked": checked, "chats": len(chats), "written": ""}
    db.kv_set("obs_tidy_last", {"ts": time.time(), "links": links[:30], "conflicts": conflicts, "checked": checked})
    if writable():
        done, info = await write("每日", f"{day} 每日整理", content, "每日差事：今天聊了什么、整理建议", overwrite=True)
        res["written"] = info if done else f"等你决定 #{info}"
    return res


# ---------------- 给界面和 Agent 状态 ----------------
def status() -> dict:
    vs = []
    for v in vaults():
        n = db.one("SELECT COUNT(*) n, COALESCE(SUM(private),0) p FROM notes WHERE vault=?", (v["id"],))
        c = db.one("SELECT COUNT(*) n, COALESCE(SUM(vec IS NULL),0) w FROM note_chunks WHERE vault=?", (v["id"],))
        ok = Path(v["path"]).is_dir()
        mem = _memory_root()
        folders = sorted(d.name for d in Path(v["path"]).iterdir() if d.is_dir() and not d.name.startswith(".")
                         and (mem is None or d.resolve() != mem)) if ok else []
        vs.append({**v, "exists": ok, "folders": folders[:60], "notes": n["n"], "privNotes": int(n["p"]), "chunks": c["n"], "waiting": int(c["w"]),
                   "roDrive": _ro_drive(v["path"])})
    w = writable()
    from . import memory
    mem = memory.root().resolve()
    mem_in = next((v["name"] for v in vaults() if Path(v["path"]).is_dir() and Path(v["path"]).resolve() in mem.parents), "")
    return {"on": bool(settings.S.get("obsOn", True)), "vaults": vs, "inbox": inbox_name(), "inboxVault": w["name"] if w else "",
            "memIn": mem_in, "memDir": paths.show(mem), "scan": db.kv_get("obs_scan") or {}, "tidy": db.kv_get("obs_tidy_last") or {},
            "embedOn": bool(M._health and M._health.get("embed_loaded"))}


def check_path(path: str) -> dict:
    """界面上填了库的路径，先看看对不对：在不在、是不是 Obsidian 库、有多少篇、第一层有哪些文件夹（好选私人文件夹）。"""
    p = Path(str(path or "").strip().strip('"'))
    if not str(p) or not p.is_dir():
        return {"ok": False, "msg": "这个文件夹不在（路径从资源管理器地址栏复制过来）", "ro": _ro_drive(str(p))}
    v = {"id": "chk", "name": p.name, "path": str(p), "ro": True, "private": []}
    md = _scan(v)
    folders = sorted({r.split("/", 1)[0] for r, *_ in md if "/" in r})
    return {"ok": True, "obsidian": (p / ".obsidian").is_dir(), "notes": len(md), "folders": folders[:60], "ro": _ro_drive(str(p)),
            "msg": ("是 Obsidian 库" if (p / ".obsidian").is_dir() else "不是 Obsidian 库（没有 .obsidian），也能当普通笔记文件夹用") + f" · {len(md)} 篇笔记"}
