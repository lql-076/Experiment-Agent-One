"""打包成给用户解压覆盖的压缩包：python dev/pack.py Agent-v1.4.1.zip [输出文件夹，默认 dist/]

- 只打 git 里该有的文件（被跟踪的 + 还没提交但没被 .gitignore 排除的），所以压缩包和仓库内容一致。
  数据、记忆、密钥、模型、环境本来就被 .gitignore 排除，不会进包；打完再按"禁止清单"查一遍，有就报错不出包。
- .bat 一律 CRLF（Windows 的 cmd 对只有 LF 的批处理有怪毛病）。
- 用 zipfile 写：中文文件名自动带 UTF-8 标记，Windows 解压不乱码。
"""
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBID = ("data/", "memory/", "ai-env/", "tts-env/", "配音输出/", "生图输出/", ".venv/", "tools/cache/", "tools/tmp/", "models/hf-cache/", "models/ms-cache/")
FORBID_EXT = (".db", ".bin", ".safetensors", ".gguf", ".whl", ".pt", ".pth", ".env", ".jsonl", ".wav")


def files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", "-z"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    return sorted(f for f in out.split("\0") if f and (ROOT / f).is_file())


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Agent.zip"
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "dist"
    outdir.mkdir(parents=True, exist_ok=True)
    dst = outdir / name
    fs = files()
    bad = [f for f in fs if f.startswith(FORBID) or f.endswith(FORBID_EXT)]
    if bad:
        sys.exit("这些不该进包，先检查 .gitignore：\n  " + "\n  ".join(bad))
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in fs:
            p = ROOT / f
            data = p.read_bytes()
            if f.endswith(".bat"):
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            zi = zipfile.ZipInfo("Agent/" + f, time.localtime(p.stat().st_mtime)[:6])
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)
    z = zipfile.ZipFile(dst)
    cn = [i for i in z.infolist() if any(ord(c) > 127 for c in i.filename)]
    print(f"{dst}：{len(z.infolist())} 个文件，{dst.stat().st_size / 1024:.0f} KB；"
          f"中文名 {len(cn)} 个，UTF-8 标记{'都有' if all(i.flag_bits & 0x800 for i in cn) else '有缺的！'}")


if __name__ == "__main__":
    main()
