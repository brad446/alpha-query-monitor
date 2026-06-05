from dataclasses import dataclass, field
from typing import Optional

from .config import Config
from .speed_figures import composite_speed_rating, peak_beyer_bounce
from .final_furlong import final_furlong_score
from .class_analyzer import class_score
from .pace_analyzer import classify_pace_style, pace_scenario, pace_score
from .form_analyzer import form_score
from .connections import connections_score
from .maxims import MaximFlag, evaluate as evaluate_maxims
from .probability_model import (
    power_ratio_probs, implied_prob_from_odds,
    ml_to_decimal, normalize_with_overround, overlay_factor,
)
from .kelly_sizer import kelly_fraction_bet
from .exotic_calculator import build_exotic_ticket


@dataclass
class HorseRating:
    name: str
    post: int
    pace_style: str
    # Raw component scores (un-normalized, for display)
    speed_raw: float
    ff_raw: float
    pace_raw: float
    connections_raw: float
    class_form_raw: float
    # Normalized (0-100) component scores
    speed_norm: float
    ff_norm: float
    pace_norm: float
    connections_norm: float
    class_form_norm: float
    # Flags
    bounce_triggered: bool
    bounce_penalty: float
    sol_triggered: bool
    sol_bonus: float
    maxims: list[MaximFlag]
    # Final outputs
    composite: float
    model_prob: float
    market_prob: float
    decimal_odds: float
    edge: float
    bet: dict


@dataclass
class RaceAnalysis:
    race_number: int
    race_name: str
    distance_furlongs: float
    surface: str
    class_level: str
    pace_scenario_label: str
    horses: list[HorseRating]
    top_pick: Optional[HorseRating]
    value_picks: list[HorseRating]
    exotics: dict


def _min_max_normalize(values: list[float]) -> list[float]:
    """Scale to 0-100 so every component contributes equally after weighting."""
    mn, mx = min(values), max(values)
    if mx == mn:
        return [50.0] * len(values)
    return [(v - mn) / (mx - mn) * 100.0 for v in values]


def analyze_race(race: dict, config: Config, bankroll: float) -> RaceAnalysis:
    horses_raw = race["horses"]
    surf = race.get("surface", "dirt")
    furlongs = race.get("distance_furlongs", 8.0)
    curr_class = race.get("class_level", "Allowance")
    race_date = race.get("date", "2026-06-07")
    w = config.handicapping.weights
    lookback = config.handicapping.speed_lookback
    decay = config.handicapping.speed_decay

    # ── Step 1: pace styles ─────────────────────────────────────────────────
    for h in horses_raw:
        h["_pace_style"] = classify_pace_style(h.get("past_races", []))

    scenario = pace_scenario([h["_pace_style"] for h in horses_raw])

    # ── Step 2: raw component scores for every horse ────────────────────────
    raw_scores: list[dict] = []
    for h in horses_raw:
        past = h.get("past_races", [])
        cbp  = h.get("career_best_beyer", 0)

        # Speed — with bounce penalty baked in
        spd_base = composite_speed_rating(past, surf, furlongs, lookback, decay)
        bounce_hit, bounce_pen = peak_beyer_bounce(past, cbp, race_date,
                                                    config.handicapping.peak_beyer_weeks)
        spd = spd_base + bounce_pen   # penalty is negative

        # Final furlong
        ff = final_furlong_score(past, surf, lookback, decay)

        # Pace fit
        pac = pace_score(past, h["_pace_style"], scenario, furlongs)

        # Connections
        con = connections_score(
            trainer_win_pct=h.get("trainer_win_pct", 0.18),
            jockey_win_pct=h.get("jockey_win_pct", 0.18),
            trainer_jockey_combo_pct=h.get("trainer_jockey_combo_pct"),
            trainer_distance_win_pct=h.get("trainer_distance_win_pct"),
            combo_starts=h.get("trainer_jockey_combo_starts", 0),
        )

        # Class + form (2nd-off-layoff bonus is inside form_score)
        cls = class_score(past, curr_class, lookback)
        frm, sol_hit, sol_bon = form_score(
            past, race_date, config.handicapping.layoff_threshold_days
        )
        cf = cls + frm   # combined class/form

        raw_scores.append({
            "horse": h,
            "spd": spd, "spd_base": spd_base,
            "ff": ff, "pac": pac, "con": con, "cf": cf,
            "bounce_hit": bounce_hit, "bounce_pen": bounce_pen,
            "sol_hit": sol_hit, "sol_bon": sol_bon,
        })

    # ── Step 3: field-level normalization (0-100 per component) ────────────
    def norm(key):
        vals = [s[key] for s in raw_scores]
        return _min_max_normalize(vals)

    spd_n  = norm("spd")
    ff_n   = norm("ff")
    pac_n  = norm("pac")
    con_n  = norm("con")
    cf_n   = norm("cf")

    # ── Step 4: weighted composite ──────────────────────────────────────────
    composites = [
        w.speed * spd_n[i]
        + w.final_furlong * ff_n[i]
        + w.pace_fit * pac_n[i]
        + w.connections * con_n[i]
        + w.class_form * cf_n[i]
        for i in range(len(raw_scores))
    ]

    # ── Step 5: probabilities ───────────────────────────────────────────────
    # Composite is already 0-100, power ratio needs positive values
    probs = power_ratio_probs([max(c, 0.1) for c in composites],
                               k=config.handicapping.power_k)

    ml_odds  = [ml_to_decimal(h.get("morning_line", "10-1")) for h in horses_raw]
    implied  = [implied_prob_from_odds(o) for o in ml_odds]
    fair_mkt = normalize_with_overround(implied)

    # ── Step 6: assemble HorseRating objects ────────────────────────────────
    horse_ratings: list[HorseRating] = []
    for i, rs in enumerate(raw_scores):
        h = rs["horse"]
        model_p  = probs[i]
        market_p = fair_mkt[i]
        edge     = overlay_factor(model_p, market_p)

        # Evaluate maxims (needs model_prob, market_prob already computed)
        maxims = evaluate_maxims(
            horse=h, past_races=h.get("past_races", []),
            career_best_beyer=h.get("career_best_beyer", 0),
            race_date=race_date, race=race,
            bounce_triggered=rs["bounce_hit"],
            sol_triggered=rs["sol_hit"],
            model_prob=model_p, market_prob=market_p,
        )

        bet = kelly_fraction_bet(
            win_prob=model_p, decimal_odds=ml_odds[i], bankroll=bankroll,
            kelly_fraction=config.bankroll.kelly_fraction,
            max_bet_pct=config.bankroll.max_bet_fraction,
            min_edge=config.handicapping.min_edge_win,
        )

        horse_ratings.append(HorseRating(
            name=h.get("name", "Unknown"),
            post=h.get("post_position", i + 1),
            pace_style=h["_pace_style"],
            speed_raw=round(rs["spd_base"], 1),
            ff_raw=round(rs["ff"], 1),
            pace_raw=round(rs["pac"], 1),
            connections_raw=round(rs["con"], 1),
            class_form_raw=round(rs["cf"], 1),
            speed_norm=round(spd_n[i], 1),
            ff_norm=round(ff_n[i], 1),
            pace_norm=round(pac_n[i], 1),
            connections_norm=round(con_n[i], 1),
            class_form_norm=round(cf_n[i], 1),
            bounce_triggered=rs["bounce_hit"],
            bounce_penalty=round(rs["bounce_pen"], 1),
            sol_triggered=rs["sol_hit"],
            sol_bonus=round(rs["sol_bon"], 1),
            maxims=maxims,
            composite=round(composites[i], 2),
            model_prob=round(model_p, 4),
            market_prob=round(market_p, 4),
            decimal_odds=round(ml_odds[i], 2),
            edge=round(edge, 4),
            bet=bet,
        ))

    horse_ratings.sort(key=lambda h: h.composite, reverse=True)

    top_pick    = horse_ratings[0] if horse_ratings else None
    value_picks = [h for h in horse_ratings
                   if h.bet["recommended"] and h.edge >= config.handicapping.min_edge_win]

    exotics = build_exotic_ticket(horse_ratings, bankroll, config)

    return RaceAnalysis(
        race_number=race.get("race_number", 0),
        race_name=race.get("race_name", ""),
        distance_furlongs=furlongs,
        surface=surf,
        class_level=curr_class,
        pace_scenario_label=scenario,
        horses=horse_ratings,
        top_pick=top_pick,
        value_picks=value_picks,
        exotics=exotics,
    )


def analyze_card(card: dict, config: Config, bankroll: float) -> list[RaceAnalysis]:
    results = []
    rc = card["race_card"]
    for race in rc.get("races", []):
        if "date" not in race:
            race["date"] = rc.get("date", "2026-06-07")
        results.append(analyze_race(race, config, bankroll))
    return results
