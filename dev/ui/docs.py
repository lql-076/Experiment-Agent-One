import sys
from playwright.sync_api import sync_playwright
from common import launch
OUT = sys.argv[1]; errs = []
with sync_playwright() as pw:
    b = launch(pw)
    for (w, h, th) in ((1999, 1077, 'abyss'), (1080, 1860, 'ember'), (1999, 1077, 'nebula')):
        p = b.new_page(viewport={"width": w, "height": h}); p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto("http://127.0.0.1:8765/"); p.wait_for_timeout(3000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()"); p.wait_for_timeout(500)
        p.evaluate(f"setTheme('{th}', 10, 10)"); p.wait_for_timeout(800)
        p.click('.nav[data-view="docs"]'); p.wait_for_timeout(1500)
        print(w, th, "nav items:", p.evaluate("document.querySelectorAll('#docNav [data-doc]').length"), "cur:", p.evaluate("DOCS.cur"))
        p.click('#docNav [data-doc="架构/00-总览.md"]'); p.wait_for_timeout(1800)
        print("  arch svg:", p.evaluate("!!document.querySelector('#liveArch svg')"), "tables:", p.evaluate("document.querySelectorAll('#docBody table').length"), "h2:", p.evaluate("document.querySelectorAll('#docBody h2').length"))
        p.screenshot(path=f"{OUT}/docs-{w}-{th}.png")
        p.click('#docBody a[data-doclink="01-决策脑与分流.md"]'); p.wait_for_timeout(1200)
        print("  after link:", p.evaluate("DOCS.cur"), p.evaluate("(document.querySelector('#docBody h1')||{}).textContent"))
        p.evaluate("openDoc('自动生成/当前结构.md')"); p.wait_for_timeout(1200)
        print("  gen tables:", p.evaluate("document.querySelectorAll('#docBody table').length"), "overflowX:", p.evaluate("document.documentElement.scrollWidth > innerWidth"))
        p.close()
    b.close()
print(errs or "no errors")
sys.exit(1 if errs else 0)
