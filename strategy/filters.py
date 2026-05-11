from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.config import FiltersConfig
from core.models import TradeSignal
from data_sources.market_data import MarketData

logger = logging.getLogger(__name__)


class EntryFilterChain:
    """진입 필터 체인 — 하나라도 실패하면 진입 거부"""

    def __init__(self, config: FiltersConfig, market_data: MarketData) -> None:
        self._cfg = config
        self._md = market_data

    def check(self, signal: TradeSignal) -> tuple[bool, str]:
        ok, reason = self._symbol_filter(signal.symbol)
        if not ok:
            return False, reason

        ok, reason = self._signal_age_filter(signal)
        if not ok:
            return False, reason

        ok, reason = self._blackout_filter()
        if not ok:
            return False, reason

        ok, reason = self._funding_filter(signal.symbol)
        if not ok:
            return False, reason

        ok, reason = self._volatility_filter(signal.symbol)
        if not ok:
            return False, reason

        ok, reason = self._trend_filter(signal)
        if not ok:
            return False, reason

        return True, "OK"

    def _symbol_filter(self, symbol: str) -> tuple[bool, str]:
        if self._cfg.symbol_blacklist and symbol in self._cfg.symbol_blacklist:
            return False, f"블랙리스트 심볼: {symbol}"
        if self._cfg.symbol_whitelist and symbol not in self._cfg.symbol_whitelist:
            return False, f"화이트리스트 미포함: {symbol}"
        return True, ""

    def _signal_age_filter(self, signal: TradeSignal) -> tuple[bool, str]:
        now = datetime.utcnow()
        age_min = (now - signal.created_at).total_seconds() / 60
        if age_min > self._cfg.max_signal_age_minutes:
            return False, f"신호 만료: {age_min:.1f}분 경과 (최대 {self._cfg.max_signal_age_minutes}분)"
        return True, ""

    def _blackout_filter(self) -> tuple[bool, str]:
        now = datetime.now(tz=timezone.utc)
        for period in self._cfg.blackout_periods:
            start = period.start
            end = period.end
            # timezone-naive 처리
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if start <= now <= end:
                return False, f"블랙아웃 기간: {period.reason}"
        return True, ""

    def _funding_filter(self, symbol: str) -> tuple[bool, str]:
        try:
            rate = self._md.get_funding_rate(symbol)
            if abs(rate) > self._cfg.max_funding_rate:
                return False, f"펀딩비 과다: {rate:.4%} (최대 {self._cfg.max_funding_rate:.4%})"
        except Exception as e:
            logger.warning("펀딩비 조회 실패 (%s): %s — 필터 통과 처리", symbol, e)
        return True, ""

    def _volatility_filter(self, symbol: str) -> tuple[bool, str]:
        try:
            current_atr = self._md.compute_atr(symbol, period=14)
            avg_atr = self._md.compute_atr(symbol, period=50)
            if avg_atr > 0 and current_atr > avg_atr * self._cfg.max_atr_multiplier:
                return False, (
                    f"변동성 과다: ATR {current_atr:.4f} > "
                    f"평균 {avg_atr:.4f} × {self._cfg.max_atr_multiplier}"
                )
        except Exception as e:
            logger.warning("ATR 조회 실패 (%s): %s — 필터 통과 처리", symbol, e)
        return True, ""

    def _trend_filter(self, signal: TradeSignal) -> tuple[bool, str]:
        try:
            price = self._md.get_price(signal.symbol)
            ema = self._md.get_ema(signal.symbol, period=200)
            if ema is None:
                return True, ""
            if signal.side == "LONG" and price < ema:
                return False, f"트렌드 불일치: 롱 진입 시도이나 가격({price:.2f}) < EMA200({ema:.2f})"
            if signal.side == "SHORT" and price > ema:
                return False, f"트렌드 불일치: 숏 진입 시도이나 가격({price:.2f}) > EMA200({ema:.2f})"
        except Exception as e:
            logger.warning("트렌드 필터 실패 (%s): %s — 통과 처리", signal.symbol, e)
        return True, ""
