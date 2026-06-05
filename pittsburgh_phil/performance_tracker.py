import sqlite3
from datetime import datetime
from pathlib import Path


class PerformanceTracker:
    def __init__(self, db_path: str = "pittsburgh_phil.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS bets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at   TEXT NOT NULL,
                race_date   TEXT NOT NULL,
                track       TEXT NOT NULL,
                race_number INTEGER NOT NULL,
                race_name   TEXT NOT NULL,
                horse_name  TEXT NOT NULL,
                post        INTEGER,
                model_prob  REAL NOT NULL,
                market_prob REAL NOT NULL,
                decimal_odds REAL NOT NULL,
                edge        REAL NOT NULL,
                bet_amount  REAL NOT NULL,
                dry_run     INTEGER NOT NULL DEFAULT 1,
                result      TEXT,
                pnl         REAL
            );
            CREATE TABLE IF NOT EXISTS balance_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at   TEXT NOT NULL,
                bankroll    REAL NOT NULL,
                note        TEXT
            );
        """)
        self.conn.commit()

    def log_bet(
        self,
        race_date: str,
        track: str,
        race_number: int,
        race_name: str,
        horse_name: str,
        post: int,
        model_prob: float,
        market_prob: float,
        decimal_odds: float,
        edge: float,
        bet_amount: float,
        dry_run: bool = True,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO bets
               (logged_at, race_date, track, race_number, race_name, horse_name,
                post, model_prob, market_prob, decimal_odds, edge, bet_amount, dry_run)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(),
                race_date, track, race_number, race_name, horse_name,
                post, model_prob, market_prob, decimal_odds, edge, bet_amount,
                int(dry_run),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def record_result(self, bet_id: int, result: str, pnl: float) -> None:
        self.conn.execute(
            "UPDATE bets SET result=?, pnl=? WHERE id=?",
            (result, pnl, bet_id),
        )
        self.conn.commit()

    def log_balance(self, bankroll: float, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO balance_log (logged_at, bankroll, note) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), bankroll, note),
        )
        self.conn.commit()

    def summary(self) -> dict:
        cur = self.conn.execute("""
            SELECT
                COUNT(*) AS total_bets,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result IS NOT NULL THEN 1 ELSE 0 END) AS settled,
                SUM(pnl) AS total_pnl,
                AVG(edge) AS avg_edge
            FROM bets
        """)
        row = cur.fetchone()
        return {
            "total_bets": row[0],
            "wins": row[1] or 0,
            "settled": row[2] or 0,
            "total_pnl": row[3] or 0.0,
            "avg_edge": row[4] or 0.0,
        }

    def close(self) -> None:
        self.conn.close()
