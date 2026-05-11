"""core/config.py 단위 테스트 — 하드 제한 검증"""
import pytest
from pydantic import ValidationError

from core.config import PositionConfig, RiskConfig


class TestPositionConfig:
    def test_leverage_hard_limit(self):
        with pytest.raises(ValidationError, match="하드 제한"):
            PositionConfig(leverage=51)

    def test_leverage_at_limit(self):
        cfg = PositionConfig(leverage=50)
        assert cfg.leverage == 50

    def test_leverage_normal(self):
        cfg = PositionConfig(leverage=5)
        assert cfg.leverage == 5


class TestRiskConfig:
    def test_daily_loss_hard_limit(self):
        with pytest.raises(ValidationError, match="하드 상한"):
            RiskConfig(max_daily_loss_pct=0.06)

    def test_daily_loss_at_limit(self):
        cfg = RiskConfig(max_daily_loss_pct=0.05)
        assert cfg.max_daily_loss_pct == pytest.approx(0.05)

    def test_daily_loss_stricter(self):
        cfg = RiskConfig(max_daily_loss_pct=0.01)
        assert cfg.max_daily_loss_pct == pytest.approx(0.01)
