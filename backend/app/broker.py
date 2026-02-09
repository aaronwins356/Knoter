from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .kalshi_client import KalshiClient
from .market_data import MarketInfo
from .models import Order


@dataclass
class BrokerOrder:
    order_id: str
    status: str
    raw: Dict[str, str]


class KalshiBroker:
    def __init__(self, client: KalshiClient) -> None:
        self.client = client

    def list_markets(self, event_type: str, time_window_hours: int) -> List[MarketInfo]:
        return self.client.list_markets(event_type, time_window_hours)

    def get_market_snapshot(self, market: MarketInfo) -> Dict[str, float]:
        return self.client.get_market_snapshot(market)

    def get_market(self, market_id: str) -> Dict[str, float]:
        market = MarketInfo(market_id=market_id, name=market_id, category="", time_to_resolution_minutes=60.0)
        return self.client.get_market_snapshot(market)

    def place_order(
        self,
        market_id: str,
        side: str,
        price: float,
        qty: int,
        order_type: str = "limit",
    ) -> Dict[str, str]:
        return self.client.place_order(market_id, side, price, qty, order_type)

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        return self.client.cancel_order(order_id)

    def get_open_orders(self) -> List[Dict[str, str]]:
        return self.client.get_open_orders()

    def get_positions(self) -> List[Dict[str, str]]:
        return self.client.get_positions()

    def get_fills(self, since: Optional[int] = None) -> List[Dict[str, str]]:
        return self.client.get_fills(since)


class PaperBroker:
    def __init__(self) -> None:
        self.orders: Dict[str, Order] = {}

    def list_markets(self, event_type: str, time_window_hours: int) -> List[MarketInfo]:
        from .market_data import DEMO_MARKETS

        return [
            MarketInfo(
                market_id=market.market_id,
                name=market.name,
                category=market.category,
                time_to_resolution_minutes=market.time_to_resolution_minutes,
            )
            for market in DEMO_MARKETS
            if market.category == event_type
        ]

    def get_market_snapshot(self, market: MarketInfo) -> Dict[str, float]:
        from .market_data import DEMO_MARKETS

        demo = next((m for m in DEMO_MARKETS if m.market_id == market.market_id), None)
        if not demo:
            return {}
        from .kalshi_client import KalshiClient

        return KalshiClient().get_market_snapshot(demo)

    def get_market(self, market_id: str) -> Dict[str, float]:
        market = MarketInfo(market_id=market_id, name=market_id, category="", time_to_resolution_minutes=60.0)
        return self.get_market_snapshot(market)

    def place_order(
        self,
        market_id: str,
        side: str,
        price: float,
        qty: int,
        order_type: str = "limit",
    ) -> Dict[str, str]:
        now = datetime.now(tz=timezone.utc)
        order = Order(
            order_id=f"paper-{market_id}-{int(now.timestamp() * 1000)}",
            market_id=market_id,
            side=side,
            price=round(price, 4),
            qty=qty,
            status="filled",
            created_at=now,
            filled_at=now,
        )
        self.orders[order.order_id] = order
        return {
            "order_id": order.order_id,
            "status": order.status,
            "filled_at": order.filled_at.isoformat(),
        }

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        order = self.orders.get(order_id)
        if order:
            order.status = "cancelled"
            self.orders[order_id] = order
        return {"order_id": order_id, "status": "cancelled"}

    def get_open_orders(self) -> List[Dict[str, str]]:
        return [
            {"order_id": order.order_id, "status": order.status}
            for order in self.orders.values()
            if order.status == "open"
        ]

    def get_positions(self) -> List[Dict[str, str]]:
        return []

    def get_fills(self, since: Optional[int] = None) -> List[Dict[str, str]]:
        return []
