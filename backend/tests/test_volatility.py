from app.trading_engine import compute_log_returns


def test_compute_log_returns():
    prices = [0.5, 0.52, 0.48, 0.55, 0.6]
    returns = compute_log_returns(prices)
    assert len(returns) == len(prices) - 1
    assert all(isinstance(value, float) for value in returns)
