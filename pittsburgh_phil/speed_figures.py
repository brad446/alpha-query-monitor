from datetime import datetime
from typing import Optional

CONDITION_ADJUSTMENTS = {
    "fast": 0, "good": -1, "good_to_firm": 1, "firm": 2,
    "yielding": -3, "soft": -5, "heavy": -8,
    "sloppy": -2, "muddy": -3, "wet_fast": -1, "frozen": -2,
}

SURFACE_ADJUSTMENT = {
    ("dirt", "dirt"): 0, ("turf", "turf"): 0, ("synthetic", "synthetic"): 0,
    ("dirt", "turf"): -3, ("turf", "dirt"): -6,   # turf-to-dirt is harder to translate
    ("synthetic", "dirt"): -2, ("dirt", "synthetic"): -2,
    ("turf", "synthetic"): -2, ("synthetic", "turf"): -2,
}


def _distance_adj(past_f: float, current_f: float) -> float:
    diff = abs(current_f - past_f)
    if diff <= 1:   return 0.0
    if diff <= 2:   return -1.0
    if diff <= 4:   return -2.5
    return -4.0


def adjust_figure(raw: int, condition: str, past_surf: str, curr_surf: str,
                  past_f: float, curr_f: float) -> float:
    return (raw
            + CONDITION_ADJUSTMENTS.get(condition.lower(), 0)
            + SURFACE_ADJUSTMENT.get((past_surf.lower(), curr_surf.lower()), -3)
            + _distance_adj(past_f, curr_f))


def weighted_speed_figure(figures: list[float], decay: float = 0.85) -> float:
    if not figures:
        return 0.0
    weights = [decay ** i for i in range(len(figures))]
    return sum(f * w for f, w in zip(figures, weights)) / sum(weights)


def best_n_average(figures: list[float], n: int = 2) -> float:
    if not figures:
        return 0.0
    top = sorted(figures, reverse=True)[:n]
    return sum(top) / len(top)


def composite_speed_rating(past_races: list[dict], current_surface: str,
                           current_furlongs: float, lookback: int = 5,
                           decay: float = 0.85) -> float:
    if not past_races:
        return 0.0
    adjusted = []
    for race in past_races[:lookback]:
        raw = race.get("speed_figure", 0)
        if raw <= 0:
            continue
        adj = adjust_figure(raw, race.get("track_condition", "fast"),
                            race.get("surface", current_surface), current_surface,
                            race.get("distance_furlongs", current_furlongs), current_furlongs)
        adjusted.append(adj)
    if not adjusted:
        return 0.0
    return 0.60 * weighted_speed_figure(adjusted, decay) + 0.40 * best_n_average(adjusted, 2)


def peak_beyer_bounce(past_races: list[dict], career_best_beyer: int,
                      race_date: str, weeks: int = 5) -> tuple[bool, float]:
    """
    Pittsburgh Phil Maxim: A horse that just ran its ALL-TIME BEST Beyer will BOUNCE
    (regress) in the next start. The all-out effort cannot be reproduced immediately.

    Returns (bounce_triggered: bool, penalty: float).
    Penalty is NEGATIVE — it is subtracted from the speed component.
    """
    if not past_races or career_best_beyer <= 0:
        return False, 0.0

    last_race = past_races[0]
    last_fig = last_race.get("speed_figure", 0)

    # Is the last race at or near career best? (within 1 point — could be a tie)
    if last_fig < career_best_beyer - 1:
        return False, 0.0

    try:
        race_dt = datetime.strptime(race_date, "%Y-%m-%d")
        last_dt = datetime.strptime(last_race.get("date", ""), "%Y-%m-%d")
        days_ago = (race_dt - last_dt).days
    except ValueError:
        return False, 0.0

    if days_ago <= weeks * 7:
        # Penalty scales with how much above their recent average the peak was
        recent_figs = [r.get("speed_figure", 0) for r in past_races[1:4] if r.get("speed_figure")]
        avg_recent = sum(recent_figs) / len(recent_figs) if recent_figs else last_fig - 5
        peak_jump = last_fig - avg_recent
        penalty = max(5.0, min(12.0, peak_jump * 0.9))  # 5–12 point penalty
        return True, -penalty

    return False, 0.0
