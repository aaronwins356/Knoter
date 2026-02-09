from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Optional, Tuple

from ..models import BotConfig, ExitConfig


@dataclass
class EntryDecision:
    action: str
    side: Optional[str]
    price: Optional[float]
    expected_edge_pct: float
    rationale: str


@dataclass
class ExitDecision:
    action: str
    price: Optional[float]
    rationale: str


def config_hash(config: BotConfig) -> str:
    payload = json.dumps(config.model_dump(), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def compute_pnl_pct(entry_price: float, current_price: float, side: str) -> float:
    if entry_price <= 0:
        return 0.0
    raw = (current_price - entry_price) / entry_price * 100
    return raw if side == "yes" else -raw


def decide_entry(
    prices: Deque[float],
    bid: float,
    ask: float,
    config: BotConfig,
    risk_allows: bool,
    risk_reason: str,
    in_cooldown: bool,
    expected_edge_cost_pct: float,
) -> EntryDecision:
    if in_cooldown:
        return EntryDecision("SKIP", None, None, 0.0, "Cooldown active")
    if not risk_allows:
        return EntryDecision("SKIP", None, None, 0.0, risk_reason)
    if len(prices) < config.entry.momentum_window:
        return EntryDecision("SKIP", None, None, 0.0, "Not enough price history")

    recent_prices = list(prices)[-config.entry.momentum_window :]
    avg_price = sum(recent_prices) / len(recent_prices)
    mid_now = recent_prices[-1]
    momentum_pct = ((mid_now - avg_price) / max(avg_price, 0.001)) * 100

    if abs(momentum_pct) <= config.entry.momentum_threshold_pct:
        return EntryDecision("SKIP", None, None, 0.0, "Momentum below threshold")

    side = "yes" if momentum_pct > 0 else "no"
    expected_edge_pct = abs(momentum_pct) - expected_edge_cost_pct
    if expected_edge_pct <= 0:
        return EntryDecision("SKIP", None, None, expected_edge_pct, "Edge negative after costs")

    edge = mid_now * (config.entry.entry_edge_pct / 100)
    if side == "yes":
        price = min(ask, mid_now - edge)
    else:
        price = max(bid, mid_now + edge)

    rationale = f"Momentum {momentum_pct:.2f}% with edge {expected_edge_pct:.2f}%"
    return EntryDecision("ENTER", side, round(price, 4), expected_edge_pct, rationale)


def decide_exit(
    entry_price: float,
    current_price: float,
    side: str,
    opened_at: datetime,
    now: datetime,
    config: ExitConfig,
    peak_pnl_pct: float,
    trailing_stop_pct: Optional[float],
    time_to_resolution_minutes: float,
    bid: float,
    ask: float,
) -> Tuple[ExitDecision, float, Optional[float]]:
    pnl_pct = compute_pnl_pct(entry_price, current_price, side)
    holding_time = (now - opened_at).total_seconds()
    new_peak = max(peak_pnl_pct, pnl_pct)
    trail_stop = trailing_stop_pct

    if pnl_pct >= config.take_profit_pct:
        price = bid if side == "yes" else ask
        return ExitDecision("TAKE_PROFIT", round(price, 4), "Target met"), new_peak, trail_stop
    if pnl_pct <= -config.stop_loss_pct:
        price = bid if side == "yes" else ask
        return ExitDecision("STOP_LOSS", round(price, 4), "Stop loss hit"), new_peak, trail_stop
    if holding_time >= config.max_hold_seconds:
        price = bid if side == "yes" else ask
        return ExitDecision("TIME_EXIT", round(price, 4), "Max hold time reached"), new_peak, trail_stop
    if time_to_resolution_minutes <= config.close_before_resolution_minutes:
        price = bid if side == "yes" else ask
        return ExitDecision("LATE_EXIT", round(price, 4), "Approaching resolution"), new_peak, trail_stop

    if pnl_pct >= config.trail_start_pct:
        trail_stop = max(trailing_stop_pct or -100.0, new_peak - config.trail_gap_pct)
        if pnl_pct <= trail_stop:
            price = bid if side == "yes" else ask
            return ExitDecision("TRAIL_STOP", round(price, 4), "Trailing stop hit"), new_peak, trail_stop

    return ExitDecision("HOLD", None, "Position healthy"), new_peak, trail_stop
