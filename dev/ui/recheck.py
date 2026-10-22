"""整备 ›「重新自检」弹出的自检窗口：一项一项转圈变对勾，查完停在结果上，「去处理」跳到第一张要处理的卡片。
用法：python dev/ui/recheck.py 截图文件夹 [--demo]（不带 --demo 要先 dev/serve.sh start）"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

from common import launch

ROOT = pathlib.Path(__file__).resolve().parents[2]
args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = args[0] if args else str(ROOT / "dev" / ".run" / "shots")
DEMO = "--demo" in sys.argv
URL = (ROOT / "ui" / "index.html").as_uri() if DEMO else "http://127.0.0.1:8765/"
errs, bad = [], []
with sync_playwright() as pw:
    b = launch(pw)
    for w, h in ((1680, 1000), (1080, 1860)):
        p = b.new_page(viewport={"width": w, "height": h})
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(URL)
        p.wait_for_timeout(1200)
        p.wait_for_function("!S.checking", timeout=30000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(600)
        p.evaluate("S.sec='prep'; renderSettings(); goView('settings')")
        p.wait_for_timeout(800)
        p.click("#recheck")
        seen = []
        for _ in range(40):
            p.wait_for_timeout(120)
            seen.append(p.evaluate("document.querySelectorAll('#bootList .bst.run').length"))
            if seen[-1] == 0:
                break
        if len(seen) >= 2 and len(set(seen)) < 3:
            bad.append(f"{w}: 转圈数没有一项一项减少：{seen}")
        p.wait_for_timeout(300)
        p.screenshot(path=f"{OUT}/recheck-{w}.png")
        st = p.evaluate("""({on: document.getElementById('boot').classList.contains('on'), done: document.getElementById('boot').classList.contains('done'),
            title: bootTitle.textContent, sub: bootSub.textContent, sum: bootSum.textContent, btn: bootSkip.textContent, go: !bootGo.hidden,
            todo: LIVE_CHECKS.length - readyCount()})""")
        print(w, "转圈数变化：", seen[:12], "…" if len(seen) > 12 else "", st, flush=True)
        if not (st["on"] and st["done"] and st["btn"] == "好" and st["go"] == (st["todo"] > 0)):
            bad.append(f"{w}: 查完的状态不对 {st}")
        p.click("#bootList")          # 点卡片里面不关
        p.wait_for_timeout(300)
        if not p.evaluate("document.getElementById('boot').classList.contains('on')"):
            bad.append(f"{w}: 点卡片里面把窗口关了")
        if st["go"]:
            p.click("#bootGo")
            p.wait_for_timeout(1400)
            r = p.evaluate("({on: document.getElementById('boot').classList.contains('on'), view: S.view, sec: S.sec, flash: !!document.querySelector('.su.flash')})")
            print("  去处理 →", r, flush=True)
            if r["on"] or r["view"] != "settings" or r["sec"] != "prep" or not r["flash"]:
                bad.append(f"{w}: 去处理没跳对 {r}")
        else:
            p.click("#bootSkip")
        p.close()
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if errs or bad else 0)
