"""
Log-normal binary probability model for BTC closing price contracts.

For a contract "BTC closes ABOVE K at expiry T hours from now":
  P(S_T > K) = N(d2)
  d2 = [ln(S/K) + (mu - sigma^2/2) * T_yr] / (sigma * sqrt(T_yr))

For "closes AT OR BELOW K":
  P(S_T <= K) = 1 - N(d2) = N(-d2)

This is the risk-neutral binary option price (digital call/put),
equivalent to Black-Scholes d2 under a zero-drift assumption.
"""
import math
import logging
from dataclasses import dataclass
from typing import Optional

from scipy.stats import norm

log = logging.getLogger(__name__)

_HOURS_PER_YEAR = 8760.0


@dataclass
class ProbabilityEstimate:
    true_prob: float          # our model's estimate of P(contract resolves YES)
    implied_prob: float       # market's implied prob (mid of bid/ask)
    edge: float               # true_prob - implied_prob
    sigma_annual: float       # volatility used
    time_to_expiry_hours: float
    strike: float
    spot: float
    direction: str            # "above" or "at_or_below"

    @property
    def has_edge(self) -> bool:
        from .config import config
        return self.edge >= config.signal.min_edge

    @property
    def in_probability_band(self) -> bool:
        from .config import config
        return (
            config.signal.min_true_probability
            <= self.true_prob
            <= config.signal.max_true_probability
        )

    @property
    def is_tradeable(self) -> bool:
        return self.has_edge and self.in_probability_band


def estimate(
    spot: float,
    strike: float,
    time_to_expiry_hours: float,
    sigma_annual: float,
    direction: str = "above",
    mu_annual: float = 0.0,
) -> Optional[ProbabilityEstimate]:
    """
    Compute probability that BTC is above (or at/below) the strike at expiry.

    spot:                 current BTC price (e.g. 67500)
    strike:               contract strike (e.g. 67000)
    time_to_expiry_hours: hours until the hourly close
    sigma_annual:         annualized realized vol (e.g. 0.65 = 65%)
    direction:            "above" → P(S > K); "at_or_below" → P(S <= K)
    mu_annual:            drift; default 0 (conservative, short horizon)
    """
    if spot <= 0 or strike <= 0 or sigma_annual <= 0:
        log.debug("Invalid inputs: spot=%s strike=%s sigma=%s", spot, strike, sigma_annual)
        return None

    if time_to_expiry_hours <= 0:
        # Already expired — but handle gracefully
        prob_above = 1.0 if spot > strike else 0.0
        prob = prob_above if direction == "above" else 1.0 - prob_above
        return ProbabilityEstimate(
            true_prob=prob,
            implied_prob=0.0,
            edge=0.0,
            sigma_annual=sigma_annual,
            time_to_expiry_hours=0.0,
            strike=strike,
            spot=spot,
            direction=direction,
        )

    T = time_to_expiry_hours / _HOURS_PER_YEAR
    log_moneyness = math.log(spot / strike)
    drift_adj = (mu_annual - 0.5 * sigma_annual**2) * T
    vol_sqrt_T = sigma_annual * math.sqrt(T)

    d2 = (log_moneyness + drift_adj) / vol_sqrt_T
    prob_above = float(norm.cdf(d2))

    true_prob = prob_above if direction == "above" else 1.0 - prob_above
    return true_prob  # caller attaches implied_prob and edge


def full_estimate(
    spot: float,
    strike: float,
    time_to_expiry_hours: float,
    sigma_annual: float,
    implied_prob: float,
    direction: str = "above",
    mu_annual: float = 0.0,
) -> Optional[ProbabilityEstimate]:
    """
    Like estimate() but also computes edge vs market implied probability.
    Returns None if inputs are invalid.
    """
    if spot <= 0 or strike <= 0 or sigma_annual <= 0:
        return None

    if time_to_expiry_hours <= 0:
        prob_above = 1.0 if spot > strike else 0.0
        true_prob = prob_above if direction == "above" else 1.0 - prob_above
        return ProbabilityEstimate(
            true_prob=true_prob,
            implied_prob=implied_prob,
            edge=true_prob - implied_prob,
            sigma_annual=sigma_annual,
            time_to_expiry_hours=0.0,
            strike=strike,
            spot=spot,
            direction=direction,
        )

    T = time_to_expiry_hours / _HOURS_PER_YEAR
    log_moneyness = math.log(spot / strike)
    drift_adj = (mu_annual - 0.5 * sigma_annual**2) * T
    vol_sqrt_T = sigma_annual * math.sqrt(T)

    d2 = (log_moneyness + drift_adj) / vol_sqrt_T
    prob_above = float(norm.cdf(d2))
    true_prob = prob_above if direction == "above" else 1.0 - prob_above

    return ProbabilityEstimate(
        true_prob=true_prob,
        implied_prob=implied_prob,
        edge=true_prob - implied_prob,
        sigma_annual=sigma_annual,
        time_to_expiry_hours=time_to_expiry_hours,
        strike=strike,
        spot=spot,
        direction=direction,
    )
