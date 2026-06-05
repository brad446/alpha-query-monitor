import json
from pathlib import Path
from typing import Any


def load_race_card(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Race card not found: {path}")
    with p.open() as f:
        data = json.load(f)
    _validate(data)
    return data


def apply_tote_odds(card: dict, tote_csv: str) -> None:
    """
    Override morning line odds with live tote board odds.
    tote_csv format: "race_number,post,odds  race_number,post,odds ..."
    Example: "11,1,4.20 11,2,3.60 11,4,18.00"
    Odds can be decimal ($6.40), fractional (5-2), or slash (5/2).
    """
    from .probability_model import tote_to_decimal

    lookup: dict[tuple[int, int], float] = {}
    for entry in tote_csv.strip().split():
        parts = entry.split(",")
        if len(parts) != 3:
            continue
        race_num, post, odds_str = int(parts[0]), int(parts[1]), parts[2]
        lookup[(race_num, post)] = tote_to_decimal(odds_str)

    if not lookup:
        return

    for race in card["race_card"]["races"]:
        rn = race.get("race_number", 0)
        for horse in race["horses"]:
            pp = horse.get("post_position", 0)
            if (rn, pp) in lookup:
                dec = lookup[(rn, pp)]
                # Store as a decimal string so ml_to_decimal picks it up
                horse["morning_line"] = f"{dec:.2f}"
                horse["_tote_override"] = True


def _validate(data: dict) -> None:
    if "race_card" not in data:
        raise ValueError("Missing top-level 'race_card' key")
    card = data["race_card"]
    for required in ("track", "date", "races"):
        if required not in card:
            raise ValueError(f"Race card missing required field: {required}")
    for race in card["races"]:
        if "horses" not in race or not race["horses"]:
            raise ValueError(f"Race {race.get('race_number', '?')} has no horses")
