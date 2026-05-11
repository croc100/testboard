use std::collections::HashMap;
use std::sync::RwLock;
use crate::core::models::MyPosition;
use tracing::info;

pub struct PositionTracker {
    positions: RwLock<HashMap<String, MyPosition>>,
}

impl PositionTracker {
    pub fn new() -> Self {
        Self {
            positions: RwLock::new(HashMap::new()),
        }
    }

    pub fn add(&self, pos: MyPosition) {
        let key = pos.position_key();
        info!("Position added: {} | entry={:.4} | qty={:.6}", key, pos.entry_price, pos.quantity);
        self.positions.write().unwrap().insert(key, pos);
    }

    pub fn remove(&self, symbol: &str, side: &str) -> Option<MyPosition> {
        let key = format!("{}_{}", symbol, side);
        let pos = self.positions.write().unwrap().remove(&key);
        if pos.is_some() {
            info!("Position removed: {}", key);
        }
        pos
    }

    pub fn get(&self, symbol: &str, side: &str) -> Option<MyPosition> {
        let key = format!("{}_{}", symbol, side);
        self.positions.read().unwrap().get(&key).cloned()
    }

    pub fn all(&self) -> Vec<MyPosition> {
        self.positions.read().unwrap().values().cloned().collect()
    }

    pub fn update_pnl(&self, symbol: &str, side: &str, unrealized_pnl: f64) {
        let key = format!("{}_{}", symbol, side);
        if let Some(pos) = self.positions.write().unwrap().get_mut(&key) {
            pos.unrealized_pnl = unrealized_pnl;
        }
    }

    pub fn update_sl_order(&self, symbol: &str, side: &str, order_id: String) {
        let key = format!("{}_{}", symbol, side);
        if let Some(pos) = self.positions.write().unwrap().get_mut(&key) {
            pos.sl_order_id = Some(order_id);
        }
    }

    pub fn update_high_water_mark(&self, symbol: &str, side: &str, price: f64) {
        let key = format!("{}_{}", symbol, side);
        if let Some(pos) = self.positions.write().unwrap().get_mut(&key) {
            if side == "LONG" {
                pos.high_water_mark = f64::max(pos.high_water_mark, price);
            } else {
                if pos.high_water_mark == 0.0 {
                    pos.high_water_mark = price;
                } else {
                    pos.high_water_mark = f64::min(pos.high_water_mark, price);
                }
            }
        }
    }

    pub fn has_position(&self, symbol: &str, side: &str) -> bool {
        let key = format!("{}_{}", symbol, side);
        self.positions.read().unwrap().contains_key(&key)
    }

    pub fn count(&self) -> usize {
        self.positions.read().unwrap().len()
    }
}
