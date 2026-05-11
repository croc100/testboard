from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from core.config import AppConfig
from core.exceptions import StopLossRegistrationError
from core.models import MyPosition, TradeSignal
from exchange.hl_client import HlClient
from execution.position_tracker import PositionTracker
from strategy.exits import ExitManager
from strategy.sizing import PositionSizer

logger = logging.getLogger(__name__)


class OrderManager:
    """주문 라이프사이클 전담 — 진입·SL 등록·청산"""

    def __init__(
        self,
        client: HlClient,
        config: AppConfig,
        tracker: PositionTracker,
        sizer: PositionSizer,
        exit_manager: ExitManager,
    ) -> None:
        self._client = client
        self._cfg = config
        self._tracker = tracker
        self._sizer = sizer
        self._exit_mgr = exit_manager

    # ── 진입 ────────────────────────────────────────────────────────────────

    def enter_position(self, signal: TradeSignal, account_state) -> Optional[MyPosition]:
        """
        1) 레버리지·마진 타입 설정
        2) 시장가 진입
        3) SL 주문 즉시 등록 (실패 시 → 포지션 강제 청산)
        4) TP 주문 등록 (실패해도 진행)
        """
        symbol = signal.symbol
        side = signal.side
        order_side = "BUY" if side == "LONG" else "SELL"

        # 레버리지 설정
        try:
            self._client.set_leverage(symbol, self._cfg.position.leverage)
            self._client.set_margin_type(symbol, self._cfg.position.margin_type)
        except Exception as e:
            logger.warning("레버리지/마진 설정 실패 (%s): %s", symbol, e)

        # 수량 계산
        quantity = self._sizer.compute_quantity(signal, account_state)
        if quantity <= 0:
            logger.error("수량 계산 결과 0 — 진입 취소")
            return None

        # 시장가 진입
        try:
            result = self._client.market_order(symbol, order_side, quantity)
            order_id = result.get("orderId", "?")
            logger.info("진입 체결: %s %s qty=%.6f orderId=%s", side, symbol, quantity, order_id)
        except Exception as e:
            logger.error("진입 주문 실패 (%s %s): %s", side, symbol, e)
            return None

        # SL 가격 계산
        entry_price = signal.avg_entry_price
        sl_price = self._exit_mgr.compute_sl_price(entry_price, side)
        sl_side = "SELL" if side == "LONG" else "BUY"

        # SL 주문 등록 — 절대 원칙 #2
        sl_order_id: Optional[str] = None
        try:
            sl_result = self._client.stop_market_order(
                symbol, sl_side, sl_price, quantity, close_position=True
            )
            sl_order_id = sl_result.get("orderId")
            logger.info("SL 등록: %s stopPrice=%.4f orderId=%s", symbol, sl_price, sl_order_id)
        except Exception as e:
            logger.critical("SL 주문 등록 실패 (%s): %s → 즉시 포지션 청산", symbol, e)
            try:
                self._client.close_position(symbol, side, quantity)
            except Exception as close_err:
                logger.critical("긴급 청산도 실패: %s", close_err)
            raise StopLossRegistrationError(
                f"SL 등록 실패로 포지션 강제 청산: {e}"
            ) from e

        # TP 주문 등록 (실패해도 계속)
        tp_order_id: Optional[str] = None
        tp_price = self._exit_mgr.compute_tp_price(entry_price, side)
        if tp_price:
            tp_side = "SELL" if side == "LONG" else "BUY"
            try:
                tp_result = self._client.take_profit_order(symbol, tp_side, tp_price, quantity)
                tp_order_id = tp_result.get("orderId")
                logger.info("TP 등록: %s stopPrice=%.4f orderId=%s", symbol, tp_price, tp_order_id)
            except Exception as e:
                logger.warning("TP 주문 등록 실패 (%s): %s — 계속 진행", symbol, e)

        pos = MyPosition(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            leverage=self._cfg.position.leverage,
            unrealized_pnl=0.0,
            opened_at=datetime.utcnow(),
            source_signal=signal,
            sl_order_id=sl_order_id,
            tp_order_id=tp_order_id,
            high_water_mark=entry_price,
        )
        self._tracker.add(pos)
        return pos

    # ── 청산 ────────────────────────────────────────────────────────────────

    def close_position(self, pos: MyPosition, reason: str = "") -> bool:
        symbol = pos.symbol
        side = pos.side

        # 기존 SL/TP 주문 취소
        for oid in [pos.sl_order_id, pos.tp_order_id]:
            if oid:
                try:
                    self._client.cancel_order(symbol, oid)
                except Exception as e:
                    logger.warning("주문 취소 실패 (%s %s): %s", symbol, oid, e)

        try:
            self._client.close_position(symbol, side, pos.quantity)
            self._tracker.remove(symbol, side)
            logger.info("포지션 청산: %s %s | 사유: %s", side, symbol, reason or "N/A")
            return True
        except Exception as e:
            logger.error("청산 실패 (%s %s): %s", side, symbol, e)
            return False

    def close_all(self, reason: str = "강제 청산") -> None:
        for pos in list(self._tracker.all()):
            self.close_position(pos, reason)

    # ── SL 주문 갱신 (트레일링) ─────────────────────────────────────────────

    def update_sl_order(self, pos: MyPosition, new_sl_price: float) -> bool:
        symbol = pos.symbol
        side = pos.side
        sl_side = "SELL" if side == "LONG" else "BUY"

        # 기존 SL 취소
        if pos.sl_order_id:
            try:
                self._client.cancel_order(symbol, pos.sl_order_id)
            except Exception as e:
                logger.warning("기존 SL 취소 실패: %s", e)

        # 새 SL 등록
        try:
            result = self._client.stop_market_order(
                symbol, sl_side, new_sl_price, pos.quantity, close_position=True
            )
            new_oid = result.get("orderId")
            self._tracker.update_sl_order(symbol, side, new_oid)
            logger.info("SL 갱신: %s → %.4f (orderId=%s)", symbol, new_sl_price, new_oid)
            return True
        except Exception as e:
            logger.error("SL 갱신 실패 (%s): %s", symbol, e)
            return False
