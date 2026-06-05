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
