"""v3.5 行为遥测：按月分片、人看的镜像、脱敏、筛选、批量上报。
用法：python dev/test_telemetry.py"""
import json
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import telemetry  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


old = telemetry.DIR
try:
    with tempfile.TemporaryDirectory() as td:
        telemetry.DIR = pathlib.Path(td)
        ev = telemetry.log("ui", "read_aloud_click", "对话页 › 朗读", "ok", 12.3,
                           {"page": "chat", "text_len": 6}, "点击「朗读」", "tr_test001")
        check(ev and ev["trace_id"] == "tr_test001" and ev["dur_ms"] == 12.3, "结构化事件字段齐")
        jp = pathlib.Path(td) / f"trace_{time.strftime('%Y-%m')}.jsonl"
        bp = pathlib.Path(td) / f"behavior_{time.strftime('%Y-%m')}.log"
        check(jp.exists() and bp.exists(), "按月生成 trace_YYYY-MM.jsonl 和 behavior_YYYY-MM.log")
        check("read_aloud_click" in jp.read_text("utf-8") and "点击「朗读」" in bp.read_text("utf-8"), "JSONL 和人类可读镜像都写进去了")
        fake_key, fake_hf = "sk-" + "x" * 24, "hf_" + "y" * 24
        fake_msg = "pass" + "word=abcdefghijklmnop " + "to" + "ken=abcdefghijklmnop"
        telemetry.log("api", "post", "/api/x", "err", 5, {"key": fake_key, "token": fake_hf}, fake_msg)
        txt = jp.read_text("utf-8")
        check("x" * 24 not in txt and "y" * 24 not in txt and "abcdefghijklmnop" not in txt, "API Key / Token / 密码入盘前脱敏")
        check(telemetry.read(cat="ui")[0]["action"] == "read_aloud_click", "按类别筛选")
        check(telemetry.read(q="朗读") and not telemetry.read(q="不存在的词"), "按关键词搜索")
        check(telemetry.read(bad=True)[0]["status"] == "err" and telemetry.read(trace="tr_test001")[0]["action"] == "read_aloud_click", "仅看异常 / 按 trace_id 搜")
        n = telemetry.ingest([{"cat": "voice", "action": "underrun", "target": "Breeze", "status": "warn", "dur_ms": 3000,
                               "metrics": {"ttfa_ms": 1560, "underrun_count": 2, "total_stall_ms": 480}, "msg": "断续 2 次", "trace_id": "tr_front001"},
                              {"cat": "ui", "action": "click", "target": "主页 › 配乐", "status": "ok", "msg": "点击"}])
        check(n == 2 and telemetry.read(cat="voice")[0]["metrics"]["underrun_count"] == 2, "前端批量上报（含断流指标）")
finally:
    telemetry.DIR = old

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
