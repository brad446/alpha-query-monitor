from typing import Optional

# Higher = more competitive class
CLASS_RATINGS: dict[str, float] = {
    "G1": 100.0,
    "G2": 95.0,
    "G3": 90.0,
    "Listed": 86.0,
    "AOC": 83.0,
    "N3X": 81.0,
    "N2X": 79.0,
    "N1X": 77.0,
    "Allowance": 75.0,
    "CLM_50000": 74.0,
    "CLM_40000": 72.0,
    "CLM_30000": 70.0,
    "CLM_25000": 68.0,
    "CLM_20000": 66.0,
    "CLM_15000": 63.0,
    "CLM_10000": 59.0,
    "MSW": 65.0,
    "MCL_25000": 55.0,
    "MCL_15000": 51.0,
    "MCL_10000": 47.0,
}


def class_rating(level: str) -> float:
    """Return numeric class rating for a race class string."""
    return CLASS_RATINGS.get(level, 65.0)


def class_delta(past_class: str, current_class: str) -> float:
    """
    How much harder is the current race vs. last race?
    Positive = moving up in class (horse faces tougher competition).
    Negative = dropping down (easier spot).
    Normalized to roughly -1 to +1 range.
    """
    prev = class_rating(past_class)
    curr = class_rating(current_class)
    return (curr - prev) / 25.0


def highest_class_beaten(past_races: list[dict], finish_threshold: int = 3) -> float:
    """Return the class rating of the best race the horse finished in the money."""
    best = 0.0
    for race in past_races:
        if race.get("finish", 99) <= finish_threshold:
            level = race.get("class_level", "")
            rating = class_rating(level)
            if rating > best:
                best = rating
    return best


def class_score(past_races: list[dict], current_class: str, lookback: int = 5) -> float:
    """
    Composite class score combining:
    - Best class successfully competed at (60%)
    - Class delta from most recent race (40%, inverted — dropping down is a positive)
    """
    if not past_races:
        return 50.0

    recent = past_races[:lookback]
    best_beaten = highest_class_beaten(recent, finish_threshold=4)

    last_class = recent[0].get("class_level", "Allowance")
    delta = class_delta(last_class, current_class)

    # Dropping in class = positive signal; raising = negative
    class_change_bonus = -delta * 5  # up to ±2 points

    return best_beaten + class_change_bonus
