"""视频、音频、图片的时长和分辨率（v2.3）：只读文件头，不装 ffmpeg、不加依赖。
认 MP4 / MOV / M4A、WEBM / MKV、WAV、MP3、FLAC、OGG，和 PNG / JPEG / GIF / WEBP。认不出就返回空，不报错。
用在：对话里收到的文件（告诉 DeepSeek 这段视频多长、多大）、做好的文件卡片。"""
import struct
from pathlib import Path

VIDEO_EXT = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".3gp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
HEAD = 4 << 20                       # 最多看前 4MB（MP4 的 moov 在文件尾时另外找）


def kind(p) -> str:
    ext = Path(p).suffix.lower()
    return "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else "image" if ext in IMAGE_EXT else ""


# ---------------- MP4 / MOV / M4A ----------------
def _atoms(f, start, end):
    """一层里的盒子：(名字, 内容开始, 内容结束)。"""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        h = f.read(16)
        if len(h) < 8:
            return
        size, name = struct.unpack(">I4s", h[:8])
        head = 8
        if size == 1 and len(h) >= 16:
            size, head = struct.unpack(">Q", h[8:16])[0], 16
        elif size == 0:
            size = end - pos
        if size < head:
            return
        yield name, pos + head, min(pos + size, end)
        pos += size


def _mp4(f, total):
    out = {}
    moov = next(((a, b) for n, a, b in _atoms(f, 0, total) if n == b"moov"), None)
    if not moov:
        return out
    for n, a, b in _atoms(f, *moov):
        if n == b"mvhd":
            f.seek(a)
            d = f.read(32)
            if d and d[0] == 1:
                ts, dur = struct.unpack(">IQ", d[20:32])
            else:
                ts, dur = struct.unpack(">II", d[12:20])
            if ts:
                out["duration"] = dur / ts
        elif n == b"trak":
            for n2, a2, b2 in _atoms(f, a, b):
                if n2 == b"tkhd":
                    f.seek(b2 - 8)
                    w, h = struct.unpack(">II", f.read(8))
                    if w >> 16 and h >> 16 and "w" not in out:
                        out["w"], out["h"] = w >> 16, h >> 16
    return out


# ---------------- WEBM / MKV（EBML）----------------
def _vint(b, i, keep=False):
    if i >= len(b):
        raise IndexError
    first = b[i]
    n = 1
    while n <= 8 and not first & (0x80 >> (n - 1)):
        n += 1
    if n > 8 or i + n > len(b):
        raise IndexError
    v = first if keep else first & (0xFF >> n)
    for k in range(1, n):
        v = (v << 8) | b[i + k]
    return v, i + n


MASTERS = {0x18538067, 0x1549A966, 0x1654AE6B, 0xAE, 0xE0}      # Segment、Info、Tracks、TrackEntry、Video


def _ebml(b):
    out, scale, dur = {}, 1_000_000, None

    def walk(i, end, depth=0):
        nonlocal scale, dur
        while i < end and depth < 6:
            try:
                eid, i = _vint(b, i, keep=True)
                size, i = _vint(b, i)
            except IndexError:
                return
            unknown = size in (0x7F, 0x3FFF, 0x1FFFFF, 0x0FFFFFFF, 0xFFFFFFFFFFFFFF)
            stop = end if unknown else min(i + size, end)
            if eid in MASTERS:
                walk(i, stop, depth + 1)
            elif eid == 0x2AD7B1:
                scale = int.from_bytes(b[i:stop], "big") or scale
            elif eid == 0x4489:
                d = b[i:stop]
                dur = struct.unpack(">f" if len(d) == 4 else ">d", d)[0] if len(d) in (4, 8) else None
            elif eid == 0xB0 and "w" not in out:
                out["w"] = int.from_bytes(b[i:stop], "big")
            elif eid == 0xBA and "h" not in out:
                out["h"] = int.from_bytes(b[i:stop], "big")
            elif eid == 0x1F43B675:                 # Cluster：后面都是画面数据，不用看了
                return
            i = stop
    walk(0, len(b))
    if dur:
        out["duration"] = dur * scale / 1e9
    return out


# ---------------- 音频 ----------------
def _wav(b, total):
    if b[:4] != b"RIFF" or b[8:12] != b"WAVE":
        return {}
    i, rate = 12, 0
    while i + 8 <= len(b):
        cid, size = b[i:i + 4], struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"fmt ":
            rate = struct.unpack("<I", b[i + 16:i + 20])[0]            # 每秒多少字节
        elif cid == b"data" and rate:
            return {"duration": min(size, total - i - 8) / rate}
        i += 8 + size + (size & 1)
    return {}


MP3_BR = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
MP3_BR2 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
MP3_SR = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _mp3(b, total):
    i = 0
    if b[:3] == b"ID3" and len(b) > 10:
        i = 10 + ((b[6] & 0x7F) << 21 | (b[7] & 0x7F) << 14 | (b[8] & 0x7F) << 7 | (b[9] & 0x7F))
    while i + 4 < len(b):
        if b[i] == 0xFF and b[i + 1] & 0xE0 == 0xE0:
            ver, layer = (b[i + 1] >> 3) & 3, (b[i + 1] >> 1) & 3
            bri, sri = b[i + 2] >> 4, (b[i + 2] >> 2) & 3
            if ver != 1 and layer == 1 and 0 < bri < 15 and sri < 3:
                sr = MP3_SR[ver][sri]
                br = (MP3_BR if ver == 3 else MP3_BR2)[bri] * 1000
                spf = 1152 if ver == 3 else 576
                for tag in (b"Xing", b"Info"):                       # 有帧数就按帧数算（可变码率也准）
                    k = b.find(tag, i, i + 200)
                    if k > 0 and struct.unpack(">I", b[k + 4:k + 8])[0] & 1:
                        return {"duration": struct.unpack(">I", b[k + 8:k + 12])[0] * spf / sr}
                return {"duration": (total - i) * 8 / br} if br else {}
        i += 1
    return {}


def _flac(b):
    if b[:4] != b"fLaC" or len(b) < 42:
        return {}
    x = int.from_bytes(b[18:26], "big")
    rate, n = x >> 44, x & ((1 << 36) - 1)
    return {"duration": n / rate} if rate and n else {}


def _ogg(f, b, total):
    rate = 0
    k = b.find(b"\x01vorbis")
    if k >= 0:
        rate = struct.unpack("<I", b[k + 12:k + 16])[0]
    elif b.find(b"OpusHead") >= 0:
        rate = 48000
    if not rate:
        return {}
    f.seek(max(0, total - 65536))
    tail = f.read()
    k = tail.rfind(b"OggS")
    if k < 0 or k + 14 > len(tail):
        return {}
    return {"duration": struct.unpack("<q", tail[k + 6:k + 14])[0] / rate}


# ---------------- 图片 ----------------
def _image(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", b[16:24])
        return {"w": w, "h": h}
    if b[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", b[6:10])
        return {"w": w, "h": h}
    if b[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            mk = b[i + 1]
            if mk in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", b[i + 5:i + 9])
                return {"w": w, "h": h}
            i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
        return {}
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        c = b[12:16]
        if c == b"VP8X":
            return {"w": int.from_bytes(b[24:27], "little") + 1, "h": int.from_bytes(b[27:30], "little") + 1}
        if c == b"VP8 ":
            w, h = struct.unpack("<HH", b[26:30])
            return {"w": w & 0x3FFF, "h": h & 0x3FFF}
        if c == b"VP8L":
            x = int.from_bytes(b[21:25], "little")
            return {"w": (x & 0x3FFF) + 1, "h": ((x >> 14) & 0x3FFF) + 1}
    return {}


def probe(path) -> dict:
    """{kind, duration（秒）, w, h}，认不出的那几项就没有。"""
    p = Path(path)
    k = kind(p)
    out = {"kind": k} if k else {}
    if not k:
        return out
    try:
        total = p.stat().st_size
        ext = p.suffix.lower()
        with open(p, "rb") as f:
            b = f.read(HEAD)
            if b[4:8] in (b"ftyp", b"moov", b"free", b"wide", b"mdat", b"skip") or ext in (".mp4", ".m4v", ".mov", ".m4a", ".3gp"):
                out.update(_mp4(f, total))
            elif b[:4] == b"\x1a\x45\xdf\xa3":
                out.update(_ebml(b))
            elif b[:4] == b"RIFF" and b[8:12] == b"WAVE":
                out.update(_wav(b, total))
            elif b[:4] == b"fLaC":
                out.update(_flac(b))
            elif b[:4] == b"OggS":
                out.update(_ogg(f, b, total))
            elif k == "image":
                out.update(_image(b))
            elif ext == ".mp3" or b[:3] == b"ID3":
                out.update(_mp3(b, total))
    except (OSError, struct.error, ValueError, IndexError, ZeroDivisionError, OverflowError):
        pass
    if out.get("duration") is not None and not 0 < out["duration"] < 360000:
        out.pop("duration")
    return out


def clock(sec) -> str:
    sec = float(sec)
    if sec < 60:
        return f"{sec:.1f} 秒"
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h} 小时 {m:02d} 分 {s:02d} 秒" if h else f"{m} 分 {s:02d} 秒"


def describe(path) -> str:
    """一句话：「视频 · 1 分 05 秒 · 1920×1080」；认不出返回空。"""
    i = probe(path)
    if not i:
        return ""
    bits = [{"video": "视频", "audio": "音频", "image": "图片"}[i["kind"]]]
    if i.get("duration"):
        bits.append(clock(i["duration"]))
    if i.get("w") and i.get("h"):
        bits.append(f"{i['w']}×{i['h']}")
    return " · ".join(bits) if len(bits) > 1 else ""
