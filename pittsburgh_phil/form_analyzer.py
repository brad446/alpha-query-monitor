from datetime import datetime
from typing import Optional


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def days_between(date_str_a: str, date_str_b: str) -> Optional[int]:
    a, b = _parse_date(date_str_a), _parse_date(date_str_b)
    if a and b:
        return abs((b - a).days)
    return None


def days_since_last_race(past_races: list[dict], race_date: str) -> Optional[int]:
    if not past_races:
        return None
    return days_between(past_races[0].get("date", ""), race_date)


def freshness_factor(days_off: Optional[int]) -> float:
    if days_off is None:       return -1.0
    if days_off < 14:          return -2.0   # May still be flat from hard effort
    if days_off <= 28:         return +2.0   # Ideal cycle
    if days_off <= 42:         return +1.0   # Still fresh
    if days_off <= 60:         return -1.0   # Slight rust
    return 0.0  # Longer layoff handled separately by second_off_layoff


def second_off_layoff(past_races: list[dict], race_date: str,
                      layoff_days: int = 60, return_window: int = 45) -> tuple[bool, float]:
    """
    Pittsburgh Phil: The SECOND start after a long layoff is often the horse's best.
    The first race back shakes off the rust; the second they arrive fit and sharp.

    Condition:
      - Gap between past_races[1] → past_races[0] >= layoff_days (the layoff period)
      - Gap between past_races[0] → race_date    <= return_window (normal spacing)

    Returns (triggered: bool, bonus: float).
    """
    if len(past_races) < 2:
        return False, 0.0

    gap_layoff = days_between(past_races[1].get("date", ""), past_races[0].get("date", ""))
    gap_return = days_between(past_races[0].get("date", ""), race_date)

    if gap_layoff is None or gap_return is None:
        return False, 0.0

    if gap_layoff >= layoff_days and gap_return <= return_window:
        # Larger bonus the longer the layoff (they've had plenty of time to freshen)
        bonus = 4.0 if gap_layoff < 120 else 6.0
        return True, bonus

    return False, 0.0


def finish_trend(past_races: list[dict], lookback: int = 3) -> float:
    recent = past_races[:lookback]
    if len(recent) < 2:
        return 0.0
    positions = [r.get("finish", 99) for r in recent]
    flipped = [100 - p for p in positions]
    mid = max(len(flipped) // 2, 1)
    early_avg = sum(flipped[mid:]) / len(flipped[mid:])
    recent_avg = sum(flipped[:mid]) / len(flipped[:mid])
    return (recent_avg - early_avg) * 0.5


def trouble_last_out(past_races: list[dict]) -> float:
    """Horse encountered trouble last race → likely better than finish shows."""
    if not past_races:
        return 0.0
    comment = past_races[0].get("comment", "").lower()
    keywords = ("trouble", "checked", "blocked", "bumped", "wide", "shuffled",
                 "steadied", "traffic", "interfered", "clipped")
    if any(k in comment for k in keywords):
        return 2.5
    return 0.0


def form_score(past_races: list[dict], race_date: str,
               layoff_threshold: int = 60) -> tuple[float, bool, float]:
    """
    Composite form score.
    Returns (score, second_off_layoff_triggered, second_off_layoff_bonus).
    """
    days_off = days_since_last_race(past_races, race_date)
    fresh = freshness_factor(days_off)
    trend = finish_trend(past_races)
    trouble = trouble_last_out(past_races)
    sol_triggered, sol_bonus = second_off_layoff(past_races, race_date, layoff_threshold)

    score = fresh + trend + trouble + sol_bonus
    return score, sol_triggered, sol_bonus
