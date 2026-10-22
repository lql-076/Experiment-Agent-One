"""测试用：模仿真脚本的输出（@@SAY 讲解、@@PROGRESS、pip raw、tqdm）。models 第一次会超时失败。"""
import json, os, sys, time
from pathlib import Path
k = sys.argv[1]; flag = Path(sys.argv[2]) / f"fake_{k}.flag"
FEED = os.environ.get("AGENT_FEED") == "1"
def say(m, kind=""): print(("@@SAY " + kind + m) if FEED else m, flush=True)
def prog(**kw): print("@@PROGRESS " + json.dumps(kw, ensure_ascii=False), flush=True)
total = 3_400_000_000
if k == "aienv":
    say("先把 pip 升到最新（新版才能报下载进度）")
    print("Successfully installed pip-25.3", flush=True)
    say("安装显卡版 PyTorch 2.8.0（cu128，约 3GB，要等一会）")
    prog(phase="测哪个源最快", src="", done=0, total=0, speed=0, eta=None)
    say("要下载 torch-2.8.0+cu128-cp313-cp313-win_amd64.whl。先同时测 4 个下载源哪个最快（阿里云镜像、上海交大镜像、南京大学镜像、PyTorch 官方，各下 3MB）")
    time.sleep(0.6)
    say("  阿里云镜像：能用，测速 28.3 MB/s，文件 3.17 GB")
    say("  上海交大镜像：能用，测速 11.2 MB/s，文件 3.17 GB")
    say("  南京大学镜像：连不上（HTTP 404）", "!")
    say("  PyTorch 官方：能用，测速 1.4 MB/s，文件 3.17 GB")
    say("测完了：最快的是「阿里云镜像」（28.3 MB/s）", "✓")
    say("用「阿里云镜像」下载，12 条连接分段一起下（每段 8MB），文件 3.17 GB")
    for i in range(1, 41):
        d = total * i / 40
        prog(phase="下载 PyTorch", src="阿里云镜像", done=d, total=total, speed=28e6, eta=(total - d) / 28e6)
        time.sleep(0.2)
    prog(phase="检查文件", src="阿里云镜像", done=0, total=1, speed=0, eta=None)
    say("下完了，检查文件有没有下坏（逐个文件校验，要几十秒）……"); time.sleep(0.5)
    prog(phase="检查文件", src="阿里云镜像", done=1, total=1, speed=0, eta=0)
    say("文件是好的", "✓")
    say("下好了，放在 F:\\Agent\\tools\\wheels\\torch-2.8.0+cu128-cp313-cp313-win_amd64.whl（3.17 GB）", "✓")
    say("用 pip 安装 PyTorch：下好的安装包")
    for name, size in (("networkx-3.7-py3-none-any.whl", 2_100_000), ("sympy-1.14.0-py3-none-any.whl", 6_300_000), ("transformers-5.20.1-py3-none-any.whl", 12_300_000)):
        print(f"  Downloading {name} ({size / 1e6:.1f} MB)", flush=True)
        for d in range(0, size + 1, size // 5):
            print(f"Progress {d} of {size}", flush=True); time.sleep(0.08)
    print("Installing collected packages: mpmath, sympy, networkx, MarkupSafe, jinja2, fsspec, filelock, torch", flush=True)
    time.sleep(0.8)
    print("Successfully installed MarkupSafe-3.0.2 filelock-3.20.0 fsspec-2025.9.0 jinja2-3.1.6 mpmath-1.3.0 networkx-3.7 sympy-1.14.0 torch-2.8.0+cu128", flush=True)
    say("PyTorch 装好了，显卡能用：2.8.0+cu128", "✓")
elif k == "models":
    say("下载 底座 MiniCPM5-2B（约 5GB）：从魔搭 OpenBMB/MiniCPM5-2B，放到 F:\\Agent\\models\\base\\MiniCPM5-2B")
    for f in ("config.json", "tokenizer.json", "generation_config.json"):
        sys.stdout.write(f"\rDownloading [{f}]: 100%|██████████| 12.0k/12.0k [00:00<00:00, 1.2MB/s]\n"); sys.stdout.flush(); time.sleep(0.1)
    for i in range(0, 101, 5):
        sys.stdout.write(f"\rDownloading [model.safetensors]: {i:3d}%|{'█' * (i // 10):<10}| {4.7 * i / 100:.2f}G/4.70G [00:{i // 5:02d}<00:20, 31.5MB/s]"); sys.stdout.flush(); time.sleep(0.15)
    print()
    if not flag.exists():
        flag.write_text("1"); print("httpx.ReadTimeout: The read operation timed out", flush=True); sys.exit(1)
    say("底座 MiniCPM5-2B（约 5GB） 下好了", "✓")
else:
    for i in range(0, 101, 25):
        print(f"做 {k} 第 {i}%", flush=True); time.sleep(0.2)
print(f"{k} 好了", flush=True)
