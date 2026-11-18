"""自由节点画布点一遍（v3.9.0 / R10）：添加删除、拖动、缩放、连线断线、适应窗口。
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


def drag(p, a, b, steps=10):
    ab, bb = a.bounding_box(), b.bounding_box()
    p.mouse.move(ab["x"] + ab["width"] / 2, ab["y"] + ab["height"] / 2)
    p.mouse.down()
    p.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2, steps=steps)
    p.mouse.up()
    p.wait_for_timeout(400)


def drag_by(p, a, dx, dy):
    ab = a.bounding_box()
    p.mouse.move(ab["x"] + ab["width"] / 2, ab["y"] + ab["height"] / 2)
    p.mouse.down()
    p.mouse.move(ab["x"] + ab["width"] / 2 + dx, ab["y"] + ab["height"] / 2 + dy, steps=8)
    p.mouse.up()
    p.wait_for_timeout(500)


with httpx.Client(base_url=BASE, timeout=20, headers={"X-Agent": "1"}) as c:
    st = c.post("/api/studio/new", json={"topic": "画布界面测试", "voice_id": "local:preset:Vivian"}).json()
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
            p.wait_for_function("document.querySelectorAll('[data-node]').length === 9", timeout=12000)
        except Exception:
            pass
        check(p.locator("[data-node]").count() == 9, "一进来 9 个节点")
        check(p.locator('path.st-edge').count() == 0, "默认没有连线")
        check(p.locator('[data-ndel="script"]').is_disabled() and p.locator('[data-ndel="mux"]').is_disabled()
              and p.locator('[data-ndel="publish"]').is_disabled(), "固定节点删除按钮置灰")
        # 添加节点
        p.click('[data-st="add"]')
        p.click('[data-add="image"]')
        try:
            p.wait_for_function("stGraph().nodes.length >= 10", timeout=10000)
        except Exception:
            pass
        p.wait_for_timeout(300)
        check(p.locator("[data-node]").count() == 10, "菜单能加一个生图节点")
        g = p.evaluate("stGraph()")
        new = [n for n in g["nodes"] if n["id"].startswith("image-2")][0]
        check(new["type"] == "image", "新节点是生图")
        # 拖动位置
        hd = p.locator('[data-drag="' + new["id"] + '"]')
        before = p.evaluate("stNodeMap()['" + new["id"] + "'].x")
        drag_by(p, hd, 70, 50)
        after = p.evaluate("stNodeMap()['" + new["id"] + "'].x")
        check(after > before + 40, "拖动节点标题能移动")
        p.wait_for_timeout(800)
        p.reload()
        p.wait_for_timeout(1800)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(800)
        moved = p.evaluate("(id => { var n = stNodeMap()[id]; return n && n.x; })('" + new["id"] + "')")
        check(moved and moved > before + 40, "刷新后位置还在（写进 project.json）")
        # 缩放节点
        rs = p.locator('[data-rs="' + new["id"] + '"]')
        w0 = p.evaluate("stNodeMap()['" + new["id"] + "'].w")
        drag_by(p, rs, 60, 40)
        w1 = p.evaluate("stNodeMap()['" + new["id"] + "'].w")
        check(w1 > w0 + 30, "拖右下角能放大节点")
        # 连线
        out = p.locator('[data-port="image-1.image"]')
        inp = p.locator('[data-inport="mux.image"]')
        drag(p, out, inp)
        try:
            p.wait_for_function("stGraph().edges.length >= 1", timeout=10000)
        except Exception:
            pass
        p.wait_for_timeout(300)
        e = p.evaluate("stGraph().edges.length")
        check(e == 1, "从输出口拖到输入口能连上")
        edge = p.evaluate("stGraph().edges[0]")
        check(edge["from"] == "image-1.image" and edge["to"] == "mux.image", "连线两端对")
        # 点线断开
        p.locator('[data-edge]').first.dispatch_event('pointerdown', {'button': 0})
        try:
            p.wait_for_function("stGraph().edges.length === 0", timeout=10000)
        except Exception:
            pass
        check(p.evaluate("stGraph().edges.length") == 0, "点连线能断开")
        # 适应窗口
        p.evaluate("STUDIO.canvas.s = .4; applyCanvas()")
        p.click('[data-st="fit"]')
        p.wait_for_timeout(300)
        check(p.evaluate("STUDIO.canvas.s") > .4, "适应窗口把画布放回合适大小")
        check(p.evaluate("document.scrollingElement.scrollHeight <= innerHeight + 2"), "页面本身不滚")
        p.screenshot(path=OUT + "/canvas.png")
        b.close()

print("JS 报错：", errs or "没有")
print("没通过：", bad or "没有")
sys.exit(1 if bad or errs else 0)
