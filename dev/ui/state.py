"""v3.5.1 主题首帧 / hydration lock / UI 状态持久化的浏览器回归。
用法：python dev/ui/state.py（先起后端）
不截图、不移动真实窗口；跑完会把主题恢复成跑之前那套。"""
import sys

from common import launch
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/"
bad, errs = [], []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1440, "height": 880})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(URL)
    p.wait_for_function("typeof S !== 'undefined' && S.view", timeout=15000)
    p.wait_for_function("typeof HYDRATED !== 'undefined' && HYDRATED", timeout=15000)
    before = p.evaluate("S.set.theme")
    target = "light" if before == "dark" else "dark"

    # 主题：第一帧脚本 + localStorage + 后端三处一致
    p.evaluate(f"setTheme('{target}', 10, 10)")
    p.wait_for_timeout(900)
    state = p.evaluate("[document.documentElement.dataset.theme, localStorage.getItem('agent_theme'), S.set.theme]")
    check(state == [target, target, target], f"切主题：<html>/agent_theme/S.set 都是 {target}（{state}）")
    backend_theme = p.evaluate("fetch('/api/settings', {cache: 'no-store'}).then(r => r.json()).then(j => j.settings.theme)")
    check(backend_theme == target, f"主题已写进 settings.json（{backend_theme}）")

    # UI 状态：前端 localStorage + 后端 uiState 增量
    p.evaluate("saveUI({monitorTab: '@trace', chatForce: 'ds', imgRatio: '16:9', docsMode: 'text'})")
    p.wait_for_timeout(1300)
    ui = p.evaluate("fetch('/api/settings', {cache: 'no-store'}).then(r => r.json()).then(j => j.settings.uiState || {})")
    check(ui.get("monitorTab") == "@trace" and ui.get("chatForce") == "ds" and ui.get("imgRatio") == "16:9",
          f"uiState 已增量落盘（{ui}）")
    check(p.evaluate("U.monitorTab === '@trace' && U.chatForce === 'ds'"), "localStorage 的 U 同步更新")

    # 刷新后仍是浅色/深色，不靠默认值猜
    p.reload(wait_until="domcontentloaded")
    p.wait_for_timeout(1200)
    check(p.evaluate("document.documentElement.dataset.theme") == target, "刷新后第一帧仍是刚才选的主题")
    check(p.evaluate("typeof U !== 'undefined' && U.monitorTab === '@trace'"), "刷新后 UI 状态仍是刚才的筛选")

    # hydration lock：GET /api/settings 延迟时，先切主题不能发 PUT
    p2 = b.new_page(viewport={"width": 1200, "height": 800})
    p2.on("pageerror", lambda e: errs.append("hydration: " + str(e)))
    p2.add_init_script("""(() => {
      const orig = window.fetch;
      window.fetch = function (input, init) {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const m = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        if (m === 'GET' && url.indexOf('/api/settings') >= 0) {
          // 把 fetchT 的 4 秒 AbortSignal 去掉：测试要控制它什么时候放行，不能被超时提前打断
          const clean = Object.assign({}, init || {});
          delete clean.signal;
          return new Promise(res => { window.__releaseSettings = () => res(orig.call(window, input, clean)); });
        }
        return orig.apply(window, arguments);
      };
    })();""")
    puts = []
    p2.on("request", lambda r: puts.append(r.url) if r.method == "PUT" and "/api/settings" in r.url else None)
    p2.goto(URL, wait_until="domcontentloaded")
    p2.wait_for_function("typeof LIVE !== 'undefined' && LIVE === true && typeof __releaseSettings === 'function' && typeof HYDRATED !== 'undefined' && HYDRATED === false", timeout=8000)
    p2.evaluate(f"setTheme('{'dark' if target == 'light' else 'light'}', 10, 10)")
    p2.wait_for_timeout(700)
    check(len(puts) == 0, f"首次 GET 成功前切主题不发 PUT（实际 {len(puts)} 次）")
    p2.evaluate("__releaseSettings()")
    p2.wait_for_function("typeof HYDRATED !== 'undefined' && HYDRATED === true", timeout=10000)
    p2.wait_for_timeout(900)
    check(len(puts) >= 1, f"hydration 完成后把排队的改动写回后端（实际 {len(puts)} 次）")
    p2.close()

    # 恢复主题，免得测试把作者真实界面留在另一套
    p.evaluate(f"setTheme('{before}', 10, 10)")
    p.wait_for_timeout(700)
    p.close()
    b.close()

print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
