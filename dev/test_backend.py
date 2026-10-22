"""测试用后端：和真的一样，只是一键补齐的每一步换成假步骤（不真的下 11GB）。由 dev/serve.sh 启动。"""
import os
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parent
sys.path.insert(0, str(DEV.parent))
RUN = DEV / ".run"
RUN.mkdir(exist_ok=True)

import uvicorn  # noqa: E402
from app import main, setup  # noqa: E402


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

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ.get("AGENT_PORT", 8765)), log_level="warning")
