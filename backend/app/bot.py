from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List

from .logging_utils import log_event
from .models import MarketSnapshot, Position, ScanSnapshot
from .signals import qualify_signal
from .state import BotState, MarketState
from .storage import log_activity, upsert_order, upsert_position
from .volatility import volatility_score


async def scan_markets(state: BotState) -> ScanSnapshot:
    markets = state.kalshi.list_markets(state.config.event_focus)
    snapshots: List[MarketSnapshot] = []
    for market in markets:
        snapshot = state.kalshi.get_market_snapshot(market)
        market_state = state.market_state.setdefault(market.market_id, MarketState())
        market_state.prices.append(snapshot["mid"])
        market_state.spreads.append(snapshot["ask"] - snapshot["bid"])
        market_state.update_count += 1

        score, volatility_pct = volatility_score(
            list(market_state.prices),
            list(market_state.spreads),
            market_state.update_count,
            snapshot["time_to_expiry_hours"],
        )
        spread_pct = ((snapshot["ask"] - snapshot["bid"]) / max(snapshot["mid"], 0.01)) * 100
        decision = qualify_signal(
            volatility_pct,
            state.config.volatility_threshold,
            spread_pct,
            state.config.max_spread_pct,
            snapshot["volume"],
            state.config.liquidity_min_volume,
        )
        market_snapshot = MarketSnapshot(
            market_id=market.market_id,
            name=market.name,
            type=market.category.title(),
            mid_price=snapshot["mid"],
            bid=snapshot["bid"],
            ask=snapshot["ask"],
            volume=snapshot["volume"],
            volatility_percent=volatility_pct,
            volatility_score=score,
            signal=decision.signal,
            threshold=state.config.volatility_threshold,
            time_to_expiry_hours=snapshot["time_to_expiry_hours"],
        )
        market_state.last_snapshot = market_snapshot
        snapshots.append(market_snapshot)

    snapshots.sort(key=lambda item: item.volatility_percent, reverse=True)
    scan = ScanSnapshot(timestamp=datetime.now(tz=timezone.utc), markets=snapshots)
    state.last_scan = scan
    return scan


def update_positions(state: BotState) -> None:
    for position in list(state.positions.values()):
        if position.status != "open":
            continue
        market_state = state.market_state.get(position.market_id)
        if not market_state or not market_state.last_snapshot:
            continue
        current = market_state.last_snapshot.mid_price
        pnl_pct = ((current - position.entry_price) / position.entry_price) * 100
        position.current_price = current
        position.pnl_pct = pnl_pct
        if pnl_pct >= position.take_profit_pct:
            position.status = "closed"
            state.event_pnl_pct += position.take_profit_pct
            state.risk.record_trade(position.take_profit_pct)
            entry = state.add_activity(
                f"Target hit on {position.market_name}. Realized +{position.take_profit_pct:.1f}%.",
                category="trade",
            )
            log_activity(entry)
        elif pnl_pct <= -position.stop_loss_pct:
            position.status = "closed"
            state.event_pnl_pct -= position.stop_loss_pct
            state.risk.record_trade(-position.stop_loss_pct)
            entry = state.add_activity(
                f"Stopped out of {position.market_name} at -{position.stop_loss_pct:.1f}%.",
                category="risk",
            )
            log_activity(entry)
        upsert_position(position)


def maybe_open_trade(state: BotState) -> None:
    if state.trades_executed >= state.config.trade_params.max_trades_per_event:
        return
    open_positions = [pos for pos in state.positions.values() if pos.status == "open"]
    state.risk.update_exposure(
        exposure_pct=len(open_positions) * 2.0,
        active_positions=len(open_positions),
    )
    if not state.risk.can_trade():
        return
    if not state.last_scan:
        return

    candidate = next(
        (
            market
            for market in state.last_scan.markets
            if market.signal != "Standby" and market.volatility_percent >= state.config.volatility_threshold
        ),
        None,
    )
    if not candidate:
        return

    order = state.paper_broker.execute_order(candidate.market_id, "buy", candidate.mid_price)
    position = Position(
        position_id=f"pos-{order.order_id}",
        market_id=candidate.market_id,
        market_name=candidate.name,
        entry_price=order.price,
        current_price=order.price,
        take_profit_pct=state.config.trade_params.take_profit_pct,
        stop_loss_pct=state.config.trade_params.stop_loss_pct,
        opened_at=datetime.now(tz=timezone.utc),
    )

    state.positions[position.position_id] = position
    state.orders[order.order_id] = order
    state.trades_executed += 1
    entry = state.add_activity(
        f"Entered {candidate.name} aiming for {state.config.trade_params.take_profit_pct:.1f}% gain.",
        category="trade",
    )
    log_activity(entry)
    upsert_order(order)
    upsert_position(position)
    log_event(
        "order_filled",
        {
            "order_id": order.order_id,
            "market_id": order.market_id,
            "price": order.price,
            "side": order.side,
        },
    )


async def run_bot(state: BotState, publish) -> None:
    state.next_action = "Scanning for entries"
    while state.running:
        scan = await scan_markets(state)
        update_positions(state)
        maybe_open_trade(state)

        await publish("scan", scan.model_dump())
        await publish("positions", {"positions": [pos.model_dump() for pos in state.positions.values()]})
        await publish("status", state.status_snapshot().model_dump())
        await publish("activity", {"entries": [entry.model_dump() for entry in state.activity_entries()]})

        await asyncio.sleep(state.config.cadence_seconds)
