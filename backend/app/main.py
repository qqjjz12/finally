"""FastAPI application entrypoint: `uvicorn app.main:app`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import chat, routes, stream
from app.api.errors import install_handlers
from app.api.state import AppState, db
from app.api.static import mount_static
from app.db import repository as repo
from app.market import PriceCache, create_market_data_source

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    def init():
        with db() as conn:  # get_connection lazily creates + seeds the database
            return repo.list_watchlist(conn)

    tickers = await asyncio.to_thread(init)

    cache = PriceCache()
    source = create_market_data_source(cache)
    state = AppState(cache, source)
    app.state.fin = state
    await source.start(tickers)
    for t in tickers:
        state.reference_of(t)
        state.price_of(t)

    def initial_snapshot():
        with db() as conn:
            state.snapshot(conn)
            repo.prune_snapshots(conn)

    await asyncio.to_thread(initial_snapshot)
    state.snapshot_task = asyncio.create_task(state.snapshot_loop(), name="snapshots")
    try:
        yield
    finally:
        state.snapshot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.snapshot_task
        await source.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="FinAlly", lifespan=lifespan)
    install_handlers(app)
    app.include_router(routes.router)
    app.include_router(chat.router)
    app.include_router(stream.router)
    mount_static(app)  # last, so /api wins
    return app


app = create_app()
