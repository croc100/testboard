from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from core.models import MyPosition, TradeSignal

logger = logging.getLogger(__name__)


class PositionTracker:
    """내 포지션 인메모리 상태 관리"""

    def __init__(self) -> None:
        self._positions: dict[str, MyPosition] = {}  # position_key → MyPosition

    def add(self, pos: MyPosition) -> None:
        key = pos.position_key()
        self._positions[key] = pos
        logger.info("포지션 추가: %s | entry=%.4f | qty=%.6f",
                    key, pos.entry_price, pos.quantity)

    def remove(self, symbol: str, side: str) -> Optional[MyPosition]:
        key = f"{symbol}_{side}"
        pos = self._positions.pop(key, None)
        if pos:
            logger.info("포지션 제거: %s", key)
        return pos

    def get(self, symbol: str, side: str) -> Optional[MyPosition]:
        return self._positions.get(f"{symbol}_{side}")

    def get_by_key(self, key: str) -> Optional[MyPosition]:
        return self._positions.get(key)

    def all(self) -> list[MyPosition]:
        return list(self._positions.values())

    def update_pnl(self, symbol: str, side: str, unrealized_pnl: float) -> None:
        pos = self.get(symbol, side)
        if pos:
            pos.unrealized_pnl = unrealized_pnl

    def update_sl_order(self, symbol: str, side: str, order_id: str) -> None:
        pos = self.get(symbol, side)
        if pos:
            pos.sl_order_id = order_id

    def update_high_water_mark(self, symbol: str, side: str, price: float) -> None:
        pos = self.get(symbol, side)
        if not pos:
            return
        if side == "LONG":
            pos.high_water_mark = max(pos.high_water_mark, price)
        else:
            if pos.high_water_mark == 0.0:
                pos.high_water_mark = price
            else:
                pos.high_water_mark = min(pos.high_water_mark, price)

    def has_position(self, symbol: str, side: str) -> bool:
        return f"{symbol}_{side}" in self._positions

    def count(self) -> int:
        return len(self._positions)
