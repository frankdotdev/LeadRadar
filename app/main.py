import asyncio, os, time, csv, io
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from . import db, filters, notify
from .sources import build_sources, inactive

SOURCES = build_sources()
state = {"last_run": {}, "errors": {}, "found": 0}
MAX_AGE = float(os.getenv("MAX_AGE_HOURS", 48)) * 3600
MIN_STORE = int(os.getenv("MIN_STORE_SCORE", 35))

async def ingest(src, posts):
    kws, negs = db.get("keywords"), db.get("negatives")
    now = time.time()
    posts = [p for p in posts if p.get("text") and now - p["posted_at"] < MAX_AGE]
    posts = list({p["uid"]: p for p in posts}.values())  # same post returned by several queries
    seen = db.seen([p["uid"] for p in posts])
    fresh = [p for p in posts if p["uid"] not in seen]
    db.mark_seen([p["uid"] for p in fresh])
    cand = [p for p in fresh if filters.prefilter(p["text"], kws, negs, src.need_intent and not p.get("trusted"))]
    verdicts = await asyncio.gather(*[filters.classify(p["text"], kws) for p in cand])
    for p, v in zip(cand, verdicts):
        if v["score"] < MIN_STORE: continue
        fp = filters.fingerprint(p["text"])
        if db.fp_exists(fp): continue  # same post cross-posted elsewhere
        lead = {**p, "text": p["text"][:2000], **v, "fp": fp}
        lead["id"] = db.insert_lead(lead)
        if not lead["id"]: continue
        state["found"] += 1
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

@asynccontextmanager
async def lifespan(_):
    db.init()
    tasks = [asyncio.create_task(run_source(s)) for s in SOURCES] + [asyncio.create_task(notify.poll())]
    yield
    for t in tasks: t.cancel()

app = FastAPI(lifespan=lifespan, title="LeadRadar")
STATIC = Path(__file__).parent.parent / "static"

@app.get("/")
def index(): return FileResponse(STATIC / "index.html")

@app.get("/api/leads")
def leads(status: str = "", source: str = "", min_score: int = 0, q: str = "", limit: int = 100):
    sql, a = "SELECT * FROM leads WHERE score>=?", [min_score]
    if status: sql += " AND status=?"; a.append(status)
    if source: sql += " AND source LIKE ?"; a.append(source + "%")
    if q: sql += " AND text LIKE ?"; a.append(f"%{q}%")
    return [dict(r) for r in db.conn().execute(sql + " ORDER BY created_at DESC LIMIT ?", a + [limit])]

class Status(BaseModel): status: str

@app.patch("/api/leads/{lid}")
def set_status(lid: int, b: Status):
    if b.status not in {"new", "saved", "contacted", "won", "dismissed"}: raise HTTPException(400, "bad status")
    db.conn().execute("UPDATE leads SET status=? WHERE id=?", (b.status, lid)); return {"ok": True}

@app.post("/api/leads/{lid}/draft")
async def draft(lid: int):
    l = db.get_lead(lid)
    if not l: raise HTTPException(404)
    return {"draft": await filters.draft_reply(l)}

@app.get("/api/stats")
def stats():
    c = db.conn()
    by = {r[0]: r[1] for r in c.execute("SELECT status,COUNT(*) FROM leads GROUP BY status")}
    return {"by_status": by, "total": sum(by.values()), "today": c.execute("SELECT COUNT(*) FROM leads WHERE created_at>?", (time.time() - 86400,)).fetchone()[0],
            "hot": c.execute("SELECT COUNT(*) FROM leads WHERE score>=75 AND status='new'").fetchone()[0],
            "by_source": {r[0]: r[1] for r in c.execute("SELECT substr(source,1,instr(source||'/','/')-1),COUNT(*) FROM leads GROUP BY 1")},
            "last_run": state["last_run"], "errors": state["errors"], "sources": [s.name for s in SOURCES], "inactive": inactive(),
            "llm": bool(os.getenv("GROQ_API_KEY")), "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN") and notify.chat_id())}

class Settings(BaseModel):
    keywords: list[str]; negatives: list[str]; alert_score: int

@app.get("/api/settings")
def get_settings(): return {k: db.get(k) for k in ("keywords", "negatives", "alert_score")}

@app.put("/api/settings")
def put_settings(b: Settings):
    db.put("keywords", [k.strip() for k in b.keywords if k.strip()])
    db.put("negatives", [k.strip() for k in b.negatives if k.strip()]); db.put("alert_score", b.alert_score); return {"ok": True}

@app.get("/api/export.csv")
def export():
    s = io.StringIO(); w = csv.writer(s); w.writerow(["score", "status", "source", "author", "url", "service", "text"])
    for r in db.conn().execute("SELECT * FROM leads ORDER BY created_at DESC"):
        w.writerow([r["score"], r["status"], r["source"], r["author"], r["url"], r["service"], r["text"].replace("\n", " ")])
    return Response(s.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=leads.csv"})
