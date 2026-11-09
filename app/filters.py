"""Multilingual buyer-intent prefilter, Gemini + Groq AI classifier, auto-translator, and tailored pitch writer."""
import re, os, json, asyncio, hashlib
from .net import http
from . import db

# Broad English + Multilingual buyer intent patterns
INTENT = re.compile(
    r"(\[hiring\]|\bhiring\b|\bwe('re| are) hiring\b|\blooking to hire\b|\bwant to hire\b|"
    r"\blooking for (a|an|some|someone|somebody|the best|experienced|reliable|freelance)|"
    r"\b(i|we) need (a|an|some|someone|somebody|help with)|"
    r"\bneed (a|an) (good |reliable |experienced |fast |skilled |freelance )?"
    r"(dev|developer|programmer|engineer|designer|copywriter|writer|editor|marketer|specialist|expert|agency|freelancer|consultant|va|assistant|builder|manager)|"
    r"\bneed someone (to|who|for)\b|\banyone (know|recommend)\b|\bcan anyone recommend\b|"
    r"\bwho can (build|make|design|develop|write|create|setup|set up|fix|run|manage|edit|help|automate|scrape)|"
    r"\bcan someone (build|make|design|write|help|create|fix|setup)|"
    r"\bseeking (a|an|freelance|experienced)\b|\bany (devs?|developers?|designers?|writers?|copywriters?|editors?|freelancers?|experts?) (here|available)|"
    r"\brecommendations? for (a|an)\b|\bhelp me (build|make|create|write|launch|fix|setup)|"
    r"\bdm (me )?(your )?(portfolio|rates|samples|work|pricing|quote)|"
    r"\b(send|drop) (me )?(your )?(portfolio|rates|samples|work)|"
    r"\bbudget (is|of|:|\$)|"
    # Multilingual intent: Spanish, French, German, Portuguese, Vietnamese, Italian, Dutch, Indonesian, Pidgin
    r"\b(busco|necesito|contratando|presupuesto|alguien que pueda|"
    r"je cherche|nous cherchons|besoin d'un|besoin de|recherche un|"
    r"ich suche|wir suchen|brauche einen|"
    r"procuro|preciso de|contratando|orçamento|"
    r"tuyển|cần tìm|cần thuê|"
    r"cerco|cercasi|gezocht|butuh|dicari|who sabi)\b)",
    re.I,
)

# Reject self-promotion by freelancers looking for work
NOISE = re.compile(
    r"(\[for hire\]|\bfor hire\b|\bavailable for (work|hire|projects|freelance)\b|\bopen to work\b|"
    r"\bi am a (freelance|freelancer|developer|designer|copywriter|writer|editor|marketer|virtual assistant)|"
    r"\bi'?m a (freelance|freelancer|developer|designer|copywriter|writer|editor|marketer|virtual assistant)|"
    r"\bdm me for (your|any|web|design|coding|copywriting)|"
    r"\bmy portfolio\b|\blooking for (work|a job|clients|projects|gigs)\b|"
    r"\bhire me\b|\bcheck my (designs|portfolio|work)\b|\bwe offer (web|app|design|seo|marketing)|"
    r"\bget a professional website\b|\bi will (build|design|write|create|edit) your\b)",
    re.I,
)

URGENT = re.compile(r"\b(asap|urgent|urgently|this week|immediately|today|right away|deadline|quick turnaround)\b", re.I)
BUDGET = re.compile(r"(\$|£|€|₦|usd|eur|gbp|cad|aud|ngn)\s?\d+|\d+\s?(usd|eur|gbp|\$)|\bbudget\b|\bpaid\b|\bpay(ing)?\b|\brate\b", re.I)
NON_ASCII = re.compile(r"[^\x00-\x7F]{3,}")

SEM = asyncio.Semaphore(int(os.getenv("LLM_CONCURRENCY", 6)))


def fingerprint(text: str) -> str:
    return hashlib.md5(re.sub(r"\W+", "", (text or "").lower())[:140].encode()).hexdigest()


def prefilter(text: str, kws: list[str], negs: list[str], need_intent: bool = True) -> bool:
    if not text or len(text.strip()) < 20:
        return False
    t = text.lower()
    if NOISE.search(text):
        return False
    if any(n.lower() in t for n in negs if n):
        return False
    has_intent = bool(INTENT.search(text))
    has_kw = any(k.lower() in t for k in kws if k)
    # Also allow posts from non-English scripts that have buyer intent or match keywords
    if need_intent:
        return has_intent and (has_kw or bool(BUDGET.search(text)))
    return has_kw or has_intent


async def translate_free(text: str) -> tuple[str, str]:
    """Lightweight fallback translator using Google's public endpoint when no LLM is configured."""
    if not text or not NON_ASCII.search(text):
        return "en", ""
    try:
        r = await http.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text[:1200]},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            detected_lang = (data[2] if len(data) > 2 else "en") or "en"
            if detected_lang.lower().startswith("en"):
                return "en", ""
            translated = "".join(seg[0] for seg in (data[0] or []) if seg and seg[0]).strip()
            if translated and translated.lower() != text[:1200].strip().lower():
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


def heuristic_draft(post_text: str, author: str, service: str, kws: list[str]) -> tuple[str, str]:
    """Generate a clean, personalized fallback outreach message and subject without an LLM."""
    name, portfolio, company, company_url = _signature()
    pitch = db.get("my_pitch") or os.getenv(
        "MY_PITCH",
        f"I build reliable web, mobile, AI, and digital solutions at {company}."
    )
    clean_au = (author or "").lstrip("@").removeprefix("u/").strip()
    greeting = f"Hi {clean_au}," if clean_au and clean_au.lower() not in ("unknown", "anonymous") else "Hi there,"

    matched_service = service
    if not matched_service:
        t = (post_text or "").lower()
        for k in kws:
            if k.lower() in t:
                matched_service = k
                break
    matched_service = matched_service or "your project"

    first_line = (post_text or "").strip().split("\n")[0][:75].strip()
    subject = f"Re: {matched_service.title()} — {first_line}"[:78]

    comp_part = f" at {company} ({company_url})" if company else ""
    port_part = f" ({portfolio})" if portfolio else ""

    body = (
        f"{greeting}\n\n"
        f"I just saw your post regarding {matched_service}. {pitch}\n\n"
        f"I have handled similar builds and deliverables and can jump on this immediately with a clear plan and timeline. "
        f"You can check out my work here: {portfolio}\n\n"
        f"Would you be open to sharing a few more details so I can send over a tailored breakdown?\n\n"
        f"Best,\n"
        f"{name}{port_part}{comp_part}"
    )
    return subject, body


def heuristic(text: str, kws: list[str], author: str = "") -> dict:
    t = (text or "").lower()
    matched = [k for k in kws if k.lower() in t]
    s = 45
    if INTENT.search(text):
        s += 15
    if URGENT.search(text):
        s += 12
    if BUDGET.search(text):
        s += 15
    s += min(15, 5 * len(matched))
    if len(text) > 120:
        s += 5
    service = matched[0] if matched else "Project Request"
    subj, draft = heuristic_draft(text, author, service, kws)
    return {
        "score": min(s, 95),
        "service": service[:40],
        "reason": "Buyer intent + keyword match (heuristic)",
        "lang": "en",
        "translated_text": "",
        "draft_subject": subj,
        "draft": draft,
    }


async def _call_gemini(prompt: str, json_mode: bool = False) -> str | None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    gen_cfg = {"temperature": 0.15 if json_mode else 0.35}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    try:
        r = await http.post(url, params={"key": key}, json=body, timeout=22)
        if r.status_code != 200:
            return None
        cands = r.json().get("candidates") or []
        if not cands:
            return None
        parts = (cands[0].get("content") or {}).get("parts") or []
        return parts[0].get("text") if parts else None
    except Exception:
        return None


async def _call_groq(prompt: str, json_mode: bool = False) -> str | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    body = {
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.15 if json_mode else 0.3,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = await http.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=20,
        )
        if r.status_code != 200:
            return None
        return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


async def llm(prompt: str, json_mode: bool = False) -> str | None:
    """Call Gemini or Groq (whichever key is configured, with automatic failover)."""
    async with SEM:
        if os.getenv("GEMINI_API_KEY", "").strip():
            out = await _call_gemini(prompt, json_mode)
            if out:
                return out
        if os.getenv("GROQ_API_KEY", "").strip():
            out = await _call_groq(prompt, json_mode)
            if out:
                return out
        return None


def active_llm_provider() -> str:
    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip())
    has_groq = bool(os.getenv("GROQ_API_KEY", "").strip())
    if has_gemini and has_groq:
        return "Gemini + Groq"
    if has_gemini:
        return "Gemini"
    if has_groq:
        return "Groq"
    return ""


async def classify(text: str, kws: list[str], author: str = "") -> dict:
    """Classify buyer authenticity, translate if non-English, and craft an immediate tailored outreach writeup."""
    base = heuristic(text, kws, author)
    services = db.get("my_services") or os.getenv("MY_SERVICES", "software development, design, copywriting, digital marketing")
    pitch = db.get("my_pitch") or os.getenv("MY_PITCH", "")
    name, portfolio, company, company_url = _signature()

    prompt = (
        f"You are an expert buyer-intent intelligence analyst and outreach strategist.\n"
        f"Services/Roles I offer: {services}\n"
        f"Keywords I track: {', '.join(kws[:25])}\n"
        f"My background: {pitch}\n"
        f"My signature details: Name='{name}', Portfolio='{portfolio}', Company='{company}' ({company_url})\n"
        f"Post author: {author or 'unknown'}\n\n"
        f"Analyze the following post (which may be in ANY language across the world):\n"
        f"1. Determine if this is an AUTHENTIC BUYER / CLIENT / HIRING MANAGER looking to pay or hire someone for services matching what I offer or my keywords. "
        f"(Score 0 if it is a freelancer advertising themselves, '[For Hire]', spam, or unrelated).\n"
        f"2. Detect the ISO language code (e.g. 'en', 'es', 'fr', 'de', 'pt', 'vi', 'nl', etc.). If the post is NOT in English, provide a clear, complete English translation in 'translated_text' (otherwise leave 'translated_text' empty string).\n"
        f"3. If score >= 35, write a tailored, human, high-converting outreach message ('draft', 55-95 words, no emojis, no hashtags, no generic AI clichés) directly addressing their exact request/problem, mentioning one concrete way I can solve it, and signed off naturally with:\n"
        f"Best,\n{name} ({portfolio}) — {company}\n"
        f"Also provide a concise email subject line ('draft_subject').\n\n"
        f'Reply strictly in JSON:\n'
        f'{{"score": 0-100, "service": "2-4 words", "reason": "one short sentence in English", '
        f'"lang": "en", "translated_text": "", "draft_subject": "...", "draft": "..."}}\n\n'
        f"POST:\n{(text or '')[:1800]}"
    )

    out = await llm(prompt, json_mode=True)
    if out:
        try:
            v = json.loads(out)
            score = int(v.get("score", 0))
            service = str(v.get("service", "") or base["service"])[:45]
            reason = str(v.get("reason", "") or base["reason"])[:220]
            lang = str(v.get("lang", "en") or "en").lower()[:8]
            translated = str(v.get("translated_text", "") or "").strip()[:2000]
            draft_subj = str(v.get("draft_subject", "") or base["draft_subject"]).strip()[:120]
            draft_body = str(v.get("draft", "") or base["draft"]).strip()[:2000]
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

    # If no LLM or JSON parse failed, still run free auto-translation if foreign script is present
    lang, translated = await translate_free(text)
    if translated:
        base["lang"] = lang
        base["translated_text"] = translated
        # Re-run keyword/intent score boost on the English translation
        if INTENT.search(translated) or any(k.lower() in translated.lower() for k in kws):
            base["score"] = max(base["score"], 68)
    return base


async def draft_reply(lead: dict) -> dict:
    """Generate or regenerate a tailored outreach writeup for a specific lead."""
    services = db.get("my_services") or os.getenv("MY_SERVICES", "software development")
    pitch = db.get("my_pitch") or os.getenv("MY_PITCH", "")
    name, portfolio, company, company_url = _signature()
    kws = db.get("keywords") or []

    post_content = lead.get("translated_text") or lead.get("text") or ""
    orig_lang = lead.get("lang") or "en"

    prompt = (
        f"Write a short, friendly, non-spammy outreach message (60-95 words, no emojis, no hashtags) replying to this buyer post.\n"
        f"Be specific to their exact request, mention one concrete way I can deliver it, and end with a low-pressure question.\n"
        f"Sign off at the end with:\nBest,\n{name} ({portfolio}) — {company} ({company_url})\n\n"
        f"My services: {services}\n"
        f"About me: {pitch}\n"
        f"Post author: {lead.get('author') or 'there'}\n"
        f"Post language: {orig_lang}\n\n"
        f'Reply JSON only: {{"subject": "short email subject", "draft": "full message text"}}\n\n'
        f"POST:\n{post_content[:1500]}"
    )

    out = await llm(prompt, json_mode=True)
    if out:
        try:
            v = json.loads(out)
            subj = str(v.get("subject") or "").strip()
            body = str(v.get("draft") or "").strip()
            if body:
                return {"subject": subj or f"Re: {lead.get('service') or 'your post'}", "draft": body}
        except Exception:
            pass

    subj, body = heuristic_draft(post_content, lead.get("author", ""), lead.get("service", ""), kws)
    return {"subject": subj, "draft": body}
