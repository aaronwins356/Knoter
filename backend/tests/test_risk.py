from app.models import RiskLimits
from app.risk import RiskManager


def test_risk_manager_blocks_after_losses():
    limits = RiskLimits(max_consecutive_losses=2)
    manager = RiskManager(limits)
    manager.record_trade(-3.0)
    manager.record_trade(-2.0)
    assert manager.can_trade() is False


def test_risk_manager_allows_when_under_limits():
    limits = RiskLimits(max_exposure_pct=10.0, max_concurrent_positions=2)
    manager = RiskManager(limits)
    manager.update_exposure(exposure_pct=4.0, active_positions=1)
    assert manager.can_trade() is True
