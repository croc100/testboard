use std::sync::Arc;
use chrono::Utc;
use tracing::{info, error, warn};
use serde_json::Value;

use crate::core::config::AppConfig;
use crate::core::models::{MyPosition, TradeSignal, Side};
use crate::core::error::{ExchangeError, CopyTraderError};
use crate::exchange::hl_client::HlClient;
use crate::execution::position_tracker::PositionTracker;
use crate::strategy::sizing::PositionSizer;
use crate::strategy::exits::ExitManager;

pub struct OrderManager {
    client: Arc<HlClient>,
    config: AppConfig,
    tracker: Arc<PositionTracker>,
    sizer: Arc<PositionSizer>,
    exit_manager: Arc<ExitManager>,
}

impl OrderManager {
    pub fn new(
        client: Arc<HlClient>,
        config: AppConfig,
        tracker: Arc<PositionTracker>,
        sizer: Arc<PositionSizer>,
        exit_manager: Arc<ExitManager>,
    ) -> Self {
        Self {
            client,
            config,
            tracker,
            sizer,
            exit_manager,
        }
    }

    pub async fn enter_position(
        &self,
        signal: &TradeSignal,
        account_state: &crate::core::models::AccountState,
    ) -> Result<Option<MyPosition>, CopyTraderError> {
        let symbol = &signal.symbol;
        let side = &signal.side;
        let order_side = match side {
            Side::LONG => "BUY",
            Side::SHORT => "SELL",
        };

        // Leverage & Margin settings
        if let Err(e) = self.client.set_leverage(symbol, self.config.position.leverage).await {
            warn!("Leverage setting failed for {}: {}", symbol, e);
        }

        // Quantity calculation
        let quantity = self.sizer.compute_quantity(signal, account_state, 0.0).await;
        if quantity <= 0.0 {
            error!("Quantity calculation result 0 - entry cancelled");
            return Ok(None);
        }

        // Market entry
        let result = match self.client.market_order(symbol, order_side, quantity, false).await {
            Ok(res) => res,
            Err(e) => {
                error!("Market entry failed ({} {}): {}", order_side, symbol, e);
                return Err(e.into());
            }
        };

        let order_id = result["orderId"].as_str().unwrap_or("?");
        info!("Entry filled: {:?} {} qty={} orderId={}", side, symbol, quantity, order_id);

        // SL price calculation
        let entry_price = signal.avg_entry_price;
        let sl_price = self.exit_manager.compute_sl_price(entry_price, side);
        let sl_side = match side {
            Side::LONG => "SELL",
            Side::SHORT => "BUY",
        };

        // SL registration
        let sl_order_id = match self.client.stop_market_order(symbol, sl_side, sl_price, quantity, true).await {
            Ok(res) => res["orderId"].as_str().map(|s| s.to_string()),
            Err(e) => {
                error!("SL registration failed ({}): {} -> Emergency liquidation", symbol, e);
                if let Err(close_err) = self.client.close_position(symbol, side.to_string().as_str(), quantity).await {
                    error!("Emergency liquidation also failed: {}", close_err);
                }
                return Err(ExchangeError::StopLossRegistration(e.to_string()).into());
            }
        };
        info!("SL registered: {} stopPrice={} orderId={:?}", symbol, sl_price, sl_order_id);

        // TP registration (Optional)
        let mut tp_order_id = None;
        if let Some(tp_price) = self.exit_manager.compute_tp_price(entry_price, side) {
            let tp_side = match side {
                Side::LONG => "SELL",
                Side::SHORT => "BUY",
            };
            match self.client.take_profit_order(symbol, tp_side, tp_price, quantity).await {
                Ok(res) => {
                    tp_order_id = res["orderId"].as_str().map(|s| s.to_string());
                    info!("TP registered: {} stopPrice={} orderId={:?}", symbol, tp_price, tp_order_id);
                },
                Err(e) => {
                    warn!("TP registration failed ({}): {} - continuing", symbol, e);
                }
            }
        }

        let pos = MyPosition {
            symbol: symbol.clone(),
            side: side.to_string(),
            entry_price,
            quantity,
            leverage: self.config.position.leverage,
            unrealized_pnl: 0.0,
            opened_at: Utc::now(),
            source_signal: signal.clone(),
            sl_order_id,
            tp_order_id,
            high_water_mark: entry_price,
        };

        self.tracker.add(pos.clone());
        Ok(Some(pos))
    }

    pub async fn close_position(&self, pos: &MyPosition, reason: &str) -> bool {
        let symbol = &pos.symbol;
        let side = &pos.side;

        // Cancel existing orders
        if let Some(oid) = &pos.sl_order_id {
            let _ = self.client.cancel_order(symbol, oid).await;
        }
        if let Some(oid) = &pos.tp_order_id {
            let _ = self.client.cancel_order(symbol, oid).await;
        }

        match self.client.close_position(symbol, side, pos.quantity).await {
            Ok(_) => {
                self.tracker.remove(symbol, side);
                info!("Position closed: {} {} | Reason: {}", side, symbol, reason);
                true
            },
            Err(e) => {
                error!("Close failed ({} {}): {}", side, symbol, e);
                false
            }
        }
    }
}
