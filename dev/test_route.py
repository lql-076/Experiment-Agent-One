"""第三条路「更强的模型」和"换它重做"：
1. 指定交给更强的模型：按你说的走，回复里用设置里的名字，决策脑原本的判断写进"为什么"
2. 不接受更强的模型：Agent 状态里这一路显示"没开"，分数并进 DeepSeek
3. 换它重做：同一句话换个去向再做一遍，记下是重做哪一条、原来那条记一次纠正
4. 隐私的事换到云端：不确认就 409，确认了才发
用法：python dev/test_route.py（要先 dev/serve.sh start）"""
import sys
import time

import httpx

B, H, bad = "http://127.0.0.1:8765", {"X-Agent": "1"}, []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def chat(text, **kw):
    r = httpx.post(B + "/api/chat", json=dict(text=text, **kw), headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


def put(**kw):
    httpx.put(B + "/api/settings", json=kw, headers=H, timeout=10).raise_for_status()


def wait(token):
    for _ in range(120):
        j = httpx.get(B + "/api/chat/" + token, timeout=10).json()
        if j["done"]:
            return j
        time.sleep(0.25)
    return {}


def raw(eid):
    return httpx.get(B + f"/api/events/{eid}", timeout=10).json()


try:
    put(strongOn=True, strongName="网页 Claude")
    print("1. 指定交给更强的模型")
    ev = chat("帮我把这周的计划排一下", force="cl")
    check(ev.get("to") == "cl", f"按你说的交给了更强的模型（to={ev.get('to')}）")
    check("网页 Claude" in (ev.get("reply") or ""), "回复里用的是设置里的名字「网页 Claude」")
    check("你指定交给" in (ev.get("why") or "") and "决策脑原本判给" in ev["why"], "为什么里写了你指定的，以及决策脑原本怎么判的")
    check("你指定了去向" in [s[0] for s in ev.get("steps") or []], "步骤里有「你指定了去向」")

    print("2. 不接受更强的模型")
    put(strongOn=False, strongName="")
    a = httpx.get(B + "/api/agent", timeout=10).json()
    cl = [it for g in a["groups"] for it in g["items"] if it["k"] == "claude"][0]
    check(cl["st"] == "off" and cl["name"] == "更强的模型", f"Agent 状态里这一路没开、名字是默认的（{cl['st']} / {cl['name']}）")
    ev = chat("帮我系统性地设计一下整个系统的长期架构")
    check(ev.get("to") != "cl" and ev["s"].get("cl", 0) == 0, f"不会再判给它，它的分数是 0（to={ev.get('to')}，cl={ev['s'].get('cl')}）")
    put(strongOn=True)

    print("3. 换它重做")
    ev = chat("今天天气怎么样适合出门吗")
    r = httpx.post(B + f"/api/events/{ev['id']}/redo", json={"to": "cl"}, headers=H, timeout=15)
    check(r.status_code == 200 and "token" in r.json(), f"重做开始了（{r.status_code}）")
    j = wait(r.json()["token"])
    ne = j.get("event") or {}
    check(ne.get("to") == "cl" and ne.get("id") != ev["id"], f"新的一条交给了更强的模型（#{ne.get('id')} to={ne.get('to')}）")
    steps = dict((s[0], s[1]) for s in ne.get("steps") or [])
    check(f"#{ev['id']}" in steps.get("你指定了去向", ""), f"写明了是重做哪一条：{steps.get('你指定了去向')}")
    check(raw(ev["id"]).get("fix") == "cl", "原来那条记了一次纠正（以后照这个判）")

    print("4. 隐私的事换到云端")
    pe = chat("我最近在吃什么药，帮我记一下剂量")
    check(pe.get("private") in (1, True), f"认出是隐私（private={pe.get('private')}）")
    r = httpx.post(B + f"/api/events/{pe['id']}/redo", json={"to": "ds"}, headers=H, timeout=15)
    check(r.status_code == 409, f"不确认就不发出本机（{r.status_code}：{r.json().get('detail', '')[:30]}）")
    r = httpx.post(B + f"/api/events/{pe['id']}/redo", json={"to": "ds", "allow_private": True}, headers=H, timeout=15)
    ne = wait(r.json()["token"]).get("event") or {}
    check(ne.get("to") == "ds" and "你确认了发给云端" in (ne.get("why") or ""), f"确认了才交给 DeepSeek（to={ne.get('to')}）")
    check("隐私内容不发给" not in (ne.get("reply") or "") and "你确认了发出本机" in [s[0] for s in ne.get("steps") or []],
          f"确认过的这一次真的发出去了，步骤里记着：{(ne.get('reply') or '')[:30]}")
    r = httpx.post(B + "/api/chat", json={"text": "我在吃的药要不要换", "force": "ds"}, headers=H, timeout=30)
    check(r.status_code == 409, f"发消息时指定交给云端、又涉及隐私：也要先确认（{r.status_code}）")
    print("5. 不经过模型的快捷处理（v1.7.0 起这里会报错，v1.8.2 修）")
    ev = chat("记住我喜欢喝冰美式")
    check(ev.get("label") == "记住" and "记下了" in (ev.get("reply") or ""), f"「记住……」直接写进记忆（{ev.get('label')}：{(ev.get('reply') or '')[:20]}）")
finally:
    put(strongOn=True, strongName="")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
