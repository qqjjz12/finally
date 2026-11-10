"""System prompt construction."""

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant inside a simulated trading workstation (fake money).

Your job:
- Analyze portfolio composition, risk concentration, and P&L.
- Suggest trades with brief reasoning.
- Execute trades when the user asks or agrees; trades execute automatically as market orders.
- Manage the watchlist proactively (add/remove tickers).
- Before removing a ticker the user holds a position in, ask the user to confirm in `message` \
(noting that its price will stop updating). Only set "confirmed": true on the removal once they agree. \
The backend rejects an unconfirmed removal of a held ticker with `position_open`.
- Be concise and data-driven.

Always respond with valid JSON only, matching this schema:
{"message": "<conversational reply>", "actions": [
  {"type": "trade", "ticker": "AAPL", "side": "buy" | "sell", "quantity": 10},
  {"type": "watchlist", "ticker": "PYPL", "action": "add" | "remove", "confirmed": false}
]}
`actions` may be empty. Actions run in order; later ones see cash/positions left by earlier ones.

Current portfolio context:
{context}
"""


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def format_context(ctx: dict) -> str:
    lines = [
        f"Cash: {_fmt(ctx.get('cash', 0.0))}",
        f"Total portfolio value: {_fmt(ctx.get('total_value', 0.0))}",
        "Positions:",
    ]
    positions = ctx.get("positions") or []
    if not positions:
        lines.append("  (none)")
    for p in positions:
        lines.append(
            f"  {p.get('ticker')}: qty {_fmt(p.get('quantity'))}, avg cost {_fmt(p.get('avg_cost'))}, "
            f"price {_fmt(p.get('price'))}, P&L {_fmt(p.get('pnl'))} ({_fmt(p.get('pnl_pct'))}%)"
        )
    lines.append("Watchlist:")
    wl = ctx.get("watchlist") or []
    if not wl:
        lines.append("  (empty)")
    for w in wl:
        lines.append(f"  {w.get('ticker')}: {_fmt(w.get('price'))}")
    return "\n".join(lines)


def build_system_prompt(ctx: dict) -> str:
    return SYSTEM_PROMPT.replace("{context}", format_context(ctx))
