"""QQ 官方机器人（单聊）。用 WebSocket 接入，不需要公网地址。

流程：AppID + AppSecret 换访问凭证 → 取网关地址 → 连 WebSocket → 鉴权（单聊权限 1<<25）→ 收消息、心跳、断线续连。
只回复你绑定的那个 QQ（openid）；陌生人的消息只记一笔，不回复。
被动回复：用户消息后 60 分钟内、每条最多回 4 次。主动消息（提醒）不带 msg_id，你在 QQ 里关掉"允许主动发送"就会失败，
失败后由 notify.py 改用电脑弹窗和常驻屏卡片。
"""
import asyncio
import json
import os
import time

import httpx
import websockets

from . import db, settings

TOKEN_URL = os.environ.get("AGENT_QQ_TOKEN_URL", "https://bots.qq.com/app/getAppAccessToken")   # 环境变量只给测试用
API = os.environ.get("AGENT_QQ_API", "https://api.sgroup.qq.com")
SANDBOX_API = os.environ.get("AGENT_QQ_API", "https://sandbox.api.sgroup.qq.com")
INTENT_C2C = 1 << 25

ERRORS = {
    40034105: "没有主动消息权限",
    40054013: "你在 QQ 里拒收了机器人的主动消息",
    40034100: "发送太频繁，被限流",
    11241: "频道/机器人权限不足",
}


class QQ:
    def __init__(self):
        self.status, self.detail = "off", "未启动"
        self.token, self.token_exp = "", 0.0
        self.session, self.seq = None, None
        self.task = None
        self.on_message = None          # async fn(text, openid, msg_id)
        self.msg_seq = {}               # msg_id -> 已回复次数
        self.last_user_msg = {}         # openid -> (msg_id, ts)

    @property
    def api(self):
        return SANDBOX_API if settings.S["qqSandbox"] else API

    def configured(self):
        return bool(settings.S["qqAppId"] and settings.get_secret("qqSecret"))

    async def get_token(self, force=False):
        if not force and self.token and time.time() < self.token_exp - 60:
            return self.token
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(TOKEN_URL, json={"appId": settings.S["qqAppId"], "clientSecret": settings.get_secret("qqSecret")})
        j = r.json()
        if "access_token" not in j:
            raise RuntimeError(f"拿不到访问凭证：{j.get('message') or j}")
        self.token = j["access_token"]
        self.token_exp = time.time() + int(j.get("expires_in", 7200))
        return self.token

    async def _headers(self):
        return {"Authorization": f"QQBot {await self.get_token()}", "Content-Type": "application/json"}

    # ---------- 发送 ----------
    async def send(self, openid, text, msg_id=None, wakeup=False):
        """返回 (成功?, 说明)。带 msg_id 是被动回复，不带是主动消息；wakeup=互动召回（30 天内每段时间 1 条）。"""
        body = {"content": text[:2000], "msg_type": 0}
        if wakeup:
            body["is_wakeup"] = True
        elif msg_id:
            n = self.msg_seq.get(msg_id, 0) + 1
            if n > 4:
                msg_id = None   # 被动次数用完，改成主动
            else:
                self.msg_seq[msg_id] = n
                body.update(msg_id=msg_id, msg_seq=n)
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{self.api}/v2/users/{openid}/messages", json=body, headers=await self._headers())
            try:
                j = r.json()
            except Exception:
                j = {}
            code = j.get("code") or j.get("err_code") if isinstance(j, dict) else None
            if r.status_code in (200, 201, 202) and not code:
                return True, "已发出"
            return False, ERRORS.get(code, f"QQ 返回 {r.status_code}：{j.get('message') or r.text[:120]}")
        except Exception as e:
            return False, f"发送失败：{e}"

    async def reply(self, openid, text, msg_id):
        return await self.send(openid, text, msg_id)

    async def push(self, text):
        """主动消息（提醒用）。"""
        uid = settings.S["qqUser"]
        if not uid:
            return False, "还没有绑定你的 QQ"
        if not self.configured():
            return False, "QQ 机器人没配置"
        # 1. 你 55 分钟内说过话：用被动回复，最稳
        mid, ts = self.last_user_msg.get(uid, (None, 0))
        if mid and time.time() - ts < 55 * 60 and self.msg_seq.get(mid, 0) < 4:
            ok, info = await self.send(uid, text, mid)
            if ok:
                db.kv_set("qq_push_ok", time.time())
                return ok, "已发出（被动回复）"
        # 2. 主动消息
        ok, info = await self.send(uid, text)
        if ok:
            db.kv_set("qq_push_ok", time.time())
            return ok, info
        # 3. 互动召回（次数很少，只在主动消息没权限时试一次）
        if "权限" in info or "拒收" in info:
            ok2, info2 = await self.send(uid, text, wakeup=True)
            if ok2:
                db.kv_set("qq_push_ok", time.time())
                return True, "已发出（互动召回）"
        return False, info

    # ---------- 连接 ----------
    def start(self):
        if self.task and not self.task.done():
            return
        self.task = asyncio.get_event_loop().create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            self.task = None
        self.status, self.detail = "off", "已停止"

    async def restart(self):
        await self.stop()
        self.session = self.seq = None
        self.token = ""
        if settings.S["qqEnabled"] and self.configured():
            self.start()

    async def _run(self):
        backoff = 3
        while True:
            if not (settings.S["qqEnabled"] and self.configured()):
                self.status, self.detail = "off", "没填 AppID 或 AppSecret"
                await asyncio.sleep(10)
                continue
            try:
                self.status, self.detail = "connecting", "正在连接"
                async with httpx.AsyncClient(timeout=10) as c:
                    g = await c.get(f"{self.api}/gateway", headers=await self._headers())
                url = g.json()["url"]
                async with websockets.connect(url, max_size=2**22, ping_interval=None) as ws:
                    await self._session(ws)
                backoff = 3
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status, self.detail = "error", f"{e}"[:200]
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    async def _session(self, ws):
        hello = json.loads(await ws.recv())
        interval = hello.get("d", {}).get("heartbeat_interval", 41250) / 1000
        token = await self.get_token()
        if self.session and self.seq is not None:
            await ws.send(json.dumps({"op": 6, "d": {"token": f"QQBot {token}", "session_id": self.session, "seq": self.seq}}))
        else:
            await ws.send(json.dumps({"op": 2, "d": {"token": f"QQBot {token}", "intents": INTENT_C2C, "shard": [0, 1],
                                                     "properties": {"$os": "windows", "$browser": "agent", "$device": "agent"}}}))

        async def beat():
            while True:
                await asyncio.sleep(interval)
                await ws.send(json.dumps({"op": 1, "d": self.seq}))

        hb = asyncio.get_event_loop().create_task(beat())
        try:
            async for raw in ws:
                m = json.loads(raw)
                op = m.get("op")
                if m.get("s") is not None:
                    self.seq = m["s"]
                if op == 0:
                    t, d = m.get("t"), m.get("d", {})
                    if t == "READY":
                        self.session = d.get("session_id")
                        self.status, self.detail = "online", f"已连上（{d.get('user', {}).get('username', '机器人')}）"
                    elif t == "RESUMED":
                        self.status, self.detail = "online", "已重新连上"
                    elif t == "C2C_MESSAGE_CREATE":
                        asyncio.get_event_loop().create_task(self._on_c2c(d))
                elif op == 7:      # 服务器要求重连
                    return
                elif op == 9:      # 会话失效，重新鉴权
                    self.session = self.seq = None
                    return
        except websockets.ConnectionClosed as e:
            code = getattr(e, "code", None) or getattr(getattr(e, "rcvd", None), "code", None)
            if code in (4004, 4914, 4915):
                self.session = self.seq = None
            if code == 4014:
                self.status, self.detail = "error", "机器人没有单聊权限（开放平台里申请 C2C 消息权限）"
                await asyncio.sleep(60)
            if code in (4006, 4007, 4009):
                self.session = self.seq = None
        finally:
            hb.cancel()

    async def _on_c2c(self, d):
        openid = (d.get("author") or {}).get("user_openid") or (d.get("author") or {}).get("id")
        text = (d.get("content") or "").strip()
        msg_id = d.get("id")
        if not openid:
            return
        bound = settings.S["qqUser"]
        if not bound:
            db.kv_set("qq_candidate", {"openid": openid, "text": text[:60], "ts": time.time()})
            return
        if openid != bound:
            db.kv_set("qq_stranger", {"openid": openid[:8] + "…", "ts": time.time()})
            return
        self.last_user_msg[openid] = (msg_id, time.time())
        if self.on_message and text:
            await self.on_message(text, openid, msg_id)


BOT = QQ()
