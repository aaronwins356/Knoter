from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .bot import run_bot
from .execution_engine.order_manager import OrderManager
from .config import load_config, save_config
from .logging_utils import configure_logging, log_event
from .models import BotConfig, DecisionRecord, DryRunResult, HealthStatus, KalshiStatus, Order, TradingMode
from .risk.risk_manager import RiskManager
from .state import BotState
from .storage import (
    fetch_decisions,
    fetch_fills,
    fetch_orders,
    fetch_positions,
    fetch_snapshots,
    init_db,
    log_fill,
    upsert_order,
    upsert_position,
)
from .strategy.engine import compute_pnl_pct, decide_entry, decide_exit
from .strategy.scanner import scan_markets
from .strategy.scoring import MarketMetrics

app = FastAPI(title="Kalshi Volatility Trader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

state = BotState()


class WebSocketManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        if not self.connections:
            return
        for connection in list(self.connections):
            await connection.send_json(message)


manager = WebSocketManager()


@app.on_event("startup")
async def startup() -> None:
    configure_logging()
    init_db()
    state.config = load_config()


@app.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    return HealthStatus(
        status="ok",
        kalshi_configured=state.kalshi_client.configured(),
        openai_configured=state.openai.configured(),
    )


@app.get("/kalshi/status", response_model=KalshiStatus)
async def kalshi_status() -> KalshiStatus:
    status = state.kalshi_broker.auth_status()
    if not status.connected:
        log_event("kalshi_status_error", {"error": status.last_error_summary})
    return KalshiStatus(
        connected=status.connected,
        environment=status.environment,
        account_masked=status.account_masked,
        last_error_summary=status.last_error_summary,
        mode=state.config.trading_mode,
    )


@app.get("/config", response_model=BotConfig)
async def get_config() -> BotConfig:
    return state.config


@app.post("/config", response_model=BotConfig)
async def update_config(payload: Dict[str, Any]) -> BotConfig:
    live_confirm = payload.pop("live_confirm", None)
    updated = state.config.model_dump()

    def deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    updated = deep_merge(updated, payload)
    updated["live_trading_enabled"] = state.config.live_trading_enabled
    if live_confirm is not None:
        updated["live_confirm"] = live_confirm
    config = BotConfig(**updated)
    if config.trading_mode == TradingMode.LIVE:
        if not config.live_trading_enabled:
            raise HTTPException(status_code=400, detail="Live trading disabled on server")
        if config.live_confirm != "ENABLE LIVE TRADING":
            raise HTTPException(status_code=400, detail="Missing live trading confirmation")
        if state.kalshi_client.environment_label() != "live":
            raise HTTPException(status_code=400, detail="Kalshi environment is not live")
    state.config = config
    state.risk = RiskManager(state.config.risk_limits)
    state.kalshi_broker.live_gate_enabled = state.config.live_trading_enabled
    state.kalshi_broker.live_confirm = state.config.live_confirm
    state.order_manager = OrderManager(state.broker, state.config)
    save_config(state.config)
    return state.config


@app.get("/markets/scan")
async def get_scan() -> Dict[str, Any]:
    if not state.last_scan:
        return {"markets": [], "timestamp": None}
    return state.last_scan.model_dump()


@app.get("/markets/{market_id}/detail")
async def get_market_detail(market_id: str) -> Dict[str, Any]:
    market_state = state.market_state.get(market_id)
    if not market_state or not market_state.last_snapshot:
        raise HTTPException(status_code=404, detail="Market not found")
    recent_prices = list(market_state.prices)[-30:]
    audit = [record for record in fetch_decisions(200) if record.market_id == market_id][:10]
    return {
        "snapshot": market_state.last_snapshot.model_dump(),
        "recent_prices": recent_prices,
        "audit": [record.model_dump() for record in audit],
    }


@app.get("/positions")
async def get_positions() -> Dict[str, Any]:
    positions = fetch_positions()
    return {"positions": [pos.model_dump() for pos in positions]}


@app.get("/orders")
async def get_orders() -> Dict[str, Any]:
    orders = fetch_orders()
    return {"orders": [order.model_dump() for order in orders]}


@app.get("/audit")
async def get_audit() -> Dict[str, Any]:
    records = fetch_decisions()
    return {"records": [record.model_dump() for record in records]}


@app.get("/decisions")
async def get_decisions() -> Dict[str, Any]:
    records = fetch_decisions()
    return {"records": [record.model_dump() for record in records]}


@app.get("/fills")
async def get_fills() -> Dict[str, Any]:
    return {"fills": fetch_fills()}


@app.get("/snapshots")
async def get_snapshots() -> Dict[str, Any]:
    return {"snapshots": fetch_snapshots()}


@app.get("/audit/csv")
async def download_audit_csv() -> StreamingResponse:
    records = fetch_decisions()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "timestamp",
            "market_id",
            "action",
            "reason_code",
            "qualifies",
            "scores",
            "rationale",
            "config_hash",
            "order_ids",
            "fills",
            "advisory",
        ]
    )
    for record in records:
        writer.writerow(
            [
                record.timestamp.isoformat(),
                record.market_id,
                record.action,
                record.reason_code,
                record.qualifies,
                record.scores,
                record.rationale,
                record.config_hash,
                record.order_ids,
                record.fills,
                record.advisory,
            ]
        )
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="text/csv")


@app.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str) -> Dict[str, str]:
    try:
        response = state.broker.cancel_order(order_id)
        return {"status": response.get("status", "cancelled")}
    except Exception as exc:  # noqa: BLE001
        log_event("order_cancel_error", {"order_id": order_id, "error": str(exc)})
        raise HTTPException(status_code=400, detail="Unable to cancel order") from exc


@app.post("/orders/place")
async def place_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    if state.config.trading_mode != TradingMode.PAPER:
        raise HTTPException(status_code=400, detail="Manual orders only allowed in paper mode")
    ticker = payload.get("ticker")
    side = payload.get("side")
    action = payload.get("action", "buy")
    price = payload.get("price")
    qty = payload.get("qty", 1)
    if not ticker or not side or price is None:
        raise HTTPException(status_code=400, detail="Missing ticker/side/price")
    try:
        response = state.broker.place_order(ticker, action, side, float(price), int(qty))
        now = datetime.now(tz=timezone.utc)
        order = Order(
            order_id=response.get("order_id", ""),
            market_id=ticker,
            action=action,
            side=side,
            price=float(price),
            qty=int(qty),
            status=response.get("status", "open"),
            created_at=now,
            filled_at=now if response.get("status") == "filled" else None,
        )
        upsert_order(order)
        if response.get("filled_qty"):
            log_fill(order.order_id, ticker, action, side, float(price), int(response.get("filled_qty", 0)))
        return response
    except Exception as exc:  # noqa: BLE001
        log_event("manual_order_error", {"error": str(exc)})
        raise HTTPException(status_code=400, detail="Unable to place order") from exc


@app.post("/positions/{position_id}/close")
async def close_position(position_id: str) -> Dict[str, str]:
    position = state.positions.get(position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    market_state = state.market_state.get(position.market_id)
    if not market_state or not market_state.last_snapshot:
        raise HTTPException(status_code=400, detail="No market data available")
    snapshot = market_state.last_snapshot
    price = snapshot.bid if position.side == "yes" else snapshot.ask
    try:
        response = state.broker.place_order(
            position.market_id,
            "sell",
            position.side,
            price,
            position.qty,
        )
        position.status = "closed"
        position.closed_at = datetime.now(tz=timezone.utc)
        upsert_position(position)
        return {"status": response.get("status", "submitted")}
    except Exception as exc:  # noqa: BLE001
        log_event("position_close_error", {"position_id": position_id, "error": str(exc)})
        raise HTTPException(status_code=400, detail="Unable to close position") from exc


@app.post("/positions/flatten")
async def flatten_all() -> Dict[str, Any]:
    order_ids: list[str] = []
    closed_positions: list[str] = []
    errors: list[str] = []

    try:
        open_orders = state.broker.get_open_orders()
    except Exception as exc:  # noqa: BLE001
        log_event("flatten_orders_error", {"error": str(exc)})
        open_orders = []

    for order in open_orders:
        order_id = order.get("order_id")
        if not order_id:
            continue
        try:
            state.broker.cancel_order(order_id)
            order_ids.append(order_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"cancel:{order_id}:{exc}")

    order_manager = state.order_manager
    for position in list(state.positions.values()):
        if position.status != "open":
            continue
        market_state = state.market_state.get(position.market_id)
        snapshot = market_state.last_snapshot if market_state else None
        if not snapshot:
            errors.append(f"close:{position.position_id}:missing_snapshot")
            continue
        try:
            result = await order_manager.close_with_limit(
                position.market_id,
                position.side,
                snapshot.bid,
                snapshot.ask,
                position.qty,
            )
            position.status = "closed"
            position.closed_at = datetime.now(tz=timezone.utc)
            upsert_position(position)
            closed_positions.append(position.position_id)
            log_event("flatten_position_closed", {"position_id": position.position_id, "order_id": result.order_id})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"close:{position.position_id}:{exc}")

    return {"cancelled_orders": order_ids, "closed_positions": closed_positions, "errors": errors}


@app.post("/bot/dryrun", response_model=DryRunResult)
async def dry_run() -> DryRunResult:
    scan = scan_markets(state)
    decisions: list[DecisionRecord] = []
    positions = [pos for pos in state.positions.values() if pos.status == "open"]
    for snapshot in scan.markets:
        market_state = state.market_state.get(snapshot.market_id)
        metrics = MarketMetrics(
            volatility_pct=snapshot.volatility_pct,
            spread_pct=snapshot.spread_pct,
            liquidity_score=snapshot.liquidity_score,
            overall_score=snapshot.overall_score,
            qualifies=snapshot.qualifies,
            rationale=snapshot.rationale,
        )
        risk_allows, risk_reason = state.risk.can_trade()
        in_cooldown = bool(market_state and market_state.cooldown_until and market_state.cooldown_until > scan.timestamp)
        decision = decide_entry(
            prices=market_state.prices if market_state else [],
            bid=snapshot.bid,
            ask=snapshot.ask,
            config=state.config,
            risk_allows=risk_allows,
            risk_reason=risk_reason,
            in_cooldown=in_cooldown,
            expected_edge_cost_pct=snapshot.spread_pct + state.config.entry.fee_pct,
        )
        decisions.append(
            DecisionRecord(
                timestamp=scan.timestamp,
                market_id=snapshot.market_id,
                action=decision.action,
                reason_code=decision.reason_code,
                qualifies=snapshot.qualifies,
                scores={**metrics.__dict__, "expected_edge_pct": decision.expected_edge_pct},
                rationale=decision.rationale,
                config_hash="dryrun",
                order_ids=[],
                fills=[],
                advisory=None,
            )
        )
    for position in positions:
        market_state = state.market_state.get(position.market_id)
        snapshot = market_state.last_snapshot if market_state else None
        if not snapshot:
            continue
        now = scan.timestamp
        decision, _, _ = decide_exit(
            position.entry_price,
            snapshot.mid_price,
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
        pnl_pct = compute_pnl_pct(position.entry_price, snapshot.mid_price, position.side)
        decisions.append(
            DecisionRecord(
                timestamp=scan.timestamp,
                market_id=position.market_id,
                action=decision.action,
                reason_code=decision.reason_code,
                qualifies=True,
                scores={"pnl_pct": pnl_pct},
                rationale=decision.rationale,
                config_hash="dryrun",
                order_ids=[],
                fills=[],
                advisory=None,
            )
        )
    return DryRunResult(scan=scan, decisions=decisions)


@app.post("/bot/start")
async def start_bot() -> Dict[str, str]:
    if state.running:
        return {"status": "already_running"}
    state.running = True
    state.killed = False
    state.next_action = "Initializing"
    await manager.broadcast({"type": "status", "data": state.status_snapshot().model_dump()})

    async def publish(event_type: str, data: Dict[str, Any]) -> None:
        await manager.broadcast({"type": event_type, "data": data})

    state.task = asyncio.create_task(run_bot(state, publish))
    return {"status": "started"}


@app.post("/bot/stop")
async def stop_bot() -> Dict[str, str]:
    state.running = False
    if state.task:
        state.task.cancel()
        state.task = None
    state.next_action = "Paused"
    await manager.broadcast({"type": "status", "data": state.status_snapshot().model_dump()})
    return {"status": "stopped"}


@app.post("/bot/kill")
async def kill_bot() -> Dict[str, str]:
    state.running = False
    state.killed = True
    try:
        for order in state.broker.get_open_orders():
            order_id = order.get("order_id")
            if order_id:
                state.broker.cancel_order(order_id)
    except Exception as exc:  # noqa: BLE001
        log_event("kill_switch_error", {"error": str(exc)})
    if state.task:
        state.task.cancel()
        state.task = None
    state.next_action = "Killed (manual restart required)"
    await manager.broadcast({"type": "status", "data": state.status_snapshot().model_dump()})
    return {"status": "killed"}


@app.get("/bot/status")
async def bot_status() -> Dict[str, Any]:
    return state.status_snapshot().model_dump()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        await manager.broadcast({"type": "status", "data": state.status_snapshot().model_dump()})
        if state.last_scan:
            await manager.broadcast({"type": "scan", "data": state.last_scan.model_dump()})
        await manager.broadcast({"type": "positions", "data": {"positions": [pos.model_dump() for pos in state.positions.values()]}})
        await manager.broadcast({"type": "activity", "data": {"entries": [entry.model_dump() for entry in state.activity_entries()]}})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


frontend_path = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
