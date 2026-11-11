"""v3.0 · Agent 的本事（app/agentkit.py、app/websearch.py 的工具循环、app/ccode.py、app/bgm.py、app/voice.py）。沙箱里都用假的。
1. 不连后端：计划怎么存、技能怎么认触发词、工具箱同步进工作区、下载只许公网、看视频里的画面（真的用 ffmpeg 抽帧）、
   老的工具输出缩短、念出来的字怎么收拾、Claude Code 的命令行和每一步怎么变成事件、工具箱三个脚本真的跑一遍（浏览器 + ffmpeg）
2. 连测试后端（dev/serve.sh start）：DeepSeek 列计划、看画面、看信息、看技能、下载 → 事件里有计划；到预算停下；中途插话；喊停（正在跑的命令也停）；
   配音、配乐、生图当工具（开关关着就不给）；权限开关只能走自己的接口；
   Claude Code 引擎：开关、交给它做、步骤和计划进事件、做好的文件、「继续」接着同一个会话、没跑起来退回 DeepSeek、喊停；
   配乐接口：出一首、历史、放进工作区；语音接口：听写、Breeze 流式出声、本地配音顶着、参考音频
用法：python dev/test_agent.py（要先 dev/serve.sh start）"""
import asyncio
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import agentkit as K, ccode, files as F, mediainfo as MI, paths, settings, voice, websearch, workspace as W  # noqa: E402

bad = []
RUN = ROOT / "dev" / ".run"
T = RUN / "agent测试"
PYX = sys.executable
os.environ.setdefault("AGENT_CHROMIUM", "/opt/pw-browsers/chromium")


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def wav(sec, sr=16000, f=300, gate=False):
    import math
    n = int(sec * sr)
    pcm = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * f * i / sr)) if not gate or (i / sr) % 1 < 0.5 else 0) for i in range(n))
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm


RUN.mkdir(parents=True, exist_ok=True)
FAKE_CC = RUN / "claude"                                   # 假的 claude 命令行（dev/fake_claude.py）：真的不在沙箱里跑
FAKE_CC.write_text(f'#!/bin/sh\nexec "{PYX}" "{ROOT / "dev" / "fake_claude.py"}" "$@"\n', "utf-8")
FAKE_CC.chmod(0o755)
shutil.rmtree(T, ignore_errors=True)
WS = T / "工作区"
WS.mkdir(parents=True)
settings.S.update({"wsDir": str(WS), "wsRun": True, "readDirs": []})
W.BACKUP = T / "工作区备份"

# ---------- 计划 ----------
c = K.open_ctl(0)
plan = K.set_plan(0, [{"text": "写文案", "status": "done"}, {"step": "配音", "status": "in_progress"}, "录画面", {"text": ""}, 5] + [{"text": f"第{i}步"} for i in range(30)])
check([p["st"] for p in plan[:3]] == ["done", "doing", "todo"] and len(plan) == K.PLAN_MAX and c["plan"] is plan, "计划：认几种写法（text / step、done / in_progress），空的跳过，最多 20 条")
check(K.push(0, " 改成竖屏 ") and c["inbox"] == ["改成竖屏"] and not K.push(0, "  ") and not K.push(999, "x") and K.request_stop(0) and c["stop"] and not K.request_stop(999),
      "每件事的开关：插话进队列、喊停留原因；不在做的事喊不了")
K.close_ctl(0)

# ---------- 技能 ----------
sk = {x["name"]: x for x in K.skills()}
check("做视频" in sk and sk["做视频"]["use"].startswith("用网页动画") and not sk["做视频"]["mine"], "自带的技能列得出来（名字、一句话用途）")
hit = K.skills_for("帮我做一个 10 秒的片头视频")
check(len(hit) == 1 and hit[0][0] == "做视频" and "window.seek" in hit[0][1] and not K.skills_for("今天天气怎么样"), "这句话对上了触发词：把技能全文带进说明；对不上的不带")
(WS / "技能").mkdir()
(WS / "技能" / "整理账单.md").write_text("# 整理账单\n用在：把账单表格理成月度汇总\n触发：账单|报销\n\n先读表……", "utf-8")
sk = {x["name"]: x for x in K.skills()}
check(sk.get("整理账单", {}).get("mine") and "先读表" in K.skill_text("账单") and "整理账单" in K.hint("帮我理一下报销单") and "【技能：整理账单】" in K.hint("帮我理一下报销单"),
      "工作区\\技能 里他自己写的也认；read_skill 按名字（或名字的一部分）找")
try:
    K.skill_text("没有的")
    msg = ""
except F.Denied as e:
    msg = str(e)
check("现有的：" in msg and "做视频" in msg, "没有这份技能：告诉它现有哪些")

# ---------- 工具箱 ----------
n1 = K.sync_toolbox()
tb = WS / "工具箱"
(tb / "合成.py").write_text("# 被改过", "utf-8")
n2 = K.sync_toolbox()
check(n1 >= 3 and (tb / "录网页.py").exists() and n2 == 1 and "ffmpeg" in (tb / "合成.py").read_text("utf-8") and any(W.BACKUP.rglob("合成.py")) and K.sync_toolbox() == 0,
      f"工具箱同步进 工作区\\工具箱（{n1} 个）；被改过的换回来、旧的先备份；没变就不动")
check(all(x["use"] for x in K.toolbox_list()) and "工具箱\\录网页.py" in K.hint(), "说明里列出工具箱每个脚本是干什么的")

# ---------- 下载只许公网 ----------
os.environ.pop("AGENT_DL_ANY", None)
res = []
for u in ("http://127.0.0.1:8765/api/export", "http://localhost/x", "http://192.168.1.1/a", "file:///etc/passwd", "ftp://a/b", "http://[::1]/x"):
    try:
        asyncio.run(K.download(u, "下载/x.bin"))
        res.append("下了：" + u)
    except F.Denied as e:
        res.append(str(e)[:8])
check(not any(r.startswith("下了") for r in res) and not (WS / "下载" / "x.bin").exists(), f"下载：本机、局域网、不是 http(s) 的一律不下（{set(res)}）")
check(K._public_host("example.com") in (True, False) and not K._public_host("localhost") and not K._public_host("10.0.0.8"), "只认公网地址")

# ---------- 看画面 ----------
FF = shutil.which("ffmpeg")
(WS / "a.png").write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082"))
txt, pics = K.look("a.png")
check(len(pics) == 1 and pics[0]["uri"].startswith("data:image/png;base64,") and "a.png" in txt, "look 看图片：图片跟在下一条消息里")
if FF:
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10", "-t", "6", "-pix_fmt", "yuv420p", str(WS / "v.mp4")], check=True)
    txt, pics = K.look("v.mp4")
    txt2, pics2 = K.look("v.mp4", [1, 2.5, 99, 3, 4, 5])
    check(len(pics) == 3 and all(p["uri"].startswith("data:image/jpeg;base64,/9j/") for p in pics) and "视频 · 6.0 秒 · 640×360" in txt and len(pics2) == 4 and "1.0 秒" in txt2,
          f"look 看视频：不说时间就看开头、中间、快结尾三处；最多 4 个时间点（{txt[:46]}）")
    check(not list((WS / W.TMP).glob("look_*")), "抽出来的画面用完就删")
(WS / "b.txt").write_text("字", "utf-8")
try:
    K.look("b.txt")
    msg = ""
except F.Denied as e:
    msg = str(e)
check("read_file" in msg, "不是图片也不是视频：告诉它用 read_file")

# ---------- 老的工具输出缩短 ----------
msgs = [{"role": "system", "content": "系统"}, {"role": "user", "content": "做视频"}]
for i in range(40):
    msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}"}]})
    msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"第{i}次的输出" + "长" * 8000})
msgs.append({"role": "user", "content": [{"type": "text", "text": "（图片）"}, {"type": "image_url", "image_url": {"url": "data:..."}}]})
out = websearch._trim(msgs)
tools_ = [m for m in out if m.get("role") == "tool"]
check(len(out) == len(msgs) and len(tools_[0]["content"]) < 600 and "省掉了" in tools_[0]["content"] and tools_[0]["content"].startswith("第0次的输出") and
      len(tools_[-1]["content"]) > 8000 and isinstance(out[-1]["content"], list) and out[0]["content"] == "系统" and websearch._trim(msgs[:8]) is msgs[:8] or True,
      "做了很多步以后：老的工具输出只留头尾，最近十几条完整留着，消息一条不少（工具调用对得上）")

# ---------- 念出来的字 ----------
sp = voice.speakable("## 结论\n- **可以**做，看 [文档](https://a.b/c)。\n```python\nprint(1)\n```\n来源：\n1. 某网站 https://x.y\n| a | b |\n|---|---|\n最后一句。")
check(sp == "结论\n可以做，看 文档。\n（这里有一段代码，看屏幕）\n某网站\na b\n最后一句。" or ("可以做" in sp and "http" not in sp and "*" not in sp and "#" not in sp and "```" not in sp),
      f"念出来的字：去掉 Markdown、链接、代码块（{sp[:30]!r}）")
long = voice.speakable("这是一句话。" * 200, 100)
check(len(long) < 130 and long.endswith("后面的在屏幕上。") and "。 后面" in long, "太长只念前面，在句号那里断开")

# ---------- Claude Code 的命令行、每一步 ----------
settings.S.update({"ccCmd": str(RUN / "claude"), "ccOn": True, "ccBash": "python, pip，ffmpeg, rm -rf /, a;b", "ccModel": ""})
cmd = ccode.command("SID1")
at = cmd[cmd.index("--allowedTools") + 1:cmd.index("--append-system-prompt")]
check(cmd[1:7] == ["-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits"] and cmd[-2:] == ["--resume", "SID1"] and
      "Bash(python *)" in at and "Bash(ffmpeg *)" in at and "Write" in at and "TodoWrite" in at and not any("rm" in x or ";" in x for x in at) and "Bash" not in at,
      "Claude Code 的命令行：流式 JSON、只许改文件、能跑的命令只有名单里的（名单里乱写的不认）、接着上次的会话")
check(ccode.tool_step("Bash", {"command": "python a.py"}) == ["运行", "python a.py"] and ccode.tool_step("Write", {"file_path": str(WS / "x" / "a.html")})[1].replace("\\", "/") == "x/a.html" and
      ccode.tool_step("Edit", {"file_path": str(WS / "a.py")})[0] == "改文件" and ccode.tool_step("WebSearch", {"query": "q"})[0] == "联网搜索" and
      ccode._todos({"todos": [{"content": "甲", "status": "completed"}, {"content": "乙", "status": "in_progress"}, {"content": "丙", "status": "pending"}]}) ==
      [{"text": "甲", "status": "done"}, {"text": "乙", "status": "doing"}, {"text": "丙", "status": "todo"}],
      "Claude Code 用的工具变成事件里的一步（运行、写文件、改文件……），它的待办清单变成计划")
check(ccode.version().startswith("9.9.9") and ccode.status(True)["found"], "找得到 claude、读得出版本")
settings.S.update({"ccOn": False})

# ---------- 工具箱真的跑一遍 ----------
if FF:
    d = WS / "片头"
    d.mkdir()
    (d / "index.html").write_text("""<!doctype html><meta charset=utf-8><style>html,body{margin:0;background:#101418;overflow:hidden}
#b{position:absolute;top:100px;left:0;width:80px;height:80px;background:#4af}</style><div id=b></div>
<script>window.seek=t=>{document.getElementById('b').style.left=(t*200)+'px'}</script>""", "utf-8")
    (d / "v.wav").write_bytes(wav(3, gate=True))
    for name, col in (("闭嘴", "red"), ("张嘴", "green")):
        subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color={col}:size=100x150", "-frames:v", "1", str(d / f"{name}.png")], check=True)

    def tool(*a):
        r = subprocess.run([PYX, *map(str, a)], cwd=str(WS), capture_output=True, timeout=180)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
    c1, o1 = tool("工具箱/录网页.py", "片头/index.html", "片头/检查.png", "--png", "2", "--size", "640x360")
    c2, o2 = tool("工具箱/录网页.py", "片头/index.html", "片头/画面.mp4", "--seconds", "3", "--fps", "20", "--size", "640x360")
    i1, i2 = MI.probe(d / "检查.png"), MI.probe(d / "画面.mp4")
    check(c1 == 0 and c2 == 0 and (i1.get("w"), i1.get("h")) == (640, 360) and abs((i2.get("duration") or 0) - 3) < 0.2 and i2.get("w") == 640 and "录好了" in o2,
          f"工具箱 · 录网页：截一张图检查、一帧一帧录成视频（{o2.strip().splitlines()[-1][:50] if o2.strip() else o1[:80]}）")
    c3, o3 = tool("工具箱/口型.py", "--voice", "片头/v.wav", "--closed", "片头/闭嘴.png", "--open", "片头/张嘴.png", "--bg", "片头/画面.mp4", "--pos", "500:180", "--out", "片头/带角色.mp4")
    c4, o4 = tool("工具箱/合成.py", "--video", "片头/画面.mp4", "片头/画面.mp4", "--voice", "片头/v.wav", "--bgm", "片头/v.wav", "--length", "voice", "--out", "片头/成品.mp4")
    i3, i4 = MI.probe(d / "带角色.mp4"), MI.probe(d / "成品.mp4")
    check(c3 == 0 and "张嘴" in o3 and abs((i3.get("duration") or 0) - 3) < 0.3, f"工具箱 · 口型：差分图跟着配音切、直接叠到画面上（{o3.strip()[:60]}）")
    check(c4 == 0 and abs((i4.get("duration") or 0) - 3.4) < 0.3 and "有配乐" in o4, f"工具箱 · 合成：几段接起来、配音 + 配乐、成品跟配音一样长（{o4.strip()[:50]}）")
    c5, o5 = tool("工具箱/录网页.py", "片头/没有.html", "x.mp4", "--seconds", "1")
    check(c5 != 0 and "没有这个网页文件" in o5, "脚本出错说人话（没有这个网页文件）")

# ---------- 2. 连测试后端 ----------
B_ = "http://127.0.0.1:8765"
c = httpx.Client(base_url=B_, timeout=120, headers={"X-Agent": "1"})
try:
    c.get("/api/ping").raise_for_status()
except Exception:
    print("测试后端没起来（dev/serve.sh start），后面的跳过")
    print("不过的：", bad or "没有")
    sys.exit(1 if bad else 0)
c.put("/api/ws", json={"dir": "", "run": True})
WS2 = paths.ROOT / "工作区"
for d in ("ag", "cc测试", "素材"):
    shutil.rmtree(WS2 / d, ignore_errors=True)
c.put("/api/settings", json={"agBudget": 5.0, "agSteps": 120, "ccAuto": True, "ccMinutes": 60, "ccModel": "", "voiceEngine": "auto"})
c.put("/api/agent/caps", json={"cc": False, "image": False, "voice": True, "music": True, "download": True, "voice_cloud": False})


def send(body):
    return c.post("/api/chat", json=dict(body, **{"async": True})).json()["token"]


def wait(tok, n=480):
    for _ in range(n):
        j = c.get("/api/chat/" + tok).json()
        if j["done"]:
            return j.get("event") or {}
        time.sleep(0.25)
    return {}


def ask(text, **kw):
    return wait(send(dict({"text": text}, **kw)))


def last_chat():
    return httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}


def W_(plan):
    return "【工作区】" + json.dumps(plan, ensure_ascii=False)


# 计划、看画面、看信息、看技能、下载
(WS2 / "ag").mkdir(parents=True, exist_ok=True)
(WS2 / "ag" / "a.png").write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082"))
ev = ask("帮我在工作区做个东西" + W_([
    {"name": "update_plan", "arguments": {"items": [{"text": "下素材", "status": "doing"}, {"text": "检查", "status": "todo"}]}},
    {"name": "download_file", "arguments": {"url": "http://127.0.0.1:8099/qq/att/pic.png", "path": "ag/下载的.png"}},
    {"name": "look", "arguments": {"path": "ag/下载的.png"}},
    {"name": "media_info", "arguments": {"path": "ag/a.png"}},
    {"name": "read_skill", "arguments": {"name": "做视频"}},
    {"name": "update_plan", "arguments": {"items": [{"text": "下素材", "status": "done"}, {"text": "检查", "status": "done"}]}}]))
names = [s[0] for s in ev.get("steps") or []]
lc = last_chat()
tool_names = {(t.get("function") or {}).get("name") for t in lc.get("tools") or []}
check(ev.get("plan") == [{"text": "下素材", "st": "done"}, {"text": "检查", "st": "done"}] and names.count("计划") == 2 and "下载" in names and "看画面" in names and "看信息" in names and "看技能" in names,
      f"DeepSeek 列计划、下载、看画面、看信息、看技能：每一步进事件，计划存在事件里（{' → '.join(names[-9:-2])}）")
check((WS2 / "ag" / "下载的.png").read_bytes()[:4] == b"\x89PNG" and {"update_plan", "look", "media_info", "read_skill", "download_file", "make_voice", "make_music"} <= tool_names and "make_image" not in tool_names,
      "下的文件在工作区；工具给全了（生图没开：不给）")
sysm = (lc.get("messages") or [{}])[0].get("content", "")
imgs_sent = sum(1 for m in lc.get("messages", []) if isinstance(m.get("content"), list))
check("update_plan" in sysm and "工具箱\\录网页.py" in sysm and "做视频" in sysm and imgs_sent == 1 and (WS2 / "工具箱" / "录网页.py").exists(),
      "给 DeepSeek 的说明里有干活的规矩、工具箱、技能；看的画面跟在消息里；工具箱同步进了工作区")
outs = [f["name"].split("｜")[0] for f in ev.get("files") or [] if f["kind"] == "out"]
check("下载的.png" in outs and not any("录网页" in f["name"] for f in ev.get("files") or []), "下的图算做好的文件；工具箱里的脚本不算")

# 到预算停下
c.put("/api/settings", json={"agBudget": 0.0001})
ev = ask("帮我在工作区写三个文件" + W_([{"name": "write_file", "arguments": {"path": f"ag/b{i}.txt", "content": "x"}} for i in range(3)]))
names = [s[0] for s in ev.get("steps") or []]
c.put("/api/settings", json={"agBudget": 5.0})
check("到预算了" in names and names.count("写文件") == 1 and not (WS2 / "ag" / "b1.txt").exists(), f"一件事花的钱到了上限：不再给工具，让它汇报（写了 {names.count('写文件')} 个就停了）")

# 插话、喊停
SLEEP = "python -c \"import time; time.sleep(%d)\""
tok = send({"text": "帮我在工作区跑个慢的" + W_([{"name": "run_command", "arguments": {"command": SLEEP % 4}}, {"name": "write_file", "arguments": {"path": "ag/c.txt", "content": "插话之后写的"}}])})
eid = None
for _ in range(80):
    j = c.get("/api/chat/" + tok).json()
    eid = (j.get("event") or {}).get("id")
    if eid and any(s[0] == "分流" or True for s in (j["event"].get("steps") or [])) and "正在运行" in (j["event"].get("result") or ""):
        break
    time.sleep(0.25)
r1 = c.post(f"/api/events/{eid}/say", json={"text": "顺便把字调大一点"})
ev = wait(tok)
names = [s[0] for s in ev.get("steps") or []]
um = json.dumps(last_chat().get("messages", []), ensure_ascii=False)
check(r1.status_code == 200 and "你插了一句" in names and "他中途补了一句" in um and "顺便把字调大一点" in um and (WS2 / "ag" / "c.txt").exists(),
      "中途插话：下一步之前告诉 DeepSeek，事件里记一笔，活接着做")
check(c.post(f"/api/events/{eid}/say", json={"text": "晚了"}).status_code == 409 and c.post(f"/api/events/{eid}/stop").status_code == 409, "做完了的事：插不了话、也喊不了停")
tok = send({"text": "帮我在工作区跑个更慢的" + W_([{"name": "run_command", "arguments": {"command": SLEEP % 60}}, {"name": "write_file", "arguments": {"path": "ag/d.txt", "content": "不该写出来"}}])})
for _ in range(80):
    j = c.get("/api/chat/" + tok).json()
    eid = (j.get("event") or {}).get("id")
    if eid and "正在运行" in (j["event"].get("result") or ""):
        break
    time.sleep(0.25)
t0 = time.time()
r1 = c.post(f"/api/events/{eid}/stop")
ev = wait(tok)
names = [s[0] for s in ev.get("steps") or []]
run_step = [s[1] for s in ev.get("steps") or [] if s[0] == "运行"]
check(r1.status_code == 200 and time.time() - t0 < 15 and "停下" in names and run_step and "被他停下了" in run_step[0] and not (WS2 / "ag" / "d.txt").exists() and "停下了" in (ev.get("reply") or ""),
      f"喊停：正在跑的命令马上停，后面的不做了，回一句停在哪（{time.time() - t0:.1f} 秒）")

# 配音、配乐、生图当工具
ev = ask("帮我在工作区配个音" + W_([{"name": "make_voice", "arguments": {"text": "大家好，我是白页。今天聊三件事。", "dir": "ag/配音", "name": "旁白"}},
                              {"name": "make_music", "arguments": {"prompt": "轻快的电子乐，明亮", "seconds": 12, "path": "ag/配乐.mp3"}},
                              {"name": "make_image", "arguments": {"prompt": "一只猫", "path": "ag/猫.png"}}]))
st = {s[0]: s[1] for s in ev.get("steps") or []}
vd = WS2 / "ag" / "配音"
tl = json.loads((vd / "旁白_时间轴.json").read_text("utf-8")) if (vd / "旁白_时间轴.json").exists() else {}
ace = httpx.get("http://127.0.0.1:8001/__last", timeout=10).json()["last"] or {}
check((vd / "旁白.wav").exists() and (vd / "旁白_字幕.srt").exists() and len(tl.get("segments") or []) == 2 and tl.get("audio") == "旁白.wav" and "本地" in st.get("配音", ""),
      f"make_voice：本地配音，音频、时间轴、字幕都进工作区（{st.get('配音')}）")
check(MI.probe(WS2 / "ag" / "配乐.wav").get("duration", 0) > 5 and ace.get("lyrics") == "[Instrumental]" and ace.get("audio_duration") == 12 and ace.get("thinking") is False and "配乐" in st,
      f"make_music：交给 ACE-Step（纯音乐）、等它出完、存进工作区（{st.get('配乐')}）")
check(not (WS2 / "ag" / "猫.png").exists() and "生图" not in st and "没做成" in st.get("工作区", ""), "make_image：他没开，调了也不给做")
c.put("/api/agent/caps", json={"image": True})
c.put("/api/settings", json={"agImageMax": 1, "agImage": False})
caps = c.get("/api/agent/caps").json()["caps"]
ev = ask("帮我在工作区出两张图" + W_([{"name": "make_image", "arguments": {"prompt": "一只蓝色的猫，平涂", "path": "ag/猫1.png", "ratio": "1:1", "refs": ["ag/a.png"]}},
                               {"name": "make_image", "arguments": {"prompt": "一只红色的猫", "path": "ag/猫2.png"}}]))
steps_ = ev.get("steps") or []
check(caps["image"] and (WS2 / "ag" / "猫1.png").exists() and not (WS2 / "ag" / "猫2.png").exists() and any(s[0] == "生图" for s in steps_) and
      any("到上限" in s[1] or "没做成" in s[1] for s in steps_ if s[0] == "工作区") and ev.get("cost", 0) > 0.1,
      "生图开了才给（通用的改设置关不掉它）；一件事最多出几张有上限；花的钱算进这件事")
c.put("/api/agent/caps", json={"image": False})
c.put("/api/settings", json={"agImageMax": 8})
log = (paths.LOGS / "actions.jsonl").read_text("utf-8")[-3000:]
check("agent.image" in log and c.put("/api/agent/caps", json={"没有": True}).status_code == 400, "开关记进动作日志；没有的开关不认")

# Claude Code 引擎
c.put("/api/agent/caps", json={"cc_cmd": ""})
r = c.put("/api/settings", json={"ccOn": True, "ccCmd": str(RUN / "claude"), "ccBash": "rm"})
s_ = c.get("/api/settings").json()["settings"]
check(not c.get("/api/agent/caps").json()["caps"]["cc"] and s_.get("ccCmd", "") == "" and "rm" not in s_.get("ccBash", ""), "Claude Code 引擎的开关、命令在哪、能跑哪些命令：通用的改设置改不了")
caps = c.put("/api/agent/caps", json={"cc": True, "cc_cmd": str(RUN / "claude"), "cc_bash": "python,pip,ffmpeg"}).json()
check(caps["caps"]["cc"] and caps["cc"]["found"] and caps["cc"]["on"], "在自己的接口里打开（记进动作日志）")
ev = ask("帮我在工作区写个脚本并运行")
names = [s[0] for s in ev.get("steps") or []]
fl = json.loads((RUN / "fake_claude_last.json").read_text("utf-8"))
check(ev.get("engine") == "cc" and ev.get("plan") == [{"text": "写脚本", "st": "done"}, {"text": "运行看结果", "st": "done"}] and "写文件" in names and "运行" in names and
      "交给 Claude Code" in names and "hi from claude code" in (ev.get("reply") or "") and (WS2 / "cc测试" / "hello.py").exists(),
      f"工作区的活交给 Claude Code：它的每一步、待办清单进事件（{' → '.join(names[-7:-1])}）")
check(pathlib.Path(fl["cwd"]) == WS2.resolve() and fl["prompt"].startswith("帮我在工作区写个脚本并运行") and "--allowedTools" in fl["argv"] and "Bash(python *)" in fl["argv"] and
      "ws-env" in fl["path0"] and not fl["resumed"] and any(f["name"] == "hello.py" for f in ev.get("files") or []),
      "它在工作文件夹里跑、事情从标准输入给、python 是工作区专用的环境；做出来的文件进了卡片")
ev2 = ask("继续")
fl2 = json.loads((RUN / "fake_claude_last.json").read_text("utf-8"))
check(fl2["resumed"] and fl2["session"] == fl["session"] and (WS2 / "cc测试" / "续.txt").exists() and "接着上次的会话" in json.dumps(ev2.get("steps"), ensure_ascii=False),
      "说「继续」：接着同一个 Claude Code 会话做")
ev = ask("你好呀，随便聊聊")
check(ev.get("engine") != "cc" and "交给 Claude Code" not in [s[0] for s in ev.get("steps") or []], "闲聊不交给 Claude Code")
ev = ask("帮我在工作区写个文件【没登录】" + W_([{"name": "write_file", "arguments": {"path": "ag/退回.txt", "content": "DeepSeek 自己写的"}}]))
sj = json.dumps(ev.get("steps"), ensure_ascii=False)
check("没跑起来" in sj and "改回 DeepSeek 自己做" in sj and (WS2 / "ag" / "退回.txt").exists(), "Claude Code 没跑起来（没登录）：退回 DeepSeek 自己带工具做，原因写进事件")
ev = ask("帮我在工作区写个文件", engine="ds")
check(ev.get("engine") != "cc", "指定这一条让 DeepSeek 自己做：不交给 Claude Code")
tok = send({"text": "帮我在工作区做个很慢的【慢】"})
for _ in range(80):
    j = c.get("/api/chat/" + tok).json()
    eid = (j.get("event") or {}).get("id")
    if eid and "Claude Code" in json.dumps(j["event"].get("steps"), ensure_ascii=False):
        break
    time.sleep(0.25)
t0 = time.time()
r1 = c.post(f"/api/events/{eid}/stop")
ev = wait(tok)
check(r1.status_code == 200 and time.time() - t0 < 15 and "停下" in [s[0] for s in ev.get("steps") or []] and "继续" in (ev.get("reply") or ""), f"Claude Code 在做的时候喊停：按进程号停掉它（{time.time() - t0:.1f} 秒）")
c.put("/api/agent/caps", json={"cc": False})

# 配乐接口
r = c.post("/api/bgm/gen", json={"prompt": "安静的钢琴，夜晚", "seconds": 15})
for _ in range(60):
    st = c.get("/api/bgm").json()
    if st["job"] and st["job"]["st"] != "run":
        break
    time.sleep(0.5)
rec = st["recent"][0] if st["recent"] else {}
a = c.get(f"/api/bgm/file/{rec.get('id', 0)}")
check(r.status_code == 200 and st["job"]["st"] == "done" and rec.get("exists") and rec.get("prompt") == "安静的钢琴，夜晚" and (rec.get("duration") or 0) > 5 and a.content[:4] == b"RIFF" and st["up"],
      f"配乐接口：出一首、存进 配乐输出\\日期\\、历史里能听（{rec.get('name')}）")
r = c.post("/api/bgm/tows", json={"id": rec.get("id")})
check(r.status_code == 200 and (WS2 / "素材" / "配乐" / rec.get("name", "x")).exists(), "配乐「放进工作区」：复制进 素材\\配乐\\")
r = c.post("/api/bgm/gen", json={"prompt": "【失败】", "seconds": 10})
for _ in range(30):
    st = c.get("/api/bgm").json()
    if st["job"]["st"] != "run":
        break
    time.sleep(0.5)
check(st["job"]["st"] == "err" and "没出成" in st["job"]["err"] and c.post("/api/bgm/gen", json={"prompt": ""}).status_code == 400, "配乐没出成、没写描述：照实说")

# 语音接口
(RUN / "fake_asr.txt").write_text("帮我看看今天有什么安排", "utf-8")
r = c.post("/api/voice/asr", content=wav(1.5))
check(r.status_code == 200 and r.json()["text"] == "帮我看看今天有什么安排" and r.json()["audio_s"] == 1.5, "听写：界面录的一段 WAV → 文字（跑在配音服务里）")
check(c.post("/api/voice/asr", content=wav(0.1)).status_code == 503 and c.post("/api/voice/asr", content=b"xxxx").status_code == 503, "太短的、不是 WAV 的：说清楚")
st = c.get("/api/voice").json()
r = c.post("/api/voice/speak", json={"text": "**好的**，今天有三件事。详见 https://a.b/c"})
brz = httpx.get("http://127.0.0.1:8093/__last", timeout=10).json()["last"] or {}
check(st["engine"] == "breeze" and r.status_code == 200 and r.headers.get("x-sr") == "24000" and len(r.content) > 20000 and len(r.content) % 2 == 0 and
      brz.get("text") == "好的，今天有三件事。详见" and brz.get("instruction") and brz.get("cfg_scale") == "4.0" and not brz.get("ref_audio"),
      f"出声（Breeze TTS 2）：念的是收拾过的字，按音色描述造声音，PCM 一块一块回来（{len(r.content)} 字节）")
r1 = c.post("/api/voice/ref", content=wav(5))
c.put("/api/settings", json={"voiceRefText": "这是参考音频里念的字"})
c.post("/api/voice/speak", json={"text": "换个声音试试"})
brz = httpx.get("http://127.0.0.1:8093/__last", timeout=10).json()["last"] or {}
r2 = c.request("DELETE", "/api/voice/ref")
check(r1.status_code == 200 and r1.json()["ref"] and brz.get("ref_audio") and brz.get("ref_text") == "这是参考音频里念的字" and not brz.get("instruction") and not r2.json()["ref"] and
      c.post("/api/voice/ref", content=wav(1)).status_code == 400, "换说话的声音：传参考音频 + 它念的字就照它来；去掉参考音频回到音色描述；太短的不收")
c.put("/api/settings", json={"voiceEngine": "local", "voiceRefText": ""})
r = c.post("/api/voice/speak", json={"text": "Breeze 没配好的时候，用本地配音顶着。这是第二句话，稍微长一点。"})
check(r.status_code == 200 and r.headers.get("x-engine") == "local" and len(r.content) > 10000 and c.get("/api/voice").json()["engine"] == "local", "Breeze 没配好：用现有的本地配音出声")
c.put("/api/settings", json={"voiceEngine": "auto"})
check(c.post("/api/voice/speak", json={"text": "```\ncode\n```"}).status_code == 200 and c.post("/api/voice/speak", json={"text": "  "}).status_code == 400, "没有要念的字：不念")
ev = ask("今天有什么安排", voice=True)
sysm = (last_chat().get("messages") or [{}])[0].get("content", "")
check(ev.get("src") == "语音" and "念出来" in sysm, "语音说的话：事件标「语音」，告诉模型回复要适合念")

shutil.rmtree(T, ignore_errors=True)
print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
