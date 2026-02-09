# Kalshi Volatility Trader

Production-focused Kalshi trading bot with a FastAPI backend and the existing HTML dashboard wired to live backend data.
The system supports paper trading by default and can be switched to live trading once Kalshi credentials are configured.

## Features

- **Secure backend** with FastAPI, structured logs, audit trail, and SQLite persistence.
- **Kalshi + OpenAI integration** via server-side environment variables only (no keys in browser).
- **Risk controls**: max exposure, max concurrent positions, stop after N losses, event drawdown caps, kill switch.
- **Volatility scoring** using microstructure signals (returns, spread, update activity, time-to-expiry weighting).
- **Interactive dashboard** for live scan, activity log, and positions.

## Repository Layout

```
backend/     FastAPI service + trading engine
frontend/    Existing dashboard (HTML + JS)
shared/      (optional if you want to add cross-language types)
```

## Setup

### 1) Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` into `.env` and fill in your credentials:

```bash
cp ../.env.example ../.env
```

> **Important:** API keys are never stored in the database or exposed to the browser.

### 2) Run the service

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

The dashboard is served at http://localhost:8000.

## Paper Trading (Default)

The bot runs in paper mode by default (`paper_trading=true`) and uses deterministic pricing when Kalshi credentials are
not configured. This is intended for safe, testable validation of the risk logic and UI.

## Enabling Live Trading

1. Set `KALSHI_API_KEY` (and `KALSHI_API_SECRET` if needed) in your `.env`.
2. Update `paper_trading` to `false` via `POST /config` or edit `backend/data/config.json`.
3. Restart the backend.

> **Warning:** Live trading carries risk. Targets such as “5–6 trades of 3–5%” are aspirational, not guarantees. Always
> set conservative limits and monitor exposure.

## API Endpoints

- `GET /health` — service + connection status
- `GET /config` / `POST /config` — bot configuration
- `GET /markets/scan` — latest scan snapshot
- `POST /bot/start` / `POST /bot/stop` — control bot
- `GET /bot/status` — running status
- `GET /positions` — stored positions
- `GET /orders` — stored orders
- `WS /ws` — live updates (scan, status, positions, activity)

## Testing

```bash
cd backend
pytest
```

## Risk Disclaimer

Trading involves risk, and no strategy guarantees returns. Use this project for educational or controlled
experimentation, and validate all order-routing and risk checks in paper mode before connecting to live trading.
