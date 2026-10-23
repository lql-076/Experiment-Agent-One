"""接 Obsidian（连测试后端，用两个假库）：
1. E 盘的库强制只读；只读的库一个字都不写（整个测试前后，小说库的文件一模一样）
2. 扫库：跳过 .obsidian，私人文件夹和写了「私人: true」的笔记标成私人
3. 查笔记：不许看私人的时候，私人笔记一段都不给
4. 问设定：回答前先查笔记，发给 DeepSeek 的内容里有相关设定、没有私人笔记
5. DeepSeek 自己用「查笔记」工具
6. 用到私人笔记的事：私人内容不出本机
7. 「存到笔记：……」「把刚才的回答存到笔记」写进能写的库的 Agent 收件箱；撤销是挪进「已撤销」，不删
8. 每日整理：建议加的链接、前后矛盾的地方，写进收件箱「每日」
9. 只有只读库时不写；记忆搬进库里以后，记忆那个子文件夹不算笔记
用法：python dev/test_obsidian.py（要先 dev/serve.sh start）"""
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

DEV = Path(__file__).resolve().parent
sys.path.insert(0, str(DEV.parent))
from app.obsidian import clean_vaults  # noqa: E402

B, H, D, bad = "http://127.0.0.1:8765", {"X-Agent": "1"}, "http://127.0.0.1:8099", []
T = DEV / ".run" / "obs"
NOVEL, DATA, MEM = T / "笔记仓库", T / "vault-new", T / "memtest"


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def put(**kw):
    httpx.put(B + "/api/settings", json=kw, headers=H, timeout=10).raise_for_status()


def post(path, **kw):
    r = httpx.post(B + path, json=kw, headers=H, timeout=60)
    return r


def chat(text, **kw):
    r = httpx.post(B + "/api/chat", json={"text": text, **kw}, headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


def last_ds():
    j = httpx.get(D + "/__last", timeout=5).json().get("chat") or {}
    return "\n".join(str(m.get("content") or "") for m in j.get("messages") or [])


def tree(p):
    h = hashlib.sha1()
    for f in sorted(p.rglob("*")):
        h.update(str(f.relative_to(p)).encode())
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()


def w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


# 假的本地模型服务（只算向量）开在 8093，测完停掉（只停自己开的这个进程）
MODEL = subprocess.Popen([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import mocks, uvicorn; "
                          "uvicorn.run(mocks.m, host='127.0.0.1', port=8093, log_level='warning')", str(DEV)])
for _ in range(40):
    try:
        httpx.get("http://127.0.0.1:8093/health", timeout=1)
        break
    except Exception:
        time.sleep(0.25)
shutil.rmtree(T, ignore_errors=True)
w(NOVEL / ".obsidian" / "workspace.md", "不该被读到的配置")
w(NOVEL / "人物" / "主角.md", "---\ntags: [人物]\n---\n# 主角\n\n主角幻是三阶元素师，擅长雷系元素，住在栖冥谷。\n\n## 关系\n\n和白夜是同学，关系一般。\n")
w(NOVEL / "大纲" / "第二卷.md", "# 第二卷\n\n主角幻是四阶元素师，擅长雷系元素，住在栖冥谷。\n")
w(NOVEL / "世界观" / "元素体系.md", "# 元素体系\n\n元素师一共分九阶。雷系是最稀有的元素，主角就是雷系。\n")
w(NOVEL / "日记" / "2026-10-20.md", "# 日记\n\n今天写不出东西。秘密：最喜欢吃辣条。\n")
w(NOVEL / "灵感" / "结局.md", "---\n私人: true\n---\n# 结局\n\n只给自己看：结局让主角消失。\n")
w(DATA / ".obsidian" / "app.json", "{}")
w(DATA / "首页.md", "# 首页\n\n数据中心。\n")
MEM.mkdir(parents=True)
before = tree(NOVEL)
st0 = httpx.get(B + "/api/settings", timeout=5).json()["settings"]
VAULTS = [{"id": "novel", "name": "小说库", "path": str(NOVEL), "ro": True, "private": ["日记"]},
          {"id": "data", "name": "数据中心", "path": str(DATA), "ro": False, "private": []}]

try:
    print("1. 只读")
    check(clean_vaults([{"path": "E:\\gongzuochengxu\\笔记仓库"}])[0]["ro"] is True, "E 盘的库不管怎么设都是只读")
    check(clean_vaults([{"path": "e:/x", "ro": False}])[0]["ro"] is True, "小写 e:/ 也算")

    print("2. 扫库")
    put(memDir=str(MEM), obsVaults=VAULTS, obsOn=True, obsRead=True, obsWrite=True, modelPort=8093)
    time.sleep(2.5)                                    # 模型服务的状态缓存 2 秒
    s = post("/api/obsidian/refresh").json()["status"]
    v = {x["id"]: x for x in s["vaults"]}
    check(v["novel"]["notes"] == 5 and v["data"]["notes"] == 1, f"小说库 5 篇、数据中心 1 篇，.obsidian 里的不算（{v['novel']['notes']} / {v['data']['notes']}）")
    check(v["novel"]["waiting"] == 0 and v["novel"]["chunks"] >= 6, f"每段都算好了向量（{v['novel']['chunks']} 段，还差 {v['novel']['waiting']}）")
    check(v["novel"]["privNotes"] == 2, f"私人文件夹 + 写了「私人: true」的：2 篇私人（{v['novel']['privNotes']}）")
    check(s["inboxVault"] == "数据中心", f"收件箱放在能写的库（{s['inboxVault']}）")

    print("3. 查笔记")
    hits = httpx.get(B + "/api/obsidian/search", params={"q": "秘密 辣条", "private": 0}, timeout=10).json()["hits"]
    check(not any("日记" in h["path"] for h in hits), "不许看私人的时候，日记一段都不给")
    hits = httpx.get(B + "/api/obsidian/search", params={"q": "秘密 辣条", "private": 1}, timeout=10).json()["hits"]
    check(any("日记" in h["path"] for h in hits), "本地（能看私人的）找得到日记")

    print("4. 问设定，先查笔记")
    ev = chat("主角幻现在是几阶元素师", force="ds")
    st = dict((x[0], x[1]) for x in ev.get("steps") or [])
    check("查了笔记" in st, f"步骤里有「查了笔记」：{st.get('查了笔记')}")
    sent = last_ds()
    check("三阶元素师" in sent, "发给 DeepSeek 的提示里带上了《主角》的设定")
    check("最喜欢吃辣条" not in sent and "结局让主角消失" not in sent, "私人笔记一个字都没发出去")
    ev2 = chat("把刚才的回答存到笔记")
    check(ev2.get("label") == "存笔记" and "存好了" in (ev2.get("reply") or ""), f"「把刚才的回答存到笔记」：{(ev2.get('reply') or '')[:40]}")
    saved = list((DATA / "Agent 收件箱").glob("*.md"))
    check(any("（DeepSeek）" in f.read_text("utf-8") for f in saved), "存的是上一条回复")

    print("5. DeepSeek 自己查笔记")
    ev = chat("按笔记里的设定，主角擅长什么元素", force="ds")
    names = [x[0] for x in ev.get("steps") or []]
    check("查笔记" in names, f"DeepSeek 用了「查笔记」工具：{[x for x in ev.get('steps') or [] if x[0] == '查笔记']}")
    check((ev.get("reply") or "").startswith("（DeepSeek 笔记）") and "雷系" in ev["reply"], f"按查到的笔记回答：{(ev.get('reply') or '')[:40]}")

    print("6. 用到私人笔记")
    ev = chat("我日记里写的秘密是什么，辣条那个")
    names = [x[0] for x in ev.get("steps") or []]
    check("查了笔记" in names and ev.get("to") == "local", f"用到私人笔记（日记）的事交给本地小脑（{ev.get('to')} · {names}）")
    ev = chat("我日记里写的秘密是什么，辣条那个", force="ds")
    names = [x[0] for x in ev.get("steps") or []]
    check("私人笔记没发出去" in names, f"你指定交给 DeepSeek：私人笔记不跟着发（{names}）")
    check("写不出东西" not in last_ds(), "DeepSeek 收到的内容里没有日记原文")

    print("7. 存到笔记、撤销")
    ev = chat("存到笔记：第三章要写一场雷系对决")
    f = [x for x in (DATA / "Agent 收件箱").glob("*.md") if "雷系对决" in x.read_text("utf-8")]
    check(ev.get("label") == "存笔记" and len(f) == 1, f"写进了数据中心的 Agent 收件箱（{[x.name for x in f]}）")
    rep = httpx.get(B + "/api/report", timeout=10).json()
    ch = next((c for c in rep.get("changes") or [] if "写了笔记" in (c.get("w") or "") and "雷系对决" in c["w"]), None)
    r = post(f"/api/changes/{ch['id']}/undo").json() if ch else {}
    check("已撤销" in r.get("msg", "") and any((DATA / "Agent 收件箱" / "已撤销").glob("*.md")), f"撤销：挪进「已撤销」，不删（{r.get('msg')}）")

    print("8. 每日整理")
    r = post("/api/obsidian/tidy").json()
    day = next((DATA / "Agent 收件箱" / "每日").glob("*.md"), None)
    txt = day.read_text("utf-8") if day else ""
    check(bool(day) and "每日整理" in txt, f"写进了收件箱「每日」：{r.get('written')}")
    check(r.get("links", 0) >= 1 and "[[主角]]" in txt, f"建议加链接：《元素体系》提到了「主角」（{r.get('links')} 条）")
    check(r.get("conflicts", 0) >= 1 and "四阶" not in txt.split("## 可能前后矛盾的地方")[0], f"找到前后矛盾：主角三阶还是四阶（{r.get('conflicts')} 处，查了 {r.get('checked')} 对）")

    print("9. 只读库不写、记忆搬进库")
    put(obsVaults=VAULTS[:1])
    ev = chat("存到笔记：这句不该写进小说库")
    check("没存" in (ev.get("reply") or ""), f"只有只读库时不写：{(ev.get('reply') or '')[:40]}")
    put(obsVaults=VAULTS)
    r = post("/api/obsidian/move-memory", vault="data")
    check(r.status_code == 200 and (DATA / "Agent 记忆" / "记忆" / "收件箱.md").exists(), f"记忆搬进了数据中心（{r.json().get('msg', r.text)[:50]}）")
    r = post("/api/obsidian/move-memory", vault="novel")
    check(r.status_code == 400, f"只读的库不能放记忆（{r.status_code}）")
    s = post("/api/obsidian/refresh").json()["status"]
    n = {x["id"]: x["notes"] for x in s["vaults"]}["data"]
    check(s["memIn"] == "数据中心", f"Agent 状态里看得到记忆在库里（{s['memIn']}）")
    check(not any(r0["path"].startswith("Agent 记忆/") for r0 in httpx.get(B + "/api/obsidian/search", params={"q": "收件箱", "private": 1}, timeout=10).json()["hits"]),
          f"记忆那个子文件夹不算笔记（数据中心现在 {n} 篇）")
    time.sleep(0.2)
    check(tree(NOVEL) == before, "整个测试前后，小说库（只读）的文件一模一样")
finally:
    put(obsVaults=[], memDir=st0.get("memDir", ""), modelPort=st0.get("modelPort", 8090))
    httpx.post(B + "/api/obsidian/refresh", headers=H, timeout=30)
    MODEL.terminate()

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
