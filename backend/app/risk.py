from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .models import RiskLimits


@dataclass
class RiskState:
    consecutive_losses: int = 0
    event_pnl_pct: float = 0.0
    session_pnl_pct: float = 0.0
    exposure_contracts: int = 0
    exposure_dollars: float = 0.0
    active_positions: int = 0
    trade_history: List[float] = field(default_factory=list)
    last_trade_time: Optional[datetime] = None


class RiskManager:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self.state = RiskState()

    def record_trade(self, pnl_pct: float) -> None:
        self.state.trade_history.append(pnl_pct)
        self.state.session_pnl_pct += pnl_pct
        self.state.event_pnl_pct += pnl_pct
        if pnl_pct < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        self.state.last_trade_time = datetime.now(tz=timezone.utc)

    def update_exposure(
        self,
        exposure_contracts: int,
        exposure_dollars: float,
        active_positions: int,
    ) -> None:
        self.state.exposure_contracts = exposure_contracts
        self.state.exposure_dollars = exposure_dollars
        self.state.active_positions = active_positions

    def reset_event(self) -> None:
        self.state.event_pnl_pct = 0.0
        self.state.consecutive_losses = 0
        self.state.trade_history.clear()

    def in_cooldown(self) -> bool:
        if not self.state.last_trade_time:
            return False
        elapsed = (datetime.now(tz=timezone.utc) - self.state.last_trade_time).total_seconds()
        return elapsed < self.limits.cooldown_after_trade_seconds

    def can_trade(self) -> Tuple[bool, str]:
        if self.limits.kill_switch:
            return False, "Kill switch active"
        if self.state.exposure_contracts >= self.limits.max_exposure_contracts:
            return False, "Exposure contracts limit reached"
        if self.state.exposure_dollars >= self.limits.max_exposure_dollars:
            return False, "Exposure dollars limit reached"
        if self.state.active_positions >= self.limits.max_concurrent_positions:
            return False, "Max concurrent positions reached"
        if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
            return False, "Loss streak limit reached"
        if abs(self.state.event_pnl_pct) >= self.limits.max_event_loss_pct:
            return False, "Event loss cap reached"
        if abs(self.state.session_pnl_pct) >= self.limits.max_session_loss_pct:
            return False, "Session loss cap reached"
        if self.in_cooldown():
            return False, "Cooldown active"
        return True, "Ok"

    def risk_mode(self) -> str:
        if self.limits.kill_switch:
            return "Kill-switch"
        if self.state.consecutive_losses > 0:
            return "Cautious"
        return "Conservative"
