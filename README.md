# AskMate 🤖

> An LLM-powered Telegram bot with per-user conversation memory, rate limiting, structured logging, and production webhook deployment on Railway.

**Live bot:** [@askmate_llm_bot](https://t.me/askmate_llm_bot)

-----

## Overview

AskMate is a production-ready Telegram bot that integrates the Groq API (Llama 3.3 70B) to deliver fast, natural language conversations with persistent memory per user. It demonstrates the full lifecycle of a real messaging-platform integration: webhook setup, dialogue state management, graceful error handling, rate limiting, and PaaS deployment.

**Platform:** Telegram Bot API  
**LLM:** Groq — Llama 3.3 70B Versatile  
**Language:** Python 3.11+  
**Hosting:** Railway.app

-----

## Architecture

```
User (Telegram)
     │
     ▼ HTTPS webhook
┌─────────────────────────────────────┐
│          Railway.app (PaaS)         │
│                                     │
│  ┌──────────┐   ┌────────────────┐  │
│  │  bot.py  │──▶│  rate_limiter  │  │
│  │ (PTB app)│   └────────────────┘  │
│  └────┬─────┘                       │
│       │                             │
│  ┌────▼─────┐   ┌────────────────┐  │
│  │ database │   │   Groq API     │  │
│  │ (SQLite) │   │ (Llama 3.3 70B)│  │
│  └──────────┘   └────────────────┘  │
└─────────────────────────────────────┘
```

**Key design decisions:**

- **Webhook over polling** in production — lower latency, no wasted polling cycles, Railway-compatible
- **SQLite with WAL mode** — safe concurrent reads, zero-config, sufficient for single-instance bots
- **Sliding-window rate limiter** — in-memory, thread-safe, prevents API abuse
- **Layered error handling** — users always get a human-readable message, never a raw traceback

-----

## Features

|Feature              |Implementation                                                  |
|---------------------|----------------------------------------------------------------|
|Telegram Bot API     |`python-telegram-bot` v21, webhook mode                         |
|Conversational memory|Per-user message history in SQLite, last N turns sent as context|
|LLM integration      |Groq API (Llama 3.3 70B) via `groq` SDK                         |
|Rate limiting        |Sliding-window (10 req/min per user), in-memory, thread-safe    |
|Fallback handling    |All error types caught — no silent failures                     |
|Typing indicator     |`send_chat_action` while LLM processes                          |
|Structured logging   |File + stdout, includes user ID and event type                  |
|Event audit log      |Every command and LLM call logged to `events` table             |
|Conversation reset   |`/reset` clears per-user history                                |
|Configurable         |All tunable values via environment variables                    |
|Deployment           |Railway.app with `railway.toml`, restart-on-failure policy      |

-----

## Commands

|Command |Description                            |
|--------|---------------------------------------|
|`/start`|Greet the user and show help           |
|`/help` |Show available commands                |
|`/reset`|Clear conversation history for the user|

-----

## Database Schema

```sql
CREATE TABLE users (
    telegram_id  INTEGER PRIMARY KEY,
    username     TEXT,
    full_name    TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER NOT NULL,
    event_type   TEXT NOT NULL,
    detail       TEXT,
    created_at   TEXT NOT NULL
);
```

-----

## Local Development

```bash
# 1. Clone the repo
git clone https://github.com/daretech91/askmate-bot
cd askmate-bot

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add TELEGRAM_BOT_TOKEN and GROQ_API_KEY
# Leave WEBHOOK_URL empty for local polling mode

# 5. Run
python bot.py
```

-----

## Deploying to Railway

1. Push this repo to GitHub
1. Create a new project on [Railway.app](https://railway.app) → **Deploy from GitHub repo**
1. Set environment variables in Railway dashboard:
- `TELEGRAM_BOT_TOKEN`
- `GROQ_API_KEY`
- `WEBHOOK_URL` → your Railway public domain
1. Railway auto-detects Python via Nixpacks and runs `python bot.py`
1. Bot switches to webhook mode automatically when `WEBHOOK_URL` is set

-----

## Environment Variables

|Variable            |Required  |Default     |Description                                      |
|--------------------|----------|------------|-------------------------------------------------|
|`TELEGRAM_BOT_TOKEN`|✅         |—           |From [@BotFather](https://t.me/botfather)        |
|`GROQ_API_KEY`      |✅         |—           |From [console.groq.com](https://console.groq.com)|
|`WEBHOOK_URL`       |Production|—           |Public HTTPS URL for webhook registration        |
|`PORT`              |No        |`8080`      |Port for webhook server                          |
|`MAX_HISTORY_TURNS` |No        |`20`        |Number of past messages sent as LLM context      |
|`DB_PATH`           |No        |`askmate.db`|SQLite database file path                        |
|`SYSTEM_PROMPT`     |No        |See bot.py  |System prompt for the LLM                        |

-----

## Error Handling Strategy

```
Message received
       │
       ├─ Rate limit exceeded?  → "Please wait Xs"
       │
       └─ Call Groq API
              │
              └─ Any error → "Something went wrong" + logged with full traceback
```

All errors are logged with user ID and recorded in the `events` table.

-----

## Extending This Bot

- **Multi-platform:** Add Discord/Slack handlers sharing the same `database.py` and `rate_limiter.py`
- **Tool use:** Connect LLM to external APIs (weather, search, calendar)
- **User tiers:** Store subscription level in `users` table, apply different rate limits
- **Admin commands:** `/stats`, `/broadcast` behind admin ID check
- **Postgres:** Swap SQLite for Postgres for multi-instance Railway deployments

-----

## Tech Stack

- **Python 3.11+**
- [`python-telegram-bot`](https://python-telegram-bot.org/) v21
- [`groq`](https://pypi.org/project/groq/) — Groq SDK (Llama 3.3 70B)
- `sqlite3` — built-in, WAL mode
- [Railway.app](https://railway.app) — PaaS deployment

-----

## License

MIT
