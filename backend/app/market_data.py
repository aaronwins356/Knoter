from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional


@dataclass(frozen=True)
class MarketInfo:
    ticker: str
    title: str
    close_ts: Optional[int]
    status: str
    category: str
    raw_payload: dict


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    mid: float
    last: float
    spread_pct: float
    valid: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class MarketQuote:
    quote: Quote
    volume: float
    bid_depth: float
    ask_depth: float
    time_to_resolution_minutes: float


@dataclass(frozen=True)
class DemoMarket:
    ticker: str
    name: str
    category: str
    base_price: float
    sensitivity: float
    time_to_resolution_minutes: float


DEMO_MARKETS: List[DemoMarket] = [
    DemoMarket(
        ticker="NBA-LAL-GSW",
        name="Lakers vs Warriors - Winner",
        category="sports",
        base_price=0.56,
        sensitivity=0.11,
        time_to_resolution_minutes=18.0 * 60,
    ),
    DemoMarket(
        ticker="ELECT-2024",
        name="Election result - Margin",
        category="politics",
        base_price=0.42,
        sensitivity=0.14,
        time_to_resolution_minutes=96.0 * 60,
    ),
    DemoMarket(
        ticker="FED-RATE",
        name="Fed rate hike",
        category="finance",
        base_price=0.38,
        sensitivity=0.09,
        time_to_resolution_minutes=40.0 * 60,
    ),
    DemoMarket(
        ticker="EARN-NVDA",
        name="NVIDIA earnings beat",
        category="company",
        base_price=0.63,
        sensitivity=0.12,
        time_to_resolution_minutes=12.0 * 60,
    ),
    DemoMarket(
        ticker="OIL-PRICE",
        name="Oil above $90",
        category="finance",
        base_price=0.29,
        sensitivity=0.16,
        time_to_resolution_minutes=55.0 * 60,
    ),
    DemoMarket(
        ticker="NBA-PTS",
        name="Total points over 215.5",
        category="sports",
        base_price=0.51,
        sensitivity=0.08,
        time_to_resolution_minutes=8.0 * 60,
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


def _first_present(payload: dict, keys: List[str]) -> Optional[float]:
    for key in keys:
        if key in payload and payload[key] is not None:
            try:
                return float(payload[key])
            except (TypeError, ValueError):
                continue
    return None


def _extract_price(payload: dict, dollars_keys: List[str], cents_keys: List[str]) -> Optional[float]:
    dollars = _first_present(payload, dollars_keys)
    if dollars is not None:
        return float(dollars)
    cents = _first_present(payload, cents_keys)
    if cents is None:
        return None
    return float(cents) / 100.0


def _normalize_timestamp(ts: Optional[float]) -> Optional[int]:
    if ts is None:
        return None
    value = float(ts)
    if value > 1e12:
        value = value / 1000
    return int(value)


def normalize_quote(payload: dict) -> Quote:
    bid = _extract_price(
        payload,
        ["yes_bid_dollars", "bid_dollars", "bid_price_dollars"],
        ["yes_bid", "bid", "bid_price"],
    )
    ask = _extract_price(
        payload,
        ["yes_ask_dollars", "ask_dollars", "ask_price_dollars"],
        ["yes_ask", "ask", "ask_price"],
    )
    mid = _extract_price(
        payload,
        ["mid_price_dollars", "mid_dollars"],
        ["mid_price"],
    )
    last = _extract_price(
        payload,
        ["last_price_dollars", "last_dollars"],
        ["last_price", "last"],
    )

    if bid is not None and ask is not None:
        mid = (bid + ask) / 2
    if mid is None:
        mid = last

    if bid is None and mid is not None:
        bid = mid
    if ask is None and mid is not None:
        ask = mid
    if last is None and mid is not None:
        last = mid

    if bid is None or ask is None or mid is None or last is None:
        return Quote(bid=0.0, ask=0.0, mid=0.0, last=0.0, spread_pct=0.0, valid=False, reason="missing_quote")

    bid = float(bid)
    ask = float(ask)
    mid = float(mid)
    last = float(last)
    spread_pct = 0.0
    if mid > 0 and ask >= bid:
        spread_pct = ((ask - bid) / max(mid, 0.0001)) * 100

    return Quote(
        bid=round(bid, 4),
        ask=round(ask, 4),
        mid=round(mid, 4),
        last=round(last, 4),
        spread_pct=round(spread_pct, 4),
        valid=True,
    )


def normalize_market_meta(payload: dict, now_ts: Optional[int] = None) -> dict:
    volume = _first_present(payload, ["volume", "volume_dollars", "open_interest"]) or 0.0
    bid_depth = _first_present(payload, ["bid_depth", "yes_bid_depth", "bid_volume"]) or 0.0
    ask_depth = _first_present(payload, ["ask_depth", "yes_ask_depth", "ask_volume"]) or 0.0
    close_ts = _normalize_timestamp(
        _first_present(payload, ["close_ts", "close_time", "settlement_ts", "close_timestamp"])
    )
    if now_ts is None:
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    minutes_to_resolution = payload.get("minutes_to_expiry")
    if minutes_to_resolution is None and close_ts is not None:
        minutes_to_resolution = max((close_ts - now_ts) / 60, 0.0)
    elif minutes_to_resolution is None:
        minutes_to_resolution = 60.0

    return {
        "volume": float(volume),
        "bid_depth": float(bid_depth),
        "ask_depth": float(ask_depth),
        "minutes_to_resolution": float(minutes_to_resolution),
        "close_ts": close_ts,
    }
