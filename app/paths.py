"""所有文件夹的位置。整个 Agent 文件夹可以放在任何盘，这里的路径都相对于它自动算出来。"""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent.parent          # 例如 D:\Agent
APP = ROOT / "app"
UI = ROOT / "ui"
DATA = ROOT / "data"                                   # 设置、数据库、日志（自动生成）
LOGS = DATA / "logs"
MODELS = ROOT / "models"
MODELS_BASE = MODELS / "base" / "MiniCPM5-2B"          # 底座（魔搭 OpenBMB/MiniCPM5-2B）
MODELS_EMBED = MODELS / "embed" / "Qwen3-Embedding-0.6B"  # 嵌入模型（魔搭 Qwen/Qwen3-Embedding-0.6B）
MODELS_BRAINS = MODELS / "brains"                      # 小脑 LoRA，每个小脑一个子文件夹
HF_CACHE = MODELS / "hf-cache"                         # Kev 权重的下载缓存
KEV = ROOT / "kev"                                     # Kev 源码（已随项目打包）
AI_ENV = ROOT / "ai-env"                               # 本地模型的 Python 环境（安装本地模型环境.bat 生成）
TTS_ENV = ROOT / "tts-env"                             # 配音的 Python 环境（设置 › 本地模型「安装配音」或 安装配音.bat 生成；配音要的 Transformers 版本和 ai-env 不一样，分开装）
MODELS_TTS = MODELS / "tts"                            # 配音模型（魔搭 Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice、-VoiceDesign）
TTS_MODELS = {"custom": "Qwen3-TTS-12Hz-1.7B-CustomVoice",  # 预设音色 + 一句话控制语气
              "design": "Qwen3-TTS-12Hz-1.7B-VoiceDesign"}  # 用一段文字描述造音色
ALIGN_MODEL = "Qwen3-ForcedAligner-0.6B"               # 时间轴对齐（v1.8.14）：音频 + 原文 → 每个字的开始、结束（Apache 2.0，约 1.8 GB，也在 models\tts）
TTS_OUT = ROOT / "配音输出"                             # 保存的配音：每次一个文件夹（不进仓库、不进压缩包）
MEMORY = ROOT / "memory"                               # agent 自己的文件夹：记忆、技能、提示词
TRAINING = ROOT / "training"                           # 慢成长用的样本
TOOLS = ROOT / "tools"

IS_WIN = sys.platform.startswith("win")


def ai_python() -> Path:
    return AI_ENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def tts_python() -> Path:
    return TTS_ENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


TRAINING_RULES = """# 训练数据的规矩（写死在代码里）

这里的数据以后用来训练小脑和决策脑。只放这几种：
- 你自己发的消息、你的纠正
- DeepSeek 的处理记录（DeepSeek 官方明确允许用它的输出训练其他模型）
- 本地模型自己的输出

**不放任何「更强的模型」的输出**：网页 Claude、ChatGPT 这些的回答、带回的总结、聊天记录都不行，
回答时参考过这些内容的 DeepSeek 记录也不存。
原因：Anthropic 的用户条款不允许用 Claude 的服务去开发或训练 AI 模型，OpenAI 等的条款也有类似限制，一律不进最省事。
带回的总结只放在 memory\\总结，当参考资料读。
"""


def add_tool_paths():
    """一键补齐装的便携版 Git 在 tools\\git 里：加进本程序（和它开的子程序）的 PATH，不改系统设置。"""
    g = TOOLS / "git" / "cmd"
    if (g / ("git.exe" if IS_WIN else "git")).exists() and str(g) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(g) + os.pathsep + os.environ.get("PATH", "")


add_tool_paths()

CACHE = TOOLS / "cache"                                # pip、魔搭等的下载缓存（删了也没事，只是下次要重下）
TMP = TOOLS / "tmp"                                    # 安装时的临时文件


def keep_inside():
    """让所有下载缓存、临时文件都放进 Agent 文件夹，不往 C 盘用户目录里写。
    本程序和它开的所有子程序（pip、魔搭、Kev、模型服务）都按这里的来。"""
    for p in (CACHE, TMP):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
    os.environ.update({
        "PIP_CACHE_DIR": str(CACHE / "pip"),           # 默认在 C:\Users\你\AppData\Local\pip\cache
        "HF_HOME": str(HF_CACHE),                      # 默认在 C:\Users\你\.cache\huggingface
        "MODELSCOPE_CACHE": str(CACHE / "modelscope"),  # 默认在 C:\Users\你\.cache\modelscope
        "TORCH_HOME": str(CACHE / "torch"),
        "XDG_CACHE_HOME": str(CACHE),
        "CUDA_CACHE_PATH": str(CACHE / "cuda"),        # 显卡编译缓存，默认在 AppData\Roaming\NVIDIA
        "TMP": str(TMP), "TEMP": str(TMP),
        # HuggingFace 新的 Xet 下载方式要直连 cas-server.xethub.hf.co，hf-mirror 不支持（返回 401，Kev 的权重下不动）。
        # 关掉它，走老的按文件下载，hf-mirror 和官方都能用
        "HF_HUB_DISABLE_XET": "1",
    })
    import tempfile
    tempfile.tempdir = None                            # 让 Python 自己重新读 TEMP


keep_inside()


def ensure_dirs():
    for p in (DATA, LOGS, MODELS_BASE.parent, MODELS_EMBED.parent, MODELS_BRAINS, HF_CACHE, MEMORY, TRAINING, TOOLS):
        p.mkdir(parents=True, exist_ok=True)
    rules = TRAINING / "README.md"
    if not rules.exists():
        rules.write_text(TRAINING_RULES, "utf-8")


def show(p) -> str:
    """给界面看的路径：Windows 风格。"""
    s = str(p)
    return s.replace("/", "\\") if IS_WIN else s


def resolve(value: str, default: Path) -> Path:
    """设置里留空就用默认位置；填了相对路径就相对 Agent 文件夹。"""
    if not value:
        return default
    p = Path(os.path.expandvars(value))
    return p if p.is_absolute() else ROOT / p
