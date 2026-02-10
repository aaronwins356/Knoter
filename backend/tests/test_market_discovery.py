import time

from app.broker.kalshi import KalshiBroker


class DummyClient:
    def __init__(self) -> None:
        self.market_params = []

    def list_markets(self, params=None, fetch_all=True):
        self.market_params.append(params or {})
        return [
            {
                "ticker": "TEST-MKT",
                "title": "NBA Finals Winner",
                "status": "active",
                "close_ts": int(time.time()) + 3600,
            }
        ]

    def configured(self):
        return False

    def environment_label(self):
        return "demo"


def test_market_discovery_builds_time_window_and_filters_keywords():
    client = DummyClient()
    broker = KalshiBroker(client, live_gate_enabled=False, live_confirm="")
    start = int(time.time())
    markets = broker.list_markets("sports", 2, keyword_map={"sports": ["nba"]})
    assert markets
    params = client.market_params[0]
    assert params["status"] in {"active", "open"}
    assert params["min_close_ts"] >= start
    assert params["max_close_ts"] >= params["min_close_ts"]
    assert params["limit"] == 200
