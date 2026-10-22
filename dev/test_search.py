"""联网搜索和"查说明书"的整条路：问最新的会先搜再读网页、带来源；隐私的不搜；每天上限；测试按钮；问 agent 自己怎么用会带上说明书。
用法：python dev/test_search.py（要先 dev/serve.sh start）"""
import sys

import httpx

B, H, bad = "http://127.0.0.1:8765", {"X-Agent": "1"}, []


def chat(text):
    r = httpx.post(B + "/api/chat", json={"text": text}, headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


def steps(ev):
    return [s[0] for s in (ev.get("steps") or [])]


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


print("1. 问最新的")
ev = chat("帕鲁最近更新了什么")
st = steps(ev)
check(ev.get("to") == "ds", f"交给 DeepSeek（to={ev.get('to')}）")
check("联网搜索" in st and "读网页" in st, f"先搜再读网页：{st}")
check("来源" in (ev.get("reply") or "") and "https://example.com" in ev["reply"], "回复里带来源链接")
check(ev.get("cost", 0) > 0, f"花费记上了 ¥{ev.get('cost')}")

print("2. 隐私的不搜")
n0 = len(httpx.get(B.replace("8765", "8099") + "/__last").json()["searches"])
ev = chat("我最近失眠得厉害，帮我搜一下最新的治疗办法")
n1 = len(httpx.get(B.replace("8765", "8099") + "/__last").json()["searches"])
check(ev.get("private") in (1, True), f"认出是隐私（private={ev.get('private')}）")
check(n1 == n0 and "联网搜索" not in steps(ev), f"一次都没搜（{n0} → {n1}）")

print("3. 每天上限")
cur = httpx.get(B + "/api/settings").json()["settings"]["searchDaily"]
httpx.put(B + "/api/settings", json={"searchDaily": 1}, headers=H)
ev = chat("DeepSeek 最新版本是多少")
check("联网搜索" not in steps(ev) and ev.get("reply"), f"到上限后不再搜、照样回答：{steps(ev)}")
httpx.put(B + "/api/settings", json={"searchDaily": cur}, headers=H)

print("4. 测试按钮")
r = httpx.post(B + "/api/actions/search_test", json={}, headers=H, timeout=30).json()
check(r.get("msg", "").startswith("能用") and r.get("results"), r.get("msg", ""))

print("5. 界面上的统计")
s = httpx.get(B + "/api/state").json().get("search") or {}
check(s.get("today", {}).get("n", 0) >= 3, f"今天的次数：{s.get('today')}")

print("6. 问 agent 自己怎么用")
ev = chat("免打扰在哪里设置？")
st = steps(ev)
last = httpx.get(B.replace("8765", "8099") + "/__last").json()["chat"] or {}
sysmsg = (last.get("messages") or [{}])[0].get("content", "")
check("查了说明书" in st, f"查了说明书：{st}")
check("说明书里和这条消息相关的段落" in sysmsg and "免打扰" in sysmsg, "说明书段落交给了模型")
check("现在是 20" in sysmsg, "系统提示词里有今天的日期")

print("7. 思考模式带工具（要把 reasoning_content 传回去）")
cur = httpx.get(B + "/api/settings").json()["settings"]["dsThinking"]
httpx.put(B + "/api/settings", json={"dsThinking": "on"}, headers=H)
ev = chat("最近有什么新闻值得看")
check("读网页" in steps(ev) and "联网" in (ev.get("reply") or ""), f"思考模式下也能搜完再答：{steps(ev)}")
ev = chat("坏历史：帮我搜一下最新的显卡价格")
check(ev.get("reply") and "没回上来" not in ev["reply"], f"官方拒了思考模式，自动改成不思考再答：{(ev.get('reply') or '')[:40]}")
httpx.put(B + "/api/settings", json={"dsThinking": cur}, headers=H)

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
