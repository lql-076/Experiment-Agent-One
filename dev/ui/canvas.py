"""七模块零连线画布点一遍（v4.0.0 / R11）：0 连线 0 端口、7 个独立模块、拖动缩放、模块 6 三窗、适应窗口。
用法：python dev/ui/canvas.py 截图文件夹（要先 dev/serve.sh start）"""
import os
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = Path(__file__).resolve().parent.parent.parent
PORT = os.environ.get("AGENT_TEST_PORT", "8765")
BASE = "http://127.0.0.1:" + PORT
errs, bad = [], []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def drag_by(p, loc, dx, dy):
    b = loc.bounding_box()
    p.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    p.mouse.down()
    p.mouse.move(b["x"] + b["width"] / 2 + dx, b["y"] + b["height"] / 2 + dy, steps=8)
    p.mouse.up()
    p.wait_for_timeout(600)


with httpx.Client(base_url=BASE, timeout=20, headers={"X-Agent": "1"}) as c:
    st = c.post("/api/studio/new", json={"topic": "零连线界面测试", "voice_id": "local:preset:Vivian"}).json()
    pid = st["project"]["id"]
    with sync_playwright() as pw:
        b = launch(pw)
        p = b.new_page(viewport={"width": 1440, "height": 880})
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.on("dialog", lambda d: d.accept())
        p.goto(BASE + "/?tool=studio")
        p.wait_for_timeout(1600)
        p.wait_for_function("!S.checking", timeout=30000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(1600)
        try:
            p.wait_for_function("document.querySelectorAll('[data-node]').length === 7", timeout=12000)
        except Exception:
            pass
        check(p.locator("[data-node]").count() == 7, "一进来 7 个模块")
        check(p.locator("path.st-edge").count() == 0, "0 条 SVG 连线")
        check(p.locator(".st-port").count() == 0, "0 个端口 DOM")
        check(p.locator("[data-run]").count() >= 7, "每个模块都有单独的 ▶ 只跑")
        txt = p.inner_text("#stWorld")
        check("剧本与策划" in txt and "生图测试台" in txt and "角色配音 · 白页" in txt and "角色配音 · 紫苏" in txt
              and "背景配乐" in txt and "视频制作总成" in txt and "成片预览" in txt, "7 个模块名称都在")
        check("监控 A" in txt and "监控 B" in txt and "监控 C" in txt, "模块 6 内部有三个监控窗口")
        # 拖动模块
        mid = "image"
        before = p.evaluate("stModMap()['" + mid + "'].x")
        drag_by(p, p.locator('[data-drag="' + mid + '"]'), -60, 40)
        after = p.evaluate("stModMap()['" + mid + "'].x")
        check(after < before - 30, "拖动模块标题能移动")
        p.wait_for_timeout(800)
        p.reload()
        p.wait_for_timeout(1800)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(1200)
        moved = p.evaluate("(id => { var n = stModMap()[id]; return n && n.x; })('" + mid + "')")
        check(moved and moved < before - 30, "刷新后位置还在")
        # 缩放模块
        w0 = p.evaluate("stModMap()['" + mid + "'].w")
        drag_by(p, p.locator('[data-rs="' + mid + '"]'), 60, 35)
        w1 = p.evaluate("stModMap()['" + mid + "'].w")
        check(w1 > w0 + 30, "拖右下角能放大模块")
        # 适应窗口 / 页面不滚
        p.evaluate("STUDIO.canvas.s = .3; applyCanvas()")
        p.click('[data-st="fit"]')
        p.wait_for_timeout(300)
        check(p.evaluate("STUDIO.canvas.s") > .3, "适应窗口把画布放回合适大小")
        check(p.evaluate("document.scrollingElement.scrollHeight <= innerHeight + 2"), "页面本身不滚")
        p.screenshot(path=OUT + "/canvas-v4.png")
        b.close()

print("JS 报错：", errs or "没有")
print("没通过：", bad or "没有")
sys.exit(1 if bad or errs else 0)
