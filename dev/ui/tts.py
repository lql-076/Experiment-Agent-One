"""配音页点一遍（连测试后端，配音服务是假的 dev/fake_tts.py）：
贴文案 → 选音色 → 生成（进度、完成）→ 试听有声音、时间轴一句一行 → 点时间轴跳到那一句 → 保存 →
切到描述音色 → 存成我的音色（出现在上面）→ 点它把描述和种子填回来 → 删掉 → 输入的东西刷新后还在 →
换百炼云端：4 个音色、试听、预估花费、生成、刷新后还是云端、没填 Key 的提示、设置 › 云端 填 Key → 换回本地 →
设置 › 本地模型 点「安装配音」看进度到装好 → 设置 › 自动化 有「开机自启」开关。
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
    check(p.get_attribute('#ttsWay [data-way="1"]', "aria-pressed") == "true", "默认「整段一次生成」")
    p.click('#ttsWay [data-way="0"]')
    p.wait_for_timeout(700)
    check(p.get_attribute('#ttsWay [data-way="0"]', "aria-pressed") == "true" and p.evaluate("S.set.ttsWhole") is False, "点「一句一句」：切过去了，存进设置")
    p.click('#ttsWay [data-way="1"]')
    p.wait_for_timeout(700)
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

    # 百炼云端（v1.8.11，测试后端连的是假的百炼 dev/fake_bailian.py，假 Key sk-test-0000）
    p.click('#ttsEng [data-eng="cloud"]')
    p.wait_for_selector("[data-cv]")
    check(p.locator("[data-cv]").count() == 4 and "百炼" in p.inner_text(".tts .ph .sub") and p.locator("#ttsMode").count() == 0,
          "点「百炼云端」：列出 4 个中文音色，标题旁写明只把文案和语气发给百炼")
    p.fill("#ttsText", "大家好，欢迎回来。今天聊三个工具！\n\n第一个是配音。")
    check("预估 ¥" in p.inner_text("#ttsCount") and "计费字符" in p.inner_text("#ttsEst"), "贴了文案：显示字数和预估花费：" + p.inner_text("#ttsEst").split("\n")[0])
    p.click('[data-cvtry="longanlingxin_v3.1"]')
    p.wait_for_function("TTS.tryAu && TTS.tryAu.readyState >= 1", timeout=20000)
    check(p.evaluate("TTS.tryAu.duration") > 2, f"点「试听」：念一句固定的短句（{p.evaluate('TTS.tryAu.duration'):.1f} 秒）")
    p.click('[data-cv="xunanchuan_v3.1"]')
    check(p.get_attribute('[data-cv="xunanchuan_v3.1"]', "aria-pressed") == "true", "点音色：选中许南川")
    p.fill("#ttsTone", "请用轻松的语气")
    p.click('[data-act="gen"]')
    p.wait_for_function("(document.querySelector('#ttsGen .tts-msg.ok') || {}).textContent && document.querySelector('#ttsGen .tts-msg.ok').textContent.indexOf('花了约') >= 0", timeout=30000)
    p.wait_for_function("document.querySelectorAll('#ttsTl .tts-seg').length === 3 && document.querySelector('#ttsRes .hc-h').textContent.indexOf('许南川') >= 0", timeout=8000)
    check(True, "生成好了：说了花多少，时间轴 3 句，试听那里写着许南川 · 百炼：" + p.inner_text("#ttsGen .tts-msg.ok"))
    p.screenshot(path=f"{OUT}/tts-cloud.png")
    p.wait_for_timeout(600)                 # 引擎 0.4 秒后才存进设置
    p.reload()
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.evaluate("goView('tts')")
    p.wait_for_selector("[data-cv]", timeout=8000)
    check(p.get_attribute('#ttsEng [data-eng="cloud"]', "aria-pressed") == "true", "刷新以后还是百炼云端（存进了设置）")
    p.evaluate("api('PUT', '/api/secrets', {k: 'blKey', v: ''}).then(function (j) { SECRETS = j.hints; return ttsLoad(); }).then(ttsSync)")
    p.wait_for_selector('[data-act="gokey"]', timeout=8000)
    check(p.is_disabled('[data-act="gen"]') and "还没填百炼 API Key" in p.inner_text("#ttsGen"), "没填百炼 Key：提示去 设置 › 云端，生成按钮灰着")
    p.click('[data-act="gokey"]')
    p.wait_for_selector("#f-blKey", timeout=5000)
    p.fill("#f-blKey", "sk-test-0000")
    p.click('[data-secret-save="blKey"]')
    p.wait_for_function("(document.getElementById('f-blKey') || {}).placeholder && document.getElementById('f-blKey').placeholder.indexOf('0000') >= 0", timeout=8000)
    check("••••0000" in p.get_attribute("#f-blKey", "placeholder") and p.input_value("#f-blKey") == "", "设置 › 云端 填百炼 Key、保存：只显示最后 4 位")
    check(p.locator("#f-blModel").input_value() == "qwen-audio-3.1-tts-plus" and p.locator("#f-blPrice").count() == 1 and p.locator("#f-blMax").count() == 1,
          "设置 › 云端 还能改模型名（默认 Plus）、单价、一次最多发多少字")
    p.evaluate("goView('tts')")
    p.wait_for_selector("#ttsEng")
    p.click('#ttsEng [data-eng="local"]')
    p.wait_for_selector("#ttsMode")
    check(p.get_attribute('#ttsEng [data-eng="local"]', "aria-pressed") == "true", "换回本地 Qwen3-TTS")
    p.wait_for_timeout(600)
    p.evaluate("api('PUT', '/api/settings', {ttsOut: ''})")
    p.wait_for_timeout(300)

    # 设置 › 本地模型 的「安装配音」（测试后端里是假的安装，几秒就完）
    p.evaluate("S.sec='models'; renderSettings(); goView('settings')")
    p.wait_for_selector("#ttsInst [data-tti]", timeout=8000)
    txt = p.inner_text("#ttsInst")
    check("配音环境" in txt and "预设音色模型" in txt and "描述音色模型" in txt, "设置 › 本地模型 里有「配音」一块：环境、两个模型各装没装")
    p.click("#ttsInst [data-tti]")
    p.wait_for_selector("#ttsInst .prog", timeout=5000)
    check(True, "点「安装配音」：出现进度条")
    p.wait_for_selector("#ttsInst .tts-msg.ok", timeout=30000)
    check("装好了" in p.inner_text("#ttsInst"), "装完了：显示「装好了」")
    p.screenshot(path=f"{OUT}/tts-install.png")
    p.evaluate("S.sec='auto'; renderSettings(); goView('settings')")
    p.wait_for_selector("#autoSw", timeout=5000)
    check("开机自启" in p.inner_text("#autoSt"), "设置 › 自动化 最上面有「开机自启」开关（沙箱里不是 Windows，开关灰着）")
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
