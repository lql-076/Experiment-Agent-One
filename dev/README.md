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
   2. `docs/架构/00-总览.md`
   3. `docs/更新记录.md`
   4. 要改哪块，就读哪块的 `docs/架构/*.md`
5. **作者的 Claude Project 里还有两样东西（不在仓库里）：** 每一版的交付说明和来龙去脉，以及作者电脑上的规矩（哪些盘只读、什么不能删）。在那个 Project 里开的窗口，开工前先读。

## 每一版怎么交付

1. **改代码。** 只改要改的地方，不整篇重写。
2. **同步改文档：**
   - 动了哪块，就改对应的 `docs/架构/*.md`，开头「最后核对」改成新版本号。
   - 在 `docs/更新记录.md` 加一条。
   - `app/main.py` 的 `VERSION` 改成新版本号。
   - 新加的接口要在 `app/docs.py` 的 `ROUTES` 里写一句说明。不写的话，自动生成的「当前结构」会标「还没写说明」。
3. **跑回归：** `dev/check.sh` 全部通过。
4. **提交：** `git commit`（说明写中文），然后 `git tag vX.Y.Z`，最后 `git push && git push --tags`。
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
- 密钥加密：DPAPI
- 游戏帧数：ETW。统计部分可以用 `dev/test_fps.py` 测
- 内存信息：WMI
- 硬件传感器：LibreHardwareMonitor
- 真实下载：PyTorch、模型、Kev 权重
- Edge 专有的样式

交付时要写清楚哪些只在沙箱里测过。

## dev 里有什么

| 文件 | 做什么 |
| --- | --- |
| `check.sh` | 一条命令做完整回归，发版本前跑 |
| `serve.sh` | 起 / 停测试环境：假服务加测试后端，后端在 8765 |
| `test_backend.py` | 测试后端：和真的一样，只是一键补齐的每一步换成假步骤 |
| `fake_step.py` | 假的安装步骤：输出和真脚本一样（进展报告、进度、pip、tqdm），第一次跑 models 会故意失败一次 |
| `mocks.py` | 假服务：本地模型服务 8090（加 `--with-model` 才起）、Kev 8091、DeepSeek 8099、硬件监控 8085 |
| `mock_qq.py` | 假的 QQ 开放平台 |
| `make_tiny.py` | 造几 MB 的假底座和假嵌入模型，用来测真的本地模型服务；需要 torch |
| `ui_smoke.py` | 界面冒烟测试：每套风格 × 横竖屏 × 每个页面，查 JS 报错、白屏、横向溢出 |
| `ui/*.py` | 专项界面测试：交互手感（fx）、关闭菜单、说明页、竖屏后台、模型下拉 |
| `test_train.py` | "样本攒够了先问你要不要训练"这条流程 |
| `test_fps.py` | 用假的 ETW 事件测游戏帧数统计 |
| `pack.py` | 打包给作者的压缩包 |

`dev/.run/` 放测试时的日志、PID、截图，不进仓库。
