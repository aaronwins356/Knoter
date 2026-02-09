from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..logging_utils import log_event
from ..market_data import MarketInfo


@dataclass
class KalshiAuthStatus:
    connected: bool
    environment: str
    account_masked: Optional[str]
    last_error_summary: Optional[str]


class KalshiClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("KALSHI_BASE_URL", "https://trading-api.kalshi.com/trade-api/v2")
        self.api_key = os.getenv("KALSHI_API_KEY")
        self.private_key = self._load_private_key()
        self.max_retries = int(os.getenv("KALSHI_MAX_RETRIES", "3"))
        self.last_error: Optional[str] = None

    def _load_private_key(self):
        pem_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        pem_data = os.getenv("KALSHI_PRIVATE_KEY_PEM")
        raw = None
        if pem_path:
            with open(pem_path, "rb") as handle:
                raw = handle.read()
        elif pem_data:
            raw = pem_data.encode()
        if not raw:
            return None
        return serialization.load_pem_private_key(raw, password=None)

    def configured(self) -> bool:
        return bool(self.api_key and self.private_key)

    def environment_label(self) -> str:
        host = urlparse(self.base_url).hostname or ""
        if "sandbox" in host or "demo" in host or "paper" in host:
            return "paper"
        return "live"

    def _signature_headers(self, method: str, path: str) -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{path}"
        signature = base64.b64encode(
            self.private_key.sign(
                message.encode(),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
        ).decode()
        return {
            "KALSHI-ACCESS-KEY": self.api_key or "",
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 20,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload) if payload else None
        headers = {"Content-Type": "application/json"}
        if self.configured():
            headers.update(self._signature_headers(method, path))
        self.last_error = None
        for attempt in range(self.max_retries):
            try:
                response = requests.request(
                    method,
                    url,
                    params=params,
                    data=body,
                    headers=headers,
                    timeout=timeout,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"Retryable status: {response.status_code}")
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                self.last_error = str(exc)
                if attempt >= self.max_retries - 1:
                    break
                time.sleep(1 + attempt)
        log_event("kalshi_request_failed", {"path": path, "error": self.last_error})
        raise RuntimeError("Kalshi API request failed")

    def get_portfolio_balance(self) -> Dict[str, Any]:
        return self._request("GET", "/portfolio/balance")

    def list_markets(self, event_type: str, time_window_hours: int) -> List[Dict[str, Any]]:
        return self._request(
            "GET",
            "/markets",
            params={"category": event_type, "duration": time_window_hours},
        ).get("markets", [])

    def get_market(self, ticker: str) -> Dict[str, Any]:
        return self._request("GET", f"/markets/{ticker}")

    def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/orders", payload=payload)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/orders/{order_id}")

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/orders", params={"status": "open"}).get("orders", [])

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/orders/{order_id}")

    def get_positions(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/positions").get("positions", [])

    def get_fills(self, since: Optional[int] = None) -> List[Dict[str, Any]]:
        params = {"since": since} if since else None
        return self._request("GET", "/fills", params=params).get("fills", [])


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

    def list_markets(self, event_type: str, time_window_hours: int) -> List[MarketInfo]:
        data = self.client.list_markets(event_type, time_window_hours)
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
        payload = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "type": "limit",
            "price": round(price, 4),
            "size": qty,
        }
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
