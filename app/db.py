import os, sqlite3, json, time, threading
from pathlib import Path

DB = Path(__file__).parent.parent / "radar.db"
_local = threading.local()

ROLE_PRESETS = {
    "software_ai": {
        "label": "Software, Web, Mobile & AI Dev",
        "services": "Full-stack web development, mobile apps, AI agents, chatbots, custom software, APIs, e-commerce, SaaS, scraping, automation",
        "keywords": [
            "website", "web developer", "app developer", "mobile app", "full stack", "frontend", "backend",
            "react", "next.js", "python", "ai agent", "chatbot", "telegram bot", "discord bot", "automation",
            "e-commerce", "shopify", "wordpress", "landing page", "saas", "mvp", "api integration", "scraper",
            "freelance developer", "software engineer"
        ],
    },
    "copywriting": {
        "label": "Copywriting & Content Writing",
        "services": "Conversion copywriting, landing page copy, email marketing sequences, blog content, technical writing, ghostwriting, ad scripts",
        "keywords": [
            "copywriter", "copywriting", "content writer", "blog writer", "email copywriter", "ghostwriter",
            "sales page", "landing page copy", "newsletter writer", "seo writer", "scriptwriter", "technical writer",
            "article writer", "freelance writer", "brand messaging"
        ],
    },
    "paid_ads_seo": {
        "label": "Google Ads, Meta Ads & SEO Growth",
        "services": "Google Ads management, PPC campaigns, Meta/Facebook Ads, TikTok Ads, media buying, conversion rate optimization, technical SEO",
        "keywords": [
            "google ads", "ppc", "meta ads", "facebook ads", "tiktok ads", "media buyer", "paid ads",
            "ad campaign", "roas", "seo specialist", "seo expert", "digital marketing", "lead generation",
            "search ads", "marketing agency", "funnel builder"
        ],
    },
    "design_creative": {
        "label": "UI/UX, Brand & Graphic Design",
        "services": "UI/UX design, Figma prototypes, web & mobile app design, brand identity, logo design, pitch decks, social media graphics",
        "keywords": [
            "ui/ux", "ux designer", "ui designer", "figma", "product designer", "web designer", "graphic designer",
            "brand identity", "logo design", "pitch deck", "redesign", "wireframe", "design system", "illustrator"
        ],
    },
    "video_ugc": {
        "label": "Video Editing, Motion & UGC",
        "services": "Short-form video editing (Reels, TikTok, Shorts), YouTube editing, motion graphics, UGC creator videos, ad creatives",
        "keywords": [
            "video editor", "video editing", "short form editor", "tiktok editor", "youtube editor",
            "motion graphics", "after effects", "ugc creator", "ad creative", "reels editor", "videographer"
        ],
    },
    "va_operations": {
        "label": "Virtual Assistant & Operations",
        "services": "Executive virtual assistant, customer support, CRM management, data entry, research, project management, bookkeeping",
        "keywords": [
            "virtual assistant", "executive assistant", "customer support", "data entry", "lead research",
            "project manager", "notion setup", "airtable", "zapier", "make.com", "bookkeeper", "admin support"
        ],
    },
}


def conn():
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c


def _defaults():
    return {
        "keywords": [
            "website", "web developer", "app developer", "mobile app", "telegram bot", "chatbot",
            "ai agent", "automation", "e-commerce", "shopify", "landing page", "freelancer",
            "developer", "designer", "copywriter", "google ads", "seo", "video editor"
        ],
        "negatives": [
            "unpaid", "equity only", "internship", "for free", "volunteer", "rev share only"
        ],
        "alert_score": int(os.getenv("ALERT_SCORE", "70")),
        "my_services": os.getenv(
            "MY_SERVICES",
            "Full-stack web development, mobile apps, AI automation, custom bots, UI/UX design, copywriting, Google Ads, and digital growth"
        ),
        "my_pitch": os.getenv(
            "MY_PITCH",
            "I build high-converting web & mobile apps, AI automations, and digital growth systems at Hackverse Technologies."
        ),
        "sender_name": os.getenv("SENDER_NAME", "Frank Oge"),
        "sender_portfolio": os.getenv("SENDER_PORTFOLIO", "https://frankoge.com"),
        "sender_company": os.getenv("SENDER_COMPANY", "Hackverse Technologies"),
        "sender_company_url": os.getenv("SENDER_COMPANY_URL", "https://hackversetechnologies.vercel.app"),
        "auto_email": os.getenv("AUTO_SEND_EMAIL", "true").lower() == "true",
    }


def init():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS leads(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      uid TEXT UNIQUE,
      source TEXT,
      author TEXT,
      author_url TEXT DEFAULT '',
      url TEXT,
      text TEXT,
      translated_text TEXT DEFAULT '',
      lang TEXT DEFAULT 'en',
      score INTEGER DEFAULT 0,
      service TEXT,
      reason TEXT,
      email TEXT DEFAULT '',
      phone TEXT DEFAULT '',
      contact_info TEXT DEFAULT '',
      draft TEXT DEFAULT '',
      draft_subject TEXT DEFAULT '',
      email_status TEXT DEFAULT '',
      fp TEXT,
      status TEXT DEFAULT 'new',
      created_at REAL,
      posted_at REAL
    );
    CREATE INDEX IF NOT EXISTS ix_leads_list ON leads(status, created_at DESC);
    CREATE INDEX IF NOT EXISTS ix_leads_fp ON leads(fp);
    CREATE TABLE IF NOT EXISTS seen(uid TEXT PRIMARY KEY, t REAL);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS sent_emails(email TEXT PRIMARY KEY, lead_id INTEGER, sent_at REAL, status TEXT);
    """)
    # Safe schema migration for existing radar.db databases
    existing_cols = {r[1] for r in c.execute("PRAGMA table_info(leads)").fetchall()}
    migrations = {
        "author_url": "TEXT DEFAULT ''",
        "translated_text": "TEXT DEFAULT ''",
        "lang": "TEXT DEFAULT 'en'",
        "email": "TEXT DEFAULT ''",
        "phone": "TEXT DEFAULT ''",
        "contact_info": "TEXT DEFAULT ''",
        "draft": "TEXT DEFAULT ''",
        "draft_subject": "TEXT DEFAULT ''",
        "email_status": "TEXT DEFAULT ''",
    }
    for col, col_def in migrations.items():
        if col not in existing_cols:
            try:
                c.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_def}")
            except Exception:
                pass
    c.execute("DELETE FROM seen WHERE t<?", (time.time() - 14 * 86400,))


def get(key):
    r = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if r is not None:
        try:
            return json.loads(r[0])
        except Exception:
            return r[0]
    return _defaults().get(key)


def put(key, val):
    conn().execute(
        "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(val)),
    )


def seen(uids):
    if not uids:
        return set()
    out = set()
    for i in range(0, len(uids), 500):
        part = uids[i:i + 500]
        q = ",".join("?" * len(part))
        out |= {r[0] for r in conn().execute(f"SELECT uid FROM seen WHERE uid IN ({q})", part)}
    return out


def mark_seen(uids):
    now = time.time()
    conn().executemany("INSERT OR IGNORE INTO seen VALUES(?,?)", [(u, now) for u in uids])


def fp_exists(fp):
    return conn().execute("SELECT 1 FROM leads WHERE fp=?", (fp,)).fetchone() is not None


def email_already_sent(email: str) -> bool:
    if not email:
        return False
    return conn().execute("SELECT 1 FROM sent_emails WHERE email=?", (email.lower(),)).fetchone() is not None


def mark_email_sent(email: str, lead_id: int, status: str = "sent"):
    if not email:
        return
    conn().execute(
        "INSERT OR REPLACE INTO sent_emails(email, lead_id, sent_at, status) VALUES(?,?,?,?)",
        (email.lower(), lead_id, time.time(), status),
    )


def insert_lead(l):
    try:
        defaults = {
            "author": "",
            "author_url": "",
            "translated_text": "",
            "lang": "en",
            "service": "",
            "reason": "",
            "email": "",
            "phone": "",
            "contact_info": "",
            "draft": "",
            "draft_subject": "",
            "email_status": "",
            "created_at": time.time(),
        }
        row = {**defaults, **l}
        cur = conn().execute(
            """INSERT INTO leads(
                uid, source, author, author_url, url, text, translated_text, lang,
                score, service, reason, email, phone, contact_info,
                draft, draft_subject, email_status, fp, created_at, posted_at
            ) VALUES(
                :uid, :source, :author, :author_url, :url, :text, :translated_text, :lang,
                :score, :service, :reason, :email, :phone, :contact_info,
                :draft, :draft_subject, :email_status, :fp, :created_at, :posted_at
            )""",
            row,
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_lead(lid):
    r = conn().execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    return dict(r) if r else None
