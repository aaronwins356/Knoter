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
        state.config.market_filters.event_type,
        state.config.market_filters.time_window_hours,
        keyword_map=state.config.market_filters.keywords,
    )
    snapshots: List[MarketSnapshot] = []
    for market in markets:
        try:
            market_quote = state.broker.get_market_snapshot(market.ticker)
        except Exception as exc:  # noqa: BLE001
            log_event("market_snapshot_error", {"market_id": market.ticker, "error": str(exc)})
            continue
        quote = market_quote.quote
        if not quote.valid:
            continue
        market_state = state.market_state.get(market.ticker)
        if not market_state:
            market_state = MarketState()
            state.market_state[market.ticker] = market_state
        if quote.mid_yes is None or quote.yes_bid is None or quote.yes_ask is None:
            continue
        market_state.prices.append(quote.mid_yes)
        market_state.spreads.append(quote.yes_ask - quote.yes_bid)
        market_state.update_count += 1
        update_rate = max(market_state.update_count / max(state.config.cadence_seconds, 1), 0.1)

        metrics = compute_market_metrics(
            list(market_state.prices)[-state.config.scoring.vol_window :],
            quote.yes_bid,
            quote.yes_ask,
            market_quote.volume,
            market_quote.bid_depth,
            market_quote.ask_depth,
            update_rate,
            market_quote.time_to_resolution_minutes,
            state.config,
        )
        snapshot = MarketSnapshot(
            market_id=market.ticker,
            name=market.title,
            focus=state.config.market_filters.event_type,
            mid_yes=quote.mid_yes,
            yes_bid=quote.yes_bid,
            yes_ask=quote.yes_ask,
            no_bid=quote.no_bid or 0.0,
            no_ask=quote.no_ask or 0.0,
            volume=market_quote.volume,
            bid_depth=market_quote.bid_depth,
            ask_depth=market_quote.ask_depth,
            volatility_pct=metrics.volatility_pct,
            spread_yes_pct=metrics.spread_pct,
            liquidity_score=metrics.liquidity_score,
            overall_score=metrics.overall_score,
            qualifies=metrics.qualifies,
            rationale=metrics.rationale,
            time_to_resolution_minutes=market_quote.time_to_resolution_minutes,
        )
        market_state.last_snapshot = snapshot
        snapshots.append(snapshot)

    snapshots.sort(key=lambda item: item.overall_score, reverse=True)
    scan = ScanSnapshot(timestamp=datetime.now(tz=timezone.utc), markets=snapshots)
    state.last_scan = scan
    log_snapshot(scan)
    return scan
