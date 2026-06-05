from typing import Optional

# Pace style labels
EARLY = "E"    # Front runner — leads or near lead from start
PRESSER = "P"  # Races close to pace, 2-3 lengths off lead
STALKER = "S"  # Midpack, saves ground
CLOSER = "C"   # Dead last early, big late kick
UNKNOWN = "?"


def classify_pace_style(past_races: list[dict]) -> str:
    """Classify a horse's running style from its past performance pace figures."""
    if not past_races:
        return UNKNOWN

    e2_list = [r.get("e2_pace_figure", 0) for r in past_races if r.get("e2_pace_figure")]
    lp_list = [r.get("lp_figure", 0) for r in past_races if r.get("lp_figure")]

    if not e2_list or not lp_list:
        return UNKNOWN

    avg_e2 = sum(e2_list) / len(e2_list)
    avg_lp = sum(lp_list) / len(lp_list)
    ratio = avg_e2 / avg_lp if avg_lp else 1.0

    if ratio >= 1.10:
        return EARLY
    elif ratio >= 1.03:
        return PRESSER
    elif ratio >= 0.97:
        return STALKER
    else:
        return CLOSER


def pace_scenario(field_styles: list[str]) -> str:
    """
    Assess the pace scenario for a race based on the distribution of running styles.
    HOT = many speed horses → favors closers
    SLOW = no early speed → front runners can steal
    CONTESTED = 2 speed horses, balanced field
    NORMAL = typical pace setup
    """
    early_count = field_styles.count(EARLY)
    presser_count = field_styles.count(PRESSER)
    closer_count = field_styles.count(CLOSER)

    total = len(field_styles)
    if total == 0:
        return "UNKNOWN"

    speed_fraction = (early_count + presser_count) / total
    closer_fraction = closer_count / total

    if early_count >= 3 or speed_fraction >= 0.55:
        return "HOT"
    elif early_count == 0 and presser_count <= 1:
        return "SLOW"
    elif early_count == 2:
        return "CONTESTED"
    else:
        return "NORMAL"


# Pace advantage multipliers by style × scenario
# Positive = bonus, negative = penalty
PACE_ADVANTAGE: dict[tuple[str, str], float] = {
    (EARLY,    "HOT"):       -6.0,
    (EARLY,    "SLOW"):      +5.0,
    (EARLY,    "CONTESTED"): -3.0,
    (EARLY,    "NORMAL"):    +1.0,
    (PRESSER,  "HOT"):       -2.0,
    (PRESSER,  "SLOW"):      +3.0,
    (PRESSER,  "CONTESTED"): -1.0,
    (PRESSER,  "NORMAL"):    +1.5,
    (STALKER,  "HOT"):       +2.0,
    (STALKER,  "SLOW"):      -1.0,
    (STALKER,  "CONTESTED"): +1.0,
    (STALKER,  "NORMAL"):    +0.5,
    (CLOSER,   "HOT"):       +5.0,
    (CLOSER,   "SLOW"):      -3.0,
    (CLOSER,   "CONTESTED"): +2.0,
    (CLOSER,   "NORMAL"):    +0.0,
    (UNKNOWN,  "HOT"):        0.0,
    (UNKNOWN,  "SLOW"):       0.0,
    (UNKNOWN,  "CONTESTED"):  0.0,
    (UNKNOWN,  "NORMAL"):     0.0,
}


def pace_score(
    past_races: list[dict],
    pace_style: str,
    scenario: str,
    distance_furlongs: float,
) -> float:
    """
    Combined pace score for a horse in a given race scenario.
    Longer routes amplify the pace scenario effect (pace matters more at 1.5m than 6f).
    """
    base = PACE_ADVANTAGE.get((pace_style, scenario), 0.0)

    # Route multiplier: pace effects are stronger in longer races
    if distance_furlongs >= 12:  # 1.5 miles — Belmont distance
        distance_mult = 1.40
    elif distance_furlongs >= 9:
        distance_mult = 1.20
    elif distance_furlongs >= 8:
        distance_mult = 1.10
    else:
        distance_mult = 1.00

    # LP figure quality — horses with strong late pace benefit more in HOT scenarios
    lp_figs = [r.get("lp_figure", 0) for r in past_races if r.get("lp_figure")]
    avg_lp = sum(lp_figs) / len(lp_figs) if lp_figs else 80.0
    lp_bonus = (avg_lp - 80.0) * 0.05  # +0.05 per point above 80

    return base * distance_mult + lp_bonus
