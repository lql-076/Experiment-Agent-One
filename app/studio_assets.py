r"""视频工坊 · 只读媒体接口（v4.0.1 / R12）。

给灯箱、<audio>、<video> 用。只认两个根：
  工作区\视频工坊\<项目>\...      图、GIF、SVG、PPT 幻灯片、封面、配音、配乐、成片
  工作区\视频工坊\_cache\...       内容寻址缓存

规矩：
  - 绝对路径、盘符、..、NUL、解析后越界（含符号链接指到外面）一律拒绝。
  - 只给图片 / 音频 / 视频；文件头对不上就拒绝（改后缀骗不过去）。
  - SVG 当不可信内容：响应带 sandbox CSP，前端只用 <img> 内嵌。
  - 用 FileResponse（Starlette 原生支持 Accept-Ranges / 206），<audio>/<video> 能拖动进度条。
  - 只读，不写、不删、不创建任何文件。
"""
import hashlib
import re
import struct
from pathlib import Path

from . import imagegen, paths, video_maker

MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
             ".wav", ".mp3", ".flac", ".ogg", ".m4a",
             ".mp4", ".webm", ".mov", ".mkv"}
MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml",
        "wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac", "ogg": "audio/ogg", "m4a": "audio/mp4",
        "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "mkv": "video/x-matroska"}
KIND = {"png": "image", "jpg": "image", "webp": "image", "gif": "image", "svg": "image",
        "wav": "audio", "mp3": "audio", "flac": "audio", "ogg": "audio", "m4a": "audio",
        "mp4": "video", "webm": "video", "mov": "video", "mkv": "video"}
MAX_IMAGE = 80 << 20
MAX_MEDIA = 512 << 20
HEAD = 256 << 10
PART_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


class AssetError(RuntimeError):
    pass


def studio_root() -> Path:
    from . import workspace
    d = workspace.folder() / "视频工坊"
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def cache_root() -> Path:
    return (studio_root() / "_cache").resolve()


def _under(root: Path, p: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def safe_path(rel, root: Path) -> Path:
    s = str(rel or "").replace("\\", "/").strip()
    if not s or "\x00" in s:
        raise AssetError("没给文件路径")
    if s.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", s):
        raise AssetError("只收工坊里的相对路径")
    parts = [x for x in s.split("/") if x not in ("", ".")]
    if any(x == ".." for x in parts):
        raise AssetError("路径不能带 ..")
    if not parts:
        raise AssetError("没给文件路径")
    root = root.resolve()
    q = (root / Path(*parts)).resolve(strict=False)
    if q != root and not _under(root, q):
        raise AssetError("这个文件不在工坊目录里")
    if not q.is_file():
        raise AssetError("没有这个文件")
    ext = q.suffix.lower()
    if ext not in MEDIA_EXT:
        raise AssetError("只给图片 / 音频 / 视频：PNG / JPEG / WEBP / GIF / SVG / WAV / MP3 / FLAC / OGG / MP4 / WEBM")
    cap = MAX_IMAGE if KIND.get(ext.lstrip(".")) == "image" else MAX_MEDIA
    if q.stat().st_size > cap:
        raise AssetError("文件太大了（超过 %dMB）" % (cap >> 20))
    fmt = detect(q)
    want = ext.lstrip(".")
    if want == "jpeg":
        want = "jpg"
    if fmt != want:
        raise AssetError("文件内容和后缀对不上（后缀是 %s，里面是 %s）" % (want, fmt or "未知"))
    return q


def detect(path) -> str:
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    if ext in ("png", "jpg", "jpeg", "webp", "gif", "svg"):
        try:
            return imagegen.png_info(_head(p)).get("fmt") or ""
        except imagegen.ImgError:
            return ""
    with open(p, "rb") as f:
        head = f.read(4096)
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "m4a" if ext == "m4a" else "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if len(head) >= 12 and head[4:8] in (b"moov", b"mdat", b"wide", b"free"):
        return "mov" if ext == "mov" else "mp4"
    return ""


def project_asset(pid, rel) -> Path:
    d = video_maker.project_path(pid)
    return safe_path(rel, d)


def cache_asset(rel) -> Path:
    return safe_path(rel, cache_root())


def gif_info(path) -> dict:
    b = Path(path).read_bytes()
    if b[:6] not in (b"GIF87a", b"GIF89a"):
        return {"frames": 0, "duration_ms": 0}
    frames, total, delay = 0, 0, 0
    i = 6
    if len(b) < 13:
        return {"frames": 0, "duration_ms": 0}
    flags = b[10]
    i = 13
    if flags & 0x80:
        i += 3 * (2 ** ((flags & 0x07) + 1))
    while i < len(b):
        c = b[i]
        if c == 0x3B:
            break
        if c == 0x21:
            if i + 1 >= len(b):
                break
            label = b[i + 1]
            i += 2
            if label == 0xF9 and i + 5 <= len(b):
                size = b[i]
                if size >= 4 and i + 3 < len(b):
                    delay = struct.unpack("<H", b[i + 2:i + 4])[0]
                i += 1 + size
                i = _skip_blocks(b, i)
            else:
                i = _skip_blocks(b, i + 1)
            continue
        if c == 0x2C:
            if i + 10 > len(b):
                break
            lf = b[i + 9]
            i += 10
            if lf & 0x80:
                i += 3 * (2 ** ((lf & 0x07) + 1))
            i += 1
            frames += 1
            total += delay * 10 if delay else 0
            delay = 0
            i = _skip_blocks(b, i)
            continue
        i += 1
    if frames and total <= 0:
        total = frames * 100
    return {"frames": frames, "duration_ms": total}


def _skip_blocks(b, i):
    while i < len(b):
        n = b[i]
        i += 1
        if n == 0:
            return i
        i += n
    return i


def _wav_seconds(p: Path) -> float:
    try:
        data = p.read_bytes()
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return 0.0
        i, byte_rate = 12, 0
        while i + 8 <= len(data):
            cid, n = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
            if cid == b"fmt " and n >= 16 and i + 24 <= len(data):
                byte_rate = struct.unpack("<I", data[i + 16:i + 20])[0]
            if cid == b"data":
                if byte_rate:
                    return round(n / byte_rate, 2)
                break
            i += 8 + n + (n & 1)
        return 0.0
    except Exception:
        return 0.0


def info(path) -> dict:
    p = Path(path)
    st = p.stat()
    fmt = detect(p)
    if fmt not in MIME:
        raise AssetError("这个文件不是能播放的图片 / 音频 / 视频（文件头对不上）")
    out = {"fmt": fmt, "mime": MIME[fmt], "kind": KIND.get(fmt, "file"), "w": 0, "h": 0, "alpha": False,
           "size": st.st_size, "mtime": st.st_mtime, "name": p.name, "sha256": _sha(p),
           "frames": 0, "duration_ms": 0, "duration": 0.0}
    if fmt in ("png", "jpg", "webp", "gif", "svg"):
        pi = imagegen.png_info(_head(p))
        out.update({"w": int(pi.get("w") or 0), "h": int(pi.get("h") or 0), "alpha": bool(pi.get("alpha"))})
        if fmt == "gif":
            out.update(gif_info(p))
    elif fmt == "wav":
        sec = _wav_seconds(p)
        out.update({"duration": sec, "duration_ms": int(sec * 1000)})
    return out


def _head(p: Path) -> bytes:
    with open(p, "rb") as f:
        return f.read(HEAD)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_response(path):
    from fastapi.responses import FileResponse
    p = Path(path)
    pi = info(p)
    headers = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff",
               "Accept-Ranges": "bytes",
               "Content-Disposition": f'inline; filename="{p.name.encode("ascii", "ignore").decode() or "media.bin"}"'}
    if pi["fmt"] == "svg":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:"
    return FileResponse(p, media_type=pi["mime"], headers=headers)


def reveal(path):
    p = Path(path)
    if not paths.IS_WIN:
        return {"msg": "文件夹在：" + paths.show(p.parent)}
    import subprocess
    NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["explorer", "/select,", str(p)], creationflags=NOWIN)
    return {"msg": "打开了所在文件夹：" + paths.show(p.parent)}
