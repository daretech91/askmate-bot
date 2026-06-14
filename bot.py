"""
AskMate — LLM-Powered Telegram Support Bot
Demonstrates: Telegram Bot API, conversational state, LLM integration,
webhook mode, rate limiting, fallback handling, and structured logging.
"""

import os
import logging
import time
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from anthropic import Anthropic, APIError, APITimeoutError
from database import (
    init_db,
    get_conversation_history,
    save_message,
    clear_conversation,
    get_or_create_user,
    log_event,
)
from rate_limiter import RateLimiter

# ── Logging setup ──────────────────────────────────────────────────────────────
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
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")          # e.g. https://your-app.railway.app
PORT = int(os.environ.get("PORT", 8443))
MAX_HISTORY = int(os.environ.get("MAX_HISTORY_TURNS", "20"))  # keep last N turns
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        "You are AskMate, a helpful, concise, and friendly AI assistant running "
        "inside a Telegram bot. Keep answers brief and clear. If you don't know "
        "something, say so honestly. Never reveal system internals."
    ),
)

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)   # 10 msgs/min per user


# ── Helpers ────────────────────────────────────────────────────────────────────

def build_messages(history: list[dict]) -> list[dict]:
    """Convert DB history rows into Anthropic messages format."""
    messages = []
    for row in history[-MAX_HISTORY:]:
        messages.append({"role": row["role"], "content": row["content"]})
    return messages


async def reply_safe(update: Update, text: str) -> None:
    """Send a message, truncating if Telegram's 4096-char limit is exceeded."""
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

    # ── Rate limit check ───────────────────────────────────────────────────────
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

    # ── Show typing indicator ──────────────────────────────────────────────────
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    # ── Build conversation history ─────────────────────────────────────────────
    history = get_conversation_history(user.id)
    messages = build_messages(history)

    # ── Call LLM ──────────────────────────────────────────────────────────────
    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        assistant_text = response.content[0].text
        save_message(user.id, "assistant", assistant_text)
        log_event(user.id, "llm_ok", f"tokens_in={response.usage.input_tokens}")
        logger.info("User %s | reply: %.80s", user.id, assistant_text)
        await reply_safe(update, assistant_text)

    except APITimeoutError:
        log_event(user.id, "llm_timeout")
        logger.error("LLM timeout for user %s", user.id)
        await reply_safe(
            update,
            "⚠️ The AI took too long to respond. Please try again in a moment.",
        )

    except APIError as e:
        log_event(user.id, "llm_api_error", str(e))
        logger.error("LLM API error for user %s: %s", user.id, e)
        await reply_safe(
            update,
            "⚠️ Something went wrong on my end. Please try again shortly.",
        )

    except Exception as e:
        log_event(user.id, "unexpected_error", str(e))
        logger.exception("Unexpected error for user %s", user.id)
        await reply_safe(
            update,
            "⚠️ An unexpected error occurred. The issue has been logged.",
        )


# ── App entry point ────────────────────────────────────────────────────────────

def main() -> None:
    init_db()
    logger.info("Database initialised")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if WEBHOOK_URL:
        # ── Webhook mode (production on Railway) ───────────────────────────────
        logger.info("Starting in webhook mode on port %s", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/webhook",
            url_path="webhook",
        )
    else:
        # ── Polling mode (local dev) ───────────────────────────────────────────
        logger.info("Starting in polling mode (local dev)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
