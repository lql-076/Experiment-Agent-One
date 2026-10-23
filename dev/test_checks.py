"""整备自检和一键补齐的状态（连测试后端）：
1. 14 项自检都查得完，没有"检测出错"（代码出错会显示成这样）
2. 一键补齐的 6 步按自检结果标状态：已就绪 / 自动启动中 / 要补，不会每次启动都是"等待"
3. 后台重查会自己变的几项（模型服务、Kev、硬件监控助手、QQ），写回自检结果
用法：python dev/test_checks.py（要先 dev/serve.sh start）"""
import sys

import httpx

B, H, bad = "http://127.0.0.1:8765", {"X-Agent": "1"}, []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


r = httpx.post(B + "/api/checks/run", headers=H, timeout=90).json()["res"]
errs = {k: v["d"] for k, v in r.items() if "检测出错" in (v.get("d") or "")}
check(len(r) == 14 and not errs, f"14 项都查完了，没有检测出错（{errs or len(r)}）")
check(r["kev"]["st"] in ("ok", "wait", "miss") and "第一次启动会下载" not in r["kev"]["d"], f"Kev：{r['kev']['d']}")
steps = {s["k"]: s for s in httpx.get(B + "/api/setup", timeout=10).json()["steps"]}
check(all(s["st"] in ("ready", "auto", "wait") for s in steps.values()), "没跑一键补齐时，6 步都按自检结果标了：" + "、".join(f"{k}={s['st']}" for k, s in steps.items()))
check(steps["git"]["st"] == "ready" and steps["models"]["st"] == "ready", "已经好了的（Git、模型文件）标「已就绪」")
check(steps["hwmon"]["st"] == ("ready" if r["hwmon"]["st"] == "ok" else steps["hwmon"]["st"]), f"硬件监控助手跟着自检结果：{steps['hwmon']['st']} / {r['hwmon']['d']}")
print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
