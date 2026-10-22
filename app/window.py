"""桌面窗口：无边框，只显示界面本身（没有系统标题栏；收起、关闭按钮在侧栏里）。

由后端自动拉起：pythonw -m app.window（没有黑窗口）。用的是 pywebview + Windows 自带的 WebView2（Edge 内核）。
- 顶栏拖动窗口，由 Windows 接手：拖到屏幕顶部最大化、拖到两边半屏、顶部会出现贴靠布局条（app/winframe.py）
- 双击顶栏：最大化 / 还原；侧栏「全屏 / 窗口」切换全屏
- 窗口模式下，四边和四个角都能拖动改大小
- 每块屏幕按它自己的缩放比例算，拖到缩放不同的屏幕上也不会显示不全
- 窗口大小、位置、是否最大化、是否全屏都会记住（data/window.json）
- 后端停了（点了「退出 Agent」或者后端出错），这个窗口几秒内自己关掉
- 同时只开一个；再启动一次就把已经开着的窗口拿到前面
- 任务栏用自己的图标（ui/icon.ico）

贴靠那套装不上时，退回老办法（网页自己挪窗口）；pywebview 整个用不了时退出码 3，后端改用 Edge 应用模式。
"""
import json
import os
import sys
import threading
import time
import urllib.request

from . import paths

URL = "http://127.0.0.1:8765"
TITLE = "Agent 主控台"
STATE = paths.DATA / "window.json"
MUTEX = "Local\\AgentMainWindow"
ICON = paths.UI / "icon.ico"


def _load():
    try:
        return json.loads(STATE.read_text("utf-8"))
    except Exception:
        return {}


def _save(st):
    try:
        STATE.write_text(json.dumps(st), "utf-8")
    except Exception:
        pass


def _already_open() -> bool:
    """已经开着一个：把它拿到前面，自己退出。"""
    if not paths.IS_WIN:
        return False
    import ctypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.CreateMutexW.restype = ctypes.c_void_p
    _already_open.handle = k32.CreateMutexW(None, False, MUTEX)   # 进程结束前一直持有
    if k32.GetLastError() != 183:                                  # ERROR_ALREADY_EXISTS
        return False
    hwnd = u32.FindWindowW(None, TITLE)
    if hwnd:
        u32.ShowWindow(hwnd, 9)                                    # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
    return True


def _backend_alive() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/ping", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


class Api:
    """界面里通过 window.pywebview.api 调用。只开放这几个动作。"""

    def __init__(self, st):
        self._w = None
        self._st = st
        self._frame = None      # winframe.Frame，装上了才有
        self._last = 0.0

    # 在窗口自己的线程里执行（Windows 要求窗口操作在创建它的线程里做）
    def _ui(self, fn, wait=True):
        from System import Action
        form = self._w.native
        if wait:
            form.Invoke(Action(fn))
        else:
            form.BeginInvoke(Action(fn))

    def state(self):
        f = self._frame
        return {"full": bool(self._st.get("full")), "max": bool(f and f.zoomed()), "native": bool(f)}

    def toggle_fullscreen(self):
        on = not self._st.get("full")
        self._st["full"] = on          # 先记下来：切换时窗口会触发"大小变了"，全屏的大小不能当成窗口大小存
        if self._frame:
            self._ui(lambda: self._frame.set_full(on))
        else:
            self._w.toggle_fullscreen()
        _save(self._st)
        return self.state()

    def toggle_max(self):
        if self._frame:
            self._ui(self._frame.toggle_max)
        return self.state()

    def begin_move(self):
        if self._frame:
            self._ui(self._frame.begin_move, wait=False)
        return True

    def begin_resize(self, edge):
        if self._frame:
            self._ui(lambda: self._frame.begin_resize(str(edge)), wait=False)
        return True

    def minimize(self):
        self._w.minimize()
        return True

    def close_window(self):
        """只关窗口：后端还在跑（提醒、QQ 照常），再双击 启动.bat 就能打开。"""
        threading.Thread(target=self._w.destroy, daemon=True).start()
        return True

    def resize(self, width, height):
        """老办法：右下角拖动改大小（贴靠那套没装上时用）。"""
        if self._st.get("full"):
            return False
        self._w.resize(max(int(width), 640), max(int(height), 480))
        return True

    # 窗口事件：记住窗口模式下的大小和位置
    def _on_resized(self, width, height):
        if self._st.get("full"):
            return
        if self._frame and self._frame.zoomed():
            self._st["max"] = True
        elif width >= 600 and height >= 400:
            self._st.update(w=int(width), h=int(height), max=False)
        self._save_soon()

    def _on_moved(self, x, y):
        if not self._st.get("full") and not (self._frame and self._frame.zoomed()) and x > -10000:
            self._st.update(x=int(x), y=int(y))
            self._save_soon()

    def _save_soon(self):
        if time.time() - self._last > 0.5:
            self._last = time.time()
            _save(self._st)


def _watch_backend(win):
    """后端停了就关窗口。刚启动时多等一会。"""
    time.sleep(15)
    fails = 0
    while True:
        time.sleep(2)
        fails = 0 if _backend_alive() else fails + 1
        if fails >= 3:
            try:
                win.destroy()
            finally:
                return


def _native(api):
    """装上 Windows 原生的拖动、贴靠、改大小。出错就保持老办法。"""
    if not paths.IS_WIN or os.environ.get("AGENT_NATIVE_FRAME") == "0":
        return
    try:
        from . import winframe
        box = {}

        def setup():                    # 拿窗口句柄、装上，都在窗口自己的线程里做
            f = winframe.Frame(int(api._w.native.Handle.ToInt64()))
            f.install()
            box["f"] = f
        api._ui(setup)
        api._frame = box.get("f")
    except Exception as e:
        print("原生窗口没装上，用老办法：", e, file=sys.stderr)
        api._frame = None


def main():
    if _already_open():
        return 0
    if paths.IS_WIN:
        from . import winframe
        winframe.per_monitor_dpi()          # 一定要在导入 pywebview 之前
        winframe.app_id("LHY.Agent.Console")
    try:
        import webview
    except Exception as e:
        print("pywebview 用不了：", e, file=sys.stderr)
        return 3
    st = _load()
    w, h = max(int(st.get("w") or 1600), 640), max(int(st.get("h") or 960), 480)
    api = Api(st)
    opts = dict(title=TITLE, url=URL, width=w, height=h, min_size=(640, 480), frameless=True, easy_drag=False,
                background_color="#05131a", js_api=api, text_select=True)
    if st.get("x") is not None and st.get("y") is not None:
        opts.update(x=int(st["x"]), y=int(st["y"]))
    win = webview.create_window(**opts)
    api._w = win
    win.events.resized += api._on_resized
    win.events.moved += api._on_moved

    def on_shown():
        _native(api)
        # 上次是全屏 / 最大化：窗口出来以后再恢复
        if st.get("full"):
            st["full"] = False
            api.toggle_fullscreen()
        elif st.get("max") and api._frame:
            api._ui(api._frame.toggle_max)
        threading.Thread(target=_watch_backend, args=(win,), daemon=True).start()

    win.events.shown += on_shown
    paths.DATA.mkdir(parents=True, exist_ok=True)
    kw = {"icon": str(ICON)} if ICON.exists() else {}
    webview.start(private_mode=False, storage_path=str(paths.DATA / "webview"), **kw)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        print("窗口出错：", e, file=sys.stderr)
        code = 3
    sys.exit(code)
