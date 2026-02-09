from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from ..logging_utils import log_event
from ..models import MarketSnapshot, ScanSnapshot
from ..state import MarketState
from ..storage import log_snapshot
from .scoring import compute_market_metrics


def scan_markets(state) -> ScanSnapshot:
    markets = state.broker.list_markets(
        state.config.market_filters.event_type, state.config.market_filters.time_window_hours
    )
    snapshots: List[MarketSnapshot] = []
    for market in markets:
        try:
            quote = state.broker.get_market_snapshot(market.market_id)
        except Exception as exc:  # noqa: BLE001
            log_event("market_snapshot_error", {"market_id": market.market_id, "error": str(exc)})
            continue
        if not quote:
            continue
        market_state = state.market_state.get(market.market_id)
        if not market_state:
            market_state = MarketState()
            state.market_state[market.market_id] = market_state
        market_state.prices.append(quote["mid"])
        market_state.spreads.append(quote["ask"] - quote["bid"])
        market_state.update_count += 1
        update_rate = max(market_state.update_count / max(state.config.cadence_seconds, 1), 0.1)

        metrics = compute_market_metrics(
            list(market_state.prices)[-state.config.scoring.vol_window :],
            quote["bid"],
            quote["ask"],
            quote["volume"],
            quote["bid_depth"],
            quote["ask_depth"],
            update_rate,
            quote["time_to_resolution_minutes"],
            state.config,
        )
        snapshot = MarketSnapshot(
            market_id=market.market_id,
            name=market.name,
            category=market.category,
            mid_price=quote["mid"],
            bid=quote["bid"],
            ask=quote["ask"],
            last_price=quote["last"],
            volume=quote["volume"],
            bid_depth=quote["bid_depth"],
            ask_depth=quote["ask_depth"],
            volatility_pct=metrics.volatility_pct,
            spread_pct=metrics.spread_pct,
            liquidity_score=metrics.liquidity_score,
            overall_score=metrics.overall_score,
            qualifies=metrics.qualifies,
            rationale=metrics.rationale,
            time_to_resolution_minutes=quote["time_to_resolution_minutes"],
        )
        market_state.last_snapshot = snapshot
        snapshots.append(snapshot)

    snapshots.sort(key=lambda item: item.overall_score, reverse=True)
    scan = ScanSnapshot(timestamp=datetime.now(tz=timezone.utc), markets=snapshots)
    state.last_scan = scan
    log_snapshot(scan)
    return scan
