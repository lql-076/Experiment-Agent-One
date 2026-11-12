"""v3.3：批量清单先让 DeepSeek 认一遍（app/smartlist.py），还有批量发抖音（app/publish.py 的 PubBatch）。DeepSeek、抖音都是假的。
假 DeepSeek 看到「批量清单整理员」时，回清单里「【JSON】」后面那一段（测试自己写好想要它回什么），所以这里测的是：
1. 发过去的对：带行号、json 模式、配音时带着能用的音色名、发布时带着文件夹里的文件名和今天的日期
2. 回来以后整理得对：提示词、配音的字按行号从原文切（不让它改写）、去掉「03 白页：」这种说话人、音色对不上的不用、配乐「一样的出几首」
3. 回的不是 JSON、没找到条目：说清楚
4. 批量发布：固定格式（不用 DeepSeek）认、按名字配视频和封面、定时 2 小时以内的标出来；DeepSeek 认；登录后一条一条发、记录标「批量」；停下
用法：python dev/test_smart.py（要先 dev/serve.sh start）"""
import json
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
from app import paths  # noqa: E402

RUN = paths.DATA / "publish" / "run"
bad = []
c = httpx.Client(base_url="http://127.0.0.1:8765", headers={"X-Agent": "1"}, timeout=60)


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def last():
    return httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}


def J(o):
    return "【JSON】" + json.dumps(o, ensure_ascii=False)


def png(w, h):
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# ---------- 生图 ----------
print("── 生图：随便写的清单 → DeepSeek 认 → 标准表格")
c.post("/api/img/clear")
txt = "这期风格：赛博朋克，霓虹，雨夜\n第一张，竖着的，要透明背景：一个女孩撑着伞站在雨里\n第二张 横屏 城市夜景，远处有飞艇\n" + J(
    {"title": "第5期配图", "direction_lines": [2, 2], "items": [{"file": "img01_女孩", "ratio": "9:16", "transparent": True, "lines": [3, 3], "prompt": "一个女孩撑着伞站在雨里"},
                                                              {"file": "img02_夜景.png", "ratio": "16:9", "transparent": False, "lines": [4, 4], "prompt": "我自己编的提示词"}],
     "notes": ["第二张没写比例，按横屏"]})
r = c.post("/api/img/load", json={"md": txt, "name": "配图.txt", "smart": True})
b = r.json().get("board") or {}
its = b.get("items") or []
q = last()
check(r.status_code == 200 and len(its) == 2, f"认出 2 张（{r.status_code} {str(r.json())[:80] if r.status_code != 200 else ''}）")
check((q.get("response_format") or {}).get("type") == "json_object" and "生图批量清单整理员" in q["messages"][0]["content"] and "2| 这期风格" in q["messages"][1]["content"],
      "发给 DeepSeek 的：json 模式、带行号的原文")
if len(its) == 2:
    check(its[0]["file"] == "img01_女孩.png" and its[0]["ratio"] == "9:16" and its[0]["transparent"] and its[0]["prompt"] == "一个女孩撑着伞站在雨里",
          "第一张：补上 .png、竖屏、透明、提示词是原文里摘的那段")
    check(its[1]["prompt"] == "第二张 横屏 城市夜景，远处有飞艇" and not its[1]["transparent"], "第二张：它摘的提示词原文里没有 → 用原文那一整行（不让它改写）")
check(b.get("direction") == "这期风格：赛博朋克，霓虹，雨夜" and b.get("md_name") == "配图.txt" and any("DeepSeek" in w for w in b.get("warn", [])) and any("按横屏" in w for w in b.get("warn", [])),
      "视觉方向认出来了；顶上写着是 DeepSeek 认的、它没把握的地方")
r = c.post("/api/img/load", json={"md": "随便写的【坏JSON】", "smart": True})
check(r.status_code == 502 and "不是能用的清单" in r.json()["detail"], f"它回的不是 JSON：说清楚（{r.json()['detail'][:24]}）")
r = c.post("/api/img/load", json={"md": "什么都没有", "smart": True})
check(r.status_code == 400 and "没找到要做的" in r.json()["detail"], "它没找到条目：说清楚")
c.post("/api/img/clear")

# ---------- 配音 ----------
print("── 配音：剧本 + 音色写在文中 → 一段一段、配好音色")
c.post("/api/tts/batch/clear")
script = "# 第5期\n白页用 Serena，紫苏用 Dylan\n01 白页：大家好，我是白页。\n02 白页：今天聊聊 AI。\n03 紫苏：我不信！\n04 白页：那你听好。\n" + J(
    {"title": "第5期", "roles": {"白页": "Serena", "紫苏": "Dylan"}, "items": [
        {"file": "01_白页", "role": "白页", "voice": "Serena", "lines": [4, 5]},
        {"file": "02_紫苏", "role": "紫苏", "voice": "Dylan", "tone": "不服气", "lines": [6, 6]},
        {"file": "03_白页", "role": "白页", "voice": "没有这个音色", "lines": [7, 7]}]})
r = c.post("/api/tts/batch/load", json={"files": [{"name": "第5期剧本.md", "text": script}], "smart": True, "engine": "local"})
b = r.json().get("board") or {}
its = b.get("items") or []
q = last()
check(r.status_code == 200 and len(its) == 3, f"认出 3 段（{r.status_code}）")
check("能用的音色" in q["messages"][0]["content"] and "Serena" in q["messages"][0]["content"] and "===== 文件 1：第5期剧本.md =====" in q["messages"][1]["content"],
      "发过去的带着现在能用的音色名、文件名")
if len(its) == 3:
    check(its[0]["file"] == "01_白页" and its[0]["voice"] == "Serena" and its[0]["text"] == "大家好，我是白页。\n今天聊聊 AI。", "第一段：白页、Serena、连着的两句合一段，去掉了「01 白页：」")
    check(its[1]["voice"] == "Dylan" and its[1]["tone"] == "不服气" and its[1]["text"] == "我不信！", "第二段：紫苏、Dylan、语气")
    check(its[2]["voice"] == "" and any("没有这个音色" in w for w in b["warn"]), "它配了个不存在的音色：不用（用页面上选的），顶上说一声")
c.post("/api/tts/batch/clear")

# ---------- 配乐 ----------
print("── 配乐：一个描述出几首")
c.post("/api/bgm/batch/clear")
r = c.post("/api/bgm/batch/load", json={"md": "开场音乐，轻快电子，1分半，出两版挑一下\n" + J(
    {"title": "第5期配乐", "items": [{"name": "bgm01_开场_1", "seconds": 90, "prompt": "轻快 电子"}, {"name": "bgm01_开场_2", "seconds": 90, "prompt": "轻快 电子"}]}), "smart": True})
its = (r.json().get("board") or {}).get("items") or []
check(r.status_code == 200 and [(x["file"], x["seconds"], x["prompt"]) for x in its] == [("bgm01_开场_1", 90, "轻快 电子"), ("bgm01_开场_2", 90, "轻快 电子")], "认出 2 首：名字、90 秒、描述")
c.post("/api/bgm/batch/clear")

# ---------- 批量发抖音 ----------
print("── 批量发抖音：文件夹 + 清单，一条一条定时发")
c.post("/api/publish/batch/clear")
WS = paths.ROOT / "工作区" / "批量发布测试"
shutil.rmtree(WS, ignore_errors=True)
WS.mkdir(parents=True)
for n in ("01_成片.mp4", "02_成片.mp4", "03 番外.mp4"):
    (WS / n).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2000)
(WS / "01_成片_封面.png").write_bytes(png(30, 40))
(WS / "02封面.png").write_bytes(png(40, 30))
t1 = (datetime.now() + timedelta(hours=5)).strftime("%Y/%m/%d %H:%M")
t2 = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
lst = f"# 第5期\n\n## 本周最火的 AI 项目\n视频：01_成片.mp4\n简介：第一行\n第二行\n话题：#AI #开源\n定时：{t1}\n合集：AI周报\n\n## 第二条\n视频：02\n封面：02封面.png\n定时：{t2}\n\n## 第三条\n视频：没有的.mp4\n定时：{t1}\n"
(WS / "发布清单.txt").write_bytes(lst.encode("gb18030"))
r = c.post("/api/publish/batch/load", json={"folder": "批量发布测试"})
b = r.json().get("batch") or {}
its = b.get("items") or []
check(r.status_code == 200 and len(its) == 3 and b["title"] == "第5期", f"不用 DeepSeek：文件夹里的清单（GBK 编码的 txt 也认）认出 3 条（{r.status_code} {r.text[:80] if r.status_code != 200 else ''}）")
if len(its) == 3:
    a = its[0]
    check(a["video_show"] == "01_成片.mp4" and a["cover_show"] == "01_成片_封面.png" and a["tags"] == ["AI", "开源"] and a["desc"] == "第一行\n第二行" and a["collection"] == "AI周报"
          and a["schedule"] == t1.replace("/", "-") and a["st"] == "idle", "第一条：视频、自己找到同名封面、话题、两行简介、合集、时间换成标准写法；能发")
    check(its[1]["video_show"] == "02_成片.mp4" and its[1]["cover_show"] == "02封面.png" and its[1]["st"] == "err" and "2 小时" in its[1]["err"], "第二条：「02」配上 02_成片.mp4；定时不到 2 小时 → 标红说清楚")
    check(its[2]["st"] == "err" and "没找到视频" in its[2]["err"], "第三条：文件夹里没有这个视频 → 标红")
r = c.post("/api/publish/batch/run")
check(r.status_code == 400 and "登录" in r.json()["detail"], "还没登录：不让发")
# DeepSeek 认：文件名写得不一样
ds = "第5期的发布安排\n1. 第一条 发 01 那个视频，标题：本周最火的 AI 项目，周五晚上 8 点\n" + J(
    {"title": "第5期", "items": [{"video": "01_成片.mp4", "cover": "", "title": "本周最火的 AI 项目", "desc": "", "tags": ["AI"], "schedule": t1, "collection": "", "declaration": ""},
                                {"video": "03番外", "cover": "不存在.png", "title": "番外", "tags": "#番外", "schedule": (datetime.now() + timedelta(days=2)).strftime("%m月%d日 20点")}]})
r = c.post("/api/publish/batch/load", json={"folder": str(WS), "files": [{"name": "安排.md", "text": ds}], "smart": True})
b = r.json().get("batch") or {}
its = b.get("items") or []
q = last()
check(r.status_code == 200 and len(its) == 2 and b["lists"] == ["安排.md"], "DeepSeek 认：上传的清单优先（不用文件夹里那份）")
check("抖音批量发布清单整理员" in q["messages"][0]["content"] and "01_成片.mp4" in q["messages"][0]["content"] and datetime.now().strftime("%Y-%m-%d") in q["messages"][0]["content"],
      "发过去的带着文件夹里的文件名、今天的日期")
if len(its) == 2:
    check(its[1]["video_show"] == "03 番外.mp4" and its[1]["cover_show"] == "" and its[1]["schedule"].endswith(" 20:00") and its[1]["st"] == "idle"
          and any("不存在.png" in w for w in b["warn"]), "「03番外」配上「03 番外.mp4」；封面没找到就不放（顶上说）；「11月14日 20点」换成标准时间")
# 登录、发
c.post("/api/publish/login")
for _ in range(60):
    j = c.get("/api/publish").json()
    if (j["job"] or {}).get("qr"):
        break
    time.sleep(0.25)
(RUN / "fake_scan").write_text("1")
for _ in range(80):
    j = c.get("/api/publish").json()
    if j["job"]["st"] != "run":
        break
    time.sleep(0.25)
check(j["account"]["has"], "扫码登录了")
r = c.post("/api/publish/batch/run")
check(r.status_code == 200 and r.json()["batch"]["running"], "点「全部定时发出去」：开始一条一条发")
r2 = c.post("/api/publish/batch/run")
check(r2.status_code == 409, "正在发时再点不让")
for _ in range(240):
    j = c.get("/api/publish").json()
    if not j["batch"]["running"]:
        break
    time.sleep(0.25)
its = j["batch"]["items"]
sent = json.loads((RUN / "fake_last_upload.json").read_text("utf-8"))
check([x["st"] for x in its] == ["ok", "ok"], f"两条都发了（{[x['st'] + x['err'][:20] for x in its]}）")
check(sent["title"] == "番外" and sent["schedule"] == its[1]["schedule"] and pathlib.Path(sent["file"]).name == "03 番外.mp4" and sent["tags"] == ["番外"], "交给抖音的是第二条：标题、定时、视频、话题都对")
check([h["by"] for h in j["hist"][:2]] == ["batch", "batch"] and j["hist"][0]["title"] == "番外", "「最近发的」里两条，标着批量")
r = c.post("/api/publish/batch/run")
check(r.status_code == 400 and "没有能发的" in r.json()["detail"], "都发完了再点：没有能发的")
c.post("/api/publish/batch/clear")
check(c.get("/api/publish").json()["batch"] is None, "换一批：清掉了")
c.post("/api/publish/logout")
shutil.rmtree(WS, ignore_errors=True)
print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
