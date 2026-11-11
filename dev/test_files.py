"""读本地文件、对话里带图片（v1.8.17）。沙箱连不上 DeepSeek：用假的（dev/mocks.py，8099）。
1. 不连后端：能读的文件夹（只读、去重、不让加 data 和整个盘）→ 能不能读（.. 绕不出去、符号链接绕不出去、Agent 的 data 和密钥文件不读）→
   读（UTF-8、GBK、Word、图片、太长分段、不是文字的不读）→ 列目录（藏起 .obsidian、.env）→ 搜（文件名、内容、几个词）→
   消息里贴的路径（后面紧跟中文也认得出、不存在的、不在允许里的）→ 读出来塞进消息（本地小脑只放前 3000 字、看不了图）→
   给 DeepSeek 的工具（只给「能发给 DeepSeek」的文件夹）→ 图片上传（认文件头、10MB）
2. 连测试后端（dev/serve.sh start）：加文件夹（接口、通用改设置加不了）→ 贴文件路径 → 「查笔记」（DeepSeek 先搜再读）→
   没允许的文件夹（回「允许读这个文件夹」）→ 只给本地看的文件夹不发 DeepSeek → 隐私的不发 → 带图片（看图模型、缩略图）→
   重做带着原来的图 → 图片太多、不是图片
用法：python dev/test_files.py（要先 dev/serve.sh start）"""
import base64
import io
import json
import os
import pathlib
import shutil
import sys
import time
import zipfile

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev"))
from app import files as F, paths, settings  # noqa: E402
from fake_apiyi import png  # noqa: E402

bad = []
RUN = ROOT / "dev" / ".run"
T = RUN / "读文件测试"


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


def docx(text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body>" + "".join(f"<w:p><w:r><w:t>{x}</w:t></w:r></w:p>" for x in text.split("\n")) + "</w:body></w:document>")
    return b.getvalue()


# ---------- 准备一个「笔记仓库」 ----------
shutil.rmtree(T, ignore_errors=True)
V = T / "笔记仓库"
(V / "世界观").mkdir(parents=True)
(V / ".obsidian").mkdir()
(V / ".obsidian" / "app.json").write_text("{}", "utf-8")
(V / "世界观" / "人物.md").write_text("# 人物\n\n紫苏：技术宅，深蓝黑色头发，圆框细眼镜，宽大紫色卫衣。\n", "utf-8")
(V / "世界观" / "地理.md").write_text("# 地理\n\n" + "长长的设定。" * 4000 + "\n结尾：北方有一座雪山。", "utf-8")
(V / "旧设定.txt").write_bytes("旧版的设定：魔法要付出代价。".encode("gb18030"))
(V / "大纲.docx").write_bytes(docx("第一章 黄昏的车站\n第二章 紫色的卫衣"))
(V / "截图.png").write_bytes(png(64, 48, False, 3))
(V / ".env").write_text("SECRET=1", "utf-8")
(V / "程序.exe").write_bytes(b"MZ\x00\x00" + b"\x00" * 100)
OUT = T / "外面"
OUT.mkdir()
(OUT / "别的.md").write_text("不该被读到", "utf-8")
LOCAL = T / "日记"
LOCAL.mkdir()
(LOCAL / "今天.md").write_text("只给本地看的日记：今天去了图书馆。", "utf-8")
try:
    os.symlink(OUT / "别的.md", V / "链接.md")
    LINK = True
except OSError:
    LINK = False

# ---------- 1. 不连后端（设置写到临时文件，不碰测试后端的设置） ----------
old_file, s0 = settings._FILE, dict(settings.S)
settings._FILE = RUN / "读文件测试_设置.json"
try:
    settings.S["readDirs"] = []
    settings.S["wsDir"] = str(T / "空的工作区")           # 工作区也算能读的：换成一个空的，别的测试留在真工作区里的文件不来搅和
    check(F.clean([{"path": str(V)}, str(V), {"path": ""}, 5, {"path": str(LOCAL), "cloud": False}]) == [{"path": str(V), "cloud": True}, {"path": str(LOCAL), "cloud": False}],
          "能读的文件夹：去重、去掉不像样的，「能发给 DeepSeek」默认开")
    F.add_dir(str(V))
    F.add_dir(str(LOCAL), cloud=False)
    F.add_dir(str(V / "世界观" / "人物.md"))                 # 给的是文件：加它所在的文件夹（已经在里面了，不重复）
    e1, e2, e3 = raises(F.add_dir, str(paths.DATA)), raises(F.add_dir, "/"), raises(F.add_dir, str(T / "没有这个"))
    check(len(F.dirs()) == 3 and e1 and "整个盘" in e2 and "找不到" in e3, f"加文件夹：Agent 的 data 不能加、整个盘不能加、不存在的不能加（{e1[:16]}…）")
    F.remove_dir(str(V / "世界观"))
    check(len(F.dirs()) == 2 and [d["cloud"] for d in F.dirs()] == [True, False] and len(F.dirs(True)) == 1, "删掉、只给本地看的文件夹单独标着")
    log = (paths.LOGS / "actions.jsonl").read_text("utf-8").strip().split("\n")[-6:]
    check(any('"tool.add"' in x and "笔记仓库" in x for x in log), "加文件夹记进动作日志（给 agent 加权限）")

    check(F.check(V / "世界观" / "人物.md") and raises(F.check, OUT / "别的.md") and raises(F.check, V / ".." / "外面" / "别的.md")
          and "密钥" in raises(F.check, V / ".env"), "能读：文件夹里的；不能读：外面的、用 .. 绕出去的、.env 这类密钥文件")
    if LINK:
        check(raises(F.read, V / "链接.md") != "", "文件夹里的快捷方式指到外面：照样不让读")
    F.add_dir(str(ROOT))
    check("Agent 自己的数据" in raises(F.read, paths.DATA / "settings.json"), "就算加了 Agent 的文件夹，data 里的设置、密钥也不读")
    F.remove_dir(str(ROOT))
    check("只给本地小脑看" in raises(F.check, LOCAL / "今天.md", True) and F.check(LOCAL / "今天.md", False), "只给本地看的文件夹：给 DeepSeek 的读不了，本地的能读")

    r = F.read(V / "世界观" / "人物.md")
    g = F.read(V / "旧设定.txt")
    w = F.read(V / "大纲.docx")
    im = F.read(V / "截图.png")
    long1 = F.read(V / "世界观" / "地理.md")
    long2 = F.read(V / "世界观" / "地理.md", long1["offset"] + len(long1["text"]))
    check("紫苏：技术宅" in r["text"] and "魔法要付出代价" in g["text"] and "第二章 紫色的卫衣" in w["text"] and im["kind"] == "image" and im["uri"].startswith("data:image/png;base64,"),
          "读：UTF-8、GBK（旧的 txt）、Word、图片（给 DeepSeek 看）都行")
    check(long1["more"] and len(long1["text"]) == F.MAX_CHARS and not long2["more"] and "北方有一座雪山" in long2["text"], "太长的一次读 2 万字，用 offset 接着读到结尾")
    check("不是文字文件" in raises(F.read, V / "程序.exe") and "文件夹" in raises(F.read, V / "世界观"), "程序、文件夹不当文字读")
    ls = F.list_dir(V)["text"]
    check("[文件夹] 世界观" in ls and "人物.md" not in ls and "大纲.docx" in ls and ".obsidian" not in ls and ".env" not in ls, "列目录：文件夹和文件、大小、日期；藏起 .obsidian 和 .env")
    f1, f2, f3 = F.find("紫苏"), F.find("人物"), F.find("紫色 卫衣")
    check(f1["n"] >= 1 and "人物.md" in f1["text"] and "技术宅" in f1["text"] and "人物.md" in f2["text"] and "大纲.docx" in f3["text"] and "别的.md" not in F.find("不该")["text"],
          "搜：按内容（带命中的那句）、按文件名、几个词都要有、Word 里的也搜；外面的搜不到")
    check(F.find("今天")["n"] >= 1 and F.find("今天", cloud=True)["n"] == 0, "搜：给 DeepSeek 的只搜「能发给 DeepSeek」的文件夹")

    ms = F.mentioned(f"看一下 {V}/世界观/人物.md 写了什么")
    m2 = F.mentioned(f"{V}你看一下能不能访问这个文件夹。")
    m3 = F.mentioned(f"看看 {OUT}/别的.md 还有 {T}/没有这个文件.md")
    check(len(ms) == 1 and ms[0]["exists"] and ms[0]["allowed"] and not ms[0]["is_dir"] and ms[0]["path"].endswith("人物.md"), "消息里贴的文件路径：认出来，能读")
    check(len(m2) == 1 and m2[0]["is_dir"] and m2[0]["path"] == str(V), "路径后面紧跟着中文（没有空格）也认得出是哪个文件夹")
    check(len(m3) == 2 and m3[0]["exists"] and not m3[0]["allowed"] and not m3[1]["exists"], "不在允许里的、不存在的：分别标出来")
    check(F.mentioned("看看 https://example.com/a/b 这个网页") == [], "网址不当成路径")
    ex, pics, used = F.attach(ms + F.mentioned(f"{V}/截图.png"), local=False)
    exl, picl, _ = F.attach(F.mentioned(f"{V}/世界观/地理.md {V}/截图.png"), local=True)
    check("紫苏：技术宅" in ex and len(pics) == 1 and [u[0] for u in used] == ["file", "fimg"], "贴的路径读出来塞进消息：文件内容、图片（给 DeepSeek 看）")
    check("前 3000 字" in exl and not picl and "本地小脑看不了图" in exl, "给本地小脑：只放前 3000 字，看不了图就说一声")
    t1, st1, _, _ = F.run_tool("find_files", {"query": "紫苏"})
    t2, st2, pic, path = F.run_tool("read_file", {"path": str(V / "截图.png")})
    check(st1[0] == "搜文件" and "人物.md" in t1 and pic and pic["kind"] == "image" and st2 == ["读文件", "笔记仓库\\截图.png · 图片"],
          "给 DeepSeek 的工具：搜文件、读文件（图片附在下一条消息里）")
    check("只给本地小脑看" in raises(F.run_tool, "read_file", {"path": str(LOCAL / "今天.md")}), "给 DeepSeek 的工具读不了只给本地看的文件夹")
    check(F.wants("帮我在笔记仓库里查一下紫苏的设定") and not F.wants("今天天气怎么样"), "看着像要查他电脑上的资料：交给带读文件工具的 DeepSeek")
    up = F.save_upload("data:image/png;base64," + base64.b64encode(png(40, 30, False, 1)).decode())
    check(pathlib.Path(up["path"]).is_file() and up["mime"] == "image/png" and pathlib.Path(up["path"]).resolve().is_relative_to(paths.CHAT_FILES.resolve()),
          "对话里发的图片：存进 data\\chat\\日期")
    check("只认" in raises(F.save_upload, "data:image/png;base64," + base64.b64encode(b"hello world").decode()) and "太大" in raises(F.save_upload, "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (11 << 20)).decode()),
          "图片认文件头（改了扩展名的不收）、10MB 以内")
    pathlib.Path(up["path"]).unlink()
finally:
    settings._FILE = old_file
    settings.S.clear()
    settings.S.update(s0)
    (RUN / "读文件测试_设置.json").unlink(missing_ok=True)

# ---------- 2. 连测试后端 ----------
B, H = "http://127.0.0.1:8765", {"X-Agent": "1"}
c = httpx.Client(base_url=B, headers=H, timeout=60)


def ask(text, **kw):
    r = c.post("/api/chat", json={"text": text, "async": True, **kw})
    r.raise_for_status()
    tok = r.json()["token"]
    for _ in range(160):
        j = c.get("/api/chat/" + tok).json()
        if j["done"]:
            return j.get("event") or {}
        time.sleep(0.25)
    return {}


def last():
    return httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()


def steps(ev, name):
    return [s[1] for s in ev.get("steps") or [] if s[0] == name]


for d in c.get("/api/files/dirs").json()["dirs"]:
    c.delete("/api/files/dirs", params={"path": d["path"]})
c.put("/api/settings", json={"readDirs": [{"path": str(OUT), "cloud": True}], "searchOn": True, "dsVision": "deepseek-flash"})
check(c.get("/api/files/dirs").json()["dirs"] == [], "通用的「改设置」加不了能读的文件夹（要走自己的接口、记日志）")
r = c.post("/api/files/dirs", json={"path": str(T / "没有这个")})
check(r.status_code == 400 and "找不到" in r.json()["detail"], "加一个不存在的文件夹：说找不到")
c.post("/api/files/dirs", json={"path": str(V)})
c.post("/api/files/dirs", json={"path": str(LOCAL), "cloud": False})
ds = c.get("/api/files/dirs").json()["dirs"]
check([(d["path"], d["cloud"], d["exists"]) for d in ds] == [(str(V), True, True), (str(LOCAL), False, True)], "设置里加了两个文件夹：笔记仓库（能发给 DeepSeek）、日记（只给本地）")

ev = ask(f"看一下 {V}/世界观/人物.md 写了什么")
lc = last()["chat"]
user = lc["messages"][-1]["content"] if isinstance(lc["messages"][-1]["content"], str) else ""
check(any("人物.md" in x for x in steps(ev, "读文件")) and "紫苏：技术宅" in json.dumps(lc["messages"], ensure_ascii=False)
      and [f["kind"] for f in ev.get("files") or []] == ["file"] and ev.get("to") != "local",
      "贴了文件路径：程序读出来一起发给 DeepSeek，事件里记着读了哪个文件")
check(any((t.get("function") or {}).get("name") == "read_file" for t in lc.get("tools") or []) and str(V) in lc["messages"][0]["content"] and str(LOCAL) not in lc["messages"][0]["content"],
      "DeepSeek 带着读文件的工具，系统提示里只列了「能发给 DeepSeek」的文件夹")
ev = ask("【查笔记】紫苏 帮我看看笔记里怎么写的")
check(steps(ev, "搜文件") and any("人物.md" in x for x in steps(ev, "读文件")) and "读到了" in (ev.get("reply") or "") and any(f["name"] == "人物.md" for f in ev.get("files") or []),
      f"问笔记里的事：DeepSeek 先搜、再读（{steps(ev, '搜文件')} → {steps(ev, '读文件')}）")
ev = ask(f"【读文件】{OUT}/别的.md")
check("不该被读到" not in json.dumps(last()["chat"]["messages"], ensure_ascii=False), "没允许的文件：DeepSeek 用工具也读不到")
ev = ask(f"看看 {OUT}/别的.md")
check("还没允许我读" in (ev.get("reply") or "") and steps(ev, "没有权限") == [str(OUT)], "贴了没允许的文件夹里的路径：不读，回一句「允许读这个文件夹」（界面上有按钮）")
ev = ask(f"看一下 {LOCAL}/今天.md")
check("今天去了图书馆" not in json.dumps(last()["chat"], ensure_ascii=False) and ev.get("id"), "只给本地看的文件夹里的文件：内容不发给 DeepSeek")
before = json.dumps(last()["chat"], ensure_ascii=False)
ev = ask(f"我最近失眠，看一下 {V}/世界观/人物.md")
check(ev.get("private") and ev.get("to") == "local" and json.dumps(last()["chat"], ensure_ascii=False) == before and steps(ev, "读文件"),
      "涉及隐私的消息：只在本地处理（读到的内容也不发出本机）")

p1 = "data:image/png;base64," + base64.b64encode(png(80, 60, False, 7)).decode()
ev = ask("这张截图里是什么", images=[p1])
lc = last()
fs = [f for f in ev.get("files") or [] if f["kind"] == "img"]
check("看图 · deepseek-flash" in (ev.get("reply") or "") and lc["chat"]["model"] == "deepseek-flash" and steps(ev, "收到图片") == ["1 张"] and ev.get("to") != "local",
      "带图片的消息：交给 DeepSeek 看（用看图的模型 deepseek-flash）")
img = c.get(f"/api/chat/file/{fs[0]['id']}") if fs else None
check(img is not None and img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n" and c.get("/api/chat/file/999999").status_code == 404, "聊天记录里拿得到这张图（缩略图、看大图）")
c.put("/api/settings", json={"dsVision": "deepseek-vision-test"})
ev2 = ask("", images=[p1, p1])
check(last()["chat"]["model"] == "deepseek-vision-test" and "2 张" in (ev2.get("reply") or "") and ev2.get("text") == "看看这张图。", "看图用的模型能在设置里换；只发图片不写字也行")
c.put("/api/settings", json={"dsVision": "deepseek-flash"})
r = c.post(f"/api/events/{ev['id']}/redo", json={"to": "ds"})
tok = r.json()["token"]
for _ in range(120):
    j = c.get("/api/chat/" + tok).json()
    if j["done"]:
        break
    time.sleep(0.25)
check([f["kind"] for f in (j.get("event") or {}).get("files") or []] == ["img"] and "看图" in ((j.get("event") or {}).get("reply") or ""), "换它重做：带着原来那张图再做一遍")
r1 = c.post("/api/chat", json={"text": "x", "async": True, "images": [p1] * 7})
r2 = c.post("/api/chat", json={"text": "x", "async": True, "images": ["data:image/png;base64," + base64.b64encode(b"not an image").decode()]})
check(r1.status_code == 400 and "6 张" in r1.json()["detail"] and r2.status_code == 400 and "只认" in r2.json()["detail"], "一次最多 6 张；不是图片的不收")
evs = c.get("/api/events?limit=20").json()
check(any(f.get("kind") == "img" for e in evs for f in e.get("files") or []), "事件列表里带着图片和读过的文件（对话页显示）")

for d in c.get("/api/files/dirs").json()["dirs"]:
    c.delete("/api/files/dirs", params={"path": d["path"]})
shutil.rmtree(T, ignore_errors=True)
print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
