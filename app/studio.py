r"""自媒体视频工坊（v4.0.1，R12）：7 个零连线独立模块 + Markdown 清单 + 模块级真并发 + 实时进度 + 三窗一体视频总成。

模块：剧本与策划 / 生图测试台 / 配音·白页 / 配音·紫苏 / 背景配乐 / 视频制作总成 / 成片预览与发布。
没有端口、没有连线、没有 DAG、没有「缺上游」；每个模块各有独立 asyncio 任务，可同时跑。
模块之间靠项目 Lists/ 下的 Markdown 清单协作；生图测试台不参与成片。
本地 GPU（Qwen3-TTS / Stable Audio 3）串行，第二个本地模块显示排队；云端/API 与本地可并行。
每个模块有 runtime（status/pct/phase/started_at/last_took_s），前端 600ms 轮询。
工程存在 工作区\视频工坊\<项目名_时间戳>\project.json（不进仓库）。
"""
import asyncio
import contextvars
import copy
import hashlib
import json
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, Response

from . import (bgm, ccode, db, deepseek, feed, imagegen, paths, publish, render_ppt, render_web, settings, studio_assets,
               studio_cache as cache, studio_graph as graph, telemetry, tts, tts_cloud, video_maker)

JOBS = "视频工坊"
RATIOS = [("9:16", "竖屏 9:16（抖音）"), ("16:9", "横屏 16:9")]
STYLE_TAG = "知识科普 × 科技数码 × 搞笑段子"
ROLES = ("白页", "紫苏", "旁白")
ROLE_DEFAULT_VOICES = {"白页": "local:preset:Serena", "紫苏": "local:preset:Vivian", "旁白": "local:preset:Uncle_Fu"}
GAP = video_maker.GAP
MAX_SHOTS = 15
_GATES = {}
_CUR_MID = contextvars.ContextVar("studio_mid", default="")
_CUR_P = contextvars.ContextVar("studio_project", default=None)
_CUR_JOB = contextvars.ContextVar("studio_job", default=None)


def _loop_gate(name, factory):
    """每个事件循环一套锁，测试里多次 asyncio.run 也不会串。"""
    loop = asyncio.get_running_loop()
    key = (id(loop), name)
    ent = _GATES.get(key)
    if not ent or ent[0] is not loop:
        ent = (loop, factory())
        _GATES[key] = ent
    return ent[1]


def _api_gate():
    return _loop_gate("api", lambda: asyncio.Semaphore(4))


def _gpu_lock():
    return _loop_gate("gpu", asyncio.Lock)
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".wav", ".mp3", ".flac", ".ogg", ".m4a",
             ".mp4", ".mov", ".mkv", ".webm", ".srt", ".json"}

PLAN_SYS = """你是「白页 × 紫苏」短视频账号的编导。账号固定风格是：知识科普 × 科技数码 × 搞笑段子。
内核必须硬核：科技原理、产品逻辑、数据或反常识结论要讲清楚；外壳必须好笑：白页和紫苏用漫剧式的拌嘴、抬杠、夸张反应把知识演出来。
只回 JSON，不要 Markdown、不要解释。格式：
{
  "title": "视频标题，30 字以内，有信息量、不夸张",
  "desc": "发布简介，80 字以内",
  "tags": ["3~6 个话题，不带 #"],
  "bgm_prompt": "English prompt for Stable Audio 3: style, mood, instruments, tempo, no vocals, suitable under narration",
  "shots": [
    {"role": "白页 或 紫苏 或 旁白", "tone": "百炼语气指令，比如 冷静吐槽 / 轻松调侃 / 夸张惊呼 / 怒气冲冲",
     "text": "这一镜要念的台词，口语、顺口，20~55 字；正文里不要写 [笑] [叹气] 这类音效词",
     "image_prompt": "这一镜的画面提示词，中文 40~120 字：主体、动作、构图、光线、色调、画风、镜头角度；画面里不要文字/logo/水印",
     "seconds_hint": 6}
  ]
}
硬性要求：
- 时长必须 65~85 秒（严格超过 1 分钟）；总口播字数约 270~350 字，按 4~4.5 字/秒估算。
- 开头 2 秒必须有钩子：反常识结论、冲突、夸张提问，不要寒暄。
- 白页负责理性拆解、讲原理、下结论；紫苏负责情绪化捧哏、抬杠、夸张吐槽；旁白只在开头或转场少量使用。
- 结尾最后一句必须带互动暗号「下期暗号：白页紫苏」，并自然收束。
- 每条台词只写要念的字；语气写在 tone 里，tone 是给阿里云百炼 TTS 的自然语言指令。
- 如果用户给了完整口播文案：原文一个字都不要改，只在句子之间分段，补 role / tone / image_prompt。
- 画面提示词按整条视频的画幅来写：竖屏以中景/近景为主，主体放中间偏上，底部给字幕留空间；横屏注意左右构图。
- 每个分镜的画面要能独立看懂，前后镜头不要重复；风格统一。
- bgm_prompt 必须是英文，只写纯音乐（no vocals）。"""

PLAN_USER = """主题：{topic}
固定风格：{style}
画幅：{ratio}（{ratio_cn}）
目标时长：{seconds} 秒（必须 65~85 秒）
完整口播文案（如果下面有字，就原样分段，不要改写）：
{text}
"""


class StudioError(RuntimeError):
    pass


class StopRequested(Exception):
    pass


# ---------------- 分镜脚本 ----------------
def _json_of(text: str) -> dict:
    t = re.sub(r"^\s*```(?:json)?\s*", "", str(text or "").strip(), flags=re.I)
    t = re.sub(r"\s*```\s*$", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        raise StudioError("DeepSeek 回的不是 JSON")
    try:
        j = json.loads(t[a:b + 1])
    except ValueError as e:
        raise StudioError(f"DeepSeek 回的 JSON 读不了：{e}") from None
    if not isinstance(j, dict):
        raise StudioError("DeepSeek 回的不是一个对象")
    return j


def _pick(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return ""


def _clean_field(s) -> str:
    s = str(s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"^\s*(?:[-*+]\s*|\d+[.、)]\s*)", "", s, flags=re.M)
    s = re.sub(r"\*\*", "", s)
    return s.strip().strip("`").strip()


def normalize_plan(j: dict) -> dict:
    """把 DeepSeek / Gemini 给的结构整理成统一分镜；JSON 和 Markdown 共用。"""
    if not isinstance(j, dict):
        raise StudioError("剧本不是一个对象")
    title = _clean_field(_pick(j, "title", "标题")) or "未命名视频"
    desc = _clean_field(_pick(j, "desc", "description", "简介"))
    tags = _pick(j, "tags", "话题", "hashtags", "标签") or []
    if isinstance(tags, str):
        tags = re.split(r"[\s,，、#＃]+", tags)
    tags = [re.sub(r"^[#＃]+", "", str(x).strip())[:20] for x in tags if str(x).strip()][:10]
    bgm_prompt = _clean_field(_pick(j, "bgm_prompt", "bgm", "配乐提示词", "music_prompt"))
    raw = _pick(j, "shots", "分镜", "storyboard", "segments", "script")
    if isinstance(raw, dict):
        raw = raw.get("shots") or raw.get("分镜")
    if not isinstance(raw, list):
        raise StudioError("剧本里没有分镜列表（shots / 分镜）")
    shots = []
    for i, x in enumerate(raw):
        if isinstance(x, str):
            x = {"text": x}
        if not isinstance(x, dict):
            continue
        body = _clean_field(_pick(x, "text", "narration", "voiceover", "口播", "台词", "文案", "content", "line"))
        pic = _clean_field(_pick(x, "image_prompt", "image", "画面提示词", "画面", "prompt", "visual"))
        role = _clean_field(_pick(x, "role", "角色", "speaker_role"))[:12]
        speaker = _clean_field(_pick(x, "speaker", "音色", "voice_id", "voice"))[:80]
        tone = _clean_field(_pick(x, "tone", "语气", "emotion"))[:60]
        if not body:
            continue
        if not role or role not in ROLES:
            role = ROLES[i % 2]
        if not tone:
            tone = "轻松调侃" if role == "紫苏" else "冷静吐槽"
        if not pic:
            pic = body
        try:
            hint = float(_pick(x, "seconds_hint", "seconds", "duration", "时长") or 0)
        except (TypeError, ValueError):
            hint = 0
        if hint <= 0:
            hint = len(body) / 4.5
        shots.append({"text": body[:500], "role": role, "speaker": speaker, "tone": tone,
                      "image_prompt": pic[:1000], "seconds_hint": max(2.5, min(20.0, hint))})
    if len(shots) < 2:
        raise StudioError("剧本只认出不到 2 个分镜：检查一下格式，或者直接在 DeepSeek 里拆")
    shots = shots[:MAX_SHOTS]
    return {"title": title[:30] or "未命名视频", "desc": desc[:300], "tags": tags,
            "bgm_prompt": bgm_prompt[:1000], "shots": shots}


def parse_plan(text: str) -> dict:
    """DeepSeek 的 JSON 回复 → 统一分镜。"""
    return normalize_plan(_json_of(text))


def _md_field(block, *names):
    """Markdown 分镜里取一个字段（角色： / 语气： / 台词： / 画面提示词：）。"""
    pat = r"(?m)^\s*(?:\*\*)?(?:" + "|".join(re.escape(x) for x in names) + r")(?:\*\*)?\s*[:：]\s*(.*)$"
    m = re.search(pat, block)
    if not m:
        return ""
    first = m.group(1)
    rest = block[m.end():]
    nxt = re.search(r"(?m)^\s*(?:\*\*)?(?:角色|role|语气|tone|音色|speaker|voice_id|台词|口播|text|文案|line|画面提示词|画面|image_prompt|视觉|prompt|简介|描述|desc|话题|标签|tags|配乐提示词|配乐|bgm_prompt|music_prompt)(?:\*\*)?\s*[:：]", rest)
    if nxt:
        rest = rest[:nxt.start()]
    return _clean_field(first + ("\n" + rest if rest.strip() else ""))


def parse_script(text: str) -> dict:
    """Gemini 导出的剧本：优先认 JSON，再认 Markdown（## 分镜 + 角色/语气/台词/画面提示词）。"""
    raw = str(text or "").strip()
    if not raw:
        raise StudioError("剧本是空的")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S | re.I)
    cand = m.group(1) if m else raw
    if cand.lstrip().startswith("{"):
        try:
            j = json.loads(cand)
            if isinstance(j, dict) and (j.get("shots") or j.get("分镜")):
                return normalize_plan(j)
        except ValueError:
            pass
    title_m = re.search(r"(?m)^#\s+(.+)$", raw)
    title = _clean_field(title_m.group(1)) if title_m else "导入的剧本"
    first_shot = re.search(r"(?m)^##+\s+", raw)
    meta = raw[:first_shot.start()] if first_shot else raw
    desc = _md_field(meta, "简介", "描述", "desc")
    tags = _md_field(meta, "话题", "标签", "tags")
    bgm_prompt = _md_field(meta, "配乐提示词", "配乐", "bgm_prompt", "music_prompt")
    blocks = re.split(r"(?m)^##+\s+.*$", raw)
    blocks = blocks[1:] if len(blocks) > 1 else []
    shots = []
    for i, b in enumerate(blocks):
        body = _md_field(b, "台词", "口播", "text", "文案", "line")
        pic = _md_field(b, "画面提示词", "画面", "image_prompt", "视觉", "prompt")
        role = _md_field(b, "角色", "role")
        speaker = _md_field(b, "音色", "speaker", "voice_id")
        tone = _md_field(b, "语气", "tone")
        if not body:
            left = re.sub(r"(?m)^\s*(?:\*\*)?(?:角色|role|语气|tone|音色|speaker|画面提示词|画面|image_prompt|台词|口播|text)(?:\*\*)?\s*[:：].*$", "", b)
            left = _clean_field(left)
            if left:
                body = left.split("\n")[0]
                if not pic and "\n" in left:
                    pic = "\n".join(left.split("\n")[1:])
        if not body:
            continue
        if not role or role not in ROLES:
            role = ROLES[i % 2]
        if not tone:
            tone = "轻松调侃" if role == "紫苏" else "冷静吐槽"
        if not pic:
            pic = body
        shots.append({"text": body[:500], "role": role, "speaker": speaker[:80], "tone": tone[:60],
                      "image_prompt": pic[:1000], "seconds_hint": max(2.5, min(20.0, len(body) / 4.5))})
    if len(shots) < 2:
        raise StudioError("没认出分镜：用「## 分镜」分隔，每块写「角色：」「语气：」「台词：」「画面提示词：」")
    return {"title": title[:30] or "导入的剧本", "desc": desc[:300],
            "tags": [re.sub(r"^[#＃]+", "", x.strip())[:20] for x in re.split(r"[\s,，、#＃]+", tags) if x.strip()][:10],
            "bgm_prompt": bgm_prompt[:1000], "shots": shots[:MAX_SHOTS]}


def prompt_pack(project=None) -> str:
    """给 Gemini 的策划启动包（Markdown）。"""
    topic = ""
    title = ""
    if isinstance(project, dict):
        topic = str(project.get("topic") or "").strip()
        title = str(project.get("title") or "").strip()
    s = """# 视频工坊 · Gemini 策划启动包

你是一名短视频编导。请为「白页 × 紫苏」账号策划一条 65~85 秒的竖屏短视频，并只输出一个 JSON 代码块。

## 1. 账号固定风格
**知识科普 × 科技数码 × 搞笑段子**
- 内核必须硬核：科技原理、产品逻辑、数据或反常识结论要讲清楚。
- 外壳必须好笑：白页和紫苏用漫剧式拌嘴、抬杠、夸张反应把知识演出来。
- 不要写成单人口播；每 1~2 句换一次角色，让两个人有来有回。

## 2. 时长与节奏
- 总时长 **65~85 秒**（严格超过 1 分钟），总口播约 **270~350 字**。
- 开头 **2 秒**必须有钩子：反常识结论、冲突或夸张提问，不要寒暄。
- 结尾最后一句必须自然带出互动暗号：**「下期暗号：白页紫苏」**。

## 3. 双角色人设
- **白页**：理性、冷静、懂技术。负责讲原理、拆逻辑、下结论；吐槽时一针见血。
- **紫苏**：情绪外放、爱抬杠、反应夸张。负责接梗、质疑、惊呼、把观众想问的话问出来。
- **旁白**：只在开头或转场少量使用，声音平稳，不抢两个人的戏。

## 4. 阿里云百炼语气指令
- `tone` 写自然语言语气指令，例如：`冷静吐槽`、`轻松调侃`、`夸张惊呼`、`怒气冲冲`、`压低声音卖关子`、`无奈叹气式吐槽`。
- **台词正文 `text` 里不要写 `[笑]`、`[叹气]`、`[咳嗽]` 这类音效词**；需要笑、叹气、停顿，都写进 `tone`。
- 每条 `text` 是一句完整的口播，不要一句里塞两个人。

## 5. 严格输出格式
只输出一个 JSON 代码块，不要额外解释：
```json
{
  "title": "标题，30 字以内",
  "desc": "发布简介，80 字以内",
  "tags": ["3~6 个话题，不带 #"],
  "bgm_prompt": "English prompt for Stable Audio 3: style, mood, instruments, tempo, no vocals",
  "shots": [
    {
      "role": "白页",
      "tone": "冷静吐槽",
      "text": "这一句要念的台词",
      "image_prompt": "这一镜的画面提示词：主体、动作、构图、光线、色调、画风、镜头角度；画面里不要文字/logo/水印",
      "seconds_hint": 6
    }
  ]
}
```
字段必须齐全：`role` 只能是「白页」「紫苏」「旁白」之一；`tone` 是百炼语气指令；`text` 只写要念的字；`image_prompt` 要能独立生成一张画面；`seconds_hint` 是这一镜大概几秒。

## 6. Markdown 备选格式（不想输出 JSON 时）
```
# 视频标题
简介：一句话
话题：AI 科技 搞笑
配乐提示词：upbeat electronic, no vocals

## 分镜 1
角色：白页
语气：冷静吐槽
台词：这一句要念的台词
画面提示词：这一镜的画面
```
每个分镜一个 `##` 块，四个字段都要有。

## 7. 本次主题
{topic}
"""
    if title:
        s += "\n当前项目标题（可沿用或改得更好）：" + title + "\n"
    return s.replace("{topic}", topic or "（请在下面补充主题或完整口播文案）")


async def _ask_plan(topic, text, ratio, seconds):
    if not settings.get_secret("dsKey"):
        raise HTTPException(400, "还没填 DeepSeek Key：到 设置 › 云端 填好，再来拆解分镜")
    topic = str(topic or "").strip()
    text = str(text or "").strip()
    if not topic and not text:
        raise HTTPException(400, "先写一个主题，或者把完整口播文案贴进来")
    if len(topic) > 4000 or len(text) > 60000:
        raise HTTPException(400, "文案太长了：主题最多 4000 字，完整口播最多 6 万字")
    try:
        seconds = max(10, min(600, int(seconds or 60)))
    except (TypeError, ValueError):
        seconds = 60
    ratio_cn = dict(RATIOS).get(ratio, "竖屏 9:16（抖音）")
    user = PLAN_USER.format(topic=topic or "（见下面的完整文案）", ratio=ratio, ratio_cn=ratio_cn, style=STYLE_TAG, seconds=seconds,
                            text=text or "（没有，按主题创作）")
    try:
        r = await deepseek.chat([{"role": "system", "content": PLAN_SYS}, {"role": "user", "content": user}],
                                json_mode=True, max_tokens=6000, purpose="视频工坊拆解", temperature=0.45, timeout=180)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"DeepSeek 没拆出来：{type(e).__name__} {str(e)[:180]}") from None
    try:
        return parse_plan(r.get("text") or ""), float(r.get("cny") or 0)
    except StudioError as e:
        raise HTTPException(502, str(e)) from None


def _voice_label(v):
    if not isinstance(v, dict):
        return "Vivian"
    return str(v.get("label") or v.get("name") or v.get("speaker") or v.get("voice") or "音色")[:60]


def voice_options() -> list:
    out = []
    for s in tts.SPEAKERS:
        out.append({"id": f"local:preset:{s['id']}", "label": f"{s['name']} · {s['d']}", "engine": "local"})
    try:
        for v in tts.T.voices():
            out.append({"id": f"local:mine:{v['id']}", "label": f"我的音色 · {v['name']}" + (f" · {v.get('desc', '')[:24]}" if v.get("desc") else ""), "engine": "local"})
    except Exception:
        pass
    try:
        if tts_cloud.key():
            for v in tts_cloud.voices():
                out.append({"id": f"cloud:{v['id']}", "label": f"百炼 · {v.get('name') or v['id']}", "engine": "cloud"})
    except Exception:
        pass
    return out


def voice_config(vid) -> dict:
    """界面选的音色 id → 生成时用的配置。只认本机已有的音色，别的一律拒绝。"""
    vid = str(vid or "local:preset:Vivian").strip()
    if vid.startswith("local:preset:"):
        sid = vid.split(":", 2)[2]
        s = next((x for x in tts.SPEAKERS if x["id"].lower() == sid.lower()), None)
        if not s:
            raise HTTPException(400, "这个预设音色不在本机：刷新一下再选")
        return {"engine": "local", "mode": "preset", "speaker": s["id"], "label": s["name"], "id": vid}
    if vid.startswith("local:mine:"):
        mid = vid.split(":", 2)[2]
        v = next((x for x in tts.T.voices() if str(x.get("id")) == str(mid)), None)
        if not v:
            raise HTTPException(400, "这个「我的音色」找不到了：刷新一下再选")
        return {"engine": "local", "mode": "design", "desc": v.get("desc") or "", "name": v.get("name") or "",
                "seed": int(v.get("seed") or 1), "label": v.get("name") or "我的音色", "id": vid}
    if vid.startswith("cloud:"):
        cid = vid.split(":", 1)[1]
        v = tts_cloud.find_voice(cid)
        if not v:
            raise HTTPException(400, "这个百炼音色找不到了：到配音页同步一下，再回来选")
        return {"engine": "cloud", "voice": v["id"], "label": v.get("name") or v["id"], "id": vid}
    raise HTTPException(400, "不认识的音色")


def image_models() -> list:
    """生图节点能选的模型：imagegen 认识的 + 用 Key 拉过的，按厂商分好再摊平。"""
    try:
        cat = imagegen.catalog()
    except Exception:
        return []
    out = []
    for g in cat.get("groups") or []:
        for m in g.get("models") or []:
            out.append({"id": m.get("id"), "name": m.get("name") or m.get("id"), "vendor": g.get("name") or "",
                        "price": m.get("price"), "route": m.get("route") or "", "d": m.get("d") or "",
                        "listed": m.get("listed"), "known": m.get("known"), "gif": bool(m.get("gif")),
                        "svg": bool(m.get("svg")), "max_refs": int(m.get("max_refs") or 0),
                        "tiers": m.get("tiers") or []})
    return out


def _default_voice(p) -> dict:
    v = (p.get("settings") or {}).get("voice")
    if isinstance(v, dict) and (v.get("id") or v.get("speaker") or v.get("voice")):
        return v
    return {"engine": "local", "mode": "preset", "speaker": "Vivian", "label": "Vivian", "id": "local:preset:Vivian"}


def _init_role_voices(p, voice=None):
    """给项目补上白页 / 紫苏 / 旁白的默认音色；已有不动。"""
    st = p.setdefault("settings", {})
    st.setdefault("bgm_seconds", 0)
    st.setdefault("bgm_steps", 8)
    st.setdefault("bgm_seed", 20261118)
    st.setdefault("img_model", settings.S.get("imgModel") or imagegen.DEFAULT_MODEL)
    st.setdefault("img_resolution", settings.S.get("imgRes") or "2k")
    st.setdefault("img_quality", settings.S.get("imgQuality") or "high")
    st.setdefault("img_complexity", "medium")
    st.setdefault("img_transparent", False)
    st.setdefault("img_gif", False)
    st.setdefault("img_output", "normal")
    st.setdefault("img_format", "png")
    st.setdefault("gif_frames", 8)
    st.setdefault("gif_delay_ms", 150)
    st.setdefault("img_n", 1)
    st.setdefault("img_custom_w", 0)
    st.setdefault("img_custom_h", 0)
    st.setdefault("web_bg", "dark")
    st.setdefault("web_sub_pos", "bottom")
    st.setdefault("web_sub_size", 0)
    st.setdefault("web_sub_color", "")
    st.setdefault("web_gif_scale", 1)
    st.setdefault("web_motion", 1)
    st.setdefault("web_fps", 24)
    st.setdefault("ppt_file", "")
    steps = p.setdefault("steps", {})
    for k in ("web", "ppt"):
        steps.setdefault(k, {"st": "idle", "msg": "", "err": "", "pct": 0, "t0": 0, "t1": 0})
    rv = st.setdefault("role_voices", {})
    v = voice if isinstance(voice, dict) else _default_voice(p)
    base = str(v.get("id") or "local:preset:Vivian")
    alt = "local:preset:Serena" if "Vivian" in base else "local:preset:Vivian"
    for role, d in (("白页", base), ("紫苏", alt if v.get("engine") != "cloud" else base), ("旁白", base)):
        rv.setdefault(role, d)


def _shot_voice(p, s) -> dict:
    """这一句用哪个音色：逐句 speaker > 角色预设 > 项目音色。"""
    rv = (p.get("settings") or {}).get("role_voices") or {}
    vid = str(s.get("speaker") or rv.get(s.get("role") or "") or (p.get("settings", {}).get("voice") or {}).get("id") or "").strip()
    try:
        cfg = voice_config(vid)
    except HTTPException:
        cfg = None
    eng = str(s.get("tts_engine") or "auto")
    if cfg and eng in ("local", "cloud") and cfg.get("engine") != eng:
        pool = [v for v in voice_options() if v.get("engine") == eng]
        if pool:
            try:
                cfg = voice_config(pool[0]["id"])
            except HTTPException:
                pass
    if cfg:
        return cfg
    try:
        return voice_config(str((p.get("settings", {}).get("voice") or {}).get("id") or "local:preset:Vivian"))
    except HTTPException:
        return {"engine": "local", "mode": "preset", "speaker": "Vivian", "label": "Vivian", "id": "local:preset:Vivian"}


def _img_cfg(p, s) -> dict:
    st = p.get("settings") or {}
    shot = s or {}
    def pick(name, default):
        v = shot.get(name)
        return v if v not in (None, "") else st.get(name, default)
    cfg = {
        "model": pick("img_model", st.get("img_model") or settings.S.get("imgModel") or imagegen.DEFAULT_MODEL),
        "ratio": pick("img_ratio", p.get("ratio") or "9:16"),
        "resolution": pick("img_resolution", st.get("img_resolution") or settings.S.get("imgRes") or "2k"),
        "quality": pick("img_quality", st.get("img_quality") or settings.S.get("imgQuality") or "high"),
        "complexity": pick("img_complexity", st.get("img_complexity") or "medium"),
        "transparent": bool(pick("img_transparent", st.get("img_transparent", False))),
        "output": pick("img_output", st.get("img_output", "gif" if st.get("img_gif") else "normal")),
        "format": pick("img_format", st.get("img_format", "png")),
        "gif": False,
        "gif_frames": int(pick("gif_frames", st.get("gif_frames", 8)) or 8),
        "gif_delay_ms": int(pick("gif_delay_ms", st.get("gif_delay_ms", 150)) or 150),
        "n": max(1, min(4, int(pick("img_n", st.get("img_n", 1)) or 1))),
        "custom_w": int(pick("img_custom_w", st.get("img_custom_w", 0)) or 0),
        "custom_h": int(pick("img_custom_h", st.get("img_custom_h", 0)) or 0),
    }
    if cfg["ratio"] not in imagegen.RATIOS:
        cfg["ratio"] = p.get("ratio") if p.get("ratio") in imagegen.RATIOS else "9:16"
    if cfg["resolution"] not in (*imagegen.TIERS, "custom"):
        cfg["resolution"] = "2k"
    if cfg["resolution"] == "custom":
        if not cfg["custom_w"] or not cfg["custom_h"]:
            raise StudioError("自定义分辨率要同时填宽和高")
        err = imagegen.validate_size(cfg["custom_w"], cfg["custom_h"])
        if err:
            raise StudioError("自定义尺寸不合规：" + err)
    if cfg["output"] not in ("normal", "gif", "svg"):
        cfg["output"] = "normal"
    cfg["gif"] = cfg["output"] == "gif"
    cfg["gif_frames"] = max(2, min(16, cfg["gif_frames"]))
    cfg["gif_delay_ms"] = max(20, min(2000, cfg["gif_delay_ms"]))
    if cfg["custom_w"] or cfg["custom_h"]:
        err = imagegen.validate_size(cfg["custom_w"], cfg["custom_h"])
        if err:
            raise StudioError("自定义尺寸不合规：" + err)
    return cfg


def _ref_paths(p, s):
    d = Path(p["dir"])
    out = []
    refs = s.get("img_refs")
    if refs is None:
        refs = (p.get("settings") or {}).get("img_refs") or []
    if isinstance(refs, str):
        refs = [x.strip() for x in re.split(r"[\n,，;；]+", refs) if x.strip()]
    for q in refs or []:
        q = str(q or "").strip()
        if not q:
            continue
        if q.startswith("shot:"):
            sid = q.split(":", 1)[1]
            other = next((x for x in p.get("shots") or [] if x.get("id") == sid), None)
            q = (other or {}).get("image") or ""
            if not q:
                continue
        if q.startswith("data:"):
            continue
        path = Path(q)
        if not path.is_absolute():
            path = d / q
        if path.is_file() and path.stat().st_size <= 20 << 20 and len(out) < 16:
            out.append(path)
    return out


def _image_prompt(p, s, cfg):
    cd = imagegen.card(cfg["model"])
    kind = "prompt" if cd.get("size") == "prompt" else "official"
    prompt = imagegen.build_prompt({"prompt": s.get("image_prompt") or s.get("text") or "", "ratio": cfg["ratio"],
                                    "transparent": bool(cfg["transparent"])}, STYLE_TAG, False, True, kind)
    if cfg.get("gif"):
        prompt += "\n\n做成循环 GIF 动图：主体动作轻微循环，背景简洁，帧数约 %d，每帧 %d 毫秒。" % (cfg["gif_frames"], cfg["gif_delay_ms"])
    return prompt, cd


def _image_fps(p, s, cfg=None):
    cfg = cfg or _img_cfg(p, s)
    prompt, cd = _image_prompt(p, s, cfg)
    refs = _ref_paths(p, s)
    ref_sha = [cache.sha_file(x) for x in refs]
    base = {"model": cfg["model"], "prompt": prompt, "aspect_ratio": cfg["ratio"], "resolution": cfg["resolution"],
            "quality": cfg["quality"], "complexity": cfg["complexity"], "custom_w": cfg["custom_w"], "custom_h": cfg["custom_h"],
            "transparent": bool(cfg["transparent"]), "output_type": cfg["output"], "output_format": cfg["format"],
            "gif_frames": cfg["gif_frames"], "gif_delay_ms": cfg["gif_delay_ms"],
            "ref_image_sha256": ref_sha, "n": cfg["n"], "force_nonce": s.get("_force_nonce") or ""}
    return [cache.fingerprint("image", dict(base, variant=i)) for i in range(cfg["n"])], prompt, cd, refs


def _shot_image_dest(p, s, variant, ext="png"):
    i = (p.get("shots") or []).index(s) + 1
    stem = str(s.get("_dest_stem") or f"shot{i:02d}")
    suffix = "" if int(_img_cfg(p, s)["n"]) == 1 else f"_v{variant + 1}"
    return Path(p["dir"]) / "images" / f"{stem}{suffix}.{(ext or 'png').lower()}"


def _tts_fp(p, s, cfg):
    speaker = cfg.get("speaker") or cfg.get("voice")
    if not speaker and cfg.get("mode") == "design":
        speaker = (cfg.get("desc") or "") + "|" + str(cfg.get("seed") or "")
    speaker = speaker or cfg.get("id") or ""
    return cache.fingerprint("tts", {"engine": cfg.get("engine"), "speaker": speaker,
                                     "tone": s.get("tone") or "", "text": s.get("text") or ""})


def _wav_duration(path):
    try:
        sr, pcm = tts.read_wav(Path(path).read_bytes())
        return round(len(pcm) / 2 / sr, 2)
    except Exception:
        return 0.0


def _bgm_fp(p):
    st = p.get("settings") or {}
    try:
        sec = int(st.get("bgm_seconds") or 0) or int(round(float(p.get("total_seconds") or p.get("target_seconds") or 75)))
    except (TypeError, ValueError):
        sec = 75
    sec = max(10, min(bgm.MAX_S, sec))
    steps = max(1, min(32, int(st.get("bgm_steps") or 8)))
    seed = int(st.get("bgm_seed") or 20261118)
    prompt = (p.get("bgm_prompt") or "").strip() or f"{STYLE_TAG} 风格短视频背景音乐，纯音乐，无人声，情绪贴合旁白，节奏舒缓"
    return cache.fingerprint("bgm", {"prompt_en": prompt, "duration": sec, "steps": steps, "seed": seed, "v": 2}), prompt, sec, steps, seed


IMG_SETTING_KEYS = ("img_model", "img_resolution", "img_quality", "img_complexity", "img_transparent",
                    "img_gif", "img_output", "img_format", "gif_frames", "gif_delay_ms", "img_n", "img_custom_w", "img_custom_h")


def _norm_img_setting(k, v, cur):
    if k == "img_model":
        return str(v or "").strip()[:120]
    if k == "img_resolution":
        return v if v in (*imagegen.TIERS, "custom") else (cur or "2k")
    if k in ("img_quality", "img_complexity"):
        return str(v or "").strip()[:30]
    if k in ("img_transparent", "img_gif"):
        return bool(v)
    if k == "img_output":
        return v if v in ("normal", "gif", "svg") else "normal"
    if k == "img_format":
        return v if v in ("png", "jpeg", "webp") else "png"
    if k == "img_n":
        return max(1, min(4, int(v or 1)))
    if k == "gif_frames":
        return max(2, min(16, int(v or 8)))
    if k == "gif_delay_ms":
        return max(20, min(2000, int(v or 150)))
    if k in ("img_custom_w", "img_custom_h"):
        return max(0, min(4096, int(v or 0)))
    return v


def _stale_images(p, msg):
    for s in p.get("shots") or []:
        s["image_st"] = "stale"
        s["image_cache_hit"] = False
    _mark(p, "images", "stale", msg)
    _mark(p, "video", "stale", msg)


def _stale_track(p, track, msg):
    _mark(p, track, "stale", msg)
    _mark(p, "video", "stale", msg)


def _default_shot(p, n=1):
    _init_role_voices(p)
    role = ROLES[(n - 1) % 2]
    rv = (p.get("settings") or {}).get("role_voices") or {}
    return {"id": f"s{n}", "text": f"这是第 {n} 句测试台词，可以直接改成你要念的内容。",
            "role": role, "speaker": str(rv.get(role) or _default_voice(p).get("id") or ""),
            "tone": "轻松调侃" if role == "紫苏" else "冷静吐槽",
            "image_prompt": f"第 {n} 个测试画面：简洁、清晰、适合竖屏短视频，主体居中偏上。",
            "seconds_hint": 4.0, "image": "", "tts": "", "duration": 0.0, "start": 0.0, "end": 0.0,
            "image_st": "idle", "tts_st": "idle", "image_err": "", "tts_err": "", "image_ver": 0, "tts_ver": 0,
            "img_variants": [], "img_selected": 0, "img_fps": [], "image_cache_hit": False, "tts_cache_hit": False,
            "img_output": "normal", "img_format": "png", "tts_engine": "auto",
            "render": "static", "render_clip": "", "render_image": "", "ppt_points": [], "img_refs": []}


def ensure_default_shots(p):
    """空项目开箱可测：没有分镜、且用户没把最后一个删掉时，自动放 1 个可独立运行的测试分镜。"""
    if p.get("shots") or p.get("no_auto_shot"):
        return False
    p["shots"] = [_default_shot(p, 1)]
    p["placeholder"] = True
    video_maker.save_project(p)
    return True


def _render_mode(s):
    m = str(s.get("render") or "static").lower()
    return m if m in ("web", "ppt", "static") else "static"


# ---------------- 七个独立模块 ----------------
class Studio:
    def __init__(self):
        self.job = None
        self._task = None
        self._tasks = {}
        self._stops = {}
        self._jobs = {}
        self._stop = threading.Event()
        self._saved = 0.0
        self._save_lock = threading.Lock()
        self._gpu_busy = False

    # ---------- 状态 ----------
    def busy(self):
        return any(not t.done() for t in self._tasks.values()) or bool(self._task and not self._task.done())

    def _running_ids(self):
        return [mid for mid, t in self._tasks.items() if not t.done()]

    def _job(self):
        return _CUR_JOB.get() or self._jobs.get("compose") or self.job

    def public(self):
        running = self._running_ids()
        j = self._jobs.get("compose") if "compose" in running else ((self._jobs.get(running[0]) if running else None) or self.job)
        if running and not j:
            j = {"st": "run", "mode": "module", "step": running[0], "msg": "运行中", "pct": 0, "t0": time.time()}
        if not j:
            return None
        out = {k: j.get(k) for k in ("id", "st", "mode", "step", "pid", "stage", "msg", "pct", "err", "shot")}
        if running and out.get("st") != "run":
            out.update(st="run", msg=out.get("msg") or "运行中")
        out["elapsed"] = round((j.get("t1") or time.time()) - j.get("t0", time.time()))
        out["web"] = j.get("web") or {}
        out["ppt"] = j.get("ppt") or {}
        out["ffmpeg"] = j.get("ffmpeg") or {}
        out["running"] = running
        return out

    def _set_runtime(self, p, mid, phase, pct=None, status=None, took=None):
        try:
            m = graph.module_of(p, mid)
        except graph.GraphError:
            return
        rt = m.setdefault("runtime", {"status": "idle", "pct": 0, "phase": "待命", "started_at": 0, "last_took_s": 0})
        rt["phase"] = str(phase or "")[:160]
        if pct is not None:
            rt["pct"] = round(max(0.0, min(100.0, float(pct))), 1)
        if status:
            rt["status"] = status
            m["status"] = status
        if took is not None:
            rt["last_took_s"] = round(float(took), 1)
        self._save(p)

    def _phase(self, phase, pct=None, status=None):
        mid, p = _CUR_MID.get(), _CUR_P.get()
        if not mid or not p:
            return
        try:
            m = graph.module_of(p, mid)
        except graph.GraphError:
            return
        rt = m.setdefault("runtime", {"status": "idle", "pct": 0, "phase": "待命", "started_at": 0, "last_took_s": 0})
        rt["phase"] = str(phase or "")[:160]
        if pct is not None:
            rt["pct"] = round(max(0.0, min(100.0, float(pct))), 1)
        if status:
            rt["status"] = status
            m["status"] = status
        j = self._job()
        if j:
            j["msg"] = rt["phase"]
            if pct is not None:
                j["pct"] = rt["pct"]
        self._save(p)

    def _recover(self, p):
        if self.busy() and self.job and self.job.get("pid") == p.get("id"):
            return
        changed = False
        for m in p.get("modules") or []:
            if m.get("status") == "run":
                m.update(status="stale", error="上次跑到一半 Agent 重启了：点这个模块重跑")
                changed = True
        if p.get("st") == "run":
            p.update(st="err", error="上次跑到一半 Agent 重启了")
            changed = True
        if changed:
            video_maker.save_project(p)

    def _load(self, pid):
        p = video_maker.load_project(pid)
        if graph.valid_modules(p):
            p.pop("shots", None)
            p.pop("graph", None)
            graph.ensure_lists(p)
            return p
        d = Path(p["dir"])
        bak = d / (video_maker.PROJECT_FILE + ".v3.bak")
        try:
            if (d / video_maker.PROJECT_FILE).is_file() and not bak.is_file():
                shutil.copy2(d / video_maker.PROJECT_FILE, bak)
            graph.ensure_modules(p)
            p["st"] = "idle"
            video_maker.save_project(p)
            self._recover(p)
            return p
        except Exception as e:
            try:
                if bak.is_file():
                    shutil.copy2(bak, d / video_maker.PROJECT_FILE)
            except OSError:
                pass
            raise StudioError(f"旧工程迁移失败，原工程没动：{type(e).__name__} {str(e)[:200]}") from None

    @staticmethod
    def _pseudo(p, shots, **kw):
        pp = copy.deepcopy(p)
        pp["_transient"] = True
        pp["shots"] = shots
        pp.setdefault("steps", {k: {"st": "idle", "msg": "", "err": "", "pct": 0, "t0": 0, "t1": 0}
                                for k in ("plan", "images", "tts", "bgm", "web", "ppt", "video")})
        pp["files"] = {}
        pp["cost"] = {"images_usd": 0.0, "tts_cny": 0.0}
        pp.update(kw)
        return pp

    def _url(self, pid, rel, ver=0):
        return f"/api/studio/media?pid={quote(str(pid))}&path={quote(str(rel))}" + (f"&v={int(ver)}" if ver else "")

    def project_view(self, p):
        d = Path(p["dir"])
        files = {}
        for k, rel in (p.get("files") or {}).items():
            q = d / rel
            if q.is_file():
                st = q.stat()
                files[k] = {"rel": rel, "name": q.name, "size": st.st_size, "mtime": st.st_mtime,
                            "url": self._url(p["id"], rel, st.st_mtime)}
        for k, rel in (("video", "output/成片.mp4"), ("cover", "output/封面.png")):
            q = d / ((p.get("files") or {}).get(k) or rel)
            if k not in files and q.is_file():
                st = q.stat()
                files[k] = {"rel": (p.get("files") or {}).get(k) or rel, "name": q.name, "size": st.st_size, "mtime": st.st_mtime,
                            "url": self._url(p["id"], (p.get("files") or {}).get(k) or rel, st.st_mtime)}
        mods = []
        for m in p.get("modules") or []:
            item = dict(m)
            item.setdefault("runtime", {"status": "idle", "pct": 0, "phase": "待命", "started_at": 0, "last_took_s": 0})
            item["outputs"] = []
            for o in m.get("outputs") or []:
                q = d / str(o.get("rel") or "")
                if q.is_file():
                    x = dict(o)
                    x["url"] = self._url(p["id"], o["rel"], q.stat().st_mtime)
                    item["outputs"].append(x)
            mods.append(item)
        total = round(sum(float((x.get("params") or {}).get("seconds") or 0) for x in
                          ((graph.module_of(p, "compose").get("params") or {}).get("shots") or [])), 2)
        return {"id": p["id"], "name": p.get("name") or p["id"], "title": p.get("title") or "", "desc": p.get("desc") or "",
                "tags": p.get("tags") or [], "created": p.get("created") or "", "updated": p.get("updated") or "",
                "ratio": p.get("ratio") or "9:16", "style": STYLE_TAG, "style_tag": STYLE_TAG,
                "target_seconds": p.get("target_seconds") or 75, "topic": p.get("topic") or "",
                "source_text": p.get("source_text") or "", "bgm_prompt": p.get("bgm_prompt") or "",
                "settings": p.get("settings") or {}, "modules": mods, "modules_version": 4,
                "lists": graph.all_lists(p), "files": files,
                "total_seconds": total, "duration": round(float(p.get("duration") or 0), 2),
                "resolution": p.get("resolution") or "", "st": p.get("st") or "idle", "error": p.get("error") or "",
                "cost": p.get("cost") or {}, "dir": paths.show(d), "video_ok": bool((d / ((p.get("files") or {}).get("video") or "output/成片.mp4")).is_file())}

    def state(self, pid=None):
        projects = video_maker.list_projects()
        active = str(pid or db.kv_get("studio_active") or "").strip()
        if not active and projects:
            active = projects[0]["id"]
        p = None
        if not active and not projects:
            try:
                voice = voice_config("local:preset:Vivian")
                p = video_maker.new_project(safe_title("视频工坊草稿"), "9:16", STYLE_TAG, 75, topic="", voice=voice)
                p["settings"]["voice"] = voice
                p["settings"]["img_model"] = settings.S.get("imgModel") or imagegen.DEFAULT_MODEL
                _init_role_voices(p, voice)
                p["modules"] = graph.default_modules(p)
                p["modules_version"] = 4
                graph.write_lists(p)
                video_maker.save_project(p)
                active = p["id"]
                projects = video_maker.list_projects()
                db.kv_set("studio_active", active)
            except Exception:
                p = None
        if active and p is None:
            try:
                p = self._load(active)
                db.kv_set("studio_active", active)
            except (video_maker.MakerError, StudioError):
                p = None
        return {"projects": projects, "active": active, "project": self.project_view(p) if p else None,
                "job": self.public(), "voices": voice_options(), "ratios": [{"id": a, "label": b} for a, b in RATIOS],
                "style_tag": STYLE_TAG, "roles": list(ROLES), "models": image_models(),
                "default_model": settings.S.get("imgModel") or imagegen.DEFAULT_MODEL,
                "publish": {"pending": len(publish.pending()), "batch": len(((db.kv_get("pub_batch") or {}).get("items") or []))},
                "slot": [{"id": k, "label": v} for k, v in video_maker.SIZES.items()],
                "module_defs": graph.MODULE_DEFS, "module_types": graph.TYPE_LABEL, "fixed_ids": graph.FIXED_IDS}

    def select(self, pid):
        p = self._load(pid)
        db.kv_set("studio_active", p["id"])
        return self.state(p["id"])

    # ---------- 工程 ----------
    def new_project(self, body):
        ratio = body.get("ratio") if body.get("ratio") in video_maker.SIZES else "9:16"
        topic = str(body.get("topic") or "").strip()
        try:
            seconds = max(15, min(600, int(body.get("seconds") or 75)))
        except (TypeError, ValueError):
            seconds = 75
        voice = voice_config(body.get("voice_id"))
        p = video_maker.new_project(safe_title(topic or "未命名视频"), ratio, STYLE_TAG, seconds, topic=topic, voice=voice)
        p["settings"]["voice"] = voice
        p["settings"]["img_model"] = body.get("img_model") or settings.S.get("imgModel") or imagegen.DEFAULT_MODEL
        _init_role_voices(p, voice)
        p["title"] = safe_title(topic or "未命名视频")
        p["modules"] = graph.default_modules(p)
        p["modules_version"] = 4
        p.pop("shots", None)
        graph.write_lists(p)
        video_maker.save_project(p)
        db.kv_set("studio_active", p["id"])
        return self.state(p["id"])

    def script_import(self, body):
        p = self._load(_pid_of(body))
        text = str(body.get("text") or body.get("md") or body.get("script") or "").strip()
        if not text:
            raise StudioError("没有剧本内容：把 JSON / Markdown 贴进来，或者选一个文件")
        try:
            doc = graph.parse_script_doc(text)
        except graph.GraphError as e:
            raise HTTPException(400, str(e)) from None
        script = graph.module_of(p, "script")
        script["params"].update({"topic": str(body.get("topic") or script["params"].get("topic") or "")[:4000],
                                 "source_text": text[:60000], "script_doc": doc, "title": doc["title"], "desc": doc["desc"], "tags": doc["tags"]})
        p["title"], p["desc"], p["tags"] = doc["title"], doc["desc"], doc["tags"]
        data = graph.write_lists(p, doc)
        graph.apply_doc(p, doc)
        _mark(p, "plan", "ok", f"剧本导入：{len(doc['shots'])} 个分镜")
        script["status"] = "ok"
        video_maker.save_project(p)
        return {"state": self.state(p["id"]), "estimate": graph.estimate(doc), "summary": f"{len(doc['shots'])} 个分镜、{len(doc.get('bgm', {}).get('segments') or [])} 段配乐", "lists": data}

    async def script_plan(self, body):
        p = self._load(_pid_of(body))
        script = graph.module_of(p, "script")
        topic = str(body.get("topic") or script["params"].get("topic") or script["params"].get("source_text") or "").strip()
        text = str(body.get("text") or "").strip()
        if not topic and not text:
            raise HTTPException(400, "先在剧本模块里写一个主题，或者贴完整口播文案")
        t0 = time.time()
        self._set_runtime(p, "script", "正在请求 DeepSeek 拆解剧本…", 5, "running")
        try:
            j, cny = await _ask_plan(topic, text, p.get("ratio") or "9:16", p.get("target_seconds") or 75)
        except Exception as e:
            self._set_runtime(p, "script", "DeepSeek 拆解失败：" + _err_text(e)[:160], 0, "error", time.time() - t0)
            raise
        self._set_runtime(p, "script", "正在解析并写入 5 份 Markdown 清单…", 70, "running")
        doc = {"title": j["title"], "desc": j["desc"], "tags": j["tags"],
               "bgm": {"segments": [{"id": "bgm-1", "prompt": j["bgm_prompt"], "seconds": p.get("target_seconds") or 75,
                                     "steps": 8, "seed": int(time.time()) % 100000}]} if j.get("bgm_prompt") else {"segments": []},
               "shots": []}
        for i, s in enumerate(j["shots"]):
            render = "web" if (i == 0 or i % 5 == 4) else "ppt" if i % 3 == 2 else "static"
            doc["shots"].append({"id": f"s{i + 1}", "seconds": s.get("seconds_hint") or max(2.5, len(s["text"]) / 4.5),
                                 "render": render, "image": {"prompt": s["image_prompt"]},
                                 "voice": {"role": s["role"], "speaker": s.get("speaker") or "", "tone": s["tone"], "text": s["text"]}})
        script["params"].update({"topic": topic, "source_text": text[:60000], "script_doc": doc, "title": doc["title"],
                                 "desc": doc["desc"], "tags": doc["tags"]})
        p["title"], p["desc"], p["tags"] = doc["title"], doc["desc"], doc["tags"]
        p["cost"]["plan_cny"] = round(float((p.get("cost") or {}).get("plan_cny") or 0) + cny, 4)
        data = graph.write_lists(p, doc)
        graph.apply_doc(p, doc)
        script["status"] = "ok"
        took = time.time() - t0
        self._set_runtime(p, "script", f"已完成（{len(doc['shots'])} 个分镜，耗时 {took:.1f}s）", 100, "ok", took)
        video_maker.save_project(p)
        return {"state": self.state(p["id"]), "estimate": graph.estimate(doc), "summary": f"{len(doc['shots'])} 个分镜", "lists": data, "cny": round(cny, 4)}

    def list_get(self, pid, name):
        p = self._load(pid)
        return {"name": name, "text": graph.read_list(p, name), "lists": graph.all_lists(p)}

    def list_set(self, body):
        p = self._load(_pid_of(body))
        name = str(body.get("name") or "")
        graph.write_list(p, name, body.get("text") or "")
        graph.apply_lists(p)
        if name in graph.LIST_VOICE:
            mid = next(k for k, v in graph.LIST_VOICE.items() if v == name)
            graph.invalidate_dependents(p, mid)
        elif name == graph.LISTS[2]:
            graph.invalidate_dependents(p, "bgm")
        elif name == graph.LISTS[3]:
            graph.invalidate_dependents(p, "compose")
        video_maker.save_project(p)
        return {"state": self.state(p["id"]), "lists": graph.all_lists(p)}

    def module_update(self, body):
        p = self._load(_pid_of(body))
        m = graph.module_of(p, str(body.get("id") or ""))
        for k in ("x", "y"):
            if body.get(k) is not None:
                m[k] = max(-4000, min(14000, int(body[k])))
        for k in ("w", "h"):
            if body.get(k) is not None:
                m[k] = max(240 if k == "w" else 160, min(5000, int(body[k])))
        if body.get("title") is not None:
            m["title"] = str(body["title"] or "")[:60]
        changed = False
        if isinstance(body.get("params"), dict):
            prm = body["params"]
            if m["id"] in ("voice-white", "voice-zisu") and "lines" in prm:
                lines = prm["lines"]
                if not isinstance(lines, list) or len(lines) > 300:
                    raise HTTPException(400, "台词列表不对：最多 300 句")
                prm = dict(prm)
                prm["lines"] = [{"id": str(x.get("id") or f"l{i + 1}")[:20], "line_index": int(x.get("line_index") or 0),
                                 "text": str(x.get("text") or "")[:500], "tone": str(x.get("tone") or "")[:60],
                                 "speaker": str(x.get("speaker") or "")[:80], "engine": str(x.get("engine") or "auto")[:20]}
                                for i, x in enumerate(lines) if isinstance(x, dict)]
            if m["id"] == "image":
                for k in ("custom_w", "custom_h"):
                    if prm.get(k) is not None:
                        try:
                            prm[k] = max(0, min(4096, int(prm[k])))
                        except (TypeError, ValueError):
                            raise HTTPException(400, "自定义宽高要写数字") from None
                if prm.get("resolution") == "custom" or prm.get("custom_w") or prm.get("custom_h"):
                    err = imagegen.validate_size(prm.get("custom_w") or 0, prm.get("custom_h") or 0)
                    if err:
                        raise HTTPException(400, "自定义尺寸不合规：" + err)
            if m["id"] == "compose" and "shots" in prm:
                shots = prm["shots"]
                if isinstance(shots, list):
                    prm = dict(prm)
                    prm["shots"] = [{"id": str(x.get("id") or f"s{i + 1}")[:40], "line_index": int(x.get("line_index") or i + 1),
                                     "render": str(x.get("render") or "static") if x.get("render") in ("web", "ppt", "static") else "static",
                                     "text": str(x.get("text") or "")[:500], "visual": str(x.get("visual") or "")[:1000],
                                     "seconds": float(x.get("seconds") or 6), "transition": str(x.get("transition") or "淡入")[:20]}
                                    for i, x in enumerate(shots) if isinstance(x, dict)]
            if m["id"] == "publish" and "tags" in prm:
                tags = prm["tags"]
                if isinstance(tags, str):
                    tags = re.split(r"[\s,，、#＃]+", tags)
                prm["tags"] = [re.sub(r"^[#＃]+", "", str(x).strip())[:20] for x in (tags or []) if str(x).strip()][:10]
            old = json.dumps(m.get("params") or {}, ensure_ascii=False, sort_keys=True)
            m.setdefault("params", {}).update(prm)
            if json.dumps(m["params"], ensure_ascii=False, sort_keys=True) != old:
                changed = True
                graph.invalidate_dependents(p, m["id"])
                if m["status"] in ("ok", "warn"):
                    m["status"] = "stale"
            if m["id"] in ("script", "publish"):
                sp = m["params"]
                if "title" in prm:
                    p["title"] = str(sp.get("title") or "")[:30]
                if "desc" in prm:
                    p["desc"] = str(sp.get("desc") or "")[:300]
                if "tags" in prm:
                    p["tags"] = sp.get("tags") or []
        video_maker.save_project(p)
        return {"project": self.project_view(p), "module": m, "changed": changed}

    def module_layout(self, body):
        p = self._load(_pid_of(body))
        for q in body.get("modules") or []:
            if not isinstance(q, dict):
                continue
            try:
                m = graph.module_of(p, str(q.get("id") or ""))
            except graph.GraphError:
                continue
            m.update({k: int(q[k]) for k in ("x", "y", "w", "h") if q.get(k) is not None})
        video_maker.save_project(p)
        return {"ok": True}

    # ---------- 运行 ----------
    async def start_run(self, body):
        p = self._load(_pid_of(body))
        mid = str(body.get("id") or "")
        part = str(body.get("part") or "")
        if mid == "image" and body.get("batch"):
            shot_id = str(body.get("shot_id") or part or "").strip()
            part = "batch" + (":" + shot_id if shot_id else "")
        loop = asyncio.get_running_loop()
        if mid:
            graph.module_of(p, mid)
            if mid == "image" and body.get("force"):
                m = graph.module_of(p, mid)
                m["params"]["_force_nonce"] = f"{time.time():.6f}"
                video_maker.save_project(p)
            if not any(not t.done() for t in self._tasks.values()):
                self._stop.clear()
            old = self._tasks.get(mid)
            if old and not old.done():
                raise HTTPException(409, "这个模块正在跑：等它好了，或者先点它的「停止」")
            self._start_module_task(p, mid, part)
            await asyncio.sleep(0.05)
            return {"job": self.public(), "project": self.project_view(p)}
        if self._tasks and any(not t.done() for t in self._tasks.values()):
            raise HTTPException(409, "还有模块在跑：等它们好了，或者先逐个停下")
        self._stop.clear()
        self._saved = 0.0
        self.job = {"id": int(time.time() * 1000), "st": "run", "mode": "all", "step": "all", "pid": p["id"],
                    "stage": 1, "msg": "准备中", "pct": 0, "err": "", "shot": "", "t0": time.time(), "t1": 0.0,
                    "web": {}, "ppt": {}, "ffmpeg": {}}
        db.kv_set("studio_active", p["id"])
        self._task = loop.create_task(self._run_job(p))
        await asyncio.sleep(0.05)
        return {"job": self.public(), "project": self.project_view(p)}

    def _start_module_task(self, p, mid, part="", keep_job=False):
        loop = asyncio.get_running_loop()
        stop = threading.Event()
        self._stops[mid] = stop
        job = {"id": int(time.time() * 1000), "st": "run", "mode": "module", "step": mid, "pid": p["id"],
               "stage": 2 if mid == "compose" else 1, "msg": "准备中", "pct": 0, "err": "", "shot": "",
               "t0": time.time(), "t1": 0.0, "web": {}, "ppt": {}, "ffmpeg": {}}
        self._jobs[mid] = job
        if not keep_job:
            self.job = job
        db.kv_set("studio_active", p["id"])
        task = loop.create_task(self._module_task(p, mid, part, stop, job))
        self._tasks[mid] = task
        return task

    def stop(self, module_id=""):
        mid = str(module_id or "")
        if mid:
            task = self._tasks.get(mid)
            if not task or task.done():
                return {"ok": False, "msg": "这个模块现在没有在跑"}
            ev = self._stops.get(mid)
            if ev:
                ev.set()
            if mid in ("voice-white", "voice-zisu"):
                try:
                    tts.T.stop("视频工坊：你点了停下这个配音模块")
                except Exception:
                    pass
            if mid == "bgm":
                try:
                    if bgm.B.busy():
                        bgm.B.job["stop"] = "视频工坊：你点了停下这个配乐模块"
                except Exception:
                    pass
            j = self._jobs.get(mid) or {}
            if j.get("cc_eid"):
                try:
                    ccode.request_stop(j["cc_eid"], "视频工坊：你点了停下")
                except Exception:
                    pass
            j["msg"] = "停下中：当前这一步收尾后不再往下做"
            return {"ok": True, "msg": "停这个模块：当前这一步收尾后不再往下做", "job": self.public()}
        if not self.busy():
            return {"ok": False, "msg": "现在没有在跑的"}
        self._stop.set()
        for ev in self._stops.values():
            ev.set()
        if self.job:
            self.job["msg"] = "停下中：正在结束当前这一步……"
        try:
            tts.T.stop("视频工坊：你点了停下")
        except Exception:
            pass
        try:
            if bgm.B.busy():
                bgm.B.job["stop"] = "视频工坊：你点了停下"
        except Exception:
            pass
        for j in self._jobs.values():
            if j.get("cc_eid"):
                try:
                    ccode.request_stop(j["cc_eid"], "视频工坊：你点了停下")
                except Exception:
                    pass
        return {"ok": True, "msg": "全停了：当前这一步收尾后不再往下做", "job": self.public()}

    async def _module_task(self, p, mid, part, stop, job):
        tok_m = _CUR_MID.set(mid)
        tok_p = _CUR_P.set(p)
        tok_j = _CUR_JOB.set(job)
        m = graph.module_of(p, mid)
        rt = m.setdefault("runtime", {})
        rt.update(status="running", pct=0, phase="准备中", started_at=time.time(), last_took_s=0)
        m["status"] = "running"
        self._save(p, True)
        t0 = time.time()
        ok = False
        try:
            await self._run_module(p, mid, part)
            ok = True
        except StopRequested:
            job.update(st="stop", msg="停了：没做完的保留着", t1=time.time())
            rt.update(status="idle", pct=0, phase="已停止（没做完的保留着）")
            m["status"] = "stale"
        except asyncio.CancelledError:
            job.update(st="stop", msg="停了", t1=time.time())
            rt.update(status="idle", pct=0, phase="已停止")
            raise
        except Exception as e:
            msg = _err_text(e)
            job.update(st="err", err=msg, msg="没做成：" + msg[:200], t1=time.time())
            rt.update(status="error", phase=msg[:200])
            m["status"] = "err"
            m["error"] = msg[:500]
        finally:
            took = round(time.time() - t0, 1)
            if ok:
                job.update(st="done", pct=100, msg=f"完成（耗时 {took:.1f}s）", t1=time.time())
                rt.update(status="ok", pct=100, phase=f"已完成（耗时 {took:.1f}s）", last_took_s=took)
            elif rt.get("status") not in ("idle", "error"):
                rt.update(status="error", last_took_s=took)
            self._save(p, True)
            _CUR_MID.reset(tok_m)
            _CUR_P.reset(tok_p)
            _CUR_JOB.reset(tok_j)

    async def _run_job(self, p):
        p["st"] = "run"
        p["error"] = ""
        self._save(p, True)
        try:
            await self._run_full(p)
            if self._stopped():
                raise StopRequested()
            p["st"] = "done"
            self.job.update(st="done", pct=100, msg="全部完成", stage=4, t1=time.time())
            feed.add(f"视频工坊「{p.get('title') or p['id']}」跑完了", "ok", job=JOBS)
        except StopRequested:
            p["st"] = "stop"
            self.job.update(st="stop", msg="停了：没做完的保留着", t1=time.time())
        except asyncio.CancelledError:
            p["st"] = "stop"
            raise
        except Exception as e:
            msg = _err_text(e)
            p["st"] = "err"
            p["error"] = msg
            self.job.update(st="err", err=msg, msg="没做成：" + msg[:200], t1=time.time())
            feed.add(f"视频工坊没做成：{msg[:300]}", "err", job=JOBS)
        finally:
            self.job["t1"] = self.job.get("t1") or time.time()
            self._save(p, True)
            self._task = None

    async def _gen_project_images(self, p, ids=None):
        """按 compose 的分镜逐张出图（普通/GIF），把结果写回分镜的 image，供终混直接用。
        ids 为空时全部；给了 shot id / line_index 时只重绘这些镜。"""
        compose = graph.module_of(p, "compose")
        cshots = (compose.get("params") or {}).get("shots") or []
        if not cshots:
            return 0
        all_cshots = [dict(s) for s in cshots]
        if ids:
            want = {str(x) for x in ids}
            targets = [s for s in all_cshots if str(s.get("id")) in want or str(s.get("line_index")) in want]
        else:
            targets = all_cshots
        if not targets:
            return 0
        pp = self._pseudo(p, targets)
        im = graph.module_of(p, "image").get("params") or {}
        pp["settings"] = dict(pp.get("settings") or {})
        for k in ("img_model", "img_resolution", "img_quality", "img_complexity", "img_output", "img_format",
                  "gif_frames", "gif_delay_ms", "img_n", "img_custom_w", "img_custom_h", "img_transparent", "img_refs"):
            if im.get(k) not in (None, "", []):
                pp["settings"][k] = im[k]
        for s in pp["shots"]:
            s.setdefault("image_prompt", s.get("visual") or s.get("text") or "")
            s["image_st"] = "idle"
            s["img_variants"] = []
            s["img_selected"] = 0
        tok_m = _CUR_MID.set("image")
        tok_p = _CUR_P.set(p)
        tok_j = _CUR_JOB.set(self.job)
        try:
            await self._gen_images(pp)
        finally:
            _CUR_MID.reset(tok_m)
            _CUR_P.reset(tok_p)
            _CUR_JOB.reset(tok_j)
        by_id = {str(s.get("id")): s for s in pp["shots"]}
        img_items = graph.module_of(p, "image").get("params", {}).get("items") or []
        for s in cshots:
            q = by_id.get(str(s.get("id")))
            if not q:
                continue
            for k in ("image", "img_variants", "img_selected", "img_model", "image_st", "image_err",
                      "image_cache_hit", "image_ver", "image_w", "image_h"):
                if k in q:
                    s[k] = q[k]
            for it in img_items:
                if (it.get("line_index") == s.get("line_index")) or (str(it.get("shot_id")) == str(s.get("id"))):
                    if q.get("image"):
                        it["rel"] = q["image"]
                        it["status"] = "ok"
                    it["variants"] = q.get("img_variants") or []
                    it["selected"] = q.get("img_selected") or 0
        p["cost"]["images_usd"] = round(float((p.get("cost") or {}).get("images_usd") or 0) +
                                        float((pp.get("cost") or {}).get("images_usd") or 0), 4)
        n_ok = sum(1 for s in all_cshots if s.get("image"))
        im_mod = graph.module_of(p, "image")
        im_mod["status"] = "ok" if n_ok else "warn"
        rt = im_mod.setdefault("runtime", {})
        rt.update(status="ok" if n_ok else "warn", pct=100, phase=f"生图完成（{n_ok}/{len(all_cshots)} 张）",
                  last_took_s=rt.get("last_took_s") or 0)
        video_maker.save_project(p)
        return n_ok

    async def _run_full(self, p):
        self.job.update(stage=1, msg="第一阶段：生图 + 白页配音 + 紫苏配音 + 背景配乐", pct=2)
        await self._gen_project_images(p)
        if self._stopped():
            raise StopRequested()
        tasks = [(mid, self._start_module_task(p, mid, "", keep_job=True)) for mid in ("voice-white", "voice-zisu", "bgm")]
        res = await asyncio.gather(*(t for _m, t in tasks), return_exceptions=True)
        if self._stopped():
            raise StopRequested()
        errs = [f"{mid}：{_err_text(e)[:120]}" for (mid, _t), e in zip(tasks, res) if isinstance(e, Exception)]
        await self._rebuild_voice(p)
        if errs:
            self.job["msg"] = "配音/配乐有没成的，继续用已经有的：" + "；".join(errs[:2])
        self.job.update(stage=2, msg="第二阶段：视频制作总成（网页动效 + PPT + FFmpeg）", pct=35)
        ct = self._start_module_task(p, "compose", "", keep_job=True)
        try:
            await ct
        finally:
            if self._stopped():
                raise StopRequested()
        self.job.update(stage=3, msg="成片已送入预览与发布", pct=98)
        pub = graph.module_of(p, "publish")
        pub["status"] = "ok" if p.get("files", {}).get("video") else "idle"
        pub["params"]["waiting"] = True
        self._save(p, True)

    async def _run_module(self, p, mid, part=""):
        m = graph.module_of(p, mid)
        key = graph.cache_key(p, m)
        raw = m.get("outputs") or []
        outs = [o for o in raw if _output_ok(p, o)]
        if not part and raw and len(outs) == len(raw) and m.get("cache_key") == key:
            m.update(status="ok", error="", cache_hit=True)
            rt = m.setdefault("runtime", {})
            rt.update(status="ok", pct=100, phase="缓存命中（没有重新花钱）", last_took_s=0)
            self._save(p, True)
            return
        m.update(status="running", error="", cache_hit=False)
        self._phase(f"{m.get('title') or mid}：开始", 1, "running")
        self._save(p, True)
        try:
            out = await self._exec_module(p, m, part)
            m["outputs"] = [o for o in (out or []) if _output_ok(p, o)]
            for o in m["outputs"]:
                if not o.get("sha256"):
                    q = Path(p["dir"]) / o["rel"]
                    o["sha256"] = cache.sha_file(q)
                    o["size"] = q.stat().st_size
            m.update(status="ok", error="", cache_key=graph.cache_key(p, m), cache_hit=bool(m.get("cache_hit")), finished=time.time())
            if mid in ("voice-white", "voice-zisu"):
                self._save(p, True)
                await self._rebuild_voice(p)
        except StopRequested:
            m["status"] = "stale"
            raise
        except Exception as e:
            m.update(status="err", error=_err_text(e)[:500], cache_key="")
            raise
        finally:
            self._save(p, True)

    async def _exec_module(self, p, m, part=""):
        mid = m["id"]
        if mid == "script":
            return self._exec_script(p, m)
        if mid == "image":
            if str(part or "").startswith("batch"):
                return await self._exec_image_batch(p, m, part)
            return await self._exec_image(p, m)
        if mid in ("voice-white", "voice-zisu"):
            return await self._exec_voice(p, m)
        if mid == "bgm":
            return await self._exec_bgm(p, m)
        if mid == "compose":
            return await self._exec_compose(p, m, part)
        if mid == "publish":
            return []
        raise StudioError("不认识的模块：" + mid)

    # ---------- 模块 1：剧本与清单 ----------
    def _exec_script(self, p, m):
        prm = m["params"]
        doc = prm.get("script_doc") if isinstance(prm.get("script_doc"), dict) else {}
        if not doc.get("shots"):
            doc = graph.doc_from_modules(p)
        self._phase("正在解析并写入 5 份 Markdown 清单…", 20, "running")
        data = graph.write_lists(p, doc)
        prm["script_doc"] = doc
        outs = []
        for name in graph.LISTS[:4]:
            o = _out(p, f"Lists/{name}", "text")
            if o:
                outs.append(o)
        if not outs:
            raise StudioError("清单没写出来：检查项目 Lists 文件夹")
        self._phase("5 份 Markdown 清单已生成", 95, "running")
        return outs

    # ---------- 模块 2：生图测试台 ----------
    async def _exec_image(self, p, m):
        prm = m["params"]
        items = prm.get("items") or []
        sel = int(prm.get("selected") or 0)
        if items and 0 <= sel < len(items):
            item = items[sel]
            prm["prompt"] = item.get("prompt") or prm.get("prompt")
            prm["ratio"] = item.get("ratio") or prm.get("ratio")
            prm["transparent"] = bool(item.get("transparent")) if "transparent" in item else prm.get("transparent")
        prompt = str(prm.get("prompt") or "").strip()
        if not prompt:
            raise StudioError("生图测试台缺提示词")
        ratio = prm.get("ratio") if prm.get("ratio") in imagegen.RATIOS else (p.get("ratio") or "9:16")
        shot = {"id": "image-test", "text": prompt, "image_prompt": prompt, "role": "旁白", "speaker": "", "tone": "",
                "seconds_hint": 5, "image_st": "idle", "tts_st": "idle", "image": "", "tts": "", "duration": 0.0,
                "start": 0.0, "end": 0.0, "image_err": "", "tts_err": "", "image_ver": 0, "tts_ver": 0,
                "img_variants": [], "img_selected": sel, "img_fps": [], "image_cache_hit": False, "tts_cache_hit": False,
                "img_output": prm.get("output") or "normal", "img_format": prm.get("format") or "png", "tts_engine": "auto",
                "render": "static", "render_clip": "", "render_image": "", "ppt_points": [], "img_refs": prm.get("refs") or [],
                "_dest_stem": "image-test", "img_model": prm.get("model") or "", "img_ratio": ratio,
                "img_resolution": prm.get("resolution") or "2k", "img_quality": prm.get("quality") or "high",
                "img_complexity": prm.get("complexity") or "medium", "img_transparent": bool(prm.get("transparent")),
                "img_n": int(prm.get("n") or 1), "img_custom_w": int(prm.get("custom_w") or 0),
                "img_custom_h": int(prm.get("custom_h") or 0), "gif_frames": int(prm.get("gif_frames") or 8),
                "gif_delay_ms": int(prm.get("gif_delay_ms") or 150), "_force_nonce": str(prm.get("_force_nonce") or "")}
        pp = self._pseudo(p, [shot])
        self._phase("正在上传参考图 / 请求 API易 (GPT Image 2.6)…", 15, "running")
        await self._gen_images(pp, ids=["image-test"])
        self._phase("正在下载并校验图片…", 90, "running")
        j = self._job()
        if j:
            j["step"] = m["id"]
        s = pp["shots"][0]
        outs = [o for o in (_out(p, rel, "image", {"index": i}) for i, rel in enumerate(s.get("img_variants") or [])) if o]
        if not outs:
            raise StudioError("生图没返回可用的图片")
        prm["selected"] = int(s.get("img_selected") or 0)
        m["cache_hit"] = bool(s.get("image_cache_hit"))
        return outs

    async def _exec_image_batch(self, p, m, part=""):
        """视频工坊的生图 Agent：按 compose 分镜批量出图，part=batch[:s01,s02] 可只重绘指定镜。"""
        ids = []
        if ":" in str(part or ""):
            ids = [x.strip() for x in str(part).split(":", 1)[1].split(",") if x.strip()]
        self._phase("生图 Agent：准备批量出图…" if not ids else f"生图 Agent：只重绘 {', '.join(ids)}…", 2, "running")
        n = await self._gen_project_images(p, ids or None)
        if not n:
            raise StudioError("批量生图一张都没出来：看每个分镜的报错")
        items = (m.get("params") or {}).get("items") or []
        outs, seen = [], set()
        for it in items:
            rel = str(it.get("rel") or "")
            if not rel or rel in seen:
                continue
            seen.add(rel)
            o = _out(p, rel, "image", {"index": len(outs), "shot_id": it.get("shot_id") or "", "line": it.get("line_index") or ""})
            if o:
                outs.append(o)
        if not outs:
            raise StudioError("批量生图没有可用的图片")
        return outs

    # ---------- 模块 3/4：两个独立配音 ----------
    async def _exec_voice(self, p, m):
        prm = m["params"]
        lines = [x for x in prm.get("lines") or [] if isinstance(x, dict) and str(x.get("text") or "").strip()]
        if not lines:
            raise StudioError("这个角色模块还没有台词：在模块里写一句，或者编辑对应的配音清单")
        role = str(prm.get("role") or "旁白")
        shots = []
        used = set()
        for i, ln in enumerate(lines, 1):
            try:
                idx = int(ln.get("line_index") or 0)
            except (TypeError, ValueError):
                idx = 0
            if idx <= 0 or idx in used:
                idx = max([x.get("line_index") or 0 for x in prm.get("lines") or []] + [0]) + 1
            used.add(idx)
            ln["line_index"] = idx
            lid = str(ln.get("id") or f"l{i}")[:20]
            rel = f"tts/shot{idx:02d}.wav"
            shots.append({"id": f"{m['id']}:{lid}", "text": str(ln.get("text") or "")[:500], "role": role,
                          "speaker": str(ln.get("speaker") or prm.get("speaker") or ""),
                          "tone": str(ln.get("tone") or prm.get("tone") or ""),
                          "tts_engine": str(ln.get("engine") or prm.get("engine") or "auto"), "tts_st": "idle",
                          "tts": "", "image": "", "duration": 0.0, "start": 0.0, "end": 0.0, "tts_err": "",
                          "tts_cache_hit": False, "_tts_rel": rel, "line_index": idx})
        pp = self._pseudo(p, shots)
        self._phase("正在读取台词，准备逐句合成…", 3, "running")
        await self._gen_tts(pp, out_prefix=f"{m['id']}_")
        self._phase("正在整理逐句音频…", 90, "running")
        j = self._job()
        if j:
            j["step"] = m["id"]
        outs = []
        for s in pp["shots"]:
            o = _out(p, s.get("tts"), "audio", {"line": str(s.get("line_index") or ""), "duration": s.get("duration"),
                                                "text": s.get("text")})
            if o:
                outs.append(o)
                for ln in prm["lines"]:
                    if int(ln.get("line_index") or 0) == int(s.get("line_index") or 0):
                        ln["output"] = s.get("tts") or ""
        m["cache_hit"] = all(s.get("tts_cache_hit") for s in pp["shots"])
        m["outputs"] = outs
        try:
            p["cost"]["tts_cny"] = round(float((p.get("cost") or {}).get("tts_cny") or 0) + float(pp.get("cost", {}).get("tts_cny") or 0), 4)
        except Exception:
            pass
        await self._rebuild_voice(p)
        return outs

    async def _rebuild_voice(self, p):
        """白页/紫苏所有已有逐句音频，按全局 line_index 拼成 voice.wav + srt + timeline。"""
        async with _loop_gate("voice-rebuild", asyncio.Lock):
            with self._save_lock:
                latest = video_maker.load_project(p["id"])
                mid = _CUR_MID.get()
                if mid in ("voice-white", "voice-zisu"):
                    try:
                        idx = next(i for i, x in enumerate(latest.get("modules") or []) if x.get("id") == mid)
                        nm = graph.module_of(p, mid)
                        for k in ("x", "y", "w", "h"):
                            if latest["modules"][idx].get(k) is not None:
                                nm[k] = latest["modules"][idx][k]
                        latest["modules"][idx] = nm
                    except (StopIteration, graph.GraphError):
                        pass
                rows = []
                for vmid in ("voice-white", "voice-zisu"):
                    m = graph.module_of(latest, vmid)
                    by_idx = {int(x.get("line_index") or 0): x for x in (m.get("params") or {}).get("lines") or []}
                    for o in m.get("outputs") or []:
                        if o.get("kind") != "audio":
                            continue
                        idx = int(o.get("line") or 0)
                        if not idx or not _output_ok(latest, o):
                            continue
                        ln = by_idx.get(idx) or {}
                        rows.append({"idx": idx, "tts": o["rel"], "text": str(ln.get("text") or o.get("text") or ""),
                                     "role": (m.get("params") or {}).get("role") or ("白页" if vmid == "voice-white" else "紫苏"),
                                     "speaker": ln.get("speaker") or (m.get("params") or {}).get("speaker") or "",
                                     "tone": ln.get("tone") or (m.get("params") or {}).get("tone") or ""})
                rows.sort(key=lambda x: x["idx"])
                if not rows:
                    latest.setdefault("files", {}).pop("voice", None)
                    p.setdefault("files", {}).pop("voice", None)
                    video_maker.save_project(latest)
                    return {}
                shots = []
                for r in rows:
                    dur = _wav_duration(Path(p["dir"]) / r["tts"])
                    shots.append({"id": f"s{r['idx']}", "text": r["text"], "role": r["role"], "speaker": r["speaker"],
                                  "tone": r["tone"], "tts": r["tts"], "duration": dur, "start": 0.0, "end": 0.0})
                pp = self._pseudo(latest, shots)
                await self._build_voice(pp, shots=shots, out_prefix="")
                for k in ("voice", "srt", "timeline"):
                    if (pp.get("files") or {}).get(k):
                        latest.setdefault("files", {})[k] = pp["files"][k]
                        p.setdefault("files", {})[k] = pp["files"][k]
                latest["total_seconds"] = pp.get("total_seconds") or 0
                p["total_seconds"] = latest["total_seconds"]
                video_maker.save_project(latest)
                return pp.get("files") or {}

    # ---------- 模块 5：配乐 ----------
    async def _exec_bgm(self, p, m):
        prm = m["params"]
        pp = self._pseudo(p, [])
        pp["bgm_prompt"] = str(prm.get("prompt") or "").strip() or "upbeat electronic, no vocals, suitable under narration"
        st = pp.setdefault("settings", {})
        st["bgm_seconds"] = int(prm.get("seconds") or 0)
        st["bgm_steps"] = int(prm.get("steps") or 8)
        st["bgm_seed"] = int(prm.get("seed") or 20261118)
        try:
            pp["total_seconds"] = float(p.get("total_seconds") or p.get("target_seconds") or 75)
        except (TypeError, ValueError):
            pp["total_seconds"] = 75
        await self._gen_bgm(pp, dest_rel="bgm/bgm.wav", project_key="bgm")
        j = self._job()
        if j:
            j["step"] = m["id"]
        m["cache_hit"] = bool(pp.get("bgm_cache_hit"))
        o = _out(p, "bgm/bgm.wav", "audio", {"duration": pp.get("bgm_seconds")})
        if not o:
            raise StudioError("配乐没写出文件")
        return [o]

    # ---------- 模块 6：视频制作总成 ----------
    def _compose_shots(self, p):
        m = graph.module_of(p, "compose")
        prm = m.get("params") or {}
        text = graph.read_list(p, graph.LISTS[3])
        shots = graph.parse_render_list(text) if text.strip() else []
        if not shots:
            shots = list(prm.get("shots") or [])
        old = {str(x.get("id")): x for x in (prm.get("shots") or []) if isinstance(x, dict)}
        keep = ("render_clip", "render_image", "image", "image_prompt", "_dest_stem", "img_model", "img_ratio",
                "img_resolution", "img_quality", "img_complexity", "img_transparent", "img_output", "img_format",
                "img_n", "img_custom_w", "img_custom_h", "gif_frames", "gif_delay_ms", "img_refs")
        for x in shots:
            q = old.get(str(x.get("id"))) or {}
            for k in keep:
                if q.get(k) not in (None, "", []):
                    x[k] = q[k]
            x.setdefault("image_prompt", x.get("visual") or x.get("text") or "")
            x.setdefault("image", "")
        if not shots:
            shots = [{"id": "s1", "line_index": 1, "render": "web", "text": "视频制作总成测试字幕",
                      "visual": "深色科技感排版", "seconds": 6, "transition": "淡入", "render_clip": "", "render_image": ""}]
        lines = {}
        for mid in ("voice-white", "voice-zisu"):
            vm = graph.module_of(p, mid)
            for o in vm.get("outputs") or []:
                if o.get("kind") == "audio":
                    ln = next((x for x in (vm.get("params") or {}).get("lines") or [] if int(x.get("line_index") or 0) == int(o.get("line") or 0)), {})
                    lines[int(o.get("line") or 0)] = {"role": (vm.get("params") or {}).get("role") or "白页",
                                                      "speaker": ln.get("speaker") or (vm.get("params") or {}).get("speaker") or "",
                                                      "tone": ln.get("tone") or (vm.get("params") or {}).get("tone") or "",
                                                      "text": ln.get("text") or o.get("text") or ""}
        voice_rows = []
        for i, s in enumerate(shots, 1):
            idx = int(s.get("line_index") or i)
            ln = lines.get(idx) or {}
            s["line_index"] = idx
            s["text"] = str(ln.get("text") or s.get("text") or "")
            s["role"] = ln.get("role") or ("白页" if i % 2 else "紫苏")
            s["speaker"] = ln.get("speaker") or ""
            s["tone"] = ln.get("tone") or ""
            dur = float(s.get("seconds") or 6)
            o = next((x for x in (graph.module_of(p, "voice-white").get("outputs") or []) + (graph.module_of(p, "voice-zisu").get("outputs") or [])
                      if x.get("kind") == "audio" and int(x.get("line") or 0) == idx), None)
            if o:
                dur = _wav_duration(Path(p["dir"]) / o["rel"]) or dur
                voice_rows.append({"id": f"s{idx}", "text": s["text"], "role": s["role"], "speaker": s["speaker"],
                                   "tone": s["tone"], "tts": o["rel"], "duration": dur, "start": 0.0, "end": 0.0})
            s["seconds"] = max(1.0, dur)
        return shots, voice_rows

    async def _exec_compose(self, p, m, part=""):
        prm = m.get("params") or {}
        self._phase("正在读取视频渲染清单与配音时间轴…", 3, "running")
        shots, voice_rows = self._compose_shots(p)
        prm["shots"] = shots
        m["params"]["shots"] = shots
        if not voice_rows:
            await self._make_silence(p, shots)
        else:
            pp = self._pseudo(p, voice_rows)
            await self._build_voice(pp, shots=voice_rows, out_prefix="")
            for k in ("voice", "srt", "timeline"):
                if (pp.get("files") or {}).get(k):
                    p.setdefault("files", {})[k] = pp["files"][k]
            p["total_seconds"] = pp.get("total_seconds") or 0
        web = [s for s in shots if s.get("render") == "web"]
        ppt = [s for s in shots if s.get("render") == "ppt" or (s.get("render") == "static" and not s.get("image"))]
        if part in ("", "web") and (web or part == "web"):
            self._phase("正在渲染网页动效…", 20, "running")
            await self._render_web(p, m, web)
        if part in ("", "ppt") and (ppt or part == "ppt"):
            self._phase("正在生成 PPT 卡片…", 55, "running")
            await self._render_ppt(p, m, ppt)
        if self._stopped():
            raise StopRequested()
        m["params"]["shots"] = shots
        video_maker.save_project(p)
        return await self._compose_final(p, m, shots)

    async def _make_silence(self, p, shots):
        total = max(1.0, sum(float(s.get("seconds") or 5) for s in shots))
        sr = 24000
        wav = Path(p["dir"]) / "tts" / "voice.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        tts.write_wav(wav, sr, bytes(int(sr * total) * 2))
        srt = Path(p["dir"]) / "tts" / "subtitles.srt"
        srt.write_text("", "utf-8")
        meta = {"created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "sample_rate": sr, "total_seconds": round(total, 3),
                "shots": [{"id": s["id"], "role": s.get("role"), "speaker": s.get("speaker"), "tone": s.get("tone"),
                           "text": s.get("text"), "start": 0, "end": s.get("seconds"), "duration": s.get("seconds")} for s in shots]}
        (Path(p["dir"]) / "tts" / "timeline.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        p.setdefault("files", {}).update({"voice": "tts/voice.wav", "srt": "tts/subtitles.srt", "timeline": "tts/timeline.json"})
        p["total_seconds"] = round(total, 3)

    def _set_web(self, **kw):
        j = self._job()
        if j:
            w = j.setdefault("web", {})
            w.update(kw)

    def _set_ppt(self, **kw):
        j = self._job()
        if j:
            w = j.setdefault("ppt", {})
            w.update(kw)

    def _set_ff(self, **kw):
        j = self._job()
        if j:
            w = j.setdefault("ffmpeg", {})
            w.update(kw)

    async def _render_web(self, p, m, shots):
        prm = m.get("params") or {}
        W, H = (1080, 1920) if (prm.get("ratio") or p.get("ratio") or "9:16") != "16:9" else (1920, 1080)
        fps = int(prm.get("fps") or 24)
        self._set_web(st="run", msg="准备网页动效", pct=0, current=0, total=len(shots), fps=fps, preview_rel="",
                      cc="开" if (ccode.usable() and prm.get("cc_drive", True)) else "没开")
        d = Path(p["dir"])
        try:
            for i, s in enumerate(shots, 1):
                if self._stopped():
                    raise StopRequested()
                self._set_web(current=i, msg=f"网页渲染 第 {i}/{len(shots)} 镜 · {s.get('id')}", pct=round((i - 1) / max(1, len(shots)) * 100, 1))
                self._phase(f"网页渲染 第 {i}/{len(shots)} 镜 · {s.get('id')}…", 20 + (i - 1) / max(1, len(shots)) * 32, "running")
                rel = f"render/web_{s['id']}.mp4"
                dest = d / rel
                html_rel = f"render/cc_{s['id']}.html"
                html = d / html_rel
                src = ""
                duration = max(1.0, float(s.get("seconds") or 5))
                use_cc = bool(ccode.usable() and prm.get("cc_drive", True))
                if use_cc:
                    prompt = self._cc_prompt(p, s, W, H, fps, duration)
                    fp = cache.fingerprint("cc_html", {"shot": s.get("id"), "text": s.get("text"), "visual": s.get("visual"),
                                                       "w": W, "h": H, "fps": fps, "dur": duration, "v": graph.MODEL_VERSION})
                    ent = cache.project_get(p["dir"], f"cc:{s['id']}")
                    if ent and ent.get("fp") == fp and (d / (ent.get("path") or "")).is_file():
                        html = d / ent["path"]
                        html_rel = ent["path"]
                    else:
                        self._set_web(msg=f"Claude Code 正在写第 {i} 镜的网页动效……")
                        steps = []
                        eid = -int(time.time() * 1000) - i
                        j = self._job()
                        if j:
                            j["cc_eid"] = eid
                        try:
                            r = await ccode.run(eid, prompt, steps, lambda x: self._set_web(msg=str(x)[:120]), extra=f"产物：{html_rel}")
                            if r.get("stopped"):
                                raise StopRequested()
                            if not html.is_file():
                                raise RuntimeError("Claude Code 没写出 HTML")
                            cache.project_set(p["dir"], f"cc:{s['id']}", fp, html_rel, False)
                        except StopRequested:
                            raise
                        except Exception as e:
                            self._set_web(cc="失败，退回内置模板：" + str(e)[:60])
                            use_cc = False
                if self._stopped():
                    raise StopRequested()
                if use_cc and html.is_file():
                    src = cache.sha_file(html)
                    key = cache.fingerprint("track_web_cc", {"html": src, "w": W, "h": H, "fps": fps, "dur": duration})
                    if not cache.hit_to(key, dest, "tracks"):
                        self._set_web(msg=f"录制网页动效 {i}/{len(shots)}……")
                        await asyncio.to_thread(render_web.render_html_file, html, dest, W, H, fps, duration, self._stopped,
                                                str(d / "render" / f"preview_web_{s['id']}.jpg"),
                                                lambda fr, tot: self._set_web(frame=fr, total_frames=tot,
                                                                               pct=round(fr / max(1, tot) * 100, 1)))
                        cache.put(key, dest, "tracks", {"type": "web_cc", "w": W, "h": H, "fps": fps})
                else:
                    key = cache.fingerprint("track_web", {"text": s.get("text"), "visual": s.get("visual"), "duration": duration,
                                                          "w": W, "h": H, "fps": fps, "cfg": {k: prm.get(k) for k in
                                                          ("web_bg", "web_sub_pos", "web_sub_size", "web_sub_color", "web_gif_scale", "web_motion")}})
                    if not cache.hit_to(key, dest, "tracks"):
                        shot = {"id": s["id"], "text": s.get("text") or "", "role": s.get("role") or "", "tone": s.get("tone") or "",
                                "duration": duration, "gif": "", "render_image": "", "image": ""}
                        self._set_web(msg=f"内置模板录制 {i}/{len(shots)}……")
                        await asyncio.to_thread(render_web.render_shot, p["dir"], shot, prm, dest, W, H, fps, self._stopped,
                                                str(d / "render" / f"preview_web_{s['id']}.jpg"),
                                                lambda fr, tot: self._set_web(frame=fr, total_frames=tot,
                                                                               pct=round(fr / max(1, tot) * 100, 1)))
                        cache.put(key, dest, "tracks", {"type": "web", "w": W, "h": H, "fps": fps})
                s["render_clip"] = rel
                s["render_image"] = ""
                for x in (m.get("params") or {}).get("shots") or []:
                    if str(x.get("id")) == str(s.get("id")):
                        x["render_clip"] = rel
                self._set_web(progress_rel=f"render/preview_web_{s['id']}.jpg", preview_rel=f"render/preview_web_{s['id']}.jpg",
                              pct=round(i / max(1, len(shots)) * 100, 1))
                self._save(p, True)
            self._set_web(st="ok", msg=f"{len(shots)} 镜网页动效好了", pct=100)
            self._phase(f"{len(shots)} 镜网页动效好了", 52, "running")
        except Exception as e:
            self._set_web(st="err", msg=str(e)[:200], pct=100)
            raise

    def _cc_prompt(self, p, s, W, H, fps, dur):
        lines = graph.read_list(p, graph.LISTS[3])
        return f"""你是短视频的网页动效导演。请为下面这一镜写一个单文件 HTML，后面会用无头浏览器逐帧录制。
参考清单：{lines[:2000]}
这一镜：{s.get('id')}；字幕：{s.get('text') or ''}；画面排版要点：{s.get('visual') or ''}；时长 {dur:.2f} 秒。
画布 {W}×{H}，帧率 {fps}，循环动效。
配色按 60-30-10：主色 60%、辅色 30%、点缀色 10%，深色科技感/高对比，和「知识科普 × 科技数码 × 搞笑」账号风格一致。
动效：代码动画、数据跳动、趣味弹幕/贴纸都可以；字幕要清晰，底部避开抖音文案区。
禁止联网加载任何外部资源（字体/图片/脚本/CDN 都不行），只能用 CSS/SVG/Canvas 和本地 data URI。
画面里不要放 logo、商标、二维码、水印。
请写文件：{Path(p['dir']) / 'render' / ('cc_' + s['id'] + '.html')}
写完后自己检查浏览器能打开。"""

    async def _render_ppt(self, p, m, shots):
        prm = m.get("params") or {}
        self._set_ppt(st="run", msg="准备 PPT 卡片", pct=0, current=0, total=len(shots), slides=[])
        self._phase("PPT 卡片：正在生成/渲染…", 56, "running")
        if not shots:
            self._set_ppt(st="ok", msg="没有 PPT/静态镜头", pct=100)
            return
        pp = self._pseudo(p, [])
        pp["ratio"] = prm.get("ratio") or p.get("ratio") or "9:16"
        pp["settings"] = dict(pp.get("settings") or {})
        pp["settings"]["ppt_file"] = str(prm.get("ppt_file") or "")
        fake = []
        for s in shots:
            fake.append({"id": s["id"], "text": s.get("text") or "", "role": s.get("role") or "旁白", "tone": s.get("tone") or "",
                         "duration": float(s.get("seconds") or 5), "render": "ppt", "n": 1,
                         "ppt_points": [x.strip() for x in re.split(r"[、,，;；\n]+", s.get("visual") or "") if x.strip()][:5],
                         "image": "", "start": 0.0, "end": 0.0})
        pp["shots"] = fake
        done = {"n": 0}

        async def watch():
            while done["n"] == 0:
                files = sorted((Path(p["dir"]) / "render").glob("ppt_*.png"))
                if files:
                    slides = [f"render/{x.name}" for x in files]
                    self._set_ppt(slides=slides, current=len(slides))
                await asyncio.sleep(.35)
        wt = asyncio.get_running_loop().create_task(watch())
        try:
            await asyncio.to_thread(render_ppt.render_all, p["dir"], pp, lambda x: self._set_ppt(msg=str(x)[:120]), self._stopped)
        finally:
            done["n"] = 1
            try:
                await wt
            except Exception:
                pass
        for s, fs in zip(shots, fake):
            s["render_image"] = fs.get("render_image") or ""
            s["render_clip"] = ""
            for x in (m.get("params") or {}).get("shots") or []:
                if str(x.get("id")) == str(s.get("id")):
                    x["render_image"] = s["render_image"]
        files = sorted((Path(p["dir"]) / "render").glob("ppt_*.png"))
        self._set_ppt(st="ok", msg=f"{len(shots)} 页 PPT 卡片好了", pct=100, current=len(files),
                      slides=[f"render/{x.name}" for x in files])
        self._phase(f"{len(shots)} 页 PPT 卡片好了", 78, "running")

    async def _compose_final(self, p, m, shots):
        prm = m.get("params") or {}
        d = Path(p["dir"])
        proj = copy.deepcopy(p)
        proj["_transient"] = True
        proj["shots"] = []
        tl_by_idx = {}
        try:
            tl_rel = (p.get("files") or {}).get("timeline") or "tts/timeline.json"
            tl = json.loads((d / tl_rel).read_text("utf-8"))
            for i, x in enumerate(tl.get("shots") or []):
                mnum = re.search(r"\d+", str(x.get("id") or ""))
                tl_by_idx[int(mnum.group()) if mnum else i + 1] = x
        except Exception:
            tl_by_idx = {}
        for i, s in enumerate(shots):
            dur = max(1.0, float(s.get("seconds") or 5))
            li = int(s.get("line_index") or 0)
            if not li:
                mnum = re.search(r"\d+", str(s.get("id") or ""))
                li = int(mnum.group()) if mnum else i + 1
            seg = tl_by_idx.get(li)
            if seg and seg.get("end") is not None:
                try:
                    start, end = float(seg.get("start") or 0), float(seg.get("end") or 0)
                    if end > start:
                        dur = max(0.1, end - start)
                    else:
                        start = 0.0
                except (TypeError, ValueError):
                    start, end = 0.0, dur
            else:
                start, end = 0.0, dur
            proj["shots"].append({"id": s["id"], "text": s.get("text") or "", "role": s.get("role") or "", "tone": s.get("tone") or "",
                                  "duration": dur, "start": start, "end": end, "image": s.get("image") or "",
                                  "render": s.get("render") or "static",
                                  "render_clip": s.get("render_clip") or "", "render_image": s.get("render_image") or "",
                                  "n": 1, "seconds_hint": dur})
        proj["files"] = {k: (p.get("files") or {}).get(k) for k in ("voice", "srt", "timeline", "bgm") if (p.get("files") or {}).get(k)}
        proj["ratio"] = prm.get("ratio") or p.get("ratio") or "9:16"
        proj["settings"] = dict(proj.get("settings") or {})
        proj["settings"].update({"subtitle": bool(prm.get("subtitle", True)), "kenburns": bool(prm.get("kenburns", True)),
                                 "bgm_volume": float(prm.get("bgm_volume", .18)), "duck_depth": float(prm.get("duck_depth", .16)),
                                 "fade": float(prm.get("fade", 2.0)), "use_bgm": bool((p.get("files") or {}).get("bgm"))})
        if not proj["files"].get("voice"):
            await self._make_silence(p, shots)
            proj["files"].update({k: (p.get("files") or {}).get(k) for k in ("voice", "srt", "timeline")})
        params = {"ratio": proj["ratio"], "subtitle": proj["settings"]["subtitle"], "bgm_volume": proj["settings"]["bgm_volume"],
                  "duck_depth": proj["settings"]["duck_depth"], "fade": proj["settings"]["fade"],
                  "fps": 30, "bgm": bool(proj["files"].get("bgm"))}
        self._set_ff(st="run", msg="开始 FFmpeg 混流压制", pct=0, fps=30, params=params, log="开始合成")
        logs = []

        def prog(x):
            pct = float(x.get("pct") or 0)
            msg = str(x.get("msg") or "")
            if msg:
                logs.append(msg)
                del logs[:-12]
            self._set_ff(pct=pct, msg=msg, log="\n".join(logs[-8:]))
        try:
            r = await asyncio.to_thread(video_maker.compose_video, p["dir"], bool(proj["settings"].get("subtitle", True)),
                                        float(proj["settings"].get("bgm_volume", .18)), bool(proj["settings"].get("kenburns", True)),
                                        self._stopped, prog, duck_depth=float(proj["settings"].get("duck_depth", .16)),
                                        fade=float(proj["settings"].get("fade", 2.0)), project=proj)
        except Exception as e:
            self._set_ff(st="err", msg=str(e)[:240], log="\n".join(logs[-8:]) + "\n" + str(e)[:300])
            raise
        if r.get("stopped"):
            raise StopRequested()
        p.setdefault("files", {})["video"] = r["rel"]
        if r.get("cover_rel"):
            p["files"]["cover"] = r["cover_rel"]
        p["duration"] = r.get("duration")
        p["resolution"] = f"{r.get('w')}×{r.get('h')}"
        self._set_ff(st="ok", msg=f"成片好了：{r.get('duration', 0):.1f} 秒 · {p['resolution']}", pct=100, log="合成完成")
        outs = [_out(p, r["rel"], "video", {"duration": r.get("duration")})]
        if r.get("cover_rel"):
            outs.append(_out(p, r["cover_rel"], "image", {"cover": True}))
        return [o for o in outs if o]


    def _image_stale(self, p, s):
        if not _shot_ok(p, s, "image") or s.get("image_st") in ("idle", "stale", "err", "missing"):
            return True
        try:
            fps, _, _, _ = _image_fps(p, s)
        except Exception:
            return True
        return list(s.get("img_fps") or []) != list(fps)

    async def _gen_images(self, p, ids=None):
        self._step_start(p, "images", "准备生图（API 通道）")
        shots = p["shots"]
        if ids:
            targets = [s for s in shots if s["id"] in ids]
        else:
            targets = [s for s in shots if self._image_stale(p, s)]
        if not targets:
            _mark(p, "images", "ok", "都已经出好了", 100)
            return
        self._span = (5, 30)
        fails, done = [], 0
        lock = asyncio.Lock()

        async def one(s):
            nonlocal done
            try:
                await self._image_one(p, s)
            except imagegen.ImgError as e:
                s.update(image_st="err", image_err=str(e)[:300])
                fails.append(f"第 {shots.index(s) + 1} 镜：{str(e)[:100]}")
                if getattr(e, "fatal", False):
                    raise StudioError(f"生图停了：{str(e)[:300]}") from None
            except Exception as e:
                s.update(image_st="err", image_err=f"{type(e).__name__} {str(e)[:200]}")
                fails.append(f"第 {shots.index(s) + 1} 镜：{type(e).__name__}")
            finally:
                async with lock:
                    done += 1
                    self._progress(done / max(1, len(targets)) * 100,
                                   f"正在下载并校验图片 {done}/{len(targets)}（第 {shots.index(s) + 1} 镜）…")
                    self._phase(f"正在下载并校验图片 {done}/{len(targets)}（第 {shots.index(s) + 1} 镜）…",
                                10 + done / max(1, len(targets)) * 80, "running")
                self._save(p)

        await asyncio.gather(*(one(s) for s in targets))
        good = sum(1 for s in shots if _shot_ok(p, s, "image"))
        if not good:
            _mark(p, "images", "err", "一张都没出来：" + "；".join(fails[:3]), 0)
            raise StudioError("生图一张都没出来：" + "；".join(fails[:3]))
        msg = f"出了 {good}/{len(shots)} 镜" + (f"，{len(fails)} 镜没出来" if fails else "")
        _mark(p, "images", "warn" if fails else "ok", msg, 100)
        j = self._job()
        if j:
            j.update(stage=2, pct=self._span[0] + self._span[1])
        self._save(p, True)

    async def _image_one(self, p, s):
        cfg = _img_cfg(p, s)
        fps, prompt, cd, refs = _image_fps(p, s, cfg)
        if cfg["output"] == "gif" and not cd.get("gif"):
            raise StudioError(f"{cd.get('name') or cfg['model']} 不支持 GIF：换 GPT Image 2.6 Sunburst 或普通/ SVG 模式")
        if cfg["output"] == "svg" and not cd.get("svg"):
            raise StudioError(f"{cd.get('name') or cfg['model']} 不支持 SVG：换 GPT Image 2.6 Sunburst 或普通/ GIF 模式")
        sid = s["id"]
        variants, all_hit, hit_any = [], True, False
        for i, fp in enumerate(fps):
            rel = ""
            ent = cache.project_get(p["dir"], f"img:{sid}:{i}")
            if ent and ent.get("fp") == fp:
                q = Path(p["dir"]) / str(ent.get("path") or "")
                if q.is_file():
                    rel = str(ent["path"])
                    hit_any = True
            if not rel:
                cp = cache.lookup(fp, "image")
                if cp:
                    ext = cp.suffix.lower().lstrip(".") or "png"
                    dest = _shot_image_dest(p, s, i, ext)
                    cache.hit_to(fp, dest, "image")
                    rel = dest.relative_to(Path(p["dir"])).as_posix()
                    cache.project_set(p["dir"], f"img:{sid}:{i}", fp, rel, True)
                    hit_any = True
            if not rel:
                all_hit = False
                break
            variants.append(rel)
        if all_hit and len(variants) == len(fps):
            self._apply_image_variants(p, s, variants, fps, cd, True)
            return
        # 有任意一张没命中：整镜按当前参数重新请求（n 张一次）；已有缓存变体仍会被重新缓存
        s["image_st"] = "run"
        self._save(p, True)
        key = settings.get_secret("imgKey")
        if not key:
            raise imagegen.ImgError("还没填 API易 的 Key：到 设置 › 云端 填好，再生成画面")
        base = (settings.S.get("imgBase") or "https://api.apiyi.com/v1").rstrip("/")
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=imagegen.TIMEOUT, write=120.0, pool=None)) as c:
            async with _api_gate():
                imgs, usage, _sent = await imagegen.call_images(
                    c, base, key, cd, prompt, cfg["ratio"], cfg["resolution"], cfg["quality"], bool(cfg["transparent"]),
                    [x.read_bytes() for x in refs], n=cfg["n"], custom_w=cfg["custom_w"] or None,
                    custom_h=cfg["custom_h"] or None, complexity=cfg["complexity"] or None,
                    gif_frames=cfg["gif_frames"] if cfg["gif"] else None, gif_delay_ms=cfg["gif_delay_ms"] if cfg["gif"] else None,
                    output_type=cfg["output"], output_format=cfg["format"])
        if not imgs:
            raise imagegen.ImgError("没返回图片")
        variants, fps2 = [], []
        for i, img in enumerate(imgs[:cfg["n"]]):
            pi = imagegen.png_info(img)
            ext = pi["fmt"] if pi["fmt"] in ("png", "jpg", "webp", "gif") else "png"
            dest = _shot_image_dest(p, s, i, ext)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            tmp.write_bytes(img)
            tmp.replace(dest)
            rel = dest.relative_to(Path(p["dir"])).as_posix()
            fp = fps[i]
            cache.put(fp, dest, "image", {"model": cd["id"], "w": pi.get("w"), "h": pi.get("h"), "fmt": ext})
            cache.project_set(p["dir"], f"img:{sid}:{i}", fp, rel, False)
            variants.append(rel)
            fps2.append(fp)
        if not variants:
            raise imagegen.ImgError("没返回可用的图片")
        self._apply_image_variants(p, s, variants, fps2, cd, all_hit)
        # 费用按返回的 usage / 模型价格粗算
        try:
            if usage and cd["price"] is None:
                usd = float(usage.get("output_tokens") or 0) * imagegen.USD_OUT + float(usage.get("input_tokens") or 0) * imagegen.USD_IN
            else:
                usd = (cd["price"] if cd["price"] is not None else imagegen.est_usd(cd, cfg["ratio"], cfg["resolution"], cfg["quality"])) or 0.0
            p["cost"]["images_usd"] = round(float(p["cost"].get("images_usd") or 0) + float(usd), 4)
        except Exception:
            pass
        telemetry.log("app", "studio_image", "视频工坊", "ok", 0,
                      {"shot": sid, "model": cd["id"], "n": len(variants), "cache": all_hit,
                       "gif": bool(cfg["gif"])}, f"视频工坊生图：{sid}")

    def _apply_image_variants(self, p, s, variants, fps, cd, cache_hit):
        sel = int(s.get("img_selected") or 0)
        if sel < 0 or sel >= len(variants):
            sel = 0
        q = Path(p["dir"]) / variants[sel]
        pi = {}
        try:
            pi = imagegen.png_info(q.read_bytes()[:65536])
        except Exception:
            pass
        s.update(image=variants[sel], img_variants=variants, img_selected=sel, img_fps=fps, image_model=cd["id"],
                 image_st="ok", image_err="", image_cache_hit=bool(cache_hit),
                 image_ver=int(time.time() * 1000), image_w=pi.get("w"), image_h=pi.get("h"))

    # ---------- 配音 ----------
    def _tts_stale(self, p, s):
        if not _shot_ok(p, s, "tts") or s.get("tts_st") in ("idle", "stale", "err", "missing"):
            return True
        try:
            cfg = _shot_voice(p, s)
            return s.get("tts_fp") != _tts_fp(p, s, cfg)
        except Exception:
            return True

    async def _gen_tts(self, p, ids=None, shots=None, out_prefix=""):
        self._step_start(p, "tts", "准备逐句配音")
        self._phase("正在准备逐句配音…", 5, "running")
        shots = shots if shots is not None else p["shots"]
        if ids:
            targets = [s for s in shots if s["id"] in ids]
        else:
            targets = [s for s in shots if self._tts_stale(p, s)]
        if not targets:
            await self._build_voice(p, shots=shots, out_prefix=out_prefix)
            _mark(p, "tts", "ok", "配音都在", 100)
            return
        self._span = (35, 30)
        miss, hits = [], 0
        for s in targets:
            cfg = _shot_voice(p, s)
            fp = _tts_fp(p, s, cfg)
            idx = shots.index(s) + 1
            rel = str(s.get("_tts_rel") or f"tts/shot{idx:02d}.wav")
            dest = Path(p["dir"]) / rel
            ent = cache.project_get(p["dir"], f"tts:{s['id']}")
            hit = False
            if ent and ent.get("fp") == fp and (Path(p["dir"]) / rel).is_file():
                hit = True
            elif cache.hit_to(fp, dest, "tts"):
                cache.project_set(p["dir"], f"tts:{s['id']}", fp, rel, True)
                hit = True
            if hit:
                s.update(tts=rel, tts_st="ok", tts_err="", tts_fp=fp, tts_cache_hit=True,
                         tts_ver=int(time.time() * 1000), duration=_wav_duration(dest))
                hits += 1
            else:
                s["tts_st"] = "run"
                miss.append((s, cfg, fp, idx, dest, rel))
        if not miss:
            await self._build_voice(p, shots=shots, out_prefix=out_prefix)
            _mark(p, "tts", "ok", f"{len(targets)} 句全部缓存命中", 100)
            j = self._job()
            if j:
                j.update(stage=2, pct=self._span[0] + self._span[1])
            self._save(p, True)
            return
        cloud = [x for x in miss if x[1].get("engine") == "cloud"]
        local = [x for x in miss if x[1].get("engine") != "cloud"]
        done = len(targets) - len(miss)
        lock = asyncio.Lock()
        fails = []
        seed = int(time.time()) % 65535 or 1

        async def tick(s, ok=True, why=""):
            nonlocal done
            async with lock:
                done += 1
                pct = 10 + done / max(1, len(targets)) * 78
                self._progress(pct, f"正在合成第 {done}/{len(targets)} 句（{s.get('role') or '旁白'}，语气：{s.get('tone') or '默认'}）…")
                self._phase(f"正在合成第 {done}/{len(targets)} 句（{s.get('role') or '旁白'}，语气：{s.get('tone') or '默认'}）…", pct, "running")
            if not ok:
                fails.append(f"{s.get('id')}：{why[:120]}")
            self._save(p)

        async def cloud_one(item):
            s, cfg, fp, idx, dest, rel = item
            if not tts_cloud.key():
                s.update(tts_st="err", tts_err="没填百炼 Key")
                await tick(s, False, "没填百炼 Key")
                return
            try:
                async with _api_gate():
                    r, _asked = await tts_cloud.synth_once_more(s.get("text") or "", cfg["voice"], (s.get("tone") or "")[:120],
                                                                seed, stop=lambda: self._stopped())
                sr, pcm = int(r["sr"]), r["pcm"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                tts.write_wav(dest, sr, pcm)
                dur = len(pcm) / 2 / sr
                cache.put(fp, dest, "tts", {"engine": "cloud", "voice": cfg.get("voice")})
                cache.project_set(p["dir"], f"tts:{s['id']}", fp, rel, False)
                s.update(tts=rel, tts_st="ok", tts_err="", tts_fp=fp, tts_cache_hit=False,
                         tts_ver=int(time.time() * 1000), duration=round(dur, 2))
                try:
                    _bill, cny = tts_cloud.record(cfg["voice"], s.get("text") or "", r.get("usage"), "视频工坊", dur)
                    p["cost"]["tts_cny"] = round(float(p["cost"].get("tts_cny") or 0) + float(cny), 4)
                except Exception:
                    pass
                await tick(s)
            except tts_cloud.Cancelled:
                s.update(tts_st="stale", tts_err="停下了")
                await tick(s, False, "停下了")
            except Exception as e:
                s.update(tts_st="err", tts_err=str(e)[:300])
                await tick(s, False, str(e))

        async def local_group():
            if not local:
                return
            if _gpu_lock().locked() or self._gpu_busy:
                self._phase("正在等待上一本地模型释放 GPU…", 5, "queued")
            self._gpu_busy = True
            try:
                async with _gpu_lock():
                    self._phase("已取得 GPU，正在启动本地配音服务…", 12, "running")
                    try:
                        bgm.B.stop("视频工坊：换配音模型，先释放显存")
                    except Exception:
                        pass
                    try:
                        await tts.T.ensure()
                    except Exception as e:
                        for s, cfg, fp, idx, dest, rel in local:
                            s.update(tts_st="err", tts_err=f"配音服务没起来：{str(e)[:200]}")
                            await tick(s, False, str(e))
                        return
                    for s, cfg, fp, idx, dest, rel in local:
                        if self._stopped():
                            s.update(tts_st="stale", tts_err="停下了")
                            await tick(s, False, "停下了")
                            continue
                        try:
                            req = {"mode": cfg.get("mode") or "preset", "speaker": cfg.get("speaker"), "desc": cfg.get("desc"),
                                   "name": cfg.get("name"), "seed": cfg.get("seed"), "tone": ""}
                            vv = tts.T.voice(req)
                            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=None)) as c:
                                r = await c.post(tts.T.url("/generate"), json={
                                    "kind": vv["kind"], "text": s.get("text") or "", "speaker": vv.get("speaker"),
                                    "instruct": (s.get("tone") or vv.get("instruct") or "")[:200],
                                    "language": vv.get("lang") or "Chinese", "seed": vv.get("seed")})
                            if r.status_code != 200:
                                try:
                                    why = r.json().get("detail") or r.text
                                except Exception:
                                    why = r.text
                                raise RuntimeError(str(why)[:200])
                            sr, pcm = tts.read_wav(r.content)
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            tts.write_wav(dest, sr, pcm)
                            dur = len(pcm) / 2 / sr
                            cache.put(fp, dest, "tts", {"engine": "local", "speaker": cfg.get("speaker") or cfg.get("id")})
                            cache.project_set(p["dir"], f"tts:{s['id']}", fp, rel, False)
                            s.update(tts=rel, tts_st="ok", tts_err="", tts_fp=fp, tts_cache_hit=False,
                                     tts_ver=int(time.time() * 1000), duration=round(dur, 2))
                            await tick(s)
                        except Exception as e:
                            s.update(tts_st="err", tts_err=str(e)[:300])
                            await tick(s, False, str(e))
            finally:
                self._gpu_busy = False

        await asyncio.gather(local_group(), *(cloud_one(x) for x in cloud))
        if fails:
            _mark(p, "tts", "err", "有句子没配成：" + "；".join(fails[:3]), 0)
            raise StudioError("配音有句子没配成：" + "；".join(fails[:3]))
        self._check_stop()
        self._phase("正在拼接音频与生成 SRT 时间轴…", 92, "running")
        await self._build_voice(p, shots=shots, out_prefix=out_prefix)
        _mark(p, "tts", "ok", f"配好 {len(shots)} 句" + (f"（{hits} 句缓存命中）" if hits else ""), 100)
        j = self._job()
        if j:
            j.update(stage=2, pct=self._span[0] + self._span[1])
        self._save(p, True)

    async def _build_voice(self, p, shots=None, out_prefix=""):
        """把每段配音拼成一条 voice.wav，并按实际时长写 subtitles.srt、每个分镜的 start/end。"""
        shots = shots if shots is not None else (p.get("shots") or [])
        if not shots:
            raise StudioError("还没有分镜")
        chunks, sr, tl = [], None, []
        cursor = 0.0
        texts = []
        for i, s in enumerate(shots):
            q = Path(p["dir"]) / (s.get("tts") or "")
            if not s.get("tts") or not q.is_file():
                raise StudioError(f"第 {i + 1} 镜还没有配音：先点「配音」或「一键全自动」")
            try:
                one_sr, pcm = tts.read_wav(q.read_bytes())
            except Exception as e:
                raise StudioError(f"第 {i + 1} 镜的配音文件读不了：{str(e)[:160]}") from None
            if sr is None:
                sr = one_sr
            if one_sr != sr:
                raise StudioError(f"第 {i + 1} 镜的采样率和其他段不一样（{one_sr} / {sr}）：重配这一段")
            dur = len(pcm) / 2 / sr
            if dur <= 0.05:
                raise StudioError(f"第 {i + 1} 镜的配音是空的：重配这一段")
            s["duration"] = round(dur, 3)
            s["start"] = round(cursor, 3)
            end = cursor + dur
            if i < len(shots) - 1:
                end += GAP
            s["end"] = round(end, 3)
            chunks.append(pcm)
            chunks.append(bytes(2 * int(sr * (GAP if i < len(shots) - 1 else 0))))
            cursor = end
            texts.append((s.get("text") or "").strip())
        total = cursor
        pcm_all = bytearray()
        for x in chunks:
            pcm_all += x
        d = Path(p["dir"]) / "tts"
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (str(out_prefix or "") + "voice.part.wav")
        tts.write_wav(tmp, sr, pcm_all)
        tmp.replace(d / (str(out_prefix or "") + "voice.wav"))
        # 字幕：一镜里太长就在逗号处再切，按字数分这段时间
        n = 0
        for i, ((s, text)) in enumerate(zip(shots, texts)):
            pieces = tts.soft_split(text) or [text]
            pieces = [x for x in pieces if x.strip()] or [text]
            weights = [max(1, len(x)) for x in pieces]
            tot = sum(weights)
            at = float(s["start"])
            span = max(0.1, float(s["duration"]))
            for j, (piece, w) in enumerate(zip(pieces, weights)):
                n += 1
                if j == len(pieces) - 1:
                    en = float(s["start"]) + span
                else:
                    en = at + span * w / tot
                tl.append({"i": n, "start": round(at, 3), "end": round(max(at + 0.05, en), 3), "text": piece})
                at = en
        (d / (str(out_prefix or "") + "subtitles.srt")).write_text(tts.to_srt(tl), "utf-8")
        meta = {"created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "sample_rate": sr, "total_seconds": round(total, 3),
                "voice": p["settings"].get("voice"), "role_voices": p["settings"].get("role_voices"),
                "shots": [{"id": s["id"], "role": s.get("role"), "speaker": s.get("speaker"), "tone": s.get("tone"),
                           "start": s["start"], "end": s["end"], "duration": s["duration"], "text": s.get("text")} for s in shots]}
        (d / (str(out_prefix or "") + "timeline.json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        pre = str(out_prefix or "")
        p["files"].update(voice=f"tts/{pre}voice.wav", srt=f"tts/{pre}subtitles.srt", timeline=f"tts/{pre}timeline.json")
        p["total_seconds"] = round(total, 3)
        if not p.get("_transient"):
            video_maker.save_project(p)
        return {"voice": f"tts/{pre}voice.wav", "srt": f"tts/{pre}subtitles.srt", "timeline": f"tts/{pre}timeline.json",
                "seconds": round(total, 3), "shots": shots}

    # ---------- 配乐 ----------
    async def _gen_bgm(self, p, dest_rel="bgm/bgm.wav", project_key="bgm"):
        self._step_start(p, "bgm", "准备配乐（GPU 通道）")
        fp, prompt, seconds, steps, seed = _bgm_fp(p)
        self._span = (65, 15)
        rel = str(dest_rel)
        dest = Path(p["dir"]) / rel
        ent = cache.project_get(p["dir"], project_key)
        if (ent and ent.get("fp") == fp and dest.is_file()) or cache.hit_to(fp, dest, "bgm"):
            cache.project_set(p["dir"], project_key, fp, rel, True)
            p["files"]["bgm"] = rel
            p["settings"]["use_bgm"] = True
            p["bgm_seconds"] = _wav_duration(dest) or seconds
            p["bgm_cache_hit"] = True
            _mark(p, "bgm", "ok", "配乐缓存命中", 100)
            j = self._job()
            if j:
                j.update(stage=2, pct=80)
            self._save(p, True)
            return
        # 换模型前先放显存：本地配音服务出完先关掉；和本地配音共用 GPU_LOCK
        if _gpu_lock().locked() or self._gpu_busy:
            self._phase("正在等待上一本地模型释放 GPU…", 0, "queued")
        self._progress(5, "正在启动/检查 Stable Audio 3 服务 (8094)…")
        self._phase("正在启动/检查 Stable Audio 3 服务 (8094)…", 8, "running")
        self._gpu_busy = True
        try:
            async with _gpu_lock():
                self._phase("已取得 GPU，正在准备 Stable Audio 3…", 15, "running")
                try:
                    tts.T.stop("视频工坊：换配乐模型，先释放显存")
                except Exception:
                    pass
                try:
                    r = await bgm.B.generate(prompt, seconds, say=lambda m: (self._progress(60, m), self._phase(m, 60, "running")),
                                             stopped=lambda: self._stopped(),
                                             dest=dest, steps=steps, seed=seed)
                except bgm.BgmError as e:
                    if self._stopped():
                        raise StopRequested() from None
                    _mark(p, "bgm", "warn", str(e)[:300], 0)
                    raise StudioError(str(e)) from None
        finally:
            self._gpu_busy = False
        self._phase("正在写入 bgm.wav…", 95, "running")
        p["files"]["bgm"] = f"bgm/{Path(r['path']).name}"
        p["settings"]["use_bgm"] = True
        p["bgm_seconds"] = r.get("duration") or seconds
        p["bgm_cache_hit"] = False
        cache.put(fp, dest, "bgm", {"duration": p["bgm_seconds"], "steps": steps, "seed": seed})
        cache.project_set(p["dir"], project_key, fp, rel, False)
        _mark(p, "bgm", "ok", f"配乐好了：{p['bgm_seconds']:.0f} 秒", 100)
        j = self._job()
        if j:
            j.update(stage=2, pct=80)
        self._save(p, True)
        telemetry.log("app", "studio_bgm", "视频工坊", "ok", float(r.get("sec") or 0) * 1000,
                      {"seconds": seconds, "duration": r.get("duration"), "seed": seed}, "视频工坊配乐好了")

    # ---------- 合成 ----------

    # ---------- 进度、保存 ----------
    def _stopped(self):
        if self._stop.is_set():
            return True
        ev = self._stops.get(_CUR_MID.get())
        return bool(ev and ev.is_set())

    def _check_stop(self):
        if self._stopped():
            raise StopRequested()

    def _step_start(self, p, name, msg):
        s = p["steps"].setdefault(name, {})
        s.update(st="run", msg=msg, err="", pct=0, t0=time.time(), t1=0)
        j = self._job()
        if j:
            j["step"] = name
            j["msg"] = msg
        self._phase(msg, None, "running")
        self._save(p, True)

    def _progress(self, local, msg):
        j = self._job()
        if j:
            j["pct"] = round(max(0.0, min(100.0, float(local or 0))), 1)
            if msg:
                j["msg"] = str(msg)[:200]
        self._phase(msg or j.get("msg", "") if j else "", local)

    def _save(self, p, force=False):
        if p.get("_transient"):
            return
        now = time.time()
        if force or now - self._saved >= 1.5:
            try:
                with self._save_lock:
                    mid = _CUR_MID.get()
                    if mid:
                        latest = video_maker.load_project(p["id"])
                        try:
                            idx = next(i for i, x in enumerate(latest.get("modules") or []) if x.get("id") == mid)
                            nm = graph.module_of(p, mid)
                            for k in ("x", "y", "w", "h"):
                                if latest["modules"][idx].get(k) is not None:
                                    nm[k] = latest["modules"][idx][k]
                            latest["modules"][idx] = nm
                            for k in ("files", "total_seconds", "duration", "resolution", "cost", "title", "desc", "tags"):
                                if k in p:
                                    latest[k] = p[k]
                            video_maker.save_project(latest)
                        except (StopIteration, graph.GraphError):
                            video_maker.save_project(p)
                    else:
                        video_maker.save_project(p)
                self._saved = now
            except Exception:
                pass

    # ---------- 参考图、发布 ----------
    def add_ref(self, body):
        p = self._load(_pid_of(body))
        b = imagegen.read_uri(body.get("data") or "")
        pi = imagegen.png_info(b)
        if pi["fmt"] not in ("png", "jpg"):
            raise HTTPException(400, "参考图只收 JPG / PNG（单张 ≤20MB，最多 16 张）")
        d = Path(p["dir"]) / "refs"
        d.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(b).hexdigest()[:12]
        name = re.sub(r'[\\/:*?"<>|]+', "", Path(str(body.get("name") or "参考图")).stem)[:30] or "参考图"
        dest = d / f"{h}_{name}.{pi['fmt']}"
        dest.write_bytes(b)
        return {"ok": True, "rel": dest.relative_to(Path(p["dir"])).as_posix(), "w": pi.get("w"), "h": pi.get("h")}

    def to_publish(self, body):
        p = self._load(_pid_of(body))
        d = Path(p["dir"])
        rel = (p.get("files") or {}).get("video") or "output/成片.mp4"
        video = d / rel
        if not video.is_file():
            raise HTTPException(400, "还没有成片：先跑视频制作总成，再送去发布")
        cv = body.get("cover")
        cover = None
        if cv in (None, "", "auto"):
            q = d / ((p.get("files") or {}).get("cover") or "")
            if q.is_file():
                cover = q
        elif str(cv).startswith("shot:"):
            pass
        else:
            q = Path(str(cv))
            cover = q if q.is_absolute() else d / q
        title = str(body.get("title") if body.get("title") is not None else p.get("title") or p.get("name") or "视频工坊成片").strip()[:publish.TITLE_MAX]
        desc = str(body.get("desc") if body.get("desc") is not None else p.get("desc") or "").strip()[:publish.DESC_MAX]
        tags = body.get("tags")
        if tags is None or (isinstance(tags, (list, str)) and not tags):
            tags = p.get("tags") or ["ai漫剧", "ai创作浪潮计划", "搞笑"]
        schedule = str(body.get("schedule") or "").strip().replace("T", " ")[:16]
        decl = str(body.get("declaration") or ("内容由AI生成" if body.get("ai_decl", True) else "") or settings.S.get("pubDecl") or "内容由AI生成").strip()
        if decl not in publish.DECL:
            decl = settings.S.get("pubDecl") or "内容由AI生成"
        try:
            item = publish.check_item({"file": str(video), "title": title, "desc": desc, "tags": tags, "schedule": schedule,
                                       "cover": str(cover) if cover and cover.is_file() else "", "declaration": decl,
                                       "collection": str(body.get("collection") or "").strip()[:40]})
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        mode = "batch" if body.get("mode") == "batch" else "single"
        if mode == "batch":
            if not schedule:
                raise HTTPException(400, "加入批量发布清单必须写定时发布时间（抖音批量都要定时）")
            board = db.kv_get("pub_batch") or None
            if not isinstance(board, dict) or not isinstance(board.get("items"), list):
                board = {"id": int(time.time() * 1000), "title": p.get("title") or p["id"], "folder": str(d / "output"),
                         "folder_show": paths.show(d / "output"), "warn": [], "lists": ["视频工坊"], "smart": False,
                         "items": [], "nv": 1, "ni": 1}
            same = next((x for x in board["items"] if x.get("video") == str(video)), None)
            row = {"id": same.get("id") if same else f"p{int(time.time() * 1000)}", "title": item["title"], "desc": item["desc"],
                   "tags": item["tags"], "schedule": item["schedule"], "collection": item["collection"],
                   "declaration": item["declaration"], "video_raw": video.name, "video": str(video), "video_show": video.name,
                   "cover": item["cover"], "cover_show": Path(item["cover"]).name if item["cover"] else "", "st": "idle", "err": "", "msg": ""}
            if same:
                same.update(row)
            else:
                board["items"].append(row)
            db.kv_set("pub_batch", board)
            return {"ok": True, "mode": "batch", "title": title, "n": len(board["items"]),
                    "msg": f"加入批量发布清单了（共 {len(board['items'])} 条）：到「发布」批量里确认，点两下才发"}
        for x in publish.pending():
            if (x.get("item") or {}).get("file") == str(video):
                return {"ok": True, "pid": x["id"], "msg": "这条已经在「发布」窗口等你确认了", "title": title}
        pub_id = publish.ask(item, None)
        feed.add(f"「{title}」放进发布窗口了：到「发布」看一眼，点两下才发", "warn", job=JOBS)
        return {"ok": True, "mode": "single", "pid": pub_id, "msg": "放进发布窗口了：到「发布」看一眼，改一改，点两下才发", "title": title}


S = Studio()
api = APIRouter()


def _pid_of(body) -> str:
    return str((body or {}).get("pid") or db.kv_get("studio_active") or "")


def _output_ok(p, o) -> bool:
    rel = (o or {}).get("rel") or ""
    return bool(rel and (Path(p["dir"]) / rel).is_file())


def _out(p, rel, kind, extra=None):
    """项目里的一个产出 → 节点 outputs 的一项（带内容哈希）。"""
    q = Path(p["dir"]) / str(rel or "") if rel else None
    if not q or not q.is_file():
        return None
    out = {"key": str(rel), "rel": str(rel), "kind": kind, "sha256": cache.sha_file(q), "size": q.stat().st_size}
    if extra:
        out.update({k: v for k, v in (extra or {}).items() if v not in (None, "")})
    return out


def _shot_ok(p, s, kind):
    rel = s.get(kind) or ""
    return bool(rel and (Path(p["dir"]) / rel).is_file())


def _mark(p, name, st, msg="", pct=None):
    s = p["steps"].setdefault(name, {})
    s.update(st=st, msg=str(msg)[:300], err=str(msg)[:300] if st in ("err", "warn", "stop") else "")
    if pct is not None:
        s["pct"] = pct
    if st in ("ok", "warn", "err", "stop") and not s.get("t1"):
        s["t1"] = time.time()


def _err_text(e):
    if isinstance(e, HTTPException):
        return str(e.detail)[:500]
    return str(e)[:500] or type(e).__name__


def safe_title(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", str(s or "")).strip(" .")
    return (s or "视频项目")[:24]


# ---------------- 接口 ----------------
@api.get("/api/studio/projects")
def studio_projects():
    return {"projects": video_maker.list_projects(), "active": db.kv_get("studio_active") or ""}


@api.get("/api/studio/state")
def studio_state(pid: str = ""):
    return S.state(pid or None)


@api.post("/api/studio/select")
def studio_select(body: dict = Body(...)):
    pid = str(body.get("pid") or "")
    try:
        return S.select(pid)
    except video_maker.MakerError as e:
        raise HTTPException(404, str(e)) from None
    except StudioError as e:
        raise HTTPException(400, str(e)) from None


@api.post("/api/studio/new")
def studio_new(body: dict = Body(default={})):
    try:
        return S.new_project(body)
    except HTTPException:
        raise
    except video_maker.MakerError as e:
        raise HTTPException(400, str(e)) from None


@api.get("/api/studio/export_prompt_pack")
def studio_export_prompt_pack(pid: str = ""):
    p = None
    if pid:
        try:
            p = S._load(pid)
        except (video_maker.MakerError, StudioError):
            p = None
    text = prompt_pack(p)
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="gemini_prompt_pack.md"'})


@api.post("/api/studio/script/import")
def studio_script_import(body: dict = Body(...)):
    try:
        return S.script_import(body)
    except HTTPException:
        raise
    except StudioError as e:
        raise HTTPException(400, str(e)) from None
    except (graph.GraphError, video_maker.MakerError) as e:
        raise HTTPException(400, str(e)) from None


@api.post("/api/studio/script/plan")
async def studio_script_plan(body: dict = Body(...)):
    try:
        return await S.script_plan(body)
    except HTTPException:
        raise
    except (graph.GraphError, video_maker.MakerError) as e:
        raise HTTPException(400, str(e)) from None


@api.get("/api/studio/list")
def studio_list_get(pid: str = "", name: str = ""):
    try:
        return S.list_get(pid, name)
    except (graph.GraphError, video_maker.MakerError, StudioError) as e:
        raise HTTPException(404, str(e)) from None


@api.put("/api/studio/list")
def studio_list_set(body: dict = Body(...)):
    try:
        return S.list_set(body)
    except HTTPException:
        raise
    except (graph.GraphError, video_maker.MakerError, StudioError) as e:
        raise HTTPException(400, str(e)) from None


@api.post("/api/studio/module/update")
def studio_module_update(body: dict = Body(...)):
    try:
        return S.module_update(body)
    except HTTPException:
        raise
    except (graph.GraphError, video_maker.MakerError) as e:
        raise HTTPException(404, str(e)) from None


@api.post("/api/studio/module/layout")
def studio_module_layout(body: dict = Body(...)):
    try:
        return S.module_layout(body)
    except (graph.GraphError, video_maker.MakerError) as e:
        raise HTTPException(404, str(e)) from None


@api.post("/api/studio/module/run")
async def studio_module_run(body: dict = Body(...)):
    return await S.start_run(body)


@api.post("/api/studio/stop")
def studio_stop(body: dict = Body(default={})):
    return S.stop(str((body or {}).get("module_id") or (body or {}).get("id") or ""))


@api.post("/api/studio/to_publish")
def studio_to_publish(body: dict = Body(default={})):
    return S.to_publish(body)


@api.get("/api/studio/media")
def studio_media(pid: str, path: str, v: int = 0):
    try:
        d = video_maker.project_path(pid)
    except video_maker.MakerError as e:
        raise HTTPException(404, str(e)) from None
    q = (d / path).resolve()
    if d.resolve() not in q.parents or q.suffix.lower() not in MEDIA_EXT or not q.is_file():
        raise HTTPException(404, "没有这个文件")
    return FileResponse(q, headers={"Cache-Control": "private, max-age=31536000"})


@api.get("/api/studio/asset")
def studio_asset(pid: str = "", path: str = "", cache: int = 0):
    try:
        q = studio_assets.cache_asset(path) if cache else studio_assets.project_asset(pid, path)
        return studio_assets.file_response(q)
    except (studio_assets.AssetError, video_maker.MakerError) as e:
        raise HTTPException(404, str(e)) from None


@api.get("/api/studio/asset/info")
def studio_asset_info(pid: str = "", path: str = "", cache: int = 0):
    try:
        q = studio_assets.cache_asset(path) if cache else studio_assets.project_asset(pid, path)
        return {"ok": True, "rel": str(path), "cache": bool(cache), **studio_assets.info(q)}
    except (studio_assets.AssetError, video_maker.MakerError) as e:
        raise HTTPException(404, str(e)) from None


@api.post("/api/studio/reveal")
def studio_reveal(body: dict = Body(default={})):
    try:
        q = studio_assets.cache_asset(body.get("path")) if body.get("cache") else \
            studio_assets.project_asset(body.get("pid"), body.get("path"))
        return studio_assets.reveal(q)
    except (studio_assets.AssetError, video_maker.MakerError) as e:
        raise HTTPException(404, str(e)) from None


@api.post("/api/studio/ref")
def studio_ref(body: dict = Body(...)):
    try:
        return S.add_ref(body)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"参考图没存成：{type(e).__name__} {str(e)[:120]}") from None


@api.post("/api/studio/open")
def studio_open(body: dict = Body(default={})):
    pid = str(body.get("pid") or db.kv_get("studio_active") or "")
    try:
        d = video_maker.project_path(pid)
    except video_maker.MakerError as e:
        raise HTTPException(404, str(e)) from None
    target = d / "output" if str(body.get("what") or "") == "output" else d
    target.mkdir(parents=True, exist_ok=True)
    if paths.IS_WIN:
        import os
        os.startfile(str(target))
        return {"msg": "打开了：" + paths.show(target)}
    return {"msg": "文件夹在：" + paths.show(target)}
