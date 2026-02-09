from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalDecision:
    signal: str
    qualifies: bool
    reason: str


def qualify_signal(
    volatility_pct: float,
    threshold: float,
    spread_pct: float,
    max_spread_pct: float,
    volume: float,
    min_volume: float,
) -> SignalDecision:
    if volatility_pct < threshold:
        return SignalDecision(signal="Standby", qualifies=False, reason="Below volatility threshold")
    if spread_pct > max_spread_pct:
        return SignalDecision(signal="Standby", qualifies=False, reason="Spread too wide")
    if volume < min_volume:
        return SignalDecision(signal="Standby", qualifies=False, reason="Insufficient volume")
    if volatility_pct >= threshold + 4:
        return SignalDecision(signal="Exploit spike", qualifies=True, reason="Volatility spike")
    return SignalDecision(signal="Monitor", qualifies=True, reason="Qualified for monitoring")
