import time

from app.broker.kalshi import KalshiBroker


class DummyClient:
    def __init__(self) -> None:
        self.market_params = []

    def list_series(self, params=None, fetch_all=True):
        return []

    def list_events(self, params=None, fetch_all=True):
        return []

    def list_markets(self, params=None, fetch_all=True):
        self.market_params.append(params or {})
        return [
            {
                "ticker": "TEST-MKT",
                "title": "NBA Finals Winner",
                "status": "open",
                "close_ts": int(time.time()) + 3600,
            }
        ]

    def configured(self):
        return False

    def environment_label(self):
        return "demo"


class SeriesClient(DummyClient):
    def __init__(self) -> None:
        super().__init__()
        self.events_params = []

    def list_series(self, params=None, fetch_all=True):
        return [{"ticker": "SER-2024", "title": "Election 2024"}]

    def list_events(self, params=None, fetch_all=True):
        self.events_params.append(params or {})
        return [{"ticker": "EVT-2024"}]


def test_market_discovery_fallback_builds_time_window():
    client = DummyClient()
    broker = KalshiBroker(client, live_gate_enabled=False, live_confirm="")
    start = int(time.time())
    markets = broker.list_markets("sports", 2)
    assert markets
    params = client.market_params[0]
    assert params["status"] == "open"
    assert params["min_close_ts"] >= start
    assert params["max_close_ts"] >= params["min_close_ts"]


def test_market_discovery_uses_series_and_events():
    client = SeriesClient()
    broker = KalshiBroker(client, live_gate_enabled=False, live_confirm="")
    markets = broker.list_markets("politics", 4)
    assert markets
    assert client.events_params[0]["series_ticker"] == "SER-2024"
    assert client.market_params[0]["event_ticker"] == "EVT-2024"
