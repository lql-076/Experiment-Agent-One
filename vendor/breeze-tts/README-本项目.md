# Breeze TTS 2 推理代码（随 Agent 一起带着）

- 来源：https://github.com/breezeblue-ai/breeze-tts ，提交 `daa6cb2`（2026-11 取的），**没有改动**，只拷了跑接口要用的
  `breeze_infer/`、`models/`、`configs/` 和 `LICENSE`（测试、Docker、图片没拷）。
- 代码是 Apache-2.0（见 `LICENSE`）。
- **模型权重不在这里**：一键装好时下到 `models\tts\breeze-tts-2`。权重是 BreezeBlue 的「研究和非商业用途」许可：
  只给自己和 Agent 聊天用，它念出来的不放进要挣钱的视频。
- 为什么随包带着：作者家里连 GitHub 不稳，装的时候不用再去 GitHub 拿代码。
- 怎么跑：`app/breeze_run.py`（在配音环境 tts-env 里，先把 qwen-tts 一导入就要的 sox 用空模块顶替，再启动 `breeze_infer.api`）。
- 要升级：把上面那个仓库新版本的这几个文件夹换进来，改这里的提交号。
