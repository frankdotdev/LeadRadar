"""Global multilingual buyer-intent analyzer, multi-model AI classifier (Gemini + Groq cascade), auto-translator, and deep post-specific outreach writer."""
import re, os, json, asyncio, hashlib
from .net import http
from . import db

# Broad English + Multilingual buyer intent patterns (Americas, Europe, Asia, China, LATAM, Africa)
INTENT = re.compile(
    r"(\[hiring\]|\bhiring\b|\bwe('re| are) hiring\b|\blooking to hire\b|\bwant to hire\b|"
    r"\blooking for (a|an|some|someone|somebody|the best|experienced|reliable|freelance|help|dev|designer|writer|editor|marketer|agency)|"
    r"\b(i|we) need (a|an|some|someone|somebody|help with|to hire|to build|to create|to redesign|to fix)|"
    r"\bneed (a|an) (good |reliable |experienced |fast |skilled |freelance |senior |part-time |contract )?"
    r"(dev|developer|programmer|engineer|coder|designer|copywriter|writer|editor|marketer|specialist|expert|agency|freelancer|consultant|va|assistant|builder|manager|strategist|scraper)|"
    r"\bneed someone (to|who|for)\b|\banyone (know|recommend)\b|\bcan anyone recommend\b|"
    r"\bwho can (build|make|design|develop|write|create|setup|set up|fix|run|manage|edit|help|automate|scrape|integrate|migrate)|"
    r"\bcan someone (build|make|design|write|help|create|fix|setup)|"
    r"\bseeking (a|an|freelance|experienced|senior|contract)\b|"
    r"\bany (devs?|developers?|designers?|writers?|copywriters?|editors?|freelancers?|experts?|agencies|marketers?) (here|available|interested)|"
    r"\brecommendations? for (a|an)\b|\bhelp me (build|make|create|write|launch|fix|setup|scale)|"
    r"\bdm (me )?(your )?(portfolio|rates|samples|work|pricing|quote|cv|resume|links)|"
    r"\b(send|drop|share) (me )?(your )?(portfolio|rates|samples|work|links|pricing)|"
    r"\bbudget (is|of|:|\$|€|£)|\bquote for\b|\bproject (budget|brief)\b|\bpaid (gig|project|task|work|role)\b|"
    # Spanish / Portuguese (LATAM, Spain, Portugal, Brazil)
    r"\b(busco|necesito|contratando|se busca|presupuesto|alguien que pueda|procuro|preciso de|orçamento|vaga freelancer)\b|"
    # French (France, Canada, Europe, Africa)
    r"\b(je cherche|nous cherchons|besoin d'un|besoin de|recherche un|cherche freelance|mission freelance)\b|"
    # German / Dutch / Italian (Europe)
    r"\b(ich suche|wir suchen|brauche einen|gesucht|freelancer gesucht|gezocht|cerco|cercasi)\b|"
    # Chinese / Japanese / Korean / Vietnamese / Indonesian (China & Asia)
    r"(招聘|招募|寻找|外包|兼职|急招|需要一个|开发|求推荐|有偿|预算|接单|"
    r"募集|探しています|外注|業務委託|"
    r"구인|외주|찾습니다|"
    r"\btuyển\b|\bcần tìm\b|\bcần thuê\b|\bbutuh\b|\bdicari\b|\bwho sabi\b))",
    re.I,
)

# Reject self-promotion by freelancers looking for work
NOISE = re.compile(
    r"(\[for hire\]|\bfor hire\b|\bavailable for (work|hire|projects|freelance)\b|\bopen to work\b|"
    r"\bi am a (freelance|freelancer|developer|designer|copywriter|writer|editor|marketer|virtual assistant)|"
    r"\bi'?m a (freelance|freelancer|developer|designer|copywriter|writer|editor|marketer|virtual assistant)|"
    r"\bdm me for (your|any|web|design|coding|copywriting)|"
    r"\bmy portfolio\b|\blooking for (work|a job|clients|projects|gigs|opportunities)\b|"
    r"\bhire me\b|\bcheck my (designs|portfolio|work)\b|\bwe offer (web|app|design|seo|marketing)|"
    r"\bget a professional website\b|\bi will (build|design|write|create|edit) your\b|"
    r"求职|找工作|个人简历|可接单)",
    re.I,
)

URGENT = re.compile(r"\b(asap|urgent|urgently|this week|immediately|today|right away|deadline|quick turnaround|急|尽快)\b", re.I)
BUDGET = re.compile(r"(\$|£|€|₦|¥|₹|usd|eur|gbp|cad|aud|sgd|rmb|cny|ngn)\s?\d+|\d+\s?(usd|eur|gbp|元|刀|\$|€|£)|\bbudget\b|\bpaid\b|\bpay(ing)?\b|\brate\b|\bhourly\b", re.I)
NON_ASCII = re.compile(r"[^\x00-\x7F]{2,}")

# Tech, creative, marketing & business skill patterns for deep post analysis
SKILL_PATTERNS = [
    ("AI & LLM Engineering", re.compile(r"\b(ai|llm|rag|openai|gpt|claude|gemini|langchain|agent|chatbot|machine learning|automation|n8n|make\.com|zapier)\b", re.I)),
    ("Full-Stack / Web Development", re.compile(r"\b(react|next\.?js|vue|angular|node\.?js|typescript|javascript|python|django|fastapi|flask|laravel|php|ruby|golang|full[- ]?stack|frontend|backend|web app|website|portal|dashboard)\b", re.I)),
    ("Mobile App Development", re.compile(r"\b(ios|android|flutter|react native|swift|kotlin|mobile app)\b", re.I)),
    ("E-Commerce & CMS", re.compile(r"\b(shopify|woocommerce|wordpress|webflow|framer|squarespace|magento|e-?commerce|online store|stripe|payment)\b", re.I)),
    ("Data Scraping & APIs", re.compile(r"\b(scrap(er|ing)|crawler|playwright|selenium|puppeteer|apify|api integration|webhook|etl|data pipeline|bot|telegram bot|discord bot)\b", re.I)),
    ("UI/UX & Brand Design", re.compile(r"\b(ui/?ux|figma|web design|app design|redesign|wireframe|prototype|brand identity|logo|pitch deck|graphic design)\b", re.I)),
    ("Copywriting & Content", re.compile(r"\b(copywrit(er|ing)|content writ(er|ing)|blog|newsletter|email sequence|sales page|landing page copy|ghostwrit(er|ing)|scriptwrit(er|ing)|technical writ(er|ing)|seo content)\b", re.I)),
    ("Paid Ads & Growth Marketing", re.compile(r"\b(google ads|ppc|meta ads|facebook ads|tiktok ads|media buyer|paid social|roas|seo|lead gen(eration)?|funnel|cro|marketing)\b", re.I)),
    ("Video Editing & Motion", re.compile(r"\b(video edit(or|ing)|premiere|after effects|capcut|davinci|reels|shorts|tiktok video|ugc|motion graphics|youtube editor)\b", re.I)),
    ("Virtual Assistant & Ops", re.compile(r"\b(virtual assistant|executive assistant|customer support|data entry|crm|notion|airtable|bookkeeping|operations|project manager)\b", re.I)),
]

SEM = asyncio.Semaphore(int(os.getenv("LLM_CONCURRENCY", 4)))


def fingerprint(text: str) -> str:
    return hashlib.md5(re.sub(r"\W+", "", (text or "").lower())[:140].encode()).hexdigest()


def prefilter(text: str, kws: list[str], negs: list[str], need_intent: bool = True) -> bool:
    if not text or len(text.strip()) < 18:
        return False
    t = text.lower()
    if NOISE.search(text):
        return False
    if any(n.lower() in t for n in negs if n):
        return False
    has_intent = bool(INTENT.search(text))
    has_kw = any(k.lower() in t for k in kws if k)
    has_skill = any(pat.search(text) for _, pat in SKILL_PATTERNS)
    has_foreign = bool(NON_ASCII.search(text))

    if need_intent:
        return has_intent and (has_kw or has_skill or bool(BUDGET.search(text)) or has_foreign)
    return has_kw or has_skill or has_intent or (has_foreign and len(text) > 40)


async def translate_free(text: str) -> tuple[str, str]:
    """Translate non-English text into English using Google's free endpoint."""
    if not text or not NON_ASCII.search(text):
        return "en", ""
    try:
        r = await http.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text[:1500]},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            detected_lang = (data[2] if len(data) > 2 else "en") or "en"
            if detected_lang.lower().startswith("en"):
                return "en", ""
            translated = "".join(seg[0] for seg in (data[0] or []) if seg and seg[0]).strip()
            if translated and translated.lower() != text[:1500].strip().lower():
                return detected_lang, translated
    except Exception:
        pass
    return "en", ""


def _signature() -> tuple[str, str, str, str]:
    name = db.get("sender_name") or os.getenv("SENDER_NAME", "Frank Oge")
    portfolio = db.get("sender_portfolio") or os.getenv("SENDER_PORTFOLIO", "https://frankoge.com")
    company = db.get("sender_company") or os.getenv("SENDER_COMPANY", "Hackverse Technologies")
    company_url = db.get("sender_company_url") or os.getenv("SENDER_COMPANY_URL", "https://hackversetechnologies.vercel.app")
    return name, portfolio, company, company_url


def analyze_post_details(text: str, kws: list[str]) -> dict:
    """Deeply inspect the post text to extract exact topic, deliverables, skills/tech stack, and budget."""
    clean_lines = [
        re.sub(r"^\[?(hiring|job|for hire|wanted|urgent|need)\]?[\s:\-—]*", "", ln.strip(), flags=re.I)
        for ln in (text or "").splitlines()
        if ln.strip() and not ln.strip().startswith("http")
    ]
    headline = clean_lines[0][:95] if clean_lines else "your post"
    # Clean trailing punctuation
    headline = headline.rstrip(".:,-— ")

    # Extract specific technologies/skills mentioned in the post
    found_tech = []
    detected_category = ""
    for cat_name, pat in SKILL_PATTERNS:
        matches = pat.findall(text or "")
        if matches:
            if not detected_category:
                detected_category = cat_name
            for m in matches:
                term = m[0] if isinstance(m, tuple) else m
                term_clean = term.strip()
                if term_clean and term_clean.lower() not in [x.lower() for x in found_tech]:
                    found_tech.append(term_clean)

    # Also check user's custom keywords
    t_low = (text or "").lower()
    for k in kws or []:
        if k and k.lower() in t_low and k.lower() not in [x.lower() for x in found_tech]:
            found_tech.append(k)
            if not detected_category:
                detected_category = k.title()

    # Extract a key requirement sentence from body
    detail_sentence = ""
    if len(clean_lines) > 1:
        for ln in clean_lines[1:5]:
            if 25 < len(ln) < 220 and not ln.lower().startswith("budget"):
                detail_sentence = ln.strip()
                break

    budget_match = BUDGET.search(text or "")
    budget_str = budget_match.group(0) if budget_match else ""

    service_label = detected_category or (found_tech[0].title() if found_tech else headline[:38])
    return {
        "headline": headline,
        "service": service_label[:42],
        "tech_list": found_tech[:5],
        "detail_sentence": detail_sentence,
        "budget": budget_str,
    }


def build_specific_draft(post_text: str, author: str, kws: list[str]) -> tuple[str, str, str]:
    """Build a post-specific outreach writeup that directly addresses the poster's exact request & stack."""
    info = analyze_post_details(post_text, kws)
    name, portfolio, company, company_url = _signature()

    clean_au = (author or "").lstrip("@").removeprefix("u/").strip()
    greeting = f"Hi {clean_au}," if clean_au and clean_au.lower() not in ("unknown", "anonymous", "") and not clean_au.isdigit() else "Hi there,"

    headline = info["headline"]
    techs = info["tech_list"]
    tech_str = ", ".join(techs[:4])

    subject = f"Re: {headline}"[:78]

    if techs:
        opening = f'I saw your post looking for help with "{headline}" (specifically around {tech_str}).'
        solution = (
            f"I have hands-on experience delivering production {tech_str} projects and can step in immediately to handle the architecture, implementation, and delivery."
        )
    else:
        opening = f'I just read your request regarding "{headline}".'
        solution = (
            f"I have delivered similar projects end-to-end and can jump in right away with a clear execution plan and fast turnaround."
        )

    if info["detail_sentence"]:
        context_line = f'Regarding your requirement ("{info["detail_sentence"][:110]}"), I can share relevant examples of how I have solved this.'
    else:
        context_line = "I would be glad to walk you through similar work I have shipped and outline a quick plan for your timeline."

    comp_part = f" — {company} ({company_url})" if company else ""
    body = (
        f"{greeting}\n\n"
        f"{opening}\n\n"
        f"{solution} {context_line}\n\n"
        f"You can review my recent work and portfolio at {portfolio}. What is the best way to share a quick breakdown for this?\n\n"
        f"Best,\n"
        f"{name} ({portfolio}){comp_part}"
    )
    return info["service"], subject, body


def heuristic(text: str, kws: list[str], author: str = "") -> dict:
    t = (text or "").lower()
    matched = [k for k in kws if k.lower() in t]
    info = analyze_post_details(text, kws)
    s = 45
    if INTENT.search(text):
        s += 15
    if URGENT.search(text):
        s += 12
    if BUDGET.search(text):
        s += 15
    s += min(15, 5 * (len(matched) + len(info["tech_list"])))
    if len(text) > 120:
        s += 5
    service, subj, draft = build_specific_draft(text, author, kws)
    reason_parts = [f"Request for {info['headline'][:55]}"]
    if info["tech_list"]:
        reason_parts.append(f"Skills: {', '.join(info['tech_list'][:3])}")
    return {
        "score": min(s, 95),
        "service": service,
        "reason": " · ".join(reason_parts)[:200],
        "lang": "en",
        "translated_text": "",
        "draft_subject": subj,
        "draft": draft,
    }


async def _call_gemini(prompt: str, json_mode: bool = False) -> str | None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    models = [os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(), "gemini-2.0-flash"]
    gen_cfg = {"temperature": 0.2 if json_mode else 0.35}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    for model in dict.fromkeys(models):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            r = await http.post(url, params={"key": key}, json=body, timeout=22)
            if r.status_code == 200:
                cands = r.json().get("candidates") or []
                if cands:
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    if parts and parts[0].get("text"):
                        return parts[0]["text"]
        except Exception:
            continue
    return None


async def _call_groq(prompt: str, json_mode: bool = False) -> str | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    # Cascade across multiple Groq models so if one hits rate-limit (429), the next model bucket answers immediately
    primary = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    models = list(dict.fromkeys([primary, "llama-3.1-8b-instant", "gemma2-9b-it"]))

    for model in models:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2 if json_mode else 0.3,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for attempt in range(2):
            try:
                r = await http.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                    timeout=20,
                )
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
                if r.status_code == 429 and attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                break
            except Exception:
                break
    return None


async def llm(prompt: str, json_mode: bool = False) -> str | None:
    """Call Groq or Gemini with multi-model fallback and concurrency control."""
    async with SEM:
        if os.getenv("GROQ_API_KEY", "").strip():
            out = await _call_groq(prompt, json_mode)
            if out:
                return out
        if os.getenv("GEMINI_API_KEY", "").strip():
            out = await _call_gemini(prompt, json_mode)
            if out:
                return out
        return None


def active_llm_provider() -> str:
    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip())
    has_groq = bool(os.getenv("GROQ_API_KEY", "").strip())
    if has_gemini and has_groq:
        return "Groq + Gemini"
    if has_groq:
        return "Groq AI"
    if has_gemini:
        return "Gemini AI"
    return ""


async def classify(text: str, kws: list[str], author: str = "") -> dict:
    """Classify buyer authenticity, translate if non-English, and craft a post-specific outreach writeup."""
    # First translate if non-ASCII foreign script is present
    detected_lang, pre_translated = await translate_free(text)
    analysis_text = pre_translated or text
    base = heuristic(analysis_text, kws, author)
    if pre_translated:
        base["lang"] = detected_lang
        base["translated_text"] = pre_translated

    services = db.get("my_services") or os.getenv("MY_SERVICES", "software development, AI automation, design, copywriting, digital marketing")
    pitch = db.get("my_pitch") or os.getenv("MY_PITCH", "")
    name, portfolio, company, company_url = _signature()

    prompt = (
        f"You are an elite global deal finder and outreach strategist.\n"
        f"Services/Roles I offer: {services}\n"
        f"My background: {pitch}\n"
        f"My signature: {name} ({portfolio}) at {company} ({company_url})\n"
        f"Poster username: {author or 'there'}\n\n"
        f"Read the post below carefully:\n"
        f"1. Is this a REAL BUYER, CLIENT, FOUNDER, or HIRING post looking for someone to build, write, design, market, or work on a project/role? "
        f"(Score 0 if it is a freelancer advertising themselves / '[For Hire]' / spam).\n"
        f"2. Identify the exact service/role they are asking for in 2-5 words ('service', e.g., 'Enterprise RAG AI Engineer', 'Shopify Store Redesign', 'SaaS Copywriter'). NEVER say 'Project Request'.\n"
        f"3. If the post is not in English, set 'lang' to its ISO code (e.g. 'zh', 'es', 'fr', 'de', 'vi', 'pt') and provide a full English translation in 'translated_text'.\n"
        f"4. Write a highly specific, natural outreach message ('draft', 65-105 words, no emojis, no hashtags) that:\n"
        f"   - Explicitly references the EXACT thing they asked for in their post (their project topic, tech stack, deliverables, or pain point).\n"
        f"   - Explains concretely how I can deliver or solve that exact requirement.\n"
        f"   - Includes my portfolio link ({portfolio}) and ends with a direct, low-friction question.\n"
        f"   - Ends with:\nBest,\n{name} ({portfolio}) — {company} ({company_url})\n\n"
        f'Reply in valid JSON only:\n'
        f'{{"score": 0-100, "service": "exact 2-5 word role/topic", "reason": "1 sentence on what they need and why it fits", '
        f'"lang": "{detected_lang}", "translated_text": "", "draft_subject": "Re: specific topic", "draft": "..."}}\n\n'
        f"POST:\n{(text or '')[:1800]}"
    )

    out = await llm(prompt, json_mode=True)
    if out:
        try:
            v = json.loads(out)
            score = int(v.get("score", 0))
            service = str(v.get("service", "") or base["service"]).strip()[:48]
            if service.lower() in ("project request", "general", "unknown", ""):
                service = base["service"]
            reason = str(v.get("reason", "") or base["reason"]).strip()[:220]
            lang = str(v.get("lang", detected_lang) or detected_lang).lower()[:8]
            translated = str(v.get("translated_text", "") or pre_translated).strip()[:2000]
            draft_subj = str(v.get("draft_subject", "") or base["draft_subject"]).strip()[:120]
            draft_body = str(v.get("draft", "") or "").strip()[:2000]
            if not draft_body or "regarding Project Request" in draft_body:
                draft_body = base["draft"]
            return {
                "score": score,
                "service": service,
                "reason": reason,
                "lang": lang,
                "translated_text": translated if lang != "en" else "",
                "draft_subject": draft_subj,
                "draft": draft_body,
            }
        except Exception:
            pass

    return base


async def draft_reply(lead: dict) -> dict:
    """Generate or regenerate a deeply specific outreach writeup for a lead."""
    services = db.get("my_services") or os.getenv("MY_SERVICES", "software development")
    pitch = db.get("my_pitch") or os.getenv("MY_PITCH", "")
    name, portfolio, company, company_url = _signature()
    kws = db.get("keywords") or []

    post_content = lead.get("translated_text") or lead.get("text") or ""

    prompt = (
        f"Write a highly specific, human, non-spammy outreach message (65-105 words, no emojis, no hashtags) replying to this post.\n"
        f"CRITICAL RULE: You MUST mention the exact project, role, technology, or problem described in their post (never write generic placeholders like 'Project Request').\n"
        f"Explain one concrete way I can execute what they need, share my portfolio ({portfolio}), and end with a short question.\n"
        f"Sign off with:\nBest,\n{name} ({portfolio}) — {company} ({company_url})\n\n"
        f"My services: {services}\n"
        f"About me: {pitch}\n"
        f"Poster username: {lead.get('author') or 'there'}\n\n"
        f'Reply JSON only: {{"subject": "Re: specific project/role", "draft": "full message text"}}\n\n'
        f"POST:\n{post_content[:1600]}"
    )

    out = await llm(prompt, json_mode=True)
    if out:
        try:
            v = json.loads(out)
            subj = str(v.get("subject") or "").strip()
            body = str(v.get("draft") or "").strip()
            if body and "regarding Project Request" not in body:
                return {"subject": subj or f"Re: {lead.get('service') or 'your post'}", "draft": body}
        except Exception:
            pass

    _, subj, body = build_specific_draft(post_content, lead.get("author", ""), kws)
    return {"subject": subj, "draft": body}
