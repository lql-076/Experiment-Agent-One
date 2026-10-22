"""说明页的树状图：每篇架构都画得出来、能收起展开、→ 能跳转、状态灯有颜色、图 / 文字能切换、竖屏不溢出。
用法：python dev/ui/tree.py 截图文件夹（要先 dev/serve.sh start）"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

from common import launch

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "dev" / ".run" / "shots")
errs, bad = [], []
with sync_playwright() as pw:
    b = launch(pw)
    for w, h, th in ((1680, 1000, "nebula"), (1080, 1860, "abyss"), (1999, 1077, "ember")):
        p = b.new_page(viewport={"width": w, "height": h})
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.add_init_script("try{localStorage.removeItem('agentDocs.mode');localStorage.removeItem('agentDocs.cur')}catch(e){}")
        p.goto("http://127.0.0.1:8765/")
        p.wait_for_timeout(1500)
        p.wait_for_function("!S.checking", timeout=30000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.evaluate(f"setTheme('{th}', 10, 10)")
        p.wait_for_timeout(500)
        p.click('.nav[data-view="docs"]')
        p.wait_for_timeout(2000)
        arch = p.evaluate("[].map.call(document.querySelectorAll('#docNav [data-doc]'), function (e) { return e.dataset.doc; }).filter(isArch)")
        if len(arch) != 14:
            bad.append(f"{w}: 架构图只有 {len(arch)} 篇")
        for rel in arch:
            p.evaluate(f"openDoc('{rel}')")
            p.wait_for_timeout(700)
            r = p.evaluate("""({nodes: document.querySelectorAll('.tn:not(.gone)').length, trees: document.querySelectorAll('.tree-wrap').length,
                over: document.documentElement.scrollWidth - innerWidth, h: (document.querySelector('.tree-size') || {}).offsetHeight || 0,
                overlap: (function () { var r = [].map.call(document.querySelectorAll('.tn:not(.gone)'), function (e) { return e.getBoundingClientRect(); }), n = 0;
                  for (var i = 0; i < r.length; i++) for (var j = i + 1; j < r.length; j++) { var a = r[i], c = r[j]; if (a.left < c.right - 1 && c.left < a.right - 1 && a.top < c.bottom - 1 && c.top < a.bottom - 1) n++; } return n; })()})""")
            if not r["trees"] or r["nodes"] < 8 or r["over"] > 1 or r["overlap"] or r["h"] < 100:
                bad.append(f"{w} {rel}: {r}")
            if rel.endswith(("00-总览.md", "04-QQ通道与提醒.md", "09-整备与一键补齐.md")):
                p.wait_for_timeout(600)
                p.screenshot(path=f"{OUT}/tree-{w}-{rel.split('/')[-1][:2]}.png")
        print(w, th, "14 篇都画了", flush=True)
        # 收起、展开
        p.evaluate("openDoc('AI文档/架构/04-QQ通道与提醒.md')")
        p.wait_for_timeout(900)
        n0 = p.evaluate("document.querySelectorAll('.tn:not(.gone)').length")
        p.click(".tn.d1.has >> nth=0")
        p.wait_for_timeout(600)
        n1 = p.evaluate("document.querySelectorAll('.tn:not(.gone)').length")
        p.click("[data-tree-top]")
        p.wait_for_timeout(600)
        n2 = p.evaluate("document.querySelectorAll('.tn:not(.gone)').length")
        p.click("[data-tree-all]")
        p.wait_for_timeout(600)
        n3 = p.evaluate("document.querySelectorAll('.tn:not(.gone)').length")
        print("  收起展开：", n0, n1, n2, n3, flush=True)
        if not (n1 < n0 and n2 < n1 and n3 == n0):
            bad.append(f"{w}: 收起展开不对 {n0} {n1} {n2} {n3}")
        dots = p.evaluate("[].map.call(document.querySelectorAll('.tn-dot'), function (d) { return d.className; })")
        if not dots or all(d == "tn-dot" for d in dots):
            bad.append(f"{w}: 状态灯没有颜色 {dots}")
        # → 跳转
        p.evaluate("openDoc('AI文档/架构/00-总览.md')")
        p.wait_for_timeout(900)
        p.click(".tn-go >> nth=0")
        p.wait_for_timeout(900)
        cur = p.evaluate("DOCS.cur")
        print("  → 跳到：", cur, flush=True)
        if cur == "AI文档/架构/00-总览.md":
            bad.append(f"{w}: → 没跳转")
        # 文字版
        p.click('[data-doc-mode="text"]')
        p.wait_for_timeout(700)
        t = p.evaluate("({h2: document.querySelectorAll('#docBody h2').length, tree: document.querySelectorAll('.tree-wrap').length})")
        p.click('[data-doc-mode="tree"]')
        p.wait_for_timeout(500)
        print("  文字版：", t, flush=True)
        if t["h2"] < 3 or t["tree"] != 1:
            bad.append(f"{w}: 文字版不对 {t}")
        # AI文档 README 里有四个反引号包着的示例，不能被画成树
        p.evaluate("openDoc('AI文档/README.md')")
        p.wait_for_timeout(700)
        r = p.evaluate("({tree: document.querySelectorAll('.tree-wrap').length, pre: document.querySelectorAll('pre.md-code').length})")
        if r["tree"] != 0 or r["pre"] < 1:
            bad.append(f"{w}: AI文档 README 渲染不对 {r}")
        p.close()
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if errs or bad else 0)
