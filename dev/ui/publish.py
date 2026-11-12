"""「发布」窗口点一遍（v3.2，连测试后端，抖音是假的 dev/fake_sau.py），再看一眼下边栏和设置里挪过去的那几样：
扫码登录（二维码出现在右边）→ 点工作区里的视频（预览）→ 写标题、话题（# 小标签）、定时、放封面 → 「发布到抖音」点两下才发 → 最近发的里有；
Agent 交来的一条：顶上出现 →「填进来看看」表单填好 → 发；下边栏只剩主页、常驻、生图、配音、配乐、发布、事件、后台、设置；
设置里有「其他页面」（大脑、报告、说明）和 外观 › 全屏、深色 / 浅色。
用法：python dev/ui/publish.py 截图文件夹（要先 dev/serve.sh start）"""
import json
import pathlib
import shutil
import struct
import sys
import time
import zlib

import httpx
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RUN = ROOT / "data" / "publish" / "run"
errs, bad = [], []
cov_rel = ""


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def png(w, h):
    raw = b"".join(b"\x00" + b"\x40\x90\xc0" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


c = httpx.Client(base_url="http://127.0.0.1:8765", headers={"X-Agent": "1"}, timeout=30)
c.put("/api/agent/caps", json={"publish": False, "publish_ask": True})
c.post("/api/publish/logout")
WS = ROOT / "工作区" / "发布界面测试"
shutil.rmtree(WS, ignore_errors=True)
WS.mkdir(parents=True)
(WS / "第5期成片.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2000)
cover = ROOT / "dev" / ".run" / "封面竖.png"
cover.write_bytes(png(30, 40))


def boot(p, url):
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(url)
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")


with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1440, "height": 880})
    boot(p, "http://127.0.0.1:8765/?tool=publish")
    p.evaluate("localStorage.removeItem('agentPub.v1'); PUB.f = null; $('#view-publish').innerHTML = ''; renderPub(); pubFetch()")
    p.wait_for_selector('[data-pb="login"]')
    check("没登录" in p.inner_text("#pbAcctSt") and p.is_disabled("#pbGo"), "没登录：右边写着没登录，「发布到抖音」点不了")
    p.click('[data-pb="login"]')
    p.wait_for_selector(".pb-qr img", timeout=15000)
    check(p.get_attribute(".pb-qr img", "src").startswith("data:image/png"), "点「扫码登录」：二维码出现在右边")
    (RUN / "fake_scan").write_text("1")
    p.wait_for_function("document.querySelector('#pbAcctSt').textContent.indexOf('登录了') >= 0", timeout=15000)
    check(True, "扫完：右边变成「登录了」")
    p.wait_for_selector('.pb-v', timeout=8000)
    p.click('.pb-v >> text=第5期成片.mp4')
    p.wait_for_selector("#pbVideo")
    check("第5期成片.mp4" in p.inner_text(".pb-sel"), "点工作区里的视频：左边出预览")
    p.fill("#pbTitle", "本周最火的 5 个 AI 项目")
    p.fill("#pbTags", "#AI 开源 GitHub")
    check(p.inner_text("#pbTn").strip() == f"{len('本周最火的 5 个 AI 项目')} / 30" and p.locator("#pbTagv span").count() == 3, "标题字数跟着变；话题变成 3 个小标签")
    p.click('[data-pbwhen="1"]')
    check(p.is_visible("#pbWhen") and p.input_value("#pbWhen") >= p.evaluate("pubMinWhen()")[:13], "点「定时」：出来时间框，默认 2 小时以后")
    p.click('[data-pbwhen="0"]')
    p.set_input_files("#pbCoverFile", str(cover))
    p.wait_for_selector(".pb-cv", timeout=8000)
    cov_rel = p.evaluate("PUB.f.cover && PUB.f.cover.path") or ""
    check("封面竖" in p.inner_text(".pb-cv") and cov_rel.endswith(".png"), "放一张封面（放进工作区）")
    p.click("#pbGo")
    p.wait_for_function("document.querySelector('#pbGo').textContent.indexOf('再点一下') >= 0", timeout=5000)
    check(True, "点一下「发布到抖音」：先变成「再点一下就发」（防手滑）")
    p.screenshot(path=f"{OUT}/publish-armed.png")
    p.click("#pbGo")
    p.wait_for_function("PUB.st && PUB.st.hist && PUB.st.hist.length && PUB.st.hist[0].title === '本周最火的 5 个 AI 项目' && PUB.st.job.st !== 'run'", timeout=20000)
    p.wait_for_timeout(600)
    sent = json.loads((RUN / "fake_last_upload.json").read_text("utf-8"))
    check(sent["title"] == "本周最火的 5 个 AI 项目" and sent["tags"] == ["AI", "开源", "GitHub"] and pathlib.Path(sent["cover"]).name.startswith("封面竖") and sent["cover_kind"] == "portrait" and not sent["schedule"],
          "再点一下：发了（标题、话题、竖封面、马上发）")
    check("本周最火的 5 个 AI 项目" in p.inner_text("#pbHist") and p.input_value("#pbTitle") == "", "「最近发的」里有；表单清空了，下一条重新写")
    # Agent 交来的
    c.put("/api/agent/caps", json={"publish": True})
    tok = c.post("/api/chat", json={"text": "发抖音【工作区】" + json.dumps([{"name": "publish_douyin", "arguments": {"path": "发布界面测试/第5期成片.mp4", "title": "Agent 写的标题", "tags": ["开源"]}}], ensure_ascii=False),
                                    "async": True}).json()["token"]
    for _ in range(120):
        if c.get("/api/chat/" + tok).json()["done"]:
            break
        time.sleep(0.25)
    p.wait_for_selector(".pb-pend", timeout=10000)
    check("Agent 想发：Agent 写的标题" in p.inner_text(".pb-pend"), "Agent 交来的一条出现在中间顶上")
    p.click('.pb-pend [data-act="fill"]')
    p.wait_for_function("document.querySelector('#pbTitle') && document.querySelector('#pbTitle').value === 'Agent 写的标题'", timeout=5000)
    check("确认，发 Agent 这一条" in p.inner_text("#pbGo") and "第5期成片.mp4" in p.inner_text(".pb-sel"), "「填进来看看」：表单、视频都填好，按钮写着发 Agent 这一条")
    p.screenshot(path=f"{OUT}/publish-pending.png")
    p.click("#pbGo")
    p.wait_for_function("document.querySelector('#pbGo').textContent.indexOf('再点一下') >= 0", timeout=5000)
    p.click("#pbGo")
    p.wait_for_function("PUB.st && PUB.st.hist.length && PUB.st.hist[0].title === 'Agent 写的标题' && PUB.st.job.st !== 'run' && !PUB.st.pending.length", timeout=20000)
    p.wait_for_timeout(500)
    check("Agent" in p.inner_text("#pbHist .pb-hr >> nth=0"), "发了：记录里标着 Agent")
    p.close()

    # 下边栏、设置
    p = b.new_page(viewport={"width": 1680, "height": 1000})
    boot(p, "http://127.0.0.1:8765/")
    vis = p.evaluate("[].map.call(document.querySelectorAll('.rail .nav'), function (b) { return getComputedStyle(b).display !== 'none' ? b.textContent.trim().replace(/\\d+$/, '') : ''; }).filter(Boolean)")
    check(vis == ["主页", "常驻", "生图", "配音", "配乐", "发布", "事件", "后台", "设置"], f"下边栏只剩：{'、'.join(vis)}")
    th0 = p.evaluate("S.set.theme")
    p.keyboard.press("t")
    p.wait_for_timeout(900)
    th = p.evaluate("S.set.theme")
    p.keyboard.press("t")
    p.wait_for_timeout(900)
    check(th != th0 and p.evaluate("S.set.theme") == th0, "快捷键 T 还能切深浅色")
    p.close()
    p = b.new_page(viewport={"width": 1440, "height": 880})
    boot(p, "http://127.0.0.1:8765/?tool=settings")
    names = p.evaluate("[].map.call(document.querySelectorAll('.snav [data-open-tool]'), function (b) { return b.dataset.openTool; })")
    check(names[:3] == ["brains", "reports", "docs"], "设置左边最上面是「其他页面」：大脑、报告、说明（点了开它的窗口）")
    p.click('.sitem[data-sec="look"]')
    p.wait_for_selector('[data-main-full]')
    check(p.is_visible('[data-tone="light"]') and p.is_visible('[data-main-full]'), "设置 › 外观：主窗口全屏、深色 / 浅色")
    p.evaluate("localStorage.removeItem('agentCmd')")
    th0 = p.evaluate("S.set.theme")
    other = "dark" if th0 == "light" else "light"
    p.click(f'[data-tone="{other}"]')
    p.wait_for_timeout(900)
    sent = p.evaluate("JSON.parse(localStorage.getItem('agentCmd') || '{}')")
    check(p.evaluate("S.set.theme") == other and sent.get("theme") == other, f"点{'浅色' if other == 'light' else '深色'}：设置窗口变了，也告诉了主窗口（浏览器里走 storage）")
    p.click(f'[data-tone="{th0}"]')
    p.wait_for_timeout(900)                       # 设置 0.4 秒后才存到后端：等它存上再关
    p.close()
    b.close()

c.put("/api/agent/caps", json={"publish": False, "publish_ask": True})
c.post("/api/publish/logout")
shutil.rmtree(WS, ignore_errors=True)
cover.unlink(missing_ok=True)
if cov_rel:                                       # 测试放进工作区的封面删掉
    (ROOT / "工作区" / cov_rel.replace("\\", "/")).unlink(missing_ok=True)
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
