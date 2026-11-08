"""一页内容一屏放下（作者的规矩：闲下来"一眼看"的页，信息不靠鼠标滚轮翻）。
v2.0 起主窗口只有主页（横屏 1680×1000、竖屏 1080×1860，竖屏再把字调到 130%）；工具都是独立窗口（?tool=），
按工具窗口的默认大小 1440×880 和竖屏 1080×1860 看每个工具、每个设置分区：除了本来就是长列表的地方
（聊天记录、事件列表、后台日志、说明文档、报告里的两张清单、事件的回复正文、配音的文案框和时间轴、生图页里自己滚的几块：清单、出好的图、历史、模板、提示词框；配音页本地、云端两种引擎都看），别的地方都不该出现滚动。
要动手操作的页可以滚（作者说的：用它时手本来就在鼠标上），列在 SCROLL_OK 里，不查。
用法：python dev/ui/fit.py 截图文件夹（要先 dev/serve.sh start）"""
import sys

from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
SCROLL_OK = {"prep", "remind", "models", "cloud"}   # 整备、提醒列表、本地模型（v1.8.7 加了「安装配音」）、云端（v1.8.11 加了百炼 Key）：要动手操作的页，可以上下滚（v1.8.1 起）
LISTS = "#chatLog, .hm-pop, #evlist, #feedBox, .feed, .logbox, #docBody, #docNav, .rlists, .rec, .ag-list, .detail>.cards2, #ttsText, .tts-tl, .tts-vb, .fg-scroll"   # .tts-vb：配音页的音色面板（音色列表、设计、复刻表单，v1.8.12）；.fg-scroll：生图页里自己滚的几块（v1.8.16）
JS = """(lists) => { const out = []; document.querySelectorAll('#content *, #content').forEach(el => {
  if (!el.offsetParent && el.id !== 'content') return;
  if (el.closest(lists)) return;
  const cs = getComputedStyle(el);
  if (/(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 4 && el.clientHeight > 120)
    out.push((el.id ? '#' + el.id : el.className.toString().split(' ')[0]) + ' ' + el.clientHeight + '/' + el.scrollHeight); });
  return out; }"""
TOOLS = [("view", v) for v in ("events", "monitor", "brains", "reports", "tts", "tts-cloud", "img", "img-batch")]
bad, errs = [], []


def look(p, w, h, name, shot):
    over = p.evaluate(JS, LISTS)
    print(("  ✓ " if not over else "  ✗ ") + f"{w}×{h} {name}" + (f"：要滚 {over}" if over else ""), flush=True)
    if over:
        bad.append(f"{w}×{h} {name}")
        p.screenshot(path=f"{OUT}/fit-{w}-{shot}.png")


def edges(p, w, h, name):
    """底栏、标题栏的每个按钮整个在屏幕里（v2.1：竖屏时最右边的「关闭」被切掉一半）。桌面窗口才有的「收起」「关闭」也放出来量。"""
    cut = p.evaluate("""() => { ['btnMin', 'btnClose'].forEach(function (id) { var b = document.getElementById(id); if (b) b.hidden = false; });
      var out = []; document.querySelectorAll('.rail .nav, .tw-btns button, .topbar button').forEach(function (b) {
        var r = b.getBoundingClientRect(); if (!r.width || getComputedStyle(b).display === 'none') return;
        if (r.left < -1 || r.right > innerWidth + 1 || r.top < -1 || r.bottom > innerHeight + 1) out.push((b.textContent || b.id).trim().slice(0, 4) + ' ' + Math.round(r.left) + '~' + Math.round(r.right)); });
      ['btnMin', 'btnClose'].forEach(function (id) { var b = document.getElementById(id); if (b) b.hidden = true; });
      return out; }""")
    print(("  ✓ " if not cut else "  ✗ ") + f"{w}×{h} {name}：按钮都整个在屏幕里" + (f"，被切掉的 {cut}" if cut else ""), flush=True)
    if cut:
        bad.append(f"{w}×{h} {name} 按钮被切")


def start(p, url):
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(url)
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")


with sync_playwright() as pw:
    b = launch(pw)
    # 主窗口：主页
    for w, h in ((1680, 1000), (1080, 1860)):
        p = b.new_page(viewport={"width": w, "height": h})
        start(p, "http://127.0.0.1:8765/")
        p.wait_for_timeout(600)
        look(p, w, h, "主页", "home")
        edges(p, w, h, "主页")
        if h > w:                                      # 竖屏把字调大（设置 › 外观 › 文字大小 130%）也不该要滚（v1.8.2）
            p.evaluate("S.set.scale=130; applyScale(); homeFill()")
            p.wait_for_timeout(1200)
            look(p, w, h, "字 130% 主页", "130-home")
            p.evaluate("S.set.scale=100; applyScale()")
        # 主页不能来回闪：模仿 Windows 占宽度的滚动条，连看 2 秒，每一块的大小不能变
        p.add_style_tag(content="::-webkit-scrollbar{width:17px;height:17px}")
        p.wait_for_timeout(600)
        seen = p.evaluate("""() => new Promise(r => { var out = []; var t = setInterval(function () {
            out.push([].map.call(document.querySelectorAll('.hm-card'), function (c) { var b = c.getBoundingClientRect(); return Math.round(b.width) + 'x' + Math.round(b.height); }).join(','));
            if (out.length >= 20) { clearInterval(t); r(out); } }, 100); })""")
        ok = len(set(seen)) == 1
        print(("  ✓ " if ok else "  ✗ ") + f"{w}×{h} 主页不来回闪" + ("" if ok else f"：{sorted(set(seen))}"), flush=True)
        if not ok:
            bad.append(f"{w}×{h} 主页来回闪")
        p.close()
    # 工具窗口：每个工具、每个设置分区
    for w, h in ((1440, 880), (1080, 1860)):
        for kind, k in TOOLS:
            tool = k.split("-")[0]
            p = b.new_page(viewport={"width": w, "height": h})
            start(p, "http://127.0.0.1:8765/?tool=" + tool)
            if k.startswith("tts"):                     # 配音页的两种引擎都看（v1.8.11 加了百炼云端；只在这页切，不存进设置）
                p.evaluate("TTS.eng='" + ("cloud" if k == "tts-cloud" else "local") + "'; if (TTS.st) TTS.st.engine=TTS.eng; if (TTS.st) renderTTS()")
            if k.startswith("img"):                     # 生图的单张页、批量页都看（v2.1 撤掉了角色、模板）
                p.wait_for_timeout(800)
                p.evaluate("imgTab('" + ("batch" if k == "img-batch" else "single") + "', true)")
            p.wait_for_timeout(900)
            look(p, w, h, "工具窗口 " + k, k)
            if k in ("img", "settings", "events"):
                edges(p, w, h, "工具窗口 " + k)
            p.close()
        p = b.new_page(viewport={"width": w, "height": h})
        start(p, "http://127.0.0.1:8765/?tool=settings")
        for s in p.evaluate("SECTIONS.map(function (s) { return s.id; })"):
            if s in SCROLL_OK:
                continue
            p.evaluate(f"S.sec='{s}'; renderSettings()")
            p.wait_for_timeout(700)
            look(p, w, h, "设置 › " + s, "set-" + s)
        p.close()
    b.close()
print("JS 报错：", errs or "没有")
print("要滚才看全的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
