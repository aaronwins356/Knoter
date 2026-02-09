from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    def build_market_query(now_ts: int, time_window_hours: int, status: str = "open") -> Dict[str, Any]:
        return {
            "status": status,
            "min_close_ts": now_ts,
            "max_close_ts": now_ts + (time_window_hours * 3600),
            "limit": 200,
        }

    def get_markets_windowed(self, now_ts: int, time_window_hours: int, status: str = "open") -> List[MarketInfo]:
        params = self.build_market_query(now_ts, time_window_hours, status=status)
        markets = self.client.list_markets(params=params, fetch_all=True)
        normalized: List[MarketInfo] = []
        for item in markets:
            ticker = item.get("ticker") or item.get("market_ticker") or ""
            if not ticker:
                continue
            meta = normalize_market_meta(item, now_ts=now_ts)
            normalized.append(
                MarketInfo(
                    ticker=ticker,
                    title=item.get("title") or item.get("name") or "Unknown",
                    close_ts=meta["close_ts"],
                    status=(item.get("status") or status).lower(),
                    category="",
                    raw_payload=item,
                )
            )
        return normalized

    def list_markets(self, event_type: str, time_window_hours: int) -> List[MarketInfo]:
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        keywords = self._keywords_for_event_type(event_type)
        series_tickers, event_tickers = self._resolve_focus_tickers(keywords)

        collected: Dict[str, MarketInfo] = {}
        windowed = self.get_markets_windowed(now_ts, time_window_hours, status="open")
        for market in windowed:
            payload = market.raw_payload
            series_ticker = payload.get("series_ticker")
            event_ticker = payload.get("event_ticker")
            if event_tickers and event_ticker:
                if event_ticker not in event_tickers:
                    continue
            elif series_tickers and series_ticker:
                if series_ticker not in series_tickers:
                    continue
            elif not self._market_matches(payload, keywords):
                continue
            market = MarketInfo(
                ticker=market.ticker,
                title=market.title,
                close_ts=market.close_ts,
                status=(payload.get("status") or "open").lower(),
                category=event_type,
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
    def _keywords_for_event_type(event_type: str) -> List[str]:
        mapping = {
            "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "game", "match", "playoff", "championship"],
            "politics": ["election", "vote", "senate", "house", "president", "ballot", "poll"],
            "finance": ["fed", "rate", "inflation", "cpi", "gdp", "jobs", "treasury", "oil", "macro"],
            "company": ["earnings", "revenue", "guidance", "ipo", "stock", "ceo"],
        }
        return mapping.get(event_type, [event_type])

    def _resolve_focus_tickers(self, keywords: Iterable[str]) -> Tuple[set[str], set[str]]:
        series_tickers: set[str] = set()
        event_tickers: set[str] = set()
        try:
            series = self.client.list_series(params={"limit": 200}, fetch_all=True)
        except Exception as exc:  # noqa: BLE001
            log_event("series_lookup_failed", {"error": str(exc)})
            return series_tickers, event_tickers
        for item in series:
            if self._series_matches(item, keywords):
                ticker = item.get("ticker")
                if ticker:
                    series_tickers.add(ticker)
        for series_ticker in series_tickers:
            try:
                events = self.client.list_events(
                    params={"status": "open", "series_ticker": series_ticker, "limit": 200},
                    fetch_all=True,
                )
            except Exception as exc:  # noqa: BLE001
                log_event("event_lookup_failed", {"series_ticker": series_ticker, "error": str(exc)})
                continue
            for event in events:
                event_ticker = event.get("ticker") or event.get("event_ticker")
                if event_ticker:
                    event_tickers.add(event_ticker)
        return series_tickers, event_tickers

    @staticmethod
    def _series_matches(series: Dict[str, Any], keywords: Iterable[str]) -> bool:
        title = (series.get("title") or series.get("name") or "").lower()
        tags = " ".join(series.get("tags", []) if isinstance(series.get("tags"), list) else [])
        haystack = f"{title} {tags}".lower()
        return any(keyword in haystack for keyword in keywords)

    @staticmethod
    def _market_matches(market: Dict[str, Any], keywords: Iterable[str]) -> bool:
        title = (market.get("title") or market.get("name") or "").lower()
        event_title = (market.get("event_title") or "").lower()
        series_title = (market.get("series_title") or market.get("series_name") or "").lower()
        haystack = f"{title} {event_title} {series_title}".lower()
        return any(keyword in haystack for keyword in keywords)
