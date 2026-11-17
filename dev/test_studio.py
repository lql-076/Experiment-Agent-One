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

from app import imagegen, render_ppt, render_web, settings, studio, studio_cache as cache, video_maker  # noqa: E402

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
                                                      gif_frames=8, gif_delay_ms=150))
    finally:
        imagegen._post = old
    f = seen.get("json") or {}
    check(len(imgs) == 2, "一次回 2 张")
    check(f.get("size") == "720x1280", "自定义宽高透传")
    check(f.get("n") == 2 and f.get("background") == "transparent", "n / 透明背景")
    check(f.get("output_format") == "gif" and f.get("gif_frames") == 8 and f.get("gif_delay_ms") == 150, "GIF 帧参数")
    check(f.get("complexity") == "high", "规划复杂度")


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


def main():
    shutil.rmtree(RUN, ignore_errors=True)
    RUN.mkdir(parents=True, exist_ok=True)
    old_ws = settings.S.get("wsDir")
    settings.S["wsDir"] = str(RUN / "ws")
    try:
        test_parse()
        test_project()
        test_plan_project()
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
    print("\n" + ("全部通过" if not BAD else "没通过：" + "；".join(BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
