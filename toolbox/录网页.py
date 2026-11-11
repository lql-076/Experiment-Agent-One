"""把一个网页动画录成视频（一帧一帧截图再合成，不掉帧；也能只截一张图检查画面）"""
# 用法（在工作文件夹里）：
#   python 工具箱\录网页.py 片头\index.html 片头\画面.mp4 --seconds 10
#   python 工具箱\录网页.py 片头\index.html 片头\检查.png --png 3.5          只截第 3.5 秒的一张图（先用它检查，再录整段）
# 常用参数：--fps 30  --size 1920x1080  --audio 配音.wav（顺手把声音合进去）  --start 0（从第几秒开始录，长视频分段录）
#
# 网页怎么写才录得准：
#   1. 最稳：网页里写一个 window.seek(t) 函数，把画面摆成第 t 秒的样子（t 是秒）。录的时候每一帧调一次。
#   2. 没写 seek 也行：这个脚本会接管页面里的时间（requestAnimationFrame、setTimeout、Date.now、CSS 动画、Web Animations），
#      一帧一帧往前拨。所以网页按平常的写法做动画就可以，但不要依赖真实的时钟、不要放视频标签。
#   3. 画面大小就是 --size，网页里按这个尺寸排版（body 不要有滚动条）。字体用系统自带的（微软雅黑：font-family:"Microsoft YaHei"）。
# 第一次用要装：pip install playwright imageio-ffmpeg（浏览器用电脑上的 Edge，不用另外下）
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

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
      try { typeof due.cb === 'function' ? due.cb(...(due.args || [])) : (0, eval)(String(due.cb)); } catch (e) { console.error(e); }
    }
    vt.now = to;
    const q = vt.raf; vt.raf = [];
    for (const x of q) { try { x.cb(vt.now); } catch (e) { console.error(e); } }
    try { for (const a of document.getAnimations()) { a.pause(); a.currentTime = vt.now; } } catch (e) {}
    if (typeof window.seek === 'function') { try { window.seek(vt.now / 1000); } catch (e) { console.error(e); } }
  };
})();
"""


def ffmpeg_exe():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("没找到 ffmpeg：先运行 pip install imageio-ffmpeg")


def open_browser(pw):
    exe = os.environ.get("AGENT_CHROMIUM")
    tries = ([{"executable_path": exe}] if exe else []) + ([{"channel": "msedge"}, {"channel": "chrome"}] if os.name == "nt" else []) + [{}]
    err = None
    for kw in tries:
        try:
            return pw.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--force-color-profile=srgb", "--hide-scrollbars"], **kw)
        except Exception as e:
            err = e
    sys.exit(f"浏览器没打开：{str(err)[:200]}\n电脑上要有 Edge（Windows 自带）。")


def main():
    ap = argparse.ArgumentParser(description="把网页动画录成视频，或者截其中一秒的画面")
    ap.add_argument("page", help="网页文件（相对当前文件夹）或 http 网址")
    ap.add_argument("out", help="输出：.mp4 录视频；.png 截一张图")
    ap.add_argument("--seconds", type=float, default=0, help="录多少秒（录视频必填）")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", default="1920x1080", help="画面大小，宽x高")
    ap.add_argument("--start", type=float, default=0, help="从动画的第几秒开始录")
    ap.add_argument("--png", type=float, default=None, help="只截第几秒的一张图（out 写 .png）")
    ap.add_argument("--audio", default="", help="顺手合进去的声音文件")
    ap.add_argument("--wait", type=int, default=300, help="打开网页后等多少毫秒再开始（等字体、图片）")
    ap.add_argument("--crf", type=int, default=18, help="画质，越小越清楚（15~23）")
    ap.add_argument("--transparent", action="store_true", help="截图时背景透明（只对 --png 有用）")
    a = ap.parse_args()
    try:
        w, h = (int(x) for x in a.size.lower().replace("×", "x").split("x"))
    except ValueError:
        sys.exit("--size 写成 1920x1080 这样")
    out = Path(a.out)
    shot = a.png is not None or out.suffix.lower() in (".png", ".jpg", ".jpeg")
    if not shot and a.seconds <= 0:
        sys.exit("录视频要写 --seconds 多少秒")
    if not shot and (w % 2 or h % 2):
        sys.exit("录视频的宽和高要是偶数")
    url = a.page if a.page.startswith(("http://", "https://")) else Path(a.page).resolve().as_uri()
    if not a.page.startswith(("http://", "https://")) and not Path(a.page).is_file():
        sys.exit(f"没有这个网页文件：{a.page}")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("先运行 pip install playwright（浏览器用电脑上的 Edge，不用 playwright install）")
    t0 = time.time()
    with sync_playwright() as pw:
        br = open_browser(pw)
        page = br.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)[:200]))
        page.add_init_script(VIRTUAL_TIME)
        page.goto(url, wait_until="load")
        page.wait_for_timeout(a.wait)                      # 这段是真实时间：等字体和图片
        try:
            page.evaluate("document.fonts && document.fonts.ready")
        except Exception:
            pass
        if shot:
            t = a.png if a.png is not None else a.start
            page.evaluate("t => window.__vt.step(t)", t * 1000)
            page.screenshot(path=str(out), omit_background=a.transparent, type="png" if out.suffix.lower() == ".png" else "jpeg")
            br.close()
            print(f"截好了：{out}（第 {t:g} 秒，{w}×{h}）" + (f"\n网页里有报错：{errs[0]}" if errs else ""))
            return
        n = max(1, round(a.seconds * a.fps))
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(a.fps), "-c:v", "mjpeg", "-i", "-"]
        if a.audio:
            if not Path(a.audio).is_file():
                sys.exit(f"没有这个声音文件：{a.audio}")
            cmd += ["-i", a.audio]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-r", str(a.fps), "-movflags", "+faststart"]
        if a.audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-t", f"{a.seconds:.3f}", str(out)]
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        last = 0.0
        try:
            for i in range(n):
                page.evaluate("t => window.__vt.step(t)", (a.start + i / a.fps) * 1000)
                ff.stdin.write(page.screenshot(type="jpeg", quality=95))
                if time.time() - last > 5:
                    last = time.time()
                    print(f"进度 {i + 1}/{n} 帧", flush=True)
        except BrokenPipeError:
            pass
        finally:
            try:
                ff.stdin.close()
            except OSError:
                pass
        code = ff.wait()
        br.close()
    if code != 0 or not out.exists():
        sys.exit(f"ffmpeg 合成没成（退出码 {code}）")
    print(f"录好了：{out}（{a.seconds:g} 秒，{n} 帧，{w}×{h}，{a.fps} 帧/秒，用了 {time.time() - t0:.0f} 秒）" + (f"\n网页里有报错（画面可能不对）：{errs[0]}" if errs else ""))


if __name__ == "__main__":
    main()
