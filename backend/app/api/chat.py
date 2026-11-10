"""Chat routes and LLM action orchestration."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Body, Request

from app.db import repository as repo
from app.db.repository import DbError
from app.llm import LLMError, get_llm_reply

from .errors import ApiError
from .state import AppState, db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

LLM_FAILURE_MESSAGE = "Sorry, I couldn't reach the AI service. Try again."


@router.get("/chat")
async def get_chat():
    def work():
        with db() as conn:
            return repo.list_chat_messages(conn)

    return await asyncio.to_thread(work)


@router.post("/chat")
async def post_chat(request: Request, body: dict = Body(...)):
    state: AppState = request.app.state.fin
    text = body.get("message")
    if not isinstance(text, str) or not text.strip():
        raise ApiError("invalid_request", "message is required")
    text = text.strip()

    def prepare():
        with db() as conn:
            history = repo.list_chat_messages(conn, limit=20)
            context = state.llm_context(conn)
            repo.add_chat_message(conn, "user", text)
            return history, context

    history, context = await asyncio.to_thread(prepare)
    history = [{"role": m["role"], "content": m["content"]} for m in history]

    try:
        reply = await get_llm_reply(context, history, text)
    except Exception as exc:  # LLMError or anything unexpected: execute nothing
        if not isinstance(exc, LLMError):
            logger.exception("Unexpected LLM failure")
        else:
            logger.warning("LLM failure: %s", exc)

        def store_failure():
            with db() as conn:
                repo.add_chat_message(conn, "assistant", LLM_FAILURE_MESSAGE)

        await asyncio.to_thread(store_failure)
        return {"message": LLM_FAILURE_MESSAGE, "actions": []}

    results = []
    for action in reply.actions:
        results.append(await _execute_action(state, action))

    def store():
        with db() as conn:
            repo.add_chat_message(conn, "assistant", reply.message, results)

    await asyncio.to_thread(store)
    return {"message": reply.message, "actions": results}


async def _execute_action(state: AppState, action) -> dict:
    result = action.model_dump()
    try:
        if action.type == "trade":

            def work():
                with db() as conn:
                    return state.trade(conn, action.ticker, action.side, action.quantity)

            trade = await asyncio.to_thread(work)
            result["ticker"] = trade["ticker"]
            result["price"] = trade["price"]
        else:
            if action.action == "add":
                result["ticker"] = await state.watchlist_add(action.ticker)
            else:
                result["ticker"] = await state.watchlist_remove(
                    action.ticker, confirm=action.confirmed
                )
        result["status"] = "ok"
    except (ApiError, DbError) as exc:
        result.update(status="error", code=exc.code, message=exc.message)
    except Exception:
        logger.exception("Action failed")
        result.update(status="error", code="internal_error", message="Internal server error")
    return result
