use chrono::Utc;
use crate::core::config::ExitsConfig;
use crate::core::models::MyPosition;
use crate::core::models::Side;

pub struct ExitManager {
    config: ExitsConfig,
}

impl ExitManager {
    pub fn new(config: ExitsConfig) -> Self {
        Self { config }
    }

    pub fn compute_sl_price(&self, entry_price: f64, side: &Side) -> f64 {
        match side {
            Side::LONG => (entry_price * (1.0 - self.config.hard_stop_loss_pct) * 10000.0).round() / 10000.0,
            Side::SHORT => (entry_price * (1.0 + self.config.hard_stop_loss_pct) * 10000.0).round() / 10000.0,
        }
    }

    pub fn compute_tp_price(&self, entry_price: f64, side: &Side) -> Option<f64> {
        if self.config.partial_tp_levels.is_empty() {
            return None;
        }
        let first_tp = self.config.partial_tp_levels[0].pct;
        match side {
            Side::LONG => Some((entry_price * (1.0 + first_tp) * 10000.0).round() / 10000.0),
            Side::SHORT => Some((entry_price * (1.0 - first_tp) * 10000.0).round() / 10000.0),
        }
    }

    pub fn should_trail_stop(&self, position: &MyPosition, current_price: f64) -> bool {
        let activation = self.config.trailing_activation_pct;
        let profit_pct = if position.side == "LONG" {
            (current_price - position.entry_price) / position.entry_price
        } else {
            (position.entry_price - current_price) / position.entry_price
        };
        profit_pct >= activation
    }

    pub fn compute_trail_sl(&self, position: &MyPosition) -> f64 {
        let hwm = position.high_water_mark;
        if position.side == "LONG" {
            (hwm * (1.0 - self.config.trailing_distance_pct) * 10000.0).round() / 10000.0
        } else {
            (hwm * (1.0 + self.config.trailing_distance_pct) * 10000.0).round() / 10000.0
        }
    }

    pub fn update_high_water_mark(&self, position: &MyPosition, current_price: f64) -> f64 {
        if position.side == "LONG" {
            f64::max(position.high_water_mark, current_price)
        } else {
            if position.high_water_mark == 0.0 {
                current_price
            } else {
                f64::min(position.high_water_mark, current_price)
            }
        }
    }

    pub fn is_time_stop(&self, position: &MyPosition) -> bool {
        let now = Utc::now();
        let elapsed = now.signed_duration_since(position.opened_at);
        elapsed.num_hours() >= self.config.time_stop_hours as i64
    }

    pub fn get_partial_close_ratio(&self, position: &MyPosition, current_price: f64) -> f64 {
        for level in &self.config.partial_tp_levels {
            let pct = if position.side == "LONG" {
                (current_price - position.entry_price) / position.entry_price
            } else {
                (position.entry_price - current_price) / position.entry_price
            };
            if pct >= level.pct {
                return level.close_ratio;
            }
        }
        0.0
    }
}
