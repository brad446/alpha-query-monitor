"""
Risk manager — enforces daily loss limit, drawdown circuit-breaker,
and open position count cap before any order is placed.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .config import config

log = logging.getLogger(__name__)


@dataclass
class RiskState:
    peak_balance: float = 0.0
    day_start_balance: float = 0.0
    day_start_ts: float = field(default_factory=time.time)
    open_position_count: int = 0
    halted: bool = False
    halt_reason: str = ""

    def new_day(self, balance: float):
        self.day_start_balance = balance
        self.day_start_ts = time.time()

    def update_peak(self, balance: float):
        if balance > self.peak_balance:
            self.peak_balance = balance


class RiskManager:
    def __init__(self):
        self._state = RiskState()

    def initialize(self, balance: float):
        self._state.peak_balance = balance
        self._state.day_start_balance = balance
        self._state.day_start_ts = time.time()
        log.info(
            "Risk manager initialized: balance=%.2f",
            balance,
        )

    def update_balance(self, balance: float):
        self._state.update_peak(balance)
        # Roll over day at midnight UTC
        if time.time() - self._state.day_start_ts > 86400:
            self._state.new_day(balance)

    def open_position(self):
        self._state.open_position_count += 1

    def close_position(self):
        self._state.open_position_count = max(0, self._state.open_position_count - 1)

    def can_trade(self, balance: float) -> tuple[bool, str]:
        """
        Returns (True, "") if trading is allowed, else (False, reason).
        """
        if self._state.halted:
            return False, f"halted: {self._state.halt_reason}"

        # Open position cap
        if self._state.open_position_count >= config.risk.max_open_positions:
            return False, (
                f"max open positions ({config.risk.max_open_positions}) reached"
            )

        # Daily loss limit
        if self._state.day_start_balance > 0:
            daily_pnl_pct = (balance - self._state.day_start_balance) / self._state.day_start_balance
            if daily_pnl_pct < -config.risk.daily_loss_limit_pct:
                reason = (
                    f"daily loss limit hit: {daily_pnl_pct:.1%} "
                    f"(limit {-config.risk.daily_loss_limit_pct:.1%})"
                )
                self._halt(reason)
                return False, reason

        # Drawdown circuit-breaker
        if self._state.peak_balance > 0:
            dd = (self._state.peak_balance - balance) / self._state.peak_balance
            if dd > config.risk.drawdown_limit_pct:
                reason = (
                    f"drawdown limit hit: {dd:.1%} "
                    f"(limit {config.risk.drawdown_limit_pct:.1%})"
                )
                self._halt(reason)
                return False, reason

        return True, ""

    def _halt(self, reason: str):
        self._state.halted = True
        self._state.halt_reason = reason
        log.critical("TRADING HALTED — %s", reason)

    def reset_halt(self):
        self._state.halted = False
        self._state.halt_reason = ""
        log.warning("Trading halt manually reset")

    @property
    def state(self) -> RiskState:
        return self._state
