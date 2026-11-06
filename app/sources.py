"""Add a source = subclass Source, implement fetch(kws) -> list of normalized dicts, append to build_sources()."""
import os, re, time, html, asyncio, itertools, json
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from .net import http

def iso(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return time.time()

def clean(s): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()

def envlist(k): return [x.strip() for x in os.getenv(k, "").split(",") if x.strip()]

def phrases(kws, n=5):
    """Search queries: intent phrase x top keywords."""
    return [f"{i} {k}" for i, k in itertools.product(["looking for a", "i need a", "need someone"], kws[:n])]

class Source:
    name = "base"; interval = 120; need_intent = True
    async def fetch(self, kws): raise NotImplementedError

def parse_feed(xml, source):
    out = []
    root = ET.fromstring(xml)
    A = "{http://www.w3.org/2005/Atom}"
    for it in root.findall(".//item") + root.findall(f".//{A}entry"):
        g = lambda t: (it.findtext(t) or it.findtext(A + t) or "")
        link = g("link") or (it.find(A + "link").get("href") if it.find(A + "link") is not None else "")
        body = clean(g("description") or g("summary") or g("content"))
        when = g("pubDate") or g("updated") or g("published")
        try: ts = parsedate_to_datetime(when).timestamp()
        except Exception: ts = iso(when) if when else time.time()
        au = it.findtext(f"{A}author/{A}name") or g("author") or g("{http://purl.org/dc/elements/1.1/}creator")
        out.append({"uid": f"{source}:{g('guid') or g('id') or link}", "source": source, "author": clean(au),
                    "url": link, "text": f"{clean(g('title'))}\n{body}", "posted_at": ts})
    return out

class HackerNews(Source):
    name = "hackernews"; interval = 120
    async def fetch(self, kws):
        qs = ["looking for developer", "need a developer", "looking for freelancer", "need a website", "hire freelancer"]
        rs = await asyncio.gather(*[http.get("https://hn.algolia.com/api/v1/search_by_date",
              params={"query": q, "tags": "(story,comment)", "hitsPerPage": 40}) for q in qs], return_exceptions=True)
        out = []
        for r in rs:
            if isinstance(r, Exception): continue
            for x in r.json().get("hits", []):
                t = clean(x.get("comment_text") or x.get("story_text") or x.get("title") or "")
                out.append({"uid": f"hn:{x['objectID']}", "source": self.name, "author": x.get("author", ""),
                            "url": f"https://news.ycombinator.com/item?id={x['objectID']}", "text": t,
                            "posted_at": x.get("created_at_i", time.time())})
        return out

class Reddit(Source):
    name = "reddit"; interval = 90
    SUBS = envlist("REDDIT_SUBS") or ["forhire", "slavelabour", "DoneDirtCheap", "hiring", "startups", "Entrepreneur",
            "smallbusiness", "SideProject", "webdev", "nigeria", "lagos", "ecommerce", "shopify", "SaaS"]
    async def one(self, sub):
        r = await http.get(f"https://www.reddit.com/r/{sub}/new.json", params={"limit": 50})
        if r.status_code == 200:
            return [{"uid": f"rd:{d['id']}", "source": f"reddit/r/{sub}", "author": d.get("author", ""),
                     "url": "https://reddit.com" + d["permalink"], "text": f"{d.get('title','')}\n{d.get('selftext','')}",
                     "posted_at": d["created_utc"]} for d in (c["data"] for c in r.json()["data"]["children"])]
        r = await http.get(f"https://www.reddit.com/r/{sub}/new/.rss")  # fallback when JSON is blocked
        return parse_feed(r.text, f"reddit/r/{sub}") if r.status_code == 200 else []
    async def fetch(self, kws):
        rs = await asyncio.gather(*[self.one(s) for s in self.SUBS], return_exceptions=True)
        return [p for r in rs if not isinstance(r, Exception) for p in r]

class Bluesky(Source):
    name = "bluesky"; interval = 45
    async def fetch(self, kws):
        h = {}
        if os.getenv("BSKY_HANDLE") and os.getenv("BSKY_APP_PASSWORD"):
            r = await http.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": os.getenv("BSKY_HANDLE"), "password": os.getenv("BSKY_APP_PASSWORD")})
            if r.status_code == 200: h = {"Authorization": "Bearer " + r.json()["accessJwt"]}
        base = "https://bsky.social" if h else "https://public.api.bsky.app"
        rs = await asyncio.gather(*[http.get(f"{base}/xrpc/app.bsky.feed.searchPosts", headers=h,
              params={"q": q, "sort": "latest", "limit": 30}) for q in phrases(kws, 4)], return_exceptions=True)
        out = []
        for r in rs:
            if isinstance(r, Exception) or r.status_code != 200: continue
            for p in r.json().get("posts", []):
                rk = p["uri"].split("/")[-1]
                out.append({"uid": "bsky:" + p["uri"], "source": self.name, "author": p["author"].get("handle", ""),
                            "url": f"https://bsky.app/profile/{p['author']['handle']}/post/{rk}",
                            "text": p.get("record", {}).get("text", ""), "posted_at": iso(p.get("indexedAt", ""))})
        return out

class Mastodon(Source):
    name = "mastodon"; interval = 60
    TAGS = envlist("MASTODON_TAGS") or ["hiring", "freelance", "forhire", "needadeveloper", "webdev", "needadesigner", "startup"]
    INSTANCES = envlist("MASTODON_INSTANCES") or ["mastodon.social", "mas.to", "fosstodon.org"]
    async def fetch(self, kws):
        jobs = [http.get(f"https://{i}/api/v1/timelines/tag/{t}", params={"limit": 40}) for i in self.INSTANCES for t in self.TAGS]
        out = []
        for r in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(r, Exception) or r.status_code != 200: continue
            for s in r.json():
                out.append({"uid": "masto:" + s["uri"], "source": self.name, "author": s["account"].get("acct", ""),
                            "url": s.get("url") or s["uri"], "text": clean(s.get("content", "")), "posted_at": iso(s["created_at"])})
        return out

class TelegramChannels(Source):
    """Public channels/groups with a web preview (t.me/s/<name>). Set TG_CHANNELS=a,b,c"""
    name = "telegram"; interval = 60
    async def one(self, ch):
        r = await http.get(f"https://t.me/s/{ch}")
        out = []
        for chunk in r.text.split('data-post="')[1:]:
            post = chunk.split('"', 1)[0]
            m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', chunk, re.S)
            d = re.search(r'datetime="([^"]+)"', chunk)
            if m: out.append({"uid": "tg:" + post, "source": f"telegram/{ch}", "author": ch, "url": f"https://t.me/{post}",
                              "text": clean(m.group(1)), "posted_at": iso(d.group(1)) if d else time.time(),
                              "trusted": ch in envlist("TG_JOB_CHANNELS")})
        return out
    async def fetch(self, kws):
        chans = list(dict.fromkeys(envlist("TG_CHANNELS") + envlist("TG_JOB_CHANNELS")))
        rs = await asyncio.gather(*[self.one(c) for c in chans], return_exceptions=True)
        return [p for r in rs if not isinstance(r, Exception) for p in r]

class RSS(Source):
    """Any RSS/Atom feed: job boards, freelance marketplaces' feeds, site search feeds. Set RSS_FEEDS=url1,url2"""
    name = "rss"; interval = 300; need_intent = False  # feeds are already hiring posts
    async def fetch(self, kws):
        urls = envlist("RSS_FEEDS")
        rs = await asyncio.gather(*[http.get(u) for u in urls], return_exceptions=True)
        out = []
        for u, r in zip(urls, rs):
            if isinstance(r, Exception) or r.status_code != 200: continue
            try: out += parse_feed(r.text, "rss/" + re.sub(r"^https?://(www\.)?", "", u).split("/")[0])
            except ET.ParseError: pass
        return out

class X(Source):
    """Official X API v2 recent search (paid tier). Set X_BEARER_TOKEN."""
    name = "x"; interval = 120
    async def fetch(self, kws):
        ks = " OR ".join(f'"{k}"' for k in kws[:6])
        q = f'("looking for a" OR "i need a" OR "need someone" OR "can anyone recommend") ({ks}) -is:retweet -is:reply lang:en'
        r = await http.get("https://api.x.com/2/tweets/search/recent", headers={"Authorization": "Bearer " + os.environ["X_BEARER_TOKEN"]},
              params={"query": q[:500], "max_results": 50, "tweet.fields": "created_at,author_id"})
        if r.status_code != 200: raise RuntimeError(f"X API {r.status_code}")
        return [{"uid": "x:" + t["id"], "source": self.name, "author": t.get("author_id", ""), "url": f"https://x.com/i/status/{t['id']}",
                 "text": t["text"], "posted_at": iso(t.get("created_at", ""))} for t in r.json().get("data", [])]

class Freelancer(Source):
    """Freelancer.com public projects API (no key). Every post is a buyer, so no intent regex needed."""
    name = "freelancer"; interval = 180; need_intent = False
    async def fetch(self, kws):
        rs = await asyncio.gather(*[http.get("https://www.freelancer.com/api/projects/0.1/projects/active/",
              params={"query": k, "limit": 40, "full_description": "true", "compact": "true"}) for k in kws[:8]], return_exceptions=True)
        out = []
        for r in rs:
            if isinstance(r, Exception) or r.status_code != 200: continue
            for p in (r.json().get("result") or {}).get("projects", []):
                b = p.get("budget") or {}
                bud = f"Budget {b.get('minimum')}-{b.get('maximum')} {(p.get('currency') or {}).get('code','')}" if b else ""
                out.append({"uid": f"fl:{p['id']}", "source": self.name, "author": "", "url": "https://www.freelancer.com/projects/" + str(p.get("seo_url", p["id"])),
                            "text": f"{p.get('title','')}\n{p.get('description') or p.get('preview_description') or ''}\n{bud}",
                            "posted_at": p.get("time_submitted", time.time())})
        return out

class Lemmy(Source):
    """Open Lemmy search API (no key)."""
    name = "lemmy"; interval = 120
    async def fetch(self, kws):
        jobs = [http.get(f"https://{i}/api/v3/search", params={"q": q, "type_": "Posts", "sort": "New", "limit": 20})
                for i in (envlist("LEMMY_INSTANCES") or ["lemmy.world"]) for q in phrases(kws, 3)]
        out = []
        for r in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(r, Exception) or r.status_code != 200: continue
            for x in r.json().get("posts", []):
                p = x["post"]
                out.append({"uid": "lemmy:" + p["ap_id"], "source": self.name, "author": x["creator"].get("name", ""), "url": p["ap_id"],
                            "text": f"{p.get('name','')}\n{p.get('body') or ''}", "posted_at": iso(p.get("published", ""))})
        return out

class Nairaland(Source):
    """Nairaland boards, newest topics first (/<board>/new). No key. HTML scraping, so it can break if the site changes.
    Titles are screened first, then only promising threads are opened to read the first post."""
    name = "nairaland"; interval = 300; need_intent = False
    BASE = "https://www.nairaland.com"
    LINK = re.compile(r'<a[^>]+href="(?:https?://www\.nairaland\.com)?/(\d{5,9})/([a-z0-9._\-]+)"[^>]*>(.*?)</a>', re.S | re.I)
    WANT = re.compile(r"\b(need(ed|s)?|want(ed)?|looking for|hiring|seeking|require[sd]?|recommend\w*|who can|anyone|help|urgent(ly)?|gig|project|freelanc\w*)\b", re.I)
    FULLTIME = re.compile(r"\b(vacanc(y|ies)|full[- ]time|intern(ship)?s?|graduate trainee|recruitment|apply now|salary|shortlist|resume)\b", re.I)
    SEM = asyncio.Semaphore(5)

    async def thread(self, tid, slug):
        async with self.SEM:
            r = await http.get(f"{self.BASE}/{tid}/{slug}")
        if r.status_code != 200: return ""
        m = re.search(r'<div class="narrow">(.*?)</div>', r.text, re.S)
        if m: return clean(m.group(1))[:1500]
        m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', r.text, re.I) or \
            re.search(r'<meta[^>]+content="([^"]*)"[^>]+name="description"', r.text, re.I)
        return clean(m.group(1)) if m else ""

    async def board(self, board, kws):
        r = await http.get(f"{self.BASE}/{board}/new")
        if r.status_code != 200: raise RuntimeError(f"nairaland {r.status_code}")
        topics, seen = [], set()
        for m in self.LINK.finditer(r.text):
            tid, slug, title = int(m.group(1)), m.group(2), clean(m.group(3))
            if tid in seen or not title or title.isdigit(): continue
            seen.add(tid)
            by = re.search(r"Created by\s*(?:<[^>]+>\s*)*([A-Za-z0-9_.\-]+)", r.text[m.end():m.end() + 700])
            topics.append((tid, slug, title, by.group(1) if by else ""))
        if not topics: return []
        top = max(t[0] for t in topics)
        include_jobs = os.getenv("NAIRALAND_INCLUDE_JOBS", "false").lower() == "true"
        keep = [t for t in topics if t[0] > top - 3000  # skips old stickies
                and (include_jobs or not self.FULLTIME.search(t[2]))
                and (self.WANT.search(t[2]) or any(k.lower() in t[2].lower() for k in kws))][:15]
        bodies = await asyncio.gather(*[self.thread(t[0], t[1]) for t in keep], return_exceptions=True)
        return [{"uid": f"nl:{t[0]}", "source": f"nairaland/{board}", "author": t[3], "url": f"{self.BASE}/{t[0]}/{t[1]}",
                 "text": f"{t[2]}\n{b if isinstance(b, str) else ''}", "posted_at": time.time()} for t, b in zip(keep, bodies)]

    async def fetch(self, kws):
        boards = envlist("NAIRALAND_BOARDS") or ["jobs", "business", "webmasters", "programming", "techmarket"]
        rs = await asyncio.gather(*[self.board(b, kws) for b in boards], return_exceptions=True)
        if all(isinstance(r, Exception) for r in rs): raise rs[0]
        return [p for r in rs if not isinstance(r, Exception) for p in r]

def _pick(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}): return v
    return None

def _name(v):
    if isinstance(v, dict): return str(_pick(v, ["name", "fullName", "username", "screen_name", "handle", "publicIdentifier"]) or "")
    return str(v or "")

def _subst(obj, queries):
    if obj == "{keywords}": return queries
    if obj == "{query}": return queries[0]
    if isinstance(obj, dict): return {k: _subst(v, queries) for k, v in obj.items()}
    if isinstance(obj, list): return [y for x in obj for y in (_subst(x, queries) if x == "{keywords}" else [_subst(x, queries)])]
    return obj

def map_item(it, label):
    """Best-effort mapping: Apify actors name their output fields differently."""
    text = " ".join(str(_pick(it, [k]) or "") for k in ["title", "text", "postText", "content", "full_text", "fullText", "description", "caption", "message", "body"]).strip()
    url = _pick(it, ["url", "postUrl", "post_url", "link", "permalink", "projectUrl", "tweetUrl", "twitterUrl"]) or ""
    when = _pick(it, ["postedAt", "posted_at", "timestamp", "createdAt", "created_at", "date", "time", "publishedAt"])
    ts = time.time()
    if isinstance(when, (int, float)): ts = when / 1000 if when > 1e11 else when
    elif isinstance(when, dict): ts = iso(str(_pick(when, ["date", "timestamp"]) or "")) if isinstance(_pick(when, ["date", "timestamp"]), str) else ts
    elif isinstance(when, str): ts = iso(when)
    uid = _pick(it, ["id", "postId", "post_id", "urn", "tweetId"]) or url or text[:80]
    return {"uid": f"{label}:{uid}", "source": label, "author": _name(_pick(it, ["author", "authorName", "username", "user", "profile", "owner"])),
            "url": str(url), "text": text, "posted_at": ts}

class ApifyActor(Source):
    """Any Apify actor (LinkedIn, X, Facebook...). Only runs when APIFY_TOKEN is set. Config comes from APIFY_ACTORS (JSON)."""
    need_intent = True
    def __init__(self, cfg):
        self.cfg, self.name = cfg, cfg["name"]
        self.interval = max(int(cfg.get("interval", 900)), 300)  # each run costs money, so never faster than 5 min
        self.need_intent = cfg.get("need_intent", True)
    async def fetch(self, kws):
        queries = [f"{i} {k}" for i in self.cfg.get("intents", ["looking for a", "i need a"]) for k in kws[:int(self.cfg.get("max_keywords", 3))]]
        body = _subst(self.cfg.get("input", {"query": "{query}"}), queries)
        actor = self.cfg["actor"].replace("/", "~")
        r = await http.post(f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
                            params={"token": os.environ["APIFY_TOKEN"], "timeout": 240}, json=body, timeout=270)
        if r.status_code not in (200, 201): raise RuntimeError(f"Apify {r.status_code}")
        return [map_item(i, self.name) for i in r.json() if isinstance(i, dict)]

def apify_sources():
    if not os.getenv("APIFY_TOKEN"): return []
    try: cfgs = json.loads(os.getenv("APIFY_ACTORS", "[]"))
    except ValueError: return []
    return [ApifyActor(c) for c in cfgs if c.get("actor") and c.get("name")]

def inactive():
    """Which optional sources are off and what turns them on (shown in the dashboard)."""
    off = {}
    if not os.getenv("X_BEARER_TOKEN"): off["x"] = "set X_BEARER_TOKEN"
    if not os.getenv("APIFY_TOKEN"): off["apify (LinkedIn/Facebook/X)"] = "set APIFY_TOKEN + APIFY_ACTORS"
    if not (envlist("TG_CHANNELS") or envlist("TG_JOB_CHANNELS")): off["telegram"] = "set TG_CHANNELS"
    if not envlist("RSS_FEEDS"): off["rss"] = "set RSS_FEEDS"
    return off

def build_sources():
    s = [HackerNews(), Reddit(), Bluesky(), Mastodon(), Freelancer(), Lemmy(), Nairaland()]
    if envlist("TG_CHANNELS") or envlist("TG_JOB_CHANNELS"): s.append(TelegramChannels())
    if envlist("RSS_FEEDS"): s.append(RSS())
    if os.getenv("X_BEARER_TOKEN"): s.append(X())
    return s + apify_sources()
