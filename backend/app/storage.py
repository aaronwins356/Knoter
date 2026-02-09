from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

from .models import ActivityEntry, Order, Position

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
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                filled_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                market_name TEXT NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                take_profit_pct REAL NOT NULL,
                stop_loss_pct REAL NOT NULL,
                opened_at TEXT NOT NULL,
                status TEXT NOT NULL,
                pnl_pct REAL NOT NULL
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
            INSERT INTO orders (order_id, market_id, side, price, size, status, created_at, filled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET status=excluded.status, filled_at=excluded.filled_at
            """,
            (
                order.order_id,
                order.market_id,
                order.side,
                order.price,
                order.size,
                order.status,
                order.created_at.isoformat(),
                order.filled_at.isoformat() if order.filled_at else None,
            ),
        )


def fetch_orders(limit: int = 50) -> List[Order]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT order_id, market_id, side, price, size, status, created_at, filled_at FROM orders ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        Order(
            order_id=row[0],
            market_id=row[1],
            side=row[2],
            price=row[3],
            size=row[4],
            status=row[5],
            created_at=datetime.fromisoformat(row[6]),
            filled_at=datetime.fromisoformat(row[7]) if row[7] else None,
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
                entry_price,
                current_price,
                take_profit_pct,
                stop_loss_pct,
                opened_at,
                status,
                pnl_pct
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(position_id) DO UPDATE SET current_price=excluded.current_price, status=excluded.status, pnl_pct=excluded.pnl_pct
            """,
            (
                position.position_id,
                position.market_id,
                position.market_name,
                position.entry_price,
                position.current_price,
                position.take_profit_pct,
                position.stop_loss_pct,
                position.opened_at.isoformat(),
                position.status,
                position.pnl_pct,
            ),
        )


def fetch_positions(limit: int = 50) -> List[Position]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT position_id, market_id, market_name, entry_price, current_price, take_profit_pct,
                   stop_loss_pct, opened_at, status, pnl_pct
            FROM positions ORDER BY opened_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        Position(
            position_id=row[0],
            market_id=row[1],
            market_name=row[2],
            entry_price=row[3],
            current_price=row[4],
            take_profit_pct=row[5],
            stop_loss_pct=row[6],
            opened_at=datetime.fromisoformat(row[7]),
            status=row[8],
            pnl_pct=row[9],
        )
        for row in rows
    ]
