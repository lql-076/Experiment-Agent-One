"""生图页「渲染舱」点一遍（v1.8.16；连测试后端，API易 是假的 dev/fake_apiyi.py，假 Key sk-test-0000）：
批量：空着时有拖放区 → 粘贴一份清单 → 一行一张 → 点一行改比例、透明背景、提示词（存到后端）→ 换画质、档位 →
批量生成（中间的核心在转、当前这行亮、右上角变「停下」）→ 出好的图落进右边格子 → 点开看大图、Esc 关 →
单张：写提示词、选比例和张数、放一张参考图 → 生成（带参考图走 /v1/images/edits）→ 存为模板 → 模板页套用 →
换模型（按厂商分好的列表、刷新列表、换成 Seedream 再换回来）→ 历史页「再来一张」→ 三套风格、竖屏截图 → 清掉。
用法：python dev/ui/img.py 截图文件夹（要先 dev/serve.sh start）"""
import pathlib
import shutil
import sys

import httpx
from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RUN = ROOT / "dev" / ".run"
sys.path.insert(0, str(ROOT / "dev"))
from fake_apiyi import png  # noqa: E402

errs, bad = [], []
LIST = """# 界面测试 · 生图清单

## 这期的视觉方向
深夜地铁导视风：深蓝近黑的底，荧光黄和青色的细线条，扁平的等距插画。

### img01_重点_地铁站.png（用在：本周重点）
- 比例：16:9
- 透明背景：不开
- 提示词：等距视角的深夜地铁站台，荧光黄的导视线条，扁平插画。

### img02_道具_灶台.png（用在：五个灶台）
- 比例：1:1
- 透明背景：开
- 提示词：一个独立的小灶台，等距视角，扁平插画。

### img03_第五名_图谱.png（用在：第五名）
- 比例：21:9
- 透明背景：不开
- 提示词：一张发光的关系图谱，深蓝近黑背景。
"""


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


def get(p, path):
    return p.evaluate(f"api('GET', '{path}')")


with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1680, "height": 1000})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/")
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    shutil.rmtree(RUN / "生图输出-界面测试", ignore_errors=True)               # 上一次界面测试出的图清掉（只在 dev/.run 里）
    for fl in ("slow", "quota", "opaque"):
        (RUN / f"fake_img_{fl}.flag").unlink(missing_ok=True)
    p.evaluate("api('PUT', '/api/settings', {imgOut: 'dev/.run/生图输出-界面测试', imgQuality: 'high', imgRes: '2k', imgModel: 'gpt-image-2.5-sunburst-vip', imgConc: 1})")
    p.evaluate("api('POST', '/api/img/clear', {})")
    for t in get(p, "/api/img")["templates"]:
        p.evaluate(f"api('DELETE', '/api/img/templates/{t['id']}')")
    p.wait_for_timeout(400)
    p.evaluate("IMG.tab = 'batch'; IMG.st = null")
    p.click('.nav[data-view="img"]')
    p.wait_for_selector("#fg #fgFx")
    check(p.locator(".fg-boot").count() == 1, "第一次进生图页：开机那一秒多（LINK、MODEL、OUTPUT……）")
    p.wait_for_function("!document.querySelector('.fg-boot')", timeout=6000)
    check("把生图清单拖进来" in p.inner_text("#fgQl") and "选清单" in p.inner_text("#fgGo") and p.evaluate("FG.raf > 0"),
          "批量：还没清单时左边是拖放区，右上角是「选清单」；中间的核心在转")
    check("Sunburst VIP" in p.inner_text("#fgMdl") and "$0.03/张" in p.inner_text("#fgMdl") and "推荐" in p.inner_text("#fgMdl"),
          "右上角那块写着当前模型：Sunburst VIP、按次 $0.03/张、推荐")
    p.click('#fgQl [data-act="paste"]')
    p.wait_for_selector("#fgPaste")
    p.fill("#fgPaste", LIST)
    p.click('#fgBox [data-act="pasteok"]')
    p.wait_for_function("document.querySelectorAll('#fgQl .fg-r').length === 3", timeout=8000)
    rows = p.locator("#fgQl .fg-r")
    check(p.locator("#fgBox").count() == 0 and "img02_道具_灶台.png" in rows.nth(1).inner_text() and "透明" in rows.nth(1).inner_text() and "3 张" in p.inner_text("#fgQc"),
          "粘贴清单：认出 3 张，一行一张（文件名、比例、透明背景）")
    check("批量生成" in p.inner_text("#fgGo") and "$0.09" in p.inner_text("#fgGo") and "认出 3 张" in p.inner_text("#fgFn"),
          "右上角变成「批量生成 · 3 张 · 约 $0.09」；中间写着认出几张")
    rows.nth(2).click()
    p.wait_for_selector("#fgEdPr")
    p.select_option("#fgEdR", "16:9")
    p.click("#fgEdT")
    p.fill("#fgEdPr", "一张发光的关系图谱，深蓝近黑背景，改过。")
    p.wait_for_timeout(1300)
    it3 = get(p, "/api/img")["board"]["items"][2]
    check(it3["ratio"] == "16:9" and it3["transparent"] and it3["prompt"].endswith("改过。") and it3["edited"] and "改过" in rows.nth(2).inner_text(),
          "点一行：下面展开能改比例、透明背景、提示词，存到后端，行上标「改过」")
    p.click('#fgPar [data-q="medium"]')
    p.wait_for_timeout(700)
    p.click('#fgPar [data-tier="1k"]')
    p.wait_for_timeout(700)
    st = get(p, "/api/settings")["settings"]
    check(st["imgQuality"] == "medium" and st["imgRes"] == "1k" and p.get_attribute('#fgPar [data-tier="1k"]', "aria-pressed") == "true",
          "上面一排换画质、档位：存进设置")
    p.click('#fgPar [data-q="high"]')
    p.wait_for_timeout(500)
    p.click('#fgPar [data-tier="2k"]')
    p.wait_for_timeout(700)
    (RUN / "fake_img_slow.flag").write_text("2")
    p.click("#fgGo")
    p.wait_for_function("document.querySelector('#fgQl .fg-r.run') && FG.A", timeout=8000)
    p.wait_for_timeout(800)
    check("停下" in p.inner_text("#fgGo") and "RENDER CORE · 01" in p.inner_text("#fgLab") and "img01_重点_地铁站.png" in p.inner_text("#fgFn"),
          "点「批量生成」：当前这行亮、核心写着 01 / 03 和文件名、右上角变「停下」")
    p.screenshot(path=f"{OUT}/img-run.png")
    p.wait_for_function("IMG.st.job && IMG.st.job.st === 'done' && !FG.RV.length", timeout=40000)
    (RUN / "fake_img_slow.flag").unlink()
    p.wait_for_function("document.querySelectorAll('#fgOg .fg-tile img').length === 3 && [].every.call(document.querySelectorAll('#fgOg .fg-tile img'), function(i){return i.complete && i.naturalWidth > 0})", timeout=10000)
    check(p.locator("#fgOg .fg-tile.wait").count() == 0 and p.inner_text("#kD") == "03" and p.inner_text("#kS") == "$0.09" and "全部出好了" in p.inner_text("#fgGo"),
          "都出好了：3 张图落进右边格子，上面写着已出 03、已花 $0.09，右上角变「全部出好了」")
    check(p.locator("#fgOg .fg-tile.t").count() == 2 and "出完了" in p.inner_text("#fgFn") and "好了" in p.inner_text("#fgLog"), "透明的两张垫棋盘格；中间和日志写着出完了")
    p.click('#fgOg .fg-tile[data-k="i2"]')
    p.wait_for_selector("#fgBox .fg-big img")
    p.wait_for_function("document.querySelector('#fgBox .fg-big img').naturalWidth === 2048", timeout=5000)
    check("img02_道具_灶台.png" in p.inner_text("#fgBox") and p.locator("#fgBox .fg-big.t").count() == 1 and "2048×2048" in p.inner_text("#fgBox"),
          "点图：看大图（透明的垫棋盘格），写着尺寸、模型、花费、提示词")
    p.screenshot(path=f"{OUT}/img-box.png")
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)
    check(p.locator("#fgBox").count() == 0, "Esc 关掉大图")

    # 单张：带一张参考图
    ref = RUN / "界面测试_参考图.png"
    ref.write_bytes(png(320, 240, False, 33))
    p.click('.fg-tab[data-tab="single"]')
    p.wait_for_selector("#fgPrompt")
    p.fill("#fgPrompt", "一只发光的水母漂在深蓝的海里")
    p.click('#fgChips [data-ratio="3:4"]')
    p.click('#fgCnt [data-cnt="2"]')
    p.set_input_files("#fgImgs", str(ref))
    p.wait_for_function("document.querySelectorAll('#fgRefs .fg-ref img').length === 1", timeout=5000)
    check(p.inner_text("#fgRn") == "1 / 8" and "1536×2048" in p.inner_text("#fgSz") and "2 张" in p.inner_text("#fgGo") and "$0.06" in p.inner_text("#fgGo"),
          "单张：放了 1 张参考图（最多 8 张），3:4 是 1536×2048，2 张约 $0.06")
    p.click("#fgGo")
    p.wait_for_function("IMG.st.job && IMG.st.job.kind === 'single' && IMG.st.job.st === 'done' && !FG.RV.length", timeout=40000)
    fk = httpx.get("http://127.0.0.1:8096/_fake/img/log").json()["items"][-1]
    check(fk["path"] == "edits" and fk["refs"] == 1 and fk["body"]["size"] == "1536x2048" and fk["body"]["prompt"].startswith("一只发光的水母"),
          "带参考图生成：走 /v1/images/edits，参考图和提示词一起发过去")
    check(p.locator('#fgOg .fg-tile[data-act="viewh"]').count() >= 2 and p.inner_text("#kD") == "02", "出好的 2 张落进右边（最近出的在最前面）")

    # 存为模板 → 模板页套用
    p.click('[data-act="tplsave"]')
    p.wait_for_selector("#fgTn")
    p.fill("#fgTn", "界面测试模板")
    p.click('#fgBox [data-act="tplok"]')
    p.wait_for_function("IMG.st.templates.length === 1", timeout=5000)
    p.fill("#fgPrompt", "")
    p.evaluate("IMG.prompt=''; IMG.refs=[]")
    p.click('.fg-tab[data-tab="tpl"]')
    p.wait_for_selector("#fgTg .fg-tc")
    check("界面测试模板" in p.inner_text("#fgTg") and p.locator("#fgTg .fg-tc .rf img").count() == 1, "存为模板：模板页有了，带着那张参考图")
    p.screenshot(path=f"{OUT}/img-tpl.png")
    p.click('#fgTg [data-act="tpluse"]')
    p.wait_for_function("document.querySelector('#fgPrompt') && document.querySelectorAll('#fgRefs .fg-ref img').length === 1", timeout=6000)
    check(p.input_value("#fgPrompt") == "一只发光的水母漂在深蓝的海里" and p.get_attribute('#fgChips [data-ratio="3:4"]', "aria-pressed") == "true",
          "模板页点「套用」：回到单张，提示词、比例、参考图都填好了")

    # 换模型
    p.click("#fgMdl")
    p.wait_for_selector("#fgBox .fg-mc")
    check(p.locator("#fgVd button").count() >= 4 and "推荐" in p.inner_text('#fgBox .fg-mc[aria-pressed="true"]'), "点右上角的模型：按厂商分好的列表，用着的那个标「使用中」「推荐」")
    p.click("#fgMr")
    p.wait_for_function("document.querySelector('#fgMs').textContent.indexOf('14 个') >= 0", timeout=8000)
    p.click('#fgVd [data-v="seedream"]')
    p.screenshot(path=f"{OUT}/img-models.png")
    p.click('#fgBox .fg-mc[data-id="seedream-5-0-flash-260915"]')
    p.wait_for_function("!document.querySelector('#fgBox') && IMG.st.model.id === 'seedream-5-0-flash-260915'", timeout=6000)
    check("Seedream 5.0 Flash" in p.inner_text("#fgMdl") and "固定" in p.inner_text("#fgPar") and "$0.018" in p.inner_text("#fgMdl"),
          "刷新列表（这个 Key 能用 14 个），换成 Seedream 5.0 Flash：右上角跟着变，档位写着固定")
    p.click("#fgMdl")
    p.wait_for_selector("#fgBox .fg-mc")
    p.click('#fgVd [data-v="openai"]')
    p.click('#fgBox .fg-mc[data-id="gpt-image-2.5-sunburst-vip"]')
    p.wait_for_function("!document.querySelector('#fgBox') && IMG.st.model.id === 'gpt-image-2.5-sunburst-vip'", timeout=6000)
    check(get(p, "/api/settings")["settings"]["imgModel"] == "gpt-image-2.5-sunburst-vip", "再换回 Sunburst VIP（存进设置）")

    # 历史
    p.click('.fg-tab[data-tab="hist"]')
    p.wait_for_function("document.querySelectorAll('#fgHg .fg-ht').length >= 5", timeout=6000)
    p.locator("#fgHg .fg-ht").nth(2).click()
    p.wait_for_timeout(300)
    check("MODEL" in p.inner_text("#fgHd") and p.locator('#fgHd [data-act="again"]').count() == 1, "历史：出过的每一张；点一张右边看详情（模型、尺寸、花费、提示词）")
    p.screenshot(path=f"{OUT}/img-hist.png")
    p.click('#fgHd [data-act="again"]')
    p.wait_for_selector("#fgPrompt")
    check(p.input_value("#fgPrompt") != "" and p.get_attribute('.fg-tab[data-tab="single"]', "aria-selected") == "true", "「再来一张」：回到单张，提示词、比例填好")

    for th in ("abyss", "nebula", "ember"):
        p.evaluate(f"document.documentElement.dataset.theme='{th}'; fgColors()")
        p.wait_for_timeout(400)
        p.screenshot(path=f"{OUT}/img-{th}.png")
    p.evaluate("document.documentElement.dataset.theme='abyss'; fgColors()")
    p.set_viewport_size({"width": 1080, "height": 1860})
    p.wait_for_timeout(1500)
    p.screenshot(path=f"{OUT}/img-portrait.png")
    p.set_viewport_size({"width": 1680, "height": 1000})
    p.wait_for_timeout(600)

    # 收尾：删模板（点两下）、清掉清单
    p.click('.fg-tab[data-tab="tpl"]')
    p.wait_for_selector('#fgTg [data-act="tpldel"]')
    p.click('#fgTg [data-act="tpldel"]')
    check("再点一次删除" in p.inner_text("#fgTg"), "删模板要点两下")
    p.click('#fgTg [data-act="tpldel"]')
    p.wait_for_function("IMG.st.templates.length === 0", timeout=5000)
    p.click('.fg-tab[data-tab="batch"]')
    p.wait_for_selector('#fgQb [data-act="clear"]')
    p.click('#fgQb [data-act="clear"]')
    p.wait_for_function("document.querySelector('#fgQl .fg-drop')", timeout=5000)
    check(True, "点「清掉」：回到拖放区（文件夹里的图不动）")
    ref.unlink(missing_ok=True)
    p.evaluate("api('PUT', '/api/settings', {imgOut: 'dev/.run/生图输出-测试'})")
    p.wait_for_timeout(300)
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
