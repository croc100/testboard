from __future__ import annotations

import logging

from core.models import AccountState, TradeSignal

logger = logging.getLogger(__name__)

# BTC/ETH/SOL 같은 방향 동시 3개 이상 금지
_CORRELATED_GROUPS: list[set[str]] = [
    {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"},
]
_MAX_SAME_DIRECTION_IN_GROUP = 2


class CorrelationChecker:
    def would_exceed_limit(self, signal: TradeSignal, account: AccountState) -> bool:
        """신규 진입 시 상관관계 한도 초과 여부"""
        for group in _CORRELATED_GROUPS:
            if signal.symbol not in group:
                continue
            same_direction = sum(
                1
                for pos in account.open_positions
                if pos.symbol in group and pos.side == signal.side
            )
            if same_direction >= _MAX_SAME_DIRECTION_IN_GROUP:
                logger.info(
                    "상관관계 제한: %s %s — 그룹 내 %s 방향 포지션 이미 %d개",
                    signal.symbol, signal.side, signal.side, same_direction,
                )
                return True
        return False
