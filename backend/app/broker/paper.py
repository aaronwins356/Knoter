from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..market_data import DEMO_MARKETS, MarketInfo, MarketQuote, Quote, build_quote_from_prices
from ..models import Order, Position
from ..strategy.engine import compute_pnl_pct


@dataclass
class PaperFill:
    order_id: str
    qty: int
    price: float
    timestamp: datetime


class PaperBroker:
    def __init__(self) -> None:
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        self.fills: List[PaperFill] = []

    def list_markets(self, event_type: str, time_window_hours: int) -> List[MarketInfo]:
        return [
            MarketInfo(
                ticker=market.ticker,
                title=market.name,
                close_ts=None,
                settlement_ts=None,
                status="open",
                yes_subtitle=None,
                no_subtitle=None,
                raw_payload={
                    "ticker": market.ticker,
                    "title": market.name,
                    "category": market.category,
                },
            )
            for market in DEMO_MARKETS
            if market.category == event_type
        ]

    def get_market_snapshot(self, ticker: str) -> MarketQuote:
        from datetime import datetime, timezone

        from ..market_data import demo_spread, deterministic_mid_price

        market = next((m for m in DEMO_MARKETS if m.ticker == ticker), None)
        if not market:
            return MarketQuote(
                quote=build_quote_from_prices(ticker, None, None),
                volume=0.0,
                bid_depth=0.0,
                ask_depth=0.0,
                time_to_resolution_minutes=0.0,
            )
        timestamp = datetime.now(tz=timezone.utc)
        mid = deterministic_mid_price(market, timestamp)
        spread = demo_spread(mid)
        bid = round(mid - spread / 2, 4)
        ask = round(mid + spread / 2, 4)
        quote = build_quote_from_prices(ticker, yes_bid=bid, yes_ask=ask)
        return MarketQuote(
            quote=quote,
            volume=200.0,
            bid_depth=200.0,
            ask_depth=200.0,
            time_to_resolution_minutes=market.time_to_resolution_minutes,
        )

    def place_order(self, ticker: str, action: str, side: str, price: float, qty: int) -> Dict[str, Any]:
        now = datetime.now(tz=timezone.utc)
        order_id = f"paper-{ticker}-{int(now.timestamp() * 1000)}"
        status = "filled" if action == "buy" else "filled"
        order = Order(
            order_id=order_id,
            market_id=ticker,
            action=action,
            side=side,
            price=round(price, 4),
            qty=qty,
            status=status,
            created_at=now,
            filled_at=now if status == "filled" else None,
        )
        self.orders[order_id] = order
        if status == "filled":
            self.fills.append(PaperFill(order_id=order_id, qty=qty, price=price, timestamp=now))
        return {
            "order_id": order_id,
            "status": status,
            "filled_qty": qty if status == "filled" else 0,
            "avg_fill_price": price if status == "filled" else None,
        }

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        order = self.orders.get(order_id)
        if order:
            order.status = "cancelled"
            self.orders[order_id] = order
        return {"order_id": order_id, "status": "cancelled"}

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return [
            {"order_id": order.order_id, "status": order.status}
            for order in self.orders.values()
            if order.status == "open"
        ]

    def get_order(self, order_id: str) -> Dict[str, Any]:
        order = self.orders.get(order_id)
        if not order:
            return {}
        return {
            "order_id": order.order_id,
            "status": order.status,
            "filled_qty": order.qty if order.status == "filled" else 0,
            "avg_fill_price": order.price if order.status == "filled" else None,
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        return []

    def get_fills(self, since: Optional[int] = None) -> List[Dict[str, Any]]:
        return [
            {
                "order_id": fill.order_id,
                "price": fill.price,
                "size": fill.qty,
                "timestamp": fill.timestamp.isoformat(),
            }
            for fill in self.fills
        ]

    def mark_position(self, position: Position, mid_yes: float) -> None:
        current = mid_yes if position.side == "yes" else max(0.0, min(1.0, 1.0 - mid_yes))
        position.current_price = current
        position.pnl_pct = round(compute_pnl_pct(position.entry_price, current, position.side), 4)
