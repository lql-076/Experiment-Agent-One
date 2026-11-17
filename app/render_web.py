r"""网页动效渲染轨道（v3.8 起，v3.8.1 加轨道缓存）。

用 Playwright 无头 Chromium 把一条分镜渲染成短视频轨：
- 深色毛玻璃底板、缓慢粒子 / 光影、按 timeline 高亮的字幕；
- 有 Q 版 GIF 时，叠加带白边圆角贴纸的 GIF 空间位移动画层；
- 支持背景风格、字幕位置 / 字号 / 配色、GIF 缩放、动效强度；
- 每帧截图直接 pipe 给 ffmpeg，生成 H.264 MP4（无音轨），由 video_maker 最终混流。

没有浏览器 / Playwright 时抛 RenderWebError，视频工坊会降级回静态分镜 Ken Burns，不阻塞整条流水线。
"""
import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VIRTUAL_TIME = r"""
(() => {
  if (window.__vt) return;
  const vt = window.__vt = { now: 0, raf: [], timers: [], id: 1, t0: Date.now() };
  const RealDate = Date;
  class VDate extends RealDate { constructor(...a) { if (a.length) super(...a); else super(vt.t0 + vt.now); } static now() { return vt.t0 + vt.now; } }
  window.Date = VDate;
  performance.now = () => vt.now;
  window.requestAnimationFrame = cb => { const id = vt.id++; vt.raf.push({ id, cb }); return id; };
  window.cancelAnimationFrame = id => { vt.raf = vt.raf.filter(x => x.id !== id); };
  const add = (cb, ms, rep, args) => { const id = vt.id++; vt.timers.push({ id, cb, at: vt.now + Math.max(0, +ms || 0), every: rep ? Math.max(1, +ms || 1) : 0, args }); return id; };
  window.setTimeout = (cb, ms, ...a) => add(cb, ms, false, a);
  window.setInterval = (cb, ms, ...a) => add(cb, ms, true, a);
  window.clearTimeout = window.clearInterval = id => { vt.timers = vt.timers.filter(x => x.id !== id); };
  vt.step = (to) => {
    for (let guard = 0; guard < 10000; guard++) {
      const due = vt.timers.filter(x => x.at <= to).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      vt.now = due.at;
      if (due.every) due.at += due.every; else vt.timers = vt.timers.filter(x => x !== due);
      try { typeof due.cb === 'function' ? due.cb(...(due.args || [])) : (0, eval)(String(due.cb)); } catch (e) {}
    }
    vt.now = to;
    const q = vt.raf; vt.raf = [];
    for (const x of q) { try { x.cb(vt.now); } catch (e) {} }
    try { for (const a of document.getAnimations()) { a.pause(); a.currentTime = vt.now; } } catch (e) {}
    if (typeof window.seek === 'function') { try { window.seek(vt.now / 1000); } catch (e) {} }
  };
})();
"""


class RenderWebError(RuntimeError):
    pass


def _data_uri(p: Path) -> str:
    ext = p.suffix.lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "webp": "webp", "gif": "gif", "png": "png"}.get(ext, "png")
    return f"data:image/{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _bg(name):
    name = str(name or "dark")
    return {
        "dark": ("#060a12", "#0b1a2a", "rgba(18,38,56,.72)", "#eaffff", "#8fd8ff"),
        "tech": ("#03121e", "#072a3a", "rgba(8,48,64,.78)", "#dffcff", "#38f2d0"),
        "warm": ("#1a0d08", "#2b1510", "rgba(64,30,20,.72)", "#fff2dd", "#ffb46b"),
        "light": ("#eef4f7", "#dce8ee", "rgba(255,255,255,.72)", "#102330", "#0b6b8a"),
    }.get(name, ("#060a12", "#0b1a2a", "rgba(18,38,56,.72)", "#eaffff", "#8fd8ff"))


def _html(shot, W, H, settings):
    bg = _bg(settings.get("web_bg"))
    text = str(shot.get("text") or "")
    role = str(shot.get("role") or "")
    tone = str(shot.get("tone") or "")
    pos = str(settings.get("web_sub_pos") or "bottom")
    size = max(20, min(96, int(settings.get("web_sub_size") or (56 if H > W else 38))))
    color = str(settings.get("web_sub_color") or bg[3])
    gif_scale = max(.4, min(2.2, float(settings.get("web_gif_scale") or 1)))
    motion = max(0, min(2, float(settings.get("web_motion") if settings.get("web_motion") is not None else 1)))
    img = None
    for key in ("gif", "render_image", "image", "img"):
        q = shot.get(key)
        if q and Path(str(q)).is_file():
            img = Path(str(q))
            break
    style = f"""
    :root{{--bg1:{bg[0]};--bg2:{bg[1]};--glass:{bg[2]};--fg:{bg[3]};--accent:{bg[4]};}}
    *{{box-sizing:border-box}} html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:var(--bg1);color:var(--fg)}}
    body{{position:relative}}
    .bg{{position:absolute;inset:-10%;background:
      radial-gradient(circle at 20% 15%,color-mix(in srgb,var(--accent) 22%,transparent),transparent 34%),
      radial-gradient(circle at 82% 78%,color-mix(in srgb,var(--accent) 16%,transparent),transparent 38%),
      linear-gradient(135deg,var(--bg1),var(--bg2));}}
    .grid{{position:absolute;inset:0;opacity:.16;background-image:linear-gradient(color-mix(in srgb,var(--accent) 28%,transparent) 1px,transparent 1px),linear-gradient(90deg,color-mix(in srgb,var(--accent) 28%,transparent) 1px,transparent 1px);background-size:64px 64px;transform:perspective(900px) rotateX(56deg) translateY(22%);transform-origin:center bottom}}
    .glass{{position:absolute;left:6%;right:6%;top:12%;bottom:22%;border:1px solid color-mix(in srgb,var(--accent) 34%,transparent);background:var(--glass);backdrop-filter:blur(14px);border-radius:28px;box-shadow:0 24px 80px rgba(0,0,0,.32),inset 0 0 60px color-mix(in srgb,var(--accent) 7%,transparent)}}
    .role{{position:absolute;left:10%;top:17%;font-size:{max(18,size*.45)}px;letter-spacing:.14em;color:var(--accent);border:1px solid color-mix(in srgb,var(--accent) 50%,transparent);padding:.35em .7em;border-radius:999px;background:color-mix(in srgb,var(--accent) 9%,transparent)}}
    .tone{{position:absolute;right:10%;top:17%;font-size:{max(14,size*.32)}px;color:color-mix(in srgb,var(--fg) 58%,transparent)}}
    .stage{{position:absolute;left:10%;right:10%;top:34%;bottom:30%;display:flex;align-items:center;justify-content:center}}
    .gif{{max-width:82%;max-height:100%;border-radius:24px;border:6px solid rgba(255,255,255,.88);box-shadow:0 22px 60px rgba(0,0,0,.38);transform:scale({gif_scale});}}
    .sub{{position:absolute;left:7%;right:7%;{('bottom:10%' if pos == 'bottom' else 'top:45%' if pos == 'center' else 'top:8%')};text-align:center;font-size:{size}px;line-height:1.35;font-weight:700;color:{color};text-shadow:0 3px 0 rgba(0,0,0,.55),0 0 24px color-mix(in srgb,var(--accent) 45%,transparent);letter-spacing:.02em}}
    .sub span{{transition:color .08s linear,transform .08s linear;display:inline-block}}
    .sub span.on{{color:var(--accent);transform:translateY(-.06em)}}
    .particle{{position:absolute;width:6px;height:6px;border-radius:50%;background:var(--accent);opacity:.55;filter:blur(.3px)}}
    .vignette{{position:absolute;inset:0;background:radial-gradient(circle at 50% 45%,transparent 38%,rgba(0,0,0,.34));}}
    </style>"""
    spans = "".join(f'<span data-i="{i}">{_esc(ch)}</span>' for i, ch in enumerate(text))
    parts = "".join(f'<i class="particle" style="left:{(i*37)%94}%;top:{(i*53)%88}%;animation-delay:{(i%9)*.4}s"></i>' for i in range(18))
    img_tag = f'<img class="gif" src="{_data_uri(img)}" alt="">' if img else ''
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{style}</style></head><body>
<div class="bg"></div><div class="grid"></div>{parts}<div class="vignette"></div>
<div class="glass"></div><div class="role">{_esc(role or '旁白')}</div><div class="tone">{_esc(tone)}</div>
<div class="stage">{img_tag}</div><div class="sub" id="sub">{spans}</div>
<script>
const TOTAL = {max(.2, float(shot.get('duration') or 5))};
const N = {len(text)};
window.seek = function(t) {{
  const p = Math.max(0, Math.min(1, t / TOTAL));
  const k = Math.min(N - 1, Math.floor(p * N));
  document.querySelectorAll('#sub span').forEach((e,i) => e.classList.toggle('on', i <= k));
  const img = document.querySelector('.gif');
  if (img) {{ img.style.transform = 'scale({gif_scale}) translate(' + (Math.sin(t*1.4)*{10*motion}) + 'px,' + (Math.cos(t*1.1)*{8*motion}) + 'px) rotate(' + (Math.sin(t*.9)*{1.2*motion}) + 'deg)'; }}
  document.querySelectorAll('.particle').forEach((e,i) => {{ e.style.transform = 'translate(0,' + (-(t*{6+18*motion} + i*2)%120) + 'px)'; }});
}};
</script></body></html>"""


def rasterize_svg(svg_path, png_path, W, H):
    """把 SVG 贴纸/图标渲染成 PNG，给 FFmpeg 当静态画面（最终视频不直接吃 SVG）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RenderWebError("没装 Playwright，SVG 不能转成画面") from None
    svg_path, png_path = Path(svg_path), Path(png_path)
    with sync_playwright() as pw:
        br = _open_browser(pw)
        page = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.goto(svg_path.resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(200)
        page.screenshot(path=str(png_path), type="png")
        br.close()
    return png_path


def _ffmpeg():
    from .video_maker import ffmpeg_exe
    return ffmpeg_exe()


def _open_browser(pw):
    exe = os.environ.get("AGENT_CHROMIUM")
    tries = ([{"executable_path": exe}] if exe else []) + ([{"channel": "msedge"}, {"channel": "chrome"}] if os.name == "nt" else []) + [{}]
    err = None
    for kw in tries:
        try:
            return pw.chromium.launch(headless=True, args=["--hide-scrollbars", "--force-color-profile=srgb", "--allow-file-access-from-files"], **kw)
        except Exception as e:
            err = e
    raise RenderWebError(f"网页渲染的浏览器没打开：{str(err)[:200]}")


def render_shot(project_dir, shot, settings, out_path, W, H, fps=24, stopped=None) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RenderWebError("没装 Playwright：pip install playwright（浏览器用电脑上的 Edge / Chrome）") from None
    d = Path(project_dir)
    render_dir = d / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    shot = dict(shot)
    for k in ("gif", "render_image", "image", "img"):
        q = shot.get(k)
        if q and not Path(str(q)).is_absolute():
            shot[k] = str(d / str(q))
    html = _html(shot, W, H, settings or {})
    hp = render_dir / (Path(out_path).stem + ".html")
    hp.write_text(html, "utf-8")
    dur = max(.2, float(shot.get("duration") or 5))
    n = max(2, int(round(dur * fps)))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part.mp4")
    cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps),
           "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", "-t", f"{dur:.3f}", str(tmp)]
    with sync_playwright() as pw:
        br = _open_browser(pw)
        page = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.add_init_script(VIRTUAL_TIME)
        page.goto(hp.resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(250)
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=NOWIN)
        try:
            for i in range(n):
                if stopped and stopped():
                    raise RenderWebError("停下了：网页渲染没做完")
                page.evaluate("t => window.__vt.step(t)", (i / fps) * 1000)
                ff.stdin.write(page.screenshot(type="jpeg", quality=92))
        except BrokenPipeError:
            pass
        finally:
            try:
                ff.stdin.close()
            except OSError:
                pass
        code = ff.wait()
        br.close()
    if code != 0 or not tmp.is_file():
        raise RenderWebError(f"网页渲染的 ffmpeg 没合成成（退出码 {code}）")
    tmp.replace(out)
    return out


def render_all(project_dir, project, say=None, stopped=None) -> dict:
    """渲染所有 render=web 的分镜；返回 {shot_id: 相对路径}。命中内容寻址缓存直接复用。"""
    from . import studio_cache as cache
    say = say or (lambda _m: None)
    d = Path(project_dir)
    settings = project.get("settings") or {}
    W, H = (1080, 1920) if project.get("ratio") != "16:9" else (1920, 1080)
    fps = int(settings.get("web_fps") or 24)
    out = {}
    shots = [s for s in (project.get("shots") or []) if s.get("render") == "web"]
    cfg = {k: settings.get(k) for k in ("web_bg", "web_sub_pos", "web_sub_size", "web_sub_color", "web_gif_scale", "web_motion", "web_fps")}
    for i, s in enumerate(shots):
        if stopped and stopped():
            raise RenderWebError("停下了")
        say(f"网页动效渲染 {i + 1}/{len(shots)}：第 {s.get('n') or s.get('id')} 镜")
        p = d / "render" / f"web_{s['id']}.mp4"
        src = s.get("gif") or s.get("render_image") or s.get("image") or ""
        sp = (d / src) if src and not Path(str(src)).is_absolute() else Path(str(src or ""))
        src_sha = cache.sha_file(sp) if sp.is_file() else ""
        fp = cache.fingerprint("track_web", {"image_sha": src_sha, "text": s.get("text") or "", "role": s.get("role") or "",
                                             "tone": s.get("tone") or "", "duration": float(s.get("duration") or 5),
                                             "start": float(s.get("start") or 0), "end": float(s.get("end") or 0),
                                             "w": W, "h": H, "fps": fps, "cfg": cfg})
        if cache.hit_to(fp, p, "tracks"):
            s["render_cache_hit"] = True
            s["render_clip"] = f"render/{p.name}"
            out[s["id"]] = s["render_clip"]
            continue
        s["render_cache_hit"] = False
        render_shot(d, s, settings, p, W, H, fps, stopped)
        cache.put(fp, p, "tracks", {"type": "web", "w": W, "h": H, "fps": fps})
        s["render_clip"] = f"render/{p.name}"
        out[s["id"]] = s["render_clip"]
    return out
