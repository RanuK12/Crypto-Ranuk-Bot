"""Risk manager — daily loss cap, position limits, kill switch.

State is persisted to disk so restarts don't reset daily limits or exposure.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from ranuk.config import TOTAL_CAPITAL, DAILY_LOSS_CAP_PCT, MAX_POSITION_PCT

STATE_PATH = Path(__file__).parent.parent / "risk_state.json"

@dataclass
class RiskState:
    pnl_today: float = 0.0
    total_exposure: float = 0.0
    kill_switch: bool = False
    day_start: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**{k: v for k, v in d.items() if k in {f.name for f in cls.__dataclass_fields__.values()}})

class RiskManager:
    def __init__(self):
        self.capital = TOTAL_CAPITAL
        self.state = self._load_state()
        self._reset_day()

    def _load_state(self) -> RiskState:
        if STATE_PATH.exists():
            try:
                return RiskState.from_dict(json.loads(STATE_PATH.read_text()))
            except Exception:
                pass
        return RiskState()

    def _save_state(self):
        try:
            STATE_PATH.write_text(json.dumps(self.state.to_dict(), indent=2))
        except Exception:
            pass

    def _reset_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.day_start != today:
            self.state.day_start = today
            self.state.pnl_today = 0.0
            self.state.kill_switch = False
            self._save_state()

    def can_trade(self, size_usdt: float) -> tuple[bool, str]:
        self._reset_day()
        if self.state.kill_switch:
            return False, "kill_switch"
        if -self.state.pnl_today >= self.capital * DAILY_LOSS_CAP_PCT:
            self.state.kill_switch = True
            self._save_state()
            return False, "daily_loss_cap"
        if size_usdt > self.capital * MAX_POSITION_PCT:
            return False, "position_too_large"
        # Don't allow total exposure > 80% of capital
        if self.state.total_exposure + size_usdt > self.capital * 0.80:
            return False, "max_exposure"
        return True, "ok"

    def register_pnl(self, pnl: float):
        self._reset_day()
        self.state.pnl_today += pnl
        self.capital += pnl
        self._save_state()

    def available_capital(self) -> float:
        return max(0, self.capital - self.state.total_exposure)
