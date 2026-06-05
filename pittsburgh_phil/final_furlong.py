"""
Final furlong (last 2 furlongs) scoring.
Pittsburgh Phil: "The final eighth of a mile reveals a horse's true class."
A horse that accelerates through the stretch — rather than merely hanging on —
is a horse with reserves. This module scores closing kick from final_2f_figure
fields in past race data.
"""
from .speed_figures import CONDITION_ADJUSTMENTS, SURFACE_ADJUSTMENT, weighted_speed_figure


def _adjust_ff_figure(raw: int, condition: str, past_surf: str, curr_surf: str) -> float:
    """Condition + surface adjustment for final furlong figures."""
    return (raw
            + CONDITION_ADJUSTMENTS.get(condition.lower(), 0)
            + SURFACE_ADJUSTMENT.get((past_surf.lower(), curr_surf.lower()), -3))


def final_furlong_score(past_races: list[dict], current_surface: str,
                        lookback: int = 5, decay: float = 0.85) -> float:
    """
    Weighted average of adjusted final-2f figures from recent races.
    Higher = stronger closing kick = better suited to long-stretch tracks like Belmont.
    """
    adjusted = []
    for race in past_races[:lookback]:
        raw = race.get("final_2f_figure", 0)
        if raw <= 0:
            continue
        adj = _adjust_ff_figure(raw, race.get("track_condition", "fast"),
                                race.get("surface", current_surface), current_surface)
        adjusted.append(adj)

    if not adjusted:
        return 0.0

    return weighted_speed_figure(adjusted, decay)


def closer_kick_rating(past_races: list[dict], current_surface: str,
                       lookback: int = 5) -> float:
    """
    Measures the DIFFERENTIAL between final-2f figure and overall speed figure.
    Positive = horse accelerates late (true closer with kick).
    Negative = horse decelerates (front-runner who fades).
    """
    diffs = []
    for race in past_races[:lookback]:
        ff = race.get("final_2f_figure", 0)
        spd = race.get("speed_figure", 0)
        if ff > 0 and spd > 0:
            diffs.append(ff - spd)

    if not diffs:
        return 0.0

    return sum(diffs) / len(diffs)
