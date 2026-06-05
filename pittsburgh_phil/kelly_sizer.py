def kelly_fraction_bet(
    win_prob: float,
    decimal_odds: float,
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_bet_pct: float = 0.05,
    min_edge: float = 0.05,
) -> dict:
    """
    Fractional Kelly criterion bet sizing.
    Pittsburgh Phil sized bets relative to his perceived edge — never betting
    more than his edge justified, never chasing steam.

    Returns a dict with: bet_amount, edge, full_kelly_pct, recommended
    """
    b = decimal_odds - 1.0  # Net profit per $1 wagered
    p = win_prob
    q = 1.0 - p

    if b <= 0 or p <= 0:
        return _no_bet("Invalid odds/probability")

    full_kelly = (b * p - q) / b
    edge = b * p - q  # Expected value per $1

    if full_kelly <= 0 or edge < min_edge:
        return _no_bet(f"Edge {edge:.3f} below threshold {min_edge:.3f}")

    fractional = full_kelly * kelly_fraction
    cap = max_bet_pct
    bet_pct = min(fractional, cap)
    bet_amount = bankroll * bet_pct

    return {
        "recommended": True,
        "bet_amount": round(bet_amount, 2),
        "bet_pct": round(bet_pct * 100, 2),
        "edge": round(edge, 4),
        "full_kelly_pct": round(full_kelly * 100, 2),
        "fractional_kelly_pct": round(fractional * 100, 2),
        "note": "",
    }


def _no_bet(reason: str) -> dict:
    return {
        "recommended": False,
        "bet_amount": 0.0,
        "bet_pct": 0.0,
        "edge": 0.0,
        "full_kelly_pct": 0.0,
        "fractional_kelly_pct": 0.0,
        "note": reason,
    }
