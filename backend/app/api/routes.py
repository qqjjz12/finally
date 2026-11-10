"""REST routes: health, portfolio, watchlist."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Request

from app.db import repository as repo

from .state import AppState, db

router = APIRouter(prefix="/api")


def _state(request: Request) -> AppState:
    return request.app.state.fin


@router.get("/health")
async def health():
    return {"status": "ok"}


# ---- portfolio ----------------------------------------------------------
@router.get("/portfolio")
async def get_portfolio(request: Request):
    state = _state(request)

    def work():
        with db() as conn:
            return state.build_portfolio(conn)

    return await asyncio.to_thread(work)


@router.post("/portfolio/trade")
async def post_trade(request: Request, body: dict = Body(...)):
    state = _state(request)

    def work():
        with db() as conn:
            result = state.trade(conn, body.get("ticker"), body.get("side"), body.get("quantity"))
            return {"trade": result, "portfolio": state.build_portfolio(conn)}

    return await asyncio.to_thread(work)


@router.get("/portfolio/history")
async def get_history():
    def work():
        with db() as conn:
            return repo.list_snapshots(conn)

    return await asyncio.to_thread(work)


@router.get("/portfolio/trades")
async def get_trades():
    def work():
        with db() as conn:
            return repo.list_trades(conn)

    return await asyncio.to_thread(work)


# ---- watchlist ----------------------------------------------------------
def _watch_row(state: AppState, ticker: str) -> dict:
    update = state.cache.get(ticker)
    return {
        "ticker": ticker,
        "price": update.price if update else None,
        "previous_price": update.previous_price if update else None,
        "reference_price": state.reference_of(ticker),
    }


@router.get("/watchlist")
async def get_watchlist(request: Request):
    state = _state(request)

    def work():
        with db() as conn:
            return repo.list_watchlist(conn)

    tickers = await asyncio.to_thread(work)
    return [_watch_row(state, t) for t in tickers]


@router.post("/watchlist", status_code=201)
async def add_watchlist(request: Request, body: dict = Body(...)):
    state = _state(request)
    ticker = await state.watchlist_add(body.get("ticker"))
    return _watch_row(state, ticker)


@router.delete("/watchlist/{ticker}")
async def delete_watchlist(ticker: str, request: Request, confirm: bool = False):
    state = _state(request)
    removed = await state.watchlist_remove(ticker, confirm=confirm)
    return {"ticker": removed}
