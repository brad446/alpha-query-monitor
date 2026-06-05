import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class HandicappingWeights:
    # Pittsburgh Phil model weights — must sum to 1.0
    speed: float = 0.25          # Beyer speed figs (bounce-adjusted)
    final_furlong: float = 0.20  # Closing kick in final 2f
    pace_fit: float = 0.20       # Running style vs. race pace scenario
    connections: float = 0.15    # Jockey/trainer combo stats
    class_form: float = 0.20     # Class appropriateness + form cycle


@dataclass
class HandicappingConfig:
    speed_lookback: int = 5
    speed_decay: float = 0.85
    power_k: float = 2.0
    min_edge_win: float = 0.10       # 10% edge minimum for win bets
    min_edge_exotic: float = 0.25    # 25% edge minimum for exotic recommendations
    peak_beyer_weeks: int = 5        # Window for bounce detection
    layoff_threshold_days: int = 60  # Days off that constitute a layoff
    weights: HandicappingWeights = field(default_factory=HandicappingWeights)


@dataclass
class BankrollConfig:
    starting_bankroll: float = float(os.getenv("STARTING_BANKROLL", "10000"))
    kelly_fraction: float = float(os.getenv("KELLY_FRACTION", "0.25"))
    kelly_fraction_exotic: float = float(os.getenv("KELLY_FRACTION_EXOTIC", "0.10"))
    max_bet_fraction: float = float(os.getenv("MAX_BET_FRACTION", "0.05"))
    max_exotic_fraction: float = float(os.getenv("MAX_EXOTIC_FRACTION", "0.02"))
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"


@dataclass
class Config:
    handicapping: HandicappingConfig = field(default_factory=HandicappingConfig)
    bankroll: BankrollConfig = field(default_factory=BankrollConfig)
    race_card_path: str = os.getenv("RACE_CARD_PATH", "races/belmont_2026_race_card.json")
