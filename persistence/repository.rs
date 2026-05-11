use sqlx::{sqlite::SqlitePool, Row};
use chrono::{DateTime, Utc};
use tracing::info;

pub struct TradeRepository {
    pool: SqlitePool,
}

impl TradeRepository {
    pub async fn new(db_url: &str) -> Result<Self, sqlx::Error> {
        let pool = SqlitePool::connect(db_url).await?;
        
        // Initialize tables
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS trade_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                quantity REAL NOT NULL,
                leverage INTEGER,
                pnl REAL,
                opened_at DATETIME,
                closed_at DATETIME,
                close_reason TEXT,
                signal_confidence REAL,
                supporting_traders TEXT
            )"
        ).execute(&pool).await?;

        sqlx::query(
            "CREATE TABLE IF NOT EXISTS signal_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                confidence REAL,
                supporting_traders TEXT,
                avg_entry_price REAL,
                acted INTEGER,
                reject_reason TEXT,
                created_at DATETIME
            )"
        ).execute(&pool).await?;

        sqlx::query(
            "CREATE TABLE IF NOT EXISTS circuit_breaker_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reason TEXT NOT NULL,
                tripped_at DATETIME,
                reset_at DATETIME
            )"
        ).execute(&pool).await?;

        Ok(Self { pool })
    }

    pub async fn open_trade(
        &self,
        symbol: &str,
        side: &str,
        entry_price: f64,
        quantity: f64,
        leverage: i32,
        confidence: f64,
        traders: &[String],
    ) -> Result<i64, sqlx::Error> {
        let traders_str = traders.join(",");
        let now = Utc::now();
        let res = sqlx::query(
            "INSERT INTO trade_logs (symbol, side, entry_price, quantity, leverage, signal_confidence, supporting_traders, opened_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        .bind(symbol)
        .bind(side)
        .bind(entry_price)
        .bind(quantity)
        .bind(leverage)
        .bind(confidence)
        .bind(traders_str)
        .bind(now)
        .execute(&self.pool)
        .await?;

        Ok(res.last_insert_rowid())
    }

    pub async fn close_trade(
        &self,
        trade_id: i64,
        exit_price: f64,
        pnl: f64,
        reason: &str,
    ) -> Result<(), sqlx::Error> {
        let now = Utc::now();
        sqlx::query(
            "UPDATE trade_logs SET exit_price = ?, pnl = ?, closed_at = ?, close_reason = ?
             WHERE id = ?"
        )
        .bind(exit_price)
        .bind(pnl)
        .bind(now)
        .bind(reason)
        .bind(trade_id)
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    pub async fn log_signal(
        &self,
        symbol: &str,
        side: &str,
        confidence: f64,
        traders: &[String],
        avg_price: f64,
        acted: bool,
        reject_reason: &str,
    ) -> Result<(), sqlx::Error> {
        let traders_str = traders.join(",");
        let now = Utc::now();
        sqlx::query(
            "INSERT INTO signal_logs (symbol, side, confidence, supporting_traders, avg_entry_price, acted, reject_reason, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        .bind(symbol)
        .bind(side)
        .bind(confidence)
        .bind(traders_str)
        .bind(avg_price)
        .bind(if acted { 1 } else { 0 })
        .bind(reject_reason)
        .bind(now)
        .execute(&self.pool)
        .await?;

        Ok(())
    }
}
