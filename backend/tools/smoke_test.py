from __future__ import annotations

__test__ = False

import os
import sys
from typing import Any, Dict

import requests


def _print_step(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")


def _base_url() -> str:
    return os.getenv("KNOTER_API_URL", "http://localhost:8000")


def _get(path: str) -> requests.Response:
    return requests.get(f"{_base_url()}{path}", timeout=10)


def _post(path: str, payload: Dict[str, Any] | None = None) -> requests.Response:
    return requests.post(f"{_base_url()}{path}", json=payload, timeout=10)


def run() -> int:
    try:
        health = _get("/health")
        _print_step("/health", health.ok, str(health.status_code))
        if not health.ok:
            return 1
    except Exception as exc:  # noqa: BLE001
        _print_step("/health", False, str(exc))
        return 1

    creds_present = bool(os.getenv("KALSHI_API_KEY_ID") or os.getenv("KALSHI_API_KEY"))
    if creds_present:
        try:
            status = _get("/kalshi/status")
            ok = status.ok and status.json().get("connected") is True
            _print_step("/kalshi/status", ok, status.text[:200])
            if not ok:
                return 1
        except Exception as exc:  # noqa: BLE001
            _print_step("/kalshi/status", False, str(exc))
            return 1
    else:
        _print_step("/kalshi/status", True, "Skipped (no credentials)")

    try:
        scan = _get("/markets/scan")
        scan_data = scan.json() if scan.ok else {}
        markets = scan_data.get("markets") or []
        if not markets:
            _print_step("/markets/scan", False, "Empty scan (run /bot/dryrun next)")
        else:
            _print_step("/markets/scan", True, f"markets={len(markets)}")
    except Exception as exc:  # noqa: BLE001
        _print_step("/markets/scan", False, str(exc))
        return 1

    try:
        dryrun = _post("/bot/dryrun")
        ok = dryrun.ok and dryrun.json().get("scan", {}).get("markets")
        _print_step("/bot/dryrun", bool(ok), dryrun.text[:200])
        if not ok:
            return 1
    except Exception as exc:  # noqa: BLE001
        _print_step("/bot/dryrun", False, str(exc))
        return 1

    try:
        config = _get("/config")
        if not config.ok:
            _print_step("/config", False, config.text[:200])
            return 1
        config_data = config.json()
        if config_data.get("trading_mode") != "paper":
            _print_step("paper order", False, "Trading mode is not paper")
            return 1
    except Exception as exc:  # noqa: BLE001
        _print_step("/config", False, str(exc))
        return 1

    try:
        scan_data = dryrun.json().get("scan", {})
        first_market = (scan_data.get("markets") or [{}])[0]
        ticker = first_market.get("market_id") or first_market.get("ticker")
        if not ticker:
            _print_step("paper order", False, "Missing ticker from scan")
            return 1
        order = _post(
            "/orders/place",
            {"ticker": ticker, "side": "yes", "action": "buy", "price": 0.51, "qty": 1},
        )
        if not order.ok:
            _print_step("paper order", False, order.text[:200])
            return 1
        order_id = order.json().get("order_id")
        _print_step("paper order", bool(order_id), f"order_id={order_id}")
        if not order_id:
            return 1
        cancel = _post(f"/orders/{order_id}/cancel")
        _print_step("cancel order", cancel.ok, cancel.text[:200])
        if not cancel.ok:
            return 1
        orders = _get("/orders")
        ok = orders.ok and any(item.get("order_id") == order_id for item in orders.json().get("orders", []))
        _print_step("/orders", ok, orders.text[:200])
        if not ok:
            return 1
    except Exception as exc:  # noqa: BLE001
        _print_step("paper order", False, str(exc))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(run())
