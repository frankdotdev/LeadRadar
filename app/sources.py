"""Global multi-platform & multilingual ingestion sources (Americas, Europe, China, Asia, Africa + X, LinkedIn, Facebook, Meta Threads)."""
import os, re, time, html, asyncio, itertools, json
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, unquote
from .net import http


def iso(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


def clean(s):
    s = html.unescape(s or "")
    # Preserve mailto: email links and anchor URLs before stripping HTML tags
    s = re.sub(r'href=["\']mailto:([^"\'?\s>]+)["\']', r" \1 ", s, flags=re.I)
    s = re.sub(r'<a[^>]+href=["\'](https?://[^"\'>\s]+)["\'][^>]*>(.*?)</a>', r"\2 (\1) ", s, flags=re.I | re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def envlist(k):
    return [x.strip() for x in os.getenv(k, "").split(",") if x.strip()]


def phrases(kws, n=5):
    """Search queries: intent phrase x top keywords."""
    top = [k for k in (kws or []) if k][:n] or ["developer", "designer", "copywriter"]
    return [f"{i} {k}" for i, k in itertools.product(["looking for a", "need a", "hiring a"], top)]


class Source:
    name = "base"
    interval = 120
    need_intent = True

    async def fetch(self, kws):
        raise NotImplementedError


def parse_feed(xml, source):
    out = []
    root = ET.fromstring(xml)
    A = "{http://www.w3.org/2005/Atom}"
    for it in root.findall(".//item") + root.findall(f".//{A}entry"):
        g = lambda t: (it.findtext(t) or it.findtext(A + t) or "")
        link = g("link") or (it.find(A + "link").get("href") if it.find(A + "link") is not None else "")
        body = clean(g("description") or g("summary") or g("content"))
        when = g("pubDate") or g("updated") or g("published")
        try:
            ts = parsedate_to_datetime(when).timestamp()
        except Exception:
            ts = iso(when) if when else time.time()
        au = it.findtext(f"{A}author/{A}name") or g("author") or g("{http://purl.org/dc/elements/1.1/}creator")
        out.append({
            "uid": f"{source}:{g('guid') or g('id') or link}",
            "source": source,
            "author": clean(au),
            "url": link,
            "text": f"{clean(g('title'))}\n{body}",
            "posted_at": ts,
        })
    return out


class HackerNews(Source):
    name = "hackernews"
    interval = 120

    async def fetch(self, kws):
        top = (kws or ["developer", "freelancer", "designer"])[:5]
        qs = [f"looking for {k}" for k in top[:3]] + [f"hire {k}" for k in top[:3]] + ["need a freelancer", "looking for agency"]
        rs = await asyncio.gather(
            *[
                http.get(
                    "https://hn.algolia.com/api/v1/search_by_date",
                    params={"query": q, "tags": "(story,comment)", "hitsPerPage": 35},
                )
                for q in qs
            ],
            return_exceptions=True,
        )
        out = []
        for r in rs:
            if isinstance(r, Exception) or r.status_code != 200:
                continue
            for x in r.json().get("hits", []):
                t = clean(x.get("comment_text") or x.get("story_text") or x.get("title") or "")
                out.append({
                    "uid": f"hn:{x['objectID']}",
                    "source": self.name,
                    "author": x.get("author", ""),
                    "url": f"https://news.ycombinator.com/item?id={x['objectID']}",
                    "text": t,
                    "posted_at": x.get("created_at_i", time.time()),
                })
        return out


class Reddit(Source):
    name = "reddit"
    interval = 90
    SUBS = envlist("REDDIT_SUBS") or [
        "forhire", "HireAWriter", "DesignJobs", "jobbit", "slavelabour", "DoneDirtCheap", "hiring",
        "startups", "Entrepreneur", "smallbusiness", "SideProject", "SaaS", "webdev", "reactjs",
        "nextjs", "node", "Python", "shopify", "ecommerce", "wordpress", "Automate", "AI_Agents",
        "LocalLLaMA", "marketing", "PPC", "SEO", "copywriting", "VideoEditing", "freelance",
        "nigeria", "lagos", "ukjobs", "freelance_de", "buhaydigital", "developersIndia", "brdev"
    ]

    async def one(self, sub):
        r = await http.get(f"https://www.reddit.com/r/{sub}/new.json", params={"limit": 45})
        if r.status_code == 200:
            return [
                {
                    "uid": f"rd:{d['id']}",
                    "source": f"reddit/r/{sub}",
                    "author": d.get("author", ""),
                    "url": "https://reddit.com" + d["permalink"],
                    "text": f"{d.get('title','')}\n{d.get('selftext','')}",
                    "posted_at": d["created_utc"],
                }
                for d in (c["data"] for c in r.json().get("data", {}).get("children", []))
            ]
        r = await http.get(f"https://www.reddit.com/r/{sub}/new/.rss")
        return parse_feed(r.text, f"reddit/r/{sub}") if r.status_code == 200 else []

    async def search_global(self, kws):
        """Global Reddit search across all subreddits worldwide."""
        top = (kws or ["developer", "designer", "copywriter"])[:5]
        queries = [
            f'("hiring" OR "looking for") ({ " OR ".join(top[:3]) })',
            f'("need a" OR "anyone recommend") ({ " OR ".join(top[2:5] or top[:2]) })',
        ]
        out = []
        for q in queries:
            r = await http.get(
                "https://www.reddit.com/search.json",
                params={"q": q, "sort": "new", "t": "week", "limit": 35},
            )
            if r.status_code == 200:
                for c in r.json().get("data", {}).get("children", []):
                    d = c["data"]
                    out.append({
                        "uid": f"rd:{d['id']}",
                        "source": f"reddit/r/{d.get('subreddit', 'search')}",
                        "author": d.get("author", ""),
                        "url": "https://reddit.com" + d.get("permalink", ""),
                        "text": f"{d.get('title','')}\n{d.get('selftext','')}",
                        "posted_at": d.get("created_utc", time.time()),
                    })
        return out

    async def fetch(self, kws):
        jobs = [self.one(s) for s in self.SUBS] + [self.search_global(kws)]
        rs = await asyncio.gather(*jobs, return_exceptions=True)
        return [p for r in rs if not isinstance(r, Exception) for p in r]


class Bluesky(Source):
    name = "bluesky"
    interval = 50

    async def fetch(self, kws):
        h = {}
        if os.getenv("BSKY_HANDLE") and os.getenv("BSKY_APP_PASSWORD"):
            r = await http.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": os.getenv("BSKY_HANDLE"), "password": os.getenv("BSKY_APP_PASSWORD")},
            )
            if r.status_code == 200:
                h = {"Authorization": "Bearer " + r.json()["accessJwt"]}
        base = "https://bsky.social" if h else "https://public.api.bsky.app"
        # Include English + multilingual queries on Bluesky
        search_qs = phrases(kws, 4) + ["busco desarrollador", "cherche freelance", "looking for freelancer"]
        rs = await asyncio.gather(
            *[
                http.get(
                    f"{base}/xrpc/app.bsky.feed.searchPosts",
                    headers=h,
                    params={"q": q, "sort": "latest", "limit": 30},
                )
                for q in search_qs
            ],
            return_exceptions=True,
        )
        out = []
        for r in rs:
            if isinstance(r, Exception) or r.status_code != 200:
                continue
            for p in r.json().get("posts", []):
                rk = p["uri"].split("/")[-1]
                out.append({
                    "uid": "bsky:" + p["uri"],
                    "source": self.name,
                    "author": p["author"].get("handle", ""),
                    "url": f"https://bsky.app/profile/{p['author']['handle']}/post/{rk}",
                    "text": p.get("record", {}).get("text", ""),
                    "posted_at": iso(p.get("indexedAt", "")),
                })
        return out


class Mastodon(Source):
    name = "mastodon"
    interval = 90
    TAGS = envlist("MASTODON_TAGS") or [
        "hiring", "forhire", "freelance", "getfedihired", "jobs", "remotejobs", "webdev", "copywriting"
    ]
    INSTANCES = envlist("MASTODON_INSTANCES") or [
        "mastodon.social", "fosstodon.org", "hachyderm.io", "indieweb.social"
    ]

    async def fetch(self, kws):
        jobs = [http.get(f"https://{i}/api/v1/timelines/tag/{t}", params={"limit": 25}) for i in self.INSTANCES[:4] for t in self.TAGS[:6]]
        out = []
        for r in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(r, Exception) or r.status_code != 200:
                continue
            for s in r.json():
                out.append({
                    "uid": "masto:" + s["uri"],
                    "source": self.name,
                    "author": s["account"].get("acct", ""),
                    "url": s.get("url") or s["uri"],
                    "text": clean(s.get("content", "")),
                    "posted_at": iso(s["created_at"]),
                })
        return out


class V2EX(Source):
    """V2EX (China & Asia largest developer, startup & outsourcing community) — Free JSON API."""
    name = "v2ex"
    interval = 180
    need_intent = False  # Posts in jobs/outsourcing/create nodes are already project/role requests

    async def _node(self, node: str) -> list[dict]:
        r = await http.get(f"https://www.v2ex.com/api/topics/show.json", params={"node_name": node}, timeout=15)
        if r.status_code != 200 or not isinstance(r.json(), list):
            return []
        out = []
        for t in r.json():
            tid = t.get("id")
            title = clean(t.get("title") or "")
            body = clean(t.get("content") or "")
            member = (t.get("member") or {}).get("username") or ""
            out.append({
                "uid": f"v2ex:{tid}",
                "source": f"v2ex/{node}",
                "author": member,
                "url": t.get("url") or f"https://www.v2ex.com/t/{tid}",
                "text": f"{title}\n{body}",
                "posted_at": t.get("created", time.time()),
                "trusted": node in ("jobs", "outsourcing"),
            })
        return out

    async def fetch(self, kws):
        nodes = ["jobs", "outsourcing", "career", "create"]
        rs = await asyncio.gather(*[self._node(n) for n in nodes], return_exceptions=True)
        return [p for r in rs if not isinstance(r, Exception) for p in r]


class SerperXRay(Source):
    """Google X-Ray Search via Serper.dev across X/Twitter, LinkedIn, Facebook, Meta Threads, Notion Briefs, Europe, Asia & Americas."""
    name = "serper"
    interval = int(os.getenv("SERPER_INTERVAL", "240"))
    need_intent = False

    def _build_queries(self, kws: list[str]) -> list[tuple[str, str]]:
        top = [k for k in (kws or []) if k][:6] or ["developer", "designer", "copywriter", "google ads"]
        kw1 = top[0] if len(top) > 0 else "developer"
        kw2 = top[1] if len(top) > 1 else "website"
        kw3 = top[2] if len(top) > 2 else "mobile app"
        kw4 = top[3] if len(top) > 3 else "copywriter"

        return [
            # X / Twitter (both x.com and twitter.com)
            ("x/xray", f'site:x.com "looking for a" ("{kw1}" OR "{kw2}" OR "freelancer" OR "developer")'),
            ("x/xray", f'site:twitter.com "looking for a" ("{kw1}" OR "{kw3}" OR "designer" OR "agency")'),
            ("x/xray", f'site:x.com ("need someone to build" OR "hiring a freelance" OR "drop your portfolio")'),
            # Facebook Public Posts & Groups
            ("facebook/xray", f'site:facebook.com "looking for a" ("{kw1}" OR "{kw2}" OR "web developer" OR "designer")'),
            ("facebook/xray", f'site:facebook.com/groups ("looking for" OR "need someone" OR "hiring") ("{kw1}" OR "{kw3}" OR "website")'),
            # LinkedIn Posts
            ("linkedin/xray", f'site:linkedin.com/posts ("looking for a" OR "hiring a freelance") ("{kw1}" OR "{kw2}" OR "{kw4}")'),
            ("linkedin/xray", f'site:linkedin.com/posts ("drop your portfolio" OR "send your portfolio" OR "need a freelancer")'),
            # Meta Threads (threads.net & threads.com)
            ("threads/xray", f'site:threads.net ("looking for a" OR "need a" OR "hiring") ("{kw1}" OR "developer" OR "designer" OR "editor")'),
            ("threads/xray", f'site:threads.com ("looking for a" OR "need a" OR "hiring") ("{kw1}" OR "developer" OR "designer")'),
            # Notion Briefs & Google Forms Applications
            ("briefs/xray", f'site:notion.site ("hiring" OR "looking for" OR "project brief") ("{kw1}" OR "{kw2}" OR "freelance")'),
            # Europe & LATAM Multilingual (Spanish, French, German, Portuguese)
            ("global/europe-latam", f'("busco desarrollador" OR "necesito programador" OR "je cherche un développeur" OR "ich suche entwickler" OR "procuro freelancer")'),
            # China & Asia Multilingual
            ("global/asia", f'("寻找开发" OR "外包项目" OR "远程开发" OR "急招远程" OR "hiring remote developer asia")'),
        ]

    async def _one_query(self, label: str, q: str, key: str) -> list[dict]:
        payload = {"q": q, "num": 15}
        tbs = os.getenv("SERPER_TBS", "qdr:m").strip()
        if tbs:
            payload["tbs"] = tbs
        r = await http.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json=payload,
            timeout=18,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Serper {r.status_code}")
        out = []
        for it in r.json().get("organic", []):
            link = it.get("link") or ""
            title = clean(it.get("title") or "")
            snippet = clean(it.get("snippet") or "")
            if not link or not (title or snippet):
                continue
            author = ""
            if "x.com/" in link or "twitter.com/" in link:
                m_x = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,25})", link, re.I)
                if m_x and m_x.group(1).lower() not in ("i", "search", "explore", "home", "hashtag"):
                    author = f"@{m_x.group(1)}"
            elif "threads." in link:
                m_th = re.search(r"threads\.(?:net|com)/@?([A-Za-z0-9_.\-]{1,30})", link, re.I)
                if m_th:
                    author = f"@{m_th.group(1).lstrip('@')}"
            elif "linkedin.com" in link:
                author = title.split(" on LinkedIn")[0].split(" | ")[0].split(" - ")[0][:40]
            elif "facebook.com" in link:
                author = title.split(" - ")[0].split(" | ")[0][:40]
            out.append({
                "uid": f"srp:{link}",
                "source": label,
                "author": author,
                "url": link,
                "text": f"{title}\n{snippet}",
                "posted_at": time.time(),
                "trusted": True,
            })
        return out

    async def fetch(self, kws):
        key = os.getenv("SERPER_API_KEY", "").strip()
        if not key:
            return []
        queries = self._build_queries(kws)
        rs = await asyncio.gather(*[self._one_query(lbl, q, key) for lbl, q in queries], return_exceptions=True)
        if all(isinstance(r, Exception) for r in rs):
            raise rs[0]
        return [p for r in rs if not isinstance(r, Exception) for p in r]


class SocialWebXRay(Source):
    """Free Zero-Key Social X-Ray Search across X, LinkedIn, Facebook & Meta Threads via DuckDuckGo HTML."""
    name = "social_xray"
    interval = 210
    need_intent = False
    RESULT_RE = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.S | re.I,
    )

    def _queries(self, kws: list[str]) -> list[tuple[str, str]]:
        top = [k for k in (kws or []) if k][:4] or ["developer", "designer", "copywriter"]
        k_str = " OR ".join(f'"{k}"' for k in top[:3])
        return [
            ("x/web", f'site:x.com ("looking for a" OR "hiring a" OR "need a") ({k_str})'),
            ("linkedin/web", f'site:linkedin.com/posts ("looking for" OR "hiring" OR "freelance") ({k_str})'),
            ("facebook/web", f'site:facebook.com ("looking for a" OR "need someone" OR "hiring") ({k_str})'),
            ("threads/web", f'site:threads.net ("looking for" OR "need a" OR "hiring") ({k_str})'),
        ]

    async def _one(self, label: str, q: str) -> list[dict]:
        r = await http.post(
            "https://html.duckduckgo.com/html/",
            data={"q": q, "df": "w"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        out = []
        for m in self.RESULT_RE.finditer(r.text):
            raw_href, raw_title, raw_snip = m.group(1), m.group(2), m.group(3)
            if "uddg=" in raw_href:
                raw_href = unquote(raw_href.split("uddg=", 1)[1].split("&", 1)[0])
            link = html.unescape(raw_href).strip()
            if not link.startswith("http"):
                continue
            title = clean(raw_title)
            snip = clean(raw_snip)
            out.append({
                "uid": f"ddg:{link}",
                "source": label,
                "author": "",
                "url": link,
                "text": f"{title}\n{snip}",
                "posted_at": time.time(),
                "trusted": True,
            })
        return out

    async def fetch(self, kws):
        rs = await asyncio.gather(*[self._one(lbl, q) for lbl, q in self._queries(kws)], return_exceptions=True)
        return [p for r in rs if not isinstance(r, Exception) for p in r]


class TelegramChannels(Source):
    """Public channels/groups with a web preview (t.me/s/<name>). Set TG_CHANNELS=a,b,c"""
    name = "telegram"
    interval = 60

    async def one(self, ch):
        r = await http.get(f"https://t.me/s/{ch}")
        out = []
        for chunk in r.text.split('data-post="')[1:]:
            post = chunk.split('"', 1)[0]
            m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', chunk, re.S)
            d = re.search(r'datetime="([^"]+)"', chunk)
            if m:
                out.append({
                    "uid": "tg:" + post,
                    "source": f"telegram/{ch}",
                    "author": ch,
                    "url": f"https://t.me/{post}",
                    "text": clean(m.group(1)),
                    "posted_at": iso(d.group(1)) if d else time.time(),
                    "trusted": ch in envlist("TG_JOB_CHANNELS"),
                })
        return out

    async def fetch(self, kws):
        chans = list(dict.fromkeys(envlist("TG_CHANNELS") + envlist("TG_JOB_CHANNELS")))
        rs = await asyncio.gather(*[self.one(c) for c in chans], return_exceptions=True)
        return [p for r in rs if not isinstance(r, Exception) for p in r]


class RSS(Source):
    """Any RSS/Atom feed: job boards, freelance marketplaces' feeds, site search feeds. Set RSS_FEEDS=url1,url2"""
    name = "rss"
    interval = 300
    need_intent = False

    async def fetch(self, kws):
        urls = envlist("RSS_FEEDS")
        rs = await asyncio.gather(*[http.get(u) for u in urls], return_exceptions=True)
        out = []
        for u, r in zip(urls, rs):
            if isinstance(r, Exception) or r.status_code != 200:
                continue
            try:
                out += parse_feed(r.text, "rss/" + re.sub(r"^https?://(www\.)?", "", u).split("/")[0])
            except ET.ParseError:
                pass
        return out


class X(Source):
    """Official X API v2 recent search (paid tier). Set X_BEARER_TOKEN."""
    name = "x"
    interval = 120

    async def fetch(self, kws):
        ks = " OR ".join(f'"{k}"' for k in kws[:6])
        q = f'("looking for a" OR "i need a" OR "need someone" OR "hiring a" OR "can anyone recommend") ({ks}) -is:retweet -is:reply'
        r = await http.get(
            "https://api.x.com/2/tweets/search/recent",
            headers={"Authorization": "Bearer " + os.environ["X_BEARER_TOKEN"]},
            params={"query": q[:500], "max_results": 50, "tweet.fields": "created_at,author_id"},
        )
        if r.status_code != 200:
            raise RuntimeError(f"X API {r.status_code}")
        return [
            {
                "uid": "x:" + t["id"],
                "source": self.name,
                "author": t.get("author_id", ""),
                "url": f"https://x.com/i/status/{t['id']}",
                "text": t["text"],
                "posted_at": iso(t.get("created_at", "")),
            }
            for t in r.json().get("data", [])
        ]


class Freelancer(Source):
    """Freelancer.com public projects API (no key). Every post is a buyer, so no intent regex needed."""
    name = "freelancer"
    interval = 180
    need_intent = False

    async def fetch(self, kws):
        rs = await asyncio.gather(
            *[
                http.get(
                    "https://www.freelancer.com/api/projects/0.1/projects/active/",
                    params={"query": k, "limit": 35, "full_description": "true", "compact": "true"},
                )
                for k in (kws or [])[:8]
            ],
            return_exceptions=True,
        )
        out = []
        for r in rs:
            if isinstance(r, Exception) or r.status_code != 200:
                continue
            for p in (r.json().get("result") or {}).get("projects", []):
                b = p.get("budget") or {}
                bud = f"Budget {b.get('minimum')}-{b.get('maximum')} {(p.get('currency') or {}).get('code','')}" if b else ""
                out.append({
                    "uid": f"fl:{p['id']}",
                    "source": self.name,
                    "author": "",
                    "url": "https://www.freelancer.com/projects/" + str(p.get("seo_url", p["id"])),
                    "text": f"{p.get('title','')}\n{p.get('description') or p.get('preview_description') or ''}\n{bud}",
                    "posted_at": p.get("time_submitted", time.time()),
                })
        return out


class Lemmy(Source):
    """Open Lemmy search API (no key)."""
    name = "lemmy"
    interval = 120

    async def fetch(self, kws):
        instances = envlist("LEMMY_INSTANCES") or [
            "lemmy.world", "programming.dev", "lemmy.ml", "sh.itjust.works", "lemmy.ca", "feddit.org"
        ]
        jobs = [
            http.get(f"https://{i}/api/v3/search", params={"q": q, "type_": "Posts", "sort": "New", "limit": 20})
            for i in instances
            for q in phrases(kws, 3)
        ]
        out = []
        for r in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(r, Exception) or r.status_code != 200:
                continue
            for x in r.json().get("posts", []):
                p = x["post"]
                out.append({
                    "uid": "lemmy:" + p["ap_id"],
                    "source": self.name,
                    "author": x["creator"].get("name", ""),
                    "url": p["ap_id"],
                    "text": f"{p.get('name','')}\n{p.get('body') or ''}",
                    "posted_at": iso(p.get("published", "")),
                })
        return out


class Nairaland(Source):
    """Nairaland boards, newest topics first (/<board>/new). No key."""
    name = "nairaland"
    interval = 300
    need_intent = False
    BASE = "https://www.nairaland.com"
    LINK = re.compile(r'<a[^>]+href="(?:https?://www\.nairaland\.com)?/(\d{5,9})/([a-z0-9._\-]+)"[^>]*>(.*?)</a>', re.S | re.I)
    WANT = re.compile(r"\b(need(ed|s)?|want(ed)?|looking for|hiring|seeking|require[sd]?|recommend\w*|who can|anyone|help|urgent(ly)?|gig|project|freelanc\w*|writer|copywriter|designer|developer|ads|marketer)\b", re.I)
    FULLTIME = re.compile(r"\b(vacanc(y|ies)|full[- ]time|intern(ship)?s?|graduate trainee|recruitment|apply now|salary|shortlist|resume)\b", re.I)
    SEM = asyncio.Semaphore(5)

    async def thread(self, tid, slug):
        async with self.SEM:
            r = await http.get(f"{self.BASE}/{tid}/{slug}")
        if r.status_code != 200:
            return ""
        m = re.search(r'<div class="narrow">(.*?)</div>', r.text, re.S)
        if m:
            return clean(m.group(1))[:1500]
        m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', r.text, re.I) or \
            re.search(r'<meta[^>]+content="([^"]*)"[^>]+name="description"', r.text, re.I)
        return clean(m.group(1)) if m else ""

    async def board(self, board, kws):
        r = await http.get(f"{self.BASE}/{board}/new")
        if r.status_code != 200:
            raise RuntimeError(f"nairaland {r.status_code}")
        topics, seen = [], set()
        for m in self.LINK.finditer(r.text):
            tid, slug, title = int(m.group(1)), m.group(2), clean(m.group(3))
            if tid in seen or not title or title.isdigit():
                continue
            seen.add(tid)
            by = re.search(r"Created by\s*(?:<[^>]+>\s*)*([A-Za-z0-9_.\-]+)", r.text[m.end():m.end() + 700])
            topics.append((tid, slug, title, by.group(1) if by else ""))
        if not topics:
            return []
        top = max(t[0] for t in topics)
        include_jobs = os.getenv("NAIRALAND_INCLUDE_JOBS", "false").lower() == "true"
        keep = [
            t for t in topics
            if t[0] > top - 3000
            and (include_jobs or not self.FULLTIME.search(t[2]))
            and (self.WANT.search(t[2]) or any(k.lower() in t[2].lower() for k in kws))
        ][:15]
        bodies = await asyncio.gather(*[self.thread(t[0], t[1]) for t in keep], return_exceptions=True)
        return [
            {
                "uid": f"nl:{t[0]}",
                "source": f"nairaland/{board}",
                "author": t[3],
                "url": f"{self.BASE}/{t[0]}/{t[1]}",
                "text": f"{t[2]}\n{b if isinstance(b, str) else ''}",
                "posted_at": time.time(),
            }
            for t, b in zip(keep, bodies)
        ]

    async def fetch(self, kws):
        boards = envlist("NAIRALAND_BOARDS") or [
            "jobs", "business", "webmasters", "programming", "techmarket", "career", "graphics", "computers", "investment", "adverts"
        ]
        rs = await asyncio.gather(*[self.board(b, kws) for b in boards], return_exceptions=True)
        if all(isinstance(r, Exception) for r in rs):
            raise rs[0]
        return [p for r in rs if not isinstance(r, Exception) for p in r]


def _pick(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _name(v):
    if isinstance(v, dict):
        return str(_pick(v, ["name", "fullName", "username", "screen_name", "handle", "publicIdentifier"]) or "")
    return str(v or "")


def _subst(obj, queries):
    if obj == "{keywords}":
        return queries
    if obj == "{query}":
        return queries[0]
    if isinstance(obj, dict):
        return {k: _subst(v, queries) for k, v in obj.items()}
    if isinstance(obj, list):
        return [y for x in obj for y in (_subst(x, queries) if x == "{keywords}" else [_subst(x, queries)])]
    return obj


def map_item(it, label):
    """Best-effort mapping: Apify actors name their output fields differently."""
    text = " ".join(
        str(_pick(it, [k]) or "")
        for k in ["title", "text", "postText", "content", "full_text", "fullText", "description", "caption", "message", "body"]
    ).strip()
    url = _pick(it, ["url", "postUrl", "post_url", "link", "permalink", "projectUrl", "tweetUrl", "twitterUrl"]) or ""
    when = _pick(it, ["postedAt", "posted_at", "timestamp", "createdAt", "created_at", "date", "time", "publishedAt"])
    ts = time.time()
    if isinstance(when, (int, float)):
        ts = when / 1000 if when > 1e11 else when
    elif isinstance(when, dict):
        ts = iso(str(_pick(when, ["date", "timestamp"]) or "")) if isinstance(_pick(when, ["date", "timestamp"]), str) else ts
    elif isinstance(when, str):
        ts = iso(when)
    uid = _pick(it, ["id", "postId", "post_id", "urn", "tweetId"]) or url or text[:80]
    return {
        "uid": f"{label}:{uid}",
        "source": label,
        "author": _name(_pick(it, ["author", "authorName", "username", "user", "profile", "owner"])),
        "url": str(url),
        "text": text,
        "posted_at": ts,
    }


class ApifyActor(Source):
    """Any Apify actor (LinkedIn, X, Facebook, Threads...). Only runs when APIFY_TOKEN is set."""
    need_intent = True

    def __init__(self, cfg):
        self.cfg, self.name = cfg, cfg["name"]
        self.interval = max(int(cfg.get("interval", 900)), 300)
        self.need_intent = cfg.get("need_intent", True)

    async def fetch(self, kws):
        actor_raw = self.cfg.get("actor", "")
        if not actor_raw or "PUT_" in actor_raw:
            return []
        queries = [
            f"{i} {k}"
            for i in self.cfg.get("intents", ["looking for a", "i need a", "hiring a"])
            for k in (kws or [])[:int(self.cfg.get("max_keywords", 3))]
        ]
        body = _subst(self.cfg.get("input", {"query": "{query}"}), queries)
        actor = actor_raw.replace("/", "~")
        token = os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN") or ""
        r = await http.post(
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
            params={"token": token, "timeout": 240},
            json=body,
            timeout=270,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Apify {r.status_code}")
        return [map_item(i, self.name) for i in r.json() if isinstance(i, dict)]


def apify_sources():
    if not (os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN")):
        return []
    try:
        cfgs = json.loads(os.getenv("APIFY_ACTORS", "[]"))
    except ValueError:
        return []
    return [
        ApifyActor(c)
        for c in cfgs
        if c.get("actor") and c.get("name") and "PUT_" not in c.get("actor", "") and "SOME_PUBLIC_PAGE" not in json.dumps(c.get("input", {}))
    ]


def inactive():
    """Which optional sources/integrations are off and what turns them on (shown in the dashboard)."""
    off = {}
    if not os.getenv("SERPER_API_KEY"):
        off["serper (Google X-Ray for X/LinkedIn/FB/Threads)"] = "set SERPER_API_KEY"
    if not (os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN")):
        off["apify (LinkedIn/Facebook/X/Ads)"] = "set APIFY_TOKEN + APIFY_ACTORS"
    if not os.getenv("HUNTER_API_KEY"):
        off["hunter.io (Email Enrichment)"] = "set HUNTER_API_KEY"
    if not os.getenv("SMTP_EMAIL"):
        off["smtp (Auto Email Dispatch)"] = "set SMTP_EMAIL + SMTP_APP_PASSWORD"
    if not os.getenv("X_BEARER_TOKEN"):
        off["x (Official API)"] = "set X_BEARER_TOKEN"
    return off


def build_sources():
    s = [
        SerperXRay(),
        SocialWebXRay(),
        HackerNews(),
        Reddit(),
        Bluesky(),
        Mastodon(),
        Freelancer(),
        V2EX(),
        TelegramChannels(),
        RSS(),
        Lemmy(),
        Nairaland(),
    ]
    if os.getenv("X_BEARER_TOKEN"):
        s.append(X())
    return s + apify_sources()
