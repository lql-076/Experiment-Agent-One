r"""自媒体视频工坊（v3.8.1，R09）：默认可测子节点 + 全参数生图 + 内容寻址缓存 + 三路并行 DAG + 双轨缓存渲染。

八个顶层节点 + 动态子工作流：
  ① 剧本与策划：主题 / 完整口播；导出 Gemini 策划包；导入 Gemini .md/.json；DeepSeek 一键拆解。
  ② 分镜生图：每镜一个独立子节点；项目级/单镜全参数（模型、比例、自定义、1K~4K、n、画质、复杂度、透明、GIF、参考图）。
  ③ 角色配音：每句一个独立子节点；白页 / 紫苏 / 旁白默认音色；逐句 role/speaker/tone；单句试听与重配。
  ④ 背景配乐：Stable Audio 3 提示词、时长、步数、种子。
  ⑤ 网页动效：Playwright 渲染深色毛玻璃 / 粒子 / 动态字幕 / Q 版 GIF 贴纸轨。
  ⑥ PPT 卡片：python-pptx 自动生成或导入 OnlyOffice .pptx，渲染成幻灯片图。
  ⑦ FFmpeg 终混：网页/PPT/静态图 + 逐句配音 + 侧链闪避配乐 + 字幕。
  ⑧ 发布与排期：单条送审 / 批量清单 / 定时 / 话题 / 封面 / 合规声明。

生图 / 云端配音走 API 通道（4 并发），本地配音 / 配乐走 GPU 锁；生图、配音、配乐同时启动，
全部 ready 后汇聚到双轨渲染和合成。所有原子节点用 SHA-256 指纹查 studio_cache，命中直接复用。


固定风格「知识科普 × 科技数码 × 搞笑段子」；白页负责理性科普、紫苏负责夸张吐槽。
生图复用 app/imagegen.py 的低层调用，不碰生图页清单；本地配音和本地配乐串行，换模型前释放显存。
工程都存在 工作区\视频工坊\<项目名_时间戳>\project.json（不进仓库），单步重跑只动点名的那一步。
"""
import asyncio
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, Response

from . import bgm, db, deepseek, feed, imagegen, paths, publish, render_ppt, render_web, settings, studio_assets, studio_cache as cache, telemetry, tts, tts_cloud, video_maker

JOBS = "视频工坊"
RATIOS = [("9:16", "竖屏 9:16（抖音）"), ("16:9", "横屏 16:9")]
STYLE_TAG = "知识科普 × 科技数码 × 搞笑段子"
ROLES = ("白页", "紫苏", "旁白")
ROLE_DEFAULT_VOICES = {"白页": "local:preset:Serena", "紫苏": "local:preset:Vivian", "旁白": "local:preset:Uncle_Fu"}
GAP = video_maker.GAP
MAX_SHOTS = 15
_GATES = {}


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
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".wav", ".mp3", ".flac", ".mp4", ".mov", ".mkv", ".webm", ".srt", ".json"}

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
            "ref_image_sha256": ref_sha, "n": cfg["n"]}
    return [cache.fingerprint("image", dict(base, variant=i)) for i in range(cfg["n"])], prompt, cd, refs


def _shot_image_dest(p, s, variant, ext="png"):
    i = (p.get("shots") or []).index(s) + 1
    suffix = "" if int(_img_cfg(p, s)["n"]) == 1 else f"_v{variant + 1}"
    return Path(p["dir"]) / "images" / f"shot{i:02d}{suffix}.{(ext or 'png').lower()}"


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
    return cache.fingerprint("bgm", {"prompt_en": prompt, "duration": sec, "steps": steps, "seed": seed}), prompt, sec, steps, seed


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


# ---------------- 流水线 ----------------
class Studio:
    def __init__(self):
        self.job = None
        self._task = None
        self._stop = threading.Event()
        self._saved = 0.0
        self._span = (0.0, 100.0)

    # ---------- 状态 ----------
    def busy(self):
        return bool(self._task and not self._task.done())

    def public(self):
        j = self.job
        if not j:
            return None
        return {k: j.get(k) for k in ("id", "st", "mode", "step", "pid", "stage", "msg", "pct", "err", "shot")} | \
               {"elapsed": round((j.get("t1") or time.time()) - j.get("t0", time.time()))}

    def _recover(self, p):
        """Agent 重启后：上次停在 run 的步骤改成「中断」，别让它永远转圈。"""
        if self.busy() and self.job and self.job.get("pid") == p.get("id"):
            return
        changed = False
        for s in (p.get("steps") or {}).values():
            if s.get("st") == "run":
                s.update(st="err", err="上次跑到一半 Agent 重启了：点这一步重跑", pct=0)
                changed = True
        if p.get("st") == "run":
            p.update(st="err", error="上次跑到一半 Agent 重启了")
            changed = True
        if changed:
            video_maker.save_project(p)

    def _url(self, pid, rel, ver=0):
        return f"/api/studio/media?pid={quote(str(pid))}&path={quote(str(rel))}" + (f"&v={int(ver)}" if ver else "")

    def project_view(self, p) -> dict:
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
        shots = []
        for i, s in enumerate(p.get("shots") or []):
            img = s.get("image") or ""
            ip = d / img if img else None
            tp = d / (s.get("tts") or "") if s.get("tts") else None
            item = dict(s)
            item["n"] = i + 1
            role = item.get("role") if item.get("role") in ROLES else ROLES[i % 2]
            item["role"] = role
            rv = (p.get("settings") or {}).get("role_voices") or {}
            if not item.get("speaker"):
                item["speaker"] = rv.get(role) or ""
            if not item.get("tone"):
                item["tone"] = "轻松调侃" if role == "紫苏" else "冷静吐槽"
            item["image_ok"] = bool(ip and ip.is_file())
            item["tts_ok"] = bool(tp and tp.is_file())
            item["image_url"] = self._url(p["id"], img, ip.stat().st_mtime if item["image_ok"] else 0) if img else ""
            item["img_variant_urls"] = [self._url(p["id"], x, int(s.get("image_ver") or 0)) for x in (s.get("img_variants") or [])]
            item["tts_url"] = self._url(p["id"], s.get("tts"), tp.stat().st_mtime if item["tts_ok"] else 0) if s.get("tts") else ""
            if s.get("image_st") == "ok" and not item["image_ok"]:
                item["image_st"] = "missing"
            if s.get("tts_st") == "ok" and not item["tts_ok"]:
                item["tts_st"] = "missing"
            shots.append(item)
        steps = p.get("steps") or {}
        total = p.get("total_seconds")
        if not total:
            total = sum(float(s.get("duration") or s.get("seconds_hint") or 0) for s in shots)
        return {"id": p["id"], "name": p.get("name") or p["id"], "title": p.get("title") or "", "desc": p.get("desc") or "",
                "tags": p.get("tags") or [], "created": p.get("created") or "", "updated": p.get("updated") or "",
                "ratio": p.get("ratio") or "9:16", "style": STYLE_TAG, "style_tag": STYLE_TAG,
                "img_model": (p.get("settings") or {}).get("img_model") or settings.S.get("imgModel") or imagegen.DEFAULT_MODEL,
                "target_seconds": p.get("target_seconds") or 75, "topic": p.get("topic") or "",
                "source_text": p.get("source_text") or "", "bgm_prompt": p.get("bgm_prompt") or "",
                "settings": p.get("settings") or {}, "node_layout": p.get("node_layout") or {},
                "placeholder": bool(p.get("placeholder")), "no_auto_shot": bool(p.get("no_auto_shot")),
                "steps": steps, "files": files, "shots": shots, "bgm_cache_hit": bool(p.get("bgm_cache_hit")),
                "total_seconds": round(total or 0, 2), "duration": round(float(p.get("duration") or 0), 2),
                "resolution": p.get("resolution") or "", "st": p.get("st") or "idle", "error": p.get("error") or "",
                "cost": p.get("cost") or {}, "dir": paths.show(d),
                "video_ok": bool((d / (p.get("files", {}).get("video") or "output/成片.mp4")).is_file())}

    def state(self, pid=None) -> dict:
        projects = video_maker.list_projects()
        active = str(pid or db.kv_get("studio_active") or "").strip()
        if not active and projects:
            active = projects[0]["id"]
        # 没有任何项目时，开箱就建一个草稿项目：节点 2/3 立刻有默认可测节点，不用先拆剧本
        if not active and not projects:
            try:
                voice = voice_config("local:preset:Vivian")
                p = video_maker.new_project(safe_title("视频工坊草稿"), "9:16", STYLE_TAG, 75, topic="", voice=voice)
                p["settings"]["voice"] = voice
                p["settings"]["img_model"] = settings.S.get("imgModel") or imagegen.DEFAULT_MODEL
                _init_role_voices(p, voice)
                p["shots"] = [_default_shot(p, 1)]
                p["placeholder"] = True
                video_maker.save_project(p)
                active = p["id"]
                projects = video_maker.list_projects()
                db.kv_set("studio_active", active)
            except Exception:
                p = None
        p = p if 'p' in locals() and p else None
        if active and p is None:
            try:
                p = video_maker.load_project(active)
                self._recover(p)
                _init_role_voices(p)
                p["settings"].setdefault("img_model", settings.S.get("imgModel") or imagegen.DEFAULT_MODEL)
                ensure_default_shots(p)
                db.kv_set("studio_active", active)
            except video_maker.MakerError:
                p = None
        return {"projects": projects, "active": active, "project": self.project_view(p) if p else None,
                "job": self.public(), "voices": voice_options(), "ratios": [{"id": a, "label": b} for a, b in RATIOS],
                "style_tag": STYLE_TAG, "roles": list(ROLES), "models": image_models(),
                "default_model": settings.S.get("imgModel") or imagegen.DEFAULT_MODEL,
                "publish": {"pending": len(publish.pending()), "batch": len(((db.kv_get("pub_batch") or {}).get("items") or []))},
                "slot": [{"id": k, "label": v} for k, v in video_maker.SIZES.items()]}

    def select(self, pid):
        p = video_maker.load_project(pid)
        self._recover(p)
        _init_role_voices(p)
        ensure_default_shots(p)
        db.kv_set("studio_active", p["id"])
        return self.state(p["id"])

    # ---------- 工程 ----------
    async def plan(self, body) -> dict:
        pid = str(body.get("pid") or "").strip()
        old = video_maker.load_project(pid) if pid else None
        ratio = body.get("ratio") if body.get("ratio") in video_maker.SIZES else ((old or {}).get("ratio") or "9:16")
        topic = str(body.get("topic") or "").strip()
        text = str(body.get("text") or "").strip()
        voice = _default_voice(old) if old else voice_config(body.get("voice_id"))
        try:
            seconds = max(65, min(85, int(body.get("seconds") or (old or {}).get("target_seconds") or 75)))
        except (TypeError, ValueError):
            seconds = 75
        j, cny = await _ask_plan(topic or (old or {}).get("topic") or "", text or (old or {}).get("source_text") or "",
                                ratio or (old or {}).get("ratio") or "9:16", seconds)
        if old:
            p = old
            p["ratio"] = ratio
            p["target_seconds"] = seconds
        else:
            name = safe_title(j["title"] or topic or text or "视频项目")
            p = video_maker.new_project(name, ratio, STYLE_TAG, seconds, topic=topic or text[:4000], voice=voice)
        p["title"], p["desc"], p["tags"], p["bgm_prompt"] = j["title"], j["desc"], j["tags"], j["bgm_prompt"]
        p["source_text"] = text or p.get("source_text") or ""
        p["cost"]["plan_cny"] = round(cny, 4)
        p["settings"]["voice"] = voice
        p["settings"]["img_model"] = body.get("img_model") or (p.get("settings") or {}).get("img_model") or settings.S.get("imgModel") or imagegen.DEFAULT_MODEL
        _init_role_voices(p, voice)
        self._apply_plan(p, j)
        db.kv_set("studio_active", p["id"])
        telemetry.log("app", "studio_plan", "视频工坊", "ok", 0,
                      {"shots": len(p["shots"]), "ratio": p["ratio"], "seconds": seconds, "cny": round(cny, 4)},
                      f"拆好分镜：{len(p['shots'])} 镜 · {p['title']}")
        feed.add(f"视频工坊拆好分镜「{p['title']}」：{len(p['shots'])} 镜，约 {seconds} 秒", "ok", job=JOBS)
        return self.state(p["id"])

    def new_project(self, body) -> dict:
        ratio = body.get("ratio") if body.get("ratio") in video_maker.SIZES else "9:16"
        topic = str(body.get("topic") or "").strip()
        try:
            seconds = max(65, min(85, int(body.get("seconds") or 75)))
        except (TypeError, ValueError):
            seconds = 75
        voice = voice_config(body.get("voice_id"))
        p = video_maker.new_project(safe_title(topic or "未命名视频"), ratio, STYLE_TAG, seconds, topic=topic, voice=voice)
        p["settings"]["voice"] = voice
        p["settings"]["img_model"] = body.get("img_model") or settings.S.get("imgModel") or imagegen.DEFAULT_MODEL
        _init_role_voices(p, voice)
        p["shots"] = [_default_shot(p, 1)]
        p["placeholder"] = True
        video_maker.save_project(p)
        db.kv_set("studio_active", p["id"])
        return self.state(p["id"])

    def import_script(self, body) -> dict:
        text = str(body.get("text") or body.get("md") or body.get("script") or "").strip()
        if not text:
            raise StudioError("没有剧本内容：把 Gemini 的输出贴进来，或者选一个 .md / .json 文件")
        j = parse_script(text)
        pid = str(body.get("pid") or "").strip()
        old = video_maker.load_project(pid) if pid else None
        if old:
            p = old
        else:
            voice = voice_config(body.get("voice_id"))
            p = video_maker.new_project(safe_title(j["title"]), body.get("ratio") if body.get("ratio") in video_maker.SIZES else "9:16",
                                        STYLE_TAG, 75, topic=str(body.get("topic") or "").strip()[:4000], voice=voice)
            p["settings"]["voice"] = voice
            p["settings"]["img_model"] = body.get("img_model") or settings.S.get("imgModel") or imagegen.DEFAULT_MODEL
            _init_role_voices(p, voice)
        p["title"], p["desc"], p["tags"], p["bgm_prompt"] = j["title"], j["desc"], j["tags"], j["bgm_prompt"]
        p["source_text"] = text[:60000]
        p["style"] = STYLE_TAG
        self._apply_plan(p, j)
        p["steps"]["plan"].update(msg=f"导入剧本：{len(p['shots'])} 个分镜")
        video_maker.save_project(p)
        db.kv_set("studio_active", p["id"])
        feed.add(f"视频工坊导入剧本「{p['title']}」：{len(p['shots'])} 镜，可以直接跑", "ok", job=JOBS)
        return self.state(p["id"])

    def _apply_plan(self, p, j):
        had = bool(p.get("shots"))
        _init_role_voices(p)
        rv = (p.get("settings") or {}).get("role_voices") or {}
        p["style"] = STYLE_TAG
        p.setdefault("node_layout", {})
        p["placeholder"] = False
        p["no_auto_shot"] = False
        p["shots"] = []
        for i, s in enumerate(j["shots"]):
            role = s.get("role") if s.get("role") in ROLES else ROLES[i % 2]
            speaker = str(s.get("speaker") or rv.get(role) or _default_voice(p).get("id") or "")
            render = "web" if (i == 0 or i % 5 == 4) else "ppt" if i % 3 == 2 else "static"
            p["shots"].append({"id": f"s{i + 1}", "text": s["text"], "role": role, "speaker": speaker,
                               "tone": s.get("tone") or ("轻松调侃" if role == "紫苏" else "冷静吐槽"),
                               "image_prompt": s.get("image_prompt") or s["text"],
                               "seconds_hint": s.get("seconds_hint") or max(2.5, min(20.0, len(s["text"]) / 4.5)),
                               "image": "", "tts": "", "duration": 0.0, "start": 0.0, "end": 0.0,
                               "image_st": "idle", "tts_st": "idle", "image_err": "", "tts_err": "",
                               "image_ver": 0, "tts_ver": 0, "img_variants": [], "img_selected": 0,
                               "img_fps": [], "image_cache_hit": False, "tts_cache_hit": False,
                               "img_output": "normal", "img_format": "png", "tts_engine": "auto",
                               "render": render, "render_clip": "", "render_image": "", "ppt_points": [], "img_refs": []})
        if had:
            for k in ("voice", "srt", "timeline", "bgm", "video", "cover"):
                p.get("files", {}).pop(k, None)
            for k in ("images", "tts", "bgm", "video"):
                _mark(p, k, "stale", "剧本换了：这一步要重做")
        s = p["steps"]["plan"]
        s.update(st="ok", msg=f"{len(p['shots'])} 个分镜", pct=100, t1=time.time(), err="")
        video_maker.save_project(p)

    def update(self, body) -> dict:
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        p = video_maker.load_project(pid)
        _init_role_voices(p)
        p["settings"].setdefault("img_model", settings.S.get("imgModel") or imagegen.DEFAULT_MODEL)
        old_ratio = p.get("ratio")
        ratio = body.get("ratio")
        if ratio in video_maker.SIZES and ratio != old_ratio:
            p["ratio"] = ratio
            for s in p["shots"]:
                s["image_st"] = "stale"
            _mark(p, "images", "stale", "画幅改了：要重出图")
            _mark(p, "video", "stale", "画幅改了：要重新合成")
        p["style"] = STYLE_TAG
        if isinstance(body.get("node_layout"), dict):
            lay = {}
            for k, v in body["node_layout"].items():
                if isinstance(v, dict):
                    lay[str(k)[:60]] = {kk: v.get(kk) for kk in ("x", "y", "w", "h", "collapsed") if kk in v}
            p["node_layout"] = lay
        if "target_seconds" in body:
            try:
                p["target_seconds"] = max(10, min(600, int(body["target_seconds"])))
            except (TypeError, ValueError):
                pass
        for k in ("title", "desc", "bgm_prompt"):
            if k in body:
                old = p.get(k) or ""
                p[k] = str(body.get(k) or "").strip()[: (30 if k == "title" else 1000)]
                if k == "bgm_prompt" and p[k] != old:
                    p["files"].pop("bgm", None)
                    p["settings"]["use_bgm"] = True
                    _mark(p, "bgm", "stale", "配乐描述改了：要重做配乐")
                    _mark(p, "video", "stale", "配乐改了：要重新合成")
        if "tags" in body:
            tags = body.get("tags")
            if isinstance(tags, str):
                tags = re.split(r"[\s,，、#＃]+", tags)
            p["tags"] = [re.sub(r"^[#＃]+", "", str(x).strip())[:20] for x in (tags or []) if str(x).strip()][:10]
        st = body.get("settings")
        if isinstance(st, dict):
            for k in ("subtitle", "kenburns"):
                if k in st:
                    old = bool(p["settings"].get(k, True))
                    p["settings"][k] = bool(st[k])
                    if p["settings"][k] != old:
                        _mark(p, "video", "stale", "合成参数改了：要重新合成")
            if "bgm_volume" in st:
                try:
                    old = float(p["settings"].get("bgm_volume") or 0.18)
                    p["settings"]["bgm_volume"] = max(0.0, min(0.6, float(st["bgm_volume"])))
                    if abs(p["settings"]["bgm_volume"] - old) > 1e-4:
                        _mark(p, "video", "stale", "配乐音量改了：要重新合成")
                except (TypeError, ValueError):
                    pass
            for k in ("duck_depth", "fade"):
                if k in st:
                    try:
                        old = float((p.get("settings") or {}).get(k) if (p.get("settings") or {}).get(k) is not None else (0.16 if k == "duck_depth" else 2.0))
                        v = max(0.0, min(1.0 if k == "duck_depth" else 6.0, float(st[k])))
                        p["settings"][k] = v
                        if abs(v - old) > 1e-4:
                            _mark(p, "video", "stale", "混音参数改了：要重新合成")
                    except (TypeError, ValueError):
                        pass
            if st.get("img_model"):
                mid = str(st["img_model"]).strip()[:120]
                if mid and mid != ((p.get("settings") or {}).get("img_model") or ""):
                    p["settings"]["img_model"] = mid
                    for x in p.get("shots") or []:
                        x["image_st"] = "stale"
                    _mark(p, "images", "stale", "换生图模型了：要重出图")
                    _mark(p, "video", "stale", "换生图模型了：要重新合成")
            changed_img = False
            for k in IMG_SETTING_KEYS:
                if k in st:
                    old = (p.get("settings") or {}).get(k)
                    try:
                        val = _norm_img_setting(k, st[k], old)
                    except (TypeError, ValueError):
                        continue
                    if val != old:
                        p["settings"][k] = val
                        changed_img = True
            if "img_refs" in st:
                refs = st.get("img_refs")
                if isinstance(refs, str):
                    refs = [x.strip() for x in re.split(r"[\n,，;；]+", refs) if x.strip()]
                p["settings"]["img_refs"] = [str(x)[:300] for x in (refs or [])][:16] if isinstance(refs, list) else []
                changed_img = True
            if changed_img:
                _stale_images(p, "生图参数改了：要按新参数重出")
            web_changed = False
            for k in ("web_bg", "web_sub_pos", "web_sub_color"):
                if k in st and str(st[k] or "")[:60] != str((p.get("settings") or {}).get(k) or ""):
                    p["settings"][k] = str(st[k] or "")[:60]
                    web_changed = True
            for k in ("web_sub_size", "web_fps"):
                if k in st:
                    try:
                        v = max(12, min(120, int(st[k] or 0))) if k == "web_sub_size" else max(12, min(30, int(st[k] or 24)))
                        if v != int((p.get("settings") or {}).get(k) or 0):
                            p["settings"][k] = v
                            web_changed = True
                    except (TypeError, ValueError):
                        pass
            for k in ("web_gif_scale", "web_motion"):
                if k in st:
                    try:
                        v = max(.4, min(2.2, float(st[k] or 1)))
                        if abs(v - float((p.get("settings") or {}).get(k) or 1)) > 1e-4:
                            p["settings"][k] = v
                            web_changed = True
                    except (TypeError, ValueError):
                        pass
            if web_changed:
                _stale_track(p, "web", "网页动效参数改了：要重新渲染")
            if "ppt_file" in st:
                v = str(st["ppt_file"] or "").strip()[:500]
                if v != str((p.get("settings") or {}).get("ppt_file") or ""):
                    p["settings"]["ppt_file"] = v
                    _stale_track(p, "ppt", "PPT 文件改了：要重新渲染")
            if "bgm_seed" in st:
                try:
                    v = int(st["bgm_seed"] or 20261118)
                    if v != int((p.get("settings") or {}).get("bgm_seed") or 20261118):
                        p["settings"]["bgm_seed"] = v
                        _mark(p, "bgm", "stale", "配乐种子改了：要重做配乐")
                        _mark(p, "video", "stale", "配乐种子改了：要重新合成")
                except (TypeError, ValueError):
                    pass
            if isinstance(st.get("role_voices"), dict):
                rv = p["settings"].setdefault("role_voices", {})
                touched = False
                for role in ROLES:
                    vid = str(st["role_voices"].get(role) or "").strip()
                    if not vid or vid == rv.get(role):
                        continue
                    voice_config(vid)
                    old = rv.get(role)
                    rv[role] = vid
                    for x in p.get("shots") or []:
                        if x.get("role") == role and (not x.get("speaker") or x.get("speaker") == old):
                            x["speaker"] = vid
                            x["tts_st"] = "stale"
                    touched = True
                if touched:
                    _mark(p, "tts", "stale", "角色音色改了：要重配")
                    _mark(p, "video", "stale", "角色音色改了：要重新合成")
            if "bgm_seconds" in st:
                try:
                    old = int((p.get("settings") or {}).get("bgm_seconds") or 0)
                    p["settings"]["bgm_seconds"] = max(10, min(380, int(st["bgm_seconds"] or 0)))
                    if p["settings"]["bgm_seconds"] != old:
                        _mark(p, "bgm", "stale", "配乐时长改了：要重做配乐")
                        _mark(p, "video", "stale", "配乐时长改了：要重新合成")
                except (TypeError, ValueError):
                    pass
            if "bgm_steps" in st:
                try:
                    p["settings"]["bgm_steps"] = max(1, min(32, int(st["bgm_steps"] or 8)))
                    _mark(p, "bgm", "stale", "配乐步数改了：要重做配乐")
                except (TypeError, ValueError):
                    pass
            if st.get("voice_id"):
                cur = (p["settings"].get("voice") or {}).get("id")
                if str(st["voice_id"]) != str(cur):
                    p["settings"]["voice"] = voice_config(st["voice_id"])
                    for s in p["shots"]:
                        s["tts_st"] = "stale"
                    _mark(p, "tts", "stale", "换音色了：要重配")
                    _mark(p, "video", "stale", "换音色了：要重新合成")
        shots = body.get("shots")
        if isinstance(shots, list):
            by_id = {str(s.get("id")): s for s in shots if isinstance(s, dict)}
            for s in p["shots"]:
                q = by_id.get(s["id"])
                if not q:
                    continue
                changed_img = False
                for k in IMG_SETTING_KEYS:
                    if k in q:
                        old = s.get(k)
                        try:
                            val = _norm_img_setting(k, q[k], old)
                        except (TypeError, ValueError):
                            continue
                        if val != old:
                            s[k] = val
                            changed_img = True
                if "img_refs" in q:
                    refs = q.get("img_refs")
                    if isinstance(refs, str):
                        refs = [x.strip() for x in re.split(r"[\n,，;；]+", refs) if x.strip()]
                    s["img_refs"] = [str(x)[:300] for x in (refs or [])][:16] if isinstance(refs, list) else []
                    changed_img = True
                if "img_selected" in q and s.get("img_variants"):
                    try:
                        sel = max(0, min(len(s["img_variants"]) - 1, int(q["img_selected"])))
                    except (TypeError, ValueError):
                        sel = 0
                    s["img_selected"] = sel
                    s["image"] = s["img_variants"][sel]
                    s["image_ver"] = int(time.time() * 1000)
                    _mark(p, "video", "stale", "换了选中的那张图：要重新合成")
                if changed_img:
                    s["image_st"] = "stale"
                    s["image_cache_hit"] = False
                    _stale_images(p, "某一镜生图参数改了：要重出")
                if "render" in q:
                    r = str(q["render"] or "static")
                    r = r if r in ("web", "ppt", "static") else "static"
                    if r != (s.get("render") or "static"):
                        old = s.get("render") or "static"
                        s["render"] = r
                        if old in ("web", "ppt"):
                            _stale_track(p, old, "某一镜换了画面轨道：要重新渲染")
                        if r in ("web", "ppt"):
                            _stale_track(p, r, "某一镜换了画面轨道：要重新渲染")
                        _mark(p, "video", "stale", "画面轨道改了：要重新合成")
                if "ppt_points" in q:
                    pts = q.get("ppt_points")
                    if isinstance(pts, str):
                        pts = [x.strip() for x in re.split(r"[\n,，;；]+", pts) if x.strip()]
                    pts = [str(x)[:120] for x in (pts or [])][:5] if isinstance(pts, list) else []
                    if pts != (s.get("ppt_points") or []):
                        s["ppt_points"] = pts
                        _stale_track(p, "ppt", "PPT 卡片要点改了：要重新渲染")
                if "tts_engine" in q:
                    eng = str(q.get("tts_engine") or "auto")
                    eng = eng if eng in ("auto", "local", "cloud") else "auto"
                    if eng != (s.get("tts_engine") or "auto"):
                        s["tts_engine"] = eng
                        s["tts_st"] = "stale"
                        _mark(p, "tts", "stale", "配音引擎改了：要重配")
                        _mark(p, "video", "stale", "配音引擎改了：要重新合成")
                if "role" in q and str(q["role"]).strip() != (s.get("role") or ""):
                    role = str(q["role"]).strip()[:12]
                    if role not in ROLES:
                        role = s.get("role") or "白页"
                    s["role"] = role
                    rv = (p.get("settings") or {}).get("role_voices") or {}
                    if not q.get("speaker") and rv.get(role):
                        s["speaker"] = rv[role]
                    s["tts_st"] = "stale"
                    _mark(p, "tts", "stale", "角色改了：要重配")
                    _mark(p, "video", "stale", "角色改了：要重新合成")
                if "speaker" in q:
                    sp = str(q.get("speaker") or "").strip()[:80]
                    if sp and sp != (s.get("speaker") or ""):
                        voice_config(sp)
                        s["speaker"] = sp
                        s["tts_st"] = "stale"
                        _mark(p, "tts", "stale", "逐句音色改了：要重配")
                        _mark(p, "video", "stale", "逐句音色改了：要重新合成")
                if "text" in q and str(q["text"]).strip() != s["text"]:
                    s["text"] = str(q["text"]).strip()[:500]
                    s["tts_st"] = "stale"
                    _mark(p, "tts", "stale", "台词改了：要重配")
                    _mark(p, "video", "stale", "台词改了：要重新合成")
                if "tone" in q and str(q["tone"]).strip() != (s.get("tone") or ""):
                    s["tone"] = str(q["tone"]).strip()[:40]
                    s["tts_st"] = "stale"
                    _mark(p, "tts", "stale", "语气改了：要重配")
                    _mark(p, "video", "stale", "语气改了：要重新合成")
                if "image_prompt" in q and str(q["image_prompt"]).strip() != (s.get("image_prompt") or ""):
                    s["image_prompt"] = str(q["image_prompt"]).strip()[:1000]
                    s["image_st"] = "stale"
                    _mark(p, "images", "stale", "画面提示词改了：要重出这一张")
                    _mark(p, "video", "stale", "画面改了：要重新合成")
        # 自定义尺寸刚性校验（项目默认 + 每个分镜覆盖）
        scopes = [p.get("settings") or {}] + list(p.get("shots") or [])
        for sc in scopes:
            if sc.get("img_resolution") == "custom" or sc.get("img_custom_w") or sc.get("img_custom_h"):
                err = imagegen.validate_size(sc.get("img_custom_w") or 0, sc.get("img_custom_h") or 0)
                if err:
                    raise HTTPException(400, "自定义尺寸不合规：" + err + "（宽高 16 倍数、长边≤3840、比例≤3:1、像素 655,360–8,294,400）")
        video_maker.save_project(p)
        return self.project_view(p)

    # ---------- 跑 ----------
    async def start(self, body) -> dict:
        if self.busy():
            raise HTTPException(409, "正在跑：等它好了，或者先点「停下」")
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        mode = "step" if body.get("mode") == "step" else "all"
        step = str(body.get("step") or "").strip()
        if mode == "step" and step not in ("images", "tts", "bgm", "web", "ppt", "video"):
            raise HTTPException(400, "单步只能是 images / tts / bgm / video")
        if not pid:
            topic = str(body.get("topic") or "").strip()
            text = str(body.get("text") or "").strip()
            if mode != "all" or not (topic or text):
                raise HTTPException(400, "还没有项目：先在左边写主题，再一键全自动")
            ratio = body.get("ratio") if body.get("ratio") in video_maker.SIZES else "9:16"
            voice = voice_config(body.get("voice_id"))
            p = video_maker.new_project(safe_title(topic or text), ratio, STYLE_TAG,
                                        max(65, min(85, int(body.get("seconds") or 75))), topic=topic or text[:4000], voice=voice)
            p["settings"]["voice"] = voice
            p["settings"]["img_model"] = body.get("img_model") or settings.S.get("imgModel") or imagegen.DEFAULT_MODEL
            _init_role_voices(p, voice)
            p["shots"] = [_default_shot(p, 1)]
            p["placeholder"] = True
            p["source_text"] = text
            video_maker.save_project(p)
        else:
            p = video_maker.load_project(pid)
        ids = body.get("ids")
        if ids is not None:
            if not isinstance(ids, list):
                raise HTTPException(400, "ids 要是列表")
            ids = {str(x) for x in ids}
        if not p.get("shots") and not (mode == "all" and (p.get("topic") or p.get("source_text"))):
            raise HTTPException(400, "还没有分镜：先写主题点「AI 拆解分镜」，或者在一键全自动之前写好主题")
        self._stop.clear()
        self._saved = 0.0
        self.job = {"id": int(time.time() * 1000), "st": "run", "mode": mode, "step": step, "pid": p["id"],
                    "stage": 1 if not p.get("shots") else 2, "msg": "准备中", "pct": 0, "err": "", "shot": "",
                    "t0": time.time(), "t1": 0.0}
        db.kv_set("studio_active", p["id"])
        self._task = asyncio.get_running_loop().create_task(self._run(p, mode, step, ids))
        await asyncio.sleep(0.05)
        return {"job": self.public()}

    def stop(self):
        if not self.busy():
            return {"ok": False, "msg": "现在没有在跑的"}
        self._stop.set()
        if self.job:
            self.job["msg"] = "停下中：正在结束当前这一步……"
        step = (self.job or {}).get("step")
        if step == "tts":
            try:
                tts.T.stop("视频工坊：你点了停下")
            except Exception:
                pass
        if step == "bgm":
            try:
                if bgm.B.busy():
                    bgm.B.job["stop"] = "视频工坊：你点了停下"
            except Exception:
                pass
        telemetry.log("app", "studio_stop", "视频工坊", "warn", 0, {"pid": (self.job or {}).get("pid")}, "视频工坊：停下了")
        return {"ok": True, "msg": "停了：当前这一步收尾后不再往下做", "job": self.public()}

    async def _run(self, p, mode, step, ids):
        self.job["pid"] = p["id"]
        p["st"] = "run"
        p["error"] = ""
        video_maker.save_project(p)
        try:
            if mode == "all":
                await self._all(p)
            else:
                await self._one(p, step, ids)
            p["st"] = "done"
            p["error"] = ""
            self.job.update(st="done", pct=100, msg="全部完成", stage=4, t1=time.time())
            feed.add(f"视频工坊「{p.get('title') or p['id']}」好了：{self.job.get('msg')}", "ok", job=JOBS)
            if p.get("files", {}).get("video"):
                feed.done(f"视频工坊 · {p.get('title') or p['id']}", "生图 + 配音 + 配乐 + 合成", self.job["t1"] - self.job["t0"], "", "studio")
        except StopRequested:
            for s in p["steps"].values():
                if s.get("st") == "run":
                    s.update(st="stop", err="你点了停下", pct=0)
            for s in p.get("shots") or []:
                if s.get("image_st") == "run":
                    s["image_st"] = "stale"
                if s.get("tts_st") == "run":
                    s["tts_st"] = "stale"
            p["st"] = "stop"
            self.job.update(st="stop", msg="停了：没做完的保留着，下次点单步或一键全自动接着做", t1=time.time())
            feed.add("视频工坊停了：没做完的保留着，可以单步接着做", "warn", job=JOBS)
        except asyncio.CancelledError:
            p["st"] = "stop"
            raise
        except Exception as e:
            msg = _err_text(e)
            for s in p["steps"].values():
                if s.get("st") == "run":
                    s.update(st="err", err=msg, pct=0)
            for s in p.get("shots") or []:
                if s.get("image_st") == "run":
                    s["image_st"] = "stale"
                if s.get("tts_st") == "run":
                    s["tts_st"] = "stale"
            p["st"] = "err"
            p["error"] = msg
            self.job.update(st="err", err=msg, msg="没做成：" + msg[:200], t1=time.time())
            feed.add(f"视频工坊没做成：{msg[:300]}", "err", job=JOBS)
            telemetry.log("app", "studio_run", "视频工坊", "err", (time.time() - self.job["t0"]) * 1000,
                          {"pid": p["id"], "step": self.job.get("step"), "mode": mode}, msg[:300])
        finally:
            self.job["t1"] = self.job.get("t1") or time.time()
            video_maker.save_project(p)
            self._task = None

    async def _all(self, p):
        if (not p.get("shots")) or (p.get("placeholder") and (p.get("topic") or p.get("source_text"))):
            self.job.update(stage=1, msg="第一步：拆解分镜", pct=2)
            j, cny = await _ask_plan(p.get("topic") or "", p.get("source_text") or "", p.get("ratio"), p.get("target_seconds"))
            p["title"], p["desc"], p["tags"], p["bgm_prompt"] = j["title"], j["desc"], j["tags"], j["bgm_prompt"]
            p["cost"]["plan_cny"] = round(cny, 4)
            self._apply_plan(p, j)
        self._check_stop()
        tasks = [self._gen_images(p), self._gen_tts(p)]
        bgm_on = float((p.get("settings") or {}).get("bgm_volume") or 0) > 0
        if bgm_on:
            tasks.append(self._gen_bgm(p))
        res = await asyncio.gather(*tasks, return_exceptions=True)
        if self._stop.is_set():
            raise StopRequested()
        # 生图失败：一张都没有才阻塞；有部分就继续（video_maker 循环使用已有图）
        if isinstance(res[0], Exception):
            if not any(_shot_ok(p, s, "image") for s in p["shots"]):
                raise StudioError(_err_text(res[0]))
            _mark(p, "images", "warn", f"部分生图失败，先用已有的图：{_err_text(res[0])[:120]}", 100)
        # 配音失败：阻塞下游（成片必须有完整的逐句配音）
        if isinstance(res[1], Exception):
            raise StudioError(_err_text(res[1]))
        if not p.get("files", {}).get("voice"):
            await self._build_voice(p)
        # 配乐失败：不阻塞，合成无配乐版本
        if bgm_on and len(res) > 2 and isinstance(res[2], Exception):
            _mark(p, "bgm", "warn", f"配乐没出成，先合成无配乐版本：{_err_text(res[2])[:120]}", 100)
            p.get("files", {}).pop("bgm", None)
            p["settings"]["use_bgm"] = False
        self._check_stop()
        await self._render_tracks(p)
        await self._compose(p)

    async def _render_tracks(self, p, only=None):
        """网页动效 + PPT 卡片两条视觉轨道；失败降级为静态分镜。only='web'/'ppt' 时只跑一条。"""
        web = [s for s in p.get("shots") or [] if _render_mode(s) == "web"] if only in (None, "web") else []
        ppt = [s for s in p.get("shots") or [] if _render_mode(s) == "ppt"] if only in (None, "ppt") else []
        if web:
            self._step_start(p, "web", "网页动效渲染")
            self._span = (55, 10)
            try:
                await asyncio.to_thread(render_web.render_all, p["dir"], p, lambda m: self._progress(30, m), self._stop.is_set)
                hits = sum(1 for s in web if s.get("render_cache_hit"))
                _mark(p, "web", "ok", f"{len(web)} 镜网页动效好了" + (f"（{hits} 镜缓存命中）" if hits else ""), 100)
            except Exception as e:
                if self._stop.is_set():
                    raise StopRequested()
                _mark(p, "web", "warn", f"网页动效没成，降级静态分镜：{_err_text(e)[:120]}", 100)
                for s in web:
                    s["render_clip"] = ""
        else:
            _mark(p, "web", "ok", "这次没有网页动效镜头", 100)
        if ppt:
            self._step_start(p, "ppt", "PPT 卡片渲染")
            self._span = (60, 12)
            try:
                await asyncio.to_thread(render_ppt.render_all, p["dir"], p, lambda m: self._progress(40, m), self._stop.is_set)
                hits = sum(1 for s in ppt if s.get("render_cache_hit"))
                _mark(p, "ppt", "ok", f"{len(ppt)} 镜 PPT 卡片好了" + (f"（{hits} 镜缓存命中）" if hits else ""), 100)
            except Exception as e:
                if self._stop.is_set():
                    raise StopRequested()
                _mark(p, "ppt", "warn", f"PPT 卡片没成，降级静态分镜：{_err_text(e)[:120]}", 100)
                for s in ppt:
                    s["render_image"] = ""
        else:
            _mark(p, "ppt", "ok", "这次没有 PPT 卡片镜头", 100)
        self._save(p, True)

    async def _one(self, p, step, ids):
        if step == "images":
            await self._gen_images(p, ids)
        elif step == "tts":
            await self._gen_tts(p, ids)
        elif step == "bgm":
            await self._gen_bgm(p)
        elif step in ("web", "ppt"):
            await self._render_tracks(p, step)
        elif step == "video":
            if not p.get("files", {}).get("voice"):
                await self._build_voice(p)
            await self._compose(p)

    # ---------- 生图 ----------
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
                                   f"分镜生图 {done}/{len(targets)}：第 {shots.index(s) + 1} 镜")
                self._save(p)

        await asyncio.gather(*(one(s) for s in targets))
        good = sum(1 for s in shots if _shot_ok(p, s, "image"))
        if not good:
            _mark(p, "images", "err", "一张都没出来：" + "；".join(fails[:3]), 0)
            raise StudioError("生图一张都没出来：" + "；".join(fails[:3]))
        msg = f"出了 {good}/{len(shots)} 镜" + (f"，{len(fails)} 镜没出来" if fails else "")
        _mark(p, "images", "warn" if fails else "ok", msg, 100)
        if self.job:
            self.job.update(stage=2, pct=self._span[0] + self._span[1])
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

    async def _gen_tts(self, p, ids=None):
        self._step_start(p, "tts", "准备逐句配音")
        shots = p["shots"]
        if ids:
            targets = [s for s in shots if s["id"] in ids]
        else:
            targets = [s for s in shots if self._tts_stale(p, s)]
        if not targets:
            await self._build_voice(p)
            _mark(p, "tts", "ok", "配音都在", 100)
            return
        self._span = (35, 30)
        miss, hits = [], 0
        for s in targets:
            cfg = _shot_voice(p, s)
            fp = _tts_fp(p, s, cfg)
            idx = shots.index(s) + 1
            dest = Path(p["dir"]) / "tts" / f"shot{idx:02d}.wav"
            rel = f"tts/shot{idx:02d}.wav"
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
            await self._build_voice(p)
            _mark(p, "tts", "ok", f"{len(targets)} 句全部缓存命中", 100)
            if self.job:
                self.job.update(stage=2, pct=self._span[0] + self._span[1])
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
                self._progress(done / max(1, len(targets)) * 100,
                               f"逐句配音 {done}/{len(targets)}：{s.get('role') or '旁白'}")
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
                                                                seed, stop=lambda: self._stop.is_set())
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
            async with _gpu_lock():
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
                    if self._stop.is_set():
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

        await asyncio.gather(local_group(), *(cloud_one(x) for x in cloud))
        if fails:
            _mark(p, "tts", "err", "有句子没配成：" + "；".join(fails[:3]), 0)
            raise StudioError("配音有句子没配成：" + "；".join(fails[:3]))
        self._check_stop()
        await self._build_voice(p)
        _mark(p, "tts", "ok", f"配好 {len(shots)} 句" + (f"（{hits} 句缓存命中）" if hits else ""), 100)
        if self.job:
            self.job.update(stage=2, pct=self._span[0] + self._span[1])
        self._save(p, True)

    async def _build_voice(self, p):
        """把每段配音拼成一条 voice.wav，并按实际时长写 subtitles.srt、每个分镜的 start/end。"""
        shots = p.get("shots") or []
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
        tmp = d / "voice.part.wav"
        tts.write_wav(tmp, sr, pcm_all)
        tmp.replace(d / "voice.wav")
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
        (d / "subtitles.srt").write_text(tts.to_srt(tl), "utf-8")
        meta = {"created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "sample_rate": sr, "total_seconds": round(total, 3),
                "voice": p["settings"].get("voice"), "role_voices": p["settings"].get("role_voices"),
                "shots": [{"id": s["id"], "role": s.get("role"), "speaker": s.get("speaker"), "tone": s.get("tone"),
                           "start": s["start"], "end": s["end"], "duration": s["duration"], "text": s.get("text")} for s in shots]}
        (d / "timeline.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        p["files"].update(voice="tts/voice.wav", srt="tts/subtitles.srt", timeline="tts/timeline.json")
        p["total_seconds"] = round(total, 3)
        video_maker.save_project(p)

    # ---------- 配乐 ----------
    async def _gen_bgm(self, p):
        self._step_start(p, "bgm", "准备配乐（GPU 通道）")
        fp, prompt, seconds, steps, seed = _bgm_fp(p)
        self._span = (65, 15)
        dest = Path(p["dir"]) / "bgm" / "bgm.wav"
        rel = "bgm/bgm.wav"
        ent = cache.project_get(p["dir"], "bgm")
        if (ent and ent.get("fp") == fp and dest.is_file()) or cache.hit_to(fp, dest, "bgm"):
            cache.project_set(p["dir"], "bgm", fp, rel, True)
            p["files"]["bgm"] = rel
            p["settings"]["use_bgm"] = True
            p["bgm_seconds"] = _wav_duration(dest) or seconds
            p["bgm_cache_hit"] = True
            _mark(p, "bgm", "ok", "配乐缓存命中", 100)
            if self.job:
                self.job.update(stage=2, pct=80)
            self._save(p, True)
            return
        # 换模型前先放显存：本地配音服务出完先关掉；和本地配音共用 GPU_LOCK
        self._progress(0, "正在准备配乐（第一次要加载 Stable Audio 3）")
        async with _gpu_lock():
            try:
                tts.T.stop("视频工坊：换配乐模型，先释放显存")
            except Exception:
                pass
            try:
                r = await bgm.B.generate(prompt, seconds, say=lambda m: self._progress(10, m),
                                         stopped=lambda: self._stop.is_set(),
                                         dest=dest, steps=steps, seed=seed)
            except bgm.BgmError as e:
                if self._stop.is_set():
                    raise StopRequested() from None
                _mark(p, "bgm", "warn", str(e)[:300], 0)
                raise StudioError(str(e)) from None
        p["files"]["bgm"] = f"bgm/{Path(r['path']).name}"
        p["settings"]["use_bgm"] = True
        p["bgm_seconds"] = r.get("duration") or seconds
        p["bgm_cache_hit"] = False
        cache.put(fp, dest, "bgm", {"duration": p["bgm_seconds"], "steps": steps, "seed": seed})
        cache.project_set(p["dir"], "bgm", fp, rel, False)
        _mark(p, "bgm", "ok", f"配乐好了：{p['bgm_seconds']:.0f} 秒", 100)
        if self.job:
            self.job.update(stage=2, pct=80)
        self._save(p, True)
        telemetry.log("app", "studio_bgm", "视频工坊", "ok", float(r.get("sec") or 0) * 1000,
                      {"seconds": seconds, "duration": r.get("duration"), "seed": seed}, "视频工坊配乐好了")

    # ---------- 合成 ----------
    async def _compose(self, p):
        self._step_start(p, "video", "准备合成")
        if not p.get("files", {}).get("voice"):
            await self._build_voice(p)
        self._span = (80, 20)
        self.job.update(stage=3)
        opts = p.get("settings") or {}
        try:
            r = await asyncio.to_thread(video_maker.compose_video, p["dir"],
                                        bool(opts.get("subtitle", True)), float(opts.get("bgm_volume") or 0.18),
                                        bool(opts.get("kenburns", True)), self._stop.is_set,
                                        lambda x: self._progress(x.get("pct", 0), x.get("msg", "")),
                                        duck_depth=float(opts.get("duck_depth") or 0.16),
                                        fade=float(opts.get("fade") if opts.get("fade") is not None else 2.0))
        except video_maker.MakerError as e:
            _mark(p, "video", "err", str(e)[:300], 0)
            raise StudioError(str(e)) from None
        if r.get("stopped"):
            raise StopRequested()
        p["files"]["video"] = r["rel"]
        if r.get("cover_rel"):
            p["files"]["cover"] = r["cover_rel"]
        p["duration"] = r.get("duration")
        p["resolution"] = f"{r.get('w')}×{r.get('h')}"
        _mark(p, "video", "ok", f"成片好了：{r.get('duration', 0):.1f} 秒 · {p['resolution']}", 100)
        self.job.update(stage=4, pct=100)
        self._save(p, True)
        feed.add(f"成片合成好了：{p.get('title') or p['id']} · {r.get('duration', 0):.1f} 秒 · {p['resolution']}", "ok", job=JOBS)

    # ---------- 进度、保存 ----------
    def _check_stop(self):
        if self._stop.is_set():
            raise StopRequested()

    def _step_start(self, p, name, msg):
        s = p["steps"].setdefault(name, {})
        s.update(st="run", msg=msg, err="", pct=0, t0=time.time(), t1=0)
        if self.job:
            self.job["step"] = name
            self.job["shot"] = ""
            self.job["msg"] = msg
        self._save(p, True)

    def _progress(self, local, msg):
        if not self.job:
            return
        base, span = self._span
        self.job["pct"] = round(max(0.0, min(100.0, base + (float(local or 0) / 100.0) * span)), 1)
        if msg:
            self.job["msg"] = str(msg)[:200]

    def _save(self, p, force=False):
        now = time.time()
        if force or now - self._saved >= 1.5:
            try:
                video_maker.save_project(p)
                self._saved = now
            except Exception:
                pass

    # ---------- 发布 ----------
    def add_shot(self, body) -> dict:
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        p = video_maker.load_project(pid)
        _init_role_voices(p)
        used = {str(s.get("id")) for s in p.get("shots") or []}
        n = len(p.get("shots") or []) + 1
        while f"s{n}" in used:
            n += 1
        s = _default_shot(p, n)
        for k in ("text", "image_prompt", "tone"):
            if body.get(k):
                s[k] = str(body[k])[:500]
        if body.get("role") in ROLES:
            s["role"] = body["role"]
            rv = (p.get("settings") or {}).get("role_voices") or {}
            s["speaker"] = rv.get(s["role"]) or s["speaker"]
        p.setdefault("shots", []).append(s)
        p["placeholder"] = False
        p["no_auto_shot"] = False
        _mark(p, "images", "stale", "手动添加了分镜：要生图")
        _mark(p, "tts", "stale", "手动添加了分镜：要配音")
        _mark(p, "video", "stale", "分镜变了：要重新合成")
        video_maker.save_project(p)
        return self.project_view(p)

    def del_shot(self, body) -> dict:
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        sid = str(body.get("id") or "")
        p = video_maker.load_project(pid)
        before = len(p.get("shots") or [])
        p["shots"] = [s for s in (p.get("shots") or []) if str(s.get("id")) != sid]
        if len(p["shots"]) == before:
            raise HTTPException(404, "没有这个分镜")
        p["placeholder"] = False
        if not p["shots"]:
            p["no_auto_shot"] = True
        _mark(p, "images", "stale", "删了分镜：要重出/重新合成")
        _mark(p, "tts", "stale", "删了分镜：要重配")
        _mark(p, "video", "stale", "删了分镜：要重新合成")
        video_maker.save_project(p)
        return self.project_view(p)

    def add_ref(self, body) -> dict:
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        p = video_maker.load_project(pid)
        b = imagegen.read_uri(body.get("data") or "")
        pi = imagegen.png_info(b)
        if pi["fmt"] not in ("png", "jpg"):
            raise HTTPException(400, "参考图只收 JPG / PNG（单张 ≤20MB，最多 16 张）")
        ext = pi["fmt"]
        d = Path(p["dir"]) / "refs"
        d.mkdir(parents=True, exist_ok=True)
        h = cache.sha_file_bytes(b)[:12] if hasattr(cache, "sha_file_bytes") else __import__("hashlib").sha256(b).hexdigest()[:12]
        name = Path(str(body.get("name") or "参考图")).stem
        name = re.sub(r'[\/:*?"<>|]+', "", name)[:30] or "参考图"
        dest = d / f"{h}_{name}.{ext}"
        dest.write_bytes(b)
        rel = dest.relative_to(Path(p["dir"])).as_posix()
        return {"ok": True, "rel": rel, "w": pi.get("w"), "h": pi.get("h")}

    def to_publish(self, body) -> dict:
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        p = video_maker.load_project(pid)
        d = Path(p["dir"])
        rel = (p.get("files") or {}).get("video") or "output/成片.mp4"
        video = d / rel
        if not video.is_file():
            raise HTTPException(400, "还没有成片：先合成视频，再送去发布")
        # 封面：auto 用成片封面 / 选中分镜图；shot:<id> 用那一镜；也可以传项目里的路径
        cv = body.get("cover")
        cover = None
        if cv in (None, "", "auto"):
            q = d / ((p.get("files") or {}).get("cover") or "")
            if q.is_file():
                cover = q
            else:
                s0 = next((s for s in p.get("shots") or [] if s.get("image")), None)
                if s0:
                    cover = d / s0["image"]
        elif str(cv).startswith("shot:"):
            sid = str(cv).split(":", 1)[1]
            s0 = next((s for s in p.get("shots") or [] if s.get("id") == sid), None)
            if s0 and s0.get("image"):
                cover = d / s0["image"]
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
                                       "cover": str(cover) if cover and cover.is_file() else "",
                                       "declaration": decl,
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
            row = {"id": same.get("id") if same else f"p{int(time.time() * 1000)}",
                   "title": item["title"], "desc": item["desc"], "tags": item["tags"], "schedule": item["schedule"],
                   "collection": item["collection"], "declaration": item["declaration"],
                   "video_raw": video.name, "video": str(video), "video_show": video.name,
                   "cover": item["cover"], "cover_show": Path(item["cover"]).name if item["cover"] else "",
                   "st": "idle", "err": "", "msg": ""}
            if same:
                same.update(row)
            else:
                board["items"].append(row)
            db.kv_set("pub_batch", board)
            telemetry.log("app", "studio_to_publish", "视频工坊", "ok", 0,
                          {"pid": p["id"], "title": title, "mode": "batch", "schedule": schedule},
                          "视频工坊：成片已加入批量发布清单")
            feed.add(f"「{title}」加入批量发布清单了（定时 {schedule}）：到「发布」批量里确认", "warn", job=JOBS)
            return {"ok": True, "mode": "batch", "title": title, "n": len(board["items"]),
                    "msg": f"加入批量发布清单了（共 {len(board['items'])} 条）：到「发布」批量里确认，点两下才发"}
        for x in publish.pending():
            if (x.get("item") or {}).get("file") == str(video):
                return {"ok": True, "pid": x["id"], "msg": "这条已经在「发布」窗口等你确认了", "title": title}
        pub_id = publish.ask(item, None)
        telemetry.log("app", "studio_to_publish", "视频工坊", "ok", 0, {"pid": p["id"], "title": title, "mode": "single"},
                      "视频工坊：成片已放进发布待确认队列")
        feed.add(f"「{title}」放进发布窗口了：到「发布」看一眼，点两下才发", "warn", job=JOBS)
        return {"ok": True, "mode": "single", "pid": pub_id,
                "msg": "放进发布窗口了：到「发布」看一眼，改一改，点两下才发", "title": title}


S = Studio()
api = APIRouter()


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
            p = video_maker.load_project(pid)
        except video_maker.MakerError:
            p = None
    text = prompt_pack(p)
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="gemini_prompt_pack.md"'})


@api.post("/api/studio/import_script")
def studio_import_script(body: dict = Body(...)):
    try:
        return S.import_script(body)
    except StudioError as e:
        raise HTTPException(400, str(e)) from None
    except video_maker.MakerError as e:
        raise HTTPException(404, str(e)) from None


@api.post("/api/studio/plan")
async def studio_plan(body: dict = Body(...)):
    try:
        return await S.plan(body)
    except HTTPException:
        raise
    except video_maker.MakerError as e:
        raise HTTPException(400, str(e)) from None


@api.put("/api/studio/project")
def studio_update(body: dict = Body(...)):
    try:
        p = S.update(body)
        return {"project": p}
    except video_maker.MakerError as e:
        raise HTTPException(404, str(e)) from None
    except HTTPException:
        raise


@api.post("/api/studio/run")
async def studio_run(body: dict = Body(...)):
    return await S.start(body)


@api.post("/api/studio/stop")
def studio_stop():
    return S.stop()


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
    """灯箱读图：只给工坊项目目录或 _cache 里的图片，越界/符号链接/非图片都拒绝（v3.9.0）。"""
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
    """灯箱信息栏「打开所在文件夹」：只允许工坊目录里的图片。"""
    try:
        q = studio_assets.cache_asset(body.get("path")) if body.get("cache") else \
            studio_assets.project_asset(body.get("pid"), body.get("path"))
        return studio_assets.reveal(q)
    except (studio_assets.AssetError, video_maker.MakerError) as e:
        raise HTTPException(404, str(e)) from None


@api.post("/api/studio/shot_add")
def studio_shot_add(body: dict = Body(default={})):
    try:
        return {"project": S.add_shot(body)}
    except HTTPException:
        raise
    except video_maker.MakerError as e:
        raise HTTPException(404, str(e)) from None


@api.post("/api/studio/shot_delete")
def studio_shot_delete(body: dict = Body(...)):
    try:
        return {"project": S.del_shot(body)}
    except HTTPException:
        raise
    except video_maker.MakerError as e:
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
    what = str(body.get("what") or "")
    target = d / "output" if what == "output" else d
    target.mkdir(parents=True, exist_ok=True)
    if paths.IS_WIN:
        import os
        os.startfile(str(target))
        return {"msg": "打开了：" + paths.show(target)}
    return {"msg": "文件夹在：" + paths.show(target)}
