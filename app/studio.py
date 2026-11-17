r"""自媒体视频工坊（v3.6，R06）：文案拆解 → 生图 → 配音 → 配乐 → 视频合成 → 送去发布。

一条流水线，四步：
  ① 创意与拆解：主题 / 完整口播文案 + 画幅 + 风格 + 目标时长 → DeepSeek 一次给出四份联动脚本
     （分镜口播与语气、逐镜画面提示词、配乐英文提示词、标题与话题）。
  ② 素材生成：生图（复用 app/imagegen.py 的低层调用，不碰生图页的清单）、配音（复用配音服务）、配乐（复用 Stable Audio 3）。
     显存调度：本地配音和本地配乐不同时占显存——配音出完先停配音服务，再起配乐服务。
  ③ 视频合成：app/video_maker.py，时间轴按配音实际时长对齐，Ken Burns、字幕、配乐闪避、可停下。
  ④ 预览与发布：成片和封面填进「发布」模块的待确认队列，绝不绕过人工确认直接发抖音。

工程都存在 工作区\视频工坊\<项目名_时间戳>\project.json（不进仓库）。单步重跑只动点名的那一步，其余成果保留。
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
from fastapi.responses import FileResponse

from . import bgm, db, deepseek, feed, imagegen, paths, publish, settings, telemetry, tts, tts_cloud, video_maker

JOBS = "视频工坊"
RATIOS = [("9:16", "竖屏 9:16（抖音）"), ("16:9", "横屏 16:9")]
STYLES = ["知识科普", "科技数码", "情感故事", "搞笑段子", "生活记录", "影视解说", "职场干货", "历史人文"]
GAP = video_maker.GAP
MAX_SHOTS = 15
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".flac", ".mp4", ".mov", ".mkv", ".webm", ".srt", ".json"}

PLAN_SYS = """你是短视频编导，负责把一个主题（或用户写好的完整口播文案）拆成能直接生产的竖屏/横屏分镜。
只回 JSON，不要 Markdown、不要解释。格式：
{
  "title": "视频标题，30 字以内，有信息量、不夸张",
  "desc": "发布简介，80 字以内",
  "tags": ["3~6 个话题，不带 #"],
  "bgm_prompt": "English prompt for Stable Audio 3: style, mood, instruments, tempo, no vocals, suitable under narration",
  "shots": [
    {"text": "这一镜的口播，口语、顺口，20~60 字", "tone": "这一镜的语气，比如 轻松/兴奋/平静/稳重",
     "image_prompt": "这一镜的画面提示词，中文 40~120 字：主体、动作、构图、光线、色调、画风、镜头角度；画面里不要文字/logo/水印",
     "seconds_hint": 6}
  ]
}
规则：
- 4~10 个分镜，总口播字数接近「目标时长 × 4 字/秒」，别太长也别太短。
- 如果用户给了完整口播文案：原文一个字都不要改，只在句子之间分段，给它配画面和语气。
- 如果只给主题：口播由你写，开头 3 秒就要抓住人，结尾给一句自然的收束或互动。
- 画面提示词按整条视频的画幅来写：竖屏以中景/近景为主，主体放中间偏上，底部给字幕留空间；横屏注意左右构图。
- 每个分镜的画面要能独立看懂，前后镜头不要重复；风格统一。
- bgm_prompt 必须是英文，只写纯音乐（no vocals）。"
"""

PLAN_USER = """主题：{topic}
画幅：{ratio}（{ratio_cn}）
风格：{style}
目标时长：{seconds} 秒
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


def parse_plan(text: str) -> dict:
    """把 DeepSeek 的回复整理成统一结构；不认识的写法尽量认，认不出就报清楚。"""
    j = _json_of(text)
    title = str(_pick(j, "title", "标题") or "未命名视频").strip()
    desc = str(_pick(j, "desc", "description", "简介") or "").strip()
    tags = _pick(j, "tags", "话题", "hashtags") or []
    if isinstance(tags, str):
        tags = re.split(r"[\s,，、#＃]+", tags)
    tags = [re.sub(r"^[#＃]+", "", str(x).strip())[:20] for x in tags if str(x).strip()][:10]
    bgm_prompt = str(_pick(j, "bgm_prompt", "bgm", "配乐提示词", "music_prompt") or "").strip()
    raw = _pick(j, "shots", "分镜", "storyboard", "segments")
    if not isinstance(raw, list):
        raise StudioError("DeepSeek 没给分镜列表（shots）")
    shots = []
    for i, x in enumerate(raw):
        if isinstance(x, str):
            x = {"text": x}
        if not isinstance(x, dict):
            continue
        body = str(_pick(x, "text", "narration", "voiceover", "口播", "文案", "content", "line") or "").strip()
        pic = str(_pick(x, "image_prompt", "image", "画面提示词", "画面", "prompt", "visual") or "").strip()
        tone = str(_pick(x, "tone", "语气", "emotion") or "").strip()[:40]
        if not body:
            continue
        if not pic:
            pic = body
        try:
            hint = float(_pick(x, "seconds_hint", "seconds", "duration", "时长") or 6)
        except (TypeError, ValueError):
            hint = 6.0
        shots.append({"text": body[:500], "tone": tone, "image_prompt": pic[:1000],
                      "seconds_hint": max(2.5, min(20.0, hint))})
    if len(shots) < 2:
        raise StudioError("DeepSeek 只给出不到 2 个分镜：再说清楚一点，或者直接贴口播文案再试")
    shots = shots[:MAX_SHOTS]
    return {"title": title[:30] or "未命名视频", "desc": desc[:300], "tags": tags, "bgm_prompt": bgm_prompt[:1000], "shots": shots}


async def _ask_plan(topic, text, ratio, style, seconds):
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
    user = PLAN_USER.format(topic=topic or "（见下面的完整文案）", ratio=ratio, ratio_cn=ratio_cn, style=style, seconds=seconds,
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
            item["image_ok"] = bool(ip and ip.is_file())
            item["tts_ok"] = bool(tp and tp.is_file())
            item["image_url"] = self._url(p["id"], img, ip.stat().st_mtime if item["image_ok"] else 0) if img else ""
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
                "ratio": p.get("ratio") or "9:16", "style": p.get("style") or "知识科普",
                "target_seconds": p.get("target_seconds") or 60, "topic": p.get("topic") or "",
                "source_text": p.get("source_text") or "", "bgm_prompt": p.get("bgm_prompt") or "",
                "settings": p.get("settings") or {}, "steps": steps, "files": files, "shots": shots,
                "total_seconds": round(total or 0, 2), "duration": round(float(p.get("duration") or 0), 2),
                "resolution": p.get("resolution") or "", "st": p.get("st") or "idle", "error": p.get("error") or "",
                "cost": p.get("cost") or {}, "dir": paths.show(d),
                "video_ok": bool((d / (p.get("files", {}).get("video") or "output/成片.mp4")).is_file())}

    def state(self, pid=None) -> dict:
        projects = video_maker.list_projects()
        active = str(pid or db.kv_get("studio_active") or "").strip()
        if not active and projects:
            active = projects[0]["id"]
        p = None
        if active:
            try:
                p = video_maker.load_project(active)
                self._recover(p)
                db.kv_set("studio_active", active)
            except video_maker.MakerError:
                p = None
        return {"projects": projects, "active": active, "project": self.project_view(p) if p else None,
                "job": self.public(), "voices": voice_options(), "ratios": [{"id": a, "label": b} for a, b in RATIOS],
                "styles": STYLES, "slot": [{"id": k, "label": v} for k, v in video_maker.SIZES.items()]}

    def select(self, pid):
        p = video_maker.load_project(pid)
        self._recover(p)
        db.kv_set("studio_active", p["id"])
        return self.state(p["id"])

    # ---------- 工程 ----------
    async def plan(self, body) -> dict:
        ratio = body.get("ratio") if body.get("ratio") in video_maker.SIZES else "9:16"
        style = str(body.get("style") or "知识科普")[:40]
        topic = str(body.get("topic") or "").strip()
        text = str(body.get("text") or "").strip()
        voice = voice_config(body.get("voice_id"))
        j, cny = await _ask_plan(topic, text, ratio, style, body.get("seconds") or 60)
        name = safe_title(j["title"] or topic or text or "视频项目")
        p = video_maker.new_project(name, ratio, style, body.get("seconds") or 60, topic=topic or text[:4000], voice=voice)
        p["title"] = j["title"]
        p["desc"] = j["desc"]
        p["tags"] = j["tags"]
        p["bgm_prompt"] = j["bgm_prompt"]
        p["source_text"] = text
        p["cost"]["plan_cny"] = round(cny, 4)
        self._apply_plan(p, j)
        db.kv_set("studio_active", p["id"])
        telemetry.log("app", "studio_plan", "视频工坊", "ok", 0,
                      {"shots": len(p["shots"]), "ratio": ratio, "seconds": p["target_seconds"], "cny": round(cny, 4)},
                      f"拆好分镜：{len(p['shots'])} 镜 · {p['title']}")
        feed.add(f"视频工坊拆好分镜「{p['title']}」：{len(p['shots'])} 镜，预估 {p['target_seconds']} 秒", "ok", job=JOBS)
        return self.state(p["id"])

    def _apply_plan(self, p, j):
        p["shots"] = []
        for i, s in enumerate(j["shots"]):
            p["shots"].append({"id": f"s{i + 1}", "text": s["text"], "tone": s["tone"], "image_prompt": s["image_prompt"],
                               "seconds_hint": s["seconds_hint"], "image": "", "tts": "", "duration": 0.0,
                               "start": 0.0, "end": 0.0, "image_st": "idle", "tts_st": "idle",
                               "image_err": "", "tts_err": "", "image_ver": 0, "tts_ver": 0})
        s = p["steps"]["plan"]
        s.update(st="ok", msg=f"{len(p['shots'])} 个分镜", pct=100, t1=time.time(), err="")
        video_maker.save_project(p)

    def update(self, body) -> dict:
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        p = video_maker.load_project(pid)
        old_ratio = p.get("ratio")
        ratio = body.get("ratio")
        if ratio in video_maker.SIZES and ratio != old_ratio:
            p["ratio"] = ratio
            for s in p["shots"]:
                s["image_st"] = "stale"
            _mark(p, "images", "stale", "画幅改了：要重出图")
            _mark(p, "video", "stale", "画幅改了：要重新合成")
        if "style" in body:
            p["style"] = str(body.get("style") or "知识科普")[:40]
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
        video_maker.save_project(p)
        return self.project_view(p)

    # ---------- 跑 ----------
    async def start(self, body) -> dict:
        if self.busy():
            raise HTTPException(409, "正在跑：等它好了，或者先点「停下」")
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        mode = "step" if body.get("mode") == "step" else "all"
        step = str(body.get("step") or "").strip()
        if mode == "step" and step not in ("images", "tts", "bgm", "video"):
            raise HTTPException(400, "单步只能是 images / tts / bgm / video")
        if not pid:
            topic = str(body.get("topic") or "").strip()
            text = str(body.get("text") or "").strip()
            if mode != "all" or not (topic or text):
                raise HTTPException(400, "还没有项目：先在左边写主题，再一键全自动")
            ratio = body.get("ratio") if body.get("ratio") in video_maker.SIZES else "9:16"
            p = video_maker.new_project(safe_title(topic or text), ratio, str(body.get("style") or "知识科普")[:40],
                                        body.get("seconds") or 60, topic=topic or text[:4000], voice=voice_config(body.get("voice_id")))
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
        if not p.get("shots"):
            self.job.update(stage=1, msg="第一步：拆解分镜", pct=2)
            j, cny = await _ask_plan(p.get("topic") or "", p.get("source_text") or "", p.get("ratio"), p.get("style"), p.get("target_seconds"))
            p["title"], p["desc"], p["tags"], p["bgm_prompt"] = j["title"], j["desc"], j["tags"], j["bgm_prompt"]
            p["cost"]["plan_cny"] = round(cny, 4)
            self._apply_plan(p, j)
        self._check_stop()
        need_img = any(not _shot_ok(p, s, "image") for s in p["shots"]) or p["steps"]["images"].get("st") in ("idle", "stale", "err")
        if need_img:
            await self._gen_images(p)
        else:
            _mark(p, "images", "ok", f"{len(p['shots'])} 张都在", 100)
        self._check_stop()
        need_tts = any(not _shot_ok(p, s, "tts") for s in p["shots"]) or p["steps"]["tts"].get("st") in ("idle", "stale", "err")
        if need_tts:
            await self._gen_tts(p)
        else:
            await self._build_voice(p)
            _mark(p, "tts", "ok", "配音都在", 100)
        self._check_stop()
        bgm_ok = bool(p["files"].get("bgm")) and (Path(p["dir"]) / p["files"]["bgm"]).is_file()
        if float(p["settings"].get("bgm_volume") or 0) > 0 and not bgm_ok:
            try:
                await self._gen_bgm(p)
            except StopRequested:
                raise
            except Exception as e:
                _mark(p, "bgm", "warn", f"配乐没出成，先合成没有配乐的版本：{_err_text(e)[:160]}", 100)
                p["files"].pop("bgm", None)
                p["settings"]["use_bgm"] = False
                feed.add("视频工坊：配乐没出成，先合成没有配乐的版本（配音和画面不受影响）", "warn", job=JOBS)
        elif bgm_ok:
            _mark(p, "bgm", "ok", "配乐在", 100)
        await self._compose(p)

    async def _one(self, p, step, ids):
        if step == "images":
            await self._gen_images(p, ids)
        elif step == "tts":
            await self._gen_tts(p, ids)
        elif step == "bgm":
            await self._gen_bgm(p)
        elif step == "video":
            if not p.get("files", {}).get("voice"):
                await self._build_voice(p)
            await self._compose(p)

    # ---------- 生图 ----------
    async def _gen_images(self, p, ids=None):
        self._step_start(p, "images", "准备生图")
        shots = p["shots"]
        if ids:
            targets = [s for s in shots if s["id"] in ids]
        else:
            targets = [s for s in shots if not _shot_ok(p, s, "image") or s.get("image_st") in ("idle", "stale", "err", "missing")]
        if not targets:
            _mark(p, "images", "ok", "都已经出好了", 100)
            return
        key = settings.get_secret("imgKey")
        if not key:
            raise HTTPException(400, "还没填 API易 的 Key：到 设置 › 云端 填好，再生成画面")
        cd = imagegen.card()
        tiers = imagegen.tiers_of(cd)
        tier = settings.S.get("imgRes") if settings.S.get("imgRes") in tiers else (tiers[0] if tiers else "2k")
        quality = settings.S.get("imgQuality") or "high"
        base = (settings.S.get("imgBase") or "https://api.apiyi.com/v1").rstrip("/")
        kind = "prompt" if cd["size"] == "prompt" else "official"
        self._span = (5, 30)
        fails = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=imagegen.TIMEOUT, write=120.0, pool=None)) as c:
            for k, s in enumerate(targets):
                self._check_stop()
                s["image_st"] = "run"
                if self.job:
                    self.job["shot"] = s["id"]
                self._progress(k / max(1, len(targets)) * 100, f"正在生图 {k + 1}/{len(targets)}：第 {p['shots'].index(s) + 1} 镜")
                self._save(p, True)
                prompt = imagegen.build_prompt({"prompt": s["image_prompt"] or s["text"], "ratio": p["ratio"], "transparent": False},
                                               p.get("style") or "", False, True, kind)
                try:
                    img, usage, _sent = await imagegen.CALL.get(cd["proto"], imagegen._call_openai)(
                        c, base, key, cd, prompt, p["ratio"], tier, quality, False, [])
                    pi = imagegen.png_info(img)
                    ext = pi["fmt"] if pi["fmt"] in ("png", "jpg", "webp") else "png"
                    name = f"shot{(p['shots'].index(s) + 1):02d}.{ext}"
                    dest = Path(p["dir"]) / "images" / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    for old in dest.parent.glob(f"shot{(p['shots'].index(s) + 1):02d}.*"):
                        if old != dest:
                            try:
                                old.unlink()
                            except OSError:
                                pass
                    tmp = dest.with_name(dest.name + ".part")
                    tmp.write_bytes(img)
                    tmp.replace(dest)
                    if usage and cd["price"] is None:
                        usd = float(usage.get("output_tokens") or 0) * imagegen.USD_OUT + float(usage.get("input_tokens") or 0) * imagegen.USD_IN
                    else:
                        usd = cd["price"] if cd["price"] is not None else (imagegen.est_usd(cd, p["ratio"], tier, quality) or 0.0)
                    s.update(image=f"images/{name}", image_st="ok", image_err="", image_ver=int(time.time() * 1000),
                             image_w=pi["w"], image_h=pi["h"])
                    p["cost"]["images_usd"] = round(float(p["cost"].get("images_usd") or 0) + float(usd), 4)
                    telemetry.log("app", "studio_image", "视频工坊", "ok", 0,
                                  {"shot": s["id"], "ratio": p["ratio"], "w": pi["w"], "h": pi["h"], "usd": round(float(usd), 4)},
                                  f"视频工坊生图：第 {p['shots'].index(s) + 1} 镜")
                except imagegen.ImgError as e:
                    s.update(image_st="err", image_err=str(e)[:300])
                    fails.append(f"第 {p['shots'].index(s) + 1} 镜：{str(e)[:100]}")
                    if getattr(e, "fatal", False):
                        raise StudioError(f"生图停了：{str(e)[:300]}") from None
                except Exception as e:
                    s.update(image_st="err", image_err=f"{type(e).__name__} {str(e)[:200]}")
                    fails.append(f"第 {p['shots'].index(s) + 1} 镜：{type(e).__name__}")
                self._save(p)
        good = sum(1 for s in shots if _shot_ok(p, s, "image"))
        if not good:
            _mark(p, "images", "err", "一张都没出来：" + "；".join(fails[:3]), 0)
            raise StudioError("生图一张都没出来：" + "；".join(fails[:3]))
        msg = f"出了 {good}/{len(shots)} 张" + (f"，{len(fails)} 张没出来" if fails else "")
        _mark(p, "images", "warn" if fails else "ok", msg, 100)
        self.job.update(stage=2, pct=self._span[0] + self._span[1])
        self._save(p, True)

    # ---------- 配音 ----------
    async def _gen_tts(self, p, ids=None):
        self._step_start(p, "tts", "准备配音")
        shots = p["shots"]
        if ids:
            targets = [s for s in shots if s["id"] in ids]
        else:
            targets = [s for s in shots if not _shot_ok(p, s, "tts") or s.get("tts_st") in ("idle", "stale", "err", "missing")]
        if not targets:
            await self._build_voice(p)
            _mark(p, "tts", "ok", "配音都在", 100)
            return
        v = p["settings"].get("voice") or {"engine": "local", "mode": "preset", "speaker": "Vivian", "label": "Vivian"}
        self._span = (35, 30)
        if v.get("engine") == "cloud":
            await self._tts_cloud(p, targets, v)
        else:
            await self._tts_local(p, targets, v)
        self._check_stop()
        await self._build_voice(p)
        _mark(p, "tts", "ok", f"配好 {len(shots)} 段，总长 {p.get('total_seconds', 0):.1f} 秒", 100)
        self.job.update(stage=2, pct=self._span[0] + self._span[1])
        self._save(p, True)

    async def _tts_local(self, p, targets, v):
        # 换模型前先放显存：配乐服务要是开着（上一轮或配乐页），先关掉
        try:
            bgm.B.stop("视频工坊：换配音模型，先释放显存")
        except Exception:
            pass
        try:
            req = {"mode": v.get("mode") or "preset", "speaker": v.get("speaker"), "desc": v.get("desc"),
                   "name": v.get("name"), "seed": v.get("seed"), "tone": ""}
            vv = tts.T.voice(req)
        except HTTPException as e:
            raise StudioError(str(e.detail)) from None
        try:
            await tts.T.ensure()
        except Exception as e:
            raise StudioError(f"配音服务没起来：{str(e)[:300]}") from None
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=None)) as c:
            for k, s in enumerate(targets):
                self._check_stop()
                s["tts_st"] = "run"
                if self.job:
                    self.job["shot"] = s["id"]
                self._progress(k / max(1, len(targets)) * 100, f"正在配音 {k + 1}/{len(targets)}：第 {p['shots'].index(s) + 1} 镜")
                self._save(p, True)
                text = (s.get("text") or "").strip()
                if not text:
                    raise StudioError(f"第 {p['shots'].index(s) + 1} 镜的台词是空的")
                try:
                    r = await c.post(tts.T.url("/generate"), json={
                        "kind": vv["kind"], "text": text, "speaker": vv.get("speaker"),
                        "instruct": (s.get("tone") or vv.get("instruct") or "")[:200],
                        "language": vv.get("lang") or "Chinese", "seed": vv.get("seed")})
                except httpx.HTTPError as e:
                    if self._stop.is_set():
                        raise StopRequested() from None
                    raise StudioError(f"配音服务断了：{type(e).__name__}") from None
                if r.status_code != 200:
                    if self._stop.is_set():
                        raise StopRequested()
                    try:
                        why = r.json().get("detail") or r.text
                    except Exception:
                        why = r.text
                    raise StudioError(f"第 {p['shots'].index(s) + 1} 镜没配成：{str(why)[:300]}")
                try:
                    sr, pcm = tts.read_wav(r.content)
                except Exception as e:
                    raise StudioError(f"配音服务回来的音频不对：{str(e)[:200]}") from None
                idx = p["shots"].index(s) + 1
                dest = Path(p["dir"]) / "tts" / f"shot{idx:02d}.wav"
                dest.parent.mkdir(parents=True, exist_ok=True)
                tts.write_wav(dest, sr, pcm)
                s.update(tts=f"tts/shot{idx:02d}.wav", tts_st="ok", tts_err="", tts_ver=int(time.time() * 1000),
                         duration=round(len(pcm) / 2 / sr, 2))
                telemetry.log("app", "studio_tts", "视频工坊", "ok", 0,
                              {"shot": s["id"], "seconds": s["duration"], "engine": "local"}, f"视频工坊配音：第 {idx} 镜")
                self._save(p)
        self.job.update(pct=self._span[0] + self._span[1])

    async def _tts_cloud(self, p, targets, v):
        if not tts_cloud.key():
            raise StudioError("还没填百炼 API Key：到 设置 › 云端 填好，或者把音色换成本地的")
        seed = int(v.get("seed") or (int(time.time()) % 65535))
        for k, s in enumerate(targets):
            self._check_stop()
            s["tts_st"] = "run"
            if self.job:
                self.job["shot"] = s["id"]
            self._progress(k / max(1, len(targets)) * 100, f"正在云端配音 {k + 1}/{len(targets)}：第 {p['shots'].index(s) + 1} 镜")
            self._save(p, True)
            text = (s.get("text") or "").strip()
            try:
                r, _asked = await tts_cloud.synth_once_more(text, v["voice"], (s.get("tone") or "")[:100], seed,
                                                            stop=lambda: self._stop.is_set())
            except tts_cloud.Cancelled:
                raise StopRequested() from None
            except tts_cloud.CloudError as e:
                raise StudioError(f"第 {p['shots'].index(s) + 1} 镜没配成：{str(e)[:300]}") from None
            sr, pcm = int(r["sr"]), r["pcm"]
            idx = p["shots"].index(s) + 1
            dest = Path(p["dir"]) / "tts" / f"shot{idx:02d}.wav"
            dest.parent.mkdir(parents=True, exist_ok=True)
            tts.write_wav(dest, sr, pcm)
            dur = len(pcm) / 2 / sr
            try:
                _bill, cny = tts_cloud.record(v["voice"], text, r.get("usage"), "视频工坊", dur)
                p["cost"]["tts_cny"] = round(float(p["cost"].get("tts_cny") or 0) + float(cny), 4)
            except Exception:
                pass
            s.update(tts=f"tts/shot{idx:02d}.wav", tts_st="ok", tts_err="", tts_ver=int(time.time() * 1000), duration=round(dur, 2))
            telemetry.log("app", "studio_tts", "视频工坊", "ok", 0, {"shot": s["id"], "seconds": round(dur, 2), "engine": "cloud"},
                          f"视频工坊云端配音：第 {idx} 镜")
            self._save(p)
        self.job.update(pct=self._span[0] + self._span[1])

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
                "voice": p["settings"].get("voice"), "shots": [{"id": s["id"], "start": s["start"], "end": s["end"],
                                                                 "duration": s["duration"], "text": s.get("text")} for s in shots]}
        (d / "timeline.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        p["files"].update(voice="tts/voice.wav", srt="tts/subtitles.srt", timeline="tts/timeline.json")
        p["total_seconds"] = round(total, 3)
        video_maker.save_project(p)

    # ---------- 配乐 ----------
    async def _gen_bgm(self, p):
        self._step_start(p, "bgm", "准备配乐")
        total = float(p.get("total_seconds") or 0)
        if total <= 0:
            await self._build_voice(p)
            total = float(p.get("total_seconds") or 0)
        seconds = max(10, min(bgm.MAX_S, int(round(total or p.get("target_seconds") or 60))))
        prompt = (p.get("bgm_prompt") or "").strip()
        if not prompt:
            prompt = f"{p.get('style') or '知识科普'}风格短视频背景音乐，纯音乐，无人声，情绪贴合旁白，节奏舒缓"
        self._span = (65, 15)
        # 换模型前先放显存：本地配音服务出完先关掉
        try:
            tts.T.stop("视频工坊：换配乐模型，先释放显存")
        except Exception:
            pass
        self._progress(0, "正在准备配乐（第一次要加载 Stable Audio 3）")
        try:
            r = await bgm.B.generate(prompt, seconds, say=lambda m: self._progress(10, m),
                                     stopped=lambda: self._stop.is_set(),
                                     dest=Path(p["dir"]) / "bgm" / "bgm.wav")
        except bgm.BgmError as e:
            if self._stop.is_set():
                raise StopRequested() from None
            _mark(p, "bgm", "warn", str(e)[:300], 0)
            raise StudioError(str(e)) from None
        p["files"]["bgm"] = f"bgm/{Path(r['path']).name}"
        p["settings"]["use_bgm"] = True
        p["bgm_seconds"] = r.get("duration") or seconds
        _mark(p, "bgm", "ok", f"配乐好了：{p['bgm_seconds']:.0f} 秒", 100)
        self.job.update(stage=2, pct=80)
        self._save(p, True)
        telemetry.log("app", "studio_bgm", "视频工坊", "ok", float(r.get("sec") or 0) * 1000,
                      {"seconds": seconds, "duration": r.get("duration")}, "视频工坊配乐好了")

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
                                        lambda x: self._progress(x.get("pct", 0), x.get("msg", "")))
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
    def to_publish(self, body) -> dict:
        pid = str(body.get("pid") or db.kv_get("studio_active") or "")
        p = video_maker.load_project(pid)
        d = Path(p["dir"])
        rel = (p.get("files") or {}).get("video") or "output/成片.mp4"
        video = d / rel
        if not video.is_file():
            raise HTTPException(400, "还没有成片：先合成视频，再送去发布")
        cover = d / ((p.get("files") or {}).get("cover") or "output/封面.png")
        title = str(body.get("title") or p.get("title") or p.get("name") or "视频工坊成片").strip()[:publish.TITLE_MAX]
        desc = str(body.get("desc") if body.get("desc") is not None else p.get("desc") or "").strip()[:publish.DESC_MAX]
        tags = body.get("tags") if body.get("tags") is not None else p.get("tags") or []
        try:
            item = publish.check_item({"file": str(video), "title": title, "desc": desc, "tags": tags,
                                       "cover": str(cover) if cover.is_file() else "",
                                       "declaration": settings.S.get("pubDecl") or "内容由AI生成"})
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        for x in publish.pending():
            if (x.get("item") or {}).get("file") == str(video):
                return {"ok": True, "pid": x["id"], "msg": "这条已经在「发布」窗口等你确认了", "title": title}
        pub_id = publish.ask(item, None)
        telemetry.log("app", "studio_to_publish", "视频工坊", "ok", 0, {"pid": p["id"], "title": title},
                      "视频工坊：成片已放进发布待确认队列")
        feed.add(f"「{title}」放进发布窗口了：到「发布」看一眼，点两下才发", "warn", job=JOBS)
        return {"ok": True, "pid": pub_id, "msg": "放进发布窗口了：到「发布」看一眼，改一改，点两下才发", "title": title}


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
