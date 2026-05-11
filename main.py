#!/usr/bin/env python3
"""
Ebenezer — Hyperliquid Copy Trading Bot
진입점: python main.py [--once] [--live] [--reset-cb]
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 환경변수 로드 (.env) ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.config import load_config
from core.exceptions import CircuitBreakerTrippedError, StopLossRegistrationError
from core.models import AccountState, MyPosition
from data_sources.market_data import MarketData
from data_sources.trader_pool import TraderPool
from exchange.hl_client import HlClient
from execution.order_manager import OrderManager
from execution.position_tracker import PositionTracker
from execution.reconciler import Reconciler
from ops.controller import TelegramController
from ops.health import HealthChecker
from ops.metrics import MetricsCollector, TradeRecord
from ops.notifier import Notifier
from persistence.database import init_db
from persistence.repository import TradeRepository
from risk.circuit_breaker import CircuitBreaker
from risk.correlation import CorrelationChecker
from risk.limits import LimitsChecker
from strategy.consensus import ConsensusEngine
from strategy.exits import ExitManager
from strategy.filters import EntryFilterChain
from strategy.sizing import PositionSizer

logger = logging.getLogger(__name__)

_RUNNING = True


def _setup_logging(log_file: str, level: str) -> None:
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)


def _confirm_live_mode() -> bool:
    """DRY_RUN → 실거래 전환 시 명시적 컨펌 (절대 원칙 #5)"""
    print("\n" + "=" * 60)
    print("⚠️  실거래 모드 전환 요청")
    print("실제 자금으로 거래됩니다. 계속하려면 'YES'를 입력하세요.")
    print("=" * 60)
    answer = input("입력: ").strip()
    return answer == "YES"


def _make_account_state(client: HlClient, tracker: PositionTracker,
                        daily_pnl: float, cum_pnl: float, peak: float) -> AccountState:
    balance = client.get_balance()
    return AccountState(
        balance_usdt=balance,
        open_positions=tracker.all(),
        daily_realized_pnl=daily_pnl,
        cumulative_pnl=cum_pnl,
        peak_balance=peak or balance,
    )


class CopyTrader:
    """전체 봇 조립자"""

    def __init__(self, config_path: str = "config.yaml", live: bool = False) -> None:
        self._cfg = load_config(config_path)

        # 실거래 전환 처리
        if live:
            if not _confirm_live_mode():
                print("취소됨. DRY_RUN으로 실행합니다.")
            else:
                self._cfg.mode.dry_run = False
                logger.warning("🔴 실거래 모드 활성화")

        _setup_logging(self._cfg.ops.log_file, self._cfg.ops.log_level)
        init_db(self._cfg.ops.db_path)

        # 의존성 초기화
        self._client = HlClient(self._cfg)
        self._tracker = PositionTracker()
        self._market = MarketData(self._client)
        self._pool = TraderPool(self._cfg.traders)
        self._exit_mgr = ExitManager(self._cfg.exits)
        self._sizer = PositionSizer(self._cfg.position, self._market)
        self._consensus = ConsensusEngine(self._cfg.consensus, self._pool)
        self._filters = EntryFilterChain(self._cfg.filters, self._market)
        self._cb = CircuitBreaker(
            max_consecutive_losses=self._cfg.risk.max_consecutive_losses,
        )
        self._limits = LimitsChecker(self._cfg.risk)
        self._correlation = CorrelationChecker()
        self._order_mgr = OrderManager(
            self._client, self._cfg, self._tracker, self._sizer, self._exit_mgr
        )
        self._reconciler = Reconciler(self._client, self._tracker)
        self._notifier = Notifier(
            self._cfg.ops.telegram_bot_token, self._cfg.ops.telegram_chat_id
        )
        self._metrics = MetricsCollector()
        self._health = HealthChecker()
        self._repo = TradeRepository()

        # 운영 상태
        self._daily_pnl: float = 0.0
        self._cum_pnl: float = 0.0
        self._peak_balance: float = 0.0
        self._paused: bool = False
        self._trade_ids: dict[str, int] = {}  # position_key → db id

        # 텔레그램 컨트롤러 (명령어 수신)
        self._controller = TelegramController(
            self._cfg.ops.telegram_bot_token,
            self._cfg.ops.telegram_chat_id,
            self,
        )

    # ── 시작 ─────────────────────────────────────────────────────────────────

    def start(self, once: bool = False) -> None:
        logger.info("Ebenezer 봇 시작 (DRY_RUN=%s)", self._cfg.mode.dry_run)

        # API 권한 검증 (절대 원칙 #1)
        try:
            self._client.validate_api_permissions()
        except Exception as e:
            logger.critical("API 권한 검증 실패: %s — 봇 종료", e)
            sys.exit(1)

        balance = self._client.get_balance()
        self._peak_balance = balance
        self._notifier.on_start(balance)

        # 텔레그램 컨트롤러 시작 (--once 모드에선 생략)
        if not once:
            self._controller.start()

        if once:
            self._cycle()
            return

        interval = self._cfg.ops.poll_interval_sec
        while _RUNNING:
            try:
                self._cycle()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("사이클 예외: %s", e, exc_info=True)
                self._health.on_error(str(e))
            time.sleep(interval)

        self._shutdown()

    def _cycle(self) -> None:
        self._health.on_cycle_start()

        # 1. 가격 스탈 체크
        try:
            self._client.get_ticker_price("BTCUSDT")
            self._cb.on_price_update()
        except Exception:
            self._cb.check_price_stall()

        # 2. 회로차단기 확인
        if self._cb.is_tripped():
            logger.warning("회로차단기 발동 중 — 사이클 건너뜀 (사유: %s)", self._cb.get_reason())
            return

        # 3. 계좌 상태 조회
        try:
            account = _make_account_state(
                self._client, self._tracker,
                self._daily_pnl, self._cum_pnl, self._peak_balance,
            )
            self._cb.on_api_call(True)
        except Exception as e:
            logger.error("계좌 조회 실패: %s", e)
            self._cb.on_api_call(False)
            return

        # 4. 일일 손실 / 드로우다운 체크
        ok, reason = self._limits.check_daily_loss(account)
        if not ok:
            self._cb.on_daily_loss_limit()
            self._emergency_shutdown(reason)
            return

        ok, reason = self._limits.check_drawdown(account)
        if not ok:
            self._cb.on_drawdown_limit()
            self._emergency_shutdown(reason)
            return

        # 5. 기존 포지션 모니터링 (SL/트레일링/시간손절)
        self._monitor_positions(account)

        # 6. 거래소 ↔ 내부 정합성 확인
        drifted = self._reconciler.reconcile()
        if drifted:
            self._notifier.on_drift(drifted)

        # 7. 랭커 포지션 폴링
        all_positions = self._pool.fetch_all()

        # 8. 합의 신호 생성
        reduction = self._limits.drawdown_size_reduction(account)
        signals = self._consensus.evaluate(
            all_positions,
            base_capital_usdt=account.balance_usdt * self._cfg.position.base_capital_pct,
            stop_loss_pct=self._cfg.exits.hard_stop_loss_pct,
            take_profit_pct=(
                self._cfg.exits.partial_tp_levels[0].pct
                if self._cfg.exits.partial_tp_levels else 0.03
            ),
        )

        # 9. 신호 처리
        for signal in signals:
            if self._tracker.has_position(signal.symbol, signal.side):
                continue
            self._process_signal(signal, account, reduction)

        self._health.on_success()

    # ── 신호 처리 ────────────────────────────────────────────────────────────

    def _process_signal(self, signal, account, size_reduction: float) -> None:
        self._repo.log_signal(
            signal.symbol, signal.side, signal.confidence,
            signal.supporting_traders, signal.avg_entry_price, acted=False,
        )
        self._notifier.on_signal(
            signal.symbol, signal.side, signal.confidence,
            len(signal.supporting_traders),
        )

        # Pre-trade 체크 (사양서 §6.1)
        ok, reason = self._pre_trade_check(signal, account)
        if not ok:
            logger.info("진입 거부 [%s]: %s", signal.position_key(), reason)
            self._repo.log_signal(
                signal.symbol, signal.side, signal.confidence,
                signal.supporting_traders, signal.avg_entry_price,
                acted=False, reject_reason=reason,
            )
            return

        # 진입
        try:
            pos = self._order_mgr.enter_position(signal, account)
        except StopLossRegistrationError as e:
            logger.critical("SL 등록 실패 — 포지션 강제 청산됨: %s", e)
            return
        except Exception as e:
            logger.error("진입 실패: %s", e)
            return

        if pos is None:
            return

        sl_price = self._exit_mgr.compute_sl_price(pos.entry_price, pos.side)
        tp_price = self._exit_mgr.compute_tp_price(pos.entry_price, pos.side)
        self._notifier.on_entry(
            pos.symbol, pos.side, pos.quantity, pos.entry_price, sl_price, tp_price
        )

        trade_id = self._repo.open_trade(
            pos.symbol, pos.side, pos.entry_price, pos.quantity,
            pos.leverage, signal.confidence, signal.supporting_traders,
        )
        self._trade_ids[pos.position_key()] = trade_id

    def _pre_trade_check(self, signal, account: AccountState) -> tuple[bool, str]:
        if self._paused:
            return False, "일시중지 상태 (/resume으로 재개)"
        if self._cb.is_tripped():
            return False, "회로차단기 발동"
        ok, reason = self._limits.check_daily_loss(account)
        if not ok:
            return False, reason
        ok, reason = self._limits.check_drawdown(account)
        if not ok:
            return False, reason
        if len(account.open_positions) >= self._cfg.position.max_concurrent:
            return False, f"동시 포지션 한도 ({self._cfg.position.max_concurrent}개)"
        if self._correlation.would_exceed_limit(signal, account):
            return False, "상관관계 한도"
        ok, reason = self._filters.check(signal)
        if not ok:
            return False, reason
        if signal.confidence < self._cfg.consensus.min_confidence:
            return False, f"신뢰도 부족 ({signal.confidence:.2f})"
        return True, "OK"

    # ── 포지션 모니터링 ──────────────────────────────────────────────────────

    def _monitor_positions(self, account: AccountState) -> None:
        for pos in list(self._tracker.all()):
            try:
                price = self._market.get_price(pos.symbol)
            except Exception:
                continue

            self._tracker.update_high_water_mark(pos.symbol, pos.side, price)
            pos = self._tracker.get(pos.symbol, pos.side)
            if pos is None:
                continue

            # 시간 손절
            if self._exit_mgr.is_time_stop(pos):
                logger.info("시간 손절: %s (%s)", pos.symbol, pos.side)
                self._close_and_record(pos, price, "시간손절")
                continue

            # 트레일링 스탑 갱신
            if self._exit_mgr.should_trail_stop(pos, price):
                new_sl = self._exit_mgr.compute_trail_sl(pos, price)
                old_sl = self._exit_mgr.compute_sl_price(pos.entry_price, pos.side)
                is_better = (
                    (pos.side == "LONG" and new_sl > old_sl) or
                    (pos.side == "SHORT" and new_sl < old_sl)
                )
                if is_better:
                    self._order_mgr.update_sl_order(pos, new_sl)

    def _close_and_record(self, pos: MyPosition, exit_price: float, reason: str) -> None:
        pnl = (
            (exit_price - pos.entry_price) * pos.quantity
            if pos.side == "LONG"
            else (pos.entry_price - exit_price) * pos.quantity
        )
        self._order_mgr.close_position(pos, reason)

        self._daily_pnl += pnl
        self._cum_pnl += pnl
        hold_h = (datetime.utcnow() - pos.opened_at).total_seconds() / 3600

        self._notifier.on_close(pos.symbol, pos.side, pnl, hold_h, reason)
        if pnl < 0:
            self._notifier.on_stop_loss(pos.symbol, pnl)
            self._cb.on_loss()
            self._sizer.notify_loss()
        else:
            self._cb.on_win()
            self._sizer.notify_win()

        self._metrics.record_trade(TradeRecord(
            symbol=pos.symbol, side=pos.side,
            entry_price=pos.entry_price, exit_price=exit_price,
            quantity=pos.quantity, pnl=pnl,
            opened_at=pos.opened_at, closed_at=datetime.utcnow(),
            reason=reason,
        ))

        trade_id = self._trade_ids.pop(pos.position_key(), None)
        if trade_id:
            self._repo.close_trade(trade_id, exit_price, pnl, reason)

    # ── 긴급 종료 ────────────────────────────────────────────────────────────

    def _emergency_shutdown(self, reason: str) -> None:
        logger.critical("긴급 종료: %s", reason)
        self._order_mgr.close_all(reason)
        closed = len(self._tracker.all())  # after close_all should be 0
        self._notifier.on_circuit_breaker(reason, closed)
        self._repo.log_circuit_breaker(reason)

    def _shutdown(self) -> None:
        logger.info("봇 정상 종료")
        summary = self._metrics.daily_summary()
        self._notifier.on_stop(
            f"PNL={summary.get('total_pnl', 0):.2f} "
            f"trades={summary.get('trades', 0)}"
        )

    def reset_circuit_breaker(self) -> None:
        self._cb.manual_reset()
        logger.info("회로차단기 수동 해제 완료")


# ── 엔트리포인트 ──────────────────────────────────────────────────────────────

def main() -> None:
    global _RUNNING

    parser = argparse.ArgumentParser(description="Ebenezer Copy Trader")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument("--once", action="store_true", help="단일 사이클만 실행")
    parser.add_argument("--live", action="store_true", help="DRY_RUN 해제 (실거래)")
    parser.add_argument("--reset-cb", action="store_true", help="회로차단기 수동 해제")
    args = parser.parse_args()

    def _sig_handler(sig, frame):
        global _RUNNING
        logger.info("종료 신호 수신 (%s)", sig)
        _RUNNING = False

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    bot = CopyTrader(config_path=args.config, live=args.live)

    if args.reset_cb:
        bot.reset_circuit_breaker()
        return

    bot.start(once=args.once)


if __name__ == "__main__":
    main()
