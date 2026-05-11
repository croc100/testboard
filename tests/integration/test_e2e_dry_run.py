"""
E2E 통합 테스트 — Mock 서버로 DRY_RUN 사이클 검증
가짜 랭커 데이터 → 신호 생성 → DRY_RUN 주문 → 포지션 추적
"""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.config import (AppConfig, ConsensusConfig, ExitsConfig, FiltersConfig,
                          ModeConfig, OpsConfig, PositionConfig, RiskConfig,
                          ExchangeConfig)
from core.models import TraderPosition
from execution.order_manager import OrderManager
from execution.position_tracker import PositionTracker
from risk.circuit_breaker import CircuitBreaker
from strategy.consensus import ConsensusEngine
from strategy.exits import ExitManager
from strategy.sizing import PositionSizer


def _make_full_config() -> AppConfig:
    cfg = MagicMock(spec=AppConfig)
    cfg.exchange = ExchangeConfig()
    # V3 지갑 인증 (테스트용 더미 키)
    cfg.user_address = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
    cfg.signer_address = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    cfg.signer_private_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    cfg.mode = ModeConfig(dry_run=True)
    cfg.position = PositionConfig(leverage=5, base_capital_pct=0.05,
                                   max_concurrent=3, max_position_capital_pct=0.10)
    cfg.consensus = ConsensusConfig(min_traders=2, min_confidence=0.4)
    cfg.exits = ExitsConfig(hard_stop_loss_pct=0.02)
    cfg.risk = RiskConfig()
    cfg.filters = FiltersConfig()
    cfg.ops = OpsConfig()
    return cfg


def _make_trader_positions(ts_offset_ms=0):
    ts = int(time.time() * 1000) + ts_offset_ms
    return [
        TraderPosition("UID_A", "BTCUSDT", "LONG", 50000.0, 50500.0, 0.1, 5, 50.0, 0.05, ts),
        TraderPosition("UID_B", "BTCUSDT", "LONG", 50100.0, 50500.0, 0.1, 5, 40.0, 0.04, ts + 1000),
    ]


class TestE2EDryRun:
    def test_signal_generated_from_consensus(self):
        cfg_mock = MagicMock()
        cfg_mock.trader_count = 2
        pool = MagicMock()
        pool.trader_count = 2

        consensus = ConsensusEngine(
            ConsensusConfig(min_traders=2, max_entry_lag_minutes=30, min_confidence=0.4),
            pool,
        )
        ts = int(time.time() * 1000)
        all_positions = {
            "UID_A": [TraderPosition("UID_A", "BTCUSDT", "LONG",
                                     50000.0, 50500.0, 0.1, 5, 50.0, 0.05, ts)],
            "UID_B": [TraderPosition("UID_B", "BTCUSDT", "LONG",
                                     50100.0, 50500.0, 0.1, 5, 40.0, 0.04, ts + 500)],
        }
        signals = consensus.evaluate(all_positions, 1000.0, 0.02, 0.03)
        assert len(signals) == 1
        assert signals[0].symbol == "BTCUSDT"
        assert signals[0].side == "LONG"

    def test_position_tracked_after_entry(self):
        from core.config import AppConfig
        from exchange.hl_client import HlClient as AsterClient

        cfg = _make_full_config()
        client = AsterClient(cfg)  # DRY_RUN 모드
        tracker = PositionTracker()
        market = MagicMock()
        market.compute_atr.return_value = 500.0
        sizer = PositionSizer(cfg.position, market)
        exit_mgr = ExitManager(cfg.exits)
        order_mgr = OrderManager(client, cfg, tracker, sizer, exit_mgr)

        from core.models import AccountState, TradeSignal
        signal = TradeSignal(
            symbol="BTCUSDT", side="LONG", confidence=0.8,
            supporting_traders=["UID_A", "UID_B"],
            avg_entry_price=50000.0, suggested_size_usdt=50.0,
            stop_loss_pct=0.02, take_profit_pct=0.03,
        )
        account = AccountState(balance_usdt=1000.0, peak_balance=1000.0)
        pos = order_mgr.enter_position(signal, account)

        assert pos is not None
        assert tracker.has_position("BTCUSDT", "LONG")
        assert tracker.count() == 1

    def test_circuit_breaker_blocks_after_3_losses(self):
        cb = CircuitBreaker(max_consecutive_losses=3)
        for _ in range(3):
            cb.on_loss()
        assert cb.is_tripped()
        # 수동 해제 후 재사용 가능
        cb.manual_reset()
        assert not cb.is_tripped()
