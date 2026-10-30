# FinAlly — AI Trading Workstation

FinAlly (Finance Ally) is a Bloomberg-style trading terminal with an AI copilot. It streams live (simulated) market prices, lets you trade a $10,000 virtual portfolio, and includes an LLM chat assistant that can analyze positions and execute trades or manage your watchlist from natural language.

Built entirely by coding agents as the capstone for an agentic AI coding course.

## Features

- Live-streaming watchlist (10 default tickers) with price flashes and sparklines
- Detailed price chart, portfolio heatmap, P&L chart, and positions table
- Market-order trading: instant fill, no fees
- AI chat that auto-executes trades and watchlist changes
- Single user, no login

## Architecture

One container, one port (8000):

- **Frontend**: Next.js + TypeScript, static export served by FastAPI
- **Backend**: FastAPI (Python, managed with `uv`), REST + Server-Sent Events
- **Database**: SQLite (`db/finally.db`), lazily initialized and volume-mounted
- **Market data**: built-in GBM simulator by default; real data via Massive API if `MASSIVE_API_KEY` is set
- **LLM**: LiteLLM → OpenRouter (`gpt-oss-120b` on Cerebras) with structured outputs

## Quick Start

```bash
cp .env.example .env   # add your OPENROUTER_API_KEY
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

Then open <http://localhost:8000>. Start/stop scripts for macOS/Linux and Windows will live in `scripts/`.

### Environment variables

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Required for AI chat |
| `MASSIVE_API_KEY` | Optional; real market data instead of the simulator |
| `LLM_MOCK` | Set `true` for deterministic mock LLM replies (tests) |

## Development

```bash
cd backend && uv sync && uv run pytest   # backend + market data tests
```

## Status

The market data component (simulator, Massive client, price cache, SSE stream) is complete. The rest of the platform (portfolio, chat, frontend, Docker) is still to be built.

## Docs

- [`planning/PLAN.md`](planning/PLAN.md) — full project specification
- [`planning/MARKET_DATA_SUMMARY.md`](planning/MARKET_DATA_SUMMARY.md) — market data component summary

## License

See [`LICENSE`](LICENSE).
