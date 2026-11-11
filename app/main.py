"""主后端：界面 + 所有接口 + 后台任务。
启动.bat 用 pythonw 跑 app/launch.py（没有黑窗口，起不来会弹框），它再调这里的 run()；
排查问题时 `启动.bat 看日志` 或 python -m app.main 还是在黑窗口里跑。
只监听本机 127.0.0.1:8765，别的电脑访问不到。"""
import asyncio
import contextlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import (agent, agentkit, agentstate, autostart, bgm, ccode, checks, db, deepseek, docs, events, exam, feed, files, growth, hw, hwctl, imagegen, memory,
               monitor, nightly, osd, paths, reminders, reports, router, safety, settings, setup, tts, tts_install, voice, websearch, workspace)
from .models import M
from .qq import BOT

VERSION = "3.0.0"
PORT = 8765
_bg = []


def _restart_keys(ch):
    return any(k in ch for k in ("modelPort", "baseQuant", "baseDir", "embedDir", "loraDir", "idleUnload", "aiPython"))


@settings.on_change
def _on_settings(ch):
    loop = asyncio.get_event_loop()
    if _restart_keys(ch):
        loop.create_task(M.restart_server())
    if any(k in ch for k in ("qqAppId", "qqSecret", "qqSandbox", "qqEnabled")):
        loop.create_task(BOT.restart())
    if ch.get("kevMode") == "off":
        M.kevp.stop()
    if "ttsPort" in ch or "ttsPython" in ch:
        tts.T.stop("配音设置改了")
    if any(k in ch for k in ("bgmUrl", "bgmDir")):
        bgm.B.stop("配乐设置改了")
    if any(k in ch for k in ("voiceUrl", "voiceDir", "voiceModel", "voicePython")):
        voice.V.stop("语音设置改了")
    if "memDir" in ch or "useGit" in ch:
        memory.init()
    if ch.get("quiet") is False:      # 关掉免打扰：把攒着的消息一起发
        from . import notify
        loop.create_task(notify.flush_held())


_seen = {}


def _watch(name, state, msgs):
    """各个服务的状态一变，就在进展报告里写一句（不变就不写）。"""
    old = _seen.get(name)
    _seen[name] = state
    if old is None or old == state:
        return
    text, kind = msgs.get(state, (None, None))
    if text:
        feed.add(text, kind, job=name)


async def housekeeping():
    n, last_try = 0, 0.0
    while True:
        try:
            # 本地模型环境装好了但服务没在跑：自动拉起（失败了 5 分钟后再试）
            if n % 15 == 3 and M.ai_ready() and not M.server.alive() and not M._health and time.time() - last_try > 300:
                last_try = time.time()
                feed.add("本地模型服务没在运行，自动启动它", "info", job="本地模型服务")
                with contextlib.suppress(Exception):
                    M.start_server()
            if n % 30 == 7 and settings.S["kevMode"] == "resident" and M.kev_installed() and not M.kevp.alive() and not M.yielding:
                with contextlib.suppress(Exception):
                    M.start_kev()
            data = await hw.sample()
            M.tick(data)
            tts.T.tick()                          # 配音服务：让路时关掉、闲置久了关掉
            bgm.B.tick()                          # 配乐服务（ACE-Step）、语音服务（Breeze TTS 2）：一样的规矩
            voice.V.tick()
            if n % 15 == 0 and M._health:
                await router.embed_missing()
            if n % 150 == 5 and M._health:
                await memory.index()
            if n % 30 == 10:
                await agent.process_queue()
            if n % 5 == 0:
                h = await M.health(fresh=True)
                _watch("本地模型服务", "ok" if h and not h.get("error") else "bad" if h else "off",
                       {"ok": ("本地模型服务在线了" + ("，嵌入模型已加载" if h and h.get("embed_loaded") else ""), "ok"),
                        "bad": (f"本地模型服务出错：{((h or {}).get('error') or '')[:120]}", "err"),
                        "off": ("本地模型服务停了", "warn")})
                if M._kev_ts:
                    _watch("Kev", "ok" if M._kev_ok else "off", {"ok": ("Kev 在线了", "ok"), "off": ("Kev 停了", "warn")})
                _watch("QQ 通道", _seen.get("QQ 通道") if BOT.status == "connecting" else BOT.status, {"online": ("QQ 通道连上了", "ok"), "error": (f"QQ 通道出错：{BOT.detail}", "err"),
                                               "off": ("QQ 通道断开了", "warn")})
            if n % 5 == 2 and settings.S["kevMode"] != "off":
                asyncio.get_event_loop().create_task(M.kev_ready())   # 不等它，免得卡住别的
            if n % 15 == 1:
                await deepseek.balance_tick(n)
                monitor.beat()                    # 运行标记：每半分钟写一次"还活着"
            if n % 60 == 30:
                await growth.tick()
            if n % 2 == 1:
                osd.ctl().tick()                      # 游戏内显示：设置里开了就拉起小框，关了就停
            hwctl.tick(n)                             # 硬件监控助手：开关开着、没在跑就拉起来（不弹管理员确认）
        except Exception as e:
            print("后台照看出错：", e)
        n += 1
        await asyncio.sleep(2)


async def live_checks():
    """会自己变的几项（本地模型环境、模型服务、Kev、硬件监控助手、QQ、DeepSeek）：启动后头两分钟每 10 秒、之后每 30 秒重查一次，
    写回自检结果，整备和「一键补齐」的每一步跟着变（界面轮询 /api/state 看到 prep.ts 变了就刷新）。"""
    n, settled = 0, False
    while True:
        await asyncio.sleep(10 if n < 12 else 30)
        n += 1
        with contextlib.suppress(Exception):
            await checks.refresh_live()
        if not settled and not checks.booting():      # 开机缓冲结束：还在「启动中」的再查一遍，日志里写一句整备情况
            settled = True
            with contextlib.suppress(Exception):
                await checks.after_boot()


@contextlib.asynccontextmanager
async def lifespan(app):
    monitor.tee_console()
    asyncio.get_running_loop().set_exception_handler(monitor.quiet_handler)
    settings.load()
    db.conn()
    feed.load()
    monitor.report_last_exit()
    write_themes_js()
    with contextlib.suppress(Exception):
        docs.tidy_old()
        docs.generate(app, VERSION, theme_list())      # docs/AI文档/当前结构.md：每次启动按代码重写
    with contextlib.suppress(Exception):
        await asyncio.to_thread(setup.cleanup_orphans)
    with contextlib.suppress(Exception):
        await asyncio.to_thread(M.cleanup_orphans)      # 上次留下的模型服务、Kev、游戏内小框：先停掉，免得端口被占
    memory.init()
    router.seed_examples()
    router.MEM.load()
    reminders.seed()
    if M.ai_ready():
        try:
            M.start_server()
        except Exception as e:
            print("本地模型服务没起来：", e)
    if settings.S["qqEnabled"] and BOT.configured():
        BOT.start()
    for fn in (reminders.loop, nightly.loop, housekeeping, live_checks, workspace.loop):
        _bg.append(asyncio.get_event_loop().create_task(fn()))
    if os.environ.get("AGENT_OPEN_UI") == "1":
        _bg.append(asyncio.get_event_loop().create_task(_open_later()))
    print(f"\n  Agent 已启动：http://127.0.0.1:{PORT}\n  文件夹：{paths.show(paths.ROOT)}\n")
    yield
    for t in _bg:
        t.cancel()
    await BOT.stop()
    M.stop_all()
    with contextlib.suppress(Exception):
        osd.ctl().stop()


app = FastAPI(title="Agent", lifespan=lifespan)
app.include_router(tts.api)                       # 配音页的接口（app/tts.py）
app.include_router(tts_install.api)               # 设置 › 本地模型 的「安装配音」（app/tts_install.py）
app.include_router(imagegen.api)                  # 「生图」页的接口（app/imagegen.py，v1.8.15）
app.include_router(autostart.api)                 # 设置 › 自动化 的「开机自启」（app/autostart.py）
app.include_router(bgm.api)                       # 「配乐」的接口（app/bgm.py，v3.0）
app.include_router(voice.api)                     # 语音对话的接口（app/voice.py，v3.0）
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}", "127.0.0.1", "localhost"}


@app.middleware("http")
async def guard(request, call_next):
    """只接受本机地址（防 DNS 重绑定）；改东西的请求必须带 X-Agent 头（别的网页发不出这个头，防跨站请求）。"""
    if request.headers.get("host", "") not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "只接受本机访问"}, status_code=403)
    if request.method in ("POST", "PUT", "DELETE") and request.headers.get("x-agent") != "1":
        return JSONResponse({"detail": "缺少 X-Agent 头"}, status_code=403)
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"   # 界面文件每次都核对一下，更新后不用清缓存
    return resp


@app.get("/")
def index():
    return FileResponse(paths.UI / "index.html", headers={"Cache-Control": "no-store"})


# ---------------- 主题：ui/themes 里一个 .css 就是一套 ----------------
_META = re.compile(r"@(id|name|desc|order|fx|retired)[ \t]+([^\n]*)")


def theme_list():
    out = []
    for p in sorted((paths.UI / "themes").glob("*.css")):
        try:
            head = p.read_text("utf-8", errors="replace")[:2000]
        except Exception:
            continue
        m = re.search(r"/\*(.*?)\*/", head, re.S)
        meta = {}
        for k, v in _META.findall(m.group(1) if m else ""):
            meta.setdefault(k, v.strip())
        tid = meta.get("id") or p.stem
        if meta.get("retired"):                  # 停用的旧主题（v2.0 换成极简深 / 浅两套）：文件留着，不再列出来
            continue
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", tid):
            continue
        order = meta.get("order", "")
        fx = [x for x in re.split(r"[\s,，]+", meta.get("fx", "")) if re.fullmatch(r"[a-z][a-z0-9-]{0,20}", x)]
        out.append({"id": tid, "name": meta.get("name") or tid, "desc": meta.get("desc", ""), "file": p.name,
                    "order": int(order) if order.isdigit() else 99, "v": int(p.stat().st_mtime), "fx": fx})
    out.sort(key=lambda t: (t["order"], t["id"]))
    return out


def themes_js():
    return ("/* 自动生成：Agent 启动时扫描 ui\\themes 里的 .css 文件写出这份清单（直接双击 index.html 看演示时也用它）。\n"
            "   不用手改：往 themes 文件夹放一个新的 .css，刷新界面就会出现在 设置 › 外观 里。 */\n"
            f"window.AGENT_THEMES = {json.dumps(theme_list(), ensure_ascii=False)};\n"
            "(function () { var t = window.AGENT_THEMES; for (var i = 0; i < t.length; i++) "
            "document.write('<link rel=\"stylesheet\" href=\"themes/' + t[i].file + '?v=' + t[i].v + '\">'); })();\n")


def write_themes_js():
    with contextlib.suppress(Exception):
        p = paths.UI / "themes" / "themes.js"
        js = themes_js()
        if not p.exists() or p.read_text("utf-8") != js:
            p.write_text(js, "utf-8")


@app.get("/themes/themes.js")
def get_themes_js():
    return Response(themes_js(), media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/api/ping")
def ping():
    return {"ok": True, "version": VERSION, "root": paths.show(paths.ROOT), "windows": paths.IS_WIN}


# ---------------- 设置 ----------------
@app.get("/api/settings")
def get_settings():
    return {"settings": settings.S, "secrets": settings.secret_hints(), "places": checks.places(), "safety": safety.safety_view(),
            "ds_models": db.kv_get("ds_models"),
            "locked": list(settings.LOCKED), "secure": settings.is_secure()}


@app.put("/api/settings")
async def put_settings(changes: dict = Body(...)):
    return {"applied": settings.update(changes)}


@app.put("/api/secrets")
async def put_secret(body: dict = Body(...)):
    k, v = body.get("k"), body.get("v", "")
    if k not in settings.SECRET_KEYS:
        raise HTTPException(400, "不认识的密钥")
    settings.set_secret(k, v)
    if k == "dsKey":
        with contextlib.suppress(Exception):
            await deepseek.refresh_balance(force=True)
    return {"hints": settings.secret_hints()}


@app.post("/api/safety")
def set_safety(body: dict = Body(...)):
    try:
        safety.set_group(body.get("group"), body.get("value"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    safety.log("safety.set", body, "user")
    return safety.safety_view()


@app.get("/api/export")
def export():
    return {"app": "agent-shell", "v": 3, "set": {k: v for k, v in settings.S.items()}, "safety": safety.safety_view(),
            "reminders": reminders.all_reminders()}


@app.post("/api/import")
async def import_(body: dict = Body(...)):
    if body.get("app") != "agent-shell":
        raise HTTPException(400, "不是本界面导出的设置")
    applied = settings.update(body.get("set") or {})
    for g, v in (body.get("safety") or {}).items():
        with contextlib.suppress(Exception):
            safety.set_group(g, v)
    return {"applied": applied}


# ---------------- 状态 ----------------
@app.get("/api/state")
async def state():
    return await reports.state()


@app.get("/api/tasks")
def get_tasks():
    return {"tasks": reports.tasks()}


@app.get("/api/osd")
def osd_state():
    return osd.state()


@app.get("/api/agent")
async def agent_state():
    return await agentstate.view()


@app.post("/api/agent/restart/{k}")
async def agent_restart(k: str):
    """Agent 状态里「卡住了」的那一项点「重启」：只重启我们自己开的进程（按 PID 停）。"""
    if k == "model":
        await M.restart_server()
    elif k == "kev":
        M.kevp.stop()
        await M.ensure_kev(wait=False)
    elif k == "qq":
        await BOT.restart()
    elif k == "osd":
        osd.ctl().proc.stop()          # 后台每 4 秒看一眼，没在跑就拉起来
    else:
        raise HTTPException(404, "这一项不能从这里重启")
    name = {"model": "本地模型服务", "kev": "Kev", "qq": "QQ 通道", "osd": "游戏内显示"}[k]
    feed.add(f"你在 Agent 状态里点了重启：{name}", job="Agent 状态")
    return {"ok": True, "msg": f"重启了{name}，等一会儿就好"}


@app.get("/api/hw")
async def get_hw():
    return await hw.sample()


@app.get("/api/hw/history")
def get_hw_history():
    return hw.HIST


@app.get("/api/models")
async def models():
    return await M.status()


@app.get("/api/brains")
async def brains():
    await M.health()
    return reports.brains_view()


@app.get("/api/report")
def report():
    return reports.report()


@app.get("/api/wishes")
def wishes():
    """你问过「能不能加这个功能」的那些（最新的在前），开发时看。"""
    return list(reversed(db.kv_get("wishes", []) or []))


# ---------------- 事件 ----------------
@app.get("/api/events")
def list_events(limit: int = 60):
    return events.recent(min(limit, 300))


@app.get("/api/events/{eid}")
def get_event(eid: int):
    e = events.get(eid)
    if not e:
        raise HTTPException(404, "没有这条事件")
    return e


@app.post("/api/events/{eid}/fix")
async def fix_event(eid: int, body: dict = Body(...)):
    to = body.get("to")
    e = db.one("SELECT * FROM events WHERE id=?", (eid,))
    if not e:
        raise HTTPException(404, "没有这条事件")
    if to is None:
        db.update("events", eid, {"fix": None})
        db.run("DELETE FROM examples WHERE event_id=? AND source='fix'", (eid,))
        router.MEM.load()
        return events.get(eid)
    if to not in ("local", "neu", "ds", "cl"):
        raise HTTPException(400, "去向不对")
    await _apply_fix(e, to)
    return events.get(eid)


async def _apply_fix(e, to):
    """记一次纠正：这条应该交给 to。纠正立刻变成新判例，下次决策脑就参考它。"""
    db.update("events", e["id"], {"fix": to})
    vec = await M.embed([e["text"]])
    router.add_example(e["text"], to, "fix", bool(e["private"]), e["id"], vec[0] if vec else None)
    safety.log("route.fix", {"event": e["id"], "to": to}, "user")


@app.post("/api/events/{eid}/redo")
async def redo_event(eid: int, body: dict = Body(...)):
    """换它重做：觉得决策脑判得不对，同一句话按你指定的去向再处理一遍（也记一次纠正）。
    隐私的事改派到云端：不带 allow_private 就回 409，界面先问你，确认了再发。返回 token，和异步发消息一样查进度。"""
    to = body.get("to")
    if to not in ("local", "neu", "ds", "cl"):
        raise HTTPException(400, "去向不对")
    e = db.one("SELECT * FROM events WHERE id=?", (eid,))
    if not e:
        raise HTTPException(404, "没有这条事件")
    allow = bool(body.get("allow_private"))
    if e["private"] and to != "local" and not allow:
        raise HTTPException(409, "这件事标了隐私，交给云端会发出本机，要你确认")
    await _apply_fix(e, to)
    imgs = [{"path": r["path"]} for r in db.q("SELECT path FROM chat_files WHERE event_id=? AND kind='img'", (eid,)) if Path(r["path"]).is_file()]
    return _start_job(e["text"], force=to, allow_private=allow, redo_of=eid, images=imgs or None)


CHAT_JOBS = {}


def _start_job(text, **kw):
    for k in [k for k, j in CHAT_JOBS.items() if time.time() - j["ts"] > 900]:
        CHAT_JOBS.pop(k, None)
    token = os.urandom(6).hex()
    job = CHAT_JOBS[token] = {"ts": time.time(), "eid": None, "done": False, "event": None, "err": None}

    async def run():
        try:
            job["event"] = await agent.handle(text, "ui", "me", job=job, **kw)
        except router.NeedConfirm as e:
            job["err"] = str(e)
            job["confirm"] = True
        except Exception as e:
            job["err"] = str(e)[:200]
        job["done"] = True
    asyncio.get_event_loop().create_task(run())
    return {"token": token}


@app.post("/api/chat")
async def chat(body: dict = Body(...)):
    """界面上发消息。带 async=true 时马上返回一个 token，界面拿它每半秒来问一次进度（/api/chat/{token}），
    处理到哪一步（决策脑、查说明书、联网搜索、读网页……）就能实时显示；不带就等处理完再返回（旧用法）。"""
    text = (body.get("text") or "").strip()
    raw = body.get("images") or []
    if not isinstance(raw, list) or len(raw) > files.MAX_UPLOADS:
        raise HTTPException(400, f"一次最多带 {files.MAX_UPLOADS} 张图片")
    got = await asyncio.to_thread(workspace.received, body.get("files") if isinstance(body.get("files"), list) else [])   # v2.2：先传好的文件
    if not text and not raw and not got:
        raise HTTPException(400, "空消息")
    try:
        imgs = [files.save_upload(u, k) for k, u in enumerate(raw)]      # 先存进 data\chat（聊天记录里显示、重做时再用）
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    text = text or ("看看这张图。" if raw else "收到这些文件，先放在工作区。")
    force = body.get("force") if body.get("force") in ("local", "neu", "ds", "cl") else None   # 你指定交给谁（留的口子）
    kw = {"force": force, "allow_private": bool(body.get("allow_private")), "images": imgs or None, "received": got or None}
    if not body.get("async"):
        try:
            return await agent.handle(text, "ui", "me", **kw)
        except router.NeedConfirm as e:
            raise HTTPException(409, str(e)) from None
    return _start_job(text, **kw)


@app.post("/api/ws/recvdir")
async def ws_recvdir(body: dict = Body(...)):
    """整个文件夹拖进来（v2.3）：先建好 收到的\\日期\\文件夹名（重名加序号），返回它的相对路径；里面的文件再一个个传（/api/ws/upload 带 into、sub）。"""
    try:
        d = await asyncio.to_thread(workspace.recv_dir, body.get("name"))
    except OSError as e:
        raise HTTPException(400, f"工作文件夹用不了：{e}") from None
    return {"rel": workspace.rel(d), "name": d.name}


@app.post("/api/ws/upload")
async def ws_upload(request: Request, name: str = "", into: str = "", sub: str = ""):
    """对话里拖进来、粘贴、回形针选的任何文件（v2.2）：原样流式存进 工作区\\收到的\\日期\\原文件名（重名加序号），一个最多 2 GB。
    发消息时把返回的 rel 放进 /api/chat 的 files，DeepSeek 就知道文件在哪。into、sub：整个文件夹拖进来时，放进哪个文件夹的哪个子文件夹（v2.3）。"""
    if int(request.headers.get("content-length") or 0) > workspace.MAX_RECV:
        raise HTTPException(413, "太大了：一个文件最多 2 GB")
    try:
        dst = await asyncio.to_thread(workspace.recv_target, name, into, sub)
    except workspace.Denied as e:
        raise HTTPException(400, str(e)) from None
    except OSError as e:
        raise HTTPException(400, f"工作文件夹用不了：{e}") from None
    tmp, got = dst.with_name(dst.name + ".part"), 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                got += len(chunk)
                if got > workspace.MAX_RECV:
                    raise HTTPException(413, "太大了：一个文件最多 2 GB")
                f.write(chunk)
        os.replace(tmp, dst)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    safety.log("workspace.file", {"op": "收到", "path": workspace.rel(dst), "size": got}, "user")
    return {"rel": workspace.rel(dst), "name": dst.name, "size": got}


@app.get("/api/chat/file/{fid}")
def chat_file(fid: int):
    """对话里的一张图（你发的，或者读到的图片文件）：聊天记录里的缩略图、点开看大图。"""
    p = files.file_row(fid)
    if not p:
        raise HTTPException(404, "这张图找不到了")
    return FileResponse(p, headers={"Cache-Control": "private, max-age=31536000"})


@app.get("/api/chat/out/{fid}")
def chat_out(fid: int):
    """做好的文件（v2.3）：对话里直接看视频、图、听音频（支持拖进度条）。只给还在工作区里的。"""
    p = workspace.out_row(fid)
    if not p or not p.is_file():
        raise HTTPException(404, "这个文件找不到了（被挪走或删了）")
    return FileResponse(p, headers={"Cache-Control": "private, no-cache"})


@app.post("/api/chat/out/{fid}/open")
def chat_out_open(fid: int, body: dict = Body(default={})):
    """做好的文件：用默认程序打开，或者在资源管理器里显示。"""
    p = workspace.out_row(fid)
    if not p:
        raise HTTPException(404, "这个文件找不到了（被挪走或删了）")
    return {"msg": workspace.reveal(p, "file" if body.get("how") == "file" else "folder")}


# ---------------- 能读的文件夹（v1.8.17，只读；加文件夹 = 给 agent 加权限，只能在界面上点） ----------------
@app.get("/api/files/dirs")
def files_dirs():
    return {"dirs": files.public()}


@app.post("/api/files/dirs")
def files_add(body: dict = Body(...)):
    try:
        files.add_dir(body.get("path"), bool(body.get("cloud", True)))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"dirs": files.public()}


@app.patch("/api/files/dirs")
def files_patch(body: dict = Body(...)):
    files.set_cloud(body.get("path") or "", bool(body.get("cloud")))
    return {"dirs": files.public()}


@app.delete("/api/files/dirs")
def files_del(path: str):
    files.remove_dir(path)
    return {"dirs": files.public()}


# ---------------- Agent 自己的工作文件夹（v2.1，app/workspace.py：在里面写、改、删、挪、运行程序都不用问你；改和删之前先备份） ----------------
@app.get("/api/ws")
def ws_status():
    return workspace.status()


@app.put("/api/ws")
def ws_set(body: dict = Body(...)):
    try:
        if "dir" in body:
            workspace.set_dir(body.get("dir"))
        if "run" in body:
            workspace.set_run(bool(body.get("run")))
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e)) from None
    return workspace.status()


@app.post("/api/ws/open")
def ws_open(body: dict = Body(default={})):
    w = body.get("what") or "ws"
    if w == "list":
        st = workspace.status()
        if not st["last_list"]:
            raise HTTPException(404, "还没清理过（半年清一次）")
        p = Path(st["last_list"])
    else:
        p = workspace.BACKUP if w == "backup" else workspace.ensure() / workspace.RECV if w == "recv" else workspace.ensure()
        p.mkdir(parents=True, exist_ok=True)
    if paths.IS_WIN:
        os.startfile(str(p))          # 打开资源管理器（不是黑窗口）
        return {"msg": "打开了：" + paths.show(p)}
    return {"msg": "在：" + paths.show(p)}


# ---------------- Agent 的本事（v3.0，app/agentkit.py）：喊停、插话、开关 ----------------
@app.post("/api/events/{eid}/stop")
def event_stop(eid: int):
    """停下一件正在做的事：这一步做完就停，正在跑的命令也停。做好的文件留着，说「继续」能接着做。"""
    if not agentkit.request_stop(eid) and not ccode.request_stop(eid):
        raise HTTPException(409, "这件事已经不在做了")
    feed.add(f"你点了停下：事件 #{eid}", "warn", job="Agent")
    return {"ok": True}


@app.post("/api/events/{eid}/say")
def event_say(eid: int, body: dict = Body(...)):
    """中途插一句话：下一步之前告诉它（改方向、补要求）。"""
    if not agentkit.push(eid, body.get("text")):
        raise HTTPException(409, "这件事已经做完了：直接发新的一条吧")
    return {"ok": True}


@app.get("/api/agent/caps")
def agent_caps():
    return {"caps": agentkit.caps(), "skills": agentkit.skills(), "toolbox": agentkit.toolbox_list(), "cc": ccode.status()}


@app.put("/api/agent/caps")
def agent_caps_set(body: dict = Body(...)):
    """打开 / 关上一项本事（下载、配音、云端配音、生图、配乐、Claude Code 引擎）。给 agent 加权限：只有界面上你点的才算，记进动作日志。"""
    try:
        for k, v in body.items():
            agentkit.set_cap(k, bool(v))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return agent_caps()


@app.get("/api/chat/{token}")
def chat_progress(token: str):
    job = CHAT_JOBS.get(token)
    if not job:
        raise HTTPException(404, "没有这次对话（过期了）")
    ev = job["event"] or (events.get(job["eid"]) if job["eid"] else None)
    return {"done": job["done"], "event": ev, "err": job["err"], "confirm": job.get("confirm", False)}


# ---------------- 报告里的按钮 ----------------
@app.post("/api/changes/{cid}/undo")
def undo(cid: int):
    return {"msg": memory.undo(cid)}


@app.post("/api/asks/{aid}")
async def decide(aid: int, body: dict = Body(...)):
    return {"msg": await safety.decide(aid, bool(body.get("approve")))}


# ---------------- 后台监控 ----------------
@app.get("/api/docs")
def docs_list():
    return {"items": docs.listing(), "root": paths.show(docs.DOCS)}


@app.get("/api/docs/{rel:path}")
def docs_read(rel: str):
    try:
        return docs.read(rel)
    except FileNotFoundError:
        raise HTTPException(404, "没有这篇文档") from None


# ---------------- 硬件监控助手（设置 › 硬件监控 的开关） ----------------
@app.get("/api/hw/helper")
async def hw_helper_state():
    return dict(hwctl.state(), running=await hwctl.running())


@app.post("/api/hw/helper")
async def hw_helper_switch(body: dict = Body(...)):
    on = bool(body.get("on"))
    if on:
        ok, msg = await hwctl.start(allow_prompt=True)
        settings.update({"hwOn": ok or bool(settings.S.get("hwOn"))})
    else:
        settings.update({"hwOn": False})
        ok, msg = await hwctl.stop()
    return dict(hwctl.state(), ok=ok, msg=msg, running=await hwctl.running())


@app.post("/api/quit")
async def quit_all():
    """界面上的「退出 Agent」：停掉自己开的子进程（模型服务、Kev、正在跑的安装），然后退出；启动.bat 的黑窗口也会跟着关。"""
    feed.add("你点了「退出 Agent」，正在停掉所有部分", "head", job="后端")
    print("界面上点了「退出 Agent」，正在退出……")

    async def bye():
        await asyncio.sleep(0.8)          # 先让这次请求回给界面
        with contextlib.suppress(Exception):
            setup.stop()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(BOT.stop(), 3)
        with contextlib.suppress(Exception):
            M.stop_all()
        with contextlib.suppress(Exception):
            osd.ctl().stop()
        if settings.S.get("hwOn"):        # 硬件监控助手是跟着 Agent 起的，也一起关
            with contextlib.suppress(Exception):
                await asyncio.wait_for(hwctl.stop(), 6)
        monitor.clean_exit()
        os._exit(11)                      # 11：界面上点了退出（启动.bat 看日志模式下，黑窗口也跟着关）
    asyncio.get_event_loop().create_task(bye())
    return {"ok": True}


@app.get("/api/feed")
def get_feed(n: int = 400):
    return feed.view(max(20, min(n, 600)))


@app.get("/api/monitor")
async def get_monitor():
    return await monitor.overview()


@app.get("/api/logs")
def get_logs():
    return monitor.logs()


@app.get("/api/logs/{name}")
def get_log(name: str, n: int = 300):
    try:
        return monitor.tail(name, min(max(n, 20), 1000))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------- 一键补齐 ----------------
@app.get("/api/setup")
def setup_status():
    return setup.status()


@app.post("/api/setup/start")
async def setup_start():
    if not setup.start():
        raise HTTPException(409, "已经在补了")
    return setup.status()


@app.post("/api/setup/stop")
def setup_stop():
    setup.stop()
    return setup.status()


# ---------------- 整备 ----------------
@app.get("/api/checks")
def last_checks():
    return {"last": db.kv_get("checks"), "places": checks.places()}


@app.post("/api/checks/run")
async def run_checks():
    res = await checks.run_all()
    return {"res": res, "places": checks.places(), "ts": time.time()}


@app.post("/api/checks/{k}/run")
async def run_one(k: str, quick: int = 0):
    """重新检测一项。quick=1 时和整体自检一样快查（重新自检的窗口 14 项同时发，每项查完立刻显示）；
    不带 quick 是卡片上单独点的，模型服务和本地模型环境会查得更深。"""
    if k not in checks.CHECKS:
        raise HTTPException(404, "没有这一项")
    fn = checks.CHECKS[k]
    try:
        if k == "models" and not quick:
            r = await asyncio.wait_for(checks.c_models(deep=True), 40)
        elif k == "aienv" and not quick:
            r = await asyncio.wait_for(checks.c_aienv(force=True), 40)
        else:
            r = await asyncio.wait_for(fn(), 20)
    except asyncio.TimeoutError:
        r = checks.miss("检测超时", heal=True)
    except Exception as e:
        r = checks.miss(f"检测出错：{str(e)[:120]}")
    checks.record(k, r, bump=True)
    return (db.kv_get("checks") or {}).get("res", {}).get(k, r)


@app.post("/api/actions/{name}")
async def action(name: str, body: dict = Body(default={})):
    try:
        if name == "start_models":
            h = await M.ensure_server()
            await router.embed_missing()
            return {"msg": "模型服务已启动", "health": h}
        if name == "start_kev":
            ok = await M.ensure_kev(wait=False)
            return {"msg": "Kev 已在线" if ok else "Kev 正在启动（第一次要下载权重，看 data\\logs\\kev.log）"}
        if name == "load_base":
            await M.ensure_server()
            import httpx
            async with httpx.AsyncClient(timeout=300) as c:
                await c.post(M.url("/load"), json={"what": "base"})
            return {"msg": "底座已加载"}
        if name == "unload_base":
            await M.unload("base")
            return {"msg": "底座已卸载"}
        if name == "qq_bind":
            cand = db.kv_get("qq_candidate") or {}
            oid = body.get("openid") or cand.get("openid")
            if not oid:
                raise HTTPException(400, "还没有收到消息")
            settings.update({"qqUser": oid})
            db.kv_set("qq_candidate", None)
            safety.log("qq.bind", {"openid": oid[:8]}, "user")
            return {"msg": "已绑定，之后只回复这个 QQ"}
        if name == "qq_test":
            res = await reminders.test_push()
            return {"msg": "；".join(f"{ {'qq': 'QQ', 'toast': '弹窗', 'card': '卡片'}[k] }：{v['info']}" for k, v in res.items()), "res": res}
        if name == "run_exam":
            await M.ensure_server()
            r = await exam.run()
            return {"msg": f"实测完成：语义路由 {r['embed']}% · Kev {r['kev'] if r['kev'] is not None else '没准备好'}", "res": r}
        if name == "ds_balance":
            b = await deepseek.refresh_balance(force=True)
            if not b:
                raise HTTPException(400, "还没填 DeepSeek Key")
            if b.get("err"):
                return {"msg": "没查到：" + b["err"]}
            return {"msg": f"余额 {deepseek.money(b['total'], b['currency'])}", "balance": b}
        if name == "search_test":
            q = (body.get("q") or "DeepSeek 搜索 API").strip()
            t0 = time.time()
            try:
                res = await websearch.search(q, count=5, purpose="search_test")
            except deepseek.NoKey:
                raise HTTPException(400, "先填好 DeepSeek Key 并点「保存」") from None
            except Exception as e:
                raise HTTPException(400, f"没搜成：{str(e)[:120]}") from None
            top = res[0] if res else {}
            return {"msg": f"能用：搜「{q}」{len(res)} 条，用时 {time.time() - t0:.1f} 秒" + (f"；第一条：{(top.get('title') or '')[:30]}" if top else "（这次没有结果，不收钱）"),
                    "results": [{"title": r.get("title"), "url": r.get("url"), "site": r.get("site_name"), "date": r.get("date")} for r in res[:5]],
                    "search": websearch.stats()}
        if name == "ds_models":
            try:
                m = await deepseek.list_models()
            except deepseek.NoKey:
                raise HTTPException(400, "先填好 DeepSeek Key 并点「保存」，再获取模型列表") from None
            except Exception as e:
                raise HTTPException(400, str(e)) from None
            cur = settings.S["dsModel"]
            tip = "" if cur in m["models"] else f"；现在用的「{cur}」不在列表里，记得换一个"
            return {"msg": f"查到 {len(m['models'])} 个模型{tip}", "ds_models": m}
        if name == "nightly_run":
            return {"msg": "每日差事跑完了", "res": await nightly.run_all()}
        if name == "copy_prompt":
            cps = db.kv_get("claude_prompts", []) or []
            if not cps:
                raise HTTPException(404, "还没有提示词")
            return {"prompt": cps[-1]["prompt"]}
        if name == "diagnose":
            k = body.get("k")
            last = (db.kv_get("checks") or {}).get("res", {}).get(k, {})
            out = await deepseek.chat([{"role": "system", "content": "你在帮一个 Windows 11 用户排查本地 AI 助手的安装问题。他的电脑：" + (hw.machine() or "未知") + "。网络：国内，GitHub 打不开，PyPI、阿里云镜像、魔搭能用。用中文给出 3 步以内的具体修法，简短。"},
                                       {"role": "user", "content": f"整备项「{k}」检测结果：{last.get('d', '')}"}], purpose="diagnose", max_tokens=500)
            return {"msg": out["text"]}
        raise HTTPException(404, "没有这个动作")
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"msg": str(e)[:300]}, status_code=500)


# ---------------- 提醒 ----------------
@app.get("/api/reminders")
def list_reminders():
    return {"items": reminders.all_reminders(), "next": reminders.next_info()}


@app.post("/api/reminders")
def add_reminder(body: dict = Body(...)):
    rid = reminders.save(body)
    safety.log("reminder.create", {"id": rid, "by": "user"}, "user")
    return db.one("SELECT * FROM reminders WHERE id=?", (rid,))


@app.put("/api/reminders/{rid}")
def edit_reminder(rid: int, body: dict = Body(...)):
    reminders.save(body, rid)
    return db.one("SELECT * FROM reminders WHERE id=?", (rid,))


@app.delete("/api/reminders/{rid}")
def del_reminder(rid: int):
    db.run("DELETE FROM reminders WHERE id=?", (rid,))
    safety.log("reminder.delete", {"id": rid, "by": "user"}, "user")
    return {"ok": True}


@app.post("/api/reminders/{rid}/fire")
async def fire_reminder(rid: int):
    r = db.one("SELECT * FROM reminders WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "没有这个提醒")
    did, res = await reminders.fire(r)
    return {"delivery": did, "res": res}


@app.post("/api/train/answer")
async def train_answer(body: dict = Body(default={})):
    r = growth.answer(bool(body.get("go")))
    if r is None:
        raise HTTPException(409, "现在没有在问要不要训练")
    with contextlib.suppress(Exception):
        await BOT.push(r)
    return {"msg": r}


@app.post("/api/deliveries/{did}/ack")
def ack(did: int):
    return {"ok": reminders.ack(did)}


@app.post("/api/deliveries/{did}/snooze")
def snooze(did: int, body: dict = Body(default={})):
    return {"ok": reminders.snooze(did, int(body.get("minutes", 30)))}


# ---------------- 从更强的模型带回的总结（接口名沿用 claude，判例和老数据不用改） ----------------
@app.post("/api/claude/import")
async def import_summary(body: dict = Body(...)):
    content = body.get("content") or ""
    if not content.strip():
        raise HTTPException(400, "文件是空的")
    if len(content) > 300_000:
        raise HTTPException(400, "文件太大（超过 300KB）")
    name = re.sub(r"[^\w一-鿿\-]+", "_", (body.get("name") or "总结").rsplit(".", 1)[0])[:40]
    rel = f"总结/{datetime.now():%Y-%m-%d}-{name}.md"
    await memory.write(rel, content, "你从更强的模型带回的总结")
    lst = db.kv_get("summaries", []) or []
    lst.append({"rel": rel, "ts": time.time()})
    db.kv_set("summaries", lst[-100:])
    cps = db.kv_get("claude_prompts", []) or []
    for c in reversed(cps):
        if not c.get("done"):
            c["done"] = True
            break
    db.kv_set("claude_prompts", cps)
    try:
        msg = await nightly.ingest_summary(rel)
    except Exception as e:
        msg = f"已保存；抽取要点失败：{str(e)[:80]}（每日差事会再试）"
    return {"msg": msg, "rel": rel}


@app.get("/api/log/verify")
def verify():
    return safety.verify_log()


app.mount("/", StaticFiles(directory=str(paths.UI)), name="ui")


def _open_edge(url):
    import subprocess
    from .models import NOWIN
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "msedge", f"--app={url}", "--window-size=1600,900"], creationflags=NOWIN)
        return True
    except Exception:
        return False


def open_ui():
    """打开界面。默认是无边框的桌面窗口（app/window.py）；它起不来就用 Edge 应用模式；再不行用默认浏览器。
    设置 › 外观 › 打开方式 可以改成一直用 Edge。"""
    url = f"http://127.0.0.1:{PORT}"
    if paths.IS_WIN:
        import subprocess
        import sys
        from pathlib import Path
        shell = settings.S.get("uiShell", "desk")
        if shell in ("desk", "desk-basic"):
            exe = Path(sys.executable)
            pyw = exe.with_name("pythonw.exe")
            env = dict(os.environ, AGENT_NATIVE_FRAME="0" if shell == "desk-basic" else "1")
            try:
                p = subprocess.Popen([str(pyw if pyw.exists() else exe), "-m", "app.window"], cwd=str(paths.ROOT), env=env,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for _ in range(16):          # 8 秒内退出了（退出码 3 = pywebview 用不了）就改用 Edge
                    time.sleep(0.5)
                    if p.poll() is not None:
                        break
                if p.poll() is None or p.returncode == 0:
                    return
                print("桌面窗口没打开（退出码 %s），改用 Edge 应用模式。" % p.returncode)
            except Exception as e:
                print("桌面窗口没打开：", e)
        if _open_edge(url):
            return
    import webbrowser
    webbrowser.open(url)


async def _open_later():
    await asyncio.sleep(1.5)
    await asyncio.to_thread(open_ui)


def run():
    """起后端。返回退出码：0 正常停了；10 已经在运行（刚帮你把界面拿出来了）。"""
    import socket
    import uvicorn
    monitor.tee_console()                 # 从一开始就写进 data\logs\backend.log（pythonw 没有黑窗口，出错原因全靠它）
    with socket.socket() as sk:
        sk.settimeout(0.5)
        if sk.connect_ex(("127.0.0.1", PORT)) == 0:
            print("Agent 已经在运行了，直接打开界面。")
            if os.environ.get("AGENT_OPEN_UI") == "1":
                settings.load()
                open_ui()
            return 10
    monitor.start_guard()                 # 崩溃记录 + 看看上次是不是正常退出的
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", use_colors=False)
    monitor.clean_exit()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
