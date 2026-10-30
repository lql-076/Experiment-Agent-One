"""生图页点一遍（连测试后端，API易 是假的 dev/fake_apiyi.py，假 Key sk-test-0000）：
空着时有拖放区 → 粘贴一份清单 → 五个节点（清单、视觉方向、模型、出图、输出）和一格一张图 → 改比例、透明背景、提示词（存到后端）→
换画质 → 全部生成（线上在流、卡片显示出图中）→ 出好的图显示出来（透明的垫棋盘格）→ 点开看大图、Esc 关 → 选文件换一份清单 →
横竖屏 × 三套风格截图 → 清掉。
用法：python dev/ui/img.py 截图文件夹（要先 dev/serve.sh start）"""
import pathlib
import shutil
import sys

from playwright.sync_api import sync_playwright

from common import launch

OUT = sys.argv[1] if len(sys.argv) > 1 else "dev/.run/shots"
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RUN = ROOT / "dev" / ".run"
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


with sync_playwright() as pw:
    b = launch(pw)
    p = b.new_page(viewport={"width": 1680, "height": 1000})
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/")
    p.wait_for_timeout(1500)
    p.wait_for_function("!S.checking", timeout=30000)
    p.evaluate("var b=document.getElementById('boot'); if (b.classList.contains('on')) b.click()")
    shutil.rmtree(RUN / "生图输出-界面测试", ignore_errors=True)               # 上一次界面测试出的图清掉（只在 dev/.run 里）
    p.evaluate("api('PUT', '/api/settings', {imgOut: 'dev/.run/生图输出-界面测试', imgQuality: 'medium', imgRes: '2k', imgModel: 'gpt-image-2.5-flare', imgConc: 3})")
    p.evaluate("api('POST', '/api/img/clear', {})")
    p.wait_for_timeout(400)
    p.click('.nav[data-view="img"]')
    p.wait_for_selector("#igFlow .ig-node")
    check(p.locator("#igFlow .ig-node").count() == 5 and p.locator("#igFlow .ig-link").count() == 4 and "把生图清单拖到这里" in p.inner_text("#igGrid"),
          "生图页：五个节点连成一条线；还没清单时下面是拖放区")
    check(p.is_disabled('[data-act="run"]'), "没清单时「全部生成」点不了")
    p.click('#igFlow [data-act="paste"]')
    p.wait_for_selector("#igPaste")
    p.fill("#igPaste", LIST)
    p.click('[data-act="pasteok"]')
    p.wait_for_function("document.querySelectorAll('#igGrid .ig-card').length === 3", timeout=8000)
    check(p.locator("#igBox").count() == 0 and "深夜地铁导视风" in p.inner_text("#igFlow .n-dir") and "3" in p.inner_text("#igFlow .n-src .ig-kpi"),
          "粘贴清单：认出 3 张，视觉方向显示在第二个节点里")
    c2 = p.locator('.ig-card[data-id="2"]')
    check("img02_道具_灶台.png" in c2.inner_text() and c2.locator(".ig-pv.t-on").count() == 1 and c2.locator(".ig-ratio").input_value() == "1:1",
          "每张一格：文件名、比例；透明背景开的那张预览垫棋盘格")
    p.locator('.ig-card[data-id="3"] .ig-ratio').select_option("16:9")
    p.click('.ig-card[data-id="3"] .ig-tp')
    p.fill('.ig-card[data-id="3"] .ig-pr', "一张发光的关系图谱，深蓝近黑背景，改过。")
    p.wait_for_timeout(1200)
    it3 = p.evaluate("api('GET','/api/img').then(function(j){return j.board.items[2]})")
    check(it3["ratio"] == "16:9" and it3["transparent"] and it3["prompt"].endswith("改过。") and it3["edited"], "改比例、透明背景、提示词：存到后端，记下「改过」")
    p.click('#igFlow [data-q="low"]')
    p.wait_for_timeout(600)
    check(p.evaluate("api('GET','/api/settings').then(function(j){return j.settings.imgQuality})") == "low"
          and p.get_attribute('#igFlow [data-q="low"]', "aria-pressed") == "true", "模型节点里点「草稿」：画质存进设置")
    p.click('#igFlow [data-q="medium"]')
    (RUN / "fake_img_slow.flag").write_text("1")
    p.click('#igFlow [data-act="run"]')
    p.wait_for_function("document.querySelector('#igFlow.run') && document.querySelector('.ig-card.st-run')", timeout=8000)
    check(p.locator('#igFlow [data-act="stop"]').count() == 1 and "出图中" in p.inner_text("#igFlow .n-run .ig-nh"), "点「全部生成」：线上在流、出图节点亮、卡片显示出图中、有「停下」")
    p.screenshot(path=f"{OUT}/img-run.png")
    p.wait_for_function("IMG.st.job && IMG.st.job.st === 'done'", timeout=30000)
    (RUN / "fake_img_slow.flag").unlink()
    p.wait_for_function("[].every.call(document.querySelectorAll('.ig-card .ig-pv img'), function(i){return i.complete && i.naturalWidth > 0}) && document.querySelectorAll('.ig-card .ig-pv img').length === 3", timeout=10000)
    check(p.locator(".ig-card.st-ok").count() == 3 and "3" in p.inner_text("#igFlow .n-run .ig-kpi") and "好了" in p.inner_text("#igFlow .n-run"),
          "都出好了：3 张图显示在卡片里，出图节点写着花了多少")
    check(p.locator('.ig-card[data-id="2"] .ig-tag').inner_text() == "透明 ✓" and "1536×1536" in p.inner_text('.ig-card[data-id="2"] .ig-stx'),
          "透明的那张标「透明 ✓」，下面写着尺寸、用时、花费")
    p.click('.ig-card[data-id="2"] .ig-pv')
    p.wait_for_selector("#igBox .ig-big img")
    p.wait_for_function("document.querySelector('#igBox .ig-big img').naturalWidth === 1536", timeout=5000)
    check("img02_道具_灶台.png" in p.inner_text("#igBox") and p.locator("#igBox .ig-big.t-on").count() == 1, "点图：看大图（透明的垫棋盘格），写着文件名、尺寸、提示词")
    p.screenshot(path=f"{OUT}/img-box.png")
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)
    check(p.locator("#igBox").count() == 0, "Esc 关掉大图")
    md2 = RUN / "界面测试_清单2.md"
    md2.write_text("# 第二份\n\n| 文件名 | 用在哪 | 比例 | 透明背景 | 提示词 |\n| --- | --- | --- | --- | --- |\n| img01_封面.png | 封面 | 16:9 | 不开 | 胶片质感的书桌 |\n", "utf-8")
    p.set_input_files("#igFile", str(md2))
    p.wait_for_function("document.querySelectorAll('#igGrid .ig-card').length === 1", timeout=8000)
    check("界面测试_清单2.md" in p.inner_text("#igFlow .n-src"), "「换一份」选文件：认了新的清单")
    for th in ("abyss", "nebula", "ember"):
        p.evaluate(f"document.documentElement.dataset.theme='{th}'")
        p.wait_for_timeout(300)
        p.screenshot(path=f"{OUT}/img-{th}.png")
    p.evaluate("document.documentElement.dataset.theme='abyss'")
    p.set_viewport_size({"width": 1080, "height": 1860})
    p.wait_for_timeout(1200)
    p.screenshot(path=f"{OUT}/img-portrait.png")
    p.set_viewport_size({"width": 1680, "height": 1000})
    p.click('#igFlow [data-act="clear"]')
    p.wait_for_function("document.querySelector('#igGrid.empty')", timeout=5000)
    check(True, "点 ×：清掉这份清单，回到拖放区（文件夹里的图不动）")
    p.evaluate("api('PUT', '/api/settings', {imgOut: 'dev/.run/生图输出-测试'})")
    p.wait_for_timeout(300)
    b.close()
print("JS 报错：", errs or "没有")
print("不过的：", bad or "没有")
sys.exit(1 if bad or errs else 0)
