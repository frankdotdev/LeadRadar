# LeadRadar

[![GitHub Repository](https://img.shields.io/badge/GitHub-frankdotdev%2FLeadRadar-black?logo=github)](https://github.com/frankdotdev/LeadRadar)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-black.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-black.svg)](https://fastapi.tiangolo.com)
[![SQLite WAL](https://img.shields.io/badge/SQLite-WAL%20Mode-black.svg)](https://www.sqlite.org)

An open-source, autonomous **buyer-intent discovery, contact enrichment, and instant outreach engine** for freelancers, software engineers, copywriters, media buyers, designers, agencies, and consultants.

**LeadRadar** continuously listens across social networks, forums, job boards, and Google X-Ray search for real people asking to hire or pay for services—in **any language around the world**. The moment a post is discovered, LeadRadar qualifies its authenticity, translates non-English posts into English, extracts every available contact detail (`email`, `phone/WhatsApp`, `@handle`, direct DM link, or domain email via Hunter.io), prepares a **tailored outreach writeup** signed with your name and portfolio, and either **automatically dispatches an email** (when an email address is found) or holds the tailored message ready on your dashboard for a **single-click Copy & DM**.

---

## Table of Contents

- [Why LeadRadar?](#why-leadradar)
- [How It Works (Architecture)](#how-it-works-architecture)
- [Key Features](#key-features)
- [Universal Role & Service Adaptability](#universal-role--service-adaptability)
- [Directory Layout](#directory-layout)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [Local Setup (Linux / macOS / Windows)](#local-setup)
  - [Docker & Production Deployment](#docker--production-deployment)
- [Environment Configuration Guide](#environment-configuration-guide)
- [How to Obtain Free API Keys & Credentials](#how-to-obtain-free-api-keys--credentials)
- [Safety, Deduplication & Outreach Rules](#safety-deduplication--outreach-rules)
- [Adding Custom Ingestion Sources](#adding-custom-ingestion-sources)
- [Contributing](#contributing)
- [Author & Credits](#author--credits)
- [License & Disclaimer](#license--disclaimer)

---

## Why LeadRadar?

Manually refreshing job boards, X searches, subreddits, and forums wastes hours every day, and most high-intent buyer posts receive dozens of replies within an hour.

**LeadRadar** automates the entire top-of-funnel workflow:

1. **Global, Multi-Language Buyer Intent Discovery:** Captures real-time buyer signals across 7+ zero-key sources out of the box (Reddit, Hacker News, Bluesky, Mastodon, Freelancer.com, Lemmy, Nairaland) plus Google X-Ray via **Serper.dev** (covering X/Twitter, LinkedIn Posts, Facebook, Threads, Notion briefs, and Google Forms) and **Apify** actors.
2. **Works for Any Service or Role:** Not limited to software development. Switch between one-click presets (*Software & AI Dev*, *Copywriting & Content*, *Google & Meta Ads*, *UI/UX & Design*, *Video Editing & UGC*, *Virtual Assistant*) or type any custom service on the dashboard, and LeadRadar dynamically reconfigures its search queries and AI prompts.
3. **Automatic Translation (Any Language -> English):** Buyer requests posted in Spanish, French, German, Vietnamese, Portuguese, Dutch, Italian, or any other language are automatically detected and translated into English so you never miss international opportunities.
4. **Immediate Tailored Writeup on Every Lead:** Every qualified post immediately gets a custom, human outreach writeup tailored to that exact request and signed by you (e.g., `Frank Oge (https://frankoge.com) — Hackverse Technologies`, configurable via `.env` or the dashboard).
5. **Auto-Email When Found, One-Click Copy & DM When Not:**
   - **Email Present:** Automatically sends the tailored pitch via SMTP (or lets you launch your default mail app via `mailto:` with `To`, `Subject`, and `Body` pre-filled).
   - **No Email Present (X, Facebook, Reddit, Telegram, LinkedIn):** Extracts the poster's `@username`, phone/WhatsApp number, and direct profile URL so you can click **Copy & Open DM**, paste the tailored message into their DM, and hit send in seconds.

---

## How It Works (Architecture)

```
 ┌───────────────────────────────── Concurrent Ingestion Loops ─────────────────────────────────┐
 │ Free (On by default): Reddit · Hacker News · Bluesky · Mastodon · Freelancer · Lemmy · NL   │
 │ Optional Free-Tier:   Serper.dev (X / LinkedIn / FB / Notion X-Ray) · Apify · Telegram · RSS │
 └──────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                ▼
 ┌──────────────────────────────────── Fast Prefilter & Dedupe ─────────────────────────────────┐
 │ 1. Drop stale posts (> MAX_AGE_HOURS) & already-seen UIDs (batched SQLite lookup)            │
 │ 2. Multilingual regex buyer-intent check + self-promotion ("[For Hire]") & negative rejection│
 │ 3. Cross-platform MD5 text fingerprint deduplication                                         │
 └──────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                ▼
 ┌─────────────────────── AI Qualification, Translation & Contact Enrichment ───────────────────┐
 │ - Google Gemini (gemini-2.5-flash) OR Groq (llama-3.3-70b) OR Heuristic Engine               │
 │ - Scores buyer authenticity (0-100) + auto-translates foreign posts to English               │
 │ - Extracts direct emails, phone/WhatsApp numbers, @handles, profile DM URLs + Hunter.io      │
 │ - Generates tailored outreach writeup + subject signed with your configured identity         │
 └──────────────────────┬───────────────────────┴───────────────────────┬───────────────────────┘
                        ▼                                               ▼
         ┌─────────────────────────────┐                 ┌─────────────────────────────┐
         │     If Email Discovered     │                 │   If Social / DM Only       │
         │ - Auto-dispatches via SMTP  │                 │ - Writeup + @handle waiting │
         │   (or 1-click mailto: link) │                 │   on Dashboard & Telegram   │
         │ - Deduplicated per address  │                 │ - 1-click "Copy & Open DM"  │
         └─────────────────────────────┘                 └─────────────────────────────┘
```

---

## Key Features

- **Zero-Key Default Sources:** Runs immediately upon install using public endpoints for Reddit (subreddit feeds + global keyword search), Hacker News, Bluesky, Mastodon, Freelancer.com, Lemmy, and Nairaland.
- **Google X-Ray via Serper.dev (`SERPER_API_KEY`):** Uses Serper's 2,500 free searches to X-Ray search `site:x.com`, `site:linkedin.com/posts`, `site:facebook.com`, `site:threads.net`, `site:notion.site`, and `site:docs.google.com/forms` for live hiring and buyer posts.
- **Dual AI Engine (`GEMINI_API_KEY` / `GROQ_API_KEY`):** Supports Google Gemini (`gemini-2.5-flash`) and Groq (`llama-3.3-70b-versatile`) with automatic failover—and falls back gracefully to a built-in heuristic scorer and free translator if no AI key is provided.
- **Contact Extraction & Hunter.io (`HUNTER_API_KEY`):**
  - Parses standard and obfuscated emails (`name [at] domain [dot] com`), international phone numbers, WhatsApp links (`wa.me/...`), Telegram handles (`t.me/...`), and `@usernames`.
  - Resolves direct profile/DM links for Reddit (`u/user`), X (`@handle`), Bluesky, Hacker News, Telegram, and Nairaland.
  - Optionally queries **Hunter.io** when a post links an external company domain to uncover verified decision-maker emails.
- **Editorial Monochrome Dashboard:**
  - Strict black, gray, and paper palette with a persistent **Light / Dark Mode** toggle.
  - Zero external frontend frameworks, zero AI gradients, and zero emoji clutter.
  - Inline **Tailored Outreach Writeup** box on every card with `Copy Writeup`, `Copy & Open DM`, `Send Email`, `Mail App`, and `Edit / AI Rewrite` actions.
  - Filter by status (`New`, `Saved`, `Contacted`, `Won`, `Dismissed`), minimum score, source, contact availability (`Has Email Address`, `Has Handle / Phone / Email`), or live search query.

---

## Universal Role & Service Adaptability

LeadRadar is built to hunt for **any** freelance service, consulting offer, or job role. Click **Role & Settings** in the dashboard header to:

1. **Select a 1-Click Industry Preset:**
   - **Software, Web, Mobile & AI Dev:** Websites, mobile apps, full-stack, React, Python, AI agents, chatbots, SaaS, scraping, automation.
   - **Copywriting & Content Writing:** Landing page copy, email sequences, ghostwriting, blog writing, technical writing, scriptwriting.
   - **Google Ads, Meta Ads & SEO Growth:** PPC, Google Ads, Facebook/TikTok Ads, media buying, ROAS optimization, SEO, funnels.
   - **UI/UX, Brand & Graphic Design:** Figma, product design, web design, brand identity, pitch decks, wireframes.
   - **Video Editing, Motion & UGC:** Short-form editing (Reels, TikTok, Shorts), YouTube editing, After Effects, UGC creator briefs.
   - **Virtual Assistant & Operations:** Executive assistant, customer support, CRM setup, Notion/Airtable/Zapier operations.
2. **Or Enter Any Custom Service:** Type your own service description into **Services / Roles You Offer** and your target terms into **Monitored Buyer Keywords**, then click **Save & Apply** to immediately scan across all sources.

---

## Directory Layout

```
LeadRadar/
├── app/
│   ├── main.py               # FastAPI application, ingestion loop & REST endpoints
│   ├── db.py                 # SQLite WAL database, auto-migrations, settings & role presets
│   ├── sources.py            # Concurrent source connectors (Free sources + Serper X-Ray + Apify)
│   ├── filters.py            # Multilingual intent prefilter, Gemini/Groq classifier & pitch writer
│   ├── enrichment.py         # Email/phone/@handle extractor, Hunter.io client & SMTP mailer
│   ├── notify.py             # Telegram long-polling bot with inline triage buttons
│   └── net.py                # Shared pooled HTTP/1.1 & HTTP/2 async client
├── static/
│   └── index.html            # Zero-dependency monochrome web dashboard (Dark & Light mode)
├── .env.example              # Documented environment configuration template
├── requirements.txt          # Python package dependencies
├── Dockerfile                # Production container definition
├── docker-compose.yml        # Single-command container orchestration
└── LICENSE                   # MIT License
```

---

## Quick Start

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Git

### Local Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/frankdotdev/LeadRadar.git
   cd LeadRadar
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv

   # On Linux / macOS:
   source .venv/bin/activate

   # On Windows:
   .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure your environment:**
   ```bash
   cp .env.example .env
   ```
   Open `.env` in your editor. Every API key is optional—LeadRadar works immediately out of the box using free sources and heuristic scoring, and you can also customize your identity and services directly in the web UI.

5. **Start the server:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
   Open **`http://localhost:8000`** in your browser.

### Docker & Production Deployment

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f
```

---

## Environment Configuration Guide

| Variable | Default | Required? | Description |
| :--- | :--- | :--- | :--- |
| **Sender Identity & Offer** | | | |
| `SENDER_NAME` | `Frank Oge` | No | Your name signed at the bottom of every generated writeup and email. |
| `SENDER_PORTFOLIO` | `https://frankoge.com` | No | Your portfolio or personal website URL included in pitches. |
| `SENDER_COMPANY` | `Hackverse Technologies` | No | Your company or agency name. |
| `SENDER_COMPANY_URL` | `https://hackversetechnologies.vercel.app` | No | Your company or agency URL. |
| `MY_SERVICES` | *Web, mobile, AI, copy, ads...* | No | Services or roles you offer (also editable in Dashboard Settings). |
| `MY_PITCH` | *Custom value proposition* | No | Short summary of your track record used to tailor outreach writeups. |
| **AI Classifier & Translator** | | | |
| `GEMINI_API_KEY` | `""` | Recommended | Google Gemini API key for semantic scoring, translation, and writeups. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | No | Gemini model name. |
| `GROQ_API_KEY` | `""` | Optional | Groq Cloud API key (`llama-3.3-70b-versatile`). Works standalone or as failover. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | No | Groq model name. |
| **Extended Discovery** | | | |
| `SERPER_API_KEY` | `""` | Recommended | Serper.dev key for Google X-Ray searches across X, LinkedIn, Facebook & Notion. |
| `SERPER_INTERVAL` | `600` | No | Seconds between Serper X-Ray runs (default: 10 minutes). |
| `APIFY_TOKEN` | `""` | Optional | Apify API token for LinkedIn, Facebook, or X scraper actors. |
| `APIFY_ACTORS` | `[...]` | Optional | JSON list of Apify actors and input templates. |
| **Enrichment & Auto-Email** | | | |
| `HUNTER_API_KEY` | `""` | Optional | Hunter.io key to find verified emails on external company domains. |
| `SMTP_EMAIL` | `""` | For Auto-Email | Sending Gmail / Google Workspace / custom SMTP email address. |
| `SMTP_APP_PASSWORD` | `""` | For Auto-Email | 16-character Google App Password or SMTP password. |
| `SMTP_HOST` | `smtp.gmail.com` | No | SMTP server hostname. |
| `SMTP_PORT` | `465` | No | SMTP SSL port (`465` for SSL, `587` for STARTTLS). |
| `AUTO_SEND_EMAIL` | `true` | No | Automatically email leads when a direct email address is discovered. |
| `AUTO_EMAIL_MIN_SCORE` | `65` | No | Minimum lead score required before auto-sending an email. |
| `DRY_RUN` | `false` | No | When `true`, simulates email sending without dispatching over SMTP. |
| **Telegram Alerts** | | | |
| `TELEGRAM_BOT_TOKEN` | `""` | Optional | Bot token from `@BotFather`. Send `/start` to your bot to link automatically. |
| `ALERT_SCORE` | `70` | No | Minimum lead score to trigger a real-time Telegram notification. |

---

## How to Obtain Free API Keys & Credentials

All external integrations are **100% optional and modular**. You can add any of the following free-tier keys at your own pace:

### 1. Google Gemini API Key (`GEMINI_API_KEY`) — Free Tier
*Powers multilingual translation, authentic buyer scoring, and tailored outreach writeups.*
1. Visit [Google AI Studio](https://aistudio.google.com/) and sign in.
2. Click **Get API key** -> **Create API key**.
3. Paste into `.env`:
   ```env
   GEMINI_API_KEY=AIzaSy...
   ```

### 2. Groq Cloud API Key (`GROQ_API_KEY`) — Free Tier
*Ultra-fast Llama 3.3 70B inference (can be used instead of or alongside Gemini).*
1. Visit [console.groq.com](https://console.groq.com/) and create a free account.
2. Open **API Keys** -> **Create API Key** and paste into `.env`:
   ```env
   GROQ_API_KEY=gsk_...
   ```

### 3. Serper.dev API Key (`SERPER_API_KEY`) — 2,500 Free Searches
*Powers Google X-Ray discovery across X/Twitter, LinkedIn Posts, Facebook, Threads, Notion briefs, and Google Forms.*
1. Sign up at [serper.dev](https://serper.dev/) (no credit card required for the 2,500 free search credits).
2. Copy your API key from the dashboard and paste into `.env`:
   ```env
   SERPER_API_KEY=your_serper_key_here
   ```

### 4. Hunter.io API Key (`HUNTER_API_KEY`) — 25 Free Searches/Month
*Uncovers verified decision-maker emails when a post links a company domain.*
1. Create a free account at [hunter.io](https://hunter.io/).
2. Go to **API** in your account menu, copy the key, and paste into `.env`:
   ```env
   HUNTER_API_KEY=your_hunter_key_here
   ```
*(Note: Even without Hunter.io, LeadRadar's built-in regex extractor automatically pulls direct emails, phone/WhatsApp numbers, and `@handles` written inside posts for free.)*

### 5. Gmail / SMTP Credentials (`SMTP_EMAIL` & `SMTP_APP_PASSWORD`)
*Enables automatic background email dispatch whenever a lead contains an email address.*
- If you do not have a work email or SMTP configured yet, leave `SMTP_EMAIL` blank—LeadRadar will still prepare the subject and tailored body on every lead card and let you open it in your default mail client with one click (`Mail App`) or copy it (`Copy & Open DM`).
- When you are ready to enable automatic sending with Gmail or Google Workspace:
  1. Enable **2-Step Verification** on your Google Account at [myaccount.google.com/security](https://myaccount.google.com/security).
  2. Visit [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), generate a 16-character App Password, and add to `.env`:
     ```env
     SMTP_EMAIL=you@yourdomain.com
     SMTP_APP_PASSWORD=abcdefghijklmnop
     ```

### 6. Telegram Bot (`TELEGRAM_BOT_TOKEN`)
1. Message [@BotFather](https://t.me/BotFather) on Telegram and send `/newbot`.
2. Paste the token into `TELEGRAM_BOT_TOKEN` in `.env`.
3. Start LeadRadar and send `/start` to your new bot—your chat ID is saved automatically.

---

## Safety, Deduplication & Outreach Rules

1. **Cross-Platform Fingerprint Deduplication:** Every post is hashed using a normalized text fingerprint so cross-posted requests across Reddit, X, LinkedIn, or Freelancer are never stored or alerted twice.
2. **Single-Send Email Guard (`sent_emails` table):** LeadRadar tracks every emailed address in SQLite. Automated outreach will never email the same address more than once.
3. **Human-First Social DM Workflow:** Because platforms like X, Facebook, and LinkedIn ban automated DM bots, LeadRadar never risks your social accounts. Instead, it prepares the tailored response and extracts the poster's `@username`, phone/WhatsApp, or profile URL so you can click **Copy & Open DM** and send personally in seconds.
4. **CSV Formula Sanitization:** CSV exports automatically neutralize leading `=`, `+`, `-`, and `@` characters to protect spreadsheet tools against formula injection.

---

## Adding Custom Ingestion Sources

Subclass `Source` in `app/sources.py`, implement `async def fetch(self, kws)`, and append your class in `build_sources()`:

```python
from .sources import Source
from .net import http

class CustomBoard(Source):
    name = "custom_board"
    interval = 180
    need_intent = False  # False if every post on the board is already a buyer request

    async def fetch(self, kws):
        r = await http.get("https://api.example.com/jobs")
        if r.status_code != 200:
            return []
        return [{
            "uid": f"cb:{item['id']}",
            "source": self.name,
            "author": item.get("username", ""),
            "url": item.get("url", ""),
            "text": f"{item.get('title', '')}\n{item.get('description', '')}",
            "posted_at": item.get("created_at"),
        } for item in r.json().get("items", [])]
```

---

## Contributing

1. Fork the repository at [github.com/frankdotdev/LeadRadar](https://github.com/frankdotdev/LeadRadar).
2. Create a feature branch (`git checkout -b feat/your-feature`).
3. Commit your changes (`git commit -m "feat: add new source connector"`).
4. Push to your branch and open a Pull Request.

---

## Author & Credits

Built by **Frank Oge** ([frankoge.com](https://frankoge.com)) of **Hackverse Technologies** ([hackversetechnologies.vercel.app](https://hackversetechnologies.vercel.app)).

- **GitHub**: [@frankdotdev](https://github.com/frankdotdev)
- **Repository**: [https://github.com/frankdotdev/LeadRadar](https://github.com/frankdotdev/LeadRadar)

---

## License & Disclaimer

This project is licensed under the **[MIT License](LICENSE)**.

*Disclaimer: You are responsible for ensuring your outreach practices comply with applicable local and international regulations (such as CAN-SPAM, GDPR, and platform terms of service).*
