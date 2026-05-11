use thiserror::Error;

#[derive(Error, Debug)]
pub enum CopyTraderError {
    #[error("Config error: {0}")]
    Config(#[from] ConfigError),

    #[error("Exchange error: {0}")]
    Exchange(#[from] ExchangeError),

    #[error("Circuit breaker tripped")]
    CircuitBreakerTripped,

    #[error("Risk limit error: {0}")]
    RiskLimit(String),

    #[error("Data source error: {0}")]
    DataSource(String),

    #[error("Reconciliation error: {0}")]
    Reconciliation(String),

    #[error("Internal error: {0}")]
    Internal(String),
}

#[derive(Error, Debug)]
pub enum ConfigError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("YAML error: {0}")]
    Yaml(#[from] serde_yaml::Error),

    #[error("Validation error: {0}")]
    Validation(String),
}

#[derive(Error, Debug)]
pub enum ExchangeError {
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    #[error("API error: {0}")]
    Api(String),

    #[error("Insufficient balance")]
    InsufficientBalance,

    #[error("Order error: {0}")]
    Order(String),

    #[error("Stop loss registration error (Emergency liquidatation needed): {0}")]
    StopLossRegistration(String),

    #[error("Sign error: {0}")]
    Sign(String),
}
