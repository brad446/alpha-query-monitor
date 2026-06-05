"""
Exotic bet calculator — Exacta, Trifecta, Superfecta.
Pittsburgh Phil was famous for building overlays into exacta and trifecta tickets,
targeting races where the public's chalk-heavy betting left the exotics undervalued.

Fair value math:
  P(A-B exacta)      = P_A × P_B / (1 - P_A)
  P(A-B-C trifecta)  = P_A × P_B/(1-P_A) × P_C/(1-P_A-P_B)
  P(A-B-C-D super4)  = extend the chain
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExoticBet:
    bet_type: str           # "Exacta", "Trifecta", "Superfecta"
    horses: list[str]       # Horse names in finish order
    posts: list[int]
    model_prob: float       # Our estimated probability
    fair_value_odds: float  # 1 / model_prob  (what we'd need to break even)
    ml_implied_odds: float  # Market-implied fair value
    edge: float             # (model_prob - ml_prob) / ml_prob
    kelly_bet: float        # Suggested wager
    overlay: bool


def _chain_prob(probs: list[float], indices: list[int]) -> float:
    """Compute the probability of a specific finishing order."""
    remaining = 1.0
    p = 1.0
    used = 0.0
    for idx in indices:
        if remaining <= 0:
            return 0.0
        p_i = probs[idx] / remaining
        p *= p_i
        used += probs[idx]
        remaining -= probs[idx]
    return p


def _ml_implied_prob_order(market_probs: list[float], indices: list[int]) -> float:
    """ML-implied probability of a specific finish order."""
    return _chain_prob(market_probs, indices)


def _kelly_exotic(model_p: float, fair_value_odds: float, bankroll: float,
                  kelly_fraction: float = 0.10, max_fraction: float = 0.02) -> float:
    b = fair_value_odds - 1.0  # net profit per $1
    q = 1 - model_p
    if b <= 0 or model_p <= 0:
        return 0.0
    full_kelly = (b * model_p - q) / b
    if full_kelly <= 0:
        return 0.0
    return min(full_kelly * kelly_fraction * bankroll, bankroll * max_fraction)


def exacta_recommendations(
    horses: list[dict],  # list of HorseRating-like dicts with name, post, model_prob, market_prob
    bankroll: float,
    top_n: int = 4,
    min_edge: float = 0.20,
    kelly_fraction: float = 0.10,
    max_fraction: float = 0.02,
) -> list[ExoticBet]:
    """Top N horses form the universe; evaluate all directional pairs."""
    field = horses[:top_n]
    results = []
    probs = [h["model_prob"] for h in field]
    mkt   = [h["market_prob"] for h in field]

    for i in range(len(field)):
        for j in range(len(field)):
            if i == j:
                continue
            model_p = _chain_prob(probs, [i, j])
            ml_p    = _ml_implied_prob_order(mkt, [i, j])
            if model_p <= 0 or ml_p <= 0:
                continue
            fv_odds = 1.0 / model_p
            ml_odds = 1.0 / ml_p
            edge    = (model_p - ml_p) / ml_p
            bet     = _kelly_exotic(model_p, fv_odds, bankroll, kelly_fraction, max_fraction) if edge >= min_edge else 0.0
            results.append(ExoticBet(
                bet_type="Exacta",
                horses=[field[i]["name"], field[j]["name"]],
                posts=[field[i]["post"], field[j]["post"]],
                model_prob=round(model_p, 5),
                fair_value_odds=round(fv_odds, 1),
                ml_implied_odds=round(ml_odds, 1),
                edge=round(edge, 4),
                kelly_bet=round(bet, 2),
                overlay=edge >= min_edge,
            ))

    results.sort(key=lambda x: x.edge, reverse=True)
    return [r for r in results if r.overlay]


def trifecta_key(
    horses: list[dict],
    key_idx: int,       # index within horses list to key on top
    bankroll: float,
    min_edge: float = 0.30,
    kelly_fraction: float = 0.10,
    max_fraction: float = 0.015,
) -> list[ExoticBet]:
    """Key one horse to win, combine all pairs from rest for 2nd/3rd."""
    if len(horses) < 3:
        return []
    probs = [h["model_prob"] for h in horses]
    mkt   = [h["market_prob"] for h in horses]
    others = [i for i in range(len(horses)) if i != key_idx]
    results = []

    for j in others:
        for k in others:
            if j == k:
                continue
            indices = [key_idx, j, k]
            model_p = _chain_prob(probs, indices)
            ml_p    = _ml_implied_prob_order(mkt, indices)
            if model_p <= 0 or ml_p <= 0:
                continue
            fv_odds = 1.0 / model_p
            edge    = (model_p - ml_p) / ml_p
            bet     = _kelly_exotic(model_p, fv_odds, bankroll, kelly_fraction, max_fraction) if edge >= min_edge else 0.0
            results.append(ExoticBet(
                bet_type="Trifecta",
                horses=[horses[i]["name"] for i in indices],
                posts=[horses[i]["post"] for i in indices],
                model_prob=round(model_p, 6),
                fair_value_odds=round(fv_odds, 1),
                ml_implied_odds=round(1.0 / ml_p, 1),
                edge=round(edge, 4),
                kelly_bet=round(bet, 2),
                overlay=edge >= min_edge,
            ))

    results.sort(key=lambda x: x.edge, reverse=True)
    return [r for r in results if r.overlay][:8]


def superfecta_box(
    horses: list[dict],
    top_n: int = 4,
    bankroll: float = 10000,
    min_edge: float = 0.40,
    kelly_fraction: float = 0.08,
    max_fraction: float = 0.01,
) -> list[ExoticBet]:
    """Box top N horses in superfecta — evaluate all 4! = 24 permutations."""
    from itertools import permutations
    field = horses[:top_n]
    if len(field) < 4:
        return []

    probs = [h["model_prob"] for h in field]
    mkt   = [h["market_prob"] for h in field]
    results = []

    for perm in permutations(range(len(field))):
        model_p = _chain_prob(probs, list(perm))
        ml_p    = _ml_implied_prob_order(mkt, list(perm))
        if model_p <= 0 or ml_p <= 0:
            continue
        fv_odds = 1.0 / model_p
        edge    = (model_p - ml_p) / ml_p
        bet     = _kelly_exotic(model_p, fv_odds, bankroll, kelly_fraction, max_fraction) if edge >= min_edge else 0.0
        results.append(ExoticBet(
            bet_type="Superfecta",
            horses=[field[i]["name"] for i in perm],
            posts=[field[i]["post"] for i in perm],
            model_prob=round(model_p, 7),
            fair_value_odds=round(fv_odds, 1),
            ml_implied_odds=round(1.0 / ml_p, 1) if ml_p > 0 else 999.0,
            edge=round(edge, 4),
            kelly_bet=round(bet, 2),
            overlay=edge >= min_edge,
        ))

    results.sort(key=lambda x: x.edge, reverse=True)
    return [r for r in results if r.overlay][:6]


def build_exotic_ticket(
    analysis_horses: list,  # HorseRating objects sorted by composite
    bankroll: float,
    config,
) -> dict:
    """
    Build a complete exotic ticket for a race using the model rankings.
    Returns dict with exacta, trifecta, superfecta recommendations.
    """
    # Convert HorseRating objects to dicts for the calculator
    field = [
        {"name": h.name, "post": h.post,
         "model_prob": h.model_prob, "market_prob": h.market_prob}
        for h in analysis_horses
    ]

    exactas = exacta_recommendations(
        field, bankroll,
        top_n=min(5, len(field)),
        min_edge=config.handicapping.min_edge_exotic,
        kelly_fraction=config.bankroll.kelly_fraction_exotic,
        max_fraction=config.bankroll.max_exotic_fraction,
    )

    # Key the top-rated horse in trifectas
    trifectas = trifecta_key(
        field[:6], key_idx=0, bankroll=bankroll,
        min_edge=config.handicapping.min_edge_exotic + 0.05,
        kelly_fraction=config.bankroll.kelly_fraction_exotic,
        max_fraction=config.bankroll.max_exotic_fraction * 0.75,
    )

    superfectas = superfecta_box(
        field, top_n=4, bankroll=bankroll,
        min_edge=config.handicapping.min_edge_exotic + 0.15,
        kelly_fraction=config.bankroll.kelly_fraction_exotic * 0.8,
        max_fraction=config.bankroll.max_exotic_fraction * 0.5,
    )

    return {"exactas": exactas, "trifectas": trifectas, "superfectas": superfectas}
