from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from core.config import ExitsConfig
from core.models import MyPosition

logger = logging.getLogger(__name__)


class ExitManager:
    def __init__(self, config: ExitsConfig) -> None:
        self._cfg = config

    def compute_sl_price(self, entry_price: float, side: str) -> float:
        """하드 손절가 계산"""
        if side == "LONG":
            return round(entry_price * (1 - self._cfg.hard_stop_loss_pct), 4)
        return round(entry_price * (1 + self._cfg.hard_stop_loss_pct), 4)

    def compute_tp_price(self, entry_price: float, side: str) -> Optional[float]:
        """1차 익절가 (레벨이 없으면 None)"""
        if not self._cfg.partial_tp_levels:
            return None
        first_tp = self._cfg.partial_tp_levels[0].pct
        if side == "LONG":
            return round(entry_price * (1 + first_tp), 4)
        return round(entry_price * (1 - first_tp), 4)

    def should_trail_stop(self, position: MyPosition, current_price: float) -> bool:
        """트레일링 스탑 조건 충족 여부"""
        activation = self._cfg.trailing_activation_pct
        if position.side == "LONG":
            profit_pct = (current_price - position.entry_price) / position.entry_price
        else:
            profit_pct = (position.entry_price - current_price) / position.entry_price
        return profit_pct >= activation

    def compute_trail_sl(self, position: MyPosition, current_price: float) -> float:
        """트레일링 SL 가격 계산 (최고점 대비 distance)"""
        hwm = position.high_water_mark
        if position.side == "LONG":
            return round(hwm * (1 - self._cfg.trailing_distance_pct), 4)
        return round(hwm * (1 + self._cfg.trailing_distance_pct), 4)

    def update_high_water_mark(self, position: MyPosition, current_price: float) -> float:
        if position.side == "LONG":
            return max(position.high_water_mark, current_price)
        return min(position.high_water_mark or current_price, current_price)

    def is_time_stop(self, position: MyPosition) -> bool:
        """시간 손절 조건"""
        elapsed = datetime.utcnow() - position.opened_at
        return elapsed >= timedelta(hours=self._cfg.time_stop_hours)

    def get_partial_close_ratio(self, position: MyPosition, current_price: float) -> float:
        """부분 익절 비율 반환 (없으면 0)"""
        for level in self._cfg.partial_tp_levels:
            if position.side == "LONG":
                pct = (current_price - position.entry_price) / position.entry_price
            else:
                pct = (position.entry_price - current_price) / position.entry_price
            if pct >= level.pct:
                return level.close_ratio
        return 0.0
