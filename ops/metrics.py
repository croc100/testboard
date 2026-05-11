from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    opened_at: datetime
    closed_at: datetime
    reason: str

    @property
    def hold_hours(self) -> float:
        return (self.closed_at - self.opened_at).total_seconds() / 3600

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


class MetricsCollector:
    """거래 통계 수집 및 일일 리포트 생성"""

    def __init__(self) -> None:
        self._records: list[TradeRecord] = []
        self._daily: dict[date, list[TradeRecord]] = {}

    def record_trade(self, record: TradeRecord) -> None:
        self._records.append(record)
        day = record.closed_at.date()
        self._daily.setdefault(day, []).append(record)
        logger.info(
            "거래 기록: %s %s PNL=%.2f (%.1fh 보유)",
            record.symbol, record.side, record.pnl, record.hold_hours,
        )

    def daily_summary(self, target: Optional[date] = None) -> dict:
        target = target or datetime.utcnow().date()
        records = self._daily.get(target, [])
        if not records:
            return {"date": str(target), "trades": 0, "win_rate": 0.0, "pnl": 0.0}
        wins = sum(1 for r in records if r.is_win)
        pnl = sum(r.pnl for r in records)
        return {
            "date": str(target),
            "trades": len(records),
            "wins": wins,
            "losses": len(records) - wins,
            "win_rate": wins / len(records),
            "total_pnl": pnl,
            "avg_hold_hours": sum(r.hold_hours for r in records) / len(records),
        }

    def cumulative_pnl(self) -> float:
        return sum(r.pnl for r in self._records)

    def total_trades(self) -> int:
        return len(self._records)

    def overall_win_rate(self) -> float:
        if not self._records:
            return 0.0
        return sum(1 for r in self._records if r.is_win) / len(self._records)
