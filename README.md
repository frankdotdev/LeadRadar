# LeadRadar

> **Autonomous Buyer-Intent Radar & Opportunity Listener.**  
> Continuously monitors social networks, discussion forums, job boards, and communities for high-intent buyer posts, filters out noise, scores leads with heuristics or LLMs, and delivers actionable Telegram alerts with single-click workflow triage.

[![GitHub Repository](https://img.shields.io/badge/GitHub-frankdotdev%2FLeadRadar-black?logo=github)](https://github.com/frankdotdev/LeadRadar)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-black.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-black.svg)](https://fastapi.tiangolo.com)
[![SQLite WAL](https://img.shields.io/badge/SQLite-WAL%20Mode-black.svg)](https://www.sqlite.org)

---

## Overview

Finding high-value freelance clients and agency projects typically means manually refreshing dozens of feeds, subreddits, and platforms. Most leads are buried under spam, recruitment posts, and low-budget noise.

**LeadRadar** solves this by running an autonomous, low-overhead listening pipeline:

1. **Ingest**: Concurrently polls 7+ free and keyed platforms on non-blocking asynchronous loops.
2. **Prefilter**: Runs fast regex intent detection, noise rejection, and negative-keyword exclusion in microseconds.
3. **Classify & Score**: Grades buyer intent from 0–100 using built-in heuristics or parallel Groq LLM reasoning (`llama-3.3-70b-versatile`).
4. **Deduplicate**: Computes cross-platform cryptographic text fingerprints so identical cross-posted messages are never duplicated.
5. **Alert & Action**: Fires instant Telegram messages with inline buttons (`Save`, `Contacted`, `Dismiss`) or presents them in a zero-framework, high-performance web dashboard with dark and light themes.

---

## Ingestion Sources

| Source | Access Type | Default Status | Notes |
| :--- | :--- | :--- | :--- |
| **Hacker News** | Public API | Enabled | Algolia real-time date search across stories and comments. |
| **Reddit** | Public JSON / RSS | Enabled | Polls 14+ subreddits (`r/forhire`, `r/webdev`, `r/startups`, etc.). |
| **Bluesky** | AT Protocol | Enabled | Public AT Protocol search; supports authenticated mode. |
| **Mastodon** | Public Timelines | Enabled | Federated tag timelines across multiple instances. |
| **Freelancer.com** | Public API | Enabled | Real-time project search filtered to active budgets. |
| **Lemmy** | Public Search API | Enabled | Open Fediverse search on target communities. |
| **Nairaland** | Web Ingestion | Enabled | Scrapes newest board topics across tech, business, and programming. |
| **Telegram Channels** | Web Preview Scraper | Optional | Set `TG_CHANNELS` or `TG_JOB_CHANNELS`. |
| **Custom RSS/Atom** | Feed Parser | Optional | Set `RSS_FEEDS` to any XML/Atom feed. |
| **X (Twitter) API v2**| Bearer Auth | Optional | Set `X_BEARER_TOKEN` for real-time recent search. |
| **Apify Actors** | Apify Token | Optional | Run LinkedIn, Facebook, or custom scrapers via Apify. |

---

## Quickstart

### Prerequisites
- Python 3.10, 3.11, or 3.12
- Git

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/frankdotdev/LeadRadar.git
cd LeadRadar

python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy the example configuration:

```bash
cp .env.example .env
```

Open `.env` in your editor. All keys are optional — LeadRadar works immediately out of the box using free sources and heuristic scoring.

### 4. Start the Application

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at **`http://localhost:8000`**.

---

## Telegram Alerts in 2 Minutes

LeadRadar uses Telegram long-polling to deliver real-time notifications with interactive action buttons — no public webhook URL or SSL domain required.

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, choose a name and username, then copy the HTTP API token into your `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
   ```
3. Start LeadRadar, open your bot in Telegram, and send `/start`.
4. Your chat ID is automatically captured and persisted in SQLite. When a lead meets or exceeds your `alert_score` threshold, it will arrive with inline triage buttons (`Open Post`, `Save`, `Contacted`, `Dismiss`).

---

## Groq AI Classification & Outreach Drafts

By default, LeadRadar scores intent using high-speed heuristics. Adding a free [Groq Cloud API key](https://console.groq.com/) enables LLM semantic evaluation:

```env
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
MY_SERVICES=web development, mobile apps, AI automation, e-commerce
MY_PITCH=I run Hackverse Technologies and build high-performance web, mobile, and AI solutions.
```

With Groq enabled:
- Leads receive an accurate buyer score (0–100), identified service category, and one-sentence intent reason.
- Clicking **AI Reply Draft** in the dashboard generates a customized, 70-word non-spammy outreach response tailored to the post's exact requirements.

---

## Dashboard Features

The web dashboard is designed with clean typography, sharp borders, and zero external framework overhead:

- **Light & Dark Mode**: Persistent theme toggle supporting system preferences with zero flicker.
- **Real-Time Stream**: Live connection status, active source tracking, and error diagnostics.
- **Search & Filtering**: Search by content text, author, or keyword; filter by status tab (`New`, `Saved`, `Contacted`, `Won`, `Dismissed`); filter by source; adjust minimum score threshold.
- **AI Reply Modal**: Review, edit, and copy tailored outreach responses before messaging.
- **CSV Export**: One-click download of all stored leads formatted for CRM import.
- **Live Settings**: Adjust monitored keywords, negative keywords, and alert thresholds in real time without restarting the server.
- **Keyboard Shortcuts**:
  - `/` : Focus search input
  - `Esc` : Close open modals

---

## Environment Configuration

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | *empty* | Telegram bot token from @BotFather. |
| `TELEGRAM_CHAT_ID` | *empty* | Auto-discovered upon `/start`, or manual chat ID. |
| `GROQ_API_KEY` | *empty* | Groq Cloud API key for Llama 3.3 70B analysis. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model identifier. |
| `MY_SERVICES` | `software development` | Services you offer (guides the LLM classifier). |
| `MY_PITCH` | *Custom string* | Brief background used to craft outreach replies. |
| `REDDIT_SUBS` | *14 default subs* | Comma-separated list of subreddits to monitor. |
| `TG_CHANNELS` | *empty* | Public Telegram channel handles for conversational posts. |
| `TG_JOB_CHANNELS` | *empty* | Channel handles where all posts are vacancy/gig listings. |
| `RSS_FEEDS` | *empty* | Comma-separated list of RSS/Atom feed URLs. |
| `X_BEARER_TOKEN` | *empty* | Official X API v2 bearer token. |
| `APIFY_TOKEN` | *empty* | Apify API token for running actor scrapers. |
| `APIFY_ACTORS` | `[]` | JSON array defining Apify actors and query templates. |
| `MAX_AGE_HOURS` | `48` | Maximum post age in hours before dropping as stale. |
| `MIN_STORE_SCORE` | `35` | Minimum score required to store a lead in the database. |

---

## Adding a Custom Source

To add an ingestion source, inherit from `Source` in `app/sources.py`, implement `async def fetch(self, kws)`, and add it to `build_sources()`:

```python
from .sources import Source
from .net import http

class MyCustomJobBoard(Source):
    name = "custom_board"
    interval = 180  # Run every 3 minutes
    need_intent = False  # Set to False if every item is already a buyer

    async def fetch(self, kws):
        response = await http.get("https://api.example.com/v1/jobs")
        if response.status_code != 200:
            return []
        
        items = response.json().get("data", [])
        return [{
            "uid": f"cb:{item['id']}",
            "source": self.name,
            "author": item.get("company", ""),
            "url": item.get("apply_url", ""),
            "text": f"{item.get('title')}\n{item.get('description')}",
            "posted_at": item.get("timestamp")
        } for item in items]
```

---

## Production Deployment

### Option A: Systemd Service (Ubuntu / Debian VPS)

Create `/etc/systemd/system/leadradar.service`:

```ini
[Unit]
Description=LeadRadar Intent Listener
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/leadradar
ExecStart=/home/ubuntu/leadradar/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
EnvironmentFile=/home/ubuntu/leadradar/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now leadradar
```

### Option B: Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Run:
```bash
docker build -t leadradar .
docker run -d -p 8000:8000 --env-file .env -v $(pwd)/radar.db:/app/radar.db leadradar
```

---

## Authors & Credits

Built by **Frank Oge** ([frankoge.com](https://frankoge.com)) of **Hackverse Technologies** ([hackversetechnologies.vercel.app](https://hackversetechnologies.vercel.app)).

- **GitHub Profile**: [@frankdotdev](https://github.com/frankdotdev)
- **Repository**: [https://github.com/frankdotdev/LeadRadar](https://github.com/frankdotdev/LeadRadar)

---

## License

This project is licensed under the [MIT License](LICENSE).
