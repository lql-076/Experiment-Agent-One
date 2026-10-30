"""测试用后端：和真的一样，只是一键补齐的每一步换成假步骤（不真的下 11GB）。由 dev/serve.sh 启动。"""
import asyncio
import os
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parent
sys.path.insert(0, str(DEV.parent))
RUN = DEV / ".run"
RUN.mkdir(exist_ok=True)

import uvicorn  # noqa: E402
from app import main, reminders, settings, setup, tts, tts_install  # noqa: E402

# 配音：沙箱里没有 tts-env、没有显卡、下不了模型。启动命令换成假的配音服务（dev/fake_tts.py），
# "用到才启动、闲置关掉、让路关掉"还是走真的那一套
tts.T.py = lambda: Path(sys.executable)
tts.T.model_ok = lambda kind: True
tts.T.align_ok = lambda: not (RUN / "fake_tts_noalign.flag").exists()       # 对齐模型（v1.8.14）：放这个文件就当没下
tts.T.cmd = lambda: [sys.executable, DEV / "fake_tts.py", "--port", settings.S["ttsPort"]]
tts_install.command = lambda: [sys.executable, DEV / "fake_tts_install.py"]      # 「安装配音」按钮：假的安装，几秒就完


async def fake(k, opts):
    code = await setup._run(k, [sys.executable, str(DEV / "fake_step.py"), k, str(RUN)])
    if k == "hwmon":
        return False, "90 秒内没连上硬件监控助手"
    return (code == 0), ("假步骤完成" if code == 0 else f"退出码 {code}")


def mk(k):
    async def f(opts):
        return await fake(k, opts)
    return f


setup.STEP_FN = {s["k"]: mk(s["k"]) for s in setup.STEPS}


async def never(k):
    return False


setup.already = never


async def no_reminders():
    """测试环境不真的到点发提醒：发出来的提醒卡片会挡住界面测试要点的按钮（按测试跑的时间随机出现）。"""
    while True:
        await asyncio.sleep(3600)


reminders.loop = no_reminders

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ.get("AGENT_PORT", 8765)), log_level="warning")
