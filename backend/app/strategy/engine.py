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
    reason_code: str
    rationale: str


@dataclass
class ExitDecision:
    action: str
    price: Optional[float]
    reason_code: str
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
    yes_bid: float,
    yes_ask: float,
    no_bid: float,
    no_ask: float,
    config: BotConfig,
    risk_allows: bool,
    risk_reason: str,
    in_cooldown: bool,
    expected_edge_cost_pct: float,
) -> EntryDecision:
    if in_cooldown:
        return EntryDecision("SKIP", None, None, 0.0, "SKIP_COOLDOWN", "Cooldown active")
    if not risk_allows:
        return EntryDecision("SKIP", None, None, 0.0, "SKIP_RISK", risk_reason)
    if len(prices) < config.entry.momentum_window:
        return EntryDecision("SKIP", None, None, 0.0, "SKIP_HISTORY", "Not enough price history")

    recent_prices = list(prices)[-config.entry.momentum_window :]
    avg_price = sum(recent_prices) / len(recent_prices)
    mid_now = recent_prices[-1]
    momentum_pct = ((mid_now - avg_price) / max(avg_price, 0.001)) * 100

    if abs(momentum_pct) <= config.entry.momentum_threshold_pct:
        return EntryDecision("SKIP", None, None, 0.0, "SKIP_MOMENTUM", "Momentum below threshold")

    side = "yes" if momentum_pct > 0 else "no"
    expected_edge_pct = abs(momentum_pct) - expected_edge_cost_pct
    if expected_edge_pct <= 0:
        return EntryDecision("SKIP", None, None, expected_edge_pct, "SKIP_EDGE", "Edge negative after costs")

    edge_base = mid_now if side == "yes" else max(0.0, min(1.0, 1.0 - mid_now))
    edge = edge_base * (config.entry.entry_edge_pct / 100)
    if side == "yes":
        price = min(yes_ask, mid_now - edge)
    else:
        mid_no = edge_base
        if no_bid <= 0 or no_ask <= 0:
            return EntryDecision("SKIP", None, None, 0.0, "SKIP_NO_QUOTE", "No-side quote missing")
        price = min(no_ask, mid_no - edge)

    price = max(0.01, min(price, 0.99))
    rationale = f"Momentum {momentum_pct:.2f}% with edge {expected_edge_pct:.2f}%"
    reason_code = "ENTER_LONG" if side == "yes" else "ENTER_SHORT"
    return EntryDecision("ENTER", side, round(price, 4), expected_edge_pct, reason_code, rationale)


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
        return ExitDecision("TAKE_PROFIT", round(price, 4), "EXIT_TP", "Target met"), new_peak, trail_stop
    if pnl_pct <= -config.stop_loss_pct:
        price = bid if side == "yes" else ask
        return ExitDecision("STOP_LOSS", round(price, 4), "EXIT_SL", "Stop loss hit"), new_peak, trail_stop
    if holding_time >= config.max_hold_seconds:
        price = bid if side == "yes" else ask
        return ExitDecision("TIME_EXIT", round(price, 4), "EXIT_TIME", "Max hold time reached"), new_peak, trail_stop
    if time_to_resolution_minutes <= config.close_before_resolution_minutes:
        price = bid if side == "yes" else ask
        return ExitDecision("LATE_EXIT", round(price, 4), "EXIT_LATE", "Approaching resolution"), new_peak, trail_stop

    if pnl_pct >= config.trail_start_pct:
        trail_stop = max(trailing_stop_pct or -100.0, new_peak - config.trail_gap_pct)
        if pnl_pct <= trail_stop:
            price = bid if side == "yes" else ask
            return ExitDecision("TRAIL_STOP", round(price, 4), "EXIT_TRAIL", "Trailing stop hit"), new_peak, trail_stop

    return ExitDecision("HOLD", None, "HOLD", "Position healthy"), new_peak, trail_stop
