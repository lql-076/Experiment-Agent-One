"""高清灯箱点一遍（v3.9.0 / R10）：开关、缩放、双击复位、棋盘格切换、GIF、多张切换、信息栏数字。
用法：python dev/ui/lightbox.py 截图文件夹（要先 dev/serve.sh start）"""
import base64
import os
import struct
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

errs, bad = [], []
PORT = os.environ.get("AGENT_TEST_PORT", "8765")
BASE = "http://127.0.0.1:" + PORT
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lzq4WQAAAABJRU5ErkJggg==")


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def tiny_gif(path, frames=4, delay_cs=9):
    head = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
    gce = b"\x21\xf9\x04\x01" + struct.pack("<H", delay_cs) + b"\x00\x00"
    img = b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00"
    path.write_bytes(head + (gce + img) * frames + b"\x3b")


def make_files(project_dir):
    d = Path(project_dir)
    (d / "images").mkdir(parents=True, exist_ok=True)
    (d / "images" / "lb.png").write_bytes(PNG)
    tiny_gif(d / "images" / "lb.gif", 4, 9)
    (d / "images" / "lb.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="48"><rect width="64" height="48" fill="#4af"/></svg>', "utf-8")
    return d


with httpx.Client(base_url=BASE, timeout=20, headers={"X-Agent": "1"}) as c:
    st = c.post("/api/studio/new", json={"topic": "灯箱界面测试", "voice_id": "local:preset:Vivian"}).json()
    pid = st["project"]["id"]
    make_files(st["project"]["dir"])

    with sync_playwright() as pw:
        b = launch(pw)
        p = b.new_page(viewport={"width": 1440, "height": 880})
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE + "/?tool=studio")
        p.wait_for_timeout(1500)
        p.wait_for_function("!S.checking", timeout=30000)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(1200)
        items = [
            {"pid": pid, "rel": "images/lb.png", "name": "lb.png", "cacheHit": True},
            {"pid": pid, "rel": "images/lb.gif", "name": "lb.gif", "cacheHit": False},
            {"pid": pid, "rel": "images/lb.svg", "name": "lb.svg", "cacheHit": False},
        ]
        p.evaluate("(it) => Lightbox.open(it, 0)", items)
        p.wait_for_timeout(700)
        check(p.is_visible("#lbRoot"), "灯箱打开了")
        info = p.inner_text("#lbInfo")
        check("1 × 1 px" in info and "缓存命中" in info, "信息栏：真实分辨率 + 缓存命中")
        check(p.get_attribute("#lbRoot", "data-bg") == "checker", "默认棋盘格底衬")
        s0 = p.evaluate("Lightbox._state.scale")
        box = p.locator("#lbStage").bounding_box()
        p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        p.mouse.wheel(0, -240)
        p.wait_for_timeout(200)
        check(p.evaluate("Lightbox._state.scale") > s0 * 1.05, "滚轮放大")
        p.dblclick("#lbStage")
        p.wait_for_timeout(250)
        check(abs(p.evaluate("Lightbox._state.scale") - p.evaluate("Lightbox._state.fit")) < 1e-6, "双击复位到适应窗口")
        p.click('[data-lb-bg="dark"]')
        check(p.get_attribute("#lbRoot", "data-bg") == "dark", "切深色底")
        p.click('[data-lb-bg="light"]')
        check(p.get_attribute("#lbRoot", "data-bg") == "light", "切浅色底")
        p.click('[data-lb-bg="checker"]')
        check(p.get_attribute("#lbRoot", "data-bg") == "checker", "切回棋盘格")
        p.click('[data-lb="next"]')
        p.wait_for_function("document.getElementById('lbInfo').textContent.includes('4 帧')", timeout=4000)
        info = p.inner_text("#lbInfo")
        check("GIF" in info and "4 帧" in info and "0.4 秒" in info, "GIF：帧数和时长对得上（4 帧 × 90ms）")
        check(p.evaluate("document.querySelector('#lbImg').src.includes('lb.gif')"), "GIF 用 <img> 原速循环（不是静态截图）")
        check(p.evaluate("document.querySelector('#lbImg').complete && document.querySelector('#lbImg').naturalWidth > 0"), "GIF 真的解码出来了")
        p.click('[data-lb="next"]')
        p.wait_for_selector("#lbSvgNote:not([hidden])", timeout=4000)
        check(p.is_visible("#lbSvgNote"), "SVG：提示脚本不会执行")
        check("64 × 48 px" in p.inner_text("#lbInfo"), "SVG 信息栏尺寸 64 × 48")
        p.click('[data-lb="prev"]')
        p.wait_for_timeout(400)
        check(p.inner_text("#lbCount").strip() == "2 / 3", "多张产出左右切换")
        p.keyboard.press("Escape")
        p.wait_for_timeout(300)
        check(p.evaluate("!Lightbox.isOpen() && document.getElementById('lbRoot').hidden"), "Esc 关闭")
        b.close()

print("JS 报错：", errs or "没有")
print("没通过：", bad or "没有")
sys.exit(1 if bad or errs else 0)
