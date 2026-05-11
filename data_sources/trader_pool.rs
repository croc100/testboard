use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use reqwest::Client;
use crate::core::config::TraderConfig;
use crate::core::models::{TraderPosition, Side};
use tracing::{warn, debug};
use tokio::time::sleep;

pub struct HlPositionFetcher {
    trader_uid: String,
    client: Client,
    max_retries: usize,
    backoff_base: f64,
}

impl HlPositionFetcher {
    pub fn new(trader_uid: &str) -> Self {
        Self {
            trader_uid: trader_uid.to_lowercase(),
            client: Client::new(),
            max_retries: 5,
            backoff_base: 2.0,
        }
    }

    pub async fn fetch_positions(&self) -> Result<Vec<TraderPosition>, String> {
        let payload = json!({"type": "clearinghouseState", "user": self.trader_uid});
        let url = "https://api.hyperliquid.xyz/info";

        let mut last_error = String::new();
        for attempt in 0..self.max_retries {
            match self.client.post(url).json(&payload).send().await {
                Ok(resp) => {
                    if resp.status() == 429 {
                        let wait = self.backoff_base.powi(attempt as i32 + 2) as u64;
                        warn!("Rate limited. Waiting {}s before retry.", wait);
                        sleep(Duration::from_secs(wait)).await;
                        continue;
                    }
                    match resp.json::<Value>().await {
                        Ok(data) => return Ok(self.parse(data)),
                        Err(e) => {
                            last_error = e.to_string();
                        }
                    }
                },
                Err(e) => {
                    last_error = e.to_string();
                }
            }
            let wait = self.backoff_base.powi(attempt as i32) as u64;
            warn!("Fetch failed (attempt {}/{}): {}. Retrying in {}s.", attempt + 1, self.max_retries, last_error, wait);
            sleep(Duration::from_secs(wait)).await;
        }

        Err(format!("Failed to fetch positions for {}: {}", self.trader_uid, last_error))
    }

    fn parse(&self, data: Value) -> Vec<TraderPosition> {
        let mut positions = Vec::new();
        let now_ms = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as i64;
        
        if let Some(asset_positions) = data.get("assetPositions").and_then(|v| v.as_array()) {
            for asset_pos in asset_positions {
                if let Some(p) = asset_pos.get("position") {
                    let size_str = p.get("szi").and_then(|v| v.as_str()).unwrap_or("0");
                    let size: f64 = size_str.parse().unwrap_or(0.0);
                    if size == 0.0 { continue; }

                    let side = if size > 0.0 { Side::LONG } else { Side::SHORT };
                    let entry_px: f64 = p.get("entryPx").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0.0);
                    let lev = p.get("leverage").and_then(|v| v.get("value")).and_then(|v| v.as_i64()).unwrap_or(1) as i32;
                    let pnl: f64 = p.get("unrealizedPnl").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0.0);
                    let roe: f64 = p.get("returnOnEquity").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0.0);

                    positions.append(&mut vec![TraderPosition {
                        trader_uid: self.trader_uid.clone(),
                        symbol: format!("{}USDT", p.get("coin").and_then(|v| v.as_str()).unwrap_or("")),
                        side,
                        entry_price: entry_px,
                        mark_price: entry_px,
                        amount: size.abs(),
                        leverage: lev,
                        pnl,
                        roe,
                        update_time: now_ms,
                    }]);
                }
            }
        }
        positions
    }
}

pub struct TraderPool {
    configs: RwLock<Vec<TraderConfig>>,
    scrapers: RwLock<HashMap<String, Arc<HlPositionFetcher>>>,
    last_positions: RwLock<HashMap<String, Vec<TraderPosition>>>,
    error_counts: RwLock<HashMap<String, usize>>,
}

impl TraderPool {
    pub fn new(trader_configs: Vec<TraderConfig>) -> Self {
        let mut configs = Vec::new();
        let mut scrapers = HashMap::new();
        let mut error_counts = HashMap::new();

        for c in trader_configs {
            let uid = c.uid.to_lowercase();
            scrapers.insert(uid.clone(), Arc::new(HlPositionFetcher::new(&c.uid)));
            error_counts.insert(uid.clone(), 0);
            configs.push(c);
        }

        Self {
            configs: RwLock::new(configs),
            scrapers: RwLock::new(scrapers),
            last_positions: RwLock::new(HashMap::new()),
            error_counts: RwLock::new(error_counts),
        }
    }

    pub fn trader_count(&self) -> usize {
        self.configs.read().unwrap().len()
    }

    pub async fn fetch_all(&self) -> HashMap<String, Vec<TraderPosition>> {
        let scrapers = self.scrapers.read().unwrap().clone();
        let mut results = HashMap::new();

        for (uid, scraper) in scrapers {
            match scraper.fetch_positions().await {
                Ok(positions) => {
                    self.error_counts.write().unwrap().insert(uid.clone(), 0);
                    self.last_positions.write().unwrap().insert(uid.clone(), positions.clone());
                    results.insert(uid, positions);
                },
                Err(e) => {
                    let mut counts = self.error_counts.write().unwrap();
                    let count = counts.entry(uid.clone()).or_insert(0);
                    *count += 1;
                    warn!("Trader {} fetch failed (consecutive {}): {}", uid, *count, e);
                    
                    let last = self.last_positions.read().unwrap();
                    results.insert(uid.clone(), last.get(&uid).cloned().unwrap_or_default());
                }
            }
        }
        results
    }
}
