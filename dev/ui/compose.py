"""模块 6 三窗一体点一遍（v4.0.0 / R11）：网页动效监控、PPT 监控、FFmpeg 监控、成片进模块 7。
用法：python dev/ui/compose.py 截图文件夹（要先 dev/serve.sh start）"""
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
errs, bad = [], []
LIST = """# 视频渲染清单

- 标题：三窗界面测试
- 画幅：9:16
- 总时长：4

## 01
时长：2
方式：网页动效
画面：深色科技感排版，主标题和动态字幕
字幕：网页动效测试字幕
转场：淡入

## 02
时长：2
方式：PPT 卡片
画面：两个要点、对比卡片
字幕：PPT 卡片测试字幕
转场：推近
"""


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def wait_job(c, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(1)
        s = c.get("/api/studio/state").json()
        j = s.get("job") or {}
        if j.get("st") != "run":
            return s
    return s


with httpx.Client(base_url=BASE, timeout=300, headers={"X-Agent": "1"}) as c:
    st = c.post("/api/studio/new", json={"topic": "三窗界面测试", "voice_id": "local:preset:Vivian"}).json()
    pid = st["project"]["id"]
    c.put("/api/studio/list", json={"pid": pid, "name": "视频渲染清单.md", "text": LIST})
    c.post("/api/studio/module/update", json={"pid": pid, "id": "compose", "params": {"subtitle": False, "bgm_volume": 0, "cc_drive": False}})
    with sync_playwright() as pw:
        b = launch(pw)
        p = b.new_page(viewport={"width": 1440, "height": 880})
        p.on("pageerror", lambda e: errs.append(str(e)))
        p.goto(BASE + "/?tool=studio")
        p.wait_for_timeout(1800)
        p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
        p.wait_for_timeout(1500)
        try:
            p.wait_for_function("document.querySelectorAll('[data-node]').length === 7", timeout=12000)
        except Exception:
            pass
        check(p.locator('.st-mon').count() == 3, "模块 6 里有 3 个监控窗口")
        check(p.locator('.st-mon-a').count() == 1 and p.locator('.st-mon-b').count() == 1 and p.locator('.st-mon-c').count() == 1, "A 网页 / B PPT / C FFmpeg 三窗都在")
        # 点模块 6 的一键合成
        p.evaluate("STUDIO.canvas.s=.55; applyCanvas(); var e=document.querySelector('[data-node=compose]'); if(e) e.scrollIntoView();")
        p.wait_for_timeout(300)
        p.locator('[data-node="compose"] [data-run="compose"]').first.dispatch_event('click')
        s = wait_job(c, 300)
        check((s.get("job") or {}).get("st") in ("done", "stop"), "一键合成跑完")
        w = (s.get("job") or {}).get("web") or {}
        pp = (s.get("job") or {}).get("ppt") or {}
        ff = (s.get("job") or {}).get("ffmpeg") or {}
        check(w.get("st") == "ok" and w.get("preview_rel"), "A 窗：网页动效完成且有预览帧")
        check(pp.get("st") == "ok" and (pp.get("slides") or []), "B 窗：PPT 卡片完成且有缩略图")
        check(ff.get("st") == "ok" and ff.get("pct") == 100, "C 窗：FFmpeg 压制完成、进度 100%")
        p.wait_for_timeout(1800)
        try:
            p.wait_for_function("document.querySelectorAll('.st-mon-a img.st-mon-img').length > 0 && document.querySelectorAll('.st-mon-b .st-slide').length > 0", timeout=12000)
        except Exception:
            pass
        check(p.locator('.st-mon-a img.st-mon-img').count() >= 1, "界面里能看到网页预览帧")
        check(p.locator('.st-mon-b .st-slide').count() >= 1, "界面里能看到 PPT 缩略图")
        check("100%" in p.inner_text('.st-mon-c'), "界面里 C 窗显示 100%")
        check(p.locator('[data-node="publish"] video').count() >= 1, "成片自动进模块 7 预览")
        check((s.get("project") or {}).get("video_ok") is True, "后端标记成片已就绪")
        # 仅重跑 FFmpeg
        p.locator('[data-runpart="ffmpeg"]').dispatch_event('click')
        s2 = wait_job(c, 180)
        check((s2.get("job") or {}).get("st") in ("done", "stop"), "仅重跑 FFmpeg 完成")
        p.screenshot(path=OUT + "/compose-v4.png")
        b.close()

print("JS 报错：", errs or "没有")
print("没通过：", bad or "没有")
sys.exit(1 if bad or errs else 0)
