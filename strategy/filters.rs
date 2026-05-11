use std::sync::Arc;
use chrono::Utc;
use tracing::warn;
use crate::core::config::FiltersConfig;
use crate::core::models::{TradeSignal, Side};
use crate::data_sources::market_data::MarketData;

pub struct EntryFilterChain {
    config: FiltersConfig,
    market_data: Arc<MarketData>,
}

impl EntryFilterChain {
    pub fn new(config: FiltersConfig, market_data: Arc<MarketData>) -> Self {
        Self { config, market_data }
    }

    pub async fn check(&self, signal: &TradeSignal) -> (bool, String) {
        let (ok, reason) = self.symbol_filter(&signal.symbol);
        if !ok { return (false, reason); }

        let (ok, reason) = self.signal_age_filter(signal);
        if !ok { return (false, reason); }

        let (ok, reason) = self.blackout_filter();
        if !ok { return (false, reason); }

        let (ok, reason) = self.funding_filter(&signal.symbol).await;
        if !ok { return (false, reason); }

        let (ok, reason) = self.volatility_filter(&signal.symbol).await;
        if !ok { return (false, reason); }

        let (ok, reason) = self.trend_filter(signal).await;
        if !ok { return (false, reason); }

        (true, "OK".to_string())
    }

    fn symbol_filter(&self, symbol: &str) -> (bool, String) {
        if !self.config.symbol_blacklist.is_empty() && self.config.symbol_blacklist.contains(&symbol.to_string()) {
            return (false, format!("Blacklisted symbol: {}", symbol));
        }
        if !self.config.symbol_whitelist.is_empty() && !self.config.symbol_whitelist.contains(&symbol.to_string()) {
            return (false, format!("Symbol not in whitelist: {}", symbol));
        }
        (true, String::new())
    }

    fn signal_age_filter(&self, signal: &TradeSignal) -> (bool, String) {
        let now = Utc::now();
        let age_min = (now - signal.created_at).num_seconds() as f64 / 60.0;
        if age_min > self.config.max_signal_age_minutes as f64 {
            return (false, format!("Signal expired: {:.1}m elapsed (max {}m)", age_min, self.config.max_signal_age_minutes));
        }
        (true, String::new())
    }

    fn blackout_filter(&self) -> (bool, String) {
        let now = Utc::now();
        for period in &self.config.blackout_periods {
            if now >= period.start && now <= period.end {
                return (false, format!("Blackout period: {}", period.reason));
            }
        }
        (true, String::new())
    }

    async fn funding_filter(&self, symbol: &str) -> (bool, String) {
        let rate = self.market_data.get_funding_rate(symbol).await;
        if rate.abs() > self.config.max_funding_rate {
            return (false, format!("Funding rate too high: {:.4}% (max {:.4}%)", rate * 100.0, self.config.max_funding_rate * 100.0));
        }
        (true, String::new())
    }

    async fn volatility_filter(&self, symbol: &str) -> (bool, String) {
        let current_atr = self.market_data.compute_atr(symbol, 14).await;
        let avg_atr = self.market_data.compute_atr(symbol, 50).await;
        if avg_atr > 0.0 && current_atr > avg_atr * self.config.max_atr_multiplier {
            return (false, format!("Volatility too high: ATR {:.4} > avg {:.4} x {:.1}", current_atr, avg_atr, self.config.max_atr_multiplier));
        }
        (true, String::new())
    }

    async fn trend_filter(&self, signal: &TradeSignal) -> (bool, String) {
        match self.market_data.get_price(&signal.symbol).await {
            Ok(price) => {
                if let Some(ema) = self.market_data.get_ema(&signal.symbol, 200).await {
                    if signal.side == Side::LONG && price < ema {
                        return (false, format!("Trend mismatch: LONG but price({:.2}) < EMA200({:.2})", price, ema));
                    }
                    if signal.side == Side::SHORT && price > ema {
                        return (false, format!("Trend mismatch: SHORT but price({:.2}) > EMA200({:.2})", price, ema));
                    }
                }
            },
            Err(e) => {
                warn!("Price fetch failed for trend filter ({}): {} - passing", signal.symbol, e);
            }
        }
        (true, String::new())
    }
}
