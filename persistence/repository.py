from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, select
from sqlalchemy.orm import Session

from persistence.database import Base, get_session

logger = logging.getLogger(__name__)


# ── ORM 모델 ──────────────────────────────────────────────────────────────────

class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False)
    leverage = Column(Integer, default=1)
    pnl = Column(Float, default=0.0)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    close_reason = Column(String(100), nullable=True)
    signal_confidence = Column(Float, default=0.0)
    supporting_traders = Column(Text, default="")   # comma-separated UIDs


class SignalLog(Base):
    __tablename__ = "signal_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    confidence = Column(Float, default=0.0)
    supporting_traders = Column(Text, default="")
    avg_entry_price = Column(Float, default=0.0)
    acted = Column(Integer, default=0)   # 1=진입, 0=필터 차단
    reject_reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CircuitBreakerLog(Base):
    __tablename__ = "circuit_breaker_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reason = Column(String(200), nullable=False)
    tripped_at = Column(DateTime, default=datetime.utcnow)
    reset_at = Column(DateTime, nullable=True)


# ── CRUD ──────────────────────────────────────────────────────────────────────

class TradeRepository:
    def open_trade(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        leverage: int,
        confidence: float,
        traders: list[str],
    ) -> int:
        with get_session() as session:
            row = TradeLog(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                leverage=leverage,
                signal_confidence=confidence,
                supporting_traders=",".join(traders),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
        reason: str,
    ) -> None:
        with get_session() as session:
            row = session.get(TradeLog, trade_id)
            if row:
                row.exit_price = exit_price
                row.pnl = pnl
                row.closed_at = datetime.utcnow()
                row.close_reason = reason
                session.commit()

    def log_signal(
        self,
        symbol: str,
        side: str,
        confidence: float,
        traders: list[str],
        avg_price: float,
        acted: bool,
        reject_reason: str = "",
    ) -> None:
        with get_session() as session:
            row = SignalLog(
                symbol=symbol,
                side=side,
                confidence=confidence,
                supporting_traders=",".join(traders),
                avg_entry_price=avg_price,
                acted=1 if acted else 0,
                reject_reason=reject_reason,
            )
            session.add(row)
            session.commit()

    def log_circuit_breaker(self, reason: str) -> int:
        with get_session() as session:
            row = CircuitBreakerLog(reason=reason)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def get_daily_trades(self, date_str: str) -> list[TradeLog]:
        with get_session() as session:
            result = session.execute(
                select(TradeLog).where(
                    TradeLog.closed_at >= f"{date_str} 00:00:00",
                    TradeLog.closed_at < f"{date_str} 23:59:59",
                )
            )
            return list(result.scalars().all())
