"""v3.5.1 窗口生命周期、主题首帧、UI 状态增量合并的静态/单元回归。
不移动鼠标、不开真实窗口；真机级联关闭和 启动.bat 双击由 handover 记录里的真机步骤验证。
用法：python dev/test_window.py"""
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import settings, window  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


# ---------- 窗口健康判定 ----------
check(window.classify_window({"exists": False}) == "missing", "没有 HWND：判为 missing（不能直接静默退出）")
check(window.classify_window({"exists": True, "visible": False, "responsive": True}) == "hidden", "有 HWND 但不可见：判为 hidden，要还原")
check(window.classify_window({"exists": True, "visible": True, "responsive": False}) == "hung", "可见但 WM_NULL 超时：判为 hung，要重启")
check(window.classify_window({"exists": True, "visible": True, "responsive": True, "iconic": True}) == "ok", "最小化但可见且响应：判为 ok（还原即可）")
p = window.probe_main_window(120)
check(set(("exists", "hwnd", "pid", "visible", "iconic", "responsive")) <= set(p), "probe_main_window 返回 HWND/进程/可见/最小化/响应状态")
check(hasattr(window, "ensure_main_window") and hasattr(window, "_close_all"), "启动.bat 复检和主窗口级联关闭的实现都在")

# ---------- 主题首帧 ----------
html = (ROOT / "ui" / "index.html").read_text("utf-8")
head = html.split("<body", 1)[0]
theme_script = head.find("agent_theme")
css = head.find('rel="stylesheet" href="css/core.css"')
check(theme_script >= 0, "index.html <head> 里同步读取 agent_theme")
check(css >= 0 and theme_script < css, "主题脚本在第一个 CSS 之前执行（零 FOUC）")
check('data-theme="dark"' in html, "静态 index.html 的默认主题仍是深色")
main_py = (ROOT / "app" / "main.py").read_text("utf-8")
check('VERSION = "3.8.0"' in main_py, "app/main.py VERSION 是 3.8.0")
check("data-theme=\"{theme}\"" in main_py or 'f\'data-theme="{theme}"\'' in main_py or 'f"data-theme=\\"{theme}\\""' in main_py,
      "后端把当前主题注入首页 <html data-theme>（新窗口/清缓存也不先闪深色）")

# ---------- 设置默认值 ----------
check(settings.DEFAULTS.get("theme") == "dark", "app/settings.py 默认主题是深色")
check("uiState" in settings.DEFAULTS and isinstance(settings.DEFAULTS["uiState"], dict), "settings 有 uiState 字段")
check("uiState" not in settings.PERM and "uiState" not in settings.LOCKED, "uiState 走普通设置接口，不占权限/锁定键")

# ---------- UI 状态字段级合并 ----------
old_file, old_s = settings._FILE, dict(settings.S)
try:
    with tempfile.TemporaryDirectory() as td:
        settings._FILE = pathlib.Path(td) / "settings.json"
        settings.S.clear()
        settings.S.update(settings.DEFAULTS)
        settings.S["uiState"] = {}
        settings.update({"theme": "light", "uiState": {"monitorTab": "@trace", "tts": {"speaker": "Serena"}}})
        settings.update({"uiState": {"tts": {"rate": 1.2}}})
        st = settings.S["uiState"]
        check(st.get("monitorTab") == "@trace" and st.get("tts", {}).get("speaker") == "Serena" and st["tts"].get("rate") == 1.2,
              "uiState 增量合并：改 tts.rate 不会丢 monitorTab / tts.speaker")
        settings.update({"uiState": {"tts": {"speaker": "Vivian"}}})
        st = settings.S["uiState"]
        check(st["tts"]["speaker"] == "Vivian" and st["tts"]["rate"] == 1.2 and st["monitorTab"] == "@trace",
              "再改 tts.speaker 仍保留 tts.rate / monitorTab")
        check(settings.S["theme"] == "light", "只改 uiState 不会把主题打回默认深色")
        check(settings._FILE.exists() and json.loads(settings._FILE.read_text("utf-8")).get("uiState", {}).get("tts", {}).get("rate") == 1.2,
              "合并后的 uiState 已落进 settings.json")
        settings.update({"uiState": {"huge": "x" * 40000}})
        check(settings.S["uiState"].get("monitorTab") == "@trace", "异常超大的 uiState 整包丢弃，不清空旧状态")
finally:
    settings._FILE, settings.S = old_file, old_s

# ---------- 前端没有用默认值整体覆盖后端的写法 ----------
main_js = (ROOT / "ui" / "js" / "settings.js").read_text("utf-8")
data_js = (ROOT / "ui" / "js" / "data.js").read_text("utf-8")
check("function markHydrated" in main_js and "HYDRATED" in data_js, "前端有 hydration lock（首次 GET 成功前不写后端）")
check("function pushSet(ch, now)" in main_js and "uiMerge" in data_js, "设置/UI 状态按字段合并而不是整包覆盖")
check("agent_theme" in data_js or "agent_theme" in (ROOT / "ui" / "index.html").read_text("utf-8"), "主题使用独立 agent_theme 键")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
