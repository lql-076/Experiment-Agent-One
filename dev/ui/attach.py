"""对话页带图片、读文件点一遍（v1.8.17；连测试后端，DeepSeek 是假的 dev/mocks.py）：
点回形针选图 → 上面出缩略图、能去掉 → Ctrl+V 粘贴图片 → 发出去（交给 DeepSeek 看图）→ 聊天记录里有缩略图、点开看大图 →
贴一个没允许的文件夹里的路径 → 回复下面「允许读这个文件夹，再问一次」→ 点了就读出来、回复下面写着读了哪个文件 →
设置 › 记忆与文件 里列着、能关「能发给 DeepSeek」、能「不让读了」→ 截图（横竖屏）。
用法：python dev/ui/attach.py 截图文件夹（要先 dev/serve.sh start）"""
import base64
import pathlib
import shutil
import sys

import httpx
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RUN = ROOT / "dev" / ".run"
sys.path.insert(0, str(ROOT / "dev"))
from fake_apiyi import png  # noqa: E402

errs, bad = [], []
H = {"X-Agent": "1"}


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


T = RUN / "界面读文件"
shutil.rmtree(T, ignore_errors=True)
(T / "笔记").mkdir(parents=True)
(T / "笔记" / "设定.md").write_text("# 设定\n\n看板娘：原创角色，黄昏色调。", "utf-8")
IMG = RUN / "界面测试_截图.png"
IMG.write_bytes(png(120, 80, False, 21))
uri = "data:image/png;base64," + base64.b64encode(png(90, 60, False, 5)).decode()
for d in httpx.get("http://127.0.0.1:8765/api/files/dirs", headers=H).json()["dirs"]:
    httpx.delete("http://127.0.0.1:8765/api/files/dirs", params={"path": d["path"]}, headers=H)

with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1680, "height": 1000})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/")
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.evaluate("chatOpen()")
    p.wait_for_selector("#cClip")
    p.set_input_files("#cFile", str(IMG))
    p.wait_for_function("document.querySelectorAll('#cAtts .c-att img').length === 1", timeout=5000)
    check("1 张图片会交给 DeepSeek 看" in p.inner_text("#cAtts"), "点回形针选一张图：输入框上面出缩略图，写着会交给 DeepSeek 看")
    p.click("#cAtts [data-unatt='0']")
    check(p.locator("#cAtts .c-att").count() == 0, "点 × 去掉")
    p.evaluate("""(u) => fetch(u).then(r => r.blob()).then(bl => { const dt = new DataTransfer(); dt.items.add(new File([bl], 'paste.png', {type: 'image/png'}));
        document.getElementById('cIn').dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true})); })""", uri)
    p.wait_for_function("document.querySelectorAll('#cAtts .c-att img').length === 1", timeout=5000)
    check(True, "Ctrl+V 粘贴截图：也带上了")
    p.set_input_files("#cFile", str(IMG))
    p.wait_for_function("document.querySelectorAll('#cAtts .c-att img').length === 2", timeout=5000)
    p.fill("#cIn", "这两张截图里是什么")
    p.click("#cSend")
    p.wait_for_function("!CHAT.pending", timeout=30000)
    p.wait_for_timeout(500)
    last = p.locator(".msg.ai").last
    me = p.locator(".msg.me").last
    p.wait_for_function("(function(){ var ms = document.querySelectorAll('.msg.me'), im = ms[ms.length - 1].querySelectorAll('.m-img img'); return im.length === 2 && [].every.call(im, function(i){return i.complete && i.naturalWidth > 0}); })()", timeout=8000)
    check("看图" in last.inner_text() and "看了 2 张图" in last.locator(".why-chip").inner_text() and me.locator(".m-img img").count() == 2 and p.locator("#cAtts .c-att").count() == 0,
          "发出去：DeepSeek 看了图，你的消息里带着两张缩略图，回复下面写着「看了 2 张图」")
    p.screenshot(path=f"{OUT}/chat-img.png")
    me.locator(".m-img").first.click()
    p.wait_for_selector(".c-box img")
    check(p.evaluate("document.querySelector('.c-box img').naturalWidth") > 0, "点缩略图看大图")
    p.keyboard.press("Escape")
    check(p.locator(".c-box").count() == 0, "Esc 关掉")

    p.fill("#cIn", f"看看 {T}/笔记/设定.md 写了啥")
    p.click("#cSend")
    p.wait_for_function("!CHAT.pending", timeout=30000)
    p.wait_for_selector(".msg.ai:last-child [data-allow-dir], .msg.ai [data-allow-dir]")
    btn = p.locator("[data-allow-dir]").last
    check("还没允许我读" in p.locator(".msg.ai").last.inner_text() and btn.get_attribute("data-allow-dir") == str(T / "笔记"), "贴了没允许的文件夹里的路径：回复下面有「允许读这个文件夹，再问一次」")
    btn.click()
    p.wait_for_function("CHAT.pending", timeout=5000)
    p.wait_for_function("!CHAT.pending", timeout=30000)
    p.wait_for_timeout(400)
    ai = p.locator(".msg.ai").last
    check("设定.md" in ai.locator(".m-files").inner_text() and "读了 1 个文件" in ai.locator(".why-chip").inner_text(), "点了就允许（只读）并且再问一次：读出来了，回复下面写着读了哪个文件")
    p.screenshot(path=f"{OUT}/chat-files.png")
    ai.locator(".why-chip").click()
    p.wait_for_timeout(400)
    check("设定.md" in p.inner_text("#hmNow .hm-pop") and "读文件" in p.inner_text("#hmNow .hm-pop"), "主页「细节」里列着读了哪个文件、每一步")

    p.evaluate("S.sec='memory'; renderSettings(); goView('settings')")
    p.wait_for_selector("#rdirs .rd-row")
    row = p.locator("#rdirs .rd-row").first
    check(str(T / "笔记") in row.inner_text() and row.locator(".switch").get_attribute("aria-checked") == "true", "设置 › 记忆与文件：列着能读的文件夹，「能发给 DeepSeek」开着")
    row.locator(".switch").click()
    p.wait_for_timeout(500)
    ds = httpx.get("http://127.0.0.1:8765/api/files/dirs", headers=H).json()["dirs"]
    check(ds and ds[0]["cloud"] is False and p.locator("#rdirs .switch").first.get_attribute("aria-checked") == "false", "关掉「能发给 DeepSeek」：只给本地小脑看")
    p.screenshot(path=f"{OUT}/settings-rdirs.png")
    p.set_viewport_size({"width": 1080, "height": 1860})
    p.wait_for_timeout(800)
    p.screenshot(path=f"{OUT}/settings-rdirs-portrait.png")
    p.wait_for_timeout(600)
    p.evaluate("chatOpen()")
    p.wait_for_timeout(800)
    p.screenshot(path=f"{OUT}/chat-img-portrait.png")
    p.set_viewport_size({"width": 1680, "height": 1000})
    p.wait_for_timeout(600)
    p.evaluate("S.sec='memory'; renderSettings(); goView('settings')")
    p.wait_for_selector("#rdirs [data-rd-del]")
    p.click("#rdirs [data-rd-del]")
    p.wait_for_timeout(500)
    check(httpx.get("http://127.0.0.1:8765/api/files/dirs", headers=H).json()["dirs"] == [] and "还没有" in p.inner_text("#rdirs"), "「不让读了」：从列表里去掉")
    b.close()
shutil.rmtree(T, ignore_errors=True)
IMG.unlink(missing_ok=True)
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
