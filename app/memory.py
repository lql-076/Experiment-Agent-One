"""agent 自己的文件夹：记忆、技能、提示词，全是中文 Markdown，你随时能打开看、改。

memory\\
  记忆\\收件箱.md      你说"记住……"的内容先进这里，每日差事整理到对应文件
  记忆\\关于我.md      整理后的长期记忆
  技能\\               做事的方法（SKILL.md 格式），快成长就是改这里
  提示词\\人设.md      它的说话方式，可以自己改（先斩后奏，事后写进报告）
  总结\\               你从网页 Claude 带回来的总结、和 Claude 的聊天记录（只当参考资料读）

开了 git 的话，每次改动都会提交一次，报告里的"撤销"就是 git revert。
找相关记忆用嵌入模型（本地），只在这个文件夹里找。
"""
import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from . import db, paths, privacy, safety, settings
from .models import M, NOWIN
from .seeds import PERSONA

DEFAULT_FILES = {
    "记忆/收件箱.md": "# 收件箱\n\n你说\"记住……\"的内容先放这里，每日差事整理到对应的文件。\n\n",
    "记忆/关于我.md": "# 关于我\n\n",
    "技能/README.md": "# 技能\n\n每个技能一个 .md 文件：什么时候用、怎么做、注意什么。agent 做成一件新事后可以在这里加一个技能。\n",
    "提示词/人设.md": PERSONA,
    "总结/README.md": "# 网页 Claude 带回的总结\n\n在界面 大脑 › 网页 Claude › 导入总结，文件会放到这里。和 Claude 的聊天记录也可以放这里。\n\n**规矩（写死在代码里）：这个文件夹里的内容只当参考资料读，不发给 DeepSeek 加工，不进任何训练数据。**\nAnthropic 的用户条款不允许用 Claude 的服务去开发或训练 AI 模型，我们不冒封号的险。\n",
}


def root() -> Path:
    return paths.resolve(settings.S["memDir"], paths.MEMORY)


def git_ok():
    return shutil.which("git") is not None


def _git(*args, check=False):
    r = subprocess.run(["git", *args], cwd=root(), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=NOWIN)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r


def init():
    r = root()
    r.mkdir(parents=True, exist_ok=True)
    for rel, content in DEFAULT_FILES.items():
        p = r / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, "utf-8")
    if settings.S["useGit"] and git_ok() and not (r / ".git").exists():
        _git("init")
        _git("config", "user.name", "agent")
        _git("config", "user.email", "agent@localhost")
        _git("add", "-A")
        _git("commit", "-m", "初始化 agent 文件夹")


def commit(msg: str) -> str:
    if not (settings.S["useGit"] and git_ok() and (root() / ".git").exists()):
        return ""
    _git("add", "-A")
    r = _git("commit", "-m", msg)
    if r.returncode != 0:
        return ""
    return _git("rev-parse", "HEAD").stdout.strip()


def persona() -> str:
    try:
        return (root() / "提示词/人设.md").read_text("utf-8")
    except FileNotFoundError:
        return PERSONA


def _inside(rel: str) -> Path:
    p = (root() / rel).resolve()
    if root().resolve() not in p.parents and p != root().resolve():
        raise PermissionError("只能写 agent 自己的文件夹")
    return p


async def write(rel: str, content: str, why: str, kind="memory.write", append=False):
    """写记忆或技能文件。走安全闸：默认先斩后奏，事后写进报告，可撤销。"""
    async def run():
        return _do_write(rel, content, why, kind, append)

    return await safety.request(kind, f"写入 {rel}", why, {"rel": rel, "content": content, "why": why, "append": append, "kind": kind}, run)


def _do_write(rel, content, why, kind="memory.write", append=False):
    p = _inside(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    if append and p.exists():
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
    else:
        p.write_text(content, "utf-8")
    cid = commit(f"{why}（{rel}）")
    safety.record_change(kind, f"{'追加' if append else '修改'}「{rel}」", why, cid)
    return cid


@safety.handler("memory.write")
async def _approved_write(payload):
    _do_write(payload["rel"], payload["content"], payload.get("why", "你同意的改动"), payload.get("kind", "memory.write"), payload.get("append", False))
    return "已写入"


@safety.handler("prompt.update")
async def _approved_prompt(payload):
    _do_write(payload["rel"], payload["content"], payload.get("why", "你同意的改动"), "prompt.update", False)
    return "提示词已改好"


async def remember(text: str, event_id=None):
    line = f"- {time.strftime('%Y-%m-%d %H:%M')} {text.strip()}\n"
    return await write("记忆/收件箱.md", line, f"你让我记住的内容 · 事件 #{event_id}" if event_id else "你让我记住的内容", append=True)


def undo(change_id: int) -> str:
    c = db.one("SELECT * FROM changes WHERE id=?", (change_id,))
    if not c:
        return "找不到这条改动"
    if c["undone"]:
        return "已经撤销过了"
    if (c["commit_id"] or "").startswith("reminder:"):
        rid = int(c["commit_id"].split(":", 1)[1])
        db.run("DELETE FROM reminders WHERE id=?", (rid,))
        db.update("changes", change_id, {"undone": 1})
        safety.log("undo", {"change": change_id, "reminder": rid}, "user")
        return "已撤销：这个提醒删掉了"
    if c["commit_id"]:
        r = _git("revert", "--no-edit", c["commit_id"])
        if r.returncode != 0:
            return "撤销失败：" + (r.stderr.strip() or r.stdout.strip())[:200]
        db.update("changes", change_id, {"undone": 1})
        safety.log("undo", {"change": change_id}, "auto")
        return "已撤销（git revert）"
    db.update("changes", change_id, {"undone": 1})
    return "已标记撤销（这条改动没有 git 记录，需要手动恢复）"


# ---------------- 找相关记忆 ----------------
DOC_TAG = "@说明/"          # 说明书的段落也切块放进 chunks 表，file 前面加这个标记，和记忆分开找
ABOUT = re.compile(r"你(能|会|可以|怎么|是怎么|有哪些|有什么|的(功能|设置|界面|提醒|记忆|规矩|安全线))|怎么(用|设置|设|改|关|开|打开|装|绑定|退出)|"
                   r"在哪(里)?(改|设|看|找|开|关)|设置里|界面上|侧栏|整备|一键补齐|免打扰|让路|决策脑|小脑|每日差事|安全线|"
                   r"操作手册|说明书|说明页|后台页|报告页|常驻屏|主题|风格|开机自启|硬件监控|游戏帧数|找 ?Claude|联网搜索|agent|Agent")


def about_agent(text: str) -> bool:
    """这句话是不是在问 agent 自己（能做什么、怎么用、在哪设置）。是的话回答前先查说明书。"""
    return bool(ABOUT.search(text or ""))


def _doc_files():
    """给 agent 自己读的说明书：操作手册 + docs/AI文档 里的全部（架构说明、当前结构）。"""
    d = paths.ROOT / "docs"
    fs = [d / "操作手册.md"] + sorted((d / "AI文档").rglob("*.md"))
    return [(f, DOC_TAG + f.relative_to(d).as_posix()) for f in fs if f.exists()]


def _split(rel, text):
    out = []
    for part in [x.strip() for x in text.split("\n\n") if len(x.strip()) > 6]:
        for i in range(0, len(part), 400):
            piece = part[i:i + 400]
            out.append((hashlib.sha1((rel + piece).encode()).hexdigest(), rel, piece))
    return out


def _chunks():
    out = []
    for p in root().rglob("*.md"):
        if ".git" in p.parts or p.name.lower() == "readme.md":   # 说明文件不算记忆
            continue
        rel = str(p.relative_to(root()))
        try:
            text = p.read_text("utf-8")
        except Exception:
            continue
        out += _split(rel, text)
    for f, rel in _doc_files():
        try:
            out += _split(rel, f.read_text("utf-8"))
        except Exception:
            continue
    return out


async def index():
    """给记忆文件和说明书切块、算向量（只算新增的，每批 64 段，一次没算完下次接着算）。"""
    cs = _chunks()
    have = {r["hash"] for r in db.q("SELECT hash FROM chunks")}
    new = [c for c in cs if c[0] not in have]
    done = 0
    for i in range(0, len(new), 64):
        part = new[i:i + 64]
        vecs = await M.embed([c[2] for c in part], instruct=False)
        if not vecs:
            return done
        for (h, rel, piece), v in zip(part, vecs):
            priv = 0 if rel.startswith(DOC_TAG) else int(privacy.check(piece)[0])     # 说明书是公开的，里面举例提到"吃药"不算隐私
            db.run("INSERT OR REPLACE INTO chunks(hash,file,text,private,vec,mtime) VALUES(?,?,?,?,?,?)",
                   (h, rel, piece, priv, np.asarray(v, dtype=np.float32).tobytes(), time.time()))
        done += len(part)
    keep = {c[0] for c in cs}
    for r in db.q("SELECT hash FROM chunks"):
        if r["hash"] not in keep:
            db.run("DELETE FROM chunks WHERE hash=?", (r["hash"],))
    return done


CLAUDE_DIRS = ("总结",)


def is_claude(rel: str) -> bool:
    """这段内容是不是来自 Claude（总结、聊天记录）。"""
    first = str(rel).replace("\\", "/").split("/", 1)[0]
    return first in CLAUDE_DIRS


async def search(qvec, k=4, allow_private=True):
    if qvec is None:
        return []
    rows = db.q("SELECT file,text,private,vec FROM chunks WHERE file NOT LIKE ?", (DOC_TAG + "%",))
    if not rows:
        return []
    mat = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
    if mat.shape[1] != len(qvec):
        db.run("DELETE FROM chunks")
        return []
    sims = mat @ np.asarray(qvec, dtype=np.float32)
    out = []
    for i in np.argsort(-sims)[: k * 3]:
        r = rows[i]
        if r["private"] and not allow_private:
            continue
        if sims[i] < 0.45:
            break
        out.append({"file": r["file"], "text": r["text"], "sim": float(sims[i]), "claude": is_claude(r["file"])})
        if len(out) >= k:
            break
    return out


async def search_docs(qvec, text="", k=3, floor=0.35):
    """从说明书里找和这句话最相关的几段（问到 agent 自己时用）。
    嵌入模型没开时，退回按关键词数重合的字找，保证说明书总能查到点东西。"""
    rows = db.q("SELECT file,text,vec FROM chunks WHERE file LIKE ?", (DOC_TAG + "%",))
    if qvec is not None and rows:
        mat = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
        if mat.shape[1] == len(qvec):
            sims = mat @ np.asarray(qvec, dtype=np.float32)
            out = []
            for i in np.argsort(-sims)[:k]:
                if sims[i] < floor:
                    break
                out.append({"file": rows[i]["file"], "text": rows[i]["text"], "sim": float(sims[i])})
            if out:
                return out
    grams = {text[i:i + 2] for i in range(len(text) - 1)} - {"你的", "怎么", "什么", "一下", "可以", "我的", "在哪"}
    if not grams:
        return []
    pool = [(f, s) for _, f, s in _split_all_docs()]
    scored = sorted(((sum(g in s for g in grams), f, s) for f, s in pool), key=lambda x: -x[0])
    return [{"file": f, "text": s, "sim": 0.0} for n, f, s in scored[:k] if n >= 2]


def _split_all_docs():
    out = []
    for f, rel in _doc_files():
        try:
            out += _split(rel, f.read_text("utf-8"))
        except Exception:
            continue
    return out
