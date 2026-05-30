"""
Main async event loop for the BTC hourly Kalshi algo.

Flow (every SCAN_INTERVAL seconds):
  1. Poll order statuses (fill / settle / cancel stale)
  2. Refresh balance; run risk checks
  3. Scan open BTC markets for high-probability signals
  4. For each signal: size position (Kelly) and place order
  5. Log balance snapshot
"""
import asyncio
import logging
import signal
import sys
import time
from typing import Optional

from .btc_feed import BTCFeed
from .kalshi_client import KalshiClient
from .order_manager import OrderManager
from .performance_tracker import PerformanceTracker
from .risk_manager import RiskManager
from .signal_engine import scan
from .config import config

log = logging.getLogger(__name__)


def _setup_logging():
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


class Algo:
    def __init__(self):
        self._feed = BTCFeed(lookback_hours=config.volatility.lookback_hours)
        self._tracker = PerformanceTracker(config.db_path)
        self._risk = RiskManager()
        self._traded_tickers: set[str] = set()  # avoid re-entering same market
        self._stop = asyncio.Event()

    def _handle_signal(self, *_):
        log.info("Shutdown requested")
        self._stop.set()

    async def run(self):
        _setup_logging()

        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(sig, self._handle_signal)

        log.info("Starting BTC hourly algo (env=%s)", config.kalshi.env)

        # Start BTC feed in background
        feed_task = asyncio.create_task(self._feed.run(), name="btc-feed")

        log.info("Waiting for first BTC price tick...")
        try:
            await self._feed.wait_ready(timeout=30.0)
        except asyncio.TimeoutError:
            log.error("No BTC price received in 30s — check network")
            feed_task.cancel()
            return

        log.info("BTC spot price: %.2f", self._feed.current_price)

        async with KalshiClient() as kalshi:
            balance = await kalshi.get_balance()
            self._risk.initialize(balance)
            self._tracker.log_balance(balance)
            log.info("Kalshi balance: $%.2f", balance)

            orders = OrderManager(kalshi, self._tracker, self._risk)

            log.info(
                "Algo running — scanning every %ds for ≥%.0f%% probability trades",
                config.signal.scan_interval_seconds,
                config.signal.min_true_probability * 100,
            )

            while not self._stop.is_set():
                loop_start = time.monotonic()
                try:
                    await self._tick(kalshi, orders, balance)
                    balance = await kalshi.get_balance()
                    self._risk.update_balance(balance)
                    self._tracker.log_balance(balance)
                except Exception as exc:
                    log.exception("Tick error: %s", exc)

                elapsed = time.monotonic() - loop_start
                sleep_time = max(0.0, config.signal.scan_interval_seconds - elapsed)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=sleep_time)
                except asyncio.TimeoutError:
                    pass

        feed_task.cancel()
        log.info("Algo stopped. Final report:\n%s", self._tracker.calibration_report())

    async def _tick(self, kalshi: KalshiClient, orders: OrderManager, balance: float):
        # 1. Poll existing orders for fills/settlements
        await orders.poll()

        # 2. Risk check before scanning for new trades
        ok, reason = self._risk.can_trade(balance)
        if not ok:
            log.warning("Trading blocked: %s", reason)
            return

        sigma = self._feed.realized_vol_annual
        if sigma is None:
            hours_data = len(self._feed.hourly_log_returns)
            log.info(
                "Insufficient vol data (%d/%d hours needed)",
                hours_data, config.volatility.min_data_hours,
            )
            return

        log.debug(
            "Tick: spot=%.2f sigma=%.2f%% open=%d balance=%.2f",
            self._feed.current_price, sigma * 100,
            orders.open_count, balance,
        )

        # 3. Scan for signals
        signals = await scan(kalshi, self._feed, already_traded=self._traded_tickers)

        # 4. Place orders
        for sig in signals:
            ok, reason = self._risk.can_trade(balance)
            if not ok:
                log.info("Risk stop during signal loop: %s", reason)
                break
            order_id = await orders.place(sig, bankroll=balance)
            if order_id:
                self._traded_tickers.add(sig.market.ticker)

        # Purge resolved tickers so we can re-enter new hourly markets
        # (tickers are unique per hour, so the set naturally grows and old ones expire)
        if len(self._traded_tickers) > 500:
            self._traded_tickers = set(list(self._traded_tickers)[-200:])


async def _main():
    await Algo().run()


def main():
    asyncio.run(_main())
