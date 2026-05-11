from __future__ import annotations

import logging
from typing import Optional

from core.config import PositionConfig
from core.models import AccountState, TradeSignal
from data_sources.market_data import MarketData

logger = logging.getLogger(__name__)


class PositionSizer:
    def __init__(self, config: PositionConfig, market_data: MarketData) -> None:
        self._cfg = config
        self._md = market_data
        self._consecutive_losses: int = 0
        # 런타임 오버라이드: 텔레그램 /capital 명령으로 설정 가능.
        # 설정되면 실제 잔고 무시하고 이 금액(USDC)을 마진 기준으로 사용.
        # None이면 잔고 × base_capital_pct 자동.
        self._fixed_capital: Optional[float] = None

    def notify_loss(self) -> None:
        self._consecutive_losses += 1

    def notify_win(self) -> None:
        self._consecutive_losses = 0

    def set_fixed_capital(self, amount: Optional[float]) -> None:
        """봇 실행 중 자본 금액 변경. None이면 자동(잔고 비율)로 복원."""
        self._fixed_capital = amount
        if amount is None:
            logger.info("자본 모드 → 자동(잔고 × base_capital_pct)")
        else:
            logger.info("자본 모드 → 고정 $%.2f USDC", amount)

    def get_capital_mode(self) -> str:
        if self._fixed_capital is None:
            return f"AUTO (잔고 × {self._cfg.base_capital_pct*100:.0f}%)"
        return f"FIXED ${self._fixed_capital:.2f}"

    def compute_quantity(
        self,
        signal: TradeSignal,
        account: AccountState,
        drawdown_reduction_pct: float = 0.0,
    ) -> float:
        """
        주문 수량(코인 단위) 계산.
        drawdown_reduction_pct: 0이면 정상, 0.5이면 절반 사이즈
        """
        if self._fixed_capital is not None:
            # 고정 금액 모드: 잔고 무시
            base_usdt = self._fixed_capital
        else:
            base_usdt = account.balance_usdt * self._cfg.base_capital_pct

        # 드로우다운 축소
        if drawdown_reduction_pct > 0:
            base_usdt *= (1.0 - drawdown_reduction_pct)
            logger.info("드로우다운 사이즈 축소: %.0f%%", drawdown_reduction_pct * 100)

        # 연속 손실 축소
        if self._consecutive_losses >= 3:
            base_usdt *= 0.5
            logger.info("연속 손실 %d회 — 사이즈 50%% 축소", self._consecutive_losses)

        # 변동성 조정
        try:
            target_atr = self._md.compute_atr(signal.symbol, period=14)
            avg_atr = self._md.compute_atr(signal.symbol, period=50)
            if avg_atr > 0 and target_atr > 0:
                vol_adj = avg_atr / target_atr
                # 0.5~1.5 범위 클램프
                vol_adj = max(0.5, min(1.5, vol_adj))
                base_usdt *= vol_adj
                logger.debug("변동성 조정 계수: %.3f", vol_adj)
        except Exception as e:
            logger.warning("변동성 조정 실패: %s", e)

        # 최대 포지션 자본 제한 (FIXED 모드에선 사용자가 명시한 금액 그대로 사용)
        if self._fixed_capital is not None:
            notional_usdt = base_usdt
        else:
            max_usdt = account.balance_usdt * self._cfg.max_position_capital_pct
            notional_usdt = min(base_usdt, max_usdt)

        # 레버리지 적용 — notional = quantity * price
        price = signal.avg_entry_price
        if price <= 0:
            logger.error("진입가 0 — 수량 계산 불가")
            return 0.0

        # 증거금 기준 notional 역산
        margin_usdt = notional_usdt
        notional_with_lev = margin_usdt * self._cfg.leverage
        quantity = notional_with_lev / price

        logger.info(
            "사이즈 계산: 마진 $%.2f × %dx레버 / $%.4f = %.6f %s",
            margin_usdt, self._cfg.leverage, price, quantity, signal.symbol,
        )
        return round(quantity, 6)
