"""把画面、配音、配乐、字幕合成一个视频（几段画面接起来、配乐自动压低、头尾淡入淡出）"""
# 用法（在工作文件夹里）：
#   python 工具箱\合成.py --video 片头\画面.mp4 --voice 片头\配音\旁白.wav --bgm 素材\配乐\轻快.wav --out 片头\成品.mp4
#   python 工具箱\合成.py --video 段1.mp4 段2.mp4 段3.mp4 --out 整条.mp4                 只把几段接起来
# 参数：--bgm-volume 0.16（配乐多大声，有人说话时再自动压低）  --srt 字幕.srt（把字幕烧进画面）  --fade 0.6（头尾淡入淡出几秒）
#       --length voice|video|数字（成品多长：跟配音、跟画面，或者写死几秒；默认跟画面）
# 第一次用要装：pip install imageio-ffmpeg
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
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


def duration(ff, f):
    r = subprocess.run([ff, "-hide_banner", "-i", str(f)], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.search(rb"Duration: (\d+):(\d+):(\d+\.?\d*)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        sys.exit("ffmpeg 没成：\n" + r.stderr.decode("utf-8", "replace")[-1500:])


def main():
    ap = argparse.ArgumentParser(description="合成：画面 + 配音 + 配乐 + 字幕")
    ap.add_argument("--video", nargs="+", required=True, help="画面（一段或几段，几段会按顺序接起来；要一样的大小和帧率）")
    ap.add_argument("--voice", default="", help="配音")
    ap.add_argument("--bgm", default="", help="配乐")
    ap.add_argument("--bgm-volume", type=float, default=0.16)
    ap.add_argument("--srt", default="", help="字幕文件，烧进画面")
    ap.add_argument("--font", default="Microsoft YaHei", help="字幕字体")
    ap.add_argument("--font-size", type=int, default=22)
    ap.add_argument("--fade", type=float, default=0.6)
    ap.add_argument("--length", default="video")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ff = ffmpeg_exe()
    for f in a.video + [x for x in (a.voice, a.bgm, a.srt) if x]:
        if not Path(f).is_file():
            sys.exit(f"没有这个文件：{f}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="hc_", dir=str(out.parent)))
    try:
        video = Path(a.video[0])
        if len(a.video) > 1:                               # 几段接起来（重新编码一遍，免得各段参数不一样接不上）
            ins, n = [], len(a.video)
            for v in a.video:
                ins += ["-i", v]
            flt = "".join(f"[{i}:v:0]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
            video = tmp / "joined.mp4"
            run([ff, "-y", "-loglevel", "error", *ins, "-filter_complex", flt, "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", video])
        vd = duration(ff, video)
        if a.length == "voice" and a.voice:
            total = duration(ff, a.voice) + 0.4
        elif a.length not in ("video", "voice"):
            try:
                total = float(a.length)
            except ValueError:
                sys.exit("--length 写 voice、video 或者秒数")
        else:
            total = vd
        if total <= 0:
            sys.exit("算不出成品多长：画面文件可能是坏的")
        cmd = [ff, "-y", "-loglevel", "error", "-i", video]
        vf, af, amap = [], "", None
        if total > vd + 0.05:
            vf.append(f"tpad=stop_mode=clone:stop_duration={total - vd:.3f}")      # 画面比声音短：最后一帧停住
        if a.srt:
            srt = str(Path(a.srt).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            vf.append(f"subtitles='{srt}':force_style='FontName={a.font},FontSize={a.font_size},Outline=2,Shadow=0,MarginV=42'")
        if a.fade > 0:
            vf.append(f"fade=t=in:st=0:d={a.fade:.2f},fade=t=out:st={max(0, total - a.fade):.2f}:d={a.fade:.2f}")
        k = 1
        if a.voice:
            cmd += ["-i", a.voice]
            vi, k = k, k + 1
        if a.bgm:
            cmd += ["-stream_loop", "-1", "-i", a.bgm]
            bi, k = k, k + 1
        fo = max(0.0, total - max(a.fade, 1.2))
        if a.voice and a.bgm:                               # 有人说话时配乐自动压低（侧链压缩）
            af = (f"[{vi}:a]aresample=48000,apad,asplit=2[v1][v2];[{bi}:a]aresample=48000,volume={a.bgm_volume}[b0];"
                  f"[b0][v2]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=600[b1];"
                  f"[v1][b1]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={fo:.2f}:d={max(a.fade, 1.2):.2f}[a]")
            amap = "[a]"
        elif a.voice:
            af, amap = f"[{vi}:a]aresample=48000,apad[a]", "[a]"
        elif a.bgm:
            af, amap = f"[{bi}:a]aresample=48000,volume={max(a.bgm_volume, 0.5)},afade=t=in:st=0:d=0.8,afade=t=out:st={fo:.2f}:d={max(a.fade, 1.2):.2f}[a]", "[a]"
        fc = (f"[0:v]{','.join(vf)}[v]" if vf else "") + (";" if vf and af else "") + af
        if fc:
            cmd += ["-filter_complex", fc]
        cmd += ["-map", "[v]" if vf else "0:v:0"]
        if amap:
            cmd += ["-map", amap, "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", f"{total:.3f}", out]
        run(cmd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"合成好了：{out}（{total:.1f} 秒" + ("，有配音" if a.voice else "") + ("，有配乐" if a.bgm else "") + ("，字幕烧进画面了" if a.srt else "") + "）")


if __name__ == "__main__":
    main()
