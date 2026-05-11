"""Hyperliquid 리더보드 — 단일 트레이더 포지션 조회 + 전체 리더보드 조회"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from core.exceptions import DataSourceError
from core.models import TraderPosition

logger = logging.getLogger(__name__)

_INFO_URL = "https://api.hyperliquid.xyz/info"
_LB_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"


class HlPositionFetcher:
    """단일 트레이더(지갑) 포지션 조회 — clearinghouseState 사용"""

    def __init__(
        self,
        trader_uid: str,           # ETH 지갑 주소 (0x...)
        backoff_base: float = 2.0,
        max_retries: int = 5,
        timeout: int = 10,
    ) -> None:
        self.trader_uid = trader_uid.lower()
        self._backoff_base = backoff_base
        self._max_retries = max_retries
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._consecutive_errors = 0

    def fetch_positions(self) -> list[TraderPosition]:
        payload = {"type": "clearinghouseState", "user": self.trader_uid}
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.post(_INFO_URL, json=payload, timeout=self._timeout)
                if resp.status_code == 429:
                    wait = self._backoff_base ** (attempt + 2)
                    logger.warning("Rate limited. %ds 대기 후 재시도.", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                self._consecutive_errors = 0
                return self._parse(data)
            except (requests.RequestException, KeyError, ValueError) as e:
                last_exc = e
                wait = self._backoff_base ** attempt
                logger.warning(
                    "HL position fetch 실패 (시도 %d/%d): %s. %.1fs 후 재시도.",
                    attempt + 1, self._max_retries, e, wait,
                )
                time.sleep(wait)
        self._consecutive_errors += 1
        raise DataSourceError(
            f"트레이더 {self.trader_uid[:10]}… 포지션 조회 실패: {last_exc}"
        )

    def _parse(self, data: dict) -> list[TraderPosition]:
        positions: list[TraderPosition] = []
        now_ms = int(time.time() * 1000)
        for asset_pos in data.get("assetPositions", []):
            try:
                p = asset_pos.get("position", {})
                size = float(p.get("szi", 0))
                if size == 0:
                    continue
                side = "LONG" if size > 0 else "SHORT"
                lev = p.get("leverage", {})
                positions.append(TraderPosition(
                    trader_uid=self.trader_uid,
                    symbol=p.get("coin", "") + "USDT",   # BTC → BTCUSDT
                    side=side,
                    entry_price=float(p.get("entryPx") or 0),
                    mark_price=float(p.get("entryPx") or 0),  # HL는 markPx 별도 호출 필요
                    amount=abs(size),
                    leverage=int(lev.get("value", 1)),
                    pnl=float(p.get("unrealizedPnl") or 0),
                    roe=float(p.get("returnOnEquity") or 0),
                    update_time=now_ms,
                ))
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("HL 포지션 파싱 스킵: %s — %s", asset_pos, e)
        return positions


class HlLeaderboard:
    """Hyperliquid 전체 리더보드 조회 — 후보 트레이더 발굴용"""

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout
        self._session = requests.Session()

    def fetch(self) -> list[dict]:
        """
        전체 리더보드 반환. 각 entry는:
            {
              "ethAddress": "0x...",
              "accountValue": "...",     (현재 계좌 가치 USDT)
              "windowPerformances": [
                  ["day"|"week"|"month"|"allTime",
                   {"pnl": "...", "roi": "...", "vlm": "..."}],
                  ...
              ],
              "displayName": "..."|null,
            }
        """
        try:
            resp = self._session.get(_LB_URL, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json().get("leaderboardRows", [])
        except (requests.RequestException, ValueError) as e:
            raise DataSourceError(f"HL 리더보드 조회 실패: {e}") from e

    def filter_candidates(
        self,
        rows: list[dict],
        min_account_value: float = 10_000,
        min_month_roi: float = 0.20,
        min_month_volume: float = 100_000,
        max_month_drawdown: float = 0.30,
    ) -> list[dict]:
        """
        후보 트레이더 필터링.
        - accountValue ≥ min_account_value
        - 월 ROI ≥ min_month_roi
        - 월 거래량 ≥ min_month_volume
        - 월 PnL이 -drawdown 한도 이내 (단순 근사)
        """
        out: list[dict] = []
        for row in rows:
            try:
                acct = float(row.get("accountValue", 0))
                if acct < min_account_value:
                    continue
                perf_map = {p[0]: p[1] for p in row.get("windowPerformances", [])}
                month = perf_map.get("month")
                if not month:
                    continue
                roi = float(month.get("roi", 0))
                vlm = float(month.get("vlm", 0))
                if roi < min_month_roi:
                    continue
                if vlm < min_month_volume:
                    continue
                if roi < -max_month_drawdown:
                    continue
                out.append(row)
            except (KeyError, TypeError, ValueError):
                continue
        # ROI 내림차순
        out.sort(
            key=lambda r: float(
                next((p[1]["roi"] for p in r["windowPerformances"] if p[0] == "month"), 0)
            ),
            reverse=True,
        )
        return out
