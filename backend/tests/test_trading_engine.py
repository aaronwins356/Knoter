from datetime import datetime, timedelta, timezone
import asyncio

from app.execution.order_manager import OrderManager
from app.models import BotConfig
from app.strategy.engine import decide_entry, decide_exit


class FakeBroker:
    def __init__(self) -> None:
        self.calls = 0
        self.cancelled = []

    def place_order(self, ticker, action, side, price, qty):
        self.calls += 1
        status = "open" if self.calls < 3 else "filled"
        return {"order_id": f"order-{self.calls}", "status": status, "filled_qty": qty if status == "filled" else 0}

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return {"status": "cancelled"}


class DummyState:
    def __init__(self) -> None:
        self.config = BotConfig()
        self.config.entry.max_replacements = 2
        self.config.entry.order_ttl_seconds = 0
        self.broker = FakeBroker()


def test_entry_decision_requires_momentum():
    config = BotConfig()
    decision = decide_entry(
        prices=[0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        bid=0.49,
        ask=0.51,
        config=config,
        risk_allows=True,
        risk_reason="Ok",
        in_cooldown=False,
        expected_edge_cost_pct=0.2,
    )
    assert decision.action == "SKIP"


def test_exit_triggers_take_profit():
    config = BotConfig()
    now = datetime.now(tz=timezone.utc)
    decision, _, _ = decide_exit(
        entry_price=0.5,
        current_price=0.53,
        side="yes",
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
        side="yes",
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


def test_exit_triggers_stop_loss():
    config = BotConfig()
    now = datetime.now(tz=timezone.utc)
    decision, _, _ = decide_exit(
        entry_price=0.5,
        current_price=0.47,
        side="yes",
        opened_at=now - timedelta(seconds=60),
        now=now,
        config=config.exit,
        peak_pnl_pct=0.0,
        trailing_stop_pct=None,
        time_to_resolution_minutes=120,
        bid=0.47,
        ask=0.48,
    )
    assert decision.action == "STOP_LOSS"


def test_exit_triggers_late_event():
    config = BotConfig()
    now = datetime.now(tz=timezone.utc)
    decision, _, _ = decide_exit(
        entry_price=0.5,
        current_price=0.5,
        side="yes",
        opened_at=now - timedelta(seconds=60),
        now=now,
        config=config.exit,
        peak_pnl_pct=0.0,
        trailing_stop_pct=None,
        time_to_resolution_minutes=30,
        bid=0.5,
        ask=0.51,
    )
    assert decision.action == "LATE_EXIT"


def test_exit_triggers_trailing_stop():
    config = BotConfig()
    now = datetime.now(tz=timezone.utc)
    decision, _, trail_stop = decide_exit(
        entry_price=0.5,
        current_price=0.515,
        side="yes",
        opened_at=now - timedelta(seconds=60),
        now=now,
        config=config.exit,
        peak_pnl_pct=5.0,
        trailing_stop_pct=4.0,
        time_to_resolution_minutes=120,
        bid=0.514,
        ask=0.515,
    )
    assert decision.action == "TRAIL_STOP"
    assert trail_stop is not None


def test_order_ttl_replace_loop():
    state = DummyState()
    manager = OrderManager(state.broker, state.config)
    result = asyncio.run(manager.place_with_ttl("TEST", "buy", "yes", 0.5))
    assert result.status == "filled"
    assert result.order_id == "order-3"
    assert len(state.broker.cancelled) == 2
