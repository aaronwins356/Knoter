from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

from .models import ActivityEntry, DecisionRecord, Order, Position, ScanSnapshot

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "audit.db"


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                action TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                filled_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                market_id TEXT NOT NULL,
                action TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                market_name TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                take_profit_pct REAL NOT NULL,
                stop_loss_pct REAL NOT NULL,
                max_hold_seconds INTEGER NOT NULL,
                close_before_resolution_minutes INTEGER NOT NULL,
                opened_at TEXT NOT NULL,
                status TEXT NOT NULL,
                pnl_pct REAL NOT NULL,
                peak_pnl_pct REAL NOT NULL,
                trail_stop_pct REAL,
                closed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                action TEXT NOT NULL,
                qualifies INTEGER NOT NULL,
                scores TEXT NOT NULL,
                rationale TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                order_ids TEXT NOT NULL,
                fills TEXT NOT NULL,
                advisory TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )


def log_activity(entry: ActivityEntry) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO activity_log (timestamp, category, message) VALUES (?, ?, ?)",
            (entry.timestamp.isoformat(), entry.category, entry.message),
        )


def fetch_activity(limit: int = 20) -> List[ActivityEntry]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT timestamp, category, message FROM activity_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        ActivityEntry(timestamp=datetime.fromisoformat(row[0]), category=row[1], message=row[2])
        for row in rows
    ]


def upsert_order(order: Order) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO orders (order_id, market_id, action, side, price, qty, status, created_at, filled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET status=excluded.status, filled_at=excluded.filled_at
            """,
            (
                order.order_id,
                order.market_id,
                order.action,
                order.side,
                order.price,
                order.qty,
                order.status,
                order.created_at.isoformat(),
                order.filled_at.isoformat() if order.filled_at else None,
            ),
        )


def fetch_orders(limit: int = 50) -> List[Order]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT order_id, market_id, action, side, price, qty, status, created_at, filled_at FROM orders ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        Order(
            order_id=row[0],
            market_id=row[1],
            action=row[2],
            side=row[3],
            price=row[4],
            qty=row[5],
            status=row[6],
            created_at=datetime.fromisoformat(row[7]),
            filled_at=datetime.fromisoformat(row[8]) if row[8] else None,
        )
        for row in rows
    ]


def upsert_position(position: Position) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                position_id,
                market_id,
                market_name,
                side,
                qty,
                entry_price,
                current_price,
                take_profit_pct,
                stop_loss_pct,
                max_hold_seconds,
                close_before_resolution_minutes,
                opened_at,
                status,
                pnl_pct,
                peak_pnl_pct,
                trail_stop_pct,
                closed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(position_id) DO UPDATE SET
                current_price=excluded.current_price,
                status=excluded.status,
                pnl_pct=excluded.pnl_pct,
                peak_pnl_pct=excluded.peak_pnl_pct,
                trail_stop_pct=excluded.trail_stop_pct,
                closed_at=excluded.closed_at
            """,
            (
                position.position_id,
                position.market_id,
                position.market_name,
                position.side,
                position.qty,
                position.entry_price,
                position.current_price,
                position.take_profit_pct,
                position.stop_loss_pct,
                position.max_hold_seconds,
                position.close_before_resolution_minutes,
                position.opened_at.isoformat(),
                position.status,
                position.pnl_pct,
                position.peak_pnl_pct,
                position.trail_stop_pct,
                position.closed_at.isoformat() if position.closed_at else None,
            ),
        )


def fetch_positions(limit: int = 50) -> List[Position]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT position_id, market_id, market_name, side, qty, entry_price, current_price, take_profit_pct,
                   stop_loss_pct, max_hold_seconds, close_before_resolution_minutes, opened_at, status, pnl_pct,
                   peak_pnl_pct, trail_stop_pct, closed_at
            FROM positions ORDER BY opened_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        Position(
            position_id=row[0],
            market_id=row[1],
            market_name=row[2],
            side=row[3],
            qty=row[4],
            entry_price=row[5],
            current_price=row[6],
            take_profit_pct=row[7],
            stop_loss_pct=row[8],
            max_hold_seconds=row[9],
            close_before_resolution_minutes=row[10],
            opened_at=datetime.fromisoformat(row[11]),
            status=row[12],
            pnl_pct=row[13],
            peak_pnl_pct=row[14],
            trail_stop_pct=row[15],
            closed_at=datetime.fromisoformat(row[16]) if row[16] else None,
        )
        for row in rows
    ]


def log_decision(record: DecisionRecord) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO decisions (
                timestamp,
                market_id,
                action,
                qualifies,
                scores,
                rationale,
                config_hash,
                order_ids,
                fills,
                advisory
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.timestamp.isoformat(),
                record.market_id,
                record.action,
                1 if record.qualifies else 0,
                json.dumps(record.scores),
                record.rationale,
                record.config_hash,
                json.dumps(record.order_ids),
                json.dumps(record.fills),
                json.dumps(record.advisory) if record.advisory else None,
            ),
        )


def fetch_decisions(limit: int = 200) -> List[DecisionRecord]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT timestamp, market_id, action, qualifies, scores, rationale, config_hash, order_ids, fills, advisory
            FROM decisions ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    records = []
    for row in rows:
        records.append(
            DecisionRecord(
                timestamp=datetime.fromisoformat(row[0]),
                market_id=row[1],
                action=row[2],
                qualifies=bool(row[3]),
                scores=json.loads(row[4]),
                rationale=row[5],
                config_hash=row[6],
                order_ids=json.loads(row[7]),
                fills=json.loads(row[8]),
                advisory=json.loads(row[9]) if row[9] else None,
            )
        )
    return records


def log_fill(order_id: str, market_id: str, action: str, side: str, price: float, qty: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO fills (order_id, market_id, action, side, price, qty, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (order_id, market_id, action, side, price, qty, datetime.now().isoformat()),
        )


def fetch_fills(limit: int = 200) -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT order_id, market_id, action, side, price, qty, timestamp
            FROM fills ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "order_id": row[0],
            "market_id": row[1],
            "action": row[2],
            "side": row[3],
            "price": row[4],
            "qty": row[5],
            "timestamp": row[6],
        }
        for row in rows
    ]


def log_snapshot(scan: ScanSnapshot) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO snapshots (timestamp, payload) VALUES (?, ?)",
            (scan.timestamp.isoformat(), json.dumps(scan.model_dump())),
        )


def fetch_snapshots(limit: int = 50) -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT payload FROM snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [json.loads(row[0]) for row in rows]
