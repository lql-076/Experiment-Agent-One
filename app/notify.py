"""三层送达：QQ → Windows 通知 → 常驻屏大卡片。

QQ 发不出去（你关了"允许主动发送"、没权限、断网）就弹 Windows 通知；
不管 QQ 成没成功，提醒都会在界面上挂一张卡片，直到你点"吃了/好了"或"晚点"。
"""
import asyncio
import base64
import subprocess
import time

from . import paths, settings
from .models import NOWIN
from .qq import BOT

CARDS = {}   # delivery_id -> {id, title, text, ts, reminder_id}

# 用 Windows PowerShell 自带的组件弹通知，不用装任何东西
_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast scenario="reminder"><visual><binding template="ToastGeneric"><text>__T__</text><text>__B__</text></binding></visual><actions><action content="知道了" arguments="dismiss" activationType="system"/></actions><audio src="ms-winsoundevent:Notification.Reminder"/></toast>')
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
"""


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


async def toast(title: str, body: str) -> bool:
    if not paths.IS_WIN:
        return False
    script = _PS.replace("__T__", _xml_escape(title)[:80]).replace("__B__", _xml_escape(body)[:200])
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        p = await asyncio.create_subprocess_exec("powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NOWIN)
        return (await asyncio.wait_for(p.wait(), 20)) == 0
    except Exception:
        return False


async def deliver(title: str, text: str, delivery_id=None, reminder_id=None, card=True):
    """返回每个渠道的结果，界面和报告里都能看到。"""
    res = {}
    ok, info = await BOT.push(f"⏰ {title}\n{text}" if text and text != title else f"⏰ {title}")
    res["qq"] = {"ok": ok, "info": info}
    if not ok and settings.S["toastFallback"]:
        t = await toast(title, text or "点界面上的卡片确认")
        res["toast"] = {"ok": t, "info": "已弹出 Windows 通知" if t else "Windows 通知没弹出来"}
    if card and settings.S["resCard"] and delivery_id is not None:
        CARDS[delivery_id] = {"id": delivery_id, "title": title, "text": text, "ts": time.time(), "reminder_id": reminder_id}
        res["card"] = {"ok": True, "info": "界面上已挂卡片"}
    return res


async def say(text):
    """主动发一条不是提醒的消息（比如排队的事做完了）。开着免打扰就先攒着，关掉后一起发。"""
    from . import db
    if settings.S.get("quiet"):
        held = db.kv_get("held_msgs", []) or []
        held.append({"ts": time.time(), "text": text})
        db.kv_set("held_msgs", held[-50:])
        return False, "免打扰中，先攒着"
    return await BOT.push(text)


async def flush_held():
    from . import db
    held = db.kv_get("held_msgs", []) or []
    if not held:
        return 0
    db.kv_set("held_msgs", [])
    body = "免打扰期间攒下的消息：\n\n" + "\n\n".join(f"{time.strftime('%H:%M', time.localtime(h['ts']))}  {h['text']}" for h in held)
    await BOT.push(body[:1800])
    return len(held)


def drop_card(delivery_id):
    CARDS.pop(delivery_id, None)


def cards():
    return sorted(CARDS.values(), key=lambda c: c["ts"])
