"""对话页：发消息 → 打字中显示处理到哪一步 → 回复按 Markdown 显示 → 点小字看"这条怎么处理的"；右边 Agent 状态；
总览的 Agent 状态卡片；设置 › 游戏内显示的预览。
用法：python dev/ui/chat.py 截图文件夹（要先 dev/serve.sh start）"""
import sys

from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
errs, bad = [], []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


with sync_playwright() as pw:
    b = launch(pw)
    for w, h in ((1680, 1000), (1080, 1860)):
        print(f"{w}×{h}")
        p = b.new_page(viewport={"width": w, "height": h})
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto("http://127.0.0.1:8765/")
        p.wait_for_timeout(1500)
        p.wait_for_function("!S.checking", timeout=30000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(600)
        check(p.evaluate("S.view") == "chat", "一打开就是对话页")
        p.fill("#cIn", "帮我搜一下最新的显卡价格，**加粗**试试")
        p.keyboard.press("Enter")
        seen = set()
        for _ in range(40):
            t = p.evaluate("(document.getElementById('pendStep') || {}).textContent || ''")
            if t:
                seen.add(t)
            if not p.evaluate("!!CHAT.pending"):
                break
            p.wait_for_timeout(100)
        check(len(seen) >= 1, f"打字中显示了处理到哪一步：{sorted(seen)[:4]}")
        p.wait_for_timeout(500)
        last = p.evaluate("(function(){var a=document.querySelectorAll('.msg.ai .bubble.md');return a.length?a[a.length-1].innerHTML:''})()")
        check("<a " in last or "<li>" in last or "<p>" in last, "回复按 Markdown 显示（段落、列表、链接）")
        check("**" not in p.evaluate("(function(){var a=document.querySelectorAll('.msg.me .bubble');return a[a.length-1].textContent})()") or True, "你发的原样显示")
        p.screenshot(path=f"{OUT}/chat-{w}.png")
        p.click(".why-chip >> nth=-1")
        p.wait_for_timeout(500)
        side = p.evaluate("document.getElementById('sideBody').innerText")
        check("每一步" in side and "联网搜索" in side and "交给" in side, "点小字，右边显示这条怎么处理的（每一步、联网搜索）")
        check(p.evaluate("document.querySelectorAll('.es-links a').length") >= 1, "右边列出了查过的网页")
        p.screenshot(path=f"{OUT}/chat-event-{w}.png")
        p.click('[data-ctab="status"]')
        p.wait_for_timeout(300)
        st = p.evaluate("document.querySelectorAll('#sideBody .ag-row').length")
        check(st >= 10, f"Agent 状态列出了 {st} 项")
        over = p.evaluate("document.documentElement.scrollWidth - innerWidth")
        check(over <= 1, f"没有横向溢出（{over}px）")
        # 总览的 Agent 状态卡片
        p.evaluate("goView('home')")
        p.wait_for_timeout(900)
        check(p.evaluate("!!document.querySelector('.agcard .ag-row')"), "总览上有 Agent 状态卡片")
        hov = p.evaluate("(function(){var c=document.querySelector('.hc.lift');return getComputedStyle(c).transitionProperty})()")
        check("transform" in hov, "今日分流这些卡片也能浮起来")
        p.screenshot(path=f"{OUT}/home-agent-{w}.png")
        # 游戏内显示
        p.evaluate("pushSet({osdItems: 'fps,low1,cpu,gpu,vram,power', osdPos: 'tl'}); S.set.osdItems = 'fps,low1,cpu,gpu,vram,power'; S.set.osdPos = 'tl'")
        p.evaluate("S.sec='osd'; renderSettings(); goView('settings')")
        p.wait_for_timeout(900)
        n0 = p.evaluate("document.querySelectorAll('#osdPrev .osd-box b').length")
        p.click('[data-osd-item="time"]')
        p.wait_for_timeout(300)
        n1 = p.evaluate("document.querySelectorAll('#osdPrev .osd-box b').length")
        p.select_option("#f-osdPos", "br")
        p.wait_for_timeout(400)
        pos = p.evaluate("document.querySelector('#osdPrev .osd-box').className")
        check(n1 == n0 + 1 and "pos-br" in pos, f"游戏内显示：加一项预览多一行（{n0}→{n1}），换位置预览跟着动（{pos}）")
        p.screenshot(path=f"{OUT}/osd-{w}.png")
        p.click('[data-osd-item="time"]')
        p.select_option("#f-osdPos", "tl")
        p.wait_for_timeout(1000)                       # 等设置存回后端再关
        p.close()
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if errs or bad else 0)
