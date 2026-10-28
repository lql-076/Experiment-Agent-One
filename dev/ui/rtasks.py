"""常驻屏的后台任务进度条（v1.8.8）：没任务时不显示；有任务（安装配音、一键补齐、生成配音）时硬件格子下面多一条。
连测试后端真的点一次「安装配音」（假的安装，放慢了走），看常驻屏上出现进度条、数字在走；
横屏 1680×1000、竖屏 1080×1860、三套风格都要一屏放下（fit.py 不查常驻屏，这里查）；点「停下」后进度条自己消失。
用法：python dev/ui/rtasks.py 截图文件夹（要先 dev/serve.sh start）"""
import pathlib
import sys

import httpx
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
SLOW = pathlib.Path(__file__).resolve().parents[1] / ".run" / "fake_tts_install_slow.flag"
H = {"X-Agent": "1"}
errs, bad = [], []
FIT = """() => { var e = document.querySelector('#rTasks'), r = e.getBoundingClientRect(), s = document.querySelector('#resident .rs');
  return {shown: !e.hidden && r.height > 0, bottom: Math.round(r.bottom), h: innerHeight, over: s.scrollHeight - s.clientHeight,
          rows: e.querySelectorAll('.rtask').length, text: e.innerText.replace(/\\s+/g, ' ').trim()}; }"""


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def open_page(b, w, h):
    p = b.new_page(viewport={"width": w, "height": h})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/")
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    return p


with sync_playwright() as pw:
    b = launch(pw)
    p = open_page(b, 1680, 1000)
    p.evaluate("enterResident()")
    p.wait_for_timeout(2500)
    check(not p.evaluate(FIT)["shown"], "没有后台任务：常驻屏不显示进度条")
    p.close()
    SLOW.write_text("1")
    httpx.post("http://127.0.0.1:8765/api/tts/install", json={}, headers=H)
    try:
        for w, h in ((1680, 1000), (1080, 1860)):
            p = open_page(b, w, h)
            for th in ("abyss", "nebula", "ember"):
                p.evaluate(f"setTheme('{th}', 5, 5)")
                p.wait_for_timeout(500)
                p.evaluate("enterResident()")
                p.wait_for_selector('#rTasks .rtask[data-k="tts_install"]', timeout=8000)
                p.wait_for_timeout(2200)
                r = p.evaluate(FIT)
                check(r["shown"] and r["bottom"] <= r["h"] and r["over"] <= 1 and "安装配音" in r["text"],
                      f"{w}×{h} {th}：「{r['text'][:46]}」在一屏里（底边 {r['bottom']} / {r['h']}）")
                p.screenshot(path=f"{OUT}/rtasks-{w}-{th}.png")
                p.evaluate("exitResident()")
                p.wait_for_timeout(1400)
            p.close()
        for w, h in ((1080, 1860), (1680, 1000)):           # 字调到 130%（作者竖屏字比较大）：放不下就收紧格子，还是一屏
            p = open_page(b, w, h)
            p.evaluate("setTheme('abyss', 5, 5); S.set.scale = 130; applyScale(); enterResident()")
            p.wait_for_selector('#rTasks .rtask', timeout=8000)
            p.wait_for_timeout(2500)
            r = p.evaluate(FIT)
            check(r["bottom"] <= r["h"] and r["over"] <= 1, f"{w}×{h} 字 130%：进度条也在一屏里（底边 {r['bottom']} / {r['h']}）")
            p.screenshot(path=f"{OUT}/rtasks-{w}-130.png")
            p.evaluate("S.set.scale = 100; applyScale()")
            p.close()
        p = open_page(b, 1680, 1000)
        p.evaluate("enterResident()")
        p.wait_for_selector('#rTasks .rtask', timeout=8000)
        a = p.evaluate(FIT)["text"]
        p.wait_for_timeout(7500)
        z = p.evaluate(FIT)["text"]
        check(a != z, f"进度在走（常驻屏每 2 秒更新）：{a[-24:]} → {z[-24:]}")
    finally:
        SLOW.unlink(missing_ok=True)
        httpx.post("http://127.0.0.1:8765/api/tts/install/stop", headers=H)
    p.wait_for_function("document.getElementById('rTasks').hidden", timeout=15000)
    check(True, "停下以后：进度条自己消失")
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
