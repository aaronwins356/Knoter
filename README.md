# Knoter Trading Dashboard

Production-focused Kalshi trading bot with a FastAPI backend and a vanilla HTML dashboard. The system defaults to paper
trading, supports a gated LIVE mode, and logs every trading decision with auditability.

## Features

- **Kalshi + OpenAI integrations** secured via server-side environment variables only (no keys in the browser).
- **Paper vs LIVE mode** with explicit confirmation phrase and server-side enable flag.
- **Trading engine** with deterministic entry/exit/cash-out rules and configurable thresholds.
- **Risk safety controls**: max exposure, max loss per event/session, max loss streak, cooldowns, and kill switch.
- **Audit logs** with CSV download and advisory explanations.
- **Dashboard** with live scanner, trade detail drawer, and positions/orders management.

## Repository Layout

```
backend/     FastAPI service + trading engine
frontend/    Dashboard (HTML + JS)
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
cp .env.example .env
```

> **Important:** API keys are never stored in the database or exposed to the browser.

### 2) Run the service

```bash
cd backend
python -m dashboard.app
```

The dashboard is served at http://localhost:8000.

## Paper Trading (Default)

The bot runs in paper mode by default (`trading_mode=paper`) and uses deterministic pricing when Kalshi credentials are
not configured. This is intended for safe, testable validation of the risk logic and UI, and requires no Kalshi
credentials.

## Enabling Live Trading

1. Set `KALSHI_API_KEY_ID` (or `KALSHI_API_KEY`) in your `.env`.
2. Provide your RSA private key via **either** `KALSHI_PRIVATE_KEY_PATH` (preferred) **or** `KALSHI_PRIVATE_KEY_PEM`.
3. Set `KALSHI_ENV=live` in your `.env`.
4. Set `KNOTER_LIVE_TRADING_ENABLED=true` in your `.env` and restart the backend.
5. In the dashboard, switch mode to LIVE and type the confirmation phrase **ENABLE LIVE TRADING**.

> **Warning:** Live trading carries risk. No strategy guarantees returns. Always validate in paper mode first.

## Kalshi Price Fields Update

Kalshi market responses are transitioning away from cent-denominated fields (`yes_bid`, `yes_ask`, `last_price`, etc).
Knoter now normalizes **dollar-denominated** fields first (`yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`)
and falls back safely when needed. All internal prices are stored as floats in the `[0, 1]` dollar range.

## API Endpoints

- `GET /health` — service + connection status
- `GET /kalshi/status` — Kalshi connectivity, environment, and masked account info
- `GET /config` / `POST /config` — bot configuration
- `GET /markets/scan` — latest scan snapshot
- `GET /markets/{market_id}/detail` — market detail (prices, audit, scores)
- `POST /bot/start` / `POST /bot/stop` / `POST /bot/kill` — control bot
- `POST /bot/dryrun` — run one scan cycle without placing orders
- `GET /bot/status` — running status
- `GET /positions` / `POST /positions/{position_id}/close` — positions
- `GET /orders` / `POST /orders/{order_id}/cancel` — orders
- `GET /audit` / `GET /audit/csv` / `GET /decisions` — decision audit log
- `GET /fills` — recent fills
- `GET /snapshots` — scan snapshots history
- `WS /ws` — live updates (scan, status, positions, activity)

## Testing

```bash
cd backend
pytest
```

## Demo smoke test

```bash
cd backend
python -m tools.smoke_test
```

## Risk Disclaimer

Trading involves risk, and no strategy guarantees returns. Use this project for educational or controlled
experimentation, and validate all order-routing and risk checks in paper mode before connecting to live trading.
