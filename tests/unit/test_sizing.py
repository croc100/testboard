"""strategy/sizing.py 단위 테스트"""
from unittest.mock import MagicMock

import pytest

from core.config import PositionConfig
from core.models import AccountState, TradeSignal
from strategy.sizing import PositionSizer


def _make_config(**kwargs) -> PositionConfig:
    defaults = dict(
        mode="RATIO", base_capital_pct=0.05,
        max_position_capital_pct=0.10, max_concurrent=3,
        leverage=5, margin_type="ISOLATED",
    )
    defaults.update(kwargs)
    return PositionConfig(**defaults)


def _make_signal(price=50000.0) -> TradeSignal:
    return TradeSignal(
        symbol="BTCUSDT", side="LONG", confidence=0.6,
        supporting_traders=["A", "B"], avg_entry_price=price,
        suggested_size_usdt=100.0, stop_loss_pct=0.02, take_profit_pct=0.03,
    )


def _make_account(balance=1000.0) -> AccountState:
    return AccountState(balance_usdt=balance, peak_balance=balance)


def _make_sizer(base_pct=0.05, max_pct=0.10, leverage=5) -> PositionSizer:
    cfg = _make_config(base_capital_pct=base_pct,
                       max_position_capital_pct=max_pct, leverage=leverage)
    market = MagicMock()
    market.compute_atr.return_value = 500.0  # 단순 고정값
    return PositionSizer(cfg, market)


class TestPositionSizer:
    def test_basic_quantity(self):
        sizer = _make_sizer()
        sig = _make_signal(price=50000.0)
        acc = _make_account(1000.0)
        qty = sizer.compute_quantity(sig, acc)
        # margin = 1000 * 0.05 = 50
        # notional = 50 * 5 = 250
        # qty = 250 / 50000 = 0.005
        assert qty == pytest.approx(0.005, rel=0.1)

    def test_zero_price_returns_zero(self):
        sizer = _make_sizer()
        sig = _make_signal(price=0.0)
        acc = _make_account(1000.0)
        qty = sizer.compute_quantity(sig, acc)
        assert qty == 0.0

    def test_drawdown_reduction(self):
        sizer = _make_sizer()
        sig = _make_signal(price=50000.0)
        acc = _make_account(1000.0)
        qty_normal = sizer.compute_quantity(sig, acc, drawdown_reduction_pct=0.0)
        qty_reduced = sizer.compute_quantity(sig, acc, drawdown_reduction_pct=0.5)
        assert qty_reduced == pytest.approx(qty_normal * 0.5, rel=0.1)

    def test_consecutive_loss_reduction(self):
        sizer = _make_sizer()
        sig = _make_signal(price=50000.0)
        acc = _make_account(1000.0)
        qty_normal = sizer.compute_quantity(sig, acc)
        sizer.notify_loss()
        sizer.notify_loss()
        sizer.notify_loss()
        qty_reduced = sizer.compute_quantity(sig, acc)
        assert qty_reduced == pytest.approx(qty_normal * 0.5, rel=0.2)

    def test_win_resets_consecutive(self):
        sizer = _make_sizer()
        sig = _make_signal(price=50000.0)
        acc = _make_account(1000.0)
        sizer.notify_loss()
        sizer.notify_loss()
        sizer.notify_loss()
        sizer.notify_win()
        qty_after = sizer.compute_quantity(sig, acc)
        sizer2 = _make_sizer()
        qty_fresh = sizer2.compute_quantity(sig, acc)
        assert qty_after == pytest.approx(qty_fresh, rel=0.1)

    def test_max_position_cap(self):
        sizer = _make_sizer(base_pct=0.20, max_pct=0.10)  # base > max → capped
        sig = _make_signal(price=50000.0)
        acc = _make_account(1000.0)
        qty = sizer.compute_quantity(sig, acc)
        # max = 1000 * 0.10 = 100, notional = 100*5 = 500, qty = 500/50000 = 0.01
        assert qty == pytest.approx(0.01, rel=0.1)
