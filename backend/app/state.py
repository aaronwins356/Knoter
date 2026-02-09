from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from .broker import PaperBroker
from .config import load_config
from .kalshi_client import KalshiClient
from .models import ActivityEntry, BotConfig, MarketSnapshot, Order, Position, ScanSnapshot, StatusSnapshot
from .openai_client import OpenAIClient
from .risk import RiskManager
from .storage import fetch_activity, init_db


@dataclass
class MarketState:
    prices: Deque[float] = field(default_factory=lambda: deque(maxlen=20))
    spreads: Deque[float] = field(default_factory=lambda: deque(maxlen=20))
    update_count: int = 0
    last_snapshot: Optional[MarketSnapshot] = None


class BotState:
    def __init__(self) -> None:
        init_db()
        self.config: BotConfig = load_config()
        self.kalshi = KalshiClient()
        self.openai = OpenAIClient()
        self.paper_broker = PaperBroker(self.config.trade_params)
        self.risk = RiskManager(self.config.risk_limits)
        self.running: bool = False
        self.task = None
        self.market_state: Dict[str, MarketState] = {}
        self.last_scan: Optional[ScanSnapshot] = None
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        self.activity: Deque[ActivityEntry] = deque(fetch_activity(limit=20), maxlen=50)
        self.trades_executed = 0
        self.event_pnl_pct = 0.0
        self.sentiment_label = "Waiting"
        self.next_action = "Configure bot"

    def status_snapshot(self) -> StatusSnapshot:
        return StatusSnapshot(
            status="Running" if self.running else "Paused",
            trades_executed=self.trades_executed,
            open_positions=len([pos for pos in self.positions.values() if pos.status == "open"]),
            event_pnl_pct=self.event_pnl_pct,
            high_vol_count=len(
                [market for market in (self.last_scan.markets if self.last_scan else []) if market.signal != "Standby"]
            ),
            sentiment_label=self.sentiment_label,
            next_action=self.next_action,
            risk_mode=self.risk.risk_mode(),
            paper_trading=self.config.paper_trading,
        )

    def add_activity(self, message: str, category: str = "info") -> ActivityEntry:
        entry = ActivityEntry(timestamp=datetime.now(tz=timezone.utc), message=message, category=category)
        self.activity.appendleft(entry)
        return entry

    def activity_entries(self) -> List[ActivityEntry]:
        return list(self.activity)
