from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import pstdev
from typing import List

from ..models import BotConfig


@dataclass
class MarketMetrics:
    volatility_pct: float
    spread_pct: float
    liquidity_score: float
    overall_score: float
    qualifies: bool
    rationale: str


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
    update_rate: float,
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
    update_score = min(update_rate / config.scoring.liquidity_update_ref, 1.0)
    tightness = max(0.0, 1 - (spread_pct / max(config.scoring.max_spread_pct, 0.1)))
    liquidity_score = (volume_score * 0.5 + depth_score * 0.3 + update_score * 0.2) * tightness * 100

    vol_score = min(volatility_pct / max(config.scoring.vol_threshold, 0.1), 2.0) * 50
    spread_score = max(0.0, 100 - (spread_pct / max(config.scoring.max_spread_pct, 0.1)) * 100)
    resolution_score = min(
        time_to_resolution_minutes / max(config.scoring.resolution_minutes_ref, 1.0), 1.0
    ) * 100

    overall_score = (
        config.scoring.weights.volatility * vol_score
        + config.scoring.weights.spread * spread_score
        + config.scoring.weights.liquidity * liquidity_score
        + config.scoring.weights.resolution * resolution_score
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
