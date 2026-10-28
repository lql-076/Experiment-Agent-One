"""配音页点一遍（连测试后端，配音服务是假的 dev/fake_tts.py）：
贴文案 → 选音色 → 生成（进度、完成）→ 试听有声音、时间轴一句一行 → 点时间轴跳到那一句 → 保存 →
切到描述音色 → 存成我的音色（出现在上面）→ 点它把描述和种子填回来 → 删掉 → 输入的东西刷新后还在。
用法：python dev/ui/tts.py 截图文件夹（要先 dev/serve.sh start）"""
import sys

from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
errs, bad = [], []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1680, "height": 1000})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/")
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.evaluate("localStorage.removeItem('agentTTS.v1'); TTS.form=null")
    p.evaluate("api('PUT', '/api/settings', {ttsOut: 'dev/.run/配音输出-测试'})")     # 测试存的配音放 dev/.run，不放进「配音输出」
    p.click('.nav[data-view="tts"]')
    p.wait_for_selector("#ttsText")
    p.fill("#ttsText", "大家好，欢迎回来。今天聊三个工具！\n\n第一个是本地配音。")
    check("字" in p.inner_text("#ttsCount"), "贴了文案：显示字数和大概多长：" + p.inner_text("#ttsCount"))
    p.click('.tts-sp[data-spk="Uncle_Fu"]')
    check(p.get_attribute('.tts-sp[data-spk="Uncle_Fu"]', "aria-pressed") == "true", "点音色：选中 Uncle_Fu")
    p.fill("#ttsTone", "语速稍快")
    p.click('[data-act="gen"]')
    p.wait_for_selector("#ttsGen .prog", timeout=5000)
    check(True, "点生成：出现进度条")
    p.wait_for_selector("#ttsGen .tts-msg.ok", timeout=30000)
    p.wait_for_selector("#ttsTl .tts-seg", timeout=8000)
    n = p.locator("#ttsTl .tts-seg").count()
    check(n == 3, f"生成好了：时间轴一句一行（{n} 行）")
    check("Uncle_Fu" in p.inner_text("#ttsRes .hc-h"), "试听那里写着音色：" + p.inner_text("#ttsRes .hc-h"))
    p.wait_for_function("document.getElementById('ttsAudio').readyState >= 1", timeout=8000)
    dur = p.evaluate("document.getElementById('ttsAudio').duration")
    check(dur > 4, f"试听：浏览器读得到音频（{dur:.2f} 秒）")
    p.locator("#ttsTl .tts-seg").nth(2).click()
    p.wait_for_timeout(300)
    t = p.evaluate("document.getElementById('ttsAudio').currentTime")
    check(t >= 3.0, f"点时间轴第 3 句：跳到那里（{t:.2f} 秒）")
    p.screenshot(path=f"{OUT}/tts-done.png")
    p.click('[data-act="save"]')
    p.wait_for_function("(document.querySelector('.tts-saved') || {}).textContent && document.querySelector('.tts-saved').textContent.indexOf(TTS.st.draft.name) > 0", timeout=8000)
    check(True, "保存：显示存的文件夹名：" + p.inner_text(".tts-saved"))

    p.click('#ttsMode [data-mode="design"]')
    p.wait_for_selector("#ttsDesc")
    p.fill("#ttsDesc", "三十岁左右的男声，低沉温和，语速平稳")
    seed = p.input_value("#ttsSeed")
    p.click('[data-act="reseed"]')
    check(p.input_value("#ttsSeed") != seed, "换一个：种子变了")
    p.fill("#ttsSeed", "12345")
    p.fill("#ttsName", "测试解说")
    p.click('[data-act="savevoice"]')
    p.wait_for_selector('[data-voice]', timeout=5000)
    check("测试解说" in p.inner_text(".tts-mine"), "存成我的音色：出现在「我的音色」里")
    p.fill("#ttsDesc", "别的描述")
    p.fill("#ttsSeed", "9")
    p.click('[data-voice]')
    check(p.input_value("#ttsDesc") == "三十岁左右的男声，低沉温和，语速平稳" and p.input_value("#ttsSeed") == "12345", "点我的音色：描述和种子填回来")
    p.screenshot(path=f"{OUT}/tts-design.png")
    p.wait_for_timeout(500)                 # 输入框的内容 0.3 秒后才存进浏览器
    p.reload()
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.evaluate("goView('tts')")
    try:
        p.wait_for_selector("#ttsDesc", timeout=8000)
    except Exception:
        print(p.evaluate("[S.view, JSON.stringify(TTS.form), localStorage.getItem('agentTTS.v1')]"))
        p.screenshot(path=f"{OUT}/tts-reload.png")
        raise
    check(p.input_value("#ttsDesc").startswith("三十岁") and p.input_value("#ttsTone") == "语速稍快", "刷新以后：描述、语气还在")
    p.click('[data-delvoice]')
    p.wait_for_timeout(800)
    check(p.locator("[data-voice]").count() == 0, "删掉我的音色")
    p.click('#ttsMode [data-mode="preset"]')
    p.evaluate("api('PUT', '/api/settings', {ttsOut: ''})")
    p.wait_for_timeout(300)
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
