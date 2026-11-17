r"""桌面窗口：无边框，只显示界面本身（没有系统标题栏；收起、关闭按钮在侧栏里）。

由后端自动拉起：pythonw -m app.window（没有黑窗口）。用的是 pywebview + Windows 自带的 WebView2（Edge 内核）。
- 顶栏拖动窗口，由 Windows 接手：拖到屏幕顶部最大化、拖到两边半屏、顶部会出现贴靠布局条（app/winframe.py）
- 双击顶栏：最大化 / 还原；侧栏「全屏 / 窗口」切换全屏
- 窗口模式下，四边和四个角都能拖动改大小
- 每块屏幕按它自己的缩放比例算，拖到缩放不同的屏幕上也不会显示不全
- 窗口大小、位置、是否最大化、是否全屏都会记住（data/window.json）
- 后端连续 10 次（约 20 秒）连不上才自己关掉，免得后端忙一下就把窗口误关
- 窗口自己的日志在 data\logs\window.log（pythonw 没有黑窗口；超过 5MB 轮转）；暴露给前端的接口都兜住异常，
  不让异常穿过 pythonnet（那会把整个窗口进程炸掉，0xe0434352）
- 同时只开一个；再启动一次就把已经开着的窗口拿到前面
- 任务栏用自己的图标（ui/icon.ico）
- v2.0：生图、配音、设置这些工具点了另开一个独立窗口（open_tool），能拖到另一块屏；每个工具同时只开一个，
  再点就把它拿到前面；每个工具窗口的大小、位置、置顶各记各的（data/window.json 的 tools）

贴靠那套装不上时，退回老办法（网页自己挪窗口）；pywebview 整个用不了时退出码 3，后端改用 Edge 应用模式。
"""
import functools
import json
import logging
import os
import sys
import threading
import time
import traceback
import urllib.request
from urllib.parse import quote

from . import paths

URL = "http://127.0.0.1:8765"
TITLE = "Agent 主控台"
STATE = paths.DATA / "window.json"
MUTEX = "Local\\AgentMainWindow"
ICON = paths.UI / "icon.ico"
# 工具窗口的默认大小：都按 1600×975 的设计尺寸等比缩放（界面里 autoScale），这个大小下字是 0.9 倍；屏幕大就按屏幕的七成八放大
TOOLS = {k: (v, 1440, 880) for k, v in {"img": "生图", "tts": "配音", "bgm": "配乐", "publish": "发布", "events": "事件", "monitor": "后台", "brains": "大脑",
                                         "reports": "报告", "ccode": "Claude Code", "settings": "设置", "docs": "说明"}.items()}
WINS = {}          # 开着的工具窗口：key → webview.Window
MAIN = {}          # 主窗口（工具窗口里点「去对话」时拿到前面）
ROOT_ST = {}       # data/window.json 的全部内容（主窗口 + tools）
WLOG = paths.LOGS / "window.log"
_LOG = {"fh": None}


class _Tee:
    """有控制台时同时写到控制台和 window.log；pythonw（没有控制台）就直接写文件。"""

    def __init__(self, stream, fh):
        self.s, self.f = stream, fh

    def write(self, text):
        try:
            self.s.write(text)
        except Exception:
            pass
        try:
            self.f.write(text)
            self.f.flush()
        except Exception:
            pass
        return len(text)

    def flush(self):
        for x in (self.s, self.f):
            try:
                x.flush()
            except Exception:
                pass

    def __getattr__(self, k):
        return getattr(self.s, k)


def _log_exc(msg):
    try:
        logging.getLogger("agent.window").exception(msg)
    except Exception:
        pass


def _setup_log():
    """窗口自己的日志：pythonw 没有 stderr，闪退时全靠 data\\logs\\window.log。
    超过 5MB 先轮转成 window.old.log；faulthandler、未捕获异常、pywebview 的 logger 都写进来。"""
    if _LOG["fh"] is not None:
        return _LOG["fh"]
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    try:
        if WLOG.exists() and WLOG.stat().st_size > 5 << 20:
            WLOG.replace(WLOG.with_suffix(".old.log"))
    except Exception:
        pass
    try:
        fh = open(WLOG, "a", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        return None
    _LOG["fh"] = fh
    fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 桌面窗口启动 · 进程 {os.getpid()}\n")
    fh.flush()
    sys.stdout = fh if sys.stdout is None else _Tee(sys.stdout, fh)
    sys.stderr = fh if sys.stderr is None else _Tee(sys.stderr, fh)
    try:
        import faulthandler
        faulthandler.enable(file=fh, all_threads=True)
    except Exception:
        pass

    fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%m-%d %H:%M:%S")
    lg = logging.getLogger("agent.window")
    lg.setLevel(logging.INFO)
    lg.handlers.clear()
    h = logging.StreamHandler(fh)
    h.setFormatter(fmt)
    lg.addHandler(h)
    lg.propagate = False

    # pywebview 默认把日志写 stderr；它自己的 _setup_logger 看到有 handler 就不再加。
    pl = logging.getLogger("pywebview")
    pl.setLevel(logging.INFO)
    pl.handlers.clear()
    ph = logging.StreamHandler(fh)
    ph.setFormatter(logging.Formatter("%(asctime)s  [pywebview] %(levelname)s  %(message)s", "%m-%d %H:%M:%S"))
    pl.addHandler(ph)
    pl.propagate = False

    def hook(t, v, tb):
        try:
            fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 未捕获的异常 =====\n")
            traceback.print_exception(t, v, tb, file=fh)
            fh.flush()
        except Exception:
            pass

    def thread_hook(args):
        try:
            name = getattr(getattr(args, "thread", None), "name", "?")
            fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 线程 {name} 出错 =====\n")
            traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=fh)
            fh.flush()
        except Exception:
            pass

    sys.excepthook = hook
    threading.excepthook = thread_hook
    return fh


def _safe(fallback=None):
    """暴露给前端的 js_api 统一兜底：异常记进 window.log，返回安全结果，绝不让它穿过 pythonnet。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrap(self, *a, **kw):
            try:
                return fn(self, *a, **kw)
            except Exception:
                _log_exc(f"窗口接口 {fn.__name__} 出错")
                try:
                    return fallback(self) if callable(fallback) else fallback
                except Exception:
                    return None
        return wrap
    return deco


def _destroy(w):
    """关窗口：后台线程里调 destroy 出错只记日志，不影响别的窗口。"""
    try:
        w.destroy()
    except Exception:
        _log_exc("关闭窗口出错")


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
    """界面里通过 window.pywebview.api 调用。只开放这几个动作。主窗口和每个工具窗口各有一个（key 区分）。"""

    def __init__(self, st, key="main"):
        self._w = None
        self._st = st
        self._key = key
        self._frame = None      # winframe.Frame，装上了才有
        self._last = 0.0

    # 在窗口自己的线程里执行（Windows 要求窗口操作在创建它的线程里做）
    def _ui(self, fn, wait=True):
        if self._w is None or self._w.native is None:
            raise RuntimeError("窗口还没准备好")
        from System import Action
        form = self._w.native
        if wait:
            form.Invoke(Action(fn))
        else:
            form.BeginInvoke(Action(fn))

    def _safe_state(self):
        return {"full": False, "max": False, "native": False, "tool": self._key if self._key != "main" else "", "top": False}

    @_safe(_safe_state)
    def state(self):
        f = self._frame
        return {"full": bool(self._st.get("full")), "max": bool(f and f.zoomed()), "native": bool(f),
                "tool": self._key if self._key != "main" else "", "top": bool(self._st.get("top"))}

    @_safe(False)
    def open_tool(self, key, arg=""):
        """打开一个工具窗口（已经开着就拿到前面）。arg 是「跳到哪一块」（JSON，比如设置的某个分区），已经开着的就告诉它。"""
        key, arg = str(key), str(arg or "")[:400]
        if key not in TOOLS:
            return False
        w = WINS.get(key)
        if w is not None:
            try:
                w.restore()
                w.show()
                if paths.IS_WIN and w.native is not None:
                    self._bring(w)
                if arg:
                    w.evaluate_js(f"toolArg({json.dumps(arg)})")
                return True
            except Exception:
                _log_exc(f"工具窗口 {key} 调用失败，重开一个")
                WINS.pop(key, None)
        threading.Thread(target=open_tool_window, args=(key, arg), daemon=True).start()
        return True

    @_safe(False)
    def open_main(self, arg=""):
        """工具窗口里点「去对话」这类：把主窗口拿到前面（arg：要不要展开对话）。"""
        w = MAIN.get("w")
        if w is None:
            return False
        try:
            w.restore()
            w.show()
            if paths.IS_WIN and w.native is not None:
                self._bring(w)
            if arg:
                w.evaluate_js(f"mainArg({json.dumps(str(arg)[:400])})")
            return True
        except Exception:
            _log_exc("把主窗口拿到前面失败")
            return False

    @_safe(0)
    def broadcast(self, cmd=""):
        """v3.2：深浅色、布局、全屏挪进了设置（设置是单独的窗口）。设置里一改，告诉主窗口和别的工具窗口跟着变（界面里的 winCmd）。"""
        cmd = str(cmd or "")[:400]
        n = 0
        for k, w in [("main", MAIN.get("w"))] + list(WINS.items()):
            if w is None or k == self._key:
                continue
            try:
                w.evaluate_js(f"winCmd({json.dumps(cmd)})")
                n += 1
            except Exception:
                logging.getLogger("agent.window").debug("告诉窗口 %s 失败（可能已经关了）", k, exc_info=True)
        return n

    def _bring(self, w):
        import ctypes
        try:
            h = int(w.native.Handle.ToInt64())
            ctypes.windll.user32.SetForegroundWindow(h)
        except Exception:
            logging.getLogger("agent.window").debug("把窗口拿到前面失败", exc_info=True)

    @_safe(_safe_state)
    def set_top(self, on):
        """工具窗口置顶（钉住）：比如生图窗口放在竖屏上一直看得到。"""
        self._st["top"] = bool(on)
        try:
            self._w.on_top = bool(on)
        except Exception:
            _log_exc("设置窗口置顶失败")
        _save(ROOT_ST)
        return self.state()

    @_safe(_safe_state)
    def toggle_fullscreen(self):
        on = not self._st.get("full")
        self._st["full"] = on          # 先记下来：切换时窗口会触发"大小变了"，全屏的大小不能当成窗口大小存
        if self._frame:
            self._ui(lambda: self._frame.set_full(on))
        else:
            self._w.toggle_fullscreen()
        _save(ROOT_ST)
        return self.state()

    @_safe(_safe_state)
    def toggle_max(self):
        if self._frame:
            self._ui(self._frame.toggle_max)
        return self.state()

    @_safe(False)
    def begin_move(self):
        if self._frame:
            self._ui(self._frame.begin_move, wait=False)
        return True

    @_safe(False)
    def begin_resize(self, edge):
        if self._frame:
            self._ui(lambda: self._frame.begin_resize(str(edge)), wait=False)
        return True

    @_safe(False)
    def minimize(self):
        if self._w is None:
            raise RuntimeError("窗口还没准备好")
        self._w.minimize()
        return True

    @_safe(False)
    def close_window(self):
        """只关窗口：后端还在跑（提醒、QQ 照常），再双击 启动.bat 就能打开。"""
        if self._w is None:
            return False
        threading.Thread(target=_destroy, args=(self._w,), daemon=True).start()
        return True

    @_safe(False)
    def resize(self, width, height):
        """老办法：右下角拖动改大小（贴靠那套没装上时用）。"""
        if self._st.get("full"):
            return False
        if self._w is None:
            raise RuntimeError("窗口还没准备好")
        self._w.resize(max(int(width), 640), max(int(height), 480))
        return True

    # 窗口事件：记住窗口模式下的大小和位置
    @_safe(None)
    def _on_resized(self, width, height):
        if self._st.get("full"):
            return
        if self._frame and self._frame.zoomed():
            self._st["max"] = True
        elif width >= 600 and height >= 400:
            self._st.update(w=int(width), h=int(height), max=False)
        self._save_soon()

    @_safe(None)
    def _on_moved(self, x, y):
        if not self._st.get("full") and not (self._frame and self._frame.zoomed()) and x > -10000:
            self._st.update(x=int(x), y=int(y))
            self._save_soon()

    def _save_soon(self):
        if time.time() - self._last > 0.5:
            self._last = time.time()
            _save(ROOT_ST)


def open_tool_window(key, arg=""):
    """新开一个工具窗口：地址是主界面加 ?tool=key，界面只显示这一个工具（自己的标题栏：拖动、置顶、收起、关掉）。"""
    import webview
    name, dw, dh = TOOLS[key]
    st = ROOT_ST.setdefault("tools", {}).setdefault(key, {})
    api = Api(st, key)
    if not st.get("w"):
        try:
            sc = webview.screens[0]
            k = max(1.0, min(sc.width * 0.78 / dw, sc.height * 0.78 / dh))
            dw, dh = int(dw * k), int(dh * k)
        except Exception:
            pass
    w, h = max(int(st.get("w") or dw), 640), max(int(st.get("h") or dh), 480)
    opts = dict(title=f"{name} · Agent", url=f"{URL}/?tool={key}" + (f"&arg={quote(arg)}" if arg else ""), width=w, height=h, min_size=(640, 480), frameless=True, easy_drag=False,
                background_color="#0a0a0b", js_api=api, text_select=True, on_top=bool(st.get("top")))
    if st.get("x") is not None and st.get("y") is not None:
        opts.update(x=int(st["x"]), y=int(st["y"]))
    win = webview.create_window(**opts)
    api._w = win
    WINS[key] = win
    win.events.resized += api._on_resized
    win.events.moved += api._on_moved
    win.events.closed += lambda: WINS.pop(key, None)

    def shown():
        try:
            _native(api)
            if st.get("max") and api._frame:
                api._ui(api._frame.toggle_max)
        except Exception:
            _log_exc(f"工具窗口 {key} 显示时出错")
    win.events.shown += shown
    return win


def _watch_backend(win):
    """后端停了就关窗口。刚启动时多等一会；连续 10 次（约 20 秒）都不通才关，
    免得后端忙一下（加载模型、NVML 偶发卡顿）就把窗口误关。"""
    time.sleep(15)
    fails = 0
    while True:
        time.sleep(2)
        fails = 0 if _backend_alive() else fails + 1
        if fails >= 10:
            logging.getLogger("agent.window").warning("后端连续 %s 次连不上，关闭窗口", fails)
            for w in list(WINS.values()):
                _destroy(w)
            _destroy(win)
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
    except Exception:
        _log_exc("原生窗口没装上，用老办法")
        api._frame = None


def main():
    _setup_log()
    log = logging.getLogger("agent.window")
    if _already_open():
        log.info("已经开着一个窗口，把已有的拿到前面")
        return 0
    if paths.IS_WIN:
        from . import winframe
        winframe.per_monitor_dpi()          # 一定要在导入 pywebview 之前
        winframe.app_id("LHY.Agent.Console")
    try:
        import webview
    except Exception:
        _log_exc("pywebview 用不了")
        return 3
    st = _load()
    ROOT_ST.clear()
    ROOT_ST.update(st)
    st = ROOT_ST
    w, h = max(int(st.get("w") or 1600), 640), max(int(st.get("h") or 960), 480)
    api = Api(st)
    opts = dict(title=TITLE, url=URL, width=w, height=h, min_size=(640, 480), frameless=True, easy_drag=False,
                background_color="#0a0a0b", js_api=api, text_select=True)
    if st.get("x") is not None and st.get("y") is not None:
        opts.update(x=int(st["x"]), y=int(st["y"]))
    win = webview.create_window(**opts)
    api._w = win
    MAIN["w"] = win
    win.events.resized += api._on_resized
    win.events.moved += api._on_moved

    def on_shown():
        try:
            _native(api)
            # 上次是全屏 / 最大化：窗口出来以后再恢复
            if st.get("full"):
                st["full"] = False
                api.toggle_fullscreen()
            elif st.get("max") and api._frame:
                api._ui(api._frame.toggle_max)
        except Exception:
            _log_exc("主窗口显示时恢复状态出错")
        threading.Thread(target=_watch_backend, args=(win,), daemon=True).start()

    win.events.shown += on_shown
    paths.DATA.mkdir(parents=True, exist_ok=True)
    kw = {"icon": str(ICON)} if ICON.exists() else {}
    webview.start(private_mode=False, storage_path=str(paths.DATA / "webview"), **kw)
    return 0


if __name__ == "__main__":
    _setup_log()
    try:
        code = main()
    except Exception:
        _log_exc("窗口出错")
        code = 3
    sys.exit(code)
