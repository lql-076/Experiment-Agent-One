# 开发说明 · 给接手的人（包括新开的 Claude 窗口）

> 这一篇讲"怎么接着开发"。"它是什么、怎么搭的"看 `docs/`。

## 接手第一件事

1. **拉代码。** `git clone <仓库地址> Agent`。在 Claude 里先把仓库接进当前会话（要推送就要写权限），再 clone。
2. **装开发环境（Linux 沙箱）：**
   ```bash
   cd Agent
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt -r dev/requirements-dev.txt
   ```
   Windows 专用的几个包（pywebview、pythonnet、HardwareMonitor、pywintrace）在 Linux 上会自动跳过。
3. **跑一遍回归：** `dev/check.sh`。全部通过再动手，这样之后坏了能分清是谁弄坏的。
4. **按顺序读：**
   1. `docs/README.md`
   2. `docs/AI文档/架构/00-总览.md`
   3. `docs/更新记录.md`
   4. 要改哪块，就读哪块的 `docs/AI文档/架构/*.md`
5. **作者的 Claude Project 里还有两样东西（不在仓库里）：** 每一版的交付说明和来龙去脉，以及作者电脑上的规矩（哪些盘只读、什么不能删）。在那个 Project 里开的窗口，开工前先读。

## 每一版怎么交付

1. **改代码。** 只改要改的地方，不整篇重写。
2. **同步改文档：**
   - 动了哪块，就改对应的 `docs/AI文档/架构/*.md`：开头的结构图（mermaid）和后面的文字要一起改，「最后核对」改成新版本号。结构图的写法见 `docs/AI文档/README.md`。
   - 在 `docs/更新记录.md` 加一条。
   - `app/main.py` 的 `VERSION` 改成新版本号。
   - 新加的接口要在 `app/docs.py` 的 `ROUTES` 里写一句说明。不写的话，自动生成的「当前结构」会标「还没写说明」。
3. **跑回归：** `dev/check.sh` 全部通过。
4. **提交：** `git commit`，说明写中文、第一行以版本号开头（比如 `v1.4.2：……`），然后 `git push`。Claude 的沙箱推不了标签，要打标签或发 Release，作者在 GitHub 网页上点。
5. **打包：** `python dev/pack.py Agent-vX.Y.Z.zip`，包会放在 `dist/` 里。发给作者，作者解压到原来的 Agent 文件夹，选「替换」。
6. **跟作者交代：** 中文，简短。说清楚改了什么，哪些只能在 Windows 上实测（见下面）。

## 不能碰的

- **这些东西不进仓库、不进压缩包：** 设置、密钥、数据库、日志、记忆、人设、聊天和提醒记录、训练样本、模型。`.gitignore` 管着它们，`dev/pack.py` 打包时会按禁止清单再查一遍，查到了就不出包。
- **真的 Key 不进沙箱。** 测试用 `dev/serve.sh` 填进去的假 Key，DeepSeek、QQ 都连假服务。
- **停进程只按 PID 文件停，不按进程名杀。** `serve.sh` 就是这么做的。
- **Claude 的内容不进任何训练数据。** 网页 Claude 的回答、带回的总结、聊天记录都算。这条写死在代码里，不要改，原因见 `training/README.md`。
- **安全线（`app/safety.py`）只能往严里改。**

## 沙箱里测不了的（只能在 Windows 上实测）

- 无边框窗口的 Win32 部分：`app/winframe.py`，包括贴靠、DPI、最小尺寸、全屏
- 游戏内显示的小框：`app/osd.py` 的 `run()`（tkinter、点得穿、最上层、快捷键、多屏位置）
- 密钥加密：DPAPI
- 游戏帧数：ETW。统计部分（包括"哪个算游戏"）可以用 `dev/test_fps.py` 测
- 硬件监控助手的开关：`app/hwctl.py`（计划任务提权、ShellExecute runas、`/quit`）
- 没有黑窗口的启动：`app/launch.py`（pythonw、起不来弹框）、`启动.bat`
- Windows 性能计数器（PDH）：CPU 占用和频率、显卡各引擎占用、每个程序的显存（`app/hw.py` 的 `_Pdh`；汇总逻辑用 `dev/test_hw.py` 测）
- 磁盘列表和盘符：PowerShell `Get-Disk`（`app/hw.py` 的 `_disk_info`）
- 内存信息：WMI
- 硬件传感器：LibreHardwareMonitor
- 真实下载：PyTorch、模型、Kev 权重、配音模型
- 真的配音（Qwen3-TTS）：沙箱里没有显卡，配音服务换成假的 `dev/fake_tts.py`；音质、显存、速度、同一个人像不像都要在作者电脑上听
- Edge 专有的样式

交付时要写清楚哪些只在沙箱里测过。

## dev 里有什么

| 文件 | 做什么 |
| --- | --- |
| `check.sh` | 一条命令做完整回归，发版本前跑：ruff、演示模式界面、自检窗口、连后端的界面、说明页、树状图、帧数统计、硬件读数和显存让路、开机自检和意外退出、更强的模型和换它重做、配音、一页一屏放下、Kev 权重 |
| `serve.sh` | 起 / 停测试环境：假服务加测试后端，后端在 8765 |
| `test_backend.py` | 测试后端：和真的一样，只是一键补齐的每一步换成假步骤；配音服务的启动命令换成 `fake_tts.py` |
| `fake_tts_install.py` | 假的「安装配音」：输出和 `scripts/install_tts.py` 一样（讲解、pip、魔搭进度），几秒就完；`dev/.run/fake_tts_install_fail.flag` 在就装到一半失败一次，`fake_tts_install_slow.flag` 在就慢慢走 |
| `fake_tts.py` | 假的配音服务：接口和 `app/tts_server.py` 一样，念出来是一段"嘟——"（一个字 0.2 秒），用来查拼接、停顿、时间轴 |
| `fake_step.py` | 假的安装步骤：输出和真脚本一样（进展报告、进度、pip、tqdm），第一次跑 models 会故意失败一次 |
| `mocks.py` | 假服务：本地模型服务 8090（加 `--with-model` 才起）、Kev 8091、DeepSeek 8099（含工具调用、搜索、抓取；`/__last` 能看最近一次请求）、硬件监控 8085 |
| `mock_qq.py` | 假的 QQ 开放平台 |
| `make_tiny.py` | 造几 MB 的假底座和假嵌入模型，用来测真的本地模型服务；需要 torch |
| `ui_smoke.py` | 界面冒烟测试：每套风格 × 横竖屏 × 每个页面，查 JS 报错、白屏、横向溢出 |
| `ui/*.py` | 专项界面测试：交互手感（fx）、关闭菜单、说明页、说明页树状图（tree）、重新自检窗口（recheck）、设置里的联网搜索（search）、对话页和 Agent 状态和游戏内显示设置（chat）、竖屏后台、模型下拉 |
| `test_search.py` | 联网搜索和查说明书：问最新的先搜再读、带来源；隐私的不搜；每天上限；测试按钮；思考模式带工具；问它自己时带上说明书 |
| `test_train.py` | "样本攒够了先问你要不要训练"这条流程 |
| `test_osd.py` | 游戏内显示：显示什么、什么时候显示（Win32 和 tkinter 部分沙箱里跑不了） |
| `test_hw.py` | 硬件读数和显存让路：显卡占用按任务管理器算（含视频编码）、CPU 以 Windows 计数器为准、硬盘全列带盘符、让路几级和什么时候退、本地模型环境自检不再超时（Windows 计数器用假数据） |
| `test_startup.py` | 开机稳不稳：头 2 分钟会自己好的项显示「启动中」、后台一项一项重查、状态变了写日志、认出上次留下的子进程（只认本项目的）、上次为什么停了、日志噪音过滤 |
| `test_fps.py` | 用假的 ETW 事件测游戏帧数统计，以及游戏加加、播放器这些不当成游戏 |
| `test_checks.py` | 整备 14 项都查得完、没有"检测出错"；一键补齐 6 步按自检结果标「已就绪 / 自动启动中 / 要补」 |
| `test_kev.py` | Kev 权重在不在本机：没有、LoRA 缺底座、都在、有半截文件 |
| `test_route.py` | 第三条路「更强的模型」：指定去向、不接受时并进 DeepSeek、换它重做、隐私的事要确认才发出本机 |
| `test_tts.py` | 配音：切句子、字幕时间、音色参数、配音服务算我们自己的显存、让路和闲置时关掉、不进仓库；连测试后端生成 → 拼接停顿 → 时间轴对得上 WAV → 保存 → 我的音色 → 试同一个人 → 停下；「安装配音」按钮：后台装、进展报告、失败再点、改走 hf-mirror、停下 |
| `ui/tts.py` | 配音页点一遍：生成、试听、点时间轴跳过去、保存、描述音色、存我的音色、刷新后输入还在；设置 › 本地模型 点「安装配音」到装好；设置 › 自动化 有开机自启开关 |
| `ui/rtasks.py` | 常驻屏的后台任务进度条：没任务不显示；真的点一次安装（假安装放慢走，`dev/.run/fake_tts_install_slow.flag`）看进度条出来、数字在走、横竖屏 × 三套风格 × 字 130% 都在一屏里、停下后消失 |
| `test_autostart.py` | 开机自启开关：写当前用户的启动项、认出开机自启.bat 建的旧任务、关掉时删旧任务（点「否」说清楚）、启动项指向别的文件夹、launch.py 依赖变了交给 启动.bat |
| `ui/fit.py` | 一页一屏放下：每个页面、每个设置分区，横竖屏都不该出现要滚的地方（长列表和整备这种操作页除外，见 `SCROLL_OK`）；竖屏再把字调到 130% 查对话页和总览 |
| `pack.py` | 打包给作者的压缩包 |

`dev/.run/` 放测试时的日志、PID、截图，不进仓库。
