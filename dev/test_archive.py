"""v3.5 日志归档：先提炼重要事项永久备份，再压缩/清理过期原始日志；180/365 天档位。
用法：python dev/test_archive.py"""
import json
import os
import pathlib
import sys
import tempfile
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import log_archive, settings, telemetry  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


old = {k: getattr(log_archive, k) for k in ("LOGS", "BACKUP", "ARCHIVE", "WS_BACKUP")}
old_dir = telemetry.DIR
old_ret = settings.S.get("logRetainDays")
old_get, old_set, old_feed = log_archive.db.kv_get, log_archive.db.kv_set, log_archive.feed.add
kv = {}
try:
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        logs = base / "logs"
        tel = logs / "telemetry"
        tel.mkdir(parents=True)
        now = time.time()
        old_m = "2024-01"
        cur_m = time.strftime("%Y-%m")
        (tel / f"trace_{old_m}.jsonl").write_text("\n".join([
            json.dumps({"ts": 1, "time": "2024-01-01 00:00:00.000", "trace_id": "tr_old", "cat": "voice", "action": "underrun",
                        "target": "Breeze", "status": "warn", "dur_ms": 3000, "metrics": {"ttfa_ms": 1600, "underrun_count": 2, "total_stall_ms": 480, "rtf": 1.18}, "msg": "断续 2 次"}),
            json.dumps({"ts": 2, "time": "2024-01-01 00:00:01.000", "trace_id": "tr_old2", "cat": "api", "action": "GET",
                        "target": "/api/slow", "status": "warn", "dur_ms": 2200, "metrics": {"code": 200}, "msg": "慢"}),
            json.dumps({"ts": 3, "time": "2024-01-01 00:00:02.000", "trace_id": "tr_old3", "cat": "ccode", "action": "done",
                        "target": "Claude Code", "status": "ok", "dur_ms": 5000, "metrics": {}, "msg": "做完了"}),
        ]) + "\n", "utf-8")
        (tel / f"trace_{cur_m}.jsonl").write_text(json.dumps({"ts": now, "time": "now", "trace_id": "tr_new", "cat": "ui", "action": "click", "target": "主页", "status": "ok", "dur_ms": 1, "metrics": {}, "msg": "点击"}) + "\n", "utf-8")
        crash = logs / "crash.old.log"
        crash.write_text("Windows fatal exception: access violation\n", "utf-8")
        oldt = now - 400 * 86400
        os.utime(crash, (oldt, oldt))
        setup = logs / "setup_bgm.log"
        setup.write_text("配乐装好了\n", "utf-8")
        os.utime(setup, (oldt, oldt))
        # 300 天前的分片：180 天档要归档，365 天档不该归档
        (tel / "trace_2025-12.jsonl").write_text(json.dumps({"ts": 4, "time": "2025-12-01 00:00:00.000", "trace_id": "tr_300", "cat": "ui", "action": "click", "target": "x", "status": "ok", "dur_ms": 1, "metrics": {}, "msg": "x"}) + "\n", "utf-8")
        log_archive.LOGS, log_archive.BACKUP, log_archive.ARCHIVE, log_archive.WS_BACKUP = logs, logs / "important_backups", logs / "archive", base / "工作区" / "备份" / "日志重要事项"
        telemetry.DIR = tel
        settings.S["logRetainDays"] = 180
        log_archive.db.kv_get = lambda k, d=None: kv.get(k, d)
        log_archive.db.kv_set = lambda k, v: kv.__setitem__(k, v)
        log_archive.feed.add = lambda *a, **k: None
        expired = log_archive._expired(now, 365)
        check(not any(p.name == "trace_2025-12.jsonl" for p in expired), "365 天档：300 天前的分片不归档")
        check(log_archive.due(now), "从没归档过：到期")
        r = log_archive.run(force=True, now=now)
        check(r["ok"] and not r["skipped"] and r["files"] >= 2, f"归档跑完：{r.get('files')} 个旧文件")
        md = pathlib.Path(r["report"])
        check(md.exists() and "重要事项永久备份" in md.read_text("utf-8") and "语音朗读异常" in md.read_text("utf-8"), "先生成《重要事项永久备份》")
        check((log_archive.WS_BACKUP / md.name).exists(), "工作区\\备份\\日志重要事项 也留一份")
        check(pathlib.Path(r["zip"]).exists() and zipfile.ZipFile(r["zip"]).namelist(), "旧日志压缩成 zip")
        check(not (tel / f"trace_{old_m}.jsonl").exists() and not crash.exists() and not setup.exists(), "过期原始分片/旧日志清理")
        check((tel / f"trace_{cur_m}.jsonl").exists(), "当前月热日志保留")
        check(kv.get("logArchiveLast") == now, "记录上次归档时间")
        check(not log_archive.due(now + 100), "不到 180 天不重复归档")
finally:
    for k, v in old.items():
        setattr(log_archive, k, v)
    telemetry.DIR = old_dir
    settings.S["logRetainDays"] = old_ret
    log_archive.db.kv_get, log_archive.db.kv_set, log_archive.feed.add = old_get, old_set, old_feed

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
