"""Lazy database initialization: schema + seed data."""
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_db_path() -> str:
    env = os.environ.get("FINALLY_DB_PATH")
    if env:
        return env
    # backend/app/db/init.py -> repo root is parents[3]
    return str(Path(__file__).resolve().parents[3] / "db" / "finally.db")


def init_db(path: str | None = None) -> str:
    """Create tables and seed defaults if missing. Idempotent. Returns the db path."""
    path = str(path or default_db_path())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        ts = now_iso()
        with conn:
            has_user = conn.execute("SELECT 1 FROM users_profile WHERE id='default'").fetchone()
            if not has_user:
                conn.execute(
                    "INSERT INTO users_profile (id, cash_balance, created_at) "
                    "VALUES ('default', 10000.0, ?)",
                    (ts,),
                )
                # Seed watchlist only on first creation so user removals persist.
                for t in DEFAULT_TICKERS:
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) "
                        "VALUES (?, 'default', ?, ?)",
                        (str(uuid.uuid4()), t, ts),
                    )
    finally:
        conn.close()
    return path
