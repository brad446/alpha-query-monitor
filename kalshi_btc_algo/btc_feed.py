"""
Real-time BTC/USDT price feed via Binance WebSocket.
Maintains a rolling window of hourly prices for volatility estimation.
"""
import asyncio
import json
import logging
import math
import time
from collections import deque
from typing import Optional

import websockets

log = logging.getLogger(__name__)

_BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@miniTicker"
_RECONNECT_DELAY = 5  # seconds


class BTCFeed:
    """
    Subscribes to Binance BTC/USDT 1-second ticker.
    Provides:
      - current_price: latest spot price
      - hourly_prices: deque of (timestamp, price) sampled once per minute
      - realized_vol_annual: annualized volatility from recent hourly log-returns
    """

    def __init__(self, lookback_hours: int = 72):
        self._lookback = lookback_hours
        self.current_price: float = 0.0
        self._last_sample_ts: float = 0.0
        # Store one price per minute; 60 samples = 1 hour
        self._minute_prices: deque = deque(maxlen=lookback_hours * 60)
        self._running = False
        self._ready = asyncio.Event()

    @property
    def is_ready(self) -> bool:
        return self.current_price > 0

    @property
    def hourly_log_returns(self) -> list[float]:
        """Compute log-returns from minute-sampled prices at 60-min intervals."""
        prices = list(self._minute_prices)
        # Sample every 60 minutes
        hourly = [prices[i][1] for i in range(0, len(prices), 60)]
        if len(hourly) < 2:
            return []
        return [math.log(hourly[i] / hourly[i - 1]) for i in range(1, len(hourly))]

    @property
    def realized_vol_annual(self) -> Optional[float]:
        """
        Annualized realized volatility from hourly log-returns.
        Returns None if insufficient data.
        """
        returns = self.hourly_log_returns
        if len(returns) < 4:
            return None
        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        sigma_hourly = math.sqrt(variance)
        return sigma_hourly * math.sqrt(8760)

    def _record_sample(self, price: float):
        now = time.time()
        # One sample per minute
        if now - self._last_sample_ts >= 60:
            self._minute_prices.append((now, price))
            self._last_sample_ts = now

    async def _connect(self):
        async for ws in websockets.connect(_BINANCE_WS, ping_interval=20):
            try:
                log.info("Binance BTC feed connected")
                async for raw in ws:
                    msg = json.loads(raw)
                    price = float(msg.get("c", 0) or msg.get("p", 0))
                    if price > 0:
                        self.current_price = price
                        self._record_sample(price)
                        if not self._ready.is_set():
                            self._ready.set()
            except websockets.ConnectionClosed:
                log.warning("BTC feed disconnected, reconnecting in %ds", _RECONNECT_DELAY)
                await asyncio.sleep(_RECONNECT_DELAY)
            except Exception as exc:
                log.error("BTC feed error: %s", exc)
                await asyncio.sleep(_RECONNECT_DELAY)

    async def run(self):
        self._running = True
        await self._connect()

    async def wait_ready(self, timeout: float = 30.0):
        """Block until we have at least one price tick."""
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)
