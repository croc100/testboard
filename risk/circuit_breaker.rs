use std::sync::RwLock;
use std::time::{SystemTime, UNIX_EPOCH};
use chrono::{DateTime, Utc};
use tracing::{info, warn, error};

#[derive(Debug, Clone, Default)]
pub struct CircuitBreakerState {
    pub tripped: bool,
    pub reason: String,
    pub tripped_at: Option<DateTime<Utc>>,
    pub consecutive_losses: i32,
}

pub struct CircuitBreaker {
    max_cons_losses: i32,
    api_window_sec: u64,
    api_threshold: f64,
    price_stall_sec: u64,
    state: RwLock<CircuitBreakerState>,
    last_price_update: RwLock<f64>,
    api_calls: RwLock<Vec<f64>>,
    api_errors: RwLock<Vec<f64>>,
}

impl CircuitBreaker {
    pub fn new(
        max_consecutive_losses: i32,
        api_error_window_sec: u64,
        api_error_threshold: f64,
        price_stall_sec: u64,
    ) -> Self {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64();
        Self {
            max_cons_losses: max_consecutive_losses,
            api_window_sec: api_error_window_sec,
            api_threshold: api_error_threshold,
            price_stall_sec,
            state: RwLock::new(CircuitBreakerState::default()),
            last_price_update: RwLock::new(now),
            api_calls: RwLock::new(Vec::new()),
            api_errors: RwLock::new(Vec::new()),
        }
    }

    pub fn is_tripped(&self) -> bool {
        self.state.read().unwrap().tripped
    }

    pub fn get_reason(&self) -> String {
        self.state.read().unwrap().reason.clone()
    }

    pub fn on_loss(&self) {
        let mut state = self.state.write().unwrap();
        state.consecutive_losses += 1;
        info!("Consecutive losses: {}", state.consecutive_losses);
        if state.consecutive_losses >= self.max_cons_losses {
            drop(state); // avoid deadlock
            self.trip(format!("Consecutive losses {} reached", self.max_cons_losses));
        }
    }

    pub fn on_win(&self) {
        let mut state = self.state.write().unwrap();
        state.consecutive_losses = 0;
    }

    pub fn on_api_call(&self, success: bool) {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64();
        let cutoff = now - self.api_window_sec as f64;
        
        {
            let mut calls = self.api_calls.write().unwrap();
            calls.retain(|&t| t > cutoff);
            calls.push(now);
        }
        
        if !success {
            let mut errors = self.api_errors.write().unwrap();
            errors.retain(|&t| t > cutoff);
            errors.push(now);
        }

        let calls_len = self.api_calls.read().unwrap().len();
        if calls_len >= 10 {
            let errors_len = self.api_errors.read().unwrap().len();
            let error_rate = errors_len as f64 / calls_len as f64;
            if error_rate >= self.api_threshold {
                self.trip(format!("API error rate {:.0}% exceeded", error_rate * 100.0));
            }
        }
    }

    pub fn on_price_update(&self) {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64();
        *self.last_price_update.write().unwrap() = now;
    }

    pub fn check_price_stall(&self) {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64();
        let elapsed = now - *self.last_price_update.read().unwrap();
        if elapsed > self.price_stall_sec as f64 {
            self.trip(format!("Price stall detected: {:.0}s", elapsed));
        }
    }

    pub fn trip(&self, reason: String) {
        let mut state = self.state.write().unwrap();
        if state.tripped {
            return;
        }
        state.tripped = true;
        state.reason = reason.clone();
        state.tripped_at = Some(Utc::now());
        error!("🚨 Circuit Breaker TRIPPED: {}", reason);
    }

    pub fn manual_reset(&self) {
        let mut state = self.state.write().unwrap();
        warn!("Circuit Breaker manually reset (previous reason: {})", state.reason);
        *state = CircuitBreakerState::default();
        self.api_calls.write().unwrap().clear();
        self.api_errors.write().unwrap().clear();
        *self.last_price_update.write().unwrap() = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64();
    }
}
