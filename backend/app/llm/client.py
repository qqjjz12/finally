"""LLM client: LiteLLM -> OpenRouter -> Cerebras, with structured outputs."""

import os

from litellm import acompletion
from pydantic import ValidationError

from .models import LLMResponse, TradeAction, WatchlistAction
from .prompts import build_system_prompt

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
TIMEOUT_SECONDS = 60


class LLMError(Exception):
    """Any failure obtaining a valid LLM response."""


def mock_reply(user_message: str) -> LLMResponse:
    text = user_message.lower()
    if "buy" in text:
        return LLMResponse(
            message="Bought 10 shares of AAPL.",
            actions=[TradeAction(ticker="AAPL", side="buy", quantity=10)],
        )
    if "sell" in text:
        return LLMResponse(
            message="Sold 5 shares of AAPL.",
            actions=[TradeAction(ticker="AAPL", side="sell", quantity=5)],
        )
    if "watch" in text:
        return LLMResponse(
            message="Added PYPL to your watchlist.",
            actions=[WatchlistAction(ticker="PYPL", action="add")],
        )
    return LLMResponse(
        message=(
            "Your portfolio looks balanced. Consider diversifying across sectors "
            "and keeping some cash in reserve."
        )
    )


async def get_llm_reply(
    portfolio_context: dict, history: list[dict], user_message: str
) -> LLMResponse:
    if os.environ.get("LLM_MOCK", "").strip().lower() == "true":
        return mock_reply(user_message)

    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        raise LLMError("OPENROUTER_API_KEY is not set")

    messages = [{"role": "system", "content": build_system_prompt(portfolio_context)}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        response = await acompletion(
            model=MODEL,
            messages=messages,
            response_format=LLMResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
            timeout=TIMEOUT_SECONDS,
        )
        content = response.choices[0].message.content
    except Exception as e:  # timeout, provider error, malformed envelope
        raise LLMError(f"LLM call failed: {type(e).__name__}") from e

    if not content or not isinstance(content, str):
        raise LLMError("LLM returned empty content")
    try:
        return LLMResponse.model_validate_json(content)
    except ValidationError as e:
        raise LLMError("LLM output did not match schema") from e
