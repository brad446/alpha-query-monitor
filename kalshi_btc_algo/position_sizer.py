"""
Fractional Kelly position sizing for binary (win/lose $1) contracts.

For a binary contract:
  - You pay `price` (0 < price < 1) and win $1 if correct, $0 if wrong
  - Net profit per contract: (1 - price) if right, -price if wrong
  - Kelly fraction: f* = (p - price) / (1 - price)
  - We use fractional Kelly (e.g. 0.25x) to reduce variance

Contract count = floor(kelly_f * kelly_fraction * bankroll / price)
Capped by max_dollars_per_trade and max_bankroll_pct_per_trade.
"""
import logging
import math

from .config import config

log = logging.getLogger(__name__)


def kelly_fraction(true_prob: float, price: float) -> float:
    """
    Full Kelly fraction for a binary contract.
    price is cost per contract as a decimal (e.g. 0.87 for 87-cent contract).
    Returns 0 if no edge.
    """
    if price <= 0 or price >= 1:
        return 0.0
    edge = true_prob - price
    if edge <= 0:
        return 0.0
    # Kelly for binary: f* = (p - price) / (1 - price)
    return edge / (1.0 - price)


def size_position(
    true_prob: float,
    price_cents: int,
    bankroll: float,
) -> int:
    """
    Return the number of contracts to buy.

    true_prob:   model probability (0-1)
    price_cents: contract price in cents (e.g. 87 for 87 cents)
    bankroll:    current available balance in dollars

    Returns 0 if no edge or position is below minimum.
    """
    if bankroll <= 0:
        return 0

    price = price_cents / 100.0
    full_kelly = kelly_fraction(true_prob, price)
    if full_kelly <= 0:
        log.debug("No edge: true_prob=%.3f price=%.2f", true_prob, price)
        return 0

    frac_kelly = full_kelly * config.risk.kelly_fraction

    # Dollar amount to wager (cost basis)
    dollar_kelly = frac_kelly * bankroll

    # Apply hard caps
    max_by_pct = bankroll * config.risk.max_bankroll_pct_per_trade
    max_by_abs = config.risk.max_dollars_per_trade
    dollar_spend = min(dollar_kelly, max_by_pct, max_by_abs)

    contracts = math.floor(dollar_spend / price)

    if contracts < config.risk.min_contracts:
        log.debug(
            "Position too small: contracts=%d (bankroll=%.2f, price=%.2f)",
            contracts, bankroll, price,
        )
        return 0

    log.debug(
        "Size: true_prob=%.3f price=%.2f full_kelly=%.3f frac=%.3f "
        "spend=%.2f contracts=%d",
        true_prob, price, full_kelly, frac_kelly, dollar_spend, contracts,
    )
    return contracts


def expected_return_pct(true_prob: float, price_cents: int) -> float:
    """Expected return as a percentage of capital risked."""
    price = price_cents / 100.0
    if price <= 0:
        return 0.0
    ev = true_prob * (1.0 - price) + (1.0 - true_prob) * (-price)
    return (ev / price) * 100.0
