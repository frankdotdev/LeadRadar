"""Deep contact extraction, free website & author-bio email crawler, profile/DM URL resolution, Hunter.io enrichment, and SMTP auto-mailer."""
import os, re, html, asyncio, smtplib
from email.message import EmailMessage
from urllib.parse import urlparse
from .net import http
from . import db

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,12}\b")
# Matches both partial ("john [at] gmail.com", "john(at)company.io") and full ("john [at] company [dot] io") obfuscations
OBFUSCATED_EMAIL_RE = re.compile(
    r"\b([A-Za-z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+|\s*@\s*)\s*([A-Za-z0-9.\-]+?)"
    r"(?:\s*(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+|\.)\s*([A-Za-z]{2,12}))\b",
    re.I,
)
MAILTO_RE = re.compile(r"mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,12})", re.I)

PHONE_RE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s.\-]?)?(?:\(?\d{2,4}\)?[\s.\-]?)?\d{3,4}[\s.\-]?\d{3,4}\b"
)
WA_RE = re.compile(r"(?:https?://)?(?:wa\.me|api\.whatsapp\.com/send\?phone=)/?\+?(\d{7,15})", re.I)
TG_HANDLE_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,32})\b", re.I)
AT_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9._%+\-])@([A-Za-z0-9_]{2,30})\b")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
BARE_DOMAIN_RE = re.compile(
    r"\b([a-z0-9][a-z0-9\-]{1,40}\.(?:com|io|co|ai|app|dev|org|net|xyz|tech|studio|agency|design|gg|me|us|uk|de|fr|ca|au|ng))\b",
    re.I,
)

IGNORE_EMAIL_DOMAINS = {
    "example.com", "domain.com", "email.com", "yoursite.com", "test.com", "company.com",
    "sentry.io", "w3.org", "schema.org", "cloudflare.com", "googleapis.com", "gstatic.com",
    "weworkremotely.com", "remotive.com", "freelancer.com", "reddit.com", "nairaland.com",
    "png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "woff", "woff2", "ttf"
}

IGNORE_EMAIL_PREFIXES = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster",
    "privacy", "abuse", "legal", "billing", "unsubscribe", "security"
}

PLATFORM_DOMAINS = {
    "reddit.com", "redd.it", "news.ycombinator.com", "bsky.app", "x.com", "twitter.com", "t.co",
    "t.me", "telegram.me", "telegram.org", "nairaland.com", "freelancer.com", "lemmy.world",
    "programming.dev", "lemmy.ml", "sh.itjust.works", "lemmy.ca", "feddit.org", "v2ex.com",
    "mastodon.social", "mas.to", "fosstodon.org", "hachyderm.io", "indieweb.social", "techhub.social",
    "infosec.exchange", "mastodon.de", "piaille.fr", "mstdn.jp", "linkedin.com", "facebook.com",
    "fb.com", "instagram.com", "threads.net", "threads.com", "github.com", "youtube.com", "youtu.be",
    "imgur.com", "docs.google.com", "forms.gle", "drive.google.com", "notion.so", "notion.site",
    "weworkremotely.com", "remotive.com", "himalayas.app", "jobicy.com", "nodesk.co", "remoteok.com",
    "problogger.com", "frankoge.com", "vercel.app", "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"
}

_domain_cache: dict[str, tuple[list[str], list[str]]] = {}
_bio_cache: dict[str, str] = {}
CRAWL_SEM = asyncio.Semaphore(6)


def _valid_email(em: str) -> bool:
    if not em or "@" not in em or len(em) > 90:
        return False
    prefix, dom = em.split("@", 1)
    ext = dom.rsplit(".", 1)[-1]
    if dom in IGNORE_EMAIL_DOMAINS or ext in IGNORE_EMAIL_DOMAINS:
        return False
    if prefix in IGNORE_EMAIL_PREFIXES:
        return False
    if any(em.endswith("." + x) for x in ("png", "jpg", "jpeg", "gif", "svg", "webp", "js", "css")):
        return False
    return True


def extract_emails(text: str) -> list[str]:
    if not text:
        return []
    raw_text = html.unescape(text)
    found = []
    for m in MAILTO_RE.finditer(raw_text):
        em = m.group(1).strip(".,;:!?)(").lower()
        if _valid_email(em) and em not in found:
            found.append(em)
    for m in EMAIL_RE.finditer(raw_text):
        em = m.group(0).strip(".,;:!?)(").lower()
        if _valid_email(em) and em not in found:
            found.append(em)
    for m in OBFUSCATED_EMAIL_RE.finditer(raw_text):
        em = f"{m.group(1)}@{m.group(2)}.{m.group(3)}".lower().replace(" ", "")
        if _valid_email(em) and em not in found:
            found.append(em)
    return found


def _rank_emails(emails: list[str]) -> list[str]:
    """Prioritize personal/founder/hiring emails over generic support@ addresses."""
    def score_em(em: str) -> int:
        p = em.split("@", 1)[0]
        if any(k in p for k in ("founder", "ceo", "hire", "hiring", "jobs", "careers", "talent", "projects", "work", "partner")):
            return 0
        if any(k in p for k in ("hello", "hi", "contact", "info", "team", "office", "studio")):
            return 2
        if any(k in p for k in ("support", "help", "sales", "press", "media", "admin")):
            return 3
        return 1  # Likely a direct personal first-name email (e.g. john@company.com)
    return sorted(emails, key=score_em)


def extract_phones(text: str) -> list[str]:
    if not text:
        return []
    phones = []
    for m in WA_RE.finditer(text):
        num = "+" + m.group(1).lstrip("+")
        if num not in phones:
            phones.append(num)
    for m in PHONE_RE.finditer(text):
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if 10 <= len(digits) <= 15:
            ctx_start = max(0, m.start() - 40)
            ctx = text[ctx_start:m.end() + 25].lower()
            if raw.startswith("+") or any(w in ctx for w in ("call", "phone", "whatsapp", "wa", "text", "sms", "tel", "contact", "dm", "reach", "mobile", "080", "081", "090", "070", "091")):
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
            u = urlparse(m.group(0).rstrip(".,;:!?)("))
            host = (u.netloc or "").lower().removeprefix("www.")
            if host and "." in host and not any(host == p or host.endswith("." + p) for p in PLATFORM_DOMAINS):
                if host not in domains:
                    domains.append(host)
        except Exception:
            pass
    # Also catch bare domains written in text like "our site is acme.io"
    for m in BARE_DOMAIN_RE.finditer(text):
        # Skip if preceded by @ (which is an email domain)
        if m.start() > 0 and text[m.start() - 1] == "@":
            continue
        dom = m.group(1).lower().removeprefix("www.")
        if dom not in PLATFORM_DOMAINS and not any(dom.endswith("." + p) for p in PLATFORM_DOMAINS):
            if dom not in domains:
                domains.append(dom)
    return handles[:4], domains[:3]


async def crawl_domain_for_contacts(domain: str) -> tuple[list[str], list[str]]:
    """Crawl a company domain (homepage + /contact + /about) for free to uncover emails & phone numbers."""
    if not domain or domain in PLATFORM_DOMAINS:
        return [], []
    if domain in _domain_cache:
        return _domain_cache[domain]

    emails, phones = [], []
    urls = [f"https://{domain}", f"https://{domain}/contact", f"https://{domain}/about"]
    async with CRAWL_SEM:
        rs = await asyncio.gather(*[http.get(u, timeout=6) for u in urls], return_exceptions=True)
        for r in rs:
            if isinstance(r, Exception) or r.status_code != 200:
                continue
            body = r.text[:80000]
            for em in extract_emails(body):
                if em not in emails:
                    emails.append(em)
            for ph in extract_phones(body):
                if ph not in phones:
                    phones.append(ph)
            if emails:
                break

    ranked = _rank_emails(emails)[:3]
    _domain_cache[domain] = (ranked, phones[:2])
    return _domain_cache[domain]


async def fetch_author_bio_contacts(source: str, author: str, post_url: str) -> str:
    """Fetch the poster's profile bio on Hacker News, Bluesky, or Reddit to find their email or website."""
    src = (source or "").lower()
    clean_au = (author or "").lstrip("@").removeprefix("u/").strip()
    cache_key = f"{src}:{clean_au}:{post_url}"
    if cache_key in _bio_cache:
        return _bio_cache[cache_key]

    bio_text = ""
    async with CRAWL_SEM:
        try:
            if src == "hackernews" and clean_au:
                r = await http.get(f"https://hn.algolia.com/api/v1/users/{clean_au}", timeout=6)
                if r.status_code == 200:
                    bio_text = html.unescape(r.json().get("about") or "")
            elif src == "bluesky" and clean_au:
                r = await http.get(
                    "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
                    params={"actor": clean_au},
                    timeout=6,
                )
                if r.status_code == 200:
                    bio_text = r.json().get("description") or ""
            elif src.startswith("reddit") and clean_au and clean_au.lower() not in ("deleted", "automoderator"):
                r = await http.get(f"https://www.reddit.com/user/{clean_au}/about.json", timeout=6)
                if r.status_code == 200:
                    sub = (r.json().get("data") or {}).get("subreddit") or {}
                    bio_text = sub.get("public_description") or ""
            elif (src.startswith("rss") or "briefs" in src) and post_url.startswith("http"):
                # Fetch the actual job listing / brief page to extract application email or company domain
                r = await http.get(post_url, timeout=6)
                if r.status_code == 200:
                    bio_text = r.text[:60000]
        except Exception:
            pass

    _bio_cache[cache_key] = bio_text
    return bio_text


def build_author_info(source: str, author: str, url: str, text: str) -> tuple[str, str]:
    """Return normalized (display_author, direct_profile_or_dm_url)."""
    src = (source or "").lower()
    au = (author or "").strip()
    u = (url or "").strip()

    if not au:
        if "x.com/" in u or "twitter.com/" in u:
            m = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,25})(?:/status/|$|\?)", u, re.I)
            if m and m.group(1).lower() not in ("i", "intent", "search", "home", "explore", "hashtag"):
                au = f"@{m.group(1)}"
        elif "threads.net/" in u or "threads.com/" in u:
            m = re.search(r"threads\.(?:net|com)/@?([A-Za-z0-9_.\-]{1,30})", u, re.I)
            if m:
                au = f"@{m.group(1).lstrip('@')}"
        elif "linkedin.com/" in u:
            m = re.search(r"linkedin\.com/(?:in|posts)/([A-Za-z0-9_\-]+)", u, re.I)
            if m:
                au = m.group(1).split("_")[0]
        elif "facebook.com/" in u:
            m = re.search(r"facebook\.com/(?:groups/[^/]+/posts/|people/|profile\.php\?id=)?([A-Za-z0-9.\-_]+)", u, re.I)
            if m and m.group(1).lower() not in ("posts", "share", "permalink.php", "watch", "events", "groups"):
                au = m.group(1)
        elif "reddit.com/" in u:
            m = re.search(r"reddit\.com/user/([A-Za-z0-9_\-]+)", u, re.I)
            if m:
                au = f"u/{m.group(1)}"
        elif "t.me/" in u:
            m = re.search(r"t\.me/(?:s/)?([A-Za-z0-9_]+)", u, re.I)
            if m:
                au = f"@{m.group(1)}"

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
    elif ("threads" in src or "threads.net" in u or "threads.com" in u) and clean_au:
        author_url = f"https://www.threads.net/@{clean_au}"
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
    elif src.startswith("v2ex") and clean_au:
        author_url = f"https://www.v2ex.com/member/{clean_au}"
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
            timeout=10,
        )
        if r.status_code != 200:
            return ""
        emails = (r.json().get("data") or {}).get("emails") or []
        if not emails:
            return ""
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
    """Multi-stage contact enrichment:
    1. Direct post text & obfuscated email/phone/@handle regex
    2. Author profile bio / job listing page lookup (HN, Bluesky, Reddit, RSS, Briefs)
    3. Autonomous free website crawler (homepage + /contact + /about of any mentioned company domain)
    4. Optional Hunter.io domain lookup
    """
    text = post.get("text", "")
    source = post.get("source", "")
    url = post.get("url", "")
    author, author_url = build_author_info(source, post.get("author", ""), url, text)

    emails = extract_emails(text)
    phones = extract_phones(text)
    handles, domains = extract_handles_and_domains(text)

    # Stage 2: If no email in post text, check author profile bio or linked job/brief page
    if not emails:
        bio_text = await fetch_author_bio_contacts(source, author, url)
        if bio_text:
            for em in extract_emails(bio_text):
                if em not in emails:
                    emails.append(em)
            for ph in extract_phones(bio_text):
                if ph not in phones:
                    phones.append(ph)
            bio_handles, bio_domains = extract_handles_and_domains(bio_text)
            for h in bio_handles:
                if h not in handles:
                    handles.append(h)
            for d in bio_domains:
                if d not in domains:
                    domains.append(d)

    # Stage 3: If still no email and a company domain was found, crawl the company website (/ and /contact) for free
    if not emails and domains:
        for dom in domains[:2]:
            dom_emails, dom_phones = await crawl_domain_for_contacts(dom)
            for em in dom_emails:
                if em not in emails:
                    emails.append(em)
            for ph in dom_phones:
                if ph not in phones:
                    phones.append(ph)
            if emails:
                break

    # Stage 4: Optional Hunter.io fallback if still no email
    if not emails and domains and os.getenv("HUNTER_API_KEY", "").strip():
        for dom in domains[:2]:
            found = await hunter_lookup(dom)
            if found:
                emails.append(found)
                break

    ranked_emails = _rank_emails(emails)
    email = ranked_emails[0] if ranked_emails else ""
    phone = phones[0] if phones else ""

    parts = []
    if author:
        parts.append(f"User: {author}")
    if email:
        parts.append(f"Email: {email}")
    if phone:
        parts.append(f"Phone/WA: {phone}")
    for h in handles[:3]:
        if h.lower() != author.lower():
            parts.append(f"Handle: {h}")
    for d in domains[:2]:
        parts.append(f"Web: {d}")

    return {
        "author": author or post.get("author", ""),
        "author_url": author_url or url,
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
    """Send tailored outreach email to the lead if email is present."""
    to_email = (lead.get("email") or "").strip().lower()
    if not to_email:
        return ""

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
