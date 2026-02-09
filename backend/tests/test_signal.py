from app.models import BotConfig
from app.trading_engine import compute_market_metrics


def test_market_qualification_passes_thresholds():
    config = BotConfig()
    prices = [0.5, 0.52, 0.55, 0.58, 0.6]
    metrics = compute_market_metrics(
        prices=prices,
        bid=0.59,
        ask=0.61,
        volume=400.0,
        bid_depth=300.0,
        ask_depth=300.0,
        time_to_resolution_minutes=120,
        config=config,
    )
    assert metrics.liquidity_score > 0


def test_market_rejects_wide_spread():
    config = BotConfig()
    metrics = compute_market_metrics(
        prices=[0.5, 0.5, 0.5],
        bid=0.4,
        ask=0.6,
        volume=400.0,
        bid_depth=300.0,
        ask_depth=300.0,
        time_to_resolution_minutes=120,
        config=config,
    )
    assert metrics.qualifies is False
