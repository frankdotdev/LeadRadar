"""Telegram alerts with action buttons. Send /start to your bot once; the chat id is learned automatically."""
import os, html, asyncio
from . import db
from .net import http

TOKEN = lambda: os.getenv("TELEGRAM_BOT_TOKEN")
API = lambda m: f"https://api.telegram.org/bot{TOKEN()}/{m}"


def chat_id():
    return os.getenv("TELEGRAM_CHAT_ID") or db.get("tg_chat")


async def send_lead(l):
    if not TOKEN() or not chat_id():
        return
    e = lambda s: html.escape(str(s or ""))
    tag = "[HOT] " if l["score"] >= 85 else ""
    lang = (l.get("lang") or "en").lower()
    lang_badge = f" · [{lang.upper()}]" if lang != "en" else ""
    email_badge = f"\n<b>Email Status:</b> {e(l.get('email_status')).upper()}" if l.get("email_status") else ""
    contacts = f"\n<b>Contacts:</b> <code>{e(l.get('contact_info'))}</code>" if l.get("contact_info") else ""

    display_text = l.get("translated_text") or l.get("text") or ""
    draft_part = f"\n\n<b>Tailored Pitch (Tap to copy):</b>\n<code>{e(l.get('draft')[:500])}</code>" if l.get("draft") else ""

    msg = (
        f"<b>{tag}SCORE: {l['score']}/100</b> · {e(l['source'])}"
        f"{' · ' + e(l['service']) if l.get('service') else ''}{lang_badge}\n\n"
        f"{e(display_text[:550])}\n\n"
        f"<i>{e(l.get('reason'))}</i>"
        f"{contacts}{email_badge}{draft_part}"
    )

    buttons = [{"text": "Open Post", "url": l["url"]}]
    if l.get("author_url") and l["author_url"] != l["url"] and l["author_url"].startswith("http"):
        buttons.append({"text": "Author / DM", "url": l["author_url"]})

    kb = {
        "inline_keyboard": [
            buttons,
            [
                {"text": t, "callback_data": f"st:{l['id']}:{s}"}
                for t, s in (("Save", "saved"), ("Contacted", "contacted"), ("Dismiss", "dismissed"))
            ],
        ]
    }
    try:
        await http.post(
            API("sendMessage"),
            json={
                "chat_id": chat_id(),
                "text": msg[:4000],
                "parse_mode": "HTML",
                "reply_markup": kb,
                "disable_web_page_preview": True,
            },
        )
    except Exception:
        pass


async def poll():
    """Long-poll for button taps and /start. No webhook or public URL needed."""
    offset = 0
    while True:
        if not TOKEN():
            await asyncio.sleep(30)
            continue
        try:
            r = await http.get(API("getUpdates"), params={"offset": offset, "timeout": 25}, timeout=35)
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                if "message" in u and u["message"].get("text", "").startswith("/start"):
                    db.put("tg_chat", u["message"]["chat"]["id"])
                    await http.post(
                        API("sendMessage"),
                        json={
                            "chat_id": u["message"]["chat"]["id"],
                            "text": "LeadRadar connected. High-intent leads with tailored pitches will appear here.",
                        },
                    )
                if "callback_query" in u:
                    cq = u["callback_query"]
                    _, lid, st = cq["data"].split(":")
                    db.conn().execute("UPDATE leads SET status=? WHERE id=?", (st, int(lid)))
                    await http.post(
                        API("answerCallbackQuery"),
                        json={"callback_query_id": cq["id"], "text": f"Marked {st}"},
                    )
        except Exception:
            await asyncio.sleep(5)
