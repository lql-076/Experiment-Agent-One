"""设置 › 云端的联网搜索那一块：次数、开关、「测试一下」；事件页能看到搜了什么、读了哪页。
用法：python dev/ui/search.py 截图文件夹（要先 dev/serve.sh start）"""
import sys

from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
errs, bad = [], []
with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1680, "height": 1000})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/")
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.evaluate("S.sec='cloud'; renderSettings(); goView('settings')")
    p.wait_for_timeout(900)
    labels = p.evaluate("[].map.call(document.querySelectorAll('#sbody label, #sbody .label'), function (e) { return e.textContent.trim(); }).join(' | ')")
    for need in ("联网搜索", "每天最多搜几次", "一个问题最多查几轮"):
        if need not in labels:
            bad.append("设置里没有「" + need + "」")
    p.click("#searchTest")
    p.wait_for_timeout(1500)
    out = p.evaluate("(document.getElementById('searchOut') || {}).textContent || ''")
    print("测试一下 →", out[:80], flush=True)
    if not out.startswith("能用"):
        bad.append("测试一下没出结果：" + out)
    p.screenshot(path=f"{OUT}/search-settings.png")
    # 事件页：问一句最新的，点开看步骤
    p.evaluate("goView('events')")
    p.wait_for_timeout(800)
    p.fill("#chatIn", "帕鲁最近更新了什么") if p.query_selector("#chatIn") else None
    p.evaluate("api('POST', '/api/chat', {text: '帕鲁最近更新了什么'}, 60000)")
    p.wait_for_timeout(2500)
    p.evaluate("typeof fetchEvents === 'function' && fetchEvents()")
    p.wait_for_timeout(1500)
    p.click("#evlist .ev >> nth=0")
    p.wait_for_timeout(900)
    txt = p.evaluate("(document.querySelector('.detail') || {}).innerText || ''")
    print("事件详情里有联网搜索：", "联网搜索" in txt, "读网页：", "读网页" in txt, flush=True)
    if "联网搜索" not in txt:
        bad.append("事件详情里看不到联网搜索那一步")
    p.screenshot(path=f"{OUT}/search-event.png")
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if errs or bad else 0)
