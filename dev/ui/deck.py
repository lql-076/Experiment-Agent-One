"""v3.0「指挥舱」点一遍：
主页中间有核心（画布在画）→ 指令条一直在：不用点开直接打字发 → 「现在」里出计划清单、核心变成干活、指令条多出「停下」、发送变「插话」→
插一句话 → 停下 → 回答好了对话自己展开 → 打开 Claude Code 引擎后「交给」里多一行「动手干活用」→
说话：点话筒（假麦克风）→ 听写成字 → 发出去 → 回答念出来（假 Breeze 收到了要念的字）→
配乐窗口：出一首、历史里有、放进工作区 → 设置里 Agent 能力 / 语音 / 配乐三块 → 生图的差分弹窗排出一份清单。
用法：python dev/ui/deck.py 截图文件夹（要先 dev/serve.sh start）"""
import json
import pathlib
import sys

import httpx
from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = pathlib.Path(__file__).resolve().parents[2]
RUN = ROOT / "dev" / ".run"
B = "http://127.0.0.1:8765"
H = {"X-Agent": "1"}
errs, bad = [], []
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082")


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def W_(plan):
    return "【工作区】" + json.dumps(plan, ensure_ascii=False)


def page(b, url, w=1680, h=1000):
    p = b.new_page(viewport={"width": w, "height": h})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(url)
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    p.wait_for_timeout(400)
    return p


c = httpx.Client(base_url=B, headers=H, timeout=30)
c.put("/api/ws", json={"dir": "", "run": True})
c.put("/api/agent/caps", json={"cc": False})
c.put("/api/settings", json={"voiceOn": False, "voiceEngine": "auto", "voiceHands": False, "voiceAuto": True})
SLEEP = "python -c \"import time; time.sleep(%d)\""
PLAN = [{"name": "update_plan", "arguments": {"items": [{"text": "写文案", "status": "done"}, {"text": "做网页动画", "status": "doing"}, {"text": "录成视频", "status": "todo"}]}},
        {"name": "write_file", "arguments": {"path": "deck/a.txt", "content": "x"}}, {"name": "run_command", "arguments": {"command": SLEEP % 5}},
        {"name": "write_file", "arguments": {"path": "deck/b.txt", "content": "y"}}, {"name": "run_command", "arguments": {"command": SLEEP % 40}}]

with sync_playwright() as pw:
    try:
        b = pw.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
    except Exception:
        b = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
    p = page(b, B + "/")
    # ---------- 核心、指令条 ----------
    a = p.evaluate("""() => { var cv = document.getElementById('coreCv'), x = cv.getContext('2d'), d = x.getImageData(0, 0, cv.width, cv.height).data, n = 0;
      for (var i = 3; i < d.length; i += 4 * 97) if (d[i] > 20) n++;
      var bar = document.getElementById('cBar').getBoundingClientRect(), st = document.getElementById('hmSt').getBoundingClientRect();
      return { lit: n, w: cv.width, st: document.getElementById('nwCore').dataset.st, word: coreWord.textContent, barTop: bar.top, barBottom: bar.bottom, h: innerHeight, stBottom: st.bottom,
               focusable: !cIn.disabled, open: document.getElementById('view-chat').classList.contains('open'), stop: cStop.hidden, send: cSend.textContent }; }""")
    check(a["lit"] > 150 and a["w"] > 300 and a["st"] == "idle" and a["word"] == "待命", f"主页中间的核心在画（亮着的点 {a['lit']} 处），闲着写「待命」")
    check(a["focusable"] and not a["open"] and a["barBottom"] <= a["h"] and a["barTop"] >= a["stBottom"] - 2 and a["stop"] and a["send"] == "发送", "指令条一直在最下面、不压着上面的面板；没事的时候只有「发送」")
    p.fill("#cIn", "帮我在工作区做个片头" + W_(PLAN))
    p.press("#cIn", "Enter")
    p.wait_for_function("document.querySelectorAll('.hm-plan li').length >= 3 && document.getElementById('nwCore').dataset.st === 'work'", timeout=20000)
    p.wait_for_timeout(600)
    a = p.evaluate("""() => ({ plan: [].map.call(document.querySelectorAll('.hm-plan li'), function (l) { return l.className + ':' + l.textContent; }), title: document.querySelector('.hm-title').textContent,
      chip: [].map.call(document.querySelectorAll('.hm-chip'), function (x) { return x.textContent; }).join('|'), word: coreWord.textContent, sub: coreSub.textContent, corePlan: CORE.plan.join(','),
      stop: !cStop.hidden, send: cSend.textContent, busy: cBar.classList.contains('busy'), ph: cIn.placeholder, nowStop: !!document.querySelector('#hmNow [data-ev-stop]'), live: hmNow.classList.contains('live'),
      open: document.getElementById('view-chat').classList.contains('open') })""")
    check(a["plan"] == ["pl-done:写文案", "pl-doing:做网页动画", "pl-todo:录成视频"] and "做网页动画" in a["title"] and "计划 1/3" in a["chip"] and a["live"],
          f"没点开对话直接发：「现在」里出了计划清单（{len(a['plan'])} 步），大字是正在做的那步")
    check(a["word"] == "干活中" and "计划 1/3" in a["sub"] and a["corePlan"] == "done,doing,todo", f"核心变成「干活中」，外面一圈是计划（{a['corePlan']}）")
    check(a["stop"] and a["send"] == "插话" and a["busy"] and "改方向" in a["ph"] and a["nowStop"] and not a["open"], "有事在做：指令条多出「停下」，「发送」变「插话」；「现在」里也有「停下」")
    p.screenshot(path=f"{OUT}/deck-working.png")
    p.fill("#cIn", "字调大一点")
    p.press("#cIn", "Enter")
    p.wait_for_timeout(1200)
    p.evaluate("chatOpen()")
    p.wait_for_function("(function () { var e = nowLive(); return e && (e.steps || []).some(function (s) { return s[0] === '你插了一句'; }); })()", timeout=20000)
    a = p.evaluate("({ said: chatLog.innerText.indexOf('字调大一点') >= 0 && chatLog.innerText.indexOf('中途插的一句') >= 0, plan: document.querySelectorAll('#pendPlan li').length, inp: cIn.value })")
    check(a["said"] and a["plan"] == 3 and a["inp"] == "", "插话：发出去了、记在对话里（中途插的一句）；正在做的那条下面也有计划清单")
    p.wait_for_function("(function () { var e = nowLive(); return e && /sleep\\(40\\)/.test(e.result || ''); })()", timeout=30000)
    p.click("#cStop")
    p.wait_for_function("!CHAT.pending && !nowLive()", timeout=20000)
    p.wait_for_timeout(500)
    a = p.evaluate("""() => ({ stop: cStop.hidden, send: cSend.textContent, st: document.getElementById('nwCore').dataset.st, open: document.getElementById('view-chat').classList.contains('open'),
      last: (function () { var l = homeEvs(); return l[l.length - 1]; })() })""")
    check(a["stop"] and a["send"] == "发送" and a["st"] == "idle" and any(s[0] == "停下" for s in a["last"]["steps"]) and "停下了" in (a["last"]["reply"] or ""),
          "点「停下」：马上停住（那条 40 秒的命令没跑完），回一句停在哪；指令条变回去")
    made = [f["name"] for f in a["last"].get("files") or []]
    check(p.evaluate("!!document.querySelector('#hmNow [data-out-open], #hmNow [data-chat-open]')") and any("a.txt" in x or "b.txt" in x for x in made), "停下之前做好的文件留着，「现在」里能打开")
    p.keyboard.press("Escape")
    # ---------- 动手干活用谁 ----------
    check(p.evaluate("(function () { cForce.click(); var r = !document.querySelector('#cRoute [data-engine]'); cForce.click(); return r; })()"), "没开 Claude Code 引擎：「交给」里没有「动手干活用」")
    c.put("/api/agent/caps", json={"cc": True, "cc_cmd": str(RUN / "claude"), "cc_bash": "python,pip,ffmpeg"})
    p.evaluate("capsLoad(true)")
    p.wait_for_function("ccOn()", timeout=10000)
    p.click("#cForce")
    p.click("#cRoute [data-engine='ds']")
    check(p.evaluate("cForce.textContent") == "交给：自动 · DeepSeek 自己做" and p.evaluate("cForce.classList.contains('set')"), "开了以后多一行「动手干活用」：自动 / Claude Code / DeepSeek 自己做")
    p.click("#cRoute [data-engine='cc']")
    p.evaluate("cRoute.hidden = true")
    p.fill("#cIn", "帮我在工作区写个脚本并运行")
    p.press("#cIn", "Enter")
    p.wait_for_function("!CHAT.pending", timeout=40000)
    p.wait_for_timeout(600)
    a = p.evaluate("(function () { var l = homeEvs(), e = l[l.length - 1]; return { eng: e.engine, plan: (e.plan || []).length, chip: document.querySelector('.hm-chip.eng') ? document.querySelector('.hm-chip.eng').textContent : '', meta: chatLog.innerText }; })()")
    check(a["eng"] == "cc" and a["plan"] == 2 and a["chip"] == "Claude Code" and "Claude Code 做的" in a["meta"] and "计划 2/2" in a["meta"], "指定用 Claude Code：这件事标着 Claude Code，它的待办清单就是计划")
    c.put("/api/agent/caps", json={"cc": False})
    p.evaluate("CHAT.engine = 'auto'; chatClose()")
    # ---------- 说话 ----------
    p.click("#cMic")
    p.wait_for_timeout(1500)
    check(p.evaluate("VOICE.mode") == "" and p.evaluate("[].map.call(document.querySelectorAll('.toast'), function (t) { return t.textContent; }).join('|')").find("语音还没开") >= 0, "语音没开：点话筒告诉你去哪开")
    c.put("/api/settings", json={"voiceOn": True})
    (RUN / "fake_asr.txt").write_text("今天有什么安排", "utf-8")
    p.evaluate("VOICE_HUSH = 0.35; voiceLoad(true)")
    p.wait_for_function("voiceReady()", timeout=10000)
    check(p.evaluate("coreSub.textContent") == "点一下核心说话", "语音开了：核心下面写「点一下核心说话」")
    p.click("#coreHit")
    p.wait_for_function("VOICE.mode === 'listen'", timeout=10000)
    a = p.evaluate("({ rec: cBar.classList.contains('rec'), mic: cMic.getAttribute('aria-pressed'), word: coreWord.textContent, st: document.getElementById('nwCore').dataset.st })")
    check(a["rec"] and a["mic"] == "true" and a["word"] == "在听" and a["st"] == "listen", "点核心：开始听，指令条变成波形，核心写「在听」")
    p.wait_for_function("VOICE.mode === 'speak' || (VOICE.mode === '' && !CHAT.pending && (function () { var l = homeEvs(); return l.length && l[l.length - 1].src === '语音'; })())", timeout=60000)
    p.wait_for_function("!CHAT.pending && VOICE.mode !== 'think'", timeout=30000)
    p.wait_for_timeout(1500)
    brz = httpx.get("http://127.0.0.1:8093/__last", timeout=10).json()["last"] or {}
    a = p.evaluate("(function () { var l = homeEvs(), e = l[l.length - 1]; return { src: e.src, text: e.text, mode: VOICE.mode, said: VOICE.play ? VOICE.play.n : -1, open: document.getElementById('view-chat').classList.contains('open') }; })()")
    check(a["src"] == "语音" and a["text"] == "今天有什么安排", f"说完停一下自动收住 → 听写成字 → 当成一条消息发出去（标「语音」：{a['text']}）")
    check(bool(brz.get("text")) and "http" not in brz.get("text", ""), f"回答念出来了：语音服务收到了要念的字（{(brz.get('text') or '')[:24]}…）")
    p.wait_for_function("VOICE.mode === ''", timeout=60000)
    check(p.evaluate("document.getElementById('nwCore').dataset.st") == "idle" and not a["open"], "念完回到待命；说话问的不弹对话（听就行）")
    c.put("/api/settings", json={"voiceOn": False})
    p.screenshot(path=f"{OUT}/deck-home.png")
    p.close()

    # ---------- 配乐窗口 ----------
    p = page(b, B + "/?tool=bgm", 1440, 880)
    p.wait_for_selector("#bgPrompt")
    n0 = p.evaluate("(BGM.st.recent || []).length")
    p.click("[data-bgm-pre='1']")
    check("钢琴" in p.evaluate("bgPrompt.value"), "配乐：点一个现成的风格，描述填进去")
    p.evaluate("bgSec.value = 15; bgSec.dispatchEvent(new Event('input', { bubbles: true }))")
    p.click("[data-bgm-gen]")
    p.wait_for_function(f"BGM.st && (!BGM.st.job || BGM.st.job.st !== 'run') && (BGM.st.recent || []).length > {n0}", timeout=60000)
    p.wait_for_timeout(800)
    a = p.evaluate("({ row: document.querySelectorAll('.bg-row').length, name: (document.querySelector('.bg-t') || {}).textContent, wave: !!document.getElementById('bgWave'), dur: BGM.st.recent[0].duration })")
    check(a["row"] > n0 and a["wave"] and a["dur"] > 5 and a["name"].endswith(".wav"), f"出一首：出好了在右边历史里、中间能看波形能播（{a['name']}）")
    p.click("[data-bgm-tows]")
    p.wait_for_timeout(1200)
    check((ROOT / "工作区" / "素材" / "配乐" / a["name"]).exists(), "「放进工作区」：复制进 素材\\配乐\\")
    p.screenshot(path=f"{OUT}/deck-bgm.png")
    p.close()

    # ---------- 设置里的三块 ----------
    p = page(b, B + "/?tool=settings", 1440, 880)
    for sec, need in (("agent", "Claude Code 引擎"), ("voice", "听（你说的话变成字）"), ("bgm", "ACE-Step 1.5")):
        p.evaluate(f"goSec('{sec}')")
        p.wait_for_function(f"document.getElementById('view-settings').innerText.indexOf('{need}') >= 0 && document.getElementById('view-settings').innerText.indexOf('正在读取') < 0", timeout=10000)
        p.screenshot(path=f"{OUT}/deck-set-{sec}.png")
    p.evaluate("goSec('agent')")
    p.wait_for_selector("[data-cap='image']")
    p.click("[data-cap='image']")
    p.wait_for_timeout(1000)
    on = c.get("/api/agent/caps").json()["caps"]["image"]
    p.click("[data-cap='image']")
    p.wait_for_timeout(1000)
    check(on and not c.get("/api/agent/caps").json()["caps"]["image"] and p.evaluate("document.querySelectorAll('#capsBox .cap-row').length") >= 4, "设置 › Agent 能力：开关走自己的接口（开了又关上）；列着技能和工具箱")
    p.close()

    # ---------- 生图：差分 ----------
    c.post("/api/img/clear")
    p = page(b, B + "/?tool=img", 1440, 880)
    p.wait_for_timeout(800)
    p.evaluate("imgTab('batch', true)")
    p.click("[data-act='diff']")
    p.wait_for_selector("#fgDiffName")
    p.set_input_files("#fgDiffImg", {"name": "定稿.png", "mimeType": "image/png", "buffer": PNG})
    p.wait_for_selector("#fgDiffPv img")
    p.fill("#fgDiffName", "白页_Q版")
    p.click("#fgBox [data-act='diffok']")
    p.wait_for_timeout(800)
    check(p.evaluate("!!document.getElementById('fgBox')") and "外观写全" in p.evaluate("[].map.call(document.querySelectorAll('.toast'), function (t) { return t.textContent; }).join('|')"), "差分：外观没写就不排，告诉你为什么")
    p.fill("#fgDiffLook", "银白色短发、蓝色眼睛、白色连帽衫、Q 版二头身、平涂")
    p.fill("#fgDiffMore", "歪头：头向左歪 15 度")
    p.click("#fgBox [data-act='diffok']")
    p.wait_for_function("!document.getElementById('fgBox') && IMG.st.board && IMG.st.board.items.length === 5", timeout=15000)
    a = p.evaluate("({ files: IMG.st.board.items.map(function (x) { return x.file; }), refs: IMG.st.board.items.every(function (x) { return x.refs === 1; }), tag: document.querySelector('#fgQl .ftg').textContent })")
    check(a["files"][0] == "白页_Q版_闭嘴.png" and "白页_Q版_歪头.png" in a["files"] and a["refs"] and "参考 1" in a["tag"], f"差分弹窗：放定稿图、写外观、选几种 → 排成清单（{len(a['files'])} 张，每张带参考图）")
    p.click("#fgQl .fg-r")
    p.wait_for_selector(".fg-irefs")
    check(p.evaluate("!!document.querySelector('.fg-irefs img') && !!document.getElementById('fgTows')"), "点开一条看得到它挂的参考图；出好的能「放进工作区」")
    p.screenshot(path=f"{OUT}/deck-diff.png")
    c.post("/api/img/clear")
    p.close()
    b.close()
c.post("/api/tts/off")
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
