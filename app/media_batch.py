r"""配音批量、配乐批量（v3.1）：照生图的批量做——一份清单 → 一条一条出完 → 按清单里的名字存进一个文件夹。

配音清单（视频窗口写的配音稿也能直接用）：
  # 第 5 期 · 配音清单             ← 标题（文件夹名用）
  ## 01_橘页_开场                  ← 一段一个标题，标题就是文件名
  音色：橘页                       ← 可选：这一段用哪个音色（我的音色 / 预设音色 / 云端音色的名字）；不写就用配音页中间选的
  语气：平静、温和                 ← 可选；还能写「语言：英文」「种子：123」
  正文……（空一行算换段）
  也能一次选几个 .txt：一个文件一段，文件名就是名字（橘页配音稿.txt、紫苏配音稿.txt 这种）。
配乐清单：
  ## bgm01_开场
  时长：30 秒                      ← 30 / 30秒 / 0:30 / 1分30秒 都认；不写 60 秒
  描述：轻快的电子乐……              ← 不写「描述：」的话，这一节剩下的字就是描述
  也能一行一首：bgm01_开场 | 30 | 轻快的电子乐……；或者 Markdown 表格（名字、时长、描述三列）。

一条一条出（配音服务、ACE-Step 一次只出一个）。配音用 app/tts.py 的 T.start（和点「生成配音」走同一条路：整段 / 一句一句、
本地对齐、云端），念完把试听台那一份复制进批量文件夹；配乐用 app/bgm.py 的 B.generate（直接存进批量文件夹）。
点「停下」：手上这一条按单个的规矩停（配音一句一句的念完这句；整段的关服务；配乐不等了），后面的不出了。连着两条没出成也停。
存：配音输出\<日期>_<清单名>\<名字>.wav + _字幕.srt + _时间轴.json + _文案.txt；配乐输出\<日期>_<清单名>\<名字>.wav + .json。
同名的旧文件挪进「旧版」（不删）。清单原文存一份在文件夹里。重新上传同一份清单：文件夹里已经有的标成好了，「只补没出的」只补缺的。
清单存在 data\batch\tts.json、bgm.json（Agent 关了再开还在）。"""
import asyncio
import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from . import feed, mediainfo, paths, settings

OLD = "旧版"
BAD = r'[\\/:*?"<>|\r\n\t]+'
EXT = re.compile(r"\.(wav|mp3|flac|ogg|m4a|txt|md|markdown|srt|json)$", re.I)
HEAD = re.compile(r"^\s{0,3}(#{1,4})\s+(.+?)\s*#*\s*$")
FIELD = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?(音色|声音|角色|语气|情绪|语言|种子|时长|长度|秒数|多长|描述|提示词|风格|prompt)(?:\*\*)?\s*[:：]\s*(.*)$", re.I)
MAX_ITEMS = 200


def keep_old(p):
    """同名的旧文件挪进同一个文件夹的「旧版」（不删），名字后面加时分秒。"""
    p = Path(p)
    if not p.exists():
        return None
    od = p.parent / OLD
    od.mkdir(exist_ok=True)
    stem, ext = os.path.splitext(p.name)
    q, k = od / f"{stem}_{datetime.now():%H%M%S}{ext}", 2
    while q.exists():
        q, k = od / f"{stem}_{datetime.now():%H%M%S}_{k}{ext}", k + 1
    p.replace(q)
    return q


def put_file(src, dst):
    """复制一份过去：旧的先挪进「旧版」，新的先写 .part 再换名（写到一半断电不会留半个文件）。"""
    dst = Path(dst)
    keep_old(dst)
    tmp = dst.with_name(dst.name + ".part")
    shutil.copyfile(src, tmp)
    tmp.replace(dst)
    return dst


def put_text(dst, text):
    dst = Path(dst)
    keep_old(dst)
    tmp = dst.with_name(dst.name + ".part")
    tmp.write_text(text, "utf-8")
    tmp.replace(dst)
    return dst


def clean_name(s, n=60):
    s = re.sub(r"\*\*|`", "", str(s or "")).strip()
    s = re.sub(r"^\s*(?:[-*]\s+|\d+[.、)]\s+)", "", s)                  # 「- xxx」「1. xxx」：去掉列表的记号（01_xxx 这种不动）
    s = EXT.sub("", s)
    s = re.sub(BAD, "", s)
    s = re.sub(r"\s+", "_", s).strip(" ._")
    return s[:n]


def dedupe(name, seen):
    base, k = name, 2
    while name.lower() in seen:
        name, k = f"{base}_{k}", k + 1
    seen.add(name.lower())
    return name


def seconds_of(s):
    """30 / 30秒 / 30s / 0:30 / 1:30 / 1分30秒 / 2分钟 → 秒数（10~600）；认不出来 None。"""
    s = str(s or "").strip().lower().replace("：", ":")
    if not s:
        return None
    m = re.match(r"^(\d+):(\d{1,2})$", s)
    if m:
        v = int(m.group(1)) * 60 + int(m.group(2))
    else:
        mm = re.search(r"(\d+(?:\.\d+)?)\s*(?:分钟|分|min|m(?![a-z]))", s)
        ss = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒钟|秒|sec|s(?![a-z]))", s)
        if mm or ss:
            v = (float(mm.group(1)) * 60 if mm else 0) + (float(ss.group(1)) if ss else 0)
        else:
            m = re.match(r"^(\d+(?:\.\d+)?)", s)
            if not m:
                return None
            v = float(m.group(1))
    return int(max(10, min(600, round(v))))


def _body(lines):
    """正文：去掉代码块的 ``` 行、HTML 注释、引用的「> 」、加粗的 **；段落（空一行）留着。"""
    t = "\n".join(x for x in lines if not x.strip().startswith("```"))
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"(?m)^\s*>\s?", "", t)
    t = re.sub(r"\*\*|`", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _sections(md):
    """# 标题 + 一节一节（## / ### 开头）。返回 (标题, [(名字, [行])], 开头那段)。"""
    title, secs, cur, pre, fence = "", [], None, [], False
    for line in (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
        m = None if fence else HEAD.match(line)
        if m and len(m.group(1)) == 1 and not title and cur is None:
            title = re.sub(r"\*\*|`", "", m.group(2)).strip()
            continue
        if m and len(m.group(1)) >= 2:
            cur = (m.group(2), [])
            secs.append(cur)
            continue
        (cur[1] if cur else pre).append(line)
    return title, secs, pre


def _fields(lines, keys):
    """一节开头的「音色：」「时长：」这些（中间可以夹空行）；遇到正文就不认了。返回 ({键: 值}, 剩下的行)。"""
    got, i = {}, 0
    while i < len(lines):
        x = lines[i]
        if not x.strip():
            i += 1
            continue
        m = FIELD.match(x)
        if not m:
            break
        k = keys.get(m.group(1).lower())
        if k is None:
            break
        got[k] = m.group(2).strip()
        i += 1
    return got, lines[i:]


TTS_KEYS = {"音色": "voice", "声音": "voice", "角色": "voice", "语气": "tone", "情绪": "tone", "语言": "lang", "种子": "seed"}
BGM_KEYS = {"时长": "seconds", "长度": "seconds", "秒数": "seconds", "多长": "seconds", "描述": "prompt", "提示词": "prompt", "风格": "prompt", "prompt": "prompt"}


def parse_tts(md, name=""):
    """配音清单 → {title, items:[{file, text, voice, tone, lang, seed}], warn}。没有 ## 小节：整份就是一段。"""
    title, secs, pre = _sections(md)
    stem = clean_name(name) if name else ""
    items, warn, seen = [], [], set()
    if not secs:
        f, rest = _fields(pre, TTS_KEYS)
        secs = [(stem or title or "配音", rest)]
        pre_fields = f
    else:
        pre_fields = {}
    for head, lines in secs:
        f, rest = _fields(lines, TTS_KEYS)
        f = {**pre_fields, **f}
        text = _body(rest)
        nm = clean_name(head) or f"段{len(items) + 1:02d}"
        if not text:
            warn.append(f"「{nm}」没有正文，跳过了")
            continue
        items.append({"file": dedupe(nm, seen), "text": text, "voice": f.get("voice", "")[:60], "tone": f.get("tone", "")[:200],
                      "lang": f.get("lang", "")[:20], "seed": f.get("seed", "")[:12]})
    return {"title": title or stem or "配音批量", "items": items[:MAX_ITEMS], "warn": warn}


def _rows(lines):
    """一行一首：「名字 | 时长 | 描述」或 Markdown 表格。表头、分隔行跳过。"""
    out = []
    for x in lines:
        s = x.strip()
        if "|" not in s:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3 or all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        name, sec, prompt = cells[0], cells[1], "|".join(cells[2:]).strip()
        if seconds_of(sec) is None and re.search(r"名|文件|时长|描述|name", name + sec, re.I):
            continue                                                      # 表头
        out.append((name, sec, prompt))
    return out


def parse_bgm(md, name=""):
    """配乐清单 → {title, items:[{file, prompt, seconds}], warn}。"""
    title, secs, pre = _sections(md)
    stem = clean_name(name) if name else ""
    items, warn, seen = [], [], set()

    def add(head, prompt, sec):
        nm = clean_name(head) or f"bgm{len(items) + 1:02d}"
        prompt = re.sub(r"(?<=[\u3000-\u303f\u3400-\u9fff\uff00-\uffef])\s*\n\s*(?=[\u3000-\u303f\u3400-\u9fff\uff00-\uffef])", "", _body(prompt.split("\n")))   # 中文换行接上不加空格
        prompt = re.sub(r"\s+", " ", prompt).strip()[:1000]
        if not prompt:
            warn.append(f"「{nm}」没写描述，跳过了")
            return
        s = seconds_of(sec)
        if sec and s is None:
            warn.append(f"「{nm}」的时长「{sec}」没认出来，按 60 秒")
        items.append({"file": dedupe(nm, seen), "prompt": prompt, "seconds": s or 60})

    def one_section(head, lines, fallback):
        table = [x for x in lines if x.strip().startswith("|") or x.count("|") >= 2]
        f, rest = _fields([x for x in lines if x not in table], BGM_KEYS)
        body = "\n".join(rest).strip()
        if f or body or not table:                                       # 这一节自己是一首（标题当名字）
            add(head or fallback, (f.get("prompt", "") + "\n" + body).strip(), f.get("seconds", ""))
        for r in _rows(table):                                           # 一节里的表格、一行一首的：每行一首
            add(r[0], r[2], r[1])

    for head, lines in secs:
        one_section(head, lines, "")
    if not secs:
        one_section("", pre, stem or title or "配乐")
    return {"title": title or stem or "配乐批量", "items": items[:MAX_ITEMS], "warn": warn}


class Batch:
    KIND, WHAT, UNIT, JOBN, MD_NAME = "", "", "条", "", ""

    def __init__(self):
        self.path = paths.DATA / "batch" / f"{self.KIND}.json"
        self.board = self._load()
        self.job = None
        self._task = None

    @property
    def s(self):
        return settings.S

    # ---------- 要子类给的 ----------
    def out_root(self):
        raise NotImplementedError

    def parse(self, md, name):
        raise NotImplementedError

    def outputs(self, it):
        """这一条存成哪些文件（第一个是音频）。"""
        return [f"{it['file']}.wav"]

    async def _one(self, job, it, base):
        raise NotImplementedError

    async def precheck(self, todo, base):
        pass

    def edit_fields(self, it, body):
        pass

    # ---------- 存、读 ----------
    def _load(self):
        try:
            b = json.loads(self.path.read_text("utf-8"))
            for it in b.get("items", []):
                if it.get("st") in ("run", "queue"):                    # 上次跑到一半 Agent 关了
                    it["st"] = "idle"
            return b
        except Exception:
            return None

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.board, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    def folder(self):
        return Path(self.board["dir"]) if self.board and self.board.get("dir") else None

    def busy(self):
        return bool(self.job and self.job["st"] == "run")

    def audio(self, it):
        d = self.folder()
        return d / (it.get("saved") or self.outputs(it)[0]) if d else None

    def _scan(self):
        """文件夹里已经有的：标成好了（重新上传同一份清单，「只补没出的」就只补缺的）。"""
        for it in self.board["items"]:
            p = self.audio(it)
            if p and p.exists() and it.get("st") != "ok":
                it.update(st="ok", err="", old=True, ver=int(p.stat().st_mtime), dur=mediainfo.probe(p).get("duration"))

    def load(self, md="", name="", files=None):
        if self.busy():
            raise HTTPException(409, f"正在批量{self.WHAT}，等这批出完或者先点「停下」")
        if files:                                                        # 一次选了几个文件：.md 按清单认，.txt 一个文件一条
            items, warn, title, seen, mds = [], [], "", set(), []
            for f in files[:MAX_ITEMS]:
                fn, txt = str(f.get("name") or ""), str(f.get("text") or "")
                if len(txt) > 400_000:
                    raise HTTPException(400, f"「{fn}」太大了（超过 40 万字），是不是传错文件了")
                p = self.parse(txt, fn if not re.search(r"\.(md|markdown)$", fn, re.I) or len(files) > 1 else "")
                if not p["items"] and len(files) > 1:
                    warn.append(f"「{fn}」里没认出东西")
                for it in p["items"]:
                    it["file"] = dedupe(it["file"], seen)
                    items.append(it)
                warn += p["warn"]
                title = title or (p["title"] if re.search(r"\.(md|markdown)$", fn, re.I) else "")
                mds.append(f"<!-- {fn} -->\n{txt.strip()}\n")
            p = {"title": title or (clean_name(files[0].get("name"))[:30] + (f" 等 {len(files)} 个" if len(files) > 1 else "")) or f"{self.WHAT}批量",
                 "items": items[:MAX_ITEMS], "warn": warn}
            md = "\n".join(mds)
            name = ", ".join(str(f.get("name") or "") for f in files)[:80]
        else:
            if not (md or "").strip():
                raise HTTPException(400, "清单是空的")
            if len(md) > 400_000:
                raise HTTPException(400, "清单太大了（超过 40 万字），是不是传错文件了")
            p = self.parse(md, name)
        if not p["items"]:
            raise HTTPException(400, self.EMPTY)
        stem = re.sub(r"\s*[·\-—|]*\s*(配音清单|配乐清单|配音稿|清单)\s*$", "", p["title"]).strip() or p["title"]
        safe = re.sub(BAD, "", stem).strip(" .")[:40] or self.WHAT
        d = self.out_root() / f"{datetime.now():%Y-%m-%d}_{safe}"
        for i, it in enumerate(p["items"]):
            it.update(id=f"b{i + 1}", st="idle", err="", warn="", dur=None, sec=None, ver=0, old=False)
            it["src"] = it.get("text") or it.get("prompt") or ""
        self.job = None
        self.board = {"id": int(time.time() * 1000), "title": p["title"], "md": md, "md_name": (name or "")[:80], "warn": p["warn"], "dir": str(d),
                      "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "items": p["items"]}
        self._scan()
        self._save()
        n_ok = sum(1 for it in p["items"] if it["st"] == "ok")
        feed.add(f"认了一份{self.WHAT}清单「{p['title']}」：{len(p['items'])} {self.UNIT}" + (f"，文件夹里已经有 {n_ok} {self.UNIT}" if n_ok else ""), "info", job=self.JOBN)
        return self.board

    def clear(self):
        if self.busy():
            raise HTTPException(409, "正在出，先点「停下」")
        self.board, self.job = None, None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def item(self, iid):
        it = next((x for x in (self.board or {}).get("items", []) if x["id"] == str(iid)), None)
        if not it:
            raise HTTPException(404, "没有这一条")
        return it

    def edit(self, iid, body):
        it = self.item(iid)
        if it["st"] in ("run", "queue"):
            raise HTTPException(409, "这一条正在出，出完再改")
        self.edit_fields(it, body)
        it["edited"] = (it.get("text") or it.get("prompt") or "") != it.get("src")
        self._save()
        return it

    # ---------- 跑一批 ----------
    async def start(self, body):
        if self.busy():
            raise HTTPException(409, f"正在批量{self.WHAT}，等这批出完或者先点「停下」")
        if not self.board or not self.board.get("items"):
            raise HTTPException(400, "先认一份清单")
        items, ids = self.board["items"], body.get("ids")
        if ids:
            want = {str(x) for x in ids}
            todo = [it for it in items if it["id"] in want]
        elif body.get("only_missing"):
            todo = [it for it in items if it["st"] != "ok"]
        else:
            todo = list(items)
        if not todo:
            raise HTTPException(400, "没有要出的：都出好了（要重出点那一条的「重来」）")
        base = dict(body.get("req") or {})
        await self.precheck(todo, base)
        if self.busy():
            raise HTTPException(409, f"正在批量{self.WHAT}")
        for it in todo:
            it["prev"] = it["st"]
            it.update(st="queue", err="", warn="")
        self.job = {"id": int(time.time() * 1000), "st": "run", "n": len(todo), "done": 0, "fail": 0, "t0": time.time(), "t1": 0.0, "stop": "",
                    "cur": None, "msg": "准备中", "audio_s": 0.0, "cny": 0.0, "fatal": ""}
        feed.add(f"开始批量{self.WHAT}「{self.board['title']}」：{len(todo)} {self.UNIT}，一{self.UNIT}一{self.UNIT}出，存进 {paths.show(self.folder())}", "head", job=self.JOBN)
        self._task = asyncio.get_running_loop().create_task(self._run(self.job, todo, base))
        return self.public()

    def stop(self):
        if self.busy():
            self.job["stop"] = "你点了「停下」"
            self.job["msg"] = "停下：手上这一条停了就不往下出了"
            self.stop_current()
        return self.public()

    def stop_current(self):
        pass

    async def _run(self, job, todo, base):
        d = self.folder()
        d.mkdir(parents=True, exist_ok=True)
        if self.board.get("md"):
            try:
                p = d / self.MD_NAME
                if not p.exists() or p.read_text("utf-8") != self.board["md"]:
                    put_text(p, self.board["md"])
            except Exception:
                pass
        miss = 0
        for it in todo:
            if job["stop"]:
                it["st"] = it.pop("prev", "idle") if it.get("prev") in ("ok", "err") else "idle"
                continue
            job["cur"] = it["id"]
            job["msg"] = f"第 {job['done'] + job['fail'] + 1}/{job['n']} {self.UNIT}：{it['file']}"
            it.update(st="run", err="", t0=time.time())
            it.pop("prev", None)
            self._save()
            try:
                ok = await self._one(job, it, base)
            except HTTPException as e:                                   # 配音服务那边不让开始（在让路、在对齐……）：整批停
                it.update(st="err", err=str(e.detail))
                job["fatal"] = job["fatal"] or str(e.detail)
                job["stop"] = job["stop"] or str(e.detail)
                ok = False
            except Exception as e:
                it.update(st="err", err=f"出错了：{type(e).__name__} {e}"[:300])
                ok = False
            if ok is None:                                               # 停下了：这一条不算没出成（重来的那条，原来出好的还在就还算好的）
                a = self.audio(it)
                it["st"] = "ok" if a and a.exists() else "idle"
            elif ok:
                job["done"] += 1
                miss = 0
            else:
                job["fail"] += 1
                miss += 1
                if miss >= 2 and not job["stop"]:
                    job["fatal"] = f"连着两{self.UNIT}没出成，先停下（最后一条：{it.get('err', '')[:120]}）"
                    job["stop"] = job["fatal"]
            self._save()
        job.update(st="stop" if job["stop"] else "done", t1=time.time(), cur=None)
        took = job["t1"] - job["t0"]
        mins = f"{int(took // 60)} 分 {int(took % 60):02d} 秒" if took >= 60 else f"{int(took)} 秒"
        job["msg"] = (f"{'停了' if job['stop'] else '好了'}：出了 {job['done']} {self.UNIT}" + (f"，{job['fail']} {self.UNIT}没出成" if job["fail"] else "") +
                      f"，用了 {mins}" + self.money(job) + (f"。{job['fatal']}" if job["fatal"] else ""))
        self._save()
        feed.add(f"批量{self.WHAT}" + job["msg"], "warn" if job["fail"] or job["stop"] else "ok", job=self.JOBN)
        if job["done"]:
            feed.done(f"批量{self.WHAT} · {self.board['title']} · {job['done']} {self.UNIT}" + (f"（{job['fail']} {self.UNIT}没出成）" if job["fail"] else ""),
                      self.engine_name(), took, self.money(job).lstrip("，") or "免费", self.KIND)

    def money(self, job):
        return ""

    def engine_name(self):
        return "本地"

    # ---------- 打开、打包、放进工作区 ----------
    def file(self, iid):
        p = self.audio(self.item(iid))
        if not p or not p.exists():
            raise HTTPException(404, "这一条还没出")
        return p

    def done_files(self):
        d, out = self.folder(), []
        for it in (self.board or {}).get("items", []):
            if it.get("st") != "ok" or not d:
                continue
            for n in self.outputs(it):
                if (d / n).is_file():
                    out.append(d / n)
        return out

    def zip(self):
        d, files = self.folder(), self.done_files()
        if not d or not files:
            raise HTTPException(404, f"还没有出好的{self.WHAT}")
        z, k = d / f"{d.name}_{self.WHAT}.zip", 2
        while z.exists():
            z, k = d / f"{d.name}_{self.WHAT}_{k}.zip", k + 1
        tmp = z.with_name(z.name + ".part")
        with zipfile.ZipFile(tmp, "w") as f:
            for x in files:
                f.write(x, x.name, compress_type=zipfile.ZIP_DEFLATED if x.suffix.lower() in (".wav", ".srt", ".json", ".txt") else zipfile.ZIP_STORED)
        tmp.replace(z)
        feed.add(f"批量{self.WHAT}打包好了：{paths.show(z)}（{len(files)} 个文件）", "ok", job=self.JOBN)
        return z, len(files)

    def tows(self, body):
        from . import workspace
        if not self.board:
            raise HTTPException(400, "没有清单")
        if body.get("id"):
            it = self.item(body["id"])
            files = [self.folder() / n for n in self.outputs(it) if (self.folder() / n).is_file()] if it.get("st") == "ok" else []
        else:
            files = self.done_files()
        stem = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", self.folder().name) if self.folder() else (self.board.get("title") or "清单")
        sub = self.WHAT + "/" + re.sub(BAD, "", stem).replace(" · ", "_").strip()[:30]
        try:
            return workspace.take_in(files, sub)
        except workspace.Denied as e:
            raise HTTPException(400, str(e)) from None

    def open(self):
        d = self.folder() if self.folder() and self.folder().exists() else self.out_root()
        d.mkdir(parents=True, exist_ok=True)
        if paths.IS_WIN:
            os.startfile(str(d))                                          # 打开资源管理器（不是黑窗口）
            return {"msg": "打开了：" + paths.show(d)}
        return {"msg": "文件夹在：" + paths.show(d)}

    # ---------- 给界面 ----------
    def public(self):
        j = self.job
        if not j:
            return None
        out = {k: j.get(k) for k in ("id", "st", "n", "done", "fail", "cur", "msg", "fatal")}
        out["elapsed"] = round((j["t1"] or time.time()) - j["t0"])
        out["audio_s"] = round(j.get("audio_s") or 0, 1)
        out["cny"] = round(j.get("cny") or 0, 4)
        return out

    def status(self):
        b, board = self.board, None
        if b:
            keys = self.ITEM_KEYS
            board = {k: b.get(k) for k in ("id", "title", "md_name", "warn", "created")}
            board["dir"] = paths.show(b["dir"])
            board["items"] = [{k: it.get(k) for k in keys} for it in b["items"]]
        return {"board": board, "job": self.public(), "out": paths.show(self.out_root())}


# ======================= 配音批量 =======================
class TtsBatch(Batch):
    KIND, WHAT, UNIT, JOBN, MD_NAME = "tts", "配音", "段", "配音", "配音清单.md"
    EMPTY = "没认出要念的：每段用「## 文件名」开头，下面写要念的字（要换音色写一行「音色：名字」）；或者一次选几个 .txt，一个文件一段"
    ITEM_KEYS = ("id", "file", "text", "voice", "tone", "lang", "seed", "st", "err", "warn", "dur", "sec", "cny", "ver", "old", "edited", "segs", "chars")

    def out_root(self):
        from . import tts
        return tts.T.out_dir()

    def parse(self, md, name):
        p = parse_tts(md, name)
        for it in p["items"]:
            it["chars"] = len(re.sub(r"\s+", "", it["text"]))
        return p

    def outputs(self, it):
        n = it["file"]
        return [f"{n}.wav", f"{n}_字幕.srt", f"{n}_时间轴.json", f"{n}_文案.txt"]

    def edit_fields(self, it, body):
        from . import tts
        if "text" in body:
            t = str(body["text"] or "").strip()
            if len(t) > tts.MAX_CHARS:
                raise HTTPException(400, f"一段最多 {tts.MAX_CHARS} 字")
            it["text"] = t
            it["chars"] = len(re.sub(r"\s+", "", t))
        for k, n in (("voice", 60), ("tone", 200)):
            if k in body:
                it[k] = str(body[k] or "").strip()[:n]

    def voice_req(self, it, base):
        """这一段的请求：配音页现在选的（base）+ 清单里这一段自己写的音色、语气、语言、种子。"""
        from . import tts, tts_cloud
        cloud = (base.get("engine") or self.s.get("ttsEngine") or "local") == "cloud"
        req = {k: v for k, v in base.items() if k not in ("text", "same", "_batch")}
        req["engine"] = "cloud" if cloud else "local"
        name = (it.get("voice") or "").strip()
        if name:
            n = name.lower()
            if cloud:
                v = next((x for x in tts_cloud.voices() if x["id"].lower() == n or str(x.get("name") or "").lower() == n), None)
                if not v:
                    raise HTTPException(400, f"「{it['file']}」写的音色「{name}」在云端音色里没找到（音色库里的名字、自己造的音色名字都行）")
                req["voice"] = v["id"]
            else:
                mine = next((x for x in tts.T.voices() if str(x.get("name") or "").lower() == n), None)
                spk = next((x for x in tts.SPEAKERS if x["id"].lower() == n or x["name"].lower() == n), None)
                if mine:
                    req.update(mode="design", desc=mine["desc"], seed=mine["seed"], name=mine["name"], lang=mine.get("lang") or req.get("lang") or "Chinese")
                elif spk:
                    req.update(mode="preset", speaker=spk["id"])
                else:
                    raise HTTPException(400, f"「{it['file']}」写的音色「{name}」没找到：要是「我的音色」里存过的名字，或者预设音色（Vivian、Serena……）")
        if it.get("tone"):
            req["tone"] = it["tone"]
        lang = (it.get("lang") or "").strip()
        if lang:
            req["lang"] = {"中文": "Chinese", "英文": "English", "英语": "English", "自动": "Auto"}.get(lang, lang)
        if str(it.get("seed") or "").strip().isdigit():
            req["seed"] = int(it["seed"])
        req.update(text=it["text"], same=False, _batch=True)
        return req

    async def precheck(self, todo, base):
        """开始前先查一遍：音色都认得、字数不超、引擎能用（不然跑到一半才发现）。"""
        from . import tts, tts_cloud
        if tts.T.busy():
            raise HTTPException(409, "配音页上一段还在生成，等它好了或者先点「停下」")
        if tts.T.aligning:
            raise HTTPException(409, "正在重新对齐时间轴，等几秒")
        for it in todo:
            if not (it.get("text") or "").strip():
                raise HTTPException(400, f"「{it['file']}」没有要念的字")
            if len(it["text"]) > tts.MAX_CHARS:
                raise HTTPException(400, f"「{it['file']}」超过 {tts.MAX_CHARS} 字，拆成两段吧")
            req = self.voice_req(it, base)
            cloud = req["engine"] == "cloud"
            v = tts.T.voice(dict(req, mode="cloud") if cloud else req)
            if cloud:
                if not tts_cloud.key():
                    raise HTTPException(400, "还没填百炼 API Key：到 设置 › 云端 填好再生成")
            else:
                if tts.M.yielding:
                    raise HTTPException(409, f"现在在让路（{tts.M.yield_reason or '显存不够'}），配音先不开；游戏关了再生成（或者换「百炼云端」，不用显卡）")
                if not tts.T.model_ok(v["kind"]) and not ((tts.T._h or {}).get("models") or {}).get(v["kind"]):
                    raise HTTPException(400, f"{tts.MODEL_INFO[v['kind']]}的模型还没下：到 设置 › 整备 一键装好（或者 设置 › 本地模型 点「安装配音」）")

    def stop_current(self):
        from . import tts
        if tts.T.busy() and (tts.T.job or {}).get("batch"):
            tts.tts_stop()

    async def _one(self, job, it, base):
        from . import tts
        tts.T.start(self.voice_req(it, base))
        tts.T.job["batch"] = True
        task = tts.T._task
        tj = tts.T.job
        while not task.done():
            await asyncio.sleep(0.4)
            job["msg"] = f"第 {job['done'] + job['fail'] + 1}/{job['n']} 段 · {it['file']}：{tj.get('msg') or ''}"
        if tj["st"] == "stop":
            return None
        if tj["st"] != "done":
            it.update(st="err", err=tj.get("err") or tj.get("msg") or "没生成成", sec=round(time.time() - it["t0"], 1))
            return False
        m = tts.T.draft()
        if not m:
            it.update(st="err", err="生成完了，但试听台那一份找不到了")
            return False
        d, n = self.folder(), it["file"]
        meta = dict(m, name=n, audio=f"{n}.wav", subtitles=f"{n}_字幕.srt", script=f"{n}_文案.txt", batch=self.board.get("title"))
        meta.pop("ver", None)
        put_file(tts.DRAFT / "draft.wav", d / f"{n}.wav")
        put_file(tts.DRAFT / "draft.srt", d / f"{n}_字幕.srt")
        put_file(tts.DRAFT / "draft.txt", d / f"{n}_文案.txt")
        put_text(d / f"{n}_时间轴.json", json.dumps(meta, ensure_ascii=False, indent=2))
        chk = m.get("check") or {}
        warn = []
        if chk.get("estimated"):
            warn.append(f"{chk['estimated']} 句的开始、结束是估的")
        if chk.get("sure") is False:
            warn.append("时间轴是按停顿猜的，要准的话在配音页「重新对齐」")
        job["audio_s"] += m.get("duration") or 0
        job["cny"] += float(tj.get("cny") or 0)
        it.update(st="ok", err="", warn="；".join(warn), dur=m.get("duration"), sec=round(m.get("gen_seconds") or (time.time() - it["t0"]), 1),
                  cny=round(float(tj.get("cny") or 0), 4), segs=len(m.get("segments") or []), ver=int(time.time() * 1000), old=False)
        return True

    def money(self, job):
        return (f"，{job['audio_s'] / 60:.1f} 分钟音频" if job.get("audio_s") else "") + (f"，约 ¥{job['cny']:.2f}" if job.get("cny") else "")

    def engine_name(self):
        return "百炼云端" if self.s.get("ttsEngine") == "cloud" else "本地"


# ======================= 配乐批量 =======================
class BgmBatch(Batch):
    KIND, WHAT, UNIT, JOBN, MD_NAME = "bgm", "配乐", "首", "配乐", "配乐清单.md"
    EMPTY = "没认出要出的曲子：每首用「## 名字」开头，下面写「时长：30 秒」和描述；或者一行一首「名字 | 30 | 描述」"
    ITEM_KEYS = ("id", "file", "prompt", "seconds", "st", "err", "warn", "dur", "sec", "ver", "old", "edited", "hid", "saved")

    def fmt(self):
        f = self.s.get("bgmFormat") or "wav"
        return f if f in ("mp3", "flac") else "wav"

    def out_root(self):
        from . import bgm
        return bgm.B.out_dir()

    def parse(self, md, name):
        return parse_bgm(md, name)

    def outputs(self, it):
        a = it.get("saved") or f"{it['file']}.{self.fmt()}"
        return [a, os.path.splitext(a)[0] + ".json"]

    def edit_fields(self, it, body):
        if "prompt" in body:
            p = re.sub(r"\s+", " ", str(body["prompt"] or "")).strip()
            if len(p) > 1000:
                raise HTTPException(400, "描述太长了（最多 1000 字）")
            it["prompt"] = p
        if "seconds" in body:
            s = seconds_of(body["seconds"])
            if s is None:
                raise HTTPException(400, "时长写秒数（10~600），或者 1:30、1分30秒")
            it["seconds"] = s

    async def precheck(self, todo, base):
        from . import bgm
        if bgm.B.busy():
            raise HTTPException(409, "上一首还在出，等它好了")
        for it in todo:
            if not (it.get("prompt") or "").strip():
                raise HTTPException(400, f"「{it['file']}」没写描述")
        if not bgm.B.cmd() and not await bgm.B.health():
            raise HTTPException(400, "配乐还没装：到 设置 › 整备 点「配音、语音、配乐」那张卡片的一键装好（或者只装 ACE-Step 那一项）")
        if bgm.M.yielding:
            raise HTTPException(409, f"现在在让路（{bgm.M.yield_reason or '显存不够'}），配乐先不开")

    def stop_current(self):
        from . import bgm
        if bgm.B.busy():
            bgm.B.job["stop"] = "你点了「停下」"

    async def _one(self, job, it, base):
        from . import bgm

        def say(m):
            job["msg"] = f"第 {job['done'] + job['fail'] + 1}/{job['n']} 首 · {it['file']}：{m}"
        try:
            r = await bgm.B.generate(it["prompt"], it["seconds"], say=say, stopped=lambda: bool(job["stop"]),
                                     dest=self.folder() / f"{it['file']}.{self.fmt()}")
        except bgm.BgmError as e:
            if job["stop"]:
                return None
            it.update(st="err", err=str(e)[:300], sec=round(time.time() - it["t0"], 1))
            if "还没装" in str(e) or "让路" in str(e):
                job["fatal"] = job["stop"] = str(e)
            return False
        it.update(st="ok", err="", dur=r.get("duration"), sec=round(r["sec"], 1), hid=r.get("id"), saved=r["name"], ver=int(time.time() * 1000), old=False)
        job["audio_s"] += r.get("duration") or it["seconds"]
        return True

    def engine_name(self):
        return "本地 ACE-Step"


TB = TtsBatch()
MB = BgmBatch()


# ---------------- 接口：/api/tts/batch…、/api/bgm/batch… ----------------
api = APIRouter()


def _routes(b, pre):
    @api.get(pre)
    def st():
        return b.status()

    @api.post(pre + "/load")
    def load(body: dict = Body(...)):
        b.load(body.get("md") or "", body.get("name") or "", body.get("files"))
        return b.status()

    @api.patch(pre + "/item/{iid}")
    def edit(iid: str, body: dict = Body(...)):
        b.edit(iid, body)
        return b.status()

    @api.post(pre + "/run")
    async def run(body: dict = Body(default={})):
        await b.start(body)
        await asyncio.sleep(0.05)
        return b.status()

    @api.post(pre + "/stop")
    def stop():
        b.stop()
        return b.status()

    @api.post(pre + "/clear")
    def clear():
        b.clear()
        return b.status()

    @api.get(pre + "/file/{iid}")
    def file(iid: str):
        return FileResponse(b.file(iid), headers={"Cache-Control": "no-store"})

    @api.post(pre + "/zip")
    def zp():
        z, n = b.zip()
        if paths.IS_WIN:
            os.startfile(str(z.parent))
        return {"zip": paths.show(z), "n": n, "msg": f"打包好了：{z.name}（{n} 个文件）"}

    @api.post(pre + "/tows")
    def tows(body: dict = Body(default={})):
        return b.tows(body)

    @api.post(pre + "/open")
    def opn():
        return b.open()


_routes(TB, "/api/tts/batch")
_routes(MB, "/api/bgm/batch")
