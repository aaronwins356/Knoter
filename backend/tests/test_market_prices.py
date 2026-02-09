from app.market_data import normalize_market_prices


def test_normalize_prices_prefers_dollars_fields():
    payload = {
        "yes_bid_dollars": 0.41,
        "yes_ask_dollars": 0.45,
        "last_price_dollars": 0.44,
        "volume": 120,
        "close_ts": 1_700_000_000,
    }
    normalized = normalize_market_prices(payload, now_ts=1_699_999_000)
    assert normalized["bid"] == 0.41
    assert normalized["ask"] == 0.45
    assert normalized["last"] == 0.44


def test_normalize_prices_falls_back_to_cent_fields():
    payload = {
        "yes_bid": 0.2,
        "yes_ask": 0.22,
        "last_price": 0.21,
        "minutes_to_expiry": 90,
    }
    normalized = normalize_market_prices(payload)
    assert normalized["bid"] == 0.2
    assert normalized["ask"] == 0.22
    assert normalized["minutes_to_resolution"] == 90
