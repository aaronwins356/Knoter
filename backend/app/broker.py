from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

from .models import Order, TradeParams


class PaperBroker:
    def __init__(self, trade_params: TradeParams) -> None:
        self.trade_params = trade_params

    def execute_order(self, market_id: str, side: str, mid_price: float) -> Order:
        edge = self.trade_params.limit_edge_pct / 100
        fill_price = mid_price + edge if side == "buy" else mid_price - edge
        now = datetime.now(tz=timezone.utc)
        return Order(
            order_id=f"paper-{market_id}-{int(now.timestamp())}",
            market_id=market_id,
            side=side,
            price=round(fill_price, 4),
            size=1,
            status="filled",
            created_at=now,
            filled_at=now,
        )
