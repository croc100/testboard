use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use reqwest::Client;
use crate::core::config::AppConfig;
use crate::core::error::ExchangeError;
use tracing::{info, warn};

pub struct HlClient {
    user: String,
    signer_private_key: String,
    dry_run: bool,
    client: Client,
    api_url: String,
    asset_index: HashMap<String, i32>,
}

impl HlClient {
    pub fn new(config: &AppConfig) -> Self {
        Self {
            user: config.user_address.to_lowercase(),
            signer_private_key: config.signer_private_key.clone(),
            dry_run: config.mode.dry_run,
            client: Client::new(),
            api_url: config.exchange.api_url.clone(),
            asset_index: HashMap::new(),
        }
    }

    async fn info(&self, payload: Value) -> Result<Value, ExchangeError> {
        let url = format!("{}/info", self.api_url);
        let resp = self.client.post(&url)
            .json(&payload)
            .send()
            .await?;
        
        let data: Value = resp.json().await?;
        if data.get("status") == Some(&json!("err")) {
            return Err(ExchangeError::Api(data["response"].to_string()));
        }
        Ok(data)
    }

    pub async fn get_ticker_price(&self, symbol: &str) -> Result<f64, ExchangeError> {
        let coin = symbol.replace("USDT", "").replace("PERP", "").replace("-PERP", "");
        let mids = self.info(json!({"type": "allMids"})).await?;
        
        mids.get(&coin)
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse::<f64>().ok())
            .ok_or_else(|| ExchangeError::Api(format!("Price not found for {}", symbol)))
    }

    pub async fn get_funding_rate(&self, symbol: &str) -> Result<f64, ExchangeError> {
        let coin = symbol.replace("USDT", "").replace("PERP", "").replace("-PERP", "");
        let data = self.info(json!({"type": "metaAndAssetCtxs"})).await?;
        
        let universe = data[0].get("universe").and_then(|v| v.as_array()).ok_or(ExchangeError::Api("Universe not found".to_string()))?;
        let ctxs = data[1].as_array().ok_or(ExchangeError::Api("Ctxs not found".to_string()))?;
        
        for (i, asset) in universe.iter().enumerate() {
            if asset["name"] == coin {
                return Ok(ctxs[i]["funding"].as_str().and_then(|s| s.parse::<f64>().ok()).unwrap_or(0.0));
            }
        }
        Ok(0.0)
    }

    pub async fn get_klines(&self, symbol: &str, interval: &str, limit: usize) -> Result<Value, ExchangeError> {
        let coin = symbol.replace("USDT", "").replace("PERP", "").replace("-PERP", "");
        let now_ms = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as i64;
        
        let step = match interval {
            "1m" => 60_000,
            "5m" => 300_000,
            "15m" => 900_000,
            "1h" => 3_600_000,
            "4h" => 14_400_000,
            "1d" => 86_400_000,
            _ => 3_600_000,
        };
        let start_ms = now_ms - (step * limit as i64);

        self.info(json!({
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_ms,
                "endTime": now_ms
            }
        })).await
    }

    pub async fn get_balance(&self) -> Result<f64, ExchangeError> {
        let perp = self.info(json!({"type": "clearinghouseState", "user": self.user})).await?;
        let perp_val = perp["marginSummary"]["accountValue"]
            .as_str()
            .and_then(|s| s.parse::<f64>().ok())
            .unwrap_or(0.0);

        let spot_val = match self.info(json!({"type": "spotClearinghouseState", "user": self.user})).await {
            Ok(spot) => {
                spot["balances"]
                    .as_array()
                    .and_then(|balances| {
                        balances.iter().find(|b| b["coin"] == "USDC")
                            .and_then(|b| b["total"].as_str())
                            .and_then(|s| s.parse::<f64>().ok())
                    })
                    .unwrap_or(0.0)
            },
            Err(e) => {
                warn!("Failed to fetch spot balance: {}", e);
                0.0
            }
        };

        Ok(perp_val + spot_val)
    }

    pub async fn market_order(
        &self, 
        symbol: &str, 
        side: &str, 
        quantity: f64, 
        reduce_only: bool
    ) -> Result<Value, ExchangeError> {
        if self.dry_run {
            info!("[DRY_RUN] MARKET {} {} qty={}", side, symbol, quantity);
            return Ok(json!({
                "orderId": format!("DRY_{}", SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis()),
                "status": "FILLED"
            }));
        }
        Err(ExchangeError::Order("Signing not yet implemented".to_string()))
    }

    pub async fn stop_market_order(
        &self,
        symbol: &str,
        side: &str,
        stop_price: f64,
        quantity: f64,
        _close_position: bool,
    ) -> Result<Value, ExchangeError> {
        if self.dry_run {
            info!("[DRY_RUN] STOP_MARKET {} {} stopPrice={}", side, symbol, stop_price);
            return Ok(json!({
                "orderId": format!("DRY_SL_{}", SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis()),
                "status": "NEW"
            }));
        }
        Err(ExchangeError::Order("Signing not yet implemented".to_string()))
    }

    pub async fn take_profit_order(
        &self,
        symbol: &str,
        side: &str,
        stop_price: f64,
        quantity: f64,
    ) -> Result<Value, ExchangeError> {
        if self.dry_run {
            info!("[DRY_RUN] TAKE_PROFIT {} {} stopPrice={}", side, symbol, stop_price);
            return Ok(json!({
                "orderId": format!("DRY_TP_{}", SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis()),
                "status": "NEW"
            }));
        }
        Err(ExchangeError::Order("Signing not yet implemented".to_string()))
    }

    pub async fn cancel_order(&self, symbol: &str, order_id: &str) -> Result<Value, ExchangeError> {
        if self.dry_run {
            info!("[DRY_RUN] cancel_order {} {}", symbol, order_id);
            return Ok(json!({}));
        }
        Err(ExchangeError::Order("Signing not yet implemented".to_string()))
    }

    pub async fn close_position(&self, symbol: &str, side: &str, quantity: f64) -> Result<Value, ExchangeError> {
        let close_side = if side == "LONG" || side == "BUY" { "SELL" } else { "BUY" };
        self.market_order(symbol, close_side, quantity, true).await
    }

    pub async fn set_leverage(&self, symbol: &str, leverage: i32) -> Result<Value, ExchangeError> {
        if self.dry_run {
            info!("[DRY_RUN] set_leverage {} x{}", symbol, leverage);
            return Ok(json!({}));
        }
        Err(ExchangeError::Order("Signing not yet implemented".to_string()))
    }
}
