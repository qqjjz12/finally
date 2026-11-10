"""Synchronous SQLite repository (single-user, user_id='default')."""
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from .init import default_db_path, init_db, now_iso

USER = "default"


class DbError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def get_connection(path: str | None = None) -> sqlite3.Connection:
    path = str(path or default_db_path())
    init_db(path)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)  # autocommit; we manage txns
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _norm(ticker) -> str:
    return ticker.strip().upper() if isinstance(ticker, str) else ""


def get_cash(conn) -> float:
    row = conn.execute("SELECT cash_balance FROM users_profile WHERE id=?", (USER,)).fetchone()
    return float(row["cash_balance"])


def list_positions(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ticker, quantity, avg_cost, updated_at FROM positions "
        "WHERE user_id=? ORDER BY ticker",
        (USER,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_watchlist(conn) -> list[str]:
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id=? ORDER BY added_at, rowid", (USER,)
    ).fetchall()
    return [r["ticker"] for r in rows]


def add_watchlist(conn, ticker: str) -> None:
    t = _norm(ticker)
    if not t:
        raise DbError("invalid_request", "ticker is required")
    try:
        conn.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), USER, t, now_iso()),
        )
    except sqlite3.IntegrityError:
        raise DbError("already_exists", f"{t} is already on the watchlist") from None


def remove_watchlist(conn, ticker: str, confirm: bool = False) -> None:
    t = _norm(ticker)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not conn.execute(
            "SELECT 1 FROM watchlist WHERE user_id=? AND ticker=?", (USER, t)
        ).fetchone():
            raise DbError("not_found", f"{t} is not on the watchlist")
        if not confirm and conn.execute(
            "SELECT 1 FROM positions WHERE user_id=? AND ticker=?", (USER, t)
        ).fetchone():
            raise DbError(
                "position_open",
                f"You hold a position in {t}; its price will stop updating if removed",
            )
        conn.execute("DELETE FROM watchlist WHERE user_id=? AND ticker=?", (USER, t))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _validate_quantity(quantity) -> Decimal:
    try:
        if isinstance(quantity, bool) or quantity is None:
            raise InvalidOperation
        q = Decimal(str(quantity))
    except (InvalidOperation, ValueError):
        raise DbError("invalid_request", "quantity must be a number") from None
    if not q.is_finite() or q <= 0:
        raise DbError("invalid_request", "quantity must be greater than 0")
    if q != q.quantize(Decimal("0.000001")):
        raise DbError("invalid_request", "quantity may have at most 6 decimal places")
    return q


def execute_trade(conn, ticker: str, side: str, quantity, price: float) -> dict:
    t = _norm(ticker)
    if not t:
        raise DbError("invalid_request", "ticker is required")
    side = side.strip().lower() if isinstance(side, str) else ""
    if side not in ("buy", "sell"):
        raise DbError("invalid_request", "side must be 'buy' or 'sell'")
    q = float(_validate_quantity(quantity))
    try:
        price = float(price)
    except (TypeError, ValueError):
        raise DbError("invalid_request", "price must be a number") from None
    if not (0 < price < float("inf")):
        raise DbError("invalid_request", "price must be greater than 0")

    ts = now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cash = get_cash(conn)
        pos = conn.execute(
            "SELECT id, quantity, avg_cost FROM positions WHERE user_id=? AND ticker=?", (USER, t)
        ).fetchone()
        cost = q * price
        if side == "buy":
            if cost > cash + 1e-9:
                raise DbError(
                    "insufficient_cash", f"Need ${cost:,.2f} but only ${cash:,.2f} available"
                )
            cash -= cost
            if pos:
                new_q = pos["quantity"] + q
                new_avg = (pos["quantity"] * pos["avg_cost"] + cost) / new_q
                conn.execute(
                    "UPDATE positions SET quantity=?, avg_cost=?, updated_at=? WHERE id=?",
                    (new_q, new_avg, ts, pos["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), USER, t, q, price, ts),
                )
        else:
            held = pos["quantity"] if pos else 0.0
            if q > held + 1e-9:
                raise DbError("insufficient_shares", f"Cannot sell {q:g} {t}; you hold {held:g}")
            cash += q * price
            new_q = held - q
            if new_q <= 1e-9:
                conn.execute("DELETE FROM positions WHERE id=?", (pos["id"],))
            else:
                conn.execute(
                    "UPDATE positions SET quantity=?, updated_at=? WHERE id=?",
                    (new_q, ts, pos["id"]),
                )
        conn.execute("UPDATE users_profile SET cash_balance=? WHERE id=?", (cash, USER))
        conn.execute(
            "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), USER, t, side, q, price, ts),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return {"ticker": t, "side": side, "quantity": q, "price": price, "cash_balance": cash}


def list_trades(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ticker, side, quantity, price, executed_at FROM trades "
        "WHERE user_id=? ORDER BY executed_at DESC, rowid DESC",
        (USER,),
    ).fetchall()
    return [dict(r) for r in rows]


def record_snapshot(conn, total_value: float) -> None:
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), USER, float(total_value), now_iso()),
    )


def list_snapshots(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT recorded_at, total_value FROM portfolio_snapshots WHERE user_id=? "
        "ORDER BY recorded_at, rowid",
        (USER,),
    ).fetchall()
    return [dict(r) for r in rows]


def prune_snapshots(conn, days: int = 7) -> int:
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    cur = conn.execute(
        "DELETE FROM portfolio_snapshots WHERE user_id=? AND recorded_at < ?", (USER, cutoff)
    )
    return cur.rowcount


def add_chat_message(conn, role: str, content: str, actions=None) -> None:
    if role not in ("user", "assistant"):
        raise DbError("invalid_request", "role must be 'user' or 'assistant'")
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            USER,
            role,
            content,
            json.dumps(actions) if actions is not None else None,
            now_iso(),
        ),
    )


def list_chat_messages(conn, limit: int | None = None) -> list[dict]:
    """Oldest first. With limit, returns the most recent `limit` messages (still oldest first)."""
    sql = (
        "SELECT id, role, content, actions, created_at FROM chat_messages "
        "WHERE user_id=? ORDER BY created_at DESC, rowid DESC"
    )
    params: list = [USER]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    out = []
    for row in reversed(rows):
        d = dict(row)
        d["actions"] = json.loads(d["actions"]) if d["actions"] else None
        out.append(d)
    return out
