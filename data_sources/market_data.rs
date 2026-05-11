use std::collections::HashMap;
use std::sync::Arc;
use crate::exchange::hl_client::HlClient;
use crate::core::error::ExchangeError;
use tracing::warn;

pub struct MarketData {
    client: Arc<HlClient>,
    atr_cache: HashMap<String, (f64, i64)>,
}

impl MarketData {
    pub fn new(client: Arc<HlClient>) -> Self {
        Self {
            client,
            atr_cache: HashMap::new(),
        }
    }

    pub async fn get_price(&self, symbol: &str) -> Result<f64, ExchangeError> {
        self.client.get_ticker_price(symbol).await
    }

    pub async fn get_funding_rate(&self, symbol: &str) -> f64 {
        self.client.get_funding_rate(symbol).await.unwrap_or(0.0)
    }

    pub async fn compute_atr(&self, symbol: &str, period: usize) -> f64 {
        let klines = match self.client.get_klines(symbol, "1h", period + 1).await {
            Ok(k) => k,
            Err(_) => return 0.0,
        };

        let k_arr = match klines.as_array() {
            Some(a) => a,
            None => return 0.0,
        };

        if k_arr.len() < 2 {
            warn!("ATR calculation impossible ({}): insufficient data", symbol);
            return 0.0;
        }

        let mut trs = Vec::new();
        for i in 1..k_arr.len() {
            let high: f64 = k_arr[i][2].as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0);
            let low: f64 = k_arr[i][3].as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0);
            let prev_close: f64 = k_arr[i - 1][4].as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0);
            
            let tr = f64::max(high - low, f64::max((high - prev_close).abs(), (low - prev_close).abs()));
            trs.push(tr);
        }

        if trs.is_empty() {
            return 0.0;
        }
        
        let start = trs.len().saturating_sub(period);
        trs[start..].iter().sum::<f64>() / (trs.len() - start) as f64
    }

    pub async fn get_ema(&self, symbol: &str, period: usize) -> Option<f64> {
        let klines = self.client.get_klines(symbol, "1h", period + 1).await.ok()?;
        let k_arr = klines.as_array()?;

        if k_arr.len() < period {
            return None;
        }

        let closes: Vec<f64> = k_arr.iter()
            .map(|k| k[4].as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0))
            .collect();

        let k = 2.0 / (period as f64 + 1.0);
        let mut ema = closes[0];
        for c in &closes[1..] {
            ema = c * k + ema * (1.0 - k);
        }
        Some(ema)
    }
}
