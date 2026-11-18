"""七模块零连线画布点一遍（v4.0.0 / R11）：0 连线 0 端口、7 个独立模块、拖动缩放、模块 6 三窗、适应窗口。
用法：python dev/ui/canvas.py 截图文件夹（要先 dev/serve.sh start）"""
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
import wave
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


def make_wav(path, seconds=1.0, freq=440, sr=24000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(sr * seconds)
    pcm = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / sr))) for i in range(n))
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr); f.writeframes(pcm)


def add_output(project_dir, mid, rel, kind, extra=None):
    d = Path(project_dir)
    q = d / rel
    data = q.read_bytes()
    pj = json.loads((d / "project.json").read_text("utf-8"))
    m = next(x for x in pj["modules"] if x["id"] == mid)
    o = {"key": rel, "rel": rel, "kind": kind, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    if extra:
        o.update(extra)
    m["outputs"] = [x for x in (m.get("outputs") or []) if x.get("rel") != rel] + [o]
    (d / "project.json").write_text(json.dumps(pj, ensure_ascii=False, indent=2), "utf-8")


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
    pdir = Path(st["project"]["dir"])
    make_wav(pdir / "tts" / "shot01.wav", 1.0, 440)
    make_wav(pdir / "bgm" / "bgm.wav", 1.0, 220, 48000)
    add_output(pdir, "voice-white", "tts/shot01.wav", "audio", {"line": "1", "duration": 1.0, "text": "媒体测试"})
    rng = httpx.get(BASE + "/api/studio/asset", params={"pid": pid, "path": "tts/shot01.wav"},
                    headers={"X-Agent": "1", "Range": "bytes=0-99"}, timeout=20)
    check(rng.status_code == 206 and rng.headers.get("accept-ranges") == "bytes" and len(rng.content) == 100,
          "媒体接口支持 Range 206（可拖动音频进度条）")
    add_output(pdir, "bgm", "bgm/bgm.wav", "audio", {"duration": 1.0})
    ff = shutil.which("ffmpeg")
    if not ff:
        cand = ROOT / "ws-env" / ("Scripts/ffmpeg.exe" if os.name == "nt" else "bin/ffmpeg")
        ff = str(cand) if cand.is_file() else None
    if ff:
        (pdir / "output").mkdir(exist_ok=True)
        subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x1e3a8a:s=360x640:r=12",
                        "-t", "1", "-pix_fmt", "yuv420p", str(pdir / "output" / "media-test.mp4")], check=True)
        add_output(pdir, "compose", "output/media-test.mp4", "video", {"duration": 1.0})
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
        # 音频/视频真实加载
        try:
            p.wait_for_function("document.querySelectorAll('#view-studio audio').length >= 2", timeout=8000)
            p.wait_for_function("[...document.querySelectorAll('#view-studio audio')].every(a => a.readyState >= 1 && !a.error)", timeout=12000)
        except Exception:
            pass
        a_ok = p.evaluate("[...document.querySelectorAll('#view-studio audio')].map(a => ({src:a.currentSrc.split('/').pop(), ready:a.readyState, err:a.error && a.error.code}))")
        check(len(a_ok) >= 2 and all(x["ready"] >= 1 and not x["err"] for x in a_ok), "WAV 音频真实加载（readyState ≥ 1，error 为空）: " + str(a_ok))
        if ff:
            try:
                p.wait_for_function("document.querySelectorAll('#view-studio video').length >= 1 && [...document.querySelectorAll('#view-studio video')].every(v => v.readyState >= 1 && !v.error)", timeout=12000)
            except Exception:
                pass
            v_ok = p.evaluate("[...document.querySelectorAll('#view-studio video')].map(v => ({ready:v.readyState, err:v.error && v.error.code}))")
            check(len(v_ok) >= 1 and all(x["ready"] >= 1 and not x["err"] for x in v_ok), "MP4 视频真实加载（readyState ≥ 1，error 为空）: " + str(v_ok))
        # 实时进度：起一个配音模块，界面立刻有进度条和阶段文字
        rr = c.post("/api/studio/module/run", json={"pid": pid, "id": "voice-white"})
        check(rr.status_code == 200, "启动一个模块（不返回 409）")
        try:
            p.wait_for_function("document.querySelector('[data-node=voice-white]').classList.contains('st-live')", timeout=5000)
        except Exception:
            p.wait_for_timeout(900)
        rt_txt = p.inner_text('[data-node="voice-white"] .st-rt')
        check("耗时" in rt_txt or "运行" in rt_txt or "准备" in rt_txt or "正在" in rt_txt, "运行中模块显示进度/阶段文字: " + rt_txt.replace("\n", " ")[:80])
        check(p.locator('[data-node="voice-white"] [data-rbar]').count() == 1, "运行中模块有进度条 DOM")
        c.post("/api/studio/stop", json={})
        time.sleep(1)
        # 两个独立模块同时运行（生图用慢接口、配音用长台词，确保同时看得到）
        slow = ROOT / "dev" / ".run" / "fake_img_slow.flag"
        slow.write_text("4", "utf-8")
        c.post("/api/studio/module/update", json={"pid": pid, "id": "image", "params": {"prompt": "慢速并发测试图 " + str(time.time()), "items": []}})
        long_text = "这是并发测试用的一句稍长的台词，用来让本地配音多花一点时间。" * 4
        c.post("/api/studio/module/update", json={"pid": pid, "id": "voice-white", "params": {"lines": [{"id": "l1", "line_index": 1, "text": long_text, "tone": "冷静吐槽"}]}})
        c.post("/api/studio/module/run", json={"pid": pid, "id": "image"})
        c.post("/api/studio/module/run", json={"pid": pid, "id": "voice-white"})
        try:
            p.wait_for_function("document.querySelector('[data-node=image]').classList.contains('st-live') && document.querySelector('[data-node=voice-white]').classList.contains('st-live')", timeout=8000)
        except Exception:
            pass
        live = [p.locator('[data-node="image"]').evaluate("e => e.classList.contains('st-live')"),
                p.locator('[data-node="voice-white"]').evaluate("e => e.classList.contains('st-live')")]
        check(all(live), "生图 + 白页配音两个模块同时显示运行中（并发不互斥）: " + str(live))
        c.post("/api/studio/stop", json={})
        try:
            slow.unlink()
        except OSError:
            pass
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
        try:
            p.wait_for_function("document.querySelectorAll('[data-node]').length === 7", timeout=12000)
        except Exception:
            pass
        p.wait_for_timeout(500)
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
