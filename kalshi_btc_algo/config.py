"""
Central configuration. All env vars are read here; everything else imports from this module.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, default))


def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


@dataclass
class KalshiConfig:
    email: str = field(default_factory=lambda: _env("KALSHI_EMAIL", ""))
    password: str = field(default_factory=lambda: _env("KALSHI_PASSWORD", ""))
    # dry_run=True: reads real market data but never places orders
    dry_run: bool = field(default_factory=lambda: _env("DRY_RUN", "true").lower() != "false")
    # Starting balance to simulate in dry-run mode
    simulated_balance: float = field(
        default_factory=lambda: _env_float("SIMULATED_BALANCE", 10000.0)
    )

    @property
    def base_url(self) -> str:
        return "https://trading-api.kalshi.com/trade-api/v2"


@dataclass
class SignalConfig:
    # Only trade when true probability falls in [min, max]
    min_true_probability: float = field(
        default_factory=lambda: _env_float("MIN_TRUE_PROBABILITY", 0.91)
    )
    max_true_probability: float = field(
        default_factory=lambda: _env_float("MAX_TRUE_PROBABILITY", 0.97)
    )
    # Minimum gap between our model probability and the market implied probability
    min_edge: float = field(default_factory=lambda: _env_float("MIN_EDGE", 0.03))
    # Scan interval in seconds
    scan_interval_seconds: int = 30
    # BTC hourly market series ticker on Kalshi (confirmed: KXBTCD)
    btc_series_ticker: str = "KXBTCD"


@dataclass
class RiskConfig:
    kelly_fraction: float = field(
        default_factory=lambda: _env_float("KELLY_FRACTION", 0.25)
    )
    max_bankroll_pct_per_trade: float = field(
        default_factory=lambda: _env_float("MAX_BANKROLL_PCT_PER_TRADE", 0.02)
    )
    max_open_positions: int = field(
        default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 5)
    )
    daily_loss_limit_pct: float = field(
        default_factory=lambda: _env_float("DAILY_LOSS_LIMIT_PCT", 0.05)
    )
    drawdown_limit_pct: float = field(
        default_factory=lambda: _env_float("DRAWDOWN_LIMIT_PCT", 0.10)
    )
    # Minimum contracts to bother placing (Kalshi minimum is 1)
    min_contracts: int = 1
    # Hard cap per single trade in dollars regardless of Kelly
    max_dollars_per_trade: float = 500.0


@dataclass
class VolatilityConfig:
    # Number of recent hourly BTC returns to use for vol estimation
    lookback_hours: int = 72
    # Minimum hours of data before trading
    min_data_hours: int = 24
    # Annualization factor for hourly data
    annual_factor: float = 8760.0


@dataclass
class Config:
    kalshi: KalshiConfig = field(default_factory=KalshiConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    volatility: VolatilityConfig = field(default_factory=VolatilityConfig)
    db_path: str = "btc_algo.db"
    log_level: str = "INFO"


# Singleton — import this everywhere
config = Config()
