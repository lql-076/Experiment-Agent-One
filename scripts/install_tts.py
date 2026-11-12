"""安装配音（Qwen3-TTS）：配音环境 tts-env + 两个配音模型 + 时间轴对齐模型（v1.8.14）。由「安装配音.bat」调用。
可以重复运行：装过的、下过的都跳过；下到一半断了，再运行一次接着下。
  python scripts/install_tts.py            环境 + 模型
  python scripts/install_tts.py --env      只装环境
  python scripts/install_tts.py --models   只下模型
  python scripts/install_tts.py --asr      只下听写模型（v3.0，语音对话用：Qwen/Qwen3-ASR-0.6B，Apache 2.0，约 1.9 GB；代码就是已经装好的 qwen-asr）
  python scripts/install_tts.py --breeze   只下 Breeze TTS 2 的权重（v3.1，语音对话「说话的声音」：BreezeBlue/breeze-tts-2，研究和非商业用途；
                                           先 hf-mirror、不行再魔搭；推理代码随包在 vendor\breeze-tts，环境就是这个配音环境，不另装）

为什么单独一个环境：官方的 qwen-tts 要 Transformers 4.57.3，本地模型环境（ai-env）用的是 5.x，装在一起会互相打架。
PyTorch 和 ai-env 用同一个版本（2.8.0 cu128）：tools\\wheels 里已经有安装包就直接用，不用再下 3GB。
不装 flash-attn（Windows 上装不上）：配音服务自动用 PyTorch 自带的注意力（sdpa），能用，只是显存多用一点。
不装 SoX：只有我们不用的旧版 25Hz 模型才用到（配音服务里放了个空模块顶替，不会去找它）。
不装 gradio（官方网页演示用的，我们有自己的「配音」页）。

模型从魔搭下（国内快；一键补齐判断魔搭不通时 AGENT_MODEL_SOURCE=hf，改走 hf-mirror），放 models\\tts\\，不进 GitHub、不进压缩包：
  Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice   预设音色（9 个，其中 5 个中文）+ 一句话控制语气
  Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign   用一段文字描述造一个新音色
  Qwen/Qwen3-ForcedAligner-0.6B          时间轴对齐（v1.8.14）：音频 + 原文 → 每个字的开始、结束，字幕和声音对得上（约 1.8 GB）
都是 Apache 2.0 许可证，可以商用。配音模型每个大约 4~5 GB。
对齐模型的代码在 qwen-asr 包里：它要 Transformers 4.57.6，和 qwen-tts 锁的 4.57.3 只差小版本，用 --no-deps 装、不动 Transformers；
它一导入就 import nagisa（日语分词，我们不用），和 sox 一样放个空模块顶替。
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
QWEN_ASR = "qwen-asr==0.0.6"      # 只用里面的对齐器（Qwen3ForcedAligner），不听写
# qwen-tts 0.1.1 要的库（去掉了 gradio 和 sox：sox 在配音服务里用空模块顶替）。Transformers、accelerate 必须是这两个版本（官方锁死的）
DEPS = ["transformers==4.57.3", "accelerate==1.12.0", "librosa", "soundfile", "onnxruntime", "einops",
        "huggingface_hub", "safetensors", "fastapi", "uvicorn"]
TORCHAUDIO = [
    ("阿里云镜像", ["install", f"torchaudio=={A.TORCH}+cu128", "-f", "https://mirrors.aliyun.com/pytorch-wheels/cu128/"]),
    ("PyTorch 官方", ["install", f"torchaudio=={A.TORCH}", "--index-url", "https://download.pytorch.org/whl/cu128", "--extra-index-url", "https://pypi.org/simple"]),
    ("上海交大镜像", ["install", f"torchaudio=={A.TORCH}+cu128", "-f", "https://mirror.sjtu.edu.cn/pytorch-wheels/cu128/"]),
]
MODELS = [("预设音色 CustomVoice", "Qwen/" + paths.TTS_MODELS["custom"]),
          ("描述音色 VoiceDesign", "Qwen/" + paths.TTS_MODELS["design"]),
          ("时间轴对齐模型 ForcedAligner", "Qwen/" + paths.ALIGN_MODEL)]
ASR_MODEL = "Qwen3-ASR-0.6B"
NO_TOKENIZER = {paths.ALIGN_MODEL, ASR_MODEL}       # 这两个没有声音编解码器
TOKENIZER = "Qwen/Qwen3-TTS-Tokenizer-12Hz"     # 正常已经在模型的 speech_tokenizer 文件夹里；缺了才单独下
SOURCE = os.environ.get("AGENT_MODEL_SOURCE", "modelscope")


# 装完后的自检：在配音环境里真的导入一次。qwen-tts 一导入就 import sox，而 SoX 我们不装（只有旧版 25Hz 模型用它）：
# 和配音服务（app/tts_server.py）一样，导入前放一个空的 sox 模块顶替（v1.8.7 这里忘了放，自检报错、模型没下）
# 对齐器（qwen-asr）一导入就 import nagisa：也放空模块顶替（和 app/tts_server.py 一样）
CHECK = ("import sys, types\n"
         "sys.modules.setdefault('sox', types.ModuleType('sox'))\n"
         "sys.modules.setdefault('nagisa', types.ModuleType('nagisa'))\n"
         "import torch, transformers, qwen_tts\n"
         "from qwen_asr import Qwen3ForcedAligner\n"
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
    say("安装时间轴对齐器 qwen-asr（几百 KB，只用它的对齐，不动 Transformers）")
    if not A.pip_any("--no-deps", QWEN_ASR):
        say("qwen-asr 没装上，看上面的报错", "!")
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
    tok = dest.name in NO_TOKENIZER or (dest / "speech_tokenizer" / "config.json").exists()     # 对齐模型、听写模型没有声音编解码器
    return ((dest / "config.json").exists() and tok and any(dest.glob("*.safetensors")) and not any(dest.rglob("*.incomplete")))


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
        size = "约 1.8 GB" if dest.name in NO_TOKENIZER else "大约 4~5 GB"
        say(f"下载 {name}（{size}）：从{'hf-mirror' if SOURCE == 'hf' else '魔搭'} {repo}，放到 {paths.show(dest)}")
        download(repo, dest)
        if dest.name not in NO_TOKENIZER and not (dest / "speech_tokenizer" / "config.json").exists():
            say("模型里没带声音编解码器（speech_tokenizer），单独下一份")
            download(TOKENIZER, dest / "speech_tokenizer")
        say(f"{name} 下好了" if done(dest) else f"{name} 好像没下全，再运行一次接着下", "✓" if done(dest) else "!")
    return 0


BREEZE = "BreezeBlue/breeze-tts-2"


def breeze_done(d: Path) -> bool:
    return ((d / "config.json").exists() and any(d.glob("*.safetensors")) and (d / "audio_tokenizer" / "config.json").exists()
            and not any(d.rglob("*.incomplete")))


def install_breeze():
    """Breeze TTS 2 的权重：先 hf-mirror（官方仓库的镜像），不行再试魔搭。要登录才给下的话，用 设置 › 语音 里填的 Hugging Face 令牌（HF_TOKEN）。"""
    dest = paths.MODELS_TTS / "breeze-tts-2"
    if breeze_done(dest):
        say("Breeze TTS 2 的权重已经下好了，跳过", "✓")
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    errs = []
    for src in ("hf", "modelscope"):
        try:
            if src == "hf":
                os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
                os.environ["HF_HUB_DISABLE_XET"] = "1"          # hf-mirror 不支持新的 Xet 下载方式（Kev 踩过）
                try:
                    from huggingface_hub import snapshot_download
                except ImportError:
                    say("先装下载工具 huggingface_hub")
                    subprocess.run([sys.executable, "-m", "pip", "install", "huggingface_hub"], check=False)
                    from huggingface_hub import snapshot_download
                say(f"下载 Breeze TTS 2 的权重：从 hf-mirror {BREEZE}，放到 {paths.show(dest)}（几个 GB，断了再点一次接着下）")
                snapshot_download(BREEZE, local_dir=str(dest), token=os.environ.get("HF_TOKEN") or None)
            else:
                try:
                    from modelscope import snapshot_download as ms
                except ImportError:
                    subprocess.run([sys.executable, "-m", "pip", "install", "modelscope"], check=False)
                    from modelscope import snapshot_download as ms
                say(f"改从魔搭试一次：{BREEZE}")
                ms(BREEZE, local_dir=str(dest))
            if breeze_done(dest):
                say("Breeze TTS 2 的权重下好了", "✓")
                return 0
            errs.append(f"{src}：下完了但文件不全")
        except Exception as e:
            msg = str(e)
            print(f"{src} 不行：{msg[:600]}", flush=True)
            if any(x in msg for x in ("401", "403", "gated", "Gated", "accept", "authorized")):
                errs.append(f"{src}：要登录才给下（{msg[:80]}）")
                say("Hugging Face 上这个模型要先登录、点同意许可证才能下：到 huggingface.co 打开 BreezeBlue/breeze-tts-2 点同意，"
                    "再在 Hugging Face 设置里建一个 Read 令牌，填到 Agent 的 设置 › 语音 ›「Hugging Face 令牌」，回来再点一次", "!")
            else:
                errs.append(f"{src}：{msg[:120]}")
                say(f"{'hf-mirror' if src == 'hf' else '魔搭'} 没下成：{msg[:120]}", "!")
    print("Breeze TTS 2 的权重没下成：" + "；".join(errs), flush=True)
    return 7


def main():
    args = sys.argv[1:]
    code = 0
    if "--breeze" in args:                         # 只下 Breeze 的权重（配音环境由一键装好那一步先保证）
        code = install_breeze()
        print("\nBreeze TTS 2 装好了。" if not code else "\nBreeze TTS 2 没装好，看上面的说明。")
        return code
    if "--asr" in args:                            # 只下听写模型（配音环境要先装好）
        MODELS[:] = [("听写模型 Qwen3-ASR", "Qwen/" + ASR_MODEL)]
        code = install_models()
        print("\n听写模型下好了。" if not code else "\n听写模型没下全，再点一次接着下。")
        return code
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
