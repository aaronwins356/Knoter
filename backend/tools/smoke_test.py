from __future__ import annotations

__test__ = False

import os
import sys
from typing import Any, Dict

from app.kalshi_client import KalshiClient


def _print_step(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")


def _require_config(client: KalshiClient) -> bool:
    if not client.configured():
        _print_step("Credentials", False, "Missing KALSHI_API_KEY_ID/KALSHI_API_KEY or private key.")
        return False
    if client.environment_label() != "demo":
        _print_step("Environment", False, "KALSHI_ENV must be demo for smoke test.")
        return False
    _print_step("Credentials", True, "Configured for demo.")
    return True


def _get_first_market(client: KalshiClient) -> Dict[str, Any]:
    markets = client.list_markets(params={"status": "open", "limit": 5}, fetch_all=False)
    return markets[0] if markets else {}


def run() -> int:
    client = KalshiClient()
    if not _require_config(client):
        return 1

    try:
        balance = client.get_portfolio_balance()
        _print_step("Fetch balance", True, f"keys={list(balance.keys())[:3]}")
    except Exception as exc:  # noqa: BLE001
        _print_step("Fetch balance", False, str(exc))
        return 1

    market = _get_first_market(client)
    if not market:
        _print_step("Fetch markets", False, "No markets returned.")
        return 1
    _print_step("Fetch markets", True, market.get("ticker", "unknown"))

    ticker = market.get("ticker") or market.get("id")
    if not ticker:
        _print_step("Market ticker", False, "Missing ticker.")
        return 1

    try:
        details = client.get_market(ticker)
    except Exception as exc:  # noqa: BLE001
        _print_step("Fetch market detail", False, str(exc))
        return 1

    mid = float(details.get("mid_price", details.get("last_price", 0.5)))
    price = max(min(mid - 0.01, 0.99), 0.01)
    payload = client.format_order_payload(ticker, "buy", "yes", price, 1, order_type="limit")

    order_id = None
    try:
        order = client.place_order(payload)
        order_id = order.get("order_id") or order.get("id")
        _print_step("Place order", bool(order_id), f"order_id={order_id}")
    except Exception as exc:  # noqa: BLE001
        _print_step("Place order", False, str(exc))
        return 1

    try:
        cancel = client.cancel_order(order_id)
        _print_step("Cancel order", True, f"status={cancel.get('status')}")
    except Exception as exc:  # noqa: BLE001
        _print_step("Cancel order", False, str(exc))
        return 1

    try:
        orders = client.get_open_orders()
        _print_step("Fetch orders", True, f"open_orders={len(orders)}")
    except Exception as exc:  # noqa: BLE001
        _print_step("Fetch orders", False, str(exc))
        return 1

    try:
        fills = client.get_fills()
        _print_step("Fetch fills", True, f"fills={len(fills)}")
    except Exception as exc:  # noqa: BLE001
        _print_step("Fetch fills", False, str(exc))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(run())
