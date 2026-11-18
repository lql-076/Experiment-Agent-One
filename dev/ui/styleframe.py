"""看图复刻点一遍（v3.9.0 / R10）：网页动效节点接参考图 → 点按钮（确认额度）→ 假 Claude Code 写 HTML → 录成视频轨；同参数再点直接命中。
用法：python dev/ui/styleframe.py 截图文件夹（要先 dev/serve.sh start，并配好假 claude）"""
import base64
import os
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = Path(__file__).resolve().parent.parent.parent
PORT = os.environ.get("AGENT_TEST_PORT", "8765")
BASE = "http://127.0.0.1:" + PORT
RUN = ROOT / "dev" / ".run"
errs, bad = [], []
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lzq4WQAAAABJRU5ErkJggg==")


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def wait_job(c, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(1)
        s = c.get("/api/studio/state").json()
        j = s.get("job") or {}
        if j.get("st") != "run":
            return s
    return s


with httpx.Client(base_url=BASE, timeout=180, headers={"X-Agent": "1"}) as c:
    st = c.post("/api/studio/new", json={"topic": "看图复刻界面测试", "voice_id": "local:preset:Vivian"}).json()
    pid = st["project"]["id"]
    d = Path(st["project"]["dir"])
    (d / "images").mkdir(parents=True, exist_ok=True)
    (d / "images" / "ref.png").write_bytes(PNG)
    # 直接把参考图挂到生图节点上（不花 API 的钱）
    p = c.get("/api/studio/state").json()["project"]
    # 用后端测试口做不到直接写 outputs，这里通过一次真实的假 API 生图：先改提示词再跑
    c.post("/api/studio/graph/update", json={"pid": pid, "id": "image-1", "params": {"prompt": "一张界面排版参考图"}})
    c.post("/api/studio/graph/run", json={"pid": pid, "id": "image-1"})
    s = wait_job(c)
    img = next(n for n in s["project"]["graph"]["nodes"] if n["id"] == "image-1")
    check(img["status"] == "ok" and img.get("outputs"), "先出好参考图")
    c.post("/api/studio/graph/connect", json={"pid": pid, "from": "image-1.image", "to": "web-1.image"})
    c.post("/api/studio/graph/update", json={"pid": pid, "id": "web-1", "params": {"text": "看图复刻字幕", "duration": 1, "fps": 12}})
    # 假的 claude
    cc = RUN / ("claude.cmd" if os.name == "nt" else "claude")
    if os.name == "nt":
        cc.write_text('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, ROOT / "dev" / "fake_claude.py"), "utf-8")
    else:
        cc.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, ROOT / "dev" / "fake_claude.py"), "utf-8")
        cc.chmod(0o755)
    r = c.put("/api/agent/caps", json={"cc": True, "cc_cmd": str(cc), "cc_bash": "python"})
    check(r.status_code == 200 and r.json().get("cc", {}).get("on"), "Claude Code 引擎开（假的 claude）")

    with sync_playwright() as pw:
        b = launch(pw)
        p = b.new_page(viewport={"width": 1440, "height": 880})
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.on("dialog", lambda x: x.accept())
        p.goto(BASE + "/?tool=studio")
        p.wait_for_timeout(1800)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(1400)
        p.click('[data-st="fit"]')
        p.wait_for_timeout(400)
        btn = p.locator('[data-act="styleframe"]')
        check(btn.count() == 1, "网页动效节点有「交给 Claude Code 看图复刻并录制」按钮")
        btn.click()
        p.wait_for_timeout(800)
        s = wait_job(c, 240)
        w = next(n for n in s["project"]["graph"]["nodes"] if n["id"] == "web-1")
        check(w["status"] == "ok" and w.get("outputs"), "复刻完成、节点有视频轨" + ("（" + str(w.get("error"))[:160] + "）" if w.get("error") else ""))
        fl = RUN / "fake_claude_last.json"
        prompt = (fl.read_text("utf-8") if fl.is_file() else "")
        check("60-30-10" in prompt and "禁止联网" in prompt, "提示词带 60-30-10 和禁止外链")
        mt = fl.stat().st_mtime if fl.is_file() else 0
        # 同参数再点一次：直接命中，不再调 Claude Code
        p.wait_for_timeout(1200)
        btn = p.locator('[data-act="styleframe"]')
        btn.click()
        p.wait_for_timeout(1000)
        s2 = wait_job(c, 60)
        mt2 = fl.stat().st_mtime if fl.is_file() else 0
        check(abs(mt2 - mt) < 0.01, "第二次没有调用 Claude Code（假的命令行文件没被重写）")
        check("参数没变" in (s2.get("job") or {}).get("msg", ""), "第二次提示参数没变、直接用上次的轨")
        try:
            p.wait_for_selector('[data-node="web-1"] video', timeout=5000)
        except Exception:
            pass
        check(p.locator('[data-node="web-1"] video').count() >= 1, "界面里能看到复刻出来的视频")
        p.screenshot(path=OUT + "/styleframe.png")
        b.close()

print("JS 报错：", errs or "没有")
print("没通过：", bad or "没有")
sys.exit(1 if bad or errs else 0)
