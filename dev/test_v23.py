"""v2.3 · 文件进出工作区的配套（app/workspace.py、app/files.py、app/mediainfo.py、app/qq.py）。
1. 不连后端：视频 / 音频 / 图片的时长和分辨率（用 ffmpeg 现做几个样本）→ PDF、Excel 读出文字 → 整个文件夹收进来（子文件夹原样、重名加序号、出不去）→
   收到的文件给模型的那段话（带时长、分辨率、小文件的内容、文件夹里有什么）→ 做好的文件（视频排前面、一文件夹的画面只算一个、不算收到的）→
   生图 / 配音「放进工作区」→ QQ 附件（认地址和名字、下载进「收到的」、图片另给模型看、下不了照实说）→ 图片发回 QQ（先传再发、只发 PNG / JPEG）
2. 连测试后端（dev/serve.sh start）：整个文件夹的两个接口 → 带着文件夹发消息 → DeepSeek 做出来的文件进事件、能看能打开 → 设置里「收到的」多大
用法：python dev/test_v23.py（要先 dev/serve.sh start）"""
import asyncio
import json
import pathlib
import shutil
import subprocess
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import files as F, mediainfo as MI, paths, qq, settings, workspace as W  # noqa: E402

bad = []
RUN = ROOT / "dev" / ".run"
T = RUN / "v23测试"


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


shutil.rmtree(T, ignore_errors=True)
WS = T / "工作区"
WS.mkdir(parents=True)
settings.S.update({"wsDir": str(WS), "wsRun": True, "readDirs": []})
W.BACKUP = T / "工作区备份"
S_ = T / "样本"
S_.mkdir()

# ---------- 时长、分辨率 ----------
FF = shutil.which("ffmpeg")
if FF:
    def ff(*a):
        subprocess.run([FF, "-y", "-loglevel", "error", *a], check=True)
    ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=10", "-t", "2.5", "-pix_fmt", "yuv420p", str(S_ / "a.mp4"))
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "1.5", "-movflags", "+faststart", "-pix_fmt", "yuv420p", str(S_ / "b.mov"))
    ff("-f", "lavfi", "-i", "testsrc=size=480x270:rate=10", "-t", "2", "-c:v", "libvpx", str(S_ / "c.webm"))
    ff("-f", "lavfi", "-i", "testsrc=size=480x270:rate=10", "-t", "3", "-pix_fmt", "yuv420p", str(S_ / "d.mkv"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=3.2", str(S_ / "e.wav"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-b:a", "128k", str(S_ / "f.mp3"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(S_ / "g.flac"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2.4", "-c:a", "aac", str(S_ / "h.m4a"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "libvorbis", str(S_ / "i.ogg"))
    ff("-f", "lavfi", "-i", "testsrc=size=300x200", "-frames:v", "1", str(S_ / "j.png"))
    ff("-f", "lavfi", "-i", "testsrc=size=300x200", "-frames:v", "1", str(S_ / "k.jpg"))
    ff("-f", "lavfi", "-i", "testsrc=size=300x200", "-frames:v", "1", str(S_ / "l.webp"))
    ff("-f", "lavfi", "-i", "testsrc=size=300x200", "-frames:v", "1", str(S_ / "m.gif"))
    want = {"a.mp4": (2.5, 640, 360), "b.mov": (1.5, 320, 240), "c.webm": (2, 480, 270), "d.mkv": (3, 480, 270), "e.wav": (3.2, 0, 0), "f.mp3": (4, 0, 0),
            "g.flac": (2, 0, 0), "h.m4a": (2.4, 0, 0), "i.ogg": (3, 0, 0), "j.png": (0, 300, 200), "k.jpg": (0, 300, 200), "l.webp": (0, 300, 200), "m.gif": (0, 300, 200)}
    wrong = []
    for n, (d, w, h) in want.items():
        i = MI.probe(S_ / n)
        if (d and abs((i.get("duration") or 0) - d) > 0.25) or (w and (i.get("w"), i.get("h")) != (w, h)):
            wrong.append(f"{n}→{i}")
    check(not wrong, "认出时长和分辨率：MP4、MOV、WEBM、MKV、WAV、MP3、FLAC、M4A、OGG、PNG、JPEG、WEBP、GIF（只读文件头）" + ("：" + "；".join(wrong) if wrong else ""))
    check(MI.describe(S_ / "a.mp4") == "视频 · 2.5 秒 · 640×360" and MI.describe(S_ / "e.wav") == "音频 · 3.2 秒" and MI.describe(S_ / "j.png") == "图片 · 300×200",
          f"一句话说清：{MI.describe(S_ / 'a.mp4')}｜{MI.describe(S_ / 'e.wav')}｜{MI.describe(S_ / 'j.png')}")
else:
    print("  （沙箱里没有 ffmpeg，时长分辨率的样本测不了）")
(S_ / "坏的.mp4").write_bytes(b"\x00\x00\x00\x08ftyp" + b"\xff" * 50)
check(MI.probe(S_ / "坏的.mp4") == {"kind": "video"} and MI.describe(S_ / "坏的.mp4") == "" and MI.probe(S_ / "x.txt") == {} and MI.clock(125) == "2 分 05 秒",
      "坏文件、认不出的：不报错，就是不带时长")

# ---------- PDF、Excel ----------
from pypdf import PdfWriter  # noqa: E402
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject  # noqa: E402
pw = PdfWriter()
for k, txt in enumerate(("Hello PDF page one", "Second page 2026")):
    pg = pw.add_blank_page(width=300, height=200)
    st_ = DecodedStreamObject()
    st_.set_data(f"BT /F1 12 Tf 20 100 Td ({txt}) Tj ET".encode())
    pg[NameObject("/Contents")] = pw._add_object(st_)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    pg[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): pw._add_object(font)})})
pw.add_blank_page(width=300, height=200)
with open(WS / "说明.pdf", "wb") as f:
    pw.write(f)
r = F.read(str(WS / "说明.pdf"))
check(r["kind"] == "text" and "共 3 页" in r["text"] and "【第 1 页】\nHello PDF page one" in r["text"] and "【第 2 页】\nSecond page 2026" in r["text"] and "第 3 页" not in r["text"],
      "PDF 读出文字：一页一段、标第几页，空白页不占地方")
pw2 = PdfWriter()
pw2.add_blank_page(width=100, height=100)
with open(WS / "扫描件.pdf", "wb") as f:
    pw2.write(f)
try:
    F.read(str(WS / "扫描件.pdf"))
    msg = ""
except F.Denied as e:
    msg = str(e)
check("没有能读出来的文字" in msg, f"整页是图的 PDF：照实说读不出字（{msg[:30]}）")
from openpyxl import Workbook  # noqa: E402
wb = Workbook()
ws_ = wb.active
ws_.title = "预算"
ws_.append(["项目", "金额", "备注"])
ws_.append(["显卡", 3299, None])
ws_.append(["合计", "=B2", "公式"])
wb.create_sheet("空的")
wb.save(WS / "账.xlsx")
r = F.read(str(WS / "账.xlsx"))
check("【表：预算（3 行）】" in r["text"] and "项目 | 金额 | 备注" in r["text"] and "显卡 | 3299" in r["text"] and "【表：空的（0 行）】\n（空表）" in r["text"],
      "Excel 读出文字：一张表一段，一行一行用 | 隔开")
(WS / "片子.mp4").write_bytes(b"\x00" * 64)
try:
    F.read(str(WS / "片子.mp4"))
    msg = ""
except F.Denied as e:
    msg = str(e)
check("不是文字文件" in msg and ".pdf .xlsx" in msg, "读不了的（视频）：说清楚能读哪些")

# ---------- 整个文件夹收进来 ----------
d1 = W.recv_dir("素材包")
d2 = W.recv_dir("素材包")
d3 = W.recv_dir("..\\..\\a<b")
day = time.strftime("%Y-%m-%d")
check(W.rel(d1).replace("\\", "/") == f"收到的/{day}/素材包" and d2.name == "素材包 (2)" and d3.name == "a_b" and d3.parent == d1.parent,
      "整个文件夹：建在 收到的\\日期\\ 下面，重名加 (2)，名字里带路径的只留名字")
p1 = W.recv_target("图.png", W.rel(d1), "画面/第一段")
p1.write_bytes(b"x")
p2 = W.recv_target("图.png", W.rel(d1), "画面/第一段")
p3 = W.recv_target("说明.txt", W.rel(d1), "../../..//外面")
check(p1 == d1 / "画面" / "第一段" / "图.png" and p2.name == "图 (2).png" and p3 == d1 / "外面" / "说明.txt", "里面的文件：子文件夹原样保留，重名加序号，.. 往上走的被去掉")
ok_ = True
for bad_into in ("../外面", str(T), "收到的", "片头"):
    try:
        W.recv_target("a.txt", bad_into, "")
        ok_ = False
    except F.Denied:
        pass
check(ok_ and not (T / "a.txt").exists(), "into 只能是「收到的」里面的文件夹（外面的、工作区别处的都不行）")
p3.write_text("这是说明：做一个 10 秒的片头", "utf-8")
if FF:
    shutil.copy(S_ / "a.mp4", d1 / "画面" / "片头.mp4")
(d1 / "node_modules").mkdir()
(d1 / "node_modules" / "x.js").write_text("x", "utf-8")
f1 = W.recv_target("单独的.txt")
f1.write_text("单独一个文件的内容", "utf-8")
shutil.copy(WS / "账.xlsx", f1.parent / "账.xlsx")
got = W.received([W.rel(d1), W.rel(f1), W.rel(f1.parent / "账.xlsx"), "说明.pdf", "../x", W.rel(d1)])
note = W.recv_note(got)
check(len(got) == 3 and got[0]["dir"] and got[0]["n"] >= 2 and "[文件夹] " in note and "个文件，共" in note and "node_modules" not in note,
      f"发消息带上文件夹：只认「收到的」里的，重复的算一次，告诉模型里面有什么（{got[0]['n']} 个文件）")
check("单独一个文件的内容" in note and "【表：预算" in note and (not FF or "视频 · 2.5 秒 · 640×360" in note),
      "给模型的那段话：小的文字文件、Excel 带上内容，视频带上时长和分辨率")

# ---------- 做好的文件 ----------
time.sleep(0.3)
t0 = time.time()
time.sleep(0.3)
(WS / "片头").mkdir()
(WS / "片头" / "make.py").write_text("print(1)", "utf-8")
(WS / "片头" / "进度.md").write_text("做完了", "utf-8")
(WS / "片头" / "帧").mkdir()
for k in range(30):
    (WS / "片头" / "帧" / f"{k:05d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 30)
(WS / "片头" / "封面.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x06\x40\x00\x00\x04\xb0" + b"0" * 30)
if FF:
    shutil.copy(S_ / "a.mp4", WS / "片头" / "成品.mp4")
    (WS / "片头" / "成品.mp4").touch()
(WS / "片头" / "配音.wav").write_bytes(b"RIFF" + b"\x00" * 40)
(WS / W.TMP).mkdir(exist_ok=True)
(WS / W.TMP / "t.png").write_bytes(b"x")
W.recv_target("后来的.png").write_bytes(b"x")
dv = W.deliverables(t0)
names = [m["name"] for m in dv["media"]]
check(names == (["成品.mp4"] if FF else []) + ["配音.wav", "封面.png"] and [f["name"] for f in dv["folders"]] == ["帧"] and dv["folders"][0]["n"] == 30,
      f"做好的文件：视频、音频、图片按这个顺序；一个文件夹里 30 张画面只算一个文件夹（{names}）")
check([m["name"] for m in dv["others"]] == ["make.py"] and (not FF or dv["media"][0]["info"] == "视频 · 2.5 秒 · 640×360") and dv["media"][-1]["info"] == "图片 · 1600×1200",
      "别的文件（脚本）单列，进度.md、收到的、临时文件夹里的不算；视频和图带着时长、分辨率")
check(W.deliverables(time.time() + 5)["n"] == 0, "这件事之前就有的文件不算")

# ---------- 生图 / 配音「放进工作区」----------
r = W.take_in([S_ / "坏的.mp4", (S_ / "x不存在.png", "a.png")], "生图/第一期")
r2 = W.take_in([(S_ / "坏的.mp4", "改名.mp4"), S_ / "坏的.mp4"], "生图/../../第一期")
check(r["n"] == 1 and (WS / "素材" / "生图" / "第一期" / "坏的.mp4").exists() and r2["n"] == 2 and (WS / "素材" / "生图" / "第一期" / "改名.mp4").exists() and
      any(W.BACKUP.rglob("坏的.mp4")), "放进工作区：复制进 素材\\…，能改名，同名的旧文件先备份，.. 出不去")
try:
    W.take_in([S_ / "没有.png"], "x")
    msg = ""
except F.Denied as e:
    msg = str(e)
check("没有能放进去的" in msg, "没有文件可放：照实说")

# ---------- QQ 附件 ----------
qq.API = qq.SANDBOX_API = "http://127.0.0.1:8099/qq"
qq.BOT.token, qq.BOT.token_exp = "T", time.time() + 3600
atts = qq.attachments({"attachments": [{"content_type": "image/png", "filename": "", "url": "127.0.0.1:8099/qq/att/a.png", "size": 70},
                                       {"content_type": "file", "filename": "报价单.txt", "url": "//127.0.0.1:8099/qq/att/b.txt"},
                                       {"content_type": "voice", "url": "http://127.0.0.1:8099/qq/att/404"}, {"url": ""}, "乱的"]})
check(len(atts) == 3 and atts[0]["url"].startswith("https://127.0.0.1") and atts[0]["name"].startswith("QQ图片_") and atts[0]["name"].endswith(".png") and
      atts[1]["name"] == "报价单.txt" and atts[2]["name"].endswith(".silk"), "QQ 消息里的附件：地址没带 https 的补上，没名字的按类型起名")
for a in atts[:2]:
    a["url"] = a["url"].replace("https://", "http://")          # 假平台只有 http
atts.append({"url": "http://127.0.0.1:8099/qq/att/big.bin", "name": "太大.bin", "type": "", "size": qq.MAX_ATT + 1})
paths.CHAT_FILES = T / "chat"
try:
    rels, imgs, badl = asyncio.run(qq.fetch_attachments(atts))
    recv = WS / "收到的" / day
    check(len(rels) == 2 and (recv / atts[0]["name"]).read_bytes()[:4] == b"\x89PNG" and (recv / "报价单.txt").read_text("utf-8") == "QQ 发来的文件：b.txt" and
          not list(recv.glob("*.part")), f"QQ 附件下载进 工作区\\收到的\\日期\\（{rels}）")
    check(len(imgs) == 1 and pathlib.Path(imgs[0]["path"]).is_file() and len(badl) == 2 and "404" in badl[0] and "太大" in badl[1], f"图片另存一份给模型看；下不了的、太大的照实说（{badl}）")
    ok1, info1 = asyncio.run(qq.BOT.send_image("OID", recv / atts[0]["name"], "MSG9"))
    ok2, info2 = asyncio.run(qq.BOT.send_image("OID", recv / "报价单.txt", "MSG9"))
    seen = httpx.get("http://127.0.0.1:8099/__qq", timeout=10).json()
    m = seen["msgs"][-1]
    check(ok1 and seen["files"][-1] == {"oid": "OID", "file_type": 1, "n": seen["files"][-1]["n"], "srv_send_msg": False} and seen["files"][-1]["n"] > 50 and
          m["msg_type"] == 7 and m["media"] == {"file_info": f"FI_{len(seen['files'])}"} and m["msg_id"] == "MSG9" and m["msg_seq"] == 1,
          "图片发回 QQ：先传上去拿 file_info，再发富媒体消息（带着被动回复的 msg_id）")
    check(not ok2 and "PNG / JPEG" in info2, f"不是图片的不发（{info2}）")
except httpx.ConnectError:
    print("  （假服务没起来，QQ 附件的下载和发送跳过）")

# ---------- 2. 连测试后端 ----------
B_ = "http://127.0.0.1:8765"
c = httpx.Client(base_url=B_, timeout=60, headers={"X-Agent": "1"})
try:
    c.get("/api/ping").raise_for_status()
except Exception:
    print("测试后端没起来（dev/serve.sh start），后面的跳过")
    print("不过的：", bad or "没有")
    sys.exit(1 if bad else 0)
c.put("/api/ws", json={"dir": "", "run": True})
WS2 = paths.ROOT / "工作区"
shutil.rmtree(WS2 / "收到的", ignore_errors=True)
shutil.rmtree(WS2 / "v23", ignore_errors=True)


def ask(body):
    tok = c.post("/api/chat", json=dict(body, **{"async": True})).json()["token"]
    for _ in range(240):
        j = c.get("/api/chat/" + tok).json()
        if j["done"]:
            return j.get("event") or {}
        time.sleep(0.25)
    return {}


d = c.post("/api/ws/recvdir", json={"name": "第一期素材"}).json()
u1 = c.post("/api/ws/upload", params={"name": "文案.txt", "into": d["rel"], "sub": ""}, content="片头文案：欢迎来到白页的频道".encode()).json()
u2 = c.post("/api/ws/upload", params={"name": "a.png", "into": d["rel"], "sub": "图/角色"}, content=b"\x89PNG\r\n\x1a\n" + b"0" * 40).json()
u3 = c.post("/api/ws/upload", params={"name": "a.txt", "into": "../../app", "sub": ""}, content=b"x")
check(d["rel"].replace("\\", "/") == f"收到的/{day}/第一期素材" and u1["rel"].replace("\\", "/").endswith("第一期素材/文案.txt") and
      u2["rel"].replace("\\", "/").endswith("第一期素材/图/角色/a.png") and u3.status_code == 400 and not (paths.ROOT / "app" / "a.txt").exists(),
      "接口：整个文件夹先建好再一个个传，子文件夹原样；into 写到外面的被拦下")
ev = ask({"text": "这个文件夹里有什么", "files": [d["rel"]]})
last = httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}
umsg = json.dumps(last.get("messages", [])[-1:], ensure_ascii=False)
rcv = [s for s in ev.get("steps") or [] if s[0] == "收到文件"]
check(ev.get("to") == "ds" and rcv and "1 个文件夹" in rcv[0][1] and "[文件夹]" in umsg and "文案.txt" in umsg and "a.png" in umsg and
      any(f["kind"] == "dir" for f in ev.get("files") or []), f"带着文件夹发消息：交给 DeepSeek，告诉它文件夹在哪、里面有什么（{rcv[0][1] if rcv else '没有'}）")
plan = [{"name": "write_file", "arguments": {"path": "v23/make.py", "content": "print('hi')"}},
        {"name": "write_file", "arguments": {"path": "v23/封面.png", "content": "假装是图"}},
        {"name": "write_file", "arguments": {"path": "v23/成品.mp4", "content": "假装是视频"}}]
ev = ask({"text": "帮我在工作区做个片头【工作区】" + json.dumps(plan, ensure_ascii=False)})
fs = ev.get("files") or []
outs = [f for f in fs if f["kind"] == "out"]
st = [s for s in ev.get("steps") or [] if s[0] == "做好的文件"]
check([f["name"] for f in outs] == ["成品.mp4", "封面.png"] and [f["name"] for f in fs if f["kind"] == "outf"] == ["make.py"] and st and "3 个" in st[0][1],
      f"DeepSeek 做出来的文件记进事件：视频、图给卡片，脚本单列（{st[0][1] if st else '没有'}）")
if outs:
    r = c.get(f"/api/chat/out/{outs[0]['id']}", headers={"Range": "bytes=0-5"})
    r2 = c.post(f"/api/chat/out/{outs[0]['id']}/open", json={"how": "folder"})
    (WS2 / "v23" / "成品.mp4").unlink()
    r3 = c.get(f"/api/chat/out/{outs[0]['id']}")
    rd = [f for f in fs if f["kind"] not in ("out", "outf", "outd")]
    r4 = c.get(f"/api/chat/out/{rd[0]['id']}") if rd else None
    check(r.status_code == 206 and len(r.content) == 6 and r2.status_code == 200 and "v23" in r2.json()["msg"] and r3.status_code == 404 and (r4 is None or r4.status_code == 404),
          "做好的文件：能看（视频能拖进度条）、能在文件夹里显示；挪走了就说找不到；不是做好的文件不给")
ev = ask({"text": "你好呀"})
check(not [f for f in ev.get("files") or [] if f["kind"].startswith("out")], "没动工作区的事不带做好的文件")
st = c.get("/api/ws").json()
check(st["recv_files"] >= 2 and st["recv_size"] > 40 and st["recv"].replace("\\", "/").endswith("工作区/收到的") and c.post("/api/ws/open", json={"what": "recv"}).status_code == 200,
      f"设置里的工作文件夹：「收到的」有多少个、多大（{st['recv_files']} 个 · {st['recv_size']} 字节）")

shutil.rmtree(T, ignore_errors=True)
print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
