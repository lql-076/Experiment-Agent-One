"""v3.5.2 Breeze 显存策略：常驻、80% 卸载、50% 低 10 分钟重载。
不启动模型、不占显存，只测纯函数。
用法：python dev/test_voice_policy.py"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.voice import vram_policy  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


now = 10000.0
# Breeze 活着：16GB 卡，自己 10.5GB；别的占用到 80% 就卸
check(vram_policy(10.5 + 4.4, 16, 10.5, True, None, now)[0] == "stop", "Breeze 活着，别的占用超过 80%：立刻卸载")
check(vram_policy(10.5 + 4.0, 16, 10.5, True, None, now)[0] == "keep", "Breeze 活着，别的占用 80% 以下：继续常驻")
# Breeze 不在：低于 50% 开始计时；到 10 分钟才加载；50~80 不加载
act, pct = vram_policy(6, 16, 0, False, None, now)
check(act == "wait" and pct < 50, "Breeze 不在、占用低于 50%：开始计时，不马上加载")
check(vram_policy(6, 16, 0, False, now - 599, now, 600)[0] == "wait", "低于 50% 但不满 10 分钟：不加载")
check(vram_policy(6, 16, 0, False, now - 600, now, 600)[0] == "load", "低于 50% 连续满 10 分钟：自动加载")
check(vram_policy(9, 16, 0, False, now - 600, now, 600)[0] == "hold", "占用 50%~80%：不自动加载")
# 阈值边界
check(vram_policy(10.5 + 4.4, 16, 10.5, True, None, now)[0] == "stop", "边界 80%：按超过处理")
check(vram_policy(8, 16, 0, False, now - 600, now, 600)[0] == "hold", "边界 50%：不加载（要低于 50%）")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
