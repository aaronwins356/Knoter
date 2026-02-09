from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..kalshi_client import KalshiClient
from ..logging_utils import log_event
from ..market_data import MarketInfo


@dataclass
class KalshiAuthStatus:
    connected: bool
    environment: str
    account_masked: Optional[str]
    last_error_summary: Optional[str]


class KalshiBroker:
    def __init__(self, client: KalshiClient, live_gate_enabled: bool, live_confirm: str) -> None:
        self.client = client
        self.live_gate_enabled = live_gate_enabled
        self.live_confirm = live_confirm

    def configured(self) -> bool:
        return self.client.configured()

    def _ensure_live_gate(self) -> None:
        if not self.live_gate_enabled or self.live_confirm != "ENABLE LIVE TRADING":
            raise RuntimeError("Live trading is not enabled")
        if self.client.environment_label() != "live":
            raise RuntimeError("Live trading is not enabled")

    def list_markets(self, event_type: str, time_window_hours: int) -> List[MarketInfo]:
        data = self.client.list_markets(
            params={"category": event_type, "duration": time_window_hours},
            fetch_all=True,
        )
        markets = []
        for item in data:
            markets.append(
                MarketInfo(
                    market_id=item.get("ticker", item.get("id", "")),
                    name=item.get("title", "Unknown"),
                    category=event_type,
                    time_to_resolution_minutes=float(item.get("minutes_to_expiry", 60.0)),
                )
            )
        return markets

    def get_market_snapshot(self, ticker: str) -> Dict[str, Any]:
        payload = self.client.get_market(ticker)
        mid = payload.get("mid_price", payload.get("last_price", 0.5))
        bid = payload.get("yes_bid", mid - 0.01)
        ask = payload.get("yes_ask", mid + 0.01)
        return {
            "mid": float(mid),
            "bid": float(bid),
            "ask": float(ask),
            "last": float(payload.get("last_price", mid)),
            "volume": float(payload.get("volume", 0.0)),
            "bid_depth": float(payload.get("bid_depth", 0.0)),
            "ask_depth": float(payload.get("ask_depth", 0.0)),
            "time_to_resolution_minutes": float(payload.get("minutes_to_expiry", 60.0)),
        }

    def place_order(self, ticker: str, action: str, side: str, price: float, qty: int) -> Dict[str, Any]:
        self._ensure_live_gate()
        payload = self.client.format_order_payload(ticker, action, side, price, qty, order_type="limit")
        response = self.client.place_order(payload)
        return {
            "order_id": response.get("order_id", response.get("id", "")),
            "status": response.get("status", "open"),
            "filled_qty": response.get("filled_size", 0) or 0,
            "avg_fill_price": response.get("avg_fill_price"),
        }

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self.client.cancel_order(order_id)

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return self.client.get_open_orders()

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self.client.get_order(order_id)

    def get_positions(self) -> List[Dict[str, Any]]:
        return self.client.get_positions()

    def get_fills(self, since: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.client.get_fills(since)

    def auth_status(self) -> KalshiAuthStatus:
        if not self.client.configured():
            return KalshiAuthStatus(
                connected=False,
                environment=self.client.environment_label(),
                account_masked=None,
                last_error_summary="Missing credentials",
            )
        try:
            payload = self.client.get_portfolio_balance()
            handle = payload.get("member_id") or payload.get("email") or payload.get("account_id")
            masked = None
            if handle:
                handle = str(handle)
                masked = f"{handle[:2]}***{handle[-2:]}" if len(handle) > 4 else "***"
            return KalshiAuthStatus(
                connected=True,
                environment=self.client.environment_label(),
                account_masked=masked,
                last_error_summary=self.client.last_error,
            )
        except Exception as exc:  # noqa: BLE001
            self.client.last_error = str(exc)
            return KalshiAuthStatus(
                connected=False,
                environment=self.client.environment_label(),
                account_masked=None,
                last_error_summary=self.client.last_error,
            )
