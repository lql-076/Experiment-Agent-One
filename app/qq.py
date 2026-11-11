r"""QQ 官方机器人（单聊）。用 WebSocket 接入，不需要公网地址。

流程：AppID + AppSecret 换访问凭证 → 取网关地址 → 连 WebSocket → 鉴权（单聊权限 1<<25）→ 收消息、心跳、断线续连。
只回复你绑定的那个 QQ（openid）；陌生人的消息只记一笔，不回复。
被动回复：用户消息后 60 分钟内、每条最多回 4 次。主动消息（提醒）不带 msg_id，你在 QQ 里关掉"允许主动发送"就会失败，
失败后由 notify.py 改用电脑弹窗和常驻屏卡片。

v2.3：QQ 里发的图片、文件也收（消息的 attachments 里有下载地址、文件名、大小）：下载进 工作区\收到的\日期\，图片另外交给 DeepSeek 看；
Agent 做好的图片能发回 QQ（富媒体：先 POST /v2/users/{openid}/files 用 file_data 传 base64 拿到 file_info，再发 msg_type=7 的消息）。
视频和别的文件先不发（官方的文件类型 file_type=4 还没开放），回复里给路径。
"""
import asyncio
import base64
import json
import os
import re
import time
from pathlib import Path

import httpx
import websockets

from . import db, settings

TOKEN_URL = os.environ.get("AGENT_QQ_TOKEN_URL", "https://bots.qq.com/app/getAppAccessToken")   # 环境变量只给测试用
API = os.environ.get("AGENT_QQ_API", "https://api.sgroup.qq.com")
SANDBOX_API = os.environ.get("AGENT_QQ_API", "https://sandbox.api.sgroup.qq.com")
INTENT_C2C = 1 << 25

MAX_ATT = 200 << 20             # QQ 发来的附件一个最多收 200 MB
MAX_SEND_IMG = 10 << 20         # 发回 QQ 的图片一张最多 10 MB
EXT_OF = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "video/mp4": ".mp4",
          "audio/silk": ".silk", "audio/amr": ".amr", "audio/mpeg": ".mp3", "audio/wav": ".wav", "voice": ".silk", "application/pdf": ".pdf", "text/plain": ".txt"}


def attachments(d) -> list:
    """一条 C2C 消息里的附件 → [{url, name, type, size}]。地址有时不带 https://，补上。"""
    out = []
    for a in (d.get("attachments") or [])[:10]:
        if not isinstance(a, dict):
            continue
        url = str(a.get("url") or "").strip()
        if not url:
            continue
        if url.startswith("//"):
            url = "https:" + url
        elif not re.match(r"https?://", url, re.I):
            url = "https://" + url
        ct = str(a.get("content_type") or "").split(";")[0].strip().lower()
        name = str(a.get("filename") or "").strip()
        if not name:
            name = f"QQ{'图片' if ct.startswith('image') else '语音' if 'voice' in ct or ct.startswith('audio') else '视频' if ct.startswith('video') else '文件'}_{time.strftime('%H%M%S')}{EXT_OF.get(ct, '')}"
        elif "." not in name and EXT_OF.get(ct):
            name += EXT_OF[ct]
        out.append({"url": url, "name": name, "type": ct, "size": int(a.get("size") or 0)})
    return out


async def fetch_attachments(atts):
    """把附件下载进 工作区\\收到的\\日期\\（流式，先写 .part）。返回 (收到的相对路径, 能给模型看的图片, 没收下来的说明)。"""
    from . import files, workspace
    rels, imgs, bad = [], [], []
    if not atts:
        return rels, imgs, bad
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=120, write=30, pool=None), follow_redirects=True) as c:
        for a in atts:
            if a["size"] > MAX_ATT:
                bad.append(f"{a['name']} 太大了（超过 200 MB）")
                continue
            try:
                dst = await asyncio.to_thread(workspace.recv_target, a["name"])
                tmp, got = dst.with_name(dst.name + ".part"), 0
                try:
                    async with c.stream("GET", a["url"]) as r:
                        if r.status_code != 200:
                            raise RuntimeError(f"下载地址返回 {r.status_code}")
                        with open(tmp, "wb") as f:
                            async for chunk in r.aiter_bytes(1 << 16):
                                got += len(chunk)
                                if got > MAX_ATT:
                                    raise RuntimeError("太大了（超过 200 MB）")
                                f.write(chunk)
                    os.replace(tmp, dst)
                finally:
                    if tmp.exists():
                        tmp.unlink()
            except Exception as e:
                bad.append(f"{a['name']} 没收下来（{str(e)[:60] or type(e).__name__}）")
                continue
            rels.append(workspace.rel(dst))
            if got <= files.MAX_IMG and len(imgs) < files.MAX_UPLOADS:           # 图片（按文件头认）：另外存一份给聊天记录，交给 DeepSeek 看
                head = dst.read_bytes()[:16]
                sn = files._sniff(head)
                if sn:
                    try:
                        imgs.append(files.save_upload(f"data:{sn[1]};base64," + base64.b64encode(dst.read_bytes()).decode(), len(imgs)))
                    except ValueError:
                        pass
    return rels, imgs, bad


ERRORS = {
    40034105: "没有主动消息权限",
    40054013: "你在 QQ 里拒收了机器人的主动消息",
    40034100: "发送太频繁，被限流",
    11241: "频道/机器人权限不足",
}


class QQ:
    def __init__(self):
        self.status, self.detail = "off", "未启动"
        self.since = 0.0                # 从什么时候开始连（连着失败也不重算），Agent 状态据此判「启动中 / 卡住了」
        self.token, self.token_exp = "", 0.0
        self.session, self.seq = None, None
        self.task = None
        self.on_message = None          # async fn(text, openid, msg_id, atts)
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

    async def send_image(self, openid, path, msg_id=None):
        """发一张图片（PNG / JPEG，10 MB 以内）：先传上去拿 file_info，再发富媒体消息。返回 (成功?, 说明)。"""
        p = Path(path)
        try:
            b = p.read_bytes()
        except OSError as e:
            return False, f"读不到图片：{type(e).__name__}"
        if len(b) > MAX_SEND_IMG:
            return False, "图片超过 10 MB"
        if not (b[:8] == b"\x89PNG\r\n\x1a\n" or b[:3] == b"\xff\xd8\xff"):
            return False, "QQ 只收 PNG / JPEG 图片"
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{self.api}/v2/users/{openid}/files", headers=await self._headers(),
                                 json={"file_type": 1, "file_data": base64.b64encode(b).decode(), "srv_send_msg": False})
                try:
                    j = r.json()
                except Exception:
                    j = {}
                info = j.get("file_info") if isinstance(j, dict) else None
                if r.status_code not in (200, 201, 202) or not info:
                    code = j.get("code") or j.get("err_code") if isinstance(j, dict) else None
                    return False, ERRORS.get(code, f"QQ 没收下图片（{r.status_code}）：{(j.get('message') if isinstance(j, dict) else '') or r.text[:120]}")
                body = {"content": " ", "msg_type": 7, "media": {"file_info": info}}
                if msg_id and self.msg_seq.get(msg_id, 0) < 4:
                    self.msg_seq[msg_id] = self.msg_seq.get(msg_id, 0) + 1
                    body.update(msg_id=msg_id, msg_seq=self.msg_seq[msg_id])
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
                if self.status != "connecting":
                    self.since = time.time()
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
        atts = attachments(d)
        if self.on_message and (text or atts):
            await self.on_message(text, openid, msg_id, atts)


BOT = QQ()
