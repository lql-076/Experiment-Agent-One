# v3.8.0 交接包

- 版本：v3.8.0（R08）
- 日期：2026-11-18
- 远端：`origin/main` 已包含主提交 `0bbe31cd883b7ed6f482cb8a70f5c0c9882a180d`；最新 SHA 以 `git ls-remote --heads origin` 为准
- 用途：直接把这个文件夹整体交给接手的人；**只需要发本文件夹里的文件**，旧的 `v3.3.2`、`v3.4.0`、`v3.5.0`、`v3.5.1`、`v3.5.2`、`v3.6.0`、`v3.7.0` 和根目录 `INDEX.md` 不用一起发。

## 本文件夹里有什么

| 文件 | 内容 |
|---|---|
| `README.md` | 这一页：交接范围、关键结论、发哪些文件 |
| [`2026-11-18_R08_v3.8.0_DAG并行工坊与内容寻址缓存及双轨渲染.md`](2026-11-18_R08_v3.8.0_DAG并行工坊与内容寻址缓存及双轨渲染.md) | 本轮完整报告：改动、架构决策、验证、隐私安检、Git SHA、待办 |

## 这一版做了什么

1. **动态子工作流：** 每个分镜一个独立生图节点，每句台词一个独立配音节点，挂在可折叠/可缩放的组容器里；8 个顶层节点覆盖剧本、生图、配音、配乐、网页动效、PPT 卡片、FFmpeg、发布。
2. **可调大小节点：** 右下角拖拽缩放，`ResizeObserver` 实时重算连线，`node_layout` 写回 `project.json`；折叠状态也持久化。
3. **内容寻址缓存：** 生图/配音/配乐按 SHA-256 指纹查全局 `_cache` 和项目 `cache_index.json`，命中直接复用、节点显示「缓存命中」，不再花 API 钱。
4. **三路并行 DAG：** API 通道（生图 + 云端配音，4 并发）与本地 GPU 通道（配音/配乐，GPU 锁）同时启动；全部 ready 后汇聚到渲染和合成。
5. **全参数生图：** 模型（含 GPT Image 2.6 GIF）、比例/自定义、1K/2K/4K、n=1~4 选图、画质、复杂度、透明、参考图、GIF 帧/毫秒。
6. **网页 + PPT 双轨：** Playwright 网页动效轨（毛玻璃、粒子、动态字幕、Q 版 GIF 贴纸）+ python-pptx/OnlyOffice 卡片轨 + 静态 Ken Burns 兜底；FFmpeg 终混。
7. **完整发布清单：** 单条送审 / 批量清单、定时、标题、简介、默认话题、封面、AI 合规声明；仍由「发布」窗口人工点两下才发。
8. **测试安全锁：** `dev/serve.sh start` 检测到真实 `data/secrets.bin` 默认拒绝启动（退出码 3），显式 `AGENT_ALLOW_OVERWRITE_DATA=1` 才允许并备份/还原 data。

## 验证

- `dev/test_studio.py`：全部通过（缓存命中/单节点失效、三路并发、全参数生图、网页+PPT+FFmpeg 双轨、发布清单、真实 FFmpeg 横竖屏、单步重跑、停下）。
- `dev/ui_smoke.py`：12 工具 × 深/浅色 × 横/竖屏，0 JS 报错、0 内容缺失；`--demo` 也通过。
- `dev/ui/fit.py`：横屏 1440×880、竖屏 1080×1860，0 个要滚的地方、0 JS 报错。
- `dev/test_hw.py`、`dev/test_window.py`、`dev/ui/state.py`、`dev/ui/docs.py`：通过。
- 真机：8 节点、动态子节点、节点缩放/折叠、布局持久化、缩略图选图、发布节点、网页/PPT 渲染 + FFmpeg 成片；`dev/serve.sh` 安全锁拒绝覆盖真实 data。

## 限制 / 真机待验

- 真实 DeepSeek、真实 API易（尤其 GPT Image 2.6 GIF）、真实 Qwen3-TTS/百炼/Stable Audio 3、真实 OnlyOffice `.pptx` 尚未用真 Key/真工程跑端到端。
- 动态子节点在组内滚动，组容器可缩放；子卡片不单独拖拽缩放。
- 网页/PPT 轨道暂未做内容寻址缓存；重复渲染同一镜会重新跑 Playwright。
- WebView2 桌面窗口里的节点拖拽/缩放手感待真机确认（Playwright Chromium 已验证逻辑）。

## 重要注意（密钥）

R06 阶段 `dev/serve.sh` 曾覆盖 `data/secrets.bin` 的三个 Key；R06 已清空并恢复服务地址。R08 没有再覆盖 data，且安全锁已生效。**如果还没重填，需要到 设置 › 云端 重新填 DeepSeek / API易 / 百炼 Key。**
