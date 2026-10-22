"""整备自检：每次启动都跑一遍，查到就绪的自动打勾。
快检（启动时）不会去启动模型、不会花钱；深检（按钮）才会启动模型服务、跑实测。
每一项都告诉界面"放到哪"，路径按你把 Agent 文件夹放在哪里自动算。
"""
import asyncio
import shutil
import subprocess
import sys
import time

import httpx

from . import db, deepseek, memory, paths, settings
from .models import M, NOWIN
from .qq import BOT

_ai_cache = {"ts": 0, "res": None}


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace", creationflags=NOWIN)
        return r.returncode, (r.stdout or r.stderr).strip()
    except FileNotFoundError:
        return -1, "没找到"
    except subprocess.TimeoutExpired:
        return -2, "超时"


def _size(p):
    try:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 2**30
    except Exception:
        return 0


def ok(d, **kw):
    return {"st": "ok", "d": d, **kw}


def miss(d, **kw):
    return {"st": "miss", "d": d, **kw}


def wait(d, **kw):
    return {"st": "wait", "d": d, **kw}


async def c_driver():
    code, out = await asyncio.to_thread(_run, ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    if code == 0 and out:
        name, drv, mem = [x.strip() for x in out.splitlines()[0].split(",")]
        return ok(f"{name.replace('NVIDIA GeForce ', '')} · 驱动 {drv} · {mem}")
    return miss("读不到 nvidia-smi：显卡驱动没装好")


async def c_python():
    v = sys.version_info
    d = f"Python {v.major}.{v.minor}.{v.micro}（后端正在用它运行）"
    return ok(d) if v >= (3, 12) else miss(d + "，Kev 需要 3.12 或更新")


async def c_git():
    code, out = await asyncio.to_thread(_run, ["git", "--version"])
    if code != 0:
        return miss("没找到 git：点上面的「一键补齐」会装一个便携版（只给 agent 用，不装进系统）")
    exe = shutil.which("git") or ""
    return ok(out + ("（便携版，在 tools\\git）" if str(paths.TOOLS) in exe else ""))


async def c_aienv(force=False):
    if not M.ai_ready():
        return miss("还没装本地模型环境", place=paths.show(paths.AI_ENV))
    if not force and _ai_cache["res"] and time.time() - _ai_cache["ts"] < 600:
        return _ai_cache["res"]
    code, out = await asyncio.to_thread(_run, [str(M.aipy()), "-c",
                                               "import torch,transformers,peft;print(torch.__version__,torch.cuda.is_available(),torch.version.cuda,transformers.__version__,peft.__version__)"], 120)
    if code != 0:
        res = miss("环境装了但导入失败：" + out[-160:], place=paths.show(paths.AI_ENV))
    else:
        tv, cuda, cv, trv, pv = out.split()[-5:]
        if cuda != "True":
            res = miss(f"PyTorch {tv} 用不了显卡（装成了 CPU 版？），重新运行 安装本地模型环境.bat", place=paths.show(paths.AI_ENV))
        else:
            res = ok(f"PyTorch {tv} · CUDA {cv} · Transformers {trv} · PEFT {pv}", place=paths.show(paths.AI_ENV))
    _ai_cache.update(ts=time.time(), res=res)
    return res


async def c_base():
    p = M.base_dir()
    if (p / "config.json").exists() and list(p.glob("*.safetensors")):
        return ok(f"模型文件在 · {_size(p):.1f} GB", place=paths.show(p))
    return miss("文件夹里没有 config.json 和 .safetensors", place=paths.show(p))


async def c_embed():
    p = M.embed_dir()
    if (p / "config.json").exists() and list(p.glob("*.safetensors")):
        return ok(f"模型文件在 · {_size(p):.1f} GB", place=paths.show(p))
    return miss("文件夹里没有 config.json 和 .safetensors", place=paths.show(p))


async def c_models(deep=False):
    h = await M.health(fresh=True)
    if h:
        if not h.get("cuda"):
            return miss(h.get("error") or "模型服务用不了显卡")
        bits = [f"显卡 {h.get('gpu', '').replace('NVIDIA GeForce ', '')}"]
        bits.append("嵌入模型已加载" if h.get("embed_loaded") else "嵌入模型未加载")
        bits.append("底座已加载" if h.get("base_loaded") else "底座闲置（用到才加载）")
        if h.get("vram", {}).get("alloc_gb") is not None:
            bits.append(f"占显存 {h['vram']['alloc_gb']} GB")
        if h.get("error"):
            return miss("；".join(bits) + "；出错：" + h["error"][:120])
        return ok(" · ".join(bits))
    if not M.ai_ready():
        return miss("先装本地模型环境")
    if deep:
        try:
            await M.ensure_server()
            return await c_models(False)
        except Exception as e:
            return miss(str(e)[:200])
    return wait("模型服务没在运行（启动后自动拉起；也可以点按钮现在启动）", action="start_models")


async def c_kev():
    if not (M.kev_dir() / "kev" / "serve.py").exists():
        return miss("Kev 源码不在（项目里自带，别删 kev 文件夹）", place=paths.show(M.kev_dir()))
    if not M.ai_ready():
        return miss("先装本地模型环境", place=paths.show(M.kev_dir()))
    if settings.S["kevMode"] == "off":
        return wait("已在设置里关掉 Kev，决策脑只用语义路由一票")
    if await M.kev_ready():
        return ok("Kev 服务在线（127.0.0.1:%s）" % settings.S["kevPort"])
    if M.kevp.alive():
        return wait("Kev 正在启动（第一次会下载约 2GB 权重，要等一会）", action="start_kev")
    return wait("按需启动：用到时自动启动；第一次启动会下载约 2GB 权重", action="start_kev", place=paths.show(paths.HF_CACHE))


async def c_hwmon():
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            r = await c.get(settings.S["hwUrl"])
        from .hw import parse_lhm
        d = parse_lhm(r.json())
        if (d.get("cpu") or {}).get("temp") is not None:
            return ok(f"传感器可读 · CPU {d['cpu']['temp']:.0f}°C")
        return wait("数据能读到，但没有 CPU 温度：装一下 PawnIO 驱动，并确认是管理员身份运行")
    except Exception:
        return miss("硬件监控助手没开：设置 › 硬件监控 打开（第一次弹一次管理员确认）")


async def c_ds():
    if not settings.get_secret("dsKey"):
        return miss("还没有填 Key")
    b = await deepseek.refresh_balance(force=True)
    if not b or b.get("err"):
        return miss(f"Key 验证失败：{(b or {}).get('err') or '查不到余额'}")
    return ok(f"Key 可用 · 余额 {deepseek.money(b['total'], b['currency'])} · 本月估计花了 ¥{deepseek.month_cost_cny():.2f}")


async def c_qq():
    if not BOT.configured():
        return miss("还没有填 AppID 和 AppSecret")
    if BOT.status == "online":
        return ok(BOT.detail + ("（沙箱）" if settings.S["qqSandbox"] else ""))
    try:
        await BOT.get_token(force=True)
        return wait(f"凭证有效，连接状态：{BOT.detail}")
    except Exception as e:
        return miss(str(e)[:120])


async def c_qqbind():
    if settings.S["qqUser"]:
        return ok("已绑定 openid " + settings.S["qqUser"][:8] + "…")
    cand = db.kv_get("qq_candidate")
    if cand:
        return wait(f"收到一条消息「{cand['text'][:16]}」，是你发的就点「是我」", action="qq_bind", extra={"openid": cand["openid"]})
    return miss("用你的 QQ 给机器人发一句话，这里会出现「是我」按钮")


async def c_qqpush():
    t = db.kv_get("qq_push_ok")
    if t:
        return ok("主动消息发送成功过（" + time.strftime("%m-%d %H:%M", time.localtime(t)) + "）", action="qq_test")
    if not settings.S["qqUser"]:
        return wait("先绑定你的 QQ")
    return wait("还没测过：点按钮发一条测试提醒", action="qq_test")


async def c_memory():
    r = memory.root()
    if not r.exists():
        return miss("文件夹还不在（启动后自动创建）", place=paths.show(r))
    git = (r / ".git").exists()
    if settings.S["useGit"] and not git:
        return wait("文件夹在，但还没有 git 记录（装好 git 后重启一次）", place=paths.show(r))
    return ok(f"文件夹在{' · git 记录中' if git else ''}", place=paths.show(r))


CHECKS = {"driver": c_driver, "python": c_python, "git": c_git, "aienv": c_aienv, "base": c_base, "embed": c_embed,
          "models": c_models, "kev": c_kev, "hwmon": c_hwmon, "ds": c_ds, "qq": c_qq, "qqbind": c_qqbind, "qqpush": c_qqpush,
          "memory": c_memory}


async def run_all():
    async def one(k, fn):
        try:
            return k, await asyncio.wait_for(fn(), 20)
        except asyncio.TimeoutError:
            return k, miss("检测超时")
        except Exception as e:
            return k, miss(f"检测出错：{str(e)[:120]}")
    res = dict(await asyncio.gather(*(one(k, fn) for k, fn in CHECKS.items())))
    db.kv_set("checks", {"ts": time.time(), "res": res})
    return res


def places():
    """整备里"放到哪"用的路径。"""
    return {"root": paths.show(paths.ROOT), "base": paths.show(M.base_dir()), "embed": paths.show(M.embed_dir()),
            "brains": paths.show(M.lora_dir()), "kev": paths.show(M.kev_dir()), "aienv": paths.show(paths.AI_ENV),
            "memory": paths.show(memory.root()), "hfcache": paths.show(paths.HF_CACHE), "training": paths.show(paths.TRAINING),
            "logs": paths.show(paths.LOGS)}

