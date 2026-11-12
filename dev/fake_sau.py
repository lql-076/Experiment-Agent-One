"""假的抖音发布（v3.2）：dev/test_publish.py、dev/ui/publish.py 用。app/douyin_run.py 看到环境变量 AGENT_SAU_FAKE 就用这个，不导入真的代码、不开浏览器、不联网。
- 登录：给一张二维码；等 run\\fake_scan 这个文件出现（测试「扫码」）或者 FAKE_SAU_AUTOSCAN=1 时一秒后自己好；写一份带 sessionid 的 cookie。
- 查登录：cookie 里有 sessionid、没有 expired 就算有效。
- 发布：标题里带「【失败】」就失败、「【慢】」慢慢传（停下用）、「【验证码】」要短信验证码（等 run\\verify_code.txt）；
  发出去的参数原样记在 run\\fake_last_upload.json（测试对一下发的是什么），cookie 里加一个 refreshed（测试看它有没有重新加密存）。"""
import asyncio
import json
import os
from pathlib import Path

PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAAAAAA6mKC9AAAAKklEQVR4nGNkYPjPgAz+M6IIMDJAFBA1MDEwMDAw"
       "/GdgYGRgYGBg+M8AAMvXBxF9W8k7AAAAAElFTkSuQmCC")


def _valid(p: Path):
    try:
        d = json.loads(p.read_text("utf-8"))
    except Exception:
        return False
    return any(c.get("name") == "sessionid" for c in d.get("cookies", [])) and not d.get("expired")


async def run(action, job, emit):
    def say(m):
        emit(t="log", msg=m)
    ck, base = Path(job["cookie"]), Path(job["base"])
    if action == "check":
        await asyncio.sleep(0.3)
        ok = ck.exists() and _valid(ck)
        return ok, "登录还有效" if ok else "登录失效了，要重新扫码"
    if action == "login":
        if ck.exists() and _valid(ck):
            return True, "原来的登录还有效，不用扫码"
        say("🖼️ 二维码已经准备好啦")
        emit(t="qr", img=PNG)
        say("🧍 请扫码，小人正在耐心等待登录完成")
        for i in range(150):
            if (base / "fake_scan").exists() or (os.environ.get("FAKE_SAU_AUTOSCAN") and i >= 5):
                break
            await asyncio.sleep(0.2)
        else:
            return False, "登录没成：等待抖音扫码登录超时"
        try:
            (base / "fake_scan").unlink()
        except OSError:
            pass
        ck.write_text(json.dumps({"cookies": [{"name": "sessionid", "value": "fake-session-0000"}], "origins": []}), "utf-8")
        return True, "扫码登录好了"
    if action == "upload":
        if not (ck.exists() and _valid(ck)):
            raise RuntimeError("cookie文件已失效，请先完成抖音登录")
        title = job.get("title", "")
        say(f"🏃 小人开始搬运视频: {title}.mp4")
        if "【失败】" in title:
            await asyncio.sleep(0.3)
            raise RuntimeError("检测到上传失败（假的）")
        for i in range(40 if "【慢】" in title else 3):
            say(f"🏃 小人正在努力上传视频（{i + 1}）")
            await asyncio.sleep(0.25)
        if "【验证码】" in title:
            say("📱 检测到短信验证码弹窗")
            emit(t="sms")
            f = base / "verify_code.txt"
            for _ in range(200):
                if f.exists():
                    break
                await asyncio.sleep(0.1)
            else:
                return False, "等验证码等太久了"
            code = f.read_text("utf-8").strip()
            f.unlink()
            say(f"✅ 验证码提交了（{len(code)} 位）")
        rec = {k: v for k, v in job.items() if k not in ("cookie",)}
        (base / "fake_last_upload.json").write_text(json.dumps(rec, ensure_ascii=False), "utf-8")
        d = json.loads(ck.read_text("utf-8"))
        d["refreshed"] = True
        ck.write_text(json.dumps(d), "utf-8")
        say("🥳 视频发布成功，小人开心收工")
        return True, (f"定好了：{job['schedule']} 发" if job.get("schedule") else "发出去了")
    if action == "selftest":
        return True, "导入好了（假的）"
    return False, "不认识的动作"
