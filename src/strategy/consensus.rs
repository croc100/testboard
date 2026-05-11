use std::collections::HashMap;
use std::sync::Arc;
use chrono::Utc;
use tracing::{info, debug};
use crate::core::config::ConsensusConfig;
use crate::core::models::{TradeSignal, TraderPosition};
use crate::data_sources::trader_pool::TraderPool;

pub struct ConsensusEngine {
    config: ConsensusConfig,
    trader_pool: Arc<TraderPool>,
}

impl ConsensusEngine {
    pub fn new(config: ConsensusConfig, trader_pool: Arc<TraderPool>) -> Self {
        Self { config, trader_pool }
    }

    pub fn evaluate(
        &self,
        all_positions: &HashMap<String, Vec<TraderPosition>>,
        base_capital_usdt: f64,
        stop_loss_pct: f64,
        take_profit_pct: f64,
    ) -> Vec<TradeSignal> {
        let mut grouped: HashMap<String, Vec<TraderPosition>> = HashMap::new();
        for positions in all_positions.values() {
            for pos in positions {
                let key = pos.position_key();
                grouped.entry(key).or_default().push(pos.clone());
            }
        }

        let mut signals = Vec::new();
        let total_traders = self.trader_pool.trader_count();

        for (key, positions) in grouped {
            if positions.len() < self.config.min_traders as usize {
                continue;
            }

            if !self.within_lag(&positions) {
                debug!("Signal {}: Entry lag exceeded ({} min)", key, self.config.max_entry_lag_minutes);
                continue;
            }

            let confidence = positions.len() as f64 / total_traders as f64;
            if confidence < self.config.min_confidence {
                debug!("Signal {}: Confidence {:.2} < {:.2}", key, confidence, self.config.min_confidence);
                continue;
            }

            let avg_entry = positions.iter().map(|p| p.entry_price).sum::<f64>() / positions.len() as f64;
            let supporting = positions.iter().map(|p| p.trader_uid.clone()).collect();

            signals.push(TradeSignal {
                symbol: positions[0].symbol.clone(),
                side: positions[0].side.clone(),
                confidence,
                supporting_traders: supporting,
                avg_entry_price: avg_entry,
                suggested_size_usdt: base_capital_usdt,
                stop_loss_pct,
                take_profit_pct,
                created_at: Utc::now(),
            });
            info!("Consensus signal: {} | {} supporting traders | Confidence {:.2}",
                  key, positions.len(), confidence);
        }

        signals
    }

    fn within_lag(&self, positions: &[TraderPosition]) -> bool {
        if positions.len() < 2 {
            return true;
        }
        let times: Vec<i64> = positions.iter().map(|p| p.update_time).collect();
        let max_time = *times.iter().max().unwrap();
        let min_time = *times.iter().min().unwrap();
        let lag_min = (max_time - min_time) as f64 / 60_000.0;
        lag_min <= self.config.max_entry_lag_minutes as f64
    }
}
