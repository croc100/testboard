use std::sync::{Arc, RwLock};
use tracing::{info, warn, debug};
use crate::core::config::PositionConfig;
use crate::core::models::{AccountState, TradeSignal};
use crate::data_sources::market_data::MarketData;

pub struct PositionSizer {
    config: PositionConfig,
    market_data: Arc<MarketData>,
    consecutive_losses: RwLock<i32>,
    fixed_capital: RwLock<Option<f64>>,
}

impl PositionSizer {
    pub fn new(config: PositionConfig, market_data: Arc<MarketData>) -> Self {
        Self {
            config,
            market_data,
            consecutive_losses: RwLock::new(0),
            fixed_capital: RwLock::new(None),
        }
    }

    pub fn notify_loss(&self) {
        let mut losses = self.consecutive_losses.write().unwrap();
        *losses += 1;
    }

    pub fn notify_win(&self) {
        let mut losses = self.consecutive_losses.write().unwrap();
        *losses = 0;
    }

    pub fn set_fixed_capital(&self, amount: Option<f64>) {
        let mut fixed = self.fixed_capital.write().unwrap();
        *fixed = amount;
        if let Some(amt) = amount {
            info!("Capital mode -> FIXED ${:.2} USDC", amt);
        } else {
            info!("Capital mode -> AUTO (Balance x base_capital_pct)");
        }
    }

    pub fn get_capital_mode(&self) -> String {
        let fixed = self.fixed_capital.read().unwrap();
        if let Some(amt) = *fixed {
            format!("FIXED ${:.2}", amt)
        } else {
            format!("AUTO (Balance x {:.0}%)", self.config.base_capital_pct * 100.0)
        }
    }

    pub async fn compute_quantity(
        &self,
        signal: &TradeSignal,
        account: &AccountState,
        drawdown_reduction_pct: f64,
    ) -> f64 {
        let mut base_usdt = {
            let fixed = self.fixed_capital.read().unwrap();
            if let Some(amt) = *fixed {
                amt
            } else {
                account.balance_usdt * self.config.base_capital_pct
            }
        };

        if drawdown_reduction_pct > 0.0 {
            base_usdt *= 1.0 - drawdown_reduction_pct;
            info!("Drawdown size reduction: {:.0}%", drawdown_reduction_pct * 100.0);
        }

        let losses = *self.consecutive_losses.read().unwrap();
        if losses >= 3 {
            base_usdt *= 0.5;
            info!("Consecutive losses {} - size 50% reduction", losses);
        }

        // Volatility adjustment
        let target_atr = self.market_data.compute_atr(&signal.symbol, 14).await;
        let avg_atr = self.market_data.compute_atr(&signal.symbol, 50).await;
        if avg_atr > 0.0 && target_atr > 0.0 {
            let vol_adj = (avg_atr / target_atr).clamp(0.5, 1.5);
            base_usdt *= vol_adj;
            debug!("Volatility adjustment factor: {:.3}", vol_adj);
        }

        let notional_usdt = {
            let fixed = self.fixed_capital.read().unwrap();
            if fixed.is_some() {
                base_usdt
            } else {
                let max_usdt = account.balance_usdt * self.config.max_position_capital_pct;
                f64::min(base_usdt, max_usdt)
            }
        };

        let price = signal.avg_entry_price;
        if price <= 0.0 {
            warn!("Entry price 0 - cannot compute quantity");
            return 0.0;
        }

        let margin_usdt = notional_usdt;
        let notional_with_lev = margin_usdt * self.config.leverage as f64;
        let quantity = notional_with_lev / price;

        info!("Size calculation: Margin ${:.2} x {}x lev / ${:.4} = {:.6} {}",
              margin_usdt, self.config.leverage, price, quantity, signal.symbol);
        
        (quantity * 1_000_000.0).round() / 1_000_000.0
    }
}
