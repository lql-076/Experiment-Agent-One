r"""视频工坊 · 内容寻址缓存（v3.8，R08）。

目标：同一条生图/配音/配乐参数，不管在哪个项目、哪次重跑，只要指纹完全一样，就直接复用文件，
不再调用付费 API / 本地模型。

存哪：
  工作区\视频工坊\_cache\
    cache_index.json         全局索引：sha256 → {kind, path, ts, meta}
    image\<前2位>\<sha>.png|jpg|webp|gif
    tts\<前2位>\<sha>.wav
    bgm\<前2位>\<sha>.wav
  项目文件夹\cache_index.json  这个项目每个子节点的指纹和最后产出（只存相对路径）

指纹：调用方把参数整理成 dict，这里做 json.dumps(sort_keys=True) 后 sha256。
所有文件写入都是原子写；索引有锁，多个并发任务不会写坏。
"""
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

from . import paths

_LOCK = threading.RLock()


def cache_root() -> Path:
    from . import workspace
    d = workspace.folder() / "视频工坊" / "_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return cache_root() / "cache_index.json"


def _read(path, default):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except Exception:
        return default


def _write(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(p)


def sha_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(kind: str, params: dict) -> str:
    blob = json.dumps({"kind": kind, "params": params}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def lookup(fp: str, kind: str = ""):
    """全局缓存命中返回 Path，否则 None。"""
    with _LOCK:
        idx = _read(_index_path(), {})
        x = idx.get(fp)
    if not x:
        return None
    p = Path(x.get("path") or "")
    if p.is_file() and (not kind or x.get("kind") == kind):
        return p
    return None


def put(fp: str, src, kind: str, meta=None) -> Path:
    """把文件复制进全局缓存；同名指纹已经存在就不重复写。返回缓存路径。"""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(src)
    ext = src.suffix.lower() or ".bin"
    d = cache_root() / kind / fp[:2]
    d.mkdir(parents=True, exist_ok=True)
    dest = d / (fp + ext)
    with _LOCK:
        if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
            tmp = dest.with_name(dest.name + ".part")
            shutil.copy2(src, tmp)
            tmp.replace(dest)
        idx = _read(_index_path(), {})
        idx[fp] = {"kind": kind, "path": str(dest), "ts": time.time(), "meta": meta or {}}
        # 索引太大时只留最近 4000 条（老缓存文件不删，仍可按路径命中）
        if len(idx) > 4000:
            keep = sorted(idx.items(), key=lambda kv: kv[1].get("ts") or 0, reverse=True)[:4000]
            idx = dict(keep)
        _write(_index_path(), idx)
    return dest


def hit_to(fp: str, dest, kind: str = ""):
    """全局命中就复制到 dest（项目里的产出路径），返回 True。"""
    p = lookup(fp, kind)
    if not p:
        return False
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    shutil.copy2(p, tmp)
    tmp.replace(dest)
    return True


def project_index(project_dir) -> Path:
    return Path(project_dir) / "cache_index.json"


def project_get(project_dir, key: str):
    idx = _read(project_index(project_dir), {})
    return idx.get(key) or None


def project_set(project_dir, key: str, fp: str, rel: str, cache_hit: bool, meta=None):
    with _LOCK:
        p = project_index(project_dir)
        idx = _read(p, {})
        idx[key] = {"fp": fp, "path": rel, "cache_hit": bool(cache_hit), "ts": time.time(), "meta": meta or {}}
        _write(p, idx)


def project_drop(project_dir, key: str):
    with _LOCK:
        p = project_index(project_dir)
        idx = _read(p, {})
        if key in idx:
            idx.pop(key, None)
            _write(p, idx)
