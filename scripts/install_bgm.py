r"""安装配乐引擎 Stable Audio 3 Medium（v3.4）。

整备 ›「配音、语音、配乐」一键装好的最后一步调用；也可以单独运行：
  python scripts/install_bgm.py

做什么（都是写死的，不让模型随手敲命令）：
1. 准备 `bgm-env`：只装 diffusers / soundfile / lameenc；torch 和 transformers 通过一个 .pth 复用 `ai-env`，
   不另装一份 3GB 的 PyTorch。tts-env 的 transformers 4.57.3 和 diffusers 0.43 的 huggingface-hub 依赖冲突，
   所以不去动配音环境。
2. 下载 `stabilityai/stable-audio-3-medium`（约 10.4GB，含 T5Gemma 文本编码器和 SAME 自编码器权重）：
   先魔搭 ModelScope，失败再走 hf-mirror（gated 仓库要 HF_TOKEN，并在网页上同意 Stability / Gemma 条款）。
   放到 `models\bgm\stable-audio-3-medium-src`。
3. 用 `scripts/convert_stable_audio_3.py`（diffusers 官方转换脚本，Apache-2.0）把原始 checkpoint 转成
   diffusers 格式，放到 `models\bgm\stable-audio-3-medium`。转换时固定用 SDPA（Windows 没有 flash-attn），
   并按 `rf_denoiser` 自动写入 `stochastic_sampling=True` 的 8 步调度器。
4. 自检：bgm-env 能导入 torch / diffusers / soundfile，显卡看得见。

测试时可用 `AGENT_BGM_FAKE=1` 直接造一份小的假模型目录，不下载 10GB；`AGENT_BGM_MODEL` / `AGENT_BGM_SRC` /
`AGENT_BGM_ENV` 可以换目录（`dev/test_media.py` 用）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import paths  # noqa: E402

paths.keep_inside()

REPO = "stabilityai/stable-audio-3-medium"
TEXT_REPO = "google/t5gemma-b-b-ul2"
ENV = Path(os.environ.get("AGENT_BGM_ENV") or paths.BGM_ENV)
SRC = Path(os.environ.get("AGENT_BGM_SRC") or paths.BGM_SRC)
DST = Path(os.environ.get("AGENT_BGM_MODEL") or paths.BGM_MODEL)
CONVERT = ROOT / "scripts" / "convert_stable_audio_3.py"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
SRC_FILES = ("model.safetensors", "model_config.json", "t5gemma-b-b-ul2/model.safetensors",
             "t5gemma-b-b-ul2/config.json", "t5gemma-b-b-ul2/tokenizer.json")
TQDM_LINE = re.compile(r"\d+%\|")


def say(msg, kind=""):
    print(("@@SAY " + kind + msg) if os.environ.get("AGENT_FEED") == "1" else msg, flush=True)


def emit(**kw):
    print("@@PROGRESS " + json.dumps(kw, ensure_ascii=False), flush=True)


def run_fwd(cmd, cwd=None, env=None):
    """跑一个子程序，输出原样转到整备日志；返回 (退出码, 最后几行)。"""
    p = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd or ROOT), env=env or os.environ,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=NOWIN)
    out = getattr(sys.stdout, "buffer", None)
    tail, buf = [], b""
    while True:
        chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
        if not chunk:
            break
        if out is not None:
            try:
                out.write(chunk)
                out.flush()
            except Exception:
                out = None
        buf += chunk
        *lines, buf = re.split(rb"[\r\n]", buf)
        for x in lines:
            t = x.decode("utf-8", "replace").strip()
            if t and not TQDM_LINE.search(t):
                tail = (tail + [t])[-40:]
    t = buf.decode("utf-8", "replace").strip()
    if t:
        tail.append(t)
    return p.wait(), tail


def src_ok():
    return all((SRC / f).exists() for f in SRC_FILES)


def models_ok(d=None):
    """转换好的 diffusers 目录：核心 safetensors、配置齐备；`.cache` 里的半截文件不算。"""
    d = Path(d or DST)
    return ((d / "model_index.json").exists()
            and all((d / n).is_dir() and any((d / n).glob("*.safetensors")) for n in ("transformer", "vae", "text_encoder"))
            and (d / "scheduler" / "scheduler_config.json").exists()
            and not any(p for p in d.rglob("*.incomplete") if ".cache" not in p.parts))


def _site(env_dir: Path) -> Path | None:
    for pat in ("Lib/site-packages", "lib/python*/site-packages"):
        for p in env_dir.glob(pat):
            if p.is_dir():
                return p
    return None


def ensure_env():
    py = ENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    ok = False
    if py.exists():
        code, _ = run_fwd([py, "-c", "import torch, diffusers, soundfile, lameenc; print('ok')"])
        ok = code == 0
    if ok:
        say("配乐环境已经有了，跳过", "✓")
        return py
    if not py.exists():
        say(f"建配乐环境：{paths.show(ENV)}（只装 diffusers / soundfile，不另装 PyTorch）")
        code, tail = run_fwd([sys.executable, "-m", "venv", str(ENV)])
        if code != 0:
            raise RuntimeError("配乐环境建不起来：" + " ".join(tail[-3:]))
        py = ENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # 复用 ai-env 的 torch / transformers，避免再装一份几 GB 的 PyTorch
    ai_site = _site(paths.AI_ENV)
    if not ai_site:
        raise RuntimeError("没有找到 ai-env：先到 设置 › 整备 装好「本地模型环境」，配乐复用它的 PyTorch")
    site = _site(ENV)
    if not site:
        raise RuntimeError("配乐环境里找不到 site-packages")
    (site / "ai-env.pth").write_text(str(ai_site), "utf-8")
    say("安装配乐用的 diffusers、soundfile、lameenc（走清华镜像）")
    code, tail = run_fwd([py, "-m", "pip", "install", "-i", MIRROR, "-U", "diffusers>=0.43", "soundfile", "lameenc", "protobuf"])
    if code != 0:
        raise RuntimeError("配乐依赖没装上：" + " ".join(tail[-4:]))
    code, tail = run_fwd([py, "-c", "import torch, diffusers, soundfile, lameenc; print('ok')"])
    if code != 0:
        raise RuntimeError("配乐环境装好了但导入失败：" + " ".join(tail[-4:]))
    say("配乐环境好了", "✓")
    return py


def _download_modelscope():
    """大文件用 fastdl（12 连接，单连接被限速时快很多），小文件用 snapshot_download 补齐。"""
    say(f"下载 Stable Audio 3 Medium（约 10.4GB）：魔搭 {REPO} → {paths.show(SRC)}")
    base_www = f"https://www.modelscope.cn/models/{REPO}/resolve/master/"
    base = f"https://modelscope.cn/models/{REPO}/resolve/master/"
    big_ok = True
    try:
        import fastdl
        (SRC / "model.safetensors.incomplete").unlink(missing_ok=True)
        for rel in ("model.safetensors", "t5gemma-b-b-ul2/model.safetensors"):
            dest = SRC / rel
            if dest.exists() and dest.stat().st_size > 0:
                continue
            fastdl.fetch(dest, [("魔搭", base_www + rel), ("魔搭备用", base + rel)], phase=f"下载 {rel}")
    except Exception as e:
        big_ok = False
        say(f"多连接下载没成（{str(e)[:120]}），改用魔搭的 snapshot_download 单连接续传", "!")
    small = ['*.json', '*.md', '*.gitattributes', 'LICENSE*', 'NOTICE', 't5gemma-b-b-ul2/*.json',
             't5gemma-b-b-ul2/*.model', 't5gemma-b-b-ul2/*.md', 't5gemma-b-b-ul2/.gitattributes']
    patterns = None if not big_ok else small
    code = ("from modelscope import snapshot_download\n"
            f"snapshot_download({REPO!r}, local_dir={str(SRC)!r}, allow_patterns={patterns!r})\n")
    return run_fwd([sys.executable, "-c", code], ROOT, dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))


def _download_hf(token=""):
    code = ("import os\n"
            "from huggingface_hub import snapshot_download\n"
            f"snapshot_download({REPO!r}, local_dir={str(SRC)!r}, token=os.environ.get('HF_TOKEN') or None)\n")
    env = dict(os.environ, HF_ENDPOINT="https://hf-mirror.com", HF_HUB_DISABLE_XET="1",
               HF_TOKEN=token or os.environ.get("HF_TOKEN", ""), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    say(f"魔搭没下成，改走 hf-mirror：{REPO}")
    return run_fwd([sys.executable, "-c", code], ROOT, env)


def ensure_models(py: Path, token=""):
    if models_ok():
        say("Stable Audio 3 的模型已经转换好了，跳过", "✓")
        return
    if not src_ok():
        code, tail = _download_modelscope()
        if code != 0 or not src_ok():
            why = " ".join(tail[-3:])[:300]
            code, tail = _download_hf(token)
            if code != 0 or not src_ok():
                raise RuntimeError("模型没下全：" + (why or "魔搭失败") + "；hf-mirror：" + " ".join(tail[-3:])[:300] +
                                   "（HF 仓库是 gated：先在网页同意 Stability / Gemma 条款，再填 设置 › 语音 的 Hugging Face 令牌）")
    say("把原始 checkpoint 转成 diffusers 格式（一次性，几分钟到十几分钟）")
    shutil.rmtree(DST, ignore_errors=True)
    cmd = [py, CONVERT,
           "--checkpoint_path", SRC / "model.safetensors",
           "--model_config_path", SRC / "model_config.json",
           "--text_encoder_repo", SRC / "t5gemma-b-b-ul2",
           "--output_dir", DST,
           "--dtype", "bfloat16",
           "--skip_sanity_check"]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
    code, tail = run_fwd(cmd, ROOT, env)
    if code != 0 or not models_ok():
        raise RuntimeError("转换失败（退出码 %s）：%s" % (code, " ".join(tail[-6:])[:500]))
    say("Stable Audio 3 的模型转换好了", "✓")


def check(py: Path):
    code, tail = run_fwd([py, "-c",
                          "import torch, diffusers, soundfile; print('PyTorch', torch.__version__, '| diffusers', diffusers.__version__, "
                          "'| 显卡', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '用不了')"])
    if code != 0:
        raise RuntimeError("配乐环境自检失败：" + " ".join(tail[-4:]))
    info = tail[-1] if tail else ""
    if "用不了" in info:
        say("配乐环境能导入，但 PyTorch 看不到显卡（NVIDIA 驱动要支持 CUDA 12.8）：" + info, "!")
    else:
        say("配乐能用了：" + info, "✓")
    if not models_ok():
        raise RuntimeError(f"模型文件不全：{paths.show(DST)}")


def fake_model():
    """测试用：造一份小的、结构正确的假模型，不下载。"""
    shutil.rmtree(DST, ignore_errors=True)
    DST.mkdir(parents=True, exist_ok=True)
    (DST / "model_index.json").write_text(json.dumps({"_class_name": "StableAudio3Pipeline"}, ensure_ascii=False), "utf-8")
    for n in ("transformer", "vae", "text_encoder"):
        (DST / n).mkdir(exist_ok=True)
        (DST / n / "model.safetensors").write_bytes(b"fake")
    (DST / "scheduler").mkdir(exist_ok=True)
    (DST / "scheduler" / "scheduler_config.json").write_text("{}", "utf-8")
    say("测试模式：造了一份假的 Stable Audio 3 模型", "✓")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", action="store_true", help="只下模型/转换（环境已好时）")
    ap.add_argument("--env", action="store_true", help="只准备环境")
    ap.add_argument("--hf-token", default="", help="hf-mirror 用的令牌（gated 仓库）")
    args = ap.parse_args()
    if os.environ.get("AGENT_BGM_FAKE") == "1":
        fake_model()
        return 0
    t0 = time.time()
    py = ensure_env()
    if not args.env:
        ensure_models(py, args.hf_token or os.environ.get("HF_TOKEN", ""))
    if not args.models:
        check(py)
    say(f"配乐装好了（{time.time() - t0:.0f} 秒）。左边点「配乐」出一首试试。", "✓")
    print("\n配乐装好了。左边点「配乐」出一首试试。", flush=True)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        print("\n停了。再运行一次会接着下、接着装。")
        code = 1
    except Exception as e:
        print("\n出错了：", e, flush=True)
        say(str(e)[:400], "!")
        code = 9
    sys.exit(code)
