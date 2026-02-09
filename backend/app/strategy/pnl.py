from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from ..models import Position
from .engine import compute_pnl_pct


def compute_realized_pnl_pct(fills: Iterable[dict]) -> float:
    inventory: Dict[Tuple[str, str], Dict[str, float]] = {}
    realized_weighted = 0.0
    realized_qty = 0.0
    for fill in fills:
        market_id = fill.get("market_id")
        side = fill.get("side")
        action = fill.get("action")
        qty = fill.get("qty") or fill.get("size") or fill.get("count")
        price = fill.get("price")
        if not market_id or not side or not action or qty is None or price is None:
            continue
        key = (market_id, side)
        position = inventory.setdefault(key, {"qty": 0.0, "avg": 0.0})
        qty = float(qty)
        price = float(price)
        if action == "buy":
            new_qty = position["qty"] + qty
            if new_qty > 0:
                position["avg"] = (position["avg"] * position["qty"] + price * qty) / new_qty
            position["qty"] = new_qty
        elif action == "sell":
            matched = min(position["qty"], qty)
            if matched > 0:
                pnl_pct = compute_pnl_pct(position["avg"], price, side)
                realized_weighted += pnl_pct * matched
                realized_qty += matched
                position["qty"] -= matched
            if qty > matched:
                position["qty"] = 0.0
                position["avg"] = price
    if realized_qty == 0:
        return 0.0
    return round(realized_weighted / realized_qty, 4)


def compute_unrealized_pnl_pct(positions: Iterable[Position]) -> float:
    weighted = 0.0
    qty_total = 0.0
    for position in positions:
        if position.status != "open":
            continue
        qty = float(position.qty)
        pnl_pct = compute_pnl_pct(position.entry_price, position.current_price, position.side)
        weighted += pnl_pct * qty
        qty_total += qty
    if qty_total == 0:
        return 0.0
    return round(weighted / qty_total, 4)
