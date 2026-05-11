use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Side {
    LONG,
    SHORT,
}

impl std::fmt::Display for Side {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Side::LONG => write!(f, "LONG"),
            Side::SHORT => write!(f, "SHORT"),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraderPosition {
    pub trader_uid: String,
    pub symbol: String,
    pub side: Side,
    pub entry_price: f64,
    pub mark_price: f64,
    pub amount: f64,
    pub leverage: i32,
    pub pnl: f64,
    pub roe: f64,
    pub update_time: i64,
}

impl TraderPosition {
    pub fn position_key(&self) -> String {
        format!("{}_{}", self.symbol, self.side)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradeSignal {
    pub symbol: String,
    pub side: Side,
    pub confidence: f64,
    pub supporting_traders: Vec<String>,
    pub avg_entry_price: f64,
    pub suggested_size_usdt: f64,
    pub stop_loss_pct: f64,
    pub take_profit_pct: f64,
    pub created_at: DateTime<Utc>,
}

impl Default for TradeSignal {
    fn default() -> Self {
        Self {
            symbol: String::new(),
            side: Side::LONG,
            confidence: 0.0,
            supporting_traders: Vec::new(),
            avg_entry_price: 0.0,
            suggested_size_usdt: 0.0,
            stop_loss_pct: 0.0,
            take_profit_pct: 0.0,
            created_at: Utc::now(),
        }
    }
}

impl TradeSignal {
    pub fn position_key(&self) -> String {
        format!("{}_{}", self.symbol, self.side)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MyPosition {
    pub symbol: String,
    pub side: String,
    pub entry_price: f64,
    pub quantity: f64,
    pub leverage: i32,
    pub unrealized_pnl: f64,
    pub opened_at: DateTime<Utc>,
    pub source_signal: TradeSignal,
    pub sl_order_id: Option<String>,
    pub tp_order_id: Option<String>,
    pub high_water_mark: f64,
}

impl MyPosition {
    pub fn position_key(&self) -> String {
        format!("{}_{}", self.symbol, self.side)
    }

    pub fn notional_value(&self) -> f64 {
        self.entry_price * self.quantity
    }

    pub fn pnl_pct(&self) -> f64 {
        if self.entry_price == 0.0 {
            return 0.0;
        }
        self.unrealized_pnl / (self.entry_price * self.quantity / self.leverage as f64)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AccountState {
    pub balance_usdt: f64,
    pub open_positions: Vec<MyPosition>,
    pub daily_realized_pnl: f64,
    pub cumulative_pnl: f64,
    pub peak_balance: f64,
}

impl AccountState {
    pub fn daily_loss_pct(&self) -> f64 {
        if self.balance_usdt == 0.0 {
            return 0.0;
        }
        self.daily_realized_pnl / self.balance_usdt
    }

    pub fn total_drawdown_pct(&self) -> f64 {
        if self.peak_balance == 0.0 {
            return 0.0;
        }
        (self.balance_usdt - self.peak_balance) / self.peak_balance
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderResult {
    pub order_id: String,
    pub symbol: String,
    pub side: String,
    pub order_type: String,
    pub quantity: f64,
    pub price: Option<f64>,
    pub status: String,
    pub created_at: DateTime<Utc>,
}
