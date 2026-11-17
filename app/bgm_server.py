r"""配乐引擎：Stable Audio 3 Medium（v3.4）。

由后端在「配乐」用到时拉起（`app/bgm.py` 的 `Bgm.ensure`），跑在独立的 `bgm-env` 里：
  bgm-env\Scripts\python.exe app\bgm_server.py --model models\bgm\stable-audio-3-medium --host 127.0.0.1 --port 8094 --log

为什么单独一个进程：
- 模型约 1.4B（DiT）+ SAME-L 自编码器 + T5Gemma，加载要几 GB 显存；后端不背这个包袱。
- 空闲 `bgmIdle` 分钟、打游戏让路时，后端把这个进程关掉，显存就还回去了。

Windows 上的关键点：
- 不装 flash-attn。diffusers 的 `AttnProcessor2_0` 用 PyTorch 原生 SDPA（`F.scaled_dot_product_attention`），
  这里显式把 DiT / VAE 的注意力处理器设成它，避免官方库在缺 flash-attn 时回退不当产生电流杂音。
- 用 bfloat16（显卡支持时）或 float16 加载到 CUDA。
- 8 步对抗蒸馏模型（`rf_denoiser`）：`num_inference_steps=8`、`guidance_scale=1.0`、不传 `negative_prompt`、
  `silence_padding_duration=0.0`。CFG 已经蒸馏进权重，传 >1.0 或 negative_prompt 反而会坏。
- 采样率 44.1 kHz 立体声；一次最长 380 秒。

接口沿用原来的异步任务契约（release_task / query_result / v1/audio），前端和批量队列不用大改：
  GET  /health                         → 模型加载好没有
  POST /release_task                   → {prompt, duration, format, num_inference_steps, seed} → {code, data:{task_id}}
  POST /query_result                   → {task_id_list:[...]} → {code, data:[{task_id,status,result}]}（0=跑着，1=好了，2=失败）
  GET  /v1/audio?path=<文件名>          → 下载出好的音频
  POST /generate                       → 同步生成（测试/调试用）
  POST /quit（带 X-Agent: 1）           → 退出

所有子进程（MP3 编码兜底）都带 CREATE_NO_WINDOW。日志写在 data\logs\bgm.log，超过 5 MB 轮转。
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# diffusers 的原生注意力后端就是 torch.nn.functional.scaled_dot_product_attention（SDPA）；
# 不要换成 AttnProcessor2_0：SA3 的 DiT 用的是自定义 StableAudio3SelfAttnProcessor（带差分注意力/RoPE）。
os.environ.setdefault("DIFFUSERS_ATTN_BACKEND", "native")

from app import paths  # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MIN_S, MAX_S = 10, 380
LOG = paths.LOGS / "bgm.log"
TASK_DIR = paths.DATA / "bgm" / "tasks"
FMT = ("wav", "mp3", "flac")

PIPE = None
SR = 44100
DTYPE = ""
DEVICE = "cuda"
MODEL_DIR = ""
_LOCK = threading.Lock()
_TASKS = {}
_QUEUE = queue.Queue()
_SEQ = 0
_SEQ_LOCK = threading.Lock()
_LOG_FH = None


class _Tee:
    """有控制台/父进程管道时同时写一份到 bgm.log。"""

    def __init__(self, stream, fh):
        self.s, self.f = stream, fh

    def write(self, text):
        for x in (self.s, self.f):
            try:
                x.write(text)
            except Exception:
                pass
        return len(text)

    def flush(self):
        for x in (self.s, self.f):
            try:
                x.flush()
            except Exception:
                pass

    def __getattr__(self, k):
        return getattr(self.s, k)


def _setup_log():
    global _LOG_FH
    if _LOG_FH is not None:
        return _LOG_FH
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    # 后端 Proc.start 已经把 stdout 接到 data\logs\bgm.log：直接用，别再开一份（否则每一行写两遍）。
    try:
        if sys.stdout is not None and Path(getattr(sys.stdout, "name", "")).resolve() == LOG.resolve():
            _LOG_FH = sys.stdout
            try:
                import faulthandler
                faulthandler.enable(file=sys.stdout, all_threads=True)
            except Exception:
                pass
            return _LOG_FH
    except Exception:
        pass
    # 手动在控制台跑、又没加 --log：留一份到控制台。
    if sys.stdout is not None and "--log" not in sys.argv:
        _LOG_FH = sys.stderr
        try:
            import faulthandler
            faulthandler.enable(file=sys.stderr, all_threads=True)
        except Exception:
            pass
        return _LOG_FH
    try:
        if LOG.exists() and LOG.stat().st_size > 5 << 20:
            LOG.replace(LOG.with_suffix(".old.log"))
    except Exception:
        pass
    try:
        fh = open(LOG, "a", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        return None
    _LOG_FH = fh
    fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 配乐服务（Stable Audio 3）启动 · 进程 {os.getpid()}\n")
    fh.flush()
    sys.stdout = _Tee(sys.stdout, fh) if sys.stdout is not None else fh
    sys.stderr = _Tee(sys.stderr, fh) if sys.stderr is not None else fh
    try:
        import faulthandler
        faulthandler.enable(file=fh, all_threads=True)
    except Exception:
        pass
    return fh


def _log(msg):
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def _clean_old(days=2):
    try:
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        cut = time.time() - days * 86400
        for p in TASK_DIR.iterdir():
            if p.is_file() and p.stat().st_mtime < cut:
                p.unlink(missing_ok=True)
    except Exception:
        pass


def load_model(model_dir):
    global PIPE, SR, DTYPE, MODEL_DIR
    import torch
    from diffusers import StableAudio3Pipeline

    model_dir = Path(model_dir)
    if not (model_dir / "model_index.json").exists():
        raise RuntimeError(f"模型没装好：{paths.show(model_dir)} 里没有 model_index.json（先到 设置 › 整备 装配乐）")
    if not torch.cuda.is_available():
        raise RuntimeError("Stable Audio 3 要 NVIDIA 显卡：现在 PyTorch 看不到 CUDA")
    DTYPE = "bfloat16" if torch.cuda.is_bf16_supported() else "float16"
    dtype = torch.bfloat16 if DTYPE == "bfloat16" else torch.float16
    _log(f"加载 Stable Audio 3 Medium：{paths.show(model_dir)}（{DTYPE}）")
    t0 = time.time()
    pipe = StableAudio3Pipeline.from_pretrained(str(model_dir), torch_dtype=dtype, local_files_only=True)
    # SA3 的 DiT 用自定义 StableAudio3SelfAttnProcessor / CrossAttnProcessor，内部走
    # dispatch_attention_fn → native 后端 → torch.nn.functional.scaled_dot_product_attention（SDPA）。
    # 不要用 set_attn_processor 换成通用 AttnProcessor2_0：那会丢掉差分注意力和 RoPE，并在 spatial_norm 上报错。
    _log("注意力：diffusers native 后端（PyTorch SDPA）")
    try:
        pipe.set_progress_bar_config(disable=True)
    except Exception:
        pass
    pipe.to("cuda")
    for name in ("text_encoder", "transformer", "vae"):
        obj = getattr(pipe, name, None)
        if obj is not None:
            try:
                obj.eval()
            except Exception:
                pass
    try:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    except Exception:
        pass
    SR = int(getattr(pipe.vae.config, "sampling_rate", 0) or 44100)
    PIPE = pipe
    MODEL_DIR = str(model_dir)
    vram = torch.cuda.get_device_properties(0).total_memory / 2**30
    _log(f"模型加载好了：{time.time() - t0:.1f} 秒 · {torch.cuda.get_device_name(0)} · 显存 {vram:.1f} GB · 采样率 {SR} Hz")
    return pipe


def _mp3(path, audio, sr):
    """MP3：优先 lameenc（不启子进程）；没有就退到 ffmpeg（带 CREATE_NO_WINDOW）。"""
    import numpy as np
    try:
        import lameenc
        enc = lameenc.Encoder()
        enc.set_bit_rate(192)
        enc.set_in_sample_rate(int(sr))
        enc.set_channels(int(audio.shape[1]))
        enc.set_quality(2)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        path.write_bytes(enc.encode(pcm) + enc.flush())
        return
    except Exception as e:
        _log(f"lameenc 用不了，试 ffmpeg：{e}")
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ff = None
    if not ff:
        raise RuntimeError("要导出 MP3 需要 lameenc 或 ffmpeg：到 设置 › 整备 重新装配乐")
    import soundfile as sf
    tmp = path.with_suffix(".tmp.wav")
    sf.write(tmp, audio, int(sr), format="WAV")
    try:
        r = subprocess.run([ff, "-y", "-i", str(tmp), "-codec:a", "libmp3lame", "-q:a", "2", str(path)],
                           capture_output=True, text=True, errors="replace", timeout=120,
                           creationflags=NOWIN, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not path.exists():
            raise RuntimeError("ffmpeg 转 MP3 失败：" + (r.stderr or "")[-200:])
    finally:
        tmp.unlink(missing_ok=True)


def generate(prompt, seconds=60, fmt="wav", seed=0, steps=8):
    """同步出一首。返回 {path, seconds, sampling_rate, fmt}。"""
    import numpy as np
    import soundfile as sf
    import torch
    if PIPE is None:
        raise RuntimeError("模型还没加载好")
    prompt = str(prompt or "").strip()
    if not prompt:
        raise RuntimeError("写一句描述：风格、情绪、乐器、快慢")
    try:
        seconds = float(seconds or 60)
    except (TypeError, ValueError):
        seconds = 60.0
    seconds = max(MIN_S, min(MAX_S, seconds))
    fmt = fmt if fmt in FMT else "wav"
    steps = max(1, min(32, int(steps or 8)))
    with _LOCK:
        t0 = time.time()
        gen = torch.Generator(device="cuda").manual_seed(int(seed) & 0x7FFFFFFF)
        with torch.inference_mode():
            out = PIPE(
                prompt=prompt,
                duration=seconds,
                num_inference_steps=steps,       # 蒸馏模型默认 8 步
                guidance_scale=1.0,               # CFG 已蒸馏进权重
                negative_prompt=None,             # 不要传 negative_prompt
                silence_padding_duration=0.0,
                num_waveforms_per_prompt=1,
                generator=gen,
                output_type="pt",
            )
        audio = out.audios[0].T.float().cpu().numpy()      # [samples, channels]
        if not np.isfinite(audio).all():
            _log("生成的音频里有 NaN/Inf，修一下再写")
            audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{int(time.time() * 1000)}_{os.getpid()}.{fmt}"
        path = TASK_DIR / name
        if fmt == "mp3":
            _mp3(path, audio, SR)
        else:
            sf.write(path, audio, SR, format="FLAC" if fmt == "flac" else "WAV")
        _log(f"出好了：{name} · {seconds:.0f} 秒 · 用了 {time.time() - t0:.1f} 秒")
        return {"path": path, "name": name, "seconds": seconds, "sampling_rate": SR, "fmt": fmt}
    # 锁外不做别的：后端会按 task id 来取文件


def _new_task(prompt, seconds, fmt, steps, seed):
    global _SEQ
    with _SEQ_LOCK:
        _SEQ += 1
        tid = f"{int(time.time() * 1000)}_{_SEQ}"
    _TASKS[tid] = {"task_id": tid, "status": 0, "result": None, "error": "",
                   "prompt": prompt, "seconds": seconds, "fmt": fmt, "steps": steps, "seed": seed, "t0": time.time()}
    _QUEUE.put(tid)
    return tid


def _worker():
    while True:
        tid = _QUEUE.get()
        if tid is None:
            return
        task = _TASKS.get(tid)
        if not task:
            continue
        try:
            r = generate(task["prompt"], task["seconds"], task["fmt"], task["seed"], task["steps"])
            rel = r["name"]
            task["result"] = json.dumps([{"file": "/v1/audio?path=" + quote(rel)}], ensure_ascii=False)
            task["status"] = 1
        except Exception as e:
            task["status"] = 2
            task["error"] = str(e)[:500]
            _log("出一首失败：" + traceback.format_exc())


def _jsonl(j):
    return json.dumps(j, ensure_ascii=False).encode("utf-8")


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = _jsonl(obj)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(n, 1 << 20)) if n else b"{}"
            return json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            if PIPE is None:
                self._send(503, {"ok": False, "loaded": False})
            else:
                self._send(200, {"ok": True, "loaded": True, "model": paths.show(Path(MODEL_DIR)), "device": DEVICE,
                                 "dtype": DTYPE, "sampling_rate": SR})
            return
        if u.path == "/v1/audio":
            rel = parse_qs(u.query).get("path", [""])[0]
            name = Path(rel).name
            p = (TASK_DIR / name).resolve()
            try:
                if TASK_DIR.resolve() not in p.parents or not p.is_file():
                    raise FileNotFoundError
            except Exception:
                self._send(404, {"ok": False, "error": "没有这个音频"})
                return
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav" if p.suffix == ".wav" else "audio/mpeg" if p.suffix == ".mp3" else "audio/flac")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(404, {"ok": False, "error": "没有这个接口"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/quit":
            if self.headers.get("X-Agent") == "1":
                self._send(200, {"ok": True})
                _log("Agent 让我退出")
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._send(403, {"ok": False})
            return
        body = self._read()
        if u.path == "/release_task":
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                self._send(400, {"code": 400, "message": "prompt 不能为空"})
                return
            try:
                seconds = float(body.get("duration", body.get("audio_duration", body.get("seconds", 60))) or 60)
            except (TypeError, ValueError):
                seconds = 60.0
            seconds = max(MIN_S, min(MAX_S, seconds))
            fmt = str(body.get("format") or body.get("audio_format") or "wav").lower()
            fmt = fmt if fmt in FMT else "wav"
            try:
                steps = int(body.get("num_inference_steps", body.get("inference_steps", 8)) or 8)
            except (TypeError, ValueError):
                steps = 8
            steps = max(1, min(32, steps))          # 蒸馏模型固定 8 步最稳；这里只做上限保护
            try:
                seed = int(body.get("seed", 0) or 0)
            except (TypeError, ValueError):
                seed = 0
            tid = _new_task(prompt, seconds, fmt, steps, seed)
            self._send(200, {"code": 200, "data": {"task_id": tid}})
            return
        if u.path == "/query_result":
            ids = body.get("task_id_list") or []
            if isinstance(ids, str):
                ids = [ids]
            out = []
            for tid in ids:
                t = _TASKS.get(str(tid))
                if not t:
                    out.append({"task_id": tid, "status": 2, "result": "", "error": "没有这个任务"})
                    continue
                out.append({"task_id": tid, "status": t["status"], "result": t.get("result") or "",
                            "error": t.get("error") or "", "seconds": t.get("seconds"), "fmt": t.get("fmt")})
            self._send(200, {"code": 200, "data": out})
            return
        if u.path == "/generate":
            try:
                r = generate(str(body.get("prompt") or ""), body.get("duration", body.get("seconds", 60)),
                             body.get("format", body.get("audio_format", "wav")), body.get("seed", 0),
                             body.get("num_inference_steps", body.get("inference_steps", 8)))
                self._send(200, {"ok": True, "path": r["name"], "seconds": r["seconds"], "sampling_rate": r["sampling_rate"], "format": r["fmt"]})
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)[:500]})
            return
        self._send(404, {"ok": False, "error": "没有这个接口"})

    def log_message(self, *a):
        pass


class Srv(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(paths.BGM_MODEL))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8094)
    ap.add_argument("--log", action="store_true")
    args = ap.parse_args()
    _setup_log()
    _clean_old()
    _log(f"进程 {os.getpid()} · Python {sys.version.split()[0]}")
    try:
        load_model(args.model)
    except Exception:
        _log("模型加载失败：\n" + traceback.format_exc())
        return 2
    threading.Thread(target=_worker, daemon=True).start()
    httpd = Srv((args.host, args.port), H)
    _log(f"接口起来了：http://{args.host}:{args.port} · 模型 {paths.show(Path(args.model))}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _QUEUE.put(None)
        httpd.server_close()
        _log("配乐服务停了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
