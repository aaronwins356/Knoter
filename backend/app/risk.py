from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .models import RiskLimits


@dataclass
class RiskState:
    consecutive_losses: int = 0
    event_drawdown_pct: float = 0.0
    exposure_pct: float = 0.0
    active_positions: int = 0
    trade_history: List[float] = field(default_factory=list)


class RiskManager:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self.state = RiskState()

    def record_trade(self, pnl_pct: float) -> None:
        self.state.trade_history.append(pnl_pct)
        if pnl_pct < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        self.state.event_drawdown_pct = min(0.0, sum(self.state.trade_history))

    def update_exposure(self, exposure_pct: float, active_positions: int) -> None:
        self.state.exposure_pct = exposure_pct
        self.state.active_positions = active_positions

    def reset_event(self) -> None:
        self.state = RiskState()

    def can_trade(self) -> bool:
        if self.limits.kill_switch:
            return False
        if self.state.exposure_pct >= self.limits.max_exposure_pct:
            return False
        if self.state.active_positions >= self.limits.max_concurrent_positions:
            return False
        if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
            return False
        if abs(self.state.event_drawdown_pct) >= self.limits.max_event_drawdown_pct:
            return False
        return True

    def risk_mode(self) -> str:
        if self.limits.kill_switch:
            return "Kill-switch"
        if self.state.consecutive_losses > 0:
            return "Cautious"
        return "Conservative"
