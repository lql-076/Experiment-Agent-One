"""一页内容一屏放下（作者的规矩：闲下来"一眼看"的页，信息不靠鼠标滚轮翻）。
每个页面、每个设置分区，横屏 1680×1000 和竖屏 1080×1860 都看一遍：除了本来就是长列表的地方
（聊天记录、事件列表、后台日志、说明文档、报告里的两张清单、事件的回复正文），别的地方都不该出现滚动。
要动手操作的页可以滚（作者说的：用它时手本来就在鼠标上），列在 SCROLL_OK 里，不查。
用法：python dev/ui/fit.py 截图文件夹（要先 dev/serve.sh start）"""
import sys

from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
SCROLL_OK = {"prep", "obsidian", "remind"}   # 整备、Obsidian 笔记、提醒列表：要动手操作的页，可以上下滚（v1.8.1 起）
LISTS = "#chatLog, #evlist, #feedBox, .feed, .logbox, #docBody, #docNav, .rlists, .rec, .ag-list, .detail>.cards2"
JS = """(lists) => { const out = []; document.querySelectorAll('#content *, #content').forEach(el => {
  if (!el.offsetParent && el.id !== 'content') return;
  if (el.closest(lists)) return;
  const cs = getComputedStyle(el);
  if (/(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 4 && el.clientHeight > 120)
    out.push((el.id ? '#' + el.id : el.className.toString().split(' ')[0]) + ' ' + el.clientHeight + '/' + el.scrollHeight); });
  return out; }"""
bad, errs = [], []
with sync_playwright() as pw:
    b = launch(pw)
    for w, h in ((1680, 1000), (1080, 1860)):
        p = b.new_page(viewport={"width": w, "height": h})
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto("http://127.0.0.1:8765/")
        p.wait_for_timeout(1500)
        p.wait_for_function("!S.checking", timeout=30000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        targets = [("view", v) for v in ("chat", "home", "events", "monitor", "brains", "reports")]
        targets += [("sec", s) for s in p.evaluate("SECTIONS.map(function (s) { return s.id; })") if s not in SCROLL_OK]
        for kind, k in targets:
            p.evaluate(f"goView('{k}')" if kind == "view" else f"S.sec='{k}'; renderSettings(); goView('settings')")
            p.wait_for_timeout(900)
            over = p.evaluate(JS, LISTS)
            name = k if kind == "view" else "设置 › " + k
            print(("  ✓ " if not over else "  ✗ ") + f"{w}×{h} {name}" + (f"：要滚 {over}" if over else ""), flush=True)
            if over:
                bad.append(f"{w}×{h} {name}")
                p.screenshot(path=f"{OUT}/fit-{w}-{k}.png")
        if h > w:                                      # 竖屏把字调大（设置 › 外观 › 文字大小 130%）：对话页也不该要滚（v1.8.2）
            for k in ("chat", "home"):
                p.evaluate(f"S.set.scale=130; applyScale(); goView('{k}')")
                p.wait_for_timeout(1200)
                over = p.evaluate(JS, LISTS)
                print(("  ✓ " if not over else "  ✗ ") + f"{w}×{h} 字 130% {k}" + (f"：要滚 {over}" if over else ""), flush=True)
                if over:
                    bad.append(f"{w}×{h} 字 130% {k}")
                    p.screenshot(path=f"{OUT}/fit-{w}-130-{k}.png")
            p.evaluate("S.set.scale=100; applyScale()")
        p.close()
    b.close()
print("JS 报错：", errs or "没有")
print("要滚才看全的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
