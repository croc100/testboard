from __future__ import annotations

import logging

from core.config import RiskConfig
from core.models import AccountState

logger = logging.getLogger(__name__)

_HARD_MAX_DAILY_LOSS_PCT = 0.05  # 절대 원칙 #3


class LimitsChecker:
    def __init__(self, config: RiskConfig) -> None:
        self._cfg = config

    def check_daily_loss(self, account: AccountState) -> tuple[bool, str]:
        loss = account.daily_loss_pct
        # 하드 제한 먼저
        if loss <= -_HARD_MAX_DAILY_LOSS_PCT:
            return False, f"하드 일일 손실 제한 도달: {loss:.2%}"
        if loss <= -self._cfg.max_daily_loss_pct:
            return False, f"일일 손실 한도 도달: {loss:.2%} (한도 {self._cfg.max_daily_loss_pct:.2%})"
        return True, ""

    def check_drawdown(self, account: AccountState) -> tuple[bool, str]:
        dd = account.total_drawdown_pct
        if dd <= -self._cfg.max_drawdown_pct:
            return False, f"최대 드로우다운 도달: {dd:.2%} (한도 {self._cfg.max_drawdown_pct:.2%})"
        return True, ""

    def check_concurrent_positions(self, account: AccountState) -> tuple[bool, str]:
        n = len(account.open_positions)
        if n >= self._cfg.max_concurrent_positions if hasattr(self._cfg, 'max_concurrent_positions') else 3:
            return False, f"동시 포지션 한도: {n}개"
        return True, ""

    def drawdown_size_reduction(self, account: AccountState) -> float:
        """드로우다운에 따른 사이즈 축소 비율 반환 (0이면 정상, 0.5이면 50% 축소)"""
        dd = abs(account.total_drawdown_pct)
        if dd >= 0.05:   # -5% 이상 드로우다운
            return 0.5
        return 0.0
