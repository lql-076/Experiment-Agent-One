"""v3.7 视频工坊：工程目录、AI 拆解、三合一风格、生图模型、双角色逐句配音、Gemini 策划包、FFmpeg 合成、单步重跑、停下中断。

不连后端、不用显卡、不花钱：图用 ffmpeg 生成纯色，配音和配乐用 Python 写正弦波 WAV。
只在 dev/.run/studio_test 里折腾，跑完留着方便排查。
"""
import asyncio
import json
import math
import struct
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RUN = ROOT / "dev" / ".run" / "studio_test"

from app import imagegen, render_ppt, render_web, settings, studio, studio_assets, studio_cache as cache, video_maker  # noqa: E402

BAD = []


def check(ok, name):
    print(("  [OK] " if ok else "  [FAIL] ") + name, flush=True)
    if not ok:
        BAD.append(name)


def ffmpeg():
    try:
        return video_maker.ffmpeg_exe()
    except Exception as e:
        print("没有 ffmpeg，跳过合成测试：", e)
        return ""


def wav(path, seconds, freq=440, sr=24000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(sr * seconds)
    pcm = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / sr))) for i in range(n))
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(pcm)


def png(ff, path, color, w=1080, h=1920):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}",
                    "-frames:v", "1", str(path)], check=True)


def srt(path, cues):
    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for i, (a, b, text) in enumerate(cues, 1):
        def t(x):
            ms = int(round(x * 1000))
            return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        out.append(f"{i}\n{t(a)} --> {t(b)}\n{text}\n")
    path.write_text("\n".join(out), "utf-8")


def test_parse():
    print("\nAI 拆解：结构化解析")
    txt = """```json
    {"title":"三个被低估的 AI 用法","desc":"普通人马上能用","tags":["#AI","效率工具"],
     "bgm_prompt":"upbeat electronic, no vocals",
     "shots":[{"text":"第一句","tone":"轻松","image_prompt":"书桌前的年轻人","seconds_hint":5},
              {"text":"第二句","tone":"平静","image_prompt":"屏幕上的图表","seconds_hint":6}]}
    ```"""
    j = studio.parse_plan(txt)
    check(j["title"] == "三个被低估的 AI 用法", "标题")
    check(j["tags"] == ["AI", "效率工具"], "话题去掉 #")
    check(len(j["shots"]) == 2 and j["shots"][0]["text"] == "第一句", "分镜和台词")
    check(j["shots"][0]["seconds_hint"] == 5.0, "每镜时长")
    check(bool(j["bgm_prompt"]), "配乐英文提示词")
    bad = False
    try:
        studio.parse_plan('{"title":"x","shots":[]}')
    except studio.StudioError:
        bad = True
    check(bad, "空分镜会被拦下")


def test_project():
    print("\n工程目录：project.json 和四个子文件夹")
    p = video_maker.new_project("目录测试", "9:16", "知识科普", 30, topic="目录测试")
    d = Path(p["dir"])
    check((d / "project.json").is_file(), "project.json 写出来了")
    check(all((d / x).is_dir() for x in ("images", "tts", "bgm", "output")), "images / tts / bgm / output")
    check(video_maker.load_project(p["id"])["ratio"] == "9:16", "读回来还是 9:16")
    ps = video_maker.list_projects()
    check(any(x["id"] == p["id"] for x in ps), "项目列表里能找到")
    return p["id"]


def test_plan_project():
    print("\nAI 拆解 → 新项目：分镜、标题、话题、配乐描述都落进 project.json")
    async def fake(topic, text, ratio, seconds):
        return {"title": "拆解测试标题", "desc": "简介", "tags": ["AI", "测试"],
                "bgm_prompt": "calm piano, no vocals",
                "shots": [{"text": "第一镜", "role": "白页", "tone": "冷静吐槽", "image_prompt": "画面一", "seconds_hint": 5},
                          {"text": "第二镜", "role": "紫苏", "tone": "夸张惊呼", "image_prompt": "画面二", "seconds_hint": 6}]}, 0.001
    old = studio._ask_plan
    studio._ask_plan = fake
    try:
        st = asyncio.run(studio.S.plan({"topic": "拆解测试", "ratio": "9:16", "style": "知识科普", "seconds": 30,
                                        "voice_id": "local:preset:Vivian"}))
        p = st["project"]
        check(p["title"] == "拆解测试标题", "标题")
        check([x["text"] for x in p["shots"]] == ["第一镜", "第二镜"], "分镜台词")
        check(p["steps"]["plan"]["st"] == "ok", "plan 这一步标成好了")
        check(p["settings"]["voice"]["speaker"] == "Vivian", "音色配置")
        check(p["bgm_prompt"] == "calm piano, no vocals", "配乐描述")
        check(p["style"] == studio.STYLE_TAG, "固定三合一风格")
        check([x["role"] for x in p["shots"]] == ["白页", "紫苏"], "白页/紫苏双角色")
        check(p["shots"][0]["speaker"] and p["shots"][1]["speaker"], "每句都有音色")
    finally:
        studio._ask_plan = old


def test_style_models():
    print("\n固定三合一风格 + 生图模型透传")
    check(studio.STYLE_TAG == "知识科普 × 科技数码 × 搞笑段子", "三合一固定标签")
    S = studio.Studio()
    st = S.new_project({"topic": "模型测试", "ratio": "9:16", "seconds": 75, "voice_id": "local:preset:Vivian",
                        "img_model": "gpt-image-2.5-sunburst-vip"})
    p = st["project"]
    check(p["style"] == studio.STYLE_TAG, "新项目用固定风格")
    check(p["img_model"] == "gpt-image-2.5-sunburst-vip", "生图模型进 project.json")
    check(len(studio.image_models()) >= 5, "能列出可用生图模型")
    q = S.update({"pid": p["id"], "settings": {"img_model": "gemini-3.1-flash-image"}})
    check(q["img_model"] == "gemini-3.1-flash-image" and q["steps"]["images"]["st"] == "stale", "换模型 → 图要重出")


def test_dual_role_voice():
    print("\n白页/紫苏双角色逐句配音：按句拼接时间轴")
    p = make_project("双角色配音", shots=2, image_count=2, seconds=1.0)
    d = Path(p["dir"])
    wav(d / "tts" / "shot01.wav", 1.0, 440)
    wav(d / "tts" / "shot02.wav", 1.0, 550)
    for i, s in enumerate(p["shots"]):
        s["tts"] = f"tts/shot{i + 1:02d}.wav"; s["tts_st"] = "ok"
    p["files"].pop("voice", None); p["files"].pop("srt", None)
    video_maker.save_project(p)
    S = studio.Studio()
    asyncio.run(S._build_voice(video_maker.load_project(p["id"])))
    q = video_maker.load_project(p["id"])
    meta = json.loads((d / "tts" / "timeline.json").read_text("utf-8"))
    check((d / "tts" / "voice.wav").is_file(), "拼出 voice.wav")
    check([x["role"] for x in meta["shots"]] == ["白页", "紫苏"], "时间轴保留双角色")
    check([x["speaker"] for x in meta["shots"]] == ["local:preset:Vivian", "local:preset:Serena"], "时间轴保留逐句音色")
    check(abs(meta["total_seconds"] - 2.25) < 0.2, "两段 + 停顿的总长")


def test_gemini_pack():
    print("\nGemini 策划包：固定风格、时长、钩子、双角色、严格格式")
    s = studio.prompt_pack({"topic": "AI 手机", "title": "测试"})
    check(studio.STYLE_TAG in s, "包含三合一风格")
    check("65~85" in s and "2 秒" in s, "包含时长和 2 秒钩子")
    check("白页" in s and "紫苏" in s and "百炼" in s, "包含双角色和百炼语气")
    check("下期暗号" in s, "包含结尾互动暗号")
    check('"role"' in s and '"tone"' in s and '"image_prompt"' in s and '"bgm_prompt"' in s, "包含严格 JSON 字段")
    check("[笑]" in s and "不要写" in s, "提醒台词里不要写音效词")


def test_import_script():
    print("\nGemini 剧本导入：JSON 和 Markdown 都能回填")
    js = '```json\n{"title":"JSON 剧本","tags":["AI"],"shots":[{"role":"白页","tone":"冷静","text":"甲","image_prompt":"图一"},{"role":"紫苏","tone":"夸张","text":"乙","image_prompt":"图二"}]}\n```'
    j = studio.parse_script(js)
    check(j["title"] == "JSON 剧本" and [x["role"] for x in j["shots"]] == ["白页", "紫苏"], "JSON 剧本")
    md = """# Markdown 剧本
简介：一句话
话题：科技 搞笑
配乐提示词：calm piano, no vocals

## 分镜 1
角色：白页
语气：冷静吐槽
台词：第一句。
画面提示词：画面一

## 分镜 2
角色：紫苏
语气：夸张惊呼
台词：第二句。
画面提示词：画面二
"""
    m = studio.parse_script(md)
    check(m["title"] == "Markdown 剧本" and m["tags"] == ["科技", "搞笑"], "Markdown 标题和话题")
    check([x["text"] for x in m["shots"]] == ["第一句。", "第二句。"], "Markdown 台词")
    S = studio.Studio()
    st = S.new_project({"topic": "导入测试", "voice_id": "local:preset:Vivian"})
    pid = st["project"]["id"]
    st = S.import_script({"pid": pid, "text": md})
    p = st["project"]
    check(p["title"] == "Markdown 剧本" and len(p["shots"]) == 2, "导入落到项目")
    check([x["role"] for x in p["shots"]] == ["白页", "紫苏"], "导入保留角色")
    check(p["steps"]["plan"]["st"] == "ok", "导入后 plan 节点完成")


def make_project(name, shots=2, image_count=1, seconds=3.0, ratio="9:16"):
    p = video_maker.new_project(name, ratio, "知识科普", 30, topic=name)
    p["shots"] = []
    for i in range(shots):
        role = "白页" if i % 2 == 0 else "紫苏"
        p["shots"].append({"id": f"s{i + 1}", "text": f"第 {i + 1} 段测试口播。", "role": role,
                           "speaker": "local:preset:Vivian" if role == "白页" else "local:preset:Serena",
                           "tone": "冷静吐槽" if role == "白页" else "夸张惊呼",
                           "image_prompt": f"第 {i + 1} 个画面", "seconds_hint": seconds, "image_st": "idle", "tts_st": "idle"})
    d = Path(p["dir"])
    ff = ffmpeg()
    if ff:
        for i in range(image_count):
            png(ff, d / "images" / f"shot{i + 1:02d}.png", ["0x1e3a8a", "0xb45309", "0x166534"][i % 3])
    for i in range(image_count):
        p["shots"][min(i, shots - 1)]["image"] = f"images/shot{i + 1:02d}.png"
    for i, s in enumerate(p["shots"]):
        if s.get("image"):
            s["image_st"] = "ok"
    # 配音：每段 seconds 秒 + 分镜之间 0.25 秒
    total = shots * seconds + (shots - 1) * video_maker.GAP
    wav(d / "tts" / "voice.wav", total, 440)
    srt(d / "tts" / "subtitles.srt", [(i * (seconds + video_maker.GAP), i * (seconds + video_maker.GAP) + seconds,
                                       f"第 {i + 1} 段字幕") for i in range(shots)])
    wav(d / "bgm" / "bgm.wav", max(4, total + 2), 220, 48000)
    p["files"].update(voice="tts/voice.wav", srt="tts/subtitles.srt", bgm="bgm/bgm.wav")
    for i, s in enumerate(p["shots"]):
        a = i * (seconds + video_maker.GAP)
        end = a + seconds + (video_maker.GAP if i < shots - 1 else 0)
        s["start"], s["end"], s["duration"] = round(a, 3), round(end, 3), seconds
        s["tts"] = "tts/voice.wav"
        s["tts_st"] = "ok"
    video_maker.save_project(p)
    return p


def test_compose():
    ff = ffmpeg()
    if not ff:
        return
    print("\nFFmpeg 合成：竖屏 1080×1920、音轨、字幕、配乐，图片比配音少也能铺满")
    p = make_project("合成测试", shots=2, image_count=1, seconds=1.5)
    r = video_maker.compose_video(p["dir"], srt=True, bgm_volume=0.18, progress=lambda x: None)
    out = Path(r["path"])
    check(out.is_file() and out.stat().st_size > 20000, "成片文件出来了")
    check(r["w"] == 1080 and r["h"] == 1920, "分辨率 1080×1920")
    check(abs((r["duration"] or 0) - 3.25) < 0.25, "时长跟配音对得上（约 3.25 秒）")
    q = subprocess.run([ff, "-hide_banner", "-i", str(out)], capture_output=True, text=True, errors="replace")
    blob = q.stderr
    check("Audio: aac" in blob or "Audio: " in blob, "有音轨")
    check("Video: h264" in blob, "有视频流")
    check((Path(p["dir"]) / (r.get("cover_rel") or "output/封面.png")).is_file(), "封面抽出来了")
    # 16:9 也走一遍（只换画幅，不要求字幕位置像素级）
    p2 = make_project("横屏测试", shots=2, image_count=2, seconds=1.0, ratio="16:9")
    r2 = video_maker.compose_video(p2["dir"], srt=True, bgm_volume=0.18, progress=lambda x: None)
    check((r2["w"], r2["h"]) == (1920, 1080), "横屏 1920×1080")


def test_single_step():
    print("\n单步重跑：只重新合成视频，不动图、不动配音")
    p = make_project("单步测试", shots=2, image_count=2, seconds=1.0)
    calls = []
    old = video_maker.compose_video

    def fake(d, srt=True, bgm_volume=0.18, kenburns=True, stopped=None, progress=None, **kw):
        calls.append(str(d))
        out = Path(d) / "output" / "成片.mp4"
        out.write_bytes(b"fake" * 1000)
        if progress:
            progress({"stage": "compose", "pct": 50, "msg": "假装合成中"})
        return {"stopped": False, "path": str(out), "rel": "output/成片.mp4", "cover": "", "cover_rel": "",
                "duration": 2.0, "w": 1080, "h": 1920, "sec": 0.01, "bytes": 4000}

    video_maker.compose_video = fake
    try:
        S = studio.Studio()
        S.job = {"id": 1, "st": "run", "pid": p["id"], "stage": 3, "msg": "", "pct": 0, "step": "video", "t0": time.time(), "t1": 0}
        S._span = (80, 20)
        asyncio.run(S._one(video_maker.load_project(p["id"]), "video", None))
        check(calls == [p["dir"]], "只调了一次合成")
        q = video_maker.load_project(p["id"])
        check(q["steps"]["video"]["st"] == "ok", "video 这一步标成好了")
        check(q["steps"]["images"]["st"] == "idle", "图这一步没被重跑")
        check(q["steps"]["tts"]["st"] == "idle", "配音这一步没被重跑")
        check(all(k in q["steps"] for k in ("plan", "images", "tts", "bgm", "video")), "五个节点步骤状态都在")
    finally:
        video_maker.compose_video = old
    # 改台词只让配音和视频过期；改画面提示词只让图和视频过期
    S = studio.Studio()
    body = {"pid": p["id"], "shots": [{"id": "s1", "text": "改过的台词", "tone": "平静", "image_prompt": "第 1 个画面"}]}
    S.update(body)
    q = video_maker.load_project(p["id"])
    check(q["steps"]["tts"]["st"] == "stale" and q["steps"]["video"]["st"] == "stale", "改台词 → 配音和视频要重做")
    S.update({"pid": p["id"], "shots": [{"id": "s1", "text": "改过的台词", "tone": "平静", "image_prompt": "改过的画面"}]})
    q = video_maker.load_project(p["id"])
    check(q["steps"]["images"]["st"] == "stale", "改画面 → 图要重做")


def test_stop():
    ff = ffmpeg()
    if not ff:
        return
    print("\n停下：安全结束自己开的 ffmpeg，不留下半截成片")
    p = make_project("停下测试", shots=6, image_count=2, seconds=2.0)
    ev = threading.Event()
    timer = threading.Timer(0.6, ev.set)
    timer.start()
    t0 = time.time()
    r = video_maker.compose_video(p["dir"], srt=True, bgm_volume=0.18, stopped=ev.is_set, progress=lambda x: None)
    timer.cancel()
    check(r.get("stopped") is True, "返回 stopped")
    check(not (Path(p["dir"]) / "output" / "成片.mp4").exists(), "没有留下半截成片")
    check(time.time() - t0 < 20, "很快就停下来了")


def test_image_params():
    print("\n生图全参数：n / 自定义尺寸 / 透明度 / GIF 帧 / 复杂度 / 参考图透传")
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lzq4WQAAAABJRU5ErkJggg==")
    seen = {}

    async def fake_post(c, url, k, **kw):
        seen["url"], seen["json"] = url, kw.get("json") or {}
        return {"data": [{"b64_json": base64.b64encode(png).decode()}, {"b64_json": base64.b64encode(png).decode()}]}

    old = imagegen._post
    imagegen._post = fake_post
    try:
        cd = imagegen.card("gpt-image-2.6-sunburst")
        imgs, _, _ = asyncio.run(imagegen.call_images(None, "http://x", "sk-x", cd, "p", "9:16", "2k", "high", True, [],
                                                      n=2, custom_w=720, custom_h=1280, complexity="high",
                                                      gif_frames=8, gif_delay_ms=150, output_type="gif", output_format="gif"))
    finally:
        imagegen._post = old
    f = seen.get("json") or {}
    check(len(imgs) == 2, "一次回 2 张")
    check(f.get("size") == "720x1280", "自定义宽高透传")
    check(f.get("n") == 2, "n 数量")
    check(f.get("output_format") == "gif" and f.get("gif_frames") == 8 and f.get("gif_delay_ms") == 150, "GIF 帧参数")
    check(f.get("complexity") == "high", "规划复杂度")
    check(f.get("quality") == "high", "质量档透传")
    check(imagegen.validate_size(512, 512) != "", "512×512 被总像素规则拦下")
    check(imagegen.validate_size(1024, 1024) == "", "1024×1024 合法")
    check(imagegen.validate_size(1024, 600) != "", "非 16 倍数被拦下")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="48"><rect width="64" height="48"/></svg>'
    check(imagegen.png_info(svg)["fmt"] == "svg" and imagegen.png_info(svg)["w"] == 64, "SVG 文件头识别")


def test_default_nodes():
    print("\n空项目默认节点 / 手动增删")
    S = studio.Studio()
    st = S.new_project({"topic": "空项目", "voice_id": "local:preset:Vivian"})
    p = st["project"]
    check(len(p["shots"]) == 1 and p.get("placeholder"), "空项目自带 1 个可测分镜/台词节点")
    check(p["shots"][0]["text"] and p["shots"][0]["image_prompt"], "默认节点有台词和画面提示词")
    q = S.add_shot({"pid": p["id"]})
    check(len(q["shots"]) == 2, "手动加一个节点")
    q = S.del_shot({"pid": p["id"], "id": q["shots"][-1]["id"]})
    check(len(q["shots"]) == 1, "手动删掉一个节点")
    q = S.del_shot({"pid": p["id"], "id": q["shots"][-1]["id"]})
    check(len(q["shots"]) == 0, "删掉最后一个节点")
    q = S.add_shot({"pid": p["id"]})
    check(len(q["shots"]) == 1, "删空后还能再加")
    bad = False
    try:
        S.update({"pid": p["id"], "shots": [{"id": q["shots"][0]["id"], "img_resolution": "custom", "img_custom_w": 512, "img_custom_h": 512}]})
    except Exception:
        bad = True
    check(bad, "后端拦下 512×512 自定义尺寸")


def test_cache_scheduler():
    print("\n内容寻址缓存 + 三路并发调度")
    p = video_maker.new_project("缓存调度测试", "9:16", studio.STYLE_TAG, 20, topic="缓存")
    p["shots"] = [
        {"id": "s1", "text": "缓存第一句。", "role": "白页", "speaker": "local:preset:Vivian", "tone": "冷静吐槽",
         "image_prompt": "图一", "seconds_hint": 3, "image_st": "idle", "tts_st": "idle"},
        {"id": "s2", "text": "缓存第二句。", "role": "紫苏", "speaker": "local:preset:Serena", "tone": "夸张惊呼",
         "image_prompt": "图二", "seconds_hint": 3, "image_st": "idle", "tts_st": "idle"}]
    p["settings"]["bgm_volume"] = .18
    video_maker.save_project(p)
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lzq4WQAAAABJRU5ErkJggg==")
    calls = []

    async def fake_images(c, base, k, cd, prompt, ratio, tier, quality, transparent, refs, **kw):
        calls.append(prompt)
        return [png], {}, {}

    old = imagegen.call_images
    old_get = settings.get_secret
    imagegen.call_images = fake_images
    settings.get_secret = lambda k: "sk-test-0000" if k == "imgKey" else old_get(k)
    try:
        S = studio.Studio()
        asyncio.run(S._gen_images(video_maker.load_project(p["id"])))
        q = video_maker.load_project(p["id"])
        check(len(calls) == 2, "第一遍两镜都请求 API")
        check(all(s.get("image_st") == "ok" for s in q["shots"]), "两镜都出图")
        for s in q["shots"]:
            s["image_st"] = "stale"
        video_maker.save_project(q)
        asyncio.run(S._gen_images(video_maker.load_project(p["id"])))
        q = video_maker.load_project(p["id"])
        check(len(calls) == 2, "第二遍没有重复请求付费 API")
        check(all(s.get("image_cache_hit") for s in q["shots"]), "两镜都标缓存命中")
        for i, s in enumerate(q["shots"]):
            wav(Path(q["dir"]) / "tts" / f"shot{i + 1:02d}.wav", 1.0, 440 + i * 50)
            cfg = studio._shot_voice(q, s)
            fp = studio._tts_fp(q, s, cfg)
            cache.put(fp, Path(q["dir"]) / "tts" / f"shot{i + 1:02d}.wav", "tts", {"test": True})
        for s in q["shots"]:
            s["tts_st"] = "stale"
        video_maker.save_project(q)
        asyncio.run(studio.Studio()._gen_tts(video_maker.load_project(p["id"])))
        q = video_maker.load_project(p["id"])
        check((Path(q["dir"]) / "tts" / "voice.wav").is_file(), "配音缓存拼出 voice.wav")
        check(all(s.get("tts_cache_hit") for s in q["shots"]), "逐句配音都缓存命中")
        events = []

        async def gi(_p):
            events.append(("img_start", time.time())); await asyncio.sleep(.12); events.append(("img_end", time.time()))

        async def gt(_p):
            events.append(("tts_start", time.time())); await asyncio.sleep(.12); events.append(("tts_end", time.time()))

        async def gb(_p):
            events.append(("bgm_start", time.time())); await asyncio.sleep(.12); events.append(("bgm_end", time.time()))

        async def rt(_p):
            events.append(("render", time.time()))

        async def cp(_p):
            events.append(("compose", time.time()))

        S2 = studio.Studio()
        S2.job = {"st": "run", "pid": q["id"], "t0": time.time(), "t1": 0, "msg": "", "pct": 0, "stage": 2, "step": "images"}
        for attr, fn in (("_gen_images", gi), ("_gen_tts", gt), ("_gen_bgm", gb), ("_render_tracks", rt), ("_compose", cp)):
            setattr(S2, attr, fn)
        q["files"]["voice"] = "tts/voice.wav"
        video_maker.save_project(q)
        asyncio.run(S2._all(video_maker.load_project(p["id"])))
        starts = [t for k, t in events if k.endswith("_start")]
        ends = [t for k, t in events if k.endswith("_end")]
        check(len(starts) == 3 and max(starts) - min(starts) < .08, "API / 本地配音 / 配乐同时启动")
        check(all(t > max(ends) for k, t in events if k in ("render", "compose")), "汇聚屏障后才进入渲染和合成")
    finally:
        imagegen.call_images = old
        settings.get_secret = old_get


def test_render_tracks():
    print("\n网页动效轨道 + PPT 轨道 + FFmpeg 终混")
    try:
        import playwright  # noqa: F401
        import pptx  # noqa: F401
    except Exception as e:
        print("  跳过：没装 Playwright / python-pptx：", e)
        return
    p = make_project("双轨渲染测试", shots=2, image_count=2, seconds=1.5)
    p["settings"].update({"web_bg": "tech", "web_sub_size": 44, "web_gif_scale": 1.0})
    p["shots"][0]["render"] = "web"
    p["shots"][1]["render"] = "ppt"
    video_maker.save_project(p)
    d = Path(p["dir"])
    render_web.render_all(d, p, say=lambda _m: None)
    render_ppt.render_all(d, p, say=lambda _m: None)
    check((d / "render" / "web_s1.mp4").is_file(), "网页动效轨出来了")
    check((d / "render" / "ppt_s2.png").is_file(), "PPT 卡片图出来了")
    check((d / "output" / "卡片.pptx").is_file(), "自动生成 .pptx")
    check(p["shots"][0].get("render_cache_hit") is False and p["shots"][1].get("render_cache_hit") is False, "第一次网页/PPT 不是缓存")
    render_web.render_all(d, p, say=lambda _m: None)
    render_ppt.render_all(d, p, say=lambda _m: None)
    check(p["shots"][0].get("render_cache_hit") is True and p["shots"][1].get("render_cache_hit") is True, "第二次网页/PPT 轨道缓存命中")
    video_maker.save_project(p)
    r = video_maker.compose_video(d, srt=True, bgm_volume=.18, progress=lambda _x: None)
    check(Path(r["path"]).is_file() and r["duration"] > 2, "双轨 + 配音 + 字幕合成成片")


def test_publish_matrix():
    print("\n发布清单：单条送审 / 批量入队 / 定时 / 声明")
    p = make_project("发布矩阵测试", shots=2, image_count=2, seconds=1.0)
    d = Path(p["dir"])
    (d / "output").mkdir(exist_ok=True)
    (d / "output" / "成片.mp4").write_bytes(b"x" * 2000)
    p["files"]["video"] = "output/成片.mp4"
    video_maker.save_project(p)
    S = studio.Studio()
    old_check, old_pending, old_ask = studio.publish.check_item, studio.publish.pending, studio.publish.ask
    got = {}
    studio.publish.check_item = lambda body, agent=False: dict(body, file=body["file"], name="成片.mp4", cover_kind="portrait")
    studio.publish.pending = lambda: []
    studio.publish.ask = lambda item, eid=None: got.update(item) or 123
    try:
        r = S.to_publish({"pid": p["id"], "mode": "single", "title": "测试标题", "tags": ["ai漫剧", "搞笑"],
                          "declaration": "内容由AI生成"})
        check(r.get("ok") and got.get("title") == "测试标题", "单条送审进 pending")
        check(got.get("tags") == ["ai漫剧", "搞笑"], "话题完整")
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + 3 * 3600))
        r = S.to_publish({"pid": p["id"], "mode": "batch", "title": "批量标题", "schedule": when,
                          "tags": ["ai创作浪潮计划"], "declaration": "内容由AI生成"})
        check(r.get("ok") and r.get("mode") == "batch", "加入批量发布清单")
    finally:
        studio.publish.check_item, studio.publish.pending, studio.publish.ask = old_check, old_pending, old_ask
        from app import db
        db.kv_set("pub_batch", None)


def tiny_gif(path, frames=3, delay_cs=7):
    """手写一个能过 GIF 结构解析的多帧 GIF：测帧数和总时长。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    head = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
    gce = b"\x21\xf9\x04\x01" + struct.pack("<H", delay_cs) + b"\x00\x00"
    img = b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00"
    path.write_bytes(head + (gce + img) * frames + b"\x3b")


def test_assets():
    print("\n灯箱取图：只给工坊里的图片，越界 / 符号链接 / 假图片都拦下")
    p = video_maker.new_project("灯箱测试", "9:16", studio.STYLE_TAG, 20, topic="灯箱")
    d = Path(p["dir"])
    png = __import__("base64").b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lzq4WQAAAABJRU5ErkJggg==")
    (d / "images").mkdir(parents=True, exist_ok=True)
    (d / "images" / "a.png").write_bytes(png)
    tiny_gif(d / "images" / "loop.gif", 4, 9)
    (d / "images" / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="48"><rect width="64" height="48"/></svg>', "utf-8")
    (d / "images" / "notes.txt").write_text("not an image", "utf-8")
    (d / "images" / "fake.png").write_text("not a png at all", "utf-8")
    j = studio_assets.info(d / "images" / "a.png")
    check(j["fmt"] == "png" and j["w"] == 1 and j["h"] == 1 and j["size"] > 0, "PNG 真实分辨率和大小")
    g = studio_assets.info(d / "images" / "loop.gif")
    check(g["fmt"] == "gif" and g["frames"] == 4 and g["duration_ms"] == 360, "GIF 帧数和时长（4 帧 × 90ms）")
    s = studio_assets.info(d / "images" / "icon.svg")
    check(s["fmt"] == "svg" and s["w"] == 64 and s["h"] == 48, "SVG 尺寸")
    for bad, why in (("../project.json", ".. 越界"), (str(d / "images" / "a.png"), "绝对路径"),
                     ("images/notes.txt", "非图片扩展名"), ("images/fake.png", "假 PNG 文件头"),
                     ("images/missing.png", "文件不存在")):
        ok = False
        try:
            studio_assets.project_asset(p["id"], bad)
        except studio_assets.AssetError:
            ok = True
        check(ok, "拦下：" + why)
    # 符号链接指到工坊外面（Windows 没权限建就跳过）
    outside = RUN / "outside-secret.png"
    outside.write_bytes(png)
    link = d / "images" / "link.png"
    try:
        link.symlink_to(outside)
        ok = False
        try:
            studio_assets.project_asset(p["id"], "images/link.png")
        except studio_assets.AssetError:
            ok = True
        check(ok, "拦下：符号链接越界")
    except (OSError, NotImplementedError):
        print("  跳过：这个环境不能建符号链接")
    # 缓存目录只给 _cache 里的图片
    croot = studio_assets.cache_root()
    (croot / "image" / "aa").mkdir(parents=True, exist_ok=True)
    (croot / "image" / "aa" / "x.png").write_bytes(png)
    check(studio_assets.cache_asset("image/aa/x.png").is_file(), "缓存图片能读")
    ok = False
    try:
        studio_assets.cache_asset("../灯箱测试/images/a.png")
    except studio_assets.AssetError:
        ok = True
    check(ok, "拦下：从 _cache 越界到项目")


def test_graph_model():
    print("\n自由节点图：默认 9 个节点、固定节点、端口类型、环检测、断线")
    S = studio.Studio()
    st = S.new_project({"topic": "图模型", "voice_id": "local:preset:Vivian"})
    p = video_maker.load_project(st["project"]["id"])
    g = p["graph"]
    check(len(g["nodes"]) == 9 and not g["edges"], "默认 9 个节点、0 条连线")
    check([n["type"] for n in g["nodes"]].count("script") == 1 and [n["type"] for n in g["nodes"]].count("mux") == 1
          and [n["type"] for n in g["nodes"]].count("publish") == 1, "script / mux / publish 各 1 个")
    check(sum(1 for n in g["nodes"] if n["type"] == "voice") == 2, "默认两个配音角色节点")
    check(any(n["id"] == "voice-1" and "Serena" in n["params"]["speaker"] for n in g["nodes"]), "白页默认女声 Serena")
    check(any(n["id"] == "voice-2" and "Dylan" in n["params"]["speaker"] for n in g["nodes"]), "紫苏默认男声 Dylan")
    a = S.graph_add({"pid": p["id"], "type": "image"})
    nid = a["node"]["id"]
    check(a["node"]["type"] == "image" and nid.startswith("image-"), "能加生图节点")
    ok = False
    try:
        S.graph_add({"pid": p["id"], "type": "script"})
    except Exception:
        ok = True
    check(ok, "固定节点不能再加")
    ok = False
    try:
        S.graph_delete({"pid": p["id"], "id": "script"})
    except Exception:
        ok = True
    check(ok, "固定节点不能删")
    S.graph_delete({"pid": p["id"], "id": nid})
    check(len(S._load(p["id"])["graph"]["nodes"]) == 9, "普通节点能删")
    # 类型不兼容
    ok = False
    try:
        S.graph_connect({"pid": p["id"], "from": "mux.video", "to": "image-1.prompt"})
    except Exception:
        ok = True
    check(ok, "视频口接文字口被拦下")
    b = S.graph_add({"pid": p["id"], "type": "image"})["node"]["id"]
    S.graph_connect({"pid": p["id"], "from": "image-1.image", "to": b + ".ref"})
    ok = False
    try:
        S.graph_connect({"pid": p["id"], "from": b + ".image", "to": "image-1.ref"})
    except Exception:
        ok = True
    check(ok, "会形成环的连线被拦下")
    q = S._load(p["id"])["graph"]
    e = [x for x in q["edges"] if x["to"] == b + ".ref"][0]
    S.graph_disconnect({"pid": p["id"], "edge": e["id"]})
    check(not S._load(p["id"])["graph"]["edges"], "点连线能断开")


def test_graph_topo_parallel():
    print("\nDAG 调度：无依赖并行、有依赖按拓扑、发布节点不自动跑")
    S = studio.Studio()
    st = S.new_project({"topic": "拓扑", "voice_id": "local:preset:Vivian"})
    pid = st["project"]["id"]
    p = S._load(pid)
    for a, b in (("script.text", "image-1.prompt"), ("script.text", "voice-1.text"),
                 ("image-1.image", "mux.image"), ("voice-1.audio", "mux.audio"), ("mux.video", "publish.video")):
        S.graph_connect({"pid": pid, "from": a, "to": b})
    p = S._load(pid)
    order = studio.graph.topo_order(p["graph"])
    check(order.index("script") < order.index("image-1") < order.index("mux") < order.index("publish"), "拓扑顺序对")
    events = []

    async def fake_exec(self, pp, n):
        events.append((n["id"], "start", time.time()))
        await asyncio.sleep(.12)
        rel = f"fake/{n['id']}.bin"
        q = Path(pp["dir"]) / rel
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(b"fake")
        events.append((n["id"], "end", time.time()))
        return [studio._out(pp, rel, "image")]

    old = studio.Studio._graph_exec
    studio.Studio._graph_exec = fake_exec
    try:
        async def go():
            await S.graph_run({"pid": pid})
            t = S._task
            if t:
                await t
        asyncio.run(go())
    finally:
        studio.Studio._graph_exec = old
    starts = {k: t for k, what, t in events if what == "start"}
    ends = {k: t for k, what, t in events if what == "end"}
    check("image-1" in starts and "voice-1" in starts and abs(starts["image-1"] - starts["voice-1"]) < .08,
          "两条独立分支同时开跑")
    check(starts["mux"] > max(ends["image-1"], ends["voice-1"]) - .02, "汇聚节点等上游都完成")
    check("publish" not in starts, "发布节点全流程里不自动跑")
    check(S.job["st"] == "done", "全流程跑完")


def test_graph_cache_scope():
    print("\n节点缓存：改了谁只失效谁和下游；同参数第二次直接命中")
    S = studio.Studio()
    st = S.new_project({"topic": "缓存范围", "voice_id": "local:preset:Vivian"})
    pid = st["project"]["id"]
    p = S._load(pid)
    g = p["graph"]
    for n in g["nodes"]:
        if n["id"] in ("image-1", "voice-1", "bgm-1", "mux"):
            n["status"] = "ok"
            n["cache_key"] = "old"
    # 先给上游做一个产出，才能连出「下游」
    d = Path(p["dir"])
    (d / "images" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
    for n in g["nodes"]:
        if n["id"] == "image-1":
            n["outputs"] = [{"key": "images/a.png", "rel": "images/a.png", "kind": "image", "sha256": "abc", "size": 20}]
    video_maker.save_project(p)
    S.graph_connect({"pid": pid, "from": "image-1.image", "to": "mux.image"})
    S.graph_update({"pid": pid, "id": "image-1", "params": {"prompt": "改过的画面"}})
    q = S._load(pid)["graph"]
    by = {n["id"]: n for n in q["nodes"]}
    check(by["image-1"]["status"] == "stale" and by["mux"]["status"] == "stale", "改生图节点 → 它和 mux 失效")
    check(by["voice-1"]["status"] == "ok" and by["bgm-1"]["status"] == "ok", "平行分支不受影响")
    check(by["image-1"]["cache_key"] == "" and by["mux"]["cache_key"] == "", "下游缓存键清空")
    # 第二次同参数运行命中，不调执行器
    calls = []

    async def fake_exec(self, pp, n):
        calls.append(n["id"])
        rel = f"images/{n['id']}.png"
        (Path(pp["dir"]) / rel).parent.mkdir(parents=True, exist_ok=True)
        (Path(pp["dir"]) / rel).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
        return [studio._out(pp, rel, "image")]

    old = studio.Studio._graph_exec
    studio.Studio._graph_exec = fake_exec
    try:
        asyncio.run(S._graph_one(S._load(pid), "image-1"))
        check(calls == ["image-1"], "第一次真的执行")
        asyncio.run(S._graph_one(S._load(pid), "image-1"))
        check(calls == ["image-1"], "第二次同参数直接命中，没有再执行")
        # 上游产出换了哈希，下游缓存键要变
        p2 = S._load(pid)
        q = p2["graph"]
        by = {n["id"]: n for n in q["nodes"]}
        key_before = studio.graph.cache_key(by["mux"], q)
        by["image-1"]["outputs"][0]["sha256"] = "changed"
        key_after = studio.graph.cache_key(by["mux"], q)
        check(key_before != key_after, "上游内容哈希变了，下游缓存键跟着变")
    finally:
        studio.Studio._graph_exec = old


def test_graph_missing_upstream():
    print("\n单节点运行：上游没产出就报「缺上游产出」，不偷偷跑上游")
    S = studio.Studio()
    st = S.new_project({"topic": "缺上游", "voice_id": "local:preset:Vivian"})
    pid = st["project"]["id"]
    S.graph_connect({"pid": pid, "from": "image-1.image", "to": "mux.image"})
    p = S._load(pid)
    ok = False
    try:
        asyncio.run(S._graph_one(p, "mux"))
    except studio.StudioError as e:
        ok = "缺上游产出" in str(e)
    check(ok, "mux 缺图时报缺上游产出")
    check(S._load(pid)["graph"]["nodes"][1]["status"] != "ok", "上游没有被偷偷跑过")


def test_migration():
    print("\n旧工程自动迁移：一图一节点、一句一配音，产出和缓存保留，.bak 备份，幂等")
    p = make_project("迁移测试", shots=2, image_count=2, seconds=1.0)
    d = Path(p["dir"])
    # 造一点旧缓存指纹，迁移后应保留
    p["shots"][0]["img_fps"] = ["fp0"]
    p["shots"][0]["image_cache_hit"] = True
    p["shots"][1]["tts_engine"] = "cloud"
    p["shots"][1]["tts_cache_hit"] = True
    p.pop("graph", None)
    video_maker.save_project(p)
    S = studio.Studio()
    q = S._load(p["id"])
    g = q["graph"]
    check((d / "project.json.bak").is_file(), "迁移前留了 project.json.bak")
    check(sum(1 for n in g["nodes"] if n["type"] == "image") == 2, "两张分镜图 → 两个生图节点")
    check(sum(1 for n in g["nodes"] if n["type"] == "voice") == 2, "两句台词 → 两个配音节点")
    by = {n["id"]: n for n in g["nodes"]}
    check(by["image-1"]["params"]["prompt"] == "第 1 个画面", "生图提示词保留")
    check(by["voice-1"]["params"]["speaker"] == "local:preset:Vivian", "配音音色保留")
    check(by["voice-2"]["params"]["engine"] == "cloud", "配音引擎保留")
    check(by["voice-1"]["params"]["lines"][0]["text"] == "第 1 段测试口播。", "台词保留")
    check(by["image-1"]["outputs"] and (d / by["image-1"]["outputs"][0]["rel"]).is_file(), "已有图保留")
    check(by["voice-1"]["outputs"] and (d / by["voice-1"]["outputs"][0]["rel"]).is_file(), "已有配音保留")
    check(by["image-1"]["cache_hit"] is True and by["voice-2"]["cache_hit"] is True, "缓存命中标记保留")
    e = {(x["from"], x["to"]) for x in g["edges"]}
    check(("image-1.image", "mux.image") in e and ("voice-1.audio", "mux.audio") in e, "图和音都接到混流")
    check(("mux.video", "publish.video") in e, "混流接到发布")
    n0 = len(g["nodes"])
    S._load(p["id"])
    check(len(S._load(p["id"])["graph"]["nodes"]) == n0, "重复打开不会重复迁移（幂等）")
    # 迁移失败：原工程不动，.bak 还在
    p2 = make_project("迁移失败测试", shots=1, image_count=1, seconds=1.0)
    p2.pop("graph", None)
    video_maker.save_project(p2)
    orig = (Path(p2["dir"]) / "project.json").read_text("utf-8")
    old = studio.graph.migrate_from_shots
    studio.graph.migrate_from_shots = lambda _p: (_ for _ in ()).throw(RuntimeError("故意失败"))
    try:
        ok = False
        try:
            studio.Studio()._load(p2["id"])
        except studio.StudioError:
            ok = True
        check(ok, "迁移失败给出明确报错")
        check((Path(p2["dir"]) / "project.json").read_text("utf-8") == orig, "迁移失败原工程没动")
    finally:
        studio.graph.migrate_from_shots = old


def sample_doc():
    return {
        "title": "剧本导入测试", "desc": "简介", "tags": ["AI", "测试"],
        "bgm": {"segments": [{"id": "bgm-1", "prompt": "calm piano, no vocals", "seconds": 30, "steps": 8, "seed": 1}]},
        "shots": [
            {"id": "s1", "seconds": 5, "render": "web",
             "image": {"prompt": "第一张画面", "n": 1}, "voice": {"role": "白页", "tone": "冷静吐槽", "text": "第一句台词。"}},
            {"id": "s2", "seconds": 6, "render": "ppt",
             "image": {"prompt": "第二张画面"}, "voice": {"role": "紫苏", "tone": "夸张惊呼", "text": "第二句台词。"}},
            {"id": "s3", "seconds": 7, "render": "static",
             "image": {"prompt": "第三张画面"}, "voice": {"role": "白页", "tone": "轻松调侃", "text": "第三句台词。"}}
        ]
    }


def test_script_schema():
    print("\n剧本 schema：JSON / Markdown 都能认，缺字段和类型不对给出行号和原因")
    doc = studio.graph.parse_script_doc(json.dumps(sample_doc(), ensure_ascii=False))
    check(len(doc["shots"]) == 3 and [x["render"] for x in doc["shots"]] == ["web", "ppt", "static"], "JSON 分镜和画面轨道")
    check(doc["bgm"]["segments"][0]["prompt"] == "calm piano, no vocals", "JSON 配乐段")
    md = """# Markdown 测试
简介：一句话
话题：科技 搞笑

## 配乐 bgm-1
描述：upbeat, no vocals
时长：30

## 分镜 s1
画面轨道：网页
画面：第一张画面
角色：白页
语气：冷静吐槽
台词：第一句。

## 分镜 s2
画面轨道：静态
画面：第二张画面
角色：紫苏
语气：夸张惊呼
台词：第二句。
"""
    m = studio.graph.parse_script_doc(md)
    check(m["title"] == "Markdown 测试" and len(m["shots"]) == 2, "Markdown 标题和分镜")
    check(m["shots"][0]["render"] == "web" and m["shots"][1]["render"] == "static", "Markdown 画面轨道")
    bad = json.loads(json.dumps(sample_doc()))
    bad["shots"][1].pop("voice")
    ok = False
    try:
        studio.graph.parse_script_doc(json.dumps(bad, ensure_ascii=False))
    except studio.graph.GraphError as e:
        ok = "缺台词" in str(e) and "s2" in str(e)
    check(ok, "缺台词：指出是哪个分镜、缺什么")
    bad2 = json.loads(json.dumps(sample_doc()))
    bad2["shots"][0]["voice"]["role"] = "张三"
    ok = False
    try:
        studio.graph.parse_script_doc(json.dumps(bad2, ensure_ascii=False))
    except studio.graph.GraphError as e:
        ok = "角色" in str(e) and "张三" in str(e)
    check(ok, "角色不对：给出允许值和实际值")
    ok = False
    try:
        studio.graph.parse_script_doc('{"title":"x", bad json}')
    except studio.graph.GraphError as e:
        ok = "JSON" in str(e) and "行" in str(e)
    check(ok, "JSON 语法错：给出行列")
    ok = False
    try:
        studio.graph.parse_script_doc("## 分镜 s1\n画面轨道：网页动画\n画面：x\n台词：y\n角色：白页\n语气：z")
    except studio.graph.GraphError as e:
        ok = "画面轨道" in str(e)
    check(ok, "Markdown 轨道写错：指出字段")


def test_script_import():
    print("\n剧本导入：自动建节点和连线、不生成、幂等、增量更新、移除只标记")
    S = studio.Studio()
    st = S.new_project({"topic": "剧本导入", "voice_id": "local:preset:Vivian"})
    pid = st["project"]["id"]
    text = json.dumps(sample_doc(), ensure_ascii=False)
    r = S.graph_import({"pid": pid, "text": text})
    g = S._load(pid)["graph"]
    n0 = len(g["nodes"])
    check(n0 == 9 + 3 * 2 + 2 + 1, "3 个分镜：各加图/音节点，网页/PPT 各加轨道节点，配乐 1 个")
    check(r["estimate"]["images"] == 3 and r["estimate"]["tts_chars"] > 0, "导入只给预估费用")
    e = {(x["from"], x["to"]) for x in g["edges"]}
    check(("mux.video", "publish.video") in e, "混流接到发布")
    check(any(a.endswith(".image") and b == "mux.image" for a, b in e), "图接到混流")
    check(any(a.endswith(".audio") and b == "mux.audio" for a, b in e), "音接到混流")
    check(any(a.endswith(".video") and b == "mux.video" for a, b in e), "网页轨接到混流")
    # 幂等
    r2 = S.graph_import({"pid": pid, "text": text})
    g2 = S._load(pid)["graph"]
    check(len(g2["nodes"]) == n0, "同一份剧本导入两次，节点数不变")
    # 增量更新：s1 台词改了，别的节点参数不动
    doc = sample_doc()
    doc["shots"][0]["voice"]["text"] = "改过的第一句。"
    r3 = S.graph_import({"pid": pid, "text": json.dumps(doc, ensure_ascii=False)})
    g3 = S._load(pid)["graph"]
    by = {(n["params"].get("script_key") or n["id"]): n for n in g3["nodes"]}
    check(by["voice:s1"]["params"]["lines"][0]["text"] == "改过的第一句。", "同 key 更新台词")
    check(by["voice:s2"]["params"]["lines"][0]["text"] == "第二句台词。", "没改的分镜保持原样")
    check(len(g3["nodes"]) == n0, "增量更新不新增节点")
    # 移除一个分镜：只标记，不删除；接到混流的线断开
    doc2 = sample_doc()
    doc2["shots"] = [doc2["shots"][0]]
    S.graph_import({"pid": pid, "text": json.dumps(doc2, ensure_ascii=False)})
    g4 = S._load(pid)["graph"]
    by = {(n["params"].get("script_key") or n["id"]): n for n in g4["nodes"]}
    check(by["image:s2"]["params"].get("script_removed") is True, "剧本里没有的节点标成已移除")
    check(any(n["id"] == by["image:s2"]["id"] for n in g4["nodes"]), "标已移除但不删除")
    e4 = {(x["from"], x["to"]) for x in g4["edges"]}
    check((by["image:s2"]["id"] + ".image", "mux.image") not in e4, "已移除节点不再接在混流上")
    check(len(g4["nodes"]) == n0, "移除不改变节点数")
    # 没触发任何生成
    check(all(n["status"] != "ok" or not n["outputs"] for n in g4["nodes"] if n["type"] in ("image", "voice")),
          "导入没跑生成（没有新产出）")


def test_styleframe():
    print("\n看图复刻：Claude Code（假的）看参考图写 HTML，再录成视频轨；同参数第二次直接命中")
    try:
        import playwright  # noqa: F401
    except Exception as e:
        print("  跳过：没装 Playwright：", e)
        return
    import os
    S = studio.Studio()
    st = S.new_project({"topic": "看图复刻", "voice_id": "local:preset:Vivian"})
    pid = st["project"]["id"]
    p = S._load(pid)
    d = Path(p["dir"])
    (d / "images").mkdir(parents=True, exist_ok=True)
    ff = ffmpeg()
    if not ff:
        print("  跳过：没有 ffmpeg")
        return
    ref = d / "images" / "ref.png"
    png(ff, ref, "0x1e3a8a", 360, 640)
    img = next(n for n in p["graph"]["nodes"] if n["id"] == "image-1")
    img["outputs"] = [studio._out(p, "images/ref.png", "image")]
    img["status"] = "ok"
    video_maker.save_project(p)
    S.graph_connect({"pid": pid, "from": "image-1.image", "to": "web-1.image"})
    p = S._load(pid)
    S.graph_update({"pid": pid, "id": "web-1", "params": {"text": "看图复刻字幕", "duration": 1, "fps": 12}})
    p = S._load(pid)
    web = next(n for n in p["graph"]["nodes"] if n["id"] == "web-1")
    cc = RUN / ("claude.cmd" if os.name == "nt" else "claude")
    if os.name == "nt":
        cc.write_text('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, ROOT / "dev" / "fake_claude.py"), "utf-8")
    else:
        cc.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, ROOT / "dev" / "fake_claude.py"), "utf-8")
        cc.chmod(0o755)
    old = {k: settings.S.get(k) for k in ("ccOn", "ccCmd", "ccBash", "wsRun")}
    settings.S.update({"ccOn": True, "ccCmd": str(cc), "ccBash": "python", "wsRun": False})
    try:
        S.job = {"id": 1, "st": "run", "mode": "styleframe", "step": "web-1", "pid": pid, "msg": "", "pct": 0,
                 "t0": time.time(), "t1": 0, "stage": 3, "err": "", "shot": ""}
        asyncio.run(S._graph_styleframe(p, web))
        q = S._load(pid)
        w = next(n for n in q["graph"]["nodes"] if n["id"] == "web-1")
        check(w["status"] == "ok" and w.get("outputs"), "复刻后节点完成、有视频轨" + ("（" + str(w.get("error"))[:200] + "）" if w.get("error") else ""))
        rel = (w.get("outputs") or [{}])[0].get("rel")
        check(bool(rel) and (d / rel).is_file() and (d / rel).stat().st_size > 1000, "视频轨文件真的录出来了")
        h = d / (w["params"].get("styleframe") or {}).get("html", "")
        check(h.is_file(), "Claude Code 写出的 index.html 在")
        fl = json.loads((ROOT / "dev" / ".run" / "fake_claude_last.json").read_text("utf-8"))
        pr = fl.get("prompt") or ""
        check("60-30-10" in pr and "禁止联网" in pr and "1080" in pr, "提示词带 60-30-10、尺寸、禁止外链")
        check(str(ref) in pr, "提示词带参考图路径")
        # 第二次：同参数直接命中，不再调用 Claude Code
        called = []

        async def boom(*a, **kw):
            called.append(1)
            raise RuntimeError("不该再调用 Claude Code")

        old_run = studio.ccode.run
        studio.ccode.run = boom
        try:
            p2 = S._load(pid)
            w2 = next(n for n in p2["graph"]["nodes"] if n["id"] == "web-1")
            S.job = {"id": 2, "st": "run", "mode": "styleframe", "step": "web-1", "pid": pid, "msg": "", "pct": 0,
                     "t0": time.time(), "t1": 0, "stage": 3, "err": "", "shot": ""}
            asyncio.run(S._graph_styleframe(p2, w2))
        finally:
            studio.ccode.run = old_run
        check(not called, "参数没变：没有再调用 Claude Code")
        w3 = next(n for n in S._load(pid)["graph"]["nodes"] if n["id"] == "web-1")
        check(w3.get("cache_hit") is True, "节点显示缓存命中")
    finally:
        for k, v in old.items():
            settings.S[k] = v


def main():
    shutil.rmtree(RUN, ignore_errors=True)
    RUN.mkdir(parents=True, exist_ok=True)
    old_ws = settings.S.get("wsDir")
    from app import db
    old_active = db.kv_get("studio_active")
    settings.S["wsDir"] = str(RUN / "ws")
    try:
        test_parse()
        test_assets()
        test_project()
        test_plan_project()
        test_default_nodes()
        test_graph_model()
        test_graph_topo_parallel()
        test_graph_cache_scope()
        test_graph_missing_upstream()
        test_migration()
        test_script_schema()
        test_script_import()
        test_styleframe()
        test_style_models()
        test_dual_role_voice()
        test_gemini_pack()
        test_import_script()
        test_image_params()
        test_cache_scheduler()
        test_compose()
        test_render_tracks()
        test_single_step()
        test_publish_matrix()
        test_stop()
    finally:
        settings.S["wsDir"] = old_ws
        keep = ""
        if old_active:
            try:
                video_maker.load_project(old_active)
                keep = old_active
            except Exception:
                keep = ""
        db.kv_set("studio_active", keep)
    print("\n" + ("全部通过" if not BAD else "没通过：" + "；".join(BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
