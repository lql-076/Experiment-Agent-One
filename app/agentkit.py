r"""Agent 的本事（v3.0）：交给 DeepSeek 做事时，除了联网、读文件、工作区那几样，再给它这些：

- update_plan   先列计划、做一步勾一步。计划存在事件里，主页「现在」那块看得到（做到第几条、哪条正在做）。
- look          看一张图，或者看视频里某几秒的画面（自己检查做出来的东西对不对）。
- media_info    一个视频 / 音频 / 图片多长、多大。
- download_file 从网上下一个文件进工作区（素材、字体……）。只走 http(s)，不碰本机和局域网地址，一个最多 500 MB。
- read_skill    看一份「技能」（做某类事的现成办法：skills\ 里自带的，和 工作区\技能\ 里他或者你自己写的）。
- make_voice    配音（用配音页上次用的音色）。默认只用本地的；云端（百炼，花钱）要他在 设置 › Agent 能力 里打开。
- make_image    生图（API易，花钱）。默认关着，要他打开；一件事最多出几张有上限。
- make_music    配乐（本地 ACE-Step，纯音乐）。配好了才给。

还管三件事：
- 喊停、插话：每件正在做的事有一个开关（CTRL）。界面上点「停下」→ 这一步做完就停；中途又说了一句 → 下一步之前告诉 DeepSeek。
- 预算：一件事最多花多少钱（agBudget，0 = 不限），到了就停下汇报。
- 工具箱：toolbox\ 里的现成脚本（网页动画录成视频、配音字幕配乐合成）每次用工作区之前同步到 工作区\工具箱\，DeepSeek 直接拿来跑，不用每次重写。

给 Agent 加本事（花钱的、能动更多东西的）只有界面上他点了才算：这些开关在 settings.PERM 里，通用的改设置改不了。
"""
import asyncio
import base64
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import db, files, mediainfo, paths, privacy, safety, settings, workspace

SKILLS = paths.ROOT / "skills"                  # 自带的技能（随项目打包）
TOOLBOX = paths.ROOT / "toolbox"                # 自带的工具箱脚本（同步进 工作区\工具箱）
WS_SKILLS, WS_TOOLBOX = "技能", "工具箱"
MAX_DL = 500 << 20
PLAN_MAX = 20

# ---------------- 每件事的开关：喊停、插话、计划 ----------------
CTRL = {}


def open_ctl(eid, user="me"):
    CTRL[eid] = {"stop": "", "inbox": [], "plan": [], "t0": time.time(), "user": user, "imgs": 0}
    for k in [k for k, v in CTRL.items() if time.time() - v["t0"] > 6 * 3600 and k != eid]:
        CTRL.pop(k, None)
    return CTRL[eid]


def close_ctl(eid):
    CTRL.pop(eid, None)


def running(user=None):
    return [k for k, v in CTRL.items() if user is None or v["user"] == user]


def request_stop(eid, why="你点了停下"):
    c = CTRL.get(eid)
    if not c:
        return False
    c["stop"] = why
    workspace.cancel_run()                       # 正在跑的命令也停
    return True


def push(eid, text):
    """中途插一句话：下一步之前告诉 DeepSeek。"""
    c = CTRL.get(eid)
    if not c or not str(text or "").strip():
        return False
    c["inbox"].append(str(text).strip()[:2000])
    return True


def set_plan(eid, items):
    plan = []
    for it in (items or []):
        if len(plan) >= PLAN_MAX:
            break
        if isinstance(it, str):
            it = {"text": it}
        if not isinstance(it, dict):
            continue
        t = str(it.get("text") or it.get("step") or it.get("content") or "").strip()[:80]
        st = str(it.get("status") or it.get("st") or "todo").lower()
        st = {"done": "done", "completed": "done", "完成": "done", "doing": "doing", "in_progress": "doing", "进行中": "doing"}.get(st, "todo")
        if t:
            plan.append({"text": t, "st": st})
    if eid in CTRL:
        CTRL[eid]["plan"] = plan
    if eid:
        db.update("events", eid, {"plan": plan})
    return plan


# ---------------- 技能 ----------------
def _skill_files():
    out = {}
    for base, mine in ((SKILLS, False), (workspace.folder() / WS_SKILLS, True)):
        if base.is_dir():
            for p in sorted(base.glob("*.md")):
                out[p.stem] = (p, mine)
    return out


def _skill_meta(p: Path):
    """开头几行：「用在：……」一句话说明；「触发：词1|词2」对上了就自动带上全文。"""
    try:
        head = p.read_text("utf-8", errors="replace")[:600]
    except OSError:
        return "", None
    m = re.search(r"^用在[:：]\s*(.+)$", head, re.M)
    t = re.search(r"^触发[:：]\s*(.+)$", head, re.M)
    rx = None
    if t:
        try:
            rx = re.compile(t.group(1).strip(), re.I)
        except re.error:
            rx = None
    return (m.group(1).strip() if m else "")[:80], rx


def skills():
    return [{"name": n, "use": _skill_meta(p)[0], "mine": mine, "path": paths.show(p)} for n, (p, mine) in _skill_files().items()]


def skill_text(name, cap=9000):
    fs = _skill_files()
    hit = fs.get(str(name or "").strip()) or next((v for k, v in fs.items() if str(name or "").strip() and str(name).strip() in k), None)
    if not hit:
        raise workspace.Denied(f"没有这份技能：{name}。现有的：" + ("、".join(fs) or "还没有"))
    return hit[0].read_text("utf-8", errors="replace")[:cap]


def skills_for(text, cap=6000):
    """这句话对上了哪份技能的「触发」：全文带进说明（最多两份）。"""
    out = []
    for n, (p, _mine) in _skill_files().items():
        rx = _skill_meta(p)[1]
        if rx and rx.search(text or "") and len(out) < 2:
            out.append((n, p.read_text("utf-8", errors="replace")[:cap]))
    return out


# ---------------- 工具箱：同步进工作区 ----------------
def sync_toolbox():
    """toolbox\\ 里的脚本复制进 工作区\\工具箱\\（内容不一样才换；被改过的旧的先进备份）。返回同步了几个。"""
    if not TOOLBOX.is_dir() or not workspace.on():
        return 0
    dst = workspace.folder() / WS_TOOLBOX
    n = 0
    for src in TOOLBOX.rglob("*"):
        if not src.is_file() or "__pycache__" in src.parts:
            continue
        d = dst / src.relative_to(TOOLBOX)
        try:
            if d.exists() and d.read_bytes() == src.read_bytes():
                continue
            d.parent.mkdir(parents=True, exist_ok=True)
            if d.exists():
                workspace._backup(d, "改")
            shutil.copyfile(src, d)
            n += 1
        except OSError:
            continue
    return n


def toolbox_list():
    d = TOOLBOX
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.py")):
            try:
                doc = re.search(r'"""(.+?)(?:\n|""")', p.read_text("utf-8"), re.S)
            except OSError:
                doc = None
            out.append({"name": p.name, "use": (doc.group(1).strip() if doc else "")[:90]})
    return out


# ---------------- 开关 ----------------
def caps():
    """现在给了 Agent 哪些本事（设置 › Agent 能力）。"""
    s = settings.S
    from . import bgm, tts
    img_key = bool(settings.get_secret("imgKey"))
    return {"plan": True, "look": True, "download": bool(s.get("agDownload", True)),
            "voice": bool(s.get("agVoice", True)), "voice_cloud": bool(s.get("agVoiceCloud", False)), "voice_ready": bool(db.kv_get("tts_last_req")),
            "voice_env": tts.T.env_ok(),
            "image": bool(s.get("agImage", False)), "image_key": img_key, "image_max": int(s.get("agImageMax") or 8),
            "music": bool(s.get("agMusic", True)), "music_ready": bgm.B.configured(),
            "steps": int(s.get("agSteps") or 120), "budget": float(s.get("agBudget") or 0),
            "cc": bool(s.get("ccOn", False))}


def set_cap(k, v):
    """打开 / 关上一项本事（只有界面上他点的才走到这里），记进动作日志。"""
    keys = {"download": "agDownload", "voice": "agVoice", "voice_cloud": "agVoiceCloud", "image": "agImage", "music": "agMusic", "cc": "ccOn"}
    texts = {"cc_cmd": "ccCmd", "cc_bash": "ccBash"}             # Claude Code 在哪、许它跑哪些程序：也是权限
    if k in texts:
        settings.S[texts[k]] = str(v or "").strip()[:400]
        settings.save()
        safety.log("tool.add", {"perm": "agent." + k, "value": settings.S[texts[k]][:120]}, "user")
        return caps()
    if k not in keys:
        raise ValueError("没有这一项")
    settings.S[keys[k]] = bool(v)
    settings.save()
    safety.log("tool.add" if v else "tool.remove", {"perm": "agent." + k, "on": bool(v)}, "user")
    return caps()


# ---------------- 工具的说明 ----------------
def _fn(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": props, "required": req}}}


P = {"type": "string", "description": "工作文件夹里的相对路径"}


def tools():
    c = caps()
    t = [
        _fn("update_plan", "步骤多的活（三步以上）：先把计划列出来，之后每做完一步就更新（把做完的标 done、正在做的标 doing）。他在界面上看得到这份计划做到哪了。"
            "每次给完整的清单（不是只给变了的那条）。闲聊、一两步的小事不用列。",
            {"items": {"type": "array", "description": "按顺序的步骤，最多 20 条", "items": {"type": "object", "properties": {
                "text": {"type": "string", "description": "这一步做什么，十几个字"}, "status": {"type": "string", "enum": ["todo", "doing", "done"]}}, "required": ["text", "status"]}}},
            ["items"]),
        _fn("look", "亲眼看一下：一张图片（PNG / JPEG / WEBP / GIF），或者视频里某几秒的画面。做出图、网页截图、视频以后，用它检查对不对（字有没有出框、画面是不是黑的、角色对不对），不要没看过就说做好了。",
            {"path": P, "at": {"type": "array", "items": {"type": "number"}, "description": "看视频时：要看第几秒（最多 4 个时间点）；不写就看开头、中间、快结尾三处"}}, ["path"]),
        _fn("media_info", "一个视频 / 音频 / 图片有多长、多大（时长、分辨率、文件大小）。", {"path": P}, ["path"]),
        _fn("read_skill", "看一份技能说明（做某类事的现成办法和现成工具怎么用）。做视频、配音这类事先看对应的技能。", {"name": {"type": "string", "description": "技能的名字"}}, ["name"]),
    ]
    if c["download"]:
        t.append(_fn("download_file", "从网上下载一个文件到工作文件夹（素材、字体、图片、压缩包）。网址要来自搜索结果或他给的。一个最多 500 MB。",
                     {"url": {"type": "string", "description": "完整网址，http 或 https"}, "path": P}, ["url", "path"]))
    if c["voice"]:
        t.append(_fn("make_voice", "配音：把一段文案念成音频（WAV），同时给出每句的时间轴（JSON）和字幕（SRT），都存进你指定的文件夹。"
                     "用的是他在配音页上次用的音色。一次最多几千字；长的分几次。" + ("" if c["voice_cloud"] else "只用本地配音模型（不花钱）。"),
                     {"text": {"type": "string", "description": "要念的文案（只写要念出来的字）"}, "dir": {"type": "string", "description": "存进工作文件夹的哪个文件夹，比如 片头\\配音"},
                      "name": {"type": "string", "description": "文件名（不带扩展名），比如 旁白01"}}, ["text", "dir"]))
    if c["image"] and c["image_key"]:
        t.append(_fn("make_image", f"生图（要花钱，一张约 0.2 元；这件事最多 {c['image_max']} 张，想清楚再出）。提示词要把主体、画风、构图写全；角色要把外形写全。图里不要放文字。",
                     {"prompt": {"type": "string"}, "path": {"type": "string", "description": "存成工作文件夹里的哪个文件，.png 结尾"},
                      "ratio": {"type": "string", "description": "比例，16:9 / 9:16 / 1:1 / 4:3 / 3:4 等，默认 16:9"},
                      "transparent": {"type": "boolean", "description": "透明背景（角色、道具用）"},
                      "refs": {"type": "array", "items": {"type": "string"}, "description": "参考图（工作文件夹里的图片路径，最多 4 张），比如角色定稿图"}}, ["prompt", "path"]))
    if c["music"] and c["music_ready"]:
        t.append(_fn("make_music", "配乐：生成一段纯音乐（背景音乐，没有人声），存成 WAV。描述写风格、情绪、乐器、速度。要等一两分钟。",
                     {"prompt": {"type": "string", "description": "比如：轻快的电子流行，明亮的合成器和鼓点，适合科技类视频开场"},
                      "seconds": {"type": "integer", "description": "多长，10~600 秒，默认 60"}, "path": {"type": "string", "description": "存成工作文件夹里的哪个文件，.wav 结尾"}}, ["prompt", "path"]))
    return t


NAMES = {"update_plan", "look", "media_info", "read_skill", "download_file", "make_voice", "make_image", "make_music"}


def hint(user_text="") -> str:
    c = caps()
    sk = skills()
    tb = toolbox_list()
    s = ("干活的规矩：三步以上的活先 update_plan 列计划，做完一步更新一次；做出来的图、视频用 look 亲眼看过再说做好了；"
         "出错了先看报错、改了再试，同一个办法连着失败两次就换办法；做不到的照实说，不要编。\n")
    if tb:
        s += (f"工作文件夹的「{WS_TOOLBOX}」里有现成的脚本，直接用 run_command 跑（加 -h 看用法），不用自己重写：\n" +
              "\n".join(f"- {WS_TOOLBOX}\\{x['name']}：{x['use']}" for x in tb) + "\n")
    if sk:
        s += "有这些技能说明（做这类事先 read_skill 看一遍）：" + "；".join(f"{x['name']}（{x['use']}）" if x["use"] else x["name"] for x in sk) + "。\n"
    if c["voice"]:
        s += "配音用 make_voice（用他配音页上次的音色" + ("；" if c["voice_ready"] else "；他还没在配音页用过，会用默认音色；") + "给时间轴和字幕）。"
    else:
        s += "配音他没让你用。"
    if c["image"] and c["image_key"]:
        s += f"生图用 make_image（花钱，这件事最多 {c['image_max']} 张）。"
    else:
        s += "生图现在没给你（他没开或者没填 Key）：需要图就用他给的素材，或者告诉他去 设置 › Agent 能力 打开。"
    if c["music"] and c["music_ready"]:
        s += "配乐用 make_music。"
    for n, body in skills_for(user_text):
        s += f"\n\n【技能：{n}】\n{body}"
    return s


# ---------------- 工具的实现 ----------------
def _ffmpeg():
    """工作区专用环境里的 ffmpeg（pip install imageio-ffmpeg 以后有），没有就找系统里的。"""
    p = workspace._bin() / ("ffmpeg.exe" if paths.IS_WIN else "ffmpeg")
    if p.exists():
        return str(p)
    return shutil.which("ffmpeg")


def _frames(rp: Path, at):
    """从视频里抽几帧（JPEG，宽最多 960）。"""
    ff = _ffmpeg()
    if not ff:
        raise workspace.Denied("看视频画面要 ffmpeg：先 run_command 跑 pip install imageio-ffmpeg")
    info = mediainfo.probe(rp)
    dur = info.get("duration") or 0
    ts = [float(x) for x in (at if isinstance(at, list) else [at] if at is not None else []) if isinstance(x, (int, float)) and not isinstance(x, bool)][:4]
    if not ts:
        ts = [dur * 0.08, dur * 0.5, dur * 0.92] if dur > 1.5 else [0.0]
    out = []
    tmp = workspace.ensure() / workspace.TMP
    tmp.mkdir(exist_ok=True)
    for k, t in enumerate(ts):
        t = max(0.0, min(t, max(0.0, dur - 0.2)) if dur else t)
        f = tmp / f"look_{os.getpid()}_{int(time.time() * 1000) % 100000}_{k}.jpg"
        try:
            for tt in (t, max(0.0, t - 1.0)):                    # 太靠近结尾有时抽不出来：往前一秒再试一次
                subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{tt:.3f}", "-i", str(rp), "-frames:v", "1", "-vf", "scale='min(960,iw)':-2", "-q:v", "4", str(f)],
                               capture_output=True, timeout=60, creationflags=workspace.NOWIN)
                if f.exists() and f.stat().st_size:
                    out.append((tt, f.read_bytes()))
                    break
        finally:
            with __import__("contextlib").suppress(OSError):
                f.unlink()
    if not out:
        raise workspace.Denied("没抽出画面（这个视频可能是坏的，或者是空的）")
    return out, info


def look(path, at=None):
    """返回 (给模型的文字, [{name, uri}])。"""
    rp = files.check(str(workspace.real(path, must_exist=True)), True)
    k = mediainfo.kind(rp)
    desc = mediainfo.describe(rp)
    if k == "image":
        r = files.read(str(rp), cloud=True)
        return f"这是 {workspace.rel(rp)}（{desc or files._size(r['size'])}），图片在下一条消息里。", [{"name": rp.name, "uri": r["uri"]}]
    if k == "video":
        fr, info = _frames(rp, at)
        pics = [{"name": f"{rp.name} 第 {t:.1f} 秒", "uri": "data:image/jpeg;base64," + base64.b64encode(b).decode()} for t, b in fr]
        return (f"这是 {workspace.rel(rp)}（{desc or '视频'}）在 " + "、".join(f"{t:.1f} 秒" for t, _ in fr) + " 的画面，在下一条消息里。"), pics
    raise workspace.Denied(f"「{rp.name}」不是图片也不是视频，看不了" + (f"（它是{desc}）" if desc else "") + "；文字文件用 read_file")


def _public_host(host):
    """只许公网地址：本机、局域网、链路本地的都不行（免得被网页里的话骗去拿本机的东西）。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for i in infos:
        ip = ipaddress.ip_address(i[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(infos)


async def download(url, path, say=None):
    url = str(url or "").strip()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or len(url) > 4000:
        raise workspace.Denied("网址不对：要 http 或 https 开头的完整网址")
    if privacy.check(url)[0]:
        raise workspace.Denied("这个网址里有隐私词，没有发出去")
    if not os.environ.get("AGENT_DL_ANY") and not await asyncio.to_thread(_public_host, u.hostname):
        raise workspace.Denied("只能下公网上的文件：本机和局域网的地址不行")
    dst = workspace.real(path)
    if dst.is_dir():
        raise workspace.Denied("path 要写成文件名，不是文件夹")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp, got, t0, last = dst.with_name(dst.name + ".part"), 0, time.time(), 0.0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20, read=60, write=30, pool=None), follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Agent"}) as c:
            async with c.stream("GET", url) as r:
                if r.status_code != 200:
                    raise workspace.Denied(f"下载不了：网站返回 {r.status_code}")
                if not os.environ.get("AGENT_DL_ANY") and r.url.host and not await asyncio.to_thread(_public_host, r.url.host):
                    raise workspace.Denied("被转到了本机或局域网的地址，没有下")
                total = int(r.headers.get("content-length") or 0)
                if total > MAX_DL:
                    raise workspace.Denied(f"太大了（{files._size(total)}），一个最多 500 MB")
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        got += len(chunk)
                        if got > MAX_DL:
                            raise workspace.Denied("太大了，超过 500 MB，停了")
                        f.write(chunk)
                        if say and time.time() - last > 1.5:
                            last = time.time()
                            say(f"正在下载 {dst.name}（{files._size(got)}" + (f" / {files._size(total)}" if total else "") + "）……")
        if dst.exists():
            workspace._backup(dst, "覆盖")
        os.replace(tmp, dst)
    except httpx.HTTPError as e:
        raise workspace.Denied(f"下载断了：{type(e).__name__}") from None
    finally:
        if tmp.exists():
            tmp.unlink()
    workspace._did("下载", workspace.rel(dst), bytes=got, host=u.hostname)
    info = mediainfo.describe(dst)
    return {"rel": workspace.rel(dst), "size": got, "sec": time.time() - t0, "info": info, "host": u.hostname}


async def make_voice(text, d, name=None, say=None, stopped=None):
    """用配音页那一套生成（本地；他开了云端才用云端），再把音频、时间轴、字幕复制进工作区。"""
    from . import tts
    text = str(text or "").strip()
    if not text:
        raise workspace.Denied("没有要念的字")
    req = dict(db.kv_get("tts_last_req") or {"mode": "preset", "speaker": "Vivian", "lang": "Chinese"})
    cloud = (req.get("engine") or "local") == "cloud"
    if cloud and not settings.S.get("agVoiceCloud", False):
        req = {"mode": "preset", "speaker": "Vivian", "lang": "Chinese"}
        cloud = False
    req.update(text=text, engine="cloud" if cloud else "local", same=False)
    out = workspace.real(d)
    try:
        tts.T.start(req)
    except Exception as e:                                   # HTTPException：正在让路、模型没装、上一段还在生成……
        raise workspace.Denied("配音没开始：" + str(getattr(e, "detail", e))[:200]) from None
    job = tts.T.job
    t0 = time.time()
    while job["st"] == "run":
        if stopped and stopped():
            job["stop"] = "这件事被停下了"
        if say:
            p = tts.T.public() or {}
            say(f"正在配音（{p.get('pct') or 0:.0f}%）……")
        await asyncio.sleep(0.5)
        if time.time() - t0 > 3600:
            job["stop"] = "超过一小时"
    if job["st"] != "done":
        raise workspace.Denied("配音没成：" + str(job.get("err") or job.get("msg") or job["st"])[:200])
    m = tts.T.draft()
    if not m:
        raise workspace.Denied("配音生成了但没找到音频")
    base = workspace.safe_name(name or m.get("name") or "配音")
    out.mkdir(parents=True, exist_ok=True)
    meta = dict(m, audio=f"{base}.wav", subtitles=f"{base}_字幕.srt")
    meta.pop("ver", None)
    made = []
    for src, fn in ((tts.DRAFT / "draft.wav", f"{base}.wav"), (tts.DRAFT / "draft.srt", f"{base}_字幕.srt")):
        dst = out / fn
        if dst.exists():
            workspace._backup(dst, "覆盖")
        shutil.copyfile(src, dst)
        made.append(workspace.rel(dst))
    tl = out / f"{base}_时间轴.json"
    if tl.exists():
        workspace._backup(tl, "覆盖")
    tl.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    made.append(workspace.rel(tl))
    workspace._did("配音", workspace.rel(out), files=len(made), engine="cloud" if cloud else "local")
    return {"files": made, "audio_s": float(job.get("audio_s") or 0), "cny": float(job.get("cny") or 0), "voice": job["voice"]["label"],
            "engine": "百炼云端" if cloud else "本地", "sentences": len(m.get("segments") or [])}


async def make_image(eid, prompt, path, ratio="16:9", transparent=False, refs=None, say=None, stopped=None):
    from . import imagegen
    c = caps()
    ctl = CTRL.get(eid) or {"imgs": 0}
    if ctl["imgs"] >= c["image_max"]:
        raise workspace.Denied(f"这件事已经出了 {ctl['imgs']} 张图，到上限了（设置 › Agent 能力 能调）。用已有的图接着做。")
    dst = workspace.real(path)
    if dst.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        dst = dst.with_suffix(".png")
    uris = []
    for r in (refs or [])[:4]:
        rp = files.check(str(workspace.real(r, must_exist=True)), True)
        uris.append(imagegen.data_uri(rp.read_bytes()))
    G = imagegen.G
    for _ in range(600):                                         # 生图页正在出别的：等它
        if not G.busy():
            break
        if stopped and stopped():
            raise workspace.Denied("停下了")
        if say:
            say("生图那边正在出别的图，等它出完……")
        await asyncio.sleep(1)
    try:
        G.single({"prompt": str(prompt or ""), "ratio": ratio if ratio in imagegen.RATIOS else "16:9", "n": 1, "transparent": bool(transparent), "refs": uris})
    except Exception as e:
        raise workspace.Denied("生图没开始：" + str(getattr(e, "detail", e))[:200]) from None
    job, t0 = G.job, time.time()
    while job["st"] == "run":
        if say:
            say(f"正在生图（{int(time.time() - t0)} 秒）……")
        await asyncio.sleep(0.5)
    res = (job["results"] or [{}])[-1]
    if not res.get("ok"):
        raise workspace.Denied("图没出来：" + str(res.get("err") or job.get("msg"))[:200])
    src = G.hpath(res["hid"])
    dst = dst.with_suffix(src.suffix)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        workspace._backup(dst, "覆盖")
    shutil.copyfile(src, dst)
    ctl["imgs"] = ctl.get("imgs", 0) + 1
    workspace._did("生图", workspace.rel(dst), usd=res.get("usd"))
    return {"rel": workspace.rel(dst), "w": res.get("w"), "h": res.get("h"), "alpha": res.get("alpha"), "usd": float(res.get("usd") or 0),
            "sec": res.get("sec"), "warn": res.get("warn") or "", "n": ctl["imgs"], "max": c["image_max"]}


async def make_music(prompt, path, seconds=60, say=None, stopped=None):
    from . import bgm
    dst = workspace.real(path)
    if dst.suffix.lower() != ".wav":
        dst = dst.with_suffix(".wav")
    try:
        r = await bgm.B.generate(str(prompt or ""), seconds, say=say, stopped=stopped)
    except bgm.BgmError as e:
        raise workspace.Denied("配乐没成：" + str(e)[:200]) from None
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        workspace._backup(dst, "覆盖")
    shutil.copyfile(r["path"], dst)
    workspace._did("配乐", workspace.rel(dst), sec=r.get("duration"))
    return {"rel": workspace.rel(dst), "duration": r.get("duration"), "sec": r.get("sec")}


async def run_tool(name, args, eid=None, say=None):
    """执行一个工具。返回 (给模型的文字, 步骤 [名, 说明], 图片 [{name, uri}], 花了多少钱 ¥)。"""
    say = say or (lambda _m: None)
    ctl = CTRL.get(eid) or {}
    stopped = lambda: bool(ctl.get("stop"))      # noqa: E731
    if name == "update_plan":
        plan = set_plan(eid, args.get("items"))
        if not plan:
            raise workspace.Denied("计划是空的：items 里每条要有 text 和 status")
        done = sum(1 for x in plan if x["st"] == "done")
        cur = next((x["text"] for x in plan if x["st"] == "doing"), "")
        return f"计划记下了（{done}/{len(plan)} 完成）。接着做。", ["计划", f"{done}/{len(plan)}" + (f" · 正在：{cur}" if cur else "")], [], 0.0
    if name == "look":
        say("正在看画面……")
        txt, pics = await asyncio.to_thread(look, args.get("path"), args.get("at"))
        return txt, ["看画面", f"{Path(str(args.get('path') or '')).name}" + (f" · {len(pics)} 帧" if len(pics) > 1 else "")], pics, 0.0
    if name == "media_info":
        rp = files.check(str(workspace.real(args.get("path"), must_exist=True)), True)
        d = mediainfo.describe(rp) or "认不出时长和分辨率"
        return f"{workspace.rel(rp)}：{d} · {files._size(rp.stat().st_size)}", ["看信息", f"{rp.name} · {d}"], [], 0.0
    if name == "read_skill":
        body = skill_text(args.get("name"))
        return body, ["看技能", str(args.get("name"))[:30]], [], 0.0
    if name == "download_file":
        if not settings.S.get("agDownload", True):
            raise workspace.Denied("下载他关掉了（设置 › Agent 能力）")
        say("正在下载……")
        r = await download(args.get("url"), args.get("path"), say)
        return (f"下好了：{r['rel']}（{files._size(r['size'])}" + (f" · {r['info']}" if r["info"] else "") + f"，用了 {r['sec']:.0f} 秒）。",
                ["下载", f"{r['rel']} · {files._size(r['size'])} · {r['host']}"], [], 0.0)
    if name == "make_voice":
        if not settings.S.get("agVoice", True):
            raise workspace.Denied("配音他没让你用（设置 › Agent 能力）")
        say("正在配音……")
        r = await make_voice(args.get("text"), args.get("dir") or "配音", args.get("name"), say, stopped)
        return (f"配好了（{r['engine']} · {r['voice']} · {r['sentences']} 句 · {mediainfo.clock(r['audio_s'])}）：" + "、".join(r["files"]) +
                "。时间轴 JSON 里 segments 是每句的 start / end（秒）和 text，做字幕、对口型按它来。",
                ["配音", f"{r['voice']} · {mediainfo.clock(r['audio_s'])} · {r['engine']}" + (f" · ¥{r['cny']:.3f}" if r["cny"] else "")], [], r["cny"])
    if name == "make_image":
        if not (settings.S.get("agImage", False) and settings.get_secret("imgKey")):
            raise workspace.Denied("生图没给你（他没开或者没填 Key）：用已有的素材，或者告诉他去 设置 › Agent 能力 打开")
        say("正在生图……")
        r = await make_image(eid, args.get("prompt"), args.get("path"), args.get("ratio") or "16:9", bool(args.get("transparent")), args.get("refs"), say, stopped)
        cny = r["usd"] * float(settings.S.get("usdCny") or 7.2)
        return (f"图出好了：{r['rel']}（{r['w']}×{r['h']}" + ("，透明背景" if r["alpha"] else "") + f"，这件事第 {r['n']}/{r['max']} 张）。" +
                (f"注意：{r['warn']}。" if r["warn"] else "") + "用 look 看一眼对不对。",
                ["生图", f"{r['rel']} · {r['w']}×{r['h']} · ${r['usd']:.2f}"], [], cny)
    if name == "make_music":
        say("正在配乐……")
        r = await make_music(args.get("prompt"), args.get("path"), args.get("seconds") or 60, say, stopped)
        return f"配乐好了：{r['rel']}（{mediainfo.clock(r['duration'] or 0)}，用了 {r['sec']:.0f} 秒）。", ["配乐", f"{r['rel']} · {mediainfo.clock(r['duration'] or 0)}"], [], 0.0
    raise workspace.Denied(f"没有这个工具：{name}")
