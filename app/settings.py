"""设置与密钥。

设置存在 data/settings.json，界面上改了就写进来。
密钥（DeepSeek Key、QQ AppSecret）单独存在 data/secrets.bin，用 Windows 自带的 DPAPI 加密：
只有你这个 Windows 账号在这台电脑上能解开，拷走文件也没用。导出设置时不包含密钥。
"""
import base64
import json
import sys
import threading

from . import paths

DEFAULTS = {
    # 外观
    "theme": "abyss", "bright": 100, "warmth": 4, "scale": 100, "motion": "smooth", "perf": False,
    "layout": "auto", "h24": True, "demo": False, "autoScale": True, "uiShell": "desk", "closeAct": "ask",
    # 自动化
    "idleRes": "5", "startRes": False, "bootShow": True, "secs": False, "hideCursor": True, "drift": True,
    # 本地模型
    "baseDir": "", "embedDir": "", "loraDir": "", "kevDir": "", "aiPython": "",
    "modelPort": 8090, "kevPort": 8091, "baseQuant": "4bit", "idleUnload": 15,
    "kevMode": "ondemand", "kevRun": "jaredpalmer/kev-0.8b", "hfMirror": True,
    "yieldAuto": True, "yieldGpuLoad": 60, "gpuOnly": True,
    # 云端
    "dsBase": "https://api.deepseek.com", "dsModel": "deepseek-flash", "dsLow": 2, "usdCny": 7.2,
    "priceIn": 0.15, "priceHit": 0.003, "priceOut": 0.60, "peakX": 2, "dsThinking": "auto",
    "searchOn": True, "searchDaily": 200, "searchRounds": 4,
    # 游戏内显示（app/osd.py）
    "osdOn": False, "osdWhen": "game", "osdItems": "fps,low1,cpu,gpu,vram,power", "osdPos": "tl", "osdMargin": 16,
    "osdLayout": "v",                 # v 竖着一列 / h 横着一行（放屏幕顶部居中不挡小地图）
    "osdScreen": 0, "osdSize": "m", "osdOpacity": 80, "osdHotkey": "ctrl+alt+f10",
    # 第三条路「更强的模型」：特别难的事写好提示词，你自己带去问你能用的最强的 AI（网页 Claude、ChatGPT、Kimi……都行）。
    # strongOn=False：不用这条路，这类事也交给 DeepSeek。strongMode 现在只有 manual（你去问）；api（自动调接口）以后加
    "strongOn": True, "strongName": "更强的模型", "strongMode": "manual",
    "claudeTpl": "我在搭一个自己的本地 agent。下面是遇到的问题和相关背景，请帮我分析。聊完请输出一份简短的 Markdown 总结，方便我带回给 agent 学习。",
    # QQ
    "qqEnabled": True, "qqAppId": "", "qqUser": "", "qqSandbox": True,
    # 记忆
    "memDir": "", "useGit": True, "logDays": 90,
    # Obsidian 笔记（app/obsidian.py）：obsVaults 是几个库 [{"id","name","path","ro","private":[私人文件夹]}]
    "obsOn": True, "obsVaults": [], "obsInbox": "Agent 收件箱", "obsRead": True, "obsWrite": True, "obsTidy": True,
    # 分流旋钮
    "take": 60, "fresh": 40, "clLine": 50, "daily": 3, "quiet": False,
    "privLocal": True, "privWords": "", "voteEmbed": 50, "voteAuto": True,
    # 成长
    "fast": True, "slow": True, "samples": 200, "pass": 85, "trainAsk": 2,
    "nightly": True, "synthetic": True, "realFloor": 25,
    # 送达
    "toastFallback": True, "resCard": True, "renotifyMin": 30, "renotifyMax": 2,
    # 硬件
    "hwSource": "auto", "hwUrl": "http://127.0.0.1:8085/data.json", "hwInterval": "2",
    "sysOther": 45, "psuEff": 89,
    "hwOn": False,          # 硬件监控助手：开着就跟着 Agent 一起启动（app/hwctl.py）
    "fpsSkip": "",          # 你说过"不是游戏"的程序（逗号分隔，比如 GamePP.exe），读帧数时跳过
}
SECRET_KEYS = ("dsKey", "qqSecret")
LOCKED = {"gpuOnly": True, "privLocal": True}   # 这两条界面上改不了

_lock = threading.Lock()
_FILE = paths.DATA / "settings.json"
_SECRETS = paths.DATA / "secrets.bin"
S = dict(DEFAULTS)
_listeners = []


def load():
    paths.ensure_dirs()
    try:
        S.update(json.loads(_FILE.read_text("utf-8")))
    except FileNotFoundError:
        pass
    except Exception as e:  # 文件坏了就用默认值，旧文件留着
        _FILE.rename(_FILE.with_suffix(".bad.json"))
        print("设置文件读不了，已改名保存，改用默认设置：", e)
    S.update(LOCKED)
    if S.get("bright") == 92:          # 旧版默认 92% 会一直盖一层暗色，现在默认不调暗
        S["bright"] = 100
    for k in ("nightAuto", "nightStart", "nightEnd", "nightBright", "quietStart", "quietEnd", "nightlyAt", "trainStart",
              "trainEnd", "trainVram", "idleOnly", "ramFreq", "dsCap"):
        S.pop(k, None)                 # 去掉了的设置
    return S


def save():
    with _lock:
        tmp = _FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(S, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(_FILE)


def update(changes: dict) -> dict:
    """界面传来的改动。只接受已知的键，类型跟默认值对齐。"""
    applied = {}
    for k, v in changes.items():
        if k not in DEFAULTS or k in LOCKED:
            continue
        d = DEFAULTS[k]
        try:
            if isinstance(d, bool):
                v = bool(v)
            elif isinstance(d, list):
                if not isinstance(v, list):
                    continue
                if k == "obsVaults":
                    from .obsidian import clean_vaults
                    v = clean_vaults(v)
            elif isinstance(d, int) and not isinstance(d, bool):
                v = int(float(v)) if v != "" else d
            elif isinstance(d, float):
                v = float(v) if v != "" else d
            else:
                v = "" if v is None else str(v)
        except (TypeError, ValueError):
            continue
        if S.get(k) != v:
            S[k] = v
            applied[k] = v
    if applied:
        save()
        for fn in list(_listeners):
            try:
                fn(applied)
            except Exception as e:
                print("设置监听出错：", e)
    return applied


def on_change(fn):
    _listeners.append(fn)
    return fn


# ---------------- 密钥：Windows DPAPI ----------------
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    inp = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inp), None, None, None, None, 0x01, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI 失败")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _read_secrets() -> dict:
    try:
        raw = _SECRETS.read_bytes()
    except FileNotFoundError:
        return {}
    try:
        if raw.startswith(b"DPAPI1"):
            raw = _dpapi(raw[6:], False)
        elif raw.startswith(b"PLAIN1"):  # 只在非 Windows 的开发环境出现
            raw = base64.b64decode(raw[6:])
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        print("密钥文件解不开（换了 Windows 账号？），需要重新填写：", e)
        return {}


def _write_secrets(d: dict):
    raw = json.dumps(d).encode("utf-8")
    if paths.IS_WIN:
        blob = b"DPAPI1" + _dpapi(raw, True)
    else:
        blob = b"PLAIN1" + base64.b64encode(raw)
    tmp = _SECRETS.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(_SECRETS)


def get_secret(k: str) -> str:
    return _read_secrets().get(k, "")


def set_secret(k: str, v: str):
    if k not in SECRET_KEYS:
        raise KeyError(k)
    with _lock:
        d = _read_secrets()
        if v:
            d[k] = v.strip()
        else:
            d.pop(k, None)
        _write_secrets(d)
    for fn in list(_listeners):
        try:
            fn({k: "***"})
        except Exception:
            pass


def secret_hints() -> dict:
    """给界面看：只告诉它有没有、最后 4 位是什么。"""
    d = _read_secrets()
    return {k: ("••••" + d[k][-4:] if d.get(k) else "") for k in SECRET_KEYS}


def is_secure() -> bool:
    return paths.IS_WIN or sys.platform == "win32"
