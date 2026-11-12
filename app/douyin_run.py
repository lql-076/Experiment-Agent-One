r"""抖音发布的子进程（v3.2）：扫码登录、查登录还在不在、发一条视频。每次单独起一个，app/publish.py 起它、读它的输出、到时间还没完就停掉。

  python app/douyin_run.py login|check|upload|selftest 任务.json

任务.json（app/publish.py 写的，跑完就删）：
  {"cookie": 明文 cookie 的临时文件, "base": data\publish\run, "browser": Chrome / Edge 的路径, "headless": true,
   "file": 视频, "title", "desc", "tags": [...], "schedule": "2026-11-14 20:00" 或 "", "cover": 封面图（可选）, "cover_kind": "portrait" / "landscape",
   "declaration": "内容由AI生成", "collection": ""}
输出：普通的行是日志；@@J 开头的一行是给界面的：
  {"t": "log", "msg"} 进展　{"t": "qr", "img": "data:image/png;base64,…"} 扫码　{"t": "sms"} 要短信验证码　{"t": "done", "ok", "msg"} 结束
代码在 vendor/social-auto-upload（MIT，只拿了抖音那部分，原样没改；导入前在这里放好假的 conf、精简的 utils.login_qrcode，
把 patchright 的 launch 换成他电脑上的 Chrome / Edge——见那里的 README-本项目.md）。
由 publish.py 用 python.exe + CREATE_NO_WINDOW 起：它再起的 patchright 驱动、浏览器都在这个看不见的控制台里，不弹黑窗口。
测试时环境变量 AGENT_SAU_FAKE=假的实现（dev/fake_sau.py）。"""
import asyncio
import base64
import importlib.util
import json
import os
import re
import shutil
import sys
import traceback
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "vendor" / "social-auto-upload"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def emit(**kw):
    print("@@J " + json.dumps(kw, ensure_ascii=False), flush=True)


def say(msg):
    emit(t="log", msg=str(msg)[:400])


# ---------------- 导入原项目之前放好的东西 ----------------
def _stubs(job):
    base = Path(job["base"])
    (base / "utils").mkdir(parents=True, exist_ok=True)
    (base / "logs").mkdir(exist_ok=True)
    shutil.copyfile(CODE / "utils" / "stealth.min.js", base / "utils" / "stealth.min.js")   # 它按 BASE_DIR 找这个（隐藏自动化痕迹的脚本）
    conf = types.ModuleType("conf")
    conf.BASE_DIR = base
    conf.XHS_SERVER = ""
    conf.LOCAL_CHROME_PATH = job.get("browser") or ""
    conf.LOCAL_CHROME_HEADLESS = bool(job.get("headless", True))
    conf.DEBUG_MODE = False
    conf.YT_PROXY = None
    sys.modules["conf"] = conf

    q = types.ModuleType("utils.login_qrcode")             # 原来那个要 opencv 在终端里画二维码；我们的二维码显示在「发布」窗口里

    def build_login_qrcode_path(account_file, suffix="login_qrcode"):
        p = Path(account_file)
        return p.with_name(f"{p.stem}_{suffix}_{datetime.now():%Y%m%d_%H%M%S}.png")

    def save_data_url_image(data_url, output_path):
        if not str(data_url).startswith("data:image/") or ";base64" not in data_url.split(",", 1)[0]:
            raise ValueError("二维码不是 data:image 的 base64 图片")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        return Path(output_path)

    def remove_qrcode_file(p):
        if p and Path(p).exists():
            Path(p).unlink()
            return True
        return False

    q.build_login_qrcode_path = build_login_qrcode_path
    q.save_data_url_image = save_data_url_image
    q.remove_qrcode_file = remove_qrcode_file
    q.decode_qrcode_from_path = lambda p: None
    q.print_terminal_qrcode = lambda *a, **k: None
    sys.modules["utils.login_qrcode"] = q
    sys.path.insert(0, str(CODE))


def _patch_launch(browser):
    """原项目写死 channel="chromium"（要另外下一个 Chromium）：换成他电脑上的 Chrome / Edge。用的是临时的空白配置，不碰他自己的浏览器资料。"""
    if not browser:
        return
    from patchright.async_api import BrowserType
    orig = BrowserType.launch

    async def launch(self, *a, **kw):
        kw.pop("channel", None)
        kw["executable_path"] = browser
        return await orig(self, *a, **kw)
    BrowserType.launch = launch


def _hook_log(job):
    """原项目用 loguru 打日志（带颜色）：换成一行一行转给界面，另外照样记一份文件。看到「验证码」就告诉界面弹框。"""
    from loguru import logger
    logger.remove()

    def sink(m):
        rec = m.record
        txt = ANSI.sub("", str(rec["message"])).strip()
        if not txt:
            return
        emit(t="log", msg=txt[:400], lv=rec["level"].name)
        if "验证码" in txt and ("弹窗" in txt or "等待" in txt or "获取" in txt):
            emit(t="sms")
    logger.add(sink, level="INFO")
    logger.add(Path(job["base"]) / "logs" / "douyin.log", level="INFO", rotation="10 MB", retention="10 days", encoding="utf-8")


def _real():
    from uploader.douyin_uploader import main as M
    return M


# ---------------- 三件事 ----------------
async def real_login(job):
    M = _real()

    async def cb(payload):
        emit(t="qr", img=payload.get("image_data_url") or "")
    r = await M.douyin_setup(job["cookie"], handle=True, return_detail=True, qrcode_callback=cb, headless=bool(job.get("headless", True)))
    ok = bool(r.get("success"))
    if r.get("status") == "cookie_valid":
        return True, "原来的登录还有效，不用扫码"
    return ok, "扫码登录好了" if ok else ("登录没成：" + str(r.get("message") or r.get("status") or ""))


async def real_check(job):
    M = _real()
    ok = await M.cookie_auth(job["cookie"])
    return bool(ok), "登录还有效" if ok else "登录失效了，要重新扫码"


async def real_upload(job):
    M = _real()
    sch = (job.get("schedule") or "").strip()
    when = datetime.strptime(sch, "%Y-%m-%d %H:%M") if sch else 0
    cover = job.get("cover") or None
    land = job.get("cover_kind") == "landscape"
    app = M.DouYinVideo(job["title"], job["file"], list(job.get("tags") or []), when, job["cookie"], desc=job.get("desc") or "",
                        thumbnail_portrait_path=cover if cover and not land else None, thumbnail_landscape_path=cover if cover and land else None,
                        declaration=job.get("declaration") or None, collection_name=job.get("collection") or None,
                        publish_strategy=M.DOUYIN_PUBLISH_STRATEGY_SCHEDULED if when else M.DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
                        debug=False, headless=bool(job.get("headless", True)))
    await app.douyin_upload_video()
    return True, (f"定好了：{sch} 发" if when else "发出去了")


async def selftest(job):
    """不联网：导入原项目、看要用的函数都在；给了浏览器就真开一下空白页（patchright 的 launch 换没换对）。"""
    M = _real()
    need = ["douyin_setup", "cookie_auth", "DouYinVideo", "DOUYIN_PUBLISH_STRATEGY_IMMEDIATE", "DOUYIN_PUBLISH_STRATEGY_SCHEDULED"]
    miss = [n for n in need if not hasattr(M, n)]
    if miss:
        return False, "原项目里找不到：" + "、".join(miss)
    import inspect
    ps = inspect.signature(M.DouYinVideo.__init__).parameters
    miss = [n for n in ("desc", "thumbnail_portrait_path", "thumbnail_landscape_path", "declaration", "collection_name", "publish_strategy", "headless") if n not in ps]
    if miss:
        return False, "DouYinVideo 的参数变了，少了：" + "、".join(miss)
    if job.get("browser") and job.get("launch"):
        from patchright.async_api import async_playwright
        async with async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, channel="chromium", args=["--no-sandbox"])
            pg = await b.new_page()
            await pg.set_content("<title>自检</title><p>ok</p>")
            title = await pg.title()
            await b.close()
        return title == "自检", "能开浏览器：" + title
    return True, "导入好了"


def _fake(path):
    spec = importlib.util.spec_from_file_location("fake_sau", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    action, jp = sys.argv[1], Path(sys.argv[2])
    job = json.loads(jp.read_text("utf-8"))
    ok, msg = False, ""
    try:
        fake = os.environ.get("AGENT_SAU_FAKE")
        if fake:
            ok, msg = asyncio.run(_fake(fake).run(action, job, emit))
        else:
            _stubs(job)
            _patch_launch(job.get("browser"))
            _real()                                       # 先导入（它的 utils.log 会加自己的输出），再换成我们的
            _hook_log(job)
            fn = {"login": real_login, "check": real_check, "upload": real_upload, "selftest": selftest}.get(action)
            if not fn:
                raise ValueError("不认识的动作：" + action)
            ok, msg = asyncio.run(fn(job))
    except Exception as e:
        traceback.print_exc()
        sys.stdout.flush()
        ok, msg = False, f"{type(e).__name__}: {e}"[:500]
    emit(t="done", ok=bool(ok), msg=msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
