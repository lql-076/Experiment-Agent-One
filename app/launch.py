r"""没有黑窗口的入口：启动.bat 用 pythonw 跑它（pythonw 不开命令行窗口）。

- 说的话照样写进 data\logs\backend.log（界面「后台」页能看）。
- 起不来（缺依赖、端口被占、代码出错）就弹一个框，写清楚原因和日志在哪，不会悄悄没了。
- 想看黑窗口排查问题：在 Agent 文件夹里打开命令行，运行 `启动.bat 看日志`。
"""
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "logs" / "backend.log"
if str(ROOT) not in sys.path:                    # 开机自启是直接跑这个文件（不是 -m app.launch），要把 Agent 文件夹加进来
    sys.path.insert(0, str(ROOT))


def _box(title, msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, title, 0x10 | 0x40000)     # 错误图标 + 放在最前面
    except Exception:
        pass


def _tail(n=12):
    try:
        return "\n".join(LOG.read_text("utf-8", errors="replace").splitlines()[-n:])
    except Exception:
        return ""


def autostart():
    """开机自启（设置 › 自动化）走这里：和 启动.bat 一样打开界面；依赖清单变了（刚更新了新版本）就交给 启动.bat 去补装。
    返回 True = 交给 启动.bat 了，这里不用再起。"""
    os.chdir(ROOT)
    os.environ.setdefault("AGENT_OPEN_UI", "1")
    req, done = ROOT / "requirements.txt", ROOT / ".venv" / "requirements.done"
    try:
        same = done.read_bytes() == req.read_bytes()
    except OSError:
        same = False
    if not same:
        os.startfile(str(ROOT / "启动.bat"))     # 这时候会有装依赖的窗口，装完自己关
        return True
    return False


def _log(msg):
    try:
        from app import window
        window._log_line(msg)
    except Exception:
        pass


def main():
    if "--autostart" in sys.argv and autostart():
        return 0
    if sys.stdout is None:                       # pythonw：没有命令行，先接一个"空的"，后端再把它接到日志文件上
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    t0 = time.time()
    _log("启动.bat：开始启动/检查 Agent 界面")
    try:
        from app import main as backend
        code = backend.run()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        err = traceback.format_exc()
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"\n{time.strftime('%m-%d %H:%M:%S')}  启动出错：\n{err}\n")
        except Exception:
            pass
        _log("启动.bat：启动出错，已写 backend.log")
        _box("Agent 没起来", "Agent 启动时出错了：\n\n" + err.strip().splitlines()[-1][:300] +
             f"\n\n完整原因在：{LOG}\n\n常见原因：依赖没装全（再双击一次 启动.bat）；或者想看黑窗口里的输出：在 Agent 文件夹打开命令行，运行「启动.bat 看日志」。")
        return 1
    # v3.5.1：后端在线（run 返回 10）时，open_ui 已经检查过；这里再以真实 HWND 复检一次。
    # 万一刚才窗口进程刚好在关闭/卡死，不能“退出码 10”就悄悄结束，必须把界面拉出来或说清楚。
    if code == 10 and os.environ.get("AGENT_OPEN_UI") == "1":
        try:
            from app import window
            ok = window.ensure_main_window(target="启动.bat 复检")
            _log("启动.bat：后端已在线，界面复检" + ("成功" if ok else "失败"))
        except Exception as e:
            _log(f"启动.bat：界面复检出错：{e}")
    try:
        from app import window
        window._tel("launch_done", "ok" if code in (0, 10, 11, None) else "err",
                    (time.time() - t0) * 1000, {"code": code}, f"启动.bat 结束，退出码 {code}")
    except Exception:
        pass
    if code not in (0, 10, 11, None):
        _box("Agent 停了", f"Agent 没起来或者停了（退出码 {code}）。日志最后几行：\n\n{_tail()}\n\n完整日志：{LOG}")
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
