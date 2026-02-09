from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List


@dataclass(frozen=True)
class DemoMarket:
    market_id: str
    name: str
    category: str
    base_price: float
    sensitivity: float
    time_to_expiry_hours: float


DEMO_MARKETS: List[DemoMarket] = [
    DemoMarket(
        market_id="NBA-LAL-GSW",
        name="Lakers vs Warriors - Winner",
        category="sports",
        base_price=0.56,
        sensitivity=0.11,
        time_to_expiry_hours=18.0,
    ),
    DemoMarket(
        market_id="ELECT-2024",
        name="Election result - Margin",
        category="politics",
        base_price=0.42,
        sensitivity=0.14,
        time_to_expiry_hours=96.0,
    ),
    DemoMarket(
        market_id="FED-RATE",
        name="Fed rate hike",
        category="finance",
        base_price=0.38,
        sensitivity=0.09,
        time_to_expiry_hours=40.0,
    ),
    DemoMarket(
        market_id="EARN-NVDA",
        name="NVIDIA earnings beat",
        category="company",
        base_price=0.63,
        sensitivity=0.12,
        time_to_expiry_hours=12.0,
    ),
    DemoMarket(
        market_id="OIL-PRICE",
        name="Oil above $90",
        category="finance",
        base_price=0.29,
        sensitivity=0.16,
        time_to_expiry_hours=55.0,
    ),
    DemoMarket(
        market_id="NBA-PTS",
        name="Total points over 215.5",
        category="sports",
        base_price=0.51,
        sensitivity=0.08,
        time_to_expiry_hours=8.0,
    ),
]


def deterministic_mid_price(market: DemoMarket, timestamp: datetime) -> float:
    seconds = int(timestamp.replace(tzinfo=timezone.utc).timestamp())
    pulse = math.sin((seconds / 60) + market.base_price * 10) * market.sensitivity
    drift = math.cos(seconds / 300) * market.sensitivity * 0.4
    price = min(0.98, max(0.02, market.base_price + pulse + drift))
    return round(price, 4)


def demo_spread(mid_price: float) -> float:
    return round(max(0.002, mid_price * 0.01), 4)
