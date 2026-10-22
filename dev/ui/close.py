import sys
from playwright.sync_api import sync_playwright
from common import launch
OUT = sys.argv[1]; errs = []
MOCK = """window.__calls=[];window.pywebview={api:{state:function(){return Promise.resolve({full:false,max:false,native:true})},
 minimize:function(){__calls.push('min');return Promise.resolve(true)},close_window:function(){__calls.push('close');return Promise.resolve(true)},
 toggle_fullscreen:function(){return Promise.resolve({full:true,max:false,native:true})},begin_move:function(){return Promise.resolve(true)},begin_resize:function(){return Promise.resolve(true)},toggle_max:function(){return Promise.resolve({})}}};"""
with sync_playwright() as pw:
    b = launch(pw)
    for (w, h) in ((1080, 1860),):
        ctx = b.new_context(viewport={"width": w, "height": h}); ctx.add_init_script(MOCK)
        p = ctx.new_page(); p.on("pageerror", lambda e: errs.append(str(e)))
        quits = []
        p.route("**/api/quit", lambda r: (quits.append(1), r.fulfill(status=200, content_type="application/json", body='{"ok":true}')))
        p.goto("http://127.0.0.1:8765/"); p.wait_for_timeout(3000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()"); p.wait_for_timeout(500)
        print(w, "btnClose hidden:", p.evaluate("document.getElementById('btnClose').hidden"))
        p.click("#btnClose"); p.wait_for_timeout(400)
        print("  menu:", p.evaluate("!!document.getElementById('closeMenu')"), p.evaluate("(function(m){var r=m.getBoundingClientRect();return [Math.round(r.left),Math.round(r.top),Math.round(r.right),Math.round(r.bottom)]})(document.getElementById('closeMenu'))"))
        p.screenshot(path=f"{OUT}/close-{w}.png")
        p.click('#closeMenu [data-close="window"]'); p.wait_for_timeout(400)
        print("  calls:", p.evaluate("__calls"), "menu gone:", not p.evaluate("!!document.getElementById('closeMenu')"))
        p.click("#btnClose"); p.wait_for_timeout(300)
        p.check("#closeRemember"); p.click('#closeMenu [data-close="quit"]'); p.wait_for_timeout(800)
        print("  quit api called:", len(quits), "calls:", p.evaluate("__calls"), "closeAct:", p.evaluate("S.set.closeAct"))
        p.evaluate("S.set.closeAct='ask'; pushSet({closeAct:'ask'})"); p.wait_for_timeout(300)
        ctx.close()
    b.close()
print(errs or "no errors")
