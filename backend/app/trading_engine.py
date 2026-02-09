from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
from typing import Deque, List, Optional, Tuple

from .models import BotConfig, ExitConfig, RiskLimits


@dataclass
class MarketMetrics:
    volatility_pct: float
    spread_pct: float
    liquidity_score: float
    overall_score: float
    qualifies: bool
    rationale: str


@dataclass
class EntryDecision:
    action: str
    side: Optional[str]
    price: Optional[float]
    rationale: str


@dataclass
class ExitDecision:
    action: str
    price: Optional[float]
    rationale: str


def config_hash(config: BotConfig) -> str:
    payload = json.dumps(config.model_dump(), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def compute_log_returns(prices: List[float]) -> List[float]:
    returns = []
    for previous, current in zip(prices, prices[1:]):
        if previous <= 0 or current <= 0:
            continue
        returns.append(math.log(current / previous))
    return returns


def compute_market_metrics(
    prices: List[float],
    bid: float,
    ask: float,
    volume: float,
    bid_depth: float,
    ask_depth: float,
    time_to_resolution_minutes: float,
    config: BotConfig,
) -> MarketMetrics:
    returns = compute_log_returns(prices)
    volatility_pct = pstdev(returns) * 100 if len(returns) >= 2 else 0.0
    mid = max((bid + ask) / 2, 0.001)
    spread_pct = ((ask - bid) / mid) * 100

    depth = (bid_depth + ask_depth) / 2 if (bid_depth + ask_depth) > 0 else volume
    volume_score = min(volume / config.scoring.liquidity_volume_ref, 1.0)
    depth_score = min(depth / config.scoring.liquidity_depth_ref, 1.0)
    tightness = max(0.0, 1 - (spread_pct / max(config.scoring.max_spread_pct, 0.1)))
    liquidity_score = (volume_score * 0.6 + depth_score * 0.4) * tightness * 100

    vol_score = min(volatility_pct / max(config.scoring.vol_threshold, 0.1), 2.0) * 50
    spread_score = max(0.0, 100 - (spread_pct / max(config.scoring.max_spread_pct, 0.1)) * 100)
    overall_score = (
        config.scoring.weights.volatility * vol_score
        + config.scoring.weights.spread * spread_score
        + config.scoring.weights.liquidity * liquidity_score
    )
    overall_score = max(0.0, min(100.0, overall_score))

    qualifies = (
        volatility_pct >= config.scoring.vol_threshold
        and spread_pct <= config.scoring.max_spread_pct
        and liquidity_score >= config.scoring.min_liquidity_score
    )
    rationale = "Qualified" if qualifies else "Failed thresholds"
    if time_to_resolution_minutes <= config.exit.close_before_resolution_minutes:
        rationale = "Too close to resolution"
        qualifies = False

    return MarketMetrics(
        volatility_pct=round(volatility_pct, 4),
        spread_pct=round(spread_pct, 4),
        liquidity_score=round(liquidity_score, 2),
        overall_score=round(overall_score, 2),
        qualifies=qualifies,
        rationale=rationale,
    )


def decide_entry(
    prices: Deque[float],
    bid: float,
    ask: float,
    metrics: MarketMetrics,
    config: BotConfig,
    risk_allows: bool,
    risk_reason: str,
    in_cooldown: bool,
    depth: float,
) -> EntryDecision:
    if not metrics.qualifies:
        return EntryDecision(action="SKIP", side=None, price=None, rationale=metrics.rationale)
    if in_cooldown:
        return EntryDecision(action="SKIP", side=None, price=None, rationale="Cooldown active")
    if not risk_allows:
        return EntryDecision(action="SKIP", side=None, price=None, rationale=risk_reason)
    if len(prices) < config.entry.momentum_window:
        return EntryDecision(action="SKIP", side=None, price=None, rationale="Not enough price history")

    recent_prices = list(prices)[-config.entry.momentum_window :]
    avg_price = sum(recent_prices) / len(recent_prices)
    mid_now = recent_prices[-1]
    momentum_pct = ((mid_now - avg_price) / max(avg_price, 0.001)) * 100

    side: Optional[str] = None
    if abs(momentum_pct) > config.entry.momentum_threshold_pct:
        side = "buy" if momentum_pct > 0 else "sell"
        rationale = f"Momentum {momentum_pct:.2f}% exceeds threshold"
    elif config.entry.allow_mean_reversion and metrics.spread_pct <= (config.scoring.max_spread_pct * 0.5):
        if depth >= config.entry.min_depth_for_mean_reversion:
            side = "sell" if momentum_pct > 0 else "buy"
            rationale = f"Mean reversion with depth {depth:.1f}"
        else:
            return EntryDecision(action="SKIP", side=None, price=None, rationale="Depth too thin for mean reversion")
    else:
        return EntryDecision(action="SKIP", side=None, price=None, rationale="Momentum below threshold")

    edge = mid_now * (config.entry.entry_edge_pct / 100)
    if side == "buy":
        price = min(ask, mid_now - edge)
    else:
        price = max(bid, mid_now + edge)
    return EntryDecision(action="ENTER", side=side, price=round(price, 4), rationale=rationale)


def compute_pnl_pct(entry_price: float, current_price: float, side: str) -> float:
    if entry_price <= 0:
        return 0.0
    raw = (current_price - entry_price) / entry_price * 100
    return raw if side == "buy" else -raw


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
        price = bid if side == "buy" else ask
        return ExitDecision("TAKE_PROFIT", round(price, 4), "Target met"), new_peak, trail_stop
    if pnl_pct <= -config.stop_loss_pct:
        price = bid if side == "buy" else ask
        return ExitDecision("STOP_LOSS", round(price, 4), "Stop loss hit"), new_peak, trail_stop
    if holding_time >= config.max_hold_seconds:
        price = bid if side == "buy" else ask
        return ExitDecision("TIME_EXIT", round(price, 4), "Max hold time reached"), new_peak, trail_stop
    if time_to_resolution_minutes <= config.close_before_resolution_minutes:
        price = bid if side == "buy" else ask
        return ExitDecision("LATE_EXIT", round(price, 4), "Approaching resolution"), new_peak, trail_stop

    if pnl_pct >= config.trail_start_pct:
        trail_stop = max(trailing_stop_pct or -100.0, new_peak - config.trail_gap_pct)
        if pnl_pct <= trail_stop:
            price = bid if side == "buy" else ask
            return ExitDecision("TRAIL_STOP", round(price, 4), "Trailing stop hit"), new_peak, trail_stop

    return ExitDecision("HOLD", None, "Position healthy"), new_peak, trail_stop


def exposure_from_positions(positions: List[Tuple[float, int]]) -> Tuple[int, float]:
    total_qty = sum(qty for _, qty in positions)
    total_notional = sum(price * qty for price, qty in positions)
    return total_qty, total_notional


def enforce_risk_limits(limits: RiskLimits) -> None:
    if limits.max_exposure_contracts <= 0:
        raise ValueError("max_exposure_contracts must be positive")
    if limits.max_exposure_dollars <= 0:
        raise ValueError("max_exposure_dollars must be positive")
