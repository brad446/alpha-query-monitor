"""
Cross-race exotic calculator: Daily Double, Pick 3, Pick 4.

Pittsburgh Phil's real edge came from connecting races — building multi-race
tickets where his overlay selections compounded into massive fair-value gaps.
A 40% edge in two consecutive races becomes a ~100% edge in the daily double.

Strategy implemented here:
  - KEY ticket:  1 horse per leg (pure conviction play)
  - SPREAD ticket: top 2-3 per leg (coverage when uncertain in one leg)
  - Single-single-ALL: key two legs, use all in a weaker leg

Fair value math:
  P(DD A-B)     = P_A_win × P_B_win
  P(Pick3 A-B-C) = P_A × P_B × P_C
"""
from dataclasses import dataclass
from itertools import product
from typing import Optional


@dataclass
class CrossRaceLeg:
    race_number: int
    race_name: str
    horses: list[str]    # names selected for this leg
    posts: list[int]
    probs: list[float]   # model win probs for selected horses
    market_probs: list[float]


@dataclass
class CrossRaceBet:
    bet_type: str                   # "Daily Double", "Pick 3"
    legs: list[CrossRaceLeg]
    ticket_label: str               # "KEY", "KEY+1", "SPREAD"
    model_prob: float               # combined probability for this specific ticket
    fair_value_odds: float
    ml_implied_odds: float
    edge_pct: float
    unit_cost: float                # cost for a $1 ticket (= number of combos)
    suggested_bet: float


def _leg_combo_prob(model_probs: list[float]) -> float:
    """Sum of individual win probs across a leg's selections (union approximation)."""
    return sum(model_probs)


def _leg_combo_market_prob(market_probs: list[float]) -> float:
    return sum(market_probs)


def _ticket_prob(legs: list[CrossRaceLeg]) -> tuple[float, float]:
    """Product of each leg's combined probability (model and market)."""
    model_p = 1.0
    mkt_p   = 1.0
    for leg in legs:
        model_p *= _leg_combo_prob(leg.probs)
        mkt_p   *= _leg_combo_market_prob(leg.market_probs)
    return model_p, mkt_p


def _n_combos(legs: list[CrossRaceLeg]) -> int:
    total = 1
    for leg in legs:
        total *= len(leg.horses)
    return total


def _build_bet(bet_type: str, legs: list[CrossRaceLeg],
               label: str, bankroll: float,
               kelly_fraction: float = 0.10,
               max_fraction: float = 0.02) -> Optional[CrossRaceBet]:
    model_p, mkt_p = _ticket_prob(legs)
    if model_p <= 0 or mkt_p <= 0:
        return None

    fv_odds  = 1.0 / model_p
    ml_odds  = 1.0 / mkt_p   # expected payout if the market is wrong about us
    edge_pct = (model_p - mkt_p) / mkt_p * 100

    n_combos = _n_combos(legs)
    unit_cost = float(n_combos)

    # Kelly uses the MARKET-implied payout (ml_odds) as the expected return,
    # not our fair-value odds — Kelly at fair value is always 0 by definition.
    b = ml_odds - 1.0
    q = 1.0 - model_p
    if b <= 0 or model_p <= mkt_p:
        return None
    full_kelly = (b * model_p - q) / b
    if full_kelly <= 0:
        return None

    raw_bet = full_kelly * kelly_fraction * bankroll
    cap     = bankroll * max_fraction
    per_combo_bet = min(raw_bet / n_combos, cap / n_combos)
    per_combo_bet = max(round(per_combo_bet, 0), 1.0)
    total_bet = per_combo_bet * n_combos

    return CrossRaceBet(
        bet_type=bet_type,
        legs=legs,
        ticket_label=label,
        model_prob=round(model_p, 6),
        fair_value_odds=round(fv_odds, 1),
        ml_implied_odds=round(ml_odds, 1),
        edge_pct=round(edge_pct, 1),
        unit_cost=unit_cost,
        suggested_bet=round(total_bet, 0),
    )


def _make_leg(analysis, n: int) -> CrossRaceLeg:
    """Extract top-N horses from a RaceAnalysis for use in a leg."""
    top = analysis.horses[:n]
    return CrossRaceLeg(
        race_number=analysis.race_number,
        race_name=analysis.race_name,
        horses=[h.name for h in top],
        posts=[h.post for h in top],
        probs=[h.model_prob for h in top],
        market_probs=[h.market_prob for h in top],
    )


def build_cross_race_tickets(
    analyses: list,   # list of RaceAnalysis, assumed consecutive
    bankroll: float,
    config,
) -> list[CrossRaceBet]:
    """
    Build daily double and pick-3 tickets connecting consecutive races.
    Generates KEY, KEY+1 (backup in one leg), and SPREAD variants.
    Returns all bets with positive edge, sorted by edge.
    """
    kf  = config.bankroll.kelly_fraction_exotic
    mxf = config.bankroll.max_exotic_fraction
    results: list[CrossRaceBet] = []

    # ── Daily Doubles (all adjacent pairs) ─────────────────────────────────
    for i in range(len(analyses) - 1):
        a, b = analyses[i], analyses[i + 1]
        dd_label = f"DD R{a.race_number}×R{b.race_number}"

        # KEY × KEY
        leg_a1 = _make_leg(a, 1)
        leg_b1 = _make_leg(b, 1)
        bet = _build_bet("Daily Double", [leg_a1, leg_b1], f"{dd_label} KEY×KEY",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 15:
            results.append(bet)

        # KEY × +1 (key race A, spread race B top 2)
        leg_b2 = _make_leg(b, 2)
        bet = _build_bet("Daily Double", [leg_a1, leg_b2], f"{dd_label} KEY×+1",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 10:
            results.append(bet)

        # +1 × KEY
        leg_a2 = _make_leg(a, 2)
        bet = _build_bet("Daily Double", [leg_a2, leg_b1], f"{dd_label} +1×KEY",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 10:
            results.append(bet)

        # SPREAD: top 2 × top 2
        bet = _build_bet("Daily Double", [leg_a2, leg_b2], f"{dd_label} SPREAD",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 5:
            results.append(bet)

    # ── Pick 3 (all consecutive triples) ────────────────────────────────────
    for i in range(len(analyses) - 2):
        a, b, c = analyses[i], analyses[i + 1], analyses[i + 2]
        p3_label = f"P3 R{a.race_number}×R{b.race_number}×R{c.race_number}"

        leg_a1 = _make_leg(a, 1)
        leg_b1 = _make_leg(b, 1)
        leg_c1 = _make_leg(c, 1)
        leg_a2 = _make_leg(a, 2)
        leg_b2 = _make_leg(b, 2)
        leg_c2 = _make_leg(c, 2)

        # KEY × KEY × KEY
        bet = _build_bet("Pick 3", [leg_a1, leg_b1, leg_c1], f"{p3_label} KEY×KEY×KEY",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 20:
            results.append(bet)

        # KEY × KEY × +1 (spread final leg — most uncertain)
        bet = _build_bet("Pick 3", [leg_a1, leg_b1, leg_c2], f"{p3_label} KEY×KEY×+1",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 15:
            results.append(bet)

        # KEY × +1 × KEY
        bet = _build_bet("Pick 3", [leg_a1, leg_b2, leg_c1], f"{p3_label} KEY×+1×KEY",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 15:
            results.append(bet)

        # +1 × KEY × KEY
        bet = _build_bet("Pick 3", [leg_a2, leg_b1, leg_c1], f"{p3_label} +1×KEY×KEY",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 15:
            results.append(bet)

        # SPREAD: top 2 × top 2 × top 2 (8 combos)
        bet = _build_bet("Pick 3", [leg_a2, leg_b2, leg_c2], f"{p3_label} SPREAD 2×2×2",
                         bankroll, kf, mxf)
        if bet and bet.edge_pct > 10:
            results.append(bet)

    results.sort(key=lambda x: x.edge_pct, reverse=True)
    return results
