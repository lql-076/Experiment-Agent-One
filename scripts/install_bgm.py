r"""安装配乐引擎 ACE-Step 1.5（v3.1）：整备 › 「配音、语音、配乐」一键装好的最后一步调用。
可以重复运行：下过的、解压过的、模型下过的都跳过；下到一半断了，再运行一次接着下。

  python scripts/install_bgm.py

做什么（都是写死的，不让模型随手敲命令）：
1. 解压工具 7-Zip（7za.exe，npm 上的 7zip-bin 5.2.0 包里带的官方程序，先 npmmirror 再 npmjs，下完对 sha512），放 tools\7z\。
2. 下 ACE-Step 官方的 Windows 便携包 ACE-Step-1.5.7z（files.acemusic.ai，自带 python_embedded 和装好的依赖、PyTorch 2.7.1 cu128，
   RTX 50 系能用）到 tools\downloads\，多线程分段下、断了接着下（scripts\fastdl.py）。
3. 解压到 Agent 文件夹里的 ace-step\（先解到 ace-step.tmp，好了再改名；已经有的旧版改名留着，不删）。
4. 用它自带的 Python 下模型（约 10GB）：先魔搭、不行再 hf-mirror，放 ace-step\checkpoints\（就是它自己的 ACE-Step/Ace-Step1.5 主仓库：
   出曲子的 DiT turbo、VAE、文本编码器、1.7B 语言模型——我们不开语言模型，但它是同一个仓库一起下的）。
5. 用它自带的 Python 导入一次 PyTorch 看显卡在不在。
装好以后 app\bgm.py 直接用 ace-step\ 这一份（设置 › 配乐 不用填）。启动时不走它的 start_api_server.bat（那个会检查更新、问 Y/N，没有窗口就卡住），
而是照那个 bat 一样直接跑 python_embedded\python.exe acestep\api_server.py。

测试时能用环境变量换下载地址：AGENT_7Z_URLS、AGENT_ACE_URLS（空格隔开）。
"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from app import paths  # noqa: E402
import fastdl  # noqa: E402

paths.keep_inside()

IS_WIN = os.name == "nt"
ACE = ROOT / "ace-step"
DL = paths.TOOLS / "downloads"
SEVEN = paths.TOOLS / "7z" / ("7za.exe" if IS_WIN else "7za")
SEVEN_PKG = "7zip-bin-5.2.0.tgz"
SEVEN_SHA512 = "ukTPVhqG4jNzMro2qA9HSCSSVJN3aN7tlb+hfqYCt3ER0yWroeA2VR38MNrOHLQ/cVj+DaIMad0kFCtWWowh/A=="
SEVEN_URLS = [("npmmirror", f"https://registry.npmmirror.com/7zip-bin/-/{SEVEN_PKG}"), ("npmjs", f"https://registry.npmjs.org/7zip-bin/-/{SEVEN_PKG}")]
ACE_URLS = [("ACE Studio 官方", "https://files.acemusic.ai/acemusic/win/ACE-Step-1.5.7z")]
ACE_REPO = "ACE-Step/Ace-Step1.5"
NEED = ("acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B")      # 出纯音乐要的三样（语言模型不开）
FEED = os.environ.get("AGENT_FEED") == "1"


def say(msg, kind=""):
    print(("@@SAY " + kind + msg) if FEED else msg, flush=True)


def emit(**kw):
    print("@@PROGRESS " + json.dumps(kw, ensure_ascii=False), flush=True)


def urls(env, default):
    v = os.environ.get(env, "").split()
    return [(f"源{i + 1}", u) for i, u in enumerate(v)] if v else default


def ace_python(d=ACE):
    for sub in ("python_embedded", "python_embeded"):
        for exe in (("python.exe",) if IS_WIN else ("python", "python.exe")):
            p = d / sub / exe
            if p.exists():
                return p
    return None


def code_ok(d=ACE):
    return (d / "acestep" / "api_server.py").exists() and ace_python(d) is not None


def models_ok(d=ACE):
    ck = d / "checkpoints"
    return all((ck / m).is_dir() and any((ck / m).rglob("*.safetensors")) for m in NEED) and not any(ck.rglob("*.incomplete"))


# ---------- 1. 7-Zip ----------
def ensure_7z():
    if SEVEN.exists():
        say("解压工具 7-Zip 已经有了", "✓")
        return SEVEN
    want = "package/win/x64/7za.exe" if IS_WIN else "package/linux/x64/7za"
    errs = []
    for name, url in urls("AGENT_7Z_URLS", SEVEN_URLS):
        try:
            say(f"下载解压工具 7-Zip（{SEVEN_PKG}，约 5MB）：{name}")
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(20, read=60)) as c:
                r = c.get(url)
                r.raise_for_status()
            data = r.content
            got = base64.b64encode(hashlib.sha512(data).digest()).decode()
            if got != SEVEN_SHA512:
                raise RuntimeError("校验码对不上（文件被改过或者下坏了）")
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
                f = t.extractfile(want)
                if not f:
                    raise RuntimeError("压缩包里没有 " + want)
                SEVEN.parent.mkdir(parents=True, exist_ok=True)
                tmp = SEVEN.with_name(SEVEN.name + ".part")
                tmp.write_bytes(f.read())
                tmp.chmod(0o755)
                tmp.replace(SEVEN)
            say(f"7-Zip 放好了：{paths.show(SEVEN)}", "✓")
            return SEVEN
        except Exception as e:
            errs.append(f"{name}：{str(e)[:100]}")
            say(f"「{name}」不行：{str(e)[:100]}，换下一个", "!")
    raise RuntimeError("7-Zip 没下成：" + "；".join(errs))


# ---------- 2、3. 便携包 ----------
def extract(arc: Path, sz: Path):
    """解压到 ace-step.tmp，找到里面带 acestep\\ 和 python_embedded\\ 的那一层，改名成 ace-step。"""
    tmp = ROOT / "ace-step.tmp"
    if tmp.exists():
        tmp.rename(ROOT / f"ace-step.tmp-old-{int(time.time())}")
    size = arc.stat().st_size
    say(f"解压 {arc.name}（{size / 2**30:.2f} GB，几分钟，硬盘慢的话更久）")
    p = subprocess.Popen([str(sz), "x", str(arc), f"-o{tmp}", "-y", "-bsp1", "-bso0", "-bse1"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    buf, last, err = "", -1, []
    while True:
        ch = p.stdout.read(256)
        if not ch:
            break
        buf += ch.decode("utf-8", errors="replace")
        parts = re.split(r"[\r\n\b]+", buf)
        buf = parts.pop()
        for x in parts:
            m = re.search(r"(\d{1,3})%", x)
            if m:
                pct = int(m.group(1))
                if pct != last:
                    last = pct
                    emit(phase="解压 ACE-Step", src="7-Zip", done=size * pct // 100, total=size)
            elif x.strip() and not x.strip().startswith(("7-Zip", "Scanning", "Extracting", "Everything", "Path", "Type", "Physical", "Headers", "Solid", "Blocks", "Size", "Compressed", "Files", "Folders")):
                err.append(x.strip())
    code = p.wait()
    if code != 0:
        raise RuntimeError(f"解压失败（7-Zip 退出码 {code}）：" + " ".join(err[-3:])[:200])
    emit(phase="解压 ACE-Step", src="7-Zip", done=size, total=size)
    found = next((d for d in [tmp, *sorted(tmp.iterdir())] if d.is_dir() and code_ok(d)), None) if tmp.exists() else None
    if not found:
        raise RuntimeError("解压出来的东西里没找到 acestep\\api_server.py 和 python_embedded（压缩包可能不对）")
    if ACE.exists():
        old = ROOT / f"ace-step-old-{int(time.time())}"
        ACE.rename(old)
        say(f"以前的 ace-step 改名留着：{old.name}（不删，确认新的好用了你可以自己删）")
    found.rename(ACE)
    if tmp.exists() and found != tmp:
        try:
            tmp.rmdir()                       # 空的才删得掉
        except OSError:
            pass
    say(f"ACE-Step 解压好了：{paths.show(ACE)}", "✓")


def ensure_code():
    if code_ok():
        say("ACE-Step 的程序已经解压好了，跳过", "✓")
        return
    sz = ensure_7z()
    DL.mkdir(parents=True, exist_ok=True)
    arc = fastdl.fetch(DL / "ACE-Step-1.5.7z", urls("AGENT_ACE_URLS", ACE_URLS), phase="下载 ACE-Step 便携包")
    say("检查压缩包有没有下坏（7-Zip 测一遍）")
    r = subprocess.run([str(sz), "t", str(arc), "-bso0", "-bsp0"], capture_output=True, text=True, errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        bad = arc.with_name(arc.name + f".坏的-{int(time.time())}")
        arc.rename(bad)
        raise RuntimeError("压缩包下坏了（已改名 " + bad.name + "），再点一次会重新下：" + (r.stdout + r.stderr).strip()[-160:])
    extract(arc, sz)


# ---------- 4. 模型 ----------
DL_CODE = r"""
import os, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
from acestep.api import model_download as D
ck, src = sys.argv[1], sys.argv[2]
if src == "modelscope":
    D.download_from_modelscope(%r, ck, "acestep-v15-turbo")
else:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    D.download_from_huggingface(%r, ck, "acestep-v15-turbo")
""" % (ACE_REPO, ACE_REPO)


def ensure_models():
    if models_ok():
        say("ACE-Step 的模型已经下好了，跳过", "✓")
        return
    ck = ACE / "checkpoints"
    ck.mkdir(parents=True, exist_ok=True)
    py = ace_python()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    errs = []
    for src, name in (("modelscope", "魔搭"), ("hf", "hf-mirror")):
        say(f"下载 ACE-Step 的模型（约 10GB）：从{name} {ACE_REPO}，放到 {paths.show(ck)}")
        r = subprocess.run([str(py), "-c", DL_CODE, str(ck), src], cwd=str(ACE), env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and models_ok():
            say("ACE-Step 的模型下好了", "✓")
            return
        errs.append(f"{name}：退出码 {r.returncode}" + ("" if r.returncode else "，但文件不全"))
        say(f"{name}没下全，{'换 hf-mirror 再试' if src == 'modelscope' else '都试过了'}", "!")
    raise RuntimeError("模型没下成：" + "；".join(errs))


# ---------- 5. 自检 ----------
def check():
    py = ace_python()
    r = subprocess.run([str(py), "-c", "import torch; print('PyTorch', torch.__version__, '| 显卡', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '用不了')"],
                       cwd=str(ACE), capture_output=True, text=True, errors="replace", env=dict(os.environ, PYTHONUTF8="1"),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout or "").strip().splitlines()
    if r.returncode != 0:
        print((r.stderr or "")[-1500:], flush=True)
        raise RuntimeError("它自带的 Python 导入 PyTorch 出错：" + ((r.stderr or "").strip().splitlines() or ["?"])[-1][:200])
    info = out[-1] if out else ""
    if "用不了" in info:
        say("ACE-Step 自带的 PyTorch 找不到显卡（要 CUDA 12.8 的显卡驱动：NVIDIA 驱动更新到 570 以上）：" + info, "!")
    else:
        say("ACE-Step 能用了：" + info, "✓")


def main():
    if not IS_WIN and not os.environ.get("AGENT_ACE_URLS"):
        print("ACE-Step 的便携包只有 Windows 版。")
        return 1
    ensure_code()
    ensure_models()
    check()
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
        say(str(e)[:300], "!")
        code = 9
    sys.exit(code)
