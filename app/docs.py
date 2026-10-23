r"""说明文档：给人看的图，给 AI 看的文字，放在同一批文件里，改一处两边一起更新。

docs\
  README.md                  目录
  操作手册.md                给人看：怎么装、怎么用、出问题看哪里
  更新记录.md                每一版改了什么
  图\                        截图
  AI文档\                    给 AI 看的文字版（DeepSeek、本地大脑小脑、接手开发的 Claude）
    README.md                这个文件夹是什么
    架构\00-总览.md…13-*.md  每个功能的架构：开头一段 mermaid 结构图 + 文字说明
    当前结构.md              后端每次启动按代码重写：模块、接口、后台任务、设置项、主题、端口、数据文件

界面侧栏「说明」：架构那一组默认画成树状图（读每篇开头的 mermaid 段），也能切到文字版；
操作手册、更新记录照常显示文字。全是中文 Markdown，用记事本、Obsidian 打开也行。
"""
import ast
import re
import time
from pathlib import Path

from . import paths, settings

DOCS = paths.ROOT / "docs"
AI = DOCS / "AI文档"
GEN = AI / "当前结构.md"

# 接口说明：加了新接口没在这里写说明，生成的文档里会标出来「还没写说明」，一眼就知道文档落后了
ROUTES = {
    "/": "界面首页（ui/index.html）",
    "/themes/themes.js": "主题清单：扫描 ui/themes 里的 .css 生成",
    "/api/ping": "后端在不在、版本号、文件夹位置",
    "/api/settings": "读设置 / 改设置（GET 读、PUT 改）；GET 还带上密钥提示、各项放哪、安全线、查到的模型列表",
    "/api/secrets": "存或清除密钥（DeepSeek Key、QQ AppSecret），DPAPI 加密",
    "/api/safety": "改安全线某一组是先斩后奏还是先问",
    "/api/export": "导出设置（不含密钥）",
    "/api/import": "导入设置",
    "/api/state": "总览要的一切：今日分流、余额、整备、提醒卡片、训练询问、最近事件（界面每 5 秒拉一次）",
    "/api/hw": "硬件读数（CPU、显卡、内存、功耗、硬盘温度、游戏帧数）",
    "/api/hw/history": "最近 60 次硬件读数，画走势线用",
    "/api/models": "本地模型服务和 Kev 的状态",
    "/api/brains": "大脑页：各个脑的数据",
    "/api/report": "报告页：一周汇总、先斩后奏的改动、等你决定的事",
    "/api/events": "事件列表",
    "/api/events/{eid}": "一件事的全部细节（两票分数、为什么这么判、每一步）",
    "/api/events/{eid}/fix": "你纠正分流：立刻变成新判例",
    "/api/events/{eid}/redo": "换它重做：同一句话按你指定的去向再处理一遍（也记一次纠正）；隐私的事交给云端要先确认",
    "/api/hw/helper": "硬件监控助手：GET 看开没开、在不在跑；POST {on} 打开或关闭（第一次打开弹一次管理员确认）",
    "/api/obsidian": "Obsidian 笔记：几个库、多少篇、私人多少篇、收件箱在哪、记忆在不在库里、上次整理的结果",
    "/api/obsidian/check": "检查一个库的路径：在不在、是不是 Obsidian 库、多少篇、第一层有哪些文件夹（E 盘标只读）",
    "/api/obsidian/refresh": "重新扫一遍库（只处理改过的笔记），给还没向量的段落算向量",
    "/api/obsidian/reindex": "全部重建笔记索引",
    "/api/obsidian/tidy": "现在整理一次：今天聊了什么、可能矛盾的地方、可以加的链接，写进收件箱「每日」",
    "/api/obsidian/move-memory": "把 Agent 的记忆复制进一个能写的库的「Agent 记忆」文件夹（原来的改名留着）",
    "/api/obsidian/search": "在笔记里找（private=0 时不给私人笔记）",
    "/api/chat": "界面上直接发消息（和 QQ 走同一条路）；带 async 马上返回 token，处理进度另外查；带 force 就按你指定的去向走",
    "/api/chat/{token}": "查一条消息处理到哪一步了（对话页显示「正在联网搜索……」这些）",
    "/api/agent": "Agent 状态：决策脑两票、底座和每个小脑、新类别、DeepSeek、联网搜索、QQ、提醒、后台程序、记忆，每项一个状态；有数的项带进度（m），顶层带一排大数字（kpi）",
    "/api/osd": "游戏内显示的小框每秒来拿一次：设置 + 硬件读数",
    "/api/changes/{cid}/undo": "撤销一条先斩后奏的改动（git revert）",
    "/api/asks/{aid}": "同意或拒绝一件「等你决定」的事",
    "/api/feed": "进展报告：正在做的事一步一步写成人话",
    "/api/monitor": "后台页：正在跑的任务、各个部分的状态、日志列表",
    "/api/logs": "日志文件列表",
    "/api/logs/{name}": "读一个日志的最后几百行",
    "/api/setup": "一键补齐的状态",
    "/api/setup/start": "开始一键补齐",
    "/api/setup/stop": "停下一键补齐",
    "/api/checks": "上次整备自检的结果",
    "/api/checks/run": "重新自检全部",
    "/api/checks/{k}/run": "重新检测一项（带 quick=1 时和整体自检一样快查，自检窗口 14 项同时发；卡片上单独点的会查得更深）",
    "/api/actions/{name}": "整备和设置里的按钮动作（启动模型、绑定 QQ、发测试提醒、查余额、查模型列表、测联网搜索、跑每日差事、问 DeepSeek 怎么修……）",
    "/api/reminders": "提醒列表 / 新建提醒",
    "/api/reminders/{rid}": "改 / 删一条提醒",
    "/api/reminders/{rid}/fire": "现在试发一条提醒",
    "/api/train/answer": "回答「要不要训练新小脑」",
    "/api/deliveries/{did}/ack": "提醒卡片上点「好了」",
    "/api/deliveries/{did}/snooze": "提醒卡片上点「晚点」",
    "/api/claude/import": "导入从更强的模型（网页 Claude、ChatGPT……）带回的总结（只当参考资料，不进训练集）",
    "/api/log/verify": "检查动作日志的哈希链有没有被改过",
    "/api/docs": "说明文档列表（侧栏「说明」）",
    "/api/docs/{rel:path}": "读一篇说明文档",
    "/api/quit": "退出 Agent：停掉自己开的子进程（硬件监控助手开着也一起关），然后退出",
}
LOOPS = [
    ("后台照看（housekeeping）", "每 2 秒", "读硬件、判断让路、自动拉起模型服务、补算向量、整理排队的事、查余额、问训练、记录各部分上下线"),
    ("提醒（reminders.loop）", "每几秒", "到点的提醒发出去；没确认的过一阵再提醒"),
    ("每日差事（nightly.loop）", "每 2 分钟看一次", "电脑开着、你 20 分钟没找它、离上次超过 20 小时就跑一次；隔了 36 小时还没机会就直接跑"),
    ("QQ 通道（qq.BOT）", "一直连着", "WebSocket 收消息、心跳、断线续连"),
]
PORTS = [(8765, "界面和后端（app/main.py）"), (8090, "本地模型服务（app/model_server.py，在 ai-env 里跑）"),
         (8091, "Kev 决策模型服务"), (8085, "硬件监控助手（app/hw_helper.py，管理员运行）")]


def _title(p: Path) -> str:
    try:
        for ln in p.read_text("utf-8", errors="replace").splitlines():
            if ln.startswith("# "):
                return ln[2:].strip()
    except Exception:
        pass
    return p.stem


OLD = DOCS / "旧版说明（可以删）"


def tidy_old():
    """v1.5 把架构说明搬进了 docs/AI文档。旧版解压覆盖后，docs/架构、docs/自动生成 还留在原地，
    说明页和文件夹里会出现两份：挪进「旧版说明（可以删）」，不删任何文件。"""
    old = [p for p in (DOCS / "架构", DOCS / "自动生成") if p.is_dir()]
    if not old or not (AI / "架构").is_dir():
        return
    try:
        OLD.mkdir(exist_ok=True)
        for p in old:
            t = OLD / p.name
            if t.exists():
                t = OLD / f"{p.name}-{time.strftime('%Y%m%d%H%M%S')}"
            p.rename(t)
        print("旧版的说明文档挪进了", paths.show(OLD), "（可以删）")
    except Exception as e:
        print("旧版说明文档没挪成：", e)


def listing():
    """侧栏「说明」的目录：docs 根目录的几篇 + AI文档 里的。"""
    if not DOCS.exists():
        return []
    order = {"操作手册.md": 0, "更新记录.md": 1, "README.md": 2, "AI文档/README.md": 0, "AI文档/当前结构.md": 1}
    out = []
    for p in sorted(DOCS.rglob("*.md")):
        rel = p.relative_to(DOCS).as_posix()
        if "/" in rel and not rel.startswith("AI文档/"):
            continue
        group = "架构图" if rel.startswith("AI文档/架构/") else "AI 文档" if rel.startswith("AI文档/") else "说明"
        out.append({"rel": rel, "title": _title(p), "group": group, "mtime": p.stat().st_mtime,
                    "o": (0 if group == "架构图" else 1 if group == "说明" else 2, order.get(rel, 5), rel)})
    out.sort(key=lambda d: d["o"])
    for d in out:
        d.pop("o")
    return out


def read(rel: str):
    p = (DOCS / rel).resolve()
    if DOCS.resolve() not in p.parents or p.suffix != ".md" or not p.exists():
        raise FileNotFoundError(rel)
    return {"rel": rel, "title": _title(p), "text": p.read_text("utf-8", errors="replace"), "mtime": p.stat().st_mtime,
            "path": paths.show(p)}


def _doc(path: Path) -> str:
    try:
        t = ast.parse(path.read_text("utf-8", errors="replace"))
        d = (ast.get_docstring(t) or "").strip()
        return d.splitlines()[0] if d else ""
    except Exception:
        return ""


def _js_head(path: Path) -> str:
    try:
        m = re.search(r"/\*\s*(.*?)\*/", path.read_text("utf-8", errors="replace")[:1500], re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip()[:90] if m else ""
    except Exception:
        return ""


def generate(app=None, version="", themes=None):
    """按代码重写「当前结构.md」。后端每次启动调用一次。"""
    L = ["# 当前结构（按代码自动生成）", "",
         f"> 版本 {version} · 生成于 {time.strftime('%Y-%m-%d %H:%M')} · 后端每次启动都会按代码重写这一份，所以它不会过时。",
         "> 手写的架构说明在同一个文件夹的「架构」里；这里只列事实：有哪些程序、文件、接口、设置。", ""]
    L += ["## 运行起来是哪几个程序", "", "| 端口 | 是什么 |", "| --- | --- |"]
    L += [f"| {p} | {d} |" for p, d in PORTS]
    L += ["", "都只监听本机 127.0.0.1，别的电脑访问不到。桌面窗口（app/window.py）由后端拉起，不占端口。", ""]
    L += ["## 后台一直在跑的任务", "", "| 任务 | 多久一次 | 做什么 |", "| --- | --- | --- |"]
    L += [f"| {a} | {b} | {c} |" for a, b, c in LOOPS]
    L += ["", "## 后端模块（app 文件夹）", "", "| 文件 | 行数 | 是做什么的 |", "| --- | --- | --- |"]
    for p in sorted(paths.APP.glob("*.py")):
        n = len(p.read_text("utf-8", errors="replace").splitlines())
        L.append(f"| app/{p.name} | {n} | {_doc(p) or '—'} |")
    L += ["", "## 脚本（scripts 文件夹）", "", "| 文件 | 是做什么的 |", "| --- | --- |"]
    for p in sorted((paths.ROOT / "scripts").glob("*.py")):
        L.append(f"| scripts/{p.name} | {_doc(p) or '—'} |")
    L += ["", "## 界面模块（ui 文件夹）", "", "| 文件 | 是做什么的 |", "| --- | --- |"]
    for p in sorted((paths.UI / "js").glob("*.js")):
        L.append(f"| ui/js/{p.name} | {_js_head(p) or '—'} |")
    L.append("| ui/css/core.css | 公共样式（布局、组件、交互引擎的公共部分） |")
    L += ["", "## 主题和它们的交互手感", "", "| 文件 | 名字 | 手感（@fx） | 说明 |", "| --- | --- | --- | --- |"]
    for t in themes or []:
        L.append(f"| ui/themes/{t['file']} | {t['name']} | {' '.join(t.get('fx') or []) or '—'} | {t['desc']} |")
    if app is not None:
        L += ["", "## 接口（都在 127.0.0.1:8765）", "", "| 方法 | 地址 | 做什么 |", "| --- | --- | --- |"]
        seen = set()
        for r in app.routes:
            path, methods = getattr(r, "path", ""), sorted(getattr(r, "methods", None) or [])
            if not path or path.startswith(("/docs", "/openapi", "/redoc")) or not methods or (path, tuple(methods)) in seen:
                continue
            seen.add((path, tuple(methods)))
            note = ROUTES.get(path) or "**（还没写说明）**"
            L.append(f"| {'/'.join(m for m in methods if m != 'HEAD')} | `{path}` | {note} |")
    L += ["", "## 设置项（data/settings.json）", "", "界面上 设置 › 各个分区改的就是这些。括号里是默认值。", "",
          "| 设置 | 默认 |", "| --- | --- |"]
    for k, v in settings.DEFAULTS.items():
        if k in ("claudeTpl",):
            v = "（一段提示词）"
        L.append(f"| `{k}` | {v if v != '' else '（空）'} |")
    L += ["", "密钥（DeepSeek Key、QQ AppSecret）不在这里，单独加密存在 data/secrets.bin（Windows DPAPI）。", ""]
    L += ["## 数据和日志都在哪", "", "| 位置 | 是什么 |", "| --- | --- |",
          "| data/settings.json | 设置 |", "| data/secrets.bin | 加密的密钥 |", "| data/agent.db | 数据库：事件、提醒、送达、花费、判例、类别、改动记录、等你决定 |",
          "| data/window.json | 窗口大小、位置、是否全屏 |", "| data/webview/ | 桌面窗口（WebView2）自己的缓存 |",
          "| data/logs/backend.log | 后端的输出（平时没有黑窗口，出了问题先看这里） |", "| data/logs/model_server.log、kev.log、hw_helper.log | 本地模型服务、Kev、硬件监控助手 |",
          "| data/logs/setup_*.log | 一键补齐每一步的原始日志 |", "| data/logs/report.jsonl | 进展报告 |",
          "| data/logs/actions.jsonl | 动作日志（哈希链，改不了） |", "| memory/ | 记忆、技能、提示词、Claude 总结（中文 Markdown，git 记录改动） |",
          "| training/ | 慢成长的样本 |", "| models/ | 底座、嵌入模型、小脑、Kev 权重 |", "| ai-env/、.venv/ | 两个 Python 环境 |",
          "| tools/ | 便携版 Git、PyTorch 安装包、下载缓存、临时文件 |"]
    if paths.LOGS.exists():
        L += ["", "现在 data/logs 里有：" + "、".join(sorted(p.name for p in paths.LOGS.iterdir() if p.is_file())[:30])]
    try:
        GEN.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(L) + "\n"
        GEN.write_text(text, "utf-8")
    except Exception as e:
        print("当前结构.md 没写成：", e)
