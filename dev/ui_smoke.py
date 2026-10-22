"""界面冒烟测试：每套风格 × 横屏 / 竖屏，每个页面点一遍。

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


with sync_playwright() as pw:
    b = launch(pw)
    for label, w, h in SIZES:
        p = b.new_page(viewport={"width": w, "height": h})
        p.on("pageerror", lambda e, label=label: errs.append(f"{label}: {e}"))
        p.goto(URL)
        p.wait_for_timeout(2500)
        p.evaluate("var b=document.getElementById('boot'); if (b && b.classList.contains('on')) b.click()")
        p.wait_for_timeout(500)
        themes = p.evaluate("THEMES.map(function (t) { return t.id; })")
        views = p.evaluate("[].map.call(document.querySelectorAll('.nav[data-view]'), function (e) { return e.dataset.view; })")
        for th in themes:
            p.evaluate(f"setTheme('{th}', 10, 10)")
            p.wait_for_timeout(700)
            for v in views:
                p.click(f'.nav[data-view="{v}"]')
                p.wait_for_timeout(900)
                n = p.evaluate(f"(document.getElementById('view-{v}') || {{innerText: ''}}).innerText.trim().length")
                over = p.evaluate("document.documentElement.scrollWidth - innerWidth")
                ok = n > 10 and over <= 1
                if not ok:
                    fails.append(f"{label} {th} {v}: 文字 {n} 个，横向溢出 {over}px")
                p.screenshot(path=str(OUT / f"{label}-{th}-{v}.png"))
            print(f"{label} {th}: {len(views)} 个页面走完", flush=True)
        p.close()
    b.close()

print("JS 报错：", errs or "没有")
print("不过的：", fails or "没有")
print("截图在：", OUT)
sys.exit(1 if errs or fails else 0)
