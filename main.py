#!/usr/bin/env python3
"""
Pittsburgh Phil Handicapping Model
Belmont Stakes 2026 Race Card Analyzer

Inspired by George E. Smith ("Pittsburgh Phil"), 1862-1905 — the most successful
horse racing gambler of the Gilded Age, who pioneered systematic, data-driven
handicapping long before the term existed.
"""
import argparse
import sys
from pathlib import Path

from pittsburgh_phil.config import Config
from pittsburgh_phil.data_loader import load_race_card
from pittsburgh_phil.handicapper import analyze_card
from pittsburgh_phil.performance_tracker import PerformanceTracker
from pittsburgh_phil.reporter import format_card_report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pittsburgh Phil — Horse Racing Handicapping Model"
    )
    p.add_argument(
        "--card",
        default=None,
        help="Path to race card JSON (overrides RACE_CARD_PATH env var)",
    )
    p.add_argument(
        "--bankroll",
        type=float,
        default=None,
        help="Starting bankroll in dollars (overrides STARTING_BANKROLL env var)",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="Run in live mode (logs bets to DB; default is dry-run)",
    )
    p.add_argument(
        "--race",
        type=int,
        default=None,
        help="Analyze only this race number",
    )
    p.add_argument(
        "--db",
        default="pittsburgh_phil.db",
        help="SQLite database path for bet logging",
    )
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
    dry_run = config.bankroll.dry_run

    try:
        card = load_race_card(config.race_card_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(
            "Run with --card <path> or set RACE_CARD_PATH in your .env file",
            file=sys.stderr,
        )
        sys.exit(1)

    analyses = analyze_card(card, config, bankroll)

    # Filter to single race if requested
    if args.race is not None:
        analyses = [a for a in analyses if a.race_number == args.race]
        if not analyses:
            print(f"ERROR: Race {args.race} not found in card", file=sys.stderr)
            sys.exit(1)

    # Print report to stdout
    report = format_card_report(card, analyses, bankroll, dry_run)
    print(report)

    # Log bets to database
    tracker = PerformanceTracker(db_path=args.db)
    rc = card["race_card"]
    track = rc.get("track", "Unknown")
    race_date = rc.get("date", "")

    bets_logged = 0
    for analysis in analyses:
        for horse in analysis.horses:
            if horse.bet["recommended"]:
                tracker.log_bet(
                    race_date=race_date,
                    track=track,
                    race_number=analysis.race_number,
                    race_name=analysis.race_name,
                    horse_name=horse.name,
                    post=horse.post,
                    model_prob=horse.model_prob,
                    market_prob=horse.market_prob,
                    decimal_odds=horse.decimal_odds,
                    edge=horse.edge,
                    bet_amount=horse.bet["bet_amount"],
                    dry_run=dry_run,
                )
                bets_logged += 1

    tracker.log_balance(bankroll, note="session start")
    tracker.close()

    mode_str = "DRY RUN" if dry_run else "LIVE"
    print(f"\n  [{mode_str}] {bets_logged} bet(s) logged to {args.db}")


if __name__ == "__main__":
    main()
