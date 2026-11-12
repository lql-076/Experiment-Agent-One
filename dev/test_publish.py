"""v3.2：发布到抖音（app/publish.py + app/douyin_run.py，抖音那边是假的 dev/fake_sau.py：不开浏览器、不联网）。
1. 真代码的自检：vendor/social-auto-upload 导得进来、要用的函数和参数都在（不联网）；有 patchright 和浏览器时真开一下空白页（launch 换成本机浏览器）
2. 没登录不让发 → 扫码登录（二维码到界面、扫完拿到 cookie）→ cookie 加密存、明文临时文件不留 → 查登录
3. 发之前的检查：标题 30 字、定时 2 小时以后 14 天以内、格式、文件在不在、话题整理、封面横竖
4. 发一条：交给抖音的参数原样对、记录里有、cookie 刷新后重新加密存；正在发时再发不让（409）
5. 要短信验证码：界面弹框、交过去；停下；发失败
6. Agent 的 publish_douyin：没开不给；开了默认交给他确认（等确认那一条、不发、改了再发）；关掉确认就直接发
7. 退出：删掉本机的登录信息
用法：python dev/test_publish.py（要先 dev/serve.sh start）"""
import json
import os
import pathlib
import shutil
import struct
import sys
import time
import zlib
from datetime import datetime, timedelta

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import paths, settings  # noqa: E402

RUN = paths.DATA / "publish" / "run"
COOKIE = paths.DATA / "publish" / "douyin.cookie"
bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def png(w, h):
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# ---------- 1. 真代码的自检 ----------
print("── 真的发布代码（vendor/social-auto-upload）导得进来")
import subprocess  # noqa: E402

tmp = RUN.parent / "selftest"
tmp.mkdir(parents=True, exist_ok=True)
browser = next((str(p) for p in pathlib.Path("/opt/pw-browsers").glob("chromium-*/chrome-linux*/chrome")), "") if pathlib.Path("/opt/pw-browsers").exists() else ""
jf = tmp / "job.json"
jf.write_text(json.dumps({"base": str(tmp / "run"), "browser": browser, "headless": True, "launch": bool(browser), "cookie": str(tmp / "c.json")}), "utf-8")
env = {k: v for k, v in os.environ.items() if k != "AGENT_SAU_FAKE"}
try:
    import patchright  # noqa: F401
    has_pr = True
except ImportError:
    has_pr = False
if not has_pr:
    print("  · 跳过：这个环境没装 patchright（pip install patchright loguru）")
else:
    r = subprocess.run([sys.executable, str(ROOT / "app" / "douyin_run.py"), "selftest", str(jf)], capture_output=True, text=True, timeout=180, env=env)
    last = [x for x in r.stdout.splitlines() if x.startswith("@@J ")]
    done = json.loads(last[-1][4:]) if last else {}
    check(r.returncode == 0 and done.get("ok"), "导入原项目、函数和参数都在" + (f"、patchright 的 launch 换成本机浏览器能开页面（{done.get('msg')}）" if browser else "") +
          ("" if done.get("ok") else f"：{done.get('msg') or r.stdout[-400:] + r.stderr[-400:]}"))
    check((tmp / "run" / "utils" / "stealth.min.js").exists() and not (ROOT / "vendor" / "social-auto-upload" / "logs").exists(),
          "原项目的日志、隐藏痕迹的脚本放在 data\\publish 下，不往 vendor 里写")
shutil.rmtree(tmp, ignore_errors=True)

# ---------- 2. 登录 ----------
print("── 扫码登录（假抖音）")
c = httpx.Client(base_url="http://127.0.0.1:8765", headers={"X-Agent": "1"}, timeout=30)
c.put("/api/agent/caps", json={"publish": False, "publish_ask": True})
c.post("/api/publish/logout")
WS = ROOT / "工作区" / "发布测试"
shutil.rmtree(WS, ignore_errors=True)
WS.mkdir(parents=True)
(WS / "成片.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4000)
(WS / "封面横.png").write_bytes(png(40, 30))
(WS / "说明.txt").write_text("不是视频")


def wait(t=30, cond=None):
    t0 = time.time()
    while time.time() - t0 < t:
        j = c.get("/api/publish").json()
        if cond(j) if cond else (not j["job"] or j["job"]["st"] != "run"):
            return j
        time.sleep(0.25)
    return c.get("/api/publish").json()


st = c.get("/api/publish").json()
check(st["ready"]["deps"] and st["ready"]["browser"] and st["ready"]["vendor"] and not st["account"]["has"], "组件、浏览器、代码都在；还没登录")
check(any(v["name"] == "成片.mp4" for v in st["videos"]) and not any(v["name"] == "说明.txt" for v in st["videos"]), "「工作区里最近的视频」列出了刚放的视频（不列别的文件）")
ITEM = {"file": "发布测试/成片.mp4", "title": "测试标题", "desc": "简介一句", "tags": "#AI 开源，GitHub AI"}
r = c.post("/api/publish/go", json=ITEM)
check(r.status_code == 400 and "登录" in r.json()["detail"], f"没登录不让发（{r.json().get('detail', '')[:30]}）")
r = c.post("/api/publish/login")
check(r.status_code == 200 and r.json()["job"]["st"] == "run", "开始扫码登录")
j = wait(15, lambda j: bool((j["job"] or {}).get("qr")))
check((j["job"] or {}).get("qr", "").startswith("data:image/png;base64,"), "二维码送到界面上了")
r = c.post("/api/publish/check")
check(r.status_code == 409, f"正在登录时再点别的不让（{r.status_code}）")
(RUN / "fake_scan").write_text("1")
j = wait(20)
check(j["job"]["st"] == "done" and j["account"]["has"] and j["account"]["ok"], f"扫完了：登录好了（{j['job']['msg']}）")
raw = COOKIE.read_bytes()
check(raw[:6] in (b"DPAPI1", b"PLAIN1") and b"sessionid" not in raw and json.loads(settings.unseal(raw))["cookies"][0]["name"] == "sessionid",
      "登录信息加密存在 data\\publish\\douyin.cookie（文件里看不到 sessionid 明文）")
check(not list(RUN.glob("douyin_*.json")) and not list(RUN.glob("job_*.json")), "子进程用完：明文的临时 cookie、任务文件都删了")
c.post("/api/publish/check")
j = wait(15)
check(j["job"]["kind"] == "check" and j["job"]["st"] == "done" and j["account"]["ok"], "查登录：还有效")

# ---------- 3. 发之前的检查 ----------
print("── 发之前的检查")


def pre(**kw):
    return c.post("/api/publish/preview", json=dict(ITEM, **kw))


soon = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
later = (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
far = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d %H:%M")
cases = {"标题 31 字": pre(title="一" * 31), "没标题": pre(title="  "), "定时 1 小时后": pre(schedule=soon), "定时 20 天后": pre(schedule=far),
         "定时写错": pre(schedule="明天晚上"), "不是视频": pre(file="发布测试/说明.txt"), "没有这个文件": pre(file="发布测试/没有.mp4"),
         "工作区外面的相对路径": pre(file="../app/main.py")}
check(all(x.status_code == 400 for x in cases.values()), "这些都拦下、说清楚哪里不行：" + "；".join(f"{k}→{x.json().get('detail', x.status_code)}"[:60] for k, x in cases.items()))
r = pre(schedule=later.replace(" ", "T"), cover="发布测试/封面横.png")
it = r.json().get("item") or {}
check(r.status_code == 200 and it["tags"] == ["AI", "开源", "GitHub"] and it["schedule"] == later and it["cover_kind"] == "landscape" and it["declaration"] == "内容由AI生成",
      f"整理好：话题去 # 去重、定时（网页的 T 也认）、封面是横的、自主声明默认「内容由AI生成」：{it.get('tags')} {it.get('cover_kind')}")

# ---------- 4. 发一条 ----------
print("── 发一条（假抖音）")
r = c.post("/api/publish/go", json=dict(ITEM, schedule=later, cover="发布测试/封面横.png", collection="AI 工具"))
check(r.status_code == 200 and r.json()["job"]["kind"] == "upload", "开始发")
r2 = c.post("/api/publish/go", json=ITEM)
check(r2.status_code == 409, f"正在发时再发不让（{r2.status_code}）")
j = wait(30)
sent = json.loads((RUN / "fake_last_upload.json").read_text("utf-8"))
check(j["job"]["st"] == "done" and j["job"]["msg"] == f"定好了：{later} 发", f"发好了：{j['job']['msg']}")
check(sent["title"] == "测试标题" and sent["desc"] == "简介一句" and sent["tags"] == ["AI", "开源", "GitHub"] and sent["schedule"] == later and sent["cover_kind"] == "landscape" and
      sent["collection"] == "AI 工具" and sent["file"].endswith("成片.mp4") and sent["browser"] == "/usr/bin/fake-chrome" and sent["headless"] is True,
      "交给抖音那边的参数原样对（标题、简介、话题、定时、横封面、合集、视频、浏览器、不弹窗口）")
check(json.loads(settings.unseal(COOKIE.read_bytes())).get("refreshed") is True, "发完抖音刷新的 cookie 重新加密存了")
h = j["hist"][0]
check(h["title"] == "测试标题" and h["st"] == "done" and h["by"] == "you" and h["schedule"] == later, "「最近发的」里有这一条（你发的、定时）")
log = (paths.LOGS / "publish.log").read_text("utf-8")
check("小人开始搬运视频" in log and "fake-session" not in log, "日志记了每一步，没记登录信息")

# ---------- 5. 验证码、停下、失败 ----------
print("── 短信验证码、停下、失败")
c.post("/api/publish/go", json=dict(ITEM, title="【验证码】测试"))
j = wait(15, lambda j: bool((j["job"] or {}).get("sms")))
check(j["job"]["sms"], "抖音要验证码：界面上弹框")
r = c.post("/api/publish/code", json={"code": "12a"})
check(r.status_code == 400, "验证码不是 4~8 位数字：拦下")
c.post("/api/publish/code", json={"code": "123456"})
j = wait(15)
check(j["job"]["st"] == "done" and any("验证码提交了（6 位）" in x for x in j["job"]["log"]), "交过去了，接着发完")
c.post("/api/publish/go", json=dict(ITEM, title="【慢】测试停下"))
wait(10, lambda j: len((j["job"] or {}).get("log") or []) >= 2)
c.post("/api/publish/stop")
j = wait(15)
check(j["job"]["st"] == "stop" and j["hist"][0]["st"] == "stop" and not list(RUN.glob("douyin_*.json")), f"停下：停了（{j['job']['msg'][:20]}），临时 cookie 也删了")
c.post("/api/publish/go", json=dict(ITEM, title="【失败】测试"))
j = wait(15)
check(j["job"]["st"] == "err" and "上传失败" in j["job"]["msg"] and j["hist"][0]["st"] == "err", f"发失败：说清楚（{j['job']['msg'][:40]}）")

# ---------- 6. Agent 的 publish_douyin ----------
print("── Agent 的 publish_douyin")


def chat(plan):
    tok = c.post("/api/chat", json={"text": "把视频发到抖音【工作区】" + json.dumps(plan, ensure_ascii=False), "async": True}).json()["token"]
    for _ in range(240):
        r = c.get("/api/chat/" + tok).json()
        if r["done"]:
            return r.get("event") or {}
        time.sleep(0.25)
    return {}


def tools():
    return {(t.get("function") or {}).get("name") for t in (httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}).get("tools") or []}


CALL = [{"name": "publish_douyin", "arguments": {"path": "发布测试/成片.mp4", "title": "Agent 发的", "tags": ["AI", "自动化"]}}]
ev = chat(CALL)
check("publish_douyin" not in tools() and not c.get("/api/publish").json()["pending"], "没开「自己发抖音」：不给这个工具，也没交过去")
c.put("/api/agent/caps", json={"publish": True})
caps = c.get("/api/agent/caps").json()["caps"]
check(caps["publish"] and caps["publish_ask"] and caps["publish_ready"], "打开以后：默认要你确认")
r = c.put("/api/settings", json={"agPublishAsk": False})
check(c.get("/api/agent/caps").json()["caps"]["publish_ask"], "通用的改设置改不了「要不要确认」（是权限，只能在 Agent 能力里点）")
ev = chat(CALL)
st = c.get("/api/publish").json()
steps = [s[0] for s in ev.get("steps") or []]
check("publish_douyin" in tools() and "发抖音" in steps and len(st["pending"]) == 1 and st["pending"][0]["item"]["title"] == "Agent 发的" and not (st["job"] or {}).get("by") == "agent",
      "开了：交过去等你确认，没直接发")
pid = st["pending"][0]["id"]
r = c.post(f"/api/publish/pending/{pid}", json={"act": "drop"})
check(r.status_code == 200 and not r.json()["pending"], "点「不发」：扔掉")
chat(CALL)
pid = c.get("/api/publish").json()["pending"][0]["id"]
r = c.post(f"/api/publish/pending/{pid}", json={"act": "ok", "edits": {"title": "改过的标题", "file": "发布测试/成片.mp4", "tags": ["AI"]}})
j = wait(20)
check(r.status_code == 200 and j["job"]["st"] == "done" and j["hist"][0]["title"] == "改过的标题" and j["hist"][0]["by"] == "agent" and not j["pending"],
      "填进来改了标题再发：发的是改过的，记录写着 Agent 交来的")
c.put("/api/agent/caps", json={"publish_ask": False})
ev = chat([{"name": "publish_douyin", "arguments": {"path": "发布测试/成片.mp4", "title": "直接发的"}}])
j = c.get("/api/publish").json()
check(j["hist"][0]["title"] == "直接发的" and j["hist"][0]["st"] == "done" and not j["pending"], "关掉确认：它直接发了")
ev = chat([{"name": "publish_douyin", "arguments": {"path": "../app/main.py", "title": "越界"}}])
check(any("出错" in str(s[1]) or "不在工作文件夹" in str(s[1]) for s in ev.get("steps") or []) and j["hist"][0]["title"] == "直接发的", "Agent 给工作区外面的文件：拦下")
c.put("/api/agent/caps", json={"publish": False, "publish_ask": True})

# ---------- 7. 退出 ----------
r = c.post("/api/publish/logout")
check(r.status_code == 200 and not r.json()["account"]["has"] and not COOKIE.exists(), "退出：本机的登录信息删了")
shutil.rmtree(WS, ignore_errors=True)
c.post("/api/publish/logout")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
