import sys
from playwright.sync_api import sync_playwright
from common import launch
OUT = sys.argv[1]; errs = []
with sync_playwright() as pw:
    b = launch(pw); p = b.new_page(viewport={"width": 1999, "height": 1077})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/"); p.wait_for_timeout(3500)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()"); p.wait_for_timeout(600)
    p.evaluate("setTheme('abyss', 10, 10)"); p.wait_for_timeout(800)
    p.evaluate("goView('settings')"); p.wait_for_timeout(400); p.evaluate("S.sec='cloud'; renderSettings()"); p.wait_for_timeout(800)
    print("tag:", p.evaluate("document.getElementById('f-dsModel').tagName"), p.evaluate("[...document.querySelectorAll('#f-dsModel option')].map(o=>o.textContent)"))
    p.select_option("#f-dsModel", "deepseek-chat"); p.wait_for_timeout(1500)
    print("saved:", p.evaluate("api('GET','/api/settings').then(j=>j.settings.dsModel)"))
    p.select_option("#f-dsModel", "__manual"); p.wait_for_timeout(500)
    print("manual tag:", p.evaluate("document.getElementById('f-dsModel').tagName"), p.evaluate("document.activeElement.id"))
    p.click("[data-fetch-models]"); p.wait_for_timeout(1500)
    print("after refresh tag:", p.evaluate("document.getElementById('f-dsModel').tagName"), p.evaluate("(document.querySelector('.toast')||{}).textContent"))
    p.screenshot(path=f"{OUT}/cloud.png")
    b.close()
print(errs or "no errors")
