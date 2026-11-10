import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.db import init_db
from app.db import repository as r
from app.db.init import DEFAULT_TICKERS


@pytest.fixture
def conn(tmp_path):
    c = r.get_connection(str(tmp_path / "sub" / "t.db"))
    yield c
    c.close()


def code(exc):
    return exc.value.code


def test_init_seeds_and_is_idempotent(tmp_path):
    p = str(tmp_path / "x" / "a.db")
    init_db(p)
    init_db(p)
    c = r.get_connection(p)
    assert r.get_cash(c) == 10000.0
    assert r.list_watchlist(c) == DEFAULT_TICKERS
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_reinit_does_not_reseed_removed_ticker(tmp_path):
    p = str(tmp_path / "a.db")
    c = r.get_connection(p)
    r.remove_watchlist(c, "AAPL")
    init_db(p)
    assert "AAPL" not in r.list_watchlist(r.get_connection(p))


def test_env_path(tmp_path, monkeypatch):
    p = tmp_path / "env.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(p))
    r.get_connection().close()
    assert p.exists()


def test_watchlist_add_remove(conn):
    r.add_watchlist(conn, " pypl ")
    assert r.list_watchlist(conn)[-1] == "PYPL"
    with pytest.raises(r.DbError) as e:
        r.add_watchlist(conn, "PYPL")
    assert code(e) == "already_exists"
    r.remove_watchlist(conn, "pypl")
    with pytest.raises(r.DbError) as e:
        r.remove_watchlist(conn, "PYPL")
    assert code(e) == "not_found"


def test_remove_held_requires_confirm(conn):
    r.execute_trade(conn, "AAPL", "buy", 1, 100)
    with pytest.raises(r.DbError) as e:
        r.remove_watchlist(conn, "AAPL")
    assert code(e) == "position_open"
    assert "AAPL" in r.list_watchlist(conn)
    r.remove_watchlist(conn, "AAPL", confirm=True)
    assert "AAPL" not in r.list_watchlist(conn)
    assert len(r.list_positions(conn)) == 1  # position stays


def test_buy_creates_position(conn):
    res = r.execute_trade(conn, "aapl", "BUY", 10, 100.0)
    assert res == {"ticker": "AAPL", "side": "buy", "quantity": 10.0, "price": 100.0,
                   "cash_balance": 9000.0}
    pos = r.list_positions(conn)
    assert len(pos) == 1 and pos[0]["ticker"] == "AAPL"
    assert pos[0]["quantity"] == 10 and pos[0]["avg_cost"] == 100
    assert r.get_cash(conn) == 9000.0


def test_weighted_avg_cost_and_sell_keeps_avg(conn):
    r.execute_trade(conn, "AAPL", "buy", 10, 100)
    r.execute_trade(conn, "AAPL", "buy", 30, 200)
    p = r.list_positions(conn)[0]
    assert p["quantity"] == 40 and p["avg_cost"] == pytest.approx(175.0)
    r.execute_trade(conn, "AAPL", "sell", 15, 300)
    p = r.list_positions(conn)[0]
    assert p["quantity"] == 25 and p["avg_cost"] == pytest.approx(175.0)
    assert r.get_cash(conn) == pytest.approx(10000 - 1000 - 6000 + 4500)


def test_sell_all_deletes_row(conn):
    r.execute_trade(conn, "AAPL", "buy", 2.5, 100)
    r.execute_trade(conn, "AAPL", "sell", 2.5, 120)
    assert r.list_positions(conn) == []
    assert r.get_cash(conn) == pytest.approx(10050)


def test_fractional_ok_and_float_residue_deletes(conn):
    r.execute_trade(conn, "AAPL", "buy", 0.1, 10)
    r.execute_trade(conn, "AAPL", "buy", 0.2, 10)
    r.execute_trade(conn, "AAPL", "sell", 0.3, 10)  # 0.1+0.2 != 0.3 in float
    assert r.list_positions(conn) == []
    r.execute_trade(conn, "AAPL", "buy", 0.000001, 10)
    assert r.list_positions(conn)[0]["quantity"] == pytest.approx(1e-6)


@pytest.mark.parametrize(
    "q", [0, -1, 0.0000001, 1.1234567, "abc", None, float("nan"), float("inf"), True]
)
def test_invalid_quantity(conn, q):
    with pytest.raises(r.DbError) as e:
        r.execute_trade(conn, "AAPL", "buy", q, 10)
    assert code(e) == "invalid_request"
    assert r.get_cash(conn) == 10000.0 and r.list_trades(conn) == []


@pytest.mark.parametrize("side", ["hold", "", None, "short"])
def test_invalid_side(conn, side):
    with pytest.raises(r.DbError) as e:
        r.execute_trade(conn, "AAPL", side, 1, 10)
    assert code(e) == "invalid_request"


def test_invalid_ticker_and_price(conn):
    for t, p in [("", 10), ("AAPL", 0), ("AAPL", -5), ("AAPL", "x")]:
        with pytest.raises(r.DbError) as e:
            r.execute_trade(conn, t, "buy", 1, p)
        assert code(e) == "invalid_request"


def test_insufficient_cash_atomic(conn):
    with pytest.raises(r.DbError) as e:
        r.execute_trade(conn, "AAPL", "buy", 101, 100)
    assert code(e) == "insufficient_cash"
    assert r.get_cash(conn) == 10000.0
    assert r.list_positions(conn) == [] and r.list_trades(conn) == []
    r.execute_trade(conn, "AAPL", "buy", 100, 100)  # exact balance allowed
    assert r.get_cash(conn) == 0


def test_oversell_and_sell_unowned(conn):
    with pytest.raises(r.DbError) as e:
        r.execute_trade(conn, "AAPL", "sell", 1, 10)
    assert code(e) == "insufficient_shares"
    r.execute_trade(conn, "AAPL", "buy", 5, 10)
    with pytest.raises(r.DbError) as e:
        r.execute_trade(conn, "AAPL", "sell", 5.5, 10)
    assert code(e) == "insufficient_shares"
    assert r.list_positions(conn)[0]["quantity"] == 5
    assert len(r.list_trades(conn)) == 1


def test_mid_transaction_failure_rolls_back(conn):
    r.execute_trade(conn, "AAPL", "buy", 1, 100)
    conn.execute("DROP TABLE trades")  # force failure at the final insert
    with pytest.raises(sqlite3.OperationalError):
        r.execute_trade(conn, "AAPL", "buy", 1, 100)
    assert r.get_cash(conn) == 9900.0
    assert r.list_positions(conn)[0]["quantity"] == 1
    assert not conn.in_transaction


def test_trades_newest_first(conn):
    r.execute_trade(conn, "AAPL", "buy", 1, 10)
    r.execute_trade(conn, "MSFT", "buy", 1, 10)
    r.execute_trade(conn, "AAPL", "sell", 1, 10)
    ts = r.list_trades(conn)
    assert [(t["ticker"], t["side"]) for t in ts] == [
        ("AAPL", "sell"), ("MSFT", "buy"), ("AAPL", "buy")]
    assert set(ts[0]) >= {"id", "ticker", "side", "quantity", "price", "executed_at"}


def test_snapshots_and_prune(conn):
    r.record_snapshot(conn, 10000)
    r.record_snapshot(conn, 10100.5)
    old = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    conn.execute(
        "INSERT INTO portfolio_snapshots (id,user_id,total_value,recorded_at) "
        "VALUES ('o','default',1,?)", (old,))
    assert len(r.list_snapshots(conn)) == 3
    assert r.prune_snapshots(conn) == 1
    s = r.list_snapshots(conn)
    assert [x["total_value"] for x in s] == [10000, 10100.5]
    assert set(s[0]) == {"recorded_at", "total_value"}


def test_chat_messages(conn):
    r.add_chat_message(conn, "user", "hi")
    r.add_chat_message(conn, "assistant", "bought",
                       [{"type": "trade", "status": "ok", "ticker": "AAPL"}])
    for i in range(3):
        r.add_chat_message(conn, "user", f"m{i}")
    msgs = r.list_chat_messages(conn)
    assert [m["content"] for m in msgs] == ["hi", "bought", "m0", "m1", "m2"]
    assert msgs[0]["actions"] is None
    assert msgs[1]["actions"][0]["ticker"] == "AAPL"
    assert [m["content"] for m in r.list_chat_messages(conn, limit=2)] == ["m1", "m2"]
    with pytest.raises(r.DbError):
        r.add_chat_message(conn, "system", "x")


def test_concurrent_connections_consistent(tmp_path):
    p = str(tmp_path / "c.db")
    r.get_connection(p).close()
    errs = []

    def work():
        c = r.get_connection(p)
        try:
            for _ in range(10):
                r.execute_trade(c, "AAPL", "buy", 1, 10)
        except Exception as e:  # pragma: no cover
            errs.append(e)
        finally:
            c.close()

    ts = [threading.Thread(target=work) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    c = r.get_connection(p)
    assert r.list_positions(c)[0]["quantity"] == 40
    assert r.get_cash(c) == pytest.approx(10000 - 400)
    assert len(r.list_trades(c)) == 40
