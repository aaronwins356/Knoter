from __future__ import annotations

from statistics import pstdev
from typing import List, Tuple


def compute_returns(prices: List[float]) -> List[float]:
    if len(prices) < 2:
        return []
    returns = []
    for previous, current in zip(prices, prices[1:]):
        if previous <= 0:
            continue
        returns.append((current - previous) / previous)
    return returns


def normalize(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return min(100.0, max(0.0, (value / max_value) * 100.0))


def volatility_score(
    prices: List[float],
    spreads: List[float],
    update_count: int,
    time_to_expiry_hours: float,
) -> Tuple[float, float]:
    returns = compute_returns(prices)
    return_vol = pstdev(returns) * 100 if len(returns) >= 2 else 0.0
    spread_ratio = (sum(spreads) / max(len(spreads), 1)) / max(sum(prices) / max(len(prices), 1), 0.01)
    activity_rate = update_count / max(len(prices), 1)

    return_score = normalize(return_vol, 4.0)
    spread_score = normalize(spread_ratio * 100, 10.0)
    activity_score = normalize(activity_rate, 1.0)

    time_weight = min(1.5, max(0.6, 24.0 / max(time_to_expiry_hours, 1.0)))
    score = min(100.0, (return_score * 0.5 + spread_score * 0.2 + activity_score * 0.3) * time_weight)

    last_move = abs(returns[-1]) * 100 if returns else 0.0
    return round(score, 2), round(last_move, 2)
