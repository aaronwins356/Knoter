from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from ..kalshi_client import KalshiClient
from ..logging_utils import log_event
from ..market_data import MarketInfo, normalize_market_prices


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
        if not self.live_gate_enabled or self.live_confirm != "ENABLE LIVE TRADING":
            raise RuntimeError("Live trading is not enabled")
        if self.client.environment_label() != "live":
            raise RuntimeError("Live trading is not enabled")

    def list_markets(self, event_type: str, time_window_hours: int) -> List[MarketInfo]:
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        min_close_ts = now_ts
        max_close_ts = now_ts + (time_window_hours * 3600)
        keywords = self._keywords_for_event_type(event_type)
        collected: Dict[str, MarketInfo] = {}

        def add_market(item: Dict[str, Any]) -> None:
            status = (item.get("status") or "").lower()
            if status and status not in {"open", "active"}:
                return
            market_id = item.get("ticker", item.get("id", ""))
            if not market_id or market_id in collected:
                return
            normalized = normalize_market_prices(item, now_ts=now_ts)
            collected[market_id] = MarketInfo(
                market_id=market_id,
                name=item.get("title", item.get("name", "Unknown")),
                category=event_type,
                time_to_resolution_minutes=float(normalized["minutes_to_resolution"]),
            )

        try:
            series = self.client.list_series(params={"limit": 200}, fetch_all=True)
        except Exception as exc:  # noqa: BLE001
            log_event("series_lookup_failed", {"error": str(exc)})
            series = []

        filtered_series = [item for item in series if self._series_matches(item, keywords)]
        for series_item in filtered_series:
            series_ticker = series_item.get("ticker")
            if not series_ticker:
                continue
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
                if not event_ticker:
                    continue
                markets = self.client.list_markets(
                    params={
                        "status": "open",
                        "event_ticker": event_ticker,
                        "min_close_ts": min_close_ts,
                        "max_close_ts": max_close_ts,
                        "limit": 200,
                    },
                    fetch_all=True,
                )
                for market in markets:
                    add_market(market)

        if not collected:
            markets = self.client.list_markets(
                params={
                    "status": "open",
                    "min_close_ts": min_close_ts,
                    "max_close_ts": max_close_ts,
                    "limit": 200,
                },
                fetch_all=True,
            )
            for market in markets:
                if self._market_matches(market, keywords):
                    add_market(market)

        return list(collected.values())

    def get_market_snapshot(self, ticker: str) -> Dict[str, Any]:
        payload = self.client.get_market(ticker)
        normalized = normalize_market_prices(payload)
        bid = normalized["bid"]
        ask = normalized["ask"]
        mid = normalized["mid"]
        return {
            "mid": mid,
            "bid": bid,
            "ask": ask,
            "last": normalized["last"],
            "volume": float(payload.get("volume", normalized.get("volume", 0.0))),
            "bid_depth": float(payload.get("bid_depth", 0.0)),
            "ask_depth": float(payload.get("ask_depth", 0.0)),
            "time_to_resolution_minutes": float(normalized["minutes_to_resolution"]),
        }

    def place_order(self, ticker: str, action: str, side: str, price: float, qty: int) -> Dict[str, Any]:
        self._ensure_live_gate()
        payload = self.client.format_order_payload(ticker, action, side, price, qty, order_type="limit")
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
        haystack = f"{title} {event_title}".lower()
        return any(keyword in haystack for keyword in keywords)
