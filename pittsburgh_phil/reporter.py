from .handicapper import RaceAnalysis, HorseRating
from .exotic_calculator import ExoticBet

W = 74  # line width

PACE_LABELS = {
    "HOT":       "HOT PACE   — pace collapse favors closers",
    "SLOW":      "SLOW PACE  — front runners can steal on the lead",
    "CONTESTED": "CONTESTED  — two-horse speed duel sets up closers",
    "NORMAL":    "NORMAL PACE — balanced field",
    "UNKNOWN":   "PACE UNKNOWN",
}

STYLE_LABEL = {"E": "Front Runner", "P": "Presser", "S": "Stalker",
               "C": "Closer", "?": "Unknown"}


def _bar(text: str, ch: str = "=") -> str:
    return f"\n{ch*W}\n  {text}\n{ch*W}"


def _ml(decimal: float) -> str:
    net = decimal - 1.0
    if net <= 0:
        return "EVN"
    for den in (1, 2, 5, 10):
        num = round(net * den)
        if abs(num / den - net) < 0.11:
            return f"{num}-{den}"
    return f"{net:.1f}-1"


def _pct(f: float) -> str:
    return f"{f*100:.1f}%"


def _bar_graph(norm_score: float, width: int = 18) -> str:
    filled = round(norm_score / 100 * width)
    return "[" + "█" * filled + "·" * (width - filled) + "]"


def _bounce_tag(h: HorseRating) -> str:
    if h.bounce_triggered:
        return f"  ⚠ BOUNCE ({h.bounce_penalty:+.0f} pts on speed)"
    return ""


def _sol_tag(h: HorseRating) -> str:
    if h.sol_triggered:
        return f"  ★ 2ND OFF LAYOFF (+{h.sol_bonus:.0f} pts)"
    return ""


def _active_maxims(h: HorseRating) -> list[str]:
    lines = []
    for m in h.maxims:
        if m.triggered and m.note:
            sign = "+" if m.bullish else "-"
            lines.append(f"    [{sign}] {m.code} {m.label}: {m.note}")
    return lines


def format_horse(h: HorseRating, rank: int) -> str:
    lines = []
    rank_tag = ">>>" if rank == 1 else f"#{rank:2d} "
    bet_str  = (f"WIN ${h.bet['bet_amount']:.0f}  (edge {h.edge*100:.0f}%)"
                if h.bet["recommended"] else "No value bet")

    lines.append(
        f"\n  {rank_tag} PP{h.post:2d}  {h.name:<24s}"
        f"{STYLE_LABEL.get(h.pace_style, '?'):13s}  ML: {_ml(h.decimal_odds)}"
        + _bounce_tag(h) + _sol_tag(h)
    )
    lines.append(
        f"        Model: {_pct(h.model_prob)}  Market: {_pct(h.market_prob)}"
        f"  Composite: {h.composite:.1f}/100"
    )
    lines.append(
        f"        Spd {_bar_graph(h.speed_norm)}  FF {_bar_graph(h.ff_norm)}"
        f"  Pace {_bar_graph(h.pace_norm)}"
    )
    lines.append(
        f"        Con {_bar_graph(h.connections_norm)}  CF {_bar_graph(h.class_form_norm)}"
        f"  →  {bet_str}"
    )
    lines.append(
        f"        Raw→ Spd:{h.speed_raw:.0f}  FF:{h.ff_raw:.0f}"
        f"  Pace:{h.pace_raw:+.1f}  Con:{h.connections_raw:+.1f}  CF:{h.class_form_raw:.0f}"
    )

    maxim_lines = _active_maxims(h)
    if maxim_lines:
        lines.extend(maxim_lines)

    return "\n".join(lines)


def _format_exotic_list(bets: list[ExoticBet], label: str) -> list[str]:
    if not bets:
        return [f"  {label}: No overlays found."]
    lines = [f"\n  {label}:"]
    for b in bets[:5]:
        horses_str = " → ".join(f"PP{p} {n}" for p, n in zip(b.posts, b.horses))
        lines.append(
            f"    {horses_str}"
            f"  |  Model: {b.model_prob*100:.2f}%"
            f"  |  Fair: {b.fair_value_odds:.0f}x"
            f"  |  ML-implied: {b.ml_implied_odds:.0f}x"
            f"  |  Edge: {b.edge*100:.0f}%"
            + (f"  →  BET ${b.kelly_bet:.0f}" if b.kelly_bet > 0 else "")
        )
    return lines


def format_exotics(exotics: dict) -> str:
    lines = ["\n" + "-" * W, "  EXOTIC OVERLAY PLAYS (Pittsburgh Phil overlay method)"]
    lines.extend(_format_exotic_list(exotics.get("exactas", []), "Exacta Overlays"))
    lines.extend(_format_exotic_list(exotics.get("trifectas", []), "Trifecta Keys (top pick keyed on top)"))
    lines.extend(_format_exotic_list(exotics.get("superfectas", []), "Superfecta Box (top 4)"))
    return "\n".join(lines)


def format_race(analysis: RaceAnalysis) -> str:
    lines = [_bar(
        f"Race {analysis.race_number}: {analysis.race_name}"
        f"  |  {analysis.distance_furlongs}f {analysis.surface.upper()}"
        f"  |  {analysis.class_level}"
    )]
    lines.append(f"\n  Pace Scenario: {PACE_LABELS.get(analysis.pace_scenario_label, analysis.pace_scenario_label)}")

    for rank, horse in enumerate(analysis.horses, 1):
        lines.append(format_horse(horse, rank))

    if analysis.value_picks:
        lines.append(f"\n  {'─'*W}")
        lines.append("  WIN OVERLAYS:")
        for vp in analysis.value_picks:
            lines.append(
                f"    PP{vp.post:2d}  {vp.name:<24s}"
                f"Model {_pct(vp.model_prob)} vs Market {_pct(vp.market_prob)}"
                f"  Edge {vp.edge*100:.0f}%  →  BET ${vp.bet['bet_amount']:.0f}"
            )
    else:
        lines.append("\n  No win overlays meet the edge threshold.")

    lines.append(format_exotics(analysis.exotics))
    return "\n".join(lines)


def format_card_report(card_meta: dict, analyses: list[RaceAnalysis],
                       bankroll: float, dry_run: bool) -> str:
    rc = card_meta.get("race_card", card_meta)
    lines = [_bar(
        f"Pittsburgh Phil Model  —  {rc.get('track', 'Belmont Park')}  {rc.get('date', '')}",
        ch="*",
    )]
    mode = "DRY RUN (paper)" if dry_run else "LIVE"
    lines.append(f"\n  Mode: {mode}  |  Bankroll: ${bankroll:,.2f}")
    lines.append(
        f"  Condition: {rc.get('track_condition', 'fast').upper()}"
        f"  |  Bias: {rc.get('track_bias', 'none')}"
    )
    total_win = sum(
        h.bet["bet_amount"] for a in analyses
        for h in a.value_picks if h.bet["recommended"]
    )
    lines.append(f"  Races: {len(analyses)}  |  Total win exposure: ${total_win:,.2f}")

    for a in analyses:
        lines.append(format_race(a))

    lines.append(_bar("End of Card  —  Good Luck", ch="-"))
    return "\n".join(lines)
