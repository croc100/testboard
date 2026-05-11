from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_MANUAL_RESET_ONLY = True   # 자동 해제 절대 금지


@dataclass
class CircuitBreakerState:
    tripped: bool = False
    reason: str = ""
    tripped_at: Optional[datetime] = None
    consecutive_losses: int = 0
    api_errors_window: list[float] = field(default_factory=list)   # timestamps


class CircuitBreaker:
    """회로 차단기 — 자동 해제 없음, 수동 해제만"""

    def __init__(
        self,
        max_consecutive_losses: int = 3,
        api_error_window_sec: int = 600,
        api_error_threshold: float = 0.5,
        price_stall_sec: int = 30,
    ) -> None:
        self._max_cons_losses = max_consecutive_losses
        self._api_window = api_error_window_sec
        self._api_threshold = api_error_threshold
        self._price_stall = price_stall_sec
        self._state = CircuitBreakerState()
        self._last_price_update: float = time.time()
        self._api_calls: list[float] = []
        self._api_errors: list[float] = []

    # ── 상태 조회 ────────────────────────────────────────────────────────────

    def is_tripped(self) -> bool:
        return self._state.tripped

    def get_reason(self) -> str:
        return self._state.reason

    # ── 이벤트 수신 ──────────────────────────────────────────────────────────

    def on_loss(self) -> None:
        self._state.consecutive_losses += 1
        logger.info("연속 손절 횟수: %d", self._state.consecutive_losses)
        if self._state.consecutive_losses >= self._max_cons_losses:
            self._trip(f"1시간 내 손절 {self._state.consecutive_losses}회 연속")

    def on_win(self) -> None:
        self._state.consecutive_losses = 0

    def on_api_call(self, success: bool) -> None:
        now = time.time()
        cutoff = now - self._api_window
        self._api_calls = [t for t in self._api_calls if t > cutoff]
        self._api_errors = [t for t in self._api_errors if t > cutoff]
        self._api_calls.append(now)
        if not success:
            self._api_errors.append(now)
        if len(self._api_calls) >= 10:
            error_rate = len(self._api_errors) / len(self._api_calls)
            if error_rate >= self._api_threshold:
                self._trip(f"API 에러율 {error_rate:.0%} 초과 ({self._api_window}초 윈도우)")

    def on_price_update(self) -> None:
        self._last_price_update = time.time()

    def check_price_stall(self) -> None:
        elapsed = time.time() - self._last_price_update
        if elapsed > self._price_stall:
            self._trip(f"거래소 시세 멈춤 감지: {elapsed:.0f}초 업데이트 없음")

    def on_daily_loss_limit(self) -> None:
        self._trip("일일 손실 한도 도달")

    def on_drawdown_limit(self) -> None:
        self._trip("최대 드로우다운 도달")

    # ── 차단기 발동 ──────────────────────────────────────────────────────────

    def _trip(self, reason: str) -> None:
        if self._state.tripped:
            return
        self._state.tripped = True
        self._state.reason = reason
        self._state.tripped_at = datetime.utcnow()
        logger.critical("🚨 회로차단기 발동: %s", reason)

    # ── 수동 해제 ─────────────────────────────────────────────────────────────

    def manual_reset(self) -> None:
        """수동으로만 해제 가능 — 절대 원칙 #7"""
        logger.warning("회로차단기 수동 해제 (이전 사유: %s)", self._state.reason)
        self._state = CircuitBreakerState()
        self._api_calls.clear()
        self._api_errors.clear()
        self._last_price_update = time.time()
