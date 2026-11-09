"""Contact extraction, profile/DM URL resolution, Hunter.io enrichment, and SMTP auto-mailer."""
import os, re, asyncio, smtplib
from email.message import EmailMessage
from urllib.parse import urlparse
from .net import http
from . import db

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}\b")
OBFUSCATED_EMAIL_RE = re.compile(
    r"\b([A-Za-z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\bat\b)\s*([A-Za-z0-9.\-]+)\s*(?:\[dot\]|\(dot\)|\bdot\b)\s*([A-Za-z]{2,10})\b",
    re.I,
)
PHONE_RE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s.\-]?)?(?:\(?\d{2,4}\)?[\s.\-]?)?\d{3,4}[\s.\-]?\d{3,4}\b"
)
WA_RE = re.compile(r"(?:https?://)?(?:wa\.me|api\.whatsapp\.com/send\?phone=)/?\+?(\d{7,15})", re.I)
TG_HANDLE_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,32})\b", re.I)
AT_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9._%+\-])@([A-Za-z0-9_]{2,30})\b")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)

IGNORE_EMAIL_DOMAINS = {
    "example.com", "domain.com", "email.com", "yoursite.com", "test.com",
    "sentry.io", "w3.org", "schema.org", "png", "jpg", "jpeg", "gif", "svg", "webp"
}

PLATFORM_DOMAINS = {
    "reddit.com", "redd.it", "news.ycombinator.com", "bsky.app", "x.com", "twitter.com",
    "t.me", "telegram.me", "telegram.org", "nairaland.com", "freelancer.com", "lemmy.world",
    "mastodon.social", "mas.to", "fosstodon.org", "linkedin.com", "facebook.com", "fb.com",
    "instagram.com", "threads.net", "github.com", "youtube.com", "youtu.be", "imgur.com",
    "docs.google.com", "forms.gle", "drive.google.com", "notion.so", "notion.site"
}


def extract_emails(text: str) -> list[str]:
    if not text:
        return []
    found = []
    for m in EMAIL_RE.finditer(text):
        em = m.group(0).strip(".,;:!?)(").lower()
        dom = em.split("@", 1)[-1]
        ext = dom.rsplit(".", 1)[-1]
        if dom not in IGNORE_EMAIL_DOMAINS and ext not in IGNORE_EMAIL_DOMAINS:
            if em not in found:
                found.append(em)
    for m in OBFUSCATED_EMAIL_RE.finditer(text):
        em = f"{m.group(1)}@{m.group(2)}.{m.group(3)}".lower()
        dom = em.split("@", 1)[-1]
        if dom not in IGNORE_EMAIL_DOMAINS and em not in found:
            found.append(em)
    return found


def extract_phones(text: str) -> list[str]:
    if not text:
        return []
    phones = []
    for m in WA_RE.finditer(text):
        num = "+" + m.group(1).lstrip("+")
        if num not in phones:
            phones.append(num)
    # Look for explicit phone/whatsapp context or international format
    for m in PHONE_RE.finditer(text):
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if 10 <= len(digits) <= 15:
            # Avoid matching plain unix timestamps or random IDs unless prefixed with + or near phone/call/whatsapp/text
            ctx_start = max(0, m.start() - 35)
            ctx = text[ctx_start:m.end() + 20].lower()
            if raw.startswith("+") or any(w in ctx for w in ("call", "phone", "whatsapp", "wa", "text", "sms", "tel", "contact", "dm", "reach", "080", "081", "090", "070", "091")):
                clean_num = raw if raw.startswith("+") else digits
                if clean_num not in phones:
                    phones.append(clean_num)
    return phones[:3]


def extract_handles_and_domains(text: str) -> tuple[list[str], list[str]]:
    if not text:
        return [], []
    handles = []
    for m in TG_HANDLE_RE.finditer(text):
        h = f"t.me/{m.group(1)}"
        if h not in handles and m.group(1).lower() not in ("s", "share", "joinchat"):
            handles.append(h)
    for m in AT_HANDLE_RE.finditer(text):
        h = f"@{m.group(1)}"
        if h not in handles and len(m.group(1)) >= 3:
            handles.append(h)

    domains = []
    for m in URL_RE.finditer(text):
        try:
            u = urlparse(m.group(0))
            host = (u.netloc or "").lower().removeprefix("www.")
            if host and "." in host and not any(host == p or host.endswith("." + p) for p in PLATFORM_DOMAINS):
                if host not in domains:
                    domains.append(host)
        except Exception:
            pass
    return handles[:4], domains[:3]


def build_author_info(source: str, author: str, url: str, text: str) -> tuple[str, str]:
    """Return normalized (display_author, direct_profile_or_dm_url)."""
    src = (source or "").lower()
    au = (author or "").strip()
    u = (url or "").strip()

    # Try extracting username from URL if author is missing
    if not au:
        if "x.com/" in u or "twitter.com/" in u:
            m = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,25})(?:/status/|$)", u, re.I)
            if m and m.group(1).lower() not in ("i", "intent", "search", "home", "explore"):
                au = f"@{m.group(1)}"
        elif "reddit.com/" in u:
            m = re.search(r"reddit\.com/user/([A-Za-z0-9_\-]+)", u, re.I)
            if m:
                au = f"u/{m.group(1)}"
        elif "linkedin.com/in/" in u:
            m = re.search(r"linkedin\.com/in/([A-Za-z0-9_\-]+)", u, re.I)
            if m:
                au = m.group(1)
        elif "t.me/" in u:
            m = re.search(r"t\.me/(?:s/)?([A-Za-z0-9_]+)", u, re.I)
            if m:
                au = f"@{m.group(1)}"

    # Build direct profile / DM link
    clean_au = au.lstrip("@").removeprefix("u/")
    author_url = u

    if src.startswith("reddit") and clean_au and clean_au.lower() != "unknown":
        author_url = f"https://www.reddit.com/user/{clean_au}"
        if not au.startswith("u/"):
            au = f"u/{clean_au}"
    elif (src.startswith("x") or "x.com" in u or "twitter.com" in u) and clean_au and not clean_au.isdigit():
        author_url = f"https://x.com/{clean_au}"
        if not au.startswith("@"):
            au = f"@{clean_au}"
    elif src == "bluesky" and clean_au:
        author_url = f"https://bsky.app/profile/{clean_au}"
        if not au.startswith("@"):
            au = f"@{clean_au}"
    elif src.startswith("telegram") and clean_au:
        author_url = f"https://t.me/{clean_au}"
        if not au.startswith("@"):
            au = f"@{clean_au}"
    elif src.startswith("nairaland") and clean_au:
        author_url = f"https://www.nairaland.com/{clean_au}"
    elif src == "hackernews" and clean_au:
        author_url = f"https://news.ycombinator.com/user?id={clean_au}"

    return au, author_url


async def hunter_lookup(domain: str) -> str:
    """Query Hunter.io for a verified contact email on a domain if HUNTER_API_KEY is set."""
    key = os.getenv("HUNTER_API_KEY", "").strip()
    if not key or not domain:
        return ""
    try:
        r = await http.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": key, "limit": 5},
            timeout=12,
        )
        if r.status_code != 200:
            return ""
        emails = (r.json().get("data") or {}).get("emails") or []
        if not emails:
            return ""
        # Prioritize founder, ceo, marketing, growth, owner, ops
        priority = ("founder", "ceo", "owner", "marketing", "growth", "partner", "director", "head", "cto")
        for em in emails:
            pos = (em.get("position") or "").lower()
            dept = (em.get("department") or "").lower()
            if any(p in pos or p in dept for p in priority) and em.get("value"):
                return em["value"].lower()
        return (emails[0].get("value") or "").lower()
    except Exception:
        return ""


async def enrich_lead(post: dict) -> dict:
    """Extract all contact details (email, phone, handles, author profile link) and optionally enrich via Hunter.io."""
    text = post.get("text", "")
    emails = extract_emails(text)
    phones = extract_phones(text)
    handles, domains = extract_handles_and_domains(text)

    author, author_url = build_author_info(
        post.get("source", ""), post.get("author", ""), post.get("url", ""), text
    )

    email = emails[0] if emails else ""
    if not email and domains and os.getenv("HUNTER_API_KEY", "").strip():
        for dom in domains:
            found = await hunter_lookup(dom)
            if found:
                email = found
                break

    phone = phones[0] if phones else ""

    parts = []
    if author:
        parts.append(f"User: {author}")
    if email:
        parts.append(f"Email: {email}")
    if phone:
        parts.append(f"Phone/WA: {phone}")
    for h in handles:
        if h.lower() != author.lower():
            parts.append(f"Handle: {h}")
    for d in domains:
        parts.append(f"Web: {d}")

    return {
        "author": author or post.get("author", ""),
        "author_url": author_url or post.get("url", ""),
        "email": email,
        "phone": phone,
        "contact_info": " · ".join(parts),
    }


def _send_smtp_sync(to_email: str, subject: str, body: str) -> str:
    smtp_email = os.getenv("SMTP_EMAIL", "").strip()
    smtp_pass = os.getenv("SMTP_APP_PASSWORD", "").strip().replace(" ", "")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    sender_name = db.get("sender_name") or os.getenv("SENDER_NAME", "Frank Oge")

    if dry_run:
        return "simulated"
    if not smtp_email or not smtp_pass:
        return "ready"

    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{smtp_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["List-Unsubscribe"] = f"<mailto:{smtp_email}?subject=unsubscribe>"
    msg.set_content(body)

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as s:
            s.login(smtp_email, smtp_pass)
            s.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as s:
            s.starttls()
            s.login(smtp_email, smtp_pass)
            s.send_message(msg)
    return "sent"


async def send_lead_email(lead: dict, force: bool = False) -> str:
    """Send tailored outreach email to the lead if email is present.
    Returns email_status: 'sent', 'simulated', 'ready', or 'failed'.
    """
    to_email = (lead.get("email") or "").strip().lower()
    if not to_email:
        return ""

    # Avoid duplicate sends unless forced manually by user
    if not force and db.email_already_sent(to_email):
        return "already_sent"

    smtp_email = os.getenv("SMTP_EMAIL", "").strip()
    smtp_pass = os.getenv("SMTP_APP_PASSWORD", "").strip()
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    if not smtp_email or not smtp_pass:
        return "simulated" if dry_run else "ready"

    subject = (lead.get("draft_subject") or "").strip() or f"Re: {lead.get('service') or 'your project request'}"
    body = (lead.get("draft") or "").strip()
    if not body:
        return "ready"

    try:
        status = await asyncio.to_thread(_send_smtp_sync, to_email, subject, body)
        if status in ("sent", "simulated"):
            db.mark_email_sent(to_email, lead.get("id") or 0, status)
            if lead.get("id"):
                db.conn().execute(
                    "UPDATE leads SET email_status=?, status=CASE WHEN status='new' THEN 'contacted' ELSE status END WHERE id=?",
                    (status, lead["id"]),
                )
        return status
    except Exception:
        if lead.get("id"):
            db.conn().execute("UPDATE leads SET email_status='failed' WHERE id=?", (lead["id"],))
        return "failed"
