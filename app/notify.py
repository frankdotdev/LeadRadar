"""Telegram alerts with action buttons. Send /start to your bot once; the chat id is learned automatically."""
import os, html, asyncio
from . import db
from .net import http

TOKEN = lambda: os.getenv("TELEGRAM_BOT_TOKEN")
API = lambda m: f"https://api.telegram.org/bot{TOKEN()}/{m}"

def chat_id(): return os.getenv("TELEGRAM_CHAT_ID") or db.get("tg_chat")

async def send_lead(l):
    if not TOKEN() or not chat_id(): return
    e = lambda s: html.escape(s or "")
    tag = "[HOT] " if l['score'] >= 85 else ""
    msg = (f"<b>{tag}SCORE: {l['score']}/100</b> · {e(l['source'])}"
           f"{' · ' + e(l['service']) if l.get('service') else ''}\n\n{e(l['text'][:600])}\n\n<i>{e(l.get('reason'))}</i>")
    kb = {"inline_keyboard": [[{"text": "Open post", "url": l["url"]}],
          [{"text": t, "callback_data": f"st:{l['id']}:{s}"} for t, s in (("Save", "saved"), ("Contacted", "contacted"), ("Dismiss", "dismissed"))]]}
    try:
        await http.post(API("sendMessage"), json={"chat_id": chat_id(), "text": msg, "parse_mode": "HTML",
                        "reply_markup": kb, "disable_web_page_preview": True})
    except Exception: pass

async def poll():
    """Long-poll for button taps and /start. No webhook or public URL needed."""
    offset = 0
    while True:
        if not TOKEN():
            await asyncio.sleep(30); continue
        try:
            r = await http.get(API("getUpdates"), params={"offset": offset, "timeout": 25}, timeout=35)
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                if "message" in u and u["message"].get("text", "").startswith("/start"):
                    db.put("tg_chat", u["message"]["chat"]["id"])
                    await http.post(API("sendMessage"), json={"chat_id": u["message"]["chat"]["id"], "text": "LeadRadar connected. Hot leads will appear here."})
                if "callback_query" in u:
                    cq = u["callback_query"]
                    _, lid, st = cq["data"].split(":")
                    db.conn().execute("UPDATE leads SET status=? WHERE id=?", (st, int(lid)))
                    await http.post(API("answerCallbackQuery"), json={"callback_query_id": cq["id"], "text": f"Marked {st}"})
        except Exception:
            await asyncio.sleep(5)
