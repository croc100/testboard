use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};
use std::fs;
use std::env;
use crate::core::error::ConfigError;

pub const HARD_MAX_DAILY_LOSS_PCT: f64 = 0.05;
pub const HARD_MAX_LEVERAGE: i32 = 50;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraderConfig {
    pub uid: String,
    pub name: String,
    #[serde(default = "default_weight")]
    pub weight: f64,
}

fn default_weight() -> f64 { 1.0 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsensusConfig {
    #[serde(default = "default_min_traders")]
    pub min_traders: i32,
    #[serde(default = "default_max_entry_lag_minutes")]
    pub max_entry_lag_minutes: i32,
    #[serde(default = "default_min_confidence")]
    pub min_confidence: f64,
}

fn default_min_traders() -> i32 { 2 }
fn default_max_entry_lag_minutes() -> i32 { 30 }
fn default_min_confidence() -> f64 { 0.4 }

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PositionMode {
    Ratio,
    Fixed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MarginType {
    Isolated,
    Cross,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionConfig {
    #[serde(default = "default_position_mode")]
    pub mode: PositionMode,
    #[serde(default = "default_base_capital_pct")]
    pub base_capital_pct: f64,
    #[serde(default = "default_max_position_capital_pct")]
    pub max_position_capital_pct: f64,
    #[serde(default = "default_max_concurrent")]
    pub max_concurrent: i32,
    #[serde(default = "default_leverage")]
    pub leverage: i32,
    #[serde(default = "default_margin_type")]
    pub margin_type: MarginType,
}

fn default_position_mode() -> PositionMode { PositionMode::Ratio }
fn default_base_capital_pct() -> f64 { 0.05 }
fn default_max_position_capital_pct() -> f64 { 0.10 }
fn default_max_concurrent() -> i32 { 3 }
fn default_leverage() -> i32 { 5 }
fn default_margin_type() -> MarginType { MarginType::Isolated }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PartialTpLevel {
    pub pct: f64,
    pub close_ratio: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExitsConfig {
    #[serde(default = "default_hard_stop_loss_pct")]
    pub hard_stop_loss_pct: f64,
    #[serde(default = "default_trailing_activation_pct")]
    pub trailing_activation_pct: f64,
    #[serde(default = "default_trailing_distance_pct")]
    pub trailing_distance_pct: f64,
    #[serde(default = "default_time_stop_hours")]
    pub time_stop_hours: i32,
    #[serde(default)]
    pub partial_tp_levels: Vec<PartialTpLevel>,
}

fn default_hard_stop_loss_pct() -> f64 { 0.02 }
fn default_trailing_activation_pct() -> f64 { 0.03 }
fn default_trailing_distance_pct() -> f64 { 0.015 }
fn default_time_stop_hours() -> i32 { 4 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskConfig {
    #[serde(default = "default_max_daily_loss_pct")]
    pub max_daily_loss_pct: f64,
    #[serde(default = "default_max_drawdown_pct")]
    pub max_drawdown_pct: f64,
    #[serde(default = "default_max_consecutive_losses")]
    pub max_consecutive_losses: i32,
    #[serde(default = "default_consecutive_loss_size_reduction")]
    pub consecutive_loss_size_reduction: f64,
}

fn default_max_daily_loss_pct() -> f64 { 0.03 }
fn default_max_drawdown_pct() -> f64 { 0.10 }
fn default_max_consecutive_losses() -> i32 { 3 }
fn default_consecutive_loss_size_reduction() -> f64 { 0.5 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BlackoutPeriod {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    #[serde(default)]
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FiltersConfig {
    #[serde(default = "default_symbol_whitelist")]
    pub symbol_whitelist: Vec<String>,
    #[serde(default)]
    pub symbol_blacklist: Vec<String>,
    #[serde(default = "default_max_atr_multiplier")]
    pub max_atr_multiplier: f64,
    #[serde(default = "default_max_funding_rate")]
    pub max_funding_rate: f64,
    #[serde(default = "default_max_signal_age_minutes")]
    pub max_signal_age_minutes: i32,
    #[serde(default)]
    pub blackout_periods: Vec<BlackoutPeriod>,
}

fn default_symbol_whitelist() -> Vec<String> {
    vec!["BTCUSDT".to_string(), "ETHUSDT".to_string(), "SOLUSDT".to_string(), "BNBUSDT".to_string()]
}
fn default_max_atr_multiplier() -> f64 { 2.0 }
fn default_max_funding_rate() -> f64 { 0.0005 }
fn default_max_signal_age_minutes() -> i32 { 3 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OpsConfig {
    #[serde(default = "default_poll_interval_sec")]
    pub poll_interval_sec: u64,
    #[serde(default)]
    pub telegram_bot_token: String,
    #[serde(default)]
    pub telegram_chat_id: String,
    #[serde(default = "default_log_level")]
    pub log_level: String,
    #[serde(default = "default_log_file")]
    pub log_file: String,
    #[serde(default = "default_db_path")]
    pub db_path: String,
}

fn default_poll_interval_sec() -> u64 { 20 }
fn default_log_level() -> String { "INFO".to_string() }
fn default_log_file() -> String { "/var/log/copytrader/bot.log".to_string() }
fn default_db_path() -> String { "/var/lib/copytrader/state.db".to_string() }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModeConfig {
    #[serde(default = "default_dry_run")]
    pub dry_run: bool,
    #[serde(default)]
    pub paper_trading: bool,
}

fn default_dry_run() -> bool { true }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExchangeConfig {
    #[serde(default = "default_api_url")]
    pub api_url: String,
}

fn default_api_url() -> String { "https://api.hyperliquid.xyz".to_string() }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    #[serde(default)]
    pub exchange: ExchangeConfig,
    #[serde(default)]
    pub traders: Vec<TraderConfig>,
    #[serde(default)]
    pub consensus: ConsensusConfig,
    #[serde(default)]
    pub position: PositionConfig,
    #[serde(default)]
    pub exits: ExitsConfig,
    #[serde(default)]
    pub risk: RiskConfig,
    #[serde(default)]
    pub filters: FiltersConfig,
    #[serde(default)]
    pub ops: OpsConfig,
    #[serde(default)]
    pub mode: ModeConfig,

    #[serde(skip)]
    pub user_address: String,
    #[serde(skip)]
    pub signer_private_key: String,
}

impl Default for ExchangeConfig {
    fn default() -> Self { Self { api_url: default_api_url() } }
}

impl Default for ConsensusConfig {
    fn default() -> Self {
        Self {
            min_traders: default_min_traders(),
            max_entry_lag_minutes: default_max_entry_lag_minutes(),
            min_confidence: default_min_confidence(),
        }
    }
}

impl Default for PositionConfig {
    fn default() -> Self {
        Self {
            mode: default_position_mode(),
            base_capital_pct: default_base_capital_pct(),
            max_position_capital_pct: default_max_position_capital_pct(),
            max_concurrent: default_max_concurrent(),
            leverage: default_leverage(),
            margin_type: default_margin_type(),
        }
    }
}

impl Default for ExitsConfig {
    fn default() -> Self {
        Self {
            hard_stop_loss_pct: default_hard_stop_loss_pct(),
            trailing_activation_pct: default_trailing_activation_pct(),
            trailing_distance_pct: default_trailing_distance_pct(),
            time_stop_hours: default_time_stop_hours(),
            partial_tp_levels: Vec::new(),
        }
    }
}

impl Default for RiskConfig {
    fn default() -> Self {
        Self {
            max_daily_loss_pct: default_max_daily_loss_pct(),
            max_drawdown_pct: default_max_drawdown_pct(),
            max_consecutive_losses: default_max_consecutive_losses(),
            consecutive_loss_size_reduction: default_consecutive_loss_size_reduction(),
        }
    }
}

impl Default for FiltersConfig {
    fn default() -> Self {
        Self {
            symbol_whitelist: default_symbol_whitelist(),
            symbol_blacklist: Vec::new(),
            max_atr_multiplier: default_max_atr_multiplier(),
            max_funding_rate: default_max_funding_rate(),
            max_signal_age_minutes: default_max_signal_age_minutes(),
            blackout_periods: Vec::new(),
        }
    }
}

impl Default for OpsConfig {
    fn default() -> Self {
        Self {
            poll_interval_sec: default_poll_interval_sec(),
            telegram_bot_token: String::new(),
            telegram_chat_id: String::new(),
            log_level: default_log_level(),
            log_file: default_log_file(),
            db_path: default_db_path(),
        }
    }
}

impl Default for ModeConfig {
    fn default() -> Self {
        Self {
            dry_run: default_dry_run(),
            paper_trading: false,
        }
    }
}

impl AppConfig {
    pub fn load(path: &str) -> Result<Self, ConfigError> {
        let content = fs::read_to_string(path).map_err(|e| ConfigError::Io(e))?;
        let mut config: AppConfig = serde_yaml::from_str(&content).map_err(|e| ConfigError::Yaml(e))?;

        config.user_address = env::var("HL_USER_ADDRESS").unwrap_or_default();
        config.signer_private_key = env::var("HL_PRIVATE_KEY").unwrap_or_default();
        
        config.ops.telegram_bot_token = env::var("TELEGRAM_TOKEN").unwrap_or(config.ops.telegram_bot_token);
        config.ops.telegram_chat_id = env::var("TELEGRAM_CHAT_ID").unwrap_or(config.ops.telegram_chat_id);

        config.validate()?;

        Ok(config)
    }

    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.position.leverage > HARD_MAX_LEVERAGE {
            return Err(ConfigError::Validation(format!(
                "Leverage {} exceeds hard limit {}",
                self.position.leverage, HARD_MAX_LEVERAGE
            )));
        }
        if self.risk.max_daily_loss_pct > HARD_MAX_DAILY_LOSS_PCT {
            return Err(ConfigError::Validation(format!(
                "Max daily loss {} exceeds hard limit {}",
                self.risk.max_daily_loss_pct, HARD_MAX_DAILY_LOSS_PCT
            )));
        }
        Ok(())
    }
}
