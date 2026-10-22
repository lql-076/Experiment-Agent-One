import sys, functools
from playwright.sync_api import sync_playwright
from common import launch
print = functools.partial(print, flush=True)
OUT = sys.argv[1]; errs = []
W, H = (int(x) for x in sys.argv[2].split('x')) if len(sys.argv) > 2 else (1980, 1150)
with sync_playwright() as pw:
    b = launch(pw); p = b.new_page(viewport={"width": W, "height": H})
    p.on("pageerror", lambda e: errs.append(str(e))); p.on("console", lambda m: m.type == "error" and errs.append("console: " + m.text))
    p.goto("http://127.0.0.1:8765/"); p.wait_for_timeout(3500)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()"); p.wait_for_timeout(600)
    for th in ("nebula", "abyss", "ember"):
        p.evaluate(f"setTheme('{th}', 10, 10)"); p.wait_for_timeout(1000)
        print("==", th, "data-fx:", p.evaluate("root.dataset.fx"), "lv", p.evaluate("root.dataset.fxlv"))
        # 报告页：长页面
        p.evaluate("goView('reports')"); p.wait_for_timeout(1200)
        print(" reports pend:", p.evaluate("document.querySelectorAll('#view-reports .fx-pend').length"), "scrollH", p.evaluate("(function(v){return [v.scrollHeight,v.clientHeight]})(document.getElementById('view-reports'))"))
        p.mouse.move(W/2, H/2)
        for i in range(6): p.mouse.wheel(0, 300); p.wait_for_timeout(120)
        p.wait_for_timeout(900)
        st = p.evaluate("document.getElementById('view-reports').scrollTop")
        print(" after wheel scrollTop:", st, "stuck:", p.evaluate("document.getElementById('view-reports').classList.contains('fx-stuck')"),
              "pend left:", p.evaluate("document.querySelectorAll('#view-reports .fx-pend').length"),
              "idx:", p.evaluate("(document.getElementById('fxIdx')||{}).textContent"), "--sy:", p.evaluate("document.getElementById('view-reports').style.getPropertyValue('--sy')"))
        p.screenshot(path=f"{OUT}/{th}-reports-scrolled.png")
        p.evaluate("document.getElementById('view-reports').scrollTop=0"); p.wait_for_timeout(300)
        # 大脑页
        p.evaluate("goView('brains')"); p.wait_for_timeout(1300)
        rail = p.evaluate("(function(g){return g?[getComputedStyle(g).display,g.scrollWidth,g.clientWidth,g.scrollLeft]:null})(document.querySelector('#view-brains .bgrid'))")
        print(" brains bgrid:", rail)
        if th == "ember":
            p.mouse.move(W*0.6, H*0.5)
            p.mouse.wheel(0, 120); p.wait_for_timeout(700)
            print("  after 1 wheel scrollLeft:", p.evaluate("document.querySelector('#view-brains .bgrid').scrollLeft"))
            p.mouse.wheel(0, 120); p.wait_for_timeout(700)
            print("  after 2 wheel scrollLeft:", p.evaluate("document.querySelector('#view-brains .bgrid').scrollLeft"), p.evaluate("document.querySelector('#view-brains .bgrid').className"))
            # 拖
            p.mouse.move(W*0.6, H*0.5); p.mouse.down(); p.mouse.move(W*0.4, H*0.5, steps=8); p.mouse.up(); p.wait_for_timeout(800)
            print("  after drag scrollLeft:", p.evaluate("document.querySelector('#view-brains .bgrid').scrollLeft"), "overlay open?", p.evaluate("document.getElementById('ov').classList.contains('on')"))
            print("  ph data-big:", p.evaluate("(document.querySelector('#view-brains .ph')||{dataset:{}}).dataset.big"))
        p.screenshot(path=f"{OUT}/{th}-brains.png")
        # 悬停 + 点击
        p.evaluate("goView('home')"); p.wait_for_timeout(1200)
        box = p.evaluate("(function(){var c=document.querySelector('#view-home button.hc');if(!c)return null;var r=c.getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()")
        if box:
            p.mouse.move(box[0]+box[2]*0.8, box[1]+box[3]*0.3); p.wait_for_timeout(250)
            print(" hover classes:", p.evaluate("document.querySelector('#view-home button.hc').className"), "rx:", p.evaluate("document.querySelector('#view-home button.hc').style.getPropertyValue('--rx')"))
            p.screenshot(path=f"{OUT}/{th}-hover.png")
        # 设置页
        p.evaluate("goView('settings')"); p.wait_for_timeout(600)
        p.evaluate("S.sec='look'; renderSettings()"); p.wait_for_timeout(900)
        print(" tpick display:", p.evaluate("getComputedStyle(document.querySelector('.tpick')).display"), "sbody pend:", p.evaluate("document.querySelectorAll('.sbody .fx-pend').length"))
        p.screenshot(path=f"{OUT}/{th}-look.png")
        p.evaluate("goView('home')"); p.wait_for_timeout(500)
    # 动效关闭
    p.evaluate("S.set.motion='off'; applyLook()"); p.wait_for_timeout(400)
    print("motion off lv:", p.evaluate("root.dataset.fxlv"))
    p.evaluate("goView('reports')"); p.wait_for_timeout(800)
    print(" off pend:", p.evaluate("document.querySelectorAll('.fx-pend').length"))
    p.evaluate("S.set.motion='smooth'; applyLook()")
    b.close()
print(errs or "no errors")
