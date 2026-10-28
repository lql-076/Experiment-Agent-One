"""配音（不用显卡、不用真模型）：
1. 切句子：句号问号感叹号切开、引号跟着前一句、空一行算换段、太长的在逗号处切、只有标点的并到前一句、小数点不切
2. 字幕时间格式、音色参数（预设 / 描述 + 语气 + 种子）、文件名去掉 Windows 不让用的字
3. 管家：配音服务算"我们自己的"显存、上次留下的配音服务认得出、让路时关掉并停下正在生成的、闲置久了关掉
4. 配音环境、生成的配音不进仓库不进压缩包；两边的模型名一致
5. 连测试后端（dev/serve.sh start 起的，配音服务换成假的 dev/fake_tts.py）：生成 → 拼接和停顿 → 时间轴 JSON / SRT 对得上 WAV →
   保存（文件夹名带日期和音色、重名加 _2）→ 我的音色存 / 改 / 删 → 试同一个人 → 停下 → 生成中再点生成 → 关掉服务
用法：python dev/test_tts.py（要先 dev/serve.sh start）"""
import ast
import io
import json
import pathlib
import re
import sys
import time
import wave

import httpx

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

# ---------- 5. 连测试后端 ----------
B = "http://127.0.0.1:8765"
H = {"X-Agent": "1"}
c = httpx.Client(base_url=B, headers=H, timeout=30)
OUT = ROOT / "dev" / ".run" / "配音输出-测试"
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
check(r.status_code == 200 and r.json()["job"]["n"] == 3, f"开始生成：切成 {r.json().get('job', {}).get('n')} 句")
r2 = c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Serena", "text": "再来一段。"})
check(r2.status_code == 409, "上一段还在生成时再点生成：不让（409）")
j = wait()
check(j["job"]["st"] == "done" and j["proc"], f"生成好了，配音服务是用到才启动的：{j['job']['msg']}")
d = j["draft"]
w = c.get("/api/tts/draft.wav")
with wave.open(io.BytesIO(w.content)) as f:
    dur = f.getnframes() / f.getframerate()
s1, s2, s3 = d["segments"]
check(abs(dur - d["duration"]) < 0.01 and abs(dur - s3["end"]) < 0.01, f"WAV 长度 = 时间轴最后一句的结束（{dur:.2f} 秒）")
check(abs((s2["start"] - s1["end"]) - 0.35) < 0.01 and abs((s3["start"] - s2["end"]) - 0.7) < 0.01, "句子之间停 0.35 秒、换段停 0.7 秒")
check(all(abs((s["end"] - s["start"]) - 0.2 * len(s["text"])) < 0.01 for s in d["segments"]), "每句的开始、结束和那句的音频对得上")
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
c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Vivian", "text": "一句话。" * 40})
time.sleep(1.0)
c.post("/api/tts/stop")
j = wait(20)
check(j["job"]["st"] == "stop" and j["job"]["i"] < 39, f"点「停下」：念完手上这句就停（停在第 {j['job']['i'] + 1} 句）")
check(j["draft"]["ver"] == ver and j["proc"], "停下的这次不覆盖上一次的试听；配音服务不关（模型还在，下次不用重装）")
c.post("/api/tts/off")
check(not c.get("/api/tts").json()["proc"], "点「关掉」：配音服务关了")
c.put("/api/settings", json={"ttsOut": ""})

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
