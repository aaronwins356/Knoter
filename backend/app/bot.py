from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from .logging_utils import log_event
from .models import AuditRecord, MarketSnapshot, Position, ScanSnapshot, TradingMode
from .storage import log_activity, log_audit, upsert_order, upsert_position
from .trading_engine import (
    MarketMetrics,
    compute_market_metrics,
    compute_pnl_pct,
    config_hash,
    decide_entry,
    decide_exit,
    exposure_from_positions,
)
from .state import MarketState


def build_advisor_prompt(snapshot: MarketSnapshot, action: str, rationale: str, risk_state: str) -> str:
    return (
        f"Market: {snapshot.name} ({snapshot.market_id})\n"
        f"Action: {action}\n"
        f"Rationale: {rationale}\n"
        f"Scores: volatility={snapshot.volatility_pct:.2f}%, spread={snapshot.spread_pct:.2f}%, "
        f"liquidity={snapshot.liquidity_score:.1f}, overall={snapshot.overall_score:.1f}\n"
        f"Risk state: {risk_state}\n"
        "Provide 3-6 bullet explanations and 1-3 risk warnings. Optional suggestions only."
    )


def record_audit(state, snapshot: MarketSnapshot, action: str, rationale: str, advisory=None, order_ids=None) -> None:
    record = AuditRecord(
        timestamp=datetime.now(tz=timezone.utc),
        market_id=snapshot.market_id,
        action=action,
        qualifies=snapshot.qualifies,
        scores={
            "volatility_pct": snapshot.volatility_pct,
            "spread_pct": snapshot.spread_pct,
            "liquidity_score": snapshot.liquidity_score,
            "overall_score": snapshot.overall_score,
        },
        rationale=rationale,
        config_hash=config_hash(state.config),
        order_ids=order_ids or [],
        fills=[],
        advisory=advisory,
    )
    log_audit(record)


def _safe_advisor(state, snapshot: MarketSnapshot, action: str, rationale: str):
    if not state.config.advisor.enabled:
        return None
    if not state.openai.configured():
        return None
    try:
        prompt = build_advisor_prompt(snapshot, action, rationale, state.risk.risk_mode())
        output = state.openai.advise(prompt)
        return output.model_dump() if output else None
    except Exception as exc:  # noqa: BLE001 - safeguard advisor only
        log_event("advisor_error", {"error": str(exc)})
        return None


async def scan_markets(state) -> ScanSnapshot:
    markets = state.broker.list_markets(
        state.config.market_filters.event_type, state.config.market_filters.time_window_hours
    )
    snapshots: List[MarketSnapshot] = []
    for market in markets:
        try:
            quote = state.broker.get_market_snapshot(market)
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

        metrics = compute_market_metrics(
            list(market_state.prices)[-state.config.scoring.vol_window :],
            quote["bid"],
            quote["ask"],
            quote["volume"],
            quote["bid_depth"],
            quote["ask_depth"],
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
    return scan


def _cooldown_active(market_state) -> bool:
    if not market_state or not market_state.cooldown_until:
        return False
    return datetime.now(tz=timezone.utc) < market_state.cooldown_until


async def place_order_with_ttl(state, market_id: str, side: str, price: float) -> Tuple[str, str]:
    order_ids = []
    last_status = "open"
    for attempt in range(state.config.entry.max_replacements + 1):
        now = datetime.now(tz=timezone.utc)
        response = state.broker.place_order(
            market_id,
            side,
            price,
            state.config.trade_sizing.order_size,
            order_type="limit",
        )
        order_id = response.get("order_id", "")
        status = response.get("status", "open")
        order_ids.append(order_id)
        last_status = status
        order = state.orders.get(order_id)
        if not order and order_id:
            from .models import Order

            order = Order(
                order_id=order_id,
                market_id=market_id,
                side=side,
                price=price,
                qty=state.config.trade_sizing.order_size,
                status=status,
                created_at=now,
                filled_at=now if status == "filled" else None,
            )
            state.orders[order_id] = order
        if order:
            order.status = status
            order.filled_at = now if status == "filled" else order.filled_at
            upsert_order(order)
        if status == "filled":
            return order_id, status
        if attempt < state.config.entry.max_replacements and state.config.entry.order_ttl_seconds > 0:
            await asyncio.sleep(state.config.entry.order_ttl_seconds)
        state.broker.cancel_order(order_id)
    return order_ids[-1], last_status


async def maybe_open_trade(state) -> List[AuditRecord]:
    decisions: List[AuditRecord] = []
    if state.config.trading_mode == TradingMode.LIVE and not state.config.live_trading_enabled:
        return decisions
    if state.trades_executed >= state.config.risk_limits.max_trades_per_event:
        return decisions
    if not state.last_scan:
        return decisions

    positions = [pos for pos in state.positions.values() if pos.status == "open"]
    exposure_qty, exposure_notional = exposure_from_positions(
        [(pos.entry_price, pos.qty) for pos in positions]
    )
    state.risk.update_exposure(exposure_qty, exposure_notional, len(positions))
    risk_allows, risk_reason = state.risk.can_trade()

    for snapshot in state.last_scan.markets:
        market_state = state.market_state.get(snapshot.market_id)
        depth = snapshot.bid_depth + snapshot.ask_depth
        metrics = MarketMetrics(
            volatility_pct=snapshot.volatility_pct,
            spread_pct=snapshot.spread_pct,
            liquidity_score=snapshot.liquidity_score,
            overall_score=snapshot.overall_score,
            qualifies=snapshot.qualifies,
            rationale=snapshot.rationale,
        )
        decision = decide_entry(
            prices=market_state.prices if market_state else [],
            bid=snapshot.bid,
            ask=snapshot.ask,
            metrics=metrics,
            config=state.config,
            risk_allows=risk_allows,
            risk_reason=risk_reason,
            in_cooldown=_cooldown_active(market_state),
            depth=depth,
        )

        advisory = _safe_advisor(state, snapshot, decision.action, decision.rationale)
        record_audit(state, snapshot, decision.action, decision.rationale, advisory=advisory)
        if decision.action != "ENTER":
            continue

        order_id, status = await place_order_with_ttl(state, snapshot.market_id, decision.side, decision.price)
        now = datetime.now(tz=timezone.utc)
        position = Position(
            position_id=f"pos-{order_id}",
            market_id=snapshot.market_id,
            market_name=snapshot.name,
            side=decision.side or "buy",
            qty=state.config.trade_sizing.order_size,
            entry_price=decision.price or snapshot.mid_price,
            current_price=decision.price or snapshot.mid_price,
            take_profit_pct=state.config.exit.take_profit_pct,
            stop_loss_pct=state.config.exit.stop_loss_pct,
            opened_at=now,
        )
        if status == "filled":
            state.positions[position.position_id] = position
            state.trades_executed += 1
            if market_state:
                market_state.cooldown_until = now + timedelta(
                    seconds=state.config.risk_limits.cooldown_after_trade_seconds
                )
            entry = state.add_activity(
                f"Entered {snapshot.name} ({decision.side}) at {position.entry_price:.3f}.",
                category="trade",
            )
            log_activity(entry)
            upsert_position(position)
            log_event(
                "order_filled",
                {
                    "order_id": order_id,
                    "market_id": snapshot.market_id,
                    "price": position.entry_price,
                    "side": decision.side,
                },
            )
            record_audit(
                state,
                snapshot,
                "ENTER",
                decision.rationale,
                advisory=advisory,
                order_ids=[order_id],
            )
            break
    return decisions


def update_positions(state) -> None:
    now = datetime.now(tz=timezone.utc)
    for position in list(state.positions.values()):
        if position.status != "open":
            continue
        market_state = state.market_state.get(position.market_id)
        if not market_state or not market_state.last_snapshot:
            continue
        snapshot = market_state.last_snapshot
        current = snapshot.mid_price
        decision, new_peak, trail_stop = decide_exit(
            position.entry_price,
            current,
            position.side,
            position.opened_at,
            now,
            state.config.exit,
            position.peak_pnl_pct,
            position.trail_stop_pct,
            snapshot.time_to_resolution_minutes,
            snapshot.bid,
            snapshot.ask,
        )
        position.current_price = current
        position.pnl_pct = round(compute_pnl_pct(position.entry_price, current, position.side), 4)
        position.peak_pnl_pct = new_peak
        position.trail_stop_pct = trail_stop

        if decision.action != "HOLD":
            response = state.broker.place_order(
                position.market_id,
                "sell" if position.side == "buy" else "buy",
                decision.price or current,
                position.qty,
                order_type="limit",
            )
            position.status = "closed"
            position.closed_at = now
            state.event_pnl_pct += position.pnl_pct
            state.risk.record_trade(position.pnl_pct)
            entry = state.add_activity(
                f"Exit {position.market_name} via {decision.action} at {position.current_price:.3f}.",
                category="trade",
            )
            log_activity(entry)
            record_audit(state, snapshot, decision.action, decision.rationale, order_ids=[response.get("order_id", "")])
        upsert_position(position)


def handle_kill_switch(state) -> None:
    if not state.config.risk_limits.kill_switch:
        return
    try:
        for order in state.broker.get_open_orders():
            order_id = order.get("order_id")
            if order_id:
                state.broker.cancel_order(order_id)
    except Exception as exc:  # noqa: BLE001
        log_event("kill_switch_error", {"error": str(exc)})
    state.running = False
    state.next_action = "Kill switch engaged"


async def run_bot(state, publish) -> None:
    state.next_action = "Scanning for entries"
    while state.running:
        handle_kill_switch(state)
        scan = await scan_markets(state)
        update_positions(state)
        await maybe_open_trade(state)

        await publish("scan", scan.model_dump())
        await publish("positions", {"positions": [pos.model_dump() for pos in state.positions.values()]})
        await publish("status", state.status_snapshot().model_dump())
        await publish("activity", {"entries": [entry.model_dump() for entry in state.activity_entries()]})

        await asyncio.sleep(state.config.cadence_seconds)
