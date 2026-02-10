from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import requests
from ..logging_utils import log_event


DEMO_API_ROOT = "https://demo-api.kalshi.co"
LIVE_API_ROOT = "https://api.kalshi.com"
API_PREFIX = "/trade-api/v2"


@dataclass(frozen=True)
class KalshiEnvironment:
    name: str
    api_root: str


def _resolve_environment() -> KalshiEnvironment:
    env = os.getenv("KALSHI_ENV", "demo").lower()
    if env == "live":
        return KalshiEnvironment(name="live", api_root=LIVE_API_ROOT)
    return KalshiEnvironment(name="demo", api_root=DEMO_API_ROOT)


class KalshiClient:
    def __init__(self) -> None:
        environment = _resolve_environment()
        self.environment = environment
        api_root = os.getenv("KALSHI_BASE_URL") or environment.api_root
        self.base_url = f"{api_root.rstrip('/')}{API_PREFIX}"
        self.api_key = os.getenv("KALSHI_API_KEY_ID") or os.getenv("KALSHI_API_KEY")
        self.private_key = self._load_private_key()
        self.max_retries = int(os.getenv("KALSHI_MAX_RETRIES", "3"))
        self.last_error: Optional[str] = None

    def configured(self) -> bool:
        return bool(self.api_key and self.private_key)

    def environment_label(self) -> str:
        return self.environment.name

    def _load_private_key(self):
        pem_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        pem_data = os.getenv("KALSHI_PRIVATE_KEY_PEM")
        raw = None
        if pem_path:
            with open(pem_path, "rb") as handle:
                raw = handle.read()
        elif pem_data:
            raw = pem_data.encode()
        if not raw:
            return None
        from cryptography.hazmat.primitives import serialization

        return serialization.load_pem_private_key(raw, password=None)

    @staticmethod
    def _strip_query(path: str) -> str:
        parsed = urlsplit(path)
        return parsed.path

    @staticmethod
    def build_signature_message(timestamp_ms: str, method: str, path: str) -> str:
        clean_path = KalshiClient._strip_query(path)
        return f"{timestamp_ms}{method.upper()}{clean_path}"

    def _signature_headers(self, method: str, path: str) -> Dict[str, str]:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        timestamp = str(int(time.time() * 1000))
        signature_path = path if path.startswith(API_PREFIX) else f"{API_PREFIX}{path}"
        message = self.build_signature_message(timestamp, method, signature_path)
        signature = base64.b64encode(
            self.private_key.sign(
                message.encode(),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
        ).decode()
        return {
            "KALSHI-ACCESS-KEY": self.api_key or "",
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 20,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload) if payload else None
        headers = {"Content-Type": "application/json"}
        if self.configured():
            headers.update(self._signature_headers(method, path))
        self.last_error = None
        for attempt in range(self.max_retries):
            try:
                response = requests.request(
                    method,
                    url,
                    params=params,
                    data=body,
                    headers=headers,
                    timeout=timeout,
                )
                request_id = response.headers.get("X-Request-ID") or response.headers.get("X-Request-Id")
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"Retryable status: {response.status_code}")
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                self.last_error = self._summarize_error(exc)
                if attempt >= self.max_retries - 1:
                    snippet = ""
                    status_code = None
                    request_id = None
                    if isinstance(exc, requests.HTTPError) and exc.response is not None:
                        status_code = exc.response.status_code
                        request_id = exc.response.headers.get("X-Request-ID") or exc.response.headers.get("X-Request-Id")
                        snippet = exc.response.text[:300]
                    log_event(
                        "kalshi_request_failed",
                        {
                            "path": path,
                            "error": self.last_error,
                            "status_code": status_code,
                            "request_id": request_id,
                            "response_snippet": snippet,
                        },
                    )
                    raise RuntimeError("Kalshi API request failed") from exc
                time.sleep(1 + attempt)
        raise RuntimeError("Kalshi API request failed")

    @staticmethod
    def _summarize_error(exc: Exception) -> str:
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status = exc.response.status_code
            if status in {401, 403}:
                return "Authentication failed (check signature string, timestamp ms, key ID, and base URL)."
            if status == 404:
                return "Endpoint not found (check KALSHI_BASE_URL and /trade-api/v2 prefix)."
            if status == 400:
                return "Bad request (verify signing path without query params and payload fields)."
            if status >= 500:
                return "Kalshi API unavailable (server error)."
        return str(exc)

    def get_portfolio_balance(self) -> Dict[str, Any]:
        return self._request("GET", "/portfolio/balance")

    def list_markets(
        self,
        params: Optional[Dict[str, Any]] = None,
        fetch_all: bool = True,
    ) -> List[Dict[str, Any]]:
        markets: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            request_params = dict(params or {})
            if cursor:
                request_params["cursor"] = cursor
            payload = self._request("GET", "/markets", params=request_params)
            markets.extend(payload.get("markets", []))
            cursor = payload.get("cursor") or payload.get("next_cursor")
            if not fetch_all or not cursor:
                break
        return markets

    def list_series(
        self,
        params: Optional[Dict[str, Any]] = None,
        fetch_all: bool = True,
    ) -> List[Dict[str, Any]]:
        series: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            request_params = dict(params or {})
            if cursor:
                request_params["cursor"] = cursor
            payload = self._request("GET", "/series", params=request_params)
            series.extend(payload.get("series", []))
            cursor = payload.get("cursor") or payload.get("next_cursor")
            if not fetch_all or not cursor:
                break
        return series

    def list_events(
        self,
        params: Optional[Dict[str, Any]] = None,
        fetch_all: bool = True,
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            request_params = dict(params or {})
            if cursor:
                request_params["cursor"] = cursor
            payload = self._request("GET", "/events", params=request_params)
            events.extend(payload.get("events", []))
            cursor = payload.get("cursor") or payload.get("next_cursor")
            if not fetch_all or not cursor:
                break
        return events

    def get_market(self, ticker: str) -> Dict[str, Any]:
        return self._request("GET", f"/markets/{ticker}")

    def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_order_payload(payload)
        return self._request("POST", "/portfolio/orders", payload=payload)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/portfolio/orders", params={"status": "open"}).get("orders", [])

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/portfolio/orders/{order_id}")

    def get_positions(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/portfolio/positions").get("positions", [])

    def get_fills(self, since: Optional[int] = None) -> List[Dict[str, Any]]:
        params = {"since": since} if since else None
        return self._request("GET", "/portfolio/fills", params=params).get("fills", [])

    def format_order_payload(
        self, ticker: str, action: str, side: str, price: float, qty: int, order_type: str = "limit"
    ) -> Dict[str, Any]:
        price_str = f"{float(price):.4f}"
        payload = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "type": order_type,
            "count": int(qty),
        }
        if side == "yes":
            payload["yes_price_dollars"] = price_str
        else:
            payload["no_price_dollars"] = price_str
        return payload

    def _validate_order_payload(self, payload: Dict[str, Any]) -> None:
        ticker = payload.get("ticker")
        action = payload.get("action")
        side = payload.get("side")
        qty = payload.get("count") or payload.get("count_fp") or payload.get("size")
        yes_price = payload.get("yes_price_dollars")
        no_price = payload.get("no_price_dollars")
        if not ticker or not isinstance(ticker, str):
            raise ValueError("Order payload missing ticker")
        if action not in {"buy", "sell"}:
            raise ValueError("Order payload action must be buy or sell")
        if side not in {"yes", "no"}:
            raise ValueError("Order payload side must be yes or no")
        if qty is None or int(qty) <= 0:
            raise ValueError("Order payload count must be positive")
        price_value = yes_price if side == "yes" else no_price
        if price_value is None:
            raise ValueError("Order payload missing yes_price_dollars/no_price_dollars")
        try:
            price_float = float(price_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Order payload price must be a decimal string") from exc
        if not (0.01 <= price_float <= 0.99):
            raise ValueError("Order payload price must be between 0.01 and 0.99 dollars")
        log_event(
            "kalshi_order_request",
            {
                "ticker": ticker,
                "action": action,
                "side": side,
                "price": round(price_float, 4),
                "count": int(qty),
                "type": payload.get("type"),
            },
        )
