"""测"样本攒够了先问你要不要训练"这条流程。要先 dev/serve.sh start。"""
import sys, time, asyncio
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]   # 仓库根目录
sys.path.insert(0, str(ROOT))
import httpx
H = {"X-Agent": "1"}
B = "http://127.0.0.1:8765"
# 造一个"样本攒够"的类别：直接写库（后端同一个 sqlite）
from app import db
db.run("DELETE FROM kv WHERE k='train_ask'")
db.run("DELETE FROM categories WHERE name='查快递'")
db.insert("categories", {"name": "查快递", "count": 230, "status": "ready", "created": time.time(), "updated": time.time()})
from app import growth, settings
settings.load(); settings.S["slow"] = True
async def go():
    await growth.tick()
asyncio.run(go())
print("pending:", growth.pending())
s = httpx.get(B + "/api/state").json()
print("state.train_ask:", s.get("train_ask"))
r = httpx.post(B + "/api/chat", json={"text": "等一下"}, headers=H, timeout=30).json()
print("chat 等一下 ->", (r.get("reply") or r)[:80] if isinstance(r, dict) else r)
print("kv:", db.kv_get("train_ask"))
# 到点了再问
st = db.kv_get("train_ask"); st["until"] = time.time() - 1; db.kv_set("train_ask", st)
asyncio.run(go()); print("asked again:", growth.pending())
st = db.kv_get("train_ask"); st["asked"] = time.time() - 3 * 3600; db.kv_set("train_ask", st)
asyncio.run(go()); print("no reply, 3h later:", growth.pending())
r = httpx.post(B + "/api/train/answer", json={"go": True}, headers=H).json(); print("ui 开始 ->", r)
print("cat status:", db.one("SELECT status FROM categories WHERE name='查快递'"))
r = httpx.post(B + "/api/train/answer", json={"go": True}, headers=H); print("again ->", r.status_code)
db.run("DELETE FROM categories WHERE name='查快递'"); db.run("DELETE FROM kv WHERE k='train_ask'")
