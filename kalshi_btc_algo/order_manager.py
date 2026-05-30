"""
Order manager — places orders and tracks them through settlement.
Polls Kalshi API to detect fills and resolved outcomes.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .kalshi_client import KalshiClient, Order
from .performance_tracker import PerformanceTracker, TradeRecord
from .risk_manager import RiskManager
from .signal_engine import TradeSignal
from .position_sizer import size_position, expected_return_pct

log = logging.getLogger(__name__)

_POLL_INTERVAL = 30   # seconds between status checks
_FILL_TIMEOUT = 120   # cancel unfilled orders after this many seconds


@dataclass
class ActiveTrade:
    order: Order
    signal: TradeSignal
    trade_id: int
    placed_ts: float = field(default_factory=time.time)
    filled: bool = False
    settled: bool = False


class OrderManager:
    def __init__(
        self,
        kalshi: KalshiClient,
        tracker: PerformanceTracker,
        risk: RiskManager,
    ):
        self._kalshi = kalshi
        self._tracker = tracker
        self._risk = risk
        self._active: dict[str, ActiveTrade] = {}  # order_id -> ActiveTrade

    @property
    def open_count(self) -> int:
        return len([t for t in self._active.values() if not t.settled])

    async def place(self, signal: TradeSignal, bankroll: float) -> Optional[str]:
        """
        Size and place an order for the given signal.
        Returns order_id on success, None on failure or zero-size.
        """
        contracts = size_position(
            true_prob=signal.estimate.true_prob,
            price_cents=signal.limit_price_cents,
            bankroll=bankroll,
        )
        if contracts <= 0:
            log.info("Skipping %s: position size is 0", signal.market.ticker)
            return None

        exp_ret = expected_return_pct(signal.estimate.true_prob, signal.limit_price_cents)
        log.info(
            "Placing %d × %s %s @ %dc  [p=%.3f edge=+%.3f expRet=%.1f%%]",
            contracts, signal.side, signal.market.ticker,
            signal.limit_price_cents, signal.estimate.true_prob,
            signal.estimate.edge, exp_ret,
        )

        try:
            order = await self._kalshi.place_order(
                ticker=signal.market.ticker,
                side=signal.side,
                contracts=contracts,
                price_cents=signal.limit_price_cents,
            )
        except Exception as exc:
            log.error("Order failed for %s: %s", signal.market.ticker, exc)
            return None

        trade = TradeRecord(
            ticker=signal.market.ticker,
            side=signal.side,
            direction=signal.direction,
            strike=signal.market.floor_strike,
            spot_at_entry=signal.estimate.spot,
            true_prob=signal.estimate.true_prob,
            implied_prob=signal.estimate.implied_prob,
            edge=signal.estimate.edge,
            contracts=contracts,
            price_cents=signal.limit_price_cents,
            sigma_annual=signal.estimate.sigma_annual,
            time_to_expiry_hours=signal.estimate.time_to_expiry_hours,
            order_id=order.order_id,
        )
        trade_id = self._tracker.record_trade(trade)
        self._risk.open_position()

        active = ActiveTrade(order=order, signal=signal, trade_id=trade_id)
        self._active[order.order_id] = active
        log.info("Order placed: %s (id=%s)", signal.market.ticker, order.order_id)
        return order.order_id

    async def poll(self):
        """
        Check status of all active orders. Cancel stale unfilled orders.
        Resolve settled positions and record P&L.
        """
        to_remove = []
        for order_id, active in list(self._active.items()):
            try:
                await self._check_order(active)
            except Exception as exc:
                log.error("Error polling order %s: %s", order_id, exc)
            if active.settled:
                to_remove.append(order_id)

        for oid in to_remove:
            self._active.pop(oid, None)

    async def _check_order(self, active: ActiveTrade):
        data = await self._kalshi.get_order(active.order.order_id)
        order_data = data.get("order", data)
        status = order_data.get("status", "")
        active.order.status = status

        # Cancel stale orders that never filled
        if status == "resting":
            age = time.time() - active.placed_ts
            if age > _FILL_TIMEOUT:
                log.info(
                    "Canceling stale order %s (%ds old)",
                    active.order.order_id, age,
                )
                try:
                    await self._kalshi.cancel_order(active.order.order_id)
                except Exception as exc:
                    log.warning("Cancel failed: %s", exc)
                active.settled = True
                self._risk.close_position()
                return

        if status == "canceled":
            log.info("Order %s canceled", active.order.order_id)
            active.settled = True
            self._risk.close_position()
            return

        if status == "settled":
            await self._handle_settlement(active, order_data)
            return

        if status == "filled" and not active.filled:
            active.filled = True
            log.info("Order %s filled", active.order.order_id)

    async def _handle_settlement(self, active: ActiveTrade, order_data: dict):
        """Record P&L after the contract resolves."""
        filled_count = order_data.get("contracts_count", active.order.contracts)
        price_paid = active.order.price_cents / 100.0
        total_cost = filled_count * price_paid

        # Kalshi returns payout in the settled order; 1 = YES resolved, 0 = NO
        result = order_data.get("yes_price", None)
        if result is None:
            # Infer from settled payout
            payout_cents = order_data.get("payout", 0)
            won = payout_cents > 0
        else:
            settled_yes = int(result) >= 99  # YES settled at 100 cents
            won = (active.signal.side == "yes" and settled_yes) or (
                active.signal.side == "no" and not settled_yes
            )

        if won:
            pnl = filled_count * (1.0 - price_paid)
        else:
            pnl = -total_cost

        self._tracker.resolve_trade(active.trade_id, won=won, pnl=pnl)
        self._risk.close_position()
        active.settled = True

        log.info(
            "Settled %s: %s pnl=%.2f",
            active.signal.market.ticker,
            "WIN" if won else "LOSS",
            pnl,
        )
