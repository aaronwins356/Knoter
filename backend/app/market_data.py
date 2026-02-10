from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from .logging_utils import log_event


@dataclass(frozen=True)
class MarketInfo:
    ticker: str
    title: str
    close_ts: Optional[int]
    settlement_ts: Optional[int]
    status: str
    yes_subtitle: Optional[str]
    no_subtitle: Optional[str]
    raw_payload: dict


@dataclass(frozen=True)
class Quote:
    ticker: str
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]
    mid_yes: Optional[float]
    spread_yes_pct: Optional[float]
    ts_ms: Optional[int]
    valid: bool
    reason_if_invalid: Optional[str] = None


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


def _extract_price(payload: dict, dollars_keys: List[str], cents_keys: List[str]) -> Tuple[Optional[float], bool]:
    dollars = _first_present(payload, dollars_keys)
    if dollars is not None:
        return float(dollars), False
    cents = _first_present(payload, cents_keys)
    if cents is None:
        return None, False
    return float(cents) / 100.0, True


def _normalize_timestamp(ts: Optional[float]) -> Optional[int]:
    if ts is None:
        return None
    value = float(ts)
    if value > 1e12:
        value = value / 1000
    return int(value)


def _normalize_quote_values(
    ticker: str,
    yes_bid: Optional[float],
    yes_ask: Optional[float],
    no_bid: Optional[float],
    no_ask: Optional[float],
    mid_yes: Optional[float],
    ts_ms: Optional[int],
    reason: Optional[str] = None,
) -> Quote:
    invalid_reasons: List[str] = []

    def _clamp(value: Optional[float]) -> Tuple[Optional[float], bool]:
        if value is None:
            return None, False
        if value < 0.0 or value > 1.0:
            return max(0.0, min(1.0, float(value))), True
        return float(value), False

    yes_bid, yes_bid_clamped = _clamp(yes_bid)
    yes_ask, yes_ask_clamped = _clamp(yes_ask)
    no_bid, no_bid_clamped = _clamp(no_bid)
    no_ask, no_ask_clamped = _clamp(no_ask)
    mid_yes, mid_yes_clamped = _clamp(mid_yes)

    if yes_bid is None or yes_ask is None:
        invalid_reasons.append("missing_bid_ask")
    if yes_bid_clamped or yes_ask_clamped or no_bid_clamped or no_ask_clamped or mid_yes_clamped:
        invalid_reasons.append("out_of_range")
    if yes_bid is not None and yes_ask is not None and yes_ask < yes_bid:
        invalid_reasons.append("inverted_spread")

    if mid_yes is None and yes_bid is not None and yes_ask is not None:
        mid_yes = (yes_bid + yes_ask) / 2

    spread_yes_pct = None
    if mid_yes is not None and yes_bid is not None and yes_ask is not None and mid_yes > 0:
        spread_yes_pct = ((yes_ask - yes_bid) / max(mid_yes, 0.0001)) * 100

    is_valid = not invalid_reasons
    return Quote(
        ticker=ticker,
        yes_bid=round(yes_bid, 4) if yes_bid is not None else None,
        yes_ask=round(yes_ask, 4) if yes_ask is not None else None,
        no_bid=round(no_bid, 4) if no_bid is not None else None,
        no_ask=round(no_ask, 4) if no_ask is not None else None,
        mid_yes=round(mid_yes, 4) if mid_yes is not None else None,
        spread_yes_pct=round(spread_yes_pct, 4) if spread_yes_pct is not None else None,
        ts_ms=ts_ms,
        valid=is_valid,
        reason_if_invalid=reason or (invalid_reasons[0] if invalid_reasons else None),
    )


def normalize_quote(payload: dict) -> Quote:
    ticker = payload.get("ticker") or payload.get("market_ticker") or payload.get("market_id") or ""
    yes_bid, yes_bid_legacy = _extract_price(
        payload,
        ["yes_bid_dollars", "bid_dollars", "yes_bid_price_dollars"],
        ["yes_bid", "bid", "yes_bid_price"],
    )
    yes_ask, yes_ask_legacy = _extract_price(
        payload,
        ["yes_ask_dollars", "ask_dollars", "yes_ask_price_dollars"],
        ["yes_ask", "ask", "yes_ask_price"],
    )
    no_bid, no_bid_legacy = _extract_price(
        payload,
        ["no_bid_dollars", "no_bid_price_dollars"],
        ["no_bid", "no_bid_price"],
    )
    no_ask, no_ask_legacy = _extract_price(
        payload,
        ["no_ask_dollars", "no_ask_price_dollars"],
        ["no_ask", "no_ask_price"],
    )
    mid_yes, mid_legacy = _extract_price(
        payload,
        ["mid_price_dollars", "mid_dollars", "yes_mid_dollars"],
        ["mid_price", "yes_mid"],
    )
    ts_ms = _normalize_timestamp(_first_present(payload, ["last_updated_ts", "ts", "timestamp", "last_price_time"]))
    if ts_ms is not None and ts_ms < 1e12:
        ts_ms *= 1000

    if no_bid is None and yes_ask is not None:
        no_bid = round(1.0 - yes_ask, 4)
    if no_ask is None and yes_bid is not None:
        no_ask = round(1.0 - yes_bid, 4)

    if any([yes_bid_legacy, yes_ask_legacy, no_bid_legacy, no_ask_legacy, mid_legacy]):
        log_event(
            "kalshi_legacy_price_field",
            {"ticker": ticker, "fields": "legacy_price_fields"},
        )

    return _normalize_quote_values(
        ticker=ticker,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        mid_yes=mid_yes,
        ts_ms=ts_ms,
        reason=None,
    )


def build_quote_from_prices(
    ticker: str,
    yes_bid: Optional[float],
    yes_ask: Optional[float],
    no_bid: Optional[float] = None,
    no_ask: Optional[float] = None,
    ts_ms: Optional[int] = None,
) -> Quote:
    if no_bid is None and yes_ask is not None:
        no_bid = round(1.0 - yes_ask, 4)
    if no_ask is None and yes_bid is not None:
        no_ask = round(1.0 - yes_bid, 4)
    mid_yes = None
    if yes_bid is not None and yes_ask is not None:
        mid_yes = (yes_bid + yes_ask) / 2
    return _normalize_quote_values(
        ticker=ticker,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        mid_yes=mid_yes,
        ts_ms=ts_ms,
        reason=None,
    )


def normalize_market_meta(payload: dict, now_ts: Optional[int] = None) -> dict:
    volume = _first_present(payload, ["volume", "volume_dollars", "open_interest"]) or 0.0
    bid_depth = _first_present(payload, ["bid_depth", "yes_bid_depth", "bid_volume"]) or 0.0
    ask_depth = _first_present(payload, ["ask_depth", "yes_ask_depth", "ask_volume"]) or 0.0
    close_ts = _normalize_timestamp(_first_present(payload, ["close_ts", "close_time", "close_timestamp"]))
    settlement_ts = _normalize_timestamp(_first_present(payload, ["settlement_ts", "settlement_time"]))
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
        "settlement_ts": settlement_ts,
    }
