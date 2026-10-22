"""让无边框窗口像普通 Windows 窗口一样：拖到屏幕顶部最大化、拖到两边半屏、顶部的贴靠布局条、
Win+方向键、最小化/最大化动画、Win11 圆角和阴影。只在 Windows 上用，任何一步出错都退回老办法。

做法（Chrome、Qt 的无边框窗口也是这么做的）：
- 窗口样式加上 WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU，
  Windows 才肯对它做贴靠；
- 接管 WM_NCCALCSIZE，把系统要画的标题栏和边框全部算进内容区，所以看不到任何系统边框；
  最大化时往里收一圈，不然内容会伸出屏幕；
- 拖动和改大小不再由网页自己算位置，而是告诉 Windows "从这里开始拖 / 改大小"，
  由系统接手，贴靠动画就都有了。
- 全屏是自己做的：去掉边框样式，铺满当前屏幕，退出时原样恢复。

每块屏幕按它自己的缩放比例算（Per-Monitor V2），窗口拖到另一块屏幕时网页不会排错尺寸。
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
comctl32 = ctypes.windll.comctl32
dwmapi = ctypes.windll.dwmapi

GWL_STYLE = -16
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00020000, 0x00010000
NATIVE = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
WM_NCCALCSIZE, WM_NCLBUTTONDOWN, WM_DPICHANGED, WM_NCDESTROY, WM_GETMINMAXINFO = 0x0083, 0x00A1, 0x02E0, 0x0082, 0x0024
HTCAPTION = 2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_NOOWNERZORDER, SWP_NOSENDCHANGING = 1, 2, 4, 0x10, 0x20, 0x200, 0x400
SW_MAXIMIZE, SW_RESTORE = 3, 9
SM_CXFRAME, SM_CYFRAME, SM_CXPADDEDBORDER = 32, 33, 92
HT = {"l": 10, "r": 11, "t": 12, "tl": 13, "tr": 14, "b": 15, "bl": 16, "br": 17}

LRESULT = ctypes.c_ssize_t
SUBCLASSPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                  ctypes.c_size_t, ctypes.c_size_t)


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class MINMAXINFO(ctypes.Structure):
    _fields_ = [("ptReserved", wintypes.POINT), ("ptMaxSize", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                ("ptMinTrackSize", wintypes.POINT), ("ptMaxTrackSize", wintypes.POINT)]


MIN_W, MIN_H = 640, 480      # 窗口最小多大（按 100% 缩放算，每块屏幕按它自己的缩放换算）


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT), ("rcNormalPosition", wintypes.RECT)]


user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SendMessageW.restype = LRESULT
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
user32.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t]
comctl32.DefSubclassProc.restype = LRESULT
comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


def per_monitor_dpi():
    """要在 pywebview 之前调用（它会把程序设成"整机一个缩放"，多屏缩放不同时网页会排错尺寸）。"""
    try:
        return bool(user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))   # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            return ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0
        except Exception:
            return False


def app_id(name):
    """任务栏单独成组、用窗口自己的图标（不跟别的 Python 程序混在一起）。"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(name))
    except Exception:
        pass


class Frame:
    def __init__(self, hwnd):
        self.hwnd = wintypes.HWND(hwnd)
        self.full = False
        self._saved = None
        self._proc = SUBCLASSPROC(self._wndproc)    # 一直留着引用，不然会被回收

    # ---------- 安装（必须在窗口自己的线程里调用） ----------
    def install(self):
        if not comctl32.SetWindowSubclass(self.hwnd, self._proc, 0xA6E7, 0):
            raise OSError("SetWindowSubclass 失败")
        style = user32.GetWindowLongPtrW(self.hwnd, GWL_STYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, style | NATIVE)
        self._corner(2)                             # Win11 圆角
        user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)

    def _dwm(self, attr, v):
        try:
            val = ctypes.c_uint(v)
            dwmapi.DwmSetWindowAttribute(self.hwnd, attr, ctypes.byref(val), 4)
        except Exception:
            pass

    def _corner(self, v):
        self._dwm(33, v)                            # DWMWA_WINDOW_CORNER_PREFERENCE：2 圆角，1 直角
        if v == 2:
            self._dwm(20, 1)                        # 深色模式：边上那一像素也是深色
            self._dwm(34, 0xFFFFFFFE)               # 不画 Win11 的彩色细边框

    def _frame_px(self):
        dpi = user32.GetDpiForWindow(self.hwnd) or 96
        pad = user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
        return user32.GetSystemMetricsForDpi(SM_CXFRAME, dpi) + pad, user32.GetSystemMetricsForDpi(SM_CYFRAME, dpi) + pad

    def _wndproc(self, hwnd, msg, wp, lp, uid, ref):
        try:
            if msg == WM_NCCALCSIZE and wp:
                # 整个窗口都是内容区：系统的标题栏和边框都不画
                if not self.full and user32.IsZoomed(hwnd):
                    p = NCCALCSIZE_PARAMS.from_address(lp)
                    fx, fy = self._frame_px()        # 最大化时 Windows 会让窗口伸出屏幕一圈，收回来
                    r = p.rgrc[0]
                    r.left, r.top, r.right, r.bottom = r.left + fx, r.top + fy, r.right - fx, r.bottom - fy
                return 0
            if msg == WM_GETMINMAXINFO and lp:
                # 最小尺寸按"当前这块屏幕"的缩放算，而且不超过这块屏幕本身。
                # 之前用的是窗口创建时那块屏幕的缩放（主屏 125% 时最小宽 1200），
                # 到了 1080 宽的竖屏上，全屏会被撑到 1200 宽，右边一截跑到屏幕外面。
                res = comctl32.DefSubclassProc(hwnd, msg, wp, lp)
                mm = MINMAXINFO.from_address(lp)
                if self.full:
                    mm.ptMinTrackSize.x, mm.ptMinTrackSize.y = 1, 1
                else:
                    k = (user32.GetDpiForWindow(hwnd) or 96) / 96
                    w, h = self._work_size()
                    mm.ptMinTrackSize.x = int(min(MIN_W * k, w or MIN_W * k))
                    mm.ptMinTrackSize.y = int(min(MIN_H * k, h or MIN_H * k))
                return res
            if msg == WM_DPICHANGED and lp:
                # 拖到缩放比例不同的屏幕：按 Windows 建议的大小调整，网页会按新屏幕的比例重新排版
                r = wintypes.RECT.from_address(lp)
                user32.SetWindowPos(hwnd, None, r.left, r.top, r.right - r.left, r.bottom - r.top, SWP_NOZORDER | SWP_NOACTIVATE)
                return 0
        except Exception:
            pass
        return comctl32.DefSubclassProc(hwnd, msg, wp, lp)

    def _monitor(self):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(user32.MonitorFromWindow(self.hwnd, 2), ctypes.byref(mi))
        return mi

    def _work_size(self):
        try:
            r = self._monitor().rcWork
            return r.right - r.left, r.bottom - r.top
        except Exception:
            return 0, 0

    # ---------- 动作（也都在窗口线程里调用） ----------
    def begin_move(self):
        """从这里开始拖：交给 Windows，贴靠、半屏、布局条都由系统做。"""
        if self.full:
            return
        user32.ReleaseCapture()
        user32.SendMessageW(self.hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)

    def begin_resize(self, edge):
        if self.full or user32.IsZoomed(self.hwnd) or edge not in HT:
            return
        user32.ReleaseCapture()
        user32.SendMessageW(self.hwnd, WM_NCLBUTTONDOWN, HT[edge], 0)

    def zoomed(self):
        return bool(user32.IsZoomed(self.hwnd))

    def toggle_max(self):
        if self.full:
            return
        user32.ShowWindow(self.hwnd, SW_RESTORE if self.zoomed() else SW_MAXIMIZE)

    def set_full(self, on):
        if on == self.full:
            return
        if on:
            wp = WINDOWPLACEMENT()
            wp.length = ctypes.sizeof(WINDOWPLACEMENT)
            user32.GetWindowPlacement(self.hwnd, ctypes.byref(wp))
            style = user32.GetWindowLongPtrW(self.hwnd, GWL_STYLE)
            self._saved = (style, wp)
            mi = self._monitor()
            self.full = True
            user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, style & ~(WS_CAPTION | WS_THICKFRAME))
            self._corner(1)
            m = mi.rcMonitor
            # NOSENDCHANGING：不让最小尺寸之类的限制插手，窗口正好等于这块屏幕
            user32.SetWindowPos(self.hwnd, None, m.left, m.top, m.right - m.left, m.bottom - m.top,
                                SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED | SWP_NOSENDCHANGING)
        else:
            style, wp = self._saved or (user32.GetWindowLongPtrW(self.hwnd, GWL_STYLE) | NATIVE, None)
            self.full = False
            user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, style)
            self._corner(2)
            if wp is not None:
                user32.SetWindowPlacement(self.hwnd, ctypes.byref(wp))
            user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED)
