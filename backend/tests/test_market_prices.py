from app.market_data import normalize_market_meta, normalize_quote


def test_normalize_prices_prefers_dollars_fields():
    payload = {
        "yes_bid_dollars": 0.41,
        "yes_ask_dollars": 0.45,
        "last_price_dollars": 0.44,
        "volume": 120,
        "close_ts": 1_700_000_000,
    }
    quote = normalize_quote(payload)
    meta = normalize_market_meta(payload, now_ts=1_699_999_000)
    assert quote.yes_bid == 0.41
    assert quote.yes_ask == 0.45
    assert quote.mid_yes == 0.43
    assert meta["minutes_to_resolution"] > 0


def test_normalize_prices_falls_back_to_cent_fields():
    payload = {
        "yes_bid": 20,
        "yes_ask": 22,
        "last_price": 21,
        "minutes_to_expiry": 90,
    }
    quote = normalize_quote(payload)
    meta = normalize_market_meta(payload)
    assert quote.yes_bid == 0.2
    assert quote.yes_ask == 0.22
    assert meta["minutes_to_resolution"] == 90
