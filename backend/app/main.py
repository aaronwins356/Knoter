from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .bot import run_bot
from .config import load_config, save_config
from .logging_utils import configure_logging
from .models import BotConfig, HealthStatus
from .state import BotState
from .storage import fetch_orders, fetch_positions, init_db

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
        kalshi_configured=state.kalshi.configured(),
        openai_configured=state.openai.configured(),
    )


@app.get("/config", response_model=BotConfig)
async def get_config() -> BotConfig:
    return state.config


@app.post("/config", response_model=BotConfig)
async def update_config(payload: Dict[str, Any]) -> BotConfig:
    updated = state.config.model_dump()
    updated.update(payload)
    state.config = BotConfig(**updated)
    state.risk = state.risk.__class__(state.config.risk_limits)
    state.paper_broker = state.paper_broker.__class__(state.config.trade_params)
    save_config(state.config)
    return state.config


@app.get("/markets/scan")
async def get_scan() -> Dict[str, Any]:
    if not state.last_scan:
        return {"markets": [], "timestamp": None}
    return state.last_scan.model_dump()


@app.get("/positions")
async def get_positions() -> Dict[str, Any]:
    positions = fetch_positions()
    return {"positions": [pos.model_dump() for pos in positions]}


@app.get("/orders")
async def get_orders() -> Dict[str, Any]:
    orders = fetch_orders()
    return {"orders": [order.model_dump() for order in orders]}


@app.post("/bot/start")
async def start_bot() -> Dict[str, str]:
    if state.running:
        return {"status": "already_running"}
    state.running = True
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
