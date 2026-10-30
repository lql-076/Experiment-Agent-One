"""配音页点一遍（连测试后端，配音服务是假的 dev/fake_tts.py）：
贴文案 → 选音色 → 生成（进度、完成）→ 试听有声音、时间轴一句一行 → 点时间轴跳到那一句 → 保存 →
切到描述音色 → 存成我的音色（出现在上面）→ 点它把描述和种子填回来 → 删掉 → 输入的东西刷新后还在 →
换云端：4 个音色、插标签、试听、预估花费、语速、生成、波形（点哪听哪、空格键）、设计一个音色（试听、审核、拿来生成）、
复刻（上传录音、要先确认）、读音词典、删音色、刷新后还是云端、没填 Key 的提示、设置 › 云端 填 Key → 换回本地 →
设置 › 本地模型 点「安装配音」看进度到装好 → 设置 › 自动化 有「开机自启」开关。
用法：python dev/ui/tts.py 截图文件夹（要先 dev/serve.sh start）"""
import pathlib
import sys
import wave

import httpx
import numpy as np
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
B = "http://127.0.0.1:8765"
FAKE = "http://127.0.0.1:8097"
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

    # 百炼云端（v1.8.11；v1.8.12 加了设计、复刻、读音、语速这些。测试后端连的是假的百炼 dev/fake_bailian.py，假 Key sk-test-0000）
    p.click('#ttsEng [data-eng="cloud"]')
    p.wait_for_selector("[data-cv]")
    check(p.locator('#ttsVoice [data-cv$="_v3.1"]').count() == 4 and p.get_attribute("#ttsEng", "data-on") == "cloud" and "百炼" in p.inner_text(".tts .ph .sub")
          and p.locator("#ttsMode").count() == 0 and p.locator("#ttsTabs button").count() == 4,
          "点「云端」：开关滑过去，音色库列出 4 个现成的中文音色，有 音色库 / 设计 / 复刻 / 读音 四页")
    p.fill("#ttsText", "大家好，欢迎回来。今天聊三个工具！\n\n第一个是配音。")
    check("预估 ¥" in p.inner_text("#ttsCount") and "计费字符" in p.inner_text("#ttsEst"), "贴了文案：显示字数和预估花费：" + p.inner_text("#ttsEst").split("\n")[0])
    p.evaluate("var t=document.getElementById('ttsText'); t.focus(); t.setSelectionRange(0,0)")
    p.click('[data-tag="excited"]')
    check(p.input_value("#ttsText").startswith("[excited]大家好"), "点「兴奋」：在光标处插 [excited]")
    p.fill("#ttsText", "大家好，欢迎回来。今天聊三个工具！\n\n第一个是配音。")
    p.click('[data-cvtry="longanlingxin_v3.1"]')
    p.wait_for_function("TTS.tryAu && TTS.tryAu.readyState >= 1", timeout=20000)
    check(p.evaluate("TTS.tryAu.duration") > 2, f"点「试听」：念一句固定的短句（{p.evaluate('TTS.tryAu.duration'):.1f} 秒）")
    p.click('[data-cv="xunanchuan_v3.1"]')
    check(p.get_attribute('[data-cv="xunanchuan_v3.1"]', "aria-pressed") == "true" and "许南川" in p.inner_text(".tts-using"), "点音色：选中许南川，生成按钮旁写着用谁念")
    p.fill("#ttsTone", "请用轻松的语气")
    p.evaluate("var r=document.getElementById('ttsRate'); r.value=1.2; r.dispatchEvent(new Event('input',{bubbles:true}))")
    check(p.inner_text("#ottsRate") == "×1.2", "拖语速：数字跟着变（×1.2）")
    n0 = httpx.get(FAKE + "/_fake/log").json()["n"]
    p.click('[data-act="gen"]')
    p.wait_for_function("(document.querySelector('#ttsGen .tts-msg.ok') || {}).textContent && document.querySelector('#ttsGen .tts-msg.ok').textContent.indexOf('花了约') >= 0", timeout=30000)
    p.wait_for_function("document.querySelectorAll('#ttsTl .tts-seg').length === 3 && document.querySelector('#ttsRes .hc-h').textContent.indexOf('许南川') >= 0", timeout=8000)
    check(True, "生成好了：说了花多少，时间轴 3 句，试听那里写着许南川 · 百炼：" + p.inner_text("#ttsGen .tts-msg.ok"))
    check("百炼逐字时间戳" in p.inner_text("#ttsChk") and "3 句都是准的" in p.inner_text("#ttsChk"), "波形下面写着时间轴准不准：" + p.inner_text("#ttsChk"))
    last = httpx.get(FAKE + "/_fake/log").json()["items"][-1]["body"]["input"]
    check(httpx.get(FAKE + "/_fake/log").json()["n"] == n0 + 1 and last.get("rate") == 1.2 and last.get("instruction") == "请用轻松的语气", "发给百炼的带着语速 1.2 和语气")
    p.wait_for_function("TTS.wave && TTS.wave.peaks && TTS.wave.peaks.length > 100", timeout=8000)
    lit = p.evaluate("(function(){var c=document.getElementById('ttsWave'),x=c.getContext('2d'),d=x.getImageData(0,0,c.width,c.height).data,n=0;for(var i=3;i<d.length;i+=4)if(d[i]>0)n++;return n/(c.width*c.height)})()")
    check(lit > 0.05, f"波形画出来了（画了 {lit:.0%} 的面积）")
    box = p.locator("#ttsStage").bounding_box()
    p.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
    p.wait_for_timeout(250)
    dur = p.evaluate("TTS.st.draft.duration")
    t = p.evaluate("document.getElementById('ttsAudio').currentTime")
    check(abs(t - dur / 2) < 0.6, f"点波形中间：跳到那里播放（{t:.2f} / {dur:.2f} 秒）")
    p.evaluate("document.activeElement && document.activeElement.blur()")
    p.evaluate("document.getElementById('ttsAudio').pause()")
    p.keyboard.press(" ")
    p.wait_for_timeout(200)
    playing = p.evaluate("!document.getElementById('ttsAudio').paused")
    p.keyboard.press(" ")
    p.wait_for_timeout(200)
    check(playing and p.evaluate("document.getElementById('ttsAudio').paused"), "空格键：播放、再按暂停")
    p.dblclick("#ttsRate")
    check(p.inner_text("#ottsRate") == "×1.0", "双击语速：回到默认 ×1.0")

    # 设计一个音色
    p.click('[data-tab="design"]')
    p.wait_for_selector("#bdPrompt")
    p.fill("#bdPrompt", "三十岁左右的男声，低沉有磁性")
    p.click('[data-hint="语速平稳"]')
    check(p.input_value("#bdPrompt") == "三十岁左右的男声，低沉有磁性，语速平稳", "点灵感词：接在描述后面")
    p.fill("#bdName", "界面测试设计")
    p.click('[data-act="design"]')
    p.wait_for_function("(TTS.st.cloud.mine||[]).some(function(v){return v.name==='界面测试设计'})", timeout=15000)
    p.wait_for_function("TTS.tryAu && TTS.tryId.indexOf('-vd-') > 0 && TTS.tryAu.readyState >= 1", timeout=15000)
    check("界面测试设计" in p.inner_text("#ttsVoice"), "设计好了：出现在「最近设计的」里，马上放百炼给的试听")
    p.screenshot(path=f"{OUT}/tts-design.png")
    p.wait_for_function("(TTS.st.cloud.mine||[]).some(function(v){return v.name==='界面测试设计' && v.status==='OK'})", timeout=20000)
    check(True, "百炼审核通过：「审核中」变成能用")
    vid = p.evaluate("TTS.st.cloud.mine.filter(function(v){return v.name==='界面测试设计'})[0].id")
    p.click('[data-tab="lib"]')
    p.click(f'[data-cv="{vid}"]')
    p.click('[data-act="gen"]')
    p.wait_for_function("document.querySelector('#ttsRes .hc-h') && document.querySelector('#ttsRes .hc-h').textContent.indexOf('界面测试设计') >= 0", timeout=30000)
    check(True, "用自己设计的音色生成：试听那里写着它的名字")

    # 复刻：上传录音
    wav = ROOT / "dev" / ".run" / "复刻测试录音.wav"
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes((np.sin(np.arange(24000 * 12) * 0.05) * 6000 * (0.5 + 0.5 * np.sin(np.arange(24000 * 12) / 3000))).astype("<i2").tobytes())
    p.click('[data-tab="clone"]')
    p.wait_for_selector("#bcFile", state="attached")
    p.set_input_files("#bcFile", str(wav))
    p.wait_for_function("TTS.clone && TTS.clone.dur", timeout=8000)
    p.wait_for_selector("#bcWave")
    check("12.0 秒" in p.inner_text("#bcDrop") and p.input_value("#bcName") == "复刻测试录音", "选了录音：显示时长、画出波形、名字先用文件名")
    n_before = p.evaluate("TTS.st.cloud.mine.length")
    p.click('[data-act="clone"]')
    p.wait_for_timeout(400)
    check(p.evaluate("TTS.st.cloud.mine.length") == n_before, "没勾「是我自己的或 AI 生成的声音」：不复刻")
    p.check("#bcOk")
    p.click('[data-act="clone"]')
    p.wait_for_function("(TTS.st.cloud.mine||[]).some(function(v){return v.name==='复刻测试录音' && v.kind==='clone'})", timeout=15000)
    check(True, "复刻好了：出现在「最近复刻的」里")
    p.click('[data-csrc="draft"]')
    check("最近一次生成的配音" in p.inner_text("#ttsVoice"), "也能拿最近生成的配音来复刻（写着是哪一段）")
    p.screenshot(path=f"{OUT}/tts-clone.png")

    # 读音词典
    p.click('[data-tab="dict"]')
    p.click('[data-dictadd="p"]')
    p.locator('[data-dk="p"][data-df="w"]').last.fill("重庆")
    p.locator('[data-dk="p"][data-df="t"]').last.fill("chong2 qing4")
    p.click('[data-act="dictsave"]')
    p.wait_for_timeout(600)
    check(httpx.get(B + "/api/tts").json()["cloud"]["hotfix"]["pronunciation"].get("重庆") == "chong2 qing4", "读音词典：加一条、存好了")
    httpx.put(B + "/api/tts/cloud/hotfix", headers={"X-Agent": "1"}, json={})

    # 删掉自己造的（点两次）
    p.click('[data-tab="lib"]')
    p.click(f'[data-bdel="{vid}"]')
    check("再点一次删除" in p.inner_text(f'[data-bdel="{vid}"]'), "删音色：第一次点变成「再点一次删除」")
    p.click(f'[data-bdel="{vid}"]')
    p.wait_for_function(f"!(TTS.st.cloud.mine||[]).some(function(v){{return v.id==='{vid}'}})", timeout=8000)
    check(True, "再点一次：删掉了（百炼那边也删）")
    for v in httpx.get(B + "/api/tts").json()["cloud"]["mine"]:
        httpx.delete(B + "/api/tts/cloud/voices/" + v["id"], headers={"X-Agent": "1"})
    p.evaluate("ttsLoad().then(ttsRefresh)")
    p.click('[data-tab="lib"]')
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
