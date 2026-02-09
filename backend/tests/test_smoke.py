import asyncio
from datetime import datetime, timedelta, timezone

from app.bot import maybe_open_trade, update_positions
from app.models import MarketSnapshot, ScanSnapshot, TradingMode
from app.state import BotState, MarketState


def test_smoke_cycle_paper_broker():
    state = BotState()
    state.config.trading_mode = TradingMode.PAPER
    state.config.entry.momentum_window = 2
    state.config.entry.momentum_threshold_pct = 0.0
    state.config.scoring.vol_threshold = 0.0
    state.config.scoring.max_spread_pct = 50.0
    state.config.scoring.min_liquidity_score = 0.0
    state.config.exit.take_profit_pct = 1.0
    state.config.entry.fee_pct = 0.0

    market_id = "DEMO-MKT"
    market_state = MarketState()
    market_state.prices.extend([0.5, 0.52])
    state.market_state[market_id] = market_state

    snapshot = MarketSnapshot(
        market_id=market_id,
        name="Demo Market",
        category="sports",
        mid_price=0.52,
        bid=0.51,
        ask=0.53,
        last_price=0.52,
        volume=500.0,
        bid_depth=300.0,
        ask_depth=300.0,
        volatility_pct=2.0,
        spread_pct=0.1,
        liquidity_score=80.0,
        overall_score=75.0,
        qualifies=True,
        rationale="Qualified",
        time_to_resolution_minutes=120.0,
    )
    market_state.last_snapshot = snapshot
    state.last_scan = ScanSnapshot(timestamp=datetime.now(tz=timezone.utc), markets=[snapshot])

    asyncio.run(maybe_open_trade(state))
    assert len(state.positions) == 1

    position = next(iter(state.positions.values()))
    market_state.last_snapshot = snapshot.model_copy(update={"mid_price": 0.54, "bid": 0.54, "ask": 0.55})
    asyncio.run(update_positions(state))
    assert position.status == "closed"
    assert position.closed_at is not None
