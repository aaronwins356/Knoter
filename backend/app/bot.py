from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .logging_utils import log_event
from .models import DecisionRecord, MarketSnapshot, Order, Position, TradingMode
from .storage import fetch_fills, log_activity, log_decision, log_fill, upsert_order, upsert_position
from .strategy.engine import compute_pnl_pct, config_hash, decide_entry, decide_exit
from .strategy.pnl import compute_realized_pnl_pct, compute_unrealized_pnl_pct
from .strategy.scanner import scan_markets
from .state import MarketState


def build_advisor_prompt(snapshot: MarketSnapshot, action: str, rationale: str, risk_state: str) -> str:
    return (
        f"Market: {snapshot.name} ({snapshot.market_id})\n"
        f"Action: {action}\n"
        f"Rationale: {rationale}\n"
        f"Scores: volatility={snapshot.volatility_pct:.2f}%, spread={snapshot.spread_pct:.2f}%, "
        f"liquidity={snapshot.liquidity_score:.1f}, overall={snapshot.overall_score:.1f}\n"
        f"Risk state: {risk_state}\n"
        "Return JSON with sentiment (-1..1), confidence (0..1), notes, and veto (true/false)."
    )


def record_decision(
    state,
    snapshot: MarketSnapshot,
    action: str,
    reason_code: str,
    rationale: str,
    advisory=None,
    order_ids=None,
) -> None:
    record = DecisionRecord(
        timestamp=datetime.now(tz=timezone.utc),
        market_id=snapshot.market_id,
        action=action,
        reason_code=reason_code,
        qualifies=snapshot.qualifies,
        scores={
            "volatility_pct": snapshot.volatility_pct,
            "spread_pct": snapshot.spread_pct,
            "liquidity_score": snapshot.liquidity_score,
            "overall_score": snapshot.overall_score,
            "time_to_close_minutes": snapshot.time_to_resolution_minutes,
        },
        rationale=rationale,
        config_hash=config_hash(state.config),
        order_ids=order_ids or [],
        fills=[],
        advisory=advisory,
    )
    log_decision(record)


def _safe_advisor(state, snapshot: MarketSnapshot, action: str, rationale: str):
    if not state.config.advisor.enabled:
        return None
    if not state.openai.configured():
        return None
    try:
        prompt = build_advisor_prompt(snapshot, action, rationale, state.risk.risk_mode())
        output = state.openai.advise(prompt)
        return output.model_dump() if output else None
    except Exception as exc:  # noqa: BLE001
        log_event("advisor_error", {"error": str(exc)})
        return None


def _cooldown_active(market_state: Optional[MarketState]) -> bool:
    if not market_state or not market_state.cooldown_until:
        return False
    return datetime.now(tz=timezone.utc) < market_state.cooldown_until


def _expected_edge_cost_pct(snapshot: MarketSnapshot, config) -> float:
    return snapshot.spread_pct + config.entry.fee_pct


async def maybe_open_trade(state) -> None:
    if state.config.trading_mode == TradingMode.LIVE and (
        not state.config.live_trading_enabled or state.config.live_confirm != "ENABLE LIVE TRADING"
    ):
        return
    if not state.last_scan:
        return
    if state.trades_executed >= state.config.risk_limits.max_trades_per_event:
        return

    positions = [pos for pos in state.positions.values() if pos.status == "open"]
    exposure_qty = sum(pos.qty for pos in positions)
    exposure_notional = sum(pos.entry_price * pos.qty for pos in positions)
    state.risk.update_exposure(exposure_qty, exposure_notional, len(positions))
    risk_allows, risk_reason = state.risk.can_trade()
    qualifying = [snap for snap in state.last_scan.markets if snap.qualifies]
    if not qualifying:
        return

    max_new_positions = max(state.config.risk_limits.max_concurrent_positions - len(positions), 0)
    pick_count = 2 if max_new_positions >= 2 else 1
    selections = qualifying[:pick_count]

    order_manager = state.order_manager
    for snapshot in selections:
        if snapshot.market_id in {pos.market_id for pos in positions}:
            continue
        market_state = state.market_state.get(snapshot.market_id)
        decision = decide_entry(
            prices=market_state.prices if market_state else [],
            bid=snapshot.bid,
            ask=snapshot.ask,
            config=state.config,
            risk_allows=risk_allows,
            risk_reason=risk_reason,
            in_cooldown=_cooldown_active(market_state),
            expected_edge_cost_pct=_expected_edge_cost_pct(snapshot, state.config),
        )
        advisory = _safe_advisor(state, snapshot, decision.action, decision.rationale)
        record_decision(
            state,
            snapshot,
            decision.action,
            decision.reason_code,
            decision.rationale,
            advisory=advisory,
        )
        if advisory and advisory.get("veto") and advisory.get("confidence", 0) > 0.7:
            entry = state.add_activity(
                f"Advisor vetoed trade on {snapshot.name} (confidence {advisory.get('confidence'):.2f}).",
                category="warning",
            )
            log_activity(entry)
            continue
        if decision.action != "ENTER" or not decision.side or decision.price is None:
            continue

        result = await order_manager.place_with_ttl(snapshot.market_id, "buy", decision.side, decision.price)
        now = datetime.now(tz=timezone.utc)
        position = Position(
            position_id=f"pos-{result.order_id}",
            market_id=snapshot.market_id,
            market_name=snapshot.name,
            side=decision.side,
            qty=result.filled_qty or state.config.trade_sizing.order_size,
            entry_price=result.avg_fill_price or decision.price,
            current_price=result.avg_fill_price or decision.price,
            take_profit_pct=state.config.exit.take_profit_pct,
            stop_loss_pct=state.config.exit.stop_loss_pct,
            max_hold_seconds=state.config.exit.max_hold_seconds,
            close_before_resolution_minutes=state.config.exit.close_before_resolution_minutes,
            opened_at=now,
        )
        if result.filled_qty:
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
                    "order_id": result.order_id,
                    "market_id": snapshot.market_id,
                    "price": position.entry_price,
                    "side": decision.side,
                },
            )
            record_decision(
                state,
                snapshot,
                "ENTER",
                decision.reason_code,
                decision.rationale,
                advisory=advisory,
                order_ids=[result.order_id],
            )
            break


async def update_positions(state) -> None:
    now = datetime.now(tz=timezone.utc)
    order_manager = state.order_manager
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
            result = await order_manager.close_with_limit(
                position.market_id,
                position.side,
                snapshot.bid,
                snapshot.ask,
                position.qty,
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
            record_decision(
                state,
                snapshot,
                decision.action,
                decision.reason_code,
                decision.rationale,
                order_ids=[result.order_id],
            )
        upsert_position(position)


def _parse_fill_timestamp_ms(payload: dict) -> Optional[int]:
    raw = payload.get("created_time") or payload.get("timestamp") or payload.get("ts")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 1e12:
        value *= 1000
    return int(value)


def _refresh_pnl(state) -> None:
    fills = fetch_fills()
    state.realized_pnl_pct = compute_realized_pnl_pct(fills)
    state.unrealized_pnl_pct = compute_unrealized_pnl_pct(state.positions.values())
    state.event_pnl_pct = round(state.realized_pnl_pct + state.unrealized_pnl_pct, 4)


def reconcile_broker_state(state) -> None:
    if state.config.trading_mode != TradingMode.LIVE:
        _refresh_pnl(state)
        return
    now = datetime.now(tz=timezone.utc)
    if state.last_reconcile_ts and (now - state.last_reconcile_ts).total_seconds() < state.config.cadence_seconds:
        _refresh_pnl(state)
        return
    try:
        payload = state.order_manager.reconcile_broker(state.last_fill_ts_ms)
        open_orders = payload.get("orders", [])
        broker_positions = payload.get("positions", [])
        broker_fills = payload.get("fills", [])
    except Exception as exc:  # noqa: BLE001
        log_event("broker_orders_error", {"error": str(exc)})
        open_orders = []
        broker_positions = []
        broker_fills = []
    state.last_reconcile_ts = now

    for fill in broker_fills:
        fill_ts = _parse_fill_timestamp_ms(fill)
        if fill_ts:
            state.last_fill_ts_ms = max(state.last_fill_ts_ms or 0, fill_ts)
        fill_side = fill.get("side", "yes")
        fill_price = (
            fill.get("price_dollars")
            or fill.get("price")
            or (fill.get("yes_price_dollars") if fill_side == "yes" else fill.get("no_price_dollars"))
            or 0.0
        )
        log_fill(
            fill.get("order_id", ""),
            fill.get("ticker") or fill.get("market_ticker") or fill.get("market_id") or "",
            fill.get("action", "buy"),
            fill_side,
            float(fill_price),
            int(fill.get("count") or fill.get("size") or 0),
        )
    for order in open_orders:
        order_id = order.get("order_id") or order.get("id")
        market_id = order.get("ticker") or order.get("market_ticker") or order.get("market_id")
        if not order_id or not market_id:
            continue
        side = order.get("side", "yes")
        price = order.get("price_dollars") or order.get("price")
        if price is None:
            price = order.get("yes_price_dollars") if side == "yes" else order.get("no_price_dollars")
        upsert_order(
            Order(
                order_id=order_id,
                market_id=market_id,
                action=order.get("action", "buy"),
                side=side,
                price=float(price or 0.0),
                qty=int(order.get("count") or order.get("size") or 0),
                status=order.get("status", "open"),
                created_at=now,
                filled_at=None,
            )
        )
    for payload in broker_positions:
        market_id = payload.get("ticker") or payload.get("market_ticker") or payload.get("market_id")
        side = payload.get("side") or payload.get("position_side")
        qty = payload.get("count") or payload.get("size") or payload.get("quantity") or payload.get("position")
        entry_price = payload.get("avg_price_dollars") or payload.get("average_price_dollars") or payload.get(
            "avg_entry_price_dollars"
        )
        if not market_id or not side or qty is None or entry_price is None:
            continue
        existing = next((pos for pos in state.positions.values() if pos.market_id == market_id), None)
        if existing:
            existing.qty = int(qty)
            existing.entry_price = float(entry_price)
            upsert_position(existing)
        else:
            position = Position(
                position_id=f"pos-{market_id}",
                market_id=market_id,
                market_name=market_id,
                side=side,
                qty=int(qty),
                entry_price=float(entry_price),
                current_price=float(entry_price),
                take_profit_pct=state.config.exit.take_profit_pct,
                stop_loss_pct=state.config.exit.stop_loss_pct,
                max_hold_seconds=state.config.exit.max_hold_seconds,
                close_before_resolution_minutes=state.config.exit.close_before_resolution_minutes,
                opened_at=now,
            )
            state.positions[position.position_id] = position
            upsert_position(position)
    _refresh_pnl(state)


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
    state.killed = True
    state.next_action = "Kill switch engaged"


async def run_bot(state, publish) -> None:
    state.next_action = "Scanning for entries"
    while state.running:
        if state.killed:
            state.running = False
            break
        handle_kill_switch(state)
        scan_markets(state)
        await update_positions(state)
        await maybe_open_trade(state)
        reconcile_broker_state(state)

        await publish("scan", state.last_scan.model_dump() if state.last_scan else {})
        await publish("positions", {"positions": [pos.model_dump() for pos in state.positions.values()]})
        await publish("status", state.status_snapshot().model_dump())
        await publish("activity", {"entries": [entry.model_dump() for entry in state.activity_entries()]})

        await asyncio.sleep(state.config.cadence_seconds)
