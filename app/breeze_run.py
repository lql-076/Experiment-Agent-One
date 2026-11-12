r"""启动 Breeze TTS 2 的接口（v3.1，语音对话「说话的声音」）。在配音环境 tts-env 里跑，没有黑窗口（由 app/voice.py 拉起）。

  tts-env\Scripts\python.exe app\breeze_run.py <权重文件夹> --host 127.0.0.1 --port 8093

为什么要这一层：
- Breeze 的推理代码随包带在 vendor\breeze-tts（作者家里连 GitHub 不稳），这里把它放到 sys.path 最前面；
- 它要的 qwen-tts 一导入就 import sox（老的 25Hz 模型才用，我们没装 SoX）：和配音服务一样用空模块顶替；
- 只走官方说的 eager 路径（不开 --fast-*：那条要 torch.compile、CUDA Graph，Windows 上不稳，显存也要 14GB）。
Breeze 官方测的是 Linux + PyTorch 2.9.1；这里和配音共用 tts-env（PyTorch 2.8.0、Transformers 4.57.3、qwen-tts 0.1.1，后两样和它锁的一样）。
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "vendor" / "breeze-tts"


def main():
    sys.modules.setdefault("sox", types.ModuleType("sox"))
    sys.modules.setdefault("nagisa", types.ModuleType("nagisa"))
    sys.path.insert(0, str(CODE))
    os.chdir(CODE)
    args = [a for a in sys.argv[1:] if not a.startswith("--fast")]
    sys.argv = [str(CODE / "breeze_infer" / "api.py"), *args]
    from breeze_infer import api
    api.main()


if __name__ == "__main__":
    main()
