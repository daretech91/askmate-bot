"""
database.py — SQLite persistence layer for AskMate.
Handles users, conversation history, and event logging.
"""

import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "askmate.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent reads
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id  INTEGER PRIMARY KEY,
                username     TEXT,
                full_name    TEXT,
                created_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id  INTEGER NOT NULL,
                role         TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content      TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_user
                ON messages(telegram_id, created_at);

            CREATE TABLE IF NOT EXISTS events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id  INTEGER NOT NULL,
                event_type   TEXT NOT NULL,
                detail       TEXT,
                created_at   TEXT NOT NULL
            );
        """)


def get_or_create_user(telegram_id: int, username: str, full_name: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (telegram_id, username, full_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name
        """, (telegram_id, username, full_name, _now()))


def save_message(telegram_id: int, role: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO messages (telegram_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (telegram_id, role, content, _now()))


def get_conversation_history(telegram_id: int, limit: int = 40) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT role, content, created_at
            FROM messages
            WHERE telegram_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (telegram_id, limit)).fetchall()
    # Return in chronological order
    return [dict(r) for r in reversed(rows)]


def clear_conversation(telegram_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM messages WHERE telegram_id = ?", (telegram_id,)
        )


def log_event(telegram_id: int, event_type: str, detail: str = "") -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO events (telegram_id, event_type, detail, created_at)
            VALUES (?, ?, ?, ?)
        """, (telegram_id, event_type, detail, _now()))


def _now() -> str:
    return datetime.utcnow().isoformat()
