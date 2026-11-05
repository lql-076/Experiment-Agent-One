"""第三条路「更强的模型」和"换它重做"：
1. 指定交给更强的模型：按你说的走，回复里用设置里的名字，决策脑原本的判断写进"为什么"
2. 不接受更强的模型：Agent 状态里这一路显示"没开"，分数并进 DeepSeek
3. 换它重做：同一句话换个去向再做一遍，记下是重做哪一条、原来那条记一次纠正
4. 隐私的事换到云端：不确认就 409，确认了才发
用法：python dev/test_route.py（要先 dev/serve.sh start）"""
import json
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

    print("6. 每一步带时间，两票各投给谁写成单独的步骤（v2.0）")
    ev = chat("给我讲讲黑洞是怎么形成的")
    st = ev.get("steps") or []
    names = [s[0] for s in st]
    check("语义路由" in names and "Kev" in names, f"步骤里有「语义路由」「Kev」两行：{names[:5]}")
    check(all(len(s) >= 3 and isinstance(s[2], (int, float)) for s in st), "每一步都带着离收到过了多少秒（第三项）")
    check(all(st[i][2] <= st[i + 1][2] for i in range(len(st) - 1)), "时间是往后走的")
    kv = dict((s[0], s[1]) for s in st)
    check("%" in kv.get("Kev", "") and "没投票" not in kv.get("Kev", ""), f"Kev 投了票：{kv.get('Kev')}")

    print("7. 只有一票：不给满分，写清楚另一票为什么没投")
    one = kv.get("语义路由", "").startswith("没投票")          # 测试环境默认不起本地模型服务：语义路由投不了，只有 Kev 一票
    if one:
        check("只有一票" in (ev.get("why") or "") and "语义路由没投票" in ev["why"], f"为什么里写了只有一票、哪一票没投：{(ev.get('why') or '')[:50]}")
        check(max((ev.get("s") or {}).values() or [0]) <= 80, f"最高的分数不超过 80%：{ev.get('s')}")
    mode0 = httpx.get(B + "/api/settings", timeout=10).json()["settings"]["kevMode"]
    put(kevMode="off")
    ev = chat("给我讲讲黑洞是怎么形成的")
    kv = dict((s[0], s[1]) for s in ev.get("steps") or [])
    check(kv.get("Kev", "").startswith("没投票") and "关着" in kv.get("Kev", ""), f"Kev 关掉后，那一行写了没投票的原因：{kv.get('Kev')}")
    if one:
        check("简单规则" in (ev.get("why") or ""), f"两票都没有：按简单规则判，为什么里写着：{(ev.get('why') or '')[-30:]}")
    else:
        check("只有一票" in (ev.get("why") or ""), f"只剩语义路由一票：为什么里写了只有一票：{(ev.get('why') or '')[:40]}")
    put(kevMode=mode0)

    print("8. 问能不能给 agent 加功能：老实说要改代码、记下来，不交给本地小脑")
    n0 = len(httpx.get(B + "/api/wishes", timeout=10).json())
    ev = chat("能不能给你加一个导出聊天记录的功能？")
    names = [s[0] for s in ev.get("steps") or []]
    check("记进想要的功能" in names, f"步骤里有「记进想要的功能」：{names}")
    check(ev.get("to") == "ds" or "交给 DeepSeek" in names, f"交给了 DeepSeek（to={ev.get('to')}）")
    w = httpx.get(B + "/api/wishes", timeout=10).json()
    check(len(w) == n0 + 1 and "导出聊天记录" in w[0]["text"] and w[0]["event"] == ev["id"], "记进了「想要的功能」（/api/wishes 最新一条）")
    last = httpx.get("http://127.0.0.1:8099/__last", timeout=10).json()["chat"] or {}
    u = json.dumps(last.get("messages", [])[-1:], ensure_ascii=False)
    check("改代码" in u and "系统限制" in u, "发给 DeepSeek 的消息里带着「老实说要改代码、别说系统限制」的提示")
    ev = chat("帮我做个今天的待办清单")
    check("记进想要的功能" not in [s[0] for s in ev.get("steps") or []], "普通的「帮我做个……」不算加功能")
finally:
    put(strongOn=True, strongName="")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
