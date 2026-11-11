r"""Claude Code 执行引擎（v3.0）：把一整件事交给他电脑上装的 Claude Code 去做。

为什么：Claude Code 自带一套成熟的干活本事（自己列待办、读写改文件、跑命令、出错自己改、上下文满了自己压缩），
比我们自己那个「DeepSeek + 几个工具」的循环强得多。他本地的 Claude Code 用 CC Switch 换成了 DeepSeek 的模型，所以花的还是 DeepSeek 的钱。

怎么接（不碰他的任何配置，只是像他在命令行里那样叫它一声）：
    claude -p --output-format stream-json --verbose --permission-mode acceptEdits --allowedTools … [--resume 会话号]
- 在工作文件夹里跑（cwd = 工作区）：acceptEdits 只许它改工作区里的文件；工作区外面的它读不了、改不了（没列进允许的工具就会被拒）。
- 能跑的命令只有设置里列的那几样开头的（ccBash：python、pip、ffmpeg、node、npm、npx、git……）；别的命令没人批就不执行。
  python、pip 排在最前面的是工作区专用的 Python 环境（ws-env），和 DeepSeek 自己干活时一样。
- 要做的事从标准输入给它（不放在命令行里：中文、换行、长度在 Windows 上都容易出问题）。
- 它一边做一边往外吐一行一个 JSON：开工、每次用工具（写文件 / 改文件 / 运行 / 待办清单）、最后的结果。这里一行行读，
  变成事件里的每一步（主页「现在」那块实时看得到）；它的待办清单（TodoWrite）就是这件事的计划。
- 不弹黑窗口；日志在 data\logs\claude_code.log；一件事最多跑 ccMinutes 分钟；点「停下」按进程号结束它和它开的子进程。
- 做完记下会话号：他说「继续」就用 --resume 接着同一个会话做。
- 默认关着（设置 › Agent 能力 里他自己开）：这是给 agent 加权限。隐私的事不交给它。
- 这不是真沙箱（和工作区的运行程序一样）：它跑的 python 脚本理论上碰得到别处。
"""
import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import agentkit, db, paths, settings, workspace

LOG = paths.LOGS / "claude_code.log"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RUNNING = {}                                     # eid -> {"p": Popen, "stop": ""}
_ver = {"path": None, "v": "", "ts": 0.0}
RULES = ("你现在是这台电脑上一个本地 Agent 的执行引擎，在它的工作文件夹里干活（当前目录就是）。规矩：\n"
         "1. 只在当前目录里新建、写、改文件；外面的一律不碰。E 盘只读。不要动任何配置文件、不要装系统级的东西。\n"
         "2. 用中文。回答简短实用：做了什么、成没成、文件在哪（相对路径）。做不到的照实说。\n"
         "3. 步骤多的活先列待办，做一步勾一步；在这件事的文件夹里放一个 进度.md，随时更新做到哪。\n"
         "4. python、pip 是这个文件夹专用的环境，要什么包直接 pip install。做视频：工具箱\\ 里有现成的脚本（python 工具箱\\录网页.py -h）。\n"
         "5. 做出来的图、视频自己检查一遍再说做好了。同一个办法连着失败两次就换办法。")


def find():
    """他电脑上的 claude 在哪：设置里填的 → PATH 里的 → 常见的安装位置。"""
    v = str(settings.S.get("ccCmd") or "").strip().strip('"')
    if v:
        return v if (Path(v).exists() or shutil.which(v)) else None
    p = shutil.which("claude")
    if p:
        return p
    home = Path.home()
    for c in (home / ".local" / "bin" / "claude.exe", home / ".claude" / "local" / "claude.exe", home / "AppData" / "Roaming" / "npm" / "claude.cmd",
              home / ".local" / "bin" / "claude"):
        if c.exists():
            return str(c)
    return None


def version():
    p = find()
    if not p:
        return ""
    if _ver["path"] == p and time.time() - _ver["ts"] < 3600:
        return _ver["v"]
    try:
        r = subprocess.run([p, "--version"], capture_output=True, timeout=20, creationflags=NOWIN, stdin=subprocess.DEVNULL)
        v = (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()[0][:60] if r.returncode == 0 else ""
    except Exception:
        v = ""
    _ver.update(path=p, v=v, ts=time.time())
    return v


def status(deep=False):
    p = find()
    return {"on": bool(settings.S.get("ccOn")), "found": bool(p), "path": paths.show(Path(p)) if p else "", "version": version() if (deep and p) else _ver["v"],
            "auto": bool(settings.S.get("ccAuto", True)), "minutes": int(settings.S.get("ccMinutes") or 60), "bash": settings.S.get("ccBash") or "",
            "model": settings.S.get("ccModel") or "", "running": list(RUNNING), "log": paths.show(LOG)}


def usable():
    return bool(settings.S.get("ccOn")) and bool(find()) and workspace.on()


def allowed_tools():
    names = [x.strip() for x in str(settings.S.get("ccBash") or "").replace("，", ",").split(",") if x.strip() and all(c.isalnum() or c in "-_." for c in x.strip())]
    return ["Edit", "Write", "MultiEdit", "NotebookEdit", "TodoWrite", "Glob", "Grep"] + [f"Bash({n} *)" for n in names] + [f"Bash({n})" for n in names]


def command(session=None):
    cmd = [find(), "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
           "--allowedTools", *allowed_tools(), "--append-system-prompt", RULES]
    if settings.S.get("ccModel"):
        cmd += ["--model", str(settings.S["ccModel"])]
    if session:
        cmd += ["--resume", session]
    return cmd


def request_stop(eid, why="你点了停下"):
    r = RUNNING.get(eid)
    if not r:
        return False
    r["stop"] = why
    _kill(r.get("p"))
    return True


def _kill(p):
    """只停自己开的：按进程号，连它开的子进程一起。"""
    if not p or p.poll() is not None:
        return
    try:
        import psutil
        kids = psutil.Process(p.pid).children(recursive=True)
    except Exception:
        kids = []
    try:
        p.terminate()
    except Exception:
        pass
    for k in kids:
        try:
            k.kill()
        except Exception:
            pass
    try:
        p.wait(8)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _log(s):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 8 << 20:
            LOG.replace(LOG.with_suffix(".old.log"))
        with open(LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(s if s.endswith("\n") else s + "\n")
    except OSError:
        pass


def _short(s, n=44):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _relname(p):
    try:
        return workspace.rel(Path(str(p)).resolve(strict=False))
    except Exception:
        return Path(str(p or "")).name


def tool_step(name, inp):
    """Claude Code 用的一个工具 → 事件里的一步 [名, 说明]。"""
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        return ["运行", _short(inp.get("command"), 60)]
    if name == "Write":
        return ["写文件", _relname(inp.get("file_path"))]
    if name in ("Edit", "MultiEdit", "NotebookEdit"):
        return ["改文件", _relname(inp.get("file_path") or inp.get("notebook_path"))]
    if name == "Read":
        return ["读文件", _relname(inp.get("file_path"))]
    if name in ("Glob", "Grep"):
        return ["找文件", _short(inp.get("pattern"), 40)]
    if name in ("WebSearch", "WebFetch"):
        return ["联网搜索" if name == "WebSearch" else "读网页", _short(inp.get("query") or inp.get("url"), 40)]
    if name in ("Task", "Agent"):
        return ["派子任务", _short(inp.get("description") or inp.get("prompt"), 40)]
    return ["工具", f"{name} · {_short(json.dumps(inp, ensure_ascii=False), 40)}"]


def _todos(inp):
    return [{"text": t.get("content") or t.get("activeForm") or "", "status": {"completed": "done", "in_progress": "doing"}.get(t.get("status"), "todo")}
            for t in (inp.get("todos") or []) if isinstance(t, dict)]


def _blocking(eid, cmd, prompt, env, cwd, on_line, limit):
    p = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=NOWIN)
    RUNNING[eid]["p"] = p
    try:
        from .setup import _in_job              # Agent 关了，它也跟着停
        _in_job(p)
    except Exception:
        pass
    err = []

    def read_err():
        for line in iter(p.stderr.readline, b""):
            err.append(line.decode("utf-8", "replace").rstrip())
            _log("[stderr] " + err[-1])
    import threading
    th = threading.Thread(target=read_err, daemon=True)
    th.start()
    try:
        p.stdin.write(prompt.encode("utf-8"))
        p.stdin.close()
    except OSError:
        pass
    t0 = time.time()

    def watchdog():
        while p.poll() is None:
            if time.time() - t0 > limit:
                RUNNING.get(eid, {}).setdefault("stop", "")
                RUNNING[eid]["stop"] = RUNNING[eid]["stop"] or f"超过 {int(limit // 60)} 分钟，停了"
                _kill(p)
                return
            time.sleep(1)
    threading.Thread(target=watchdog, daemon=True).start()
    for raw in iter(p.stdout.readline, b""):
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        _log(line[:4000])
        try:
            on_line(json.loads(line))
        except ValueError:
            continue
    code = p.wait()
    th.join(timeout=3)
    return code, "\n".join(err[-8:])


async def run(eid, text, steps, say=None, session=None, extra=""):
    """把这件事交给 Claude Code。返回 {text, session, turns, usd, stopped, ok, tools}。"""
    say = say or (lambda _m: None)
    if not usable():
        raise RuntimeError("Claude Code 引擎没开，或者没找到 claude（设置 › Agent 能力）")
    err = await asyncio.to_thread(workspace._ensure_env, say) if settings.S.get("wsRun", True) else ""
    await asyncio.to_thread(agentkit.sync_toolbox)
    base = workspace.ensure()
    env = os.environ.copy()
    for k in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        env.pop(k, None)
    tmp = base / workspace.TMP
    tmp.mkdir(exist_ok=True)
    env.update({"PATH": str(workspace._bin()) + os.pathsep + env.get("PATH", ""), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "AGENT_WORKSPACE": str(base), "PLAYWRIGHT_BROWSERS_PATH": str(workspace.ENV / "browsers"),
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1"})
    if not err:
        env["VIRTUAL_ENV"] = str(workspace.ENV)
    env.setdefault("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
    st = {"text": "", "session": session, "turns": 0, "usd": 0.0, "ok": None, "tools": 0, "errors": 0, "denied": 0, "model": "", "result": None}
    RUNNING[eid] = {"p": None, "stop": ""}
    loop = asyncio.get_running_loop()

    def on_line(ev):
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            st["session"], st["model"] = ev.get("session_id") or st["session"], ev.get("model") or ""
            steps.append(["Claude Code", ("接着上次的会话" if session else "开工") + (f" · {st['model']}" if st["model"] else "")])
            loop.call_soon_threadsafe(say, "Claude Code 开工了……")
        elif t == "assistant":
            for b in ((ev.get("message") or {}).get("content") or []):
                if b.get("type") == "text" and (b.get("text") or "").strip() and not ev.get("parent_tool_use_id"):
                    st["text"] = b["text"].strip()
                    loop.call_soon_threadsafe(say, _short(st["text"], 70))
                elif b.get("type") == "tool_use":
                    st["tools"] += 1
                    name, inp = b.get("name") or "", b.get("input") or {}
                    if name == "TodoWrite":
                        plan = agentkit.set_plan(eid, _todos(inp))
                        done = sum(1 for x in plan if x["st"] == "done")
                        cur = next((x["text"] for x in plan if x["st"] == "doing"), "")
                        steps.append(["计划", f"{done}/{len(plan)}" + (f" · 正在：{cur}" if cur else "")])
                    else:
                        steps.append(tool_step(name, inp))
                    loop.call_soon_threadsafe(say, f"Claude Code：{steps[-1][0]} {steps[-1][1]}"[:80])
        elif t == "user":
            for b in ((ev.get("message") or {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    st["errors"] += 1
        elif t == "result":
            st["result"] = ev
            st["session"] = ev.get("session_id") or st["session"]
            st["turns"] = int(ev.get("num_turns") or 0)
            st["usd"] = float(ev.get("total_cost_usd") or 0)
            st["ok"] = not ev.get("is_error") and ev.get("subtype", "success") == "success"
            st["denied"] = len(ev.get("permission_denials") or [])
            if (ev.get("result") or "").strip():
                st["text"] = ev["result"].strip()

    prompt = text + ("\n\n" + extra if extra else "")
    _log(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 事件 #{eid}" + (f"（接着会话 {session}）" if session else "") + f"：{_short(text, 200)}")
    limit = max(1, int(settings.S.get("ccMinutes") or 60)) * 60
    try:
        code, errtxt = await asyncio.to_thread(_blocking, eid, command(session), prompt, env, base, on_line, limit)
    finally:
        stop = (RUNNING.pop(eid, None) or {}).get("stop", "")
    if st["session"]:
        db.update("events", eid, {"engine": {"name": "cc", "session": st["session"], "model": st["model"]}})
    if stop:
        steps.append(["停下", stop])
        return dict(st, stopped=True, text=(st["text"] + "\n\n" if st["text"] else "") + f"（{stop}。做好的都在工作文件夹里；要接着做就说「继续」。）")
    if st["ok"] is None:                                         # 没等到结果就退出了：多半是没登录、模型配置不对、版本太旧
        why = errtxt.strip() or f"退出码 {code}"
        steps.append(["Claude Code", f"没跑起来：{_short(why, 60)}"])
        raise RuntimeError("Claude Code 没跑起来：" + why[:300] + "（完整的在 data\\logs\\claude_code.log）")
    steps.append(["Claude Code", f"{'做完了' if st['ok'] else '没做完'} · {st['turns']} 轮 · 用了 {st['tools']} 次工具" +
                  (f" · {st['errors']} 次出错" if st["errors"] else "") + (f" · {st['denied']} 个动作没被允许" if st["denied"] else "")])
    if st["denied"]:
        st["text"] += f"\n\n（有 {st['denied']} 个动作没被允许——它想跑的命令不在允许的名单里：设置 › Agent 能力 › Claude Code 能改名单。）"
    return dict(st, stopped=False)
