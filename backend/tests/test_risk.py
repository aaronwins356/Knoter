from datetime import datetime, timedelta, timezone

from app.models import RiskLimits
from app.risk.risk_manager import RiskManager


def test_risk_manager_blocks_after_losses():
    limits = RiskLimits(max_consecutive_losses=2)
    manager = RiskManager(limits)
    manager.record_trade(-3.0)
    manager.record_trade(-2.0)
    allowed, _ = manager.can_trade()
    assert allowed is False


def test_risk_manager_blocks_on_session_loss():
    limits = RiskLimits(max_session_loss_pct=4.0, max_event_loss_pct=10.0)
    manager = RiskManager(limits)
    manager.record_trade(-5.0)
    allowed, reason = manager.can_trade()
    assert allowed is False
    assert "Session" in reason


def test_risk_manager_cooldown_enforced():
    limits = RiskLimits(cooldown_after_trade_seconds=30)
    manager = RiskManager(limits)
    manager.record_trade(1.0)
    manager.state.last_trade_time = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
    allowed, reason = manager.can_trade()
    assert allowed is False
    assert "Cooldown" in reason


def test_risk_manager_blocks_on_max_positions():
    limits = RiskLimits(max_concurrent_positions=1)
    manager = RiskManager(limits)
    manager.update_exposure(exposure_contracts=0, exposure_dollars=0.0, active_positions=1)
    allowed, reason = manager.can_trade()
    assert allowed is False
    assert "positions" in reason.lower()


def test_risk_manager_blocks_on_exposure_dollars():
    limits = RiskLimits(max_exposure_dollars=100.0)
    manager = RiskManager(limits)
    manager.update_exposure(exposure_contracts=0, exposure_dollars=150.0, active_positions=0)
    allowed, reason = manager.can_trade()
    assert allowed is False
    assert "Exposure dollars" in reason
