#!/usr/bin/env python3
"""
Pittsburgh Phil Handicapping Model
Belmont Stakes 2026 Race Card Analyzer

Usage examples:
  python main.py                          # full card, dry run
  python main.py --race 11               # Belmont Stakes only
  python main.py --bankroll 5000         # set bankroll
  python main.py --live                  # log bets to DB
  python main.py --tote "11,1,4.20 11,2,3.80 11,4,18.60"   # live tote odds
  python main.py --race 11 --tote "11,1,4.20 11,4,16.00"   # tote + single race
"""
import argparse
import sys

from pittsburgh_phil.config import Config
from pittsburgh_phil.data_loader import load_race_card, apply_tote_odds
from pittsburgh_phil.handicapper import analyze_card
from pittsburgh_phil.cross_race_exotics import build_cross_race_tickets
from pittsburgh_phil.performance_tracker import PerformanceTracker
from pittsburgh_phil.reporter import format_card_report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pittsburgh Phil — Horse Racing Handicapping Model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--card", default=None,
                   help="Path to race card JSON (overrides RACE_CARD_PATH env var)")
    p.add_argument("--bankroll", type=float, default=None,
                   help="Starting bankroll in dollars")
    p.add_argument("--live", action="store_true",
                   help="Live mode — logs bets to DB (default: dry-run)")
    p.add_argument("--race", type=int, default=None,
                   help="Analyze only this race number")
    p.add_argument("--db", default="pittsburgh_phil.db",
                   help="SQLite database path for bet logging")
    p.add_argument(
        "--tote",
        default=None,
        metavar="ODDS",
        help=(
            "Live tote board odds — overrides morning line for matching horses.\n"
            "Format: 'race,post,odds' pairs separated by spaces.\n"
            "Odds can be decimal (6.40), fractional (5-2), or slash (5/2).\n"
            "Example: --tote \"11,1,4.20 11,2,3.60 11,4,18.00\""
        ),
    )
    p.add_argument("--no-cross", action="store_true",
                   help="Skip cross-race (DD/Pick 3) exotic calculations")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = Config()

    if args.card:
        config.race_card_path = args.card
    if args.bankroll:
        config.bankroll.starting_bankroll = args.bankroll
    if args.live:
        config.bankroll.dry_run = False

    bankroll = config.bankroll.starting_bankroll
    dry_run  = config.bankroll.dry_run

    try:
        card = load_race_card(config.race_card_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Apply live tote odds before any analysis
    tote_applied = False
    if args.tote:
        apply_tote_odds(card, args.tote)
        tote_applied = True

    analyses = analyze_card(card, config, bankroll)

    # Filter to single race if requested
    if args.race is not None:
        analyses_display = [a for a in analyses if a.race_number == args.race]
        if not analyses_display:
            print(f"ERROR: Race {args.race} not found in card", file=sys.stderr)
            sys.exit(1)
        cross_tickets = []  # no cross-race when looking at one race
    else:
        analyses_display = analyses
        cross_tickets = (
            build_cross_race_tickets(analyses, bankroll, config)
            if not args.no_cross else []
        )

    report = format_card_report(
        card, analyses_display, bankroll, dry_run,
        cross_tickets=cross_tickets or None,
    )
    print(report)

    if tote_applied:
        print(f"\n  [TOTE] Live odds applied to {args.tote[:60]}{'...' if len(args.tote) > 60 else ''}")

    # Log bets to DB
    tracker = PerformanceTracker(db_path=args.db)
    rc = card["race_card"]
    track     = rc.get("track", "Unknown")
    race_date = rc.get("date", "")
    bets_logged = 0

    for analysis in analyses_display:
        for horse in analysis.value_picks:
            if horse.bet["recommended"]:
                tracker.log_bet(
                    race_date=race_date, track=track,
                    race_number=analysis.race_number, race_name=analysis.race_name,
                    horse_name=horse.name, post=horse.post,
                    model_prob=horse.model_prob, market_prob=horse.market_prob,
                    decimal_odds=horse.decimal_odds, edge=horse.edge,
                    bet_amount=horse.bet["bet_amount"], dry_run=dry_run,
                )
                bets_logged += 1

    tracker.log_balance(bankroll, note="session start")
    tracker.close()

    mode_str = "DRY RUN" if dry_run else "LIVE"
    print(f"\n  [{mode_str}] {bets_logged} win bet(s) logged to {args.db}")


if __name__ == "__main__":
    main()
