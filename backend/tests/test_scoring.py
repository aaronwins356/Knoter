from app.models import BotConfig
from app.strategy.scoring import compute_market_metrics


def test_scoring_volatility_spread_liquidity():
    config = BotConfig()
    prices = [0.5, 0.51, 0.49, 0.52, 0.5, 0.53]
    metrics = compute_market_metrics(
        prices=prices,
        bid=0.49,
        ask=0.51,
        volume=500.0,
        bid_depth=300.0,
        ask_depth=300.0,
        update_rate=2.0,
        time_to_resolution_minutes=240,
        config=config,
    )
    assert metrics.volatility_pct >= 0
    assert metrics.spread_pct > 0
    assert metrics.liquidity_score > 0
