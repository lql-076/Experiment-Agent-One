r"""启动 Breeze TTS 2 的接口（v3.1，语音对话「说话的声音」）。在配音环境 tts-env 里跑，没有黑窗口（由 app/voice.py 拉起）。

  tts-env\Scripts\python.exe app\breeze_run.py <权重文件夹> --host 127.0.0.1 --port 8093

为什么要这一层：
- Breeze 的推理代码随包带在 vendor\breeze-tts（作者家里连 GitHub 不稳），这里把它放到 sys.path 最前面；
- 它要的 qwen-tts 一导入就 import sox（老的 25Hz 模型才用，我们没装 SoX）：和配音服务一样用空模块顶替；
- Windows 没有 flash-attn：把模型的注意力换成 PyTorch 自带的 SDPA（比官方默认的 eager 快很多）；
- v3.5.2：官方最快的 --fast-all 依赖 torch.compile + Triton，Windows 上容易卡在编译/静态 CUDA 启动器；
  默认改走 **CUDA Graph 兼容模式**：backbone 解码和完整的 depth decoder 循环都用 CUDA Graph 捕获，
  但不编译、不依赖 Triton。实测 RTF 从 14.9 降到约 1.0，TTFA 约 0.5 秒；
- 还保留 AGENT_BREEZE_MODE=all（官方 fast-all，需要 triton-windows 和更多显存）、eager（只开 SDPA）、off（完全官方原样）供排查。

Breeze 官方测的是 Linux + PyTorch 2.9.1；这里和配音共用 tts-env（PyTorch 2.8.0、Transformers 4.57.3、qwen-tts 0.1.1，后两样和它锁的一样）。
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "vendor" / "breeze-tts"


def _mode():
    mode = os.environ.get("AGENT_BREEZE_MODE", "graph").strip().lower()
    return mode if mode in ("compile", "graph", "all", "eager", "off") else "graph"


def _patch_sdpa(enabled=True):
    from breeze_infer import api
    if enabled:
        original = api.load_runtime

        def load_runtime(ckpt_dir, *, device, attn_implementation):
            return original(ckpt_dir, device=device, attn_implementation="sdpa")

        api.load_runtime = load_runtime
    return api


def _patch_depth_graph():
    """捕获 depth decoder 的完整循环图，但不做 torch.compile。

    官方把 fast-depth-decoder 和 torch.compile 绑在一起；Windows 上 Triton 编译又慢又容易报
    static CUDA launcher 的 OverflowError。CUDA Graph 本身不需要 Triton，这里只借用官方的
    DepthDecoderGraph.capture()，把 15 个 codebook 的循环一次性 capture 下来。
    """
    from models.cudagraph.depth_decoder_graph import DepthDecoderGraph

    def prepare_eager(self):
        self.no_graph = False
        self._init_cache_layers()
        self._build_attention_masks()
        return self.capture()

    DepthDecoderGraph.prepare_eager = prepare_eager


def main():
    sys.modules.setdefault("sox", types.ModuleType("sox"))
    sys.modules.setdefault("nagisa", types.ModuleType("nagisa"))
    sys.path.insert(0, str(CODE))
    os.chdir(CODE)
    mode = _mode()
    if mode in ("compile", "all"):
        # Windows 的 TorchInductor 静态 CUDA 启动器在 Python 3.13 会 int too large；用动态启动器
        os.environ.setdefault("TORCHINDUCTOR_USE_STATIC_CUDA_LAUNCHER", "0")
    api = _patch_sdpa(mode != "off")
    if mode == "graph":
        _patch_depth_graph()
    if mode in ("compile", "graph", "all"):
        try:
            import torch
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass
    args = [a for a in sys.argv[1:] if not a.startswith("--fast")]
    if mode == "graph":
        args.append("--fast-backbone-decode")
    elif mode == "compile":
        args += ["--fast-backbone-decode", "--fast-depth-decoder"]
    elif mode == "all":
        args.append("--fast-all")
    print(f"Breeze 启动模式：{mode}", flush=True)
    sys.argv = [str(CODE / "breeze_infer" / "api.py"), *args]
    api.main()


if __name__ == "__main__":
    main()
