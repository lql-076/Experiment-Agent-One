"""配音（不用显卡、不用真模型）：
1. 切句子：句号问号感叹号切开、引号跟着前一句、空一行算换段、太长的在逗号处切、只有标点的并到前一句、小数点不切
2. 字幕时间格式、音色参数（预设 / 描述 + 语气 + 种子）、文件名去掉 Windows 不让用的字
3. 管家：配音服务算"我们自己的"显存、上次留下的配音服务认得出、让路时关掉并停下正在生成的、闲置久了关掉
4. 配音环境、生成的配音不进仓库不进压缩包；两边的模型名一致
5. 连测试后端（dev/serve.sh start 起的，配音服务换成假的 dev/fake_tts.py）：生成 → 拼接和停顿 → 时间轴 JSON / SRT 对得上 WAV →
   保存（文件夹名带日期和音色、重名加 _2）→ 我的音色存 / 改 / 删 → 试同一个人 → 停下 → 生成中再点生成 → 关掉服务
6. 设置 › 本地模型 的「安装配音」：后台装、进展报告、日志、失败再点、改走 hf-mirror、停下
用法：python dev/test_tts.py（要先 dev/serve.sh start）"""
import ast
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import wave
from contextlib import redirect_stdout

import httpx
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fastapi import HTTPException  # noqa: E402
from app import feed, paths, tts  # noqa: E402
from app.models import M, orphan_kind  # noqa: E402

bad = []
feed.add = lambda *a, **k: None


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


# ---------- 1. 切句子 ----------
segs = tts.split("第一句。第二句！\n第三行没有标点\n\n新的一段……“引号里的话。”然后呢？", gap=0.35, para=0.7)
check([s["text"] for s in segs] == ["第一句。", "第二句！", "第三行没有标点", "新的一段……", "“引号里的话。”", "然后呢？"],
      "按句号、感叹号、问号、省略号、换行切开；引号跟着前一句：" + " | ".join(s["text"] for s in segs))
check([s["gap"] for s in segs] == [0.35, 0.35, 0.7, 0.35, 0.35, 0.0], f"句子之间停 0.35、换段停 0.7、最后一句不停：{[s['gap'] for s in segs]}")
long = "这是一个特别长的句子，里面有很多逗号，" * 6 + "最后才有句号。"
ls = tts.split(long)
check(len(ls) > 1 and all(len(s["text"]) <= 60 for s in ls) and "".join(s["text"] for s in ls) == long,
      f"太长的句子在逗号处切成 {len(ls)} 块（每块不超过 60 字），拼回去一个字不少")
check(all(s["gap"] == 0.15 for s in ls[:-1]), "同一句里切开的块之间只停 0.15 秒")
check([s["text"] for s in tts.split("好。！？\n——\n下一句。")] == ["好。！？——", "下一句。"], "只有标点的并到前一句，不单独生成")
check([s["text"] for s in tts.split("版本 v1.8.6 已经发布，价格 3.5 元。Next one. And this!")] == ["版本 v1.8.6 已经发布，价格 3.5 元。", "Next one.", "And this!"],
      "小数点、版本号不切；英文句号后面有空格才切")
check(tts.split("   \n\n  ") == [], "全是空白：没有要念的")

# ---------- 1b. 整段一次生成：分块、按停顿对齐、补停顿（v1.8.9） ----------
SR = 1000


def audio(parts):
    """[(秒, 有没有声音)…] → 16 位 PCM。"""
    out = bytearray()
    for sec, loud in parts:
        n = int(round(sec * SR))
        out += (np.sin(np.arange(n) * 0.9) * (9000 if loud else 0)).astype("<i2").tobytes()
    return out


segs = tts.split("大家好，欢迎回来。今天聊三个工具！第一个是配音。")
pcm = audio([(0.4, 1), (0.14, 0), (0.8, 1), (0.3, 0), (1.6, 1), (0.3, 0), (1.4, 1)])     # 第一句中间有逗号的小停顿
spans, est, got = tts.whole_timeline(pcm, SR, segs, [0, 1, 2])
check(not any(est) and abs(spans[1][0] - 1.64) < 0.03 and abs(spans[2][0] - 3.54) < 0.03,
      f"按停顿对齐：句末的停顿对上了，逗号那个小停顿不算（第 2、3 句从 {spans[1][0]:.2f}、{spans[2][0]:.2f} 秒开始）")
pcm2 = audio([(1.2, 1), (0.3, 0), (3.0, 1)])                                            # 后两句连着念了，中间没停
spans, est, got = tts.whole_timeline(pcm2, SR, segs, [0, 1, 2])
check(est == [False, True, True] and spans[0][1] == 1.2, "有一处没停顿（两句连着念了）：那两句标「按字数估的」，别的照样对齐")
pcm3, sp3 = tts.pad_pauses(pcm, SR, [[0, 1.34], [1.64, 3.24], [3.54, 4.94]], [(1.34, 1.64), (3.24, 3.54)], [0.35, 0.7])
check(abs(len(pcm3) / 2 / SR - (len(pcm) / 2 / SR + 0.05 + 0.4)) < 0.01 and abs(sp3[1][0] - 1.69) < 0.01 and abs(sp3[2][0] - 3.99) < 0.01,
      "模型停得比设置的短：在停顿中间补静音（句间补到 0.35、换段补到 0.7），后面的时间跟着挪")
big = tts.split(("这是一句十个字的话。" * 50 + "\n\n") * 4)
ch = tts.whole_chunks(big, 1200)
check(len(ch) == 2 and all(big[c[-1]]["kind"] in ("para", "end") for c in ch) and sum(len(c) for c in ch) == len(big),
      f"太长的（2000 字）分成 {len(ch)} 块，都在换段处断开，一句不少")
check(tts.chunk_text(tts.split("标题没有标点\n\n正文一句。"), [0, 1]) == "标题没有标点。\n正文一句。", "一块里没有句末标点的行补一个句号，换段处换行")
ten = tts.split(("这是一句十个字的话。" * 40 + "\n\n") * 6)                      # 2400 字，中文大约 9 分半
check(tts.WHOLE_MAX >= 2500 and len(tts.whole_chunks(ten)) == 1, f"10 分钟以内（2400 字）一次念完，不分块（一块最多 {tts.WHOLE_MAX} 字）")
over = tts.split(("这是一句十个字的话。" * 40 + "\n\n") * 8)                     # 3200 字，超过 10 分钟
check(len(tts.whole_chunks(over)) == 2, "超过 10 分钟（3200 字）才在换段处分成两块")
srv = (ROOT / "app" / "tts_server.py").read_text("utf-8")
check("min(24000, 96 + len(text) * 6)" in srv and 96 + 2600 * 6 <= 24000, "配音服务给的长度上限够念 2600 字（一个字 6 帧，10 分钟一整段也够）")

# ---------- 2. 字幕、音色参数、文件名 ----------
check(tts.srt_time(3725.5) == "01:02:05,500" and tts.srt_time(0) == "00:00:00,000", f"SRT 时间格式：{tts.srt_time(3725.5)}")
srt = tts.to_srt([{"i": 1, "start": 0, "end": 1.25, "text": "一"}, {"i": 2, "start": 1.6, "end": 2, "text": "二"}])
check(srt.startswith("1\n00:00:00,000 --> 00:00:01,250\n一\n\n2\n00:00:01,600"), "SRT 一句一条，序号、时间、原文")
v = tts.T.voice({"mode": "preset", "speaker": "serena", "tone": "温柔一点"})
check(v["speaker"] == "Serena" and v["kind"] == "custom" and v["instruct"] == "温柔一点" and v["lang"] == "Chinese" and v["seed"] > 0,
      "预设音色：名字不分大小写，语气就是说明，默认中文，随机给一个种子")
try:
    tts.T.voice({"mode": "preset", "speaker": "张三"})
    check(False, "没有的音色要报错")
except HTTPException:
    check(True, "没有的音色：报错，不乱念")
v = tts.T.voice({"mode": "design", "desc": "低沉的男声", "tone": "慢一点", "seed": "42", "name": "解说"})
check(v["kind"] == "design" and v["instruct"] == "低沉的男声；慢一点" and v["seed"] == 42 and v["label"] == "解说", "描述音色：描述 + 语气拼成说明，种子用你给的")
try:
    tts.T.voice({"mode": "design", "desc": "  "})
    check(False, "描述音色没写描述要报错")
except HTTPException:
    check(True, "描述音色没写描述：报错")
check(tts.safe_name('a/b:c*?"<>|d') == "abcd" and tts.safe_name("") == "配音", "文件名去掉 Windows 不让用的字")

# ---------- 3. 管家 ----------
check(tts.T.proc in M.extra, "配音服务登记在模型管家里：显存算我们自己的，退出 Agent 时一起停")
check(orphan_kind(r"F:\Agent\tts-env\Scripts\python.exe F:\Agent\app\tts_server.py --port 8092", r"F:\Agent\tts-env\Scripts\python.exe", r"F:\Agent", r"F:\Agent") == "配音服务",
      "上次留下的配音服务认得出（启动时停掉，免得端口被占）")
check(orphan_kind(r"python.exe D:\别的\app\tts_server.py", r"C:\Python\python.exe", r"D:\别的", r"F:\Agent") is None, "别的文件夹里同名的程序不碰")
P = tts.T.proc
P.start([sys.executable, "-c", "import time; time.sleep(60)"], ROOT, None)
check(P.p.pid in M.own_pids(), "配音服务的进程号算进「我们自己的」（显存让路按这个算）")
tts.T.job = {"st": "run", "stop": ""}
M.yield_level, M.yield_reason = 1, "在玩游戏（test.exe），不装底座和 Kev"
tts.T.tick()
check(not P.alive() and tts.T.job["stop"].startswith("在玩游戏"), "让路（在玩游戏）：配音服务关掉，正在生成的停下")
M.yield_level, M.yield_reason = 0, ""
tts.T.job = None
P.start([sys.executable, "-c", "import time; time.sleep(60)"], ROOT, None)
tts.T.last = time.time()
tts.T.tick()
check(P.alive(), "刚用过：不关")
tts.T.last = time.time() - 11 * 60
tts.T.tick()
check(not P.alive(), "闲置超过 10 分钟：关掉，显存还回去")

# ---------- 4. 不进仓库、两边模型名一致 ----------
gi = (ROOT / ".gitignore").read_text("utf-8")
pk = (ROOT / "dev" / "pack.py").read_text("utf-8")
check("tts-env/" in gi and "配音输出/" in gi and "models/**" in gi, ".gitignore：配音环境、配音输出、模型都不进仓库")
check('"tts-env/"' in pk and '"配音输出/"' in pk and '".wav"' in pk, "打包的禁止清单里有配音环境、配音输出、.wav")
tree = ast.parse((ROOT / "app" / "tts_server.py").read_text("utf-8"))
names = next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "NAMES")
check(names == paths.TTS_MODELS, f"配音服务和后端用的模型名一致：{list(names.values())}")
inst = (ROOT / "scripts" / "install_tts.py").read_text("utf-8")
check("qwen-tts==0.1.1" in inst and "transformers==4.57.3" in inst and "gradio" not in inst.split("DEPS = ")[1].split("]")[0],
      "安装配音：qwen-tts 锁 0.1.1，Transformers 用官方要的 4.57.3，不装 gradio")
# v1.8.7 的 bug：装完自检时导入 qwen_tts，它一导入就 import sox（没装）→ 报错，界面上只显示一排星号（qwen-tts 打的 flash-attn 提示）
sys.path.insert(0, str(ROOT / "scripts"))
import install_tts  # noqa: E402
fake = pathlib.Path(tempfile.mkdtemp()) / "fakeqtts"
fake.mkdir()
(fake / "__init__.py").write_text('print("\\n********\\nWarning: flash-attn is not installed.\\n********\\n ")\nimport sox\n', "utf-8")
os.environ["PYTHONPATH"] = str(fake.parent)
install_tts.A.PY = pathlib.Path(sys.executable)
stub = install_tts.CHECK.split("import torch")[0]
ok, info = install_tts.has(stub + "import fakeqtts\nprint('好了')")
check(ok and info == "好了", f"自检先放空的 sox 再导入：像 qwen-tts 那样一导入就 import sox 也能过（{info}）")
with redirect_stdout(io.StringIO()):
    ok, info = install_tts.has("import fakeqtts")
check(not ok and "No module named 'sox'" in info, f"真出错时写出真正的报错，不是那排星号：{info}")
c0 = install_tts.CHECK
check(c0.index("sys.modules.setdefault('sox'") < c0.index("import torch, transformers, qwen_tts"), "安装自检的代码里：空 sox 放在导入 qwen_tts 之前")
os.environ.pop("PYTHONPATH")

# ---------- 5. 连测试后端 ----------
B = "http://127.0.0.1:8765"
H = {"X-Agent": "1"}
c = httpx.Client(base_url=B, headers=H, timeout=30)
OUT = ROOT / "dev" / ".run" / "配音输出-测试"
shutil.rmtree(OUT, ignore_errors=True)          # 上一次测试存的清掉（只在 dev/.run 里），免得同一分钟重名
c.put("/api/settings", json={"ttsOut": str(OUT), "ttsGap": 0.35, "ttsParaGap": 0.7})


def wait(t=60):
    t0 = time.time()
    while time.time() - t0 < t:
        j = c.get("/api/tts").json()
        if j["job"] and j["job"]["st"] != "run":
            return j
        time.sleep(0.3)
    return c.get("/api/tts").json()


c.post("/api/tts/off")
st = c.get("/api/tts").json()
check(st["env"] and not st["proc"] and len(st["speakers"]) == 9 and sum("中文" in s["lang"] for s in st["speakers"]) == 5,
      "配音页拿得到状态：9 个预设音色（5 个中文），服务没开")
TEXT = "大家好，欢迎回来。今天聊三个工具！\n\n第一个是配音。"
r = c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Serena", "text": TEXT, "tone": "轻松一点"})
check(r.status_code == 200 and r.json()["job"]["n"] == 3 and r.json()["job"]["whole"], f"开始生成：默认整段一次生成，时间轴分 {r.json().get('job', {}).get('n')} 句")
r2 = c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Serena", "text": "再来一段。"})
check(r2.status_code == 409, "上一段还在生成时再点生成：不让（409）")
j = wait()
check(j["job"]["st"] == "done" and j["proc"], f"生成好了，配音服务是用到才启动的：{j['job']['msg']}")
d = j["draft"]
check(c.get("http://127.0.0.1:8092/health").json()["stats"]["n"] == 1, "整段一次生成：三句话只念了一次（一次采样，语气连贯）")


def fake_len(t):
    """假配音服务念一句要多久：一个字 0.2 秒 + 句子中间每个逗号停 0.14 秒。"""
    return 0.2 * len(t) + 0.14 * sum(1 for ch in t[:-1] if ch in "，,、；;：:")


w = c.get("/api/tts/draft.wav")
with wave.open(io.BytesIO(w.content)) as f:
    dur = f.getnframes() / f.getframerate()
s1, s2, s3 = d["segments"]
check(abs(dur - d["duration"]) < 0.01 and abs(dur - s3["end"]) < 0.06, f"WAV 长度 = 时间轴最后一句的结束（{dur:.2f} 秒）")
check(d["way"] == "whole" and not any(x.get("est") for x in d["segments"]), "整段生成：三句的边界都对上了音频里的停顿（没有按字数估的）")
check(all(abs((x["end"] - x["start"]) - fake_len(x["text"])) < 0.06 for x in d["segments"]),
      "按停顿对齐：每句的开始、结束和那句的声音对得上（误差 0.06 秒内）：" + "、".join(f"{x['start']:.2f}-{x['end']:.2f}" for x in d["segments"]))
check(abs((s2["start"] - s1["end"]) - 0.35) < 0.06 and (s3["start"] - s2["end"]) >= 0.69,
      f"模型自己停的比设置的短就补够：句间 {s2['start'] - s1['end']:.2f} 秒（设置 0.35）、换段 {s3['start'] - s2['end']:.2f} 秒（≥ 0.7）")
r = c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Serena", "text": TEXT, "whole": False})
j = wait()
d1 = j["draft"]
t1, t2, t3 = d1["segments"]
check(d1["way"] == "sentence" and abs((t2["start"] - t1["end"]) - 0.35) < 0.01 and abs((t3["start"] - t2["end"]) - 0.7) < 0.01
      and all(abs((x["end"] - x["start"]) - fake_len(x["text"])) < 0.06 for x in d1["segments"]), "一句一句生成也还能用：句子之间 0.35 秒、换段 0.7 秒")
c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Serena", "text": TEXT, "tone": "轻松一点"})
j = wait()
d = j["draft"]
check("照这个速度，1 分钟音频要" in j["job"]["msg"], "生成完的那句话说清楚：多长音频、用了多久、照这个速度 1 分钟音频要多久：" + j["job"]["msg"])
check(d["voice"]["speaker"] == "Serena" and d["voice"]["tone"] == "轻松一点" and d["license"] == "Apache-2.0" and d["model"].endswith("CustomVoice"),
      "时间轴里记着音色、语气、模型名、许可证")
sv = c.post("/api/tts/save").json()
dd = pathlib.Path(sv["dir"].replace("\\", "/"))
base = dd.name
files = sorted(p.name for p in dd.iterdir())
check(re.match(r"\d{4}-\d{2}-\d{2}_\d{4}_Serena$", base) is not None, f"保存的文件夹名带日期和音色：{base}")
check(files == sorted([f"{base}.wav", f"{base}_时间轴.json", f"{base}_字幕.srt", f"{base}_文案.txt"]), f"一个文件夹里 4 个文件：{files}")
tj = json.loads((dd / f"{base}_时间轴.json").read_text("utf-8"))
srt = (dd / f"{base}_字幕.srt").read_text("utf-8")
check(tj["segments"] == d["segments"] and tj["audio"] == f"{base}.wav" and srt.count(" --> ") == 3 and (dd / f"{base}_文案.txt").read_text("utf-8").strip() == TEXT,
      "时间轴 JSON、字幕 SRT、文案和试听的那份一样")
sv2 = c.post("/api/tts/save").json()
check(sv2["name"] == base + "_2", f"同一分钟再存一次：加 _2，不覆盖（{sv2['name']}）")

vs = c.post("/api/tts/voices", json={"name": "解说男声", "desc": "三十岁左右的男声，低沉温和", "seed": 20261028}).json()["voices"]
vs = c.post("/api/tts/voices", json={"name": "解说男声", "desc": "三十岁左右的男声，低沉温和，语速平稳", "seed": 7}).json()["voices"]
mine = [v for v in vs if v["name"] == "解说男声"]
check(len(mine) == 1 and mine[0]["seed"] == 7, "我的音色：同名再存是改，不会多一个")
check(c.post("/api/tts/voices", json={"name": "x", "desc": "y", "seed": "abc"}).status_code == 400, "种子不是数字：不存")
vs = c.delete(f"/api/tts/voices/{mine[0]['id']}").json()["voices"]
check(not [v for v in vs if v["name"] == "解说男声"], "我的音色：删掉了")

r = c.post("/api/tts/gen", json={"mode": "design", "desc": "", "same": True})
check(r.status_code == 400, "描述音色没写描述：不生成")
r = c.post("/api/tts/gen", json={"mode": "design", "desc": "三十岁左右的男声，低沉温和", "seed": 7, "same": True, "name": "解说男声"})
j = wait()
d = j["draft"]
check(j["job"]["st"] == "done" and d["same_test"] and len(d["segments"]) == 2 and d["voice"]["seed"] == 7 and d["model"].endswith("VoiceDesign"),
      "试同一个人：用描述音色念两段不相干的话，种子记在时间轴里")
check(abs((d["segments"][1]["start"] - d["segments"][0]["end"]) - 1.2) < 0.01, "试同一个人：两段之间停 1.2 秒，好分辨")

ver = d["ver"]
c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Vivian", "text": "一句话。" * 40, "whole": False})
time.sleep(1.0)
tk = [t for t in c.get("/api/tasks").json()["tasks"] if t["k"] == "tts"]
check(tk and tk[0]["name"] == "生成配音 · Vivian" and "/40 句" in tk[0]["phase"], f"生成配音时常驻屏的后台任务里也有它：{tk[0]['phase'] if tk else '没有'}")
c.post("/api/tts/stop")
j = wait(20)
check(j["job"]["st"] == "stop" and j["job"]["i"] < 39, f"点「停下」：念完手上这句就停（停在第 {j['job']['i'] + 1} 句）")
check(j["draft"]["ver"] == ver and j["proc"], "停下的这次不覆盖上一次的试听；配音服务不关（模型还在，下次不用重装）")
c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Vivian", "text": "一句话。" * 60})
time.sleep(1.2)
tk = [t for t in c.get("/api/tasks").json()["tasks"] if t["k"] == "tts"]
check(tk and "整段一次生成" in tk[0]["phase"] and tk[0]["pct"] is not None, f"整段生成时后台任务里也有它，进度按上次的速度估：{tk[0] if tk else '没有'}")
c.post("/api/tts/stop")
j = wait(20)
check(j["job"]["st"] == "stop" and j["draft"]["ver"] == ver, f"整段生成时点「停下」：马上停（把服务关了），不覆盖上一次的试听（{j['job']['msg']}）")
c.post("/api/tts/off")
check(not c.get("/api/tts").json()["proc"], "点「关掉」：配音服务关了")

# ---------- 6. 设置 › 本地模型 的「安装配音」（测试后端里换成假的安装 dev/fake_tts_install.py） ----------
def inst_wait(t=30):
    t0 = time.time()
    while time.time() - t0 < t:
        i = c.get("/api/tts").json()["inst"]
        if i["st"] != "run":
            return i
        time.sleep(0.2)
    return c.get("/api/tts").json()["inst"]


r = c.post("/api/tts/install", json={})
check(r.status_code == 200 and r.json()["st"] == "run", "点「安装配音」：在后台开始装")
tk = c.get("/api/tasks").json()["tasks"]
check(any(t["k"] == "tts_install" and t["name"] == "安装配音" for t in tk), f"常驻屏的后台任务里有「安装配音」：{[t['name'] for t in tk]}")
check(c.post("/api/tts/install", json={}).status_code == 409, "装着的时候再点：不重复开")
i = inst_wait()
check(i["st"] == "ok" and i["code"] == 0 and i["pct"] == 100, f"装完了：{i['line']}")
check(not any(t["k"] == "tts_install" for t in c.get("/api/tasks").json()["tasks"]), "装完了：后台任务里没有它了（常驻屏的进度条消失）")
feedtxt = " | ".join(e["text"] for e in c.get("/api/feed?n=60").json()["items"] if e.get("job") == "安装配音")
check("开始安装配音" in feedtxt and "装好了 4 个包" in feedtxt and "下载 model.safetensors 完成" in feedtxt and "配音装好了" in feedtxt,
      "每一步写进进展报告（后台页，任务名「安装配音」）：开始、装了哪些包、下载完成多大多久、装好了")
log = pathlib.Path(i["log"].replace("\\", "/"))
check(log.exists() and "预设音色 CustomVoice 下好了" in log.read_text("utf-8"), "原始输出写进 data/logs/setup_tts.log")
(ROOT / "dev" / ".run" / "fake_tts_install_fail.flag").write_text("1")
c.post("/api/tts/install", json={})
i = inst_wait()
check(i["st"] == "fail" and i["code"] == 1, "下到一半断了：显示没装完（退出码 1），可以再点")
c.post("/api/tts/install", json={"hf": True})
i = inst_wait()
check(i["st"] == "ok" and i["hf"], "点「改从 hf-mirror 下」：接着装好了")
c.post("/api/tts/install", json={})
c.post("/api/tts/install/stop")
i = inst_wait()
check(i["st"] == "stop", "点「停下」：停了（再点会接着装）")
c.put("/api/settings", json={"ttsOut": ""})

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
