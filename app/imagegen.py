r"""生图（v1.8.15 起；v1.8.16 重做成「渲染舱」）：左边「生图」页的后端。

四件事：
- 单张：文生图，或者带参考图（最多十几张）+ 提示词生图（图生图）；一次出 1~4 张。
- 批量：上传视频窗口出的「生图清单」Markdown（这期的视觉方向 + 每张的文件名、用在哪、比例、透明背景开不开、提示词），
  一张一张出完，按清单里的文件名存好（以前作者要一条一条复制提示词去生成、再一张张按文件名存）。
- 历史：出过的每一张（单张、批量）都记在 data\agent.db 的 img_history：提示词、模型、尺寸、花费、存在哪；能再来一张、当参考图。
- 素材模板：把一套提示词 + 参考图 + 比例这些存起来（data\img\templates），下次一点就填好。

模型（页面上换，不一定要去设置）：默认 GPT Image 2.5 Sunburst VIP（作者挑的：按次 $0.03/张，画质够）。
「刷新模型列表」用 API易 的 Key 调 GET /v1/models，挑出生图模型，按厂商分好（Google、OpenAI、Seedream、Flux……）；
认识的模型（KNOWN）带着线路（官转 / 逆向）、计费（按次多少钱 / 按量）、大概多久、说明，和 API易 网页版「AI 图片大师」的列表一样。
各家调用方式不一样，这里按厂商分四种（_call_*）：
  openai   /v1/images/generations（JSON）；带参考图走 /v1/images/edits（multipart）。GPT Image 全家、Grok、没收录的都走这个
  gemini   /v1beta/models/{id}:generateContent（Nano Banana）：aspectRatio + imageSize，参考图放 inlineData
  seedream /v1/images/generations，size 写像素、watermark=false，参考图放 image 数组（data URI）
  flux     /v1/images/generations，size 写像素（≤4MP），参考图放 input_image、input_image_2……；回来的是链接，马上下载
尺寸：比例 × 档位（1K / 2K / 4K）用 API易 VIP 那 30 档（作者给视频窗口念过的那套，正本里的 10 种比例）；
  Seedream 固定按 2K 那档（它最小 92 万像素），Flux 按 1K 那档（它最大 4MP）；All、Nano Banana 不写像素（比例写进提示词 / aspectRatio）。
- 只把提示词和你给的参考图发给 API易，别的一律不发。Key 用 DPAPI 加密存在 data\secrets.bin（imgKey），不写日志、不进导出、不进记录。
- 透明背景：GPT Image 2.5、VIP 这些发 background=transparent；别的模型只能在提示词里要（不一定真透明，存完看 PNG 有没有透明通道）。
- 不放字：正本规矩 6，默认每条后面加一句「不要文字、logo、水印」。视觉方向默认不拼（每条提示词里已经写了画风）。
- 一张一张出（imgConc，默认 1）。点「停下」：还没开始的不出了，正在出的出完——断开的话 API易 照样计费、图却丢了。
  只试一次，不自动重试；Key 不对、余额不够、被限流整批停。
- 存：批量 → 生图输出\<日期>_<清单名>\<清单里的文件名>；单张 → 生图输出\单张\<日期>\<时分秒>_<提示词开头>.png。
  同名的旧图挪进「旧版」（不删）。每张实际发出去的提示词、尺寸、花费记在同一个文件夹的 生图记录.json。
"""
import asyncio
import base64
import json
import math
import os
import re
import struct
import time
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from . import db, feed, paths, settings

RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"]      # 正本第四节：能选的只有这 10 种
TIERS = ["1k", "2k", "4k"]
SIZES = {                                                  # API易 VIP 的 30 档（10 种比例 × 1K/2K/4K），也合官转的规矩：16 的倍数、长边 ≤3840、0.65~8.3 百万像素
    "1k": {"1:1": (1280, 1280), "2:3": (848, 1280), "3:2": (1280, 848), "3:4": (960, 1280), "4:3": (1280, 960), "4:5": (1024, 1280),
           "5:4": (1280, 1024), "9:16": (720, 1280), "16:9": (1280, 720), "21:9": (1280, 544)},
    "2k": {"1:1": (2048, 2048), "2:3": (1360, 2048), "3:2": (2048, 1360), "3:4": (1536, 2048), "4:3": (2048, 1536), "4:5": (1632, 2048),
           "5:4": (2048, 1632), "9:16": (1152, 2048), "16:9": (2048, 1152), "21:9": (2048, 864)},
    "4k": {"1:1": (2880, 2880), "2:3": (2336, 3520), "3:2": (3520, 2336), "3:4": (2480, 3312), "4:3": (3312, 2480), "4:5": (2560, 3216),
           "5:4": (3216, 2560), "9:16": (2160, 3840), "16:9": (3840, 2160), "21:9": (3840, 1632)},
}
QUALITY = {"auto": "自动", "low": "低", "medium": "中", "high": "高", "xhigh": "更高", "max": "最高"}
TOKENS_1K = {"low": 196, "medium": 439, "high": 1756, "xhigh": 3122, "max": 7024, "auto": 439}    # 官转 1024² 一张的输出 token（API易 文档）
USD_OUT, USD_IN = 30 / 1e6, 5 / 1e6                                                        # 官转：输出 $30、输入 $5 每百万 token（粗算）
TRANS_TAIL = "只画主体本身，背景完全透明：不要场景、不要地面、不要投影。（isolated subject on a transparent background, no scenery, no ground, no shadow）"
NOTEXT_TAIL = "画面里不要出现任何文字、字母、数字、水印或 logo。"
TIMEOUT = 360.0                                                                            # 高画质 + 2K 要 3~5 分钟（API易 文档：别用 120 秒）
DEFAULT_MODEL = "gpt-image-2.5-sunburst-vip"
IMGD = paths.DATA / "img"
BOARD, REFS, TPL = IMGD / "board.json", IMGD / "refs", IMGD / "templates"
LOG_NAME, MD_NAME, OLD, SINGLE = "生图记录.json", "生图清单.md", "旧版", "单张"
MAX_REF_BYTES = 10 << 20
JOBN = "生图"


class ImgError(RuntimeError):
    def __init__(self, msg, status=0, fatal=False):
        super().__init__(msg)
        self.status, self.fatal = status, fatal


# ---------------- 认清单 ----------------
FILE_RE = re.compile(r"[\w\-.（）()]*?[\w）)]\.(?:png|jpe?g|webp)(?![\w.])", re.I)
RATIO_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*[:：∶xX×比]\s*(\d{1,2})(?![\d.])")
LABEL_RE = re.compile(r"^\s*(?:[-*+>]\s*|\d+[.、)]\s*)*(?:\*\*|__)?\s*(提示词|prompt|比例|画幅|尺寸|透明背景|透明|用在|用于|用途|位置|段落|文件名|编号)\s*(?:\*\*|__)?\s*[:：]?", re.I)
NEG = ("不开", "关闭", "关", "否", "不要", "不用", "无", "没有", "不透明", "不", "no", "off", "false", "✗", "×", "❌")
POS = ("开启", "开", "是", "要", "有", "需要", "yes", "on", "true", "✓", "√", "✅")


def _strip_md(s):
    s = re.sub(r"`{1,3}", "", s or "")
    s = re.sub(r"(\*\*|__)", "", s)
    return s.strip()


def _clean_line(s):
    """一行里的 Markdown 记号去掉：开头的 # - * > 1. 这些，粗体，行内代码。"""
    s = re.sub(r"^\s*(?:#{1,6}\s*|[-*+]\s+|>\s*|\d+[.、)]\s+)*", "", s or "")
    return _strip_md(s)


def _ratio(text):
    """一段字里的比例 → '16:9' 这种；认不出返回 None。"""
    for m in RATIO_RE.finditer(text or ""):
        r = f"{int(m.group(1))}:{int(m.group(2))}"
        if r in RATIOS:
            return r
    m = RATIO_RE.search(text or "")
    if m and int(m.group(2)):
        return nearest(int(m.group(1)) / int(m.group(2)))
    return None


def nearest(v):
    return min(RATIOS, key=lambda r: abs(math.log(int(r.split(":")[0]) / int(r.split(":")[1])) - math.log(max(v, 1e-3))))


def _trans(text):
    """「透明背景：开 / 不开」→ True / False；没写返回 None。"""
    m = re.search(r"(?:透明背景|透明|transparent)\s*(?:\*\*|__)?\s*[:：]?\s*(?:\*\*|__)?\s*([^\s,，;；|)）]{1,4})", text or "", re.I)
    if not m:
        return None
    v = m.group(1).lower()
    if any(v.startswith(x) for x in NEG):
        return False
    if any(v.startswith(x) for x in POS):
        return True
    return None


def _fix_name(name, seen):
    """文件名：去掉 Windows 不让用的字，统一 .png（存的就是 PNG），重名加 _2。"""
    n = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", _strip_md(name)).strip(" .")
    stem = re.sub(r"\.(png|jpe?g|webp)$", "", n, flags=re.I) or "img"
    out, k = stem + ".png", 2
    while out.lower() in seen:
        out, k = f"{stem}_{k}.png", k + 1
    seen.add(out.lower())
    return out


def _table(lines):
    """Markdown 表格（表头里有「提示词」那张）→ 条目。"""
    rows = [ln for ln in lines if ln.strip().startswith("|") and ln.count("|") >= 3]
    if len(rows) < 3:
        return []
    cells = [[_strip_md(c) for c in r.strip().strip("|").split("|")] for r in rows]
    head = cells[0]
    if not any(re.search(r"提示词|prompt", h, re.I) for h in head):
        return []
    col = {}
    for i, h in enumerate(head):
        if re.search(r"提示词|prompt", h, re.I):
            col.setdefault("prompt", i)
        elif "比例" in h or "画幅" in h:
            col.setdefault("ratio", i)
        elif "透明" in h:
            col.setdefault("trans", i)
        elif re.search(r"用在|用于|用途|段落|位置", h):
            col.setdefault("use", i)
        elif re.search(r"文件|编号|名", h):
            col.setdefault("file", i)
    out = []
    for c in cells[1:]:
        if all(re.fullmatch(r":?-{2,}:?", x or "-") for x in c):
            continue
        g = lambda k: c[col[k]] if k in col and col[k] < len(c) else ""      # noqa: E731
        fm = FILE_RE.search(g("file")) or FILE_RE.search(" ".join(c))
        t = g("trans")
        out.append({"file": fm.group(0) if fm else g("file"), "use": g("use"), "ratio": _ratio(g("ratio")),
                    "transparent": _trans("透明：" + t) if t else None, "prompt": g("prompt").replace("<br>", "\n").strip()})
    return out


def _entry(block):
    """清单里的一条（从带文件名的那一行到下一条之前）→ {file, use, ratio, transparent, prompt}。"""
    head = block[0]
    fm = FILE_RE.search(_strip_md(head))
    use, inline = "", ""
    rest = _clean_line(head)
    if fm:
        rest = rest.replace(fm.group(0), " ", 1)
    m_ = re.search(r"(提示词|prompt)\s*[:：]", rest, re.I)              # 一条写在一行里：「img03.png 比例 21:9 提示词：……」
    if m_:
        rest, inline = rest[:m_.start()], rest[m_.end():].strip()
    ratio0 = _ratio(re.split(r"比例|画幅|尺寸", rest, maxsplit=1)[1]) if re.search(r"比例|画幅|尺寸", rest) else None
    trans0 = _trans(rest) if re.search(r"透明|transparent", rest, re.I) else None
    rest = re.split(r"比例|画幅|尺寸|透明", rest, maxsplit=1)[0]
    rest = re.sub(r"^[\s:：\-—–|·、.)）(（]+|[\s:：\-—–|·、.(（)）]+$", "", rest)
    rest = re.sub(r"^(用在|用于|用途)\s*[:：]?\s*", "", rest)
    if rest and not LABEL_RE.match(rest):
        use = rest
    ratio, trans, prompt, plines, inp, fence = ratio0, trans0, "", [inline] if inline else [], bool(inline), False
    for raw in block[1:] + [""]:
        ln = raw.rstrip()
        if fence:
            if ln.strip().startswith("```"):
                fence = False
                inp = False
                continue
            plines.append(ln)
            continue
        lab = LABEL_RE.match(ln)
        if lab or not inp:                                       # 一行里写了好几样（「比例：16:9 ｜ 透明背景：开」）也认
            if ratio is None and re.search(r"比例|画幅|尺寸", ln):
                ratio = _ratio(re.split(r"比例|画幅|尺寸", ln, maxsplit=1)[1])
            if trans is None and re.search(r"透明|transparent", ln, re.I):
                trans = _trans(ln)
        if lab:
            name, val = lab.group(1).lower(), _strip_md(ln[lab.end():]).strip()
            inp = False
            if name in ("提示词", "prompt"):
                inp = True
                if val.startswith("```"):
                    fence = True
                    val = val[3:].strip()
                if val:
                    plines.append(val)
            elif name in ("用在", "用于", "用途", "位置", "段落"):
                use = use or re.split(r"[｜|]", val)[0].strip()
            continue
        if inp:
            if ln.strip().startswith("```"):
                fence = True
                continue
            plines.append(_clean_line(ln) if ln.strip() else "")
    prompt = "\n".join(plines).strip()
    if not prompt:                                               # 没写「提示词：」：取这一条里最长的一段字
        paras = [_clean_line(x) for x in block[1:] if x.strip() and not LABEL_RE.match(x) and len(_clean_line(x)) > 15]
        prompt = max(paras, key=len) if paras else ""
    prompt = re.sub(r"\n{3,}", "\n\n", prompt).strip()
    return {"file": fm.group(0) if fm else "", "use": use[:80], "ratio": ratio, "transparent": trans, "prompt": prompt}


def parse(md, name=""):
    """生图清单 Markdown → {title, direction, items, warn}。表格、标题 + 列表、编号列表几种写法都认；认不全的写进 warn。"""
    text = (md or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    title = next((_clean_line(x) for x in lines if re.match(r"^#\s+\S", x)), "") or Path(name or "").stem or "生图清单"
    # 视觉方向：带「视觉方向」的标题或标签之后，到下一个标题或第一条之前
    direction = ""
    for k, ln in enumerate(lines):
        if "视觉方向" in ln and not FILE_RE.search(ln):
            after = re.split(r"视觉方向[^:：\n]*[:：]", _strip_md(ln), maxsplit=1)
            buf = [after[1].strip()] if len(after) > 1 and after[1].strip() and not ln.lstrip().startswith("#") else []
            for x in lines[k + 1:]:
                if re.match(r"^\s*#{1,6}\s", x) or FILE_RE.search(x) or (x.strip().startswith("|") and "|" in x[1:]):
                    break
                buf.append(_clean_line(x))
            direction = re.sub(r"\n{3,}", "\n\n", "\n".join(buf)).strip()
            break
    items = _table(lines)
    if not items:
        starts = []
        fence = False
        for k, ln in enumerate(lines):
            if ln.strip().startswith("```"):
                fence = not fence
            if fence or not FILE_RE.search(_strip_md(ln)):
                continue
            lab = LABEL_RE.match(ln)
            if (lab and lab.group(1).lower() in ("提示词", "prompt")) or re.match(r"^#\s", ln):     # 大标题里提到文件名的不算一条
                continue
            starts.append(k)
        for n_, s in enumerate(starts):
            e = starts[n_ + 1] if n_ + 1 < len(starts) else len(lines)
            blk = lines[s:e]
            while blk and (not blk[-1].strip() or re.match(r"^\s*(#{1,6}\s|---+\s*$)", blk[-1])):
                blk.pop()
            e_ = _entry(blk)
            if e_["prompt"] or e_["ratio"] or e_["transparent"] is not None:     # 只提到一个文件名、别的都没有：不是一条
                items.append(e_)
    warn, seen, out = [], set(), []
    for k, it in enumerate(items, 1):
        orig = it["file"] or f"img{k:02d}.png"
        it["file"] = _fix_name(orig, seen)
        it["id"] = str(k)
        if it["file"] != re.sub(r'[\\/:*?"<>|]+', "", _strip_md(orig)):
            warn.append(f"第 {k} 条文件名改成了 {it['file']}")
        if it["ratio"] is None:
            it["ratio"] = "1:1" if it["transparent"] else "16:9"
            warn.append(f"{it['file']}：没写比例，先按 {it['ratio']}")
        if it["transparent"] is None:
            it["transparent"] = False
            warn.append(f"{it['file']}：没写透明背景开不开，先按不开")
        if not it["prompt"]:
            warn.append(f"{it['file']}：没认出提示词，在卡片上补上")
        out.append({"id": it["id"], "file": it["file"], "use": it["use"], "ratio": it["ratio"], "transparent": bool(it["transparent"]),
                    "prompt": it["prompt"], "src": it["prompt"]})
    return {"title": title[:60], "direction": direction[:2000], "items": out, "warn": warn}



# ---------------- 模型：认识的（带线路、价格、说明）+ 从 API易 拉的列表 ----------------
VENDORS = [("google", "Google"), ("openai", "OpenAI"), ("seedream", "Seedream"), ("flux", "Flux"), ("microsoft", "Microsoft"), ("xai", "xAI"), ("other", "其他")]
Q4, Q6, Q3 = ["auto", "low", "medium", "high"], ["auto", "low", "medium", "high", "xhigh", "max"], ["low", "medium", "high"]


def _m(v, name, route, price, sec, d, proto="openai", size="preset", q=None, trans="prompt", refs=4, warn=""):
    return {"v": v, "name": name, "route": route, "price": price, "sec": sec, "d": d, "proto": proto, "size": size, "q": q, "trans": trans,
            "refs": refs, "warn": warn}


KNOWN = {      # 按 API易 文档和网页版「AI 图片大师」的列表（2026-10）；价格是每张美元，None = 按量（按 token）
    "gpt-image-2.5-sunburst-vip": _m("openai", "GPT Image 2.5 Sunburst VIP", "逆向", .03, 80, "高质量 2.5 Adobe 线路，画质与编辑精度优先；30 档尺寸（1K/2K/4K）、4 档画质、透明背景",
                                     q=Q4, trans="api", refs=8, warn="当前不稳定"),
    "gpt-image-2.5-flare-vip": _m("openai", "GPT Image 2.5 Flare VIP", "逆向", .03, 60, "高质量 2.5 Adobe 线路，速度优先、画面偏软；30 档尺寸、4 档画质、透明背景",
                                  q=Q4, trans="api", refs=8, warn="当前不稳定"),
    "gpt-image-2-vip": _m("openai", "GPT Image 2 VIP", "逆向", .03, 90, "Codex 线路，10 个比例 × 1K/2K/4K 三档分辨率", q=Q4, trans="api", refs=8),
    "gpt-image-2.5-all": _m("openai", "GPT Image 2.5 All", "逆向", .03, 60, "ChatGPT 网页版线路（Images 2.5），文字还原度好、内容限制少；不认尺寸，比例写进提示词",
                            size="prompt", refs=5),
    "gpt-image-2-all": _m("openai", "GPT Image 2 All", "逆向", .025, 90, "ChatGPT 网页版线路；不认尺寸，比例写进提示词", size="prompt", refs=5),
    "gpt-image-2.5-sunburst": _m("openai", "GPT Image 2.5 Sunburst", "官转", None, 40, "画质优先，按 token 计费（画质开高很贵）；5 档画质", q=Q6, trans="api", refs=8),
    "gpt-image-2.5-flare": _m("openai", "GPT Image 2.5 Flare", "官转", None, 20, "速度优先，按 token 计费；5 档画质", q=Q6, trans="api", refs=8),
    "gpt-image-2": _m("openai", "GPT Image 2", "官转", None, 90, "上一代官转，按 token 计费", q=Q4, refs=8),
    "gpt-image-1.5": _m("openai", "GPT Image 1.5", "官转", None, 40, "按 token 计费", q=Q3, trans="api", refs=8),
    "gpt-image-1": _m("openai", "GPT Image 1", "官转", None, 40, "按 token 计费", q=Q3, trans="api", refs=8),
    "gpt-image-1-mini": _m("openai", "GPT Image 1 Mini", "官转", None, 20, "按 token 计费，便宜", q=Q3, trans="api", refs=8),
    "gemini-3-pro-image-preview": _m("google", "Nano Banana Pro", "", .09, 30, "Google，1K/2K/4K，按原图比例编辑", proto="gemini", size="gemini", refs=14),
    "gemini-3.1-flash-image": _m("google", "Nano Banana 2", "", .055, 15, "Google，0.5K~4K、14 种比例、最多 14 张参考图", proto="gemini", size="gemini", refs=14),
    "gemini-2.5-flash-image": _m("google", "Nano Banana", "", .02, 10, "Google，便宜、快", proto="gemini", size="gemini", refs=3),
    "seedream-5-0-pro-260628": _m("seedream", "Seedream 5.0 Pro", "", .12, 40, "字节，出 PNG，最多 10 张参考图", proto="seedream", size="seedream", refs=10),
    "seedream-5-0-flash-260915": _m("seedream", "Seedream 5.0 Flash", "", .018, 15, "字节，快、便宜（默认加水印，这里关掉）", proto="seedream", size="seedream", refs=10),
    "seedream-5-0-260128": _m("seedream", "Seedream 5.0", "", .035, 25, "字节 5.0 Lite", proto="seedream", size="seedream", refs=10),
    "seedream-4-5-251128": _m("seedream", "Seedream 4.5", "", .04, 25, "字节，只出 JPEG", proto="seedream", size="seedream", refs=10),
    "seedream-4-0-250828": _m("seedream", "Seedream 4.0", "", .03, 25, "字节，只出 JPEG", proto="seedream", size="seedream", refs=10),
    "flux-2-max": _m("flux", "FLUX.2 Max", "", .07, 15, "BFL 最高质量，最多 8 张参考图", proto="flux", size="flux", refs=8),
    "flux-2-pro": _m("flux", "FLUX.2 Pro", "", .03, 10, "BFL，最多 8 张参考图", proto="flux", size="flux", refs=8),
    "flux-2-flex": _m("flux", "FLUX.2 Flex", "", .06, 30, "BFL，能调步数", proto="flux", size="flux", refs=8),
    "flux-2-klein-9b": _m("flux", "FLUX.2 Klein 9B", "", .01, 3, "BFL，一秒出图，最多 4 张参考图", proto="flux", size="flux", refs=4),
    "flux-2-klein-4b": _m("flux", "FLUX.2 Klein 4B", "", .01, 3, "BFL，一秒出图，最多 4 张参考图", proto="flux", size="flux", refs=4),
    "grok-imagine-image": _m("xai", "Grok Imagine", "", .02, 15, "xAI（要对应分组的 Key）", size="preset", refs=4),
    "grok-imagine-image-quality": _m("xai", "Grok Imagine Quality", "", .045, 25, "xAI 高质量（要对应分组的 Key）", size="preset", refs=4),
}
VENDOR_RE = [("google", r"gemini|nano-banana|imagen"), ("openai", r"gpt-image|dall-e|gpt-4o-image|chatgpt-image"), ("seedream", r"seedream|seededit"),
             ("flux", r"flux|kontext"), ("microsoft", r"mai-image|microsoft"), ("xai", r"grok")]
IMG_RE = re.compile(r"gpt-image|dall-e|-image|image-|seedream|seededit|flux|kontext|nano-banana|imagen|mai-image|grok-imagine|midjourney|^mj|ideogram|recraft|qwen-image", re.I)
PROTO_OF = {"google": "gemini", "seedream": "seedream", "flux": "flux"}


def vendor_of(mid):
    if mid in KNOWN:
        return KNOWN[mid]["v"]
    return next((v for v, pat in VENDOR_RE if re.search(pat, mid, re.I)), "other")


def card(mid=None):
    """一个模型的说明卡：厂商、名字、线路、价格、大概多久、怎么调、认哪些参数。没收录的按厂商猜。"""
    mid = (mid or settings.S.get("imgModel") or DEFAULT_MODEL).strip()
    if mid in KNOWN:
        return dict(KNOWN[mid], id=mid, known=True)
    v = vendor_of(mid)
    proto = PROTO_OF.get(v, "openai")
    return dict(_m(v, mid, "", None, 60, "没收录的模型：按「" + dict(VENDORS)[v] + "」的方式调，先试一张看看", proto=proto,
                   size={"gemini": "gemini", "seedream": "seedream", "flux": "flux"}.get(proto, "preset")), id=mid, known=False)


def tiers_of(c):
    return TIERS if c["size"] in ("preset", "gemini") else ["2k"] if c["size"] == "seedream" else ["1k"] if c["size"] == "flux" else []


def dims(c, ratio, tier):
    if c["size"] == "preset":
        return SIZES.get(tier if tier in TIERS else "2k", SIZES["2k"]).get(ratio, SIZES["2k"]["16:9"])
    if c["size"] == "seedream":
        return SIZES["2k"].get(ratio, SIZES["2k"]["16:9"])
    if c["size"] == "flux":
        return SIZES["1k"].get(ratio, SIZES["1k"]["16:9"])
    return None


def est_usd(c, ratio, tier, quality):
    """一张大概多少美元；按次的就是那个价，官转按 token 粗算，不知道的 None。"""
    if c["price"] is not None:
        return c["price"]
    if c["route"] == "官转" and c["proto"] == "openai":
        w, h = dims(c, ratio, tier) or (1024, 1024)
        return TOKENS_1K.get(quality or "medium", 439) * (w * h / 1048576) * USD_OUT
    return None


def catalog():
    """按厂商分好的模型列表：认识的排前面；listed = 这个 Key 在 API易 上能用（拉过列表才知道）。"""
    cache = db.kv_get("img_models") or {}
    ids = cache.get("ids") or []
    allids = list(KNOWN) + sorted(set(ids) - set(KNOWN))
    cur = settings.S.get("imgModel") or DEFAULT_MODEL
    if cur not in allids:
        allids.append(cur)
    groups = []
    for v, name in VENDORS:
        ms = []
        for mid in allids:
            if vendor_of(mid) != v:
                continue
            c = card(mid)
            ms.append({k: c[k] for k in ("id", "name", "route", "price", "sec", "d", "warn", "known", "proto", "refs", "trans")} |
                      {"listed": (mid in ids) if ids else None, "q": c["q"], "tiers": tiers_of(c)})
        if ms:
            groups.append({"v": v, "name": name, "models": ms})
    return {"groups": groups, "ts": cache.get("ts"), "err": cache.get("err", ""), "n": len(ids), "default": DEFAULT_MODEL}


async def refresh_models():
    """用 Key 调 API易 的 GET /v1/models，挑出生图模型存起来（kv img_models）。"""
    k = settings.get_secret("imgKey")
    if not k:
        raise HTTPException(400, "先到 设置 › 云端 填 API易 Key，才能拉模型列表")
    url = (settings.S.get("imgBase") or "https://api.apiyi.com/v1").rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(url, headers={"Authorization": f"Bearer {k}"})
    except httpx.HTTPError as e:
        raise HTTPException(502, "连不上 API易：" + _scrub(type(e).__name__, k)) from None
    if r.status_code != 200:
        raise HTTPException(502, str(explain(r.status_code, r.text, k)))
    try:
        data = r.json().get("data") or []
    except Exception:
        raise HTTPException(502, "API易 返回的模型列表看不懂") from None
    ids = sorted({str(x.get("id")) for x in data if isinstance(x, dict) and x.get("id") and IMG_RE.search(str(x.get("id")))})
    db.kv_set("img_models", {"ts": time.time(), "ids": ids, "all": len(data), "err": ""})
    feed.add(f"拉了一遍 API易 的模型列表：{len(data)} 个模型里有 {len(ids)} 个生图的", "info", job=JOBN)
    return catalog()


# ---------------- 提示词、图片文件、报错 ----------------
def build_prompt(it, direction="", with_dir=False, no_text=True, kind="official"):
    """实际发出去的提示词：（视觉方向）+ 这一条 +（透明背景那句）+（不要文字那句）；不认尺寸的模型把比例写在最前面。"""
    parts = []
    if kind in ("reverse", "prompt"):
        w, h = (int(x) for x in it["ratio"].split(":"))
        parts.append(f"画面比例 {it['ratio']}（{'横版' if w > h else '竖版' if w < h else '正方形'}）。")
    if with_dir and direction:
        parts.append("这一组图的统一画风：" + direction.strip())
    parts.append(it["prompt"].strip())
    if it["transparent"]:
        parts.append(TRANS_TAIL)
    if no_text:
        parts.append(NOTEXT_TAIL)
    return "\n\n".join(p for p in parts if p)


def png_info(b):
    """PNG / JPEG / WEBP 的宽、高、有没有透明通道（不用 Pillow：只读文件头）。"""
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", b[16:24])
        ct = b[25]
        return {"fmt": "png", "w": w, "h": h, "alpha": ct in (4, 6) or b"tRNS" in b[:4096]}
    if b[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            mk, ln = b[i + 1], struct.unpack(">H", b[i + 2:i + 4])[0]
            if mk in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", b[i + 5:i + 9])
                return {"fmt": "jpg", "w": w, "h": h, "alpha": False}
            i += 2 + ln
        return {"fmt": "jpg", "w": 0, "h": 0, "alpha": False}
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return {"fmt": "webp", "w": 0, "h": 0, "alpha": b"ALPH" in b[:200] or (b[12:16] == b"VP8X" and bool(b[20] & 0x10))}
    raise ImgError("API易返回的不是图片（PNG / JPEG / WEBP 都不是）")


MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _scrub(s, k):
    s = str(s or "")
    return s.replace(k, "***") if k else s


def explain(status, raw, k=""):
    """API易 / OpenAI 的报错 → 一句中文。fatal：后面的也都会失败（Key 不对、余额不够、限流），就别接着出了。"""
    msg = ""
    try:
        j = json.loads(raw)
        e = j.get("error") if isinstance(j.get("error"), dict) else j
        msg = str(e.get("message") or e.get("msg") or j.get("detail") or "")
    except Exception:
        msg = (raw or "")[:200]
    msg = _scrub(msg, k)[:200]
    low = msg.lower()
    if status == 401 or "invalid api key" in low or "无效的令牌" in msg:
        return ImgError("API易 Key 不对：到 设置 › 云端 重填（API易 控制台 › 令牌）", status, True)
    if status == 402 or "quota" in low or "余额" in msg or "insufficient" in low or "balance" in low:
        return ImgError("API易 余额不够了：去 API易 控制台充值，再点「只补没出的」", status, True)
    if status == 403 or "moderation" in low or "safety" in low or "content_policy" in low:
        return ImgError("内容审核没过：改一改提示词再重生成（别写真人、品牌、敏感的东西）" + (f"（{msg}）" if msg else ""), status)
    if status == 429:
        return ImgError("被限流了 / 上游太忙：过一会再点「只补没出的」" + (f"（{msg}）" if msg else ""), status, True)
    if status == 404:
        return ImgError(f"API易 说没有这个模型或接口：换个模型，或者看 设置 › 云端 的接口地址（{msg}）", status, True)
    if status == 400:
        return ImgError("参数不对：" + (msg or "看 生图记录.json 里发出去的是什么"), status)
    if status >= 500:
        return ImgError(f"API易 / 上游出错了（{status}）：过一会再点重生成" + (f"（{msg}）" if msg else ""), status)
    return ImgError(f"出错了（{status}）：{msg}", status)


def data_uri(b):
    fmt = png_info(b)["fmt"]
    return f"data:{MIME[fmt]};base64," + base64.b64encode(b).decode()


def read_uri(u):
    """界面传来的参考图（data:image/...;base64,...）→ 字节；只认 PNG / JPEG / WEBP，单张 10MB 以内。"""
    m = re.match(r"data:image/[\w.+-]+;base64,(.+)$", str(u or ""), re.S)
    if not m:
        raise HTTPException(400, "参考图格式不对（要 PNG / JPEG / WEBP）")
    try:
        b = base64.b64decode(m.group(1), validate=False)
    except Exception:
        raise HTTPException(400, "参考图读不出来") from None
    if len(b) > MAX_REF_BYTES:
        raise HTTPException(400, "参考图太大了：一张最多 10MB")
    try:
        png_info(b)
    except ImgError:
        raise HTTPException(400, "参考图只认 PNG / JPEG / WEBP") from None
    return b


# ---------------- 四种调用方式 ----------------
async def _post(c, url, k, **kw):
    try:
        r = await c.post(url, headers={"Authorization": f"Bearer {k}"}, **kw)
    except httpx.ConnectError:
        raise ImgError("连不上 API易：看看网，或者 设置 › 云端 的接口地址", 0, True) from None
    except httpx.TimeoutException:
        raise ImgError(f"{int(TIMEOUT // 60)} 分钟没回音：这张算没出来（可能已经计费），过一会点重生成") from None
    except httpx.HTTPError as e:
        raise ImgError("和 API易 的连接断了：" + _scrub(type(e).__name__, k)) from None
    if r.status_code != 200:
        raise explain(r.status_code, r.text, k)
    try:
        return r.json()
    except Exception:
        raise ImgError("API易 返回的不是 JSON") from None


async def _fetch(c, url):
    try:
        r = await c.get(url, timeout=60)
    except httpx.HTTPError as e:
        raise ImgError("图的下载链接打不开：" + type(e).__name__) from None
    if r.status_code != 200:
        raise ImgError(f"图的下载链接打不开（{r.status_code}）")
    return r.content


async def _image_of(c, j):
    d = (j.get("data") or [{}])[0] if isinstance(j, dict) else {}
    b64 = d.get("b64_json") or ""
    if b64:
        return base64.b64decode(b64.split(",", 1)[1] if b64.startswith("data:") else b64)
    if d.get("url"):
        return await _fetch(c, d["url"])
    raise ImgError("API易 返回成功，但里面没有图")


async def _call_openai(c, base, k, cd, prompt, ratio, tier, quality, transparent, refs):
    f = {"model": cd["id"], "prompt": prompt}
    wh = dims(cd, ratio, tier)
    if wh:
        f["size"] = f"{wh[0]}x{wh[1]}"
    if cd["q"] and quality in cd["q"]:
        f["quality"] = quality
    if cd["trans"] == "api":
        f["background"] = "transparent" if transparent else "opaque"
    if cd["route"] == "官转":
        f["output_format"] = "png"
    else:
        f["response_format"] = "b64_json"               # VIP、All：明着要 base64（默认给什么随负载变）
    if refs:
        name = "image[]" if len(refs) > 1 else "image"
        files = [(name, (f"ref{i + 1}.{png_info(b)['fmt']}", b, MIME[png_info(b)["fmt"]])) for i, b in enumerate(refs)]
        j = await _post(c, base + "/images/edits", k, data=f, files=files)
    else:
        j = await _post(c, base + "/images/generations", k, json=f)
    return await _image_of(c, j), j.get("usage"), f


async def _call_gemini(c, base, k, cd, prompt, ratio, tier, quality, transparent, refs):
    root = re.sub(r"/v1/?$", "", base)
    parts = [{"text": prompt}] + [{"inlineData": {"mimeType": MIME[png_info(b)["fmt"]], "data": base64.b64encode(b).decode()}} for b in refs]
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": ratio, "imageSize": (tier or "2k").upper()}}}
    j = await _post(c, f"{root}/v1beta/models/{cd['id']}:generateContent", k, json=body)
    cand = (j.get("candidates") or [{}])[0]
    img = None
    for p in (cand.get("content") or {}).get("parts") or []:
        d = p.get("inlineData") or p.get("inline_data")
        if d and d.get("data"):
            img = d["data"]                                     # 取最后一张（复杂的会先给草稿）
    if not img:
        why = cand.get("finishReason") or (j.get("promptFeedback") or {}).get("blockReason") or "没给图"
        raise ImgError(f"Google 没出图（{why}）：多半是被安全审核拦了，改一改提示词再试（被拦的不扣钱）")
    return base64.b64decode(img), None, {"model": cd["id"], "aspectRatio": ratio, "imageSize": (tier or "2k").upper(), "refs": len(refs)}


async def _call_seedream(c, base, k, cd, prompt, ratio, tier, quality, transparent, refs):
    w, h = dims(cd, ratio, tier)
    f = {"model": cd["id"], "prompt": prompt, "size": f"{w}x{h}", "watermark": False, "response_format": "b64_json"}
    if cd["id"].startswith("seedream-5"):
        f["output_format"] = "png"
    if refs:
        f["image"] = [data_uri(b) for b in refs]
        if not re.search(r"5-0-(pro|flash)", cd["id"]):
            f["sequential_image_generation"] = "disabled"
    j = await _post(c, base + "/images/generations", k, json=f)
    return await _image_of(c, j), None, {x: f[x] for x in f if x != "image"} | {"refs": len(refs)}


async def _call_flux(c, base, k, cd, prompt, ratio, tier, quality, transparent, refs):
    w, h = dims(cd, ratio, tier)
    f = {"model": cd["id"], "prompt": prompt, "size": f"{w}x{h}"}
    for i, b in enumerate(refs[:8]):
        f["input_image" if i == 0 else f"input_image_{i + 1}"] = data_uri(b)
    j = await _post(c, base + "/images/generations", k, json=f)
    return await _image_of(c, j), None, {x: f[x] for x in f if not x.startswith("input_image")} | {"refs": len(refs)}


CALL = {"openai": _call_openai, "gemini": _call_gemini, "seedream": _call_seedream, "flux": _call_flux}


# ---------------- 生图页的管家 ----------------
class Gen:
    def __init__(self):
        self.board = self._load()
        self.job = None
        self._task = None

    @property
    def s(self):
        return settings.S

    def key(self):
        return settings.get_secret("imgKey")

    def base(self):
        return (self.s.get("imgBase") or "https://api.apiyi.com/v1").rstrip("/")

    def out_root(self):
        return paths.resolve(self.s.get("imgOut", ""), paths.IMG_OUT)

    def folder(self):
        return Path(self.board["dir"]) if self.board and self.board.get("dir") else None

    def busy(self):
        return bool(self.job and self.job["st"] == "run")

    # ---------- 当前这份清单：存、读 ----------
    def _load(self):
        try:
            b = json.loads(BOARD.read_text("utf-8"))
            for it in b.get("items", []):
                if it.get("st") in ("run", "queue"):                 # 上次跑到一半 Agent 关了
                    it["st"] = "idle"
            return b
        except Exception:
            return None

    def _save(self):
        try:
            BOARD.parent.mkdir(parents=True, exist_ok=True)
            tmp = BOARD.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.board, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(BOARD)
        except Exception:
            pass

    def _scan(self):
        """文件夹里已经有的图：标成出好了（重新上传同一份清单，「只补没出的」就只补缺的）。"""
        d = self.folder()
        for it in self.board["items"]:
            p = d / it["file"] if d else None
            if p and p.exists() and it.get("st") != "ok":
                try:
                    info = png_info(p.read_bytes()[:65536])
                except Exception:
                    continue
                it.update(st="ok", w=info["w"], h=info["h"], alpha=info["alpha"], ver=int(p.stat().st_mtime), err="", old=True)

    def load(self, md, name=""):
        if self.busy():
            raise HTTPException(409, "正在出图，等这批出完或者先点「停下」")
        if not (md or "").strip():
            raise HTTPException(400, "清单是空的")
        if len(md) > 400_000:
            raise HTTPException(400, "清单太大了（超过 40 万字），是不是传错文件了")
        p = parse(md, name)
        if not p["items"]:
            raise HTTPException(400, "没认出图：清单里每条要有一个文件名（比如 img01_重点_地铁站.png）、比例、透明背景开不开、提示词")
        stem = re.sub(r"\s*[·\-—|]*\s*(GPT\s*Image\s*)?(生图清单|提示词清单|生图提示词|清单)\s*$", "", p["title"], flags=re.I).strip() or p["title"]
        safe = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", stem).strip(" .")[:40] or "生图"
        d = self.out_root() / f"{datetime.now():%Y-%m-%d}_{safe}"
        for it in p["items"]:
            it.update(st="idle", err="", warn="", w=0, h=0, alpha=None, sec=None, usd=None, ver=0, edited=False)
        self.job = None
        self.board = {"id": int(time.time() * 1000), "title": p["title"], "direction": p["direction"], "md": md, "md_name": (name or "")[:80],
                      "warn": p["warn"], "dir": str(d), "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "items": p["items"]}
        self._scan()
        self._save()
        n_ok = sum(1 for it in p["items"] if it["st"] == "ok")
        feed.add(f"认了一份生图清单「{p['title']}」：{len(p['items'])} 张" + (f"，文件夹里已经有 {n_ok} 张" if n_ok else ""), "info", job=JOBN)
        return self.board

    def clear(self):
        if self.busy():
            raise HTTPException(409, "正在出图，先点「停下」")
        self.board = None
        if self.job and self.job.get("kind") == "batch":
            self.job = None
        try:
            BOARD.unlink()
        except FileNotFoundError:
            pass

    def item(self, iid):
        it = next((x for x in (self.board or {}).get("items", []) if x["id"] == str(iid)), None)
        if not it:
            raise HTTPException(404, "没有这一张")
        return it

    def edit(self, iid, body):
        it = self.item(iid)
        if it["st"] in ("run", "queue"):
            raise HTTPException(409, "这张正在出，出完再改")
        if "prompt" in body:
            p = str(body["prompt"] or "").strip()
            if len(p) > 8000:
                raise HTTPException(400, "提示词太长了（最多 8000 字）")
            it["prompt"] = p
        if "ratio" in body:
            if body["ratio"] not in RATIOS:
                raise HTTPException(400, "比例只能是这 10 种：" + "、".join(RATIOS))
            it["ratio"] = body["ratio"]
        if "transparent" in body:
            it["transparent"] = bool(body["transparent"])
        it["edited"] = it["prompt"] != it.get("src")
        self._save()
        return it

    # ---------- 开始一批 ----------
    def _ready(self):
        if self.busy():
            raise HTTPException(409, "正在出图，等这批出完或者先点「停下」")
        if not self.key():
            raise HTTPException(400, "还没填 API易 的 Key：到 设置 › 云端 填好再生成")

    def _new_job(self, kind, tasks):
        cd = card()
        q, tier = self.s.get("imgQuality") or "high", self.s.get("imgRes") or "2k"
        est = [est_usd(cd, t["ratio"], tier, q) for t in tasks]
        self.job = {"id": int(time.time() * 1000), "st": "run", "kind": kind, "n": len(tasks), "done": 0, "fail": 0, "t0": time.time(), "t1": 0.0,
                    "stop": False, "usd": 0.0, "est": None if None in est else round(sum(est), 4), "model": cd["id"], "mname": cd["name"], "quality": q,
                    "tier": tier, "conc": max(1, min(4, int(self.s.get("imgConc") or 1))), "msg": "", "fatal": "", "results": [], "cur": None}
        feed.add(f"开始生图（{'批量' if kind == 'batch' else '单张'}）：{len(tasks)} 张，{cd['name']}、{QUALITY.get(q, q)}、{tier.upper()}" +
                 (f"，预估约 ${self.job['est']:.2f}" if self.job["est"] is not None else ""), "head", job=JOBN)
        self._task = asyncio.get_running_loop().create_task(self._run(self.job, tasks))
        return self.public()

    def start(self, ids=None, only_missing=False):
        self._ready()
        if not self.board or not self.board.get("items"):
            raise HTTPException(400, "先上传生图清单")
        items = self.board["items"]
        if ids:
            want = {str(x) for x in ids}
            todo = [it for it in items if it["id"] in want]
        elif only_missing:
            todo = [it for it in items if it["st"] != "ok"]
        else:
            todo = list(items)
        todo = [it for it in todo if it["prompt"].strip()]
        if not todo:
            raise HTTPException(400, "没有要出的：都出好了（要重出点那张的「重生成」），或者提示词是空的")
        d = self.folder()
        tasks = []
        for it in todo:
            it["prev"] = it["st"]
            it.update(st="queue", err="", warn="")
            tasks.append({"kind": "batch", "item": it, "label": it["file"], "prompt": it["prompt"], "ratio": it["ratio"], "transparent": it["transparent"],
                          "dir": d, "name": it["file"], "refs": [], "use": it.get("use", ""), "title": self.board.get("title", "")})
        self._save()
        return self._new_job("batch", tasks)

    def single(self, body):
        """单张：文生图 / 带参考图生图，一次 1~4 张。参考图先存一份到 data\\img\\refs（历史里能看到用了几张）。"""
        self._ready()
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(400, "写一句提示词")
        if len(prompt) > 8000:
            raise HTTPException(400, "提示词太长了（最多 8000 字）")
        ratio = body.get("ratio") if body.get("ratio") in RATIOS else "1:1"
        n = max(1, min(4, int(body.get("n") or 1)))
        cd = card()
        refs_in = body.get("refs") or []
        if len(refs_in) > max(1, cd["refs"]):
            raise HTTPException(400, f"{cd['name']} 最多 {cd['refs']} 张参考图")
        refs = [read_uri(u) for u in refs_in]
        rp = []
        if refs:
            REFS.mkdir(parents=True, exist_ok=True)
            stamp = int(time.time() * 1000)
            for i, b in enumerate(refs):
                p = REFS / f"{stamp}_{i + 1}.{png_info(b)['fmt']}"
                p.write_bytes(b)
                rp.append(p)
        day = self.out_root() / SINGLE / datetime.now().strftime("%Y-%m-%d")
        head = re.sub(r'[\\/:*?"<>|\r\n\t\s，。、；：！？,.;:!?]+', "", prompt)[:12] or "单张"
        stamp = datetime.now().strftime("%H%M%S")
        tasks = [{"kind": "single", "item": None, "label": f"{stamp}_{head}" + (f"_{i + 1}" if n > 1 else "") + ".png", "prompt": prompt, "ratio": ratio,
                  "transparent": bool(body.get("transparent")), "dir": day, "name": f"{stamp}_{head}" + (f"_{i + 1}" if n > 1 else "") + ".png",
                  "refs": rp, "use": "单张" + (f" · {len(rp)} 张参考图" if rp else ""), "title": "单张"} for i in range(n)]
        return self._new_job("single", tasks)

    def stop(self):
        if self.busy():
            self.job["stop"] = True
            self.job["msg"] = "停下：没开始的不出了，正在出的出完就停（断开的话照样计费、图却丢了）"
        return self.public()

    async def _run(self, job, tasks):
        sem = asyncio.Semaphore(job["conc"])
        if job["kind"] == "batch":
            d = self.folder()
            d.mkdir(parents=True, exist_ok=True)
            self._write_md(d)
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=TIMEOUT, write=120.0, pool=None)) as c:
            async def one(t):
                async with sem:
                    if job["stop"]:
                        it = t["item"]
                        if it is not None:
                            it["st"] = it.pop("prev", "idle") if it.get("prev") in ("ok", "err") else "idle"
                        return
                    await self._one(c, job, t)
            await asyncio.gather(*(one(t) for t in tasks))
        job.update(st="stop" if job["stop"] else "done", t1=time.time(), cur=None)
        took = job["t1"] - job["t0"]
        mins = f"{int(took // 60)} 分 {int(took % 60):02d} 秒" if took >= 60 else f"{int(took)} 秒"
        job["msg"] = (f"{'停了' if job['stop'] else '好了'}：出了 {job['done']} 张" + (f"，{job['fail']} 张没出来" if job["fail"] else "") +
                      f"，用了 {mins}，约 ${job['usd']:.2f}（≈¥{job['usd'] * float(self.s.get('usdCny') or 7.2):.2f}）" + (f"。{job['fatal']}" if job["fatal"] else ""))
        if job["kind"] == "batch":
            self._save()
        feed.add("生图" + job["msg"], "warn" if job["fail"] or job["stop"] else "ok", job=JOBN)

    async def _one(self, c, job, t):
        cd = card(job["model"])
        it = t["item"]
        t0 = time.time()
        job["cur"] = {"label": t["label"], "prompt": t["prompt"], "ratio": t["ratio"], "transparent": t["transparent"], "use": t["use"], "t0": t0,
                      "sec": cd["sec"], "refs": len(t["refs"]), "size": "×".join(map(str, dims(cd, t["ratio"], job["tier"]) or ())) or t["ratio"]}
        if it is not None:
            it.update(st="run", t0=t0, err="", warn="")
            it.pop("prev", None)
        kind = "prompt" if cd["size"] == "prompt" else "official"
        direction = self.board.get("direction", "") if (t["kind"] == "batch" and self.board) else ""
        prompt = build_prompt(t, direction, bool(self.s.get("imgWithDir")), bool(self.s.get("imgNoText", True)), kind)
        k = self.key()
        res = {"label": t["label"], "ok": False, "item": it["id"] if it else None, "ratio": t["ratio"], "transparent": t["transparent"]}
        try:
            if job["fatal"]:
                raise ImgError(job["fatal"])
            refs = [p.read_bytes() for p in t["refs"]]
            img, usage, sent = await CALL.get(cd["proto"], _call_openai)(c, self.base(), k, cd, prompt, t["ratio"], job["tier"], job["quality"], t["transparent"], refs)
            pi = png_info(img)
            if usage and cd["price"] is None:
                usd = float(usage.get("output_tokens") or 0) * USD_OUT + float(usage.get("input_tokens") or 0) * USD_IN
            else:
                usd = cd["price"] if cd["price"] is not None else (est_usd(cd, t["ratio"], job["tier"], job["quality"]) or 0.0)
            name = t["name"] if pi["fmt"] == "png" else re.sub(r"\.png$", "." + pi["fmt"], t["name"])
            t["dir"].mkdir(parents=True, exist_ok=True)
            path = self._put(t["dir"], name, img)
            sec = round(time.time() - t0, 1)
            warn = []
            if t["transparent"] and not pi["alpha"]:
                warn.append("要透明背景，但出来的图没有透明通道：点重生成" + ("" if cd["trans"] == "api" else "，或者换个认透明背景的模型（GPT Image 2.5 / VIP）"))
            rw, rh = (int(x) for x in t["ratio"].split(":"))
            if pi["w"] and pi["h"] and abs(math.log((pi["w"] / pi["h"]) / (rw / rh))) > 0.05:
                warn.append(f"出来的比例是 {pi['w']}×{pi['h']}，不是 {t['ratio']}")
            if name != t["name"]:
                warn.append(f"API易给的是 {pi['fmt'].upper()}，存成了 {name}")
            hid = db.insert("img_history", {"ts": time.time(), "kind": t["kind"], "title": t["title"], "file": name, "path": str(path), "model": cd["id"],
                                            "prompt": t["prompt"], "sent": prompt, "ratio": t["ratio"], "tier": job["tier"], "quality": job["quality"],
                                            "transparent": int(bool(t["transparent"])), "w": pi["w"], "h": pi["h"], "alpha": int(bool(pi["alpha"])),
                                            "usd": round(usd, 4), "sec": sec, "refs": len(t["refs"])})
            ver = int(time.time() * 1000)
            if it is not None:
                it.update(st="ok", w=pi["w"], h=pi["h"], alpha=pi["alpha"], sec=sec, usd=round(usd, 4), ver=ver, warn="；".join(warn), saved=name, old=False, hid=hid)
            res.update(ok=True, hid=hid, w=pi["w"], h=pi["h"], alpha=pi["alpha"], usd=round(usd, 4), sec=sec, warn="；".join(warn), file=name)
            job["done"] += 1
            job["usd"] += usd
            self._log(t["dir"], t, prompt, cd, job, pi, usd, sec, name, sent)
            self._month(usd)
        except ImgError as e:
            if it is not None:
                it.update(st="err", err=str(e), sec=round(time.time() - t0, 1))
            res.update(err=str(e))
            job["fail"] += 1
            if e.fatal and not job["fatal"]:
                job["fatal"] = str(e)
                job["stop"] = True
        except Exception as e:                                       # 意外的：写清楚，不让整批卡住
            msg = _scrub(f"出错了：{type(e).__name__} {e}", k)[:200]
            if it is not None:
                it.update(st="err", err=msg)
            res.update(err=msg)
            job["fail"] += 1
        job["results"].append(res)
        if t["kind"] == "batch":
            self._save()

    def _put(self, d, name, img):
        """存图：同名的旧图挪进「旧版」（不删），新的原子地写进去。"""
        p = d / name
        if p.exists():
            od = d / OLD
            od.mkdir(exist_ok=True)
            stem, ext = os.path.splitext(name)
            q, k = od / f"{stem}_{datetime.now():%H%M%S}{ext}", 2
            while q.exists():
                q, k = od / f"{stem}_{datetime.now():%H%M%S}_{k}{ext}", k + 1
            p.replace(q)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(img)
        tmp.replace(p)
        return p

    def _write_md(self, d):
        """清单原文存一份（生图清单.md）；内容变了，旧的挪进「旧版」。"""
        p = d / MD_NAME
        md = self.board.get("md") or ""
        try:
            if p.exists():
                if p.read_text("utf-8") == md:
                    return
                self._put(d, MD_NAME, md.encode("utf-8"))
            else:
                p.write_text(md, "utf-8")
        except Exception:
            pass

    def _log(self, d, t, prompt, cd, job, pi, usd, sec, name, sent):
        p = d / LOG_NAME
        try:
            log = json.loads(p.read_text("utf-8")) if p.exists() else {}
        except Exception:
            log = {}
        log.setdefault("app", "Agent 生图")
        if t["kind"] == "batch" and self.board:
            log["title"], log["direction"] = self.board.get("title"), self.board.get("direction")
            order = {x["file"]: k for k, x in enumerate(self.board["items"])}
        else:
            order = {}
        imgs = log.setdefault("images", {})
        imgs[t["name"]] = {"file": name, "use": t.get("use", ""), "ratio": t["ratio"], "transparent": t["transparent"], "size": f"{pi['w']}x{pi['h']}",
                           "alpha": pi["alpha"], "model": cd["id"], "tier": job["tier"], "quality": job["quality"] if cd["q"] else None,
                           "refs": len(t["refs"]), "prompt_sent": prompt, "params": sent, "seconds": sec, "usd": round(usd, 4),
                           "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        log["images"] = dict(sorted(imgs.items(), key=lambda kv: (order.get(kv[0], 999), kv[1].get("time", ""))))
        try:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(log, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(p)
        except Exception:
            pass

    def _month(self, usd):
        m = datetime.now().strftime("%Y-%m")
        u = db.kv_get("img_usage") or {}
        x = u.get(m) or {"n": 0, "usd": 0.0}
        x["n"] += 1
        x["usd"] = round(x["usd"] + usd, 4)
        u[m] = x
        db.kv_set("img_usage", {k: u[k] for k in sorted(u)[-12:]})

    # ---------- 历史、模板 ----------
    def history(self, q="", limit=60, before=0):
        sql, args = "SELECT id,ts,kind,title,file,path,model,prompt,ratio,tier,quality,transparent,w,h,alpha,usd,sec,refs FROM img_history", []
        cond = []
        if q:
            cond.append("(prompt LIKE ? OR file LIKE ? OR title LIKE ?)")
            args += [f"%{q}%"] * 3
        if before:
            cond.append("id < ?")
            args.append(int(before))
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(200, int(limit))))
        out = []
        for r in db.q(sql, tuple(args)):
            x = dict(r)
            x["exists"] = Path(x.pop("path") or "").exists()
            x["transparent"], x["alpha"] = bool(x["transparent"]), bool(x["alpha"])
            out.append(x)
        return out

    def hpath(self, hid):
        r = db.one("SELECT path FROM img_history WHERE id=?", (int(hid),))
        p = Path(r["path"]) if r and r["path"] else None
        if not p or not p.exists():
            raise HTTPException(404, "这张图找不到了（文件被挪走或删了）")
        return p

    def templates(self):
        return db.kv_get("img_templates") or []

    def save_tpl(self, body):
        name = str(body.get("name") or "").strip()[:40]
        prompt = str(body.get("prompt") or "").strip()[:8000]
        if not name:
            raise HTTPException(400, "给模板起个名字")
        if not prompt and not body.get("refs"):
            raise HTTPException(400, "模板里至少要有提示词或者参考图")
        refs = [read_uri(u) for u in (body.get("refs") or [])[:14]]
        tid = str(int(time.time() * 1000))
        TPL.mkdir(parents=True, exist_ok=True)
        files = []
        for i, b in enumerate(refs):
            f = f"{tid}_{i + 1}.{png_info(b)['fmt']}"
            (TPL / f).write_bytes(b)
            files.append(f)
        tpl = {"id": tid, "name": name, "prompt": prompt, "model": str(body.get("model") or settings.S.get("imgModel") or DEFAULT_MODEL),
               "ratio": body.get("ratio") if body.get("ratio") in RATIOS else "1:1", "tier": body.get("tier") if body.get("tier") in TIERS else "2k",
               "quality": body.get("quality") if body.get("quality") in QUALITY else "high", "transparent": bool(body.get("transparent")),
               "n": max(1, min(4, int(body.get("n") or 1))), "refs": files, "ts": time.time()}
        ts = [x for x in self.templates() if x["name"] != name]
        for x in self.templates():
            if x["name"] == name:
                self._del_tpl_files(x)
        ts.insert(0, tpl)
        db.kv_set("img_templates", ts[:60])
        return tpl

    def _del_tpl_files(self, x):
        for f in x.get("refs") or []:
            try:
                (TPL / f).unlink()
            except OSError:
                pass

    def del_tpl(self, tid):
        ts = self.templates()
        x = next((t for t in ts if t["id"] == str(tid)), None)
        if not x:
            raise HTTPException(404, "没有这个模板")
        self._del_tpl_files(x)
        db.kv_set("img_templates", [t for t in ts if t["id"] != str(tid)])
        return self.templates()

    def tpl_ref(self, tid, k):
        x = next((t for t in self.templates() if t["id"] == str(tid)), None)
        try:
            p = TPL / x["refs"][int(k)]
        except (TypeError, IndexError, ValueError):
            raise HTTPException(404, "没有这张参考图") from None
        if not p.exists():
            raise HTTPException(404, "这张参考图找不到了")
        return p

    # ---------- 打开、打包 ----------
    def file(self, iid):
        it = self.item(iid)
        d = self.folder()
        p = d / it.get("saved", it["file"]) if d else None
        if not p or not p.exists():
            raise HTTPException(404, "这张还没出")
        return p

    def zip(self):
        d = self.folder()
        if not d or not d.exists():
            raise HTTPException(404, "还没出图")
        pics = sorted(x for x in d.iterdir() if x.is_file() and x.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        if not pics:
            raise HTTPException(404, "文件夹里还没有图")
        z, k = d.parent / f"{d.name}_图片.zip", 2
        while z.exists():
            z, k = d.parent / f"{d.name}_图片_{k}.zip", k + 1
        tmp = z.with_name(z.name + ".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as f:          # PNG 本来就压过，不再压
            for x in pics:
                f.write(x, x.name)
        tmp.replace(z)
        feed.add(f"生图打包好了：{paths.show(z)}（{len(pics)} 张）", "ok", job=JOBN)
        return z, len(pics)

    # ---------- 给界面 ----------
    def public(self):
        j = self.job
        if not j:
            return None
        out = {k: j.get(k) for k in ("id", "st", "kind", "n", "done", "fail", "msg", "est", "model", "mname", "quality", "tier", "conc", "fatal", "results")}
        out["usd"] = round(j["usd"], 4)
        out["elapsed"] = round((j["t1"] or time.time()) - j["t0"])
        cur = j.get("cur")
        out["cur"] = dict(cur, run_s=round(time.time() - cur["t0"], 1)) if cur else None
        return out

    def status(self):
        b = self.board
        m = datetime.now().strftime("%Y-%m")
        hint = settings.secret_hints().get("imgKey", "")
        board = None
        if b:
            now = time.time()
            board = {k: b.get(k) for k in ("id", "title", "direction", "md_name", "warn", "created")}
            board["dir"] = paths.show(Path(b["dir"])) if b.get("dir") else ""
            board["exists"] = bool(b.get("dir") and Path(b["dir"]).exists())
            board["items"] = [dict({k: it.get(k) for k in ("id", "file", "use", "ratio", "transparent", "prompt", "st", "err", "warn", "w", "h", "alpha",
                                                          "sec", "usd", "ver", "edited", "old", "hid")},
                                   run_s=round(now - it["t0"]) if it.get("st") == "run" and it.get("t0") else None) for it in b["items"]]
        cd = card()
        return {"board": board, "job": self.public(), "ratios": RATIOS, "tiers": TIERS, "quality": QUALITY,
                "sizes": {t: {r: f"{w}×{h}" for r, (w, h) in v.items()} for t, v in SIZES.items()},
                "model": {k: cd[k] for k in ("id", "name", "route", "price", "sec", "d", "warn", "known", "proto", "refs", "trans", "size", "v")} |
                         {"q": cd["q"], "tiers": tiers_of(cd), "vendor": dict(VENDORS)[cd["v"]]},
                "tokens": TOKENS_1K, "usd_out": USD_OUT,
                "cfg": {"model": cd["id"], "quality": self.s.get("imgQuality") or "high", "tier": self.s.get("imgRes") or "2k", "notext": bool(self.s.get("imgNoText", True)),
                        "withdir": bool(self.s.get("imgWithDir")), "key": bool(hint), "hint": hint, "base": self.s.get("imgBase")},
                "usdCny": float(self.s.get("usdCny") or 7.2), "month": (db.kv_get("img_usage") or {}).get(m) or {"n": 0, "usd": 0.0},
                "out": paths.show(self.out_root()), "templates": [dict(t, refs=len(t.get("refs") or [])) for t in self.templates()],
                "recent": self.history(limit=12)}


G = Gen()
api = APIRouter()


@api.get("/api/img")
def img_status():
    return G.status()


@api.get("/api/img/models")
def img_models():
    return catalog()


@api.post("/api/img/models/refresh")
async def img_models_refresh():
    return await refresh_models()


@api.post("/api/img/load")
def img_load(body: dict = Body(...)):
    G.load(body.get("md") or "", body.get("name") or "")
    return G.status()


@api.patch("/api/img/item/{iid}")
def img_edit(iid: str, body: dict = Body(...)):
    return {"item": G.edit(iid, body)}


@api.post("/api/img/run")
async def img_run(body: dict = Body(default={})):
    return {"job": G.start(body.get("ids"), bool(body.get("missing")))}


@api.post("/api/img/single")
async def img_single(body: dict = Body(...)):
    return {"job": G.single(body)}


@api.post("/api/img/stop")
def img_stop():
    return {"job": G.stop()}


@api.post("/api/img/clear")
def img_clear():
    G.clear()
    return G.status()


@api.get("/api/img/file/{iid}")
def img_file(iid: str):
    return FileResponse(G.file(iid), headers={"Cache-Control": "private, max-age=31536000"})     # 地址里带着版本号，换了图地址就变


@api.get("/api/img/hist")
def img_hist(q: str = "", limit: int = 60, before: int = 0):
    return {"items": G.history(q, limit, before)}


@api.get("/api/img/hfile/{hid}")
def img_hfile(hid: int):
    return FileResponse(G.hpath(hid), headers={"Cache-Control": "private, max-age=31536000"})


@api.post("/api/img/templates")
def img_tpl_save(body: dict = Body(...)):
    return {"template": G.save_tpl(body), "templates": [dict(t, refs=len(t.get("refs") or [])) for t in G.templates()]}


@api.delete("/api/img/templates/{tid}")
def img_tpl_del(tid: str):
    return {"templates": [dict(t, refs=len(t.get("refs") or [])) for t in G.del_tpl(tid)]}


@api.get("/api/img/tplref/{tid}/{k}")
def img_tpl_ref(tid: str, k: int):
    return FileResponse(G.tpl_ref(tid, k))


@api.post("/api/img/open")
def img_open(body: dict = Body(default={})):
    if body.get("hid"):
        d = G.hpath(body["hid"]).parent
    elif body.get("single"):
        d = G.out_root() / SINGLE
    else:
        d = G.folder() if G.folder() and G.folder().exists() else G.out_root()
    d.mkdir(parents=True, exist_ok=True)
    if paths.IS_WIN:
        os.startfile(str(d))          # 打开资源管理器（不是黑窗口）
        return {"msg": "打开了：" + paths.show(d)}
    return {"msg": "文件夹在：" + paths.show(d)}


@api.post("/api/img/zip")
def img_zip():
    z, n = G.zip()
    if paths.IS_WIN:
        os.startfile(str(z.parent))
    return {"zip": paths.show(z), "n": n, "msg": f"打包好了：{z.name}（{n} 张）"}
