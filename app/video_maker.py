r"""视频合成引擎（v3.6 起，v3.8 支持网页/PPT/GIF 双轨）。

把「分镜图片 + 分镜配音 + 字幕 + 配乐」合成一条能直接发的成片：
- 工程结构：工作区\视频工坊\<项目名_时间戳>\（不进仓库）：
    project.json     状态、参数、分镜脚本、每一步的产出
    images\          分镜图
    tts\             每段配音（shotNN.wav）、拼好的 voice.wav、subtitles.srt、timeline.json
    bgm\bgm.wav      配乐
    output\成片.mp4  成片；output\封面.png 封面
- 时间轴：每个分镜的展示时长 = 这段配音的时长（分镜之间留一点停顿）；图片比配音段少就循环铺满。
- 防呆板：FFmpeg zoompan 给静态图加缓慢推近 / 拉远 / 横向微移；9:16 1080×1920（抖音默认）和 16:9 1920×1080。
- 字幕：读 subtitles.srt 烧进画面，白字黑边、靠下，竖屏给抖音底部文案区留位置。
- 配乐：循环或裁剪到总时长，结尾 2 秒淡出；有人说话时用 sidechaincompress 自动压低（Audio Ducking）。
- 进度：ffmpeg -progress 实时回百分比；停下时安全结束自己开的 ffmpeg（CREATE_NO_WINDOW，不留黑窗口）。

只依赖本机 FFmpeg：优先 PATH，其次 imageio-ffmpeg，其次工作区 ws-env 里那份（toolbox/合成.py 的探测顺序，
再加一个 ws-env 兜底，因为作者电脑上 ffmpeg 是工作区 pip 装的）。
"""
import json
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from . import mediainfo, paths, telemetry

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FPS = 30
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
PROJECT_FILE = "project.json"
DIRS = ("images", "tts", "bgm", "output")
GAP = 0.25                     # 分镜之间的停顿（秒）
BGM_FADE = 2.0                 # 结尾淡出
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
PID_RE = re.compile(r"^[\w一-鿿.\-]{1,80}$")


class MakerError(RuntimeError):
    pass


# ---------------- ffmpeg ----------------
def ffmpeg_exe() -> str:
    """本机的 ffmpeg：PATH → imageio-ffmpeg → 工作区 ws-env（pip install imageio-ffmpeg 装的那份）。"""
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and Path(p).exists():
            return p
    except Exception:
        pass
    for p in (paths.ROOT / "ws-env" / ("Scripts/ffmpeg.exe" if paths.IS_WIN else "bin/ffmpeg"),
              paths.ROOT / "ws-env" / ("Scripts/ffmpeg" if paths.IS_WIN else "bin/ffmpeg"),
              paths.ROOT / "tools" / "ffmpeg" / ("bin/ffmpeg.exe" if paths.IS_WIN else "bin/ffmpeg")):
        if p.exists():
            return str(p)
    raise MakerError("没找到 ffmpeg：在「工作区」里运行一次 pip install imageio-ffmpeg，或者把 ffmpeg 装进 PATH")


def duration_of(p) -> float:
    """音频/视频多长；先读文件头（mediainfo，不启动子进程），认不出再问 ffmpeg。"""
    d = mediainfo.probe(p).get("duration")
    if d:
        return float(d)
    ff = ffmpeg_exe()
    r = subprocess.run([ff, "-hide_banner", "-i", str(p)], capture_output=True, creationflags=NOWIN)
    m = re.search(rb"Duration: (\d+):(\d+):(\d+\.?\d*)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


# ---------------- 工程 ----------------
def projects_root() -> Path:
    from . import workspace
    d = workspace.folder() / "视频工坊"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(s, n=24) -> str:
    """文件夹名：只留文字、数字、下划线、点和短横线；空格、标点、全角冒号都去掉。"""
    s = re.sub(r"[^\w.\-]+", "", str(s or ""), flags=re.UNICODE).strip(" .")
    return (s or "视频项目")[:n]


def _project_dir(pid, must_exist=True) -> Path:
    pid = str(pid or "").strip()
    if not PID_RE.fullmatch(pid) or pid in (".", ".."):
        raise MakerError("项目名不对")
    root = projects_root().resolve()
    d = (root / pid).resolve()
    if root not in d.parents:
        raise MakerError("项目名不对")
    if must_exist and not (d / PROJECT_FILE).exists():
        raise MakerError("找不到这个项目（可能被挪走或删了）")
    return d


def project_path(pid) -> Path:
    return _project_dir(pid, True)


def load_project(pid) -> dict:
    d = project_path(pid)
    try:
        p = json.loads((d / PROJECT_FILE).read_text("utf-8"))
    except Exception as e:
        raise MakerError(f"project.json 读不了：{e}") from None
    p["id"] = d.name
    p["dir"] = str(d)
    return p


def save_project(p: dict):
    d = _project_dir(p["id"], False)
    for sub in DIRS:
        (d / sub).mkdir(parents=True, exist_ok=True)
    p["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tmp = d / (PROJECT_FILE + ".tmp")
    tmp.write_text(json.dumps({k: v for k, v in p.items() if k != "dir"}, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(d / PROJECT_FILE)


def new_project(name, ratio="9:16", style="知识科普", target_seconds=60, topic="", voice=None) -> dict:
    root = projects_root()
    base = f"{datetime.now():%Y%m%d_%H%M%S}_{safe_name(name)}"
    pid, k = base, 2
    while (root / pid).exists():
        pid, k = f"{base}_{k}", k + 1
    d = root / pid
    for sub in DIRS:
        (d / sub).mkdir(parents=True, exist_ok=True)
    p = {"id": pid, "name": safe_name(name, 40), "title": safe_name(name, 40), "desc": "", "tags": [],
         "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "updated": "",
         "ratio": ratio if ratio in SIZES else "9:16", "style": str(style or "知识科普")[:40],
         "target_seconds": max(10, min(600, int(target_seconds or 60))), "topic": str(topic or "")[:4000],
         "bgm_prompt": "", "shots": [],
         "settings": {"subtitle": True, "bgm_volume": 0.18, "kenburns": True,
                      "voice": voice or {"engine": "local", "mode": "preset", "speaker": "Vivian", "label": "Vivian"}},
         "steps": {k: {"st": "idle", "msg": "", "err": "", "pct": 0, "t0": 0, "t1": 0} for k in ("plan", "images", "tts", "bgm", "video")},
         "files": {}, "cost": {"images_usd": 0.0, "tts_cny": 0.0}, "st": "idle", "error": ""}
    save_project(p)
    return load_project(pid)


def list_projects() -> list:
    out = []
    try:
        dirs = sorted(projects_root().iterdir(), key=lambda x: x.name, reverse=True)
    except OSError:
        return out
    for d in dirs:
        if not d.is_dir() or not (d / PROJECT_FILE).exists():
            continue
        try:
            p = json.loads((d / PROJECT_FILE).read_text("utf-8"))
        except Exception:
            continue
        video = d / "output" / "成片.mp4"
        out.append({"id": d.name, "name": p.get("name") or d.name, "title": p.get("title") or "",
                    "created": p.get("created") or "", "ratio": p.get("ratio") or "9:16",
                    "st": p.get("st") or "idle", "shots": len(p.get("shots") or []),
                    "video": video.exists(), "video_mtime": video.stat().st_mtime if video.exists() else 0})
    return out


def _rel(d: Path, p: Path) -> str:
    return p.resolve().relative_to(d.resolve()).as_posix()


def _abs(d: Path, rel: str) -> Path:
    q = (d / str(rel or "")).resolve()
    base = d.resolve()
    if q != base and base not in q.parents:
        raise MakerError("文件不在这个项目里")
    return q


# ---------------- 合成 ----------------
def _zoom_expr(i: int) -> tuple:
    """三种镜头：推近、拉远、横向微移。返回 (z, x, y) 表达式（zoompan）。"""
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    mode = i % 3
    if mode == 0:
        return "min(1.10,1.0+0.0016*on)", cx, cy
    if mode == 1:
        return "if(eq(on,0),1.10,max(1.0,zoom-0.0016))", cx, cy
    return "1.06", "(iw-iw/zoom)*min(on/90,1)", cy


def _srt_escape(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def compose_video(project_dir, srt=True, bgm_volume=0.18, kenburns=True, stopped=None, progress=None,
                 duck_depth=0.16, fade=2.0, project=None) -> dict:
    """把项目文件夹里的素材合成 output/成片.mp4。

    stopped() 返回真 → 结束自己开的 ffmpeg，返回 {"stopped": True}。
    progress({"stage": "compose", "pct": 0~100, "msg": "..."}) 实时回报。
    project 给了就用这份内存里的工程（节点图混流用），不再读 project.json。
    """
    d = Path(project_dir).resolve()
    p = project if isinstance(project, dict) else json.loads((d / PROJECT_FILE).read_text("utf-8"))
    say = progress or (lambda _x: None)
    stop = stopped or (lambda: False)
    t0 = time.time()
    ratio = p.get("ratio") if p.get("ratio") in SIZES else "9:16"
    W, H = SIZES[ratio]
    shots = p.get("shots") or []
    if not shots:
        raise MakerError("还没有分镜：先点「AI 拆解分镜」")
    voice_p = _abs(d, (p.get("files") or {}).get("voice") or "tts/voice.wav")
    srt_p = _abs(d, (p.get("files") or {}).get("srt") or "tts/subtitles.srt")
    use_bgm = (p.get("settings") or {}).get("use_bgm", True) is not False
    bgm_rel = (p.get("files") or {}).get("bgm") or ("bgm/bgm.wav" if use_bgm else "")
    bgm_p = _abs(d, bgm_rel) if bgm_rel else None
    if not voice_p.exists() and not srt_p.exists():
        raise MakerError("还没有配音：先点「配音」或「一键全自动」")

    # 每个分镜用哪一轨：网页动效视频 / PPT 卡片图 / 生图（GIF 也能当动态轨）；缺失就循环用已有的
    visuals = []
    for s in shots:
        v = None
        q = s.get("render_clip") or ""
        if q and _abs(d, q).exists():
            v = {"kind": "video", "path": _abs(d, q)}
        if v is None:
            q = s.get("render_image") or s.get("image") or ""
            if q and _abs(d, q).exists():
                v = {"kind": "video" if str(q).lower().endswith(".gif") else "image", "path": _abs(d, q)}
        if v and v["kind"] == "image" and v["path"].suffix.lower() == ".svg":
            png = v["path"].with_name(v["path"].stem + "_raster.png")
            try:
                from . import render_web
                render_web.rasterize_svg(v["path"], png, W, H)
            except Exception as e:
                raise MakerError(f"SVG 贴纸转画面失败：{str(e)[:160]}") from None
            v = {"kind": "image", "path": png}
        visuals.append(v)
    have = [x for x in visuals if x]
    if not have:
        raise MakerError("还没有画面：先点「生图」、网页动效或 PPT 卡片")
    rr = 0
    for i in range(len(visuals)):
        if visuals[i] is None:
            visuals[i] = have[rr % len(have)]
            rr += 1

    # 每段时长：优先用配音段的时间轴（start/end），没有就按 duration / 预估
    spans, seg_sum = [], 0.0
    for s in shots:
        try:
            a, b = float(s.get("start") or 0), float(s.get("end") or 0)
        except (TypeError, ValueError):
            a = b = 0.0
        dur = b - a if b > a else float(s.get("duration") or s.get("seconds_hint") or 5.0)
        dur = max(1.0, min(120.0, dur))
        spans.append(dur)
        seg_sum += dur
    vd = duration_of(voice_p) if voice_p.exists() else 0.0
    total = max(seg_sum, vd)
    if total <= 0:
        raise MakerError("算不出成片多长：配音文件可能是坏的")

    ff = ffmpeg_exe()
    out = d / "output" / "成片.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name("成片.part.mp4")
    for x in (tmp,):
        try:
            x.unlink()
        except FileNotFoundError:
            pass

    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]
    for v in visuals:
        if v["kind"] == "video":
            cmd += ["-stream_loop", "-1", "-i", str(v["path"])]
        else:
            cmd += ["-i", str(v["path"])]
    vi = None
    if voice_p.exists():
        vi = len(visuals)
        cmd += ["-i", str(voice_p)]
    bi = None
    if bgm_p is not None and bgm_p.exists() and bgm_volume > 0:
        bi = len(visuals) + (1 if vi is not None else 0)
        cmd += ["-stream_loop", "-1", "-i", str(bgm_p)]

    parts, labels = [], []
    for i, (v, dur) in enumerate(zip(visuals, spans)):
        frames = max(2, int(round(dur * FPS)))
        if v["kind"] == "video":
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
                  f"trim=duration={dur:.3f},setpts=PTS-STARTPTS,setsar=1,format=yuv420p")
        elif kenburns:
            z, x, y = _zoom_expr(i)
            vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                  f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p")
        else:
            vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                  f"zoompan=z='1.0':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p")
        parts.append(f"[{i}:v]{vf}[v{i}]")
        labels.append(f"[v{i}]")
    parts.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vc]")
    vout = "[vc]"
    extra = total - seg_sum
    if extra > 0.05:
        parts.append(f"[vc]tpad=stop_mode=clone:stop_duration={extra:.3f}[vp]")
        vout = "[vp]"
    if srt and srt_p.exists():
        fs = 18 if H > W else 22
        mv = 76 if H > W else 42
        style = (f"FontName=Microsoft YaHei,FontSize={fs},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                 f"BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV={mv}")
        parts.append(f"{vout}subtitles='{_srt_escape(srt_p)}':force_style='{style}'[vs]")
        vout = "[vs]"

    audio = None
    if vi is not None and bi is not None:
        parts.append(f"[{vi}:a]aresample=48000,apad,asplit=2[va][vsc]")
        parts.append(f"[{bi}:a]aresample=48000,volume={max(0.0, float(bgm_volume)):.3f},afade=t=in:st=0:d=0.6[b0]")
        ratio = max(1.0, min(20.0, 2.0 + max(0.0, min(1.0, float(duck_depth))) * 30.0))
        parts.append(f"[b0][vsc]sidechaincompress=threshold=0.03:ratio={ratio:.1f}:attack=30:release=550[bd]")
        fad = max(0.0, min(6.0, float(fade)))
        fo = max(0.0, total - fad)
        parts.append(f"[va][bd]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={fo:.3f}:d={max(0.1, fad):.1f}[a]")
        audio = "[a]"
    elif vi is not None:
        parts.append(f"[{vi}:a]aresample=48000,apad[a]")
        audio = "[a]"
    elif bi is not None:
        fad = max(0.0, min(6.0, float(fade)))
        fo = max(0.0, total - fad)
        parts.append(f"[{bi}:a]aresample=48000,volume={max(0.0, float(bgm_volume)):.3f},"
                     f"afade=t=in:st=0:d=0.6,afade=t=out:st={fo:.3f}:d={max(0.1, fad):.1f}[a]")
        audio = "[a]"
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
        ai = len(visuals) + (1 if vi is not None else 0) + (1 if bi is not None else 0)
        parts.append(f"[{ai}:a]atrim=duration={total:.3f}[a]")
        audio = "[a]"

    cmd += ["-filter_complex", ";".join(parts), "-map", vout, "-map", audio,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", str(tmp)]
    say({"stage": "compose", "pct": 0, "msg": f"开始合成：{len(visuals)} 个分镜、{total:.1f} 秒、{W}×{H}"})
    errs = []

    def read_err(pipe):
        try:
            for line in pipe:
                errs.append(line.rstrip())
                if len(errs) > 80:
                    del errs[:20]
        except Exception:
            pass

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", creationflags=NOWIN)
    except OSError as e:
        raise MakerError(f"ffmpeg 起不来：{e}") from None
    th = threading.Thread(target=read_err, args=(proc.stderr,), daemon=True)
    th.start()
    stopped_hit = False
    try:
        for line in proc.stdout:
            if stop():
                stopped_hit = True
                try:
                    proc.terminate()
                except Exception:
                    pass
                break
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                    pct = max(0.0, min(99.0, us / 1e6 / total * 100))
                    say({"stage": "compose", "pct": round(pct, 1), "msg": f"正在合成视频：{pct:.0f}%"})
                except ValueError:
                    pass
            elif line.startswith("frame="):
                try:
                    say({"stage": "compose", "pct": None, "frame": int(line.split("=", 1)[1])})
                except ValueError:
                    pass
            elif line.startswith("fps="):
                try:
                    say({"stage": "compose", "pct": None, "fps": round(float(line.split("=", 1)[1]), 1)})
                except ValueError:
                    pass
            elif line == "progress=end":
                say({"stage": "compose", "pct": 99.0, "msg": "收尾中……"})
        if stopped_hit:
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
        rc = proc.wait()
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
    if stopped_hit or stop():
        try:
            tmp.unlink()
        except OSError:
            pass
        return {"stopped": True, "sec": round(time.time() - t0, 1), "msg": "停了：没合成完，成片没保存"}
    if rc != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        try:
            tmp.unlink()
        except OSError:
            pass
        why = "\n".join(errs[-12:])[-1200:] or f"ffmpeg 退出码 {rc}"
        raise MakerError("ffmpeg 没合成成：\n" + why)
    try:
        out.unlink()
    except FileNotFoundError:
        pass
    tmp.replace(out)
    info = mediainfo.probe(out)
    cover = _cover(ff, out, d / "output" / "封面.png", W, H, min(1.0, total / 2))
    sec = time.time() - t0
    say({"stage": "compose", "pct": 100, "msg": "合成好了"})
    telemetry.log("proc", "compose_video", "视频工坊", "ok", sec * 1000,
                  {"shots": len(visuals), "seconds": round(total, 1), "w": info.get("w"), "h": info.get("h"),
                   "bgm": bool(bi), "srt": bool(srt and srt_p.exists())}, f"成片合成好了 · {total:.1f} 秒 · {time.time() - t0:.0f} 秒")
    return {"stopped": False, "path": str(out), "rel": _rel(d, out), "cover": str(cover) if cover else "",
            "cover_rel": _rel(d, cover) if cover else "", "duration": info.get("duration") or total,
            "w": info.get("w") or W, "h": info.get("h") or H, "sec": round(sec, 1), "bytes": out.stat().st_size}


def _cover(ff, video: Path, dest: Path, W: int, H: int, at: float):
    try:
        r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, at):.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                            "-q:v", "2", str(dest)], capture_output=True, creationflags=NOWIN)
        return dest if r.returncode == 0 and dest.exists() and dest.stat().st_size > 1000 else None
    except OSError:
        return None


def stop_running(proc):
    """给外面（Studio.stop）用的兜底：结束 ffmpeg 进程树。"""
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
