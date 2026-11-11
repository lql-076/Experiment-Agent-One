"""让一张角色图跟着配音张嘴、眨眼（差分图：闭嘴、半张、张嘴、闭眼），出一段能叠在画面上的角色视频，或者直接叠到画面上"""
# 用法（在工作文件夹里）：
#   python 工具箱\口型.py --voice 配音\旁白.wav --closed 白页_闭嘴.png --open 白页_张嘴.png --out 片头\白页.mov
#   python 工具箱\口型.py --voice 配音\旁白.wav --closed 闭嘴.png --half 半张.png --open 张嘴.png --blink 闭眼.png --bg 片头\画面.mp4 --pos 1380:420 --height 620 --out 片头\带角色.mp4
# 怎么切：按配音的音量——安静 = 闭嘴，小声 = 半张（没有半张的图就用张嘴），大声 = 张嘴；隔 3~5 秒眨一下眼（给了 --blink 才眨）。
# 几张差分图要一样大、角色位置一样（同一张定稿图改出来的）。--out 写 .mov 是透明底的角色视频（以后自己叠）；给了 --bg 就直接叠到那段画面上，出 .mp4。
# 第一次用要装：pip install imageio-ffmpeg
import argparse
import array
import random
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


def ffmpeg_exe():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("没找到 ffmpeg：先运行 pip install imageio-ffmpeg")


def levels(wav, fps):
    """每一帧的音量（0~1，按整段最响的地方算）。"""
    try:
        w = wave.open(str(wav), "rb")
    except (wave.Error, EOFError):
        sys.exit("配音要 WAV 文件（16 位）")
    with w:
        if w.getsampwidth() != 2:
            sys.exit("配音要 16 位的 WAV")
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        a = array.array("h")
        a.frombytes(w.readframes(n))
    if sys.byteorder == "big":
        a.byteswap()
    step = max(1, int(sr / fps)) * ch
    out = []
    for i in range(0, len(a), step):
        seg = a[i:i + step:max(1, len(a[i:i + step]) // 400)]          # 每帧抽 400 个点算就够了
        out.append((sum(x * x for x in seg) / max(1, len(seg))) ** 0.5)
    top = sorted(out)[int(len(out) * 0.97)] if out else 0
    return [min(1.0, x / top) if top > 0 else 0.0 for x in out], len(a) / ch / sr


def main():
    ap = argparse.ArgumentParser(description="差分图跟着配音张嘴、眨眼")
    ap.add_argument("--voice", required=True)
    ap.add_argument("--closed", required=True, help="闭嘴的图")
    ap.add_argument("--open", required=True, help="张嘴的图")
    ap.add_argument("--half", default="", help="半张嘴的图（可以不给）")
    ap.add_argument("--blink", default="", help="闭眼的图（可以不给）")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--bg", default="", help="直接叠到这段画面上")
    ap.add_argument("--pos", default="0:0", help="叠在画面的哪（左上角 x:y）")
    ap.add_argument("--height", type=int, default=0, help="角色缩到多高（像素）；不写就原大小")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    for f in [a.voice, a.closed, a.open] + [x for x in (a.half, a.blink, a.bg) if x]:
        if not Path(f).is_file():
            sys.exit(f"没有这个文件：{f}")
    ff = ffmpeg_exe()
    lv, dur = levels(a.voice, a.fps)
    n = len(lv)
    if not n:
        sys.exit("配音是空的")
    for i in range(1, n - 1):                              # 平滑一下：单独一帧的跳变抹掉，嘴不乱抖
        if lv[i - 1] < 0.12 and lv[i + 1] < 0.12:
            lv[i] = min(lv[i], 0.1)
    state = ["open" if x > 0.42 else "half" if x > 0.12 else "closed" for x in lv]
    hold = max(2, a.fps // 12)                             # 一个嘴型至少停两三帧
    for i in range(1, n):
        if state[i] != state[i - 1] and i >= hold and len(set(state[i - hold:i])) > 1:
            state[i] = state[i - 1]
    if a.blink:
        rnd, t = random.Random(a.seed), 2.0
        while t < dur:
            k = next((j for j in range(int(t * a.fps), min(n, int((t + 1.2) * a.fps))) if state[j] == "closed"), None)   # 等到闭嘴的时候再眨（闭眼那张是闭着嘴的）
            if k is not None:
                for j in range(k, min(n, k + max(2, a.fps // 8))):
                    if state[j] == "closed":
                        state[j] = "blink"
            t += rnd.uniform(2.8, 5.2)
    pic = {"closed": a.closed, "open": a.open, "half": a.half or a.open, "blink": a.blink or a.closed}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="kx_", dir=str(out.parent)))
    try:
        lst, runs = tmp / "list.txt", []
        for s in state:                                    # 连着一样的并成一段
            if runs and runs[-1][0] == s:
                runs[-1][1] += 1
            else:
                runs.append([s, 1])
        lines = []
        for s, k in runs:
            lines += [f"file '{Path(pic[s]).resolve().as_posix()}'", f"duration {k / a.fps:.6f}"]
        lines.append(f"file '{Path(pic[runs[-1][0]]).resolve().as_posix()}'")
        lst.write_text("\n".join(lines), "utf-8")
        nw = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        scale = f",scale=-2:{a.height}" if a.height else ""
        if a.bg:
            x, _, y = a.pos.partition(":")
            cmd = [ff, "-y", "-loglevel", "error", "-i", a.bg, "-f", "concat", "-safe", "0", "-i", str(lst), "-i", a.voice, "-filter_complex",
                   f"[1:v]fps={a.fps},format=rgba{scale}[c];[0:v][c]overlay={x or 0}:{y or 0}:eof_action=pass[v]", "-map", "[v]", "-map", "2:a",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
        else:
            if out.suffix.lower() not in (".mov", ".webm"):
                out = out.with_suffix(".mov")
            codec = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30"] if out.suffix.lower() == ".webm" else ["-c:v", "qtrle"]
            cmd = [ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={a.fps},format=rgba{scale}", *codec, "-t", f"{dur:.3f}", str(out)]
        r = subprocess.run(cmd, capture_output=True, creationflags=nw)
        if r.returncode != 0:
            sys.exit("ffmpeg 没成：\n" + r.stderr.decode("utf-8", "replace")[-1200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cnt = {k: sum(1 for s in state if s == k) for k in ("open", "half", "closed", "blink")}
    print(f"好了：{out}（{dur:.1f} 秒，{n} 帧：张嘴 {cnt['open']}、半张 {cnt['half']}、闭嘴 {cnt['closed']}" + (f"、眨眼 {cnt['blink']}" if a.blink else "") + " 帧）")


if __name__ == "__main__":
    main()
