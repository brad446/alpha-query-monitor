"""
SQLite-backed trade log and performance statistics.
Every trade is persisted so we can verify model calibration over time.
"""
import logging
import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    ticker: str
    side: str               # "yes" or "no"
    direction: str          # "above" or "at_or_below"
    strike: float
    spot_at_entry: float
    true_prob: float        # model estimate
    implied_prob: float     # market mid
    edge: float
    contracts: int
    price_cents: int        # entry price in cents
    sigma_annual: float
    time_to_expiry_hours: float
    placed_ts: float = 0.0
    resolved: bool = False
    won: Optional[bool] = None
    pnl_dollars: Optional[float] = None
    order_id: str = ""


class PerformanceTracker:
    def __init__(self, db_path: str = "btc_algo.db"):
        self._db = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    strike REAL,
                    spot_at_entry REAL,
                    true_prob REAL,
                    implied_prob REAL,
                    edge REAL,
                    contracts INTEGER,
                    price_cents INTEGER,
                    sigma_annual REAL,
                    time_to_expiry_hours REAL,
                    placed_ts REAL,
                    resolved INTEGER DEFAULT 0,
                    won INTEGER,
                    pnl_dollars REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS balance_log (
                    ts REAL PRIMARY KEY,
                    balance REAL
                )
            """)

    def record_trade(self, trade: TradeRecord) -> int:
        with self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO trades (
                    order_id, ticker, side, direction, strike, spot_at_entry,
                    true_prob, implied_prob, edge, contracts, price_cents,
                    sigma_annual, time_to_expiry_hours, placed_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                trade.order_id, trade.ticker, trade.side, trade.direction,
                trade.strike, trade.spot_at_entry, trade.true_prob,
                trade.implied_prob, trade.edge, trade.contracts,
                trade.price_cents, trade.sigma_annual,
                trade.time_to_expiry_hours, trade.placed_ts or time.time(),
            ))
            trade_id = cur.lastrowid
            log.info(
                "Trade #%d recorded: %s %s %d @ %dc (p=%.3f edge=+%.3f)",
                trade_id, trade.ticker, trade.side, trade.contracts,
                trade.price_cents, trade.true_prob, trade.edge,
            )
            return trade_id

    def resolve_trade(self, trade_id: int, won: bool, pnl: float):
        with self._conn() as conn:
            conn.execute("""
                UPDATE trades SET resolved=1, won=?, pnl_dollars=? WHERE id=?
            """, (int(won), pnl, trade_id))
        log.info("Trade #%d resolved: won=%s pnl=%.2f", trade_id, won, pnl)

    def log_balance(self, balance: float):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO balance_log (ts, balance) VALUES (?,?)",
                (time.time(), balance),
            )

    def summary(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) as resolved,
                    SUM(CASE WHEN won=1 THEN 1 ELSE 0 END) as wins,
                    SUM(pnl_dollars) as total_pnl,
                    AVG(true_prob) as avg_true_prob,
                    AVG(edge) as avg_edge,
                    AVG(CASE WHEN resolved=1 THEN CAST(won AS FLOAT) END) as actual_win_rate
                FROM trades
            """).fetchone()
        return dict(rows) if rows else {}

    def calibration_report(self) -> str:
        """Compare model win rates to actual win rates in probability buckets."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    CAST(true_prob * 20 AS INTEGER) / 20.0 as bucket,
                    COUNT(*) as n,
                    AVG(CAST(won AS FLOAT)) as actual_rate
                FROM trades
                WHERE resolved=1
                GROUP BY bucket
                ORDER BY bucket
            """).fetchall()

        if not rows:
            return "No resolved trades yet."

        lines = ["Calibration (model prob bucket → actual win rate):"]
        for r in rows:
            lines.append(
                f"  {r['bucket']:.2f}-{r['bucket']+0.05:.2f}: "
                f"actual={r['actual_rate']:.3f} n={r['n']}"
            )
        s = self.summary()
        if s.get("total"):
            lines.append(
                f"\nTotal trades: {s['total']}  Resolved: {s['resolved']}  "
                f"Wins: {s['wins']}  Total P&L: ${s['total_pnl'] or 0:.2f}"
            )
        return "\n".join(lines)
