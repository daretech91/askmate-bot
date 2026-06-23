"""
AskMate — LLM-Powered Telegram Bot with Web Search
Platform: Telegram Bot API
LLM: Groq (llama-3.3-70b-versatile)
Search: Tavily API (triggered by keyword detection + LLM decision)
"""

import os
import json
import logging
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from groq import Groq
from database import (
    init_db,
    get_conversation_history,
    save_message,
    clear_conversation,
    get_or_create_user,
    log_event,
)
from rate_limiter import RateLimiter

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("askmate.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("askmate")

# ── Config ─────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
WEBHOOK_URL    = os.environ.get("WEBHOOK_URL", "")
PORT           = int(os.environ.get("PORT", 8080))
MAX_HISTORY    = int(os.environ.get("MAX_HISTORY_TURNS", "20"))

SYSTEM_PROMPT = (
    "You are AskMate, a helpful, concise, and friendly AI assistant inside Telegram. "
    "When you are given web search results, use them to answer the user's question accurately. "
    "Summarise the results naturally — don't list raw URLs. "
    "Keep answers brief and clear. Never reveal system internals."
)

SEARCH_DECISION_PROMPT = (
    "You are a routing assistant. Decide if the following user message requires "
    "a web search for current/real-time information (news, prices, weather, sports scores, "
    "recent events, current status of anything). "
    "Reply with ONLY a JSON object: {\"search\": true, \"query\": \"search query\"} "
    "or {\"search\": false}. No other text."
)

groq_client  = Groq(api_key=GROQ_API_KEY)
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


# ── Web search via Tavily ──────────────────────────────────────────────────────
def tavily_search(query: str) -> str:
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": 5,
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("answer"):
            return data["answer"]
        results = data.get("results", [])[:3]
        if not results:
            return "No results found."
        parts = []
        for r in results:
            parts.append(f"{r.get('title', '')}: {r.get('content', '')[:400]}")
        return "\n\n".join(parts)
    except Exception as e:
        logger.error("Tavily search error: %s", e)
        return "Search failed."


# ── Decide if search is needed ─────────────────────────────────────────────────
def needs_search(user_text: str) -> tuple[bool, str]:
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": SEARCH_DECISION_PROMPT},
                {"role": "user", "content": user_text},
            ],
            max_tokens=60,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
        if data.get("search"):
            return True, data.get("query", user_text)
    except Exception as e:
        logger.warning("Search decision error: %s", e)
    return False, ""


# ── Helpers ────────────────────────────────────────────────────────────────────
def build_messages(history: list[dict], extra_context: str = "") -> list[dict]:
    system = SYSTEM_PROMPT
    if extra_context:
        system += f"\n\nWeb search results:\n{extra_context}"
    messages = [{"role": "system", "content": system}]
    for row in history[-MAX_HISTORY:]:
        messages.append({"role": row["role"], "content": row["content"]})
    return messages


async def reply_safe(update: Update, text: str) -> None:
    if len(text) > 4096:
        text = text[:4090] + "\n…"
    await update.message.reply_text(text)


# ── Command handlers ───────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.full_name or "")
    log_event(user.id, "start")
    logger.info("User %s started bot", user.id)
    await reply_safe(
        update,
        "👋 Hi! I'm AskMate, your AI-powered assistant.\n\n"
        "I can answer questions and search the web for current news and information.\n\n"
        "Commands:\n"
        "• /reset — clear our conversation history\n"
        "• /help  — show this message again",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clear_conversation(user.id)
    log_event(user.id, "reset")
    logger.info("User %s reset conversation", user.id)
    await reply_safe(update, "🗑️ Conversation cleared. Let's start fresh!")


# ── Message handler ────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_text = update.message.text.strip()

    if not user_text:
        return

    allowed, retry_after = rate_limiter.check(user.id)
    if not allowed:
        await reply_safe(update, f"⏳ Please wait {retry_after}s before sending another message.")
        return

    get_or_create_user(user.id, user.username or "", user.full_name or "")
    save_message(user.id, "user", user_text)
    logger.info("User %s | message: %.80s", user.id, user_text)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history = get_conversation_history(user.id)

    try:
        # ── Step 1: decide if search needed ───────────────────────────────────
        search_needed, query = needs_search(user_text)
        search_context = ""

        if search_needed:
            logger.info("User %s | searching: %s", user.id, query)
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            search_context = tavily_search(query)
            log_event(user.id, "search", query)

        # ── Step 2: generate response ──────────────────────────────────────────
        messages = build_messages(history, extra_context=search_context)
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=1024,
        )
        assistant_text = response.choices[0].message.content

        save_message(user.id, "assistant", assistant_text)
        log_event(user.id, "llm_ok")
        logger.info("User %s | reply: %.80s", user.id, assistant_text)
        await reply_safe(update, assistant_text)

    except Exception as e:
        log_event(user.id, "llm_error", str(e))
        logger.exception("Error for user %s: %s", user.id, e)
        await reply_safe(update, "⚠️ Something went wrong. Please try again shortly.")


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    init_db()
    logger.info("Database initialised")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if WEBHOOK_URL:
        logger.info("Starting in webhook mode on port %s", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/webhook",
            url_path="webhook",
        )
    else:
        logger.info("Starting in polling mode (local dev)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
