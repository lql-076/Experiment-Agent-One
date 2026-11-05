"""主页和对话抽屉（v2.0）：一打开是主页（现在、后台在跑、刚做完、Agent 状态），对话收在最下面一条；
Ctrl 空格展开对话 → 发消息 → 主页「现在」跟着走（正在……、每一步几秒）→ 回复按 Markdown 显示 → 「刚做完」第一行是它 →
点回复下面的小字：抽屉收起、「现在」打开细节（每一步、查过的网页、判错了、换它重做）→ 指定交给谁 → 「全部」看每一项 →
后台在跑的生图出现在「后台在跑」→ 左边的工具按钮开新窗口（?tool=）→ 设置 › 游戏内显示的预览（在设置的工具窗口里）。
用法：python dev/ui/chat.py 截图文件夹（要先 dev/serve.sh start）"""
import pathlib
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
RUN = pathlib.Path(__file__).resolve().parents[1] / ".run"
B = "http://127.0.0.1:8765"
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
        p.goto(B + "/")
        p.wait_for_timeout(1500)
        p.wait_for_function("!S.checking", timeout=30000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(600)
        check(p.evaluate("S.view") == "home" and p.evaluate("document.querySelectorAll('#view-home .hm-card').length") == 4,
              "一打开是主页：现在、后台在跑、刚做完、Agent 状态四块")
        check(p.evaluate("document.getElementById('view-chat').hidden") and p.evaluate("!!document.querySelector('.hm-strip')"), "对话收在最下面一条，平时不占地方")
        p.keyboard.press("Control+Space")
        p.wait_for_timeout(500)
        check(p.evaluate("!document.getElementById('view-chat').hidden && document.activeElement.id === 'cIn'"), "Ctrl 空格展开对话，光标在输入框里")
        p.fill("#cIn", "帮我搜一下最新的显卡价格，**加粗**试试")
        p.keyboard.press("Enter")
        seen = set()
        for _ in range(60):
            t = p.evaluate("(document.getElementById('pendStep') || {}).textContent || ''")
            if t:
                seen.add(t)
            if not p.evaluate("!!CHAT.pending"):
                break
            p.wait_for_timeout(80)
        check(len(seen) >= 1, f"对话里打字中显示了处理到哪一步：{sorted(seen)[:3]}")
        p.wait_for_timeout(700)
        last = p.evaluate("(function(){var a=document.querySelectorAll('.msg.ai .bubble.md');return a.length?a[a.length-1].innerHTML:''})()")
        check("<a " in last or "<li>" in last or "<p>" in last, "回复按 Markdown 显示（段落、列表、链接）")
        p.screenshot(path=f"{OUT}/v2-chat-{w}.png")
        top = p.evaluate("(document.querySelector('#hmDone .hd-row .x') || {}).textContent || ''")
        check("显卡价格" in top, f"「刚做完」第一行就是刚才那句：{top[:20]}")
        steps = p.evaluate("[].map.call(document.querySelectorAll('#hmNow .hm-steps b'), function (x) { return x.textContent; })")
        check(steps[:1] == ["收到"] and "联网搜索" in steps and steps[-1] == "回答", f"「现在」那条进度：{' → '.join(steps)}")
        # 正在处理的样子（测试环境的假服务太快，看不到中间状态：塞一条「正在联网搜索」的进去看「现在」怎么画）
        p.evaluate("""(function(){var e=Object.assign({},homeEvs().slice(-1)[0],{id:999999,status:'running',ts:Date.now()/1000-1.6,latency:null,cost:0,
          text:'测试：正在处理的样子',steps:[['收到','界面输入',0],['语义路由','DeepSeek 70%',0.03],['Kev','DeepSeek 80%',0.2],['联网搜索','显卡价格',0.6]]});
          D.events=[e].concat(D.events||[]);homeFill();})()""")
        p.wait_for_timeout(400)
        ti = p.evaluate("document.querySelector('#hmNow .hm-title').textContent")
        lv = p.evaluate("[document.getElementById('hmNow').classList.contains('live'), document.querySelector('#hmNow .hm-chip').textContent,"
                        " [].map.call(document.querySelectorAll('#hmNow .hm-steps li'), function (x) { return x.className + ':' + x.querySelector('b').textContent; }).join(' ')]")
        check(ti == "正在联网搜索" and lv[0] and lv[1].startswith("处理中") and lv[2] == "st-done:收到 st-done:分流 ×2 st-act:联网搜索 st-wait:回答",
              f"正在处理时：大字「{ti}」、{lv[1]}、进度 {lv[2]}")
        rt = p.evaluate("(renderTasks(RTASK.list), RTASK.list.map(function (t) { return t.k + ':' + t.name; }))")
        check(any(x.startswith("chat:对话 · 测试") for x in rt), f"常驻屏的后台任务里也有正在处理的这句话：{rt[:2]}")
        p.screenshot(path=f"{OUT}/v2-live-{w}.png")
        p.evaluate("D.events=D.events.filter(function(e){return e.id!==999999}); renderTasks([]); homeFill()")
        p.click(".why-chip >> nth=-1")
        p.wait_for_timeout(600)
        pop = p.evaluate("(document.querySelector('#hmNow .hm-pop') || {}).innerText || ''")
        check(p.evaluate("document.getElementById('view-chat').hidden || !document.getElementById('view-chat').classList.contains('open')") and "每一步" in pop and "联网搜索" in pop,
              "点回复下面的小字：对话收起，「现在」打开细节（每一步、联网搜索）")
        check(p.evaluate("document.querySelectorAll('#hmNow .es-links a').length") >= 1 and p.evaluate("document.querySelectorAll('#hmNow [data-cfix]').length") == 4
              and p.evaluate("document.querySelectorAll('#hmNow [data-redo]').length") >= 1, "细节里有查过的网页、判错了、换它重做")
        p.screenshot(path=f"{OUT}/v2-detail-{w}.png")
        p.keyboard.press("Escape")
        p.wait_for_timeout(300)
        check(not p.evaluate("!!document.querySelector('#hmNow .hm-pop')"), "Esc 关掉细节")
        # 指定交给谁
        p.evaluate("chatOpen()")
        p.wait_for_timeout(400)
        p.click("#cForce")
        p.click('#cRoute [data-force="cl"]')
        check(p.evaluate("ROUTES.cl.name") in p.evaluate("document.getElementById('cForce').textContent"), "输入框旁边能指定这一条交给谁")
        p.fill("#cIn", "今天天气怎么样适合出门吗")
        p.keyboard.press("Enter")
        p.wait_for_function("!CHAT.pending", timeout=20000)
        p.wait_for_timeout(400)
        ev = p.evaluate("(function(){var l=homeEvs();return l[l.length-1]})()")
        check(ev["to"] == "cl" and "你指定了去向" in [s[0] for s in ev["steps"]], f"指定的去向生效了（to={ev['to']}）")
        p.click('#cForce'); p.click('#cRoute [data-force="auto"]')
        p.keyboard.press("Escape")
        p.wait_for_timeout(400)
        check(not p.evaluate("CHAT.open"), "Esc 收起对话")
        # Agent 状态
        n_ok = p.evaluate("+(document.querySelector('.hs-sum b') || {}).textContent")
        rows = p.evaluate("document.querySelectorAll('#hmSt .hs-row').length")
        check(n_ok >= 1 and 1 <= rows <= 3, f"Agent 状态：写了几项正常（{n_ok}），出问题的最多列 3 行（{rows}）")
        p.click('[data-ag-all]')
        p.wait_for_timeout(400)
        n_all = p.evaluate("document.querySelectorAll('.hm-all .ha-row').length")
        check(n_all >= 12, f"「全部」列出了每一项（{n_all} 项）")
        p.screenshot(path=f"{OUT}/v2-all-{w}.png")
        p.click('.hm-all .hm-x')
        # 后台在跑：生图在出的时候，这里有一根进度条
        (RUN / "fake_img_slow.flag").write_text("4")
        httpx.put(B + "/api/settings", json={"imgModel": "gpt-image-2.5-sunburst-vip"}, headers={"X-Agent": "1"})
        httpx.post(B + "/api/img/single", json={"prompt": "主页后台在跑的测试", "ratio": "1:1"}, headers={"X-Agent": "1"})
        p.evaluate("poll()")
        p.wait_for_timeout(1500)
        jobs = p.evaluate("(document.getElementById('hmJobs') || {}).innerText || ''")
        check("生图" in jobs and p.evaluate("document.querySelectorAll('#hmJobs .hj-bar').length") >= 1 and p.evaluate("document.querySelector('.nav[data-tool=\"img\"]').classList.contains('on-busy')"),
              "生图在出：「后台在跑」有一根进度条，左边「生图」按钮上有个小点")
        p.screenshot(path=f"{OUT}/v2-jobs-{w}.png")
        for _ in range(40):
            if not (httpx.get(B + "/api/img").json().get("job") or {}).get("st") == "run":
                break
            time.sleep(0.3)
        (RUN / "fake_img_slow.flag").unlink(missing_ok=True)
        p.evaluate("poll()")
        p.wait_for_timeout(900)
        check("生图" in p.evaluate("document.getElementById('hmDone').innerText"), "出完了：「刚做完」里有这次生图")
        over = p.evaluate("document.documentElement.scrollWidth - innerWidth")
        check(over <= 1, f"没有横向溢出（{over}px）")
        # 工具按钮：开新窗口（浏览器里用 window.open；桌面窗口里是 open_tool）
        with p.expect_popup() as pop_info:
            p.click('.nav[data-tool="events"]')
        pp = pop_info.value
        pp.wait_for_timeout(1500)
        check("tool=events" in pp.url and pp.evaluate("S.view") == "events" and pp.evaluate("getComputedStyle(document.querySelector('.rail')).display") == "none",
              "点「事件」：弹出一个只有事件的窗口（没有侧栏）")
        pp.close()
        # 游戏内显示（在设置的工具窗口里）
        p.evaluate("pushSet({osdItems: 'fps,low1,cpu,gpu,vram,power', osdPos: 'tl'})")
        p.close()
        s = b.new_page(viewport={"width": 1440, "height": 880} if w > h else {"width": 1080, "height": 1860})
        s.on("pageerror", lambda e: errs.append(str(e)))
        s.goto(B + '/?tool=settings&arg={"sec":"osd"}')
        s.wait_for_timeout(1500)
        check(s.evaluate("S.sec") == "osd", "设置窗口能直接跳到某个分区（游戏内显示）")
        n0 = s.evaluate("document.querySelectorAll('#osdPrev .osd-box b').length")
        s.click('[data-osd-item="time"]')
        s.wait_for_timeout(300)
        n1 = s.evaluate("document.querySelectorAll('#osdPrev .osd-box b').length")
        s.select_option("#f-osdPos", "br")
        s.wait_for_timeout(400)
        pos = s.evaluate("document.querySelector('#osdPrev .osd-box').className")
        check(n1 == n0 + 1 and "pos-br" in pos, f"游戏内显示：加一项预览多一行（{n0}→{n1}），换位置预览跟着动（{pos}）")
        s.screenshot(path=f"{OUT}/osd-{w}.png")
        s.click('[data-osd-item="time"]')
        s.select_option("#f-osdPos", "tl")
        s.wait_for_timeout(1000)                       # 等设置存回后端再关
        s.close()
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if errs or bad else 0)
