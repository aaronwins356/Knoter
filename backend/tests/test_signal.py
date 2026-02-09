from app.signals import qualify_signal


def test_signal_qualification():
    decision = qualify_signal(
        volatility_pct=8.0,
        threshold=6.0,
        spread_pct=2.0,
        max_spread_pct=6.0,
        volume=200.0,
        min_volume=100.0,
    )
    assert decision.qualifies is True
    assert decision.signal in {"Monitor", "Exploit spike"}


def test_signal_rejects_low_volume():
    decision = qualify_signal(
        volatility_pct=8.0,
        threshold=6.0,
        spread_pct=2.0,
        max_spread_pct=6.0,
        volume=20.0,
        min_volume=100.0,
    )
    assert decision.qualifies is False
