"""
Pittsburgh Phil's Racing Maxims
Source: "Racing Maxims and Methods of Pittsburgh Phil" — Edward Cole, 1908

These maxims are evaluated as named flags that surface in the report alongside
the numeric model. They don't replace the model — they explain it.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MaximFlag:
    code: str
    label: str
    triggered: bool
    bullish: bool   # True = positive signal, False = negative/warning
    note: str = ""


def _ml_to_decimal(ml: str) -> float:
    if "-" not in ml:
        return float(ml) + 1.0
    n, d = ml.split("-")
    return float(n) / float(d) + 1.0


def evaluate(
    horse: dict,
    past_races: list[dict],
    career_best_beyer: int,
    race_date: str,
    race: dict,
    bounce_triggered: bool,
    sol_triggered: bool,
    model_prob: float,
    market_prob: float,
) -> list[MaximFlag]:
    flags: list[MaximFlag] = []

    # M1 — The Bounce
    # "The horse that just ran his best is the one most likely to disappoint next."
    flags.append(MaximFlag(
        code="M1", label="Peak Beyer Bounce",
        triggered=bounce_triggered, bullish=False,
        note="Ran career-best Beyer last out within 5 weeks — expect regression."
        if bounce_triggered else "",
    ))

    # M2 — Second Off Layoff
    # "A horse needs one race to regain its edge after a long absence."
    flags.append(MaximFlag(
        code="M2", label="2nd Off Layoff",
        triggered=sol_triggered, bullish=True,
        note="First race back was a tightener — arrives sharp and fit today."
        if sol_triggered else "",
    ))

    # M3 — Trouble Last Out
    # "A horse that met interference is better than the chart shows."
    comment = past_races[0].get("comment", "").lower() if past_races else ""
    trouble_words = ("trouble", "checked", "blocked", "bumped", "wide", "shuffled",
                     "steadied", "traffic", "interfered", "clipped", "altered")
    trouble = any(w in comment for w in trouble_words)
    flags.append(MaximFlag(
        code="M3", label="Trouble Last Out",
        triggered=trouble, bullish=True,
        note=f"Encountered trouble last race: \"{past_races[0].get('comment', '')}\"."
        if trouble else "",
    ))

    # M4 — Class Dropper
    # "A horse dropping in class has a decisive advantage — bet it accordingly."
    from .class_analyzer import class_rating
    last_class = past_races[0].get("class_level", "") if past_races else ""
    curr_class = race.get("class_level", "")
    class_drop = class_rating(last_class) > class_rating(curr_class) + 5 if last_class and curr_class else False
    flags.append(MaximFlag(
        code="M4", label="Class Dropper",
        triggered=class_drop, bullish=True,
        note=f"Dropping from {last_class} to {curr_class}." if class_drop else "",
    ))

    # M5 — Overlay Detected
    # "The foundation of profitable betting is the overlay."
    overlay = (model_prob - market_prob) / market_prob if market_prob > 0 else 0
    is_overlay = overlay >= 0.15
    flags.append(MaximFlag(
        code="M5", label="Overlay",
        triggered=is_overlay, bullish=True,
        note=f"Model ({model_prob*100:.1f}%) exceeds market ({market_prob*100:.1f}%) by {overlay*100:.0f}%."
        if is_overlay else "",
    ))

    # M6 — Public Underlay (fade signal)
    # "Never lay against a horse that the public has clearly underestimated."
    is_underlay = (market_prob - model_prob) / market_prob > 0.25 if market_prob > 0 else False
    flags.append(MaximFlag(
        code="M6", label="Public Underlay",
        triggered=is_underlay, bullish=False,
        note=f"Public money ({market_prob*100:.1f}%) well above our model ({model_prob*100:.1f}%). Avoid."
        if is_underlay else "",
    ))

    # M7 — Sharp Combo (established jockey/trainer partnership)
    combo_pct = horse.get("trainer_jockey_combo_pct", 0)
    combo_starts = horse.get("trainer_jockey_combo_starts", 0)
    sharp_combo = combo_pct >= 0.25 and combo_starts >= 10
    flags.append(MaximFlag(
        code="M7", label="Sharp Combo",
        triggered=sharp_combo, bullish=True,
        note=f"{horse.get('jockey', '')} / {horse.get('trainer', '')} win {combo_pct*100:.0f}% together ({combo_starts} starts)."
        if sharp_combo else "",
    ))

    # M8 — Surface First-Timer
    # "Specialists on unusual surfaces are mysteries — tread with caution."
    current_surface = race.get("surface", "dirt")
    surfaces_run = [r.get("surface", "") for r in past_races]
    never_on_surface = past_races and not any(s == current_surface for s in surfaces_run)
    flags.append(MaximFlag(
        code="M8", label="Surface First-Timer",
        triggered=never_on_surface, bullish=False,
        note=f"No record on {current_surface} — uncertain quantity."
        if never_on_surface else "",
    ))

    # M9 — Improving Form (3-race positive trend)
    # "Back the horse on the upgrade, not the one at the top of its form."
    if len(past_races) >= 3:
        figs = [r.get("speed_figure", 0) for r in past_races[:3]]
        improving = figs[0] > figs[1] > figs[2]
    else:
        improving = False
    flags.append(MaximFlag(
        code="M9", label="Improving Form",
        triggered=improving, bullish=True,
        note="Three consecutive improving Beyer figures — horse trending up."
        if improving else "",
    ))

    # M10 — Closer in Long Route (Belmont-specific)
    # "The final quarter reveals true stamina. Give the nod to the horse who finishes."
    from .pace_analyzer import classify_pace_style, CLOSER, STALKER
    pace_style = classify_pace_style(past_races)
    is_route = race.get("distance_furlongs", 8.0) >= 10.0
    closer_in_route = pace_style in (CLOSER, STALKER) and is_route
    flags.append(MaximFlag(
        code="M10", label="Closer/Stalker in Long Route",
        triggered=closer_in_route, bullish=True,
        note=f"Running style ({pace_style}) suits the extended {race.get('distance_furlongs')}f distance."
        if closer_in_route else "",
    ))

    return flags
