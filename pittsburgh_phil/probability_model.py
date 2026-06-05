import math
from typing import Optional


def power_ratio_probs(ratings: list[float], k: float = 2.0) -> list[float]:
    """
    Convert composite ratings to win probabilities using the power ratio method.
    Higher k = more separation between top and bottom of field.
    Pittsburgh Phil's framework implicitly used this kind of exponential differentiation.
    """
    floored = [max(r, 0.01) for r in ratings]
    powered = [r ** k for r in floored]
    total = sum(powered)
    return [p / total for p in powered]


def implied_prob_from_odds(decimal_odds: float) -> float:
    """Convert decimal odds (e.g. 6.0 for 5-1) to implied win probability."""
    if decimal_odds <= 1.0:
        return 1.0
    return 1.0 / decimal_odds


def ml_to_decimal(morning_line: str) -> float:
    """
    Convert American morning line string ('5-2', '8-1', '3-5') to decimal odds.
    Decimal odds = net return per $1 bet + $1 stake.
    """
    if "-" not in morning_line:
        return float(morning_line) + 1.0
    parts = morning_line.split("-")
    num, den = float(parts[0]), float(parts[1])
    return (num / den) + 1.0


def overlay_factor(model_prob: float, market_prob: float) -> float:
    """
    Edge as a fraction: how much does our model probability exceed market probability?
    Positive = overlay (we think it's better than the market does).
    """
    if market_prob <= 0:
        return 0.0
    return (model_prob - market_prob) / market_prob


def normalize_with_overround(implied_probs: list[float]) -> list[float]:
    """Remove the bookmaker's overround from implied probabilities."""
    total = sum(implied_probs)
    if total <= 0:
        return [1.0 / len(implied_probs)] * len(implied_probs)
    return [p / total for p in implied_probs]
