from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, List

import requests

from .market_data import DEMO_MARKETS, DemoMarket, demo_spread, deterministic_mid_price


class KalshiClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("KALSHI_BASE_URL", "https://trading-api.kalshi.com")
        self.api_key = os.getenv("KALSHI_API_KEY")
        self.api_secret = os.getenv("KALSHI_API_SECRET")

    def configured(self) -> bool:
        return bool(self.api_key)

    def list_markets(self, category: str) -> List[DemoMarket]:
        if not self.configured():
            return [market for market in DEMO_MARKETS if market.category == category]

        response = requests.get(
            f"{self.base_url}/markets",
            params={"category": category},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json().get("markets", [])
        markets: List[DemoMarket] = []
        for item in data:
            markets.append(
                DemoMarket(
                    market_id=item.get("ticker", item.get("id")),
                    name=item.get("title", "Unknown"),
                    category=category,
                    base_price=item.get("last_price", 0.5),
                    sensitivity=0.05,
                    time_to_expiry_hours=24.0,
                )
            )
        return markets

    def get_market_snapshot(self, market: DemoMarket) -> Dict[str, float]:
        if not self.configured():
            timestamp = datetime.now(tz=timezone.utc)
            mid = deterministic_mid_price(market, timestamp)
            spread = demo_spread(mid)
            return {
                "mid": mid,
                "bid": round(mid - spread / 2, 4),
                "ask": round(mid + spread / 2, 4),
                "volume": 200.0,
                "time_to_expiry_hours": market.time_to_expiry_hours,
            }

        response = requests.get(
            f"{self.base_url}/markets/{market.market_id}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        mid = payload.get("mid_price", payload.get("last_price", 0.5))
        bid = payload.get("yes_bid", mid - 0.01)
        ask = payload.get("yes_ask", mid + 0.01)
        return {
            "mid": float(mid),
            "bid": float(bid),
            "ask": float(ask),
            "volume": float(payload.get("volume", 0.0)),
            "time_to_expiry_hours": float(payload.get("hours_to_expiry", 24.0)),
        }

    def place_order(self, market_id: str, side: str, price: float, size: int) -> Dict[str, str]:
        if not self.configured():
            return {"order_id": f"paper-{market_id}-{int(price * 10000)}", "status": "filled"}

        response = requests.post(
            f"{self.base_url}/orders",
            json={"ticker": market_id, "side": side, "price": price, "size": size},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
