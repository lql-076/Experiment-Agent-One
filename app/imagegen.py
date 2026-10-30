r"""生图（v1.8.15）：左边「生图」页的后端。

以前：视频窗口按《自媒体正本》出一份「生图清单」（这期的视觉方向 + 每张图的编号文件名、用在哪一段、比例、透明背景开不开、提示词），
作者一条一条复制提示词去生成，再一张张按文件名存，麻烦，名字也不统一。
现在：上传清单 Markdown → 认出每一条 → 按比例、透明背景调 API易（OpenAI 兼容的中转站）的 GPT Image 2.5 → 按清单里的文件名存进「生图输出」。

- 只把清单里的提示词（你在页面上改过的就用改过的）发给 API易，别的一律不发。
  Key 用 DPAPI 加密存在 data\secrets.bin（imgKey），不写日志、不进导出、不进时间轴和记录。
- 模型（设置 › 云端 / 页面上「模型」那块能换）：
  gpt-image-2.5-flare   默认。官转、按量（按 token）计费，最快；比例（size）、画质（quality）、透明背景（background）都能定
  gpt-image-2.5-sunburst 官转、按量，细节和编辑精度更好，慢一点
  gpt-image-2.5-all     官逆、按次 $0.025；不认 size、quality，比例只能写进提示词，透明背景不稳
- 比例 → 尺寸（SIZES）：清单只写比例（正本规定的 10 种），这里换成 API 要的像素：16 的倍数、长边不超过 3840、0.65~8.3 百万像素；
  「2K」档每张 200 多万像素（16:9 = 2048×1152，API易推荐的生产尺寸），「1K」档 100 多万像素、便宜一半多。
- 透明背景开：background=transparent + png，提示词后面加一句「只画主体、背景透明、不要地面和投影」；存完看 PNG 有没有透明通道，没有就标出来。
- 不放字：正本规矩 6（图里不放文字，AI 画的字容易乱码），默认在每条后面加一句「不要文字、logo、水印」（页面上能关）。
- 视觉方向：正本要求每条提示词里已经写了统一画风，所以默认只显示、不发；页面上能打开「拼进每条提示词」。
- 一次跑一批，同时出 imgConc 张（默认 3）。点「停下」：还没开始的不出了，正在出的出完再停——断开的话 API易照样计费、图却丢了。
  只试一次，不自动重试（失败的那张点「重生成」）；Key 不对、余额不够就整批停下。
- 存：生图输出\<日期>_<清单名>\<清单里的文件名>。重生成时旧的那张挪进同一个文件夹的「旧版」里（不删）。
  清单原文（生图清单.md）、每张实际发出去的提示词、尺寸、用时、花费记在同一个文件夹的 生图记录.json。「打包 zip」只打图（不含旧版）。
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
SIZES = {                                                                                  # 都是 16 的倍数，长短边比不超过 3:1
    "2k": {"16:9": (2048, 1152), "9:16": (1152, 2048), "1:1": (1536, 1536), "4:3": (1792, 1344), "3:4": (1344, 1792),
           "3:2": (1920, 1280), "2:3": (1280, 1920), "5:4": (1600, 1280), "4:5": (1280, 1600), "21:9": (2240, 960)},
    "1k": {"16:9": (1536, 864), "9:16": (864, 1536), "1:1": (1024, 1024), "4:3": (1280, 960), "3:4": (960, 1280),
           "3:2": (1536, 1024), "2:3": (1024, 1536), "5:4": (1280, 1024), "4:5": (1024, 1280), "21:9": (1680, 720)},
}
MODELS = [
    {"id": "gpt-image-2.5-flare", "name": "GPT Image 2.5 Flare", "d": "最快 · 按量计费 · 比例、画质、透明背景都能定", "kind": "official"},
    {"id": "gpt-image-2.5-sunburst", "name": "GPT Image 2.5 Sunburst", "d": "细节更好、慢一点 · 按量计费", "kind": "official"},
    {"id": "gpt-image-2.5-all", "name": "GPT Image 2.5 All", "d": "按次 $0.025 · 不认比例和画质（比例写进提示词）· 透明背景不稳", "kind": "reverse", "per": 0.025},
]
QUALITY = [("low", "草稿"), ("medium", "标准"), ("high", "精细"), ("xhigh", "更精细"), ("max", "最高")]
TOKENS_1K = {"low": 196, "medium": 439, "high": 1756, "xhigh": 3122, "max": 7024, "auto": 439}    # 1024² 一张的输出 token（API易 文档）
USD_OUT, USD_IN = 30 / 1e6, 5 / 1e6                                                        # 输出 $30、输入 $5 每百万 token（粗算）
TRANS_TAIL = "只画主体本身，背景完全透明：不要场景、不要地面、不要投影。（isolated subject on a transparent background, no scenery, no ground, no shadow）"
NOTEXT_TAIL = "画面里不要出现任何文字、字母、数字、水印或 logo。"
TIMEOUT = 360.0                                                                            # 高画质 + 2K 要 3~5 分钟（API易 文档：别用 120 秒）
BOARD = paths.DATA / "img" / "board.json"
LOG_NAME, MD_NAME, OLD = "生图记录.json", "生图清单.md", "旧版"
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


# ---------------- 尺寸、提示词、花费 ----------------
def model_info(m=None):
    m = m or settings.S.get("imgModel") or MODELS[0]["id"]
    return next((x for x in MODELS if x["id"] == m), {"id": m, "name": m, "d": "自己填的模型（按官转的参数发）", "kind": "official"})


def size_of(ratio, res=None):
    return SIZES.get(res or settings.S.get("imgRes") or "2k", SIZES["2k"]).get(ratio, SIZES["2k"]["16:9"])


def build_prompt(it, direction="", with_dir=False, no_text=True, kind="official"):
    """实际发出去的提示词：（视觉方向）+ 这一条 +（透明背景那句）+（不要文字那句）；官逆模型把比例写在最前面。"""
    parts = []
    if kind == "reverse":
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


def est_usd(it, model=None, quality=None, res=None):
    info = model_info(model)
    if info.get("per"):
        return info["per"]
    w, h = size_of(it["ratio"], res)
    q = quality or settings.S.get("imgQuality") or "medium"
    return TOKENS_1K.get(q, 439) * (w * h / 1048576) * USD_OUT


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


def _scrub(s, k):
    s = str(s or "")
    return s.replace(k, "***") if k else s


def explain(status, raw, k=""):
    """API易 / OpenAI 的报错 → 一句中文。fatal：整批都会失败的（Key 不对、余额不够），就别接着出了。"""
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
        return ImgError("内容审核没过：改一改这条提示词再重生成（别写真人、品牌、敏感的东西）" + (f"（{msg}）" if msg else ""), status)
    if status == 429:
        return ImgError("太快了，被限流：过一会再点「只补没出的」，或者把 设置 › 云端 的「同时出几张」调小", status, True)
    if status == 404:
        return ImgError(f"API易 说没有这个模型或接口：看 设置 › 云端 的生图模型、接口地址（{msg}）", status, True)
    if status == 400:
        return ImgError("参数不对：" + (msg or "看 生图记录.json 里发出去的是什么"), status)
    if status >= 500:
        return ImgError(f"API易 / OpenAI 那边出错了（{status}）：过一会再点重生成", status)
    return ImgError(f"出错了（{status}）：{msg}", status)


# ---------------- 一批 ----------------
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

    def out_root(self):
        return paths.resolve(self.s.get("imgOut", ""), paths.IMG_OUT)

    def folder(self):
        return Path(self.board["dir"]) if self.board and self.board.get("dir") else None

    def busy(self):
        return bool(self.job and self.job["st"] == "run")

    # ---------- 存、读 ----------
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
        self.job = None                                              # 上一份清单的那批结果不留在新清单上
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
        self.board, self.job = None, None
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
        if "use" in body:
            it["use"] = str(body["use"] or "")[:80]
        it["edited"] = it["prompt"] != it.get("src")
        self._save()
        return it

    # ---------- 出图 ----------
    def start(self, ids=None, only_missing=False):
        if self.busy():
            raise HTTPException(409, "正在出图，等这批出完或者先点「停下」")
        if not self.board or not self.board.get("items"):
            raise HTTPException(400, "先上传生图清单")
        if not self.key():
            raise HTTPException(400, "还没填 API易 的 Key：到 设置 › 云端 填好再生成")
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
        conc = max(1, min(6, int(self.s.get("imgConc") or 3)))
        info = model_info()
        q, res = self.s.get("imgQuality") or "medium", self.s.get("imgRes") or "2k"
        est = sum(est_usd(it, info["id"], q, res) for it in todo)
        self.job = {"id": int(time.time() * 1000), "st": "run", "n": len(todo), "done": 0, "fail": 0, "t0": time.time(), "t1": 0.0,
                    "stop": False, "usd": 0.0, "est": round(est, 4), "model": info["id"], "quality": q, "res": res, "conc": conc, "msg": "", "fatal": ""}
        for it in todo:
            it["prev"] = it["st"]
            it.update(st="queue", err="", warn="")
        self._save()
        feed.add(f"开始生图：{len(todo)} 张，{info['name']}、{dict(QUALITY).get(q, q)}、{res.upper()}，同时出 {conc} 张，预估约 ${est:.2f}", "head", job=JOBN)
        self._task = asyncio.get_running_loop().create_task(self._run(self.job, todo))
        return self.public()

    def stop(self):
        if self.busy():
            self.job["stop"] = True
            self.job["msg"] = "停下：没开始的不出了，正在出的出完就停（断开的话照样计费、图却丢了）"
        return self.public()

    async def _run(self, job, todo):
        sem = asyncio.Semaphore(job["conc"])
        d = self.folder()
        d.mkdir(parents=True, exist_ok=True)
        self._write_md(d)
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=TIMEOUT, write=60.0, pool=None)) as c:
            async def one(it):
                async with sem:
                    if job["stop"]:
                        it["st"] = it.pop("prev", "idle") if it.get("prev") in ("ok", "err") else "idle"
                        return
                    await self._one(c, job, it, d)
            await asyncio.gather(*(one(it) for it in todo))
        job.update(st="stop" if job["stop"] else "done", t1=time.time())
        took = job["t1"] - job["t0"]
        mins = f"{int(took // 60)} 分 {int(took % 60):02d} 秒" if took >= 60 else f"{int(took)} 秒"
        job["msg"] = (f"{'停了' if job['stop'] else '好了'}：出了 {job['done']} 张" + (f"，{job['fail']} 张没出来" if job["fail"] else "") +
                      f"，用了 {mins}，约 ${job['usd']:.2f}（≈¥{job['usd'] * float(self.s.get('usdCny') or 7.2):.2f}）" + (f"。{job['fatal']}" if job["fatal"] else ""))
        self._save()
        feed.add("生图" + job["msg"], "warn" if job["fail"] or job["stop"] else "ok", job=JOBN)

    async def _one(self, c, job, it, d):
        info = model_info(job["model"])
        it.update(st="run", t0=time.time(), err="", warn="")
        it.pop("prev", None)
        prompt = build_prompt(it, self.board.get("direction", ""), bool(self.s.get("imgWithDir")), bool(self.s.get("imgNoText", True)), info["kind"])
        w, h = size_of(it["ratio"], job["res"])
        body = {"model": info["id"], "prompt": prompt}
        if info["kind"] == "reverse":
            body["response_format"] = "b64_json"
        else:
            body.update(size=f"{w}x{h}", quality=job["quality"], output_format="png", n=1,
                        background="transparent" if it["transparent"] else "opaque")
        k = self.key()
        url = (self.s.get("imgBase") or "https://api.apiyi.com/v1").rstrip("/") + "/images/generations"
        try:
            if job["fatal"]:
                raise ImgError(job["fatal"])
            try:
                r = await c.post(url, json=body, headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"})
            except httpx.ConnectError:
                raise ImgError("连不上 API易：看看网，或者 设置 › 云端 的生图接口地址", 0, True) from None
            except httpx.TimeoutException:
                raise ImgError(f"{int(TIMEOUT // 60)} 分钟没回音：这张算没出来（可能已经计费），过一会点重生成") from None
            except httpx.HTTPError as e:
                raise ImgError("和 API易 的连接断了：" + _scrub(type(e).__name__, k)) from None
            if r.status_code != 200:
                raise explain(r.status_code, r.text, k)
            j = r.json()
            data = (j.get("data") or [{}])[0]
            b64 = data.get("b64_json") or ""
            if b64:
                img = base64.b64decode(b64.split(",", 1)[1] if b64.startswith("data:") else b64)
            elif data.get("url"):
                r2 = await c.get(data["url"])
                if r2.status_code != 200:
                    raise ImgError(f"图的下载链接打不开（{r2.status_code}）")
                img = r2.content
            else:
                raise ImgError("API易返回成功，但里面没有图")
            pi = png_info(img)
            u = j.get("usage") or {}
            usd = info["per"] if info.get("per") else (float(u.get("output_tokens") or 0) * USD_OUT + float(u.get("input_tokens") or 0) * USD_IN
                                                     if u else est_usd(it, info["id"], job["quality"], job["res"]))
            name = it["file"] if pi["fmt"] == "png" else re.sub(r"\.png$", "." + pi["fmt"], it["file"])
            self._put(d, name, img)
            sec = round(time.time() - it["t0"], 1)
            warn = []
            if it["transparent"] and not pi["alpha"]:
                warn.append("要透明背景，但出来的图没有透明通道：点重生成，或者换 Sunburst")
            if pi["w"] and pi["h"] and abs(math.log((pi["w"] / pi["h"]) / (int(it["ratio"].split(":")[0]) / int(it["ratio"].split(":")[1])))) > 0.05:
                warn.append(f"出来的比例是 {pi['w']}×{pi['h']}，不是 {it['ratio']}")
            if name != it["file"]:
                warn.append(f"API易给的是 {pi['fmt'].upper()}，存成了 {name}")
            it.update(st="ok", w=pi["w"], h=pi["h"], alpha=pi["alpha"], sec=sec, usd=round(usd, 4), ver=int(time.time() * 1000), warn="；".join(warn),
                      saved=name, old=False)
            job["done"] += 1
            job["usd"] += usd
            self._log(d, it, prompt, info, job, pi, usd, sec, name)
            self._month(usd)
        except ImgError as e:
            it.update(st="err", err=str(e), sec=round(time.time() - it["t0"], 1))
            job["fail"] += 1
            if e.fatal and not job["fatal"]:
                job["fatal"] = str(e)
                job["stop"] = True
        except Exception as e:                                       # 意外的：写清楚，不让整批卡住
            it.update(st="err", err=_scrub(f"出错了：{type(e).__name__} {e}", k)[:200])
            job["fail"] += 1
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

    def _log(self, d, it, prompt, info, job, pi, usd, sec, name):
        p = d / LOG_NAME
        try:
            log = json.loads(p.read_text("utf-8")) if p.exists() else {}
        except Exception:
            log = {}
        log.setdefault("app", "Agent 生图")
        log["title"], log["direction"] = self.board.get("title"), self.board.get("direction")
        order = {x["file"]: k for k, x in enumerate(self.board["items"])}
        imgs = log.setdefault("images", {})
        imgs[it["file"]] = {
            "file": name, "use": it.get("use", ""), "ratio": it["ratio"], "transparent": it["transparent"], "size": f"{pi['w']}x{pi['h']}",
            "alpha": pi["alpha"], "model": info["id"], "quality": None if info["kind"] == "reverse" else job["quality"],
            "prompt_sent": prompt, "edited": bool(it.get("edited")), "seconds": sec, "usd": round(usd, 4),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        log["images"] = dict(sorted(imgs.items(), key=lambda kv: order.get(kv[0], 999)))         # 按清单的顺序
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
        out = None
        if j:
            out = {k: j.get(k) for k in ("id", "st", "n", "done", "fail", "msg", "est", "model", "quality", "res", "conc", "fatal")}
            out["usd"] = round(j["usd"], 4)
            out["elapsed"] = round((j["t1"] or time.time()) - j["t0"])
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
                                                          "sec", "usd", "ver", "edited", "old")},
                                   run_s=round(now - it["t0"]) if it.get("st") == "run" and it.get("t0") else None) for it in b["items"]]
        return {"board": board, "job": self.public(), "models": MODELS, "ratios": RATIOS, "sizes": {r: {k: f"{w}×{h}" for k, (w, h) in v.items()} for r, v in SIZES.items()},
                "quality": QUALITY, "tokens": TOKENS_1K, "usd_out": USD_OUT,
                "cfg": {"model": self.s.get("imgModel"), "quality": self.s.get("imgQuality"), "res": self.s.get("imgRes"), "conc": self.s.get("imgConc"),
                        "notext": bool(self.s.get("imgNoText", True)), "withdir": bool(self.s.get("imgWithDir")), "key": bool(hint), "hint": hint,
                        "base": self.s.get("imgBase")},
                "usdCny": float(self.s.get("usdCny") or 7.2), "month": (db.kv_get("img_usage") or {}).get(m) or {"n": 0, "usd": 0.0},
                "out": paths.show(self.out_root())}


G = Gen()
api = APIRouter()


@api.get("/api/img")
def img_status():
    return G.status()


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


@api.post("/api/img/stop")
def img_stop():
    return {"job": G.stop()}


@api.post("/api/img/clear")
def img_clear():
    G.clear()
    return G.status()


@api.get("/api/img/file/{iid}")
def img_file(iid: str):
    p = G.file(iid)
    return FileResponse(p, headers={"Cache-Control": "private, max-age=31536000"})     # 地址里带着版本号，换了图地址就变


@api.post("/api/img/open")
def img_open():
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
