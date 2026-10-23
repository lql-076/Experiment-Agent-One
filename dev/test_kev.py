"""Kev 权重在不在本机的判断（不用起服务）：
1. 什么都没有 → 没下载；2. Kev 是 LoRA、底座没下 → 没下载；3. 都在 → 下载好了；4. 有下了一半的文件 → 没下载完
用法：python dev/test_kev.py"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app import paths, settings  # noqa: E402
from app.models import M  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


tmp = pathlib.Path(tempfile.mkdtemp(prefix="kevtest-"))
paths.HF_CACHE = tmp
settings.S["kevRun"] = "jaredpalmer/kev-0.8b"
check(not M.kev_weights(), "什么都没有：没下载")
s = tmp / "hub/models--jaredpalmer--kev-0.8b/snapshots/abc"
s.mkdir(parents=True)
(s / "head.pt").write_text("x")
(s / "adapter_model.safetensors").write_text("x")
(s / "adapter_config.json").write_text(json.dumps({"base_model_name_or_path": "Qwen/Qwen3.5-0.8B"}))
check(not M.kev_weights(), "Kev 是 LoRA、底座没下：不算下载好")
b = tmp / "hub/models--Qwen--Qwen3.5-0.8B/snapshots/def"
b.mkdir(parents=True)
(b / "config.json").write_text("{}")
(b / "model.safetensors").write_text("x")
check(M.kev_weights(), "Kev 和底座都在：下载好了（整备显示已就绪，不会再下）")
bl = tmp / "hub/models--Qwen--Qwen3.5-0.8B/blobs"
bl.mkdir()
(bl / "x.incomplete").write_text("")
check(not M.kev_weights(), "有下了一半的 .incomplete：没下载完")
(bl / "x.incomplete").unlink()
print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
