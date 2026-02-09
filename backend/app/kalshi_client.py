from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .logging_utils import log_event
from .market_data import DEMO_MARKETS, DemoMarket, MarketInfo, demo_spread, deterministic_mid_price


class KalshiClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("KALSHI_BASE_URL", "https://trading-api.kalshi.com/trade-api/v2")
        self.api_key = os.getenv("KALSHI_API_KEY")
        self.api_secret = os.getenv("KALSHI_API_SECRET")
        self.max_retries = int(os.getenv("KALSHI_MAX_RETRIES", "4"))

    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _signature_headers(self, method: str, path: str, body: str) -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{path}{body}"
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "KALSHI-ACCESS-KEY": self.api_key or "",
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload) if payload else ""
        headers = {"Content-Type": "application/json"}
        if self.configured():
            headers.update(self._signature_headers(method, path, body))
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = requests.request(
                    method,
                    url,
                    params=params,
                    data=body if payload else None,
                    headers=headers,
                    timeout=15,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"Retryable status: {response.status_code}")
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                backoff = (2 ** attempt) + random.uniform(0.2, 0.8)
                time.sleep(backoff)
        log_event("kalshi_request_failed", {"path": path, "error": str(last_error)})
        raise RuntimeError("Kalshi API request failed") from last_error

    def list_markets(self, event_type: str, time_window_hours: int) -> List[MarketInfo]:
        if not self.configured():
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

        data = self._request(
            "GET",
            "/markets",
            params={"category": event_type, "duration": time_window_hours},
        )
        markets = []
        for item in data.get("markets", []):
            markets.append(
                MarketInfo(
                    market_id=item.get("ticker", item.get("id", "")),
                    name=item.get("title", "Unknown"),
                    category=event_type,
                    time_to_resolution_minutes=float(item.get("minutes_to_expiry", 60.0)),
                )
            )
        return markets

    def get_market_snapshot(self, market: MarketInfo | DemoMarket) -> Dict[str, float]:
        if not self.configured():
            timestamp = datetime.now(tz=timezone.utc)
            mid = deterministic_mid_price(market, timestamp)  # type: ignore[arg-type]
            spread = demo_spread(mid)
            return {
                "mid": mid,
                "bid": round(mid - spread / 2, 4),
                "ask": round(mid + spread / 2, 4),
                "last": mid,
                "volume": 200.0,
                "bid_depth": 200.0,
                "ask_depth": 200.0,
                "time_to_resolution_minutes": getattr(market, "time_to_resolution_minutes", 60.0),
            }

        payload = self._request("GET", f"/markets/{market.market_id}")
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

    def get_account(self) -> Optional[Dict[str, Any]]:
        if not self.configured():
            return None
        return self._request("GET", "/account")

    def place_order(self, market_id: str, side: str, price: float, qty: int, order_type: str) -> Dict[str, Any]:
        payload = {
            "ticker": market_id,
            "side": side,
            "type": order_type,
            "price": price,
            "size": qty,
        }
        return self._request("POST", "/orders", payload=payload)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/orders/{order_id}")

    def get_open_orders(self) -> List[Dict[str, Any]]:
        payload = self._request("GET", "/orders", params={"status": "open"})
        return payload.get("orders", [])

    def get_positions(self) -> List[Dict[str, Any]]:
        payload = self._request("GET", "/positions")
        return payload.get("positions", [])

    def get_fills(self, since: Optional[int] = None) -> List[Dict[str, Any]]:
        params = {"since": since} if since else None
        payload = self._request("GET", "/fills", params=params)
        return payload.get("fills", [])
