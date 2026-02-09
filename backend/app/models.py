from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, PositiveInt


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class MarketFilters(BaseModel):
    event_type: str = "sports"
    time_window_hours: PositiveInt = 24


class ScoringWeights(BaseModel):
    volatility: float = Field(0.45, ge=0.0, le=1.0)
    spread: float = Field(0.25, ge=0.0, le=1.0)
    liquidity: float = Field(0.3, ge=0.0, le=1.0)
    resolution: float = Field(0.1, ge=0.0, le=1.0)


class ScoringConfig(BaseModel):
    vol_window: PositiveInt = 20
    vol_threshold: float = Field(1.5, ge=0.1, le=25.0)
    max_spread_pct: float = Field(6.0, ge=0.1, le=50.0)
    min_liquidity_score: float = Field(45.0, ge=0.0, le=100.0)
    liquidity_volume_ref: float = Field(200.0, ge=1.0)
    liquidity_depth_ref: float = Field(250.0, ge=1.0)
    liquidity_update_ref: float = Field(1.0, ge=0.1)
    resolution_minutes_ref: float = Field(720.0, ge=1.0)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)


class EntryConfig(BaseModel):
    momentum_window: PositiveInt = 6
    momentum_threshold_pct: float = Field(0.6, ge=0.0, le=10.0)
    entry_edge_pct: float = Field(0.3, ge=0.0, le=5.0)
    fee_pct: float = Field(0.1, ge=0.0, le=5.0)
    order_ttl_seconds: PositiveInt = 30
    max_replacements: PositiveInt = 2
    allow_mean_reversion: bool = False
    min_depth_for_mean_reversion: float = Field(200.0, ge=0.0)


class ExitConfig(BaseModel):
    take_profit_pct: float = Field(4.0, ge=0.1, le=50.0)
    stop_loss_pct: float = Field(3.0, ge=0.1, le=50.0)
    max_hold_seconds: PositiveInt = 900
    close_before_resolution_minutes: PositiveInt = 60
    trail_start_pct: float = Field(2.0, ge=0.0, le=50.0)
    trail_gap_pct: float = Field(1.0, ge=0.1, le=25.0)
    close_slippage_pct: float = Field(0.4, ge=0.0, le=5.0)
    max_close_requotes: PositiveInt = 2


class RiskLimits(BaseModel):
    max_exposure_contracts: PositiveInt = 4
    max_exposure_dollars: float = Field(400.0, ge=0.0, le=1000000.0)
    max_concurrent_positions: PositiveInt = 2
    max_trades_per_event: PositiveInt = 6
    max_consecutive_losses: PositiveInt = 2
    max_event_loss_pct: float = Field(5.0, ge=0.0, le=100.0)
    max_session_loss_pct: float = Field(8.0, ge=0.0, le=100.0)
    cooldown_after_trade_seconds: PositiveInt = 20
    kill_switch: bool = False


class TradeSizing(BaseModel):
    order_size: PositiveInt = 1


class AdvisorConfig(BaseModel):
    enabled: bool = False


class BotConfig(BaseModel):
    market_filters: MarketFilters = Field(default_factory=MarketFilters)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    entry: EntryConfig = Field(default_factory=EntryConfig)
    exit: ExitConfig = Field(default_factory=ExitConfig)
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)
    trade_sizing: TradeSizing = Field(default_factory=TradeSizing)
    cadence_seconds: PositiveInt = 30
    target_gains: str = "5-6 trades aiming for 3-5% each"
    risk_notes: str = ""
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_enabled: bool = False
    live_confirm: str = ""
    advisor: AdvisorConfig = Field(default_factory=AdvisorConfig)


class MarketSnapshot(BaseModel):
    market_id: str
    name: str
    category: str
    mid_price: float
    bid: float
    ask: float
    last_price: float
    volume: float
    bid_depth: float
    ask_depth: float
    volatility_pct: float
    spread_pct: float
    liquidity_score: float
    overall_score: float
    qualifies: bool
    rationale: str
    time_to_resolution_minutes: float


class Position(BaseModel):
    position_id: str
    market_id: str
    market_name: str
    side: str
    qty: int
    entry_price: float
    current_price: float
    take_profit_pct: float
    stop_loss_pct: float
    max_hold_seconds: int = 0
    close_before_resolution_minutes: int = 0
    opened_at: datetime
    status: str = "open"
    pnl_pct: float = 0.0
    peak_pnl_pct: float = 0.0
    trail_stop_pct: Optional[float] = None
    closed_at: Optional[datetime] = None


class Order(BaseModel):
    order_id: str
    market_id: str
    action: str
    side: str
    price: float
    qty: int
    status: str
    created_at: datetime
    filled_at: Optional[datetime] = None


class ActivityEntry(BaseModel):
    timestamp: datetime
    message: str
    category: str = "info"


class AuditRecord(BaseModel):
    timestamp: datetime
    market_id: str
    action: str
    qualifies: bool
    scores: dict
    rationale: str
    config_hash: str
    order_ids: List[str] = Field(default_factory=list)
    fills: List[dict] = Field(default_factory=list)
    advisory: Optional[dict] = None


class DecisionRecord(BaseModel):
    timestamp: datetime
    market_id: str
    action: str
    qualifies: bool
    scores: dict
    rationale: str
    config_hash: str
    order_ids: List[str] = Field(default_factory=list)
    fills: List[dict] = Field(default_factory=list)
    advisory: Optional[dict] = None


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
    trading_mode: TradingMode
    live_trading_enabled: bool


class HealthStatus(BaseModel):
    status: str
    kalshi_configured: bool
    openai_configured: bool


class KalshiStatus(BaseModel):
    connected: bool
    environment: str
    account_masked: Optional[str] = None
    last_error_summary: Optional[str] = None
    mode: TradingMode


class AdvisorOutput(BaseModel):
    sentiment: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str
    veto: bool = False


class DryRunResult(BaseModel):
    scan: ScanSnapshot
    decisions: List[DecisionRecord]
