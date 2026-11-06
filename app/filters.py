import re, os, json, asyncio, hashlib
from .net import http

INTENT = re.compile(
    r"\b(looking for (a|an|some|someone|somebody)|i need (a|an|some|someone|somebody)|we need (a|an|someone)|need (a|an) (good |reliable |experienced )?(dev|developer|designer|freelancer|programmer|engineer)|"
    r"need someone (to|who)|anyone (know|recommend)|can anyone recommend|who can (build|make|design|develop)|can someone (build|make|design)|"
    r"hiring (a|an)|want to hire|seeking (a|an)|any (devs?|developers?|designers?|freelancers?) (here|available)|"
    r"recommendations? for (a|an) (dev|developer|designer|agency|freelancer)|help me (build|make|create))\b", re.I)
NOISE = re.compile(r"\b(for hire|available for (work|hire)|open to work|i am a (freelance|developer|designer)|i'?m a (freelance|developer|designer)|"
                   r"dm me for|my portfolio|we are hiring full[- ]time|\[for hire\]|looking for (work|a job|clients|projects)|check out my|available for (projects|roles|hire)|hire me|check my designs|your no\\.?1|we offer|get a professional)\b", re.I)
URGENT = re.compile(r"\b(asap|urgent|urgently|this week|immediately|today|right away|deadline)\b", re.I)
BUDGET = re.compile(r"(\$|£|€|₦|usd|ngn)\s?\d+|\bbudget\b|\bpaid\b|\bpay(ing)?\b", re.I)
SEM = asyncio.Semaphore(int(os.getenv("LLM_CONCURRENCY", 6)))

def fingerprint(text: str) -> str:
    return hashlib.md5(re.sub(r"\W+", "", text.lower())[:140].encode()).hexdigest()

def prefilter(text: str, kws, negs, need_intent=True) -> bool:
    t = text.lower()
    if need_intent and not INTENT.search(text): return False
    if NOISE.search(text) or any(n.lower() in t for n in negs): return False
    return any(k.lower() in t for k in kws)

def heuristic(text, kws):
    s = 40 + (15 if URGENT.search(text) else 0) + (15 if BUDGET.search(text) else 0)
    s += min(20, 5 * sum(k.lower() in text.lower() for k in kws)) + (5 if len(text) > 120 else 0)
    return {"score": min(s, 95), "service": "", "reason": "intent + keyword match (heuristic)"}

async def llm(prompt, json_mode=False):
    key = os.getenv("GROQ_API_KEY")
    if not key: return None
    body = {"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "messages": [{"role": "user", "content": prompt}], "temperature": 0.2 if not json_mode else 0}
    if json_mode: body["response_format"] = {"type": "json_object"}
    async with SEM:
        try:
            r = await http.post("https://api.groq.com/openai/v1/chat/completions",
                                headers={"Authorization": f"Bearer {key}"}, json=body, timeout=20)
            return r.json()["choices"][0]["message"]["content"]
        except Exception:
            return None

async def classify(text, kws):
    base = heuristic(text, kws)
    out = await llm(f"I offer: {os.getenv('MY_SERVICES','software development')}.\n"
        "Is this post a real BUYER wanting to hire/pay someone for work I could do (not a job seeker, not an ad, not a full-time job)? "
        'Reply JSON only: {"score":0-100,"service":"2-4 words","reason":"one short sentence"}\n\nPOST:\n' + text[:1500], True)
    try:
        v = json.loads(out)
        return {"score": int(v.get("score", 0)), "service": str(v.get("service", ""))[:40], "reason": str(v.get("reason", ""))[:200]}
    except Exception:
        return base

async def draft_reply(lead):
    pitch = os.getenv("MY_PITCH", "I run Hackverse Software Solutions and build web, mobile and AI products.")
    out = await llm(f"Write a short, friendly, non-spammy reply (max 70 words, no emojis, no hashtags) to this post. "
        f"Be specific to what they need, mention one concrete way I can help, end with a low-pressure question. About me: {pitch}\n\nPOST:\n{lead['text'][:1200]}")
    if out: return out.strip()
    return (f"Hi{' ' + lead['author'] if lead.get('author') else ''}, saw your post. {pitch} "
            f"Happy to share relevant examples and a quick plan for {lead.get('service') or 'what you need'}. Want me to send a few?")
