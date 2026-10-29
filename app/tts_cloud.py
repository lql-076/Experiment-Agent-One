"""配音的云端引擎（v1.8.11）：阿里云百炼的千问语音合成 Qwen-Audio-3.1-TTS-Plus。本地 Qwen3-TTS 留着当备用。

- 接口：百炼中国站（北京）的 HTTP 接口，开 SSE 流式（X-DashScope-SSE: enable）：边念边传回来，进度是真的；
  只有流式才给字级时间戳（word_timestamp_enabled）。音频要 pcm（16 位单声道）24kHz，拼起来就是 WAV。
- 发出去的只有：配音页里贴的文案、选的音色、语气那一句、种子、格式。别的一律不发。
- Key：设置 › 云端 填，DPAPI 加密存在 data\\secrets.bin（settings.SECRET_KEYS 里的 blKey），不写日志、不进导出、不进仓库。
- 出错（Key 不对、欠费、限流、断网…）只试一次，给一句中文说明，不重试。唯一的例外：这个音色不支持字级时间戳而报参数错，
  就去掉时间戳再试一次（时间轴退回按停顿对齐），一共最多两次。
- 每次调用记一笔用量（data\\agent.db 的 tts_usage 表）：计费字符、花了多少（按 设置 › 云端 的单价估，以百炼账单为准）。
- 自己造音色（v1.8.12）：声音设计（写一段描述，百炼造一个新音色，带一段试听）、声音复刻（传一段 10~20 秒的录音）。
  都走 {blBase}/services/audio/tts/customization（model = voice-enrollment），创建不要钱，用它生成照常按字计费；
  音色和模型绑定（换模型就不能用），百炼要先审核（DEPLOYING → OK / UNDEPLOYED），一个账号最多 1000 个，一年没用过会被百炼删掉。
  我的音色记在 db 的 kv bl_voices（名字、描述、来源、状态），只存在本机。复刻只发你选的那段录音（Base64），只复刻自己的或 AI 生成的声音。
- 表达：语速、音调、音量、目标语言，读音词典（hot_fix：多音字按拼音念、词语替换，只发这次文案里出现的词）。
"""
import asyncio
import base64
import io
import json
import re
import time
import wave
from datetime import datetime

import httpx

from . import db, paths, settings

SR = 24000
PATH = "/services/audio/tts/SpeechSynthesizer"
CUSTOM = "/services/audio/tts/customization"
QUOTA = 1000                       # 一个百炼账号的自定义音色上限（声音设计和复刻共用）
DESIGN_TEXT = "大家好，欢迎来到这一期的 AI 工具实测，今天我们聊三个最近很火的新工具。"     # 声音设计的默认试听句（15~200 字）
LANGS = [("", "自动"), ("zh", "中文"), ("en", "英文"), ("ja", "日语"), ("ko", "韩语"), ("fr", "法语"), ("de", "德语"), ("es", "西班牙语"),
         ("ru", "俄语"), ("pt", "葡萄牙语"), ("it", "意大利语"), ("th", "泰语"), ("vi", "越南语"), ("id", "印尼语"), ("ms", "马来语"),
         ("fil", "菲律宾语"), ("ar", "阿拉伯语")]
PINYIN = re.compile(r"^[a-zü]+[1-5](?: [a-zü]+[1-5])*$")
TRY_TEXT = "你好，我是这个音色。这句话用来试听，听听合不合适。"      # 试听固定念这一句（20 来个字，一次不到一分钱）
FLASH_TOKEN = (1.5, 12.0)          # Flash 按 token 计费：输入、输出 元/百万 token（千问平台价格页，2026-09-22 起）

# 音色要和模型对得上（不能跨模型混用）。风格是按官方音色列表 / 试听样例写的，以「试听」为准
VOICES = {
    "qwen-audio-3.1-tts-plus": [
        {"id": "longanlingxin_v3.1", "name": "龙安灵心", "g": "女", "d": "温柔知心，娓娓道来"},
        {"id": "longanhuan_v3.1", "name": "龙安欢", "g": "女", "d": "活泼有感染力，带气氛"},
        {"id": "longanfengyue_v3.1", "name": "龙安风悦", "g": "女", "d": "平和自然，播报、叙述"},
        {"id": "xunanchuan_v3.1", "name": "许南川", "g": "男", "d": "磁性沉稳，解说、旁白"},
    ],
    "qwen-audio-3.1-tts-flash": [
        {"id": "longanlingxin_v3.1", "name": "龙安灵心", "g": "女", "d": "温柔知心（也会方言）"},
        {"id": "longanhuan_v3.1", "name": "龙安欢", "g": "女", "d": "活泼（也会方言）"},
        {"id": "longanfengyue_v3.1", "name": "龙安风悦", "g": "女", "d": "平和自然（也会方言）"},
        {"id": "xunanchuan_v3.1", "name": "许南川", "g": "男", "d": "磁性叙述（也会方言）"},
        {"id": "anmingyuan_v3.1", "name": "安明远", "g": "男", "d": "清亮自然，旁白、有声书"},
        {"id": "huozhuoshi_v3.1", "name": "霍拙石", "g": "男", "d": "清亮，有声书、旁白"},
        {"id": "yuxiaoyun_v3.1", "name": "于小云", "g": "女", "d": "元气亲切，广告、旁白"},
        {"id": "xieshurou_v3.1", "name": "谢舒柔", "g": "女", "d": "柔和知性，有声书、旁白"},
        {"id": "xuyuyuan_v3.1", "name": "许玉远", "g": "女", "d": "知性成熟，新闻、旁白"},
        {"id": "wenhuaizhi_v3.1", "name": "闻怀之", "g": "女", "d": "稳重成熟，新闻、有声书"},
        {"id": "guyunshu_v3.1", "name": "顾云舒", "g": "女", "d": "成熟稳重，电台、旁白"},
        {"id": "baianran_v3.1", "name": "白安然", "g": "女", "d": "低沉浑厚，配音讲解"},
        {"id": "xuyanchu_v3.1", "name": "许言初", "g": "女", "d": "沉稳磁性，新闻、有声书"},
        {"id": "anxiaolan_v3.1", "name": "安小岚", "g": "女", "d": "清甜纯净，有声书、新闻"},
        {"id": "yeqinghe_v3.1", "name": "叶清禾", "g": "女", "d": "亲切温柔，有声书、广告"},
        {"id": "wenhuaiqing_v3.1", "name": "温怀清", "g": "女", "d": "清亮柔和，故事、新闻"},
    ],
}
DEFAULT_MODEL = "qwen-audio-3.1-tts-plus"
# 文案里可以加的标签（官方：控制类 23 个 + 富语言类 7 个），写成 [excited] 这样。字幕里去掉
TAGS = ("sad|amazed|deep and loud shouting|trembling|angry|excited|sarcastic|curious|like dracula|bored|tired|scornful|shouting|asmr|"
        "panicked|mischievously|empathetic|whispers|reluctantly|crying|serious|very slowly|very fast|"
        "gasp|sighing|clears throat|giggles|laughing|cough|snorts")
TAG_RE = re.compile(r"\[(?:" + TAGS + r")\]", re.I)
CJK = re.compile(r"[㐀-鿿豈-﫿]")


class CloudError(RuntimeError):
    def __init__(self, msg, status=0, code="", param=False):
        super().__init__(msg)
        self.status, self.code, self.param = status, code, param


class Cancelled(Exception):
    pass


# ---------------- 设置 ----------------
def model():
    return (settings.S.get("blModel") or DEFAULT_MODEL).strip()


def system_voices(m=None):
    m = m or model()
    return [dict(v, kind="system") for v in (VOICES.get(m) or VOICES[DEFAULT_MODEL])]


def mine(m=None, ok_only=False):
    """我造的音色（声音设计、复刻），只列这个模型的（音色和模型绑定）。"""
    m = m or model()
    return [v for v in (db.kv_get("bl_voices") or []) if v.get("model") == m and (not ok_only or v.get("status") == "OK")]


def voices(m=None):
    """生成时能用的：百炼现成的 + 我造的里审核通过的。"""
    return system_voices(m) + [dict(v, g=v.get("g") or "", d=v.get("prompt") or v.get("src") or "") for v in mine(m, True)]


def find_voice(vid, m=None):
    return next((v for v in voices(m) if v["id"].lower() == str(vid or "").lower()), None)


def base():
    return (settings.S.get("blBase") or "https://dashscope.aliyuncs.com/api/v1").strip().rstrip("/")


def endpoint():
    return base() + PATH


def key():
    return settings.get_secret("blKey")


def price():
    try:
        return max(0.0, float(settings.S.get("blPrice", 1.4)))
    except (TypeError, ValueError):
        return 1.4


def strip_tags(s):
    return re.sub(r"\s{2,}", " ", TAG_RE.sub("", s or "")).strip()


def merge_tags(segs):
    """只有标签、没有字的一块（比如句末单独一个 [laughing]）并到前一块（没有前一块就并到后一块），时间轴里不单独占一行。"""
    out, carry = [], ""
    for s in segs:
        if not strip_tags(s["text"]):
            if out:
                out[-1] = dict(out[-1], text=out[-1]["text"] + s["text"], gap=s["gap"], kind=s["kind"])    # 停顿按它后面的（可能是换段）
            else:
                carry += s["text"]
            continue
        if carry:
            s = dict(s, text=carry + s["text"])
            carry = ""
        out.append(s)
    return out


# ---------------- 估价、用量 ----------------
def raw_chars(text):
    return len(re.sub(r"\s+", "", text or ""))


def estimate(text):
    """生成前估计：计费字符、多少钱。没实测过时按汉字算 2 个字符估（偏高一点）；生成过一次就按百炼实际返回的比例估。"""
    raw = raw_chars(text)
    r = db.kv_get("bl_ratio") or {}
    if r.get("ratio") and r.get("model") == model():
        bill = round(raw * float(r["ratio"]))
    else:
        bill = raw + len(CJK.findall(text or ""))
    return {"chars": raw, "bill": bill, "cny": round(bill * price() / 10000, 4), "price": price(), "measured": bool(r.get("ratio"))}


def cost(usage, text):
    """这一次花了多少（元）：按字符计费的（Plus）用 usage.characters × 单价；只有 token 的（Flash）按 token 单价；都没有按估的。"""
    ch = int(usage.get("characters") or 0)
    if ch:
        return ch, ch * price() / 10000
    tin, tout = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    if tin or tout:
        return 0, (tin * FLASH_TOKEN[0] + tout * FLASH_TOKEN[1]) / 1e6
    e = estimate(text)
    return e["bill"], e["cny"]


def record(voice, text, usage, purpose, audio_s):
    bill, cny = cost(usage or {}, text)
    if usage and usage.get("characters") and raw_chars(text):
        db.kv_set("bl_ratio", {"ratio": round(int(usage["characters"]) / raw_chars(text), 4), "model": model(), "ts": time.time()})
    db.insert("tts_usage", {"ts": time.time(), "model": model(), "voice": voice, "chars": raw_chars(text), "bill": bill,
                            "tin": int((usage or {}).get("input_tokens") or 0), "tout": int((usage or {}).get("output_tokens") or 0),
                            "cny": round(cny, 5), "audio_s": round(audio_s, 2), "purpose": purpose})
    return bill, cny


def month():
    start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    r = db.one("SELECT COUNT(*) n, COALESCE(SUM(cny),0) cny, COALESCE(SUM(bill),0) bill FROM tts_usage WHERE ts>=?", (start,)) or {}
    return {"n": int(r.get("n") or 0), "cny": round(float(r.get("cny") or 0), 4), "bill": int(r.get("bill") or 0)}


def public():
    r = db.kv_get("bl_ratio") or {}
    allmine = db.kv_get("bl_voices") or []
    return {"key": bool(key()), "model": model(), "voices": system_voices(), "mine": mine(), "known": model() in VOICES, "price": price(),
            "max": int(settings.S.get("blMax") or 2000), "ratio": r.get("ratio") if r.get("model") == model() else None,
            "month": month(), "hotfix": hotfix(), "langs": LANGS, "count": len(allmine), "quota": QUOTA, "design_text": DESIGN_TEXT,
            "synced": (db.kv_get("bl_synced") or {}).get("ts")}


# ---------------- 出错时说人话 ----------------
def explain(status, code="", msg=""):
    c, m = (code or "").lower().replace(" ", ""), (msg or "")[:200]
    if status == 401 or "invalidapikey" in c or "invalid_api_key" in c or "notauthorized" in c:
        return CloudError("百炼 API Key 不对（或者 Key 和接口地址不是同一个地域 / 业务空间）：到 设置 › 云端 重新填北京地域的 Key", status, code)
    if "arrearage" in c or "out_of_service" in c or "insufficient" in c:
        return CloudError("百炼账户欠费或余额不足：到百炼控制台充值后再生成", status, code)
    if "datainspection" in c or "data_inspection" in c:
        return CloudError("文案被百炼的内容安全检测拦下了：改改措辞再试", status, code)
    if status == 403 or "accessdenied" in c or "access_denied" in c:
        return CloudError(f"这个 Key 不能调用 {model()}（没开通、模型名写错，或者 Key 限定了模型）：看 设置 › 云端 的模型名", status, code)
    if status == 429 or "throttling" in c or "ratequota" in c or "rate_limit" in c:
        return CloudError("百炼说调用太频繁（限流）：过一两分钟再点生成", status, code)
    if status == 404 or "notfound" in c or "not_found" in c:
        return CloudError("百炼找不到这个模型或接口：看 设置 › 云端 的模型名和接口地址", status, code)
    if status >= 500:
        return CloudError(f"百炼那边出错了（{status}）：过一会再试", status, code)
    if status == 400 or "invalidparameter" in c:
        long_ = re.search(r"length|too long|exceed|长度|过长|超过", m, re.I)
        return CloudError(f"百炼说参数不对：{m or code}" + ("。文案太长就把 设置 › 云端 的「一次最多发多少字」调小" if long_ else ""),
                          status, code, param=True)
    return CloudError(f"百炼返回 {status} {code}：{m}", status, code)


def _scrub(s, k):
    s = str(s or "")
    return s.replace(k, "***") if k else s


def _err_from_body(status, raw, k):
    try:
        j = json.loads(raw)
    except Exception:
        m = re.search(r"data:\s*(\{.*\})", raw or "")
        try:
            j = json.loads(m.group(1)) if m else {}
        except Exception:
            j = {}
    return explain(status, _scrub(j.get("code"), k), _scrub(j.get("message") or (raw or "")[:200], k))


# ---------------- 调一次 ----------------
def expr_input(opts, text):
    """表达参数 → 请求里的字段：跟默认值一样的不发；读音词典只发这次文案里出现的词。"""
    o, out = opts or {}, {}
    try:
        r, p, vol = float(o.get("rate") or 1.0), float(o.get("pitch") or 1.0), int(o.get("volume") if o.get("volume") not in (None, "") else 50)
    except (TypeError, ValueError):
        r, p, vol = 1.0, 1.0, 50
    r, p, vol = min(2.0, max(0.5, r)), min(2.0, max(0.5, p)), min(100, max(0, vol))
    if abs(r - 1.0) > 1e-6:
        out["rate"] = round(r, 2)
    if abs(p - 1.0) > 1e-6:
        out["pitch"] = round(p, 2)
    if vol != 50:
        out["volume"] = vol
    if o.get("lang") in dict(LANGS) and o.get("lang"):
        out["language_hints"] = [o["lang"]]
    hf = hotfix()
    pr = {w: py for w, py in hf["pronunciation"].items() if w in (text or "")}
    rp = {w: t for w, t in hf["replace"].items() if w in (text or "")}
    if pr or rp:
        out["hot_fix"] = {**({"pronunciation": [{w: py} for w, py in pr.items()]} if pr else {}),
                          **({"replace": [{w: t} for w, t in rp.items()]} if rp else {})}
    return out


async def synth(text, voice, instruction="", seed=0, words=True, stop=None, progress=None, opts=None):
    """念一段字（流式）。返回 {pcm, sr, sents:[{text, a0, a1, words}], usage}。a0/a1 是这一句在 pcm 里的采样位置。
    stop()：返回真就马上断开，抛 Cancelled。progress(已念完的字数, 已收到的采样数, 正在念的那句)。出错抛 CloudError（只试一次）。
    opts：语速 rate、音调 pitch、音量 volume、目标语言 lang（读音词典自动带上）。"""
    k = key()
    if not k:
        raise CloudError("还没填百炼 API Key：到 设置 › 云端 填好再生成")
    inp = {"text": text, "voice": voice, "format": "pcm", "sample_rate": SR}
    if instruction:
        inp["instruction"] = instruction
    if seed:
        inp["seed"] = int(seed) % 65536
    if words:
        inp["word_timestamp_enabled"] = True
    inp.update(expr_input(opts, text))
    body = {"model": model(), "input": inp}
    hdr = {"Authorization": f"Bearer {k}", "Content-Type": "application/json", "X-DashScope-SSE": "enable"}
    pcm, sents, by_i, usage, url, done_chars = bytearray(), [], {}, {}, "", 0
    tmo = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=tmo) as c:
            async with c.stream("POST", endpoint(), json=body, headers=hdr) as r:
                if r.status_code != 200:
                    raw = (await r.aread()).decode("utf-8", "replace")
                    raise _err_from_body(r.status_code, raw, k)
                async for line in r.aiter_lines():
                    if stop and stop():
                        raise Cancelled()
                    if not line.startswith("data:"):
                        continue
                    try:
                        j = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if j.get("code") and not j.get("output"):          # 流到一半出错（event:error）
                        raise explain(int(j.get("status_code") or 400), _scrub(j.get("code"), k), _scrub(j.get("message"), k))
                    o = j.get("output") or {}
                    for kk, vv in (j.get("usage") or {}).items():
                        if isinstance(vv, (int, float)):
                            usage[kk] = max(usage.get(kk, 0), vv)
                    sen = o.get("sentence") or {}
                    idx = sen.get("index")
                    if idx is not None and idx not in by_i:
                        by_i[idx] = {"text": o.get("original_text") or "", "a0": len(pcm) // 2, "a1": None, "words": []}
                        sents.append(by_i[idx])
                    cur = by_i.get(idx)
                    if cur is not None:
                        if o.get("original_text") and not cur["text"]:
                            cur["text"] = o["original_text"]
                        if sen.get("words"):
                            cur["words"] = sen["words"]
                    data = (o.get("audio") or {}).get("data")
                    if data:
                        pcm += base64.b64decode(data)
                    if (o.get("audio") or {}).get("url"):
                        url = o["audio"]["url"]
                    if cur is not None and o.get("type") == "sentence-end":
                        cur["a1"] = len(pcm) // 2
                        done_chars += len(cur["text"])
                    if progress:
                        progress(done_chars, len(pcm) // 2, cur["text"] if cur else "")
            if not pcm and url:                          # 没走流式（或者没给音频块）：从结果链接下（24 小时有效）
                r2 = await c.get(url)
                if r2.status_code == 200:
                    pcm = bytearray(r2.content)
    except (CloudError, Cancelled):
        raise
    except httpx.ConnectError:
        raise CloudError("连不上百炼：网断了，或者 设置 › 云端 的接口地址填错了") from None
    except httpx.TimeoutException:
        raise CloudError("百炼超过 2 分钟没回音：这次停了，过一会再试") from None
    except httpx.HTTPError as e:
        raise CloudError("和百炼的连接断了：" + _scrub(type(e).__name__, k)) from None
    if len(pcm) % 2:
        pcm = pcm[:-1]
    if not pcm:
        raise CloudError("百炼没返回声音（返回成功但是空的）：换个音色或者过一会再试")
    for s in sents:
        if s["a1"] is None:
            s["a1"] = len(pcm) // 2
    return {"pcm": pcm, "sr": SR, "sents": sents, "usage": usage}


async def synth_once_more(text, voice, instruction="", seed=0, stop=None, progress=None, opts=None):
    """要字级时间戳；这个音色不支持（报参数错）就去掉时间戳再试一次。返回 (结果, 有没有要时间戳)。"""
    try:
        return await synth(text, voice, instruction, seed, True, stop, progress, opts), True
    except CloudError as e:
        if not (e.param and re.search(r"timestamp|word", str(e), re.I)):
            raise
    return await synth(text, voice, instruction, seed, False, stop, progress, opts), False


# ---------------- 字级时间戳 → 每句的开始、结束 ----------------
def _norm(s):
    """去掉空白和 [标签]，返回 (留下的字, 原文每个位置之前留下了几个字)。"""
    s = s or ""
    tag = [False] * len(s)
    for m in TAG_RE.finditer(s):
        for i in range(m.start(), m.end()):
            tag[i] = True
    keep, before = [], []
    for i, ch in enumerate(s):
        before.append(len(keep))
        if not tag[i] and not ch.isspace():
            keep.append(ch)
    before.append(len(keep))
    return "".join(keep), before


def word_spans(text, ranges, sents, sr):
    """用百炼返回的字级时间戳算每句（ranges：每句在 text 里的 [开始, 结束) 位置）的开始、结束（秒，相对这一块）。
    返回 (spans, est, got)，和 tts.whole_timeline 一样；时间戳不够用（一半以上的句子对不上）返回 None，调用的地方改按停顿对齐。"""
    N, before = _norm(text)
    owner = []
    for si, (a, b) in enumerate(ranges):
        owner += [si] * (before[b] - before[a])
    if len(owner) != len(N):
        return None
    t0 = [None] * len(ranges)
    t1 = [None] * len(ranges)
    cursor = 0
    for s in sents:
        ws = s.get("words") or []
        if not ws:
            continue
        ns, sb = _norm(s.get("text") or "")
        at = N.find(ns, cursor) if ns else -1
        if at < 0:
            continue
        cursor = at + len(ns)
        off = s["a0"] / sr
        rel = off > 0.3 and float(ws[0].get("begin_time") or 0) / 1000 < off * 0.5     # 时间是从这句开始算的，还是从整段开始算的
        for w in ws:
            try:
                bi = int(w.get("begin_index") or 0)
                b, e = float(w["begin_time"]) / 1000, float(w["end_time"]) / 1000
            except (KeyError, TypeError, ValueError):
                continue
            p = at + sb[min(max(bi, 0), len(sb) - 1)]
            if p >= len(owner):
                continue
            if rel:
                b, e = b + off, e + off
            si = owner[p]
            t0[si] = b if t0[si] is None else min(t0[si], b)
            t1[si] = e if t1[si] is None else max(t1[si], e)
    have = sum(1 for x in t0 if x is not None)
    if not ranges or have * 2 < len(ranges):
        return None
    total = max((s["a1"] or 0) for s in sents) / sr if sents else 0.0       # 没对上时间戳的句子：夹在前后两句中间（标 est）
    spans, est = [], []
    for i in range(len(ranges)):
        if t0[i] is not None:
            spans.append([t0[i], max(t0[i], t1[i])])
            est.append(False)
        else:
            prev = spans[-1][1] if spans else 0.0
            nxt = next((t0[k] for k in range(i + 1, len(ranges)) if t0[k] is not None), total)
            spans.append([prev, max(prev, nxt)])
            est.append(True)
    got = [(spans[i][1], max(spans[i][1], spans[i + 1][0])) for i in range(len(spans) - 1)]
    return spans, est, got


# ---------------- 试听 ----------------
TRY_DIR = paths.DATA / "tts" / "try"
_try_lock = asyncio.Lock()


def _try_file(vid):
    return TRY_DIR / f"{re.sub(r'[^A-Za-z0-9._-]', '_', model())}_{re.sub(r'[^A-Za-z0-9._-]', '_', vid)}.wav"


async def preview(vid):
    """用固定的一句话试听一个音色。念过的存在 data\\tts\\try，再点不花钱。声音设计的音色用创建时百炼给的那段试听（不花钱）。
    返回 (WAV 字节, 是不是存着的)。"""
    v = find_voice(vid)
    m = next((x for x in mine() if x["id"] == vid), None)
    if not v and m and m.get("kind") == "design" and _try_file(vid).exists():
        return _try_file(vid).read_bytes(), True          # 刚设计好、还在审核：先听创建时给的那段
    if not v:
        raise CloudError("这个音色百炼还在审核，过一会再试" if m and m.get("status") == "DEPLOYING" else
                         "这个音色没通过百炼的审核，用不了" if m and m.get("status") == "UNDEPLOYED" else "没有这个音色", 400)
    f = _try_file(v["id"])
    if f.exists():
        return f.read_bytes(), True
    async with _try_lock:
        if f.exists():
            return f.read_bytes(), True
        r = await synth(TRY_TEXT, v["id"], "", 1, False)
        record(v["id"], TRY_TEXT, r["usage"], "试听", len(r["pcm"]) / 2 / SR)
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(bytes(r["pcm"]))
        TRY_DIR.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(b.getvalue())
        tmp.replace(f)
        return b.getvalue(), False


# ---------------- 读音词典（hot_fix，v1.8.12） ----------------
def hotfix():
    h = db.kv_get("bl_hotfix") or {}
    return {"pronunciation": dict(h.get("pronunciation") or {}), "replace": dict(h.get("replace") or {})}


def set_hotfix(body):
    """存读音词典：pronunciation {词: 拼音带声调数字}、replace {词: 换成的字}。合计最多 200 条，拼音写成 tian1 qi4（轻声写 5）。"""
    out = {"pronunciation": {}, "replace": {}}
    for k in out:
        for w, t in (body.get(k) or {}).items():
            w, t = str(w or "").strip()[:20], re.sub(r"\s+", " ", str(t or "").strip().lower() if k == "pronunciation" else str(t or "").strip())[:40]
            if not w or not t:
                continue
            if k == "pronunciation" and not PINYIN.match(t.replace("v", "ü")):
                raise CloudError(f"「{w}」的拼音写成 tian1 qi4 这样：每个字拼音后面跟声调数字 1~5（轻声写 5），字之间空格", 400)
            out[k][w] = t.replace("v", "ü") if k == "pronunciation" else t
    if len(out["pronunciation"]) + len(out["replace"]) > 200:
        raise CloudError("读音词典最多 200 条", 400)
    db.kv_set("bl_hotfix", out)
    return out


# ---------------- 自己造音色：声音设计、声音复刻（v1.8.12） ----------------
def _prefix():
    """音色名前缀：百炼只认数字和英文字母、不超过 10 个。"""
    n, s = int(time.time() * 1000) % 36 ** 6, ""
    while n:
        n, r = divmod(n, 36)
        s = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + s
    return ("ag" + s)[:10]


async def _custom(inp, params=None, timeout=60):
    """调一次音色管理接口（只试一次）。返回 output。"""
    k = key()
    if not k:
        raise CloudError("还没填百炼 API Key：到 设置 › 云端 填好再用")
    body = {"model": "voice-enrollment", "input": inp, **({"parameters": params} if params else {})}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=timeout, write=60.0, pool=10.0)) as c:
            r = await c.post(base() + CUSTOM, json=body, headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"})
    except httpx.ConnectError:
        raise CloudError("连不上百炼：网断了，或者 设置 › 云端 的接口地址填错了") from None
    except httpx.TimeoutException:
        raise CloudError("百炼太久没回音：这次停了，过一会再试") from None
    except httpx.HTTPError as e:
        raise CloudError("和百炼的连接断了：" + type(e).__name__) from None
    if r.status_code != 200:
        raise _err_from_body(r.status_code, r.text, k)
    try:
        return r.json().get("output") or {}
    except Exception:
        raise CloudError("百炼返回的不是 JSON：" + r.text[:120]) from None


def _save_mine(vs):
    db.kv_set("bl_voices", vs[-QUOTA:])


def _upd(vid, **kw):
    vs = db.kv_get("bl_voices") or []
    for v in vs:
        if v["id"] == vid:
            v.update(kw)
    _save_mine(vs)
    return next((v for v in vs if v["id"] == vid), None)


_watching = set()


async def watch(vid, tries=45, every=2.0):
    """新造的音色百炼要先审核：每 2 秒查一次状态，查到 OK / UNDEPLOYED 就停（最多 90 秒；之后点「同步」再查）。"""
    if vid in _watching:
        return
    _watching.add(vid)
    try:
        for _ in range(tries):
            await asyncio.sleep(every)
            try:
                o = await _custom({"action": "query_voice", "voice_id": vid}, timeout=20)
            except CloudError as e:
                if e.status in (400, 404) and "not" in (e.code or "").lower():
                    _upd(vid, status="GONE")
                    return
                continue
            st = o.get("status") or ""
            if st and st != "DEPLOYING":
                _upd(vid, status=st, checked=time.time())
                return
    finally:
        _watching.discard(vid)


def _add(v):
    vs = [x for x in (db.kv_get("bl_voices") or []) if x["id"] != v["id"]]
    vs.append(v)
    _save_mine(vs)
    asyncio.get_event_loop().create_task(watch(v["id"]))
    return v


async def design(name, prompt, preview_text="", lang="zh", g=""):
    """声音设计：一段描述 → 百炼造一个新音色（不要钱），带一段试听（存起来，试听不花钱）。"""
    name, prompt = str(name or "").strip()[:20], str(prompt or "").strip()
    preview_text = str(preview_text or "").strip() or DESIGN_TEXT
    if not prompt:
        raise CloudError("写一段声音描述：性别、年龄、音色、语速、情绪、用在哪", 400)
    if len(prompt) > 500:
        raise CloudError("声音描述最多 500 字", 400)
    if not 15 <= len(preview_text) <= 200:
        raise CloudError("试听的那句要 15~200 字", 400)
    lang = lang if lang in ("zh", "en") else "zh"
    o = await _custom({"action": "create_voice", "target_model": model(), "voice_prompt": prompt, "preview_text": preview_text,
                       "prefix": _prefix(), "language_hints": [lang]}, {"sample_rate": SR, "response_format": "wav"}, timeout=120)
    vid = o.get("voice_id")
    if not vid:
        raise CloudError("百炼没返回音色 ID")
    pa = (o.get("preview_audio") or {}).get("data")
    if pa:
        TRY_DIR.mkdir(parents=True, exist_ok=True)
        _try_file(vid).write_bytes(base64.b64decode(pa))
    return _add({"id": vid, "name": name or "设计的音色", "kind": "design", "model": model(), "prompt": prompt, "preview_text": preview_text,
                 "lang": lang, "g": g, "status": "DEPLOYING", "created": time.time()})


def sniff(b):
    """看录音是什么格式（WAV / MP3 / M4A），WAV 顺便读时长和采样率。"""
    if b[:4] == b"RIFF" and b[8:12] == b"WAVE":
        try:
            with wave.open(io.BytesIO(b)) as w:
                return {"mime": "audio/wav", "dur": w.getnframes() / w.getframerate(), "sr": w.getframerate()}
        except Exception:
            return {"mime": "audio/wav", "dur": None, "sr": None}
    if b[:3] == b"ID3" or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0):
        return {"mime": "audio/mpeg", "dur": None, "sr": None}
    if b[4:8] == b"ftyp":
        return {"mime": "audio/mp4", "dur": None, "sr": None}
    return None


async def clone(name, audio, lang="zh", denoise=False, src="", g=""):
    """声音复刻：一段 10~20 秒的录音（最长 60 秒、10 MB 以内）→ 百炼照着这个声音造一个音色（不要钱）。只发这段录音。"""
    name = str(name or "").strip()[:20]
    info = sniff(audio or b"")
    if not info:
        raise CloudError("录音要是 WAV、MP3 或 M4A", 400)
    if len(audio) > 10 * 1024 * 1024:
        raise CloudError("录音最大 10 MB（推荐 10~20 秒）", 400)
    if info["dur"] is not None:
        if info["dur"] < 3:
            raise CloudError(f"录音太短（{info['dur']:.1f} 秒）：至少要 5 秒连续清楚的说话，推荐 10~20 秒", 400)
        if info["dur"] > 60:
            raise CloudError(f"录音太长（{info['dur']:.0f} 秒）：最长 60 秒，推荐 10~20 秒", 400)
        if info["sr"] and info["sr"] < 16000:
            raise CloudError(f"录音的采样率太低（{info['sr']} Hz）：至少 16000 Hz", 400)
    lang = lang if lang in dict(LANGS) and lang else "zh"
    inp = {"action": "create_voice", "target_model": model(), "prefix": _prefix(),
           "audio": f"data:{info['mime']};base64," + base64.b64encode(audio).decode(), "language_hints": [lang]}
    if denoise:
        inp["enable_preprocess"] = True
    o = await _custom(inp, timeout=180)
    vid = o.get("voice_id")
    if not vid:
        raise CloudError("百炼没返回音色 ID")
    return _add({"id": vid, "name": name or "复刻的音色", "kind": "clone", "model": model(), "src": src, "lang": lang, "g": g,
                 "dur": round(info["dur"], 1) if info["dur"] else None, "status": "DEPLOYING", "created": time.time()})


async def remove(vid):
    """删掉一个我造的音色：百炼那边也删（省配额）；百炼说没有了也照样从本机删。"""
    try:
        await _custom({"action": "delete_voice", "voice_id": vid}, timeout=20)
    except CloudError as e:
        if e.status not in (400, 404):
            raise
    vs = [v for v in (db.kv_get("bl_voices") or []) if v["id"] != vid]
    _save_mine(vs)
    f = _try_file(vid)
    if f.exists():
        f.unlink()
    return vs


def rename(vid, name):
    name = str(name or "").strip()[:20]
    if not name:
        raise CloudError("起个名字", 400)
    if not _upd(vid, name=name):
        raise CloudError("没有这个音色", 404)


async def sync():
    """和百炼对一遍：拿百炼上的音色列表（最多 1000 个），本机没有的加进来（名字先用 ID 后几位），百炼上没了的标「已删」，状态跟着更新。"""
    seen, page = {}, 0
    while page < 10:
        o = await _custom({"action": "list_voice", "page_index": page, "page_size": 100}, timeout=30)
        lst = o.get("voice_list") or []
        for v in lst:
            if v.get("voice_id"):
                seen[v["voice_id"]] = v
        if len(lst) < 100:
            break
        page += 1
    vs = db.kv_get("bl_voices") or []
    have = {v["id"] for v in vs}
    added = 0
    for vid, v in seen.items():
        tm = v.get("target_model") or next((m for m in sorted(VOICES, key=len, reverse=True) if vid.startswith(m + "-")), "")
        if not tm.startswith("qwen-audio-"):
            continue                                   # CosyVoice 这些别的模型的不管
        if vid not in have:
            vs.append({"id": vid, "name": "百炼上的音色 " + vid.rsplit("-", 1)[-1][:6], "kind": "design" if "-vd-" in vid else "clone",
                       "model": tm, "prompt": v.get("voice_prompt") or "", "src": "百炼上已有的", "status": v.get("status") or "OK",
                       "created": time.time()})
            added += 1
    gone = 0
    for v in vs:
        if v["id"] in seen:
            v["status"] = seen[v["id"]].get("status") or v.get("status")
        elif seen and v.get("status") != "GONE" and time.time() - (v.get("created") or 0) > 300:     # 列表是空的（可能查错了地方）不动；刚造的也不动
            v["status"] = "GONE"
            gone += 1
    _save_mine(vs)
    db.kv_set("bl_synced", {"ts": time.time(), "n": len(seen)})
    return {"added": added, "gone": gone, "total": len(seen)}
