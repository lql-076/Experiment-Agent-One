"""一键补齐：整备里能自动装的，按顺序装好。

装到哪、从哪下都是写死的（和手动双击那几个 .bat 一模一样），不让模型随手敲命令。
某一步失败时，把日志最后几十行交给 DeepSeek 看，它只能从下面列出的几种修法里选一种：
原样重试、等一会再试、换下载源、跳过这步、或者告诉你要手动做什么。没填 Key 时按简单规则判断。

不删除任何文件：旧的 Git 文件夹只会改名留着；下载的压缩包在内存里解开，不落临时文件。
"""
import asyncio
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

import httpx

from . import checks, db, deepseek, feed, hw, memory, paths, router, safety, settings
from .models import M, NOWIN

STEPS = [
    {"k": "git", "t": "Git（便携版）", "d": "放进 tools\\git，不装进系统，只给 agent 自己用"},
    {"k": "aienv", "t": "本地模型环境", "d": "显卡版 PyTorch、Transformers、PEFT、Kev，约 3GB"},
    {"k": "models", "t": "底座和嵌入模型", "d": "从魔搭下载，约 6GB，断了会接着下"},
    {"k": "start", "t": "启动本地模型服务", "d": "加载嵌入模型，约占 1.2GB 显存"},
    {"k": "kev", "t": "Kev 的权重", "d": "经 hf-mirror 下载约 2GB"},
    {"k": "hwmon", "t": "硬件监控助手", "d": "会弹一次管理员确认，点「是」"},
]
NEEDS = {"start": ["aienv", "models"], "kev": ["aienv"]}
FIXES = {
    "common": {
        "retry": "原样再试一次（网络抖动、超时、连接被重置）",
        "wait_retry": "等 3 分钟再试（服务器限流、暂时连不上）",
        "skip": "跳过这一步，先做后面的（这步不是必须的，或者怎么试都不行）",
        "manual": "需要用户手动处理（比如要装驱动、磁盘满了、文件被别的程序占用）",
    },
    "git": {"next_mirror": "换一个镜像下载 Git"},
    "aienv": {"pypi_mirror": "所有 pip 安装改走清华镜像"},
    "models": {"source_hf": "改从 hf-mirror 下载模型"},
}
NET_ERR = re.compile(r"time[d ]?out|connection|10054|10060|ssl|reset|temporar|getaddrinfo|readerror|remotedisconnected|incompleteread|503|502|429", re.I)


FIX_SAY = {"retry": "原样再试一次", "wait_retry": "等 3 分钟再试", "skip": "先跳过这一步", "manual": "这一步要你手动处理",
           "next_mirror": "换一个镜像下载 Git", "pypi_mirror": "改走清华镜像再试", "source_hf": "改从 hf-mirror 下载模型"}
JOBN = "一键补齐"


def _title(k):
    return next((s["t"] for s in STEPS if s["k"] == k), k)


def _say(k, text, kind="info"):
    """写一条进展报告（后台页「进展报告」里看）。"""
    feed.add(text, kind, job=JOBN, step=_title(k) if k else "")


def _blank():
    return {k["k"]: {"st": "wait", "info": "", "tail": [], "tries": 0, "why": "", "tell": "", "prog": None, "t0": 0.0, "t1": 0.0} for k in STEPS}


JOB = {"running": False, "stop": False, "started": 0.0, "finished": 0.0, "cur": None, "line": "", "steps": _blank()}
_proc = {"p": None}
_task = {"t": None}


def _clean(p):
    return {k: v for k, v in p.items() if not k.startswith("_")} if p else None


def status():
    return {"running": JOB["running"], "started": JOB["started"], "finished": JOB["finished"], "cur": JOB["cur"], "line": JOB["line"][-160:],
            "steps": [{**s, **{x: JOB["steps"][s["k"]][x] for x in ("st", "info", "why", "tell", "tries", "t0", "t1")}, "prog": _clean(JOB["steps"][s["k"]]["prog"]),
                       "tail": JOB["steps"][s["k"]]["tail"][-6:], "log": paths.show(paths.LOGS / f"setup_{s['k']}.log")} for s in STEPS],
            "last": db.kv_get("setup_last"), "ds_key": bool(settings.get_secret("dsKey"))}


def brief():
    """给总览用的一句话。"""
    if not JOB["running"]:
        return None
    i = next((n for n, s in enumerate(STEPS) if s["k"] == JOB["cur"]), 0)
    pr = JOB["steps"][STEPS[i]["k"]].get("prog") or {}
    return {"running": True, "n": i + 1, "total": len(STEPS), "t": STEPS[i]["t"], "pct": pr.get("pct")}


def _mark(k, st, info=None, **kw):
    s = JOB["steps"][k]
    if st == "run" and not s["t0"]:
        s["t0"] = time.time()
    if st in ("ok", "fail", "skip", "manual", "blocked") and s["t0"] and not s["t1"]:
        s["t1"] = time.time()
    if st != "run":
        if s.get("prog"):
            _feed_done(k, s["prog"])
        n = len(s.pop("_small", ()) or ())
        if n:
            feed.finish(f"setup:{k}:small", f"另外下载了 {n} 个小文件（每个 20MB 以下）", "info")
        s["prog"] = None
    s["st"] = st
    if info is not None:
        s["info"] = info
    s.update(kw)


def _log(k, text):
    s = JOB["steps"][k]
    for line in text.splitlines():
        line = line.rstrip()
        if line:
            s["tail"].append(line[:300])
    del s["tail"][:-60]
    try:
        with open(paths.LOGS / f"setup_{k}.log", "a", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
    except Exception:
        pass


def _redact(t: str) -> str:
    t = re.sub(r"([A-Za-z]:\\Users\\)[^\\\s]+", r"\1你", t)
    return re.sub(r"sk-[A-Za-z0-9]{8,}", "sk-***", t)


# ---------------- 进度：认出三种进度行，算出百分比、速度、还剩多久 ----------------
UNIT = {"": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}
TQDM = re.compile(r"^(?P<name>.*?):?\s*(?P<pct>\d{1,3})%\|[^|]*\|\s*(?P<d>[\d.]+)(?P<du>[kKMGT]?)i?B?/(?P<t>[\d.]+)(?P<tu>[kKMGT]?)i?B?"
                  r"(?:\s*\[[\d:]+<(?P<eta>[\d:?]+),\s*(?P<r>[\d.]+)(?P<ru>[kKMGT]?)i?B/s\])?")
PIP_RAW = re.compile(r"^Progress (\d+) of (\d+)$")
PIP_DL = re.compile(r"^\s*Downloading (\S+?)(?:\s+\(([\d.]+ [kMG]?B)\))?\s*$")


def _secs(t):
    try:
        n = [int(x) for x in t.split(":")]
        return sum(v * 60 ** i for i, v in enumerate(reversed(n)))
    except Exception:
        return None


def _set_prog(k, **p):
    s = JOB["steps"][k]
    old = s.get("prog") or {}
    now = time.time()
    hist = [h for h in old.get("_h", []) if now - h[0] <= 5] if old.get("phase") == p.get("phase") else []
    if p.get("done") is not None:
        hist.append((now, p["done"]))
    if p.get("speed") is None and len(hist) > 1 and hist[-1][0] > hist[0][0]:
        p["speed"] = max(0.0, (hist[-1][1] - hist[0][1]) / (hist[-1][0] - hist[0][0]))
    if p.get("eta") is None and p.get("speed") and p.get("total") and p.get("done") is not None:
        p["eta"] = max(0.0, (p["total"] - p["done"]) / p["speed"])
    if p.get("pct") is None and p.get("total"):
        p["pct"] = min(100.0, (p.get("done") or 0) / p["total"] * 100)
    p["_h"], p["ts"] = hist, now
    p["_t0"] = old.get("_t0", now) if old.get("phase") == p.get("phase") else now
    s["prog"] = p
    _feed_prog(k, p, old)
    # 日志里每 10% 记一行，不刷屏
    b = int((p.get("pct") or 0) // 10)
    if b != old.get("_b") or p.get("phase") != old.get("phase"):
        p["_b"] = b
        _log(k, f"[进度] {p.get('phase', '')} {p.get('pct') or 0:.0f}%" + (f" · {p['speed'] / 1e6:.1f} MB/s" if p.get("speed") else ""))
    else:
        p["_b"] = b


SMALL = 20 << 20      # 20MB 以下的小文件合成一行，不刷屏


def _is_small(p):
    return bool(p.get("total")) and p["total"] < SMALL and str(p.get("phase", "")).startswith("下载 ")


def _feed_prog(k, p, old):
    if old.get("phase") and old.get("phase") != p.get("phase"):
        _feed_done(k, old)
    phase = p.get("phase") or "进行中"
    if _is_small(p):
        st = JOB["steps"][k]
        st.setdefault("_small", set()).add(phase)
        feed.add(f"下载小文件 · 第 {len(st['_small'])} 个：{phase[3:]}", "prog", job=JOBN, step=_title(k), key=f"setup:{k}:small")
        return
    feed.add(phase, "prog", job=JOBN, step=_title(k), key=f"setup:{k}:{phase}",
             prog={x: p.get(x) for x in ("pct", "done", "total", "speed", "eta", "src")})


def _feed_done(k, p):
    """一个阶段结束：进度行改成一句结论。"""
    phase = p.get("phase") or "进行中"
    if _is_small(p):
        return
    key = f"setup:{k}:{phase}"
    if not feed.has(key):
        return
    total, pct = p.get("total") or 0, p.get("pct") or 0
    took = max(0.1, time.time() - p.get("_t0", time.time()))
    if total > 1 and pct >= 99:
        feed.finish(key, f"{phase} 完成 · {feed.size(total)} · 用时 {feed.dur(took)} · 平均 {feed.size(total / took)}/s", "ok")
    elif total > 1:
        feed.finish(key, f"{phase} 停在 {pct:.0f}%（{feed.size(p.get('done') or 0)} / {feed.size(total)}）", "warn")
    else:
        feed.drop(key)      # 只是转圈的阶段（测速、检查文件），结果另有一句话说明，这一行不用留


PIP_OK = re.compile(r"^Successfully installed (.+)$")


def _narrate(k, line):
    """把子程序打印的一行翻成进展报告。返回要写进日志的那一行（@@SAY 的前缀去掉）。"""
    s = line.strip()
    if s.startswith("@@SAY "):
        msg, kind = s[6:].strip(), "info"
        if msg[:1] in "!！":
            msg, kind = msg[1:].strip(), "warn"
        elif msg[:1] == "✓":
            msg, kind = msg[1:].strip(), "ok"
        _say(k, msg, kind)
        return msg
    m = PIP_OK.match(s)
    if m:
        pk = m.group(1).split()
        names = [re.sub(r"-\d[\w.+!]*$", "", x) for x in pk]
        _say(k, f"装好了 {len(pk)} 个包：" + "、".join(names[:8]) + ("……" if len(pk) > 8 else ""), "ok")
    elif s.startswith("Installing collected packages:"):
        n = len([x for x in s.split(":", 1)[1].split(",") if x.strip()])
        _say(k, f"都下好了，正在把 {n} 个包装进环境（大的包要一两分钟，这时候没有进度条）")
    elif s.startswith("ERROR:"):
        _say(k, "pip 报错：" + s[6:].strip()[:220], "err")
    return s


def _progress_line(k, line):
    """是进度行就更新进度、返回 True（不写进日志）；不是返回 False。"""
    line = line.strip()
    if line.startswith("@@PROGRESS "):
        try:
            j = json.loads(line[11:])
        except Exception:
            return True
        _set_prog(k, phase=j.get("phase") or "下载", src=j.get("src"), done=j.get("done"), total=j.get("total") or None,
                  speed=j.get("speed"), eta=j.get("eta"))
        return True
    m = PIP_RAW.match(line)
    if m:
        name = (JOB["steps"][k].get("pip_name") or "安装包")
        _set_prog(k, phase="下载 " + name, done=int(m.group(1)), total=int(m.group(2)) or None)
        return True
    m = PIP_DL.match(line)
    if m:
        JOB["steps"][k]["pip_name"] = m.group(1).split("/")[-1][:60]
        return False
    m = TQDM.search(line)
    if m:
        d, t = float(m.group("d")) * UNIT[m.group("du")], float(m.group("t")) * UNIT[m.group("tu")]
        r = float(m.group("r")) * UNIT[m.group("ru")] if m.group("r") else None
        name = re.sub(r"^(Downloading|Downloading \[|下载)\s*", "", m.group("name").strip()).strip("[]: ") or "下载"
        _set_prog(k, phase="下载 " + name[:50], done=d, total=t or None, speed=r, eta=_secs(m.group("eta") or ""),
                  pct=float(m.group("pct")))
        return True
    return False


# 子进程放进一个"作业"里：后端被关掉（包括直接关黑窗口）时，Windows 会把它们一起结束，不会留下没人管的下载
_job_obj = {"h": None}


def _in_job(p):
    if not paths.IS_WIN:
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        if _job_obj["h"] is None:
            class INFO(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]

            class EXT(ctypes.Structure):
                _fields_ = [("Basic", INFO), ("Io", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]
            k32.CreateJobObjectW.restype = ctypes.c_void_p
            h = k32.CreateJobObjectW(None, None)
            info = EXT()
            info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            k32.SetInformationJobObject(ctypes.c_void_p(h), 9, ctypes.byref(info), ctypes.sizeof(info))
            _job_obj["h"] = h
        k32.AssignProcessToJobObject(ctypes.c_void_p(_job_obj["h"]), ctypes.c_void_p(int(p._handle)))
    except Exception as e:
        print("子进程没放进作业（不影响安装）：", e)


def cleanup_orphans():
    """上一次后端被直接关掉时留下的安装、下载进程：按命令行里的本项目路径认出来，按 PID 结束（不碰别的程序）。"""
    try:
        import psutil
    except Exception:
        return 0
    marks = [str(paths.ROOT / "scripts" / "install_ai.py"), str(paths.ROOT / "scripts" / "download_models.py"),
             str(paths.ROOT / "scripts" / "fastdl.py")]
    aienv = str(paths.AI_ENV).lower()
    n = 0
    for p in psutil.process_iter(["pid", "cmdline", "exe"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            exe = (p.info["exe"] or "").lower()
            if p.pid == os.getpid():
                continue
            if any(m in cmd for m in marks) or (exe.startswith(aienv) and " -m pip" in cmd):
                for c in p.children(recursive=True):
                    c.kill()
                p.kill()
                n += 1
        except Exception:
            continue
    if n:
        print(f"结束了上次留下的 {n} 个安装进程")
    return n


# ---------------- 跑子进程（输出写进日志，进度行单独处理） ----------------
def _run_blocking(k, cmd, env_extra):
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "AGENT_FEED": "1"})
    env.update(env_extra or {})
    _log(k, f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(map(str, cmd))}")
    p = subprocess.Popen([str(c) for c in cmd], cwd=str(paths.ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=NOWIN)
    _in_job(p)
    _proc["p"] = p
    buf = ""
    while True:
        chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        parts = re.split(r"[\r\n]", buf)
        buf = parts.pop()
        done = [_narrate(k, x) for x in parts if x.strip() and not _progress_line(k, x)]
        if done:
            _log(k, "\n".join(done))
            JOB["line"] = done[-1].strip()
        if buf.strip() and TQDM.search(buf.strip()):
            _progress_line(k, buf)
    if buf.strip():
        _log(k, _narrate(k, buf))
    code = p.wait()
    _proc["p"] = None
    return code


async def _run(k, cmd, env_extra=None):
    return await asyncio.to_thread(_run_blocking, k, cmd, env_extra)


def _kill():
    p = _proc["p"]
    if not p or p.poll() is not None:
        return
    try:
        if paths.IS_WIN:   # 按 PID 结束这一个进程和它自己开的子进程（pip 等），不碰别的程序
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NOWIN)
        else:
            p.terminate()
    except Exception:
        pass


# ---------------- Git 便携版 ----------------
def _ver(name):
    return tuple(int(x) for x in re.findall(r"\d+", name))


def _git_npmmirror(c):
    base = "https://registry.npmmirror.com/-/binary/git-for-windows/"
    dirs = [i["name"] for i in c.get(base).json() if re.fullmatch(r"v\d+\.\d+\.\d+\.windows\.\d+/", i.get("name", ""))]
    for d in sorted(dirs, key=_ver, reverse=True)[:3]:
        for f in c.get(base + d).json():
            if re.fullmatch(r"MinGit-[\d.]+-64-bit\.zip", f.get("name", "")):
                return f["url"]


def _git_listing(base):
    def find(c):
        html = c.get(base).text
        dirs = sorted(set(re.findall(r'href="(v\d+\.\d+\.\d+\.windows\.\d+)/"', html)), key=_ver, reverse=True)
        for d in dirs[:3]:
            m = re.search(r'href="(MinGit-[\d.]+-64-bit\.zip)"', c.get(base + d + "/").text)
            if m:
                return base + d + "/" + m.group(1)
    return find


def _git_tuna(c):
    base = "https://mirrors.tuna.tsinghua.edu.cn/github-release/git-for-windows/git/LatestRelease/"
    m = re.search(r'href="(MinGit-[\d.]+-64-bit\.zip)"', c.get(base).text)
    return base + m.group(1) if m else None


GIT_SOURCES = [
    ("npmmirror", _git_npmmirror),
    ("华为云镜像", _git_listing("https://mirrors.huaweicloud.com/git-for-windows/")),
    ("清华镜像", _git_tuna),
    ("npmmirror（固定版本 2.47.1）", lambda c: "https://registry.npmmirror.com/-/binary/git-for-windows/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip"),
    ("华为云（固定版本 2.47.1）", lambda c: "https://mirrors.huaweicloud.com/git-for-windows/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip"),
]


def _git_blocking(start):
    dest = paths.TOOLS / "git"
    order = GIT_SOURCES[start % len(GIT_SOURCES):] + GIT_SOURCES[:start % len(GIT_SOURCES)]
    errs = []
    with httpx.Client(timeout=httpx.Timeout(30, read=60), follow_redirects=True) as c:
        for name, find in order:
            try:
                url = find(c)
                if not url:
                    raise RuntimeError("没找到 MinGit 文件")
                _log("git", f"从 {name} 下载：{url}")
                _say("git", f"从「{name}」下载 MinGit：{url.rsplit('/', 1)[-1]}")
                data = io.BytesIO()
                with c.stream("GET", url) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length") or 0)
                    for chunk in r.iter_bytes(1 << 16):
                        data.write(chunk)
                        _set_prog("git", phase="下载 Git", src=name, done=data.tell(), total=total or None)
                zf = zipfile.ZipFile(data)
                if "cmd/git.exe" not in zf.namelist():
                    raise RuntimeError("压缩包里没有 cmd/git.exe")
                tmp = paths.TOOLS / "git.tmp"
                if tmp.exists():
                    tmp.rename(paths.TOOLS / f"git.tmp-old-{int(time.time())}")
                zf.extractall(tmp)
                if dest.exists():   # 不删，改名留着
                    dest.rename(paths.TOOLS / f"git-old-{int(time.time())}")
                tmp.rename(dest)
                _log("git", f"好了：{dest}")
                _say("git", f"解压好了，放在 {paths.show(dest)}", "ok")
                return True, name
            except Exception as e:
                errs.append(f"{name}：{str(e)[:120]}")
                _log("git", f"{name} 不行：{e}")
                _say("git", f"「{name}」不行：{str(e)[:100]}，换下一个", "warn")
    return False, "；".join(errs)


async def s_git(opts):
    if not paths.IS_WIN:
        return False, "只有 Windows 需要（这台不是 Windows，请自己装 git）"
    ok, info = await asyncio.to_thread(_git_blocking, opts.get("mirror_i", 0))
    if not ok:
        return False, "下载失败：" + info
    paths.add_tool_paths()
    memory.init()
    code, out = checks._run(["git", "--version"])
    return (True, f"{out}（便携版，在 {paths.show(paths.TOOLS / 'git')}）") if code == 0 else (False, "解压了但 git 跑不起来：" + out)


# ---------------- 其余几步 ----------------
async def s_aienv(opts):
    code = await _run("aienv", [sys.executable, paths.ROOT / "scripts" / "install_ai.py"], {"AGENT_PIP_MIRROR": "1"} if opts.get("mirror") else None)
    checks._ai_cache.update(ts=0, res=None)
    r = await checks.c_aienv(force=True)
    if code == 0 and r["st"] == "ok":
        return True, r["d"]
    return False, {1: "Python 版本太旧", 2: "显卡版 PyTorch 没装上", 3: "Transformers 等库没装上"}.get(code, f"退出码 {code}") + "；" + r["d"]


async def s_models(opts):
    code = await _run("models", [sys.executable, paths.ROOT / "scripts" / "download_models.py"], {"AGENT_MODEL_SOURCE": "hf"} if opts.get("hf") else None)
    b, e = await checks.c_base(), await checks.c_embed()
    if b["st"] == "ok" and e["st"] == "ok":
        return True, f"底座 {b['d']}；嵌入模型 {e['d']}"
    return False, f"退出码 {code}；底座：{b['d']}；嵌入模型：{e['d']}"


def _file_tail(name, n=40):
    try:
        return (paths.LOGS / name).read_text("utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []


async def s_start(opts):
    _say("start", "启动本地模型服务，加载嵌入模型（第一次要半分钟左右）")
    h = await M.health(fresh=True)
    if h and not h.get("embed_loaded"):
        await M.restart_server()
    try:
        _say("start", "等模型服务回话……")
        h = await M.ensure_server(timeout=300)
    except Exception as e:
        h = None
        err = str(e)
    else:
        err = ""
    _log("start", "\n".join(_file_tail("model_server.log")))
    if h and h.get("embed_loaded") and h.get("cuda"):
        await router.embed_missing()
        return True, "模型服务在线 · 嵌入模型已加载"
    return False, (h or {}).get("error") or err or "模型服务没起来，看 model_server.log"


async def s_kev(opts):
    if settings.S["kevMode"] == "off":
        return True, "设置里关掉了 Kev，跳过"
    _say("kev", "启动 Kev。第一次会经 hf-mirror 下载它的底座（约 1.7GB），放在 models\\hf-cache")
    try:
        stop = asyncio.Event()

        async def follow():
            while not stop.is_set():
                t = _file_tail("kev.log", 3)
                if t:
                    last = t[-1].split("\r")[-1]
                    if not _progress_line("kev", last):
                        JOB["line"] = last[-160:]
                await asyncio.sleep(2)
        f = asyncio.create_task(follow())
        ok = await M.ensure_kev(wait=True, timeout=1800)
        stop.set()
        await f
    except Exception as e:
        ok = False
        _log("kev", str(e))
    _log("kev", "\n".join(_file_tail("kev.log")))
    return (True, "Kev 服务在线") if ok else (False, "Kev 没起来，看 kev.log（下不动的话可以先在 设置 › 本地模型 关掉 Kev）")


async def s_hwmon(opts):
    r = await checks.c_hwmon()
    if r["st"] != "miss":
        return True, r["d"]
    if not paths.IS_WIN:
        return True, "不是 Windows，跳过"
    from . import hwctl
    _say("hwmon", "打开硬件监控助手：第一次会弹一次管理员确认，点「是」。以后跟着 Agent 一起起，不再弹，也没有黑窗口", "warn")
    ok, msg = await hwctl.start(allow_prompt=True)
    if ok:
        settings.update({"hwOn": True})
        r = await checks.c_hwmon()
        return True, r["d"] + ("" if r["st"] == "ok" else "（CPU 温度要装 PawnIO 驱动：pawnio.eu，装完重启电脑）")
    return False, f"硬件监控助手没起来：{msg}"


STEP_FN = {"git": s_git, "aienv": s_aienv, "models": s_models, "start": s_start, "kev": s_kev, "hwmon": s_hwmon}


async def already(k):
    if k == "git":
        return shutil.which("git") is not None
    if k == "aienv":
        return (await checks.c_aienv())["st"] == "ok"
    if k == "models":
        return (await checks.c_base())["st"] == "ok" and (await checks.c_embed())["st"] == "ok"
    if k == "start":
        h = await M.health(fresh=True)
        return bool(h and h.get("embed_loaded"))
    if k == "kev":
        return settings.S["kevMode"] == "off" or await M.kev_ready()
    if k == "hwmon":
        return (await checks.c_hwmon())["st"] != "miss"
    return False


async def choose_fix(k, info, tries):
    allowed = dict(FIXES["common"])
    allowed.update(FIXES.get(k, {}))
    tail = _redact("\n".join(JOB["steps"][k]["tail"][-40:]))
    if not settings.get_secret("dsKey"):
        if tries == 0 and NET_ERR.search(tail + info):
            return "retry", "看着像网络问题，先重试一次（填了 DeepSeek Key 后它会帮你看日志）", ""
        return "manual", "没填 DeepSeek Key，没法自动看日志", ""
    step = next(s for s in STEPS if s["k"] == k)
    sysmsg = ("你在帮一个 Windows 11 用户自动安装本地 AI 助手的组件。电脑：" + (hw.machine() or "未知") + "。"
              "网络：国内，GitHub 打不开；PyPI、清华镜像、阿里云镜像、魔搭、hf-mirror、npmmirror 能用。"
              "你只能从给出的修法里选一个。只输出 JSON：{\"why\":\"一句话说原因\",\"fix\":\"修法代号\",\"tell\":\"要用户手动做的事，一两句话；不需要就留空\"}")
    user = (f"步骤：{step['t']}（{step['d']}）\n已经自动修过 {tries} 次。\n结果：{_redact(info)[:300]}\n可选修法：\n"
            + "\n".join(f"- {a}：{b}" for a, b in allowed.items()) + f"\n日志最后几十行：\n```\n{tail[-6000:]}\n```")
    try:
        out = await deepseek.chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": user}],
                                  json_mode=True, max_tokens=400, purpose="setup_fix")
        j = json.loads(out["text"])
        fix = j.get("fix") if j.get("fix") in allowed else "manual"
        return fix, str(j.get("why", ""))[:200], str(j.get("tell", ""))[:300]
    except Exception as e:
        return ("retry" if tries == 0 else "manual"), f"没问成 DeepSeek：{str(e)[:80]}", ""


async def _sleep(sec):
    for _ in range(int(sec)):
        if JOB["stop"]:
            return
        await asyncio.sleep(1)


async def _job():
    JOB.update(running=True, stop=False, started=time.time(), finished=0.0, cur=None, line="", steps=_blank())
    safety.log("setup.start", {}, "user")
    feed.add(f"开始一键补齐：一共 {len(STEPS)} 步，已经装好的会跳过", "head", job=JOBN)
    try:
        for step in STEPS:
            k = step["k"]
            if JOB["stop"]:
                break
            JOB["cur"], JOB["line"] = k, ""
            i = STEPS.index(step) + 1
            if any(JOB["steps"][n]["st"] != "ok" for n in NEEDS.get(k, [])):
                _mark(k, "blocked", "要等前面的步骤装好")
                _say(k, f"第 {i}/{len(STEPS)} 步「{step['t']}」：要等前面的步骤装好，这次先不做", "warn")
                continue
            _mark(k, "run", "检查中")
            if await already(k):
                _mark(k, "ok", "已经好了，跳过")
                _say(k, f"第 {i}/{len(STEPS)} 步「{step['t']}」：已经装好了，跳过", "ok")
                continue
            feed.add(f"第 {i}/{len(STEPS)} 步：{step['t']} — {step['d']}", "step", job=JOBN, step=step["t"])
            opts = {}
            for attempt in range(3):
                if JOB["stop"]:
                    break
                _mark(k, "run", "进行中" if attempt == 0 else f"第 {attempt + 1} 次尝试", tries=attempt)
                if attempt:
                    _say(k, f"第 {attempt + 1} 次尝试")
                try:
                    ok, info = await STEP_FN[k](opts)
                except Exception as e:
                    ok, info = False, f"出错：{str(e)[:200]}"
                    _log(k, info)
                if ok:
                    _mark(k, "ok", info)
                    s0 = JOB["steps"][k]
                    _say(k, f"「{step['t']}」好了 · 用时 {feed.dur(s0['t1'] - s0['t0'])} · {info}", "ok")
                    break
                if JOB["stop"]:
                    _mark(k, "fail", "已停止")
                    _say(k, "你点了停下，这一步没做完（下次再点一键补齐会接着来）", "warn")
                    break
                _say(k, f"「{step['t']}」没成功：{info}", "err")
                _say(k, "把日志最后几十行交给 DeepSeek 看……" if settings.get_secret("dsKey") else "没填 DeepSeek Key，按简单规则判断")
                fix, why, tell = await choose_fix(k, info, attempt)
                _log(k, f"[自动修] {fix}：{why} {tell}")
                _say(k, f"判断：{why} → {FIX_SAY.get(fix, fix)}", "ds")
                if tell:
                    _say(k, "要你做：" + tell, "warn")
                _mark(k, "fail", info, why=why, tell=tell)
                if attempt == 2:
                    break
                if fix == "wait_retry":
                    JOB["line"] = "等 3 分钟再试"
                    await _sleep(180)
                elif fix == "pypi_mirror":
                    opts["mirror"] = True
                elif fix == "source_hf":
                    opts["hf"] = True
                elif fix == "next_mirror":
                    opts["mirror_i"] = opts.get("mirror_i", 0) + 1
                elif fix == "skip":
                    _mark(k, "skip", info)
                    break
                elif fix == "manual":
                    _mark(k, "manual", info)
                    break
            safety.log("setup.step", {"k": k, "st": JOB["steps"][k]["st"]}, "auto")
    finally:
        JOB.update(running=False, finished=time.time(), cur=None, line="")
        c = {}
        for v in JOB["steps"].values():
            c[v["st"]] = c.get(v["st"], 0) + 1
        bits = [f"{c[x]} 步{n}" for x, n in (("ok", "好了"), ("manual", "要你处理"), ("fail", "失败"), ("skip", "跳过"), ("blocked", "没轮到")) if c.get(x)]
        feed.add(f"一键补齐结束：{'，'.join(bits)} · 总用时 {feed.dur(JOB['finished'] - JOB['started'])}", "head", job=JOBN)
        db.kv_set("setup_last", {"ts": time.time(), "res": {k: v["st"] for k, v in JOB["steps"].items()}})


def start():
    if JOB["running"]:
        return False
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    _task["t"] = asyncio.get_event_loop().create_task(_job())
    return True


def stop():
    JOB["stop"] = True
    _kill()
    return True

