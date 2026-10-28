"""测试用：假的「安装配音」（scripts/install_tts.py 的样子：@@SAY 讲解、@@PROGRESS、pip raw、魔搭的 tqdm），几秒就完。
dev/.run/fake_tts_install_fail.flag 在的话，这次装到一半失败（用一次就删掉），用来测"失败了再点一次"。"""
import json
import os
import sys
import time
from pathlib import Path

FAIL = Path(__file__).resolve().parent / ".run" / "fake_tts_install_fail.flag"
FEED = os.environ.get("AGENT_FEED") == "1"


def say(m, kind=""):
    print(("@@SAY " + kind + m) if FEED else m, flush=True)


say("先把 pip 升到最新（新版才能报下载进度）")
say("显卡版 PyTorch 已经装好：2.8.0+cu128", "✓")
say("安装 Qwen3-TTS 和它要的库（约 300MB，从 PyPI）")
print("  Downloading transformers-4.57.3-py3-none-any.whl (12.0 MB)", flush=True)
for d in range(0, 12_000_001, 3_000_000):
    print(f"Progress {d} of 12000000", flush=True)
    time.sleep(0.05)
print("Successfully installed accelerate-1.12.0 librosa-0.11.0 qwen-tts-0.1.1 transformers-4.57.3", flush=True)
say("配音环境装好了：PyTorch 2.8.0+cu128 | 显卡 假显卡 | Transformers 4.57.3", "✓")
src = "hf-mirror" if os.environ.get("AGENT_MODEL_SOURCE") == "hf" else "魔搭"
say(f"下载 预设音色 CustomVoice（大约 4~5 GB）：从{src} Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
for i in range(0, 101, 10):
    sys.stdout.write(f"\rDownloading [model.safetensors]: {i:3d}%|{'█' * (i // 10):<10}| {3.8 * i / 100:.2f}G/3.80G [00:{i // 10:02d}<00:10, 380MB/s]")
    sys.stdout.flush()
    time.sleep(0.06)
print(flush=True)
if FAIL.exists():
    FAIL.unlink()
    print("httpx.ReadTimeout: The read operation timed out", flush=True)
    sys.exit(1)
say("预设音色 CustomVoice 下好了", "✓")
print("@@PROGRESS " + json.dumps({"phase": "下载 描述音色", "done": 3_800_000_000, "total": 3_800_000_000}), flush=True)
say("描述音色 VoiceDesign 下好了", "✓")
print("\n配音装好了。打开 Agent 界面，左边点「配音」。", flush=True)
