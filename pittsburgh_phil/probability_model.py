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
    Also handles '$X.XX' tote board format (e.g. '$6.40' = decimal 6.40).
    Decimal odds = net return per $1 bet + $1 stake.
    """
    s = morning_line.strip().lstrip("$")
    # Tote board: bare decimal like "6.40" or "$6.40"
    if "." in s and "-" not in s:
        return float(s)
    if "-" not in s:
        return float(s) + 1.0
    parts = s.split("-")
    num, den = float(parts[0]), float(parts[1])
    return (num / den) + 1.0


def tote_to_decimal(tote_odds: str) -> float:
    """
    Parse live tote board odds to decimal.
    Accepts: '5/2', '5-2', '8.00', '$8.00', '3-5', 'EVN', 'even'
    """
    s = tote_odds.strip().lstrip("$").lower()
    if s in ("evn", "even", "e/v"):
        return 2.0
    if "/" in s:
        parts = s.split("/")
        return float(parts[0]) / float(parts[1]) + 1.0
    return ml_to_decimal(tote_odds)


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
