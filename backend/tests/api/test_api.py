"""API tests using FastAPI TestClient with a temp DB and the mock LLM."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(tmp_path / "nostatic"))
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    with TestClient(create_app()) as c:
        yield c


def err(resp, status, code):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["code"] == code and body["error"]


def trade(client, ticker="AAPL", side="buy", quantity=10):
    return client.post(
        "/api/portfolio/trade", json={"ticker": ticker, "side": side, "quantity": quantity}
    )


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_unknown_route_format(client):
    err(client.get("/api/nope"), 404, "not_found")


def test_initial_portfolio(client):
    pf = client.get("/api/portfolio").json()
    assert pf["cash_balance"] == 10000.0
    assert pf["total_value"] == 10000.0
    assert pf["positions"] == []


def test_watchlist_default(client):
    wl = client.get("/api/watchlist").json()
    assert len(wl) == 10
    aapl = next(w for w in wl if w["ticker"] == "AAPL")
    assert aapl["price"] > 0 and aapl["reference_price"] > 0


def test_initial_snapshot(client):
    assert len(client.get("/api/portfolio/history").json()) >= 1


def test_buy_and_sell(client):
    r = trade(client)
    assert r.status_code == 200
    body = r.json()
    assert body["trade"]["ticker"] == "AAPL"
    pf = body["portfolio"]
    assert pf["cash_balance"] < 10000
    assert pf["positions"][0]["quantity"] == 10
    assert len(client.get("/api/portfolio/history").json()) >= 2

    r = trade(client, side="sell", quantity=10)
    assert r.json()["portfolio"]["positions"] == []
    trades = client.get("/api/portfolio/trades").json()
    assert [t["side"] for t in trades] == ["sell", "buy"]


def test_trade_lowercase_ticker(client):
    assert trade(client, ticker="aapl").status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"ticker": "AAPL", "side": "hold", "quantity": 1},
        {"ticker": "AAPL", "side": "buy", "quantity": 0},
        {"ticker": "AAPL", "side": "buy", "quantity": -1},
        {"ticker": "AAPL", "side": "buy", "quantity": 0.1234567},
        {"ticker": "AAPL", "side": "buy", "quantity": "abc"},
        {"ticker": "AAPL", "side": "buy"},
        {"side": "buy", "quantity": 1},
    ],
)
def test_trade_invalid(client, payload):
    err(client.post("/api/portfolio/trade", json=payload), 400, "invalid_request")


def test_trade_bad_body(client):
    err(client.post("/api/portfolio/trade", content="nope"), 400, "invalid_request")


def test_trade_unknown_ticker(client):
    err(trade(client, ticker="$$$"), 400, "unknown_ticker")
    err(trade(client, ticker="ZZZZ"), 400, "unknown_ticker")  # valid shape, not watched


def test_insufficient_cash(client):
    err(trade(client, quantity=1_000_000), 400, "insufficient_cash")


def test_insufficient_shares(client):
    err(trade(client, side="sell", quantity=1), 400, "insufficient_shares")


def test_fractional_trade(client):
    assert trade(client, quantity=0.5).status_code == 200


def test_watchlist_add_remove(client):
    r = client.post("/api/watchlist", json={"ticker": "pypl"})
    assert r.status_code == 201
    assert r.json()["ticker"] == "PYPL" and r.json()["price"] > 0
    assert len(client.get("/api/watchlist").json()) == 11
    # now tradable
    assert trade(client, ticker="PYPL", quantity=1).status_code == 200
    assert client.delete("/api/watchlist/PYPL?confirm=true").status_code == 200
    assert len(client.get("/api/watchlist").json()) == 10


def test_watchlist_errors(client):
    err(client.post("/api/watchlist", json={"ticker": "AAPL"}), 409, "already_exists")
    err(client.post("/api/watchlist", json={"ticker": "not a ticker"}), 400, "unknown_ticker")
    err(client.post("/api/watchlist", json={}), 400, "invalid_request")
    err(client.delete("/api/watchlist/ZZZ"), 404, "not_found")


def test_remove_held_requires_confirm_and_freezes_price(client):
    trade(client, ticker="NVDA", quantity=1)
    err(client.delete("/api/watchlist/NVDA"), 409, "position_open")
    assert client.delete("/api/watchlist/NVDA?confirm=true").status_code == 200
    pf = client.get("/api/portfolio").json()
    pos = pf["positions"][0]
    assert pos["ticker"] == "NVDA" and pos["current_price"] > 0
    first = pos["current_price"]
    assert client.get("/api/portfolio").json()["positions"][0]["current_price"] == first
    # selling the frozen position still works at the frozen price
    assert trade(client, ticker="NVDA", side="sell", quantity=1).status_code == 200


def test_chat_history_empty(client):
    assert client.get("/api/chat").json() == []


def test_chat_buy(client):
    r = client.post("/api/chat", json={"message": "please BUY something"})
    assert r.status_code == 200
    body = r.json()
    assert body["message"] == "Bought 10 shares of AAPL."
    assert body["actions"][0]["status"] == "ok"
    assert body["actions"][0]["type"] == "trade"
    assert client.get("/api/portfolio").json()["positions"][0]["quantity"] == 10
    hist = client.get("/api/chat").json()
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[1]["actions"][0]["status"] == "ok"


def test_chat_sell_without_shares_reports_error(client):
    body = client.post("/api/chat", json={"message": "sell"}).json()
    a = body["actions"][0]
    assert a["status"] == "error" and a["code"] == "insufficient_shares" and a["message"]


def test_chat_watchlist(client):
    body = client.post("/api/chat", json={"message": "watch PYPL"}).json()
    assert body["actions"][0]["status"] == "ok"
    assert any(w["ticker"] == "PYPL" for w in client.get("/api/watchlist").json())
    # repeating fails independently with already_exists
    body = client.post("/api/chat", json={"message": "watch PYPL"}).json()
    assert body["actions"][0]["code"] == "already_exists"


def test_chat_plain(client):
    body = client.post("/api/chat", json={"message": "hello"}).json()
    assert body["actions"] == [] and body["message"]


def test_chat_empty_message(client):
    err(client.post("/api/chat", json={"message": "  "}), 400, "invalid_request")


def test_chat_llm_failure(client, monkeypatch):
    from app.api import chat
    from app.llm import LLMError

    async def boom(*a, **k):
        raise LLMError("down")

    monkeypatch.setattr(chat, "get_llm_reply", boom)
    body = client.post("/api/chat", json={"message": "buy"}).json()
    assert body["actions"] == [] and "Sorry" in body["message"]
    assert client.get("/api/portfolio").json()["positions"] == []
    hist = client.get("/api/chat").json()
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[1]["actions"] is None


def test_chat_sequential_actions(client, monkeypatch):
    from app.api import chat
    from app.llm import LLMResponse, TradeAction

    async def fake(ctx, hist, msg):
        return LLMResponse(
            message="ok",
            actions=[
                TradeAction(ticker="AAPL", side="buy", quantity=5),
                TradeAction(ticker="AAPL", side="sell", quantity=5),
                TradeAction(ticker="AAPL", side="sell", quantity=1),
            ],
        )

    monkeypatch.setattr(chat, "get_llm_reply", fake)
    acts = client.post("/api/chat", json={"message": "go"}).json()["actions"]
    assert [a["status"] for a in acts] == ["ok", "ok", "error"]


def test_chat_history_limited_to_20(client, monkeypatch):
    from app.api import chat
    from app.llm import LLMResponse

    seen = {}

    async def fake(ctx, hist, msg):
        seen["n"] = len(hist)
        return LLMResponse(message="r")

    monkeypatch.setattr(chat, "get_llm_reply", fake)
    for i in range(15):
        client.post("/api/chat", json={"message": f"m{i}"})
    assert seen["n"] == 20


def test_static_serving(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>home</html>")
    (static / "app.js").write_text("x")
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(static))
    with TestClient(create_app()) as c:
        assert "home" in c.get("/").text
        assert c.get("/app.js").text == "x"
        assert "home" in c.get("/some/spa/route").text
        assert c.get("/api/health").json() == {"status": "ok"}
        err(c.get("/api/missing"), 404, "not_found")
        assert "home" in c.get("/../secret").text  # no traversal


def test_sse_events(client):
    from app.api.stream import generate_events

    state = client.app.state.fin

    class Req:
        async def is_disconnected(self):
            return False

    async def collect():
        out = []
        gen = generate_events(state, Req(), interval=0.01)
        async for chunk in gen:
            out.append(chunk)
            if len(out) >= 11:
                break
        await gen.aclose()
        return out

    chunks = asyncio.run(collect())
    assert chunks[0].startswith("retry:")
    import json

    msg = json.loads(chunks[1][len("data: "):])
    assert set(msg) >= {
        "ticker",
        "price",
        "previous_price",
        "reference_price",
        "timestamp",
        "direction",
    }


def test_readded_ticker_reference_matches_new_price(client):
    for _ in range(3):
        client.post("/api/watchlist", json={"ticker": "PYPL"})
        row = next(w for w in client.get("/api/watchlist").json() if w["ticker"] == "PYPL")
        assert abs(row["price"] - row["reference_price"]) / row["reference_price"] < 0.01
        client.delete("/api/watchlist/PYPL")
