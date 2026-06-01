"""
Async Kalshi REST API client.
Handles auth, token refresh, markets, orderbook, and order management.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

from .config import config

log = logging.getLogger(__name__)


@dataclass
class Market:
    ticker: str
    event_ticker: str
    title: str
    status: str
    close_time: str          # ISO8601 — when the hourly contract resolves
    yes_bid: int             # cents (0-100)
    yes_ask: int             # cents
    last_price: int          # cents, last traded
    strike_type: str         # "greater" or "less_or_equal"
    floor_strike: float      # BTC price level the contract resolves around
    volume: int              # total contracts traded

    @property
    def implied_yes_prob(self) -> float:
        """Mid-market implied probability for YES contract."""
        if self.yes_bid > 0 and self.yes_ask > 0:
            return ((self.yes_bid + self.yes_ask) / 2) / 100.0
        return self.last_price / 100.0


@dataclass
class Order:
    order_id: str
    client_order_id: str
    ticker: str
    side: str          # "yes" or "no"
    action: str        # "buy"
    contracts: int
    price_cents: int
    status: str        # "resting", "filled", "canceled", "settled"
    created_time: str


class KalshiClient:
    def __init__(self):
        self._base = config.kalshi.base_url
        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        await self._login()
        return self

    async def __aexit__(self, *_):
        if self._session:
            await self._session.close()

    async def _login(self):
        payload = {
            "email": config.kalshi.email,
            "password": config.kalshi.password,
        }
        async with self._session.post(f"{self._base}/login", json=payload) as r:
            r.raise_for_status()
            data = await r.json()
        self._token = data["token"]
        # Kalshi tokens are valid for 24h; refresh 30 min early
        self._token_expires = time.time() + 23 * 3600
        log.info("Kalshi auth OK (env=%s)", config.kalshi.env)

    async def _ensure_auth(self):
        if time.time() > self._token_expires:
            await self._login()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        await self._ensure_auth()
        url = f"{self._base}{path}"
        async with self._session.get(url, headers=self._headers(), params=params) as r:
            r.raise_for_status()
            return await r.json()

    async def _post(self, path: str, payload: dict) -> Any:
        await self._ensure_auth()
        url = f"{self._base}{path}"
        async with self._session.post(
            url, headers=self._headers(), json=payload
        ) as r:
            r.raise_for_status()
            return await r.json()

    async def get_balance(self) -> float:
        """Return available balance in dollars."""
        data = await self._get("/portfolio/balance")
        return data["balance"] / 100.0  # Kalshi returns cents

    async def get_btc_hourly_markets(self) -> list[Market]:
        """
        Return open BTC-hourly markets sorted by close_time ascending.
        Only returns markets that are still open for trading.
        """
        params = {
            "series_ticker": config.signal.btc_series_ticker,
            "status": "open",
            "limit": 50,
        }
        data = await self._get("/markets", params=params)
        markets = []
        for m in data.get("markets", []):
            try:
                ob = m.get("yes_bid", 0), m.get("yes_ask", 0)
                markets.append(
                    Market(
                        ticker=m["ticker"],
                        event_ticker=m.get("event_ticker", ""),
                        title=m.get("title", ""),
                        status=m.get("status", ""),
                        close_time=m.get("close_time", ""),
                        yes_bid=ob[0],
                        yes_ask=ob[1],
                        last_price=m.get("last_price", 0),
                        strike_type=m.get("strike_type", "greater"),
                        floor_strike=float(m.get("floor_strike", 0) or 0),
                        volume=m.get("volume", 0),
                    )
                )
            except (KeyError, ValueError) as exc:
                log.warning("Skipping malformed market %s: %s", m.get("ticker"), exc)
        markets.sort(key=lambda m: m.close_time)
        return markets

    async def get_orderbook(self, ticker: str) -> dict:
        """Return raw orderbook for a market."""
        return await self._get(f"/markets/{ticker}/orderbook")

    async def place_order(
        self,
        ticker: str,
        side: str,
        contracts: int,
        price_cents: int,
    ) -> Order:
        """
        Place a limit buy order.

        side: "yes" or "no"
        price_cents: limit price in cents (1-99)
        contracts: number of $1-face-value contracts
        """
        client_id = str(uuid.uuid4())
        payload = {
            "ticker": ticker,
            "client_order_id": client_id,
            "type": "limit",
            "action": "buy",
            "side": side,
            "count": contracts,
            f"{side}_price": price_cents,
        }
        data = await self._post("/portfolio/orders", payload)
        o = data["order"]
        return Order(
            order_id=o["order_id"],
            client_order_id=client_id,
            ticker=ticker,
            side=side,
            action="buy",
            contracts=contracts,
            price_cents=price_cents,
            status=o.get("status", "resting"),
            created_time=o.get("created_time", ""),
        )

    async def get_order(self, order_id: str) -> dict:
        return await self._get(f"/portfolio/orders/{order_id}")

    async def cancel_order(self, order_id: str) -> dict:
        await self._ensure_auth()
        url = f"{self._base}/portfolio/orders/{order_id}"
        async with self._session.delete(url, headers=self._headers()) as r:
            r.raise_for_status()
            return await r.json()

    async def get_open_orders(self) -> list[dict]:
        data = await self._get("/portfolio/orders", params={"status": "resting"})
        return data.get("orders", [])

    async def get_positions(self) -> list[dict]:
        data = await self._get("/portfolio/positions")
        return data.get("market_positions", [])
