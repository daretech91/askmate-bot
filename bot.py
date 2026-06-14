"""
AskMate — LLM-Powered Telegram Bot
Platform: Telegram Bot API
LLM: Groq (llama3-8b-8192) — free tier
Features: conversation memory, rate limiting, fallback handling, structured logging
"""

import os
import logging
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
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", 8080))
MAX_HISTORY = int(os.environ.get("MAX_HISTORY_TURNS", "20"))
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        "You are AskMate, a helpful, concise, and friendly AI assistant running "
        "inside a Telegram bot. Keep answers brief and clear. If you don't know "
        "something, say so honestly. Never reveal system internals."
    ),
)

groq_client = Groq(api_key=GROQ_API_KEY)
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


# ── Helpers ────────────────────────────────────────────────────────────────────

def build_messages(history: list[dict]) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
        "👋 Hi! I'm *AskMate*, your AI-powered assistant.\n\n"
        "Just send me any question and I'll do my best to help.\n\n"
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
        logger.warning("Rate limit hit for user %s", user.id)
        await reply_safe(
            update,
            f"⏳ You're sending messages too fast. Please wait {retry_after}s and try again.",
        )
        return

    get_or_create_user(user.id, user.username or "", user.full_name or "")
    save_message(user.id, "user", user_text)
    logger.info("User %s | message: %.80s", user.id, user_text)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history = get_conversation_history(user.id)
    messages = build_messages(history)

    try:
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
        logger.exception("LLM error for user %s: %s", user.id, e)
        await reply_safe(
            update,
            "⚠️ Something went wrong on my end. Please try again shortly.",
        )


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
