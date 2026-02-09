from datetime import datetime, timedelta, timezone
import asyncio

from app.bot import place_order_with_ttl
from app.models import BotConfig
from app.trading_engine import MarketMetrics, decide_entry, decide_exit


class FakeBroker:
    def __init__(self) -> None:
        self.calls = 0
        self.cancelled = []

    def place_order(self, market_id, side, price, qty, order_type="limit"):
        self.calls += 1
        status = "open" if self.calls < 3 else "filled"
        return {"order_id": f"order-{self.calls}", "status": status}

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return {"status": "cancelled"}


class DummyState:
    def __init__(self) -> None:
        self.config = BotConfig()
        self.config.entry.max_replacements = 2
        self.config.entry.order_ttl_seconds = 0
        self.orders = {}
        self.broker = FakeBroker()


def test_entry_decision_requires_momentum():
    config = BotConfig()
    metrics = MarketMetrics(
        volatility_pct=5.0,
        spread_pct=1.0,
        liquidity_score=80.0,
        overall_score=75.0,
        qualifies=True,
        rationale="Qualified",
    )
    decision = decide_entry(
        prices=[0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        bid=0.49,
        ask=0.51,
        metrics=metrics,
        config=config,
        risk_allows=True,
        risk_reason="Ok",
        in_cooldown=False,
        depth=500.0,
    )
    assert decision.action == "SKIP"


def test_exit_triggers_take_profit():
    config = BotConfig()
    now = datetime.now(tz=timezone.utc)
    decision, _, _ = decide_exit(
        entry_price=0.5,
        current_price=0.53,
        side="buy",
        opened_at=now - timedelta(seconds=60),
        now=now,
        config=config.exit,
        peak_pnl_pct=0.0,
        trailing_stop_pct=None,
        time_to_resolution_minutes=120,
        bid=0.52,
        ask=0.53,
    )
    assert decision.action == "TAKE_PROFIT"


def test_exit_triggers_time_exit():
    config = BotConfig()
    now = datetime.now(tz=timezone.utc)
    decision, _, _ = decide_exit(
        entry_price=0.5,
        current_price=0.5,
        side="buy",
        opened_at=now - timedelta(seconds=config.exit.max_hold_seconds + 1),
        now=now,
        config=config.exit,
        peak_pnl_pct=0.0,
        trailing_stop_pct=None,
        time_to_resolution_minutes=120,
        bid=0.5,
        ask=0.51,
    )
    assert decision.action == "TIME_EXIT"


def test_order_ttl_replace_loop():
    state = DummyState()
    order_id, status = asyncio.run(place_order_with_ttl(state, "TEST", "buy", 0.5))
    assert status == "filled"
    assert order_id == "order-3"
    assert len(state.broker.cancelled) == 2
