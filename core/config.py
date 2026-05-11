from __future__ import annotations

import os
from datetime import datetime
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator

from core.exceptions import ConfigError

# ── 하드 제한 (config으로 우회 불가) ──────────────────────────────────────────
_HARD_MAX_DAILY_LOSS_PCT = 0.05     # 하루 최대 -5%
_HARD_MAX_LEVERAGE = 50             # 레버리지 50배 초과 거부


class TraderConfig(BaseModel):
    uid: str
    name: str
    weight: float = 1.0


class ConsensusConfig(BaseModel):
    min_traders: int = 2
    max_entry_lag_minutes: int = 30
    min_confidence: float = 0.4


class PositionConfig(BaseModel):
    mode: Literal["RATIO", "FIXED"] = "RATIO"
    base_capital_pct: float = 0.05
    max_position_capital_pct: float = 0.10
    max_concurrent: int = 3
    leverage: int = 5
    margin_type: Literal["ISOLATED", "CROSS"] = "ISOLATED"

    @field_validator("leverage")
    @classmethod
    def validate_leverage(cls, v: int) -> int:
        if v > _HARD_MAX_LEVERAGE:
            raise ValueError(f"레버리지 {v}배는 하드 제한({_HARD_MAX_LEVERAGE}배)을 초과합니다.")
        return v


class PartialTpLevel(BaseModel):
    pct: float
    close_ratio: float


class ExitsConfig(BaseModel):
    hard_stop_loss_pct: float = 0.02
    trailing_activation_pct: float = 0.03
    trailing_distance_pct: float = 0.015
    time_stop_hours: int = 4
    partial_tp_levels: list[PartialTpLevel] = []


class RiskConfig(BaseModel):
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10
    max_consecutive_losses: int = 3
    consecutive_loss_size_reduction: float = 0.5

    @field_validator("max_daily_loss_pct")
    @classmethod
    def validate_daily_loss(cls, v: float) -> float:
        if v > _HARD_MAX_DAILY_LOSS_PCT:
            raise ValueError(
                f"max_daily_loss_pct={v}는 하드 상한({_HARD_MAX_DAILY_LOSS_PCT})을 초과합니다. "
                "설정을 더 빡빡하게는 가능, 더 느슨하게는 불가."
            )
        return v


class BlackoutPeriod(BaseModel):
    start: datetime
    end: datetime
    reason: str = ""


class FiltersConfig(BaseModel):
    symbol_whitelist: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    symbol_blacklist: list[str] = []
    max_atr_multiplier: float = 2.0
    max_funding_rate: float = 0.0005
    max_signal_age_minutes: int = 3
    blackout_periods: list[BlackoutPeriod] = []


class OpsConfig(BaseModel):
    poll_interval_sec: int = 20
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    log_level: str = "INFO"
    log_file: str = "/var/log/copytrader/bot.log"
    db_path: str = "/var/lib/copytrader/state.db"


class ModeConfig(BaseModel):
    dry_run: bool = True
    paper_trading: bool = False


class ExchangeConfig(BaseModel):
    api_url: str = "https://api.hyperliquid.xyz"   # Hyperliquid


class AppConfig(BaseModel):
    exchange: ExchangeConfig = ExchangeConfig()
    traders: list[TraderConfig] = []
    consensus: ConsensusConfig = ConsensusConfig()
    position: PositionConfig = PositionConfig()
    exits: ExitsConfig = ExitsConfig()
    risk: RiskConfig = RiskConfig()
    filters: FiltersConfig = FiltersConfig()
    ops: OpsConfig = OpsConfig()
    mode: ModeConfig = ModeConfig()

    # 지갑 인증 — 환경변수에서만 로드 (yaml에 절대 기재 금지)
    user_address: str = ""       # 지갑 주소 (0x...)
    signer_private_key: str = "" # 지갑 개인 키

    @model_validator(mode="after")
    def load_credentials(self) -> "AppConfig":
        self.user_address = os.environ.get("HL_USER_ADDRESS", "")
        self.signer_private_key = os.environ.get("HL_PRIVATE_KEY", "")
        # 텔레그램 토큰도 env 치환
        self.ops.telegram_bot_token = os.environ.get(
            "TELEGRAM_TOKEN", self.ops.telegram_bot_token
        )
        self.ops.telegram_chat_id = os.environ.get(
            "TELEGRAM_CHAT_ID", self.ops.telegram_chat_id
        )
        return self


def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    return AppConfig.model_validate(raw or {})
