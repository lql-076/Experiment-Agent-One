r"""Git 安全同步 + 隐私安检（v3.4）。

用途：
  python dev/git_sync.py                 # 安检 → git add → commit → push（默认 main）
  python dev/git_sync.py --check         # 只安检（全树 + 暂存区）
  python dev/git_sync.py --guard pre-commit   # 给 .git/hooks/pre-commit 用：只查暂存区
  python dev/git_sync.py --guard pre-push     # 给 .git/hooks/pre-push 用：查待推送的提交
  python dev/git_sync.py --install-hooks # 只装钩子
  python dev/git_sync.py --no-push       # 只本地提交，不推

刚性护栏：
- 黑名单路径：运行时数据、模型、环境、输出、下载缓存、任何 `.env*` / `*.key` / `*.pem` / `*secret*` / `*token*`。
- 敏感内容正则：API Key、HF token、Google key、Bearer token、QQ appId/appSecret/token、QQ 号、个人目录路径。
- 只报告“哪个文件哪一行命中哪一类”，不把密钥原文打到终端/日志里（只显示前 4 位 + ***）。
- 绝不 `--force` 推送；远端有分叉就失败并让人处理。

所有 git 子进程都带 CREATE_NO_WINDOW（Windows），不弹黑窗口。
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_REMOTE = "https://github.com/lql-076/Experiment-Agent-One"
DEFAULT_MESSAGE = ("v4.0.1：视频工坊修复音频/视频播放与 Range、多模块真并发、全模块实时进度条；"
                   "原有页面保持不变")

# ---------- 黑名单：路径 ----------
DIRS = (
    "data/", "models/", "memory/", "记忆/", "training/", "工作区/", "工作区备份/", "配音输出/", "配乐输出/", "生图输出/",
    "dist/", ".venv/", "ai-env/", "tts-env/", "bgm-env/", "ws-env/",
    "tools/wheels/", "tools/downloads/", "tools/cache/", "tools/tmp/", "tools/7z/", "tools/git/",
    "ace-step", "docs/旧版说明",
)
# 允许保留的说明文件（training/ 里的“放这里”说明；handover/ 不在黑名单里，不用列）
ALLOW = ("training/README.md", "training/放这里.txt")
FILE_BAD = re.compile(r"(^|/)(\.env[^/]*|[^/]*\.(key|pem)|[^/]*secret[^/]*|[^/]*token[^/]*)$", re.I)

# ---------- 黑名单：内容 ----------
PATTERNS = [
    ("API Key（sk-）", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("Hugging Face token（hf_）", re.compile(r"\bhf_[A-Za-z0-9]{16,}\b")),
    ("Google API Key（AIza）", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b")),
    ("QQ appSecret", re.compile(r"\bappSecret\b\s*[:=]\s*['\"]?[A-Za-z0-9]{16,}", re.I)),
    ("QQ appId", re.compile(r"\bappId\b\s*[:=]\s*['\"]?\d{6,}", re.I)),
    ("token 字段", re.compile(r"\btoken\b\s*[:=]\s*['\"][A-Za-z0-9._\-]{16,}", re.I)),
    ("QQ 号", re.compile(r"(?:QQ|qq|扣扣)\s*(?:号|号码)?\s*[:：=]\s*[1-9]\d{4,11}\b")),
    ("个人目录路径", re.compile(r"(?:[A-Za-z]:\\Users\\[^\\\s]+|/home/[A-Za-z0-9._-]+|AppData\\Roaming)")),
    ("项目私有数据路径", re.compile(r"[A-Za-z]:\\Agent\\(?:data|memory|工作区|配音输出|配乐输出|生图输出)\\", re.I)),
]
# 明显是占位/测试的值，放行
SAFE_VALUES = re.compile(r"(?:sk-test-0000|sk-xxx+|hf_xxx+|AIza\.{3}|Bearer\s+<|Bearer\s+\{)")


def git(*args, check=False):
    p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, errors="replace",
                       creationflags=NOWIN, stdin=subprocess.DEVNULL)
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip()[:500])
    return p


def is_repo():
    return git("rev-parse", "--is-inside-work-tree").returncode == 0


def norm(p):
    return str(p or "").replace("\\", "/").lstrip("./")


def path_bad(p):
    p = norm(p)
    if not p:
        return ""
    for a in ALLOW:
        if p == a or p.startswith(a.rstrip("/") + "/") or p.startswith(a):
            return ""
    for d in DIRS:
        d = d.rstrip("/")
        if p == d or p.startswith(d + "/"):
            return f"黑名单目录 {d}/"
    if FILE_BAD.search(p):
        return "黑名单文件名（.env / .key / .pem / secret / token）"
    return ""


def redact(s):
    s = str(s)
    return (s[:4] + "***") if len(s) > 4 else "***"


def scan_diff(diff):
    """只扫新增行；报告 文件:行号。"""
    bad, cur, new_line = [], "?", 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_line = int(m.group(1)) if m else 0
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_line += 1
            text = line[1:]
            for name, rx in PATTERNS:
                for m in rx.finditer(text):
                    v = m.group(0)
                    if SAFE_VALUES.search(v):
                        continue
                    bad.append(f"{cur}:{new_line}  {name}：{redact(v)}")
        elif not line.startswith("-"):
            new_line += 1
    return bad


def staged_paths():
    # 只算新增/修改/改名；删除黑名单文件是好事，不能拦
    p = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [x for x in p.stdout.split("\0") if x]


def tree_paths():
    p = git("ls-files", "-z")
    return [x for x in p.stdout.split("\0") if x]


def strip_forbidden():
    """git add -A 会把历史上已经跟踪的黑名单文件又加回来：把它们在索引里删掉（磁盘不动）。"""
    removed = []
    for p in tree_paths():
        if path_bad(p):
            r = git("rm", "--cached", "--ignore-unmatch", "--", p)
            if r.returncode == 0:
                removed.append(p)
    return removed


def base_ref():
    for ref in ("origin/main", "origin/master"):
        if git("rev-parse", "--verify", ref).returncode == 0:
            return ref
    return ""


def audit(staged_only=False, push_range=False):
    """返回 (问题列表, 统计)。staged_only：只查暂存区；否则查全树 + 暂存区。"""
    bad = []
    if not is_repo():
        return ["当前目录不是 Git 仓库：先运行 --install-hooks / 首次同步会 git init"], 0
    paths = list(dict.fromkeys((staged_paths() if staged_only else (tree_paths() + staged_paths()))))
    for p in paths:
        why = path_bad(p)
        if why:
            bad.append(f"{p}  {why}")
    has_head = git("rev-parse", "--verify", "HEAD").returncode == 0
    chunks = []
    if staged_only:
        chunks.append(git("diff", "--cached", "--unified=0", "--no-color").stdout)
    elif push_range:
        base = base_ref()
        if base and has_head:
            chunks.append(git("diff", "--unified=0", "--no-color", f"{base}..HEAD").stdout)
        else:
            chunks.append(git("diff", "--cached", "--unified=0", "--no-color").stdout)
            if has_head:
                chunks.append(git("show", "--format=", "--unified=0", "--no-color", "HEAD").stdout)
    else:
        chunks.append(git("diff", "--cached", "--unified=0", "--no-color").stdout)
        base = base_ref()
        if base and has_head:
            chunks.append(git("diff", "--unified=0", "--no-color", f"{base}..HEAD").stdout)
        elif has_head and git("rev-parse", "--verify", "HEAD~1").returncode == 0:
            chunks.append(git("diff", "--unified=0", "--no-color", "HEAD~1..HEAD").stdout)
        elif has_head:
            chunks.append(git("show", "--format=", "--unified=0", "--no-color", "HEAD").stdout)
    for d in chunks:
        if d:
            bad += scan_diff(d)
    return bad, len(paths)


def install_hooks():
    if not is_repo():
        raise RuntimeError("先 git init / 首次同步，再装钩子")
    hp = git("rev-parse", "--git-path", "hooks").stdout.strip()
    hooks = (ROOT / hp).resolve() if not Path(hp).is_absolute() else Path(hp)
    hooks.mkdir(parents=True, exist_ok=True)
    py = '.venv/Scripts/python.exe'
    sh = f'''#!/bin/sh
ROOT="$(git rev-parse --show-toplevel)"
if [ -x "$ROOT/{py}" ]; then PY="$ROOT/{py}"
elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then PY=python3
else PY=python; fi
exec "$PY" "$ROOT/dev/git_sync.py" --guard @@MODE@@
'''
    for name, mode in (("pre-commit", "pre-commit"), ("pre-push", "pre-push")):
        p = hooks / name
        p.write_text(sh.replace("@@MODE@@", mode), "utf-8", newline="\n")
        try:
            p.chmod(0o755)
        except OSError:
            pass
        print(f"钩子装好了：{p}")
    return hooks


def ensure_repo(remote, branch):
    if is_repo():
        return
    print("当前目录没有 .git：初始化本地仓库（不会覆盖远端历史）")
    r = git("init")
    if r.returncode != 0:
        raise RuntimeError("git init 失败：" + (r.stderr or r.stdout)[:300])
    git("branch", "-M", branch)
    if remote:
        git("remote", "add", "origin", remote)
        print("远端：origin →", remote)


def sync(message, remote, branch, push=True):
    ensure_repo(remote, branch)
    install_hooks()
    rem = git("remote", "get-url", "origin")
    if rem.returncode != 0 and remote:
        git("remote", "add", "origin", remote)
        print("加了远端 origin →", remote)
    print("暂存改动……")
    git("add", "-A")
    gone = strip_forbidden()
    if gone:
        print("从索引里移除黑名单文件（磁盘不删）：" + "、".join(gone[:8]) + (f" 等 {len(gone)} 个" if len(gone) > 8 else ""))
    bad, n = audit(staged_only=True)
    if bad:
        print("\n隐私安检没过，已拦下（不会提交）：")
        for x in bad[:80]:
            print("  -", x)
        if len(bad) > 80:
            print(f"  ……还有 {len(bad) - 80} 条")
        git("reset")
        return 1
    print(f"隐私安检通过（{n} 个暂存文件）")
    st = git("status", "--porcelain").stdout.strip()
    if not st:
        print("没有要提交的改动。")
    else:
        r = git("-c", "user.name=Experiment Agent", "-c", "user.email=agent@localhost",
                "commit", "-m", message)
        if r.returncode != 0:
            print("提交失败：\n" + (r.stdout + r.stderr)[-1200:])
            return 1
        print("提交好了：", git("rev-parse", "--short", "HEAD").stdout.strip())
    if not push:
        print("按 --no-push：没有推送。完整 SHA：", git("rev-parse", "HEAD").stdout.strip())
        return 0
    print(f"推送到 origin/{branch}……")
    r = git("push", "-u", "origin", branch)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        print("推送没成功（没有强推，远端历史没有被覆盖）：\n" + out[-1500:])
        print("完整 SHA：", git("rev-parse", "HEAD").stdout.strip())
        return 2
    print(out[-1000:])
    print("推送成功。完整 SHA：", git("rev-parse", "HEAD").stdout.strip())
    return 0


def main():
    ap = argparse.ArgumentParser(description="Git 安全同步 + 隐私安检")
    ap.add_argument("--check", action="store_true", help="只安检（全树 + 暂存区）")
    ap.add_argument("--guard", choices=("pre-commit", "pre-push"), help="给 Git 钩子用")
    ap.add_argument("--install-hooks", action="store_true", help="只装 pre-commit / pre-push 钩子")
    ap.add_argument("--no-push", action="store_true", help="只提交，不推送")
    ap.add_argument("--message", default=DEFAULT_MESSAGE)
    ap.add_argument("--remote", default=DEFAULT_REMOTE)
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()
    try:
        if args.install_hooks:
            ensure_repo(args.remote, args.branch)
            install_hooks()
            return 0
        if args.guard == "pre-commit":
            bad, n = audit(staged_only=True)
        elif args.guard == "pre-push":
            bad, n = audit(push_range=True)
        elif args.check:
            bad, n = audit(staged_only=False)
        else:
            return sync(args.message, args.remote, args.branch, push=not args.no_push)
        if bad:
            print("隐私安检没过，已拦下：")
            for x in bad[:80]:
                print("  -", x)
            if len(bad) > 80:
                print(f"  ……还有 {len(bad) - 80} 条")
            return 1
        print(f"隐私安检通过（{n} 个文件）")
        return 0
    except Exception as e:
        print("出错了：", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
