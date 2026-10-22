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


def main():
    if sys.stdout is None:                       # pythonw：没有命令行，先接一个"空的"，后端再把它接到日志文件上
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout
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
        _box("Agent 没起来", "Agent 启动时出错了：\n\n" + err.strip().splitlines()[-1][:300] +
             f"\n\n完整原因在：{LOG}\n\n常见原因：依赖没装全（再双击一次 启动.bat）；或者想看黑窗口里的输出：在 Agent 文件夹打开命令行，运行「启动.bat 看日志」。")
        return 1
    if code not in (0, 10, 11, None):
        _box("Agent 停了", f"Agent 没起来或者停了（退出码 {code}）。日志最后几行：\n\n{_tail()}\n\n完整日志：{LOG}")
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
