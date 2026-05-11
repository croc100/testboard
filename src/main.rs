use std::sync::Arc;
use std::time::Duration;
use tokio::time::sleep;
use tracing::{info, error, warn, Level};
use tracing_subscriber::FmtSubscriber;
use dotenv::dotenv;

use ebenezer::core::config::AppConfig;
use ebenezer::core::models::{AccountState, TradeSignal};
use ebenezer::exchange::hl_client::HlClient;
use ebenezer::data_sources::market_data::MarketData;
use ebenezer::data_sources::trader_pool::TraderPool;
use ebenezer::execution::position_tracker::PositionTracker;
use ebenezer::execution::order_manager::OrderManager;
use ebenezer::strategy::consensus::ConsensusEngine;
use ebenezer::strategy::exits::ExitManager;
use ebenezer::strategy::sizing::PositionSizer;
use ebenezer::strategy::filters::EntryFilterChain;
use ebenezer::risk::circuit_breaker::CircuitBreaker;
use ebenezer::risk::limits::LimitsChecker;
use ebenezer::ops::notifier::Notifier;
use ebenezer::persistence::repository::TradeRepository;

struct CopyTrader {
    config: AppConfig,
    client: Arc<HlClient>,
    tracker: Arc<PositionTracker>,
    market: Arc<MarketData>,
    pool: Arc<TraderPool>,
    exit_mgr: Arc<ExitManager>,
    sizer: Arc<PositionSizer>,
    consensus: Arc<ConsensusEngine>,
    filters: Arc<EntryFilterChain>,
    cb: Arc<CircuitBreaker>,
    limits: Arc<LimitsChecker>,
    order_mgr: Arc<OrderManager>,
    notifier: Arc<Notifier>,
    repo: Arc<TradeRepository>,
}

impl CopyTrader {
    async fn new(config_path: &str) -> Result<Self, Box<dyn std::error::Error>> {
        let config = AppConfig::load(config_path)?;
        
        let client = Arc::new(HlClient::new(&config));
        let tracker = Arc::new(PositionTracker::new());
        let market = Arc::new(MarketData::new(client.clone()));
        let pool = Arc::new(TraderPool::new(config.traders.clone()));
        let exit_mgr = Arc::new(ExitManager::new(config.exits.clone()));
        let sizer = Arc::new(PositionSizer::new(config.position.clone(), market.clone()));
        let consensus = Arc::new(ConsensusEngine::new(config.consensus.clone(), pool.clone()));
        let filters = Arc::new(EntryFilterChain::new(config.filters.clone(), market.clone()));
        let cb = Arc::new(CircuitBreaker::new(
            config.risk.max_consecutive_losses,
            600,
            0.5,
            30,
        ));
        let limits = Arc::new(LimitsChecker::new(config.risk.clone()));
        let order_mgr = Arc::new(OrderManager::new(
            client.clone(),
            config.clone(),
            tracker.clone(),
            sizer.clone(),
            exit_mgr.clone(),
        ));
        let notifier = Arc::new(Notifier::new(
            config.ops.telegram_bot_token.clone(),
            config.ops.telegram_chat_id.clone(),
        ));
        
        let db_url = format!("sqlite:{}", config.ops.db_path);
        let repo = Arc::new(TradeRepository::new(&db_url).await?);

        Ok(Self {
            config,
            client,
            tracker,
            market,
            pool,
            exit_mgr,
            sizer,
            consensus,
            filters,
            cb,
            limits,
            order_mgr,
            notifier,
            repo,
        })
    }

    async fn start(&self) {
        info!("Ebenezer bot started (DRY_RUN={})", self.config.mode.dry_run);

        let balance = match self.client.get_balance().await {
            Ok(b) => b,
            Err(e) => {
                error!("Failed to get initial balance: {}", e);
                return;
            }
        };
        self.notifier.on_start(balance);

        let interval = Duration::from_secs(self.config.ops.poll_interval_sec);
        loop {
            if let Err(e) = self.cycle().await {
                error!("Cycle error: {:?}", e);
            }
            sleep(interval).await;
        }
    }

    async fn cycle(&self) -> Result<(), Box<dyn std::error::Error>> {
        // 1. Check for price stall
        if let Err(_) = self.client.get_ticker_price("BTCUSDT").await {
            self.cb.check_price_stall();
        } else {
            self.cb.on_price_update();
        }

        // 2. Check circuit breaker
        if self.cb.is_tripped() {
            warn!("Circuit breaker tripped - skipping cycle (Reason: {})", self.cb.get_reason());
            return Ok(());
        }

        // 3. Get account state
        let balance = self.client.get_balance().await?;
        let account = AccountState {
            balance_usdt: balance,
            open_positions: self.tracker.all(),
            daily_realized_pnl: 0.0, // TODO: Track this
            cumulative_pnl: 0.0,
            peak_balance: balance, // TODO: Track this
        };

        // 4. Check limits
        let (ok, reason) = self.limits.check_daily_loss(&account);
        if !ok {
            self.cb.trip(reason);
            return Ok(());
        }

        // 5. Monitor positions (Simplified)
        for pos in self.tracker.all() {
            if let Ok(price) = self.market.get_price(&pos.symbol).await {
                self.tracker.update_high_water_mark(&pos.symbol, &pos.side, price);
                // TODO: Trailing stop logic here
            }
        }

        // 6. Fetch trader positions
        let all_positions = self.pool.fetch_all().await;

        // 7. Evaluate consensus
        let tp_pct = self.config.exits.partial_tp_levels.first().map(|l| l.pct).unwrap_or(0.03);
        let signals = self.consensus.evaluate(
            &all_positions,
            balance * self.config.position.base_capital_pct,
            self.config.exits.hard_stop_loss_pct,
            tp_pct,
        );

        // 8. Process signals
        for signal in signals {
            if self.tracker.has_position(&signal.symbol, &format!("{:?}", signal.side)) {
                continue;
            }
            self.process_signal(signal, &account).await?;
        }

        Ok(())
    }

    async fn process_signal(&self, signal: TradeSignal, account: &AccountState) -> Result<(), Box<dyn std::error::Error>> {
        // Log signal
        let _ = self.repo.log_signal(
            &signal.symbol,
            &format!("{:?}", signal.side),
            signal.confidence,
            &signal.supporting_traders,
            signal.avg_entry_price,
            false,
            "",
        ).await;

        // Pre-trade checks
        let (ok, reason) = self.filters.check(&signal).await;
        if !ok {
            info!("Entry rejected [{}]: {}", signal.position_key(), reason);
            return Ok(());
        }

        // Enter position
        match self.order_mgr.enter_position(&signal, account).await {
            Ok(Some(pos)) => {
                let sl_price = self.exit_mgr.compute_sl_price(pos.entry_price, &signal.side);
                let tp_price = self.exit_mgr.compute_tp_price(pos.entry_price, &signal.side);
                self.notifier.on_entry(&pos.symbol, &pos.side, pos.quantity, pos.entry_price, sl_price, tp_price);
                
                let _ = self.repo.open_trade(
                    &pos.symbol,
                    &pos.side,
                    pos.entry_price,
                    pos.quantity,
                    pos.leverage,
                    signal.confidence,
                    &signal.supporting_traders,
                ).await;
            },
            Ok(None) => {},
            Err(e) => error!("Entry failed: {}", e),
        }

        Ok(())
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    dotenv().ok();
    
    let subscriber = FmtSubscriber::builder()
        .with_max_level(Level::INFO)
        .finish();
    tracing::subscriber::set_global_default(subscriber)?;

    let bot = CopyTrader::new("config.yaml").await?;
    bot.start().await;

    Ok(())
}
