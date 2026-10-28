"""安装本地模型环境（ai-env）：显卡版 PyTorch + Transformers + PEFT + Kev。
由「安装本地模型环境.bat」调用。可以重复运行，装过的会跳过。

PyTorch 显卡版（约 3GB）：
  1. tools\\wheels 文件夹里已经有安装包（你手动放的，或者上次下好的）就直接用；
  2. 否则同时测 阿里云 / 上海交大 / 南京大学 / PyTorch 官方 这几个源，用最快的多线程下载（scripts\\fastdl.py），
     进度、速度、还剩多久都会显示在界面上；断了再运行一次会接着下；
  3. 都不行再退回让 pip 自己从这几个源装。
其余的库用 pip 装，进度也会显示（--progress-bar raw）。
"""
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import paths  # noqa: E402

paths.keep_inside()      # pip 缓存、临时文件都放进 Agent 文件夹，不往 C 盘写

ENV = ROOT / "ai-env"
PY = ENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
WHEELS = ROOT / "tools" / "wheels"
TORCH = "2.8.0"
PYPI_BACKUP = "https://pypi.tuna.tsinghua.edu.cn/simple"


FEED = os.environ.get("AGENT_FEED") == "1"     # 一键补齐在跑：说的话加 @@SAY，进后台页的进展报告


def say(msg, kind=""):
    """kind：""普通、"!"要注意、"✓"好了。"""
    print(("@@SAY " + kind + msg) if FEED else f"\n==== {msg}", flush=True)


def run(args, check=True):
    print("  >", " ".join(map(str, args)), flush=True)
    r = subprocess.run([str(a) for a in args])
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败（{r.returncode}）")
    return r.returncode == 0


PB = []   # pip 够新就加 --progress-bar raw：每 0.25 秒报一次下载进度，界面能显示


def pip(*args, check=True):
    extra = PB if args and args[0] == "install" else []
    return run([PY, "-m", "pip", *args, *extra], check=check)


def pip_raw_ok():
    r = subprocess.run([str(PY), "-m", "pip", "--version"], capture_output=True, text=True)
    try:
        major, minor = (int(x) for x in r.stdout.split()[1].split(".")[:2])
        return (major, minor) >= (24, 1)
    except Exception:
        return False


def torch_sources():
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    name = f"torch-{TORCH}+cu128-{tag}-{tag}-win_amd64.whl"
    enc = name.replace("+", "%2B")
    return name, [("阿里云镜像", f"https://mirrors.aliyun.com/pytorch-wheels/cu128/{enc}"),
                  ("上海交大镜像", f"https://mirror.sjtu.edu.cn/pytorch-wheels/cu128/{enc}"),
                  ("南京大学镜像", f"https://mirrors.nju.edu.cn/pytorch/whl/cu128/{enc}"),
                  ("PyTorch 官方", f"https://download.pytorch.org/whl/cu128/{enc}")]


def fast_torch():
    """自己多线程下 PyTorch 安装包，下好放 tools\\wheels。返回文件路径；不行返回 None。"""
    if os.name != "nt":
        return None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import fastdl
        name, sources = torch_sources()
        path = fastdl.fetch(WHEELS / name, sources, phase="下载 PyTorch")
        say("PyTorch 安装包留在 tools\\wheels（约 3GB），以后重装不用再下；不需要了可以自己删掉。")
        return path
    except Exception as e:
        say(f"多线程下载没成：{e}，改用 pip 自己下（会慢一些）", "!")
        return None


MIRROR_FIRST = os.environ.get("AGENT_PIP_MIRROR") == "1"   # 一键补齐判断网络不好时会设这个


def pip_any(*args):
    """先用官方 PyPI，不通再换清华镜像（AGENT_PIP_MIRROR=1 时反过来）。"""
    if MIRROR_FIRST:
        if pip("install", "-i", PYPI_BACKUP, *args, check=False):
            return True
        say("清华镜像不行，换官方 PyPI 再试", "!")
        return pip("install", *args, check=False)
    if pip("install", *args, check=False):
        return True
    say("官方 PyPI 不通，换清华镜像再试", "!")
    return pip("install", "-i", PYPI_BACKUP, *args, check=False)


def torch_ok():
    r = subprocess.run([str(PY), "-c", "import torch,sys;print(torch.__version__);sys.exit(0 if torch.cuda.is_available() else 3)"],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def make_env():
    """建环境、把 pip 升到最新。安装配音（scripts/install_tts.py）也用这个，只是 ENV、PY 换成 tts-env。"""
    if not PY.exists():
        say(f"创建环境：{ENV}")
        venv.EnvBuilder(with_pip=True).create(ENV)
    say("先把 pip 升到最新（新版才能报下载进度）")
    pip("install", "-U", "pip", *(["-i", PYPI_BACKUP] if MIRROR_FIRST else []), check=False)
    if pip_raw_ok() and not PB:
        PB.extend(["--progress-bar", "raw"])


def ensure_torch():
    """装显卡版 PyTorch（装过的跳过）。装好返回 True。"""
    ok, info = torch_ok()
    if ok:
        say(f"显卡版 PyTorch 已经装好：{info}", "✓")
    else:
        say(f"安装显卡版 PyTorch {TORCH}（cu128，约 3GB，要等一会）")
        tries = []
        tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
        local = sorted(WHEELS.glob(f"torch-{TORCH}*cu128*{tag}*.whl")) if WHEELS.exists() else []
        if not local:
            got = fast_torch()
            local = [got] if got else []
        if local:
            tries.append(("下好的安装包", ["install", str(local[-1])]))
            tries.append(("下好的安装包（依赖走清华镜像）", ["install", str(local[-1]), "-i", PYPI_BACKUP]))
        tries += [
            ("阿里云镜像", ["install", f"torch=={TORCH}+cu128", "-f", "https://mirrors.aliyun.com/pytorch-wheels/cu128/"]),
            ("PyTorch 官方", ["install", f"torch=={TORCH}", "--index-url", "https://download.pytorch.org/whl/cu128", "--extra-index-url", "https://pypi.org/simple"]),
            ("上海交大镜像", ["install", f"torch=={TORCH}+cu128", "-f", "https://mirror.sjtu.edu.cn/pytorch-wheels/cu128/"]),
        ]
        for name, args in tries:
            say(f"用 pip 安装 PyTorch：{name}")
            if pip(*args, check=False):
                ok, info = torch_ok()
                if ok:
                    say(f"PyTorch 装好了，显卡能用：{info}", "✓")
                    break
                say(f"装上了，但用不了显卡：{info}", "!")
        if not ok:
            print(f"""
PyTorch 显卡版没装上。手动下载这个文件：
    torch-{TORCH}+cu128-cp312-cp312-win_amd64.whl
（在阿里云镜像 https://mirrors.aliyun.com/pytorch-wheels/cu128/ 页面里搜 {TORCH}+cu128-cp312）
放到这个文件夹：
    {WHEELS}
然后再运行一次（「安装本地模型环境.bat」或「安装配音.bat」）。""")
    return ok


def main():
    if sys.version_info < (3, 12):
        print("需要 Python 3.12 或更新（Kev 的要求）。先装 Python 3.12，再运行一次。")
        return 1
    make_env()
    if not ensure_torch():
        return 2

    say("安装 Transformers、PEFT、量化库（约 500MB，从 PyPI）")
    if not pip_any("transformers>=5.17,<6", "peft>=0.21", "accelerate>=1.15", "bitsandbytes>=0.48",
                   "fastapi", "uvicorn", "pydantic>=2.9", "huggingface_hub", "safetensors", "sentencepiece"):
        say("Transformers 这些没装上，看上面的报错；网络问题的话过一会再试", "!")
        return 3

    say("安装 Kev（源码已在 kev 文件夹）")
    if not pip_any("-e", str(ROOT / "kev") + "[serve]"):
        say("Kev 没装上。决策脑会只用语义路由一票，不影响别的功能", "!")

    ok, info = torch_ok()
    r = subprocess.run([str(PY), "-c", "import torch,transformers,peft;print('PyTorch',torch.__version__,'| 显卡',torch.cuda.get_device_name(0),'| Transformers',transformers.__version__,'| PEFT',peft.__version__)"],
                       capture_output=True, text=True)
    say("本地模型环境装好了：" + (r.stdout.strip() or r.stderr.strip()[-300:]), "✓")
    print("\n下一步：双击「下载模型.bat」下载底座和嵌入模型。然后回到界面 设置 › 整备 点「重新自检」。")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        print("出错了：", e)
        code = 9
    sys.exit(code)
