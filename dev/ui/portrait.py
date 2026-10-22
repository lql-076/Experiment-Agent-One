import sys
from playwright.sync_api import sync_playwright
from common import launch
OUT = sys.argv[1]; errs = []
with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1080, "height": 1860}); p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/"); p.wait_for_timeout(3000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()"); p.wait_for_timeout(500)
    p.evaluate("setTheme('nebula', 10, 10)"); p.wait_for_timeout(900)
    p.evaluate("api('POST','/api/setup/start',{})"); p.wait_for_timeout(3500)
    p.click('.nav[data-view="monitor"]'); p.wait_for_timeout(3000)
    v = p.evaluate("(function(){var v=document.getElementById('view-monitor');return [v.scrollHeight, v.clientHeight]})()")
    print("view scroll/client:", v, "tabbody h:", p.evaluate("document.querySelector('.tabbody').getBoundingClientRect().height"))
    p.screenshot(path=f"{OUT}/port-mon.png")
    b.close()
print(errs or "no errors")
