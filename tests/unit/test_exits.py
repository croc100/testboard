"""strategy/exits.py 단위 테스트"""
from datetime import datetime, timedelta

import pytest

from core.config import ExitsConfig, PartialTpLevel
from core.models import MyPosition, TradeSignal
from strategy.exits import ExitManager


def _make_config(**kwargs) -> ExitsConfig:
    defaults = dict(
        hard_stop_loss_pct=0.02, trailing_activation_pct=0.03,
        trailing_distance_pct=0.015, time_stop_hours=4,
        partial_tp_levels=[PartialTpLevel(pct=0.03, close_ratio=0.5)],
    )
    defaults.update(kwargs)
    return ExitsConfig(**defaults)


def _make_position(side="LONG", entry=50000.0, opened_hours_ago=0) -> MyPosition:
    sig = TradeSignal(
        symbol="BTCUSDT", side=side, confidence=0.6,
        supporting_traders=["A"], avg_entry_price=entry,
        suggested_size_usdt=100.0, stop_loss_pct=0.02, take_profit_pct=0.03,
    )
    return MyPosition(
        symbol="BTCUSDT", side=side, entry_price=entry, quantity=0.01,
        leverage=5, unrealized_pnl=0.0,
        opened_at=datetime.utcnow() - timedelta(hours=opened_hours_ago),
        source_signal=sig, sl_order_id=None, tp_order_id=None,
        high_water_mark=entry,
    )


class TestExitManager:
    def setup_method(self):
        self.mgr = ExitManager(_make_config())

    def test_sl_price_long(self):
        sl = self.mgr.compute_sl_price(50000.0, "LONG")
        assert sl == pytest.approx(49000.0, rel=0.001)

    def test_sl_price_short(self):
        sl = self.mgr.compute_sl_price(50000.0, "SHORT")
        assert sl == pytest.approx(51000.0, rel=0.001)

    def test_tp_price_long(self):
        tp = self.mgr.compute_tp_price(50000.0, "LONG")
        assert tp == pytest.approx(51500.0, rel=0.001)

    def test_tp_price_short(self):
        tp = self.mgr.compute_tp_price(50000.0, "SHORT")
        assert tp == pytest.approx(48500.0, rel=0.001)

    def test_tp_price_no_levels(self):
        mgr = ExitManager(ExitsConfig(
            hard_stop_loss_pct=0.02, trailing_activation_pct=0.03,
            trailing_distance_pct=0.015, time_stop_hours=4,
            partial_tp_levels=[],
        ))
        assert mgr.compute_tp_price(50000.0, "LONG") is None

    def test_trailing_not_activated(self):
        pos = _make_position("LONG", entry=50000.0)
        # +2% — 활성화 기준 3% 미달
        assert not self.mgr.should_trail_stop(pos, 51000.0)

    def test_trailing_activated_long(self):
        pos = _make_position("LONG", entry=50000.0)
        assert self.mgr.should_trail_stop(pos, 51500.0)  # +3%

    def test_trailing_activated_short(self):
        pos = _make_position("SHORT", entry=50000.0)
        assert self.mgr.should_trail_stop(pos, 48500.0)  # +3%

    def test_trail_sl_long(self):
        pos = _make_position("LONG", entry=50000.0)
        pos.high_water_mark = 52000.0
        sl = self.mgr.compute_trail_sl(pos, 52000.0)
        assert sl == pytest.approx(52000.0 * (1 - 0.015), rel=0.001)

    def test_time_stop_not_reached(self):
        pos = _make_position(opened_hours_ago=3)
        assert not self.mgr.is_time_stop(pos)

    def test_time_stop_reached(self):
        pos = _make_position(opened_hours_ago=5)
        assert self.mgr.is_time_stop(pos)

    def test_update_hwm_long(self):
        pos = _make_position("LONG", entry=50000.0)
        pos.high_water_mark = 50000.0
        new_hwm = self.mgr.update_high_water_mark(pos, 52000.0)
        assert new_hwm == 52000.0

    def test_update_hwm_long_no_update_below(self):
        pos = _make_position("LONG", entry=50000.0)
        pos.high_water_mark = 52000.0
        new_hwm = self.mgr.update_high_water_mark(pos, 51000.0)
        assert new_hwm == 52000.0
