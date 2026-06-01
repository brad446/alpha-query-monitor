"""
Order manager — places orders (or simulates them in dry-run mode)
and tracks them through to settlement.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .kalshi_client import KalshiClient, Order
from .performance_tracker import PerformanceTracker, TradeRecord
from .risk_manager import RiskManager
from .signal_engine import TradeSignal
from .position_sizer import size_position, expected_return_pct
from .config import config

log = logging.getLogger(__name__)

_FILL_TIMEOUT = 120   # cancel unfilled live orders after this many seconds


@dataclass
class ActiveTrade:
    order: Order
    signal: TradeSignal
    trade_id: int
    placed_ts: float = field(default_factory=time.time)
    filled: bool = False
    settled: bool = False
    is_dry_run: bool = False


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
        Size and place (or simulate) an order for the given signal.
        Returns a trade ID string on success, None on failure or zero-size.
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
        cost = contracts * signal.limit_price_cents / 100.0

        if config.kalshi.dry_run:
            return await self._place_dry_run(signal, contracts, exp_ret, cost)
        else:
            return await self._place_live(signal, contracts, exp_ret)

    async def _place_dry_run(
        self, signal: TradeSignal, contracts: int, exp_ret: float, cost: float
    ) -> Optional[str]:
        fake_id = f"DRY-{uuid.uuid4().hex[:8]}"
        log.info(
            "[DRY RUN] Would buy %d × %s %s @ %dc  "
            "[p=%.3f edge=+%.3f expRet=%.1f%% cost=$%.2f]",
            contracts, signal.side, signal.market.ticker,
            signal.limit_price_cents, signal.estimate.true_prob,
            signal.estimate.edge, exp_ret, cost,
        )

        fake_order = Order(
            order_id=fake_id,
            client_order_id=fake_id,
            ticker=signal.market.ticker,
            side=signal.side,
            action="buy",
            contracts=contracts,
            price_cents=signal.limit_price_cents,
            status="filled",   # assume instant fill in dry-run
            created_time="",
        )
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
            order_id=fake_id,
        )
        trade_id = self._tracker.record_trade(trade)
        self._risk.open_position()

        active = ActiveTrade(
            order=fake_order, signal=signal, trade_id=trade_id, is_dry_run=True
        )
        active.filled = True
        self._active[fake_id] = active
        return fake_id

    async def _place_live(
        self, signal: TradeSignal, contracts: int, exp_ret: float
    ) -> Optional[str]:
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
        """Check status of all active trades; settle completed ones."""
        to_remove = []
        for order_id, active in list(self._active.items()):
            try:
                if active.is_dry_run:
                    await self._check_dry_run(active)
                else:
                    await self._check_live_order(active)
            except Exception as exc:
                log.error("Error polling order %s: %s", order_id, exc)
            if active.settled:
                to_remove.append(order_id)

        for oid in to_remove:
            self._active.pop(oid, None)

    async def _check_dry_run(self, active: ActiveTrade):
        """
        Resolve a dry-run trade by checking whether the Kalshi market has
        settled and reading its final YES/NO outcome.
        """
        from datetime import datetime, timezone
        from .signal_engine import _parse_close_time

        close_ts = _parse_close_time(active.signal.market.close_time)
        if close_ts is None or time.time() < close_ts:
            return  # not expired yet

        # Market has expired — fetch its current state to get the outcome
        try:
            markets = await self._kalshi.get_btc_hourly_markets()
            # The market may no longer be in the open list; fetch directly
            data = await self._kalshi._get(f"/markets/{active.signal.market.ticker}")
            market_data = data.get("market", data)
            status = market_data.get("status", "")
        except Exception as exc:
            log.warning("Could not fetch settlement for %s: %s",
                        active.signal.market.ticker, exc)
            return

        if status != "settled":
            return  # give it more time

        # last_price at settlement: 99 = YES won, 1 = NO won
        final_price = market_data.get("last_price", 50)
        yes_won = final_price >= 99

        won = (active.signal.side == "yes" and yes_won) or (
            active.signal.side == "no" and not yes_won
        )
        price_paid = active.order.price_cents / 100.0
        contracts = active.order.contracts
        pnl = contracts * (1.0 - price_paid) if won else -contracts * price_paid

        self._tracker.resolve_trade(active.trade_id, won=won, pnl=pnl)
        self._risk.close_position()
        active.settled = True

        log.info(
            "[DRY RUN] Settled %s: %s  simulated pnl=$%.2f",
            active.signal.market.ticker,
            "WIN" if won else "LOSS",
            pnl,
        )

    async def _check_live_order(self, active: ActiveTrade):
        data = await self._kalshi.get_order(active.order.order_id)
        order_data = data.get("order", data)
        status = order_data.get("status", "")
        active.order.status = status

        if status == "resting":
            age = time.time() - active.placed_ts
            if age > _FILL_TIMEOUT:
                log.info("Canceling stale order %s (%ds old)", active.order.order_id, age)
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
            await self._handle_live_settlement(active, order_data)
            return

        if status == "filled" and not active.filled:
            active.filled = True
            log.info("Order %s filled", active.order.order_id)

    async def _handle_live_settlement(self, active: ActiveTrade, order_data: dict):
        filled_count = order_data.get("contracts_count", active.order.contracts)
        price_paid = active.order.price_cents / 100.0
        total_cost = filled_count * price_paid

        result = order_data.get("yes_price", None)
        if result is None:
            won = order_data.get("payout", 0) > 0
        else:
            settled_yes = int(result) >= 99
            won = (active.signal.side == "yes" and settled_yes) or (
                active.signal.side == "no" and not settled_yes
            )

        pnl = filled_count * (1.0 - price_paid) if won else -total_cost

        self._tracker.resolve_trade(active.trade_id, won=won, pnl=pnl)
        self._risk.close_position()
        active.settled = True

        log.info(
            "Settled %s: %s pnl=$%.2f",
            active.signal.market.ticker,
            "WIN" if won else "LOSS",
            pnl,
        )
