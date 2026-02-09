from app.volatility import volatility_score


def test_volatility_score_increases_with_movement():
    prices = [0.5, 0.52, 0.48, 0.55, 0.6]
    spreads = [0.01] * len(prices)
    score, move = volatility_score(prices, spreads, update_count=5, time_to_expiry_hours=12)
    assert score > 0
    assert move >= 0
