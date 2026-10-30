# Market Data — Detailed Design

Implementation-ready design for the FinAlly market data subsystem: the unified interface, the shared price cache, the GBM simulator, the Massive (Polygon.io) client, the SSE stream, and how it plugs into the watchlist, portfolio and FastAPI lifecycle.

This document is aligned with the current `PLAN.md` (sections 6, 8, 10). It **supersedes** `planning/archive/MARKET_DATA_DESIGN.md` where they differ. Section 15 lists exactly what changes relative to the code currently in `backend/app/market/`.

All code lives under `backend/app/market/`.

---

## Table of Contents

1. [Requirements Recap](#1-requirements-recap)
2. [Architecture & File Layout](#2-architecture--file-layout)
3. [Data Model — `models.py`](#3-data-model--modelspy)
4. [Errors — `errors.py`](#4-errors--errorspy)
5. [Price Cache — `cache.py`](#5-price-cache--cachepy)
6. [Unified Interface — `interface.py`](#6-unified-interface--interfacepy)
7. [Seed Data — `seed_prices.py`](#7-seed-data--seed_pricespy)
8. [Simulator — `simulator.py`](#8-simulator--simulatorpy)
9. [Massive Client — `massive_client.py`](#9-massive-client--massive_clientpy)
10. [Factory — `factory.py`](#10-factory--factorypy)
11. [SSE Stream — `stream.py`](#11-sse-stream--streampy)
12. [Watchlist, Portfolio & Lifecycle Integration](#12-watchlist-portfolio--lifecycle-integration)
13. [Testing](#13-testing)
14. [Edge Cases & Configuration](#14-edge-cases--configuration)
15. [Delta vs. Existing Code](#15-delta-vs-existing-code)

---

## 1. Requirements Recap

From `PLAN.md`; every design choice below traces back to one of these.

| # | Requirement | Where handled |
|---|---|---|
| R1 | One interface, two implementations (simulator default, Massive if `MASSIVE_API_KEY` non-empty) | §6, §10 |
| R2 | Simulator: GBM, ~500 ms ticks, correlated sectors, 2–5% random events, realistic seeds, unseeded tickers start at random $50–$300 with default vol/drift | §7, §8 |
| R3 | Massive: REST polling, **one** multi-ticker snapshot call per poll, 15 s on free tier, rejects unknown tickers with `400 unknown_ticker` | §9 |
| R4 | Single in-memory cache holds latest price, previous price, timestamp, and `reference_price` | §5 |
| R5 | Tracked tickers == the watchlist. Removing a ticker **stops its streaming** even if a position is held; the position is valued at the **last cached (frozen) price**; re-adding resumes streaming | §5, §8, §9, §12 |
| R6 | Daily change % is relative to `reference_price` (simulator: seed price, fixed for the session; Massive: previous close) | §3, §8, §9 |
| R7 | `GET /api/stream/prices`: SSE, ~500 ms cadence, **one JSON object per `data:` line, one ticker per message**, ISO timestamp, `direction` of `up`/`down`/`flat` | §11 |
| R8 | Market closed → static prices are fine, no special UI | §9, §14 |

---

## 2. Architecture & File Layout

```
                 ┌──────────────────────────┐
                 │  MarketDataSource (ABC)  │
                 └────────────┬─────────────┘
              ┌───────────────┴────────────────┐
   ┌──────────▼──────────┐          ┌──────────▼──────────┐
   │ SimulatorDataSource │          │  MassiveDataSource  │
   │  (GBMSimulator)     │          │  (REST poller)      │
   └──────────┬──────────┘          └──────────┬──────────┘
              │ write                           │ write
              └───────────────┬─────────────────┘
                    ┌─────────▼─────────┐
                    │    PriceCache     │  keeps last price of every ticker ever seen
                    └───┬───────────┬───┘
                        │ read      │ read
        ┌───────────────▼──┐   ┌────▼──────────────────────┐
        │ SSE stream       │   │ Portfolio / trade / chat   │
        │ (tracked tickers │   │ (any cached ticker,        │
        │  only)           │   │  incl. frozen ones)        │
        └──────────────────┘   └────────────────────────────┘
```

Two sets matter and must not be confused:

- **Tracked set** (owned by the `MarketDataSource`): the watchlist. Only these tickers get fresh prices and are streamed over SSE.
- **Cached set** (owned by the `PriceCache`): every ticker that has ever received a price this session. A ticker removed from the watchlist leaves the tracked set but **stays in the cache**, so a held position can still be valued (R5).

```
backend/app/market/
  __init__.py        # public re-exports
  models.py          # PriceUpdate (frozen dataclass)
  errors.py          # UnknownTickerError, MarketDataUnavailableError
  cache.py           # PriceCache
  interface.py       # MarketDataSource ABC
  seed_prices.py     # SEED_PRICES, TICKER_PARAMS, DEFAULT_PARAMS, correlation constants
  simulator.py       # GBMSimulator (math) + SimulatorDataSource (async wrapper)
  massive_client.py  # parse_snapshot() + MassiveDataSource
  factory.py         # create_market_data_source()
  stream.py          # create_stream_router()
```

---

## 3. Data Model — `models.py`

`PriceUpdate` is the only price type that leaves the market layer.

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of one ticker's price."""

    ticker: str
    price: float
    previous_price: float        # price before this update (== price on first update)
    reference_price: float       # daily-change baseline: seed price / previous close
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    seq: int = 0                 # per-ticker update counter, used by SSE change detection

    @property
    def direction(self) -> str:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def change(self) -> float:
        """Absolute change since the previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def day_change_percent(self) -> float:
        """Daily change % versus reference_price."""
        if not self.reference_price:
            return 0.0
        return round((self.price - self.reference_price) / self.reference_price * 100, 4)

    @property
    def iso_timestamp(self) -> str:
        dt = datetime.fromtimestamp(self.timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def to_sse_dict(self) -> dict:
        """Exact shape of one SSE message (PLAN.md §6)."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "reference_price": self.reference_price,
            "timestamp": self.iso_timestamp,
            "direction": self.direction,
        }

    def to_dict(self) -> dict:
        """Superset for REST responses (watchlist, portfolio)."""
        return {**self.to_sse_dict(), "change": self.change,
                "day_change_percent": self.day_change_percent}
```

**Why `reference_price` lives on the update:** the frontend computes the watchlist's "daily change %" as `(price - reference_price) / reference_price` from each SSE message alone, with no extra REST call. `day_change_percent` is provided server-side for REST consumers (`GET /api/watchlist`, the chat portfolio context).

**Why `seq`:** `previous_price` and `direction` are *per-update*; the SSE loop needs a cheap way to ask "has this ticker changed since I last sent it?" without comparing floats. See §11.

---

## 4. Errors — `errors.py`

Domain exceptions the API layer maps onto the PLAN's error format (`{"error", "code"}`).

```python
class MarketDataError(Exception):
    """Base class."""


class UnknownTickerError(MarketDataError):
    """Ticker is not recognised by the data provider -> 400 unknown_ticker."""

    def __init__(self, ticker: str) -> None:
        super().__init__(f"Unknown ticker: {ticker}")
        self.ticker = ticker


class MarketDataUnavailableError(MarketDataError):
    """Provider unreachable / rate-limited while validating -> 500 internal_error."""
```

Mapping in the FastAPI exception handlers:

```python
@app.exception_handler(UnknownTickerError)
async def _unknown_ticker(_: Request, exc: UnknownTickerError):
    return JSONResponse(status_code=400,
                        content={"error": str(exc), "code": "unknown_ticker"})

@app.exception_handler(MarketDataUnavailableError)
async def _md_unavailable(_: Request, exc: MarketDataUnavailableError):
    return JSONResponse(status_code=500,
                        content={"error": "Market data is temporarily unavailable.",
                                 "code": "internal_error"})
```

---

## 5. Price Cache — `cache.py`

The cache is the hub: sources write, SSE and portfolio code read. It uses a `threading.Lock` because the Massive client runs blocking HTTP in `asyncio.to_thread`.

**Key rule (R5): the cache never evicts on watchlist removal.** There is deliberately no `remove()` in the public flow; frozen prices are what values orphaned positions.

```python
from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe latest-price store."""

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        reference_price: float | None = None,
    ) -> PriceUpdate:
        """Record a new price.

        - First update for a ticker: previous_price == price (direction "flat").
        - reference_price: if given, (re)sets the daily baseline. If omitted, the
          existing baseline is kept; if there is none, the first price is used.
        """
        with self._lock:
            prev = self._prices.get(ticker)
            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=prev.price if prev else round(price, 2),
                reference_price=round(
                    reference_price if reference_price is not None
                    else (prev.reference_price if prev else price),
                    2,
                ),
                timestamp=timestamp if timestamp is not None else time.time(),
                seq=(prev.seq + 1) if prev else 1,
            )
            self._prices[ticker] = update
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        u = self.get(ticker)
        return u.price if u else None

    def get_many(self, tickers: list[str]) -> list[PriceUpdate]:
        """Updates for the given tickers that have a price, in the given order."""
        with self._lock:
            return [self._prices[t] for t in tickers if t in self._prices]

    def get_all(self) -> dict[str, PriceUpdate]:
        with self._lock:
            return dict(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)
```

Notes:

- Rounding to 2 decimals happens here once, so every consumer sees identical numbers (SSE, trades, portfolio).
- `PriceUpdate` is frozen, so returning the stored object (not a copy) is safe.
- The old global `version` counter is gone; per-ticker `seq` replaces it (§11).

---

## 6. Unified Interface — `interface.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Contract for price providers. Providers push into a PriceCache.

    Tracked set == the watchlist. Lifecycle:
        source = create_market_data_source(cache)
        await source.start(watchlist_tickers)
        await source.add_ticker("PYPL")      # may raise UnknownTickerError
        await source.remove_ticker("PYPL")   # stops updates; cache keeps last price
        await source.stop()
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing prices for `tickers`. Call once.

        Postcondition: every ticker that the provider recognises has a price in
        the cache when this returns (so SSE has data on the first tick).
        Startup is lenient: unrecognised tickers are logged and skipped, never raised.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Cancel background work. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking `ticker` (already normalised to uppercase).

        Raises UnknownTickerError if the provider rejects it; in that case the
        tracked set is unchanged. No-op if already tracked.
        Postcondition: the cache holds a price for `ticker`, so a trade can
        be placed immediately after the call returns.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking `ticker`. No-op if not tracked.

        MUST NOT delete the ticker from the cache: a held position is valued
        at the last cached (frozen) price.
        """

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Currently tracked tickers, in insertion order."""
```

Behavioural contract shared by both implementations (and asserted by a parametrised test, §13.6):

| Operation | Simulator | Massive |
|---|---|---|
| `start([...])` | seeds cache immediately, starts 500 ms loop | one snapshot call, seeds cache, starts 15 s loop |
| `add_ticker("X")` | always succeeds; seeds cache instantly | validates with a one-ticker snapshot; `UnknownTickerError` if empty; seeds cache from that response |
| `remove_ticker("X")` | leaves tracked set; cache price frozen | leaves tracked set (excluded from next poll); cache price frozen |
| re-`add_ticker("X")` | resumes from the frozen price (§8.3) | validated again; refreshed immediately |

---

## 7. Seed Data — `seed_prices.py`

Constants only.

```python
"""Seed prices and parameters for the simulator."""

SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00, "GOOGL": 175.00, "MSFT": 420.00, "AMZN": 185.00,
    "TSLA": 250.00, "NVDA": 800.00, "META": 500.00, "JPM": 195.00,
    "V": 280.00, "NFLX": 600.00,
}

# sigma = annualised volatility, mu = annualised drift
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT":  {"sigma": 0.20, "mu": 0.05},
    "AMZN":  {"sigma": 0.28, "mu": 0.05},
    "TSLA":  {"sigma": 0.50, "mu": 0.03},
    "NVDA":  {"sigma": 0.40, "mu": 0.08},
    "META":  {"sigma": 0.30, "mu": 0.05},
    "JPM":   {"sigma": 0.18, "mu": 0.04},
    "V":     {"sigma": 0.17, "mu": 0.04},
    "NFLX":  {"sigma": 0.35, "mu": 0.05},
}
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Unseeded tickers (e.g. a user-added PYPL) start uniformly in this range
UNSEEDED_PRICE_RANGE = (50.0, 300.0)

CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech": {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}
INTRA_TECH_CORR = 0.6
INTRA_FINANCE_CORR = 0.5
CROSS_GROUP_CORR = 0.3      # between sectors, and for any unknown ticker
TSLA_CORR = 0.3             # TSLA "does its own thing"
```

(`DEFAULT_CORR` from the old file is dropped; it duplicated `CROSS_GROUP_CORR`.)

---

## 8. Simulator — `simulator.py`

Two classes: `GBMSimulator` (pure, synchronous math, trivially unit-testable) and `SimulatorDataSource` (async wrapper implementing the interface).

### 8.1 The math

Per tick, for each ticker `i`:

```
S_i(t+dt) = S_i(t) · exp( (mu_i − σ_i²/2)·dt + σ_i·√dt·Z_i )
```

- `dt = 0.5 s / (252 · 6.5 · 3600 s)` ≈ 8.48e‑8 of a trading year.
- `Z = L · ε`, where `ε ~ N(0, I)` and `L = cholesky(C)` for correlation matrix `C` → correlated shocks.
- With probability `event_probability` (0.001) per ticker per tick, apply an extra ±(2–5)% jump.

Sanity check: TSLA σ = 0.5 → per‑tick stdev = 0.5·√8.48e‑8 ≈ 0.0146% ≈ 3.6¢ on $250. Over a simulated trading day (46,800 ticks) the stdev of the log-return is ≈ 0.5·√(46800·8.48e‑8) ≈ 3.15%. Plausible intraday range, and visibly alive on a 500 ms screen.

### 8.2 `GBMSimulator`

```python
from __future__ import annotations

import asyncio
import logging
import math
import random
import time

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .seed_prices import (
    CORRELATION_GROUPS, CROSS_GROUP_CORR, DEFAULT_PARAMS, INTRA_FINANCE_CORR,
    INTRA_TECH_CORR, SEED_PRICES, TICKER_PARAMS, TSLA_CORR, UNSEEDED_PRICE_RANGE,
)

logger = logging.getLogger(__name__)


class GBMSimulator:
    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
        rng: np.random.Generator | None = None,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        self._rng = rng or np.random.default_rng()
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None
        for t in tickers:
            self._insert(t, None)
        self._rebuild_cholesky()

    # ---- public ----

    def step(self) -> dict[str, float]:
        """Advance one tick. Returns {ticker: new_price} (unrounded floats kept internally)."""
        n = len(self._tickers)
        if n == 0:
            return {}
        z = self._rng.standard_normal(n)
        if self._cholesky is not None:
            z = self._cholesky @ z

        out: dict[str, float] = {}
        sqrt_dt = math.sqrt(self._dt)
        for i, t in enumerate(self._tickers):
            p = self._params[t]
            drift = (p["mu"] - 0.5 * p["sigma"] ** 2) * self._dt
            self._prices[t] *= math.exp(drift + p["sigma"] * sqrt_dt * z[i])
            if random.random() < self._event_prob:
                shock = random.uniform(0.02, 0.05) * random.choice((-1, 1))
                self._prices[t] *= 1 + shock
                logger.debug("shock %s %+.1f%%", t, shock * 100)
            out[t] = round(self._prices[t], 2)
        return out

    def add_ticker(self, ticker: str, start_price: float | None = None) -> float:
        """Add (or no-op) and return the ticker's current price.

        `start_price` lets the data source resume a frozen ticker from its last
        cached price instead of the seed.
        """
        if ticker not in self._prices:
            self._insert(ticker, start_price)
            self._rebuild_cholesky()
        return self._prices[ticker]

    def remove_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker], self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # ---- internals ----

    def _insert(self, ticker: str, start_price: float | None) -> None:
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = (
            start_price
            if start_price is not None
            else SEED_PRICES.get(ticker, random.uniform(*UNSEEDED_PRICE_RANGE))
        )
        self._params[ticker] = TICKER_PARAMS.get(ticker, DEFAULT_PARAMS)

    def _rebuild_cholesky(self) -> None:
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                corr[i, j] = corr[j, i] = self._pairwise(self._tickers[i], self._tickers[j])
        try:
            self._cholesky = np.linalg.cholesky(corr)
        except np.linalg.LinAlgError:           # not positive-definite: degrade to independent
            logger.warning("Correlation matrix not PD; using independent moves")
            self._cholesky = None

    @staticmethod
    def _pairwise(a: str, b: str) -> float:
        if "TSLA" in (a, b):
            return TSLA_CORR
        tech, fin = CORRELATION_GROUPS["tech"], CORRELATION_GROUPS["finance"]
        if a in tech and b in tech:
            return INTRA_TECH_CORR
        if a in fin and b in fin:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR
```

### 8.3 `SimulatorDataSource`

Responsibilities beyond the math: write to the cache, own the 500 ms loop, apply the **reference price** and **frozen-resume** rules.

- **Reference price** = the ticker's *initial* price this session (seed, or the random start for unseeded tickers). It is set once on first sight and never changes until backend restart (R6). Because the cache keeps the existing baseline when `reference_price` is omitted, only the first write passes it.
- **Resume after removal:** the simulator drops the ticker (so it no longer burns CPU / affects correlations), but the cache keeps the frozen price. On re-add we restart the walk from that cached price, so the user sees continuity rather than a jump back to the seed. The cached baseline is also retained.

```python
class SimulatorDataSource(MarketDataSource):
    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers, event_probability=self._event_prob)
        for t in self._sim.get_tickers():
            self._seed_cache(t)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def add_ticker(self, ticker: str) -> None:
        # Simulator accepts any symbol: it never raises UnknownTickerError.
        # (Syntactic validation is the API layer's job; see §12.1.)
        assert self._sim is not None, "start() first"
        if ticker in self._sim.get_tickers():
            return
        frozen = self._cache.get(ticker)                 # resume from frozen price, if any
        self._sim.add_ticker(ticker, start_price=frozen.price if frozen else None)
        self._seed_cache(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)              # cache untouched (frozen)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    # ---- internals ----

    def _seed_cache(self, ticker: str) -> None:
        price = self._sim.get_price(ticker)
        existing = self._cache.get(ticker)
        if existing is None:
            self._cache.update(ticker, price, reference_price=price)   # new: baseline = start
        else:
            self._cache.update(ticker, price)                          # resume: keep baseline

    async def _run_loop(self) -> None:
        next_tick = time.monotonic()
        while True:
            try:
                for ticker, price in self._sim.step().items():
                    self._cache.update(ticker, price)
            except Exception:
                logger.exception("Simulator step failed")
            next_tick += self._interval                  # drift-free cadence
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))
```

Concurrency note: `step()` and `add_ticker`/`remove_ticker` all run on the event loop thread and never `await` in the middle of mutation, so the simulator's dicts need no lock.

---

## 9. Massive Client — `massive_client.py`

### 9.1 API facts used

- Package `massive` (formerly `polygon-api-client`); `RESTClient(api_key=...)` is **synchronous** → always called through `asyncio.to_thread`.
- Endpoint: `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=A,B,C` via `client.get_snapshot_all(SnapshotMarketType.STOCKS, tickers=[...])`. One call regardless of ticker count.
- Free tier: 5 calls/min → poll every **15 s** (4 calls/min), leaving 1 call/min of headroom for ticker validation on add (§9.4).
- Per-snapshot fields we use: `last_trade.price`, `last_trade.timestamp`, `prev_day.close` (previous close → `reference_price`). Fallbacks listed in `parse_snapshot`.
- **Unknown tickers are simply absent** from the snapshot response (no error). That is how `add_ticker` detects them.
- Closed market: `last_trade` is the last traded price; it will not change. Fine (R8).

> The exact attribute for previous close differs between the REST JSON (`prevDay.c`) and the client model (`prev_day.close`); older docs also mention `day.previous_close`. `parse_snapshot` tries them in order and is covered by tests using realistic fixtures, so a client-library rename shows up as a failing test rather than silent bad data.

### 9.2 Pure parsing — `parse_snapshot`

Isolating parsing from I/O makes it testable without the network or the `massive` package.

```python
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .errors import MarketDataUnavailableError, UnknownTickerError
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Quote:
    ticker: str
    price: float
    timestamp: float            # Unix seconds
    reference_price: float | None


def _first(obj: Any, *paths: str) -> Any:
    """Return the first non-None attribute along dotted paths; None if all missing."""
    for path in paths:
        cur = obj
        for part in path.split("."):
            cur = getattr(cur, part, None)
            if cur is None:
                break
        if cur is not None:
            return cur
    return None


def _to_seconds(ts: float | int | None) -> float:
    """Massive timestamps vary by field: ms (1.7e12) or ns (1.7e18). Normalise to seconds."""
    if not ts:
        return time.time()
    if ts > 1e17:       # nanoseconds
        return ts / 1e9
    if ts > 1e11:       # milliseconds
        return ts / 1e3
    return float(ts)    # already seconds


def parse_snapshot(snap: Any) -> Quote | None:
    """Convert one Massive snapshot to a Quote, or None if it has no usable price."""
    ticker = getattr(snap, "ticker", None)
    price = _first(snap, "last_trade.price", "min.close", "day.close")
    if not ticker or not price or price <= 0:
        return None
    ts = _first(snap, "last_trade.timestamp", "last_trade.sip_timestamp")
    ref = _first(snap, "prev_day.close", "day.previous_close")
    return Quote(
        ticker=ticker,
        price=float(price),
        timestamp=_to_seconds(ts),
        reference_price=float(ref) if ref else None,
    )
```

### 9.3 `MassiveDataSource`

Design points:

- **`_tickers` is the tracked set**; each poll requests exactly that set (R3).
- **Single in-flight call:** an `asyncio.Lock` serialises poll and validation calls so they cannot overlap and burst past 5/min.
- **Backoff:** on any failure the delay doubles (cap 120 s) and resets on success. This protects the free tier after a `429`.
- **Fatal vs transient:** `401/403` are logged loudly each time but we keep polling (the user may rotate the key and restart; cheaper than adding a crash path). Cache keeps last-known prices; SSE keeps serving them.
- **Stale reference price:** if a snapshot lacks a previous close, we keep the cached baseline, else fall back to the first price (daily change reads 0%).

```python
class MassiveDataSource(MarketDataSource):
    MAX_BACKOFF = 120.0

    def __init__(self, api_key: str, price_cache: PriceCache, poll_interval: float = 15.0) -> None:
        self._client = RESTClient(api_key=api_key)
        self._cache = price_cache
        self._base_interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._call_lock = asyncio.Lock()

    # ---- interface ----

    async def start(self, tickers: list[str]) -> None:
        self._tickers = list(dict.fromkeys(tickers))
        await self._poll_once()                       # lenient: errors are logged, not raised
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info("Massive poller started: %d tickers, %.0fs", len(self._tickers), self._base_interval)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        try:
            quotes = await self._fetch([ticker])
        except Exception as e:
            raise MarketDataUnavailableError(str(e)) from e
        quote = next((q for q in quotes if q.ticker == ticker), None)
        if quote is None:
            raise UnknownTickerError(ticker)          # absent from snapshot => not a real ticker
        self._apply(quote)                            # seed cache so a trade can follow at once
        self._tickers.append(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers = [t for t in self._tickers if t != ticker]   # cache untouched (frozen)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # ---- internals ----

    async def _poll_loop(self) -> None:
        delay = self._base_interval
        while True:
            await asyncio.sleep(delay)
            ok = await self._poll_once()
            delay = self._base_interval if ok else min(delay * 2, self.MAX_BACKOFF)

    async def _poll_once(self) -> bool:
        """One poll cycle. Returns False on a transport/API failure (drives backoff)."""
        tickers = list(self._tickers)
        if not tickers:
            return True
        try:
            quotes = await self._fetch(tickers)
        except Exception as e:                        # 401/403/429/5xx/network
            logger.error("Massive poll failed: %s", e)
            return False
        for q in quotes:
            self._apply(q)
        missing = set(tickers) - {q.ticker for q in quotes}
        if missing:
            logger.warning("Massive returned no data for: %s", ", ".join(sorted(missing)))
        return True

    def _apply(self, q: Quote) -> None:
        self._cache.update(q.ticker, q.price, timestamp=q.timestamp,
                           reference_price=q.reference_price)

    async def _fetch(self, tickers: list[str]) -> list[Quote]:
        async with self._call_lock:
            snaps = await asyncio.to_thread(self._fetch_sync, tickers)
        quotes = []
        for snap in snaps:
            q = parse_snapshot(snap)
            if q is None:
                logger.warning("Skipping unusable snapshot: %r", getattr(snap, "ticker", "?"))
                continue
            quotes.append(q)
        return quotes

    def _fetch_sync(self, tickers: list[str]) -> list:
        return list(self._client.get_snapshot_all(SnapshotMarketType.STOCKS, tickers=tickers))
```

### 9.4 Rate-limit budget

| Event | Calls | Notes |
|---|---|---|
| Steady state, 15 s poll | 4 / min | independent of watchlist size |
| User adds a ticker | +1 | immediate validation call; seeds cache |
| Adds more than 1 / min on the free tier | may `429` → `MarketDataUnavailableError` → `500 internal_error` | acceptable; paid tiers have no such limit. The poller's backoff absorbs the knock-on. |

Paid tiers: set `MASSIVE_POLL_INTERVAL` (see §14) to 2–5 s.

---

## 10. Factory — `factory.py`

```python
from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """MASSIVE_API_KEY set and non-empty -> Massive; otherwise the simulator."""
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        from .massive_client import MassiveDataSource    # keep `massive` import off the sim path

        interval = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15"))
        logger.info("Market data: Massive API (poll %.0fs)", interval)
        return MassiveDataSource(api_key=api_key, price_cache=price_cache, poll_interval=interval)

    from .simulator import SimulatorDataSource

    logger.info("Market data: GBM simulator")
    return SimulatorDataSource(price_cache=price_cache)
```

The factory returns an **unstarted** source. Selection happens once at startup; there is no runtime switching.

---

## 11. SSE Stream — `stream.py`

### 11.1 Wire format (R7)

One ticker per message, one `data:` line each:

```
retry: 1000

data: {"ticker":"AAPL","price":190.42,"previous_price":190.31,"reference_price":189.0,"timestamp":"2025-01-01T12:00:00.123Z","direction":"up"}

data: {"ticker":"GOOGL","price":175.12,"previous_price":175.12,"reference_price":175.0,"timestamp":"2025-01-01T12:00:00.123Z","direction":"flat"}

```

Frontend:

```ts
const es = new EventSource("/api/stream/prices");
es.onopen = () => setStatus("connected");
es.onerror = () => setStatus(es.readyState === EventSource.CONNECTING ? "reconnecting" : "disconnected");
es.onmessage = (e) => onTick(JSON.parse(e.data) as PriceTick);   // one ticker per message
```

### 11.2 Behaviour

- **On connect**, emit the current price of every *tracked* ticker (so new clients paint immediately, even on a closed market where nothing ever changes).
- **Then, every ~500 ms**, emit only tickers whose `seq` changed since this client's last send. Massive therefore produces a burst every 15 s and silence between; the simulator produces ~10 messages per 500 ms.
- **Tracked only:** the loop iterates `source.get_tickers()`, not the cache. A removed ticker simply stops appearing (R5). Its frozen price remains available to REST/portfolio code.
- **Re-added ticker:** its `seq` advances, so it resumes flowing. A client that saw it before removal and sees it again will get an update because `seq` differs from the remembered value.
- **State is per connection** (`last_sent: dict[str, int]`); no shared mutable state between clients.
- **Heartbeat:** a `: keepalive` comment every 15 s keeps proxies from closing an idle (Massive, closed market) connection.
- The router is built inside the factory function, so calling it twice (tests) never double-registers the route.

```python
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

PUSH_INTERVAL = 0.5
KEEPALIVE_INTERVAL = 15.0


def create_stream_router(cache: PriceCache, source: MarketDataSource) -> APIRouter:
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            price_events(cache, source, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                     "X-Accel-Buffering": "no"},
        )

    return router


async def price_events(
    cache: PriceCache,
    source: MarketDataSource,
    request: Request,
    interval: float = PUSH_INTERVAL,
) -> AsyncGenerator[str, None]:
    yield "retry: 1000\n\n"
    last_sent: dict[str, int] = {}
    last_write = time.monotonic()
    try:
        while True:
            if await request.is_disconnected():
                break
            sent_any = False
            for update in cache.get_many(source.get_tickers()):
                if last_sent.get(update.ticker) != update.seq:
                    last_sent[update.ticker] = update.seq
                    yield f"data: {json.dumps(update.to_sse_dict(), separators=(',', ':'))}\n\n"
                    sent_any = True
            now = time.monotonic()
            if sent_any:
                last_write = now
            elif now - last_write >= KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_write = now
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("SSE client gone")
```

Testing note: `price_events` takes a plain `request`-like object (anything with `async is_disconnected()`), so it can be driven in unit tests without a server (§13.5).

---

## 12. Watchlist, Portfolio & Lifecycle Integration

### 12.1 Ticker normalisation & validation (API layer)

Done once, before touching the data source:

```python
import re

TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")      # AAPL, BRK.B

def normalise_ticker(raw: str) -> str:
    t = raw.strip().upper()
    if not TICKER_RE.match(t):
        raise ApiError(400, "invalid_request", f"Invalid ticker: {raw!r}")
    return t
```

A syntactically valid but nonexistent symbol is: accepted by the simulator (random start price), rejected by Massive with `unknown_ticker`.

### 12.2 Watchlist flows

**Add** — `POST /api/watchlist {ticker}`

```python
@router.post("/watchlist", status_code=201)
async def add_watchlist(body: WatchlistAdd, db=Depends(get_db),
                        source: MarketDataSource = Depends(get_source),
                        cache: PriceCache = Depends(get_cache)):
    ticker = normalise_ticker(body.ticker)
    if db.watchlist_contains(ticker):
        raise ApiError(409, "already_exists", f"{ticker} is already on the watchlist")
    await source.add_ticker(ticker)          # may raise UnknownTickerError -> 400; DB untouched
    db.watchlist_insert(ticker)              # only after the provider accepted it
    update = cache.get(ticker)
    return {"ticker": ticker, "price": update.to_dict() if update else None}
```

Order matters: **provider first, DB second**, so a rejected ticker never reaches the watchlist table. If the DB insert then fails, call `await source.remove_ticker(ticker)` in the `except` to keep the sets consistent.

**Remove** — `DELETE /api/watchlist/{ticker}[?confirm=true]`

```python
@router.delete("/watchlist/{ticker}")
async def remove_watchlist(ticker: str, confirm: bool = False, db=Depends(get_db),
                           source: MarketDataSource = Depends(get_source)):
    ticker = normalise_ticker(ticker)
    if not db.watchlist_contains(ticker):
        raise ApiError(404, "not_found", f"{ticker} is not on the watchlist")
    if db.get_position(ticker) and not confirm:
        raise ApiError(409, "position_open",
                       f"You hold {ticker}. Removing it stops its price updating.")
    db.watchlist_delete(ticker)
    await source.remove_ticker(ticker)       # stops streaming; cache keeps frozen price
    return {"status": "ok"}
```

This **reverses** the archived design, which kept a held ticker in the data source. The PLAN now says removal always stops streaming (R5).

The LLM chat flow calls the same two functions (`confirmed` maps to `confirm`), so behaviour and error codes are identical.

### 12.3 Valuing positions (frozen prices)

All portfolio code reads `cache.get_price(ticker)`, never the source, so tracked and frozen tickers are handled identically:

```python
def position_value(pos, cache: PriceCache) -> float:
    price = cache.get_price(pos.ticker)
    if price is None:                        # defensive: never seen a price this session
        price = pos.avg_cost
    return pos.quantity * price
```

Restart caveat: the cache is in-memory, so after a backend restart a held-but-unwatched ticker has no price. `lifespan` handles this (§12.5) by starting the source with **watchlist ∪ held tickers**, then immediately calling `remove_ticker` for the held-only ones so they are priced once and frozen — a single seed price (simulator: the seed; Massive: one snapshot) rather than streaming.

### 12.4 Trade execution

```python
def price_for_trade(ticker: str, cache: PriceCache) -> float:
    price = cache.get_price(ticker)
    if price is None:
        raise ApiError(400, "unknown_ticker", f"No price available for {ticker}")
    return price
```

A trade on a frozen (unwatched) ticker is allowed by the cache but is **rejected by the portfolio layer**: buys/sells require the ticker to be currently tracked (`ticker in source.get_tickers()`), otherwise the user would transact at a stale price. Selling an orphaned position therefore requires re-adding it to the watchlist first. (If product prefers to allow selling frozen positions, drop that check — nothing in the market layer depends on it.)

Because `add_ticker` guarantees a seeded cache on return, there is no "price not yet available" window for new tickers.

### 12.5 Application lifecycle

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.market import PriceCache, create_market_data_source, create_stream_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = PriceCache()
    source = create_market_data_source(cache)
    app.state.price_cache, app.state.market_source = cache, source

    watchlist = db.list_watchlist_tickers()
    held_only = [t for t in db.list_position_tickers() if t not in watchlist]

    await source.start(watchlist + held_only)
    for t in held_only:                      # price once, then freeze (see §12.3)
        await source.remove_ticker(t)

    app.include_router(create_stream_router(cache, source))
    yield
    await source.stop()


def get_cache(request: Request) -> PriceCache: return request.app.state.price_cache
def get_source(request: Request) -> MarketDataSource: return request.app.state.market_source
```

Startup is **lenient**: a watchlist ticker that Massive no longer recognises is logged and skipped (it is simply absent from the cache) rather than preventing boot.

Route ordering: `include_router` for `/api/*` must happen before mounting the static-files catch-all at `/`.

The 30-second portfolio snapshot task and `GET /api/portfolio` also read from `cache` only.

---

## 13. Testing

Put tests in `backend/tests/market/`. `asyncio_mode = "auto"` is already configured.

### 13.1 Models

```python
def test_direction_and_day_change():
    u = PriceUpdate("AAPL", price=191.0, previous_price=190.0, reference_price=185.0, timestamp=0)
    assert u.direction == "up"
    assert u.change == 1.0
    assert u.day_change_percent == pytest.approx(3.2432, abs=1e-3)

def test_sse_dict_shape_matches_plan():
    d = PriceUpdate("AAPL", 190.42, 190.31, 189.0, timestamp=1735732800.123).to_sse_dict()
    assert set(d) == {"ticker", "price", "previous_price", "reference_price", "timestamp", "direction"}
    assert d["timestamp"] == "2025-01-01T12:00:00.123Z"
```

### 13.2 Cache

```python
def test_first_update_is_flat_and_baseline_is_first_price():
    c = PriceCache()
    u = c.update("AAPL", 190.0)
    assert (u.direction, u.previous_price, u.reference_price, u.seq) == ("flat", 190.0, 190.0, 1)

def test_reference_price_sticks_until_overridden():
    c = PriceCache()
    c.update("AAPL", 190.0, reference_price=185.0)
    assert c.update("AAPL", 191.0).reference_price == 185.0
    assert c.update("AAPL", 191.0, reference_price=190.5).reference_price == 190.5

def test_cache_has_no_eviction_api():          # frozen-price guarantee (R5)
    assert not hasattr(PriceCache(), "remove")

def test_seq_increments_per_ticker():
    c = PriceCache(); c.update("A", 1); c.update("B", 1)
    assert c.update("A", 2).seq == 2 and c.get("B").seq == 1

def test_thread_safety():
    c = PriceCache()
    def work():
        for i in range(2000): c.update("AAPL", 100 + i % 5)
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert c.get("AAPL").seq == 16000
```

### 13.3 Simulator

```python
def test_default_watchlist_cholesky_is_valid():
    sim = GBMSimulator(list(SEED_PRICES))
    assert sim._cholesky is not None
    assert sim._cholesky.shape == (10, 10)

def test_prices_positive_over_many_steps():
    sim = GBMSimulator(["TSLA"], event_probability=0.01)
    assert all(sim.step()["TSLA"] > 0 for _ in range(20_000))

def test_gbm_log_return_statistics():
    """Without events, per-tick log-return stdev ~= sigma*sqrt(dt)."""
    sim = GBMSimulator(["AAPL"], event_probability=0.0, rng=np.random.default_rng(0))
    prev, rets = sim.get_price("AAPL"), []
    for _ in range(20_000):
        p = sim._prices["AAPL"]; sim.step(); rets.append(math.log(sim._prices["AAPL"] / p))
    expected = 0.22 * math.sqrt(GBMSimulator.DEFAULT_DT)
    assert np.std(rets) == pytest.approx(expected, rel=0.05)

def test_tech_pair_more_correlated_than_cross_sector():
    sim = GBMSimulator(["AAPL", "MSFT", "JPM"], event_probability=0.0, rng=np.random.default_rng(1))
    series = {t: [] for t in sim.get_tickers()}
    for _ in range(10_000):
        before = dict(sim._prices); sim.step()
        for t in series: series[t].append(math.log(sim._prices[t] / before[t]))
    corr = np.corrcoef([series["AAPL"], series["MSFT"], series["JPM"]])
    assert corr[0, 1] > corr[0, 2]

def test_unseeded_ticker_in_range_and_default_params():
    sim = GBMSimulator(["PYPL"])
    assert 50 <= sim.get_price("PYPL") <= 300
    assert sim._params["PYPL"] == DEFAULT_PARAMS

def test_events_occur_with_high_probability():
    sim = GBMSimulator(["AAPL"], event_probability=1.0)
    p0 = sim.get_price("AAPL"); sim.step()
    assert abs(sim.get_price("AAPL") / p0 - 1) >= 0.019      # 2-5% shock
```

### 13.4 SimulatorDataSource

```python
async def test_start_seeds_cache_and_reference():
    cache = PriceCache(); src = SimulatorDataSource(cache, update_interval=0.05)
    await src.start(["AAPL"])
    u = cache.get("AAPL")
    assert u.price == 190.0 and u.reference_price == 190.0
    await src.stop()

async def test_reference_price_fixed_while_price_moves():
    cache = PriceCache(); src = SimulatorDataSource(cache, update_interval=0.01, event_probability=0.5)
    await src.start(["AAPL"]); await asyncio.sleep(0.2)
    u = cache.get("AAPL")
    assert u.reference_price == 190.0 and u.price != 190.0
    await src.stop()

async def test_remove_freezes_price_and_readd_resumes():
    cache = PriceCache(); src = SimulatorDataSource(cache, update_interval=0.01, event_probability=0.5)
    await src.start(["AAPL", "MSFT"]); await asyncio.sleep(0.1)
    await src.remove_ticker("AAPL")
    frozen = cache.get("AAPL"); await asyncio.sleep(0.1)
    assert cache.get("AAPL") == frozen                    # no more updates
    assert "AAPL" not in src.get_tickers()
    await src.add_ticker("AAPL")
    assert cache.get("AAPL").price == frozen.price        # resumed, not reset to seed
    assert cache.get("AAPL").reference_price == 190.0     # baseline preserved
    await src.stop()
```

### 13.5 Massive (no network, no real client)

```python
def _snap(ticker, price, ts_ms, prev_close):
    return SimpleNamespace(
        ticker=ticker,
        last_trade=SimpleNamespace(price=price, timestamp=ts_ms),
        prev_day=SimpleNamespace(close=prev_close),
    )

def test_parse_snapshot_happy_path():
    q = parse_snapshot(_snap("AAPL", 125.07, 1_675_190_399_000, 129.61))
    assert (q.ticker, q.price, q.reference_price) == ("AAPL", 125.07, 129.61)
    assert q.timestamp == pytest.approx(1_675_190_399.0)

@pytest.mark.parametrize("ts,expected", [(1_675_190_399_000, 1_675_190_399.0),
                                         (1_675_190_399_000_000_000, 1_675_190_399.0),
                                         (1_675_190_399, 1_675_190_399.0)])
def test_timestamp_units(ts, expected):
    assert _to_seconds(ts) == pytest.approx(expected)

def test_parse_snapshot_bad_data_returns_none():
    assert parse_snapshot(SimpleNamespace(ticker="X", last_trade=None, min=None, day=None)) is None

@pytest.fixture
def source(monkeypatch):
    cache = PriceCache()
    monkeypatch.setattr("app.market.massive_client.RESTClient", lambda api_key: MagicMock())
    return MassiveDataSource("key", cache, poll_interval=60), cache

async def test_poll_updates_cache_with_one_call(source):
    src, cache = source
    src._tickers = ["AAPL", "GOOGL"]
    src._client.get_snapshot_all.return_value = [
        _snap("AAPL", 190.5, 1_707_580_800_000, 189.0), _snap("GOOGL", 175.25, 1_707_580_800_000, 176.0)]
    assert await src._poll_once() is True
    assert src._client.get_snapshot_all.call_count == 1          # single multi-ticker call
    assert cache.get("AAPL").reference_price == 189.0

async def test_add_unknown_ticker_raises_and_does_not_track(source):
    src, cache = source
    src._client.get_snapshot_all.return_value = []               # absent => unknown
    with pytest.raises(UnknownTickerError):
        await src.add_ticker("ZZZZ")
    assert "ZZZZ" not in src.get_tickers() and cache.get("ZZZZ") is None

async def test_add_valid_ticker_seeds_cache(source):
    src, cache = source
    src._client.get_snapshot_all.return_value = [_snap("PYPL", 70.0, 1_707_580_800_000, 69.0)]
    await src.add_ticker("PYPL")
    assert cache.get_price("PYPL") == 70.0 and "PYPL" in src.get_tickers()

async def test_poll_failure_is_swallowed_and_cache_kept(source):
    src, cache = source
    src._tickers = ["AAPL"]; cache.update("AAPL", 190.0)
    src._client.get_snapshot_all.side_effect = RuntimeError("429")
    assert await src._poll_once() is False
    assert cache.get_price("AAPL") == 190.0

async def test_remove_keeps_frozen_price(source):
    src, cache = source
    src._tickers = ["AAPL"]; cache.update("AAPL", 190.0)
    await src.remove_ticker("AAPL")
    assert src.get_tickers() == [] and cache.get_price("AAPL") == 190.0
```

### 13.6 Interface conformance (both implementations)

```python
@pytest.fixture(params=["sim", "massive"])
def make_source(request, monkeypatch): ...      # returns (source, cache); massive uses a stub client

async def test_conformance_remove_never_evicts_cache(make_source):
    src, cache = make_source
    await src.start(["AAPL"]); await src.remove_ticker("AAPL")
    assert cache.get("AAPL") is not None
    await src.stop()

async def test_conformance_stop_is_idempotent(make_source):
    src, _ = make_source
    await src.start(["AAPL"]); await src.stop(); await src.stop()
```

### 13.7 SSE

```python
class FakeRequest:
    def __init__(self, disconnect_after: int): self._n = disconnect_after
    async def is_disconnected(self):
        self._n -= 1; return self._n < 0

async def collect(gen): return [chunk async for chunk in gen]

async def test_stream_sends_initial_snapshot_one_ticker_per_message():
    cache, src = PriceCache(), StubSource(["AAPL", "MSFT"])
    cache.update("AAPL", 190.0); cache.update("MSFT", 420.0)
    out = await collect(price_events(cache, src, FakeRequest(1), interval=0))
    msgs = [json.loads(c[6:]) for c in out if c.startswith("data: ")]
    assert {m["ticker"] for m in msgs} == {"AAPL", "MSFT"}

async def test_stream_only_resends_changed_tickers():
    cache, src = PriceCache(), StubSource(["AAPL", "MSFT"])
    cache.update("AAPL", 190.0); cache.update("MSFT", 420.0)
    out = await collect(price_events(cache, src, FakeRequest(2), interval=0))
    assert sum(c.startswith("data: ") for c in out) == 2           # nothing changed on pass 2

async def test_stream_skips_untracked_tickers():
    cache = PriceCache(); cache.update("AAPL", 190.0); cache.update("TSLA", 250.0)
    out = await collect(price_events(cache, StubSource(["AAPL"]), FakeRequest(1), interval=0))
    assert all("TSLA" not in c for c in out)                         # frozen ticker not streamed
```

### 13.8 API-level (with the DB layer)

- `POST /api/watchlist` with a Massive stub returning no snapshot → `400 {"code":"unknown_ticker"}` and no DB row.
- `DELETE /api/watchlist/AAPL` while holding AAPL → `409 position_open`; with `?confirm=true` → 200, and `GET /api/portfolio` still values the position at the frozen price after several seconds.
- Re-add → price resumes changing in SSE.

---

## 14. Edge Cases & Configuration

| Case | Behaviour |
|---|---|
| Empty watchlist at startup | Both sources start idle; SSE sends only keepalives; adding a ticker works immediately. |
| Removing a held ticker | Allowed only with confirmation (API); then streaming stops, cache keeps frozen price, heatmap/table/total use it. |
| Re-adding a removed ticker | Simulator resumes from frozen price; Massive refreshes via validation call. SSE resumes (new `seq`). |
| Massive: market closed | Prices static; poll still runs; SSE sends initial snapshot per connection, then keepalives. No UI indicator. |
| Massive: bad API key (401/403) | Logged each poll with backoff; cache empty; watchlist shows no prices; add-ticker → `500 internal_error`. Fix `.env`, restart. |
| Massive: 429 | Poll backs off 15→30→60→120 s, resets on success; cache keeps last prices. |
| Massive: ticker missing from a poll | Logged; its cached price simply stops advancing. |
| Many SSE clients | Each has independent `last_sent`; cache reads are O(tickers) under a tiny lock. |
| Simulator precision | Prices rounded to 2 dp in the cache; `exp()` guarantees positivity. |
| Event-loop blocking | Only Massive I/O is blocking and is offloaded with `to_thread`; simulator step (~10 tickers) is microseconds. |

Configuration:

| Parameter | Where | Default |
|---|---|---|
| `MASSIVE_API_KEY` | env | `""` → simulator |
| `MASSIVE_POLL_INTERVAL` | env (optional) | `15` s (use 2–5 on paid plans) |
| `update_interval` | `SimulatorDataSource` | `0.5` s |
| `event_probability` | `GBMSimulator` | `0.001` per ticker per tick (~1 event / 50 s across 10 tickers) |
| `dt` | `GBMSimulator` | `0.5 / (252·6.5·3600)` ≈ 8.48e‑8 |
| `PUSH_INTERVAL` | `stream.py` | `0.5` s |
| `KEEPALIVE_INTERVAL` | `stream.py` | `15` s |
| SSE `retry` | `stream.py` | `1000` ms |

Public API (`__init__.py`):

```python
from .cache import PriceCache
from .errors import MarketDataError, MarketDataUnavailableError, UnknownTickerError
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PriceUpdate
from .stream import create_stream_router

__all__ = ["PriceUpdate", "PriceCache", "MarketDataSource", "create_market_data_source",
           "create_stream_router", "MarketDataError", "UnknownTickerError",
           "MarketDataUnavailableError"]
```

---

## 15. Delta vs. Existing Code

The code in `backend/app/market/` was built to the earlier design. To reach this one:

| Area | Existing | Change |
|---|---|---|
| `PriceUpdate` | no `reference_price`; float timestamp only; `change_percent` vs previous tick | add `reference_price`, `seq`, `iso_timestamp`, `to_sse_dict()`, `day_change_percent`; drop tick-relative `change_percent` |
| SSE payload | one event containing a dict of **all** tickers, epoch timestamp | one ticker per message, ISO timestamp, exact PLAN fields (**frontend contract change**) |
| SSE change detection | global `cache.version` | per-ticker `seq`, per-connection `last_sent`; stream only tracked tickers; keepalive |
| `PriceCache` | `remove()`, `version` | delete both; add `reference_price` handling, `get_many`; cache never evicts |
| `remove_ticker` (both sources) | calls `cache.remove` | must not touch the cache (frozen price, R5) |
| Interface | `add_ticker` never fails | `add_ticker` may raise `UnknownTickerError`; guarantees cache seeded on return |
| Simulator | reference price absent; re-add resets to seed | set reference once; resume from frozen cached price; `get_tickers()` public; seedable RNG |
| Massive | no validation, no reference price, fixed ms timestamps, no backoff | validate on add, parse `prev_day.close`, unit-normalising timestamps, backoff, call lock, `MASSIVE_POLL_INTERVAL` |
| Watchlist route | keeps held tickers in source | always removes from source; `409 position_open` unless `confirm` |
| Lifespan | loads watchlist only | loads watchlist ∪ held tickers; freezes held-only |
| `stream.py` | module-level `router` | router built inside the factory; takes `(cache, source)` |
| Lint/tests | — | add tests in §13; the old `version`/`remove` tests are replaced |

Suggested implementation order: `models` → `errors` → `cache` → `interface` → `simulator` → `massive_client` → `factory` → `stream` → watchlist/portfolio wiring → update `market_data_demo.py` (reads `to_dict()`; drop `cache.remove`/`version` usage) → regenerate `MARKET_DATA_SUMMARY.md`.
