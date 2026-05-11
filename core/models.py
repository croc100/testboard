from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass(frozen=True)
class TraderPosition:
    """바이낸스 랭커 한 명의 포지션"""
    trader_uid: str
    symbol: str
    side: Literal["LONG", "SHORT"]
    entry_price: float
    mark_price: float
    amount: float           # 양수
    leverage: int
    pnl: float
    roe: float              # 자본 대비 수익률
    update_time: int        # ms

    def position_key(self) -> str:
        return f"{self.symbol}_{self.side}"


@dataclass
class TradeSignal:
    """합의된 진입 신호"""
    symbol: str
    side: Literal["LONG", "SHORT"]
    confidence: float           # 0~1, 합의 강도
    supporting_traders: list[str]
    avg_entry_price: float
    suggested_size_usdt: float
    stop_loss_pct: float
    take_profit_pct: float
    created_at: datetime = field(default_factory=datetime.utcnow)

    def position_key(self) -> str:
        return f"{self.symbol}_{self.side}"


@dataclass
class MyPosition:
    """내가 실제 보유한 포지션"""
    symbol: str
    side: str
    entry_price: float
    quantity: float
    leverage: int
    unrealized_pnl: float
    opened_at: datetime
    source_signal: TradeSignal
    sl_order_id: Optional[str]
    tp_order_id: Optional[str]
    high_water_mark: float = 0.0    # 트레일링 스탑용

    def position_key(self) -> str:
        return f"{self.symbol}_{self.side}"

    def notional_value(self) -> float:
        return self.entry_price * self.quantity

    def pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        diff = self.unrealized_pnl / (self.entry_price * self.quantity / self.leverage)
        return diff


@dataclass
class AccountState:
    balance_usdt: float
    open_positions: list[MyPosition] = field(default_factory=list)
    daily_realized_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    peak_balance: float = 0.0

    @property
    def daily_loss_pct(self) -> float:
        if self.balance_usdt == 0:
            return 0.0
        return self.daily_realized_pnl / self.balance_usdt

    @property
    def total_drawdown_pct(self) -> float:
        if self.peak_balance == 0:
            return 0.0
        return (self.balance_usdt - self.peak_balance) / self.peak_balance


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float]
    status: str
    created_at: datetime = field(default_factory=datetime.utcnow)
