from app.kalshi_client import KalshiClient


def test_signature_message_strips_query():
    message = KalshiClient.build_signature_message(
        "1700000000000", "GET", "/trade-api/v2/portfolio/orders?status=open"
    )
    assert message == "1700000000000GET/trade-api/v2/portfolio/orders"


def test_client_uses_trade_api_endpoints():
    class Recorder(KalshiClient):
        def __init__(self) -> None:
            super().__init__()
            self.paths = []

        def _request(self, method, path, params=None, payload=None, timeout=20):
            self.paths.append(path)
            return {}

    client = Recorder()
    client.place_order(
        {
            "ticker": "TEST",
            "action": "buy",
            "side": "yes",
            "type": "limit",
            "yes_price_dollars": "0.5000",
            "count": 1,
        }
    )
    client.cancel_order("abc")
    client.get_open_orders()
    client.get_positions()
    client.get_fills()

    assert "/portfolio/orders" in client.paths[0]
    assert "/portfolio/orders/abc" in client.paths[1]
    assert "/portfolio/orders" in client.paths[2]
    assert "/portfolio/positions" in client.paths[3]
    assert "/portfolio/fills" in client.paths[4]
