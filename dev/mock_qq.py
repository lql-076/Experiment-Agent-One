"""测试用：起一个假的 QQ 开放平台（取 token、网关、发消息），配合设置里的接口地址用。"""
import asyncio, json, threading
import uvicorn, websockets
from fastapi import FastAPI, Request
app = FastAPI(); SENT = []
@app.post("/app/getAppAccessToken")
async def tok(r: Request): return {"access_token": "T123", "expires_in": "7200"}
@app.get("/gateway")
def gw(): return {"url": "ws://127.0.0.1:8098"}
@app.post("/v2/users/{oid}/messages")
async def send(oid: str, r: Request):
    j = await r.json(); SENT.append({"oid": oid, **j}); print("SENT", oid, json.dumps(j, ensure_ascii=False), flush=True)
    if not j.get("msg_id") and not j.get("is_wakeup"): return {"code": 40034105, "message": "主动消息失败, 无权限"} if len(SENT) % 2 else {"id": "ok"}
    return {"id": "m1"}
async def ws_handler(ws):
    await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 5000}}))
    ident = json.loads(await ws.recv()); print("IDENT", ident["op"], ident["d"].get("intents"), flush=True)
    await ws.send(json.dumps({"op": 0, "s": 1, "t": "READY", "d": {"session_id": "S1", "user": {"username": "测试机器人"}}}))
    await asyncio.sleep(1)
    await ws.send(json.dumps({"op": 0, "s": 2, "t": "C2C_MESSAGE_CREATE", "d": {"id": "MSG1", "content": "你好呀", "author": {"user_openid": "OPENID_ME"}}}))
    await asyncio.sleep(6)
    await ws.send(json.dumps({"op": 0, "s": 3, "t": "C2C_MESSAGE_CREATE", "d": {"id": "MSG2", "content": "帮我查一下帕鲁最近更新了什么", "author": {"user_openid": "OPENID_ME"}}}))
    await asyncio.sleep(10)
    await ws.send(json.dumps({"op": 0, "s": 4, "t": "C2C_MESSAGE_CREATE", "d": {"id": "MSG3", "content": "每天晚上十点提醒我吃药", "author": {"user_openid": "OPENID_ME"}}}))
    await asyncio.sleep(2)
    await ws.send(json.dumps({"op": 0, "s": 5, "t": "C2C_MESSAGE_CREATE", "d": {"id": "MSG4", "content": "收到", "author": {"user_openid": "OPENID_ME"}}}))
    await ws.send(json.dumps({"op": 0, "s": 6, "t": "C2C_MESSAGE_CREATE", "d": {"id": "MSG5", "content": "陌生人", "author": {"user_openid": "STRANGER"}}}))
    async for m in ws: pass
async def main():
    async with websockets.serve(ws_handler, "127.0.0.1", 8098):
        await asyncio.Future()
threading.Thread(target=lambda: uvicorn.run(app, host="127.0.0.1", port=8097, log_level="warning"), daemon=True).start()
asyncio.run(main())
