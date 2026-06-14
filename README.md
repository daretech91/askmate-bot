# AskMate 🤖

> An LLM-powered Telegram bot with per-user conversation memory, rate limiting, structured logging, and production webhook deployment on Railway.

-----

## Overview

AskMate is a production-ready Telegram bot that integrates the Anthropic Claude API to deliver natural language conversations with persistent memory per user. It demonstrates the full lifecycle of a real messaging-platform integration: webhook setup, dialogue state management, graceful error handling, rate limiting, and PaaS deployment.

**Live on:** Railway.app  
**Platform:** Telegram Bot API  
**LLM:** Anthropic Claude (claude-haiku-4-5)  
**Language:** Python 3.11+

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
│  │ database │   │  Anthropic API │  │
│  │ (SQLite) │   │  (Claude LLM)  │  │
│  └──────────┘   └────────────────┘  │
└─────────────────────────────────────┘
```

**Key design decisions:**

- **Webhook over polling** in production — lower latency, no wasted polling cycles, Railway-compatible
- **SQLite with WAL mode** — safe concurrent reads, zero-config, sufficient for single-instance bots
- **Sliding-window rate limiter** — in-memory, thread-safe, prevents API cost abuse
- **Layered error handling** — distinguishes timeout vs API error vs unexpected crash; users always get a human-readable message, never a raw traceback

-----

## Features

|Feature              |Implementation                                                        |
|---------------------|----------------------------------------------------------------------|
|Telegram Bot API     |`python-telegram-bot` v21, webhook mode                               |
|Conversational memory|Per-user message history in SQLite, last N turns sent as context      |
|LLM integration      |Anthropic Claude API via `anthropic` SDK                              |
|Rate limiting        |Sliding-window (10 req/min per user), in-memory, thread-safe          |
|Fallback handling    |Timeout, API error, and unexpected error branches — no silent failures|
|Typing indicator     |`send_chat_action` while LLM processes                                |
|Structured logging   |File + stdout, includes user ID, event type, token usage              |
|Event audit log      |Every command and LLM call logged to `events` table                   |
|Conversation reset   |`/reset` clears per-user history, confirmed to user                   |
|Configurable         |All tunable values via environment variables                          |
|Deployment           |Railway.app with `railway.toml`, restart-on-failure policy            |

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
-- Users registry
CREATE TABLE users (
    telegram_id  INTEGER PRIMARY KEY,
    username     TEXT,
    full_name    TEXT,
    created_at   TEXT NOT NULL
);

-- Per-user conversation history (role = 'user' | 'assistant')
CREATE TABLE messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- Audit log for all bot events
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
git clone https://github.com/YOUR_USERNAME/askmate-bot
cd askmate-bot

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY
# Leave WEBHOOK_URL empty for local polling mode

# 5. Run
python bot.py
```

> **Tip:** For local webhook testing, use [ngrok](https://ngrok.com/):
> `ngrok http 8443` → set `WEBHOOK_URL` to the ngrok HTTPS URL.

-----

## Deploying to Railway

1. Push this repo to GitHub
1. Create a new project on [Railway.app](https://railway.app) → **Deploy from GitHub repo**
1. Set environment variables in Railway dashboard:
- `TELEGRAM_BOT_TOKEN`
- `ANTHROPIC_API_KEY`
- `WEBHOOK_URL` → your Railway public domain (e.g. `https://askmate-bot.up.railway.app`)
1. Railway auto-detects Python via Nixpacks and runs `python bot.py`
1. Bot switches to webhook mode automatically when `WEBHOOK_URL` is set

-----

## Environment Variables

|Variable            |Required  |Default     |Description                                                |
|--------------------|----------|------------|-----------------------------------------------------------|
|`TELEGRAM_BOT_TOKEN`|✅         |—           |From [@BotFather](https://t.me/botfather)                  |
|`ANTHROPIC_API_KEY` |✅         |—           |From [console.anthropic.com](https://console.anthropic.com)|
|`WEBHOOK_URL`       |Production|—           |Public HTTPS URL for webhook registration                  |
|`PORT`              |No        |`8443`      |Port for webhook server                                    |
|`MAX_HISTORY_TURNS` |No        |`20`        |Number of past messages sent as LLM context                |
|`DB_PATH`           |No        |`askmate.db`|SQLite database file path                                  |
|`SYSTEM_PROMPT`     |No        |See bot.py  |System prompt for the LLM                                  |

-----

## Error Handling Strategy

```
Message received
       │
       ├─ Rate limit exceeded?  → "Please wait Xs" (no LLM call)
       │
       └─ Call Anthropic API
              │
              ├─ APITimeoutError  → "AI took too long, please retry"
              ├─ APIError         → "Something went wrong, try again"
              └─ Unexpected       → "Unexpected error, logged" + logger.exception()
```

All errors are:

- Logged with user ID and traceback (where applicable)
- Recorded in the `events` table for audit
- Communicated to the user with a friendly, non-technical message

-----

## Extending This Bot

This bot is designed as a foundation. Possible extensions:

- **Multi-platform:** Add Discord/Slack handlers sharing the same `database.py` and `rate_limiter.py`
- **Tool use:** Connect Claude’s tool-calling to external APIs (weather, calendar, search)
- **User tiers:** Store subscription level in `users` table, apply different rate limits
- **Admin commands:** `/stats`, `/broadcast`, `/ban` behind admin ID check
- **Postgres:** Swap SQLite for Postgres for multi-instance Railway deployments

-----

## Tech Stack

- **Python 3.11+**
- [`python-telegram-bot`](https://python-telegram-bot.org/) v21 — async Telegram wrapper
- [`anthropic`](https://pypi.org/project/anthropic/) — official Claude SDK
- `sqlite3` — built-in, WAL mode for safe concurrent access
- [Railway.app](https://railway.app) — PaaS deployment

-----

## License

MIT
