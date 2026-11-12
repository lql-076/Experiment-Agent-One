"""v3.1：配音、语音、配乐进整备一键装好；配音批量、配乐批量。
1. 清单怎么认：配音（## 文件名、音色 / 语气、没小节就整份一段、空的跳过）、配乐（## 名字 + 时长 + 描述、一行一首、表格、混着写）、时长的各种写法
2. 存文件：同名的旧文件挪进「旧版」（不删），新的先写 .part
3. 整备 ›「配音、语音、配乐」那一组：4 项、只装一项、一组在装时另一组不让开（409）、别的组的状态不被冲掉
4. 一键装配乐（scripts/install_bgm.py）真的跑一遍：假下载站（dev/mocks.py 8001 /files/）给 7za 和一个假的 ACE-Step 便携包（这里现做的，
   照官方便携包只带 acestep.model_downloader）→ 校验 7za → 多连接下载 → 7za 测试、解压、改名 ace-step → 魔搭下不了换 hf-mirror（报错进日志）→ 自检；
   装完配乐认得出（不用填文件夹）；做完把装出来的删掉
5. 说话的声音（Breeze TTS 2）一键装好之后：启动命令用随包的代码（app/breeze_run.py）+ 配音环境，设置里什么都不用填
6. 配音批量（连测试后端，假配音服务）：认清单 → 每段自己的音色（我的音色 / 预设）→ 一段一段念、存进 配音输出\\日期_清单名\\ →
   跑的时候单个生成、重新对齐不让开 → 重来一段旧的进「旧版」→ 改一段 → 一次选几个 .txt → 写错的音色开始前就拦下 → 停下 → 打包、放进工作区
7. 配乐批量（连测试后端，假 ACE-Step）：认清单 → 一首一首出、按名字存 → 跑的时候单个不让出 → 重来 → 停下 → 历史里也有
用法：python dev/test_media.py（要先 dev/serve.sh start）"""
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import feed, media_batch as mb, paths  # noqa: E402

feed.add = lambda *a, **k: None
RUN = ROOT / "dev" / ".run"
bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


# ---------- 1. 清单怎么认 ----------
print("── 清单怎么认")
p = mb.parse_tts("""# 第 5 期 · 配音清单
这一期两个人（开头这段说明不念）。

## 01_橘页_开场
音色：橘页
语气：平静、温和

大家好，**欢迎**来到这一期。

第二段在这里。

## 02_紫苏_吐槽.wav
- **音色**：紫苏
[excited] 这也太离谱了吧！

## 02_紫苏_吐槽
音色：紫苏
同名的第二段。

## 03_空的
音色：x
""")
it = p["items"]
check(p["title"] == "第 5 期 · 配音清单" and [x["file"] for x in it] == ["01_橘页_开场", "02_紫苏_吐槽", "02_紫苏_吐槽_2"],
      f"配音清单：标题、每段的名字（去掉 .wav、同名加 _2）：{[x['file'] for x in it]}")
check(it[0]["voice"] == "橘页" and it[0]["tone"] == "平静、温和" and it[0]["text"] == "大家好，欢迎来到这一期。\n\n第二段在这里。",
      "「音色：」「语气：」认出来、不念；正文的加粗去掉、空行（换段）留着")
check(it[1]["voice"] == "紫苏" and it[1]["text"].startswith("[excited]"), "「- **音色**：」这种写法也认；云端的情绪标签留着")
check(p["warn"] == ["「03_空的」没有正文，跳过了"], f"没有正文的一段跳过并提醒：{p['warn']}")
p = mb.parse_tts("就一段话。\n\n第二段。", "橘页配音稿.txt")
check(len(p["items"]) == 1 and p["items"][0]["file"] == "橘页配音稿" and p["title"] == "橘页配音稿", "没有 ## 小节：整份就是一段，名字用文件名（视频窗口给的配音稿直接能用）")
p = mb.parse_tts("音色：Serena\n就一段话。", "x.txt")
check(p["items"][0]["voice"] == "Serena" and p["items"][0]["text"] == "就一段话。", "没有小节时开头的「音色：」也认")

p = mb.parse_bgm("""# 第 5 期 · 配乐清单
## bgm01_开场
时长：30 秒
描述：轻快的电子乐，
明亮的合成器

## bgm02_讲解
时长：1分30秒
安静的钢琴独奏 and soft pads

| 名字 | 时长 | 描述 |
|---|---|---|
| bgm03_结尾 | 0:45 | 温暖吉他 |

## 只有表格
| bgm04 | 2分钟 | 8-bit |
""")
got = [(x["file"], x["seconds"], x["prompt"]) for x in p["items"]]
check(got == [("bgm01_开场", 30, "轻快的电子乐，明亮的合成器"), ("bgm02_讲解", 90, "安静的钢琴独奏 and soft pads"), ("bgm03_结尾", 45, "温暖吉他"), ("bgm04", 120, "8-bit")],
      f"配乐清单：## 小节（时长、描述；中文换行接上不加空格）、小节里混着表格、只有表格的小节不算一首：{got}")
p = mb.parse_bgm("a | 20 | lofi\nb | 几秒 | piano")
check([(x["file"], x["seconds"]) for x in p["items"]] == [("a", 20), ("b", 60)] and p["warn"] == ["「b」的时长「几秒」没认出来，按 60 秒"],
      "一行一首「名字 | 时长 | 描述」；时长认不出按 60 秒并提醒")
check(mb.parse_bgm("轻快的电子乐", "开场.md")["items"][0] == {"file": "开场", "prompt": "轻快的电子乐", "seconds": 60}, "只有一句描述：一首 60 秒，名字用文件名")
secs = {x: mb.seconds_of(x) for x in ("30", "30秒", "0:30", "1:30", "1分30秒", "2分钟", "90s", "1.5 min", "5", "1000", "abc")}
check(secs == {"30": 30, "30秒": 30, "0:30": 30, "1:30": 90, "1分30秒": 90, "2分钟": 120, "90s": 90, "1.5 min": 90, "5": 10, "1000": 600, "abc": None},
      f"时长的各种写法（10~600 秒）：{secs}")
check(mb.clean_name('  1. a/b:c*?.wav ') == "abc" and mb.clean_name("01 开场 片段") == "01_开场_片段", "文件名去掉 Windows 不让用的字、列表记号、扩展名，空格换成 _")

# ---------- 2. 存文件 ----------
print("── 存文件")
with tempfile.TemporaryDirectory() as td:
    d = pathlib.Path(td)
    src = d / "src.txt"
    src.write_text("新的", "utf-8")
    (d / "a.wav").write_text("旧的", "utf-8")
    mb.put_file(src, d / "a.wav")
    olds = list((d / mb.OLD).iterdir())
    check((d / "a.wav").read_text("utf-8") == "新的" and len(olds) == 1 and olds[0].read_text("utf-8") == "旧的" and olds[0].name.startswith("a_"),
          f"同名的旧文件挪进「旧版」（不删）：{[x.name for x in olds]}")
    mb.put_text(d / "a.wav", "再新")
    check(len(list((d / mb.OLD).iterdir())) == 2 and not list(d.glob("*.part")), "再来一次：旧版里两个，没有留下 .part")

# ---------- 3. 整备 › 配音、语音、配乐 ----------
print("── 整备 ›「配音、语音、配乐」")
B = "http://127.0.0.1:8765"
c = httpx.Client(base_url=B, headers={"X-Agent": "1"}, timeout=30)


def setup_wait(t=60):
    t0 = time.time()
    while time.time() - t0 < t:
        j = c.get("/api/setup").json()
        if not j.get("running"):
            return j
        time.sleep(0.4)
    return c.get("/api/setup").json()


st = c.get("/api/setup").json()
media = [s["k"] for s in st["steps"] if s.get("g") == "media"]
check(media == ["tts", "asr", "breeze", "bgm"] and st.get("groups", {}).get("media") == "配音、语音、配乐",
      f"整备里多一组「配音、语音、配乐」：{media}")
core_before = {s["k"]: s["st"] for s in st["steps"] if s.get("g") == "core"}
r = c.post("/api/setup/start", json={"group": "media", "keys": ["bgm"]})
check(r.status_code == 200 and r.json().get("group") == "media", f"只装配乐那一项：开始了（{r.status_code}）")
r2 = c.post("/api/setup/start", json={"group": "core"})
check(r2.status_code == 409, f"这一组在装时，一键补齐不让开（{r2.status_code}：{r2.json().get('detail', '')[:30]}）")
st = setup_wait()
steps = {s["k"]: s for s in st["steps"]}
check(steps["bgm"]["st"] in ("ok", "done", "ready") and all(steps[k]["st"] not in ("run", "fail", "err") for k in ("tts", "asr", "breeze")),
      "只跑了配乐那一项：" + "、".join(f"{k}={steps[k]['st']}" for k in media))
check({k: steps[k]["st"] for k in core_before} == core_before, "一键补齐那 6 步的状态没被冲掉")

# ---------- 4. 一键装配乐：真的跑一遍 install_bgm.py ----------
print("── 一键装配乐（scripts/install_bgm.py，假下载站）")
ACE, SEVEN_DIR, DLD = ROOT / "ace-step", paths.TOOLS / "7z", paths.TOOLS / "downloads"
if ACE.exists() or SEVEN_DIR.exists() or DLD.exists():
    print("  · 跳过：这台电脑上已经有 ace-step / tools\\7z / tools\\downloads（不碰它们）")
else:
    MF = RUN / "mockfiles"
    MF.mkdir(parents=True, exist_ok=True)
    tgz = RUN / "7zip-bin-5.2.0.tgz"
    if not tgz.exists():
        try:
            tgz.write_bytes(httpx.get("https://registry.npmjs.org/7zip-bin/-/7zip-bin-5.2.0.tgz", timeout=60, follow_redirects=True).content)
        except Exception as e:
            print("  · 拿不到 7zip-bin 的包（第一次要联网下一次，之后用 dev/.run 里存的）：", e)
    if not tgz.exists():
        check(False, "7zip-bin-5.2.0.tgz 没有：一键装配乐这一段测不了")
    else:
        shutil.copy2(tgz, MF / tgz.name)
        build = RUN / "fakeace"
        shutil.rmtree(build, ignore_errors=True)
        with tarfile.open(tgz) as tf:                        # 现做假的便携包要用 7za：从同一个包里拿 linux 版
            m = tf.getmember("package/linux/x64/7za")
            (build / "bin").mkdir(parents=True)
            (build / "bin" / "7za").write_bytes(tf.extractfile(m).read())
        za = build / "bin" / "7za"
        za.chmod(za.stat().st_mode | stat.S_IEXEC)
        a = build / "ACE-Step-1.5"
        (a / "acestep").mkdir(parents=True)
        (a / "python_embedded").mkdir()
        (a / "acestep" / "__init__.py").write_text("")
        (a / "acestep" / "api_server.py").write_text('print("fake api server")\n')
        (a / "acestep" / "model_downloader.py").write_text('''import os
from pathlib import Path
# 照便携包里那一版：只有 acestep.model_downloader（没有 acestep.api.model_download），download_main_model 没有 prefer_source 参数
def download_main_model(checkpoints_dir=None, force=False, token=None):
    src = os.environ.get("ACESTEP_DOWNLOAD_SOURCE", "")
    print("Downloading main model from ACE-Step/Ace-Step1.5... (" + src + ")", flush=True)
    if os.environ.get("FAKE_MS_FAIL") and src == "modelscope":
        print("Error: 魔搭连不上（假的）", flush=True)
        return False, "ModelScope download failed"
    for m in ("acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B", "acestep-5Hz-lm-1.7B"):
        d = Path(checkpoints_dir) / m
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.safetensors").write_bytes(b"x" * 1000)
        print(f"Downloading [{m}]: 100%|##########| 1.00k/1.00k [00:00<00:00, 5.00MB/s]", flush=True)
    return True, "Main model downloaded"
''')
        py = a / "python_embedded" / "python"                 # 便携包自带的 Python：这里用一段 sh 接到本机的 Python 上；问 PyTorch 时假装有显卡
        py.write_text('#!/bin/sh\ncase "$2" in *"import torch"*) echo "PyTorch 2.7.1+cu128 | 显卡 测试显卡"; exit 0;; esac\nexec ' + sys.executable + ' "$@"\n')
        py.chmod(0o755)
        (a / "padding.bin").write_bytes(os.urandom(12 * 1024 * 1024))    # 12MB：够多连接分段下
        arc = MF / "ACE-Step-1.5.7z"
        arc.unlink(missing_ok=True)
        subprocess.run([str(za), "a", "-t7z", "-mx=1", str(arc), "ACE-Step-1.5"], cwd=str(build), check=True, capture_output=True)
        env = dict(os.environ, AGENT_7Z_URLS="http://127.0.0.1:8001/files/7zip-bin-5.2.0.tgz", AGENT_ACE_URLS="http://127.0.0.1:8001/files/ACE-Step-1.5.7z",
                   FAKE_MS_FAIL="1", PYTHONUTF8="1")
        try:
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "install_bgm.py")], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=300)
            out = r.stdout + r.stderr
            check(r.returncode == 0 and "配乐装好了" in out, f"装完了（退出码 {r.returncode}）" + ("" if r.returncode == 0 else "：" + out[-600:]))
            check((SEVEN_DIR / "7za").exists() and "sha512" not in out.lower().replace("sha512 对上了", ""), "7za 从 npm 的包里拿出来，校验过")
            check((ACE / "acestep" / "api_server.py").exists() and (ACE / "python_embedded" / "python").exists() and not (ROOT / "ace-step.tmp").exists(),
                  "解压到 ace-step（先解到 ace-step.tmp 再改名）")
            check("换 hf-mirror" in out and all((ACE / "checkpoints" / m / "model.safetensors").exists() for m in ("acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B")),
                  "魔搭下不了，换 hf-mirror 下全了三个模型")
            check("acestep.model_downloader" in out and "魔搭连不上（假的）" in out and "换 hf-mirror 再试：" in out,
                  "便携包里只有 acestep.model_downloader（没有 api/model_download）也能下；它打印的报错进了日志，「没下全」后面写着原因")
            check((DLD / "ACE-Step-1.5.7z").exists(), "下好的便携包留在 tools\\downloads（不删；要腾地方自己删）")
            from app import bgm
            check(bgm.B.installed() and bgm.B.builtin() and str(bgm.B.cmd()[0]).endswith("python_embedded/python") and str(bgm.B.cmd()[1]).endswith("acestep/api_server.py"),
                  "装完配乐认得出：设置里不用填文件夹，启动命令是它自带的 Python 跑 acestep\\api_server.py")
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "install_bgm.py")], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
            check(r.returncode == 0 and "跳过" in r.stdout, "再点一次：都装好了，跳过")
        finally:
            for x in (ACE, ROOT / "ace-step.tmp", SEVEN_DIR, DLD, build):
                shutil.rmtree(x, ignore_errors=True)
            for x in ROOT.glob("ace-step.旧的-*"):
                shutil.rmtree(x, ignore_errors=True)

# ---------- 5. 说话的声音一键装好之后 ----------
print("── 说话的声音（Breeze TTS 2）一键装好之后")
from app import settings, tts, voice  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    md = pathlib.Path(td) / "breeze-tts-2"
    (md / "audio_tokenizer").mkdir(parents=True)
    (md / "config.json").write_text("{}")
    (md / "model.safetensors").write_bytes(b"x")
    (md / "audio_tokenizer" / "config.json").write_text("{}")
    old_model, old_env = voice.MODEL, tts.T.env_ok
    voice.MODEL = md
    tts.T.env_ok = lambda: True
    saved = {k: settings.S.get(k) for k in ("voiceCmd", "voiceDir")}
    settings.S["voiceCmd"], settings.S["voiceDir"] = "", ""
    try:
        cmd = voice.V.cmd()
        check(voice.installed() and cmd and cmd[1] == ROOT / "app" / "breeze_run.py" and cmd[2] == md and cmd[0] == paths.tts_python(),
              "权重下好了：用配音环境的 Python 跑 app\\breeze_run.py（随包的代码），设置里什么都不用填")
        check(voice.V.cwd() == voice.CODE and (voice.CODE / "breeze_infer" / "api.py").exists() and (voice.CODE / "LICENSE").exists(),
              "在随包的 vendor\\breeze-tts 里跑（Apache-2.0 的 LICENSE 跟着）")
        (md / "model.safetensors.incomplete").write_text("")
        check(not voice.installed(), "有下到一半的文件：不算装好")
    finally:
        voice.MODEL, tts.T.env_ok = old_model, old_env
        settings.S.update(saved)

# ---------- 6. 配音批量 ----------
print("── 配音批量（假配音服务）")
OUT = RUN / "配音输出-批量测试"
shutil.rmtree(OUT, ignore_errors=True)
c.put("/api/settings", json={"ttsOut": str(OUT), "ttsEngine": "local"})
c.post("/api/tts/batch/clear")
VID = [v["id"] for v in c.post("/api/tts/voices", json={"name": "橘页", "desc": "二十多岁的女声，安静温和，吐字清楚", "seed": 7, "lang": "Chinese"}).json()["voices"] if v["name"] == "橘页"]
BASE = {"mode": "preset", "speaker": "Serena", "tone": "", "lang": "Chinese", "whole": True}
MD = """# 第 5 期 · 配音清单
## 01_橘页_开场
音色：橘页
大家好，欢迎来到这一期。今天聊三个工具。

第二段在这里。
## 02_紫苏
音色：Uncle_Fu
语气：激动
这也太离谱了吧！
## 03_默认
就用中间选的。
"""


def bwait(kind="tts", t=90):
    t0 = time.time()
    while time.time() - t0 < t:
        j = c.get(f"/api/{kind}/batch").json()
        if j["job"] and j["job"]["st"] != "run":
            return j
        time.sleep(0.4)
    return c.get(f"/api/{kind}/batch").json()


r = c.post("/api/tts/batch/load", json={"md": MD, "name": "第5期.md"})
b = r.json().get("board") or {}
check(r.status_code == 200 and [x["file"] for x in b.get("items", [])] == ["01_橘页_开场", "02_紫苏", "03_默认"] and b["dir"].endswith("_第 5 期"),
      f"认清单：3 段，文件夹 配音输出\\日期_第 5 期（{b.get('dir', '')[-20:]}）")
r = c.post("/api/tts/batch/run", json={"req": BASE})
check(r.status_code == 200 and r.json()["job"]["st"] == "run", f"开始批量（{r.status_code}）")
r = c.post("/api/tts/gen", json={"mode": "preset", "speaker": "Serena", "text": "插一段。"})
check(r.status_code == 409 and "批量" in r.json()["detail"], f"批量在跑：单个生成不让开（{r.status_code}）")
r = c.post("/api/tts/batch/run", json={"req": BASE})
check(r.status_code == 409, "批量在跑：再点开始不让开")
j = bwait()
its = {x["file"]: x for x in j["board"]["items"]}
check(j["job"]["st"] == "done" and j["job"]["done"] == 3 and all(x["st"] == "ok" and x["dur"] for x in its.values()), f"3 段都念好了：{j['job']['msg']}")
d = OUT / pathlib.Path(b["dir"]).name
names = sorted(x.name for x in d.iterdir())
want = sorted([f"{n}{s}" for n in its for s in (".wav", "_字幕.srt", "_时间轴.json", "_文案.txt")] + ["配音清单.md"])
check(names == want, f"每段四个文件（WAV、字幕、时间轴、文案）按清单里的名字存，清单原文也存一份：{len(names)} 个")
m1 = json.loads((d / "01_橘页_开场_时间轴.json").read_text("utf-8"))
m2 = json.loads((d / "02_紫苏_时间轴.json").read_text("utf-8"))
m3 = json.loads((d / "03_默认_时间轴.json").read_text("utf-8"))
check(m1["voice"].get("mode") == "design" and m1["voice"].get("name") == "橘页" and m1["voice"].get("seed") == 7 and m1["audio"] == "01_橘页_开场.wav",
      "「音色：橘页」用的是「我的音色」里存的那个（描述 + 种子 7）")
check(m2["voice"].get("speaker") == "Uncle_Fu" and m2["voice"].get("tone") == "激动" and m3["voice"].get("speaker") == "Serena",
      "「音色：Uncle_Fu」用预设音色、「语气：激动」带上；没写的用配音页选的（Serena）")
check((d / "01_橘页_开场_文案.txt").read_text("utf-8").strip() == "大家好，欢迎来到这一期。今天聊三个工具。\n\n第二段在这里。" and
      (d / "01_橘页_开场_字幕.srt").read_text("utf-8").count("-->") == len(m1["segments"]) == 3,
      "文案、字幕和时间轴对得上（3 句）")
fr = c.get("/api/tts/batch/file/b2")
check(fr.status_code == 200 and fr.content[:4] == b"RIFF", "能听批量里的一段")
r = c.post("/api/tts/batch/run", json={"req": BASE, "ids": ["b3"]})
j = bwait()
olds = sorted(x.name for x in (d / mb.OLD).iterdir()) if (d / mb.OLD).exists() else []
check(j["job"]["done"] == 1 and len(olds) == 4 and all(x.startswith("03_默认") for x in olds), f"重来一段：旧的四个文件挪进「旧版」：{olds}")
r = c.patch("/api/tts/batch/item/b3", json={"text": "改过的一句话。", "voice": "Vivian"})
it3 = next(x for x in r.json()["board"]["items"] if x["id"] == "b3")
check(r.status_code == 200 and it3["text"] == "改过的一句话。" and it3["voice"] == "Vivian" and it3["edited"], "改一段的字和音色（标「改过」）")
r = c.post("/api/tts/batch/zip")
z = d / f"{d.name}_配音.zip"
check(r.status_code == 200 and z.exists() and r.json()["n"] == 12, f"打包：12 个文件放在这一批的文件夹里（{r.json().get('msg', r.text)[:40]}）")
r = c.post("/api/tts/batch/tows", json={"id": "b1"})
check(r.status_code == 200 and r.json()["n"] == 4 and r.json()["rel"].endswith("配音/第 5 期"), f"一段放进工作区：{r.json().get('rel', r.text)[:40]}")
WS = ROOT / "工作区" / "素材" / "配音" / "第 5 期"
shutil.rmtree(WS, ignore_errors=True)                        # 测试放进去的删掉（沙箱里的工作区）

r = c.post("/api/tts/batch/load", json={"files": [{"name": "橘页配音稿.txt", "text": "第一句。\n\n第二句。"}, {"name": "紫苏配音稿.txt", "text": "音色：Uncle_Fu\n吐槽一句。"}]})
its = r.json()["board"]["items"] if r.status_code == 200 else []
check([(x["file"], x["voice"]) for x in its] == [("橘页配音稿", ""), ("紫苏配音稿", "Uncle_Fu")], f"一次选两个 .txt：一个文件一段，名字是文件名：{[x['file'] for x in its]}")
r = c.post("/api/tts/batch/load", json={"md": "## a\n音色：不存在的音色\n一句话。\n## b\n第二句。"})
r = c.post("/api/tts/batch/run", json={"req": BASE})
st = c.get("/api/tts/batch").json()
check(r.status_code == 400 and "不存在的音色" in r.json()["detail"] and not st["job"] and all(x["st"] == "idle" for x in st["board"]["items"]),
      f"写错的音色：开始前就拦下，一段都不念（{r.json().get('detail', '')[:40]}）")
long = "这是很长的一段话，要念好几秒钟才念得完。" * 16
c.post("/api/tts/batch/load", json={"md": "".join(f"## 长{i}\n{long}\n" for i in range(1, 4))})
c.post("/api/tts/batch/run", json={"req": BASE})
t0 = time.time()
while time.time() - t0 < 20 and not (c.get("/api/tts").json().get("job") or {}).get("st") == "run":
    time.sleep(0.2)
time.sleep(0.5)
r = c.post("/api/tts/realign")
check(r.status_code == 409, f"批量在跑：重新对齐不让开（{r.status_code}）")
c.post("/api/tts/batch/stop")
j = bwait(t=30)
check(j["job"]["st"] == "stop" and j["job"]["done"] == 0 and all(x["st"] == "idle" for x in j["board"]["items"]) and not j["job"]["fail"],
      f"停下：手上这段停了，后面的不念，都算没出（不算没出成）：{j['job']['msg']}")
r = c.post("/api/tts/batch/clear")
check(r.status_code == 200 and r.json()["board"] is None, "换一份：清单清掉（文件夹里出好的不动）")
for v in VID:                                   # 测试存的「我的音色」删掉（不然 dev/ui/tts.py 点到的是它）
    c.delete(f"/api/tts/voices/{v}")
check(d.exists() and (d / "01_橘页_开场.wav").exists(), "出好的文件还在")

# ---------- 7. 配乐批量 ----------
print("── 配乐批量（假 ACE-Step）")
BOUT = RUN / "配乐输出-批量测试"
shutil.rmtree(BOUT, ignore_errors=True)
c.put("/api/settings", json={"bgmOut": str(BOUT), "bgmDir": "", "bgmUrl": "http://127.0.0.1:8001"})
c.post("/api/bgm/batch/clear")
c.get("/api/bgm")
r = c.post("/api/bgm/batch/load", json={"md": "# 第 5 期 · 配乐清单\n## bgm01_开场\n时长：20\n描述：轻快的电子乐\n\n| 名字 | 时长 | 描述 |\n|---|---|---|\n| bgm02_讲解 | 0:30 | 安静钢琴 |\n"})
check(r.status_code == 200 and [(x["file"], x["seconds"]) for x in r.json()["board"]["items"]] == [("bgm01_开场", 20), ("bgm02_讲解", 30)], "认清单：2 首")
r = c.post("/api/bgm/batch/run", json={})
r2 = c.post("/api/bgm/gen", json={"prompt": "插一首", "seconds": 20})
check(r.status_code == 200 and r2.status_code == 409 and "批量" in r2.json()["detail"], f"开始批量；跑的时候单个不让出（{r2.status_code}）")
j = bwait("bgm")
d = BOUT / pathlib.Path(r.json()["board"]["dir"]).name
check(j["job"]["done"] == 2 and sorted(x.name for x in d.iterdir()) == ["bgm01_开场.json", "bgm01_开场.wav", "bgm02_讲解.json", "bgm02_讲解.wav", "配乐清单.md"],
      f"2 首按清单里的名字存（旁边一份 .json）：{j['job']['msg']}")
meta = json.loads((d / "bgm02_讲解.json").read_text("utf-8"))
check(meta["prompt"] == "安静钢琴" and meta["seconds"] == 30, "发给 ACE-Step 的就是这一首的描述和时长")
rec = c.get("/api/bgm").json()["recent"]
check({"bgm01_开场.wav", "bgm02_讲解.wav"} <= {x["name"] for x in rec[:5]}, "「最近出的」里也有（点一首在中间听）")
c.post("/api/bgm/batch/run", json={"ids": ["b1"]})
bwait("bgm")
check(len(list((d / mb.OLD).iterdir())) == 2, "重来一首：旧的 wav 和 json 挪进「旧版」")
r = c.patch("/api/bgm/batch/item/b2", json={"prompt": "【慢】安静钢琴", "seconds": "1分"})
check(r.status_code == 200 and next(x for x in r.json()["board"]["items"] if x["id"] == "b2")["seconds"] == 60, "改一首的描述和时长（「1分」认成 60 秒）")
c.post("/api/bgm/batch/run", json={"ids": ["b2"]})
time.sleep(2.5)
c.post("/api/bgm/batch/stop")
j = bwait("bgm", 20)
check(j["job"]["st"] == "stop" and next(x for x in j["board"]["items"] if x["id"] == "b2")["st"] == "ok", f"停下：这一首不等了，还算原来出好的那一版：{j['job']['msg']}")
r = c.post("/api/bgm/batch/zip")
check(r.status_code == 200 and r.json()["n"] == 4, f"打包：{r.json().get('msg', r.text)[:40]}")
c.post("/api/bgm/batch/clear")
c.put("/api/settings", json={"ttsOut": "", "bgmOut": ""})

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
