r"""Agent 自己的工作文件夹（v2.1）：在里面写、改、删、挪文件、运行程序都行，不用问你。

作者 11-06 / 11-08 定的：
- 单独给 Agent 一个文件夹（默认 Agent 文件夹里的「工作区」；设置 › 记忆与文件 能换到别的盘）。在这个文件夹里它想怎么操作都行，
  不用每次问；别的地方照旧只读（「能读的文件夹」），E 盘只读的规矩不变。
- 改、删、覆盖之前，旧的那份先放进备份（「工作区备份」，在工作区外面，它自己删不到）：工作区备份\日期\时分秒_动作\原来的相对路径。
- 备份半年清一次：每 182 天清一次，清掉放了超过 182 天的；清的时候出一份清单（工作区备份\清理清单\日期_清理清单.md：
  清了哪些、原来在哪、多大、哪天备份的），主页「刚做完」也说一声。
- 运行程序（作者想让 DeepSeek 通过 API 自己做视频看看，必要的权限都给它）：在工作区里执行（Windows 的 cmd），不弹黑窗口；
  python / pip 是工作区专用的 Python 环境（ws-env，第一次运行时自动建；装的包都在这里，不碰 Agent 自己的环境）；
  pip install imageio-ffmpeg 后命令行就有 ffmpeg；pip install playwright 后用 Edge 截网页画面（不用另外下浏览器）。
  拦的：命令或脚本里写了工作区外面的绝对路径、命令里的 ..、%USERPROFILE% 这类环境变量、格式化 / 注册表 / 关机 / 结束进程 / 改权限 /
  PowerShell 这类系统命令。**这不是真沙箱**：拦的是明显越界的，它写的脚本理论上还是碰得到别处；
  不想让它运行程序，设置里关掉「能运行程序」（写、改、删文件不受影响）。
- 每一次操作都记进动作日志（data\logs\actions.jsonl，哈希链）；运行的完整输出写进 data\logs\workspace.log。
- 工作区、备份、ws-env 不进仓库、不进压缩包。
"""
import asyncio
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import db, feed, files, paths, safety, settings

DEFAULT = paths.ROOT / "工作区"
BACKUP = paths.ROOT / "工作区备份"
LISTS = "清理清单"
ENV = paths.ROOT / "ws-env"
LOG = paths.LOGS / "workspace.log"
TMP = ".临时"                                   # 运行程序时的临时文件（TEMP、TMP 指到这里，不往 C 盘写）
KEEP_DAYS = 182                                 # 备份放多久、多久清一次（半年）
MAX_WRITE = 2 << 20                             # 一次最多写 2 MB 文字
MAX_COPY = 2 << 30                              # 一次最多复制 2 GB
MAX_OUT = 6000                                  # 运行的输出最多给模型看多少字（完整的在日志里）
SKIP = {TMP, "node_modules", "__pycache__", ".git", ".venv"}
NOWIN = 0x08000000 if paths.IS_WIN else 0
_run_lock = threading.Lock()
# Agent 文件夹里这些是它自己的东西，工作区不能放进去
INTERNAL = {"app", "ui", "data", "memory", "models", "training", "tools", "kev", "scripts", "dev", "docs", "dist", ".git", ".venv",
            "ai-env", "tts-env", "ws-env", "配音输出", "生图输出", "工作区备份"}


class Denied(files.Denied):
    """不在工作文件夹里，或者被拦下的命令。"""


# ---------------- 在哪 ----------------
def folder() -> Path:
    v = str(settings.S.get("wsDir") or "").strip().strip('"')
    return Path(os.path.expanduser(str(paths.resolve(v, DEFAULT)))).resolve(strict=False)


def ensure() -> Path:
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    return d


def on() -> bool:
    try:
        ensure()
        return True
    except OSError:
        return False


def root_entry():
    """给 files.py：工作区也能读（列目录、搜、读文件），算「能发给 DeepSeek」的。"""
    d = folder()
    return {"path": str(d), "cloud": True} if d.is_dir() else None


def _bin() -> Path:
    return ENV / ("Scripts" if paths.IS_WIN else "bin")


def py() -> Path:
    return _bin() / ("python.exe" if paths.IS_WIN else "python")


def _bad_dir(rp: Path) -> str:
    """能不能当工作文件夹。"""
    if rp.parent == rp:
        return "整个盘太大了，选一个具体的文件夹（比如 F:\\Agent工作区）"
    root = paths.ROOT.resolve()
    if rp == root or files._inside(root, rp):
        return "不能是 Agent 文件夹本身或者它的上级（里面有它自己的程序和数据）"
    if files._inside(rp, root) and rp.relative_to(root).parts[0] in INTERNAL:
        return f"「{rp.relative_to(root).parts[0]}」是 Agent 自己用的文件夹，换一个"
    if files._inside(rp, BACKUP.resolve()):
        return "不能放在备份文件夹里"
    for sysd in (os.environ.get("SystemRoot"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramData")):
        if sysd and files._inside(rp, Path(sysd).resolve()):
            return "这是系统的文件夹，换一个"
    if rp == Path.home().resolve():
        return "整个用户文件夹太大了，选一个具体的文件夹"
    return ""


def set_dir(path):
    """换工作文件夹的位置（只有界面上你点的才走到这里）。原来的文件夹不动，里面的东西不搬。"""
    p = str(path or "").strip().strip('"')
    rp = DEFAULT.resolve() if not p else Path(os.path.expanduser(p)).resolve(strict=False)
    if not rp.is_absolute():
        raise ValueError("写完整的路径，比如 F:\\Agent工作区")
    why = _bad_dir(rp)
    if why:
        raise ValueError(why)
    rp.mkdir(parents=True, exist_ok=True)
    settings.S["wsDir"] = "" if rp == DEFAULT.resolve() else str(rp)
    settings.save()
    safety.log("tool.add", {"perm": "workspace", "path": str(rp)}, "user")
    return status()


def set_run(on_):
    settings.S["wsRun"] = bool(on_)
    settings.save()
    safety.log("tool.add" if on_ else "tool.remove", {"perm": "workspace.run", "on": bool(on_)}, "user")
    return status()


def real(p, must_exist=False) -> Path:
    """工作区里的路径：相对路径按工作区算；写了工作区的名字开头（工作区\\a.txt）也认。出了工作区就拦下。"""
    s = str(p or "").strip().strip('"')
    if not s:
        raise Denied("没给路径")
    base = folder()
    q = Path(s.replace("\\", "/") if not paths.IS_WIN else s)
    if not q.is_absolute():
        parts = q.parts
        if parts and parts[0] == base.name and not (base / parts[0]).exists():
            q = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        rp = (base / q).resolve(strict=False)
    else:
        rp = q.resolve(strict=False)
    if not files._inside(rp, base):
        raise Denied(f"「{s}」不在工作文件夹里：只能在 {paths.show(base)} 里面写、改、删；外面的只能读，要用就先 copy_path 复制进来")
    if files._blocked(rp):
        raise Denied(files._blocked(rp))
    if must_exist and not rp.exists():
        raise Denied(f"找不到：{s}")
    return rp


def rel(rp: Path) -> str:
    try:
        r = rp.relative_to(folder())
        return paths.show(r) if str(r) != "." else "（工作文件夹）"
    except ValueError:
        return paths.show(rp)


def _size(n):
    return files._size(n)


# ---------------- 备份 ----------------
def _backup(rp: Path, op: str):
    """改、删、覆盖之前：旧的放进 工作区备份\\日期\\时分秒_动作\\相对路径。删 = 整个挪进去（能找回来）。"""
    if not rp.exists():
        return None
    r = rp.relative_to(folder())
    now = datetime.now()
    day = BACKUP / now.strftime("%Y-%m-%d")
    d, k = day / f"{now:%H%M%S}_{op}", 2
    while (d / r).exists():
        d, k = day / f"{now:%H%M%S}_{op}_{k}", k + 1
    dst = d / r
    dst.parent.mkdir(parents=True, exist_ok=True)
    if op == "删" or op == "覆盖":
        shutil.move(str(rp), str(dst))
    elif rp.is_dir():
        shutil.copytree(rp, dst)
    else:
        shutil.copy2(rp, dst)
    return dst


def _did(op, what, **kw):
    safety.log("workspace.file", dict({"op": op, "path": what}, **kw), "auto")


# ---------------- 写、改、删、挪、复制 ----------------
def write(path, content, append=False):
    rp = real(path)
    if rp == folder():
        raise Denied("这是工作文件夹本身，给一个文件名（比如 视频\\index.html）")
    if rp.is_dir():
        raise Denied(f"「{rel(rp)}」是个文件夹")
    b = str(content if content is not None else "").encode("utf-8")
    if len(b) > MAX_WRITE:
        raise Denied("一次最多写 2 MB 文字；大的东西用程序生成（run_command）")
    existed = rp.exists()
    bk = _backup(rp, "改") if existed else None
    rp.parent.mkdir(parents=True, exist_ok=True)
    with open(rp, "ab" if append else "wb") as f:
        f.write(b)
    _did("追加" if append else "写", rel(rp), size=len(b), backup=bool(bk))
    return {"path": rp, "rel": rel(rp), "size": rp.stat().st_size, "new": not existed, "backup": bk}


def edit(path, old, new, every=False):
    rp = real(path, True)
    if rp.is_dir():
        raise Denied(f"「{rel(rp)}」是个文件夹")
    if rp.stat().st_size > MAX_WRITE * 4:
        raise Denied("文件太大了，用程序改（run_command）")
    raw = rp.read_bytes()
    txt = files._decode(raw)
    old = str(old or "")
    if not old:
        raise Denied("old 是空的：要写整个文件用 write_file")
    n = txt.count(old)
    if not n:
        raise Denied("没找到 old 那一段（要一字不差，空格、换行都算）；先 read_file 看看现在是什么样")
    if n > 1 and not every:
        raise Denied(f"old 那一段出现了 {n} 次：多带几个字让它只出现一次，或者 all=true 全换")
    txt = txt.replace(old, str(new or "")) if every else txt.replace(old, str(new or ""), 1)
    bk = _backup(rp, "改")
    rp.write_bytes(txt.encode("utf-8"))
    _did("改", rel(rp), n=n if every else 1)
    return {"path": rp, "rel": rel(rp), "n": n if every else 1, "backup": bk}


def delete(path):
    rp = real(path, True)
    if rp == folder():
        raise Denied("不能删工作文件夹本身")
    r = rel(rp)
    is_dir = rp.is_dir()
    bk = _backup(rp, "删")
    _did("删", r, dir=is_dir)
    return {"rel": r, "dir": is_dir, "backup": bk}


def _into(d: Path, dst, s: Path) -> Path:
    """目标是文件夹（已经有的、写了斜杠结尾的、还没有但不带扩展名而源文件带的）：放到它里面。"""
    if d.is_dir() or str(dst).rstrip().endswith(("/", "\\")) or (not d.exists() and not d.suffix and s.is_file() and s.suffix):
        return d / s.name
    return d


def move(src, dst):
    s, d = real(src, True), real(dst)
    if s == folder():
        raise Denied("不能挪工作文件夹本身")
    d = _into(d, dst, s)
    if d == s:
        raise Denied("挪到的地方和原来一样")
    if files._inside(d, s):
        raise Denied("不能挪进它自己里面")
    bk = _backup(d, "覆盖") if d.exists() else None
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    _did("挪", f"{rel(s)} → {rel(d)}", replaced=bool(bk))
    return {"src": rel(s), "dst": rel(d), "backup": bk}


def _tree_size(p: Path, cap=MAX_COPY):
    if p.is_file():
        return p.stat().st_size
    n = 0
    for f in p.rglob("*"):
        if f.is_file():
            n += f.stat().st_size
            if n > cap:
                break
    return n


def copy(src, dst):
    """复制：src 可以在工作区里，也可以在能读的文件夹里（把素材拿进来）；dst 必须在工作区里。"""
    sv = str(src or "").strip().strip('"')
    outside = Path(sv).is_absolute() and not files._inside(Path(sv).resolve(strict=False), folder())
    if outside:
        s = files.check(sv, cloud=True)               # 能读的文件夹（能发给 DeepSeek 的那些）
        if not s.exists():
            raise Denied(f"找不到：{sv}")
    else:
        s = real(sv, True)
    d = _into(real(dst), dst, s)
    if d == s:
        raise Denied("复制到的地方和原来一样")
    if s.is_dir() and files._inside(d, s):
        raise Denied("不能复制进它自己里面")
    if _tree_size(s) > MAX_COPY:
        raise Denied("太大了（一次最多 2 GB）")
    bk = _backup(d, "覆盖") if d.exists() else None
    d.parent.mkdir(parents=True, exist_ok=True)
    if s.is_dir():
        shutil.copytree(s, d, ignore=shutil.ignore_patterns(*SKIP))
    else:
        shutil.copy2(s, d)
    _did("复制", f"{paths.show(s) if not files._inside(s, folder()) else rel(s)} → {rel(d)}", replaced=bool(bk))
    return {"src": paths.show(s), "dst": rel(d), "size": _tree_size(d), "backup": bk}


# ---------------- 运行程序 ----------------
BLOCK_CMDS = {"format", "diskpart", "bcdedit", "reg", "regedit", "shutdown", "logoff", "taskkill", "tskill", "net", "net1", "netsh", "sc", "schtasks",
              "wmic", "vssadmin", "wbadmin", "cipher", "takeown", "icacls", "cacls", "mklink", "runas", "setx", "powershell", "pwsh", "wscript",
              "cscript", "mshta", "rundll32", "regsvr32", "start", "explorer", "bitsadmin", "certutil", "cmd", "sudo", "su", "chmod", "chown",
              "mkfs", "dd", "kill", "pkill", "killall", "reboot", "poweroff", "crontab", "subst", "pushd", "assoc", "ftype", "attrib", "del", "erase",
              "rd", "rmdir", "rm"}
WIN_ABS = re.compile(r'(?<![\w])([A-Za-z]:[\\/][^\s"\'<>|&;,]*|\\\\[^\s"\'<>|&;,]+)')
POSIX_ABS = re.compile(r'(?:(?<=^)|(?<=[\s"\'=]))(/[^\s"\'<>|&;,]+)')
STR_WIN = re.compile(r'["\']([A-Za-z]:[\\/][^"\'\n]*|\\\\\\\\[^"\'\n]+)["\']')
STR_POSIX = re.compile(r'["\'](/(?:home|root|etc|usr|var|tmp|mnt|opt|Users|Volumes)\b[^"\'\n]*)["\']')
DOTDOT = re.compile(r'(?:^|[\s"\'=\\/])\.\.(?:[\\/]|$|[\s"\'])')
ENVVAR = re.compile(r'%[A-Za-z_][A-Za-z0-9_()]*%|\$env:|\$\{?HOME\b|(?:^|\s)~[\\/]', re.I)
HOME_MARK = re.compile(r"expanduser|Path\.home\(|USERPROFILE|LOCALAPPDATA|APPDATA|HOMEPATH|HOMEDRIVE|SystemRoot|ProgramFiles|getenv\(\s*['\"]HOME", re.I)
SCRIPT_EXT = {".py", ".pyw", ".js", ".mjs", ".cjs", ".bat", ".cmd", ".ps1", ".sh"}


def _ok_abs(s: str) -> bool:
    try:
        rp = Path(s.rstrip(".,;:)")).resolve(strict=False)
    except (OSError, ValueError):
        return False
    return files._inside(rp, folder()) or files._inside(rp, ENV.resolve())


def _abs_in(text, rx):
    return [m.group(1) for m in rx.finditer(text) if not _ok_abs(m.group(1))]


def guard(cmd: str) -> str:
    """命令能不能跑：返回拦下的原因，空字符串 = 能跑。"""
    for seg in re.split(r"&&|\|\||[|&;\n]", cmd):
        w = seg.strip().lstrip("(@").strip()
        if not w:
            continue
        first = re.split(r"\s+", w)[0].strip('"\'')
        name = re.sub(r"\.(exe|com|cmd|bat)$", "", Path(first.replace("\\", "/")).name.lower())
        if name in BLOCK_CMDS:
            return (f"「{name}」这类系统命令不让用" + ("（删文件用 delete_path，会先备份）" if name in ("del", "erase", "rd", "rmdir", "rm") else
                                               "（格式化、注册表、关机、结束进程、改权限、PowerShell、开新窗口这些都拦）"))
    bad = _abs_in(cmd, WIN_ABS if paths.IS_WIN else POSIX_ABS)
    if bad:
        return f"命令里有工作文件夹外面的路径：{bad[0][:60]}。用相对路径；外面的文件先 copy_path 复制进来"
    if DOTDOT.search(cmd):
        return "命令里有 ..（往上一级走）：只能在工作文件夹里面用相对路径"
    if ENVVAR.search(cmd):
        return "命令里有 %USERPROFILE%、~ 这类指到别处的写法：只能在工作文件夹里面用相对路径"
    return _scan_scripts()


def _code_files(base: Path):
    n = 0
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".")]
        for fn in fns:
            f = Path(dp) / fn
            if f.suffix.lower() in SCRIPT_EXT:
                n += 1
                if n > 400:
                    return
                yield f


def _scan_scripts() -> str:
    """工作区里的脚本：写死了工作区外面的绝对路径、用户文件夹这类的，拦下（只是挡一下手滑，不是真沙箱）。大的（库文件）不看。"""
    base = folder()
    for f in _code_files(base):
        try:
            if f.stat().st_size > 300_000:
                continue
            t = files._decode(f.read_bytes())
        except OSError:
            continue
        bad = _abs_in(t, STR_WIN if paths.IS_WIN else STR_POSIX)
        if bad:
            return f"脚本 {rel(f)} 里写了工作文件夹外面的路径：{bad[0][:60]}。改成相对路径（素材先 copy_path 复制进来）"
        m = HOME_MARK.search(t)
        if m:
            return f"脚本 {rel(f)} 里用了 {m.group(0)}（指到用户文件夹、系统文件夹）：只能用工作文件夹里的相对路径"
    return ""


def _base_python() -> str:
    b = getattr(sys, "_base_executable", None) or sys.executable
    if paths.IS_WIN:
        c = Path(b).with_name("python.exe")
        if c.exists():
            return str(c)
    return b


def _ensure_env(say=None) -> str:
    """工作区专用的 Python 环境（ws-env）：第一次运行时自动建。返回出错的原因，空字符串 = 好了。"""
    if py().exists():
        return ""
    (say or (lambda _m: None))("第一次运行：在建工作区专用的 Python 环境（十几秒）……")
    try:
        r = subprocess.run([_base_python(), "-m", "venv", str(ENV)], capture_output=True, timeout=300, creationflags=NOWIN, cwd=str(paths.ROOT))
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"工作区的 Python 环境没建起来：{type(e).__name__}"
    if r.returncode != 0 or not py().exists():
        return "工作区的 Python 环境没建起来：" + files._decode(r.stderr or r.stdout)[-200:]
    feed.add(f"建好了工作区专用的 Python 环境（{paths.show(ENV)}）：它运行程序、pip 装的包都在这里", "ok", job="工作区")
    return ""


def _link_ffmpeg():
    """pip install imageio-ffmpeg 之后：把它带的 ffmpeg 放进 ws-env 的 Scripts，命令行直接能用 ffmpeg。"""
    tgt = _bin() / ("ffmpeg.exe" if paths.IS_WIN else "ffmpeg")
    if tgt.exists():
        return
    for sp in ENV.glob("**/site-packages/imageio_ffmpeg/binaries"):
        for f in sp.iterdir():
            if f.name.startswith("ffmpeg") and f.is_file() and (f.suffix.lower() == ".exe" or not paths.IS_WIN):
                with __import__("contextlib").suppress(OSError):
                    shutil.copy2(f, tgt)
                    tgt.chmod(0o755)
                return


def _snap(base: Path):
    out = {}
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP]
        for fn in fns:
            f = Path(dp) / fn
            try:
                st = f.stat()
            except OSError:
                continue
            out[str(f.relative_to(base))] = (st.st_size, st.st_mtime_ns)
            if len(out) >= 5000:
                return out
    return out


def _decode_lines(b: bytes) -> str:
    out = []
    for ln in b.split(b"\n"):
        try:
            out.append(ln.decode("utf-8"))
        except UnicodeDecodeError:
            out.append(ln.decode("gb18030", errors="replace"))
    return "\n".join(out).replace("\r\n", "\n").replace("\r", "\n")


def _kill(p):
    try:
        if paths.IS_WIN:      # 按 PID 结束它和它开的子进程，不碰别的程序
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NOWIN)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except Exception:
        with __import__("contextlib").suppress(Exception):
            p.kill()


def _log(text):
    try:
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 5 << 20:
            LOG.replace(LOG.with_suffix(".old.log"))
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def run(command, timeout=None, say=None):
    """在工作区里运行一条命令。返回 {code, sec, out, timed_out, changed}。"""
    say = say or (lambda _m: None)
    if not settings.S.get("wsRun", True):
        raise Denied("运行程序关着（设置 › 记忆与文件 › 工作文件夹「能运行程序」）：写、改、删文件还能用")
    cmd = str(command or "").strip()
    if not cmd:
        raise Denied("没给命令")
    if len(cmd) > 4000:
        raise Denied("命令太长了：写成脚本文件（write_file）再运行")
    base = ensure()
    why = guard(cmd)
    if why:
        safety.log("workspace.run", {"cmd": cmd[:300], "blocked": why[:120]}, "blocked")
        raise Denied(why)
    err = _ensure_env(say)
    if err:
        raise Denied(err)
    lim = max(5, min(int(timeout or 300), int(settings.S.get("wsTimeout") or 900)))
    env = os.environ.copy()
    for k in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        env.pop(k, None)
    tmp = base / TMP
    tmp.mkdir(exist_ok=True)
    env.update({"PATH": str(_bin()) + os.pathsep + env.get("PATH", ""), "VIRTUAL_ENV": str(ENV), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "TEMP": str(tmp), "TMP": str(tmp), "PLAYWRIGHT_BROWSERS_PATH": str(ENV / "browsers"),
                "AGENT_WORKSPACE": str(base)})
    env.setdefault("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
    before = _snap(base)
    short = cmd if len(cmd) <= 40 else cmd[:38] + "…"
    with _run_lock:
        t0 = time.time()
        _log(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S}  {cmd}\n")
        kw = {"cwd": str(base), "env": env, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "shell": True}
        if paths.IS_WIN:
            kw["creationflags"] = NOWIN | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        p = subprocess.Popen(cmd, **kw)
        with __import__("contextlib").suppress(Exception):
            from .setup import _in_job          # Agent 关了，它开的程序也跟着停
            _in_job(p)
        chunks = []

        def reader():
            for chunk in iter(lambda: p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096), b""):
                chunks.append(chunk)
                _log(_decode_lines(chunk))
        th = threading.Thread(target=reader, daemon=True)
        th.start()
        timed_out, last_say = False, 0.0
        while p.poll() is None:
            el = time.time() - t0
            if el > lim:
                timed_out = True
                _kill(p)
                break
            if el - last_say >= 3:
                say(f"正在运行 {short}（{int(el)} 秒）……")
                last_say = el
            time.sleep(0.25)
        with __import__("contextlib").suppress(subprocess.TimeoutExpired):
            p.wait(timeout=10)
        th.join(timeout=5)
        sec = time.time() - t0
    out = _decode_lines(b"".join(chunks)).strip()
    after = _snap(base)
    changed = []
    for k, v in after.items():
        if k.startswith(TMP):
            continue
        if k not in before:
            changed.append(("新", k, v[0]))
        elif before[k] != v:
            changed.append(("改", k, v[0]))
    changed += [("没了", k, 0) for k in before if k not in after and not k.startswith(TMP)]
    _link_ffmpeg()
    code = p.returncode
    _log(f"===== 用时 {sec:.1f} 秒 · " + ("超时被停了" if timed_out else f"退出码 {code}") + "\n")
    safety.log("workspace.run", {"cmd": cmd[:300], "code": code, "sec": round(sec, 1), "timeout": timed_out, "changed": len(changed)}, "auto")
    return {"cmd": cmd, "code": code, "sec": sec, "out": out, "timed_out": timed_out, "lim": lim, "changed": changed}


# ---------------- 备份半年清一次 ----------------
def clean(force=False, now=None):
    """每 182 天清一次：清掉放了超过 182 天的备份，出一份清单。第一次只记下从哪天开始算。返回这次的结果，没到时间返回 None。"""
    now = now or time.time()
    st = db.kv_get("ws_clean") or {}
    last = float(st.get("ts") or 0)
    if not last and not force:
        db.kv_set("ws_clean", {"ts": now, "n": 0, "bytes": 0, "list": "", "start": True})
        return None
    if not force and now - last < KEEP_DAYS * 86400:
        return None
    t0 = time.time()
    cutoff = now - KEEP_DAYS * 86400
    rows, total = [], 0
    if BACKUP.is_dir():
        for day in sorted(BACKUP.iterdir()):
            if not (day.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day.name)):
                continue
            if datetime.strptime(day.name, "%Y-%m-%d").timestamp() + 86400 > cutoff:
                continue
            for opd in sorted(day.iterdir()):
                if not opd.is_dir():
                    continue
                op = re.sub(r"_\d+$", "", opd.name.split("_", 1)[-1])
                for f in sorted(opd.rglob("*")):
                    if f.is_file():
                        sz = f.stat().st_size
                        total += sz
                        rows.append((day.name, opd.name[:6], op, paths.show(f.relative_to(opd)), sz))
            shutil.rmtree(day, ignore_errors=True)
    d = BACKUP / LISTS
    d.mkdir(parents=True, exist_ok=True)
    lp, k = d / f"{datetime.fromtimestamp(now):%Y-%m-%d}_清理清单.md", 2
    while lp.exists():
        lp, k = d / f"{datetime.fromtimestamp(now):%Y-%m-%d}_清理清单_{k}.md", k + 1
    hm = lambda s: f"{s[:2]}:{s[2:4]}:{s[4:6]}" if len(s) == 6 and s.isdigit() else s   # noqa: E731
    lines = [f"# 工作区备份 · 清理清单（{datetime.fromtimestamp(now):%Y-%m-%d %H:%M}）", "",
             f"半年清一次：这次清掉了放了超过 {KEEP_DAYS} 天的备份（{datetime.fromtimestamp(cutoff):%Y-%m-%d} 以前的），"
             f"一共 {len(rows)} 个文件、{_size(total)}。下次清理大约在 {datetime.fromtimestamp(now + KEEP_DAYS * 86400):%Y-%m-%d}。", ""]
    if rows:
        lines += ["| 哪天备份的 | 几点 | 当时在做什么 | 原来在工作区的哪里 | 大小 |", "|---|---|---|---|---|"]
        lines += [f"| {a} | {hm(b)} | {c} | {e.replace('|', '／')} | {_size(s)} |" for a, b, c, e, s in rows]
    else:
        lines.append("这次没有超过半年的备份，什么都没删。")
    lp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    db.kv_set("ws_clean", {"ts": now, "n": len(rows), "bytes": total, "list": str(lp)})
    msg = f"清理工作区备份：删了 {len(rows)} 个放了超过半年的文件（{_size(total)}），清单在 {paths.show(lp)}" if rows else \
        f"清理工作区备份：没有超过半年的，什么都没删（清单在 {paths.show(lp)}）"
    feed.add(msg, "ok", job="工作区")
    feed.done(f"清理工作区备份 · {len(rows)} 个文件 · {_size(total)}", "Agent", time.time() - t0, "", "ws")
    safety.log("workspace.file", {"op": "清理备份", "n": len(rows), "bytes": total, "list": str(lp)}, "auto")
    return {"n": len(rows), "bytes": total, "list": str(lp)}


async def loop():
    """开着就隔 6 小时看一次到没到半年。"""
    await asyncio.sleep(90)
    while True:
        try:
            await asyncio.to_thread(clean)
        except Exception as e:
            print("清理工作区备份出错：", e)
        await asyncio.sleep(6 * 3600)


# ---------------- 给界面 ----------------
def _count(p: Path, cap=20000):
    n = size = 0
    if not p.is_dir():
        return 0, 0
    for dp, dns, fns in os.walk(p):
        dns[:] = [d for d in dns if d != TMP]
        for fn in fns:
            with __import__("contextlib").suppress(OSError):
                size += (Path(dp) / fn).stat().st_size
            n += 1
            if n >= cap:
                return n, size
    return n, size


def status():
    d = folder()
    n, size = _count(d)
    bn, bsize = _count(BACKUP)
    st = db.kv_get("ws_clean") or {}
    last = float(st.get("ts") or 0)
    sp = list(ENV.glob("**/site-packages"))
    has = lambda name: any((x / name).is_dir() for x in sp)      # noqa: E731
    return {"dir": paths.show(d), "default": d == DEFAULT.resolve(), "exists": d.is_dir(), "files": n, "size": size,
            "backup": paths.show(BACKUP), "backup_files": bn, "backup_size": bsize, "run": bool(settings.S.get("wsRun", True)),
            "timeout": int(settings.S.get("wsTimeout") or 900), "keep_days": KEEP_DAYS,
            "env": py().exists(), "ffmpeg": (_bin() / ("ffmpeg.exe" if paths.IS_WIN else "ffmpeg")).exists(), "playwright": has("playwright"),
            "last_clean": None if st.get("start") or not last else last, "next_clean": last + KEEP_DAYS * 86400 if last else None,
            "last_n": st.get("n", 0), "last_list": paths.show(Path(st["list"])) if st.get("list") and Path(st["list"]).exists() else ""}


# ---------------- 对话里收到的文件（v2.2）----------------
RECV = "收到的"
MAX_RECV = 2 << 30                              # 一个文件最多 2 GB
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe_name(name) -> str:
    """原文件名去掉 Windows 不认的字符（只要名字，不要路径）。"""
    n = str(name or "").replace("\\", "/").split("/")[-1]
    n = _BAD_NAME.sub("_", n).strip().rstrip(". ") or "文件"
    if n.split(".")[0].upper() in _RESERVED:
        n = "_" + n
    if len(n) > 150:
        stem, ext = os.path.splitext(n)
        n = stem[:150 - len(ext)] + ext
    return n


def recv_target(name) -> Path:
    """存到哪：工作区\\收到的\\日期\\原文件名，重名加 (2)、(3)。"""
    d = ensure() / RECV / datetime.now().strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    n = safe_name(name)
    stem, ext = os.path.splitext(n)
    p, k = d / n, 2
    while p.exists() or p.with_name(p.name + ".part").exists():
        p, k = d / f"{stem} ({k}){ext}", k + 1
    return p


def received(rels) -> list:
    """界面传回来的「收到的」文件：只认工作区 收到的\\ 里真有的。"""
    root = (folder() / RECV).resolve(strict=False)
    out = []
    for r in list(rels or [])[:50]:
        try:
            rp = real(r, must_exist=True)
        except Denied:
            continue
        if rp.is_file() and files._inside(rp, root):
            out.append({"path": str(rp), "rel": rel(rp), "name": rp.name, "size": rp.stat().st_size})
    return out


def recv_note(items) -> str:
    """给 DeepSeek 的一段话：收到了哪些文件、在工作区哪；小的文字文件把内容也带上。"""
    if not items:
        return ""
    lines = [f"- {x['rel']}（{_size(x['size'])}）" for x in items]
    parts = ["【他发来的文件，已经放进你的工作文件夹（相对路径）：】\n" + "\n".join(lines) +
             "\n直接用这些路径：read_file 读、copy_path / move_path 挪去用、run_command 里当素材。"]
    for x in items:
        if files.kind_of(Path(x["path"])) in ("text", "docx") and x["size"] <= 200 << 10:
            try:
                r = files.read(x["path"], 0, limit=12000)
                parts.append(f"【{x['rel']} 的内容：】\n{r['text']}" + ("\n（没放完，后面的用 read_file 接着读）" if r.get("more") else ""))
            except Exception:
                pass
    return "\n\n".join(parts)


# ---------------- 给 DeepSeek 的工具 ----------------
def _fn(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": props, "required": req}}}


P = {"type": "string", "description": "工作文件夹里的相对路径，比如 视频\\index.html"}
TOOLS = [
    _fn("write_file", "在你的工作文件夹里写一个文字文件：新建，或者整个覆盖（append=true 接在后面写）。代码、网页、Markdown、字幕、笔记都用它。"
        "原来有的会先自动备份。文件夹不存在会自动建。长文件一定分段写：每次 content 不超过 3000 字，第一段 append=false，后面每段 append=true 接着写"
        "（一次写太长回复会被截断，工具就执行不了）。",
        {"path": P, "content": {"type": "string", "description": "这一段的内容（不超过 3000 字）"}, "append": {"type": "boolean", "description": "true = 接在原来的后面写"}},
        ["path", "content"]),
    _fn("edit_file", "改工作文件夹里一个文件的一段：把 old 换成 new。old 要一字不差、只出现一次（不然多带几个字，或者 all=true 全换）。改之前自动备份。",
        {"path": P, "old": {"type": "string"}, "new": {"type": "string"}, "all": {"type": "boolean"}}, ["path", "old", "new"]),
    _fn("delete_path", "删掉工作文件夹里的一个文件或文件夹（其实是挪进备份，能找回来）。", {"path": P}, ["path"]),
    _fn("move_path", "在工作文件夹里挪、改名。目标已经有了的话，旧的先挪进备份。", {"src": P, "dst": P}, ["src", "dst"]),
    _fn("copy_path", "复制：src 可以是工作文件夹里的，也可以是他允许你读的文件夹里的（把外面的素材拿进来，用完整路径）；dst 必须在工作文件夹里。",
        {"src": {"type": "string", "description": "要复制的文件或文件夹"}, "dst": P}, ["src", "dst"]),
    _fn("run_command", "在你的工作文件夹里运行一条命令（Windows 的 cmd，当前目录就是工作文件夹）：python 脚本、pip install、ffmpeg 这些。"
        "不会弹窗口；输出（最后几千字）、退出码、改动了哪些文件会返回给你。",
        {"command": {"type": "string", "description": "比如 python make.py、pip install imageio-ffmpeg、ffmpeg -y -framerate 30 -i 帧\\%05d.png -c:v libx264 -pix_fmt yuv420p 成品.mp4"},
         "timeout": {"type": "integer", "description": "最多跑多少秒，默认 300"}}, ["command"]),
]
NAMES = {t["function"]["name"] for t in TOOLS}


def tools():
    return [t for t in TOOLS if t["function"]["name"] != "run_command" or settings.S.get("wsRun", True)]


def hint() -> str:
    d = folder()
    run_on = settings.S.get("wsRun", True)
    return (f"你有一个自己的工作文件夹：{d}\n"
            "在这个文件夹里你可以随便新建、写、改、删、挪文件" + ("、运行程序" if run_on else "") + "，不用问他；改和删之前程序会自动备份旧的。"
            "路径用相对路径（相对工作文件夹）。看里面有什么用 list_dir（路径写 .）、读用 read_file。"
            "文件夹外面的只能读（他允许的那些），不能写；要用外面的文件先 copy_path 复制进来。\n" +
            ("运行程序（run_command）：python、pip 是工作文件夹专用的 Python 环境，pip install 的包都装在这里（默认走清华镜像，失败了可以加 -i https://pypi.org/simple 再试）。"
             "做视频：pip install imageio-ffmpeg 以后命令行直接能用 ffmpeg；要把网页动画录成画面，pip install playwright，"
             "然后 chromium.launch(channel='msedge') 用他电脑上的 Edge（不要 playwright install 下浏览器）。"
             "命令和脚本里不要写工作文件夹外面的绝对路径、不要用 ..、%USERPROFILE%、expanduser 这类，会被拦下。"
             f"一条命令最多跑 {int(settings.S.get('wsTimeout') or 900)} 秒（timeout 参数），长的活拆成几步。\n" if run_on else
             "运行程序他关掉了（只能写、改、删文件）。\n") +
            "工具一定用工具调用（function call）来调，不要把调用写成文字。长文件分段写（每段不超过 3000 字，后面的 append=true）。"
            "步骤多的活（比如做视频）：在这件事的文件夹里放一个 进度.md，每做完一段就更新（做完了什么、下一步做什么、文件在哪）；"
            "他说「继续 / 接着做」时先读 进度.md 再接着做，不要从头来。\n"
            "他让你记东西、写东西、做东西时用它；闲聊、问问题不用碰。做完告诉他放在哪（工作文件夹里的路径），出错了照实说。")


def wants(text) -> bool:
    return bool(WANT_RE.search(text or ""))


WANT_RE = re.compile(r"工作区|工作文件夹|做.{0,4}视频|渲染|ffmpeg|写.{0,6}(文件|脚本|代码|程序|网页)|存.{0,4}(成|到|进).{0,6}(文件|文件夹)|"
                     r"(记|写|存|放)(到|进).{0,10}(文件|文件夹|仓库|\.md|\.txt)|建.{0,3}(个|一个)?(文件|文件夹)|运行|跑一下|跑个|脚本|"
                     r"生成.{0,6}(网页|html|视频|文件)|删.{0,3}(文件|文件夹)", re.I)
FILE_RE = re.compile(r"工作区|工作文件夹|文件夹|文件里|\.md\b|\.txt\b|(记|写|存|放)(到|进).{0,10}(文件|仓库)", re.I)


def to_file(text) -> bool:
    """「帮我记一下，记到 XX 文件夹里」：要写成文件，不是记进记忆（v2.1）。"""
    return bool(FILE_RE.search(text or ""))


def run_tool(name, args, say=None):
    """执行一个工作区工具。返回 (给模型的文字, 步骤 [名, 说明])。"""
    say = say or (lambda _m: None)
    if name == "write_file":
        say("正在写文件……")
        r = write(args.get("path"), args.get("content"), bool(args.get("append")))
        return (f"写好了：{r['rel']}（{_size(r['size'])}）" + ("，新建的" if r["new"] else "，原来的备份了") + "。",
                ["写文件", f"{r['rel']} · {_size(r['size'])}" + ("" if r["new"] else " · 旧的备份了")])
    if name == "edit_file":
        say("正在改文件……")
        r = edit(args.get("path"), args.get("old"), args.get("new"), bool(args.get("all")))
        return f"改好了：{r['rel']}（换了 {r['n']} 处，改之前备份了）。", ["改文件", f"{r['rel']} · {r['n']} 处"]
    if name == "delete_path":
        r = delete(args.get("path"))
        return f"删了：{r['rel']}（挪进了备份，能找回来）。", ["删除", f"{r['rel']}" + ("（文件夹）" if r["dir"] else "") + " · 进了备份"]
    if name == "move_path":
        r = move(args.get("src"), args.get("dst"))
        return f"挪好了：{r['src']} → {r['dst']}" + ("（那里原来的备份了）" if r["backup"] else "") + "。", ["挪", f"{r['src']} → {r['dst']}"]
    if name == "copy_path":
        say("正在复制……")
        r = copy(args.get("src"), args.get("dst"))
        return f"复制好了：{r['src']} → {r['dst']}（{_size(r['size'])}）。", ["复制", f"→ {r['dst']} · {_size(r['size'])}"]
    if name == "run_command":
        r = run(args.get("command"), args.get("timeout"), say)
        st = "超时被停了（" + str(r["lim"]) + " 秒）" if r["timed_out"] else ("成功" if r["code"] == 0 else f"退出码 {r['code']}")
        ch = r["changed"]
        chs = "、".join(f"{a} {b}" + (f"（{_size(c)}）" if a != "没了" else "") for a, b, c in ch[:20]) + (f" 等 {len(ch)} 个" if len(ch) > 20 else "")
        out = r["out"]
        if len(out) > MAX_OUT:
            out = f"……（前面省略了 {len(out) - MAX_OUT} 字，完整的在日志里）\n" + out[-MAX_OUT:]
        txt = (f"命令：{r['cmd']}\n用时 {r['sec']:.1f} 秒 · {st}\n" + (f"改动的文件：{chs}\n" if ch else "没有改动文件。\n") +
               "输出：\n" + (out or "（没有输出）"))
        short = r["cmd"] if len(r["cmd"]) <= 36 else r["cmd"][:34] + "…"
        return txt, ["运行", f"{short} · {r['sec']:.0f} 秒 · {st}" + (f" · 改了 {len(ch)} 个文件" if ch else "")]
    raise Denied(f"没有这个工具：{name}")
