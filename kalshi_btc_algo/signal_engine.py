"""
Signal engine — scans active Kalshi BTC-hourly markets and returns
trade signals where the model says 91-95%+ with sufficient edge.

Handles both YES ("BTC closes above K") and NO ("BTC closes at or below K")
signals, always buying the high-probability side.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .btc_feed import BTCFeed
from .kalshi_client import KalshiClient, Market
from .probability_model import ProbabilityEstimate, full_estimate
from .config import config

log = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    market: Market
    side: str                     # "yes" or "no"
    direction: str                # "above" or "at_or_below"
    estimate: ProbabilityEstimate
    limit_price_cents: int        # aggressive limit: best ask or best bid


def _parse_close_time(close_time_str: str) -> Optional[float]:
    """Parse Kalshi ISO8601 close_time to Unix timestamp."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S+00:00"):
        try:
            dt = datetime.strptime(close_time_str, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def _hours_to_expiry(close_time_str: str) -> Optional[float]:
    ts = _parse_close_time(close_time_str)
    if ts is None:
        return None
    now = datetime.now(timezone.utc).timestamp()
    hours = (ts - now) / 3600.0
    return hours if hours > 0 else None


def evaluate_market(
    market: Market,
    spot: float,
    sigma_annual: float,
) -> Optional[TradeSignal]:
    """
    Evaluate a single Kalshi market and return a TradeSignal if tradeable.

    The contract resolves YES if BTC closes ABOVE the floor_strike (or
    at/below if strike_type == "less_or_equal").
    We check BOTH sides: buying YES when above is probable, buying NO when
    below is probable.
    """
    if market.floor_strike <= 0:
        return None

    hours = _hours_to_expiry(market.close_time)
    if hours is None or hours <= 0:
        return None

    # Only evaluate markets with at least some liquidity (bid AND ask posted)
    if market.yes_bid <= 0 or market.yes_ask <= 0:
        return None

    # Direction from market's strike_type
    yes_direction = (
        "above" if market.strike_type in ("greater", "greater_or_equal") else "at_or_below"
    )

    # YES side: implied prob = mid-market of YES contract
    yes_implied = market.implied_yes_prob
    yes_est = full_estimate(
        spot=spot,
        strike=market.floor_strike,
        time_to_expiry_hours=hours,
        sigma_annual=sigma_annual,
        implied_prob=yes_implied,
        direction=yes_direction,
    )

    # NO side: implied prob = 1 - yes_implied
    no_direction = "at_or_below" if yes_direction == "above" else "above"
    no_implied = 1.0 - yes_implied
    no_est = full_estimate(
        spot=spot,
        strike=market.floor_strike,
        time_to_expiry_hours=hours,
        sigma_annual=sigma_annual,
        implied_prob=no_implied,
        direction=no_direction,
    )

    # Check YES side
    if yes_est and yes_est.is_tradeable:
        # Use the ask price as our limit (we're buying YES)
        limit = market.yes_ask
        log.info(
            "SIGNAL YES: %s strike=%.0f spot=%.0f hours=%.2f "
            "p=%.3f implied=%.3f edge=+%.3f",
            market.ticker, market.floor_strike, spot, hours,
            yes_est.true_prob, yes_implied, yes_est.edge,
        )
        return TradeSignal(
            market=market,
            side="yes",
            direction=yes_direction,
            estimate=yes_est,
            limit_price_cents=limit,
        )

    # Check NO side
    if no_est and no_est.is_tradeable:
        # Buying NO: NO price = 100 - yes_ask
        no_ask_cents = 100 - market.yes_bid  # buying NO means paying (100 - yes_bid)
        log.info(
            "SIGNAL NO: %s strike=%.0f spot=%.0f hours=%.2f "
            "p=%.3f implied=%.3f edge=+%.3f",
            market.ticker, market.floor_strike, spot, hours,
            no_est.true_prob, no_implied, no_est.edge,
        )
        return TradeSignal(
            market=market,
            side="no",
            direction=no_direction,
            estimate=no_est,
            limit_price_cents=no_ask_cents,
        )

    return None


async def scan(
    kalshi: KalshiClient,
    feed: BTCFeed,
    already_traded: set[str],
) -> list[TradeSignal]:
    """
    Scan all open BTC-hourly markets and return qualifying trade signals.
    `already_traded` prevents duplicate positions on the same ticker.
    """
    sigma = feed.realized_vol_annual
    if sigma is None:
        log.info("Waiting for vol estimate (need more price history)")
        return []

    spot = feed.current_price
    if spot <= 0:
        return []

    try:
        markets = await kalshi.get_btc_hourly_markets()
    except Exception as exc:
        log.error("Failed to fetch markets: %s", exc)
        return []

    signals = []
    for market in markets:
        if market.ticker in already_traded:
            continue
        sig = evaluate_market(market, spot, sigma)
        if sig:
            signals.append(sig)

    if not signals:
        log.debug(
            "No signals: spot=%.0f sigma=%.2f%% markets=%d",
            spot, sigma * 100, len(markets),
        )

    return signals
