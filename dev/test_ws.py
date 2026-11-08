"""Agent 自己的工作文件夹（v2.1，app/workspace.py）。沙箱连不上 DeepSeek：用假的（dev/mocks.py，8099）。
1. 不连后端：写（新建、覆盖先备份、接着写）→ 改一段（只出现一次、全换）→ 删（挪进备份）→ 挪、改名（覆盖的先备份）→
   复制（工作区里、能读的文件夹里拿进来；没允许的不行）→ 出不去（..、绝对路径、符号链接、删工作区本身）→
   运行程序：拦哪些命令（del、PowerShell、关机、外面的路径、..、%USERPROFILE%、脚本里写死外面的路径）→ 自动建专用 Python 环境 →
   输出、退出码、改了哪些文件、超时停掉 → pip 装的 imageio-ffmpeg 自动接成 ffmpeg 命令 → 关掉「能运行程序」→
   备份半年清一次（第一次只记开始、到了半年清掉超过半年的、出清单、没到时间不清）→ 换位置（不让放进 Agent 自己的文件夹、整个盘）→
   读文件的工具也能读工作区（相对路径按工作区算）
2. 连测试后端（dev/serve.sh start）：状态接口 → 换位置、开关只能走自己的接口（通用改设置改不了）→
   对话里让 DeepSeek 写网页、运行脚本（每一步进事件）→ 「记到 XX 文件夹里」交给 DeepSeek 写文件、不进记忆 → 动作日志里有记录
用法：python dev/test_ws.py（要先 dev/serve.sh start）"""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
from datetime import datetime

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import db, files as F, paths, settings, workspace as W  # noqa: E402

bad = []
RUN = ROOT / "dev" / ".run"
T = RUN / "工作区测试"


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except (F.Denied, ValueError) as e:
        return str(e)
    return ""


# ---------- 1. 不连后端：工作区放在 dev/.run 里 ----------
shutil.rmtree(T, ignore_errors=True)
WS = T / "工作区"
OUTSIDE = T / "外面的素材"
OUTSIDE.mkdir(parents=True)
(OUTSIDE / "封面.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
(T / "不让读").mkdir()
(T / "不让读" / "秘密.txt").write_text("不该被拿进来", "utf-8")
settings.S.update({"wsDir": str(WS), "wsRun": True, "wsTimeout": 900, "readDirs": [{"path": str(OUTSIDE), "cloud": True}]})
W.BACKUP = T / "工作区备份"
W.ENV = T / "ws-env"
WS.mkdir(parents=True)
B = W.BACKUP


def backups(op):
    return sorted(B.glob(f"*/*_{op}*/**/*.*"))


r = W.write("小说/构想.md", "# 闭关锁国的效率悖论\n\n第一版\n")
f = WS / "小说" / "构想.md"
check(f.read_text("utf-8").endswith("第一版\n") and r["new"] and r["backup"] is None and not B.exists(), "写：新建文件（文件夹自动建），新建的不用备份")
W.write("小说/构想.md", "# 闭关锁国的效率悖论\n\n第二版\n")
bk = backups("改")
check(f.read_text("utf-8").endswith("第二版\n") and len(bk) == 1 and bk[0].read_text("utf-8").endswith("第一版\n")
      and bk[0].relative_to(B).parts[0] == datetime.now().strftime("%Y-%m-%d") and bk[0].name == "构想.md",
      f"覆盖：旧的先放进 工作区备份\\日期\\时分秒_改\\原来的路径（{bk[0].relative_to(B) if bk else '没有'}）")
W.write("小说/构想.md", "补一句\n", append=True)
check(f.read_text("utf-8").endswith("第二版\n补一句\n") and len(backups("改")) == 2, "接着写（append）：接在后面，也先备份")
check("没找到" in raises(W.edit, "小说/构想.md", "第三版", "x"), "改一段：没找到 old 就说没找到")
W.write("a.txt", "猫 猫 狗")
check("2 次" in raises(W.edit, "a.txt", "猫", "虎"), "改一段：old 出现了好几次，要多带几个字或者 all=true")
W.edit("a.txt", "狗", "鸭")
W.edit("a.txt", "猫", "虎", every=True)
check((WS / "a.txt").read_text("utf-8") == "虎 虎 鸭", "改一段：只出现一次的直接换；all=true 全换")
W.delete("a.txt")
check(not (WS / "a.txt").exists() and any(x.name == "a.txt" for x in backups("删")), "删文件：挪进备份（能找回来）")
W.write("临时/1.txt", "1")
W.write("临时/2.txt", "2")
W.delete("临时")
check(not (WS / "临时").exists() and len(list(B.glob("*/*_删*/临时/*.txt"))) == 2, "删文件夹：整个挪进备份")
W.write("b.txt", "B")
W.write("c.txt", "C")
r = W.move("b.txt", "c.txt")
check((WS / "c.txt").read_text("utf-8") == "B" and not (WS / "b.txt").exists() and r["backup"] and pathlib.Path(r["backup"]).read_text("utf-8") == "C",
      "挪到已经有的文件上：那里原来的先挪进备份")
W.move("c.txt", "小说")
check((WS / "小说" / "c.txt").exists(), "挪进一个文件夹：放到它里面")
r = W.copy(str(OUTSIDE / "封面.png"), "素材")
check((WS / "素材" / "封面.png").read_bytes()[:4] == b"\x89PNG", "复制：把能读的文件夹里的素材拿进工作区")
check(raises(W.copy, str(T / "不让读" / "秘密.txt"), "x.txt") != "" and not (WS / "x.txt").exists(), "复制：没允许读的文件夹拿不进来")
W.copy("小说", "小说备份")
check((WS / "小说备份" / "构想.md").exists(), "复制：工作区里整个文件夹复制")
# 出不去
check("不在工作文件夹里" in raises(W.write, "../跑出去.txt", "x") and not (T / "跑出去.txt").exists(), "写：用 .. 出不去")
check("不在工作文件夹里" in raises(W.write, str(T / "跑出去.txt"), "x") and not (T / "跑出去.txt").exists(), "写：工作区外面的绝对路径写不了")
os.symlink(OUTSIDE, WS / "链接")
check("不在工作文件夹里" in raises(W.write, "链接/偷偷写.txt", "x") and not (OUTSIDE / "偷偷写.txt").exists(), "写：符号链接指到外面的也写不了")
(WS / "链接").unlink()
check(raises(W.delete, ".") != "" and WS.exists(), "不能删工作文件夹本身")
W.write("工作区/前缀.txt", "x")
check((WS / "前缀.txt").exists(), "路径写成「工作区\\xx」也认（去掉开头的工作区名字）")
check(raises(W.write, ".env", "KEY=1") != "", "看着像密钥的文件名（.env）不写")

# 运行程序：拦哪些
for cmd, why in (("del a.txt", "del"), ("rm -rf 小说", "rm"), ("powershell -c dir", "powershell"), ("shutdown /s /t 0", "shutdown"),
                 ("python ../x.py", ".."), ("cat /etc/passwd", "外面的路径"), ("echo %USERPROFILE%", "%USERPROFILE%"),
                 ("echo hi && taskkill /F /IM node.exe", "taskkill"), ("start notepad", "start")):
    check(W.guard(cmd) != "", f"拦下：{cmd}（{W.guard(cmd)[:30]}）")
for cmd in ("python make.py", "pip install imageio-ffmpeg", "ffmpeg -y -framerate 30 -i 帧/%05d.png -c:v libx264 成品.mp4", "python -m http.server --help"):
    check(W.guard(cmd) == "", f"能跑：{cmd}")
W.write("坏.py", "open('/home/somebody/x.txt', 'w').write('x')\n")
g1 = W.guard("python 坏.py")
W.write("坏.py", "import os\nprint(os.path.expanduser('~'))\n")
g2 = W.guard("python 坏.py")
W.delete("坏.py")
check("坏.py" in g1 and "外面的路径" in g1 and "expanduser" in g2 and W.guard("python make.py") == "", "脚本里写死了外面的路径、用户文件夹：运行前拦下（改掉就能跑）")

# 运行程序：真的跑
t0 = time.time()
W.write("make.py", "import pathlib\nprint('你好，开始做')\npathlib.Path('成品').mkdir(exist_ok=True)\npathlib.Path('成品/片头.txt').write_text('片头', encoding='utf-8')\n")
said = []
r = W.run("python make.py", say=said.append)
check(W.py().exists() and r["code"] == 0 and "你好，开始做" in r["out"] and any(a == "新" and b.replace("\\", "/") == "成品/片头.txt" for a, b, _ in r["changed"]),
      f"运行：第一次自动建专用的 Python 环境（{time.time() - t0:.0f} 秒），输出、退出码、新出的文件都回来了")
check(any("Python 环境" in x for x in said), "第一次建环境时进度里说了在建")
r = W.run('python -c "import sys; print(sys.prefix); sys.exit(3)"')
check(r["code"] == 3 and "ws-env" in r["out"], f"运行：python 是工作区专用的环境（{r['out'].strip()[-30:]}），退出码照实给")
t0 = time.time()
r = W.run('python -c "import time; print(1, flush=True); time.sleep(30)"', timeout=2)
check(r["timed_out"] and time.time() - t0 < 15 and "1" in r["out"], f"超时：到点就停（{time.time() - t0:.1f} 秒），已经有的输出照样给")
txt, step = W.run_tool("run_command", {"command": "python make.py"})
check(step[0] == "运行" and "成功" in step[1] and "用时" in txt and "改动的文件" in txt, f"给模型的结果和事件里的一步：{step[1]}")
bins = W.ENV.glob("**/site-packages")
sp = next(iter(bins))
(sp / "imageio_ffmpeg" / "binaries").mkdir(parents=True)
fake = sp / "imageio_ffmpeg" / "binaries" / "ffmpeg-linux-x86_64-v7.0"
fake.write_text("#!/bin/sh\necho 假的ffmpeg $@\n")
fake.chmod(0o755)
W.run("python -c \"print('装好了')\"")
r = W.run("ffmpeg -version")
check(W.status()["ffmpeg"] and "假的ffmpeg" in r["out"], "pip 装了 imageio-ffmpeg：自动接成 ffmpeg 命令，命令行直接能用")
logt = W.LOG.read_text("utf-8") if W.LOG.exists() else ""
check("python make.py" in logt and "你好，开始做" in logt, "运行的完整输出写进 data\\logs\\workspace.log")
settings.S["wsRun"] = False
check("关着" in raises(W.run, "python make.py") and "run_command" not in [t["function"]["name"] for t in W.tools()] and "运行程序他关掉了" in W.hint(),
      "关掉「能运行程序」：不给这个工具、跑不了；写文件还能用")
settings.S["wsRun"] = True
check("write_file" in [t["function"]["name"] for t in W.tools()] and "run_command" in [t["function"]["name"] for t in W.tools()] and str(WS) in W.hint(), "给 DeepSeek 的工具和说明")

# 读文件的工具也能读工作区（相对路径按工作区算）
txt, st, _, _ = F.run_tool("list_dir", {"path": "."})
txt2, st2, _, used = F.run_tool("read_file", {"path": "小说/构想.md"})
check("小说" in txt and "make.py" in txt and "补一句" in txt2 and st2[1].startswith("工作区"), f"list_dir / read_file 也能读工作区：{st2[1]}")

# 备份半年清一次
db.run("DELETE FROM kv WHERE k='ws_clean'")
check(W.clean() is None and (db.kv_get("ws_clean") or {}).get("start"), "第一次只记下从哪天开始算，不清")
old = B / "2025-01-02" / "101500_删" / "旧草稿"
old.mkdir(parents=True)
(old / "草稿1.md").write_text("x" * 2048, "utf-8")
(B / "2025-01-02" / "101500_删" / "旧草稿" / "草稿2.md").write_text("y", "utf-8")
check(W.clean() is None and old.exists(), "没到半年：不清")
st = db.kv_get("ws_clean")
st["ts"] = time.time() - 183 * 86400
db.kv_set("ws_clean", st)
r = W.clean()
lst = pathlib.Path(r["list"]) if r else None
lt = lst.read_text("utf-8") if lst and lst.exists() else ""
check(r and r["n"] == 2 and not (B / "2025-01-02").exists() and any(B.glob(datetime.now().strftime("%Y-%m-%d"))) and "旧草稿" in lt and "草稿1.md" in lt
      and "2025-01-02" in lt and "10:15:00" in lt and "2 KB" in lt, "到了半年：清掉超过半年的（新的留着），出一份清单（哪天、几点、原来在哪、多大）")
check(lst and lst.parent == B / "清理清单" and W.clean() is None and W.status()["last_n"] == 2 and W.status()["last_list"], "清单在 工作区备份\\清理清单 里；刚清完不会再清")
db.run("DELETE FROM kv WHERE k='ws_clean'")

# 换位置
settings.S["wsDir"] = ""
for p_, why in ((paths.ROOT / "app" / "x", "Agent 自己用的"), (paths.ROOT, "Agent 文件夹本身"), (pathlib.Path("/"), "整个盘"), (RUN / "x", "dev")):
    check(raises(W.set_dir, str(p_)) != "", f"换位置：不让放进 {why}（{raises(W.set_dir, str(p_))[:24]}）")
tmpd = tempfile.mkdtemp(prefix=".agent-ws-test-", dir=str(paths.ROOT.parent))          # Agent 文件夹外面（沙箱里）
st = W.set_dir(os.path.join(tmpd, "工作区"))
check(st["dir"] == paths.show(pathlib.Path(tmpd) / "工作区") and not st["default"] and pathlib.Path(tmpd, "工作区").is_dir(), "换位置：换到别的盘的一个文件夹，自动建好")
st = W.set_dir("")
check(st["default"] and settings.S["wsDir"] == "", "换位置：留空回到默认（Agent 文件夹里的「工作区」）")
shutil.rmtree(tmpd, ignore_errors=True)

# ---------- 2. 连测试后端 ----------
B_ = "http://127.0.0.1:8765"
c = httpx.Client(base_url=B_, timeout=60, headers={"X-Agent": "1"})
try:
    c.get("/api/ping").raise_for_status()
except Exception:
    print("测试后端没起来（dev/serve.sh start），后面的跳过")
    print("不过的：", bad or "没有")
    sys.exit(1 if bad else 0)
shutil.rmtree(paths.ROOT / "工作区", ignore_errors=True)               # 只在沙箱里：测试后端用的是默认位置
shutil.rmtree(paths.ROOT / "工作区备份", ignore_errors=True)
c.put("/api/ws", json={"dir": "", "run": True})
st = c.get("/api/ws").json()
check(st["default"] and st["run"] and st["keep_days"] == 182 and st["dir"].endswith("工作区"), f"状态接口：默认在 Agent 文件夹里的「工作区」（{st['dir'][-20:]}）")
c.put("/api/settings", json={"wsDir": "/tmp", "wsRun": False})
st = c.get("/api/ws").json()
check(st["default"] and st["run"], "通用的「改设置」改不了工作区的位置和「能运行程序」（给 agent 的权限要走自己的接口）")
r = c.put("/api/ws", json={"dir": str(paths.ROOT / "app")})
check(r.status_code == 400 and "Agent 自己用的" in r.json()["detail"], "接口：不让把工作区放进 Agent 自己的文件夹")
r = c.put("/api/ws", json={"run": False}).json()
r2 = c.put("/api/ws", json={"run": True}).json()
check(not r["run"] and r2["run"], "接口：开关「能运行程序」")


def ask(text):
    r = c.post("/api/chat", json={"text": text, "async": True})
    r.raise_for_status()
    tok = r.json()["token"]
    for _ in range(400):
        j = c.get("/api/chat/" + tok).json()
        if j["done"]:
            return j.get("event") or {}
        time.sleep(0.25)
    return {}


plan = [{"name": "write_file", "arguments": {"path": "视频\\index.html", "content": "<!doctype html><title>片头</title><h1>闭关锁国的效率悖论</h1>"}},
        {"name": "write_file", "arguments": {"path": "视频\\make.py", "content": "import pathlib\npathlib.Path('视频/帧').mkdir(exist_ok=True)\n"
                                                                                  "for i in range(3):\n    pathlib.Path(f'视频/帧/{i:05d}.txt').write_text(str(i))\nprint('出了 3 帧')\n"}},
        {"name": "run_command", "arguments": {"command": "python 视频/make.py"}},
        {"name": "list_dir", "arguments": {"path": "视频"}}]
ev = ask("帮我在工作区做个视频的片头【工作区】" + json.dumps(plan, ensure_ascii=False))
names = [s[0] for s in ev.get("steps") or []]
WS2 = paths.ROOT / "工作区"
check(ev.get("to") == "ds" and names.count("写文件") == 2 and "运行" in names and "列目录" in names and (WS2 / "视频" / "index.html").exists()
      and len(list((WS2 / "视频" / "帧").glob("*.txt"))) == 3, f"对话里让 DeepSeek 写网页、写脚本、运行、看结果：每一步都进了事件（{' → '.join(names)}）")
run_step = next((s for s in ev.get("steps") or [] if s[0] == "运行"), ["", ""])
check("成功" in run_step[1] and "做完了" in (ev.get("reply") or "") and any("工作区" in s[1] for s in ev.get("steps") or [] if s[0] == "交给 DeepSeek"),
      f"运行那一步写了用时和结果（{run_step[1]}），回复里说了做完了")
ev = ask("帮我在工作区里删掉东西【工作区】" + json.dumps([{"name": "run_command", "arguments": {"command": "del 视频\\index.html"}}], ensure_ascii=False))
check((WS2 / "视频" / "index.html").exists() and any(s[0] == "工作区" and "不让用" in s[1] for s in ev.get("steps") or []), "让它用 del 删：拦下（要用 delete_path，先备份），事件里写了没做成")
ev = ask("帮我记一下，记到小说的文件夹里：男主闭关锁国的效率悖论")
st_names = [s[0] for s in ev.get("steps") or []]
check(ev.get("to") == "ds" and "写记忆" not in st_names, f"「记到 XX 文件夹里」：交给 DeepSeek 带着工作区的工具写文件，不进记忆（{' → '.join(st_names)}）")
tools = [t["function"]["name"] for t in (httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}).get("tools") or []]
sysmsg = ((httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}).get("messages") or [{}])[0].get("content", "")
check({"write_file", "edit_file", "delete_path", "move_path", "copy_path", "run_command", "list_dir", "read_file"} <= set(tools) and "工作文件夹" in sysmsg,
      "交给 DeepSeek 时带着工作区的工具和说明")
acts = (paths.LOGS / "actions.jsonl").read_text("utf-8")
check('"workspace.file"' in acts and '"workspace.run"' in acts and '"blocked"' in acts, "每一次操作都记进动作日志（写、运行、拦下的）")
v = c.get("/api/log/verify").json()
check(v.get("ok") and v.get("lines", 0) > 0, f"动作日志的哈希链没断（{v.get('lines')} 行）")

# ---------- v2.2：DeepSeek 把工具调用写成文字、回复被截断、带图片被拒；对话里发来任何文件；「继续」接着做 ----------
from app import deepseek as dsk  # noqa: E402
D = "｜DSML｜"
sample = (f"我来写。<{D}function_calls>\n<{D}invoke name=\"write_file\">\n<{D}parameter name=\"path\" string=\"true\">a\\b.txt</{D}parameter>\n"
          f"<{D}parameter name=\"content\" string=\"true\">第一行\n第二行</{D}parameter>\n<{D}parameter name=\"append\" string=\"false\">true</{D}parameter>\n</{D}invoke>\n"
          f"<{D}invoke name=\"run_command\">\n<{D}parameter name=\"command\" string=\"true\">python make.py</{D}parameter>\n<{D}parameter name=\"timeout\" string=\"false\">60</{D}parameter>\n</{D}invoke>\n</{D}function_calls>")
got = dsk.parse_dsml(sample)
check(got == [("write_file", {"path": "a\\b.txt", "content": "第一行\n第二行", "append": True}), ("run_command", {"command": "python make.py", "timeout": 60})],
      "认出 DSML 写法的工具调用：名字、参数（字符串原样，string=false 的按 JSON 解析）")
check(dsk.has_dsml(sample) and dsk.strip_dsml(sample) == "我来写。", "去掉那串文字，只留前面正常的话")
cut = f"<{D}function_calls>\n<{D}invoke name=\"write_file\">\n<{D}parameter name=\"path\" string=\"true\">a.html</{D}parameter>\n<{D}parameter name=\"content\" string=\"true\"><html>很长"
check(dsk.parse_dsml(cut) == [] and dsk.strip_dsml(cut) == "", "被截断、没写完的调用不执行，也不显示")
check(W.safe_name("a<b>:c.txt") == "a_b__c.txt" and W.safe_name("CON.txt") == "_CON.txt" and W.safe_name("..\\..\\x.exe") == "x.exe" and W.safe_name("") == "文件",
      "收到的文件名：去掉 Windows 不认的字符、不带路径、避开 CON 这类保留名")

r1 = c.post("/api/ws/upload", params={"name": "说明.txt"}, content="hello 世界\n第二行".encode("utf-8")).json()
r2 = c.post("/api/ws/upload", params={"name": "说明.txt"}, content=b"again").json()
r3 = c.post("/api/ws/upload", params={"name": "..\\..\\evil.bin"}, content=bytes(range(256)) * 4096).json()
day = time.strftime("%Y-%m-%d")
check(r1.get("rel", "").replace("\\", "/") == f"收到的/{day}/说明.txt" and (WS2 / "收到的" / day / "说明.txt").read_text("utf-8").startswith("hello 世界"),
      f"上传任何文件：原样存进 工作区\\收到的\\日期\\原文件名（{r1.get('rel')}）")
check(r2.get("name") == "说明 (2).txt" and r3.get("name") == "evil.bin" and r3.get("size") == 256 * 4096 and (WS2 / "收到的" / day / "evil.bin").exists(),
      "重名加 (2)；名字里带路径的只留名字（出不去）；二进制原样存（1MB）")
check(not list((WS2 / "收到的" / day).glob("*.part")), "传完不留 .part 临时文件")
r = c.post("/api/chat", json={"text": "这是什么文件", "async": True, "files": [r1["rel"], "视频/make.py", "../../app/main.py"]})
tok = r.json()["token"]
for _ in range(200):
    j = c.get("/api/chat/" + tok).json()
    if j["done"]:
        break
    time.sleep(0.25)
ev = j.get("event") or {}
last = httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}
umsg = json.dumps(last.get("messages", [])[-1:], ensure_ascii=False)
rcv = [s for s in ev.get("steps") or [] if s[0] == "收到文件"]
check(ev.get("to") == "ds" and rcv and "1 个" in rcv[0][1] and "他发来的文件" in umsg and "hello 世界" in umsg and "make.py" not in umsg,
      f"发消息带上收到的文件：交给 DeepSeek，告诉它文件在工作区哪、小的文字文件带上内容；不在「收到的」里的不认（{rcv[0][1] if rcv else '没有'}）")

ev = ask("帮我在工作区写个文件【DSML】")
names = [s[0] for s in ev.get("steps") or []]
f1 = WS2 / "dsml测试" / "a.txt"
check(f1.exists() and f1.read_text("utf-8") == "你好 DSML" and "认出写成文字的工具调用" in names and "DSML" not in (ev.get("reply") or ""),
      f"DeepSeek 把工具调用写成了文字：认出来照常执行，那串文字不显示（{' → '.join(names[-4:])}）")
ev = ask("帮我在工作区写个网页【截断】")
names = [s[0] for s in ev.get("steps") or []]
f2 = WS2 / "截断" / "a.html"
check("工具调用没成" in names and f2.exists() and f2.read_text("utf-8") == "<html>第一段" and "DSML" not in (ev.get("reply") or ""),
      f"回复被截断：不执行半截的，提醒它分段写再试一次，第二次写成了（{' → '.join(names[-4:])}）")
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
plan2 = [{"name": "write_file", "arguments": {"path": "拒工具/ok.txt", "content": "带图片也写成了"}}]
r = c.post("/api/chat", json={"text": "帮我在工作区写个文件【拒工具】【工作区】" + json.dumps(plan2, ensure_ascii=False), "async": True, "images": [PNG]})
tok = r.json()["token"]
for _ in range(200):
    j = c.get("/api/chat/" + tok).json()
    if j["done"]:
        break
    time.sleep(0.25)
ev = j.get("event") or {}
rej = [s for s in ev.get("steps") or [] if s[0] == "DeepSeek 拒了一次"]
check(rej and "去掉图片" in rej[0][1] and (WS2 / "拒工具" / "ok.txt").exists() and "400" in (paths.LOGS / "deepseek.log").read_text("utf-8"),
      f"带图片 + 工具被 DeepSeek 拒（400）：去掉图片再试，工具照样用上，原因记进 deepseek.log（{rej[0][1] if rej else '没有'}）")
ev = ask("继续")
last = httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}
umsg = json.dumps(last.get("messages", [])[-1:], ensure_ascii=False)
names = [s[0] for s in ev.get("steps") or []]
check(ev.get("to") == "ds" and "接着上一件事" in names and "接着上一件事" in umsg and "拒工具" in umsg and "write_file" in json.dumps(last.get("tools") or []),
      "说「继续」：沿用上一条的去向和工具，告诉 DeepSeek 上次在工作区做到哪")
sysm = (last.get("messages") or [{}])[0].get("content", "")
check("进度.md" in sysm and "3000 字" in sysm, "给 DeepSeek 的说明里有：长文件分段写、步骤多的活记 进度.md")
shutil.rmtree(T, ignore_errors=True)
print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
