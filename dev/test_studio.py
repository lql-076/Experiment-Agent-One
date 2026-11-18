"""v4.0.0 视频工坊：7 个零连线独立模块、Markdown 清单、三路并行、模块 6 三窗总成。
不连后端、不用显卡、不花钱：图/视频用 ffmpeg 生成纯色，配音/配乐用 Python 写正弦波。
"""
import asyncio
import base64
import json
import math
import shutil
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RUN = ROOT / "dev" / ".run" / "studio_test"

from app import bgm, imagegen, render_ppt, render_web, settings, studio, studio_assets, studio_cache as cache  # noqa: E402
from app import studio_graph as graph, video_maker  # noqa: E402

BAD = []
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lzq4WQAAAABJRU5ErkJggg==")


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
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr); f.writeframes(pcm)


def png(ff, path, color, w=360, h=640):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}",
                    "-frames:v", "1", str(path)], check=True)


def blank_mp4(ff, path, seconds=1.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x1e3a8a:s=360x640:r=12",
                    "-t", str(seconds), "-pix_fmt", "yuv420p", str(path)], check=True)


def make_project(name="模块测试"):
    S = studio.Studio()
    st = S.new_project({"topic": name, "voice_id": "local:preset:Vivian"})
    return S, video_maker.load_project(st["project"]["id"])


def test_default_modules():
    print("\n默认画布：7 个模块、0 连线、0 端口、每个都能独立跑")
    S, p = make_project("默认画布")
    mods = p["modules"]
    check([m["id"] for m in mods] == graph.FIXED_IDS, "7 个固定模块 id")
    check([m["type"] for m in mods] == ["script", "image", "voice", "voice", "bgm", "compose", "publish"], "7 个模块类型")
    check("graph" not in p and "shots" not in p and "edges" not in p, "工程里没有 graph / edges / shots")
    check(all((m.get("x") is not None and m.get("w", 0) > 0) for m in mods), "每个模块都有位置和大小")
    check(all((Path(p["dir"]) / "Lists" / n).is_file() for n in graph.LISTS), "5 份 Markdown 清单都落盘")
    check("方式：" in graph.read_list(p, "视频渲染清单.md"), "视频渲染清单写明了方式（网页/PPT/静态）")
    seen = []

    async def fake(self, pp, m, part=""):
        seen.append(m["id"])
        return []

    old = studio.Studio._exec_module
    studio.Studio._exec_module = fake
    try:
        async def go():
            for mid in graph.FIXED_IDS:
                await S._run_module(S._load(p["id"]), mid, "")
        asyncio.run(go())
    finally:
        studio.Studio._exec_module = old
    check(seen == graph.FIXED_IDS, "7 个模块都能单独点运行，没有「缺上游」")


def test_lists_and_script():
    print("\n模块 1：导入剧本 → 4 份清单落盘 → 模块 3/4/5/6 自动填入")
    S, p = make_project("清单测试")
    doc = {"title": "清单测试视频", "desc": "简介", "tags": ["AI"],
           "bgm": {"segments": [{"id": "bgm-1", "prompt": "calm piano, no vocals", "seconds": 30, "steps": 8, "seed": 1}]},
           "shots": [
               {"id": "s1", "seconds": 5, "render": "web", "image": {"prompt": "第一张画面"},
                "voice": {"role": "白页", "tone": "冷静吐槽", "text": "第一句。"}},
               {"id": "s2", "seconds": 6, "render": "ppt", "image": {"prompt": "第二张画面"},
                "voice": {"role": "紫苏", "tone": "夸张惊呼", "text": "第二句。"}},
               {"id": "s3", "seconds": 7, "render": "static", "image": {"prompt": "第三张画面"},
                "voice": {"role": "白页", "tone": "轻松调侃", "text": "第三句。"}}]}
    S.script_import({"pid": p["id"], "text": json.dumps(doc, ensure_ascii=False)})
    q = S._load(p["id"])
    check((Path(q["dir"]) / "Lists" / "配音清单_白页.md").is_file(), "白页配音清单")
    check("第一句。" in graph.read_list(q, "配音清单_白页.md") and "第三句。" in graph.read_list(q, "配音清单_白页.md"), "白页清单收了两句")
    check("第二句。" in graph.read_list(q, "配音清单_紫苏.md"), "紫苏清单收了一句")
    check("calm piano" in graph.read_list(q, "配乐清单.md"), "配乐清单")
    check("PPT" in graph.read_list(q, "视频渲染清单.md") and "网页" in graph.read_list(q, "视频渲染清单.md"), "渲染清单写清网页/PPT")
    check("第一张画面" in graph.read_list(q, "生图清单.md"), "生图清单（可选）")
    w = graph.module_of(q, "voice-white")
    z = graph.module_of(q, "voice-zisu")
    check([x["line_index"] for x in w["params"]["lines"]] == [1, 3], "白页句序 1、3")
    check([x["line_index"] for x in z["params"]["lines"]] == [2], "紫苏句序 2")
    check(len((graph.module_of(q, "compose")["params"].get("shots") or [])) == 3, "渲染清单进模块 6")
    txt = graph.read_list(q, "配音清单_白页.md").replace("第一句。", "改过的第一句。")
    S.list_set({"pid": q["id"], "name": "配音清单_白页.md", "text": txt})
    q = S._load(q["id"])
    check("改过的第一句。" in json.dumps(graph.module_of(q, "voice-white")["params"], ensure_ascii=False), "编辑清单能回填模块参数")
    check("edges" not in q, "清单协作不产生连线")


def test_voice_global_order():
    print("\n模块 3/4：独立运行，按全局 line_index 产出 shotNN.wav + voice/srt/timeline")
    S, p = make_project("配音顺序")
    w = graph.module_of(p, "voice-white"); z = graph.module_of(p, "voice-zisu")
    w["params"]["lines"] = [{"id": "l1", "line_index": 1, "text": "白一。", "tone": ""},
                            {"id": "l2", "line_index": 3, "text": "白三。", "tone": ""}]
    z["params"]["lines"] = [{"id": "l1", "line_index": 2, "text": "紫二。", "tone": ""},
                            {"id": "l2", "line_index": 4, "text": "紫四。", "tone": ""}]
    video_maker.save_project(p)

    async def fake_tts(self, pp, ids=None, shots=None, out_prefix=""):
        shots = shots if shots is not None else pp["shots"]
        for s in shots:
            rel = s.get("_tts_rel") or f"tts/shot{shots.index(s) + 1:02d}.wav"
            wav(Path(pp["dir"]) / rel, .4, 440 + len(rel))
            s.update(tts=rel, tts_st="ok", tts_cache_hit=True, duration=.4)
    old = studio.Studio._gen_tts
    studio.Studio._gen_tts = fake_tts
    try:
        asyncio.run(S._run_module(S._load(p["id"]), "voice-white", ""))
        asyncio.run(S._run_module(S._load(p["id"]), "voice-zisu", ""))
    finally:
        studio.Studio._gen_tts = old
    q = S._load(p["id"])
    d = Path(q["dir"])
    check(all((d / "tts" / f"shot{i:02d}.wav").is_file() for i in (1, 2, 3, 4)), "四句按全局句序写 shot01~04.wav")
    check((d / "tts" / "voice.wav").is_file() and (d / "tts" / "subtitles.srt").is_file() and (d / "tts" / "timeline.json").is_file(),
          "汇总出 voice.wav / subtitles.srt / timeline.json")
    meta = json.loads((d / "tts" / "timeline.json").read_text("utf-8"))
    check([x["text"] for x in meta["shots"]] == ["白一。", "紫二。", "白三。", "紫四。"], "时间轴按全局句序排")
    check(len(graph.module_of(q, "voice-white")["outputs"]) == 2, "白页模块只留自己的两句产出")


def test_image_module():
    print("\n模块 2：生图测试台 + 缓存，不影响视频主流程")
    S, p = make_project("生图测试")
    m = graph.module_of(p, "image")
    calls = []

    async def fake_images(c, base, k, cd, prompt, ratio, tier, quality, transparent, refs, **kw):
        calls.append(prompt)
        return [PNG], {}, {}

    old = imagegen.call_images
    old_secret = settings.get_secret
    imagegen.call_images = fake_images
    settings.get_secret = lambda k: "sk-test-0000" if k == "imgKey" else old_secret(k)
    try:
        m["params"].update({"prompt": "测试小猫", "n": 1, "model": "gpt-image-2.6-sunburst"})
        video_maker.save_project(p)
        asyncio.run(S._run_module(S._load(p["id"]), "image", ""))
        q = S._load(p["id"]); im = graph.module_of(q, "image")
        check(im["status"] == "ok" and im["outputs"], "生图模块单独出图")
        asyncio.run(S._run_module(S._load(p["id"]), "image", ""))
        q = S._load(p["id"]); im = graph.module_of(q, "image")
        check(len(calls) == 1 and im["cache_hit"] is True, "第二次同参数命中缓存")
        async def force_go():
            await S.start_run({"pid": p["id"], "id": "image", "force": True})
            t = S._tasks.get("image")
            if t:
                await t
        asyncio.run(force_go())
        check(len(calls) == 2, "点「立即生成测试」带 force：不吃缓存，真的请求 API")
        c = graph.module_of(S._load(p["id"]), "compose")
        check(c["status"] != "ok" or c.get("outputs"), "生图模块不参与视频主流程")
    finally:
        imagegen.call_images = old
        settings.get_secret = old_secret


def test_compose_independent():
    print("\n模块 6：没有配音也能独立跑（静音成片），不报缺上游")
    ff = ffmpeg()
    if not ff:
        return
    S, p = make_project("静音成片")
    c = graph.module_of(p, "compose")
    c["params"].update({"shots": [{"id": "s1", "line_index": 1, "render": "ppt", "text": "静音测试", "visual": "一个要点",
                                   "seconds": 1.0, "transition": "淡入"}], "subtitle": False, "bgm_volume": 0})
    video_maker.save_project(p)

    def fake_ppt(project_dir, project, say=None, stopped=None):
        d = Path(project_dir)
        for s in project.get("shots") or []:
            out = d / "render" / f"ppt_{s['id']}.png"
            png(ff, out, "0x1e3a8a", 360, 640)
            s["render_image"] = f"render/{out.name}"
        return {}
    old = render_ppt.render_all
    render_ppt.render_all = fake_ppt
    try:
        S.job = {"id": 1, "st": "run", "mode": "module", "step": "compose", "pid": p["id"], "stage": 2, "msg": "",
                 "pct": 0, "err": "", "shot": "", "t0": time.time(), "t1": 0, "web": {}, "ppt": {}, "ffmpeg": {}}
        asyncio.run(S._run_module(S._load(p["id"]), "compose", ""))
    finally:
        render_ppt.render_all = old
    q = S._load(p["id"])
    check(graph.module_of(q, "compose")["status"] == "ok", "模块 6 单独跑完成")
    check((Path(q["dir"]) / "output" / "成片.mp4").is_file(), "静音也能合成 mp4")


def test_compose_monitors():
    print("\n模块 6：网页/PPT/FFmpeg 三窗状态都有，合成后进模块 7")
    ff = ffmpeg()
    if not ff:
        return
    S, p = make_project("三窗监控")
    c = graph.module_of(p, "compose")
    c["params"].update({"shots": [{"id": "s1", "line_index": 1, "render": "web", "text": "网页镜头", "visual": "深色排版", "seconds": 1.0},
                                   {"id": "s2", "line_index": 2, "render": "ppt", "text": "PPT 镜头", "visual": "两个要点", "seconds": 1.0}],
                        "subtitle": False, "bgm_volume": 0})
    wav(Path(p["dir"]) / "tts" / "shot01.wav", .8, 440)
    wav(Path(p["dir"]) / "tts" / "shot02.wav", .8, 550)
    wm = graph.module_of(p, "voice-white"); zm = graph.module_of(p, "voice-zisu")
    wm["outputs"] = [studio._out(p, "tts/shot01.wav", "audio", {"line": "1", "text": "网页镜头"})]
    zm["outputs"] = [studio._out(p, "tts/shot02.wav", "audio", {"line": "2", "text": "PPT 镜头"})]
    wm["params"]["lines"] = [{"id": "l1", "line_index": 1, "text": "网页镜头", "tone": ""}]
    zm["params"]["lines"] = [{"id": "l1", "line_index": 2, "text": "PPT 镜头", "tone": ""}]
    video_maker.save_project(p)

    def fake_web(project_dir, shot, settings, out_path, W, H, fps=24, stopped=None, preview=None, on_frame=None):
        blank_mp4(ff, Path(out_path), 1.0)
        if preview:
            png(ff, Path(preview), "0x0b1a2a", 360, 640)
        return Path(out_path)

    def fake_ppt(project_dir, project, say=None, stopped=None):
        d = Path(project_dir)
        for s in project.get("shots") or []:
            out = d / "render" / f"ppt_{s['id']}.png"
            png(ff, out, "0xb45309", 360, 640)
            s["render_image"] = f"render/{out.name}"
        return {}

    old_w, old_p = render_web.render_shot, render_ppt.render_all
    render_web.render_shot, render_ppt.render_all = fake_web, fake_ppt
    try:
        S.job = {"id": 2, "st": "run", "mode": "module", "step": "compose", "pid": p["id"], "stage": 2, "msg": "",
                 "pct": 0, "err": "", "shot": "", "t0": time.time(), "t1": 0, "web": {}, "ppt": {}, "ffmpeg": {}}
        asyncio.run(S._run_module(S._load(p["id"]), "compose", ""))
        j = S.job
    finally:
        render_web.render_shot, render_ppt.render_all = old_w, old_p
    check(j["web"].get("st") == "ok" and j["web"].get("total") == 1, "网页动效监控窗有状态和总数")
    check(j["web"].get("preview_rel"), "网页监控窗有预览帧")
    check(j["ppt"].get("st") == "ok" and len(j["ppt"].get("slides") or []) >= 1, "PPT 监控窗有缩略图")
    check(j["ffmpeg"].get("st") == "ok" and j["ffmpeg"].get("pct") == 100, "FFmpeg 监控窗有进度和完成状态")
    q = S._load(p["id"])
    check((Path(q["dir"]) / "output" / "成片.mp4").is_file(), "三窗合成出 mp4")


def test_full_parallel_skips_image():
    print("\n全程：白页/紫苏/配乐三路并行，跳过生图，最后进模块 6")
    S, p = make_project("全程并行")
    events = []

    async def fake_exec(self, pp, m, part=""):
        mid = m["id"]
        events.append((mid, "start", time.time()))
        if mid in ("voice-white", "voice-zisu", "bgm"):
            await asyncio.sleep(.12)
        events.append((mid, "end", time.time()))
        return []

    async def fake_rebuild(self, pp):
        events.append(("rebuild", "start", time.time()))
        await asyncio.sleep(.02)
        events.append(("rebuild", "end", time.time()))
        return {}

    old, old_rb = studio.Studio._exec_module, studio.Studio._rebuild_voice
    studio.Studio._exec_module, studio.Studio._rebuild_voice = fake_exec, fake_rebuild
    try:
        async def go():
            await S.start_run({"pid": p["id"]})
            t = S._task
            if t:
                await t
        asyncio.run(go())
    finally:
        studio.Studio._exec_module, studio.Studio._rebuild_voice = old, old_rb
    starts = {k: t for k, what, t in events if what == "start"}
    ends = {k: t for k, what, t in events if what == "end"}
    check(all(k in starts for k in ("voice-white", "voice-zisu", "bgm")), "三路都启动")
    check(max(starts["voice-white"], starts["voice-zisu"], starts["bgm"]) - min(starts["voice-white"], starts["voice-zisu"], starts["bgm"]) < .08,
          "白页/紫苏/配乐同时开跑")
    check("image" not in starts, "全程跳过生图模块")
    check(starts.get("compose", 0) > max(ends["voice-white"], ends["voice-zisu"], ends["bgm"]) - .02, "配音配乐完成后才进模块 6")
    check(S.job["st"] == "done", "全程跑完")


def test_migration():
    print("\n旧工程迁移：graph/shots → 7 个模块，保留台词/音色/产出，无 edges")
    S, p = make_project("迁移测试")
    ff = ffmpeg()
    d = Path(p["dir"])
    wav(d / "tts" / "shot01.wav", .5, 440); wav(d / "tts" / "shot02.wav", .5, 550)
    png(ff, d / "images" / "old.png", "0x1e3a8a")
    p["graph"] = {"nodes": [
        {"id": "script", "type": "script", "params": {"title": "旧标题", "topic": "旧主题"}},
        {"id": "image-1", "type": "image", "params": {"prompt": "旧画面"}, "outputs": [{"rel": "images/old.png", "kind": "image", "sha256": "x"}], "status": "ok"},
        {"id": "voice-1", "type": "voice", "params": {"role": "白页", "speaker": "local:preset:Serena", "tone": "冷静",
                                                       "lines": [{"id": "l1", "text": "旧白页。"}], "order": 1},
         "outputs": [{"rel": "tts/shot01.wav", "kind": "audio", "line": "1"}]},
        {"id": "voice-2", "type": "voice", "params": {"role": "紫苏", "speaker": "local:preset:Dylan", "tone": "夸张",
                                                       "lines": [{"id": "l1", "text": "旧紫苏。"}], "order": 2},
         "outputs": [{"rel": "tts/shot02.wav", "kind": "audio", "line": "1"}]},
        {"id": "bgm-1", "type": "bgm", "params": {}},
        {"id": "mux", "type": "mux", "params": {}, "outputs": []},
        {"id": "publish", "type": "publish", "params": {"title": "旧标题"}}], "edges": [{"from": "image-1.image", "to": "mux.image"}]}
    p.pop("modules", None); p.pop("modules_version", None)
    p["shots"] = [{"id": "s1", "text": "旧白页。", "role": "白页", "speaker": "local:preset:Serena", "tone": "冷静",
                   "image_prompt": "旧画面", "image": "images/old.png", "tts": "tts/shot01.wav", "render": "web", "duration": .5},
                  {"id": "s2", "text": "旧紫苏。", "role": "紫苏", "speaker": "local:preset:Dylan", "tone": "夸张",
                   "tts": "tts/shot02.wav", "render": "ppt", "duration": .5}]
    video_maker.save_project(p)
    q = S._load(p["id"])
    check([m["id"] for m in q["modules"]] == graph.FIXED_IDS, "迁移成 7 个模块")
    check("graph" not in q and "shots" not in q and "edges" not in q, "旧 graph/edges 被清掉")
    w = graph.module_of(q, "voice-white"); z = graph.module_of(q, "voice-zisu")
    check(w["params"]["lines"][0]["text"] == "旧白页。" and z["params"]["lines"][0]["text"] == "旧紫苏。", "台词保留")
    check(w["params"]["speaker"] == "local:preset:Serena", "白页音色保留")
    check(graph.module_of(q, "image")["outputs"], "旧图产出保留")
    check((Path(q["dir"]) / "Lists" / "视频渲染清单.md").is_file(), "迁移后自动生成清单")



def test_media_assets():
    print("\n媒体接口：WAV/MP3/FLAC/MP4 白名单、文件头、Accept-Ranges")
    S, p = make_project("媒体测试")
    d = Path(p["dir"])
    wav(d / "tts" / "shot01.wav", 1.0, 440)
    (d / "bgm").mkdir(parents=True, exist_ok=True)
    wav(d / "bgm" / "bgm.wav", 1.0, 220, 48000)
    (d / "output").mkdir(parents=True, exist_ok=True)
    (d / "output" / "t.mp3").write_bytes(b"ID3" + bytes(40))
    (d / "output" / "t.flac").write_bytes(b"fLaC" + bytes(32))
    (d / "output" / "t.mp4").write_bytes(bytes.fromhex("000000186674797069736f6d") + bytes(32))
    for rel, mime, kind in (("tts/shot01.wav", "audio/wav", "audio"), ("bgm/bgm.wav", "audio/wav", "audio"),
                            ("output/t.mp3", "audio/mpeg", "audio"), ("output/t.flac", "audio/flac", "audio"),
                            ("output/t.mp4", "video/mp4", "video")):
        q = studio_assets.project_asset(p["id"], rel)
        info = studio_assets.info(q)
        check(info["mime"] == mime and info["kind"] == kind, "认得出 " + rel + " → " + mime)
    resp = studio_assets.file_response(d / "tts" / "shot01.wav")
    check(resp.headers.get("accept-ranges") == "bytes", "WAV 响应带 Accept-Ranges: bytes")
    check(resp.media_type == "audio/wav", "WAV Content-Type 正确")
    ok = False
    try:
        studio_assets.project_asset(p["id"], "Lists/配音清单_白页.md")
    except studio_assets.AssetError:
        ok = True
    check(ok, "清单/文本不会被当成媒体给出去")


def test_concurrent_modules():
    print("\n多模块真并发：白页配音 + 配乐同时跑，不返回 409；单模块停止只停自己")
    S, p = make_project("并发测试")
    calls = []

    async def fake(self, pp, m, part=""):
        calls.append(m["id"])
        for i in range(6):
            self._phase(f"{m['id']} 第 {i + 1} 步", 10 + i * 14, "running")
            await asyncio.sleep(.08)
            self._check_stop()
        return []

    old = studio.Studio._exec_module
    studio.Studio._exec_module = fake
    async def go():
        await S.start_run({"pid": p["id"], "id": "voice-white"})
        await S.start_run({"pid": p["id"], "id": "bgm"})
        check(set(S._running_ids()) == {"voice-white", "bgm"}, "两个模块同时在跑")
        mid_state = S.state()["project"]
        rows = {m["id"]: m["runtime"] for m in mid_state["modules"] if m["id"] in ("voice-white", "bgm")}
        check(all(rows[x]["status"] == "running" for x in rows), "两个模块 runtime 都是 running")
        check(all(rows[x]["pct"] >= 0 for x in rows), "两个模块都有 pct")
        await asyncio.gather(*[t for m, t in S._tasks.items() if m in ("voice-white", "bgm")])
        q = S._load(p["id"])
        check(all(graph.module_of(q, x)["runtime"]["status"] == "ok" for x in ("voice-white", "bgm")), "两个模块都完成")
        check(set(calls) == {"voice-white", "bgm"}, "两边都真的执行了")
    asyncio.run(go())
    # 单模块停止
    async def slow(self, pp, m, part=""):
        for i in range(50):
            self._phase(f"{m['id']} 慢速 {i}", i, "running")
            await asyncio.sleep(.05)
            self._check_stop()
        return []
    studio.Studio._exec_module = slow
    async def stop_go():
        await S.start_run({"pid": p["id"], "id": "voice-white"})
        t = S._tasks["voice-white"]
        await asyncio.sleep(.15)
        r = S.stop("voice-white")
        check(r.get("ok") is True, "单模块停止被接受")
        try:
            await asyncio.wait_for(t, 5)
        except Exception:
            pass
        q = S._load(p["id"])
        check(graph.module_of(q, "voice-white")["runtime"]["status"] in ("idle", "error"), "停下后只这个模块退出 running")
    asyncio.run(stop_go())
    studio.Studio._exec_module = old


def test_runtime_progress():
    print("\n实时进度：pct / phase / started_at / last_took_s 会更新")
    S, p = make_project("进度测试")
    seen = []
    async def fake(self, pp, m, part=""):
        for i in range(4):
            self._phase(f"阶段 {i + 1}/4", 20 + i * 20, "running")
            seen.append((time.time(), self._jobs[m["id"]]["pct"]))
            await asyncio.sleep(.08)
        return []
    old = studio.Studio._exec_module
    studio.Studio._exec_module = fake
    async def go():
        await S.start_run({"pid": p["id"], "id": "image"})
        t = S._tasks["image"]
        await asyncio.sleep(.12)
        rt = S.state()["project"]["modules"][1]["runtime"]
        check(rt.get("status") == "running" and rt.get("started_at", 0) > 0, "运行中有 status 和 started_at")
        check(rt.get("pct", 0) > 0 and rt.get("phase"), "运行中有 pct 和 phase")
        await t
        rt2 = graph.module_of(S._load(p["id"]), "image")["runtime"]
        check(rt2.get("status") == "ok" and rt2.get("last_took_s", 0) > 0, "完成后有 last_took_s")
        check(rt2.get("pct") == 100, "完成后 pct 100")
    asyncio.run(go())
    studio.Studio._exec_module = old


def main():
    shutil.rmtree(RUN, ignore_errors=True)
    RUN.mkdir(parents=True, exist_ok=True)
    old_ws = settings.S.get("wsDir")
    from app import db
    old_active = db.kv_get("studio_active")
    settings.S["wsDir"] = str(RUN / "ws")
    try:
        test_default_modules()
        test_media_assets()
        test_lists_and_script()
        test_voice_global_order()
        test_image_module()
        test_compose_independent()
        test_compose_monitors()
        test_full_parallel_skips_image()
        test_concurrent_modules()
        test_runtime_progress()
        test_migration()
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
