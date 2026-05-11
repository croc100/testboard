from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from core.config import ConsensusConfig
from core.models import TradeSignal, TraderPosition
from data_sources.trader_pool import TraderPool

logger = logging.getLogger(__name__)


class ConsensusEngine:
    """다중 트레이더 합의 로직"""

    def __init__(self, config: ConsensusConfig, trader_pool: TraderPool) -> None:
        self._cfg = config
        self._pool = trader_pool

    def evaluate(
        self,
        all_positions: dict[str, list[TraderPosition]],
        base_capital_usdt: float,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> list[TradeSignal]:
        """모든 트레이더 포지션에서 합의된 신호 추출"""
        grouped: dict[str, list[TraderPosition]] = {}
        for uid, positions in all_positions.items():
            for pos in positions:
                key = pos.position_key()
                grouped.setdefault(key, []).append(pos)

        signals: list[TradeSignal] = []
        total_traders = self._pool.trader_count

        for key, positions in grouped.items():
            if len(positions) < self._cfg.min_traders:
                continue

            if not self._within_lag(positions):
                logger.debug("신호 %s: 진입 시각 차이 초과 (%d분)", key, self._cfg.max_entry_lag_minutes)
                continue

            confidence = len(positions) / total_traders
            if confidence < self._cfg.min_confidence:
                logger.debug("신호 %s: 신뢰도 %.2f < %.2f", key, confidence, self._cfg.min_confidence)
                continue

            avg_entry = sum(p.entry_price for p in positions) / len(positions)
            supporting = [p.trader_uid for p in positions]

            signals.append(TradeSignal(
                symbol=positions[0].symbol,
                side=positions[0].side,
                confidence=confidence,
                supporting_traders=supporting,
                avg_entry_price=avg_entry,
                suggested_size_usdt=base_capital_usdt,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                created_at=datetime.utcnow(),
            ))
            logger.info("합의 신호: %s | 지지 트레이더 %d명 | 신뢰도 %.2f",
                        key, len(positions), confidence)

        return signals

    def _within_lag(self, positions: list[TraderPosition]) -> bool:
        if len(positions) < 2:
            return True
        times = [p.update_time for p in positions]
        lag_ms = (max(times) - min(times))
        lag_min = lag_ms / 60_000
        return lag_min <= self._cfg.max_entry_lag_minutes
