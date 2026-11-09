import asyncio, os, time, csv, io
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from . import db, filters, notify, enrichment
from .sources import build_sources, inactive

SOURCES = build_sources()
state = {"last_run": {}, "errors": {}, "found": 0, "scanning": False}
MAX_AGE = float(os.getenv("MAX_AGE_HOURS", 48)) * 3600
MIN_STORE = int(os.getenv("MIN_STORE_SCORE", 35))
AUTO_EMAIL_MIN_SCORE = int(os.getenv("AUTO_EMAIL_MIN_SCORE", 65))


async def ingest(src, posts):
    kws, negs = db.get("keywords"), db.get("negatives")
    now = time.time()
    posts = [p for p in posts if p.get("text") and now - p.get("posted_at", now) < MAX_AGE]
    posts = list({p["uid"]: p for p in posts}.values())
    seen = db.seen([p["uid"] for p in posts])
    fresh = [p for p in posts if p["uid"] not in seen]
    db.mark_seen([p["uid"] for p in fresh])
    cand = [
        p for p in fresh
        if filters.prefilter(p["text"], kws, negs, src.need_intent and not p.get("trusted"))
    ]
    if not cand:
        return
    verdicts = await asyncio.gather(*[filters.classify(p["text"], kws, p.get("author", "")) for p in cand])
    for p, v in zip(cand, verdicts):
        if v["score"] < MIN_STORE:
            continue
        fp = filters.fingerprint(p["text"])
        if db.fp_exists(fp):
            continue
        contacts = await enrichment.enrich_lead(p)
        email_addr = contacts.get("email", "")
        email_status = "ready" if email_addr else ""

        lead = {
            **p,
            "text": p["text"][:2000],
            **v,
            **contacts,
            "email_status": email_status,
            "fp": fp,
        }
        lead["id"] = db.insert_lead(lead)
        if not lead["id"]:
            continue
        state["found"] += 1

        # Auto-send email if email was found and auto_email is enabled
        if email_addr and db.get("auto_email") and v["score"] >= AUTO_EMAIL_MIN_SCORE:
            sent_st = await enrichment.send_lead_email(lead)
            lead["email_status"] = sent_st

        if v["score"] >= db.get("alert_score"):
            await notify.send_lead(lead)


async def run_source(src):
    while True:
        try:
            await ingest(src, await src.fetch(db.get("keywords")))
            state["errors"].pop(src.name, None)
        except Exception as e:
            state["errors"][src.name] = str(e)[:100]
        state["last_run"][src.name] = time.time()
        await asyncio.sleep(src.interval)


def _backfill_existing_leads():
    """Ensure any pre-existing leads in radar.db have extracted contacts and an immediate tailored writeup."""
    c = db.conn()
    kws = db.get("keywords") or []
    rows = c.execute("SELECT * FROM leads WHERE draft IS NULL OR draft = '' LIMIT 200").fetchall()
    for r in rows:
        d = dict(r)
        emails = enrichment.extract_emails(d.get("text", ""))
        phones = enrichment.extract_phones(d.get("text", ""))
        handles, domains = enrichment.extract_handles_and_domains(d.get("text", ""))
        au, au_url = enrichment.build_author_info(d.get("source", ""), d.get("author", ""), d.get("url", ""), d.get("text", ""))
        em = emails[0] if emails else ""
        ph = phones[0] if phones else ""
        parts = []
        if au:
            parts.append(f"User: {au}")
        if em:
            parts.append(f"Email: {em}")
        if ph:
            parts.append(f"Phone/WA: {ph}")
        for h in handles:
            if h.lower() != (au or "").lower():
                parts.append(f"Handle: {h}")
        for dm in domains:
            parts.append(f"Web: {dm}")
        contact_info = " · ".join(parts)
        subj, body = filters.heuristic_draft(d.get("text", ""), au, d.get("service", ""), kws)
        em_status = d.get("email_status") or ("ready" if em else "")
        c.execute(
            """UPDATE leads SET author=?, author_url=?, email=?, phone=?, contact_info=?,
               draft_subject=?, draft=?, email_status=? WHERE id=?""",
            (au, au_url, em, ph, contact_info, subj, body, em_status, d["id"]),
        )


@asynccontextmanager
async def lifespan(_):
    db.init()
    _backfill_existing_leads()
    tasks = [asyncio.create_task(run_source(s)) for s in SOURCES] + [asyncio.create_task(notify.poll())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan, title="LeadRadar")
STATIC = Path(__file__).parent.parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/leads")
def leads(status: str = "", source: str = "", min_score: int = 0, q: str = "", has_contact: str = "", limit: int = 100):
    sql, a = "SELECT * FROM leads WHERE score>=?", [min_score]
    if status:
        sql += " AND status=?"
        a.append(status)
    if source:
        sql += " AND source LIKE ?"
        a.append(source + "%")
    if has_contact == "email":
        sql += " AND email != ''"
    elif has_contact == "any":
        sql += " AND (email != '' OR phone != '' OR author != '')"
    if q:
        sql += " AND (text LIKE ? OR translated_text LIKE ? OR service LIKE ? OR author LIKE ? OR contact_info LIKE ?)"
        pat = f"%{q}%"
        a.extend([pat, pat, pat, pat, pat])
    return [dict(r) for r in db.conn().execute(sql + " ORDER BY created_at DESC LIMIT ?", a + [limit])]


class Status(BaseModel):
    status: str


@app.patch("/api/leads/{lid}")
def set_status(lid: int, b: Status):
    if b.status not in {"new", "saved", "contacted", "won", "dismissed"}:
        raise HTTPException(400, "bad status")
    db.conn().execute("UPDATE leads SET status=? WHERE id=?", (b.status, lid))
    return {"ok": True}


class DraftUpdate(BaseModel):
    draft: str
    draft_subject: str = ""


@app.patch("/api/leads/{lid}/draft")
def save_draft(lid: int, b: DraftUpdate):
    db.conn().execute(
        "UPDATE leads SET draft=?, draft_subject=CASE WHEN ? != '' THEN ? ELSE draft_subject END WHERE id=?",
        (b.draft, b.draft_subject, b.draft_subject, lid),
    )
    return {"ok": True}


@app.post("/api/leads/{lid}/draft")
async def draft(lid: int):
    l = db.get_lead(lid)
    if not l:
        raise HTTPException(404)
    res = await filters.draft_reply(l)
    db.conn().execute(
        "UPDATE leads SET draft=?, draft_subject=? WHERE id=?",
        (res["draft"], res["subject"], lid),
    )
    return {"draft": res["draft"], "subject": res["subject"]}


@app.post("/api/leads/{lid}/email")
async def send_email_endpoint(lid: int):
    l = db.get_lead(lid)
    if not l:
        raise HTTPException(404)
    if not l.get("email"):
        raise HTTPException(400, "No email address on this lead")
    st = await enrichment.send_lead_email(l, force=True)
    return {"ok": st in ("sent", "simulated"), "email_status": st}


@app.post("/api/scan")
async def trigger_scan():
    if state["scanning"]:
        return {"ok": True, "status": "already_scanning"}

    async def _scan_all():
        state["scanning"] = True
        try:
            kws = db.get("keywords")
            for s in SOURCES:
                try:
                    await ingest(s, await s.fetch(kws))
                    state["errors"].pop(s.name, None)
                    state["last_run"][s.name] = time.time()
                except Exception as e:
                    state["errors"][s.name] = str(e)[:100]
        finally:
            state["scanning"] = False

    asyncio.create_task(_scan_all())
    return {"ok": True, "status": "started"}


@app.get("/api/stats")
def stats():
    c = db.conn()
    by = {r[0]: r[1] for r in c.execute("SELECT status,COUNT(*) FROM leads GROUP BY status")}
    with_email = c.execute("SELECT COUNT(*) FROM leads WHERE email != ''").fetchone()[0]
    emailed = c.execute("SELECT COUNT(*) FROM leads WHERE email_status IN ('sent','simulated')").fetchone()[0]
    llm_name = filters.active_llm_provider()
    return {
        "by_status": by,
        "total": sum(by.values()),
        "today": c.execute("SELECT COUNT(*) FROM leads WHERE created_at>?", (time.time() - 86400,)).fetchone()[0],
        "hot": c.execute("SELECT COUNT(*) FROM leads WHERE score>=75 AND status='new'").fetchone()[0],
        "with_email": with_email,
        "emailed": emailed,
        "by_source": {
            r[0]: r[1]
            for r in c.execute("SELECT substr(source,1,instr(source||'/','/')-1),COUNT(*) FROM leads GROUP BY 1")
        },
        "last_run": state["last_run"],
        "errors": state["errors"],
        "scanning": state["scanning"],
        "sources": [s.name for s in SOURCES],
        "inactive": inactive(),
        "llm": bool(llm_name),
        "llm_provider": llm_name or "Heuristic",
        "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN") and notify.chat_id()),
        "serper": bool(os.getenv("SERPER_API_KEY")),
        "hunter": bool(os.getenv("HUNTER_API_KEY")),
        "smtp": bool(os.getenv("SMTP_EMAIL") and os.getenv("SMTP_APP_PASSWORD")),
    }


class Settings(BaseModel):
    keywords: list[str]
    negatives: list[str]
    alert_score: int = 70
    my_services: str = ""
    my_pitch: str = ""
    sender_name: str = ""
    sender_portfolio: str = ""
    sender_company: str = ""
    sender_company_url: str = ""
    auto_email: bool = True


@app.get("/api/settings")
def get_settings():
    keys = (
        "keywords", "negatives", "alert_score", "my_services", "my_pitch",
        "sender_name", "sender_portfolio", "sender_company", "sender_company_url", "auto_email"
    )
    out = {k: db.get(k) for k in keys}
    out["presets"] = db.ROLE_PRESETS
    return out


@app.put("/api/settings")
def put_settings(b: Settings):
    db.put("keywords", [k.strip() for k in b.keywords if k.strip()])
    db.put("negatives", [k.strip() for k in b.negatives if k.strip()])
    db.put("alert_score", b.alert_score)
    if b.my_services.strip():
        db.put("my_services", b.my_services.strip())
    if b.my_pitch.strip():
        db.put("my_pitch", b.my_pitch.strip())
    if b.sender_name.strip():
        db.put("sender_name", b.sender_name.strip())
    if b.sender_portfolio.strip():
        db.put("sender_portfolio", b.sender_portfolio.strip())
    db.put("sender_company", b.sender_company.strip())
    db.put("sender_company_url", b.sender_company_url.strip())
    db.put("auto_email", b.auto_email)
    return {"ok": True}


def _safe_csv(val) -> str:
    s = str(val if val is not None else "").replace("\n", " ").strip()
    if s and s[0] in ("=", "+", "-", "@"):
        return "'" + s
    return s


@app.get("/api/export.csv")
def export():
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow([
        "score", "status", "source", "author", "author_url", "email", "phone",
        "contact_info", "email_status", "url", "service", "lang", "text", "translated_text", "draft"
    ])
    for r in db.conn().execute("SELECT * FROM leads ORDER BY created_at DESC"):
        w.writerow([
            r["score"],
            _safe_csv(r["status"]),
            _safe_csv(r["source"]),
            _safe_csv(r["author"]),
            _safe_csv(r["author_url"]),
            _safe_csv(r["email"]),
            _safe_csv(r["phone"]),
            _safe_csv(r["contact_info"]),
            _safe_csv(r["email_status"]),
            _safe_csv(r["url"]),
            _safe_csv(r["service"]),
            _safe_csv(r["lang"]),
            _safe_csv(r["text"]),
            _safe_csv(r["translated_text"]),
            _safe_csv(r["draft"]),
        ])
    return Response(
        s.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )
