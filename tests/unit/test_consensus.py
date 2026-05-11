"""strategy/consensus.py 단위 테스트"""
import time
from unittest.mock import MagicMock

import pytest

from core.config import ConsensusConfig
from core.models import TraderPosition
from strategy.consensus import ConsensusEngine


def _make_position(uid: str, symbol: str = "BTCUSDT", side: str = "LONG",
                   update_time: int = None) -> TraderPosition:
    return TraderPosition(
        trader_uid=uid, symbol=symbol, side=side,
        entry_price=50000.0, mark_price=50500.0, amount=0.1,
        leverage=5, pnl=50.0, roe=0.05,
        update_time=update_time or int(time.time() * 1000),
    )


def _make_engine(min_traders: int = 2, total: int = 3) -> ConsensusEngine:
    cfg = ConsensusConfig(min_traders=min_traders, max_entry_lag_minutes=30, min_confidence=0.4)
    pool = MagicMock()
    pool.trader_count = total
    return ConsensusEngine(cfg, pool)


class TestConsensusEngine:
    def test_no_consensus_single_trader(self):
        engine = _make_engine(min_traders=2, total=3)
        all_pos = {"A": [_make_position("A")]}
        signals = engine.evaluate(all_pos, 1000.0, 0.02, 0.03)
        assert signals == []

    def test_consensus_two_traders(self):
        engine = _make_engine(min_traders=2, total=2)
        ts = int(time.time() * 1000)
        all_pos = {
            "A": [_make_position("A", update_time=ts)],
            "B": [_make_position("B", update_time=ts + 5000)],
        }
        signals = engine.evaluate(all_pos, 1000.0, 0.02, 0.03)
        assert len(signals) == 1
        assert signals[0].symbol == "BTCUSDT"
        assert signals[0].side == "LONG"
        assert signals[0].confidence == pytest.approx(1.0)

    def test_consensus_three_of_five(self):
        engine = _make_engine(min_traders=2, total=5)
        ts = int(time.time() * 1000)
        all_pos = {
            "A": [_make_position("A", update_time=ts)],
            "B": [_make_position("B", update_time=ts + 1000)],
            "C": [_make_position("C", update_time=ts + 2000)],
        }
        signals = engine.evaluate(all_pos, 1000.0, 0.02, 0.03)
        assert len(signals) == 1
        assert signals[0].confidence == pytest.approx(0.6)

    def test_lag_exceeded_no_signal(self):
        engine = _make_engine(min_traders=2, total=2)
        ts = int(time.time() * 1000)
        lag_ms = 31 * 60 * 1000  # 31분
        all_pos = {
            "A": [_make_position("A", update_time=ts)],
            "B": [_make_position("B", update_time=ts + lag_ms)],
        }
        signals = engine.evaluate(all_pos, 1000.0, 0.02, 0.03)
        assert signals == []

    def test_different_symbols_no_consensus(self):
        engine = _make_engine(min_traders=2, total=2)
        ts = int(time.time() * 1000)
        all_pos = {
            "A": [_make_position("A", symbol="BTCUSDT", update_time=ts)],
            "B": [_make_position("B", symbol="ETHUSDT", update_time=ts)],
        }
        signals = engine.evaluate(all_pos, 1000.0, 0.02, 0.03)
        assert signals == []

    def test_confidence_below_min(self):
        engine = _make_engine(min_traders=2, total=10)  # 2/10 = 0.2 < 0.4
        ts = int(time.time() * 1000)
        all_pos = {
            "A": [_make_position("A", update_time=ts)],
            "B": [_make_position("B", update_time=ts + 1000)],
        }
        signals = engine.evaluate(all_pos, 1000.0, 0.02, 0.03)
        assert signals == []
