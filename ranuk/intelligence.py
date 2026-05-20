"""Trade Intelligence v2 — data-driven adaptive learning.

Removed hard hour restrictions. Now uses continuous scoring.
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TRADES_FILE = Path(__file__).parent.parent / "trades_history.json"
SHARED_TRADES = Path("/app/shared/trades_history.json")


@dataclass
class TradeRecord:
    symbol: str
    entry_price: float
    exit_price: float
    entry_time: float
    exit_time: float
    reason: str
    pnl_pct: float
    volume_at_entry: float
    change_at_entry: float
    hour_utc: int
    won: bool


@dataclass
class Intelligence:
    """Learns from trade history."""
    trades: list[TradeRecord] = field(default_factory=list)
    best_hours: set[int] = field(default_factory=lambda: set(range(24)))  # all hours
    min_volume: float = 50_000
    max_volume: float = 2_000_000
    early_exit_minutes: float = 1.0  # 1 min for scalps
    early_exit_loss_pct: float = -0.003

    def should_enter(self, symbol: str, volume: float, change_pct: float) -> tuple[bool, str]:
        """Minimal filter — scoring happens in momentum scanner."""
        if volume < self.min_volume:
            return False, "vol_too_low"
        if change_pct > 30:
            return False, "pump_exhausted"
        return True, "ok"

    def should_early_exit(self, pnl_pct: float, seconds_held: float) -> bool:
        """Quick cut for scalps."""
        if seconds_held > 60 and pnl_pct < -0.003:
            return True
        return False

    def record_trade(self, trade: TradeRecord):
        self.trades.append(trade)
        self._save()

    def _save(self):
        data = [vars(t) for t in self.trades]
        TRADES_FILE.write_text(json.dumps(data, indent=2))
        # Also save to shared volume for dashboard
        try:
            SHARED_TRADES.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    @classmethod
    def load(cls) -> "Intelligence":
        intel = cls()
        for path in [TRADES_FILE, SHARED_TRADES]:
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    intel.trades = [TradeRecord(**d) for d in data]
                    break
                except Exception:
                    pass
        return intel
