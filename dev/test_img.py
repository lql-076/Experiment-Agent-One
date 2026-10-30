"""生图（v1.8.15）。沙箱连不上 API易：用假的接口（dev/fake_apiyi.py，8096）和假 Key sk-test-0000。
1. 不连后端：认清单（标题 + 列表、表格、编号列表、一行写完几种写法；没写全的给提醒）、比例 → 尺寸（都合 API 的规矩）、
   实际发出去的提示词（透明背景那句、不要文字那句、视觉方向、官逆模型写比例）、读 PNG 头、报错说人话
2. 连测试后端（dev/serve.sh start）：上传清单 → 全部生成 → 按清单的文件名存好、透明的有透明通道、尺寸对 → 发出去的只有提示词和参数 →
   清单原文和生图记录存在同一个文件夹 → 改提示词、比例、透明背景 → 重生成（旧的挪进旧版）→ 审核没过只坏那一张 → 只补没出的 →
   余额不够整批停 → 停下（正在出的出完）→ 官逆模型 → 重新上传同一份清单认得出已经出好的 → 打包 zip → 没填 Key
3. Key 不落明文、不进导出、不进日志、不进记录
用法：python dev/test_img.py（要先 dev/serve.sh start）"""
import io
import json
import pathlib
import sys
import time
import zipfile

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import imagegen as G, settings  # noqa: E402

bad = []
KEY = "sk-test-0000"
RUN = ROOT / "dev" / ".run"
FAKE = "http://127.0.0.1:8096"


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


# ---------- 1. 不连后端 ----------
A = """# GitHub AI 周榜 · 测试 3 · 生图清单

## 这期的视觉方向
深夜地铁导视风：深蓝近黑的底，荧光黄和青色的细线条，扁平的等距插画，像城市交通图。

## 清单

### img01_重点_地铁站.png（用在：本周重点 · Orca 类比开场）
- 比例：16:9
- 透明背景：不开
- 提示词：等距视角的深夜地铁站台，深蓝近黑的背景，荧光黄的导视线条沿着地面延伸，五个空的灶台整齐排开，扁平插画。

### img02_道具_灶台.png（用在：本周重点 · 五个灶台）
- **比例**：1:1
- **透明背景**：开
- **提示词**：
  一个独立的小灶台，等距视角，扁平插画，荧光黄描边，青色火焰。

### img03_第五名_图谱.png
用在：第五名 Graphify
比例：21:9 ｜ 透明背景：不开
提示词：
```
一张发光的关系图谱，节点是小圆点，连线是细的荧光黄线条，深蓝近黑背景。
```

### img04_第二名_手机.png（用在：第二名 · 手机端）
- 比例：4:5
- 透明背景：开
- 提示词：一部悬浮的手机，屏幕发着青色的光，扁平插画。
"""
p = G.parse(A, "测试3.md")
its = p["items"]
check(p["title"] == "GitHub AI 周榜 · 测试 3 · 生图清单" and p["direction"].startswith("深夜地铁导视风") and len(its) == 4 and not p["warn"],
      f"标题 + 列表的写法：认出标题、视觉方向、{len(its)} 条，没有要提醒的")
check([(x["file"], x["ratio"], x["transparent"]) for x in its] == [("img01_重点_地铁站.png", "16:9", False), ("img02_道具_灶台.png", "1:1", True),
                                                                  ("img03_第五名_图谱.png", "21:9", False), ("img04_第二名_手机.png", "4:5", True)],
      "每条的文件名、比例、透明背景开不开都对（粗体、一行写两样、代码块都认）")
check(its[0]["use"] == "本周重点 · Orca 类比开场" and its[2]["use"] == "第五名 Graphify" and its[1]["prompt"].startswith("一个独立的小灶台")
      and its[2]["prompt"].startswith("一张发光的关系图谱") and "```" not in its[2]["prompt"], "用在哪、提示词（换行写的、代码块里的）都取对了")
B = """# 测试 4 生图

**视觉方向**：暖色胶片风，颗粒感。

| 文件名 | 用在哪 | 比例 | 透明背景 | 提示词 |
| --- | --- | --- | --- | --- |
| img01_封面.png | 封面 | 16:9 | 不开 | 胶片质感的书桌，台灯暖光 |
| `img02_图标_锁.png` | 许可证 | 1:1 | 开 | 一把金属小锁，胶片质感 |
"""
p = G.parse(B)
check(p["direction"] == "暖色胶片风，颗粒感。" and [(x["file"], x["use"], x["ratio"], x["transparent"]) for x in p["items"]] ==
      [("img01_封面.png", "封面", "16:9", False), ("img02_图标_锁.png", "许可证", "1:1", True)], "表格的写法也认")
C = """生图清单（文件名统一 imgNN_xxx.png）

1. **img01_开场.png** — 开头 5 秒
   比例 16:9，透明背景：否
   提示词：一束光从左上照进来的抽象空间。
2. **img01_开场.png** — 重名了
   比例 1.5:1
   提示词：第二张。
3. img03_x.jpg 比例 7:3 提示词：宽幅的城市天际线
4. img04_空.png
   比例：3:4
   透明背景：开
"""
p = G.parse(C, "周榜.md")
f = [x["file"] for x in p["items"]]
check(p["title"] == "周榜" and f == ["img01_开场.png", "img01_开场_2.png", "img03_x.png", "img04_空.png"] and p["items"][0]["use"] == "开头 5 秒",
      f"编号列表、一行写完的也认；重名加 _2、统一 .png；开头那句提到文件名的不算一条：{f}")
w = " | ".join(p["warn"])
check(p["items"][2]["ratio"] == "21:9" and p["items"][1]["transparent"] is False and "没写透明背景" in w and "没认出提示词" in w and "改成了" in w,
      f"比例写成 7:3 认成最近的 21:9；没写全的写进提醒：{w}")
check(G.nearest(1.5) == "3:2" and G.nearest(0.56) == "9:16" and G._ratio("比例：16：9") == "16:9" and G._trans("透明背景：不开") is False and G._trans("透明：是") is True,
      "比例、透明背景的几种写法（全角冒号、是 / 否、开 / 不开）")
okz = all(w_ % 16 == 0 and h_ % 16 == 0 and max(w_, h_) <= 3840 and max(w_, h_) / min(w_, h_) <= 3 and 655360 <= w_ * h_ <= 8294400
          and abs((w_ / h_) / (int(r.split(":")[0]) / int(r.split(":")[1])) - 1) < 0.02 for res in G.SIZES.values() for r, (w_, h_) in res.items())
check(okz and set(G.SIZES["2k"]) == set(G.SIZES["1k"]) == set(G.RATIOS) and len(G.RATIOS) == 10 and G.SIZES["2k"]["16:9"] == (2048, 1152),
      "10 种比例换成的尺寸都合 API 的规矩（16 的倍数、长边 ≤3840、比例 ≤3:1、0.65~8.3 百万像素），16:9 是推荐的 2048×1152")
it = {"prompt": "一个小灶台。", "ratio": "1:1", "transparent": True}
s1 = G.build_prompt(it, "深夜地铁风", with_dir=False, no_text=True)
s2 = G.build_prompt(dict(it, transparent=False, ratio="9:16"), "深夜地铁风", with_dir=True, no_text=False, kind="reverse")
check(s1.startswith("一个小灶台。") and G.TRANS_TAIL in s1 and G.NOTEXT_TAIL in s1 and "深夜地铁风" not in s1,
      "发出去的提示词：这一条 + 「只画主体、背景透明」+「不要文字」；视觉方向默认不拼（每条里已经写了画风）")
check(s2.startswith("画面比例 9:16（竖版）") and "统一画风：深夜地铁风" in s2 and G.TRANS_TAIL not in s2 and G.NOTEXT_TAIL not in s2,
      "官逆模型把比例写在最前面；打开「拼进每条」才带视觉方向")
check(abs(G.est_usd({"ratio": "16:9"}, "gpt-image-2.5-flare", "medium", "2k") - 0.0291) < 0.002 and G.est_usd({"ratio": "16:9"}, "gpt-image-2.5-all") == 0.025,
      f"预估花费：Flare 标准 2K 一张约 ${G.est_usd({'ratio': '16:9'}, 'gpt-image-2.5-flare', 'medium', '2k'):.3f}，All 按次 $0.025")
e1, e2, e3 = G.explain(401, '{"error":{"message":"Invalid API key sk-test-0000"}}', KEY), G.explain(403, '{"error":{"message":"safety system"}}'), G.explain(429, "{}")
check(e1.fatal and "Key 不对" in str(e1) and KEY not in str(e1) and not e2.fatal and "审核没过" in str(e2) and e3.fatal and "限流" in str(e3),
      "报错说人话：Key 不对、限流整批停；审核没过只坏这一张；报错里的 Key 换成 ***")
check("imgKey" in settings.SECRET_KEYS and "imgKey" not in settings.DEFAULTS, "API易 Key 是密钥（DPAPI 加密存 data/secrets.bin），不在普通设置里")
gi, pk = (ROOT / ".gitignore").read_text("utf-8"), (ROOT / "dev" / "pack.py").read_text("utf-8")
check("生图输出/" in gi and '"生图输出/"' in pk, "「生图输出」不进仓库、不进压缩包")

# ---------- 2. 连测试后端 ----------
B_ = "http://127.0.0.1:8765"
c = httpx.Client(base_url=B_, headers={"X-Agent": "1"}, timeout=30)
OUT = RUN / "生图输出-测试"
import shutil  # noqa: E402
shutil.rmtree(OUT, ignore_errors=True)
c.put("/api/settings", json={"imgOut": str(OUT), "imgModel": "gpt-image-2.5-flare", "imgQuality": "medium", "imgRes": "2k", "imgConc": 3,
                             "imgNoText": True, "imgWithDir": False})
for fl in ("slow", "quota", "opaque"):
    (RUN / f"fake_img_{fl}.flag").unlink(missing_ok=True)
httpx.post(FAKE + "/_fake/img/clear")


def wait(t=40):
    t0 = time.time()
    while time.time() - t0 < t:
        j = c.get("/api/img").json()
        if j["job"] and j["job"]["st"] != "run":
            return j
        time.sleep(0.3)
    return c.get("/api/img").json()


def flog(k=30):
    return httpx.get(FAKE + "/_fake/img/log").json()["items"][-k:]


c.post("/api/img/clear")
j = c.get("/api/img").json()
check(j["board"] is None and len(j["models"]) == 3 and j["cfg"]["key"] and j["cfg"]["hint"] == "••••0000" and j["cfg"]["model"] == "gpt-image-2.5-flare",
      "生图页拿得到状态：还没有清单、3 个模型、Key 只看得到最后 4 位")
r = c.post("/api/img/run", json={})
check(r.status_code == 400 and "清单" in r.json()["detail"], "没上传清单就点生成：说先上传清单")
r = c.post("/api/img/load", json={"md": "# 随便写的\n\n没有图。", "name": "x.md"})
check(r.status_code == 400 and "文件名" in r.json()["detail"], f"传了不是清单的东西：说清楚清单里要有什么（{r.json()['detail'][:30]}…）")
j = c.post("/api/img/load", json={"md": A, "name": "测试3_生图清单.md"}).json()
b = j["board"]
d = OUT / f"{time.strftime('%Y-%m-%d')}_GitHub AI 周榜 · 测试 3"
check(len(b["items"]) == 4 and all(x["st"] == "idle" for x in b["items"]) and b["dir"].replace("\\", "/").endswith(d.name) and not d.exists(),
      f"上传清单：4 张，文件夹名带日期和清单名（{d.name}），出图前不建空文件夹")
r = c.post("/api/img/run", json={})
check(r.status_code == 200 and r.json()["job"]["n"] == 4 and r.json()["job"]["est"] > 0.08, f"全部生成：4 张，预估约 ${r.json()['job']['est']:.2f}")
check(c.post("/api/img/run", json={}).status_code == 409, "出图中再点：不让（409）")
j = wait()
items = {x["file"]: x for x in j["board"]["items"]}
check(j["job"]["st"] == "done" and j["job"]["done"] == 4 and all(x["st"] == "ok" for x in items.values()), "好了：" + j["job"]["msg"])
files = sorted(x.name for x in d.iterdir())
check(files == sorted(["img01_重点_地铁站.png", "img02_道具_灶台.png", "img03_第五名_图谱.png", "img04_第二名_手机.png", "生图清单.md", "生图记录.json"]),
      f"按清单里的文件名存好，清单原文、生图记录在同一个文件夹：{files}")
info = {n: G.png_info((d / n).read_bytes()) for n in files if n.endswith(".png")}
check((info["img01_重点_地铁站.png"]["w"], info["img01_重点_地铁站.png"]["h"]) == (2048, 1152) and (info["img03_第五名_图谱.png"]["w"], info["img03_第五名_图谱.png"]["h"]) == (2240, 960)
      and (info["img04_第二名_手机.png"]["w"], info["img04_第二名_手机.png"]["h"]) == (1280, 1600), "尺寸按比例来：16:9 是 2048×1152、21:9 是 2240×960、4:5 是 1280×1600")
check(info["img02_道具_灶台.png"]["alpha"] and info["img04_第二名_手机.png"]["alpha"] and not info["img01_重点_地铁站.png"]["alpha"] and items["img02_道具_灶台.png"]["alpha"],
      "透明背景开的两张有透明通道，不开的没有")
lg = flog(4)
bodies = {x["body"]["prompt"].split("\n")[0][:6]: x["body"] for x in lg}
tb = next(x["body"] for x in lg if "小灶台" in x["body"]["prompt"])
ob = next(x["body"] for x in lg if "地铁站台" in x["body"]["prompt"])
check(all(x["auth_ok"] for x in lg) and len(lg) == 4 and set(tb) == {"model", "prompt", "size", "quality", "output_format", "n", "background"}
      and tb["background"] == "transparent" and tb["size"] == "1536x1536" and tb["output_format"] == "png" and ob["background"] == "opaque" and ob["quality"] == "medium",
      "发给 API易 的只有模型、提示词、尺寸、画质、PNG、透明背景开不开；Key 带对了")
check(G.TRANS_TAIL in tb["prompt"] and G.NOTEXT_TAIL in tb["prompt"] and G.TRANS_TAIL not in ob["prompt"] and "深夜地铁导视风" not in ob["prompt"],
      "透明的那张后面加了「只画主体、背景透明」，每张都加了「不要文字」，视觉方向没拼")
rec = json.loads((d / "生图记录.json").read_text("utf-8"))
check(list(rec["images"]) == [x["file"] for x in b["items"]] and rec["images"]["img02_道具_灶台.png"]["prompt_sent"] == tb["prompt"]
      and rec["images"]["img02_道具_灶台.png"]["size"] == "1536x1536" and rec["direction"].startswith("深夜地铁") and (d / "生图清单.md").read_text("utf-8") == A,
      "生图记录.json：每张实际发出去的提示词、尺寸、模型、花费，按清单的顺序；清单原文存了一份")
v1 = items["img01_重点_地铁站.png"]["ver"]
fr = c.get("/api/img/file/1?v=1")
check(fr.status_code == 200 and fr.content[:8] == b"\x89PNG\r\n\x1a\n" and c.get("/api/img/file/99").status_code == 404, "页面拿得到出好的图（缩略图、看大图）")

# 改提示词、比例、透明背景 → 重生成：旧的挪进旧版
r = c.patch("/api/img/item/1", json={"prompt": "改过的：等距视角的地铁站台，清晨。", "ratio": "3:2", "transparent": True})
check(r.status_code == 200 and r.json()["item"]["edited"] and r.json()["item"]["ratio"] == "3:2", "改提示词、比例、透明背景：记下「改过」")
check(c.patch("/api/img/item/1", json={"ratio": "7:3"}).status_code == 400, "比例只能是那 10 种")
c.put("/api/settings", json={"imgWithDir": True, "imgNoText": False})
c.post("/api/img/run", json={"ids": ["1"]})
j = wait()
x1 = next(x for x in j["board"]["items"] if x["id"] == "1")
last = flog(1)[0]["body"]
old = list((d / "旧版").iterdir())
check(j["job"]["n"] == 1 and x1["st"] == "ok" and x1["ver"] != v1 and (x1["w"], x1["h"]) == (1920, 1280) and x1["alpha"] and last["size"] == "1920x1280"
      and last["background"] == "transparent" and last["prompt"].startswith("这一组图的统一画风：深夜地铁导视风") and "改过的" in last["prompt"] and G.NOTEXT_TAIL not in last["prompt"],
      "重生成一张：用改过的提示词、比例、透明背景；打开「拼进每条」带上视觉方向，关掉「不要文字」就不加")
check(len(old) == 1 and old[0].name.startswith("img01_重点_地铁站_") and (d / "img01_重点_地铁站.png").exists(), f"旧的那张挪进「旧版」，没删：{old[0].name if old else '没有'}")
c.put("/api/settings", json={"imgWithDir": False, "imgNoText": True})

# 审核没过：只坏那一张；只补没出的
c.patch("/api/img/item/3", json={"prompt": "【拦截】这条会被审核拦下"})
c.post("/api/img/run", json={"ids": ["2", "3"]})
j = wait()
x2, x3 = (next(x for x in j["board"]["items"] if x["id"] == k) for k in ("2", "3"))
check(x2["st"] == "ok" and x3["st"] == "err" and "审核没过" in x3["err"] and j["job"]["fail"] == 1 and j["job"]["done"] == 1, f"审核没过：只坏这一张，写清楚（{x3['err'][:24]}…）")
n0 = len(flog(100))
c.patch("/api/img/item/3", json={"prompt": "一张发光的关系图谱，深蓝背景。"})
c.post("/api/img/run", json={"missing": True})
j = wait()
check(len(flog(100)) == n0 + 1 and all(x["st"] == "ok" for x in j["board"]["items"]), "「只补没出的」：只出没出好的那一张")
r = c.post("/api/img/run", json={"missing": True})
check(r.status_code == 400 and "都出好了" in r.json()["detail"], "都出好了再点「只补没出的」：说都出好了")

# 余额不够：整批停
(RUN / "fake_img_quota.flag").write_text("1")
c.put("/api/settings", json={"imgConc": 1})
c.post("/api/img/run", json={})
j = wait()
(RUN / "fake_img_quota.flag").unlink()
sts = [x["st"] for x in j["board"]["items"]]
check(j["job"]["st"] == "stop" and j["job"]["fail"] == 1 and sts.count("err") == 1 and "余额不够" in j["job"]["msg"] and "err" not in sts[1:],
      f"余额不够 / 被限流：第一张报错后整批停下，后面的不再白发：{j['job']['msg'][:40]}…")
# 停下：正在出的出完，没开始的不出
(RUN / "fake_img_slow.flag").write_text("1")
n0 = len(flog(100))
c.post("/api/img/run", json={})
time.sleep(0.6)
r = c.post("/api/img/stop").json()
j = wait(30)
(RUN / "fake_img_slow.flag").unlink()
check(j["job"]["st"] == "stop" and j["job"]["done"] == 1 and len(flog(100)) == n0 + 1 and sum(x["st"] == "ok" for x in j["board"]["items"]) == 4,
      "点「停下」：正在出的那张出完（断开的话照样计费、图却丢了），没开始的不出；之前出好的还在")
c.put("/api/settings", json={"imgConc": 3})

# 要透明却没透明：标出来
(RUN / "fake_img_opaque.flag").write_text("1")
c.post("/api/img/run", json={"ids": ["2"]})
j = wait()
(RUN / "fake_img_opaque.flag").unlink()
x2 = next(x for x in j["board"]["items"] if x["id"] == "2")
check(x2["st"] == "ok" and not x2["alpha"] and "没有透明通道" in x2["warn"], "要透明背景但出来的没透明：卡片上提醒重生成")

# 官逆模型：不发 size、quality，比例写进提示词，b64 带前缀也认
c.put("/api/settings", json={"imgModel": "gpt-image-2.5-all"})
c.post("/api/img/run", json={"ids": ["4"]})
j = wait()
last = flog(1)[0]["body"]
x4 = next(x for x in j["board"]["items"] if x["id"] == "4")
check(set(last) == {"model", "prompt", "response_format"} and last["prompt"].startswith("画面比例 4:5（竖版）") and x4["st"] == "ok" and x4["usd"] == 0.025
      and "不是 4:5" in x4["warn"], "官逆模型（All）：不发尺寸、画质，比例写进提示词；按次 $0.025；出来的比例不对就提醒")
c.put("/api/settings", json={"imgModel": "gpt-image-2.5-flare"})

# 重新上传同一份清单：文件夹里已经有的算出好了
j = c.post("/api/img/load", json={"md": A, "name": "测试3_生图清单.md"}).json()
check(all(x["st"] == "ok" and x["old"] for x in j["board"]["items"]), "重新上传同一份清单：文件夹里已经有的认出来（算出好了，不用再花钱）")

# 打包 zip：只打图，不含旧版
r = c.post("/api/img/zip").json()
zp = OUT / r["zip"].replace("\\", "/").split("/")[-1]
names = sorted(zipfile.ZipFile(io.BytesIO(zp.read_bytes())).namelist())
check(r["n"] == 4 and names == sorted(["img01_重点_地铁站.png", "img02_道具_灶台.png", "img03_第五名_图谱.png", "img04_第二名_手机.png"]),
      f"打包 zip：4 张图，按清单的文件名，不含旧版、记录（{zp.name}）")
r2 = c.post("/api/img/zip").json()
check(r2["zip"] != r["zip"] and zp.exists(), "再打一次包：换个名字，上一个不覆盖")

# 没填 Key
c.put("/api/secrets", json={"k": "imgKey", "v": ""})
r = c.post("/api/img/run", json={})
c.put("/api/secrets", json={"k": "imgKey", "v": KEY})
check(r.status_code == 400 and "Key" in r.json()["detail"], f"没填 API易 Key：说去哪填（{r.json()['detail']}）")
c.put("/api/secrets", json={"k": "imgKey", "v": "sk-wrong-1234"})
c.post("/api/img/run", json={"ids": ["1"]})
j = wait()
c.put("/api/secrets", json={"k": "imgKey", "v": KEY})
x1 = next(x for x in j["board"]["items"] if x["id"] == "1")
check(x1["st"] == "err" and "Key 不对" in x1["err"] and "sk-wrong" not in json.dumps(j, ensure_ascii=False), "Key 不对：说清楚去哪重填，不把 Key 显示出来")

# ---------- 3. Key 不外泄 ----------
ex = c.get("/api/export").text
check(KEY not in ex and "imgKey" not in ex, "导出设置里没有 API易 Key")
leak = []
for p_ in [ROOT / "data" / "settings.json", ROOT / "data" / "img" / "board.json", RUN / "backend.log", *(ROOT / "data" / "logs").glob("*.log"), *OUT.rglob("*.*")]:
    try:
        if p_.is_file() and (KEY.encode() in p_.read_bytes() or b"sk-wrong" in p_.read_bytes()):
            leak.append(p_.name)
    except OSError:
        pass
check(not leak, f"设置、清单状态、日志、生图记录、出的图里都没有 Key{'：' + str(leak) if leak else ''}")
fd = " | ".join(e["text"] for e in c.get("/api/feed?n=200").json()["items"])
check(KEY not in fd and "sk-wrong" not in fd and "开始生图" in fd, "进展报告里写了生图的事，没有 Key")
c.post("/api/img/clear")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
