from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, PositiveInt


class RiskLimits(BaseModel):
    max_exposure_pct: float = Field(8.0, ge=0.0, le=100.0)
    max_concurrent_positions: PositiveInt = 2
    max_consecutive_losses: PositiveInt = 2
    max_event_drawdown_pct: float = Field(6.0, ge=0.0, le=100.0)
    per_event_loss_cap_pct: float = Field(4.0, ge=0.0, le=100.0)
    kill_switch: bool = False


class TradeParams(BaseModel):
    take_profit_pct: float = Field(4.0, ge=0.1, le=50.0)
    stop_loss_pct: float = Field(3.0, ge=0.1, le=50.0)
    order_ttl_seconds: PositiveInt = 30
    limit_edge_pct: float = Field(0.3, ge=0.0, le=5.0)
    cooldown_seconds: PositiveInt = 20
    max_trades_per_event: PositiveInt = 6


class BotConfig(BaseModel):
    event_focus: str = "sports"
    volatility_threshold: float = Field(6.0, ge=0.1, le=25.0)
    cadence_seconds: PositiveInt = 30
    target_gains: str = "5-6 trades aiming for 3-5% each"
    paper_trading: bool = True
    risk_notes: str = ""
    liquidity_min_volume: float = Field(100.0, ge=0.0)
    max_spread_pct: float = Field(6.0, ge=0.1, le=50.0)
    use_openai: bool = False
    openai_context_source: Optional[str] = None
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)
    trade_params: TradeParams = Field(default_factory=TradeParams)


class MarketSnapshot(BaseModel):
    market_id: str
    name: str
    type: str
    mid_price: float
    bid: float
    ask: float
    volume: float
    volatility_percent: float
    volatility_score: float
    signal: str
    threshold: float
    time_to_expiry_hours: float


class Position(BaseModel):
    position_id: str
    market_id: str
    market_name: str
    entry_price: float
    current_price: float
    take_profit_pct: float
    stop_loss_pct: float
    opened_at: datetime
    status: str = "open"
    pnl_pct: float = 0.0


class Order(BaseModel):
    order_id: str
    market_id: str
    side: str
    price: float
    size: int
    status: str
    created_at: datetime
    filled_at: Optional[datetime] = None


class ActivityEntry(BaseModel):
    timestamp: datetime
    message: str
    category: str = "info"


class ScanSnapshot(BaseModel):
    timestamp: datetime
    markets: List[MarketSnapshot]


class StatusSnapshot(BaseModel):
    status: str
    trades_executed: int
    open_positions: int
    event_pnl_pct: float
    high_vol_count: int
    sentiment_label: str
    next_action: str
    risk_mode: str
    paper_trading: bool


class HealthStatus(BaseModel):
    status: str
    kalshi_configured: bool
    openai_configured: bool
