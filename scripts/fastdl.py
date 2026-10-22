"""快速下载大文件（PyTorch 那种 3GB 的）：
1. 先同时试几个下载源，看谁能用、谁最快（各下 3MB 测速）；
2. 用最快的源多线程分段下载（每段 8MB，12 条连接一起下），镜像对单条连接限速时能快很多；
3. 断了能接着下：已经下完的段记在 .part.json 里，再运行一次只下剩下的；
4. 下完检查大小和压缩包校验，没问题才改成正式文件名。

每 0.5 秒打印一行 @@PROGRESS {...}，一键补齐靠它在界面上显示进度条、速度、还剩多久。
也可以单独用：python fastdl.py 保存到的文件 下载地址1 下载地址2 ...
"""
import json
import os
import sys
import threading
import time
import zipfile
from pathlib import Path

import httpx

CHUNK = 8 << 20
CONNS = 12
UA = {"User-Agent": "Mozilla/5.0 AgentSetup/1.2"}


def emit(**kw):
    print("@@PROGRESS " + json.dumps(kw, ensure_ascii=False), flush=True)


FEED = os.environ.get("AGENT_FEED") == "1"     # 一键补齐在跑：说的话加 @@SAY，进后台页的进展报告


def say(msg, kind=""):
    """kind：""普通、"!"要注意、"✓"好了。"""
    print(("@@SAY " + kind + msg.strip()) if FEED else msg, flush=True)


def _total(r):
    cr = r.headers.get("content-range", "")
    if "/" in cr and cr.rsplit("/", 1)[1].isdigit():
        return int(cr.rsplit("/", 1)[1])
    cl = r.headers.get("content-length")
    return int(cl) if cl and cl.isdigit() and r.status_code == 200 else 0


def probe(sources, sample=3 << 20, limit=8.0):
    """sources: [(名字, 地址)]。返回能用的源，按速度从快到慢。"""
    res = []

    def one(name, url):
        t0 = time.time()
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(10, read=10), headers=UA) as c:
                with c.stream("GET", url, headers={"Range": f"bytes=0-{sample - 1}"}) as r:
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f"HTTP {r.status_code}")
                    total, ranged, got = _total(r), r.status_code == 206, 0
                    for chunk in r.iter_bytes(1 << 16):
                        got += len(chunk)
                        if got >= sample or time.time() - t0 > limit:
                            break
            dt = max(time.time() - t0, 0.05)
            res.append({"name": name, "url": url, "total": total, "ranged": ranged, "speed": got / dt})
            say(f"  {name}：能用，测速 {got / dt / 2**20:.1f} MB/s" + (f"，文件 {total / 2**30:.2f} GB" if total else "") + ("" if ranged else "（不支持分段，只能单线程）"))
        except Exception as e:
            res.append({"name": name, "url": url, "err": str(e)[:120]})
            say(f"  {name}：连不上（{str(e)[:80]}）", "!")

    ts = [threading.Thread(target=one, args=s, daemon=True) for s in sources]
    for t in ts:
        t.start()
    for t in ts:
        t.join(limit + 15)
    return sorted([r for r in res if "err" not in r and r["total"]], key=lambda r: -r["speed"])


def download(src, dest: Path, phase="下载"):
    """多线程分段下载到 dest。src 是 probe() 返回的一项。"""
    url, total, name = src["url"], src["total"], src["name"]
    part, meta = dest.with_name(dest.name + ".part"), dest.with_name(dest.name + ".part.json")
    n = (total + CHUNK - 1) // CHUNK
    done = set()
    try:
        m = json.loads(meta.read_text("utf-8"))
        if m.get("total") == total and m.get("chunk") == CHUNK and part.exists() and part.stat().st_size == total:
            done = set(m.get("done", []))
            if done:
                say(f"接着上次下：{n} 段里已经下好 {len(done)} 段，只下剩下的")
    except Exception:
        pass
    if not done or not part.exists():
        done = set()
        with open(part, "wb") as f:
            f.truncate(total)
    lock = threading.Lock()
    todo = [i for i in range(n) if i not in done]
    state = {"bytes": sum(min(CHUNK, total - i * CHUNK) for i in done), "err": None, "fails": 0}
    if not src.get("ranged"):
        todo, done, state["bytes"] = [0], set(), 0          # 不支持分段：只能一条连接从头下

    def worker():
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(20, read=30), headers=UA) as c, open(part, "r+b") as f:
            while True:
                with lock:
                    if state["err"] or not todo:
                        return
                    i = todo.pop(0)
                a = i * CHUNK
                b = min(total, a + CHUNK) - 1 if src.get("ranged") else total - 1
                for attempt in range(6):
                    got = 0
                    try:
                        hdr = {"Range": f"bytes={a}-{b}"} if src.get("ranged") else {}
                        with c.stream("GET", url, headers=hdr) as r:
                            if r.status_code not in (200, 206):
                                raise RuntimeError(f"HTTP {r.status_code}")
                            f.seek(a)
                            for chunk in r.iter_bytes(1 << 16):
                                f.write(chunk)
                                got += len(chunk)
                                with lock:
                                    state["bytes"] += len(chunk)
                        if got != b - a + 1:
                            raise RuntimeError(f"这一段只拿到 {got} / {b - a + 1} 字节")
                        with lock:
                            done.add(i)
                        break
                    except Exception as e:
                        with lock:
                            state["bytes"] -= got
                            state["fails"] += 1
                        if attempt == 5:
                            with lock:
                                state["err"] = f"第 {i} 段下载失败：{str(e)[:100]}"
                            return
                        time.sleep(1.5 * (attempt + 1))

    workers = [threading.Thread(target=worker, daemon=True) for _ in range(CONNS if src.get("ranged") else 1)]
    for w in workers:
        w.start()
    hist, last_save = [], 0.0
    while any(w.is_alive() for w in workers):
        time.sleep(0.5)
        now = time.time()
        with lock:
            cur = state["bytes"]
            snap = sorted(done)
        hist.append((now, cur))
        hist = [h for h in hist if now - h[0] <= 5]
        speed = (hist[-1][1] - hist[0][1]) / max(hist[-1][0] - hist[0][0], 0.5) if len(hist) > 1 else 0
        eta = (total - cur) / speed if speed > 1 else None
        emit(phase=phase, src=name, done=cur, total=total, speed=speed, eta=eta)
        if now - last_save > 2:
            last_save = now
            meta.write_text(json.dumps({"total": total, "chunk": CHUNK, "done": snap, "url": url}), "utf-8")
    if state["err"]:
        meta.write_text(json.dumps({"total": total, "chunk": CHUNK, "done": sorted(done), "url": url}), "utf-8")
        raise RuntimeError(state["err"])
    if len(done) != n and src.get("ranged"):
        raise RuntimeError(f"还差 {n - len(done)} 段没下完")
    emit(phase=phase, src=name, done=total, total=total, speed=0, eta=0)
    if dest.suffix in (".whl", ".zip"):
        say("下完了，检查文件有没有下坏：把压缩包里每个文件都解一遍、对校验码（3GB 要一两分钟）")
        bad = check_zip(part, name)
        if bad:
            meta.unlink(missing_ok=True)
            part.rename(part.with_name(part.name + f".坏的-{int(time.time())}"))
            raise RuntimeError(f"文件下坏了（{bad}），下次会重新下")
        say("文件是好的", "✓")
    part.replace(dest)
    meta.unlink(missing_ok=True)
    say(f"下好了，放在 {dest}（{total / 2**30:.2f} GB）", "✓")
    return dest


def check_zip(path, src=""):
    """逐个文件解压一遍、对 CRC 校验码，边做边报进度。返回第一个坏掉的文件名；都好返回 None。"""
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        total = sum(i.compress_size for i in infos) or 1
        done, last, t0 = 0, 0.0, time.time()
        for i in infos:
            try:
                with z.open(i) as f:
                    while f.read(1 << 20):
                        pass
            except Exception:
                return i.filename
            done += i.compress_size
            now = time.time()
            if now - last > 0.5:
                last = now
                rate = done / max(now - t0, 0.1)
                emit(phase="检查文件", src=src, done=done, total=total, speed=rate, eta=(total - done) / rate if rate else None)
        emit(phase="检查文件", src=src, done=total, total=total, speed=0, eta=0)
    return None


def fetch(dest: Path, sources, phase="下载"):
    """测速选源 + 下载；最快的源半路不行就换下一个。"""
    dest = Path(dest)
    if dest.exists():
        say(f"{dest.name} 以前已经下好了，直接用", "✓")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    emit(phase="测哪个源最快", src="", done=0, total=0, speed=0, eta=None)
    say(f"要下载 {dest.name}。先同时测 {len(sources)} 个下载源哪个最快（{'、'.join(n for n, _ in sources)}，各下 3MB）")
    ok = probe(sources)
    if not ok:
        raise RuntimeError("所有下载源都连不上")
    say(f"测完了：最快的是「{ok[0]['name']}」（{ok[0]['speed'] / 2**20:.1f} MB/s）", "✓")
    last = None
    for s in ok:
        say(f"用「{s['name']}」下载，{f'{CONNS} 条连接分段一起下（每段 {CHUNK >> 20}MB）' if s['ranged'] else '只能一条连接'}，文件 {s['total'] / 2**30:.2f} GB")
        try:
            return download(s, dest, phase)
        except Exception as e:
            last = e
            say(f"「{s['name']}」中途不行了：{e}，换下一个源", "!")
    raise RuntimeError(f"都没下成：{last}")


if __name__ == "__main__":
    out, urls = Path(sys.argv[1]), sys.argv[2:]
    fetch(out, [(f"源{i + 1}", u) for i, u in enumerate(urls)])
