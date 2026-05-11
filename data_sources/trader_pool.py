from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from core.config import TraderConfig
from core.exceptions import DataSourceError
from core.models import TraderPosition
from data_sources.hl_lb import HlPositionFetcher

logger = logging.getLogger(__name__)


class TraderPool:
    """다중 트레이더 폴링 통합 관리자"""

    def __init__(self, trader_configs: list[TraderConfig]) -> None:
        self._configs: list[TraderConfig] = list(trader_configs)
        self._scrapers: dict[str, HlPositionFetcher] = {
            c.uid.lower(): HlPositionFetcher(c.uid) for c in trader_configs
        }
        self._last_positions: dict[str, list[TraderPosition]] = {}
        self._error_counts: dict[str, int] = {c.uid.lower(): 0 for c in trader_configs}
        self._lock = threading.Lock()

    @property
    def trader_count(self) -> int:
        with self._lock:
            return len(self._configs)

    # ── 런타임 추가/제거 ─────────────────────────────────────────────────────

    def add_trader(self, uid: str, name: str, weight: float = 1.0) -> bool:
        """런타임에 트레이더 추가. 이미 있으면 False."""
        uid_l = uid.lower()
        with self._lock:
            if uid_l in self._scrapers:
                return False
            self._configs.append(TraderConfig(uid=uid, name=name, weight=weight))
            self._scrapers[uid_l] = HlPositionFetcher(uid)
            self._error_counts[uid_l] = 0
        logger.info("트레이더 추가: %s (%s)", name, uid_l[:10])
        return True

    def remove_trader(self, uid: str) -> bool:
        """런타임에 트레이더 제거. 없으면 False."""
        uid_l = uid.lower()
        with self._lock:
            if uid_l not in self._scrapers:
                return False
            self._configs = [c for c in self._configs if c.uid.lower() != uid_l]
            self._scrapers.pop(uid_l, None)
            self._error_counts.pop(uid_l, None)
            self._last_positions.pop(uid_l, None)
        logger.info("트레이더 제거: %s", uid_l[:10])
        return True

    def list_traders(self) -> list[TraderConfig]:
        with self._lock:
            return list(self._configs)

    # ── 폴링 ────────────────────────────────────────────────────────────────

    def fetch_all(self) -> dict[str, list[TraderPosition]]:
        """모든 트레이더 포지션을 병렬로 조회"""
        with self._lock:
            scrapers = dict(self._scrapers)  # snapshot
        if not scrapers:
            return {}
        results: dict[str, list[TraderPosition]] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(scrapers))) as executor:
            futures = {
                executor.submit(scrapers[uid].fetch_positions): uid
                for uid in scrapers
            }
            for future in as_completed(futures):
                uid = futures[future]
                try:
                    positions = future.result()
                    results[uid] = positions
                    self._error_counts[uid] = 0
                    self._last_positions[uid] = positions
                except DataSourceError as e:
                    self._error_counts[uid] = self._error_counts.get(uid, 0) + 1
                    logger.warning("트레이더 %s 조회 실패 (연속 %d회): %s",
                                   uid, self._error_counts[uid], e)
                    # 이전 캐시 유지
                    results[uid] = self._last_positions.get(uid, [])
        return results

    def _fetch_one(self, uid: str) -> list[TraderPosition]:
        return self._scrapers[uid.lower()].fetch_positions()

    def get_all_positions_flat(self) -> list[TraderPosition]:
        """최신 캐시에서 전체 포지션 목록"""
        all_positions: list[TraderPosition] = []
        for positions in self._last_positions.values():
            all_positions.extend(positions)
        return all_positions

    def get_weight(self, trader_uid: str) -> float:
        uid_l = trader_uid.lower()
        for c in self._configs:
            if c.uid.lower() == uid_l:
                return c.weight
        return 1.0

    def get_trader_name(self, uid: str) -> str:
        uid_l = uid.lower()
        for c in self._configs:
            if c.uid.lower() == uid_l:
                return c.name
        return uid[:8]
