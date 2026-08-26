import pytest

from app.backtesting.costs import FixedBpsSlippage, PerShareCommission, ZeroCommission


def test_zero_commission_is_always_zero():
    model = ZeroCommission()
    assert model.commission(shares=100, price=50.0) == 0.0


def test_per_share_commission():
    model = PerShareCommission(rate_per_share=0.005)
    assert model.commission(shares=100, price=50.0) == pytest.approx(0.5)


def test_per_share_commission_minimum_applies():
    model = PerShareCommission(rate_per_share=0.005, minimum=1.0)
    assert model.commission(shares=10, price=50.0) == pytest.approx(1.0)


def test_fixed_bps_slippage_buy_is_worse_than_reference():
    model = FixedBpsSlippage(bps=10)
    fill = model.fill_price(reference_price=100.0, side="buy")
    assert fill == pytest.approx(100.1)
    assert fill > 100.0


def test_fixed_bps_slippage_sell_is_worse_than_reference():
    model = FixedBpsSlippage(bps=10)
    fill = model.fill_price(reference_price=100.0, side="sell")
    assert fill == pytest.approx(99.9)
    assert fill < 100.0


def test_fixed_bps_slippage_rejects_invalid_side():
    model = FixedBpsSlippage(bps=10)
    with pytest.raises(ValueError):
        model.fill_price(reference_price=100.0, side="hold")
