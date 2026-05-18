"""Risk manager — daily loss cap, position limits, kill switch."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from ranuk.config import TOTAL_CAPITAL, DAILY_LOSS_CAP_PCT, MAX_POSITION_PCT

@dataclass
class RiskState:
    pnl_today: float = 0.0
    total_exposure: float = 0.0
    kill_switch: bool = False
    day_start: str = ""

class RiskManager:
    def __init__(self):
        self.capital = TOTAL_CAPITAL
        self.state = RiskState()
        self._reset_day()

    def _reset_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.day_start != today:
            self.state.day_start = today
            self.state.pnl_today = 0.0

    def can_trade(self, size_usdt: float) -> tuple[bool, str]:
        self._reset_day()
        if self.state.kill_switch:
            return False, "kill_switch"
        if -self.state.pnl_today >= self.capital * DAILY_LOSS_CAP_PCT:
            self.state.kill_switch = True
            return False, "daily_loss_cap"
        if size_usdt > self.capital * MAX_POSITION_PCT:
            return False, "position_too_large"
        return True, "ok"

    def register_pnl(self, pnl: float):
        self._reset_day()
        self.state.pnl_today += pnl
        self.capital += pnl

    def available_capital(self) -> float:
        return max(0, self.capital - self.state.total_exposure)
