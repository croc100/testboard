use crate::core::config::RiskConfig;
use crate::core::models::AccountState;

pub const HARD_MAX_DAILY_LOSS_PCT: f64 = 0.05;

pub struct LimitsChecker {
    config: RiskConfig,
}

impl LimitsChecker {
    pub fn new(config: RiskConfig) -> Self {
        Self { config }
    }

    pub fn check_daily_loss(&self, account: &AccountState) -> (bool, String) {
        let loss = account.daily_loss_pct();
        if loss <= -HARD_MAX_DAILY_LOSS_PCT {
            return (false, format!("Hard daily loss limit reached: {:.2}%", loss * 100.0));
        }
        if loss <= -self.config.max_daily_loss_pct {
            return (false, format!("Daily loss limit reached: {:.2}% (limit {:.2}%)", 
                                   loss * 100.0, self.config.max_daily_loss_pct * 100.0));
        }
        (true, String::new())
    }

    pub fn check_drawdown(&self, account: &AccountState) -> (bool, String) {
        let dd = account.total_drawdown_pct();
        if dd <= -self.config.max_drawdown_pct {
            return (false, format!("Max drawdown reached: {:.2}% (limit {:.2}%)", 
                                   dd * 100.0, self.config.max_drawdown_pct * 100.0));
        }
        (true, String::new())
    }

    pub fn drawdown_size_reduction(&self, account: &AccountState) -> f64 {
        let dd = account.total_drawdown_pct().abs();
        if dd >= 0.05 {
            return 0.5;
        }
        0.0
    }
}
