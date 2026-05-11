"""core/models.py 단위 테스트"""
from datetime import datetime

import pytest

from core.models import AccountState, MyPosition, TradeSignal, TraderPosition


def _make_signal(**kwargs) -> TradeSignal:
    defaults = dict(
        symbol="BTCUSDT", side="LONG", confidence=0.6,
        supporting_traders=["A", "B"], avg_entry_price=50000.0,
        suggested_size_usdt=100.0, stop_loss_pct=0.02,
        take_profit_pct=0.03, created_at=datetime.utcnow(),
    )
    defaults.update(kwargs)
    return TradeSignal(**defaults)


def _make_position(**kwargs) -> MyPosition:
    sig = _make_signal()
    defaults = dict(
        symbol="BTCUSDT", side="LONG", entry_price=50000.0,
        quantity=0.01, leverage=5, unrealized_pnl=0.0,
        opened_at=datetime.utcnow(), source_signal=sig,
        sl_order_id=None, tp_order_id=None,
    )
    defaults.update(kwargs)
    return MyPosition(**defaults)


class TestTraderPosition:
    def test_position_key_long(self):
        pos = TraderPosition(
            trader_uid="UID1", symbol="BTCUSDT", side="LONG",
            entry_price=50000.0, mark_price=51000.0, amount=0.1,
            leverage=5, pnl=100.0, roe=0.1, update_time=1000,
        )
        assert pos.position_key() == "BTCUSDT_LONG"

    def test_position_key_short(self):
        pos = TraderPosition(
            trader_uid="UID1", symbol="ETHUSDT", side="SHORT",
            entry_price=3000.0, mark_price=2900.0, amount=1.0,
            leverage=10, pnl=100.0, roe=0.05, update_time=1000,
        )
        assert pos.position_key() == "ETHUSDT_SHORT"

    def test_frozen(self):
        pos = TraderPosition(
            trader_uid="UID1", symbol="BTCUSDT", side="LONG",
            entry_price=50000.0, mark_price=51000.0, amount=0.1,
            leverage=5, pnl=100.0, roe=0.1, update_time=1000,
        )
        with pytest.raises(Exception):
            pos.symbol = "ETHUSDT"  # type: ignore[misc]


class TestTradeSignal:
    def test_position_key(self):
        sig = _make_signal(symbol="SOLUSDT", side="SHORT")
        assert sig.position_key() == "SOLUSDT_SHORT"

    def test_defaults(self):
        sig = _make_signal()
        assert sig.confidence == 0.6
        assert sig.stop_loss_pct == 0.02


class TestMyPosition:
    def test_position_key(self):
        pos = _make_position(symbol="ETHUSDT", side="SHORT")
        assert pos.position_key() == "ETHUSDT_SHORT"

    def test_notional_value(self):
        pos = _make_position(entry_price=50000.0, quantity=0.002)
        assert pos.notional_value() == pytest.approx(100.0)

    def test_high_water_mark_default(self):
        pos = _make_position()
        assert pos.high_water_mark == 0.0


class TestAccountState:
    def test_daily_loss_pct_zero_balance(self):
        acc = AccountState(balance_usdt=0.0, daily_realized_pnl=-10.0)
        assert acc.daily_loss_pct == 0.0

    def test_daily_loss_pct(self):
        acc = AccountState(balance_usdt=1000.0, daily_realized_pnl=-30.0)
        assert acc.daily_loss_pct == pytest.approx(-0.03)

    def test_total_drawdown_pct(self):
        acc = AccountState(balance_usdt=900.0, peak_balance=1000.0)
        assert acc.total_drawdown_pct == pytest.approx(-0.10)

    def test_total_drawdown_zero_peak(self):
        acc = AccountState(balance_usdt=1000.0, peak_balance=0.0)
        assert acc.total_drawdown_pct == 0.0
