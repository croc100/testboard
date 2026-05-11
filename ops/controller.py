"""
텔레그램 명령어 컨트롤러.

본인 chat_id에서만 명령을 받고, 봇을 실시간 제어한다.
별도 스레드에서 polling 방식으로 동작.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Callable, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from main import CopyTrader

try:
    from telegram import Update
    from telegram.ext import (Application, CommandHandler, ContextTypes,
                              MessageHandler, filters)
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False
    logger.warning("python-telegram-bot 미설치 — 텔레그램 컨트롤러 비활성화")


_HELP_TEXT = """
<b>Ebenezer 봇 명령어</b>

<b>📊 조회</b>
/status — 종합 상태
/balance — 잔고
/positions — 현재 포지션
/pnl — 일일/누적 PnL
/traders — 추종 트레이더
/cb — 회로차단기 상태
/sizing — 자본/레버리지 설정 보기

<b>⚙️ 제어</b>
/pause — 신규 진입 중지 (모니터링은 계속)
/resume — 진입 재개
/cb_reset — 회로차단기 수동 해제
/capital &lt;금액&gt; — 1회 진입 마진 고정 (예: /capital 6)
/capital auto — 자본 비율 모드로 복원
/leverage &lt;배수&gt; — 레버리지 변경 (다음 진입부터)
/consensus &lt;N&gt; — 합의 최소 트레이더 수 (예: /consensus 1)

<b>👥 트레이더 관리</b>
/listtraders — 추종 목록
/addtrader &lt;0x주소&gt; &lt;이름&gt; — 추가
/removetrader &lt;0x주소&gt; — 제거
/findtraders [N] — 단타 후보 Top N (기본 10)
/analyze &lt;0x주소&gt; — 해당 트레이더 거래 종목 분포
/whitelist — 거래 허용 종목 보기 / 추가 / 제거

<b>🛑 긴급</b>
/closeall — 모든 포지션 청산
/close &lt;SYMBOL&gt; &lt;LONG|SHORT&gt; — 특정 포지션 청산

/help — 이 메시지
"""


class TelegramController:
    """텔레그램 명령어 수신·처리"""

    def __init__(self, bot_token: str, allowed_chat_id: str,
                 trader: "CopyTrader") -> None:
        self._token = bot_token
        self._chat_id = str(allowed_chat_id)
        self._trader = trader
        self._app: Optional[object] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── 시작/종료 ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not _TG_AVAILABLE or not self._token or not self._chat_id:
            logger.info("텔레그램 컨트롤러 비활성 (미설정)")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("텔레그램 컨트롤러 시작")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_async())
        except Exception as e:
            logger.error("텔레그램 컨트롤러 오류: %s", e, exc_info=True)

    async def _run_async(self) -> None:
        """run_polling 대신 명시적으로 컴포넌트들을 시작 (스레드 호환)"""
        app = Application.builder().token(self._token).build()
        self._app = app
        self._register_handlers(app)

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=False)
        logger.info("텔레그램 폴링 시작됨")
        # 무한 대기 (스레드가 살아있는 한 동작)
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    # ── 핸들러 등록 ──────────────────────────────────────────────────────────

    def _register_handlers(self, app) -> None:
        app.add_handler(CommandHandler("start", self._cmd_help))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("balance", self._cmd_balance))
        app.add_handler(CommandHandler("positions", self._cmd_positions))
        app.add_handler(CommandHandler("pnl", self._cmd_pnl))
        app.add_handler(CommandHandler("traders", self._cmd_traders))
        app.add_handler(CommandHandler("cb", self._cmd_cb))
        app.add_handler(CommandHandler("cb_reset", self._cmd_cb_reset))
        app.add_handler(CommandHandler("pause", self._cmd_pause))
        app.add_handler(CommandHandler("resume", self._cmd_resume))
        app.add_handler(CommandHandler("close", self._cmd_close))
        app.add_handler(CommandHandler("closeall", self._cmd_closeall))
        app.add_handler(CommandHandler("capital", self._cmd_capital))
        app.add_handler(CommandHandler("leverage", self._cmd_leverage))
        app.add_handler(CommandHandler("sizing", self._cmd_sizing))
        app.add_handler(CommandHandler("listtraders", self._cmd_listtraders))
        app.add_handler(CommandHandler("addtrader", self._cmd_addtrader))
        app.add_handler(CommandHandler("removetrader", self._cmd_removetrader))
        app.add_handler(CommandHandler("findtraders", self._cmd_findtraders))
        app.add_handler(CommandHandler("consensus", self._cmd_consensus))
        app.add_handler(CommandHandler("analyze", self._cmd_analyze))
        app.add_handler(CommandHandler("whitelist", self._cmd_whitelist))
        # 본인 chat_id 외엔 무시
        app.add_handler(MessageHandler(filters.ALL, self._cmd_unknown))

    def _is_authorized(self, update: Update) -> bool:
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        ok = chat_id == self._chat_id
        if not ok:
            logger.warning("미인가 chat_id: %s", chat_id)
        return ok

    async def _reply(self, update: Update, text: str) -> None:
        await update.effective_chat.send_message(text, parse_mode="HTML")

    # ── 명령어 핸들러 ───────────────────────────────────────────────────────

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        await self._reply(update, _HELP_TEXT)

    async def _cmd_status(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        try:
            balance = self._trader._client.get_balance()
            positions = self._trader._tracker.all()
            cb_tripped = self._trader._cb.is_tripped()
            paused = getattr(self._trader, "_paused", False)
            msg = (
                f"<b>📊 봇 상태</b>\n"
                f"DRY_RUN: {self._trader._cfg.mode.dry_run}\n"
                f"일시중지: {paused}\n"
                f"회로차단기: {'🔴 발동' if cb_tripped else '🟢 정상'}\n"
                f"\n"
                f"잔고: <code>${balance:,.2f}</code>\n"
                f"포지션: {len(positions)}개\n"
                f"일일 PnL: <code>{self._trader._daily_pnl:+,.2f}</code>\n"
                f"누적 PnL: <code>{self._trader._cum_pnl:+,.2f}</code>"
            )
            await self._reply(update, msg)
        except Exception as e:
            await self._reply(update, f"❌ 조회 실패: {e}")

    async def _cmd_balance(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        try:
            b = self._trader._client.get_balance()
            await self._reply(update, f"💰 잔고: <code>${b:,.2f} USDC</code>")
        except Exception as e:
            await self._reply(update, f"❌ 조회 실패: {e}")

    async def _cmd_positions(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        positions = self._trader._tracker.all()
        if not positions:
            await self._reply(update, "📭 열린 포지션 없음")
            return
        lines = ["<b>📈 현재 포지션</b>"]
        for p in positions:
            sign = "+" if p.unrealized_pnl >= 0 else ""
            lines.append(
                f"• {p.symbol} {p.side} | "
                f"{p.quantity:.4f} @ ${p.entry_price:.4f}\n"
                f"  PnL: <code>{sign}${p.unrealized_pnl:.2f}</code>"
            )
        await self._reply(update, "\n".join(lines))

    async def _cmd_pnl(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        await self._reply(update,
            f"<b>📊 PnL</b>\n"
            f"오늘: <code>{self._trader._daily_pnl:+,.2f}</code>\n"
            f"누적: <code>{self._trader._cum_pnl:+,.2f}</code>\n"
            f"피크 잔고: <code>${self._trader._peak_balance:,.2f}</code>"
        )

    async def _cmd_traders(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        cfgs = self._trader._cfg.traders
        lines = ["<b>👥 추종 트레이더</b>"]
        for c in cfgs:
            short = f"{c.uid[:10]}…{c.uid[-6:]}"
            lines.append(f"• <b>{c.name}</b> (가중치 {c.weight}) <code>{short}</code>")
        await self._reply(update, "\n".join(lines))

    async def _cmd_cb(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        cb = self._trader._cb
        status = "🔴 발동 중" if cb.is_tripped() else "🟢 정상"
        reason = cb.get_reason() or "-"
        await self._reply(update,
            f"<b>회로차단기</b>\n상태: {status}\n사유: {reason}"
        )

    async def _cmd_cb_reset(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        self._trader._cb.manual_reset()
        await self._reply(update, "✅ 회로차단기 수동 해제됨")

    async def _cmd_pause(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        self._trader._paused = True
        await self._reply(update, "⏸ 신규 진입 일시중지됨 (모니터링은 계속)")

    async def _cmd_resume(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        self._trader._paused = False
        await self._reply(update, "▶️ 진입 재개됨")

    async def _cmd_close(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        args = ctx.args
        if len(args) < 2:
            await self._reply(update, "사용법: <code>/close BTCUSDT LONG</code>")
            return
        symbol = args[0].upper()
        side = args[1].upper()
        pos = self._trader._tracker.get(symbol, side)
        if pos is None:
            await self._reply(update, f"❌ 포지션 없음: {symbol} {side}")
            return
        try:
            self._trader._order_mgr.close_position(pos, "수동 청산")
            await self._reply(update, f"✅ 청산 요청 보냄: {symbol} {side}")
        except Exception as e:
            await self._reply(update, f"❌ 청산 실패: {e}")

    async def _cmd_closeall(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        positions = self._trader._tracker.all()
        if not positions:
            await self._reply(update, "📭 청산할 포지션 없음")
            return
        try:
            self._trader._order_mgr.close_all("수동 일괄 청산")
            await self._reply(update, f"✅ {len(positions)}개 포지션 청산 요청")
        except Exception as e:
            await self._reply(update, f"❌ 일괄 청산 실패: {e}")

    async def _cmd_capital(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        args = ctx.args
        if not args:
            await self._reply(update,
                "사용법:\n"
                "<code>/capital 6</code> — 1회 진입 마진을 $6으로 고정\n"
                "<code>/capital auto</code> — 자동(잔고 비율) 모드로 복원"
            )
            return
        arg = args[0].lower()
        if arg in ("auto", "off", "reset", "none"):
            self._trader._sizer.set_fixed_capital(None)
            await self._reply(update, "✅ 자본 모드: <b>AUTO</b> (잔고 비율)\n다음 진입부터 적용")
            return
        try:
            amount = float(arg)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await self._reply(update, "❌ 금액은 양수여야 합니다.")
            return
        self._trader._sizer.set_fixed_capital(amount)
        await self._reply(update,
            f"✅ 자본 모드: <b>FIXED</b> ${amount:.2f}\n"
            f"레버리지 {self._trader._cfg.position.leverage}x → notional ${amount * self._trader._cfg.position.leverage:.2f}\n"
            f"<i>현재 진행중인 포지션은 영향 없음. 다음 진입부터 적용.</i>"
        )

    async def _cmd_leverage(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        args = ctx.args
        if not args:
            cur = self._trader._cfg.position.leverage
            await self._reply(update,
                f"현재 레버리지: <b>{cur}x</b>\n"
                f"변경: <code>/leverage 10</code>"
            )
            return
        try:
            new_lev = int(args[0])
            if new_lev < 1 or new_lev > 50:
                raise ValueError
        except ValueError:
            await self._reply(update, "❌ 레버리지는 1~50 정수입니다.")
            return
        old = self._trader._cfg.position.leverage
        self._trader._cfg.position.leverage = new_lev
        await self._reply(update,
            f"✅ 레버리지: {old}x → <b>{new_lev}x</b>\n"
            f"<i>다음 진입부터 적용. 현재 포지션은 영향 없음.</i>"
        )

    async def _cmd_sizing(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        sizer = self._trader._sizer
        cfg = self._trader._cfg.position
        try:
            balance = self._trader._client.get_balance()
        except Exception:
            balance = 0.0
        await self._reply(update,
            f"<b>📐 사이징 설정</b>\n"
            f"자본 모드: <b>{sizer.get_capital_mode()}</b>\n"
            f"레버리지: <b>{cfg.leverage}x</b>\n"
            f"동시 포지션: 최대 {cfg.max_concurrent}개\n"
            f"마진 타입: {cfg.margin_type}\n"
            f"\n"
            f"현재 잔고: <code>${balance:,.2f}</code>"
        )

    async def _cmd_listtraders(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        traders = self._trader._pool.list_traders()
        if not traders:
            await self._reply(update, "📭 추종 트레이더 없음. /addtrader 로 추가하세요.")
            return
        lines = [f"<b>👥 추종 트레이더 ({len(traders)}명)</b>"]
        for c in traders:
            lines.append(f"• <b>{c.name}</b> <code>{c.uid}</code>")
        await self._reply(update, "\n".join(lines))

    async def _cmd_addtrader(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        args = ctx.args
        if len(args) < 2:
            await self._reply(update,
                "사용법: <code>/addtrader 0x주소 이름</code>\n"
                "예: <code>/addtrader 0x34827044cbd4b808fc1b189fce9f50e6dafae7c9 TraderA</code>"
            )
            return
        addr = args[0]
        name = " ".join(args[1:])
        if not addr.startswith("0x") or len(addr) != 42:
            await self._reply(update, "❌ 유효하지 않은 주소 형식 (0x로 시작, 42자)")
            return
        added = self._trader._pool.add_trader(addr, name)
        if not added:
            await self._reply(update, f"⚠️ 이미 추종 중: <code>{addr}</code>")
            return
        await self._reply(update,
            f"✅ 트레이더 추가됨\n"
            f"이름: <b>{name}</b>\n주소: <code>{addr}</code>\n"
            f"\n현재 {self._trader._pool.trader_count}명 추종 중"
        )

    async def _cmd_removetrader(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        args = ctx.args
        if not args:
            await self._reply(update, "사용법: <code>/removetrader 0x주소</code>")
            return
        addr = args[0]
        removed = self._trader._pool.remove_trader(addr)
        if not removed:
            await self._reply(update, f"❌ 추종 목록에 없음: <code>{addr}</code>")
            return
        await self._reply(update,
            f"✅ 제거됨: <code>{addr}</code>\n"
            f"현재 {self._trader._pool.trader_count}명 추종 중"
        )

    async def _cmd_findtraders(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        import requests
        from collections import Counter
        from data_sources.hl_lb import HlLeaderboard

        args = ctx.args
        try:
            top_n = int(args[0]) if args else 5
        except ValueError:
            top_n = 5
        top_n = max(1, min(10, top_n))

        await self._reply(update,
            f"🔍 메이저 크립토(BTC/ETH/SOL 등) 단타러 Top {top_n} 검색 중...\n"
            f"(상위 후보들의 실제 거래 분석 — 1분 정도 걸림)"
        )

        try:
            lb = HlLeaderboard()
            rows = lb.fetch()
            cands = lb.filter_candidates(
                rows, min_account_value=10_000,
                min_month_roi=0.20, min_month_volume=100_000,
            )
            def turnover(r):
                acct = float(r.get("accountValue", 1) or 1)
                vlm = next(
                    (float(p[1].get("vlm", 0)) for p in r["windowPerformances"] if p[0] == "month"),
                    0,
                )
                return vlm / max(acct, 1)
            cands.sort(key=turnover, reverse=True)
        except Exception as e:
            await self._reply(update, f"❌ 리더보드 조회 실패: {e}")
            return

        # 상위 후보 30명에서 메이저 비중 ≥50% 필터
        majors = {"BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "XRP", "ADA",
                  "ARB", "OP", "SUI", "APT", "INJ", "TIA"}
        good: list[tuple] = []
        for r in cands[:30]:
            addr = r["ethAddress"]
            try:
                resp = requests.post(
                    "https://api.hyperliquid.xyz/info",
                    json={"type": "userFills", "user": addr},
                    timeout=8,
                )
                fills = resp.json()[:100]
            except Exception:
                continue
            if not fills:
                continue
            cnt = Counter(f.get("coin", "") for f in fills)
            major_pct = sum(c for k, c in cnt.items() if k in majors) / len(fills)
            if major_pct >= 0.5:
                top_coins = ", ".join(f"{k}({v})" for k, v in cnt.most_common(3))
                good.append((r, major_pct, top_coins))
            if len(good) >= top_n:
                break

        if not good:
            await self._reply(update,
                "⚠️ 상위 후보 30명 중 메이저 크립토 ≥50% 거래자 없음.\n"
                "기준 완화 필요. 화이트리스트에 알트 추가하는 것도 방법."
            )
            return

        lines = [f"<b>🔥 메이저 크립토 단타러 Top {len(good)}</b>", ""]
        for r, mp, top_coins in good:
            addr = r["ethAddress"]
            acct = float(r.get("accountValue", 0))
            m = next((p[1] for p in r["windowPerformances"] if p[0] == "month"), {})
            d = next((p[1] for p in r["windowPerformances"] if p[0] == "day"), {})
            roi = float(m.get("roi", 0)) * 100
            vlm = float(m.get("vlm", 0))
            day_roi = float(d.get("roi", 0)) * 100
            vlm_s = f"${vlm/1e6:.1f}M" if vlm >= 1e6 else f"${vlm/1e3:.0f}K"
            lines.append(
                f"<code>{addr}</code>\n"
                f"  💰 ${acct:,.0f} | 일{day_roi:+.1f}% 월{roi:+.1f}% | 월거래 {vlm_s}\n"
                f"  메이저 비중: <b>{mp*100:.0f}%</b>\n"
                f"  주요 종목: {top_coins}"
            )
        lines.append("")
        lines.append("추가: <code>/addtrader &lt;주소&gt; &lt;이름&gt;</code>")
        await self._reply(update, "\n".join(lines))

    async def _cmd_consensus(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        cfg = self._trader._cfg.consensus
        args = ctx.args
        if not args:
            await self._reply(update,
                f"현재 합의 임계값: <b>{cfg.min_traders}명</b>\n"
                f"변경: <code>/consensus 1</code> (한 명만 진입해도 따라감)\n"
                f"     <code>/consensus 2</code> (두 명 동시 합의 필요)"
            )
            return
        try:
            n = int(args[0])
            if n < 1:
                raise ValueError
        except ValueError:
            await self._reply(update, "❌ 1 이상 정수여야 합니다.")
            return
        traders_count = self._trader._pool.trader_count
        if n > traders_count:
            await self._reply(update,
                f"⚠️ {n}명 합의 요구하지만 추종 트레이더는 {traders_count}명뿐입니다.\n"
                f"먼저 /addtrader 로 추가하세요."
            )
            return
        old = cfg.min_traders
        cfg.min_traders = n
        await self._reply(update,
            f"✅ 합의 임계값: {old}명 → <b>{n}명</b>\n"
            f"<i>다음 사이클부터 적용</i>"
        )

    async def _cmd_analyze(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        import requests
        from collections import Counter
        args = ctx.args
        if not args:
            await self._reply(update,
                "사용법: <code>/analyze 0x주소</code>\n"
                "최근 200건 거래의 종목 분포를 분석합니다."
            )
            return
        addr = args[0].lower()
        if not addr.startswith("0x") or len(addr) != 42:
            await self._reply(update, "❌ 유효하지 않은 주소")
            return
        await self._reply(update, "🔍 분석 중...")
        try:
            r = requests.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "userFills", "user": addr},
                timeout=10,
            )
            fills = r.json()[:200]
        except Exception as e:
            await self._reply(update, f"❌ 조회 실패: {e}")
            return

        if not fills:
            await self._reply(update, "📭 최근 거래 없음")
            return

        counter = Counter()
        for f in fills:
            counter[f.get("coin", "UNK")] += 1

        # 메이저 크립토 비중 계산
        majors = {"BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "XRP", "ADA"}
        major_count = sum(c for k, c in counter.items() if k in majors)
        # 토큰화 자산 (xyz: 접두사) 비중
        rwa_count = sum(c for k, c in counter.items() if k.startswith("xyz:") or k.startswith("ushares:"))
        crypto_count = len(fills) - rwa_count

        lines = [
            f"<b>📊 트레이더 분석</b>",
            f"<code>{addr}</code>",
            f"\n최근 거래: {len(fills)}건",
            f"메이저 크립토(BTC/ETH/SOL 등): <b>{major_count/len(fills)*100:.1f}%</b>",
            f"전체 크립토: {crypto_count/len(fills)*100:.1f}%",
            f"토큰화 자산(주식/원자재): {rwa_count/len(fills)*100:.1f}%",
            f"\n<b>종목별 빈도 (Top 10)</b>",
        ]
        for coin, cnt in counter.most_common(10):
            pct = cnt / len(fills) * 100
            badge = " ⭐" if coin in majors else ""
            lines.append(f"  {coin:<12} {cnt:>3}회 ({pct:.1f}%){badge}")
        await self._reply(update, "\n".join(lines))

    async def _cmd_whitelist(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        wl = self._trader._cfg.filters.symbol_whitelist
        args = ctx.args
        if not args:
            await self._reply(update,
                f"<b>📃 화이트리스트 ({len(wl)}개)</b>\n"
                f"{', '.join(f'<code>{s}</code>' for s in wl)}\n\n"
                f"추가: <code>/whitelist add BTCUSDT</code>\n"
                f"제거: <code>/whitelist remove BTCUSDT</code>\n"
                f"전체: <code>/whitelist set BTC,ETH,SOL</code> (USDT 자동 추가)\n"
                f"비우기: <code>/whitelist clear</code> (모든 종목 허용)"
            )
            return
        action = args[0].lower()
        if action == "add" and len(args) >= 2:
            sym = args[1].upper()
            if not sym.endswith("USDT"):
                sym += "USDT"
            if sym in wl:
                await self._reply(update, f"⚠️ 이미 있음: <code>{sym}</code>")
                return
            wl.append(sym)
            await self._reply(update, f"✅ 추가됨: <code>{sym}</code>\n현재 {len(wl)}개")
        elif action == "remove" and len(args) >= 2:
            sym = args[1].upper()
            if not sym.endswith("USDT"):
                sym += "USDT"
            if sym not in wl:
                await self._reply(update, f"❌ 목록에 없음: <code>{sym}</code>")
                return
            wl.remove(sym)
            await self._reply(update, f"✅ 제거됨: <code>{sym}</code>\n현재 {len(wl)}개")
        elif action == "set" and len(args) >= 2:
            symbols = " ".join(args[1:]).upper().replace(",", " ").split()
            new_wl = []
            for s in symbols:
                if not s.endswith("USDT"):
                    s += "USDT"
                if s not in new_wl:
                    new_wl.append(s)
            wl.clear()
            wl.extend(new_wl)
            await self._reply(update, f"✅ 화이트리스트 재설정 ({len(wl)}개):\n{', '.join(wl)}")
        elif action == "clear":
            wl.clear()
            await self._reply(update,
                "✅ 화이트리스트 비움 — <b>모든 종목 허용</b>\n"
                "<i>주의: 알트/토큰화 자산도 진입 가능</i>"
            )
        else:
            await self._reply(update, "❌ 사용법: /whitelist [add|remove|set|clear] [심볼]")

    async def _cmd_unknown(self, update: Update, ctx) -> None:
        if not self._is_authorized(update):
            return
        if not update.message or not update.message.text:
            return
        if update.message.text.startswith("/"):
            await self._reply(update, "❓ 알 수 없는 명령어. /help 참조.")
