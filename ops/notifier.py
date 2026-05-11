from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import telegram
    from telegram import Bot
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False
    logger.warning("python-telegram-bot 미설치 — 텔레그램 알림 비활성화")


class Notifier:
    """텔레그램 알림 발송 (비동기 스레드)"""

    PRIORITY_LOW = "LOW"
    PRIORITY_NORMAL = "NORMAL"
    PRIORITY_HIGH = "HIGH"
    PRIORITY_CRITICAL = "CRITICAL"

    _EMOJI = {
        "LOW": "ℹ️",
        "NORMAL": "✅",
        "HIGH": "⚠️",
        "CRITICAL": "🚨",
    }

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._chat_id = chat_id
        self._bot: Optional[object] = None
        if _TG_AVAILABLE and bot_token and chat_id:
            try:
                self._bot = Bot(token=bot_token)
                logger.info("텔레그램 봇 초기화 완료")
            except Exception as e:
                logger.warning("텔레그램 봇 초기화 실패: %s", e)

    def send(self, message: str, priority: str = "NORMAL") -> None:
        emoji = self._EMOJI.get(priority, "")
        full_msg = f"{emoji} {message}" if emoji else message
        threading.Thread(target=self._send_sync, args=(full_msg,), daemon=True).start()

    def _send_sync(self, message: str) -> None:
        if self._bot is None:
            logger.info("[NOTIFY] %s", message)
            return
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                self._bot.send_message(  # type: ignore[attr-defined]
                    chat_id=self._chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            )
            loop.close()
        except Exception as e:
            logger.warning("텔레그램 발송 실패: %s", e)

    # ── 편의 메서드 ──────────────────────────────────────────────────────────

    def on_start(self, balance: float) -> None:
        self.send(
            f"<b>봇 시작</b>\n잔고: <code>${balance:,.2f} USDT</code>",
            self.PRIORITY_NORMAL,
        )

    def on_stop(self, reason: str = "") -> None:
        self.send(
            f"<b>봇 종료</b>\n사유: {reason or 'N/A'}",
            self.PRIORITY_NORMAL,
        )

    def on_signal(self, symbol: str, side: str, confidence: float, traders: int) -> None:
        self.send(
            f"📡 <b>신호 감지</b>: {symbol} {side}\n"
            f"합의 트레이더: {traders}명 | 신뢰도: {confidence:.0%}",
            self.PRIORITY_LOW,
        )

    def on_entry(self, symbol: str, side: str, qty: float, price: float,
                 sl: float, tp: Optional[float]) -> None:
        tp_str = f"${tp:.4f}" if tp else "없음"
        self.send(
            f"<b>진입 체결</b>: {symbol} {side}\n"
            f"수량: {qty:.6f} | 가격: ${price:.4f}\n"
            f"SL: ${sl:.4f} | TP: {tp_str}",
            self.PRIORITY_NORMAL,
        )

    def on_close(self, symbol: str, side: str, pnl: float,
                 hold_hours: float, reason: str) -> None:
        sign = "+" if pnl >= 0 else ""
        self.send(
            f"<b>청산</b>: {symbol} {side}\n"
            f"PNL: <code>{sign}${pnl:.2f}</code> | 보유: {hold_hours:.1f}h\n"
            f"사유: {reason}",
            self.PRIORITY_NORMAL,
        )

    def on_stop_loss(self, symbol: str, loss: float) -> None:
        self.send(
            f"<b>손절 발동</b>: {symbol}\n손실: <code>-${abs(loss):.2f}</code>",
            self.PRIORITY_HIGH,
        )

    def on_circuit_breaker(self, reason: str, closed: int) -> None:
        self.send(
            f"<b>🚨 회로차단기 발동</b>\n"
            f"사유: {reason}\n청산 포지션: {closed}개\n"
            f"신규 진입이 차단됩니다. 수동 해제 필요.",
            self.PRIORITY_CRITICAL,
        )

    def on_daily_report(self, trades: int, win_rate: float, pnl: float) -> None:
        sign = "+" if pnl >= 0 else ""
        self.send(
            f"<b>일일 리포트</b>\n"
            f"진입: {trades}회 | 승률: {win_rate:.0%}\n"
            f"누적 PNL: <code>{sign}${pnl:.2f}</code>",
            self.PRIORITY_NORMAL,
        )

    def on_api_error(self, error_rate: float, window_min: int) -> None:
        self.send(
            f"<b>API 에러 누적</b>\n"
            f"에러율: {error_rate:.0%} ({window_min}분 내)",
            self.PRIORITY_HIGH,
        )

    def on_drift(self, keys: list[str]) -> None:
        self.send(
            f"<b>포지션 불일치 감지</b>\n키: {', '.join(keys)}",
            self.PRIORITY_HIGH,
        )
