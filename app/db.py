import sqlite3, json, time, threading
from pathlib import Path

DB = Path(__file__).parent.parent / "radar.db"
_local = threading.local()

def conn():
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c

DEFAULTS = {
    "keywords": ["website", "web developer", "app developer", "mobile app", "telegram bot", "chatbot",
                 "e-commerce", "landing page", "freelancer", "developer", "designer"],
    "negatives": ["unpaid", "equity only", "internship", "for free", "volunteer"],
    "alert_score": 70,
}

def init():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS leads(
      id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE, source TEXT, author TEXT, url TEXT, text TEXT,
      score INTEGER DEFAULT 0, service TEXT, reason TEXT, fp TEXT, status TEXT DEFAULT 'new',
      created_at REAL, posted_at REAL);
    CREATE INDEX IF NOT EXISTS ix_leads_list ON leads(status, created_at DESC);
    CREATE INDEX IF NOT EXISTS ix_leads_fp ON leads(fp);
    CREATE TABLE IF NOT EXISTS seen(uid TEXT PRIMARY KEY, t REAL);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    c.execute("DELETE FROM seen WHERE t<?", (time.time() - 14 * 86400,))

def get(key):
    r = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else DEFAULTS.get(key)

def put(key, val):
    conn().execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(val)))

def seen(uids):
    if not uids: return set()
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

def insert_lead(l):
    try:
        cur = conn().execute("""INSERT INTO leads(uid,source,author,url,text,score,service,reason,fp,created_at,posted_at)
            VALUES(:uid,:source,:author,:url,:text,:score,:service,:reason,:fp,:created_at,:posted_at)""",
            {**l, "created_at": time.time()})
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None

def get_lead(lid):
    r = conn().execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    return dict(r) if r else None
