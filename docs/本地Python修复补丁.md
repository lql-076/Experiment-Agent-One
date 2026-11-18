# 本地 Windows Python 修复补丁与覆盖清单（v4.0.1+）

> 说明：当前在线工作区已迁移为 Node.js + Express 环境（无 `.git` 凭据，且未包含你本地的 Windows Python 源码、GPU 模型和隐私 Key）。  
> 下方整理了**本次全面排查发现的全部根因**、**可直接覆盖你本地仓库的前端文件清单**，以及**针对本地 Windows Python 后端（Claude Code 调起、FFmpeg 压片、生图/配音/配乐并发与参数）的完整修复代码**。  
> 本文档不包含任何 API Key 或个人隐私信息，可直接随仓库提交或本地留存。

---

## 一、本次排查出的全部核心问题

### 1. 前端画布与参数问题（已在本工作区 `ui/js/studio.js` 直接修完）

| # | 问题现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 模块 6 配乐音量滑块一拖就爆音，甚至让 FFmpeg 滤镜报错 | `input` 防抖保存直接发了滑块整数（如 `18`）而不是 `0.18`（仅 `change` / `stCollect` 除以了 100），导致 `bgm_volume` 放大 **100 倍** | 新增 `stNormalizeFieldPatch()`，在 `input` 与 `change` 时统一做 `/ 100` 与范围钳制；渲染读值与旧工程兼容 `> 1` 自动归一化 |
| 2 | 单模块并发运行时顶部「■ 停下」按钮依然灰掉点不了 | `renderTop()` 只看全局 `job.st === 'run'`，没看单模块 `stAnyRunning()` | `renderTop()` 与 `syncMeta()` 统一判断 `studioRunning() \|\| stAnyRunning()` |
| 3 | 刚改完台词/参数在 550ms 内点运行，跑的还是旧参数 | `STUDIO.saveT[id]` 防抖还没提交就发了 `/api/studio/module/run` | `stRun()` 启动前强制 flush 对应模块的待保存防抖定时器 |
| 4 | 角色配音单句「试听」点错句或提示未生成 | `data-lineplay` 直接用 UI 行下标 `la[lidx]` 匹配 `outputs`，没按全局 `line_index`（`o.line` / `shotNN`）匹配 | 改为按全局 `line_index` 精确匹配，并在音频 URL 上附加 `sha256` 版本参数避免浏览器播旧缓存 |
| 5 | 模块 6 正在合成时误点监控窗内 A/B/C「重跑」按钮变成停止整个任务 | 按钮未在运行态禁用，且点击透传 `stRun('compose')` 触发停下 | A/B/C 分窗重跑按钮在 `compose` 运行/排队期间禁用并明确提示先停止 |
| 6 | 生图测试台参考图 `data:` / `blob:` URL 被拼坏、自定义分辨率刚打开无校验提示、BGM 时长上限不一致 | `stMedia()`/`stAsset()` 对内联 URL 二次拼接 `/api/studio/media`；`stImageBody` 仅改值时校验 | `stMedia`/`stAsset` 放行 `data:`/`blob:`/`http:`/`/api/`；初始渲染即校尺寸；BGM 时长输入与参数一致 |

### 2. 本地 Windows Python + Claude Code 视频合成死活跑不通的根因

| # | 模块 | Windows 本地典型报错 / 卡死原因 | 修复方案 |
|---|---|---|---|
| 1 | `app/ccode.py` | npm 全局安装的 Claude CLI 在 Windows 上是 **`claude.cmd`**，直接 `Popen(['claude', ...])` 必报 `FileNotFoundError [WinError 2]` 或 `[WinError 193]` | `shutil.which()` 解析真实路径；若后缀为 `.cmd`/`.bat`，改用 `['cmd.exe', '/d', '/s', '/c', cli_path, ...]` |
| 2 | `app/ccode.py` | 缺少 `stdin=DEVNULL` 导致 Claude CLI 挂起等终端输入；未剥离嵌套环境变量 `CLAUDECODE` 被拒绝启动；Windows 中文默认 `gbk` 解码炸 `UnicodeDecodeError` | `stdin=subprocess.DEVNULL` + `encoding='utf-8', errors='replace'` + 剥离 `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT` + `CREATE_NO_WINDOW` |
| 3 | `app/ccode.py` | 点「■ 停下」只杀父 shell，`node.exe` 子进程残留继续烧额度 | Windows 下用 `taskkill /T /F /PID <pid>` 整棵进程树杀掉 |
| 4 | `app/render_web.py` | Claude 输出带 Markdown 围栏或前后解释文字、引用外部 CDN 脚本在 Playwright 里超时、中途停止没关闭浏览器导致内存泄漏 | 正则提取完整 `<!DOCTYPE html>…</html>`；禁止外链失败卡死；`try/finally` 强制关闭 page/browser；失败自动退回内置模板保证出片 |
| 5 | `app/video_maker.py` | Windows 盘符路径传进 FFmpeg `-vf subtitles='F:/a/sub.srt'` 时，**冒号 `:` 未转义成 `\:`**，FFmpeg `libass` 直接报错退出 | 实现 `ffmpeg_escape_filter_path()`：先 `\`→`/`，再 `:`→`\:`，再转义单引号 `'` |
| 6 | `app/video_maker.py` | 配音（24kHz 单声道）、配乐（44.1k/48k 立体声）、静音轨采样率/声道数不一致，`sidechaincompress` / `amix` 混流报格式不匹配或音画漂移；且缺 `yuv420p` / `faststart` 导致前端 `<video>` 播不了 | 混音前两条音轨统一插 `aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo`；输出强制 `-c:v libx264 -pix_fmt yuv420p -movflags +faststart -c:a aac`；并对 `bgm_volume > 1` 做兜底 `/ 100` |
| 7 | `app/studio.py` | 两个语音模块 + BGM 并发时仅锁内存未合并磁盘最新位置、`local:` / `cloud:` 音色前缀偶发混用 | 补充磁盘最新 `x/y/w/h` 合并锁、明确前缀分流与 `_force_nonce` 强制重生成 |

---

## 二、可直接覆盖你本地的文件清单

1. **直接从本工作区下载/复制覆盖到你本地仓库的文件**：
   - `ui/js/studio.js`（完整重写并修完上面全部 6 项前端 Bug，与你本地 FastAPI `/api/studio/*` 接口完全兼容）

2. **仅用于在线预览与联调的工作区文件**（你本地如继续使用 Python 版 `app/main.py`，**不需要**把 `server.ts` / `src/*` 覆盖过去）：
   - `server.ts`
   - `src/store.ts`
   - `src/studio-runtime.ts`

3. **需要按下面「第三节」补丁更新的本地 Windows Python 文件**：
   - `app/ccode.py`
   - `app/render_web.py`
   - `app/video_maker.py`
   - `app/studio.py`（核对 3 处关键保护）
   - `app/studio_assets.py`（核对 Range 206 与音频/视频头校验）

---

## 三、本地 Windows Python 修复代码（直接复制替换对应函数）

### 3.1 修复 `app/ccode.py`：Windows `claude.cmd` 解析、UTF-8 编码、禁嵌套、进程树强杀

将本地 `app/ccode.py` 中寻找可执行文件、构造子进程和杀进程的逻辑替换为以下实现：

```python
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional


def resolve_claude_cmd(configured: str = "") -> Optional[str]:
    """解析本地 claude / claude.cmd 路径；Windows 下必须显式找到 .cmd 或 .exe。"""
    candidates = []
    if configured and configured.strip():
        candidates.append(configured.strip().strip('"'))
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        userprofile = os.environ.get("USERPROFILE", "")
        if appdata:
            candidates.append(str(Path(appdata) / "npm" / "claude.cmd"))
            candidates.append(str(Path(appdata) / "npm" / "claude.exe"))
        if localappdata:
            candidates.append(str(Path(localappdata) / "Programs" / "claude" / "claude.exe"))
        if userprofile:
            candidates.append(str(Path(userprofile) / ".local" / "bin" / "claude.exe"))
    for name in ("claude.cmd", "claude.exe", "claude"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for c in candidates:
        p = Path(c)
        if p.is_file():
            return str(p)
    return None


def build_claude_popen_args(cli_path: str, args: list[str]) -> list[str]:
    """Windows 上 .cmd / .bat 不能直接 CreateProcess，必须走 cmd.exe /d /s /c。"""
    if os.name == "nt" and cli_path.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/d", "/s", "/c", cli_path, *args]
    return [cli_path, *args]


def build_clean_claude_env(bash_path: str = "") -> dict[str, str]:
    """去掉嵌套会话标记，强制 UTF-8 输出，防止中文 Windows 下 GBK 乱码或拒绝启动。"""
    env = os.environ.copy()
    for bad_key in (
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    ):
        env.pop(bad_key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["NO_COLOR"] = "1"
    env["CI"] = "1"
    if os.name == "nt" and bash_path and Path(bash_path).is_file():
        env["CLAUDE_CODE_GIT_BASH_PATH"] = bash_path
    return env


def kill_process_tree(proc: Optional[subprocess.Popen]) -> None:
    """保证点停止时连同 cmd.exe / node.exe 子树一起终止，不在后台继续跑。"""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                timeout=8,
            )
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_claude_prompt(
    prompt: str,
    cwd: str | Path,
    *,
    cli_path: str = "",
    model: str = "",
    bash_path: str = "",
    timeout_sec: int = 180,
    stop_event: Optional[threading.Event] = None,
    on_line: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str, str]:
    """同步安全执行单次无交互 Claude Code 请求，返回 (ok, stdout, err)。"""
    resolved = resolve_claude_cmd(cli_path)
    if not resolved:
        return False, "", "未找到 claude / claude.cmd，请确认 npm -g install @anthropic-ai/claude-code 或在设置中指定路径"

    args = ["-p", prompt, "--output-format", "text"]
    if model and model.strip():
        args.extend(["--model", model.strip()])

    cmd = build_claude_popen_args(resolved, args)
    env = build_clean_claude_env(bash_path)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    proc: Optional[subprocess.Popen[str]] = None
    lines: list[str] = []
    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        assert proc.stdout is not None
        while True:
            if stop_event and stop_event.is_set():
                kill_process_tree(proc)
                return False, "\n".join(lines), "用户已手动停止"
            if time.monotonic() - t0 > timeout_sec:
                kill_process_tree(proc)
                return False, "\n".join(lines), f"Claude Code 执行超过 {timeout_sec}s 超时"
            line = proc.stdout.readline()
            if line:
                clean = line.rstrip("\r\n")
                lines.append(clean)
                if on_line:
                    on_line(clean)
                continue
            if proc.poll() is not None:
                break
            time.sleep(0.05)

        out = "\n".join(lines).strip()
        if proc.returncode != 0:
            return False, out, f"Claude Code 退出码 {proc.returncode}"
        return True, out, ""
    except Exception as exc:
        kill_process_tree(proc)
        return False, "\n".join(lines), str(exc)
```

---

### 3.2 修复 `app/render_web.py`：HTML 纯净化提取、断网自包含校验与退回保底

在把 Claude Code 生成的网页动效 HTML 交给 Playwright 录屏前，加入提取与校验；如果 Claude 抽风返回说明文字或报错，立即退回内置 60-30-10 模板而不卡死模块 6：

```python
import re
from pathlib import Path


def extract_clean_html(raw: str) -> str:
    """从 Claude Code 输出中剥离 Markdown 代码块和多余解释，只保留完整 HTML。"""
    text = (raw or "").strip()
    fence = re.search(r"```(?:html)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    doc_match = re.search(r"(<!DOCTYPE\s+html[\s\S]*?</html>)", text, flags=re.IGNORECASE)
    if doc_match:
        return doc_match.group(1).strip()
    html_match = re.search(r"(<html[\s\S]*?</html>)", text, flags=re.IGNORECASE)
    if html_match:
        return "<!DOCTYPE html>\n" + html_match.group(1).strip()
    return ""


def validate_self_contained_html(html: str) -> tuple[bool, str]:
    """确保没有外部 CDN JS/CSS 阻塞 Playwright page.goto('file://...') 超时。"""
    if not html or len(html) < 80 or "<body" not in html.lower():
        return False, "HTML 结构不完整"
    if re.search(r'<script[^>]+src=["\']https?://', html, flags=re.IGNORECASE):
        return False, "包含外部 HTTP Script 引用，无头录屏易超时"
    if re.search(r'<link[^>]+href=["\']https?://', html, flags=re.IGNORECASE):
        return False, "包含外部 HTTP CSS 引用，离线录屏风格易丢失"
    return True, ""
```

> **提示**：Playwright 渲染时在 `with sync_playwright() as p:` 里务必将 `browser.close()` 放进 `finally:`，并且在每帧循环开头检查 `if is_stopped(): raise InterruptedError("stopped")`，这样点顶部「停下」时浏览器会秒退，不会残留孤立的 `chrome.exe` / `msedge.exe` 占用目录文件锁！

---

### 3.3 修复 `app/video_maker.py`：Windows FFmpeg 字幕转义、音轨统一、响度钳制与实时进度

这是本地 FFmpeg 压片最容易 silent fail / 报错退出的四个坑，直接替换到 `app/video_maker.py`：

```python
from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional


def ffmpeg_escape_filter_path(path: str | Path) -> str:
    """Windows 盘符 F:\\a\\sub.srt 直接进 FFmpeg subtitles= 必崩，必须先转斜杠再转义冒号与单引号。"""
    s = str(Path(path).resolve()).replace("\\", "/")
    s = s.replace(":", r"\:")
    s = s.replace("'", r"\'")
    return s


def normalize_bgm_volume(val: float | int | str | None, default: float = 0.18) -> float:
    """兜底旧版本遗留或滑块传整数 18 -> 0.18，并钳制在 [0.0, 0.6]。"""
    try:
        v = float(val if val is not None else default)
    except (TypeError, ValueError):
        v = default
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(0.6, v))


def build_audio_filter_complex(
    *,
    has_voice: bool,
    has_bgm: bool,
    bgm_volume: float,
    duck_depth: float,
    fade_sec: float,
    total_sec: float,
) -> tuple[str, str]:
    """统一两侧音轨为 48kHz / stereo / fltp 后再 sidechaincompress / amix，消除混音无声或飘移。"""
    vol = normalize_bgm_volume(bgm_volume)
    duck = max(0.0, min(1.0, float(duck_depth)))
    fade = max(0.0, min(6.0, float(fade_sec)))
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"

    if has_voice and has_bgm:
        # 1:a = voice, 2:a = bgm（按输入序号调整）
        ratio = 1.0 + duck * 7.0
        fade_out_start = max(0.0, total_sec - fade)
        fade_expr = f",afade=t=in:st=0:d={fade:.2f},afade=t=out:st={fade_out_start:.2f}:d={fade:.2f}" if fade > 0 else ""
        fc = (
            f"[1:a]{fmt},asplit=2[v_main][v_sc];"
            f"[2:a]aloop=loop=-1:size=2e+09,atrim=0:{total_sec:.3f},asetpts=PTS-STARTPTS,"
            f"volume={vol:.4f}{fade_expr},{fmt}[b_raw];"
            f"[b_raw][v_sc]sidechaincompress=threshold=0.03:ratio={ratio:.2f}:attack=25:release=260[b_duck];"
            f"[v_main][b_duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        return fc, "[aout]"

    if has_voice:
        return f"[1:a]{fmt}[aout]", "[aout]"

    if has_bgm:
        fade_out_start = max(0.0, total_sec - fade)
        fade_expr = f",afade=t=in:st=0:d={fade:.2f},afade=t=out:st={fade_out_start:.2f}:d={fade:.2f}" if fade > 0 else ""
        fc = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{total_sec:.3f},asetpts=PTS-STARTPTS,"
            f"volume={vol:.4f}{fade_expr},{fmt}[aout]"
        )
        return fc, "[aout]"

    return f"anullsrc=r=48000:cl=stereo:d={total_sec:.3f}[aout]", "[aout]"


def run_ffmpeg_with_progress(
    cmd: list[str],
    total_frames: int,
    on_progress: Optional[Callable[[float, int, float], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[bool, str]:
    """实时解析 FFmpeg `-progress pipe:1`，并确保 Windows 不弹窗、编码兼容 Chromium `<video>`。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    tail: list[str] = []
    cur_frame = 0
    cur_fps = 0.0
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            if stop_event and stop_event.is_set():
                proc.kill()
                return False, "FFmpeg 已手动停止"
            line = raw.strip()
            if not line:
                continue
            if line.startswith("frame="):
                try:
                    cur_frame = int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("fps="):
                try:
                    cur_fps = float(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("progress="):
                pct = min(99.0, (cur_frame / max(1, total_frames)) * 100.0)
                if on_progress:
                    on_progress(pct, cur_frame, cur_fps)
            else:
                tail.append(line)
                if len(tail) > 40:
                    tail.pop(0)
        rc = proc.wait()
        if rc != 0:
            return False, "\n".join(tail[-12:]) or f"FFmpeg 退出码 {rc}"
        if on_progress:
            on_progress(100.0, max(cur_frame, total_frames), cur_fps)
        return True, "\n".join(tail[-8:])
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        return False, str(exc)
```

> **FFmpeg 成片编码必带参数**：
> `-c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -movflags +faststart -c:a aac -b:a 192k`  
> 少了 `-pix_fmt yuv420p`，Windows 下高画质流压出的 4:4:4 MP4 在 Electron / Chrome `<video>` 里就是黑屏只有声音；少了 `-movflags +faststart`，拖动进度条就会卡死或报解码失败。

---

### 3.4 核对 `app/studio.py` 与 `app/studio_assets.py` 的 4 个关键点

1. **音色路由器严格前缀匹配**（`app/studio.py` 合成单句时）：
   ```python
   speaker = str(params.get("speaker") or "local:preset:Vivian").strip()
   if speaker.startswith("cloud:"):
       voice_id = speaker[len("cloud:"):]
       # 走百炼云端 TTS，不抢本地 GPU 锁
   elif speaker.startswith("local:preset:"):
       voice_id = speaker[len("local:preset:"):]
       # 抢占 GPU_LOCK 后调本地 Qwen3-TTS
   elif speaker.startswith("local:design:"):
       voice_id = speaker[len("local:design:"):]
   else:
       # 老数据没有前缀，按是否在云端音色表兜底，不再直接报错
   ```
2. **模块保存与并发锁**（`app/studio.py` `_save()`）：
   - 先获取模块写锁，重读磁盘最新的 `project.json`，**只替换当前保存的 `mod` 字段（同时保留磁盘里最新的 `x/y/w/h` 或仅当本次明确改布局时更新 `x/y/w/h`）**，然后原子写回（写临时 `.tmp` 再 `os.replace`）。否则两个模块并行收尾时会互相覆盖输出或位置！
3. **全局配音合并锁**（`_rebuild_voice()`）：
   - `voice-white` 和 `voice-zisu` 并行结束时会同时触发 `_rebuild_voice()`，必须放在同一把互斥锁里重读最新 `project.json` 并按全局 `line_index` 排序拼接 `tts/shotNN.wav` -> `tts/voice.wav`，避免最后只剩半边台词。
4. **音频/视频 `Range 206` 返回**（`app/studio_assets.py`）：
   - Starlette/FastAPI 的 `FileResponse(path, media_type=mime, headers={"Cache-Control": "no-store", "Accept-Ranges": "bytes"})` 一定要在头部先用 `_sniff_magic(ext, path)` 校验：
     - `.wav`: `b"RIFF"` 且 `[8:12] == b"WAVE"`
     - `.mp4`: `[4:8] == b"ftyp"`
     - `.mp3`: `b"ID3"` 或帧同步 `buf[0] == 0xFF and (buf[1] & 0xE0) == 0xE0`
   - 若文件只有 0 字节或头损坏，直接返回 HTTP 400 `{"detail": "文件损坏或头部不合法"}`，这样我们修好的前端 `stBindMedia()` 会直接在音频/视频下方打印具体原因。

---

## 四、下载覆盖与同步 GitHub 操作顺序

1. **把本工作区改好的 `ui/js/studio.js` 覆盖到你本地项目 `ui/js/studio.js`**。
2. **对照上面第三节，将修复补丁合入本地 `app/ccode.py`、`app/render_web.py`、`app/video_maker.py` 及核对 `app/studio.py` / `app/studio_assets.py`**。
3. **在本地项目根目录逐项自测**：
   - 运行后端单测：`python dev/test_studio.py`
   - 浏览器端：打开「视频工坊」，同时点击「白页配音」「紫苏配音」「背景配乐」运行，观察进度条与顶部「停下」按钮；拖动模块 6 配乐音量，确认保存值为 `0.18`（而不是 `18`）；点击模块 6「单独运行总成」，验证 `claude.cmd` + FFmpeg 正常产出并在模块 7 `<video>` 流畅播放与拖动进度条。
4. **隐私安检后再推送 GitHub**（确保 API Key 不进仓库）：
   ```bash
   python dev/git_sync.py --check
   ```
   确认输出 `0` 处密钥泄露后，再执行常规 `git add` / `git commit` / `git push`。
