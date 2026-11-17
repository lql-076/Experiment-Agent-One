"""v3.6 视频工坊：工程目录、AI 拆解结构化解析、FFmpeg 合成、单步重跑、停下中断。

不连后端、不用显卡、不花钱：图用 ffmpeg 生成纯色，配音和配乐用 Python 写正弦波 WAV。
只在 dev/.run/studio_test 里折腾，跑完留着方便排查。
"""
import asyncio
import json
import math
import struct
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RUN = ROOT / "dev" / ".run" / "studio_test"

from app import settings, studio, video_maker  # noqa: E402

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
    async def fake(topic, text, ratio, style, seconds):
        return {"title": "拆解测试标题", "desc": "简介", "tags": ["AI", "测试"],
                "bgm_prompt": "calm piano, no vocals",
                "shots": [{"text": "第一镜", "tone": "轻松", "image_prompt": "画面一", "seconds_hint": 5},
                          {"text": "第二镜", "tone": "平静", "image_prompt": "画面二", "seconds_hint": 6}]}, 0.001
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
    finally:
        studio._ask_plan = old


def make_project(name, shots=2, image_count=1, seconds=3.0, ratio="9:16"):
    p = video_maker.new_project(name, ratio, "知识科普", 30, topic=name)
    p["shots"] = []
    for i in range(shots):
        p["shots"].append({"id": f"s{i + 1}", "text": f"第 {i + 1} 段测试口播。", "tone": "平静",
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

    def fake(d, srt=True, bgm_volume=0.18, kenburns=True, stopped=None, progress=None):
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


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    old_ws = settings.S.get("wsDir")
    settings.S["wsDir"] = str(RUN / "ws")
    try:
        test_parse()
        test_project()
        test_plan_project()
        test_compose()
        test_single_step()
        test_stop()
    finally:
        settings.S["wsDir"] = old_ws
    print("\n" + ("全部通过" if not BAD else "没通过：" + "；".join(BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
