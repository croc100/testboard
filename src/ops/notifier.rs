use teloxide::prelude::*;
use teloxide::types::ParseMode;
use tracing::{info, warn};
use tokio::sync::mpsc;

#[derive(Debug, Clone)]
pub enum Priority {
    Low,
    Normal,
    High,
    Critical,
}

impl Priority {
    pub fn emoji(&self) -> &'static str {
        match self {
            Priority::Low => "ℹ️",
            Priority::Normal => "✅",
            Priority::High => "⚠️",
            Priority::Critical => "🚨",
        }
    }
}

pub struct Notifier {
    bot: Option<Bot>,
    chat_id: String,
    tx: mpsc::UnboundedSender<(String, Priority)>,
}

impl Notifier {
    pub fn new(bot_token: String, chat_id: String) -> Self {
        let bot = if !bot_token.is_empty() && !chat_id.is_empty() {
            info!("Telegram bot initialized");
            Some(Bot::new(bot_token))
        } else {
            warn!("Telegram bot token or chat ID missing - notifications disabled");
            None
        };

        let (tx, mut rx) = mpsc::unbounded_channel::<(String, Priority)>();
        let chat_id_clone = chat_id.clone();
        let bot_clone = bot.clone();

        tokio::spawn(async move {
            while let Some((message, priority)) = rx.recv().await {
                if let Some(ref bot) = bot_clone {
                    let full_msg = format!("{} {}", priority.emoji(), message);
                    if let Err(e) = bot.send_message(chat_id_clone.clone(), full_msg)
                        .parse_mode(ParseMode::Html)
                        .await {
                        warn!("Failed to send telegram message: {}", e);
                    }
                } else {
                    info!("[NOTIFY] {:?}: {}", priority, message);
                }
            }
        });

        Self { bot, chat_id, tx }
    }

    pub fn send(&self, message: String, priority: Priority) {
        let _ = self.tx.send((message, priority));
    }

    pub fn on_start(&self, balance: f64) {
        self.send(
            format!("<b>Bot Started</b>\nBalance: <code>${:.2} USDT</code>", balance),
            Priority::Normal,
        );
    }

    pub fn on_stop(&self, reason: &str) {
        self.send(
            format!("<b>Bot Stopped</b>\nReason: {}", if reason.is_empty() { "N/A" } else { reason }),
            Priority::Normal,
        );
    }

    pub fn on_signal(&self, symbol: &str, side: &str, confidence: f64, traders: usize) {
        self.send(
            format!("📡 <b>Signal Detected</b>: {} {}\nTraders: {} | Confidence: {:.0}%", 
                    symbol, side, traders, confidence * 100.0),
            Priority::Low,
        );
    }

    pub fn on_entry(&self, symbol: &str, side: &str, qty: f64, price: f64, sl: f64, tp: Option<f64>) {
        let tp_str = tp.map(|v| format!("${:.4}", v)).unwrap_or_else(|| "None".to_string());
        self.send(
            format!("<b>Entry Filled</b>: {} {}\nQty: {:.6} | Price: ${:.4}\nSL: ${:.4} | TP: {}", 
                    symbol, side, qty, price, sl, tp_str),
            Priority::Normal,
        );
    }

    pub fn on_close(&self, symbol: &str, side: &str, pnl: f64, hold_hours: f64, reason: &str) {
        let sign = if pnl >= 0.0 { "+" } else { "" };
        self.send(
            format!("<b>Position Closed</b>: {} {}\nPNL: <code>{}${:.2}</code> | Hold: {:.1}h\nReason: {}", 
                    symbol, side, sign, pnl, hold_hours, reason),
            Priority::Normal,
        );
    }

    pub fn on_circuit_breaker(&self, reason: &str, closed_count: usize) {
        self.send(
            format!("<b>🚨 Circuit Breaker Tripped</b>\nReason: {}\nClosed: {} positions\nNew entries blocked.", 
                    reason, closed_count),
            Priority::Critical,
        );
    }
}
