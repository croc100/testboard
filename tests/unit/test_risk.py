"""risk/* 단위 테스트 — 모든 회로차단 조건"""
import time
from datetime import datetime

import pytest

from core.config import RiskConfig
from core.models import AccountState, MyPosition, TradeSignal
from risk.circuit_breaker import CircuitBreaker
from risk.correlation import CorrelationChecker
from risk.limits import LimitsChecker


def _make_account(**kwargs) -> AccountState:
    defaults = dict(balance_usdt=1000.0, open_positions=[], peak_balance=1000.0)
    defaults.update(kwargs)
    return AccountState(**defaults)


def _make_signal(symbol="BTCUSDT", side="LONG") -> TradeSignal:
    return TradeSignal(
        symbol=symbol, side=side, confidence=0.6,
        supporting_traders=["A"], avg_entry_price=50000.0,
        suggested_size_usdt=100.0, stop_loss_pct=0.02, take_profit_pct=0.03,
    )


def _make_position(symbol="BTCUSDT", side="LONG") -> MyPosition:
    return MyPosition(
        symbol=symbol, side=side, entry_price=50000.0, quantity=0.01,
        leverage=5, unrealized_pnl=0.0, opened_at=datetime.utcnow(),
        source_signal=_make_signal(symbol, side), sl_order_id=None, tp_order_id=None,
    )


# ── CircuitBreaker ────────────────────────────────────────────────────────────

class TestCircuitBreaker:
    def test_not_tripped_initially(self):
        cb = CircuitBreaker()
        assert not cb.is_tripped()

    def test_trips_on_consecutive_losses(self):
        cb = CircuitBreaker(max_consecutive_losses=3)
        cb.on_loss()
        cb.on_loss()
        assert not cb.is_tripped()
        cb.on_loss()
        assert cb.is_tripped()

    def test_win_resets_consecutive(self):
        cb = CircuitBreaker(max_consecutive_losses=3)
        cb.on_loss()
        cb.on_loss()
        cb.on_win()
        cb.on_loss()
        assert not cb.is_tripped()

    def test_api_error_rate(self):
        cb = CircuitBreaker(api_error_window_sec=600, api_error_threshold=0.5)
        for _ in range(5):
            cb.on_api_call(success=True)
        for _ in range(6):
            cb.on_api_call(success=False)
        assert cb.is_tripped()

    def test_daily_loss_trips(self):
        cb = CircuitBreaker()
        cb.on_daily_loss_limit()
        assert cb.is_tripped()

    def test_drawdown_trips(self):
        cb = CircuitBreaker()
        cb.on_drawdown_limit()
        assert cb.is_tripped()

    def test_manual_reset(self):
        cb = CircuitBreaker()
        cb.on_daily_loss_limit()
        assert cb.is_tripped()
        cb.manual_reset()
        assert not cb.is_tripped()

    def test_no_auto_reset(self):
        """자동 해제 없음 — 절대 원칙 #7"""
        cb = CircuitBreaker()
        cb.on_daily_loss_limit()
        time.sleep(0.01)
        assert cb.is_tripped()  # 시간이 지나도 해제 안 됨


# ── LimitsChecker ─────────────────────────────────────────────────────────────

class TestLimitsChecker:
    def setup_method(self):
        self.checker = LimitsChecker(RiskConfig(
            max_daily_loss_pct=0.03,
            max_drawdown_pct=0.10,
        ))

    def test_daily_loss_ok(self):
        acc = _make_account(balance_usdt=1000.0, daily_realized_pnl=-20.0)
        ok, _ = self.checker.check_daily_loss(acc)
        assert ok

    def test_daily_loss_exceeded(self):
        acc = _make_account(balance_usdt=1000.0, daily_realized_pnl=-31.0)
        ok, reason = self.checker.check_daily_loss(acc)
        assert not ok
        assert "일일" in reason

    def test_hard_daily_loss_limit(self):
        """하드 -5% 제한"""
        acc = _make_account(balance_usdt=1000.0, daily_realized_pnl=-51.0)
        ok, reason = self.checker.check_daily_loss(acc)
        assert not ok
        assert "하드" in reason

    def test_drawdown_ok(self):
        acc = _make_account(balance_usdt=950.0, peak_balance=1000.0)
        ok, _ = self.checker.check_drawdown(acc)
        assert ok

    def test_drawdown_exceeded(self):
        acc = _make_account(balance_usdt=890.0, peak_balance=1000.0)
        ok, reason = self.checker.check_drawdown(acc)
        assert not ok
        assert "드로우다운" in reason

    def test_drawdown_size_reduction_zero(self):
        acc = _make_account(balance_usdt=980.0, peak_balance=1000.0)
        assert self.checker.drawdown_size_reduction(acc) == 0.0

    def test_drawdown_size_reduction_half(self):
        acc = _make_account(balance_usdt=940.0, peak_balance=1000.0)
        assert self.checker.drawdown_size_reduction(acc) == pytest.approx(0.5)


# ── CorrelationChecker ────────────────────────────────────────────────────────

class TestCorrelationChecker:
    def setup_method(self):
        self.checker = CorrelationChecker()

    def test_no_existing_positions(self):
        acc = _make_account()
        sig = _make_signal("BTCUSDT", "LONG")
        assert not self.checker.would_exceed_limit(sig, acc)

    def test_one_same_direction(self):
        acc = _make_account(open_positions=[_make_position("ETHUSDT", "LONG")])
        sig = _make_signal("BTCUSDT", "LONG")
        assert not self.checker.would_exceed_limit(sig, acc)

    def test_two_same_direction_blocks_third(self):
        acc = _make_account(open_positions=[
            _make_position("BTCUSDT", "LONG"),
            _make_position("ETHUSDT", "LONG"),
        ])
        sig = _make_signal("SOLUSDT", "LONG")
        assert self.checker.would_exceed_limit(sig, acc)

    def test_different_direction_allowed(self):
        acc = _make_account(open_positions=[
            _make_position("BTCUSDT", "LONG"),
            _make_position("ETHUSDT", "LONG"),
        ])
        sig = _make_signal("SOLUSDT", "SHORT")
        assert not self.checker.would_exceed_limit(sig, acc)

    def test_outside_group_symbol(self):
        acc = _make_account(open_positions=[
            _make_position("BTCUSDT", "LONG"),
            _make_position("ETHUSDT", "LONG"),
        ])
        sig = _make_signal("XRPUSDT", "LONG")  # 화이트리스트 외부
        assert not self.checker.would_exceed_limit(sig, acc)
