"""配音的百炼云端引擎（v1.8.11）。沙箱连不上百炼：用假的接口（dev/fake_bailian.py，8097）和假 Key sk-test-0000。
1. 不连后端：音色表、出错时的中文说明、标签（字幕里去掉、只有标签的一块并到前一句、标签后不补句号）、字级时间戳 → 每句的时间
2. 连测试后端（dev/serve.sh start）：生成 → 发出去的只有文案和音色这些 → 时间轴按字级时间戳 → WAV / JSON / SRT / 文案 4 个文件 →
   记用量、预估花费 → 长文案按段落分块（同一个音色、语气、种子）→ 没给时间戳按停顿对齐 → 音色不支持时间戳就去掉再试一次 →
   Key 不对、欠费、断网、文本太长、没填 Key：中文说明、只试一次 → 停下 → 试听（念过的不花钱）
3. 自己造音色（v1.8.12）：声音设计（带试听、审核中 → 能用）、复刻（上传的录音 / 最近生成的配音，要先确认是自己的或 AI 的声音）、
   用造的音色生成、同步、删除；语速 / 音调 / 音量 / 语言；读音词典（只发文案里出现的词）
4. Key 不落明文、不进导出、不进日志、不进时间轴；在玩游戏让路时不停云端的活
用法：python dev/test_tts_cloud.py（要先 dev/serve.sh start）"""
import base64
import io
import json
import pathlib
import shutil
import sys
import time
import wave

import httpx
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import feed, settings, tts, tts_cloud  # noqa: E402
from app.models import M  # noqa: E402

bad = []
feed.add = lambda *a, **k: None
KEY = "sk-test-0000"
RUN = ROOT / "dev" / ".run"


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


# ---------- 1. 不连后端 ----------
plus = [v["id"] for v in tts_cloud.VOICES["qwen-audio-3.1-tts-plus"]]
check(plus == ["longanlingxin_v3.1", "longanhuan_v3.1", "longanfengyue_v3.1", "xunanchuan_v3.1"], f"Plus 的 4 个音色（官方音色表）：{plus}")
check(tts_cloud.DEFAULT_MODEL == "qwen-audio-3.1-tts-plus" and settings.DEFAULTS["blModel"] == "qwen-audio-3.1-tts-plus" and "next" not in settings.DEFAULTS["blModel"],
      "默认模型是 Plus（不是体验中心默认的 Next），可以在设置里改")
check(settings.DEFAULTS["blBase"] == "https://dashscope.aliyuncs.com/api/v1" and tts_cloud.PATH == "/services/audio/tts/SpeechSynthesizer",
      "接口：百炼中国站（北京）")
check("blKey" in settings.SECRET_KEYS and "blKey" not in settings.DEFAULTS, "百炼 Key 是密钥（DPAPI 加密存 data/secrets.bin），不在普通设置里")
E = tts_cloud.explain
cases = [(E(401, "InvalidApiKey"), "Key 不对"), (E(400, "Arrearage"), "欠费"), (E(429, "Throttling.RateQuota"), "限流"),
         (E(400, "DataInspectionFailed"), "内容安全"), (E(403, "AccessDenied"), "不能调用"), (E(500, "InternalError"), "出错了"),
         (E(400, "InvalidParameter", "text length exceeds the limit"), "调小")]
check(all(w in str(e) for e, w in cases), "出错说人话：Key 不对 / 欠费 / 限流 / 内容拦截 / 没权限 / 服务端出错 / 文本太长（叫你调小单次字数）")
check(tts_cloud.strip_tags("[excited]今天真开心！[laughing]") == "今天真开心！", "字幕里去掉 [excited] 这类标签")
segs = tts_cloud.merge_tags(tts.split("好的。[laughing]\n\n[serious]下面说正事。"))
check([s["text"] for s in segs] == ["好的。[laughing]", "[serious]下面说正事。"], "只有标签的一块并到前一句：" + " | ".join(s["text"] for s in segs))
t, rg = tts.chunk_parts(segs, [0, 1])
check(t == "好的。[laughing]\n[serious]下面说正事。" and [t[a:b] for a, b in rg] == ["好的。[laughing]", "[serious]下面说正事。"],
      "标签后面不再补句号；每句在这一块里的位置记下来（拿来对字级时间戳）")
check(tts.chunk_text(tts.split("标题没有标点\n\n正文一句。"), [0, 1]) == "标题没有标点。\n正文一句。", "本地那边照旧：没标点的行补一个句号")

# 字级时间戳 → 每句的时间：时间从整段开始算、从这句开始算，两种都认
TXT = "大家好，欢迎回来。今天聊三个工具！"
sg = tts.split(TXT)
t, rg = tts.chunk_parts(sg, [0, 1])


def words(s, t0, rel_base=0.0):
    out, tt = [], t0
    for k, ch in enumerate(s):
        if ch in "，。！":
            continue
        out.append({"text": ch, "begin_index": k, "end_index": k + 1, "begin_time": round((tt - rel_base) * 1000), "end_time": round((tt + 0.2 - rel_base) * 1000)})
        tt += 0.2
    return out


s1, s2 = "大家好，欢迎回来。", "今天聊三个工具！"
sents_abs = [{"text": s1, "a0": 0, "a1": 24000 * 2, "words": words(s1, 0.0)}, {"text": s2, "a0": 24000 * 2, "a1": 24000 * 4, "words": words(s2, 2.0)}]
sents_rel = [{"text": s1, "a0": 0, "a1": 24000 * 2, "words": words(s1, 0.0)}, {"text": s2, "a0": 24000 * 2, "a1": 24000 * 4, "words": words(s2, 2.0, 2.0)}]
r1, r2 = tts_cloud.word_spans(t, rg, sents_abs, 24000), tts_cloud.word_spans(t, rg, sents_rel, 24000)
check(r1 and r2 and r1[0] == r2[0] and abs(r1[0][1][0] - 2.0) < 0.01 and abs(r1[0][0][1] - 1.4) < 0.01 and not any(r1[1]),
      f"字级时间戳拼出每句的开始、结束（时间从整段算、从这句算都对）：{r1[0] if r1 else None}")
check(tts_cloud.word_spans(t, rg, [dict(x, words=[]) for x in sents_abs], 24000) is None, "百炼没给时间戳：返回空，改按停顿对齐")
M.yield_level, M.yield_reason = 1, "在玩游戏（test.exe）"
tts.T.job = {"st": "run", "stop": "", "engine": "cloud"}
tts.T.tick()
check(tts.T.job["stop"] == "", "在玩游戏让路时：云端的活不停（不用显卡）")
M.yield_level, M.yield_reason = 0, ""
tts.T.job = None

# ---------- 2. 连测试后端 ----------
B = "http://127.0.0.1:8765"
FAKE = "http://127.0.0.1:8097"
c = httpx.Client(base_url=B, headers={"X-Agent": "1"}, timeout=30)
OUT = RUN / "配音输出-测试云端"
shutil.rmtree(OUT, ignore_errors=True)
c.put("/api/settings", json={"ttsOut": str(OUT), "ttsGap": 0.35, "ttsParaGap": 0.7, "blBase": FAKE + "/api/v1", "blMax": 2000, "blPrice": 1.4,
                             "blModel": "qwen-audio-3.1-tts-plus"})
c.put("/api/secrets", json={"k": "blKey", "v": KEY})
for f in RUN.glob("fake_bl_*.flag"):
    f.unlink()


def flag(n, on=True):
    p = RUN / f"fake_bl_{n}.flag"
    if on:
        p.write_text("1")
    elif p.exists():
        p.unlink()


def fake_n():
    return httpx.get(FAKE + "/_fake/log", timeout=5).json()["n"]


def fake_last(k=1):
    return httpx.get(FAKE + "/_fake/log", timeout=5).json()["items"][-k:]


def wait(t=60):
    t0 = time.time()
    while time.time() - t0 < t:
        j = c.get("/api/tts").json()
        if j["job"] and j["job"]["st"] != "run":
            return j
        time.sleep(0.25)
    return c.get("/api/tts").json()


def gen(text, voice="xunanchuan_v3.1", tone="", **kw):
    return c.post("/api/tts/gen", json={"engine": "cloud", "voice": voice, "tone": tone, "text": text, **kw})


st = c.get("/api/tts").json()
cl = st["cloud"]
check(cl["key"] and cl["model"] == "qwen-audio-3.1-tts-plus" and len(cl["voices"]) == 4 and cl["price"] == 1.4 and cl["max"] == 2000,
      "配音页拿得到云端状态：Key 填了、模型、4 个音色、单价、单次字数")
m0 = cl["month"]["n"]
n0 = fake_n()
TEXT = "大家好，欢迎回来。今天聊三个工具！\n\n第一个是配音。"
c.post("/api/tts/off")                  # 上一轮测试里对齐时开的配音服务先关掉
r = gen(TEXT, tone="轻松一点")
job = r.json().get("job") or {}
check(r.status_code == 200 and job.get("engine") == "cloud" and job.get("est", {}).get("bill", 0) > 0 and job["est"]["cny"] > 0,
      f"开始生成（百炼云端），带着预估：{job.get('est')}")
j = wait()
d = j["draft"]
check(j["job"]["st"] == "done" and "花了约" in j["job"]["msg"] and "计费" in j["job"]["msg"], "生成好了，说清楚多长、用了多久、花了多少：" + j["job"]["msg"])
check(not j["proc"], "云端生成、百炼给了字级时间戳（系统音色）：不启动本地配音服务（不占显存）")
check(fake_n() == n0 + 1, "只调了一次百炼")
req = fake_last()[0]
body = req["body"]
check(set(body) == {"model", "input"} and set(body["input"]) <= {"text", "voice", "format", "sample_rate", "instruction", "seed", "word_timestamp_enabled"},
      f"发出去的只有：模型、文案、音色、格式、采样率、语气、种子、要不要时间戳（{sorted(body['input'])}）")
check(body["input"]["text"] == "大家好，欢迎回来。今天聊三个工具！\n第一个是配音。" and body["input"]["voice"] == "xunanchuan_v3.1"
      and body["input"]["instruction"] == "轻松一点" and body["model"] == "qwen-audio-3.1-tts-plus",
      "文案就是配音页贴的那段（换段处一个换行），音色、语气、模型对得上")
check(req["auth_ok"] and req["sse"] == "enable" and body["input"]["format"] == "pcm" and body["input"]["sample_rate"] == 24000 and body["input"]["word_timestamp_enabled"],
      "带着 Key（Bearer）、开流式 SSE、要 pcm 24kHz、要字级时间戳")
w = c.get("/api/tts/draft.wav")
with wave.open(io.BytesIO(w.content)) as f:
    dur, sr = f.getnframes() / f.getframerate(), f.getframerate()
s1, s2, s3 = d["segments"]
check(sr == 24000 and abs(dur - d["duration"]) < 0.01 and dur >= s3["end"] - 0.01, f"WAV 24kHz，长度和时间轴对得上（{dur:.2f} 秒）")
check(d["engine"] == "cloud" and d["model"] == "qwen-audio-3.1-tts-plus" and "百炼" in d["license"] and d["voice"]["voice"] == "xunanchuan_v3.1"
      and d["voice"]["name"] == "许南川" and d["voice"]["tone"] == "轻松一点" and d["cost"]["billed_chars"] > 0,
      "时间轴 JSON 里记着：云端、模型、协议、音色、语气、计费字符和花费")
check("字级时间戳" in d["align"] and not any(x.get("est") for x in d["segments"]), "时间轴用的是百炼的字级时间戳（每句都对上了）")
ck = d.get("check") or {}
check(ck.get("method") == "百炼逐字时间戳" and ck.get("exact") == 3 and ck.get("estimated") == 0 and ck.get("bounds") == 2 and ck.get("bounds_in_silence") == 2,
      f"时间轴 JSON 里写着准不准：{ck}")
dump = json.loads((ROOT / "data" / "tts" / "last_bailian.json").read_text("utf-8"))
check(len(dump["sentences"]) == 3 and dump["sentences"][0]["words_n"] > 0 and KEY not in json.dumps(dump), "百炼返回的时间戳原样记了一份（data/tts/last_bailian.json，查问题用，没有 Key）")
BASE = [(x["start"], x["end"]) for x in d["segments"]]
check(abs(s1["start"]) < 0.01 and abs(s1["end"] - 1.54) < 0.03 and abs(s2["end"] - s2["start"] - 1.4) < 0.03 and abs(s3["end"] - s3["start"] - 1.2) < 0.03,
      "每句的开始、结束就是第一个字开口、最后一个字收声：" + "、".join(f"{x['start']:.2f}-{x['end']:.2f}" for x in d["segments"]))
check(abs((s2["start"] - s1["end"]) - 0.35) < 0.03 and (s3["start"] - s2["end"]) >= 0.69, "停得比设置的短就补够：句间 0.35、换段 0.7（和本地一样）")
st = c.get("/api/tts").json()
check(st["cloud"]["month"]["n"] == m0 + 1 and st["cloud"]["month"]["cny"] > 0 and st["cloud"]["ratio"], "记了一笔用量；以后按百炼实际的计费比例估价")
sv = c.post("/api/tts/save").json()
dd = pathlib.Path(sv["dir"].replace("\\", "/"))
base = dd.name
files = sorted(p.name for p in dd.iterdir())
check(base.endswith("_许南川") and files == sorted([f"{base}.wav", f"{base}_时间轴.json", f"{base}_字幕.srt", f"{base}_文案.txt"]),
      f"保存：和本地一样 4 个文件（{files}）")
srt = (dd / f"{base}_字幕.srt").read_text("utf-8")
check(srt.count(" --> ") == 3 and (dd / f"{base}_文案.txt").read_text("utf-8").strip() == TEXT, "字幕 3 条、文案原样")

# 百炼文档没写清楚的几种给法（v1.8.13）：字的时间从这一句开头算 / 字跟着音频一段一段给 / 先发下一句的开头。哪种都要对得上
for fl, base_ in (("reltime", "rel"), ("wordsinc", "abs"), ("pipeline", "abs"), ("reltime wordsinc pipeline", "rel")):
    for f_ in fl.split():
        flag(f_)
    gen(TEXT, tone="轻松一点")
    j = wait()
    for f_ in fl.split():
        flag(f_, False)
    d2 = j["draft"]
    got_ = [(x["start"], x["end"]) for x in d2["segments"]]
    diff = max(abs(a - b) for p_, q_ in zip(got_, BASE) for a, b in zip(p_, q_)) if len(got_) == len(BASE) else 99
    check(j["job"]["st"] == "done" and diff < 0.03 and (d2.get("check") or {}).get("time_base") == base_ and not any(x.get("est") for x in d2["segments"]),
          f"百炼{'、'.join({'reltime': '字的时间从这一句开头算', 'wordsinc': '字一段一段给', 'pipeline': '先发下一句开头'}[f_] for f_ in fl.split())}：时间轴照样对得上（最多差 {diff:.3f} 秒）")
c.put("/api/tts/cloud/hotfix", json={"replace": {"LHY": "L H Y"}})
gen("大家好，我是 LHY。今天聊三个工具！")
j = wait()
c.put("/api/tts/cloud/hotfix", json={})
check(j["job"]["st"] == "done" and not any(x.get("est") for x in j["draft"]["segments"]) and j["draft"]["check"]["exact"] == 2,
      "读音词典把字换了（百炼返回的原文和发的不一样）：时间轴照样对得上")

# 标签：发过去原样，字幕里去掉
gen("[excited]今天真开心！好的。[laughing]\n\n[serious]下面说正事。")
j = wait()
sent = fake_last()[0]["body"]["input"]["text"]
check(j["job"]["st"] == "done" and [x["text"] for x in j["draft"]["segments"]] == ["今天真开心！", "好的。", "下面说正事。"]
      and "[laughing]" in sent and "[laughing]。" not in sent, "情绪标签原样发给百炼（标签后不补句号），时间轴和字幕里去掉")

# 长文案：按段落分块，同一个音色、语气、种子
c.put("/api/settings", json={"blMax": 200})
LONG = ("这是一句十个字的话。" * 12 + "\n\n") * 3                 # 360 字，3 段
n0 = fake_n()
gen(LONG, voice="longanhuan_v3.1", tone="平稳")
j = wait(90)
reqs = [x["body"] for x in fake_last(fake_n() - n0)]
d = j["draft"]
check(j["job"]["st"] == "done" and len(reqs) == 3 and all(len(x["input"]["text"]) <= 200 for x in reqs), f"超过单次字数（200）：按段落分成 {len(reqs)} 块念")
check(len({(x["input"]["voice"], x["input"].get("instruction"), x["input"].get("seed")) for x in reqs}) == 1, "每块同一个音色、同一句语气、同一个种子")
segs_ = d["segments"]
check(len(segs_) == 36 and all(segs_[k + 1]["start"] >= segs_[k]["end"] for k in range(35)) and abs(d["duration"] - segs_[-1]["end"]) < 0.4,
      "拼成一个文件：36 句的时间轴前后接得上")
gap = segs_[12]["start"] - segs_[11]["end"]
check(abs(gap - 0.7) < 0.05, f"块和块之间按换段停（{gap:.2f} 秒）")
c.put("/api/settings", json={"blMax": 2000})

# 没给时间戳（自己设计、复刻的音色百炼就不给）→ 本地对齐（v1.8.14）；对齐模型没装 → 按停顿猜，猜的不补静音；音色不支持时间戳 → 去掉再试一次
NOALIGN = RUN / "fake_tts_noalign.flag"
NOALIGN.unlink(missing_ok=True)
flag("nowords")
a0 = (httpx.get("http://127.0.0.1:8092/health", timeout=3).json()["stats"].get("align_n", 0) if c.get("/api/tts").json()["proc"] else 0)
gen(TEXT)
j = wait()
d = j["draft"]
sg = d["segments"]
check(j["job"]["st"] == "done" and "本地对齐" in d["align"] and d["check"]["how"] == ["align"] and d["check"]["sure"] and len(sg) == 3
      and abs(sg[1]["start"] - 1.89) < 0.03 and abs(sg[0]["end"] - 1.54) < 0.03 and not any(x.get("est") for x in sg),
      f"百炼没给时间戳：用本地对齐模型对出每句的开始、结束（{d['check']['method']}：" + "、".join(f"{x['start']:.2f}-{x['end']:.2f}" for x in sg) + "）")
fa = httpx.get("http://127.0.0.1:8092/health", timeout=3).json()
check(fa["stats"]["align_n"] == a0 + 1 and fa["last_align"]["phrases"] == fa["last_align"]["runs"] == 4,
      f"对齐跑在配音服务里（用到才启动），整块一次对完：{fa['last_align']}")
check(abs((sg[2]["start"] - sg[1]["end"]) - 0.7) < 0.03 and d["check"].get("bounds_in_silence") == d["check"].get("bounds") == 2,
      f"对准了的边界照样补够停顿（换段 {sg[2]['start'] - sg[1]['end']:.2f} 秒），两处边界都落在停顿上")
NOALIGN.write_text("1")
gen(TEXT)
j = wait()
d = j["draft"]
sg = d["segments"]
check(j["job"]["st"] == "done" and d["check"]["how"] == ["pause"] and d["check"]["sure"] is False and "没装对齐模型" in d["check"].get("why_not_aligned", "")
      and "按停顿猜" in d["check"]["method"] and "重新对齐" in d["align"], f"对齐模型没装：退回按停顿猜，JSON 里写明是猜的、为什么没对齐：{d['check']}")
check(abs(sg[1]["start"] - 1.84) < 0.03 and abs((sg[2]["start"] - sg[1]["end"]) - 0.3) < 0.03 and abs(d["duration"] - 4.74) < 0.03,
      f"猜的边界不补静音（v1.8.13 以前补，猜错的地方被塞进静音、连声音节奏都乱了）：换段还是模型自己停的 {sg[2]['start'] - sg[1]['end']:.2f} 秒")
r = c.post("/api/tts/realign")
check(r.status_code == 400 and "对齐模型" in r.json()["detail"], f"没装对齐模型时点「重新对齐」：说清楚（{r.json().get('detail')}）")
NOALIGN.unlink()
w0 = c.get("/api/tts/draft.wav").content
bad_tl = dict(d, segments=[dict(x, start=round(x["start"] + 0.9, 3), end=round(x["end"] + 0.9, 3)) for x in sg])      # 当作猜错了
bad_tl.pop("ver", None)
(ROOT / "data" / "tts" / "draft.json").write_text(json.dumps(bad_tl, ensure_ascii=False), "utf-8")
r = c.post("/api/tts/realign", timeout=60)
rj = r.json()
d2 = rj.get("draft") or {}
sg2 = d2.get("segments") or []
check(r.status_code == 200 and d2["check"]["method"] == "本地对齐（重新对齐）" and d2["check"]["before"] == "按停顿猜" and len(sg2) == 3
      and abs(sg2[1]["start"] - 1.84) < 0.03 and abs(sg2[0]["end"] - 1.54) < 0.03 and d2.get("realigned"),
      f"「重新对齐」：试听的那段用本地对齐重对，时间回到对的地方（{rj.get('msg')}）")
srt = (ROOT / "data" / "tts" / "draft.srt").read_text("utf-8")
check(c.get("/api/tts/draft.wav").content == w0 and "00:00:01,840 --> " in srt and d2["check"]["moved_max"] >= 0.89,
      "重新对齐：声音一点没动（不重新生成、不花钱），字幕 SRT 跟着改了")
sv = c.post("/api/tts/save").json()
dd = pathlib.Path(sv["dir"].replace("\\", "/"))
tj = json.loads(next(dd.glob("*_时间轴.json")).read_text("utf-8"))
check(tj["segments"] == sg2 and tj["check"]["method"] == "本地对齐（重新对齐）", "重新对齐后再保存：存的是对齐过的时间轴")
flag("nowords", False)
flag("wordserr")
n0 = fake_n()
gen(TEXT)
j = wait()
two = fake_last(2)
check(j["job"]["st"] == "done" and fake_n() == n0 + 2 and two[0]["body"]["input"].get("word_timestamp_enabled") and "word_timestamp_enabled" not in two[1]["body"]["input"],
      "音色不支持时间戳（报参数错）：去掉时间戳再试一次就好了，一共两次")
flag("wordserr", False)

# 出错：中文说明，只试一次
c.put("/api/secrets", json={"k": "blKey", "v": "sk-wrong-1111"})
n0 = fake_n()
gen(TEXT)
j = wait()
check(j["job"]["st"] == "err" and "Key 不对" in j["job"]["msg"] and fake_n() == n0 + 1, "Key 不对：说清楚去哪重填，只试一次：" + j["job"]["msg"])
c.put("/api/secrets", json={"k": "blKey", "v": KEY})
flag("arrears")
n0 = fake_n()
gen(TEXT)
j = wait()
check(j["job"]["st"] == "err" and "欠费" in j["job"]["msg"] and fake_n() == n0 + 1, "欠费 / 余额不足：说清楚，只试一次：" + j["job"]["msg"])
flag("arrears", False)
c.put("/api/settings", json={"blBase": "http://127.0.0.1:1/api/v1"})
t0 = time.time()
gen(TEXT)
j = wait()
check(j["job"]["st"] == "err" and "连不上百炼" in j["job"]["msg"] and time.time() - t0 < 15, "断网（连不上）：马上说清楚，不重试：" + j["job"]["msg"])
c.put("/api/settings", json={"blBase": FAKE + "/api/v1", "blMax": 5000})
gen("这是一句十个字的话。" * 320)
j = wait()
check(j["job"]["st"] == "err" and "调小" in j["job"]["msg"], "文本太长（百炼报参数错）：叫你调小单次字数：" + j["job"]["msg"])
c.put("/api/settings", json={"blMax": 2000})
c.put("/api/secrets", json={"k": "blKey", "v": ""})
r = gen(TEXT)
check(r.status_code == 400 and "百炼 API Key" in r.json()["detail"] and not c.get("/api/tts").json()["cloud"]["key"], "没填 Key：不生成，告诉你去 设置 › 云端 填")
c.put("/api/secrets", json={"k": "blKey", "v": KEY})
r = gen(TEXT, voice="Vivian")
check(r.status_code == 400, "不是这个模型的音色：不生成")

# 停下
ver = c.get("/api/tts").json()["draft"]["ver"]
flag("slow")
gen("一句话。" * 30)
time.sleep(1.2)
tk = [t for t in c.get("/api/tasks").json()["tasks"] if t["k"] == "tts"]
check(tk and "百炼云端" in tk[0]["phase"], f"生成时常驻屏的后台任务里有它：{tk[0]['phase'] if tk else '没有'}")
c.post("/api/tts/stop")
t0 = time.time()
j = wait(20)
flag("slow", False)
check(j["job"]["st"] == "stop" and time.time() - t0 < 5 and j["draft"]["ver"] == ver, f"点「停下」：马上断开，不覆盖上一次的试听（{j['job']['msg']}）")

# 试听
m1 = c.get("/api/tts").json()["cloud"]["month"]["n"]
for f in (ROOT / "data" / "tts" / "try").glob("*longanfengyue*"):
    f.unlink()
r1 = c.post("/api/tts/cloud/try", json={"voice": "longanfengyue_v3.1"})
r2 = c.post("/api/tts/cloud/try", json={"voice": "longanfengyue_v3.1"})
with wave.open(io.BytesIO(r1.content)) as f:
    tdur = f.getnframes() / f.getframerate()
check(r1.status_code == 200 and r1.headers["x-cached"] == "0" and r2.headers["x-cached"] == "1" and r1.content == r2.content and tdur > 2,
      f"试听：念一句固定的短句（{tdur:.1f} 秒），再点用存着的")
check(c.get("/api/tts").json()["cloud"]["month"]["n"] == m1 + 1 and fake_last()[0]["body"]["input"]["text"] == tts_cloud.TRY_TEXT,
      "试听只花第一次的钱（记一笔），发的是那句固定的短句")
check(c.post("/api/tts/cloud/try", json={"voice": "nobody"}).status_code == 400, "没有的音色：不试听")

# ---------- 3. 自己造音色、表达、读音词典（v1.8.12） ----------
def until(fn, t=15):
    t0 = time.time()
    while time.time() - t0 < t:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return fn()


def mine():
    return c.get("/api/tts").json()["cloud"]["mine"]


n0 = fake_n()
r = c.post("/api/tts/cloud/design", json={"name": "科技解说", "prompt": "三十岁左右的男声，低沉有磁性，吐字清楚，语速平稳，适合科技解说", "lang": "zh"})
v = r.json().get("voice") or {}
req = fake_last()[0]
check(r.status_code == 200 and v.get("status") == "DEPLOYING" and v["kind"] == "design" and v["id"].startswith("qwen-audio-3.1-tts-plus-vd-"),
      "声音设计：写一段描述，百炼造了一个音色（先是审核中）")
inp = req["body"]["input"]
check(req["path"] == "custom" and req["body"]["model"] == "voice-enrollment" and inp["action"] == "create_voice" and inp["target_model"] == "qwen-audio-3.1-tts-plus"
      and inp["preview_text"] == tts_cloud.DESIGN_TEXT and len(inp["prefix"]) <= 10 and inp["prefix"].isalnum() and req["body"]["parameters"]["response_format"] == "wav",
      "发的是：音色描述、试听句、模型（和合成用的一样）、前缀（字母数字 10 个以内）")
r1 = c.post("/api/tts/cloud/try", json={"voice": v["id"]})
check(r1.status_code == 200 and r1.headers["x-cached"] == "1" and fake_n() == n0 + 1, "刚设计好、还在审核：先听百炼给的那段试听（不花钱，不再调接口）")
r = c.post("/api/tts/gen", json={"engine": "cloud", "voice": v["id"], "text": TEXT})
check(r.status_code == 400 and "审核" in r.json()["detail"], "审核通过之前不能用来生成")
ok = until(lambda: [x for x in mine() if x["id"] == v["id"] and x["status"] == "OK"])
check(bool(ok), "百炼审核通过：状态自己变成「能用」（后台每 2 秒查一次）")
check(c.post("/api/tts/cloud/design", json={"prompt": ""}).status_code == 400 and c.post("/api/tts/cloud/design", json={"prompt": "男声", "text": "太短"}).status_code == 400,
      "没写描述、试听句不到 15 字：不发")
n0 = fake_n()
r = c.post("/api/tts/gen", json={"engine": "cloud", "voice": v["id"], "text": TEXT, "rate": 1.25, "pitch": 1, "volume": 70, "lang": "zh"})
j = wait()
inp = fake_last()[0]["body"]["input"]
check(r.status_code == 200 and j["job"]["st"] == "done" and inp["voice"] == v["id"] and inp["rate"] == 1.25 and inp["volume"] == 70 and inp["language_hints"] == ["zh"]
      and "pitch" not in inp, "用造的音色生成；语速、音量、语言带上了，跟默认一样的（音调 1）不发")
d = j["draft"]
check(d["voice"]["vkind"] == "design" and d["voice"]["name"] == "科技解说" and d["voice"]["expr"] == {"rate": 1.25, "volume": 70, "language_hints": ["zh"]}
      and abs(d["segments"][0]["end"] - d["segments"][0]["start"] - 1.54 / 1.25) < 0.05, "时间轴里记着音色和语速；语速快了，时间轴跟着变短")

r = c.put("/api/tts/cloud/hotfix", json={"pronunciation": {"重庆": "chong2 qing4", "行长": "hang2 zhang3"}, "replace": {"LHY": "L H Y"}})
check(r.status_code == 200 and r.json()["hotfix"]["pronunciation"]["重庆"] == "chong2 qing4", "读音词典存好了")
check(c.put("/api/tts/cloud/hotfix", json={"pronunciation": {"重庆": "chongqing"}}).status_code == 400, "拼音没写声调：不存，说清楚怎么写")
gen("我是 LHY，今天去重庆。")
j = wait()
hf = fake_last()[0]["body"]["input"].get("hot_fix") or {}
check(j["job"]["st"] == "done" and hf == {"pronunciation": [{"重庆": "chong2 qing4"}], "replace": [{"LHY": "L H Y"}]},
      f"生成时只把文案里出现的词发过去（「行长」没出现就不发）：{hf}")
c.put("/api/tts/cloud/hotfix", json={})

# 复刻：上传的录音
sample = io.BytesIO()
with wave.open(sample, "wb") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(24000)
    f.writeframes((np.sin(np.arange(24000 * 12) * 0.05) * 6000).astype("<i2").tobytes())
b64 = base64.b64encode(sample.getvalue()).decode()
r = c.post("/api/tts/cloud/clone", json={"source": "upload", "data": "data:audio/wav;base64," + b64, "file": "我的录音.wav", "name": "复刻测试"})
check(r.status_code == 400 and "自己的" in r.json()["detail"], "没确认是自己的或 AI 生成的声音：不复刻")
n0 = fake_n()
r = c.post("/api/tts/cloud/clone", json={"source": "upload", "data": "data:audio/wav;base64," + b64, "file": "我的录音.wav", "name": "复刻测试", "consent": True, "denoise": True})
cv = r.json().get("voice") or {}
inp = fake_last()[0]["body"]["input"]
check(r.status_code == 200 and cv.get("kind") == "clone" and cv.get("dur") == 12.0 and fake_n() == n0 + 1 and inp["audio"].startswith("data:audio/wav;base64,")
      and inp["enable_preprocess"] is True and inp["target_model"] == "qwen-audio-3.1-tts-plus", "复刻：录音按 Base64 发过去（不用传到网上），带上降噪；造好了（审核中）")
short = io.BytesIO()
with wave.open(short, "wb") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(24000)
    f.writeframes(b"\0\0" * 24000)
r = c.post("/api/tts/cloud/clone", json={"data": base64.b64encode(short.getvalue()).decode(), "consent": True})
check(r.status_code == 400 and "太短" in r.json()["detail"], "录音太短（1 秒）：不发，说清楚")
r = c.post("/api/tts/cloud/clone", json={"data": base64.b64encode(b"not audio at all" * 100).decode(), "consent": True})
check(r.status_code == 400 and "WAV" in r.json()["detail"], "不是录音：不发")
gen(("这是一句十个字的话。" * 3 + "\n\n") * 4)        # 120 字，大约 26 秒：拿它复刻要截到 20 秒以内
wait()
n0 = fake_n()
r = c.post("/api/tts/cloud/clone", json={"source": "draft", "name": "AI 造的声音", "consent": True})
cv2 = r.json().get("voice") or {}
a = fake_last()[0]["body"]["input"]["audio"]
check(r.status_code == 200 and "最近生成的配音" in cv2.get("src", "") and 12 <= (cv2.get("dur") or 0) <= 20.01, f"复刻最近生成的配音：截到 20 秒以内、在停顿处断开（{cv2.get('dur')} 秒）")
until(lambda: all(x["status"] == "OK" for x in mine() if x["id"] in (cv["id"], cv2.get("id"))))
check(sum(1 for x in mine() if x["status"] == "OK" and x["kind"] == "clone") >= 2, "复刻的音色审核通过，能用了")

# 同步、删除
httpx.post(FAKE + "/_fake/made", json={"voice_id": "qwen-audio-3.1-tts-plus-vd-web-abc123", "status": "OK"})
r = c.post("/api/tts/cloud/sync").json()
check(r["added"] == 1 and any(x["id"] == "qwen-audio-3.1-tts-plus-vd-web-abc123" for x in mine()), "同步：在百炼控制台造的音色也拿回来了：" + r["msg"])
r = c.patch("/api/tts/cloud/voices/qwen-audio-3.1-tts-plus-vd-web-abc123", json={"name": "控制台造的"})
check(any(x["name"] == "控制台造的" for x in r.json()["mine"]), "改名字（只改本机）")
r = c.delete("/api/tts/cloud/voices/qwen-audio-3.1-tts-plus-vd-web-abc123")
del_req = fake_last()[0]["body"]["input"]
check(r.status_code == 200 and not any(x["id"] == "qwen-audio-3.1-tts-plus-vd-web-abc123" for x in r.json()["mine"]) and del_req["action"] == "delete_voice",
      "删掉：百炼那边也删了（省配额）")
flag("reject")
r = c.post("/api/tts/cloud/design", json={"name": "会被拒的", "prompt": "一个声音描述，测试审核不通过"})
bad_id = r.json()["voice"]["id"]
check(bool(until(lambda: [x for x in mine() if x["id"] == bad_id and x["status"] == "UNDEPLOYED"])), "审核没通过：标出来，不能用")
flag("reject", False)
st = c.get("/api/tts").json()["cloud"]
check(st["count"] >= 3 and st["quota"] == 1000 and any(v["id"] == v_ for v_ in [x["id"] for x in st["mine"]]) and len(st["voices"]) == 4,
      f"配音页拿得到：现成的 4 个 + 自己造的 {len(st['mine'])} 个，用了多少配额")
for x in mine():                                          # 测试造的都删掉（百炼那边、本机都删）
    c.delete("/api/tts/cloud/voices/" + x["id"])
check(mine() == [], "测试造的音色清干净了")

# ---------- 4. Key 不外泄 ----------
ex = c.get("/api/export").text
hint = c.get("/api/settings").json()["secrets"].get("blKey")
check(KEY not in ex and "blKey" not in ex, "导出设置里没有百炼 Key")
check(hint == "••••0000", f"界面只拿得到最后 4 位：{hint}")
leak = []
for p in [ROOT / "data" / "settings.json", RUN / "backend.log", RUN / "mocks.log", *(ROOT / "data" / "logs").glob("*.log"), *(ROOT / "data" / "tts").glob("draft.*"), *OUT.rglob("*.*")]:
    try:
        if p.is_file() and KEY.encode() in p.read_bytes():
            leak.append(p.name)
    except OSError:
        pass
check(not leak, f"设置文件、日志、时间轴、保存的配音里都没有 Key{'：' + str(leak) if leak else ''}")
fd = " | ".join(e["text"] for e in c.get("/api/feed?n=200").json()["items"])
check(KEY not in fd and "sk-wrong" not in fd, "进展报告里也没有 Key")
c.put("/api/settings", json={"ttsOut": "", "ttsEngine": "local"})

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
