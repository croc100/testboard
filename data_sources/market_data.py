from __future__ import annotations

import logging
import statistics
from typing import Optional

from exchange.hl_client import HlClient

logger = logging.getLogger(__name__)


class MarketData:
    def __init__(self, client: HlClient) -> None:
        self._client = client
        self._atr_cache: dict[str, tuple[float, float]] = {}  # symbol → (atr, ts)

    def get_price(self, symbol: str) -> float:
        return self._client.get_ticker_price(symbol)

    def get_funding_rate(self, symbol: str) -> float:
        return self._client.get_funding_rate(symbol)

    def compute_atr(self, symbol: str, period: int = 14) -> float:
        """ATR(14) 계산 — 1시간봉 기준"""
        klines = self._client.get_klines(symbol, interval="1h", limit=period + 1)
        if len(klines) < 2:
            logger.warning("ATR 계산 불가 (%s): 데이터 부족", symbol)
            return 0.0
        trs: list[float] = []
        for i in range(1, len(klines)):
            high = float(klines[i][2])
            low = float(klines[i][3])
            prev_close = float(klines[i - 1][4])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        return statistics.mean(trs[-period:]) if trs else 0.0

    def get_ema(self, symbol: str, period: int = 200) -> Optional[float]:
        """EMA 계산 — 1시간봉"""
        klines = self._client.get_klines(symbol, interval="1h", limit=period + 1)
        if len(klines) < period:
            return None
        closes = [float(k[4]) for k in klines]
        k = 2 / (period + 1)
        ema = closes[0]
        for c in closes[1:]:
            ema = c * k + ema * (1 - k)
        return ema
