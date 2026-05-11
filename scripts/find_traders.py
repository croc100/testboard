#!/usr/bin/env python3
"""
Hyperliquid 리더보드에서 후보 트레이더 발굴 도구.

사용법:
    python scripts/find_traders.py [--top N] [--min-roi 0.2] [--min-vol 100000]

기준:
- 월 ROI ≥ min-roi
- 월 거래량 ≥ min-vol  (활성 단타 = 거래량 큼)
- 계좌가치 ≥ 10,000 USDT
- 일/주/월 일관된 수익 (이상치 1회 대박 제외)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_sources.hl_lb import HlLeaderboard


def _format(value: str, kind: str = "usd") -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    if kind == "pct":
        return f"{v*100:+.1f}%"
    if kind == "usd":
        if abs(v) >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        if abs(v) >= 1_000:
            return f"${v/1_000:.1f}K"
        return f"${v:,.0f}"
    return str(value)


def _perf(row: dict, window: str) -> dict:
    for p in row.get("windowPerformances", []):
        if p[0] == window:
            return p[1] or {}
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="HL 리더보드 후보 발굴")
    parser.add_argument("--top", type=int, default=20, help="상위 N명 출력")
    parser.add_argument("--min-account", type=float, default=10_000)
    parser.add_argument("--min-roi", type=float, default=0.20, help="월 ROI 하한")
    parser.add_argument("--min-vol", type=float, default=100_000, help="월 거래량 하한")
    parser.add_argument("--max-dd", type=float, default=0.30, help="월 ROI 하한선(드로우다운 방지)")
    parser.add_argument("--day-trader", action="store_true", help="단타 위주(거래량/계좌비 큰 순)")
    args = parser.parse_args()

    lb = HlLeaderboard()
    print("리더보드 다운로드 중...")
    rows = lb.fetch()
    print(f"전체 트레이더: {len(rows):,}명")

    candidates = lb.filter_candidates(
        rows,
        min_account_value=args.min_account,
        min_month_roi=args.min_roi,
        min_month_volume=args.min_vol,
        max_month_drawdown=args.max_dd,
    )
    print(f"기준 통과: {len(candidates):,}명")

    if args.day_trader:
        # 거래량 / 계좌가치 비율이 높을수록 단타 (자본 회전율↑)
        def turnover(r):
            try:
                acct = float(r.get("accountValue", 1))
                vlm = float(_perf(r, "month").get("vlm", 0))
                return vlm / max(acct, 1)
            except Exception:
                return 0
        candidates.sort(key=turnover, reverse=True)
        print("(단타 정렬: 월거래량/계좌가치)\n")

    print()
    print(f"{'주소':<44} {'잔고':>10} {'일ROI':>8} {'주ROI':>8} {'월ROI':>8} {'월거래량':>10}")
    print("-" * 96)
    for row in candidates[:args.top]:
        addr = row["ethAddress"]
        acct = _format(row["accountValue"])
        d = _perf(row, "day")
        w = _perf(row, "week")
        m = _perf(row, "month")
        print(
            f"{addr:<44} "
            f"{acct:>10} "
            f"{_format(d.get('roi', 0), 'pct'):>8} "
            f"{_format(w.get('roi', 0), 'pct'):>8} "
            f"{_format(m.get('roi', 0), 'pct'):>8} "
            f"{_format(m.get('vlm', 0)):>10}"
        )

    print()
    print(f"※ 추종할 주소를 config.yaml의 traders[].uid 에 입력하세요.")


if __name__ == "__main__":
    main()
