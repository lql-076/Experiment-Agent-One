"""下载模型：底座 MiniCPM5-2B、嵌入模型 Qwen3-Embedding-0.6B（从魔搭），Kev 适配器（从 hf-mirror）。
由「下载模型.bat」调用。可以重复运行，下过的文件会跳过。下到一半断了，再运行一次会接着下。

想手动下载也行：在魔搭网页上把整个模型文件夹的文件下载下来，放到下面打印出来的文件夹里。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import paths  # noqa: E402

MODELS = [
    ("底座 MiniCPM5-2B（约 5GB）", "OpenBMB/MiniCPM5-2B", "openbmb/MiniCPM5-2B", paths.MODELS_BASE),
    ("嵌入模型 Qwen3-Embedding-0.6B（约 1.2GB）", "Qwen/Qwen3-Embedding-0.6B", "Qwen/Qwen3-Embedding-0.6B", paths.MODELS_EMBED),
]
# 默认从魔搭下载；一键补齐发现魔搭不通时会设 AGENT_MODEL_SOURCE=hf，改从 hf-mirror 下载
SOURCE = os.environ.get("AGENT_MODEL_SOURCE", "modelscope")
FEED = os.environ.get("AGENT_FEED") == "1"     # 一键补齐在跑：说的话加 @@SAY，进后台页的进展报告


def say(msg, kind=""):
    print(("@@SAY " + kind + msg) if FEED else f"\n==== {msg}", flush=True)


def ensure(pkg, mod):
    try:
        __import__(mod)
    except ImportError:
        say(f"先装下载工具 {pkg}")
        r = subprocess.run([sys.executable, "-m", "pip", "install", pkg])
        if r.returncode != 0:
            subprocess.run([sys.executable, "-m", "pip", "install", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", pkg], check=True)


def main():
    if SOURCE == "hf":
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        ensure("huggingface_hub", "huggingface_hub")
        from huggingface_hub import snapshot_download as hf_dl
    else:
        ensure("modelscope", "modelscope")
        from modelscope import snapshot_download
    for name, repo, hf_repo, dest in MODELS:
        dest.mkdir(parents=True, exist_ok=True)
        if (dest / "config.json").exists() and list(dest.glob("*.safetensors")):
            say(f"{name} 已经下好了，跳过", "✓")
            continue
        if SOURCE == "hf":
            say(f"下载 {name}：从 hf-mirror {hf_repo}，放到 {dest}")
            hf_dl(hf_repo, local_dir=str(dest))
        else:
            say(f"下载 {name}：从魔搭 {repo}，放到 {dest}")
            snapshot_download(repo, local_dir=str(dest))
        say(f"{name} 下好了", "✓")

    say("下载 Kev 的适配器（从 hf-mirror，很小）")
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ["HF_HOME"] = str(paths.HF_CACHE)
    try:
        ensure("huggingface_hub", "huggingface_hub")
        from huggingface_hub import snapshot_download as hf_dl
        hf_dl("jaredpalmer/kev-0.8b", allow_patterns=["*.json", "*.safetensors", "*.pt", "*.txt", "*.jinja"])
        say("Kev 的适配器下好了", "✓")
        print("     Kev 用的底座（Qwen3.5-0.8B，约 1.7GB）会在第一次启动 Kev 时自动下载。")
    except Exception as e:
        say(f"Kev 的适配器没下成（不影响别的）：{e}", "!")
        print("     可以在界面 设置 › 本地模型 把 Kev 先关掉，决策脑只用语义路由一票。")

    print("\n全部完成。回到界面 设置 › 整备 点「重新自检」。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n停了。再运行一次会接着下。")
    except Exception as e:
        print("\n出错了：", e)
        print("网络问题的话过一会再运行一次，会接着下。")
        sys.exit(1)
