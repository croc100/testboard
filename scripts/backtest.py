#!/usr/bin/env python3
"""
백테스트 러너 — 저장된 랭커 포지션 스냅샷으로 전략 시뮬레이션

사용법:
  python scripts/backtest.py --data data/snapshots.jsonl --capital 1000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import load_config
from core.models import TradeSignal, TraderPosition

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_balance: float = 0.0
    trade_log: list[dict] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    def print_summary(self) -> None:
        print("\n" + "=" * 50)
        print("📊 백테스트 결과")
        print("=" * 50)
        print(f"총 거래: {self.total_trades}회")
        print(f"승/패: {self.wins}/{self.losses} ({self.win_rate:.1%})")
        print(f"총 PNL: {'+' if self.total_pnl >= 0 else ''}${self.total_pnl:.2f}")
        print(f"최대 드로우다운: {self.max_drawdown:.2%}")
        print("=" * 50)


class BacktestEngine:
    def __init__(self, config_path: str = "config.yaml") -> None:
        self._cfg = load_config(config_path)

    def run(self, snapshots: list[dict], initial_capital: float = 1000.0) -> BacktestResult:
        result = BacktestResult(peak_balance=initial_capital)
        balance = initial_capital
        open_positions: dict[str, dict] = {}

        for snap in sorted(snapshots, key=lambda x: x.get("ts", 0)):
            ts = snap.get("ts", 0)
            positions_raw = snap.get("positions", [])

            # 랭커 포지션 → 합의 감지
            grouped: dict[str, list[dict]] = {}
            for p in positions_raw:
                key = f"{p['symbol']}_{p['side']}"
                grouped.setdefault(key, []).append(p)

            for key, group in grouped.items():
                if len(group) < self._cfg.consensus.min_traders:
                    continue
                symbol, side = key.rsplit("_", 1)
                entry_price = sum(p["entryPrice"] for p in group) / len(group)

                # 신규 진입
                if key not in open_positions:
                    sl_pct = self._cfg.exits.hard_stop_loss_pct
                    sl_price = (
                        entry_price * (1 - sl_pct) if side == "LONG"
                        else entry_price * (1 + sl_pct)
                    )
                    size_usdt = balance * self._cfg.position.base_capital_pct
                    qty = size_usdt * self._cfg.position.leverage / entry_price
                    open_positions[key] = {
                        "symbol": symbol, "side": side,
                        "entry": entry_price, "qty": qty,
                        "sl": sl_price, "ts": ts,
                    }
                    logger.debug("시뮬 진입: %s @ %.4f", key, entry_price)

            # 청산 체크 — 랭커가 포지션을 닫으면 청산
            active_keys = {f"{p['symbol']}_{p['side']}" for p in positions_raw}
            for key in list(open_positions.keys()):
                if key in active_keys:
                    continue
                pos = open_positions.pop(key)
                # 종가를 현재 스냅샷에서 추정
                current_price = pos["entry"]  # 실제론 mark price 사용해야 함
                for p in positions_raw:
                    if p["symbol"] == pos["symbol"]:
                        current_price = p.get("markPrice", pos["entry"])
                        break

                if pos["side"] == "LONG":
                    pnl = (current_price - pos["entry"]) * pos["qty"]
                else:
                    pnl = (pos["entry"] - current_price) * pos["qty"]

                balance += pnl
                result.total_trades += 1
                if pnl > 0:
                    result.wins += 1
                else:
                    result.losses += 1
                result.total_pnl += pnl
                result.peak_balance = max(result.peak_balance, balance)
                dd = (balance - result.peak_balance) / result.peak_balance
                result.max_drawdown = min(result.max_drawdown, dd)
                result.trade_log.append({
                    "key": key, "pnl": round(pnl, 4),
                    "balance": round(balance, 2),
                })
                logger.debug("시뮬 청산: %s PNL=%.4f", key, pnl)

        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Ebenezer 백테스트")
    parser.add_argument("--data", required=True, help="스냅샷 JSONL 파일 경로")
    parser.add_argument("--capital", type=float, default=1000.0, help="초기 자본 (USDT)")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"❌ 데이터 파일 없음: {data_path}")
        sys.exit(1)

    snapshots = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if line:
                snapshots.append(json.loads(line))

    print(f"📂 스냅샷 {len(snapshots)}개 로드 완료")
    engine = BacktestEngine(args.config)
    result = engine.run(snapshots, initial_capital=args.capital)
    result.print_summary()

    if result.total_pnl <= 0:
        print("\n⚠️  경고: 양의 기댓값 미확인 — 실거래 진행 금지 (사양서 §8.3)")
    else:
        print("\n✅ 양의 기댓값 확인됨")


if __name__ == "__main__":
    main()
