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
_ai_job = {"task": None}
T0 = time.time()          # 后端什么时候起来的（这个模块随后端一起加载）
GRACE = 120               # 开机缓冲：头 2 分钟里，会自己好的项没准备好时显示「启动中」，不判缺失
NAMES = {"driver": "显卡驱动", "python": "Python", "git": "Git", "aienv": "本地模型环境", "base": "底座模型", "embed": "嵌入模型",
         "models": "本地模型服务", "kev": "决策脑 Kev", "hwmon": "硬件监控", "ds": "DeepSeek Key", "qq": "QQ 官方机器人",
         "qqbind": "绑定你的 QQ", "qqpush": "测试主动提醒", "memory": "记忆文件夹"}


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


def run(d, **kw):
    return {"st": "run", "d": d, **kw}


async def c_aienv(force=False):
    """本地模型环境（显卡版 PyTorch）。
    模型服务就跑在这个环境里：它在线、能用显卡，就说明环境是好的，直接算就绪。
    以前每次都另开一个 Python 去加载 PyTorch，刚开机要 20 秒以上，被自检的时限掐断就成了「检测超时」，而且结果没记下来，每次都超时。
    现在只有模型服务不在线时才另开 Python 查：放在后台跑、不被时限打断，没查完显示「检测中」，查完记下来。"""
    place = paths.show(paths.AI_ENV)
    if not M.ai_ready():
        return miss("还没装本地模型环境", place=place)
    h = await M.health(max_age=10)
    if h and h.get("torch"):
        if not h.get("cuda"):
            res = miss(f"PyTorch {h['torch']} 用不了显卡（装成了 CPU 版？），重新运行 安装本地模型环境.bat", place=place)
        else:
            res = ok(f"PyTorch {h['torch']} · CUDA {h.get('cuda_version')} · 模型服务正在用它跑", place=place)
        _ai_cache.update(ts=time.time(), res=res)
        return res
    if not force and _ai_cache["res"] and time.time() - _ai_cache["ts"] < 600:
        return _ai_cache["res"]
    if M.server.alive():
        return run("模型服务正在启动，起来了就算好", place=place)
    t = _ai_job.get("task")
    if t is None or t.done():
        t = _ai_job["task"] = asyncio.create_task(_aienv_probe(place))
    try:
        return await asyncio.wait_for(asyncio.shield(t), 12)
    except asyncio.TimeoutError:
        return run("正在检查（刚开机第一次加载 PyTorch 要几十秒）", place=place)


async def _aienv_probe(place):
    code, out = await asyncio.to_thread(_run, [str(M.aipy()), "-c",
                                               "import torch,transformers,peft;print(torch.__version__,torch.cuda.is_available(),torch.version.cuda,transformers.__version__,peft.__version__)"], 240)
    if code != 0:
        res = miss(("加载 PyTorch 4 分钟都没反应" if code == -2 else "环境装了但导入失败：" + out[-160:]), place=place)
    else:
        tv, cuda, cv, trv, pv = out.split()[-5:]
        if cuda != "True":
            res = miss(f"PyTorch {tv} 用不了显卡（装成了 CPU 版？），重新运行 安装本地模型环境.bat", place=place)
        else:
            res = ok(f"PyTorch {tv} · CUDA {cv} · Transformers {trv} · PEFT {pv}", place=place)
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
    return wait("模型服务没在运行（启动后自动拉起；也可以点按钮现在启动）", action="start_models", heal=True)


async def c_kev():
    if not (M.kev_dir() / "kev" / "serve.py").exists():
        return miss("Kev 源码不在（项目里自带，别删 kev 文件夹）", place=paths.show(M.kev_dir()))
    if not M.ai_ready():
        return miss("先装本地模型环境", place=paths.show(M.kev_dir()))
    if settings.S["kevMode"] == "off":
        return wait("已在设置里关掉 Kev，决策脑只用语义路由一票")
    if await M.kev_ready():
        return ok("Kev 服务在线（127.0.0.1:%s）" % settings.S["kevPort"])
    have = M.kev_weights()
    if M.kevp.alive():
        return wait("Kev 正在启动" + ("" if have else "（第一次要下载约 2GB 权重，要等一会）"), action="start_kev")
    if have:
        return ok("权重已下载 · 闲着，用到才启动（不会再下载）", place=paths.show(paths.HF_CACHE))
    return wait("权重还没下载：点「一键补齐」或「现在启动 Kev」，经 hf-mirror 下载约 2GB（只下一次）", action="start_kev", place=paths.show(paths.HF_CACHE))


async def c_hwmon():
    from . import hwctl
    if settings.S.get("hwOn") and hwctl.ST["busy"]:      # 开关开着、正在拉起：等它一会儿再查
        for _ in range(12):
            if not hwctl.ST["busy"]:
                break
            await asyncio.sleep(1)
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            r = await c.get(settings.S["hwUrl"])
        from .hw import parse_lhm
        d = parse_lhm(r.json())
        if (d.get("cpu") or {}).get("temp") is not None:
            return ok(f"传感器可读 · CPU {d['cpu']['temp']:.0f}°C")
        return wait("助手在运行，但读不到 CPU 温度：装一下 PawnIO 驱动（pawnio.eu），装完重启电脑", running=True)
    except Exception:
        if settings.S.get("hwOn"):
            return wait("开关开着，助手正在启动或没起来" + (f"：{hwctl.ST['msg']}" if hwctl.ST.get("msg") else "") + "（每半分钟自动再拉一次）", heal=True)
        return miss("硬件监控助手没开：设置 › 硬件监控 打开（第一次弹一次管理员确认）")


async def c_ds():
    if not settings.get_secret("dsKey"):
        return miss("还没有填 Key")
    b = await deepseek.refresh_balance(force=True)
    if not b or b.get("err"):
        err = (b or {}).get("err") or "查不到余额"
        bad_key = any(x in err for x in ("401", "403", "Key 不对"))
        return miss(f"Key 验证失败：{err}", heal=not bad_key)      # 连不上（刚开机还没联网）会自己好；Key 不对不会
    return ok(f"Key 可用 · 余额 {deepseek.money(b['total'], b['currency'])} · 本月估计花了 ¥{deepseek.month_cost_cny():.2f}")


async def c_qq():
    if not BOT.configured():
        return miss("还没有填 AppID 和 AppSecret")
    if BOT.status == "online":
        return ok(BOT.detail + ("（沙箱）" if settings.S["qqSandbox"] else ""))
    try:
        await BOT.get_token(force=True)
        return wait(f"凭证有效，连接状态：{BOT.detail}", heal=True)
    except Exception as e:
        return miss(str(e)[:120], heal=True)


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


LIVE = ("aienv", "models", "kev", "hwmon", "qq", "ds")
RECHECK_IF_BAD = ("ds",)  # 这几项只在没好的时候重查（DeepSeek 要联网问余额，好了就不再每半分钟问一次）


def booting():
    return time.time() - T0 < GRACE


def settle(k, r):
    """开机缓冲：头 2 分钟里，会自己好的项（模型服务在加载、助手在启动、网络还没连上……）没准备好时显示「启动中」，
    不显示「缺失」；后台每 10 秒重查，好了自己变绿。过了 2 分钟还不行才按原样显示。"""
    if booting() and r.get("heal") and r.get("st") in ("miss", "wait"):
        r = dict(r, st="run", d="启动中 · " + r.get("d", ""))
    return r


def record(k, r, since=None, bump=False):
    """写回一项自检结果。since：开始查的时间，这期间你在界面上重查过这一项就以你那次为准（不覆盖）。
    状态变了：写进 backend.log；开机缓冲过后变成缺失的，再写进进展报告。返回状态变没变。"""
    r = dict(settle(k, r), at=time.time())
    cur = db.kv_get("checks") or {"res": {}}
    res = cur.setdefault("res", {})
    old = res.get(k) or {}
    if since is not None and old.get("at", 0) > since:
        return False
    changed = old.get("st") != r.get("st")
    res[k] = r
    if changed or bump:
        cur["ts"] = time.time()
    db.kv_set("checks", cur)
    if changed:
        name = NAMES.get(k, k)
        print(f"自检：{name} {ST_NAME.get(old.get('st'), '没查过')} → {ST_NAME.get(r['st'], r['st'])}：{r.get('d', '')[:160]}")
        if r["st"] == "miss" and not booting():
            from . import feed
            feed.add(f"整备：「{name}」缺失 · {r.get('d', '')[:120]}", "warn", job="整备")
    return changed


ST_NAME = {"ok": "已就绪", "miss": "缺失", "wait": "待处理", "run": "检测中"}


async def after_boot():
    """开机缓冲结束时调一次：还显示「启动中」的再查一遍（这次不再缓冲），然后在日志里写一句整备的情况；
    有没好的，也写进进展报告。"""
    cur = (db.kv_get("checks") or {}).get("res") or {}
    for k, r in list(cur.items()):
        if k in CHECKS and r.get("st") == "run":
            try:
                rr = await asyncio.wait_for(CHECKS[k](), 20)
            except asyncio.TimeoutError:
                rr = miss("检测超时")
            except Exception as e:
                rr = miss(f"检测出错：{str(e)[:120]}")
            record(k, rr, bump=True)
    cur = (db.kv_get("checks") or {}).get("res") or {}
    bad = [k for k in CHECKS if k in cur and cur[k].get("st") != "ok"]
    line = f"开机 2 分钟后的整备：{len(CHECKS) - len(bad)}/{len(CHECKS)} 就绪" + (
        "；没好的：" + "；".join(f"{NAMES.get(k, k)}（{cur[k].get('d', '')[:60]}）" for k in bad) if bad else "")
    print(line)
    if bad:
        from . import feed
        feed.add(line, "warn", job="整备")
    return bad


async def refresh_live() -> bool:
    """会自己变的几项（本地模型环境、模型服务、Kev、硬件监控助手、QQ、DeepSeek）：启动后它们陆续起来，后台每半分钟重查一次写回自检结果，
    整备上跟着变，不用你点重新自检。状态变了返回 True（界面据此刷新）。"""
    last = db.kv_get("checks")
    if not last or not last.get("res"):
        return False
    changed = False
    for k in LIVE:
        if k in RECHECK_IF_BAD and (last["res"].get(k) or {}).get("st") == "ok":
            continue
        t = time.time()
        try:
            r = await asyncio.wait_for(CHECKS[k](), 15)
        except Exception:
            continue
        # 一项一项写回；查这一项的时候你在界面上重查过它，就以你那次为准（以前是整轮都扔掉，开机时常常白查）
        if record(k, r, since=t):
            changed = True
    return changed


async def run_all():
    async def one(k, fn):
        try:
            return k, await asyncio.wait_for(fn(), 20)
        except asyncio.TimeoutError:
            return k, miss("检测超时", heal=True)
        except Exception as e:
            return k, miss(f"检测出错：{str(e)[:120]}")
    res = dict(await asyncio.gather(*(one(k, fn) for k, fn in CHECKS.items())))
    for k, r in res.items():
        record(k, r, bump=True)
    cur = (db.kv_get("checks") or {}).get("res") or {}
    bad = [f"{NAMES.get(k, k)}（{(cur.get(k) or {}).get('d', '')[:60]}）" for k in CHECKS if (cur.get(k) or {}).get("st") != "ok"]
    print(f"自检：{len(CHECKS) - len(bad)}/{len(CHECKS)} 就绪" + ("；没好的：" + "；".join(bad) if bad else ""))
    return {k: cur.get(k) for k in CHECKS}


def places():
    """整备里"放到哪"用的路径。"""
    return {"root": paths.show(paths.ROOT), "base": paths.show(M.base_dir()), "embed": paths.show(M.embed_dir()),
            "brains": paths.show(M.lora_dir()), "kev": paths.show(M.kev_dir()), "aienv": paths.show(paths.AI_ENV),
            "memory": paths.show(memory.root()), "hfcache": paths.show(paths.HF_CACHE), "training": paths.show(paths.TRAINING),
            "logs": paths.show(paths.LOGS)}

