from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from exchange.hl_client import HlClient
from execution.position_tracker import PositionTracker

logger = logging.getLogger(__name__)

_DRIFT_THRESHOLD_SEC = 300  # 5분 이상 불일치 → 알림 + 강제 동기화


class Reconciler:
    """거래소 실제 상태 ↔ 내부 상태 정합성 검사"""

    def __init__(self, client: HlClient, tracker: PositionTracker) -> None:
        self._client = client
        self._tracker = tracker
        self._drift_first_seen: dict[str, float] = {}  # position_key → timestamp

    def reconcile(self) -> list[str]:
        """
        불일치 목록 반환. 5분 초과 불일치 시 강제 동기화.
        Returns: 불일치 position_key 목록
        """
        drifted: list[str] = []
        try:
            exchange_positions = {
                f"{p['symbol']}_{'LONG' if float(p['positionAmt']) > 0 else 'SHORT'}": p
                for p in self._client.get_positions()
            }
        except Exception as e:
            logger.error("거래소 포지션 조회 실패 (reconcile): %s", e)
            return []

        internal_keys = {pos.position_key() for pos in self._tracker.all()}
        exchange_keys = set(exchange_positions.keys())

        # 내부에는 있으나 거래소에 없음 (SL 체결로 자동 청산됐을 수 있음)
        for key in internal_keys - exchange_keys:
            logger.warning("Drift 감지: 내부 포지션 %s 가 거래소에 없음", key)
            drifted.append(key)
            self._handle_drift(key, direction="missing_on_exchange")

        # 거래소에는 있으나 내부에 없음 (수동 진입 등)
        for key in exchange_keys - internal_keys:
            logger.warning("Drift 감지: 거래소 포지션 %s 가 내부에 없음", key)
            drifted.append(key)

        # 5분 이상 drift → 강제 동기화
        now = time.time()
        for key in drifted:
            first = self._drift_first_seen.setdefault(key, now)
            if now - first >= _DRIFT_THRESHOLD_SEC:
                logger.error("5분 이상 drift (%s) → 강제 동기화", key)
                self._force_sync(key, exchange_positions)

        # drift 해소된 키 제거
        for key in list(self._drift_first_seen):
            if key not in drifted:
                del self._drift_first_seen[key]

        # PNL 업데이트
        for key, exch_pos in exchange_positions.items():
            parts = key.rsplit("_", 1)
            if len(parts) == 2:
                symbol, side = parts
                pnl = float(exch_pos.get("unrealizedProfit", 0))
                self._tracker.update_pnl(symbol, side, pnl)

        return drifted

    def _handle_drift(self, key: str, direction: str) -> None:
        if direction == "missing_on_exchange":
            # 거래소에서 SL/TP 등으로 자동 청산된 것 → 내부에서 제거
            parts = key.rsplit("_", 1)
            if len(parts) == 2:
                symbol, side = parts
                removed = self._tracker.remove(symbol, side)
                if removed:
                    logger.info("내부 포지션 자동 정리: %s (거래소에서 청산됨)", key)

    def _force_sync(self, key: str, exchange_positions: dict) -> None:
        parts = key.rsplit("_", 1)
        if len(parts) != 2:
            return
        symbol, side = parts
        if key not in exchange_positions:
            self._tracker.remove(symbol, side)
            logger.warning("강제 동기화: %s 내부에서 제거", key)
        del self._drift_first_seen[key]
