"""配音（Qwen3-TTS 1.7B，Apache 2.0，可以商用）：后端这边的管家 + 接口。界面上的「配音」页用它。

- 配音服务（app/tts_server.py）在 tts-env 里跑，端口 8092。用到才启动；闲置 ttsIdle 分钟（默认 10）关掉；
  让路（在玩游戏、别的程序占显存）时直接关掉，正在生成就停下这次。不联网：模型都在 models\\tts。
- 两个模型：预设音色 CustomVoice（9 个音色，5 个中文，一句话控制语气）、描述音色 VoiceDesign（一段文字描述造音色）。
  不接克隆（Base）。以后接克隆时界面上要写明：不克隆任何真人的声音。
- 长文案：按句子切开一句一句生成，句子之间停 ttsGap 秒、段落之间停 ttsParaGap 秒，拼成一个 WAV；
  同时出时间轴（每句的开始、结束、原文），JSON 和 SRT 各一份，做视频时字幕和画面按它对齐。
- 生成完先放 data\\tts（试听用，只留最近一次）；点「保存」才放进「配音输出」，一次一个文件夹，名字带日期和音色名。
- 我的音色：描述音色的「描述 + 随机种子」存起来，下次一键用。存在数据库里（data），不进仓库。
- 云端引擎（v1.8.11，app/tts_cloud.py）：百炼的 Qwen-Audio-3.1-TTS-Plus。页面上选「百炼云端」就走它，不用显卡、不启动配音服务；
  输出完全一样（WAV、时间轴 JSON、SRT、文案），时间轴用百炼返回的字级时间戳，没有就按停顿对齐。
- 时间轴（v1.8.14）：百炼的字级时间戳（只有系统音色给）→ 本地对齐（Qwen3-ForcedAligner-0.6B，在配音服务里跑，云端、本地都用）
  → 都不行才按停顿猜（猜的不补静音）。试听的那段可以「重新对齐」（不用重新生成、不花钱）。
"""
import asyncio
import base64
import difflib
import io
import json
import os
import random
import re
import shutil
import time
import wave
from datetime import datetime

import httpx
import numpy as np
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, Response

from . import db, feed, paths, settings, tts_cloud
from .models import M, Proc

# 预设音色（CustomVoice 自带的 9 个；名字不分大小写）。每个音色用母语最好，但都能说别的语言
SPEAKERS = [
    {"id": "Vivian", "name": "Vivian", "d": "女声 · 明亮、略带锐气的年轻女声", "lang": "中文"},
    {"id": "Serena", "name": "Serena", "d": "女声 · 温柔、温暖的年轻女声", "lang": "中文"},
    {"id": "Uncle_Fu", "name": "Uncle_Fu", "d": "男声 · 低沉醇厚的成熟男声", "lang": "中文"},
    {"id": "Dylan", "name": "Dylan", "d": "男声 · 清亮自然的北京青年", "lang": "中文 · 北京话"},
    {"id": "Eric", "name": "Eric", "d": "男声 · 活泼、略带沙哑的成都男声", "lang": "中文 · 四川话"},
    {"id": "Ryan", "name": "Ryan", "d": "男声 · 节奏感强", "lang": "英文"},
    {"id": "Aiden", "name": "Aiden", "d": "男声 · 阳光的美式男声", "lang": "英文"},
    {"id": "Ono_Anna", "name": "Ono_Anna", "d": "女声 · 俏皮轻快", "lang": "日语"},
    {"id": "Sohee", "name": "Sohee", "d": "女声 · 温暖、情感丰富", "lang": "韩语"},
]
LANGS = [("Chinese", "中文"), ("English", "英文"), ("Auto", "自动")]
MODEL_INFO = {"custom": "预设音色（CustomVoice）", "design": "描述音色（VoiceDesign）"}
LICENSE = "Apache-2.0"
NEED_GB = 6.0          # 一个 1.7B 配音模型大概占多少显存（bf16 + 运行时，估的；真机实测后改）
MAX_CHARS = 20000
# 「试试是不是同一个人」：同一段描述 + 同一个种子，念两段内容完全不同的话，前后听像不像一个人
SAME_TEXT = "今天我们来聊一聊最近很火的几个 AI 工具，看看哪个真的好用。\n\n说完正事，再讲讲我这周写代码的时候踩过的一个坑。"
DRAFT = paths.DATA / "tts"

END = "。！？!?…"
CLOSE = "”’\"'」』）)】》"
SOFT = "，,、；;：:"


# ---------------- 切句子 ----------------
def _speak(s):
    return bool(re.search(r"\w", s))


def soft_split(s, maxlen=60, piece=40):
    """太长的句子（超过 maxlen 字）在逗号、顿号、分号处再切开，每块不超过 piece 字左右；没有逗号就硬切。"""
    if len(s) <= maxlen:
        return [s]
    parts = re.findall(r"[^，,、；;：:]+[，,、；;：:]*|[，,、；;：:]+", s)
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) > piece:
            out.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        out.append(cur)
    res = []
    for o in out:
        while len(o) > maxlen:
            cut = o.rfind(" ", 0, piece)
            cut = cut if cut > piece // 2 else piece
            res.append(o[:cut])
            o = o[cut:]
        if o:
            res.append(o)
    final = []
    for o in (x.strip() for x in res):
        if not o:
            continue
        if final and not _speak(o):
            final[-1] += o
        else:
            final.append(o)
    return final


def split(text, gap=0.35, para=0.7, comma=0.15):
    """文案 → [{text, gap}]。gap 是这一块念完后停几秒：句子之间 gap，段落（空一行）之间 para，
    长句在逗号处切开的块之间 comma，最后一块 0。只有标点没有字的块并到前一块里。"""
    out = []
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for p in re.split(r"\n\s*\n", text):
        sents = []
        for line in p.split("\n"):
            line = line.strip()
            buf, i = "", 0
            while i < len(line):
                ch = line[i]
                buf += ch
                if ch in END or (ch == "." and (i + 1 == len(line) or line[i + 1].isspace())):
                    while i + 1 < len(line) and (line[i + 1] in END or line[i + 1] in CLOSE or line[i + 1] == "."):
                        i += 1
                        buf += line[i]
                    sents.append(buf.strip())
                    buf = ""
                i += 1
            if buf.strip():
                sents.append(buf.strip())
        added = False
        for s in sents:
            if not _speak(s):
                if out:
                    out[-1]["text"] += s
                continue
            for piece in soft_split(s):
                out.append({"text": piece, "gap": comma, "kind": "comma"})
                added = True
            out[-1].update(gap=gap, kind="sent")
        if added:
            out[-1].update(gap=para, kind="para")
    if out:
        out[-1].update(gap=0.0, kind="end")
    return out


# ---------------- 时间轴 ----------------
def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(segs):
    return "\n".join(f"{s['i']}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}\n" for s in segs)


def read_wav(b):
    with wave.open(io.BytesIO(b), "rb") as f:
        if f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise RuntimeError("配音服务返回的音频格式不对（要 16 位单声道）")
        return f.getframerate(), f.readframes(f.getnframes())


def write_wav(path, sr, pcm):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(bytes(pcm))


def safe_name(s, n=24):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", str(s or "")).strip(" .")
    return s[:n] or "配音"


def yuan(x):
    return "不到 1 分钱" if 0 < x < 0.005 else f"¥{x:.2f}"


def mmss(sec):
    sec = int(round(sec))
    return f"{sec // 60} 分 {sec % 60:02d} 秒" if sec >= 60 else f"{sec} 秒"


class Stopped(Exception):
    pass


# ---------------- 整段一次生成（v1.8.9）：一段话一次念完，语气连贯；时间轴按停顿对齐 ----------------
# 一句一句生成时每句都是单独采样，9 句话 9 种语气（作者实测 v1.8.8）。Qwen3-TTS 技术报告说能一次念 10 分钟以上、韵律前后一致，
# 所以默认整段一次生成；太长的（超过 WHOLE_MAX 字）在空行处、再不行在句号处分成几大块。
WHOLE_MAX = 2600          # 一块最多多少字：中文一秒 4 字多，2600 字大约 10 分钟（v1.8.10 从 1200 放大：作者的视频不超过 10 分钟，一次念完）


def whole_chunks(segs, limit=WHOLE_MAX):
    """把 split() 切好的句子按顺序装进几大块：优先在换段处断开，一块不超过 limit 字。返回 [[句子下标…], …]。"""
    out, cur, n = [], [], 0
    for i, sg in enumerate(segs):
        L = len(sg["text"])
        if cur and n + L > limit:
            back = max((k for k in range(len(cur)) if segs[cur[k]]["kind"] == "para"), default=None)   # 往回找最近的换段处
            if back is not None and back < len(cur) - 1 and sum(len(segs[x]["text"]) for x in cur[:back + 1]) > limit * 0.4:
                out.append(cur[:back + 1])
                cur = cur[back + 1:]
            else:
                out.append(cur)
                cur = []
            n = sum(len(segs[x]["text"]) for x in cur)
        cur.append(i)
        n += L
    if cur:
        out.append(cur)
    return out


def chunk_parts(segs, idx):
    """一块要念的字：句子按原样接起来，换段处换行；没有句末标点的（比如一行标题）补一个句号，免得和下一句连成一句念。
    返回 (字, 每句在里面的 [开始, 结束) 位置)。"""
    t, ranges = "", []
    for k, i in enumerate(idx):
        x = segs[i]["text"]
        bare = tts_cloud.TAG_RE.sub("", x).rstrip()          # 末尾的 [标签] 不算（云端：「好的。[laughing]」不再补句号）
        if not re.search(r"[。！？!?…\.；;，,、：:”’\"'」』）)】》]$", bare):
            x += "." if re.search(r"[A-Za-z0-9]$", bare) and not re.search(r"[\u4e00-\u9fff]", bare) else "。"
        ranges.append((len(t), len(t) + len(x)))
        t += x + ("\n" if segs[i]["kind"] == "para" and k < len(idx) - 1 else "")
    return t, ranges


def chunk_text(segs, idx):
    return chunk_parts(segs, idx)[0]


def find_pauses(pcm, sr, min_len=0.1):
    """音频里的停顿（[开始, 结束] 秒，不算头尾）。按 10 毫秒一格算音量，比响的那部分小很多的连续几格算停顿。"""
    a = np.frombuffer(bytes(pcm), dtype="<i2").astype(np.float32) / 32768
    hop = max(1, int(sr * 0.01))
    n = len(a) // hop
    if n < 5:
        return []
    rms = np.sqrt((a[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    thr = max(0.003, float(np.percentile(rms, 90)) * 0.06)
    q = np.concatenate(([0], (rms < thr).astype(np.int8), [0]))
    d = np.diff(q)
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(s * 0.01, e * 0.01) for s, e in zip(starts, ends) if s > 0 and e < n and (e - s) * 0.01 >= min_len]


def _align_idx(points, lens, expected, weights, skip=1.5):
    """每个句子边界（估的时间 expected，句末 weights 大、逗号处小）配一个停顿（points：停顿在哪，lens：停顿多长），顺序不能乱；
    多出来的停顿（逗号、换气）不管，配不上的边界给 None。动态规划：代价 = |停顿 − 估的时间| − 权重 × 停顿长度（句末的停顿一般更长）。
    返回每个边界配上的停顿下标。"""
    m, k = len(points), len(expected)
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(k + 1)]
    bk = [[None] * (m + 1) for _ in range(k + 1)]
    for j in range(m + 1):
        dp[0][j] = 0.0
    for i in range(1, k + 1):
        for j in range(0, m + 1):
            best, how = dp[i - 1][j] + skip, ("skip", j)
            if j:
                if dp[i][j - 1] < best:
                    best, how = dp[i][j - 1], ("extra", j - 1)
                c = dp[i - 1][j - 1] + abs(points[j - 1] - expected[i - 1]) - weights[i - 1] * lens[j - 1]
                if c < best:
                    best, how = c, ("match", j - 1)
            dp[i][j], bk[i][j] = best, how
    out, i, j = [None] * k, k, m
    while i > 0:
        how, pj = bk[i][j]
        if how == "match":
            out[i - 1] = pj
            i, j = i - 1, pj
        elif how == "skip":
            i -= 1
        else:
            j = pj
    return out


def align_pauses(pauses, expected, weights, skip=1.5):
    """（旧的接口）按停顿中点配：返回每个边界配上的停顿 (开始, 结束)，配不上的 None。"""
    got = _align_idx([(s + e) / 2 for s, e in pauses], [e - s for s, e in pauses], expected, weights, skip)
    return [pauses[j] if j is not None else None for j in got]


# 按停顿猜的时候一句话估多长：v1.8.13 以前按字数，英文、数字全算错（VoiceStudio 算 11 个字，实际念 4 个音节），句子边界配到错的停顿上。
# v1.8.14 起按音节：汉字一个字一个；英文按元音算音节（全大写的缩写一个字母一个）；数字按中文读法（646 → 六百四十六，5 个）
_SYL = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]|[A-Za-z]+|\d+(?:\.\d+)?")


def _num_syl(w):
    ip, _, dp = w.partition(".")
    n = len(dp) + (1 if dp else 0)                                  # 小数：「点」+ 一位一个
    if len(ip) > 4 or (len(ip) > 1 and ip[0] == "0") or (len(ip) == 4 and ip[:2] in ("19", "20")):
        return n + len(ip)                                           # 年份、编号：一位一个
    k, zero, L = 0, False, len(ip)
    for i, ch in enumerate(ip):
        place = L - 1 - i
        if ch == "0":
            zero = True
            continue
        if zero and k:
            k += 1                                                   # 「零」
        zero = False
        if not (ch == "1" and place == 1 and i == 0):                # 十几：不念「一」
            k += 1
        k += 1 if place else 0                                       # 十、百、千
    return n + max(1, k)


def _en_syl(w):
    n = 0
    for part in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+", w):
        if part.isupper() and len(part) <= 5:
            n += len(part)                                           # AI、PDF、CPU：一个字母一个
            continue
        p = part.lower()
        k = len(re.findall(r"[aeiouy]+", p))
        if p.endswith("e") and not p.endswith(("le", "ee")) and k > 1:
            k -= 1                                                   # 不发音的 e
        n += max(1, k)
    return n


def syllables(s):
    """一句话大概念几个音节（按停顿猜时间轴时用来估每句多长）。"""
    n = 0.0
    for m in _SYL.finditer(tts_cloud.strip_tags(s or "")):
        w = m.group()
        if w[0].isdigit():
            n += _num_syl(w)
        elif w[0].isascii():
            n += _en_syl(w) * 0.85                                   # 夹在中文里的英文念得快一点
        else:
            n += 1
    return max(0.5, n)


def _edges(pcm, sr):
    """开头、结尾各有多长没声音（秒）。"""
    r, p90 = tts_cloud._rms(pcm, sr)
    if r is None:
        return 0.0, 0.0
    loud = np.flatnonzero(r >= max(0.003, p90 * 0.06))
    if not len(loud):
        return 0.0, 0.0
    return loud[0] * 0.01, max(0.0, len(pcm) / 2 / sr - (loud[-1] + 1) * 0.01)


def whole_timeline(pcm, sr, segs, idx):
    """按停顿猜（退路：百炼没给字级时间戳、本地对齐也用不了的时候）：整块音频 → 每句的 [开始, 结束]（秒）+ 这句是不是估的 + 配上的停顿。
    v1.8.14：按音节估每句多长；先把所有停顿去掉，在"只算念字的时间"里比（停顿多的地方不再把后面的句子往后推）。
    这只是猜：猜错了不补静音（调用的地方不拿它的结果补）。"""
    dur = len(pcm) / 2 / sr
    pauses = find_pauses(pcm, sr)
    lead, tail = _edges(pcm, sr)
    syl = [syllables(segs[i]["text"]) for i in idx]
    tot = sum(syl)
    speech = max(0.1, dur - lead - tail - sum(e - s for s, e in pauses))
    sp, acc = [], 0.0                                                  # 每个停顿之前已经念了多久（不算停顿）
    for s, e in pauses:
        sp.append(s - lead - acc)
        acc += e - s
    exp, c = [], 0.0
    for L in syl[:-1]:
        c += L
        exp.append(speech * c / tot)
    w = [0.5 if segs[i]["kind"] == "comma" else 2.0 for i in idx[:-1]]
    gi = _align_idx(sp, [e - s for s, e in pauses], exp, w)
    got = [pauses[j] if j is not None else None for j in gi]

    def real(t):                                                       # 念字的时间 → 音频里的时间
        return lead + t + sum(e - s for (s, e), x in zip(pauses, sp) if x < t)

    spans, est = [], []
    for n_, _ in enumerate(idx):
        st = 0.0 if n_ == 0 else (got[n_ - 1][1] if got[n_ - 1] else real(exp[n_ - 1]))
        en = dur if n_ == len(idx) - 1 else (got[n_][0] if got[n_] else real(exp[n_]))
        spans.append([st, max(st, en)])
        est.append((n_ > 0 and not got[n_ - 1]) or (n_ < len(idx) - 1 and not got[n_]))
    return spans, est, got


def _cut_at(r, p90, pz):
    """在 pz（秒，两头放宽 50 毫秒）里找最安静的一段，返回它中间的时间：静音从这里插进去。"""
    mid = (pz[0] + pz[1]) / 2
    if r is None:
        return mid
    a, b = max(0, int(pz[0] * 100) - 5), min(len(r), int(pz[1] * 100) + 6)
    if b - a < 1:
        return mid
    seg = r[a:b]
    q = seg <= seg.min() + max(1e-4, p90 * 0.02)
    best, run, start = (0, 0), 0, 0
    for k, v in enumerate(q):
        if v:
            if not run:
                start = k
            run += 1
            if run > best[0]:
                best = (run, start)
        else:
            run = 0
    return (a + best[1] + best[0] / 2) * 0.01


def pad_pauses(pcm, sr, spans, got, gaps):
    """模型停得比设置的短：在两句中间最安静的地方补静音补够（不剪掉任何声音）。返回新的 PCM 和挪过的时间。
    got[b]：第 b 句和第 b+1 句中间没声音的那段（上一句最后一个字念完 → 下一句第一个字开始）；None = 这里不补。
    只有边界是准的（百炼逐字时间戳、本地对齐）才补：v1.8.13 以前按停顿猜的也补，猜错的地方被硬塞进静音，连声音的节奏都乱了。"""
    r, p90 = tts_cloud._rms(pcm, sr)
    adds = []
    for b, pz in enumerate(got):
        if not pz:
            continue
        have = max(0.0, pz[1] - pz[0])
        if gaps[b] > have + 0.02:
            adds.append((b, _cut_at(r, p90, pz), gaps[b] - have))
    if not adds:
        return pcm, spans
    out, last = bytearray(), 0
    for _, t, extra in adds:
        cut = max(last, min(len(pcm), int(t * sr) * 2))
        out += pcm[last:cut] + bytes(2 * int(extra * sr))
        last = cut
    out += pcm[last:]
    new = []
    for k, (st, en) in enumerate(spans):
        sh = sum(x for b, _, x in adds if b < k)
        new.append([st + sh, en + sh])
    return out, new


# ---------------- 本地对齐（v1.8.14）：Qwen3-ForcedAligner-0.6B，音频 + 原文 → 每个字的开始、结束 ----------------
# 百炼只给系统音色返回字级时间戳，自己设计、复刻的音色不给（作者 2026-10-30 的 Design-test-2）；本地整段生成也没有。
# 对齐器跑在配音服务里（tts-env，用显卡）：一次最多 180 秒，长的按 ALIGN_PIECE 秒一段一段对，每段最后两句放到下一段重对（段的开头是准的）。
ALIGN_PIECE = 150.0
ALIGN_MAX = 170.0
_PUNCT = re.compile(r"[^\w']+")


class NoAlign(Exception):
    """本地对齐用不了（没装、在让路、服务起不来、对齐出错）：退回按停顿猜。"""


def align_text(t):
    """送去对齐的字：去掉 [标签]，标点换成空格（对齐器只认字和词；不换的话「PDF、Word」会被它粘成一个词）。"""
    return _PUNCT.sub(" ", tts_cloud.strip_tags(t or "")).strip()


def map_items(texts, items, total):
    """对齐器给的字和词（[{t, s, e}]，秒）→ 每句的 [开始, 结束] + 这句是不是估的。去掉标点空白后按最长公共片段对位置，不要求一字不差。"""
    n = len(texts)
    N, owner = "", []
    for si, t in enumerate(texts):
        ns, _ = tts_cloud._norm(t)
        N += ns
        owner += [si] * len(ns)
    T, pos = "", []
    for it in items:
        ns, _ = tts_cloud._norm(str(it.get("t") or ""))
        pos.append((len(T), len(T) + len(ns)))
        T += ns
    t2n = {}
    if T and N:
        for a, b, size in difflib.SequenceMatcher(None, T, N, autojunk=False).get_matching_blocks():
            for d in range(size):
                t2n[a + d] = b + d
    t0, t1 = [None] * n, [None] * n
    for (a, b), it in zip(pos, items):
        try:
            s_, e_ = float(it["s"]), float(it["e"])
        except (KeyError, TypeError, ValueError):
            continue
        for si in {owner[t2n[p]] for p in range(a, b) if p in t2n}:
            t0[si] = s_ if t0[si] is None else min(t0[si], s_)
            t1[si] = e_ if t1[si] is None else max(t1[si], e_)
    spans, est = [], []
    for i in range(n):
        if t0[i] is not None:
            st = max(t0[i], spans[-1][1] if spans else 0.0)            # 不和上一句叠在一起
            spans.append([st, min(total, max(st, t1[i]))])
            est.append(False)
        else:                                                          # 一个字都没对上：夹在前后两句中间（标 est）
            prev = spans[-1][1] if spans else 0.0
            nxt = next((t0[k] for k in range(i + 1, n) if t0[k] is not None), total)
            spans.append([prev, max(prev, nxt)])
            est.append(True)
    return spans, est


def bounds_quiet(pcm, sr, spans, est):
    """句子边界（上一句结束 → 下一句开始）落在没声音的地方的个数、边界数（两边都是准的才算）。"""
    r, p90 = tts_cloud._rms(pcm, sr)
    q, n = 0, 0
    for i in range(len(spans) - 1):
        if est[i] or est[i + 1]:
            continue
        n += 1
        q += tts_cloud._quiet(r, p90, spans[i][1], max(spans[i][1], spans[i + 1][0]))
    return q, n


# ---------------- 管家 ----------------
class TTS:
    def __init__(self):
        self.proc = Proc("tts")
        self.proc.vram_est = NEED_GB
        M.extra.append(self.proc)        # 显存按"我们自己的"算；退出 Agent 时一起停
        self.last = 0.0
        self.job = None
        self._task = None
        self._h, self._hts = None, 0.0
        self.aligning = False

    @property
    def s(self):
        return settings.S

    def py(self):
        return paths.resolve(self.s.get("ttsPython", ""), paths.tts_python())

    def env_ok(self):
        return self.py().exists()

    def model_dir(self, kind):
        return paths.MODELS_TTS / paths.TTS_MODELS[kind]

    def model_ok(self, kind):
        d = self.model_dir(kind)
        return (d / "config.json").exists() and (d / "speech_tokenizer" / "config.json").exists() and any(d.glob("*.safetensors"))

    def align_dir(self):
        return paths.MODELS_TTS / paths.ALIGN_MODEL

    def align_ok(self):
        d = self.align_dir()
        return (d / "config.json").exists() and any(d.glob("*.safetensors"))

    def model_size(self, kind):
        """模型文件夹有多大（字节；下到一半的也算）。"""
        try:
            d = self.align_dir() if kind == "align" else self.model_dir(kind)
            return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        except OSError:
            return 0

    def out_dir(self):
        return paths.resolve(self.s.get("ttsOut", ""), paths.TTS_OUT)

    def url(self, p=""):
        return f"http://127.0.0.1:{self.s['ttsPort']}{p}"

    def cmd(self):
        return [self.py(), paths.APP / "tts_server.py", "--port", self.s["ttsPort"], "--models", paths.MODELS_TTS]

    def env(self):
        e = M.env()
        e.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        return e

    def busy(self):
        return bool(self.job and self.job["st"] == "run")

    # ---------- 本地对齐（v1.8.14） ----------
    def align_why(self):
        """本地对齐现在用不了的原因；用得了返回空。"""
        if not self.env_ok():
            return "没装配音环境（设置 › 本地模型 点「安装配音」）"
        if not self.align_ok():
            return "没装对齐模型（设置 › 本地模型 点「接着装」，约 1.8 GB）"
        if M.yielding:
            return f"在让路（{M.yield_reason or '显存不够'}），不用显卡"
        return ""

    async def _post_align(self, c, pcm, sr, text, raw=""):
        """raw：带标点的原文（对齐器不用，只给测试用的假对齐器认句子）。"""
        try:
            r = await c.post(self.url("/align"), json={"pcm": base64.b64encode(bytes(pcm)).decode(), "sr": sr, "text": text, "raw": raw,
                                                       "language": "Chinese"})
        except httpx.HTTPError as e:
            raise NoAlign(f"配音服务断了：{type(e).__name__}") from None
        self.last = time.time()
        if r.status_code != 200:
            try:
                why = r.json().get("detail") or r.text
            except Exception:
                why = r.text
            raise NoAlign(str(why)[:200])
        return r.json().get("items") or []

    async def align_local(self, pcm, sr, texts, job=None):
        """音频 + 每句原文 → (spans, est, got, info)。spans：每句 [开始, 结束]（秒）；got：句子之间没声音的那段（补静音用）。
        用不了抛 NoAlign。长的分段对：每段不超过 ALIGN_MAX 秒，切在停顿处；每段最后两句放到下一段重对（下一段的开头是准的）。"""
        why = self.align_why()
        if why:
            raise NoAlign(why)
        if job is not None:
            job["msg"] = "对齐时间轴（本地对齐模型，第一次要等配音服务和模型装好，十几秒）"
        try:
            await self.ensure()
        except RuntimeError as e:
            raise NoAlign(str(e)[:200]) from None
        dur = len(pcm) / 2 / sr
        n = len(texts)
        syl = [syllables(t) for t in texts]
        pauses = find_pauses(pcm, sr)
        r, p90 = tts_cloud._rms(pcm, sr)
        out, t0, i0, rate, calls, t_start = [None] * n, 0.0, 0, None, 0, time.time()
        async with httpx.AsyncClient(timeout=300) as c:
            while i0 < n:
                if dur - t0 <= ALIGN_MAX:
                    i1, t1 = n, dur
                else:
                    per = rate or (dur - t0) / max(0.5, sum(syl[i0:]))
                    acc, i1 = 0.0, i0
                    while i1 < n and acc + syl[i1] * per <= ALIGN_PIECE:
                        acc += syl[i1] * per
                        i1 += 1
                    i1 = max(i1, min(n, i0 + 3))
                    guess = t0 + acc
                    cands = [p for p in pauses if t0 + 1 < (p[0] + p[1]) / 2 <= t0 + ALIGN_MAX and abs((p[0] + p[1]) / 2 - guess) < 10]
                    t1 = (sum(max(cands, key=lambda p: (p[1] - p[0]) - abs((p[0] + p[1]) / 2 - guess) * 0.05)) / 2 if cands
                          else min(dur, t0 + ALIGN_PIECE))
                piece = pcm[int(t0 * sr) * 2: int(t1 * sr) * 2]
                items = await self._post_align(c, piece, sr, " ".join(align_text(t) for t in texts[i0:i1]), "\n".join(texts[i0:i1]))
                calls += 1
                sp, est = map_items(texts[i0:i1], items, t1 - t0)
                last = i1 == n
                keep = (i1 - i0) if last else max(1, i1 - i0 - 2)
                if not any(not e for e in est[:keep]):
                    raise NoAlign("对齐器没对上字（音频和文案对不上？）")
                for k in range(keep):
                    out[i0 + k] = ([t0 + sp[k][0], t0 + sp[k][1]], est[k])
                if last:
                    break
                e_prev = t0 + sp[keep - 1][1]
                s_next = max(e_prev, t0 + sp[keep][0]) if not est[keep] else e_prev + 0.3
                rate = (e_prev - t0) / max(0.5, sum(syl[i0:i0 + keep]))
                t0, i0 = _cut_at(r, p90, (e_prev, s_next)), i0 + keep
        spans, est = [x[0] for x in out], [x[1] for x in out]
        for i in range(1, n):                                    # 段与段接上的地方：不叠
            if spans[i][0] < spans[i - 1][1]:
                spans[i][0] = spans[i - 1][1]
                spans[i][1] = max(spans[i][1], spans[i][0])
        got = [(spans[i][1], max(spans[i][1], spans[i + 1][0])) if not (est[i] or est[i + 1]) else None for i in range(n - 1)]
        q, nb = bounds_quiet(pcm, sr, spans, est)
        return spans, est, got, {"pieces": calls, "quiet": q, "bounds": nb, "sec": round(time.time() - t_start, 1)}

    async def health(self, fresh=False):
        if not fresh and time.time() - self._hts < 2:
            return self._h
        try:
            async with httpx.AsyncClient(timeout=1.5) as c:
                r = await c.get(self.url("/health"))
                self._h = r.json() if r.status_code == 200 else None
        except Exception:
            self._h = None
        self._hts = time.time()
        return self._h

    async def ensure(self, timeout=240):
        h = await self.health(fresh=True)
        if h:
            return h
        if not self.env_ok():
            raise RuntimeError("还没装配音：到 设置 › 本地模型 点「安装配音」")
        if not self.proc.alive():
            self.proc.start(self.cmd(), paths.ROOT, self.env())
            self.last = time.time()
        t0 = time.time()
        while time.time() - t0 < timeout:
            await asyncio.sleep(1)
            h = await self.health(fresh=True)
            if h:
                return h
            if not self.proc.alive():
                raise RuntimeError("配音服务没起来（看 data\\logs\\tts.log）：\n" + self.proc.tail(6))
        raise RuntimeError("配音服务启动超时（看 data\\logs\\tts.log）")

    def stop(self, why=""):
        if self.proc.alive():
            kids = []
            try:                       # Windows 上虚拟环境的 python.exe 会再起一个真正干活的子进程：按进程号一起停（只停自己开的）
                import psutil
                kids = psutil.Process(self.proc.p.pid).children(recursive=True)
            except Exception:
                pass
            self.proc.stop()
            for k in kids:
                try:
                    k.kill()
                except Exception:
                    pass
            self._h, self._hts = None, 0.0
            feed.add(f"配音服务关了：{why}，显存还回去了" if why else "配音服务关了", "info", job="配音")

    def tick(self):
        """后台照看每 2 秒调一次：让路（在玩游戏、显存不够）→ 停下正在生成的、关掉服务；闲置 ttsIdle 分钟 → 关掉服务。"""
        if M.yielding:
            if self.busy() and not self.job["stop"] and self.job.get("engine") != "cloud":     # 云端不用显卡，不停
                self.job["stop"] = M.yield_reason or "显存让路"
            if self.proc.alive():
                self.stop(M.yield_reason or "显存让路")
            return
        idle = float(self.s.get("ttsIdle") or 10) * 60
        if self.proc.alive() and not self.busy() and time.time() - (self.last or self.proc.started) > idle:
            self.stop(f"闲置 {int(idle // 60)} 分钟")

    async def free_vram(self):
        """显卡剩的不够一个配音模型：先让模型服务把底座卸了（底座用到时会自己再装）。"""
        v = M.vram_info or {}
        if v.get("total") and v.get("used") is not None and v["total"] - v["used"] < NEED_GB and not self.proc.alive():
            await M.unload("base")
            feed.add("显卡剩的显存不够配音，先把底座卸了（用到时会自己装回来）", "info", job="配音")

    # ---------- 一次生成 ----------
    def voice(self, req):
        """把界面传来的选择整理成：用哪个模型、念的时候带什么说明、名字叫什么（文件名用）。"""
        mode = req.get("mode") or "preset"
        tone = (req.get("tone") or "").strip()[:200]
        lang = req.get("lang") if req.get("lang") in dict(LANGS) else "Chinese"
        seed = req.get("seed")
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = random.randint(1, 2**31 - 1)
        seed = max(1, min(seed, 2**31 - 1))
        if mode == "cloud":
            cv = tts_cloud.find_voice(req.get("voice"))
            if not cv:
                raise HTTPException(400, "选一个云端音色（自己造的要等百炼审核通过才能用）")
            seed = seed if req.get("seed") not in (None, "") else random.randint(1, 65535)
            opts = {k: req.get(k) for k in ("rate", "pitch", "volume", "lang") if req.get(k) not in (None, "")}
            expr = {k: v for k, v in tts_cloud.expr_input(opts, "").items() if k != "hot_fix"}       # 跟默认一样的不记
            return {"mode": "cloud", "kind": "cloud", "voice": cv["id"], "name": cv["name"], "tone": tone[:100], "instruct": tone[:100],
                    "lang": "Chinese", "seed": max(1, min(seed, 65535)), "label": cv["name"], "model": tts_cloud.model(),
                    "vkind": cv.get("kind", "system"), "opts": opts, "expr": expr}
        if mode == "preset":
            spk = next((x["id"] for x in SPEAKERS if x["id"].lower() == str(req.get("speaker") or "").lower()), None)
            if not spk:
                raise HTTPException(400, "选一个预设音色")
            return {"mode": "preset", "kind": "custom", "speaker": spk, "tone": tone, "instruct": tone, "lang": lang, "seed": seed,
                    "label": spk}
        desc = (req.get("desc") or "").strip()[:500]
        if not desc:
            raise HTTPException(400, "写一段音色描述（比如：三十岁左右的男声，声音低沉温和，语速平稳）")
        name = (req.get("name") or "").strip()[:40]
        instruct = desc + ("；" + tone if tone else "")
        return {"mode": "design", "kind": "design", "desc": desc, "name": name, "tone": tone, "instruct": instruct, "lang": lang,
                "seed": seed, "label": name or "描述音色"}

    def start(self, req):
        cloud = (req.get("engine") or self.s.get("ttsEngine") or "local") == "cloud"
        if self.busy():
            raise HTTPException(409, "上一段还在生成，等它好了或者先点「停下」")
        if self.aligning:
            raise HTTPException(409, "正在重新对齐时间轴，等几秒")
        if M.yielding and not cloud:
            raise HTTPException(409, f"现在在让路（{M.yield_reason or '显存不够'}），配音先不开；游戏关了再生成（或者换「百炼云端」，不用显卡）")
        same = bool(req.get("same")) and not cloud
        text = SAME_TEXT if same else (req.get("text") or "")
        if len(text) > MAX_CHARS:
            raise HTTPException(400, f"一次最多 {MAX_CHARS} 字，分几次生成吧")
        v = self.voice(dict(req, mode="cloud") if cloud else req)
        if cloud:
            if not tts_cloud.key():
                raise HTTPException(400, "还没填百炼 API Key：到 设置 › 云端 填好再生成")
        elif not self.model_ok(v["kind"]) and not ((self._h or {}).get("models") or {}).get(v["kind"]):
            raise HTTPException(400, f"{MODEL_INFO[v['kind']]}的模型还没下：到 设置 › 本地模型 点「安装配音」")
        gap = float(self.s.get("ttsGap", 0.35))
        segs = split(text, gap=1.0 if same else gap, para=1.2 if same else float(self.s.get("ttsParaGap", 0.7)))
        if cloud:
            segs = tts_cloud.merge_tags(segs)      # 只有 [标签] 的一块并到前一句
        if not segs:
            raise HTTPException(400, "没有要念的字")
        chars = sum(len(x["text"]) for x in segs)
        whole = bool(self.s.get("ttsWhole", True)) if req.get("whole") is None else bool(req.get("whole"))
        if same:
            whole = False             # 试同一个人：两段要分开念（分开采样），才看得出同一段描述 + 种子换了文字还像不像
        if cloud:
            whole = True              # 云端：一块一次念完（超过 设置 › 云端 的字数按段落分块）
        est = tts_cloud.estimate(text) if cloud else None
        self.job = {"id": int(time.time() * 1000), "st": "run", "i": 0, "n": len(segs), "chars": chars, "done_chars": 0, "cur": "",
                    "msg": "准备中", "err": "", "stop": "", "same": same, "voice": v, "t0": time.time(), "t1": 0.0,
                    "audio_s": 0.0, "eta": None, "whole": whole, "chunks": 1, "chunk_t0": 0.0, "chunk_est": 0.0, "chunk_chars": 0,
                    "engine": "cloud" if cloud else "local", "est": est, "cny": 0.0, "bill": 0, "align": ""}
        self._task = asyncio.get_event_loop().create_task(self._run(self.job, text, segs))
        if cloud:
            feed.add(f"开始配音（百炼云端 {v['model']}）：{len(segs)} 句、{chars} 字，音色 {v['label']}，预估 {yuan(est['cny'])}", "head", job="配音")
        else:
            feed.add(f"开始配音：{len(segs)} 句、{chars} 字，音色 {v['label']}，" + ("整段一次生成" if whole else "一句一句生成") + ("（试同一个人）" if same else ""),
                     "head", job="配音")
        return self.public()

    async def _post(self, c, job, v, text, timeout):
        """念一段字，返回 (采样率, PCM)。点了停下 / 让路把服务关了：抛 Stopped。"""
        try:
            r = await c.post(self.url("/generate"), timeout=timeout,
                             json={"kind": v["kind"], "text": text, "speaker": v.get("speaker"), "instruct": v["instruct"],
                                   "language": v["lang"], "seed": v["seed"]})
        except httpx.HTTPError as e:
            if job["stop"]:
                raise Stopped(job["stop"]) from None
            raise RuntimeError(f"配音服务断了：{e}") from None
        self.last = time.time()
        if r.status_code != 200:
            if job["stop"]:
                raise Stopped(job["stop"])
            try:
                why = r.json().get("detail") or r.text
            except Exception:
                why = r.text
            raise RuntimeError(str(why)[:300])
        return read_wav(r.content)

    async def _by_sentence(self, c, job, v, segs):
        """一句一句生成（v1.8.6 的做法）：进度准，但每句单独采样，句与句的语气会不一样。"""
        pcm, sr, tl = bytearray(), None, []
        for i, sg in enumerate(segs):
            if job["stop"]:
                raise Stopped(job["stop"])
            job.update(i=i, cur=sg["text"])
            if i:
                job["msg"] = f"第 {i + 1}/{len(segs)} 句"
            rate, frames = await self._post(c, job, v, sg["text"], 900)
            sr = sr or rate
            if rate != sr:
                raise RuntimeError("前后两句的采样率对不上")
            start = len(pcm) / 2 / sr
            pcm += frames
            end = len(pcm) / 2 / sr
            tl.append({"i": i + 1, "start": round(start, 3), "end": round(end, 3), "text": sg["text"]})
            if sg["gap"] > 0 and i < len(segs) - 1:
                pcm += bytes(2 * int(sr * sg["gap"]))
            job["done_chars"] += len(sg["text"])
            job["audio_s"] = round(end, 2)
            per = (time.time() - job["t1"]) / max(1, job["done_chars"])
            job["eta"] = round(per * (job["chars"] - job["done_chars"]))
        return pcm, sr, tl

    async def _whole(self, c, job, v, segs):
        """整段一次生成（v1.8.9 默认）：一块（最多 WHOLE_MAX 字）一次念完，语气前后连贯；每句的开始、结束按音频里的停顿对齐，
        配不上停顿的按字数估（时间轴里标 est）；停顿比设置的短就补静音补够。"""
        pcm, sr, tl = bytearray(), None, []
        chunks = whole_chunks(segs)
        job["chunks"] = len(chunks)
        job["chk"] = {"how": set(), "quiet": 0, "bounds": 0, "base": set(), "sec": 0.0}
        per_min = float((db.kv_get("tts_speed") or {}).get("per_min") or 240)      # 生成 1 分钟音频要几秒；没测过按 4 分钟估
        for ci, idx in enumerate(chunks):
            if job["stop"]:
                raise Stopped(job["stop"])
            text = chunk_text(segs, idx)
            nc = sum(len(segs[i]["text"]) for i in idx)
            audio = nc / (4.2 if re.search(r"[\u4e00-\u9fff]", text) else 14)          # 中文一秒大约 4 个字
            est = max(5.0, audio * per_min / 60)
            job.update(i=idx[0], cur=text[:40], chunk_t0=time.time(), chunk_est=est, chunk_chars=nc,
                       msg=f"整段一次生成中：{len(idx)} 句、{nc} 字一起念（念完才出声音，进度是按上次的速度估的）" if len(chunks) == 1
                       else f"第 {ci + 1}/{len(chunks)} 块：{len(idx)} 句、{nc} 字一起念（进度是估的）")
            rate, frames = await self._post(c, job, v, text, max(900.0, est * 4 + 120))
            sr = sr or rate
            if rate != sr:
                raise RuntimeError("前后两块的采样率对不上")
            spans, est_flags, got = await self._timeline(job, frames, rate, segs, idx)
            frames, spans = pad_pauses(frames, rate, spans, got, [segs[i]["gap"] for i in idx[:-1]])
            base = len(pcm) / 2 / sr
            pcm += frames
            for (st, en), e, i in zip(spans, est_flags, idx):
                tl.append({"i": i + 1, "start": round(base + st, 3), "end": round(base + en, 3), "text": segs[i]["text"], **({"est": True} if e else {})})
            if ci < len(chunks) - 1:
                pcm += bytes(2 * int(sr * segs[idx[-1]]["gap"]))
            job["done_chars"] += nc
            job["audio_s"] = round(len(pcm) / 2 / sr, 2)
            job["chunk_t0"] = 0.0
        self._finish_check(job, tl)
        return pcm, sr, tl

    async def _timeline(self, job, frames, sr, segs, idx, words=None):
        """一块音频的时间轴：百炼字级时间戳（words，对得上停顿的才用）→ 本地对齐 → 按停顿猜。返回 (spans, est, got)；
        got 是补静音用的：只有准的边界才给，按停顿猜的全是 None（猜错了的地方不能塞静音）。"""
        ck = job["chk"]
        if words:
            spans, est, got, w = words
            if not w["bounds"] or w["quiet"] >= 0.9 * w["bounds"]:
                ck["how"].add("words")
                ck["quiet"] += w["quiet"]
                ck["bounds"] += w["bounds"]
                ck["base"].add(w["base"])
                return spans, est, got
        try:
            spans, est, got, info = await self.align_local(frames, sr, [segs[i]["text"] for i in idx], job)
            ck["how"].add("align")
            ck["quiet"] += info["quiet"]
            ck["bounds"] += info["bounds"]
            ck["sec"] += info["sec"]
            return spans, est, got
        except NoAlign as e:
            ck["why"] = str(e)
        if words:                                                # 本地对齐用不了：百炼的时间戳虽然有几处没落在停顿上，也比猜的强
            spans, est, got, w = words
            ck["how"].add("words")
            ck["quiet"] += w["quiet"]
            ck["bounds"] += w["bounds"]
            ck["base"].add(w["base"])
            return spans, est, got
        spans, est, _ = whole_timeline(frames, sr, segs, idx)
        ck["how"].add("pause")
        return spans, est, [None] * (len(idx) - 1)

    def _finish_check(self, job, tl):
        """时间轴准不准写进 JSON（check）和界面：用的什么办法、几句是准的、句子边界有几处落在停顿上、没用本地对齐的原因。"""
        ck = job["chk"]
        hows = ck["how"]
        names = {"words": "百炼逐字时间戳", "align": "本地对齐", "pause": "按停顿猜"}
        n_est = sum(1 for x in tl if x.get("est"))
        job["check"] = {"method": " + ".join(names[h] for h in ("words", "align", "pause") if h in hows), "how": sorted(hows),
                        "sure": "pause" not in hows, "sentences": len(tl), "exact": len(tl) - n_est, "estimated": n_est,
                        **({"bounds_in_silence": ck["quiet"], "bounds": ck["bounds"]} if ck["bounds"] else {}),
                        **({"time_base": "/".join(sorted(ck["base"]))} if ck["base"] else {}),
                        **({"align_sec": round(ck["sec"], 1)} if "align" in hows else {}),
                        **({"why_not_aligned": ck["why"]} if "pause" in hows and ck.get("why") else {})}
        pre = "百炼云端：" if job.get("engine") == "cloud" else "整段一次生成："
        if hows == {"words"}:
            job["align"] = pre + "每句的开始、结束用百炼返回的字级时间戳拼出来（带 est 的是没对上、夹在前后两句中间估的）"
        elif hows == {"align"}:
            job["align"] = pre + "每句的开始、结束用本地对齐模型（Qwen3-ForcedAligner-0.6B）拿音频和原文对出来的，误差几十毫秒（带 est 的是没对上、夹在中间估的）"
        elif hows == {"pause"}:
            job["align"] = pre + "没对齐（" + (ck.get("why") or "对齐用不了") + "），每句的开始、结束是按音频里的停顿猜的，可能对不上；可以点「重新对齐」"
        else:
            job["align"] = pre + "有的块用" + "、有的块用".join(names[h] for h in ("words", "align", "pause") if h in hows) + "（带 est 的是估的）"


    async def _cloud(self, job, segs):
        """百炼云端（v1.8.11）：一块（最多 blMax 字）一次念完，边念边传回来；超过的按段落分块，同一个音色、语气、种子。
        时间轴用百炼返回的字级时间戳拼每句的开始、结束；没给就按音频里的停顿对齐（和本地整段生成一样）。停顿比设置的短就补够。"""
        v = job["voice"]
        limit = max(200, int(self.s.get("blMax") or 2000))
        chunks = whole_chunks(segs, limit)
        job["chunks"] = len(chunks)
        pcm, sr, tl = bytearray(), tts_cloud.SR, []
        job["chk"] = {"how": set(), "quiet": 0, "bounds": 0, "base": set(), "sec": 0.0}
        for ci, idx in enumerate(chunks):
            if job["stop"]:
                raise Stopped(job["stop"])
            text, ranges = chunk_parts(segs, idx)
            nc = sum(len(segs[i]["text"]) for i in idx)
            base_done, base_s = job["done_chars"], len(pcm) / 2 / sr
            job.update(i=idx[0], cur=text[:40], msg="百炼生成中（边念边传回来）" if len(chunks) == 1
                       else f"百炼生成中：第 {ci + 1}/{len(chunks)} 块（{nc} 字，同一个音色和语气）")

            def prog(done, samples, cur, base_done=base_done, base_s=base_s, nc=nc):
                job["done_chars"] = base_done + min(nc, done)
                job["audio_s"] = round(base_s + samples / sr, 2)
                if cur:
                    job["cur"] = tts_cloud.strip_tags(cur)[:40]
                el = time.time() - job["t1"]
                if job["done_chars"] > 0:
                    job["eta"] = round(el / job["done_chars"] * (job["chars"] - job["done_chars"]))

            try:
                r, asked = await tts_cloud.synth_once_more(text, v["voice"], v["instruct"], v["seed"], stop=lambda: bool(job["stop"]), progress=prog,
                                                           opts=v.get("opts"))
            except tts_cloud.Cancelled:
                raise Stopped(job["stop"] or "停了") from None
            except tts_cloud.CloudError as e:
                raise RuntimeError(str(e) + (f"（前 {ci} 块已经念好、已计费，这次没保存）" if ci else "")) from None
            frames = r["pcm"]
            bill, cny = tts_cloud.record(v["voice"], text, r["usage"], "生成", len(frames) / 2 / sr)
            job["bill"] += bill
            job["cny"] += cny
            words = tts_cloud.word_spans(text, ranges, r["sents"], sr, frames) if asked else None
            spans, est_flags, got = await self._timeline(job, frames, sr, segs, idx, words)
            frames, spans = pad_pauses(frames, sr, spans, got, [segs[i]["gap"] for i in idx[:-1]])
            base = len(pcm) / 2 / sr
            pcm += frames
            for (st, en), e, i in zip(spans, est_flags, idx):
                tl.append({"i": i + 1, "start": round(base + st, 3), "end": round(base + en, 3), "text": tts_cloud.strip_tags(segs[i]["text"]),
                           **({"est": True} if e else {})})
            if ci < len(chunks) - 1:
                pcm += bytes(2 * int(sr * segs[idx[-1]]["gap"]))
            job["done_chars"] = base_done + nc
            job["audio_s"] = round(len(pcm) / 2 / sr, 2)
        self._finish_check(job, tl)
        return pcm, sr, tl

    async def _run(self, job, text, segs):
        v = job["voice"]
        try:
            if job["engine"] == "cloud":
                job["t1"] = time.time()
                pcm, sr, tl = await self._cloud(job, segs)
            else:
                job["msg"] = "启动配音服务（第一次要等半分钟到一分钟）" if not self._h else "准备中"
                await self.free_vram()
                try:
                    await self.ensure()
                except RuntimeError:
                    if job["stop"]:
                        raise Stopped(job["stop"]) from None
                    raise
                if job["stop"]:
                    raise Stopped(job["stop"])
                job["msg"] = f"装{MODEL_INFO[v['kind']]}的模型（换模型时要等一会）"
                job["t1"] = time.time()
                async with httpx.AsyncClient(timeout=900) as c:
                    pcm, sr, tl = await (self._whole(c, job, v, segs) if job["whole"] else self._by_sentence(c, job, v, segs))
            if job["stop"]:                  # 念完的那一刻点了停下：也不存（不覆盖上一次的试听）
                raise Stopped(job["stop"])
            gen = time.time() - job["t1"]
            meta = self._write_draft(job, text, sr, pcm, tl, gen)
            if job["engine"] == "cloud":
                job.update(st="done", i=len(segs), cur="", eta=0,
                           msg=f"好了：{mmss(meta['duration'])}音频，用了 {mmss(gen)}，花了约 {yuan(job['cny'])}（计费 {job['bill']} 字符）")
                feed.add(f"配音好了（百炼云端）：{len(segs)} 句，{mmss(meta['duration'])}音频，用了 {mmss(gen)}，约 {yuan(job['cny'])}", "ok", job="配音")
                return
            speed = {"audio_s": meta["duration"], "gen_s": round(gen, 1), "per_min": round(gen / max(meta["duration"], 0.1) * 60),
                     "attn": (self._h or {}).get("attn", ""), "kind": v["kind"], "whole": job["whole"], "ts": time.time()}
            db.kv_set("tts_speed", speed)
            job.update(st="done", i=len(segs), cur="", eta=0,
                       msg=f"好了：{mmss(meta['duration'])}音频，生成用了 {mmss(gen)}（照这个速度，1 分钟音频要 {mmss(speed['per_min'])}）")
            feed.add(f"配音好了：{len(segs)} 句，{mmss(meta['duration'])}音频，生成用了 {mmss(gen)}" + ("（整段一次生成）" if job["whole"] else "（一句一句）"),
                     "ok", job="配音")
        except Stopped as e:
            spent = f"；已经念完的部分百炼照样计费，约 {yuan(job['cny'])}" if job.get("cny") else ""
            job.update(st="stop", msg=f"停了：{e}（这次没生成完，没保存{spent}）")
            feed.add(f"配音停了：{e}", "warn", job="配音")
        except Exception as e:
            job.update(st="err", err=str(e)[:400], msg="没生成成：" + str(e)[:200])
            feed.add(f"配音没生成成：{str(e)[:200]}", "err", job="配音")

    def _write_draft(self, job, text, sr, pcm, tl, gen):
        v = job["voice"]
        DRAFT.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        voice = {k: v[k] for k in ("mode", "speaker", "voice", "vkind", "desc", "name", "tone", "seed", "expr") if v.get(k) not in (None, "", {})}
        cloud = job.get("engine") == "cloud"
        meta = {"app": "Agent 配音", "created": now.strftime("%Y-%m-%d %H:%M:%S"),
                "name": f"{now:%Y-%m-%d_%H%M}_{safe_name(v['label'])}", "engine": "cloud" if cloud else "local",
                "model": v["model"] if cloud else paths.TTS_MODELS[v["kind"]],
                "license": "阿里云百炼服务协议：用阿里自家模型生成的内容，知识产权归你" if cloud else LICENSE,
                "voice": voice, "language": v["lang"], "sample_rate": sr, "duration": round(len(pcm) / 2 / sr, 3),
                "gen_seconds": round(gen, 1), "same_test": job["same"], "way": "whole" if job["whole"] else "sentence",
                "align": job.get("align") or "一句一句生成：每句的开始、结束是准的",
                "gaps": {"sentence": float(self.s.get("ttsGap", 0.35)), "paragraph": float(self.s.get("ttsParaGap", 0.7))},
                **({"cost": {"billed_chars": job["bill"], "cny": round(job["cny"], 4), "chunks": job["chunks"]}} if cloud else {}),
                "check": job.get("check") or {"method": "一句一句生成", "how": ["sentence"], "sure": True, "sentences": len(tl),
                                              "exact": len(tl), "estimated": 0},
                "segments": tl}
        tmp = DRAFT / "draft.tmp.wav"
        write_wav(tmp, sr, pcm)
        tmp.replace(DRAFT / "draft.wav")
        (DRAFT / "draft.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        (DRAFT / "draft.srt").write_text(to_srt(tl), "utf-8")
        (DRAFT / "draft.txt").write_text(text.strip() + "\n", "utf-8")
        return meta

    def draft(self):
        try:
            m = json.loads((DRAFT / "draft.json").read_text("utf-8"))
        except Exception:
            return None
        if not (DRAFT / "draft.wav").exists():
            return None
        m["ver"] = int((DRAFT / "draft.wav").stat().st_mtime)
        return m

    async def realign(self):
        """试听的那段重新对一遍时间轴（v1.8.14）：用本地对齐模型，声音一点不动、不重新生成、不花钱；改 JSON 和 SRT。"""
        if self.busy():
            raise HTTPException(409, "正在生成，等它好了再对齐")
        if self.aligning:
            raise HTTPException(409, "已经在对齐了")
        m = self.draft()
        if not m or not m.get("segments"):
            raise HTTPException(404, "还没有生成过")
        why = self.align_why()
        if why:
            raise HTTPException(400, "现在对不了：" + why)
        self.aligning = True
        try:
            sr, pcm = read_wav((DRAFT / "draft.wav").read_bytes())
            texts = [x["text"] for x in m["segments"]]
            spans, est, _, info = await self.align_local(pcm, sr, texts)
        except NoAlign as e:
            raise HTTPException(503, "没对成：" + str(e)) from None
        finally:
            self.aligning = False
        old = m.get("check") or {}
        tl = [{"i": x["i"], "start": round(a, 3), "end": round(b, 3), "text": x["text"], **({"est": True} if e else {})}
              for x, (a, b), e in zip(m["segments"], spans, est)]
        n_est = sum(est)
        moved = [abs(a["start"] - b["start"]) for a, b in zip(tl, m["segments"])]
        m.pop("ver", None)
        m.update(segments=tl, realigned=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 align=("重新对齐：每句的开始、结束用本地对齐模型（Qwen3-ForcedAligner-0.6B）拿音频和原文对出来的，误差几十毫秒；"
                        "声音没动（生成时补过的静音还在）"),
                 check={"method": "本地对齐（重新对齐）", "how": ["align"], "sure": True, "sentences": len(tl), "exact": len(tl) - n_est,
                        "estimated": n_est, "bounds_in_silence": info["quiet"], "bounds": info["bounds"], "align_sec": info["sec"],
                        "before": old.get("method", ""), "moved_max": round(max(moved or [0]), 2)})
        (DRAFT / "draft.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), "utf-8")
        (DRAFT / "draft.srt").write_text(to_srt(tl), "utf-8")
        big = sum(1 for x in moved if x > 0.3)
        msg = f"重新对齐好了：{len(tl)} 句，{big} 句的开始挪了 0.3 秒以上（最多 {max(moved or [0]):.1f} 秒），用了 {info['sec']:.0f} 秒"
        feed.add("配音" + msg, "ok", job="配音")
        return {"msg": msg, "draft": self.draft()}

    def save(self):
        m = self.draft()
        if not m:
            raise HTTPException(404, "还没有生成过")
        out = self.out_dir()
        d, k = out / m["name"], 2
        while d.exists():
            d, k = out / f"{m['name']}_{k}", k + 1
        d.mkdir(parents=True)
        base = d.name
        shutil.copy2(DRAFT / "draft.wav", d / f"{base}.wav")
        meta = dict(m, audio=f"{base}.wav", subtitles=f"{base}_字幕.srt", script=f"{base}_文案.txt")
        meta.pop("ver", None)
        (d / f"{base}_时间轴.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        shutil.copy2(DRAFT / "draft.srt", d / f"{base}_字幕.srt")
        shutil.copy2(DRAFT / "draft.txt", d / f"{base}_文案.txt")
        db.kv_set("tts_saved", {"dir": str(d), "name": base, "ts": time.time()})
        feed.add(f"配音保存好了：{paths.show(d)}", "ok", job="配音")
        return d

    def public(self):
        j = self.job
        if not j:
            return None
        keys = ("id", "st", "i", "n", "chars", "done_chars", "cur", "msg", "err", "same", "audio_s", "eta", "whole", "chunks", "engine", "est")
        out = {k: j.get(k) for k in keys}
        out["cny"] = round(j.get("cny") or 0, 4)
        out["voice"] = j["voice"]["label"]
        out["elapsed"] = round(time.time() - j["t0"])
        done = j["done_chars"]
        if j["st"] == "run" and j["whole"] and j["chunk_t0"]:      # 整段生成：念完才知道，按上次的速度估这一块到哪了
            el = time.time() - j["chunk_t0"]
            done += min(0.95, el / max(1.0, j["chunk_est"])) * j["chunk_chars"]
            rest = j["chars"] - j["done_chars"] - j["chunk_chars"]
            out["eta"] = round(max(5.0, j["chunk_est"] - el) + rest * j["chunk_est"] / max(1, j["chunk_chars"]))
        out["pct"] = round(done / j["chars"] * 100, 1) if j["chars"] else None
        return out

    # ---------- 我的音色 ----------
    def voices(self):
        return db.kv_get("tts_voices", []) or []

    def add_voice(self, body):
        name = (body.get("name") or "").strip()[:40]
        desc = (body.get("desc") or "").strip()[:500]
        if not name or not desc:
            raise HTTPException(400, "起个名字，写好描述")
        try:
            seed = int(body.get("seed"))
        except (TypeError, ValueError):
            raise HTTPException(400, "种子要是数字") from None
        vs = [v for v in self.voices() if v["name"] != name]
        vs.append({"id": int(time.time() * 1000), "name": name, "desc": desc, "seed": seed, "lang": body.get("lang") or "Chinese",
                   "ts": time.time()})
        db.kv_set("tts_voices", vs[-40:])
        return vs

    def del_voice(self, vid):
        vs = [v for v in self.voices() if str(v["id"]) != str(vid)]
        db.kv_set("tts_voices", vs)
        return vs

    async def status(self):
        h = await self.health()
        from . import tts_install
        return {"env": self.env_ok(), "models": {k: self.model_ok(k) for k in paths.TTS_MODELS}, "model_names": paths.TTS_MODELS,
                "sizes": {k: self.model_size(k) for k in (*paths.TTS_MODELS, "align")}, "inst": tts_install.public(),
                "align": self.align_ok(), "align_why": self.align_why(), "aligning": self.aligning,
                "server": bool(h), "proc": self.proc.alive(), "loaded": (h or {}).get("loaded"), "attn": (h or {}).get("attn"),
                "cuda": (h or {}).get("cuda"), "yield": (M.yield_reason or "显存让路") if M.yielding else "",
                "job": self.public(), "draft": self.draft(), "speakers": SPEAKERS, "langs": LANGS, "voices": self.voices(),
                "out": paths.show(self.out_dir()), "saved": db.kv_get("tts_saved"), "speed": db.kv_get("tts_speed"),
                "idle": self.s.get("ttsIdle"), "gap": self.s.get("ttsGap"), "para": self.s.get("ttsParaGap"), "whole": bool(self.s.get("ttsWhole", True)),
                "license": LICENSE, "engine": "cloud" if self.s.get("ttsEngine") == "cloud" else "local", "cloud": tts_cloud.public()}


T = TTS()

# ---------------- 接口 ----------------
api = APIRouter()


@api.get("/api/tts")
async def tts_status():
    return await T.status()


@api.post("/api/tts/gen")
async def tts_gen(body: dict = Body(...)):
    return {"job": T.start(body)}


@api.post("/api/tts/stop")
def tts_stop():
    if T.busy():
        T.job["stop"] = "你点了「停下」"
        if T.job.get("engine") == "cloud":       # 云端：收到下一小段就断开（不碰本地配音服务）
            T.job["msg"] = "马上停"
        elif T.job["whole"]:                   # 整段生成：一块可能要念好几分钟，等不了，直接把服务关掉（下次重新装模型，要半分钟）
            T.job["msg"] = "马上停"
            T.stop("你点了「停下」")
        else:
            T.job["msg"] = "念完这一句就停"     # 一句一句：念完手上这一句就停（服务不关，模型还在，下次不用重新装）
    return {"job": T.public()}


@api.post("/api/tts/off")
def tts_off():
    if T.busy():
        raise HTTPException(409, "正在生成，先点「停下」")
    T.stop("你点了「关掉」")
    return {"ok": True}


@api.get("/api/tts/draft.wav")
def tts_draft_wav():
    p = DRAFT / "draft.wav"
    if not p.exists():
        raise HTTPException(404, "还没有生成过")
    return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@api.post("/api/tts/realign")
async def tts_realign():
    return await T.realign()


@api.post("/api/tts/save")
def tts_save():
    d = T.save()
    return {"dir": paths.show(d), "name": d.name, "msg": f"存好了：{paths.show(d)}"}


@api.post("/api/tts/open")
def tts_open(body: dict = Body(default={})):
    saved = db.kv_get("tts_saved") or {}
    d = saved.get("dir") if body.get("last") and saved.get("dir") and os.path.isdir(saved.get("dir")) else T.out_dir()
    d = str(d)
    os.makedirs(d, exist_ok=True)
    if paths.IS_WIN:
        os.startfile(d)          # 打开资源管理器（不是黑窗口）
        return {"msg": "打开了：" + paths.show(d)}
    return {"msg": "文件夹在：" + paths.show(d)}


@api.post("/api/tts/cloud/try")
async def tts_cloud_try(body: dict = Body(...)):
    """试听一个云端音色：念一句固定的短句（念过的存着，再点不花钱）。返回 WAV。"""
    try:
        b, cached = await tts_cloud.preview(str(body.get("voice") or ""))
    except tts_cloud.CloudError as e:
        raise HTTPException(e.status if e.status in (400, 401, 403, 404, 429) else 502, str(e)) from None
    return Response(content=b, media_type="audio/wav", headers={"X-Cached": "1" if cached else "0", "Cache-Control": "no-store"})


def _cloud_err(e):
    return HTTPException(e.status if e.status in (400, 401, 403, 404, 429) else 502, str(e))


def draft_sample(max_s=20.0, min_s=5.0):
    """拿最近一次生成的配音当复刻的录音：超过 20 秒就在 12~20 秒之间的停顿处截断（不切在字中间）。返回 (WAV 字节, 说明)。"""
    m = T.draft()
    if not m:
        raise HTTPException(404, "还没有生成过配音：先生成一段（比如用本地的描述音色造一个声音），再拿它来复刻")
    sr, pcm = read_wav((DRAFT / "draft.wav").read_bytes())
    dur = len(pcm) / 2 / sr
    if dur < min_s:
        raise HTTPException(400, f"最近一次的配音太短（{dur:.1f} 秒）：至少 5 秒，推荐 10~20 秒")
    cut = dur
    if dur > max_s:
        ps = [p for p in find_pauses(pcm, sr) if 12.0 <= (p[0] + p[1]) / 2 <= max_s]
        cut = ((ps[-1][0] + ps[-1][1]) / 2) if ps else max_s
    b = io.BytesIO()
    with wave.open(b, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(bytes(pcm[: int(cut * sr) * 2]))
    who = (m.get("voice") or {}).get("name") or (m.get("voice") or {}).get("speaker") or "配音"
    return b.getvalue(), f"最近生成的配音（{who}，{m.get('created', '')[5:16]}，取前 {cut:.0f} 秒）"


@api.post("/api/tts/cloud/design")
async def tts_cloud_design(body: dict = Body(...)):
    """声音设计：一段描述 → 百炼造一个新音色（不要钱），返回音色（审核中）。试听用创建时给的那段，不花钱。"""
    try:
        v = await tts_cloud.design(body.get("name"), body.get("prompt"), body.get("text"), body.get("lang") or "zh", body.get("g") or "")
    except tts_cloud.CloudError as e:
        raise _cloud_err(e) from None
    feed.add(f"声音设计：造了一个音色「{v['name']}」，百炼审核中（不要钱）", "ok", job="配音")
    return {"voice": v, "msg": f"造好了「{v['name']}」：百炼审核一般几秒到一分钟，好了就能用"}


@api.post("/api/tts/cloud/clone")
async def tts_cloud_clone(body: dict = Body(...)):
    """声音复刻：上传的录音（Base64）或者最近生成的配音 → 百炼照着这个声音造一个音色（不要钱）。只复刻自己的或 AI 生成的声音。"""
    if not body.get("consent"):
        raise HTTPException(400, "先确认：这段声音是你自己的，或者是 AI 生成的（不复刻别人的声音）")
    if body.get("source") == "draft":
        audio, src = draft_sample()
    else:
        try:
            audio = base64.b64decode(str(body.get("data") or "").split(",")[-1], validate=False)
        except Exception:
            raise HTTPException(400, "录音没传上来，重新选一下文件") from None
        src = "上传的录音" + (f"「{str(body.get('file'))[:40]}」" if body.get("file") else "")
    try:
        v = await tts_cloud.clone(body.get("name"), audio, body.get("lang") or "zh", bool(body.get("denoise")), src, body.get("g") or "")
    except tts_cloud.CloudError as e:
        raise _cloud_err(e) from None
    feed.add(f"声音复刻：造了一个音色「{v['name']}」（{src}），百炼审核中（不要钱）", "ok", job="配音")
    return {"voice": v, "msg": f"复刻好了「{v['name']}」：百炼审核一般几秒到一分钟，好了就能用"}


@api.post("/api/tts/cloud/sync")
async def tts_cloud_sync():
    try:
        r = await tts_cloud.sync()
    except tts_cloud.CloudError as e:
        raise _cloud_err(e) from None
    return {**r, "msg": f"和百炼对过了：百炼上 {r['total']} 个音色" + (f"，新加 {r['added']} 个" if r["added"] else "") + (f"，{r['gone']} 个百炼上已经没了" if r["gone"] else "")}


@api.patch("/api/tts/cloud/voices/{vid}")
def tts_cloud_rename(vid: str, body: dict = Body(...)):
    try:
        tts_cloud.rename(vid, body.get("name"))
    except tts_cloud.CloudError as e:
        raise _cloud_err(e) from None
    return {"mine": tts_cloud.mine()}


@api.delete("/api/tts/cloud/voices/{vid}")
async def tts_cloud_delete(vid: str):
    try:
        await tts_cloud.remove(vid)
    except tts_cloud.CloudError as e:
        raise _cloud_err(e) from None
    return {"mine": tts_cloud.mine(), "msg": "删掉了（百炼那边也删了）"}


@api.put("/api/tts/cloud/hotfix")
def tts_cloud_hotfix(body: dict = Body(...)):
    try:
        h = tts_cloud.set_hotfix(body)
    except tts_cloud.CloudError as e:
        raise _cloud_err(e) from None
    return {"hotfix": h, "msg": f"读音词典存好了：{len(h['pronunciation'])} 个读音、{len(h['replace'])} 个替换"}


@api.post("/api/tts/voices")
def tts_add_voice(body: dict = Body(...)):
    return {"voices": T.add_voice(body), "msg": f"存好了：{(body.get('name') or '').strip()}"}


@api.delete("/api/tts/voices/{vid}")
def tts_del_voice(vid: str):
    return {"voices": T.del_voice(vid)}
