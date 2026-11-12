"""界面冒烟测试：每套风格 × 横屏 / 竖屏：主窗口的主页和对话抽屉，每个工具窗口（?tool=，v2.0）。

检查三件事，有一件不过就退出码 1：
  1. 没有 JS 报错
  2. 每个页面都有内容（不是空白）
  3. 页面没有横向溢出（不会出现左右滚动条）
截图放到输出文件夹，方便人眼再看一遍。

用法：
  python dev/ui_smoke.py                 连 http://127.0.0.1:8765/（先 dev/serve.sh start）
  python dev/ui_smoke.py --demo          直接打开 ui/index.html（演示模式，不需要后端）
  python dev/ui_smoke.py 截图文件夹       默认放 dev/.run/shots/
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = pathlib.Path(args[0]) if args else ROOT / "dev" / ".run" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
DEMO = "--demo" in sys.argv
URL = (ROOT / "ui" / "index.html").as_uri() if DEMO else "http://127.0.0.1:8765/"
SIZES = [("横屏", 1680, 1000), ("竖屏", 1080, 1860)]
fails, errs = [], []


def launch(pw):
    try:
        return pw.chromium.launch()
    except Exception:
        # 沙箱里 playwright 版本和自带浏览器对不上时，直接用自带的 Chromium
        return pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")


TOOLS = ["img", "tts", "bgm", "publish", "events", "monitor", "brains", "reports", "settings", "docs"]   # v3.2 加了「发布」；大脑、报告、说明的按钮藏起来了（挪进设置），还在 DOM 里
TOOL_SIZE = {"横屏": (1440, 880), "竖屏": (1080, 1860)}       # 工具窗口（v2.0）：默认 1440×880；竖屏放在竖着的显示器上


def look(p, label, th, v):
    n = p.evaluate(f"(document.getElementById('view-{v}') || {{innerText: ''}}).innerText.trim().length")
    over = p.evaluate("document.documentElement.scrollWidth - innerWidth")
    if not (n > 10 and over <= 1):
        fails.append(f"{label} {th} {v}: 文字 {n} 个，横向溢出 {over}px")


with sync_playwright() as pw:
    b = launch(pw)
    for label, w, h in SIZES:
        # 主窗口：主页（现在、后台在跑、刚做完、Agent 状态）+ 对话抽屉
        p = b.new_page(viewport={"width": w, "height": h})
        p.on("pageerror", lambda e, label=label: errs.append(f"{label}: {e}"))
        p.goto(URL)
        p.wait_for_timeout(2500)
        p.evaluate("var b=document.getElementById('boot'); if (b && b.classList.contains('on')) b.click()")
        p.wait_for_timeout(500)
        themes = p.evaluate("THEMES.map(function (t) { return t.id; })")
        tools = p.evaluate("[].map.call(document.querySelectorAll('.nav[data-tool]'), function (e) { return e.dataset.tool; })")
        if tools != TOOLS:
            fails.append(f"{label}: 左边的工具按钮不对：{tools}")
        for th in themes:
            p.evaluate(f"setTheme('{th}', 10, 10)")
            p.wait_for_timeout(700)
            look(p, label, th, "home")
            p.screenshot(path=str(OUT / f"{label}-{th}-home.png"))
            p.evaluate("chatOpen()")
            p.wait_for_timeout(500)
            if not p.evaluate("!document.getElementById('view-chat').hidden && document.getElementById('chatLog') && document.getElementById('chatLog').innerText.trim().length > 10"):
                fails.append(f"{label} {th}: 对话抽屉打不开或是空的")
            p.screenshot(path=str(OUT / f"{label}-{th}-chat.png"))
            p.evaluate("chatClose()")
            p.wait_for_timeout(400)
        p.close()
        # 工具窗口：地址带 ?tool=，只显示那一个工具
        tw, thh = TOOL_SIZE[label]
        for v in TOOLS:
            p = b.new_page(viewport={"width": tw, "height": thh})
            p.on("pageerror", lambda e, label=label, v=v: errs.append(f"{label} {v}: {e}"))
            p.goto(URL + "?tool=" + v)
            p.wait_for_timeout(2200)
            if p.evaluate("getComputedStyle(document.querySelector('.rail')).display") != "none" or p.evaluate("S.view") != v:
                fails.append(f"{label} {v}: 工具窗口里还有侧栏，或者没显示这个工具（{p.evaluate('S.view')}）")
            for th in themes:
                p.evaluate(f"setTheme('{th}', 10, 10)")
                p.wait_for_timeout(900)
                look(p, label, th, v)
                p.screenshot(path=str(OUT / f"{label}-{th}-{v}.png"))
            p.close()
        print(f"{label}: 主页、对话抽屉、{len(TOOLS)} 个工具窗口 × {len(themes)} 套风格走完", flush=True)
    b.close()

print("JS 报错：", errs or "没有")
print("不过的：", fails or "没有")
print("截图在：", OUT)
sys.exit(1 if errs or fails else 0)
