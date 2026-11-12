r"""发布到抖音（v3.2）：作者 11-13「Agent 平台多一个能力：自动发布抖音视频」，用开源的 social-auto-upload（MIT，抖音那部分随包在
vendor/social-auto-upload）。界面是「发布」窗口（ui/js/publish.js），Agent 也能用（publish_douyin 工具，默认关、默认要他点确认）。

- 登录：在「发布」窗口点「扫码登录」，二维码显示在窗口里，用抖音 App 扫。登录后的 cookie 加密存在 data\publish\douyin.cookie
  （Windows DPAPI，只有这个 Windows 账号解得开；不进仓库、不进压缩包、不进日志）。每次用时解到 data\publish\run\ 的临时文件，用完就删。
- 发一条：视频（工作区里的，或者他填的路径）、标题（最多 30 字）、简介、话题、封面（可选）、定时（至少 2 小时以后、14 天以内）、自主声明（默认「内容由AI生成」）、合集。
- 每次起一个子进程 app/douyin_run.py（python.exe + CREATE_NO_WINDOW，放进 Job Object：Agent 关了它也停），一次只做一件；
  到时间没完（登录 5 分钟、发布 45 分钟）就停掉。它的每一行进展显示在窗口里，要短信验证码时窗口里弹框（写进 run\verify_code.txt，原项目自己读）。
- 浏览器：他电脑上的 Chrome，没有就用 Edge（设置 › 发布 能指定）；不另外下浏览器，用的是临时的空白配置，不碰他自己的浏览器资料。
- 组件：patchright、loguru（写在 requirements.txt，启动.bat 自动装；没装上的话「发布」窗口里点一下装）。
- 记录：kv pub_hist（最近 100 条：标题、视频、什么时候、谁发的、结果）；Agent 交来的等他确认的在 kv pub_pending。动作日志记每一次发布。"""
import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from . import db, feed, mediainfo, paths, safety, settings, workspace

DIR = paths.DATA / "publish"
RUN = DIR / "run"
COOKIE = DIR / "douyin.cookie"
LOG = paths.LOGS / "publish.log"
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v", ".mkv", ".flv", ".avi", ".wmv"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
LIMIT = {"login": 300, "check": 180, "upload": 45 * 60, "selftest": 120}
DECL = ["内容由AI生成", "内容自行拍摄", "内容取材网络", "虚构演绎，仅供娱乐", "可能引人不适", "危险行为，请勿模仿"]
NAMES = {"login": "扫码登录", "check": "看登录还在不在", "upload": "发布", "selftest": "自检", "install": "装发布用的组件"}
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TITLE_MAX, DESC_MAX, TAG_MAX = 30, 1000, 10


def _log(text):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
    except OSError:
        pass


# ---------------- 准备好了没有 ----------------
def deps_ok():
    return all(importlib.util.find_spec(m) is not None for m in ("patchright", "loguru"))


def find_browser():
    """他电脑上的 Chrome，没有就 Edge；设置 › 发布 填了就用填的。"""
    c = str(settings.S.get("pubBrowser") or "").strip().strip('"')
    if c:
        return c if Path(c).exists() else ""
    if os.environ.get("AGENT_SAU_BROWSER"):
        return os.environ["AGENT_SAU_BROWSER"]
    if paths.IS_WIN:
        cands = []
        for b in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if b:
                cands.append(Path(b) / "Google" / "Chrome" / "Application" / "chrome.exe")
        for b in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            if b:
                cands.append(Path(b) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        return next((str(p) for p in cands if p.exists()), "")
    import shutil
    return next((w for w in (shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")) if w), "")


def console_python():
    """起子进程用的 Python：同一个环境里的 python.exe（不是 pythonw）。配上 CREATE_NO_WINDOW，它再起的驱动、浏览器都待在看不见的控制台里。"""
    exe = Path(sys.executable)
    c = exe.with_name("python.exe") if paths.IS_WIN else exe
    return str(c if c.exists() else exe)


# ---------------- 登录的 cookie（加密存） ----------------
def cookie_plain():
    """解开放到临时文件（子进程用），返回路径；没登录过返回一个不存在的路径。"""
    RUN.mkdir(parents=True, exist_ok=True)
    p = RUN / f"douyin_{int(time.time() * 1000)}.json"
    if COOKIE.exists():
        try:
            p.write_bytes(settings.unseal(COOKIE.read_bytes()))
        except Exception as e:
            _log(f"cookie 解不开（换了 Windows 账号？）：{e}")
    return p


def cookie_keep(p: Path):
    """子进程用完：里面有 sessionid 就重新加密存起来（登录、发布后抖音会刷新它）；临时文件删掉。"""
    try:
        if p.exists():
            raw = p.read_bytes()
            d = json.loads(raw.decode("utf-8"))
            if any(c.get("name") == "sessionid" and c.get("value") for c in d.get("cookies", [])):
                DIR.mkdir(parents=True, exist_ok=True)
                tmp = COOKIE.with_suffix(".tmp")
                tmp.write_bytes(settings.seal(raw))
                tmp.replace(COOKIE)
                return True
    except Exception as e:
        _log(f"cookie 没存上：{type(e).__name__}")
    finally:
        try:
            p.unlink()
        except OSError:
            pass
    return False


def clean_run():
    """上次 Agent 半路关了留下的明文 cookie、任务文件：删掉（启动时、每次开始前）。"""
    if RUN.exists():
        for x in list(RUN.glob("douyin_*.json")) + list(RUN.glob("job_*.json")):
            try:
                x.unlink()
            except OSError:
                pass


# ---------------- 一条要发的：检查 ----------------
def resolve_file(p, kinds, agent=False):
    s = str(p or "").strip().strip('"')
    if not s:
        raise ValueError("没给文件")
    q = Path(s)
    if not agent and q.is_absolute():
        rp = q
    else:
        try:
            rp = workspace.real(s, must_exist=True)
        except workspace.Denied as e:
            raise ValueError(str(e)) from None
    if not rp.is_file():
        raise ValueError(f"找不到这个文件：{s}")
    if rp.suffix.lower() not in kinds:
        raise ValueError(f"「{rp.name}」不是能用的格式（要 {'、'.join(sorted(kinds))}）")
    return rp


def parse_tags(t):
    if isinstance(t, list):
        items = t
    else:
        items = re.split(r"[\s,，、#＃]+", str(t or ""))
    out = []
    for x in items:
        x = re.sub(r"^[#＃]+", "", str(x or "").strip())[:20]
        if x and x not in out:
            out.append(x)
    return out[:TAG_MAX]


def check_item(body, agent=False):
    """把要发的一条整理好；不行就 ValueError（说清楚哪里不行）。"""
    f = resolve_file(body.get("file"), VIDEO_EXT, agent)
    title = re.sub(r"\s+", " ", str(body.get("title") or "")).strip()
    if not title:
        raise ValueError("标题没写")
    if len(title) > TITLE_MAX:
        raise ValueError(f"标题 {len(title)} 字：抖音最多 {TITLE_MAX} 字，多的会被它截掉，改短一点")
    desc = str(body.get("desc") or "").strip()
    if len(desc) > DESC_MAX:
        raise ValueError(f"简介最多 {DESC_MAX} 字")
    tags = parse_tags(body.get("tags"))
    sch = str(body.get("schedule") or "").strip().replace("T", " ")[:16]
    if sch:
        try:
            when = datetime.strptime(sch, "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError("定时发布的时间写成 2026-11-14 20:00 这样") from None
        if when < datetime.now() + timedelta(hours=2, minutes=1):
            raise ValueError("定时发布要在 2 小时以后（抖音的规矩）")
        if when > datetime.now() + timedelta(days=14):
            raise ValueError("定时发布最多 14 天以内")
    cover, kind = "", "portrait"
    if body.get("cover"):
        c = resolve_file(body.get("cover"), IMG_EXT, agent)
        info = mediainfo.probe(c)
        kind = "landscape" if (info.get("w") or 0) > (info.get("h") or 0) else "portrait"
        cover = str(c)
    decl = str(body.get("declaration") if body.get("declaration") is not None else settings.S.get("pubDecl") or DECL[0]).strip()
    if decl and decl not in DECL:
        raise ValueError("自主声明要是抖音上那几项之一：" + "、".join(DECL))
    info = mediainfo.probe(f)
    return {"file": str(f), "name": f.name, "size": f.stat().st_size, "dur": info.get("duration"), "w": info.get("w"), "h": info.get("h"),
            "title": title, "desc": desc, "tags": tags, "schedule": sch, "cover": cover, "cover_kind": kind,
            "declaration": decl, "collection": str(body.get("collection") or "").strip()[:40]}


def show_item(it):
    return {k: it.get(k) for k in ("file", "name", "size", "dur", "w", "h", "title", "desc", "tags", "schedule", "cover", "cover_kind", "declaration", "collection")} | {
        "file_show": paths.show(it.get("file") or ""), "cover_show": paths.show(it.get("cover") or "")}


# ---------------- 跑一件事 ----------------
class Pub:
    def __init__(self):
        self.job = None
        self.proc = None

    def busy(self):
        return bool(self.job and self.job["st"] == "run")

    def account(self):
        a = db.kv_get("pub_acct") or {}
        return {"has": COOKIE.exists(), "ok": a.get("ok") if COOKIE.exists() else False, "at": a.get("at"), "msg": a.get("msg", "")}

    def _acct(self, ok, msg):
        db.kv_set("pub_acct", {"ok": ok, "at": time.time(), "msg": msg})

    def start(self, kind, item=None, by="you", eid=None):
        if self.busy():
            raise HTTPException(409, f"正在{NAMES.get(self.job['kind'], '')}，等它好了（或者先点「停下」）")
        if kind != "install":
            if not deps_ok():
                raise HTTPException(400, "发布用的组件还没装（patchright、loguru）：点「装一下」，一两分钟")
            if not find_browser():
                raise HTTPException(400, "没找到 Chrome 或 Edge：到 设置 › 发布 填浏览器在哪")
            if kind in ("upload", "check") and not COOKIE.exists():
                raise HTTPException(400, "还没登录抖音：先点「扫码登录」")
        self.job = {"id": int(time.time() * 1000), "kind": kind, "st": "run", "msg": NAMES.get(kind, kind) + "：开始", "log": [], "qr": "", "sms": False,
                    "t0": time.time(), "t1": 0.0, "item": item, "by": by, "eid": eid, "stop": "", "ok": None}
        threading.Thread(target=self._run, args=(self.job,), daemon=True).start()
        feed.add(f"{NAMES.get(kind, kind)}" + (f"：{item['title']}" if item else ""), "info", job="发布", key="pub")
        return self.public()

    def _line(self, job, s):
        s = s.rstrip()
        if not s:
            return
        if s.startswith("@@J "):
            try:
                ev = json.loads(s[4:])
            except Exception:
                return
            t = ev.get("t")
            if t == "log":
                job["log"] = (job["log"] + [ev.get("msg", "")])[-60:]
                job["msg"] = ev.get("msg", "")
                _log(f"  {ev.get('msg', '')}")
            elif t == "qr":
                job["qr"] = ev.get("img") or ""
                job["msg"] = "用抖音 App 扫这个二维码（App 首页左上角 ≡ › 扫一扫）"
            elif t == "sms":
                job["sms"] = True
                job["msg"] = "抖音要短信验证码：手机收到后填在下面"
            elif t == "done":
                job["ok"] = bool(ev.get("ok"))
                job["result"] = ev.get("msg", "")
            return
        _log("  | " + s[:500])
        if re.search(r"Error|Traceback|错误", s):
            job["log"] = (job["log"] + [s[:300]])[-60:]

    def _run(self, job):
        kind = job["kind"]
        _log(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} {NAMES.get(kind, kind)}" + (f"：{job['item']['title']}" if job.get("item") else ""))
        if kind == "install":
            return self._install(job)
        clean_run()
        ck = cookie_plain()
        spec = {"cookie": str(ck), "base": str(RUN), "browser": find_browser(), "headless": bool(settings.S.get("pubHeadless", True))}
        spec.update(job.get("item") or {})
        jf = RUN / f"job_{job['id']}.json"
        jf.write_text(json.dumps(spec, ensure_ascii=False), "utf-8")
        try:
            (RUN / "verify_code.txt").unlink()
        except OSError:
            pass
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", DOUYIN_COOKIE_AUTH_HEADLESS="true")
        try:
            p = subprocess.Popen([console_python(), str(paths.ROOT / "app" / "douyin_run.py"), kind, str(jf)], cwd=str(paths.ROOT), env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=NOWIN)
        except OSError as e:
            job.update(st="err", msg=f"起不来：{e}", t1=time.time())
            cookie_keep(ck)
            jf.unlink(missing_ok=True)
            return
        self.proc = p
        try:
            from .setup import _in_job                      # Agent 关了，它也跟着停
            _in_job(p)
        except Exception:
            pass
        timer = threading.Timer(LIMIT.get(kind, 600), lambda: self._kill(job, f"超过 {LIMIT.get(kind, 600) // 60} 分钟还没完，停掉了"))
        timer.daemon = True
        timer.start()
        try:
            for raw in iter(p.stdout.readline, b""):
                self._line(job, raw.decode("utf-8", "replace"))
            p.wait()
        finally:
            timer.cancel()
            self.proc = None
            kept = cookie_keep(ck)
            jf.unlink(missing_ok=True)
        ok = bool(job.get("ok")) and p.returncode == 0 and not job["stop"]
        res = job.get("result") or ""
        job["qr"] = ""
        job["sms"] = False
        if job["stop"]:
            job.update(st="stop", msg=job["stop"])
        else:
            job.update(st="done" if ok else "err", msg=res or ("好了" if ok else f"没成（退出码 {p.returncode}），细节在 {paths.show(LOG)}"))
        job["t1"] = time.time()
        if kind in ("login", "check"):
            self._acct(ok, job["msg"])
        if kind == "login" and ok and not kept and not COOKIE.exists():
            job.update(st="err", msg="扫码好了，但没拿到登录信息（cookie 里没有 sessionid），再扫一次试试")
            self._acct(False, job["msg"])
        if kind == "upload":
            if not ok and re.search(r"cookie|登录|失效", job["msg"]):
                self._acct(False, "登录失效了，要重新扫码")
            elif ok:
                self._acct(True, "刚发过一条，登录有效")
            self._hist(job, ok)
        took = job["t1"] - job["t0"]
        _log(f"===== {job['st']}：{job['msg']}（{took:.0f} 秒）")
        feed.add(f"{NAMES.get(kind, kind)}：{job['msg']}", "ok" if ok else "warn", job="发布", key="pub")
        if kind == "upload" and ok:
            feed.done(f"发抖音 · {job['item']['title']}", "抖音", took, "", "publish")

    def _hist(self, job, ok):
        it = job["item"]
        h = db.kv_get("pub_hist") or []
        h.insert(0, {"id": job["id"], "ts": job["t0"], "title": it["title"], "file": it["name"], "schedule": it.get("schedule") or "", "st": job["st"],
                     "msg": job["msg"][:200], "sec": round(job["t1"] - job["t0"]), "by": job["by"], "tags": it.get("tags") or []})
        db.kv_set("pub_hist", h[:100])
        safety.log("publish.douyin", {"title": it["title"], "file": it["name"], "schedule": it.get("schedule") or "", "ok": ok, "by": job["by"]},
                   "agent" if job["by"] == "agent" else "user")

    def _install(self, job):
        """pip 装 patchright、loguru（先默认源，不行清华镜像）。"""
        py = console_python()
        for extra in ([], ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]):
            job["msg"] = "正在装 patchright、loguru（约 40MB）" + ("：换清华镜像再试" if extra else "")
            try:
                r = subprocess.run([py, "-m", "pip", "install", "patchright", "loguru", *extra], capture_output=True, text=True, errors="replace",
                                   timeout=900, creationflags=NOWIN, env=dict(os.environ, PIP_CACHE_DIR=str(paths.TOOLS / "cache" / "pip")))
                _log(r.stdout[-3000:] + r.stderr[-2000:])
                if r.returncode == 0:
                    importlib.invalidate_caches()
                    job.update(st="done", ok=True, msg="装好了", t1=time.time())
                    return
            except Exception as e:
                _log(f"pip 出错：{e}")
        job.update(st="err", ok=False, msg=f"没装上，多半是网络问题；细节在 {paths.show(LOG)}", t1=time.time())

    def _kill(self, job, why):
        p = self.proc
        if job is not self.job or not p or p.poll() is not None:
            return
        job["stop"] = why
        try:
            import psutil
            kids = psutil.Process(p.pid).children(recursive=True)
        except Exception:
            kids = []
        for x in [p] + kids:                                 # 只停自己开的：按进程号，连它开的驱动、浏览器
            try:
                x.kill()
            except Exception:
                pass

    def stop(self):
        if self.busy():
            self._kill(self.job, "你点了「停下」" + ("（抖音那边可能已经传了一部分，到抖音创作者中心看一眼）" if self.job["kind"] == "upload" else ""))
        return self.public()

    def code(self, c):
        c = re.sub(r"\D", "", str(c or ""))
        if not 4 <= len(c) <= 8:
            raise HTTPException(400, "验证码是 4~8 位数字")
        if not self.busy():
            raise HTTPException(409, "现在没有在等验证码")
        (RUN / "verify_code.txt").write_text(c, "utf-8")
        self.job["sms"] = False
        self.job["msg"] = "验证码交过去了"
        return self.public()

    def public(self):
        j = self.job
        if not j:
            return None
        out = {k: j.get(k) for k in ("id", "kind", "st", "msg", "qr", "sms", "by")}
        out["name"] = NAMES.get(j["kind"], j["kind"])
        out["log"] = j["log"][-14:]
        out["elapsed"] = round((j["t1"] or time.time()) - j["t0"])
        out["title"] = (j.get("item") or {}).get("title", "")
        return out


P = Pub()


# ---------------- Agent 交来的：等他确认 ----------------
def pending():
    return db.kv_get("pub_pending") or []


def ask(item, eid=None):
    lst = pending()
    pid = int(time.time() * 1000)
    lst.insert(0, {"id": pid, "ts": time.time(), "eid": eid, "item": item})
    db.kv_set("pub_pending", lst[:20])
    feed.add(f"Agent 想发一条抖音「{item['title']}」：到「发布」窗口看一眼，点「发布」才发", "warn", job="发布")
    return pid


def pending_act(pid, act, edits=None):
    lst = pending()
    it = next((x for x in lst if x["id"] == int(pid)), None)
    if not it:
        raise HTTPException(404, "没有这一条了")
    if act == "drop":
        db.kv_set("pub_pending", [x for x in lst if x["id"] != it["id"]])
        return status()
    if act != "ok":
        raise HTTPException(400, "act 是 ok 或 drop")
    item = it["item"]
    if edits:
        try:
            item = check_item({**item, **edits})
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    P.start("upload", item, by="agent", eid=it.get("eid"))
    db.kv_set("pub_pending", [x for x in lst if x["id"] != it["id"]])
    return status()


# ---------------- 给界面 ----------------
def recent_videos(n=12):
    """工作区里最近的视频（「发布」窗口左边点一下就选上）。"""
    try:
        base = workspace.folder()
    except Exception:
        return []
    out, seen = [], 0
    if not base.exists():
        return []
    for p in base.rglob("*"):
        seen += 1
        if seen > 20000:
            break
        if p.suffix.lower() in VIDEO_EXT and p.is_file() and not p.name.endswith(".part"):
            try:
                st = p.stat()
            except OSError:
                continue
            out.append((st.st_mtime, p, st.st_size))
    out.sort(key=lambda x: -x[0])
    return [{"path": str(p), "rel": workspace.rel(p), "name": p.name, "size": sz, "mtime": mt} for mt, p, sz in out[:n]]


def status():
    return {"ready": {"deps": deps_ok(), "browser": find_browser(), "vendor": (paths.ROOT / "vendor" / "social-auto-upload" / "uploader" / "douyin_uploader" / "main.py").exists()},
            "account": P.account(), "job": P.public(), "hist": (db.kv_get("pub_hist") or [])[:20],
            "pending": [{"id": x["id"], "ts": x["ts"], "eid": x.get("eid"), "item": show_item(x["item"])} for x in pending()],
            "videos": recent_videos(), "decls": DECL, "batch": B.public(),
            "opts": {"headless": bool(settings.S.get("pubHeadless", True)), "decl": settings.S.get("pubDecl") or DECL[0]},
            "agent": {"on": bool(settings.S.get("agPublish", False)), "ask": bool(settings.S.get("agPublishAsk", True))}}


# ---------------- Agent 的工具 ----------------
async def agent_publish(args, eid=None, say=None, stopped=None):
    if not settings.S.get("agPublish", False):
        raise workspace.Denied("发抖音他没让你用（设置 › Agent 能力 里「自己发抖音」关着）：做好的视频告诉他在哪，让他自己在「发布」窗口发")
    try:
        item = check_item(args, agent=True)
    except ValueError as e:
        raise workspace.Denied(str(e)) from None
    if not COOKIE.exists():
        raise workspace.Denied("抖音还没登录：请他在「发布」窗口点「扫码登录」")
    if settings.S.get("agPublishAsk", True):
        ask(item, eid)
        return {"asked": True, "title": item["title"]}
    if P.busy():
        raise workspace.Denied("「发布」那边正在做别的，等一会儿再发")
    try:
        P.start("upload", item, by="agent", eid=eid)
    except HTTPException as e:
        raise workspace.Denied(str(e.detail)) from None
    job = P.job
    while job["st"] == "run":
        await asyncio.sleep(2)
        if say:
            say(f"正在发抖音：{job['msg'][:60]}")
        if stopped and stopped():
            P.stop()
    return {"asked": False, "ok": job["st"] == "done", "msg": job["msg"], "title": item["title"], "sec": round(job["t1"] - job["t0"])}


# ---------------- 批量发布（v3.3）：一个文件夹（视频、封面）+ 一份清单，一条一条定时发 ----------------
LIST_EXT = {".md", ".markdown", ".txt"}
FIELDS = {"标题": "title", "视频": "video", "文件": "video", "封面": "cover", "简介": "desc", "描述": "desc", "文案": "desc", "话题": "tags", "标签": "tags",
          "定时": "schedule", "时间": "schedule", "发布时间": "schedule", "定时发布": "schedule", "合集": "collection", "声明": "declaration", "自主声明": "declaration"}


def bat_folder(s):
    s = str(s or "").strip().strip('"')
    if not s:
        raise HTTPException(400, "填放视频和封面的那个文件夹（完整路径，或者工作区里的）")
    q = Path(s)
    if not q.is_absolute():
        try:
            q = workspace.real(s, must_exist=True)
        except workspace.Denied as e:
            raise HTTPException(400, str(e)) from None
    if not q.is_dir():
        raise HTTPException(400, f"找不到这个文件夹：{s}")
    return q


def scan_folder(d):
    """文件夹里的视频、图片、清单（往下一层的子文件夹也看；「旧版」不看）。"""
    out = {"video": [], "img": [], "list": []}
    subs = [d] + sorted(x for x in d.iterdir() if x.is_dir() and x.name != "旧版")[:30]
    for sd in subs:
        for p in sorted(sd.iterdir()):
            e = p.suffix.lower()
            k = "video" if e in VIDEO_EXT else "img" if e in IMG_EXT else "list" if e in LIST_EXT else ""
            if k and p.is_file() and len(out[k]) < 300:
                out[k].append(p)
    return out


def read_text(p):
    raw = p.read_bytes()[:400_000]
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def _key(s):
    return re.sub(r"[\s_\-—·.,，、()（）\[\]【】]+", "", Path(str(s)).stem).lower()


def _num(s):
    m = re.search(r"\d+", Path(str(s)).stem)
    return int(m.group()) if m else None


def match(name, pool, d):
    """清单里写的名字 → 文件夹里的文件：一模一样 > 去掉扩展名、空格、下划线一样 > 只有一个包含它 > 只有一个同序号。"""
    n = str(name or "").strip().strip('"').replace("\\", "/")
    if not n:
        return None
    for p in pool:
        if p.name.lower() == n.split("/")[-1].lower() or str(p.relative_to(d)).replace("\\", "/").lower() == n.lower():
            return p
    k = _key(n)
    if not k:
        return None
    for p in pool:
        if _key(p.name) == k:
            return p
    c = [p for p in pool if len(k) >= 2 and len(_key(p.name)) >= 2 and (k in _key(p.name) or _key(p.name) in k)]
    if len(c) == 1:
        return c[0]
    num = _num(n)
    c = [p for p in pool if num is not None and _num(p.name) == num]
    return c[0] if len(c) == 1 else None


def auto_cover(video, imgs):
    """清单没写封面：找和视频同名（或者「同名_封面」）的图，再不行同序号、名字里有「封面」的。"""
    k = _key(video.name)
    c = [p for p in imgs if _key(p.name) == k or (_key(p.name).startswith(k) and "封面" in p.stem) or (_key(p.name) == k + "cover")]
    if len(c) == 1:
        return c[0]
    num = _num(video.name)
    c = [p for p in imgs if num is not None and _num(p.name) == num and ("封面" in p.stem or "cover" in p.stem.lower())]
    return c[0] if len(c) == 1 else None


def norm_when(s):
    """「2026/11/14 20:00」「11月14日 20点」「2026-11-14T20:00:00」→ 2026-11-14 20:00（换不了就原样，检查时会说）。"""
    s = str(s or "").strip()
    m = re.search(r"(?:(\d{4})\s*[-/.年]\s*)?(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*[日号]?\s*[T\s]*\D{0,4}?(\d{1,2})\s*[:：点时](?:\s*(\d{1,2}))?", s)
    if not m:
        return s
    now = datetime.now()
    h = int(m.group(4))
    if re.search(r"晚|下午|PM", s, re.I) and h < 12:
        h += 12
    try:
        dt = datetime(int(m.group(1) or now.year), int(m.group(2)), int(m.group(3)), h, int(m.group(5) or 0))
    except ValueError:
        return s
    if not m.group(1) and dt < now - timedelta(days=1):
        dt = dt.replace(year=dt.year + 1)
    return dt.strftime("%Y-%m-%d %H:%M")


def parse_pub(text):
    """不用 DeepSeek 时认的固定写法：每条「## 标题」开头，下面「视频：」「封面：」「简介：」「话题：」「定时：」「合集：」「声明：」。"""
    items, cur, title, key = [], None, "", None
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        x = raw.strip()
        m = re.match(r"^(#{1,6})\s*(.+)$", x)
        if m:
            if len(m.group(1)) == 1 and cur is None:
                title = m.group(2).strip()
            else:
                cur = {"title": m.group(2).strip(), "desc": ""}
                items.append(cur)
                key = None
            continue
        if cur is None or not x:
            continue
        m = re.match(r"^[-*·]?\s*([^\s：:]{1,6})\s*[：:]\s*(.*)$", x)
        if m and m.group(1) in FIELDS:
            key = FIELDS[m.group(1)]
            v = m.group(2).strip()
            cur[key] = (cur.get(key, "") + "\n" + v).strip() if key == "desc" else v
        elif key == "desc":
            cur["desc"] = (cur["desc"] + "\n" + x).strip()
    return {"title": title, "items": items}


class PubBatch:
    def __init__(self):
        self.board = db.kv_get("pub_batch") or None
        self.running = False
        self.halt = ""
        if self.board:                                  # 上次半路关了：没发完的回到待发
            for it in self.board["items"]:
                if it["st"] in ("queue", "run"):
                    it.update(st="idle", msg="")

    def _save(self):
        db.kv_set("pub_batch", self.board)

    def public(self):
        if not self.board:
            return None
        return dict(self.board, running=self.running, halt=self.halt)

    def _body(self, it):
        if not it.get("video"):
            raise ValueError(f"文件夹里没找到视频「{it.get('video_raw') or '（清单没写）'}」")
        if not str(it.get("schedule") or "").strip():
            raise ValueError("没写定时发布的时间（批量的都定时发）")
        return check_item({"file": it["video"], "title": it.get("title"), "desc": it.get("desc"), "tags": it.get("tags"), "schedule": it.get("schedule"),
                           "cover": it.get("cover") or "", "collection": it.get("collection"), "declaration": it.get("declaration") or None})

    def _recheck(self, it):
        try:
            self._body(it)
            it.update(st="idle" if it["st"] != "ok" else "ok", err="")
        except ValueError as e:
            if it["st"] != "ok":
                it.update(st="err", err=str(e))

    async def load(self, body):
        if self.running:
            raise HTTPException(409, "正在一条一条发，先点「停下」")
        d = bat_folder(body.get("folder"))
        found = scan_folder(d)
        files = [f for f in (body.get("files") or []) if str(f.get("text") or "").strip()]
        if not files:
            files = [{"name": p.name, "text": read_text(p)} for p in found["list"][:6]]
        if not files:
            raise HTTPException(400, "没有清单：选一份 .md / .txt，或者把它放进这个文件夹")
        notes = []
        if body.get("smart"):
            from . import smartlist
            rel = lambda p: str(p.relative_to(d)).replace("\\", "/")
            ctx = ("文件夹里的文件：\n视频：" + "、".join(rel(p) for p in found["video"]) + "\n图片：" + "、".join(rel(p) for p in found["img"]))[:20000]
            j, _, cny = await smartlist.ask("pub", files, ctx)
            raws, title = j["items"], j.get("title") or ""
            notes.append(f"DeepSeek 帮你认的（¥{cny:.3f}）：发之前看一眼每一条对不对")
            notes += [str(x)[:200] for x in (j.get("notes") or []) if str(x).strip()][:8]
        else:
            raws, title = [], ""
            for f in files:
                p = parse_pub(f["text"])
                raws += p["items"]
                title = title or p["title"]
            if not raws:
                raise HTTPException(400, "没认出要发的：每条用「## 标题」开头，下面写 视频： 封面： 简介： 话题： 定时：（或者打开「DeepSeek 帮我认」）")
        items = []
        for i, r in enumerate(raws[:50], 1):
            v = match(r.get("video") or r.get("file"), found["video"], d) or (match(r.get("title"), found["video"], d) if not r.get("video") else None)
            c = match(r.get("cover"), found["img"], d) if r.get("cover") else (auto_cover(v, found["img"]) if v else None)
            if r.get("cover") and not c:
                notes.append(f"第 {i} 条的封面「{r['cover']}」文件夹里没找到，先不放封面")
            it = {"id": f"p{i}", "title": re.sub(r"\s+", " ", str(r.get("title") or "")).strip(), "desc": str(r.get("desc") or "").strip(),
                  "tags": parse_tags(r.get("tags")), "schedule": norm_when(r.get("schedule")), "collection": str(r.get("collection") or "").strip()[:40],
                  "declaration": str(r.get("declaration") or "").strip(), "video_raw": str(r.get("video") or "")[:120],
                  "video": str(v) if v else "", "cover": str(c) if c else "", "st": "idle", "err": "", "msg": ""}
            it["video_show"] = v.name if v else ""
            it["cover_show"] = c.name if c else ""
            self._recheck(it)
            items.append(it)
        self.halt = ""
        self.board = {"id": int(time.time() * 1000), "title": title or d.name, "folder": str(d), "folder_show": paths.show(str(d)), "warn": notes,
                      "lists": [f.get("name") or "" for f in files], "smart": bool(body.get("smart")), "items": items,
                      "nv": len(found["video"]), "ni": len(found["img"])}
        self._save()
        ok = sum(1 for x in items if x["st"] == "idle")
        feed.add(f"认了一批要发的「{self.board['title']}」：{len(items)} 条，能发 {ok} 条", "info", job="发布", key="pubb")
        return self.public()

    def start(self):
        if self.running:
            raise HTTPException(409, "已经在发了")
        if not self.board:
            raise HTTPException(400, "先认一批")
        if P.busy():
            raise HTTPException(409, "「发布」那边正在做别的，等它好了")
        if not COOKIE.exists():
            raise HTTPException(400, "还没登录抖音：先在右边扫码登录")
        for it in self.board["items"]:
            self._recheck(it)
        todo = [it for it in self.board["items"] if it["st"] == "idle"]
        if not todo:
            raise HTTPException(400, "没有能发的（标红的那几条看一下哪里不对）")
        for it in todo:
            it.update(st="queue", msg="")
        self.running, self.halt = True, ""
        self._save()
        threading.Thread(target=self._loop, args=(todo,), daemon=True).start()
        return self.public()

    def _loop(self, todo):
        n_ok = 0
        try:
            for it in todo:
                if self.halt:
                    it.update(st="idle", msg="")
                    continue
                try:
                    item = self._body(it)
                    it.update(st="run", msg="开始发")
                    self._save()
                    P.start("upload", item, by="batch")
                except (ValueError, HTTPException) as e:
                    it.update(st="err", err=str(getattr(e, "detail", e)))
                    self._save()
                    continue
                job = P.job
                while job["st"] == "run":
                    time.sleep(1)
                    it["msg"] = str(job.get("msg") or "")[:80]
                if job["st"] == "done":
                    it.update(st="ok", msg=job["msg"][:120], err="")
                    n_ok += 1
                else:
                    it.update(st="idle" if job["st"] == "stop" else "err", err="" if job["st"] == "stop" else job["msg"][:200], msg="")
                    if re.search(r"cookie|登录|失效", job["msg"]):
                        self.halt = "抖音登录失效了：右边重新扫码，再点「接着发」"
                self._save()
                if not self.halt:
                    time.sleep(3)
        finally:
            self.running = False
            self._save()
            left = sum(1 for x in todo if x["st"] != "ok")
            feed.add(f"批量发抖音：发了 {n_ok} 条" + (f"，还有 {left} 条没发" if left else "") + (f"（{self.halt}）" if self.halt else ""), "ok" if not left else "warn", job="发布", key="pubb")

    def stop(self):
        if self.running:
            self.halt = "停下了：没发的还在，点「接着发」继续"
            if P.busy() and P.job.get("by") == "batch":
                P.stop()

    def clear(self):
        if self.running:
            raise HTTPException(409, "正在发，先点「停下」")
        self.board = None
        db.kv_set("pub_batch", None)


B = PubBatch()


# ---------------- 接口 ----------------
api = APIRouter()
clean_run()


@api.get("/api/publish")
def pub_status():
    return status()


@api.post("/api/publish/login")
def pub_login():
    P.start("login")
    return status()


@api.post("/api/publish/check")
def pub_check():
    P.start("check")
    return status()


@api.post("/api/publish/logout")
def pub_logout():
    if P.busy():
        raise HTTPException(409, "正在用登录信息，先等它做完或者点「停下」")
    try:
        COOKIE.unlink()
    except FileNotFoundError:
        pass
    db.kv_set("pub_acct", {"ok": False, "at": time.time(), "msg": "退出了"})
    safety.log("publish.logout", {"site": "douyin"}, "user")
    return status()


@api.post("/api/publish/go")
def pub_go(body: dict = Body(...)):
    try:
        item = check_item(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    P.start("upload", item)
    return status()


@api.post("/api/publish/code")
def pub_code(body: dict = Body(...)):
    P.code(body.get("code"))
    return status()


@api.post("/api/publish/stop")
def pub_stop():
    P.stop()
    return status()


@api.post("/api/publish/pending/{pid}")
def pub_pending(pid: int, body: dict = Body(default={})):
    return pending_act(pid, body.get("act") or "", body.get("edits"))


@api.post("/api/publish/install")
def pub_install():
    if deps_ok():
        return status()
    P.start("install")
    return status()


@api.post("/api/publish/selftest")
def pub_selftest():
    P.start("selftest")
    return status()


@api.post("/api/publish/preview")
def pub_preview(body: dict = Body(...)):
    """发之前先看一下整理好的样子（标题字数、话题、定时对不对）；不行就 400 说哪里不行。"""
    try:
        return {"item": show_item(check_item(body))}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@api.get("/api/publish/media")
def pub_media(path: str):
    """「发布」窗口里预览要发的视频、封面（只给视频和图片）。"""
    try:
        p = resolve_file(path, VIDEO_EXT | IMG_EXT)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@api.post("/api/publish/batch/load")
async def pub_batch_load(body: dict = Body(...)):
    await B.load(body)
    return status()


@api.post("/api/publish/batch/run")
def pub_batch_run():
    B.start()
    return status()


@api.post("/api/publish/batch/stop")
def pub_batch_stop():
    B.stop()
    return status()


@api.post("/api/publish/batch/clear")
def pub_batch_clear():
    B.clear()
    return status()
