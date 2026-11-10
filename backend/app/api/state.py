"""Shared application state and domain helpers (valuation, trades, watchlist)."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from app.db import repository as repo
from app.market import PriceCache
from app.market.interface import MarketDataSource
from app.market.massive_client import MassiveDataSource

from .errors import ApiError

logger = logging.getLogger(__name__)

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,4}([.\-][A-Z0-9]{1,2})?$")
SNAPSHOT_INTERVAL = 30.0


@contextmanager
def db():
    """Open a short-lived connection (use and close within the same thread)."""
    conn = repo.get_connection()
    try:
        yield conn
    finally:
        conn.close()


class AppState:
    def __init__(self, cache: PriceCache, source: MarketDataSource) -> None:
        self.cache = cache
        self.source = source
        self.frozen: dict[str, float] = {}  # last price of tickers no longer streamed
        self.reference: dict[str, float] = {}  # per-ticker reference (first price seen)
        self.snapshot_task: asyncio.Task | None = None

    # ---- prices -------------------------------------------------------
    def price_of(self, ticker: str) -> float | None:
        price = self.cache.get_price(ticker)
        if price is not None:
            self.frozen[ticker] = price
            return price
        return self.frozen.get(ticker)

    def reference_of(self, ticker: str) -> float | None:
        if ticker not in self.reference:
            price = self.cache.get_price(ticker)
            if price is None:
                return self.frozen.get(ticker)
            self.reference[ticker] = price
        return self.reference[ticker]

    # ---- valuation ----------------------------------------------------
    def build_portfolio(self, conn) -> dict:
        cash = float(repo.get_cash(conn))
        positions = []
        invested = 0.0
        pnl_total = 0.0
        for p in repo.list_positions(conn):
            qty = float(p["quantity"])
            avg = float(p["avg_cost"])
            price = self.price_of(p["ticker"])
            if price is None:
                price = avg
            pnl = (price - avg) * qty
            invested += price * qty
            pnl_total += pnl
            positions.append(
                {
                    "ticker": p["ticker"],
                    "quantity": qty,
                    "avg_cost": avg,
                    "current_price": price,
                    "market_value": round(price * qty, 2),
                    "unrealized_pnl": round(pnl, 2),
                    "pnl_pct": round((price / avg - 1) * 100, 4) if avg else 0.0,
                }
            )
        return {
            "cash_balance": round(cash, 2),
            "total_value": round(cash + invested, 2),
            "unrealized_pnl": round(pnl_total, 2),
            "positions": positions,
        }

    def llm_context(self, conn) -> dict:
        pf = self.build_portfolio(conn)
        return {
            "cash": pf["cash_balance"],
            "total_value": pf["total_value"],
            "positions": [
                {
                    "ticker": p["ticker"],
                    "quantity": p["quantity"],
                    "avg_cost": p["avg_cost"],
                    "price": p["current_price"],
                    "pnl": p["unrealized_pnl"],
                    "pnl_pct": p["pnl_pct"],
                }
                for p in pf["positions"]
            ],
            "watchlist": [
                {"ticker": t, "price": self.cache.get_price(t)} for t in repo.list_watchlist(conn)
            ],
        }

    def snapshot(self, conn) -> None:
        repo.record_snapshot(conn, self.build_portfolio(conn)["total_value"])

    async def snapshot_loop(self) -> None:
        while True:
            await asyncio.sleep(SNAPSHOT_INTERVAL)
            try:
                await asyncio.to_thread(self._snapshot_and_prune)
            except Exception:
                logger.exception("Snapshot failed")

    def _snapshot_and_prune(self) -> None:
        with db() as conn:
            self.snapshot(conn)
            repo.prune_snapshots(conn)

    # ---- trades -------------------------------------------------------
    def trade(self, conn, ticker, side, quantity) -> dict:
        """Validate and execute a trade (sync; call from a worker thread)."""
        ticker, side, quantity = validate_trade(ticker, side, quantity)
        price = self.price_of(ticker)
        if price is None:
            raise ApiError(
                "unknown_ticker",
                f"No price available for {ticker}; add it to the watchlist first.",
            )
        result = repo.execute_trade(conn, ticker, side, quantity, price)
        self.snapshot(conn)
        return result

    # ---- watchlist ----------------------------------------------------
    async def watchlist_add(self, ticker) -> str:
        ticker = normalize_ticker(ticker)
        if isinstance(self.source, MassiveDataSource) and not await self._massive_knows(ticker):
            raise ApiError("unknown_ticker", f"Unknown ticker {ticker}")

        def work():
            with db() as conn:
                repo.add_watchlist(conn, ticker)

        await asyncio.to_thread(work)
        await self.source.add_ticker(ticker)
        # A re-added unseeded ticker gets a fresh random start price, so reset its reference.
        self.reference.pop(ticker, None)
        self.frozen.pop(ticker, None)
        self.reference_of(ticker)
        return ticker

    async def watchlist_remove(self, ticker, confirm: bool = False) -> str:
        ticker = normalize_ticker(ticker)

        def work():
            with db() as conn:
                repo.remove_watchlist(conn, ticker, confirm=confirm)

        await asyncio.to_thread(work)
        self.price_of(ticker)  # freeze last price before the cache drops it
        await self.source.remove_ticker(ticker)
        return ticker

    async def _massive_knows(self, ticker: str) -> bool:
        client = getattr(self.source, "_client", None)
        if client is None:
            return True
        try:
            await asyncio.to_thread(client.get_snapshot_ticker, "stocks", ticker)
            return True
        except Exception as exc:  # best effort: only a clear "not found" rejects
            text = str(exc).lower()
            return not ("404" in text or "not found" in text or "notfound" in text)


def normalize_ticker(ticker) -> str:
    if not isinstance(ticker, str) or not ticker.strip():
        raise ApiError("invalid_request", "ticker is required")
    t = ticker.strip().upper()
    if not TICKER_RE.match(t):
        raise ApiError("unknown_ticker", f"Unknown ticker {t}")
    return t


def validate_trade(ticker, side, quantity) -> tuple[str, str, float]:
    t = normalize_ticker(ticker)
    if side not in ("buy", "sell"):
        raise ApiError("invalid_request", "side must be 'buy' or 'sell'")
    if isinstance(quantity, bool) or not isinstance(quantity, int | float | str):
        raise ApiError("invalid_request", "quantity must be a number")
    try:
        dec = Decimal(str(quantity))
    except InvalidOperation:
        raise ApiError("invalid_request", "quantity must be a number") from None
    if not dec.is_finite() or dec <= 0:
        raise ApiError("invalid_request", "quantity must be greater than 0")
    if dec.as_tuple().exponent < -6:
        raise ApiError("invalid_request", "quantity may have at most 6 decimal places")
    return t, side, float(dec)
