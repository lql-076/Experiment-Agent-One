r"""视频工坊 · 高清灯箱的只读取图接口（v3.9.0 / R10）。

只认两个根：
  工作区\视频工坊\<项目>\...      节点产出的图、GIF、SVG、PPT 幻灯片、封面
  工作区\视频工坊\_cache\...       内容寻址缓存里的原图/轨道
规矩：
  - 绝对路径、盘符、..、NUL、解析后越界（含符号链接指到外面）一律拒绝。
  - 只给图片：PNG / JPEG / WEBP / GIF / SVG；文件头对不上就拒绝（改后缀骗不过去）。
  - SVG 当不可信内容：响应带 sandbox CSP，前端只用 <img> 内嵌，不执行脚本。
  - 只读，不写、不删、不创建任何文件。
"""
import hashlib
import re
import struct
from pathlib import Path

from . import imagegen, paths, video_maker

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml"}
MAX_BYTES = 80 << 20          # 单张图最大 80MB，防止误点一个巨大文件把界面卡死
HEAD = 256 << 10              # 只读文件头判尺寸（JPEG 的 SOF 一般在很前面）
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
    """相对路径 → 根目录下的真实文件；任何越界/怪路径都拒绝。"""
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
    if q.suffix.lower() not in IMG_EXT:
        raise AssetError("只给图片：PNG / JPEG / WEBP / GIF / SVG")
    if q.stat().st_size > MAX_BYTES:
        raise AssetError("图片太大了（超过 80MB）")
    try:
        fmt = imagegen.png_info(_head(q)).get("fmt") or ""
    except imagegen.ImgError:
        raise AssetError("这个文件不是能看的图片（文件头对不上）") from None
    want = q.suffix.lower().lstrip(".")
    if want == "jpeg":
        want = "jpg"
    if fmt != want:
        raise AssetError("文件内容和后缀对不上（后缀是 %s，里面是 %s）" % (want, fmt or "未知"))
    return q


def project_asset(pid, rel) -> Path:
    d = video_maker.project_path(pid)
    return safe_path(rel, d)


def cache_asset(rel) -> Path:
    return safe_path(rel, cache_root())


def gif_info(path) -> dict:
    """GIF 的帧数和总时长（毫秒）。只读文件，不依赖 Pillow。"""
    b = Path(path).read_bytes()
    if b[:6] not in (b"GIF87a", b"GIF89a"):
        return {"frames": 0, "duration_ms": 0}
    frames, total, delay = 0, 0, 0
    i = 6
    if len(b) < 13:
        return {"frames": 0, "duration_ms": 0}
    flags = b[10]
    i = 13
    if flags & 0x80:                                 # 全局调色板
        i += 3 * (2 ** ((flags & 0x07) + 1))
    while i < len(b):
        c = b[i]
        if c == 0x3B:                                # trailer
            break
        if c == 0x21:                                # extension
            if i + 1 >= len(b):
                break
            label = b[i + 1]
            i += 2
            if label == 0xF9 and i + 5 <= len(b):    # graphic control：延时（1/100 秒）
                size = b[i]
                if size >= 4 and i + 3 < len(b):
                    delay = struct.unpack("<H", b[i + 2:i + 4])[0]
                i += 1 + size
                i = _skip_blocks(b, i)
            else:
                i = _skip_blocks(b, i + 1)
            continue
        if c == 0x2C:                                # image descriptor
            if i + 10 > len(b):
                break
            lf = b[i + 9]
            i += 10
            if lf & 0x80:
                i += 3 * (2 ** ((lf & 0x07) + 1))
            i += 1                                   # LZW 最小码长
            frames += 1
            total += delay * 10 if delay else 0
            delay = 0
            i = _skip_blocks(b, i)
            continue
        i += 1
    if frames and total <= 0:
        total = frames * 100                         # 没写延时：浏览器默认 10fps
    return {"frames": frames, "duration_ms": total}


def _skip_blocks(b, i):
    while i < len(b):
        n = b[i]
        i += 1
        if n == 0:
            return i
        i += n
    return i


def info(path) -> dict:
    p = Path(path)
    st = p.stat()
    head = _head(p)
    try:
        pi = imagegen.png_info(head)
    except imagegen.ImgError:
        raise AssetError("这个文件不是能看的图片") from None
    fmt = pi.get("fmt") or p.suffix.lower().lstrip(".")
    if fmt not in MIME:
        raise AssetError("只给图片：PNG / JPEG / WEBP / GIF / SVG")
    if p.suffix.lower() not in IMG_EXT:
        raise AssetError("只给图片：PNG / JPEG / WEBP / GIF / SVG")
    out = {"fmt": fmt, "mime": MIME[fmt], "w": int(pi.get("w") or 0), "h": int(pi.get("h") or 0),
           "alpha": bool(pi.get("alpha")), "size": st.st_size, "mtime": st.st_mtime,
           "name": p.name, "sha256": _sha(p), "frames": 0, "duration_ms": 0}
    if fmt == "gif":
        g = gif_info(p)
        out.update(g)
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
    """给 FastAPI 的 FileResponse：带正确的类型和 SVG 的 sandbox CSP。"""
    from fastapi.responses import FileResponse
    p = Path(path)
    pi = info(p)
    headers = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff",
               "Content-Disposition": f'inline; filename="{p.name.encode("ascii", "ignore").decode() or "image.jpg"}"'}
    if pi["fmt"] == "svg":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:"
    return FileResponse(p, media_type=pi["mime"], headers=headers)


def reveal(path):
    """在资源管理器里选中这个文件（只给工坊里的文件）。"""
    p = Path(path)
    if not paths.IS_WIN:
        return {"msg": "文件夹在：" + paths.show(p.parent)}
    import subprocess
    NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["explorer", "/select,", str(p)], creationflags=NOWIN)
    return {"msg": "打开了所在文件夹：" + paths.show(p.parent)}
