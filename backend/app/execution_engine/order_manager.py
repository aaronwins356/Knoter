from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..models import Order
from ..storage import log_fill, upsert_order


@dataclass
class OrderResult:
    order_id: str
    status: str
    filled_qty: int
    avg_fill_price: Optional[float]


class OrderManager:
    def __init__(self, broker, config) -> None:
        self.broker = broker
        self.config = config

    def _refresh_quote(self, ticker: str) -> Optional[dict]:
        try:
            return self.broker.get_market_snapshot(ticker)
        except Exception:
            return None

    async def place_with_ttl(self, ticker: str, action: str, side: str, price: float) -> OrderResult:
        order_id = ""
        status = "open"
        filled_qty = 0
        avg_fill_price: Optional[float] = None
        remaining_qty = self.config.trade_sizing.order_size
        for attempt in range(self.config.entry.max_replacements + 1):
            quote = self._refresh_quote(ticker)
            if quote:
                if action == "buy":
                    price = min(price, quote["ask"])
                else:
                    price = max(price, quote["bid"])
            now = datetime.now(tz=timezone.utc)
            response = self.broker.place_order(
                ticker,
                action,
                side,
                price,
                remaining_qty,
            )
            order_id = response.get("order_id", "")
            status = response.get("status", "open")
            filled_qty = int(response.get("filled_qty", 0) or 0)
            avg_fill_price = response.get("avg_fill_price")

            order = Order(
                order_id=order_id,
                market_id=ticker,
                action=action,
                side=side,
                price=price,
                qty=remaining_qty,
                status=status,
                created_at=now,
                filled_at=now if status == "filled" else None,
            )
            upsert_order(order)
            if filled_qty:
                log_fill(order_id, ticker, action, side, avg_fill_price or price, filled_qty)
                remaining_qty = max(remaining_qty - filled_qty, 0)
                if remaining_qty == 0:
                    return OrderResult(order_id, "filled", filled_qty, avg_fill_price)

            if attempt < self.config.entry.max_replacements and self.config.entry.order_ttl_seconds > 0:
                await asyncio.sleep(self.config.entry.order_ttl_seconds)
            self.broker.cancel_order(order_id)
        return OrderResult(order_id, status, filled_qty, avg_fill_price)

    async def close_with_limit(
        self,
        ticker: str,
        side: str,
        bid: float,
        ask: float,
        qty: int,
    ) -> OrderResult:
        action = "sell"
        price = bid if side == "yes" else ask
        max_steps = self.config.exit.max_close_requotes
        step_pct = self.config.exit.close_slippage_pct
        current_price = price
        remaining_qty = qty
        for attempt in range(max_steps + 1):
            quote = self._refresh_quote(ticker)
            if quote:
                base_price = quote["bid"] if side == "yes" else quote["ask"]
                step = base_price * (step_pct / 100) * attempt
                current_price = base_price - step if side == "yes" else base_price + step
            response = self.broker.place_order(ticker, action, side, current_price, remaining_qty)
            order_id = response.get("order_id", "")
            status = response.get("status", "open")
            filled_qty = int(response.get("filled_qty", 0) or 0)
            avg_fill_price = response.get("avg_fill_price")
            now = datetime.now(tz=timezone.utc)
            upsert_order(
                Order(
                    order_id=order_id,
                    market_id=ticker,
                    action=action,
                    side=side,
                    price=current_price,
                    qty=remaining_qty,
                    status=status,
                    created_at=now,
                    filled_at=now if status == "filled" else None,
                )
            )
            if filled_qty:
                log_fill(order_id, ticker, action, side, avg_fill_price or current_price, filled_qty)
                remaining_qty = max(remaining_qty - filled_qty, 0)
                if remaining_qty == 0:
                    return OrderResult(order_id, "filled", filled_qty, avg_fill_price)
            if attempt >= max_steps:
                return OrderResult(order_id, status, filled_qty, avg_fill_price)
            if not quote:
                step = current_price * (step_pct / 100)
                current_price = current_price - step if side == "yes" else current_price + step
        return OrderResult(order_id, status, filled_qty, avg_fill_price)
