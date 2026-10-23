"""本地数据库（SQLite，存在 data/agent.db）。所有记录只在你电脑上。"""
import json
import sqlite3
import threading
import time

from . import paths

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, src TEXT, user TEXT, text TEXT, private INTEGER DEFAULT 0,
  route TEXT, ui_to TEXT, label TEXT, conf REAL, scores TEXT, votes TEXT, thresholds TEXT, why TEXT,
  steps TEXT, result TEXT, reply TEXT, cost REAL DEFAULT 0, latency REAL, fix TEXT, teacher TEXT,
  status TEXT DEFAULT 'done', category TEXT);
CREATE INDEX IF NOT EXISTS ev_ts ON events(ts);
CREATE TABLE IF NOT EXISTS examples(
  id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, label TEXT, source TEXT, private INTEGER DEFAULT 0,
  event_id INTEGER, vec BLOB, ts REAL);
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, text TEXT, kind TEXT DEFAULT 'daily', at TEXT DEFAULT '22:00',
  every_min INTEGER DEFAULT 90, days TEXT DEFAULT '1234567', once_ts REAL, enabled INTEGER DEFAULT 0,
  next_ts REAL, last_ts REAL, created REAL);
CREATE TABLE IF NOT EXISTS deliveries(
  id INTEGER PRIMARY KEY AUTOINCREMENT, reminder_id INTEGER, ts REAL, title TEXT, text TEXT, channels TEXT,
  status TEXT DEFAULT 'sent', acked_ts REAL, renotified INTEGER DEFAULT 0, snooze_ts REAL);
CREATE TABLE IF NOT EXISTS asks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, what TEXT, why TEXT, payload TEXT,
  status TEXT DEFAULT 'pending', decided_ts REAL);
CREATE TABLE IF NOT EXISTS changes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, what TEXT, evidence TEXT, commit_id TEXT,
  undone INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS costs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, model TEXT, tin INTEGER, thit INTEGER, tout INTEGER,
  usd REAL, purpose TEXT, event_id INTEGER);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, count INTEGER DEFAULT 0, status TEXT DEFAULT 'collecting',
  created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS chunks(
  hash TEXT PRIMARY KEY, file TEXT, text TEXT, private INTEGER DEFAULT 0, vec BLOB, mtime REAL);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS notes(
  vault TEXT, path TEXT, mtime REAL, size INTEGER, title TEXT, fmpriv INTEGER DEFAULT 0, private INTEGER DEFAULT 0,
  links TEXT, PRIMARY KEY(vault, path));
CREATE TABLE IF NOT EXISTS note_chunks(
  hash TEXT PRIMARY KEY, vault TEXT, path TEXT, heading TEXT, text TEXT, private INTEGER DEFAULT 0, vec BLOB);
CREATE INDEX IF NOT EXISTS nc_note ON note_chunks(vault, path);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        paths.ensure_dirs()
        _conn = sqlite3.connect(paths.DATA / "agent.db", check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
    return _conn


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def run(sql, args=()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        return cur.lastrowid


def insert(table: str, row: dict) -> int:
    keys = list(row)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in row.values()]
    return run(f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join('?' * len(keys))})", vals)


def update(table: str, rid: int, row: dict):
    keys = list(row)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in row.values()]
    run(f"UPDATE {table} SET {','.join(k + '=?' for k in keys)} WHERE id=?", vals + [rid])


def kv_get(k, default=None):
    r = one("SELECT v FROM kv WHERE k=?", (k,))
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except Exception:
        return r["v"]


def kv_set(k, v):
    run("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v, ensure_ascii=False)))


def jl(s, default=None):
    if s is None:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def now() -> float:
    return time.time()
