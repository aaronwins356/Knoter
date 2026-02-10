from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any, Dict, Iterable, List, Optional

from ..kalshi_client import KalshiClient
from ..logging_utils import log_event
from ..market_data import MarketInfo, MarketQuote, Quote, normalize_market_meta, normalize_quote


@dataclass
class KalshiAuthStatus:
    connected: bool
    environment: str
    account_masked: Optional[str]
    last_error_summary: Optional[str]


class KalshiBroker:
    def __init__(self, client: KalshiClient, live_gate_enabled: bool, live_confirm: str) -> None:
        self.client = client
        self.live_gate_enabled = live_gate_enabled
        self.live_confirm = live_confirm

    def configured(self) -> bool:
        return self.client.configured()

    def _ensure_live_gate(self) -> None:
        env_gate = os.getenv("KNOTER_LIVE_TRADING_ENABLED", "false").lower() in {"1", "true", "yes"}
        if not env_gate or not self.live_gate_enabled or self.live_confirm != "ENABLE LIVE TRADING":
            raise RuntimeError("Live trading is not enabled")
        if self.client.environment_label() != "live":
            raise RuntimeError("Live trading is not enabled")

    @staticmethod
    def build_market_query(now_ts: int, time_window_hours: int, status: str = "active") -> Dict[str, Any]:
        return {
            "status": status,
            "min_close_ts": now_ts,
            "max_close_ts": now_ts + (time_window_hours * 3600),
            "limit": 200,
        }

    def get_markets_windowed(self, now_ts: int, time_window_hours: int, status: str = "active") -> List[MarketInfo]:
        statuses = [status]
        if status == "active":
            statuses.append("open")
        normalized: List[MarketInfo] = []
        seen: set[str] = set()
        for status_value in statuses:
            params = self.build_market_query(now_ts, time_window_hours, status=status_value)
            markets = self.client.list_markets(params=params, fetch_all=True)
            for item in markets:
                ticker = item.get("ticker") or item.get("market_ticker") or ""
                if not ticker:
                    continue
                if ticker in seen:
                    continue
                seen.add(ticker)
                meta = normalize_market_meta(item, now_ts=now_ts)
                normalized.append(
                    MarketInfo(
                        ticker=ticker,
                        title=item.get("title") or item.get("name") or "Unknown",
                        close_ts=meta["close_ts"],
                        settlement_ts=meta["settlement_ts"],
                        status=(item.get("status") or status_value).lower(),
                        yes_subtitle=item.get("yes_subtitle") or item.get("yes_title"),
                        no_subtitle=item.get("no_subtitle") or item.get("no_title"),
                        raw_payload=item,
                    )
                )
        return normalized

    def list_markets(
        self, event_type: str, time_window_hours: int, keyword_map: Optional[Dict[str, List[str]]] = None
    ) -> List[MarketInfo]:
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        keywords = self._keywords_for_event_type(event_type, keyword_map)

        collected: Dict[str, MarketInfo] = {}
        windowed = self.get_markets_windowed(now_ts, time_window_hours, status="active")
        for market in windowed:
            payload = market.raw_payload
            if not self._market_matches(payload, keywords):
                continue
            market = MarketInfo(
                ticker=market.ticker,
                title=market.title,
                close_ts=market.close_ts,
                settlement_ts=market.settlement_ts,
                status=(payload.get("status") or "active").lower(),
                yes_subtitle=market.yes_subtitle,
                no_subtitle=market.no_subtitle,
                raw_payload=payload,
            )
            collected.setdefault(market.ticker, market)

        return list(collected.values())

    def get_market_snapshot(self, ticker: str) -> MarketQuote:
        payload = self.client.get_market(ticker)
        quote = normalize_quote(payload)
        meta = normalize_market_meta(payload)
        return MarketQuote(
            quote=quote,
            volume=meta["volume"],
            bid_depth=meta["bid_depth"],
            ask_depth=meta["ask_depth"],
            time_to_resolution_minutes=meta["minutes_to_resolution"],
        )

    def place_order(self, ticker: str, action: str, side: str, price: float, qty: int) -> Dict[str, Any]:
        self._ensure_live_gate()
        payload = self.client.format_order_payload(ticker, action, side, price, qty, order_type="limit")
        log_event(
            "kalshi_order_payload",
            {
                "ticker": ticker,
                "action": action,
                "side": side,
                "count": qty,
                "price": float(price),
            },
        )
        response = self.client.place_order(payload)
        log_event(
            "kalshi_order_response",
            {
                "order_id": response.get("order_id", response.get("id")),
                "status": response.get("status"),
                "filled_qty": response.get("filled_size") or response.get("filled_qty"),
            },
        )
        return {
            "order_id": response.get("order_id", response.get("id", "")),
            "status": response.get("status", "open"),
            "filled_qty": response.get("filled_size", 0) or 0,
            "avg_fill_price": response.get("avg_fill_price"),
        }

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self.client.cancel_order(order_id)

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return self.client.get_open_orders()

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self.client.get_order(order_id)

    def get_positions(self) -> List[Dict[str, Any]]:
        return self.client.get_positions()

    def get_fills(self, since: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.client.get_fills(since)

    def auth_status(self) -> KalshiAuthStatus:
        if not self.client.configured():
            return KalshiAuthStatus(
                connected=False,
                environment=self.client.environment_label(),
                account_masked=None,
                last_error_summary="Missing credentials",
            )
        try:
            payload = self.client.get_portfolio_balance()
            handle = payload.get("member_id") or payload.get("email") or payload.get("account_id")
            masked = None
            if handle:
                handle = str(handle)
                masked = f"{handle[:2]}***{handle[-2:]}" if len(handle) > 4 else "***"
            return KalshiAuthStatus(
                connected=True,
                environment=self.client.environment_label(),
                account_masked=masked,
                last_error_summary=self.client.last_error,
            )
        except Exception as exc:  # noqa: BLE001
            self.client.last_error = str(exc)
            return KalshiAuthStatus(
                connected=False,
                environment=self.client.environment_label(),
                account_masked=None,
                last_error_summary=self.client.last_error,
            )

    @staticmethod
    def _keywords_for_event_type(
        event_type: str, keyword_map: Optional[Dict[str, List[str]]] = None
    ) -> List[str]:
        mapping = keyword_map or {
            "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "game", "match", "playoff", "championship"],
            "politics": ["election", "vote", "senate", "house", "president", "ballot", "poll"],
            "finance": ["fed", "rate", "inflation", "cpi", "gdp", "jobs", "treasury", "oil", "macro"],
            "company": ["earnings", "revenue", "guidance", "ipo", "stock", "ceo"],
        }
        return mapping.get(event_type, [event_type])

    @staticmethod
    def _market_matches(market: Dict[str, Any], keywords: Iterable[str]) -> bool:
        title = (market.get("title") or market.get("name") or "").lower()
        event_title = (market.get("event_title") or "").lower()
        series_title = (market.get("series_title") or market.get("series_name") or "").lower()
        yes_subtitle = (market.get("yes_subtitle") or market.get("yes_title") or "").lower()
        no_subtitle = (market.get("no_subtitle") or market.get("no_title") or "").lower()
        haystack = f"{title} {event_title} {series_title} {yes_subtitle} {no_subtitle}".lower()
        return any(keyword in haystack for keyword in keywords)
