#!/usr/bin/env python3
"""
트레이더 성과 분석 도구 — 추종 후보 평가

사용법:
  python scripts/analyze_traders.py --uids UID1,UID2 --hours 24
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_sources.binance_lb import BinanceLeaderboardScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class TraderStats:
    uid: str
    positions_seen: int = 0
    avg_leverage: float = 0.0
    avg_roe: float = 0.0
    symbols: set = None

    def __post_init__(self):
        if self.symbols is None:
            self.symbols = set()

    def print_report(self) -> None:
        print(f"\n트레이더: {self.uid[:16]}...")
        print(f"  관찰 포지션: {self.positions_seen}개")
        print(f"  평균 레버리지: {self.avg_leverage:.1f}x")
        print(f"  평균 ROE: {self.avg_roe:.2%}")
        print(f"  거래 심볼: {', '.join(sorted(self.symbols))}")


def analyze(uids: list[str], poll_count: int = 6, interval_sec: int = 20) -> None:
    stats: dict[str, TraderStats] = {uid: TraderStats(uid=uid) for uid in uids}
    scrapers = {uid: BinanceLeaderboardScraper(uid) for uid in uids}

    print(f"🔍 {len(uids)}명 트레이더 분석 시작 ({poll_count}회 × {interval_sec}초)")
    for i in range(poll_count):
        print(f"\n폴 {i+1}/{poll_count}...")
        for uid, scraper in scrapers.items():
            try:
                positions = scraper.fetch_positions()
                s = stats[uid]
                leverages = [p.leverage for p in positions]
                roes = [p.roe for p in positions]
                s.positions_seen += len(positions)
                if leverages:
                    s.avg_leverage = (s.avg_leverage + sum(leverages) / len(leverages)) / 2
                if roes:
                    s.avg_roe = (s.avg_roe + sum(roes) / len(roes)) / 2
                for p in positions:
                    s.symbols.add(p.symbol)
                print(f"  {uid[:12]}...: {len(positions)}개 포지션")
            except Exception as e:
                print(f"  {uid[:12]}...: 오류 — {e}")

        if i < poll_count - 1:
            time.sleep(interval_sec)

    print("\n" + "=" * 60)
    print("📊 트레이더 분석 결과")
    print("=" * 60)
    for s in stats.values():
        s.print_report()

    # 추천
    print("\n💡 추천 (레버리지 ≤ 10, ROE > 0):")
    for s in stats.values():
        if s.avg_leverage <= 10 and s.avg_roe > 0:
            print(f"  ✅ {s.uid}")
        else:
            reason = []
            if s.avg_leverage > 10:
                reason.append(f"레버리지 {s.avg_leverage:.1f}x")
            if s.avg_roe <= 0:
                reason.append(f"ROE {s.avg_roe:.2%}")
            print(f"  ❌ {s.uid[:16]}... ({', '.join(reason)})")


def main() -> None:
    parser = argparse.ArgumentParser(description="트레이더 성과 분석")
    parser.add_argument("--uids", required=True, help="트레이더 UID 콤마 구분")
    parser.add_argument("--polls", type=int, default=6, help="폴링 횟수")
    parser.add_argument("--interval", type=int, default=20, help="폴링 간격(초)")
    args = parser.parse_args()

    uids = [u.strip() for u in args.uids.split(",") if u.strip()]
    if not uids:
        print("❌ UID를 입력하세요.")
        sys.exit(1)

    analyze(uids, poll_count=args.polls, interval_sec=args.interval)


if __name__ == "__main__":
    main()
