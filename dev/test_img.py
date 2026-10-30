"""生图（v1.8.15 起；v1.8.16 重做：单张 / 批量 / 历史 / 模板，页面上换模型）。沙箱连不上 API易：用假的接口（dev/fake_apiyi.py，8096）和假 Key sk-test-0000。
1. 不连后端：认清单（标题 + 列表、表格、编号列表、一行写完几种写法；没写全的给提醒）、比例 × 1K/2K/4K → 尺寸（VIP 那 30 档）、
   实际发出去的提示词、模型说明卡（线路、价格、多久、认哪些参数；没收录的按名字猜厂商）、只挑生图模型、报错说人话、老设置迁移
2. 连测试后端（dev/serve.sh start）：模型列表（按厂商分、拉 /v1/models）→ 批量：上传清单 → 一张一张出 → 按文件名存好、尺寸、透明 →
   发出去的只有提示词和参数 → 历史记录 → 改了重生成（旧的挪进旧版）→ 审核没过只坏一张 → 补齐没出的 → 余额不够整批停 → 停下 →
   All、官转模型 → 打包 zip → 单张：文生图、带参考图（edits、multipart）→ Nano Banana、Seedream、Flux、没收录的模型 → 素材模板 → 没填 Key
3. Key 不落明文、不进导出、不进日志、不进记录、不进数据库
用法：python dev/test_img.py（要先 dev/serve.sh start）"""
import base64
import io
import json
import pathlib
import sys
import time
import zipfile

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev"))
from app import imagegen as G, settings  # noqa: E402
from fake_apiyi import png as fpng  # noqa: E402

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
check(okz and all(set(G.SIZES[t]) == set(G.RATIOS) for t in G.TIERS) and len(G.RATIOS) == 10 and G.SIZES["2k"]["16:9"] == (2048, 1152)
      and G.SIZES["4k"]["16:9"] == (3840, 2160) and G.SIZES["1k"]["21:9"] == (1280, 544), "比例 × 1K/2K/4K 是 API易 VIP 那 30 档，也都合官转的规矩（16 的倍数、长边 ≤3840、0.65~8.3 百万像素）")
it = {"prompt": "一个小灶台。", "ratio": "1:1", "transparent": True}
s1 = G.build_prompt(it, "深夜地铁风", with_dir=False, no_text=True)
s2 = G.build_prompt(dict(it, transparent=False, ratio="9:16"), "深夜地铁风", with_dir=True, no_text=False, kind="prompt")
check(s1.startswith("一个小灶台。") and G.TRANS_TAIL in s1 and G.NOTEXT_TAIL in s1 and "深夜地铁风" not in s1,
      "发出去的提示词：这一条 + 「只画主体、背景透明」+「不要文字」；视觉方向默认不拼（每条里已经写了画风）")
check(s2.startswith("画面比例 9:16（竖版）") and "统一画风：深夜地铁风" in s2 and G.TRANS_TAIL not in s2 and G.NOTEXT_TAIL not in s2,
      "不认尺寸的模型（All）把比例写在最前面；打开「拼视觉方向」才带视觉方向")
vip, sun, al = G.card("gpt-image-2.5-sunburst-vip"), G.card("gpt-image-2.5-sunburst"), G.card("gpt-image-2.5-all")
check(G.DEFAULT_MODEL == "gpt-image-2.5-sunburst-vip" and G.est_usd(vip, "16:9", "4k", "high") == 0.03 and abs(G.est_usd(sun, "16:9", "2k", "high") - 0.1186) < 0.002
      and G.est_usd(al, "1:1", "2k", "high") == 0.03, f"默认 Sunburst VIP：按次 $0.03 一张（4K 高画质也是）；官转 Sunburst 2K 高画质一张约 ${G.est_usd(sun, '16:9', '2k', 'high'):.2f}（按 token）")
check(vip["route"] == "逆向" and vip["warn"] == "当前不稳定" and vip["sec"] == 80 and vip["q"] == ["auto", "low", "medium", "high"] and sun["route"] == "官转" and sun["price"] is None
      and len(sun["q"]) == 6, "认识的模型带线路（官转 / 逆向）、按次多少钱 / 按量、大概多久、当前不稳定、认哪几档画质")
u1, u2, u3, u4 = G.card("nano-banana-9"), G.card("flux-kontext-pro"), G.card("seedream-6-0-x"), G.card("my-own-model")
check((u1["v"], u1["proto"]) == ("google", "gemini") and (u2["v"], u2["proto"]) == ("flux", "flux") and (u3["v"], u3["proto"]) == ("seedream", "seedream")
      and (u4["v"], u4["proto"]) == ("other", "openai") and not u4["known"] and u4["price"] is None, "没收录的模型：按名字猜厂商和调用方式（Google 走 generateContent、Seedream、Flux 各走各的，别的按 OpenAI）")
check(G.dims(vip, "16:9", "4k") == (3840, 2160) and G.dims(G.card("seedream-5-0-flash-260915"), "16:9", "4k") == (2048, 1152) and G.dims(G.card("flux-2-pro"), "16:9", "2k") == (1280, 720)
      and G.dims(G.card("gemini-3.1-flash-image"), "16:9", "2k") is None and G.dims(al, "16:9", "2k") is None and G.tiers_of(G.card("flux-2-pro")) == ["1k"],
      "尺寸：VIP / 官转按档位；Seedream 固定 2K 那档（它最少 92 万像素）、Flux 固定 1K 那档（最多 4MP）；Nano Banana、All 不写像素")
check(all(G.IMG_RE.search(m) for m in ("gpt-image-2.5-sunburst-vip", "gemini-3.1-flash-image", "seedream-5-0-pro-260628", "flux-2-max", "grok-imagine-image", "mai-image-2"))
      and not any(G.IMG_RE.search(m) for m in ("deepseek-v4-flash", "gpt-5.5", "claude-sonnet-5-5", "text-embedding-3-small", "tts-1", "whisper-1")),
      "拉模型列表时只挑生图模型（聊天、向量、语音模型不算）")
e1, e2, e3 = G.explain(401, '{"error":{"message":"Invalid API key sk-test-0000"}}', KEY), G.explain(403, '{"error":{"message":"safety system"}}'), G.explain(429, "{}")
check(e1.fatal and "Key 不对" in str(e1) and KEY not in str(e1) and not e2.fatal and "审核没过" in str(e2) and e3.fatal and "限流" in str(e3),
      "报错说人话：Key 不对、限流整批停；审核没过只坏这一张；报错里的 Key 换成 ***")
check("imgKey" in settings.SECRET_KEYS and "imgKey" not in settings.DEFAULTS, "API易 Key 是密钥（DPAPI 加密存 data/secrets.bin），不在普通设置里")
gi, pk = (ROOT / ".gitignore").read_text("utf-8"), (ROOT / "dev" / "pack.py").read_text("utf-8")
check("生图输出/" in gi and '"生图输出/"' in pk, "「生图输出」不进仓库、不进压缩包（参考图、模板在 data\\img 里，data 本来就不进）")

# 设置迁移（v1.8.16）：v1.8.15 默认的按量模型会多花钱，老设置换成 Sunburst VIP、高画质、2K、一张一张出；只换一次
RUN.mkdir(parents=True, exist_ok=True)
tmp, old_file, s0 = RUN / "设置迁移测试.json", settings._FILE, dict(settings.S)
tmp.write_text(json.dumps({"imgModel": "gpt-image-2.5-sunburst", "imgQuality": "max", "imgRes": "4k", "imgConc": 3, "bright": 100}), "utf-8")
settings._FILE = tmp
try:
    settings.load()
    sv = json.loads(tmp.read_text("utf-8"))
    ok1 = (settings.S["imgModel"], settings.S["imgQuality"], settings.S["imgRes"], settings.S["imgConc"], sv.get("imgMig"), sv.get("imgModel")) == \
        ("gpt-image-2.5-sunburst-vip", "high", "2k", 1, 1816, "gpt-image-2.5-sunburst-vip")
    sv["imgModel"] = "gpt-image-2.5-flare"
    tmp.write_text(json.dumps(sv), "utf-8")
    settings.load()
    ok2 = settings.S["imgModel"] == "gpt-image-2.5-flare"
finally:
    settings._FILE = old_file
    settings.S.clear()
    settings.S.update(s0)
    tmp.unlink(missing_ok=True)
check(ok1 and ok2, "老设置（官转 Sunburst、最高画质、4K、同时 3 张）升级后换成 Sunburst VIP、高、2K、一张一张出；只换一次，之后在页面上换的不会被改回去")

# ---------- 2. 连测试后端 ----------
B_ = "http://127.0.0.1:8765"
c = httpx.Client(base_url=B_, headers={"X-Agent": "1"}, timeout=30)
OUT = RUN / "生图输出-测试"
import shutil  # noqa: E402
shutil.rmtree(OUT, ignore_errors=True)
VIP = {"imgOut": str(OUT), "imgModel": "gpt-image-2.5-sunburst-vip", "imgQuality": "high", "imgRes": "2k", "imgConc": 1, "imgNoText": True, "imgWithDir": False}
c.put("/api/settings", json=VIP)
for fl in ("slow", "quota", "opaque"):
    (RUN / f"fake_img_{fl}.flag").unlink(missing_ok=True)
httpx.post(FAKE + "/_fake/img/clear")
for t_ in c.get("/api/img").json()["templates"]:
    c.delete(f"/api/img/templates/{t_['id']}")
from app import db  # noqa: E402
db.run("DELETE FROM img_history")                    # 测试后端和这里用的是同一个 data\agent.db：历史、拉过的模型列表从空的开始
db.run("DELETE FROM kv WHERE k='img_models'")


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


def hist(n=10):
    return c.get(f"/api/img/hist?limit={n}").json()["items"]


def model(m, **kw):
    c.put("/api/settings", json=dict({"imgModel": m}, **kw))


c.post("/api/img/clear")
j = c.get("/api/img").json()
m = j["model"]
check(j["board"] is None and m["id"] == "gpt-image-2.5-sunburst-vip" and m["price"] == 0.03 and m["tiers"] == ["1k", "2k", "4k"] and j["cfg"]["key"] and j["cfg"]["hint"] == "••••0000"
      and len(j["sizes"]["4k"]) == 10 and isinstance(j["templates"], list) and isinstance(j["recent"], list), "生图页拿得到状态：Sunburst VIP（$0.03/张、1K/2K/4K），Key 只看得到最后 4 位")

# 模型列表：按厂商分好；拉一遍 API易 的 /v1/models
g = c.get("/api/img/models").json()
check([x["v"] for x in g["groups"]][:4] == ["google", "openai", "seedream", "flux"] and g["default"] == "gpt-image-2.5-sunburst-vip"
      and all(mm["listed"] is None for gg in g["groups"] for mm in gg["models"]), "模型列表按厂商分好（Google、OpenAI、Seedream、Flux……）；还没拉过时不标能不能用")
r = c.post("/api/img/models/refresh").json()
ids = {mm["id"]: mm for gg in r["groups"] for mm in gg["models"]}
check(r["n"] == 14 and "deepseek-v4-flash" not in ids and "gpt-5.5" not in ids and ids["gpt-image-3-preview"]["known"] is False and ids["gpt-image-3-preview"]["listed"]
      and ids["flux-2-max"]["listed"] is False and ids["gpt-image-2.5-sunburst-vip"]["listed"] and r["ts"],
      "「刷新模型列表」：用 Key 调 GET /v1/models，挑出 14 个生图模型；新出的（gpt-image-3-preview）也列出来，Key 用不了的标出来")
c.put("/api/secrets", json={"k": "imgKey", "v": "sk-wrong-1234"})
r = c.post("/api/img/models/refresh")
c.put("/api/secrets", json={"k": "imgKey", "v": KEY})
check(r.status_code == 502 and "Key 不对" in r.json()["detail"] and "sk-wrong" not in r.text, f"Key 不对时拉列表：说清楚（{r.json()['detail'][:20]}…）")

# 批量
r = c.post("/api/img/run", json={})
check(r.status_code == 400 and "清单" in r.json()["detail"], "没上传清单就点批量生成：说先上传清单")
r = c.post("/api/img/load", json={"md": "# 随便写的\n\n没有图。", "name": "x.md"})
check(r.status_code == 400 and "文件名" in r.json()["detail"], f"传了不是清单的东西：说清楚清单里要有什么（{r.json()['detail'][:30]}…）")
j = c.post("/api/img/load", json={"md": A, "name": "测试3_生图清单.md"}).json()
b = j["board"]
d = OUT / f"{time.strftime('%Y-%m-%d')}_GitHub AI 周榜 · 测试 3"
check(len(b["items"]) == 4 and all(x["st"] == "idle" for x in b["items"]) and b["dir"].replace("\\", "/").endswith(d.name) and not d.exists(),
      f"上传清单：4 张，文件夹名带日期和清单名（{d.name}），出图前不建空文件夹")
r = c.post("/api/img/run", json={})
check(r.status_code == 200 and r.json()["job"]["n"] == 4 and r.json()["job"]["est"] == 0.12 and r.json()["job"]["conc"] == 1, "批量生成：4 张，一张一张来，预估 $0.12（按次 $0.03）")
check(c.post("/api/img/run", json={}).status_code == 409 and c.post("/api/img/single", json={"prompt": "x"}).status_code == 409, "出图中再点批量或单张：不让（409）")
j = wait()
items = {x["file"]: x for x in j["board"]["items"]}
check(j["job"]["st"] == "done" and j["job"]["done"] == 4 and all(x["st"] == "ok" for x in items.values()) and abs(j["job"]["usd"] - 0.12) < 1e-9, "好了：" + j["job"]["msg"])
files = sorted(x.name for x in d.iterdir())
check(files == sorted(["img01_重点_地铁站.png", "img02_道具_灶台.png", "img03_第五名_图谱.png", "img04_第二名_手机.png", "生图清单.md", "生图记录.json"]),
      f"按清单里的文件名存好，清单原文、生图记录在同一个文件夹：{files}")
info = {n: G.png_info((d / n).read_bytes()) for n in files if n.endswith(".png")}
check([(info[n]["w"], info[n]["h"]) for n in ("img01_重点_地铁站.png", "img02_道具_灶台.png", "img03_第五名_图谱.png", "img04_第二名_手机.png")] == [(2048, 1152), (2048, 2048), (2048, 864), (1632, 2048)],
      "尺寸按 VIP 那 30 档：16:9 是 2048×1152、1:1 是 2048×2048、21:9 是 2048×864、4:5 是 1632×2048")
check(info["img02_道具_灶台.png"]["alpha"] and info["img04_第二名_手机.png"]["alpha"] and not info["img01_重点_地铁站.png"]["alpha"] and items["img02_道具_灶台.png"]["alpha"],
      "透明背景开的两张有透明通道，不开的没有")
lg = flog(4)
tb = next(x["body"] for x in lg if "小灶台" in x["body"]["prompt"])
ob = next(x["body"] for x in lg if "地铁站台" in x["body"]["prompt"])
check(all(x["auth_ok"] and x["path"] == "generations" for x in lg) and len(lg) == 4 and set(tb) == {"model", "prompt", "size", "quality", "background", "response_format"}
      and tb["background"] == "transparent" and tb["size"] == "2048x2048" and tb["quality"] == "high" and tb["response_format"] == "b64_json" and ob["background"] == "opaque",
      "发给 API易 的只有模型、提示词、尺寸、画质、透明背景开不开、要 base64；VIP 不带 n；Key 带对了")
check(G.TRANS_TAIL in tb["prompt"] and G.NOTEXT_TAIL in tb["prompt"] and G.TRANS_TAIL not in ob["prompt"] and "深夜地铁导视风" not in ob["prompt"],
      "透明的那张后面加了「只画主体、背景透明」，每张都加了「不要文字」，视觉方向没拼")
rec = json.loads((d / "生图记录.json").read_text("utf-8"))
check(list(rec["images"]) == [x["file"] for x in b["items"]] and rec["images"]["img02_道具_灶台.png"]["prompt_sent"] == tb["prompt"]
      and rec["images"]["img02_道具_灶台.png"]["size"] == "2048x2048" and rec["images"]["img02_道具_灶台.png"]["usd"] == 0.03 and (d / "生图清单.md").read_text("utf-8") == A,
      "生图记录.json：每张实际发出去的提示词、尺寸、模型、花费，按清单的顺序；清单原文存了一份")
h = hist(10)
check(len(h) == 4 and [x["file"] for x in h] == ["img04_第二名_手机.png", "img03_第五名_图谱.png", "img02_道具_灶台.png", "img01_重点_地铁站.png"] and all(x["kind"] == "batch" and x["exists"] for x in h)
      and h[0]["usd"] == 0.03 and h[0]["title"].startswith("GitHub AI 周榜"), "历史记录：出的每一张都记下了（最新的在前；模型、尺寸、花费、提示词、存在哪）")
fr, hr = c.get("/api/img/file/1?v=1"), c.get(f"/api/img/hfile/{h[0]['id']}")
check(fr.status_code == 200 and fr.content[:8] == b"\x89PNG\r\n\x1a\n" and hr.status_code == 200 and c.get("/api/img/file/99").status_code == 404 and c.get("/api/img/hfile/999999").status_code == 404,
      "页面拿得到出好的图（右边格子、看大图、历史）")
hq = c.get("/api/img/hist?q=关系图谱").json()["items"]
check(len(hq) == 1 and hq[0]["file"] == "img03_第五名_图谱.png", "历史能按提示词、文件名搜")

# 改提示词、比例、透明背景 → 重生成：旧的挪进旧版
v1 = items["img01_重点_地铁站.png"]["ver"]
r = c.patch("/api/img/item/1", json={"prompt": "改过的：等距视角的地铁站台，清晨。", "ratio": "3:2", "transparent": True})
check(r.status_code == 200 and r.json()["item"]["edited"] and r.json()["item"]["ratio"] == "3:2", "改提示词、比例、透明背景：记下「改过」")
check(c.patch("/api/img/item/1", json={"ratio": "7:3"}).status_code == 400, "比例只能是那 10 种")
c.put("/api/settings", json={"imgWithDir": True, "imgNoText": False})
c.post("/api/img/run", json={"ids": ["1"]})
j = wait()
x1 = next(x for x in j["board"]["items"] if x["id"] == "1")
last = flog(1)[0]["body"]
old = list((d / "旧版").iterdir())
check(j["job"]["n"] == 1 and x1["st"] == "ok" and x1["ver"] != v1 and (x1["w"], x1["h"]) == (2048, 1360) and x1["alpha"] and last["size"] == "2048x1360"
      and last["background"] == "transparent" and last["prompt"].startswith("这一组图的统一画风：深夜地铁导视风") and "改过的" in last["prompt"] and G.NOTEXT_TAIL not in last["prompt"],
      "重生成一张：用改过的提示词、比例、透明背景；打开「拼视觉方向」带上视觉方向，关掉「不要文字」就不加")
check(len(old) == 1 and old[0].name.startswith("img01_重点_地铁站_") and (d / "img01_重点_地铁站.png").exists(), f"旧的那张挪进「旧版」，没删：{old[0].name if old else '没有'}")
c.put("/api/settings", json={"imgWithDir": False, "imgNoText": True})

# 审核没过：只坏那一张；只补没出的
c.patch("/api/img/item/3", json={"prompt": "【拦截】这条会被审核拦下"})
c.post("/api/img/run", json={"ids": ["2", "3"]})
j = wait()
x2, x3 = (next(x for x in j["board"]["items"] if x["id"] == k) for k in ("2", "3"))
r3 = next(x for x in j["job"]["results"] if x["item"] == "3")
check(x2["st"] == "ok" and x3["st"] == "err" and "审核没过" in x3["err"] and j["job"]["fail"] == 1 and j["job"]["done"] == 1 and not r3["ok"] and "审核没过" in r3["err"],
      f"审核没过：只坏这一张，写清楚（{x3['err'][:24]}…）；页面拿得到每张的结果（动画用）")
n0 = len(flog(100))
c.patch("/api/img/item/3", json={"prompt": "一张发光的关系图谱，深蓝背景。"})
c.post("/api/img/run", json={"missing": True})
j = wait()
check(len(flog(100)) == n0 + 1 and all(x["st"] == "ok" for x in j["board"]["items"]), "「补齐没出的」：只出没出好的那一张")
r = c.post("/api/img/run", json={"missing": True})
check(r.status_code == 400 and "都出好了" in r.json()["detail"], "都出好了再点「补齐没出的」：说都出好了")

# 余额不够：整批停
(RUN / "fake_img_quota.flag").write_text("1")
c.post("/api/img/run", json={})
j = wait()
(RUN / "fake_img_quota.flag").unlink()
sts = [x["st"] for x in j["board"]["items"]]
check(j["job"]["st"] == "stop" and j["job"]["fail"] == 1 and sts.count("err") == 1 and "余额不够" in j["job"]["msg"] and "err" not in sts[1:],
      f"余额不够 / 被限流：第一张报错后整批停下，后面的不再白发：{j['job']['msg'][:40]}…")
# 停下：正在出的出完，没开始的不出；出图中页面拿得到当前这张（核心上显示用）
(RUN / "fake_img_slow.flag").write_text("1.5")
n0 = len(flog(100))
c.post("/api/img/run", json={})
time.sleep(0.6)
cur = c.get("/api/img").json()["job"]["cur"]
r = c.post("/api/img/stop").json()
j = wait(30)
(RUN / "fake_img_slow.flag").unlink()
check(cur and cur["label"] == "img01_重点_地铁站.png" and cur["size"] == "2048×1360" and cur["sec"] == 80 and cur["run_s"] >= 0 and cur["prompt"],
      "出图中：页面拿得到正在出的这张（文件名、尺寸、出了几秒、大概要多久、提示词）")
check(j["job"]["st"] == "stop" and j["job"]["done"] == 1 and len(flog(100)) == n0 + 1 and sum(x["st"] == "ok" for x in j["board"]["items"]) == 4 and j["job"]["cur"] is None,
      "点「停下」：正在出的那张出完（断开的话照样计费、图却丢了），没开始的不出；之前出好的还在")

# 要透明却没透明：标出来
(RUN / "fake_img_opaque.flag").write_text("1")
c.post("/api/img/run", json={"ids": ["2"]})
j = wait()
(RUN / "fake_img_opaque.flag").unlink()
x2 = next(x for x in j["board"]["items"] if x["id"] == "2")
check(x2["st"] == "ok" and not x2["alpha"] and "没有透明通道" in x2["warn"], "要透明背景但出来的没透明：提醒重生成")

# All 模型：不发 size、quality，比例写进提示词，b64 带前缀也认
model("gpt-image-2.5-all")
c.post("/api/img/run", json={"ids": ["4"]})
j = wait()
last = flog(1)[0]["body"]
x4 = next(x for x in j["board"]["items"] if x["id"] == "4")
check(set(last) == {"model", "prompt", "response_format"} and last["prompt"].startswith("画面比例 4:5（竖版）") and x4["st"] == "ok" and x4["usd"] == 0.03
      and "不是 4:5" in x4["warn"], "All 模型：不发尺寸、画质，比例写进提示词；按次 $0.03；出来的比例不对就提醒")
model("gpt-image-2.5-sunburst", imgQuality="medium")
c.post("/api/img/run", json={"ids": ["1"]})
j = wait()
last = flog(1)[0]["body"]
x1 = next(x for x in j["board"]["items"] if x["id"] == "1")
check(last.get("output_format") == "png" and "response_format" not in last and last["quality"] == "medium" and 0.03 < x1["usd"] < 0.04,
      f"官转 Sunburst：要 PNG、按 API易 回的 token 算钱（2K 中画质这张 ${x1['usd']:.3f}）")
model("gpt-image-2.5-sunburst-vip", imgQuality="high")

# 重新上传同一份清单：文件夹里已经有的算出好了
j = c.post("/api/img/load", json={"md": A, "name": "测试3_生图清单.md"}).json()
check(all(x["st"] == "ok" and x["old"] for x in j["board"]["items"]), "重新上传同一份清单：文件夹里已经有的认出来（算出好了，不用再花钱）")
r = c.post("/api/img/zip").json()
zp = OUT / r["zip"].replace("\\", "/").split("/")[-1]
names = sorted(zipfile.ZipFile(io.BytesIO(zp.read_bytes())).namelist())
check(r["n"] == 4 and names == sorted(["img01_重点_地铁站.png", "img02_道具_灶台.png", "img03_第五名_图谱.png", "img04_第二名_手机.png"]),
      f"打包 zip：4 张图，按清单的文件名，不含旧版、记录（{zp.name}）")
r2 = c.post("/api/img/zip").json()
check(r2["zip"] != r["zip"] and zp.exists(), "再打一次包：换个名字，上一个不覆盖")

# ---------- 单张：文生图、带参考图 ----------
ref1 = "data:image/png;base64," + base64.b64encode(fpng(320, 240, False, 5)).decode()
ref2 = "data:image/png;base64," + base64.b64encode(fpng(240, 320, True, 9)).decode()
r = c.post("/api/img/single", json={"prompt": "  "})
check(r.status_code == 400 and "提示词" in r.json()["detail"], "单张：没写提示词就点生成，说写一句提示词")
r = c.post("/api/img/single", json={"prompt": "一只发光的水母漂在深蓝的海里", "ratio": "3:4", "n": 2})
check(r.status_code == 200 and r.json()["job"]["n"] == 2 and r.json()["job"]["kind"] == "single" and r.json()["job"]["est"] == 0.06, "单张：一次 2 张，预估 $0.06")
j = wait()
day = OUT / "单张" / time.strftime("%Y-%m-%d")
sf = sorted(day.glob("*.png"))
check(j["job"]["done"] == 2 and len(sf) == 2 and all("一只发光的水母" in x.name for x in sf) and sf[0].name.endswith("_1.png") and G.png_info(sf[0].read_bytes())["w"] == 1536
      and (day / "生图记录.json").exists(), f"单张存进「生图输出\\单张\\日期」，文件名是时间 + 提示词开头（{sf[0].name if sf else '没有'}），3:4 是 1536×2048")
h = hist(2)
check(all(x["kind"] == "single" and x["ratio"] == "3:4" and x["refs"] == 0 for x in h) and all(x["ok"] and x["hid"] for x in j["job"]["results"]), "单张也记进历史；页面拿得到每张的历史编号（动画、格子用）")
r = c.post("/api/img/single", json={"prompt": "把这两张图里的东西放到一张海报里", "ratio": "16:9", "refs": [ref1, ref2]})
j = wait()
lg = flog(1)[0]
refs_dir = ROOT / "data" / "img" / "refs"
check(lg["path"] == "edits" and lg["multipart"] and [f["field"] for f in lg["files"]] == ["image[]", "image[]"] and lg["body"]["size"] == "2048x1152"
      and lg["body"]["prompt"].startswith("把这两张图") and j["job"]["done"] == 1 and hist(1)[0]["refs"] == 2,
      "带 2 张参考图：走 /v1/images/edits（multipart，字段 image[]），参考图、提示词、尺寸一起发；历史记着用了几张参考图")
c.post("/api/img/single", json={"prompt": "照着这张换成冬天", "ratio": "1:1", "refs": [ref1]})
wait()
check([f["field"] for f in flog(1)[0]["files"]] == ["image"], "1 张参考图：字段叫 image")
r1 = c.post("/api/img/single", json={"prompt": "x", "refs": ["data:text/plain;base64,aGVsbG8="]})
r2 = c.post("/api/img/single", json={"prompt": "x", "refs": [ref1] * 9})
check(r1.status_code == 400 and "参考图" in r1.json()["detail"] and r2.status_code == 400 and "最多 8 张" in r2.json()["detail"], "参考图只认 PNG / JPEG / WEBP；Sunburst VIP 最多 8 张")

# 别家的模型：Nano Banana、Seedream、Flux、没收录的
model("gemini-3.1-flash-image")
c.post("/api/img/single", json={"prompt": "一座雪山下的小木屋", "ratio": "16:9", "refs": [ref1]})
j = wait()
lg = flog(1)[0]
check(lg["path"] == "gemini" and lg["model"] == "gemini-3.1-flash-image" and lg["cfg"] == {"aspectRatio": "16:9", "imageSize": "2K"} and lg["modalities"] == ["IMAGE"]
      and lg["refs"] == 1 and j["job"]["done"] == 1 and (j["job"]["results"][0]["w"], j["job"]["results"][0]["h"]) == (2048, 1152) and j["job"]["usd"] == 0.055,
      "Nano Banana 2：走 /v1beta/models/…:generateContent，比例 + 2K、参考图放 inlineData；$0.055 一张")
c.post("/api/img/single", json={"prompt": "【拦截】这条会被拦"})
j = wait()
check(j["job"]["fail"] == 1 and "Google 没出图" in j["job"]["results"][0]["err"] and "IMAGE_SAFETY" in j["job"]["results"][0]["err"], "Google 拦了（回 200 但没图）：说清楚被安全审核拦了、不扣钱")
model("seedream-5-0-flash-260915")
c.post("/api/img/single", json={"prompt": "一杯冒热气的咖啡", "ratio": "1:1", "refs": [ref1]})
j = wait()
lb = flog(1)[0]["body"]
check(lb["watermark"] is False and lb["size"] == "2048x2048" and lb["output_format"] == "png" and lb["image"] == "<图>" and "sequential_image_generation" not in lb and j["job"]["done"] == 1
      and j["job"]["usd"] == 0.018, "Seedream 5.0 Flash：关水印、2K 那档像素、要 PNG、参考图放 image；$0.018 一张")
model("seedream-4-5-251128")
c.post("/api/img/single", json={"prompt": "一杯冒热气的咖啡", "ratio": "4:3"})
j = wait()
res = j["job"]["results"][0]
check(res["ok"] and res["file"].endswith(".jpg") and "存成了" in res["warn"] and (day / res["file"]).exists(), "Seedream 4.5 只出 JPEG：存成 .jpg，并且说一声")
model("flux-2-pro")
c.post("/api/img/single", json={"prompt": "极简风的山", "ratio": "16:9", "refs": [ref1, ref2]})
j = wait()
lb = flog(1)[0]["body"]
res = j["job"]["results"][0]
check(lb["size"] == "1280x720" and lb["input_image"] == "<图>" and lb["input_image_2"] == "<图>" and res["ok"] and (res["w"], res["h"]) == (1280, 720),
      "FLUX.2 Pro：1K 那档像素，参考图放 input_image、input_image_2；回来的是链接，马上下载存好")
model("gpt-image-3-preview")
c.post("/api/img/single", json={"prompt": "一只纸鹤", "ratio": "1:1"})
j = wait()
lb = flog(1)[0]["body"]
check(j["job"]["done"] == 1 and "quality" not in lb and lb["size"] == "2048x2048" and lb["response_format"] == "b64_json" and c.get("/api/img").json()["model"]["known"] is False,
      "没收录的新模型（gpt-image-3-preview）：按 OpenAI 的方式调，先试一张")
c.put("/api/settings", json=VIP)

# ---------- 素材模板 ----------
r = c.post("/api/img/templates", json={"name": "", "prompt": "x"})
check(r.status_code == 400 and "名字" in r.json()["detail"], "存模板要起名字")
t1 = c.post("/api/img/templates", json={"name": "封面 · 深夜地铁风", "prompt": "深夜城市的地铁线路图", "ratio": "16:9", "n": 2, "transparent": False, "refs": [ref1],
                                        "model": "gpt-image-2.5-sunburst-vip", "tier": "2k", "quality": "high"}).json()
tid = t1["template"]["id"]
tr = c.get(f"/api/img/tplref/{tid}/0")
st = c.get("/api/img").json()["templates"]
check(len(t1["templates"]) == 1 and st[0]["refs"] == 1 and st[0]["ratio"] == "16:9" and st[0]["n"] == 2 and tr.status_code == 200 and tr.content[:4] == b"\x89PNG"
      and c.get(f"/api/img/tplref/{tid}/5").status_code == 404, "存模板：提示词、比例、张数、模型、参考图（存在 data\\img\\templates）；页面拿得到参考图")
t2 = c.post("/api/img/templates", json={"name": "封面 · 深夜地铁风", "prompt": "换了一句", "ratio": "1:1"}).json()
tpl_dir = ROOT / "data" / "img" / "templates"
check(len(t2["templates"]) == 1 and t2["templates"][0]["prompt"] == "换了一句" and not list(tpl_dir.glob(f"{tid}_*")), "同名的模板：替换掉，旧的参考图删了")
r = c.delete(f"/api/img/templates/{t2['template']['id']}").json()
check(r["templates"] == [] and c.delete("/api/img/templates/nope").status_code == 404, "删模板")
r = c.post("/api/img/open", json={"hid": hist(1)[0]["id"]}).json()
check("单张" in r["msg"], f"历史里点「打开文件夹」：打开那张图所在的文件夹（{r['msg'][-20:]}）")

# 没填 Key
c.put("/api/secrets", json={"k": "imgKey", "v": ""})
r, r2 = c.post("/api/img/run", json={}), c.post("/api/img/single", json={"prompt": "x"})
c.put("/api/secrets", json={"k": "imgKey", "v": KEY})
check(r.status_code == 400 and "Key" in r.json()["detail"] and r2.status_code == 400 and "Key" in r2.json()["detail"], f"没填 API易 Key：说去哪填（{r.json()['detail']}）")
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
for p_ in [ROOT / "data" / "settings.json", ROOT / "data" / "agent.db", RUN / "backend.log", *(ROOT / "data" / "logs").glob("*.log"), *(ROOT / "data" / "img").rglob("*"), *OUT.rglob("*.*")]:
    try:
        if p_.is_file() and (KEY.encode() in p_.read_bytes() or b"sk-wrong" in p_.read_bytes()):
            leak.append(p_.name)
    except OSError:
        pass
check(not leak, f"设置、数据库（历史、模板）、清单状态、参考图、日志、生图记录、出的图里都没有 Key{'：' + str(leak) if leak else ''}")
fd = " | ".join(e["text"] for e in c.get("/api/feed?n=200").json()["items"])
check(KEY not in fd and "sk-wrong" not in fd and "开始生图" in fd and "模型列表" in fd, "进展报告里写了生图的事（开始、拉模型列表），没有 Key")
c.post("/api/img/clear")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
