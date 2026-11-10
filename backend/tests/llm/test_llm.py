import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.llm import LLMError, LLMResponse, TradeAction, WatchlistAction, get_llm_reply
from app.llm import client as client_mod

CTX = {
    "cash": 5000.0,
    "total_value": 10500.0,
    "positions": [
        {"ticker": "AAPL", "quantity": 10, "avg_cost": 190.0, "price": 200.0,
         "pnl": 100.0, "pnl_pct": 5.26}
    ],
    "watchlist": [{"ticker": "AAPL", "price": 200.0}, {"ticker": "TSLA", "price": 250.5}],
}


def fake_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


@pytest.fixture
def acompletion(monkeypatch):
    m = AsyncMock()
    monkeypatch.setattr(client_mod, "acompletion", m)
    return m


async def test_parses_valid_response(acompletion):
    acompletion.return_value = fake_response(json.dumps({
        "message": "Done",
        "actions": [
            {"type": "trade", "ticker": "AAPL", "side": "buy", "quantity": 3},
            {"type": "watchlist", "ticker": "PYPL", "action": "remove", "confirmed": True},
        ],
    }))
    r = await get_llm_reply(CTX, [], "hi")
    assert r.message == "Done"
    assert isinstance(r.actions[0], TradeAction)
    assert isinstance(r.actions[1], WatchlistAction)
    assert r.actions[1].confirmed is True


async def test_actions_default_empty(acompletion):
    acompletion.return_value = fake_response('{"message": "hello"}')
    r = await get_llm_reply(CTX, [], "hi")
    assert r.actions == []


async def test_call_params_and_prompt(acompletion):
    acompletion.return_value = fake_response('{"message": "ok"}')
    hist = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    await get_llm_reply(CTX, hist, "new msg")
    kw = acompletion.call_args.kwargs
    assert kw["model"] == "openrouter/openai/gpt-oss-120b"
    assert kw["extra_body"] == {"provider": {"order": ["cerebras"]}}
    assert kw["response_format"] is LLMResponse
    msgs = kw["messages"]
    assert msgs[0]["role"] == "system"
    sp = msgs[0]["content"]
    assert "FinAlly" in sp and "AAPL" in sp and "TSLA" in sp
    assert "5000.00" in sp and "10500.00" in sp
    assert "confirm" in sp and "position_open" in sp
    assert [m["content"] for m in msgs[1:]] == ["a", "b", "new msg"]
    assert msgs[-1]["role"] == "user"


async def test_empty_context_prompt(acompletion):
    acompletion.return_value = fake_response('{"message": "ok"}')
    await get_llm_reply({"cash": 1.0, "total_value": 1.0, "positions": [], "watchlist": []}, [], "x")
    assert "(none)" in acompletion.call_args.kwargs["messages"][0]["content"]


@pytest.mark.parametrize("content", [
    "not json",
    "",
    None,
    '{"actions": []}',
    '{"message": "x", "actions": [{"type": "trade", "ticker": "A", "side": "hold", "quantity": 1}]}',
    '{"message": "x", "actions": [{"type": "trade", "ticker": "A", "side": "buy", "quantity": 0}]}',
    '{"message": "x", "actions": [{"type": "bogus"}]}',
    '{"message": "x", "actions": [{"type": "watchlist", "ticker": "A", "action": "nuke"}]}',
])
async def test_malformed_raises(acompletion, content):
    acompletion.return_value = fake_response(content)
    with pytest.raises(LLMError):
        await get_llm_reply(CTX, [], "hi")


async def test_provider_error_raises(acompletion):
    acompletion.side_effect = TimeoutError("slow")
    with pytest.raises(LLMError):
        await get_llm_reply(CTX, [], "hi")


async def test_missing_key_raises(acompletion, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(LLMError):
        await get_llm_reply(CTX, [], "hi")
    acompletion.assert_not_called()


def test_discriminated_union():
    r = LLMResponse.model_validate({"message": "m", "actions": [
        {"type": "trade", "ticker": "X", "side": "sell", "quantity": 1.5}]})
    assert isinstance(r.actions[0], TradeAction)
    with pytest.raises(ValidationError):
        TradeAction(ticker="X", side="buy", quantity=-1)


@pytest.mark.parametrize("msg,text,kind,expect", [
    ("Please BUY something", "Bought 10 shares of AAPL.", "trade", ("AAPL", "buy", 10)),
    ("sell it", "Sold 5 shares of AAPL.", "trade", ("AAPL", "sell", 5)),
    ("watch PYPL", "Added PYPL to your watchlist.", "watchlist", ("PYPL", "add", None)),
    ("buy and sell", "Bought 10 shares of AAPL.", "trade", ("AAPL", "buy", 10)),
    ("sell, then watch", "Sold 5 shares of AAPL.", "trade", ("AAPL", "sell", 5)),
])
async def test_mock_rules(acompletion, monkeypatch, msg, text, kind, expect):
    monkeypatch.setenv("LLM_MOCK", "true")
    r = await get_llm_reply(CTX, [], msg)
    assert r.message == text
    a = r.actions[0]
    assert a.type == kind and a.ticker == expect[0]
    if kind == "trade":
        assert (a.side, a.quantity) == expect[1:]
    else:
        assert a.action == "add"
    acompletion.assert_not_called()


async def test_mock_default_no_actions(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    r = await get_llm_reply(CTX, [], "how am I doing?")
    assert r.actions == [] and r.message
