class CopyTraderError(Exception):
    pass


class ConfigError(CopyTraderError):
    pass


class ExchangeError(CopyTraderError):
    pass


class InsufficientBalanceError(ExchangeError):
    pass


class OrderError(ExchangeError):
    pass


class StopLossRegistrationError(OrderError):
    """SL 주문 등록 실패 — 즉시 포지션 청산해야 함"""
    pass


class CircuitBreakerTrippedError(CopyTraderError):
    pass


class RiskLimitError(CopyTraderError):
    pass


class DataSourceError(CopyTraderError):
    pass


class ReconciliationError(CopyTraderError):
    pass
