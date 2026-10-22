"""用假的 ETW 事件测游戏帧数统计（FpsMeter），不需要 Windows。"""
import ast, ctypes, threading
from collections import deque
src = (__import__('pathlib').Path(__file__).resolve().parents[1] / 'app' / 'hw_helper.py').read_text('utf-8')
tree = ast.parse(src)
cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FpsMeter'][0]
ns = {"ctypes": ctypes, "threading": threading, "deque": deque, "time": __import__('time')}
exec(compile(ast.Module([cls], []), 'fps', 'exec'), ns)
F = ns['FpsMeter']()
F.job = True; F.freq = 10_000_000
F.names = {111: 'Palworld-Win64-Shipping.exe', 222: 'dwm.exe', 333: 'msedgewebview2.exe'}
base = 133_700_000_000_000_000  # FILETIME 量级
t = 0.0
# 游戏：30 秒，平均 144 帧，每 100 帧有 1 帧卡 25ms
for i in range(144 * 30):
    dt = 0.025 if i % 100 == 50 else 1 / 144
    t += dt
    F._on((42, {"EventHeader": {"ProcessId": 111, "TimeStamp": int(base + t * 1e7)}}))
# dwm 60 帧（应该被跳过）
for i in range(60 * 30):
    F._on((42, {"EventHeader": {"ProcessId": 222, "TimeStamp": int(base + i / 60 * 1e7)}}))
print(F.stats())
# QPC 时间戳也能处理
G = ns['FpsMeter'](); G.job = True; G.freq = 10_000_000; G.names = {5: 'game.exe'}
for i in range(600):
    G._on((55, {"EventHeader": {"ProcessId": 5, "TimeStamp": int(5_000_000_000 + i / 60 * 1e7)}}))
print(G.stats())
