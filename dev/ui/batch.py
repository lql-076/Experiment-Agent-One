"""配音批量、配乐批量点一遍（v3.1，连测试后端：配音服务是假的 dev/fake_tts.py，ACE-Step 是假的 dev/mocks.py 8001）：
配音页切到「批量」→ 贴清单 → 认清单（一段一行、音色写在后面）→ 点开一段改字 → 右边「开始批量」→ 跑的时候右边写着第几段、能停 →
都好了（绿点、多长）→ 点 ▶ 有声音 → 切回「一段」文案还在 → 刷新后还是批量、清单还在；
配乐页切到「批量」→ 选文件（.md）→ 开始批量 → 好了点一首，中间放它 → 「只补没出的」不出现（都好了）。
用法：python dev/ui/batch.py 截图文件夹（要先 dev/serve.sh start）"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
RUN = pathlib.Path(__file__).resolve().parent.parent / ".run"
errs, bad = [], []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


MD = """# 界面测试 · 配音清单
## 01_开场
音色：Serena
大家好，欢迎回来。
## 02_吐槽
音色：Uncle_Fu
语气：激动
这也太离谱了吧！
## 03_结尾
下期见。
"""

with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1440, "height": 880})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/?tool=tts")
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.evaluate("api('PUT', '/api/settings', {ttsOut: 'dev/.run/配音输出-测试', bgmOut: 'dev/.run/配乐输出-测试', ttsEngine: 'local'})")
    p.evaluate("api('POST', '/api/tts/batch/clear', {}); api('POST', '/api/bgm/batch/clear', {})")
    p.evaluate("localStorage.removeItem('agentTTS.v1'); TTS.form=null; TTS.eng='local'; if (TTS.st) TTS.st.engine='local'; renderTTS()")
    p.wait_for_selector("#ttsText")
    p.fill("#ttsText", "一段模式的文案。")
    p.click('[data-ttsbm="1"]')
    p.wait_for_selector('[data-mbpaste="tts"]')
    check(p.is_visible('[data-mbpaste="tts"]') and not p.is_visible("#ttsText"), "切到「批量」：文案框换成贴清单的框")
    check(p.is_disabled('#ttsGen .tts-go'), "还没认清单：「开始批量」点不了")
    p.fill('[data-mbpaste="tts"]', MD)
    p.click('[data-mbk="tts"] [data-mba="load"]')
    p.wait_for_selector('[data-mbk="tts"] .mb-row')
    rows = p.locator('[data-mbk="tts"] .mb-row')
    check(rows.count() == 3 and "Uncle_Fu · 激动" in rows.nth(1).inner_text(), f"认好了：3 段一行一段，音色、语气写在后面（{rows.count()} 行）")
    check("开始批量 · 3 段" in p.inner_text("#ttsGen"), "右边原来「生成配音」的位置变成「开始批量 · 3 段」")
    p.click('[data-mbk="tts"] .mb-main >> nth=2')
    p.wait_for_selector('[data-mbk="tts"] .mb-ed textarea')
    p.fill('[data-mbk="tts"] .mb-ed textarea', "下期再见。")
    p.locator('[data-mbk="tts"] .mb-ed textarea').blur()
    p.wait_for_function("(MBX.tts.st.board.items[2] || {}).text === '下期再见。'", timeout=5000)
    check(True, "点开一段改字，离开输入框就存了")
    p.click('#ttsGen [data-mba="go"]')
    p.wait_for_function("mbRun('tts') || (MBX.tts.st.job && MBX.tts.st.job.st !== 'run')", timeout=10000)
    seen_now = False
    for _ in range(60):
        t = p.inner_text("#ttsGen")
        seen_now = seen_now or "批量" in t
        if p.evaluate("MBX.tts.st.job && MBX.tts.st.job.st !== 'run'"):
            break
        p.wait_for_timeout(300)
    p.wait_for_timeout(1200)
    check(seen_now, "跑的时候右边写着批量第几段、能停")
    oks = p.locator('[data-mbk="tts"] .mb-row.st-ok').count()
    check(oks == 3 and p.locator('[data-mbk="tts"] [data-mba="play"]:not([disabled])').count() == 3, f"3 段都好了（绿点、能听）：{oks}")
    p.screenshot(path=f"{OUT}/batch-tts.png")
    p.click('[data-mbk="tts"] [data-mba="play"] >> nth=0')
    p.wait_for_timeout(800)
    check(p.evaluate("!!MBX.au && MBX.au.src.indexOf('/api/tts/batch/file/b1') >= 0"), "点 ▶ 放的是这一段")
    p.evaluate("MBX.au && MBX.au.pause()")
    p.click('[data-ttsbm="0"]')
    p.wait_for_selector("#ttsText")
    check(p.input_value("#ttsText") == "一段模式的文案。", "切回「一段」：原来的文案还在")
    p.click('[data-ttsbm="1"]')
    p.wait_for_timeout(600)                      # 输入的东西 0.3 秒后存进浏览器
    p.reload()
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.wait_for_selector('[data-mbk="tts"] .mb-row', timeout=10000)
    check(p.locator('[data-mbk="tts"] .mb-row').count() == 3, "刷新后还是批量，清单还在（存在后端）")

    # 配乐
    p.goto("http://127.0.0.1:8765/?tool=bgm")
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.wait_for_selector('[data-bgm-mode="batch"]')
    p.click('[data-bgm-mode="batch"]')
    p.wait_for_selector('input[data-mbfile="bgm"]', state="attached")
    f = RUN / "界面测试_配乐清单.md"
    f.write_text("# 界面测试 · 配乐清单\n## bgm01_开场\n时长：20\n描述：轻快的电子乐\n## bgm02_结尾\n时长：25\n描述：温暖的木吉他\n", "utf-8")
    p.set_input_files('input[data-mbfile="bgm"]', str(f))
    p.wait_for_selector('[data-mbk="bgm"] .mb-row')
    check(p.locator('[data-mbk="bgm"] .mb-row').count() == 2, "选一个 .md：认出 2 首")
    p.click('[data-mbk="bgm"] [data-mba="go"]')
    for _ in range(80):
        if p.evaluate("MBX.bgm.st && MBX.bgm.st.job && MBX.bgm.st.job.st !== 'run'"):
            break
        p.wait_for_timeout(300)
    p.wait_for_timeout(1700)
    check(p.locator('[data-mbk="bgm"] .mb-row.st-ok').count() == 2, "2 首都出好了")
    check(p.locator('[data-mbk="bgm"] [data-mba="miss"]').count() == 0, "都好了：不出现「只补没出的」")
    p.click('[data-mbk="bgm"] .mb-main >> nth=1')
    p.wait_for_timeout(600)
    check("bgm02_结尾" in p.inner_text(".bg-mid"), "点一首出好的：中间放它")
    p.screenshot(path=f"{OUT}/batch-bgm.png")
    p.evaluate("api('POST', '/api/tts/batch/clear', {}); api('POST', '/api/bgm/batch/clear', {}); api('PUT', '/api/settings', {ttsOut: '', bgmOut: ''})")
    p.wait_for_timeout(300)
    f.unlink(missing_ok=True)
    b.close()

print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
