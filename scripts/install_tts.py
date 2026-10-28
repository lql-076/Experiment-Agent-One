"""安装配音（Qwen3-TTS）：配音环境 tts-env + 两个配音模型。由「安装配音.bat」调用。
可以重复运行：装过的、下过的都跳过；下到一半断了，再运行一次接着下。
  python scripts/install_tts.py            环境 + 模型
  python scripts/install_tts.py --env      只装环境
  python scripts/install_tts.py --models   只下模型

为什么单独一个环境：官方的 qwen-tts 要 Transformers 4.57.3，本地模型环境（ai-env）用的是 5.x，装在一起会互相打架。
PyTorch 和 ai-env 用同一个版本（2.8.0 cu128）：tools\\wheels 里已经有安装包就直接用，不用再下 3GB。
不装 flash-attn（Windows 上装不上）：配音服务自动用 PyTorch 自带的注意力（sdpa），能用，只是显存多用一点。
不装 SoX：只有我们不用的旧版 25Hz 模型才用到（配音服务里放了个空模块顶替，不会去找它）。
不装 gradio（官方网页演示用的，我们有自己的「配音」页）。

模型从魔搭下（国内快；一键补齐判断魔搭不通时 AGENT_MODEL_SOURCE=hf，改走 hf-mirror），放 models\\tts\\，不进 GitHub、不进压缩包：
  Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice   预设音色（9 个，其中 5 个中文）+ 一句话控制语气
  Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign   用一段文字描述造一个新音色
两个都是 Apache 2.0 许可证，可以商用。每个大约 4~5 GB。
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from app import paths  # noqa: E402
import install_ai as A  # noqa: E402   和本地模型环境共用：建环境、装 PyTorch、pip 换源

A.ENV = paths.TTS_ENV
A.PY = paths.tts_python()
say = A.say

QWEN_TTS = "qwen-tts==0.1.1"
# qwen-tts 0.1.1 要的库（去掉了 gradio 和 sox：sox 在配音服务里用空模块顶替）。Transformers、accelerate 必须是这两个版本（官方锁死的）
DEPS = ["transformers==4.57.3", "accelerate==1.12.0", "librosa", "soundfile", "onnxruntime", "einops",
        "huggingface_hub", "safetensors", "fastapi", "uvicorn"]
TORCHAUDIO = [
    ("阿里云镜像", ["install", f"torchaudio=={A.TORCH}+cu128", "-f", "https://mirrors.aliyun.com/pytorch-wheels/cu128/"]),
    ("PyTorch 官方", ["install", f"torchaudio=={A.TORCH}", "--index-url", "https://download.pytorch.org/whl/cu128", "--extra-index-url", "https://pypi.org/simple"]),
    ("上海交大镜像", ["install", f"torchaudio=={A.TORCH}+cu128", "-f", "https://mirror.sjtu.edu.cn/pytorch-wheels/cu128/"]),
]
MODELS = [("预设音色 CustomVoice", "Qwen/" + paths.TTS_MODELS["custom"]),
          ("描述音色 VoiceDesign", "Qwen/" + paths.TTS_MODELS["design"])]
TOKENIZER = "Qwen/Qwen3-TTS-Tokenizer-12Hz"     # 正常已经在模型的 speech_tokenizer 文件夹里；缺了才单独下
SOURCE = os.environ.get("AGENT_MODEL_SOURCE", "modelscope")


# 装完后的自检：在配音环境里真的导入一次。qwen-tts 一导入就 import sox，而 SoX 我们不装（只有旧版 25Hz 模型用它）：
# 和配音服务（app/tts_server.py）一样，导入前放一个空的 sox 模块顶替（v1.8.7 这里忘了放，自检报错、模型没下）
CHECK = ("import sys, types\n"
         "sys.modules.setdefault('sox', types.ModuleType('sox'))\n"
         "import torch, transformers, qwen_tts\n"
         "print('PyTorch', torch.__version__, '| 显卡', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '用不了',"
         " '| Transformers', transformers.__version__)")


def has(code):
    """在配音环境里跑一段代码。成功返回 (True, 最后一行输出)；失败返回 (False, 真正的报错那一行)，
    完整的报错打印出来（写进 setup_tts.log）。qwen-tts 导入时会往输出里打一段 flash-attn 的提示，那不是报错。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([str(A.PY), "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    out = [x for x in (r.stdout or "").splitlines() if x.strip() and x.strip("* ")]
    if r.returncode == 0:
        return True, (out[-1].strip() if out else "")
    err = [x for x in (r.stderr or "").splitlines() if x.strip()]
    if err:
        print("\n".join(err[-15:]), flush=True)
    return False, (err[-1].strip() if err else out[-1].strip() if out else f"退出码 {r.returncode}")[:300]


def install_env():
    if sys.version_info < (3, 10):
        print("需要 Python 3.10 或更新。")
        return 1
    A.make_env()
    if not A.ensure_torch():
        return 2
    ok, _ = has("import torchaudio")
    if ok:
        say("torchaudio 已经装好", "✓")
    else:
        say(f"安装 torchaudio {A.TORCH}（cu128，和 PyTorch 配对，几 MB）")
        for name, args in TORCHAUDIO:
            say(f"用 pip 安装 torchaudio：{name}")
            if A.pip(*args, check=False) and has("import torchaudio")[0]:
                break
        else:
            say("torchaudio 没装上，看上面的报错；网络问题的话过一会再试", "!")
            return 3
    say("安装 Qwen3-TTS 和它要的库（约 300MB，从 PyPI）")
    if not A.pip_any("--no-deps", QWEN_TTS):
        say("qwen-tts 没装上，看上面的报错", "!")
        return 4
    # 把 torch、torchaudio 也写进去：保证 pip 不会顺手把显卡版 PyTorch 换成别的版本
    if not A.pip_any(*DEPS, f"torch=={A.TORCH}", f"torchaudio=={A.TORCH}"):
        say("配音要的库没装上，看上面的报错；网络问题的话过一会再试", "!")
        return 5
    ok, info = has(CHECK)
    if not ok:
        say("装完了但导入出错：" + info, "!")
        return 6
    say("配音环境装好了：" + info, "✓")
    return 0


def done(dest: Path) -> bool:
    return ((dest / "config.json").exists() and (dest / "speech_tokenizer" / "config.json").exists()
            and any(dest.glob("*.safetensors")) and not any(dest.rglob("*.incomplete")))


def download(repo, dest: Path):
    if SOURCE == "hf":
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from huggingface_hub import snapshot_download as dl
    else:
        from modelscope import snapshot_download as dl
    dl(repo, local_dir=str(dest))


def install_models():
    for pkg, mod in (("huggingface_hub", "huggingface_hub"),) if SOURCE == "hf" else (("modelscope", "modelscope"),):
        try:
            __import__(mod)
        except ImportError:
            say(f"先装下载工具 {pkg}")
            if subprocess.run([sys.executable, "-m", "pip", "install", pkg]).returncode != 0:
                subprocess.run([sys.executable, "-m", "pip", "install", "-i", A.PYPI_BACKUP, pkg], check=True)
    for name, repo in MODELS:
        dest = paths.MODELS_TTS / repo.split("/")[1]
        dest.mkdir(parents=True, exist_ok=True)
        if done(dest):
            say(f"{name} 已经下好了，跳过", "✓")
            continue
        say(f"下载 {name}（大约 4~5 GB）：从{'hf-mirror' if SOURCE == 'hf' else '魔搭'} {repo}，放到 {paths.show(dest)}")
        download(repo, dest)
        if not (dest / "speech_tokenizer" / "config.json").exists():
            say("模型里没带声音编解码器（speech_tokenizer），单独下一份")
            download(TOKENIZER, dest / "speech_tokenizer")
        say(f"{name} 下好了" if done(dest) else f"{name} 好像没下全，再运行一次接着下", "✓" if done(dest) else "!")
    return 0


def main():
    args = sys.argv[1:]
    code = 0
    if "--models" not in args:
        code = install_env()
        if code:
            return code
    if "--env" not in args:
        code = install_models()
    print("\n配音装好了。打开 Agent 界面，左边点「配音」。")
    return code


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        print("\n停了。再运行一次会接着装、接着下。")
        code = 1
    except Exception as e:
        print("\n出错了：", e)
        print("网络问题的话过一会再运行一次，会接着下。")
        code = 9
    sys.exit(code)
