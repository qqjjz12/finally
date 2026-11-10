"""SSE price stream: one ticker update per `data:` line, includes reference_price."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .state import AppState

router = APIRouter()


def price_payload(state: AppState, update) -> dict:
    ref = state.reference_of(update.ticker)
    return {
        "ticker": update.ticker,
        "price": update.price,
        "previous_price": update.previous_price,
        "reference_price": ref if ref is not None else update.price,
        "timestamp": datetime.fromtimestamp(update.timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "direction": update.direction,
    }


async def generate_events(
    state: AppState, request: Request, interval: float = 0.5
) -> AsyncGenerator[str, None]:
    yield "retry: 1000\n\n"
    seen: dict[str, object] = {}
    last_version = -1
    try:
        while True:
            if await request.is_disconnected():
                break
            version = state.cache.version
            if version != last_version:
                last_version = version
                current = state.cache.get_all()
                for ticker, update in current.items():
                    if seen.get(ticker) is not update:
                        seen[ticker] = update
                        yield f"data: {json.dumps(price_payload(state, update))}\n\n"
                for gone in set(seen) - set(current):
                    seen.pop(gone, None)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


@router.get("/api/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    state: AppState = request.app.state.fin
    return StreamingResponse(
        generate_events(state, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
