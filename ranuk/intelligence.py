"""Trade Intelligence — learns from past trades to improve future decisions.

Findings from 24h of data (46 trades, 10 wins, 36 losses):

PATTERN 1 - TIME OF DAY:
  - 05-08h UTC: 60-100% winrate (Asian session open, real momentum)
  - 15-23h UTC: 0-20% winrate (buying exhausted pumps)
  → RULE: Only trade momentum during 04-10h UTC window

PATTERN 2 - VOLUME:
  - Winners avg volume: $200k-500k (mid-cap, room to grow)
  - Losers with vol < $100k: always lost (no liquidity to sustain pump)
  - Losers with vol > $2M: always lost (too crowded, pump already priced)
  → RULE: Only enter if $150k < volume < $1M

PATTERN 3 - EXIT TYPE:
  - SL exits: 100% losses (22/22). These are "bought the top" trades.
  - TRAIL exits: 100% wins (4/4). These caught real momentum.
  - TIMEOUT wins: tokens that held gains for 4h = real strength
  → RULE: If price doesn't move +2% within 30min of entry, exit early
    (don't wait for -3% SL, cut at -1.5% after 30min)

PATTERN 4 - TOKEN TYPE:
  - Winners: STORJ, OSMO, SYS, ZBT, FF (utility/infra tokens)
  - Losers: AI, KERNEL, D, PHB, PNUT, KITE (meme/hype tokens)
  → RULE: Blacklist known pump-and-dump patterns (meme, AI hype)
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TRADES_FILE = Path(__file__).parent.parent / "trades_history.json"

# Blacklisted tokens (known pump-and-dump from our data)
BLACKLIST = {
    "PNUT/USDT", "KITE/USDT", "D/USDT", "LUNC/USDT",
    "SHIB/USDT", "DOGE/USDT", "PEPE/USDT", "FLOKI/USDT",
    "BONK/USDT", "WIF/USDT", "MEME/USDT",
}

# Tokens that performed well historically
WHITELIST = {
    "STORJ/USDT", "OSMO/USDT", "SYS/USDT", "ZBT/USDT", "FF/USDT",
}


@dataclass
class TradeRecord:
    symbol: str
    entry_price: float
    exit_price: float
    entry_time: float
    exit_time: float
    reason: str  # TP, SL, TRAIL, TIMEOUT
    pnl_pct: float
    volume_at_entry: float
    change_at_entry: float
    hour_utc: int
    won: bool


@dataclass
class Intelligence:
    """Learns from trade history and provides go/no-go signals."""
    trades: list[TradeRecord] = field(default_factory=list)
    
    # Adaptive parameters (updated after each trade)
    best_hours: set[int] = field(default_factory=lambda: {4, 5, 6, 7, 8, 9, 10})
    min_volume: float = 150_000
    max_volume: float = 1_000_000
    early_exit_minutes: float = 30.0
    early_exit_loss_pct: float = -0.015  # -1.5% early exit

    def should_enter(self, symbol: str, volume: float, change_pct: float) -> tuple[bool, str]:
        """Decide if we should enter this trade based on learned patterns."""
        hour = datetime.now(timezone.utc).hour

        # Rule 1: Time window
        if hour not in self.best_hours:
            return False, f"bad_hour ({hour}h, best={sorted(self.best_hours)})"

        # Rule 2: Blacklist
        if symbol in BLACKLIST:
            return False, f"blacklisted"

        # Rule 3: Volume band
        if volume < self.min_volume:
            return False, f"vol_too_low (${volume:,.0f} < ${self.min_volume:,.0f})"
        if volume > self.max_volume:
            return False, f"vol_too_high (${volume:,.0f} > ${self.max_volume:,.0f})"

        # Rule 4: Don't chase pumps that already went too far
        if change_pct > 20:
            return False, f"pump_exhausted (+{change_pct:.1f}% already)"

        # Bonus: whitelist tokens get priority
        if symbol in WHITELIST:
            return True, "whitelisted_token"

        return True, "ok"

    def should_early_exit(self, pnl_pct: float, seconds_held: float) -> bool:
        """Cut losses early if not moving in our favor after 30min."""
        if seconds_held > self.early_exit_minutes * 60:
            if pnl_pct < self.early_exit_loss_pct:
                return True
        return False

    def record_trade(self, trade: TradeRecord):
        """Record a completed trade and update adaptive parameters."""
        self.trades.append(trade)
        self._update_rules()
        self._save()

    def _update_rules(self):
        """Recalculate rules from all historical trades."""
        if len(self.trades) < 10:
            return

        # Update best hours based on winrate per hour
        hour_stats: dict[int, dict] = {}
        for t in self.trades:
            h = t.hour_utc
            hour_stats.setdefault(h, {"w": 0, "l": 0})
            if t.won:
                hour_stats[h]["w"] += 1
            else:
                hour_stats[h]["l"] += 1

        self.best_hours = set()
        for h, s in hour_stats.items():
            total = s["w"] + s["l"]
            if total >= 2 and s["w"] / total >= 0.40:
                self.best_hours.add(h)
        
        # If no hours qualify, use the original defaults
        if not self.best_hours:
            self.best_hours = {4, 5, 6, 7, 8, 9, 10}

        # Update volume bands from winners
        winner_vols = [t.volume_at_entry for t in self.trades if t.won and t.volume_at_entry > 0]
        if len(winner_vols) >= 3:
            self.min_volume = min(winner_vols) * 0.8
            self.max_volume = max(winner_vols) * 1.5

        # Update blacklist from consistent losers
        from collections import Counter
        losses_by_sym = Counter(t.symbol for t in self.trades if not t.won)
        for sym, count in losses_by_sym.items():
            if count >= 3:
                BLACKLIST.add(sym)

    def _save(self):
        data = [vars(t) for t in self.trades]
        TRADES_FILE.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> "Intelligence":
        intel = cls()
        if TRADES_FILE.exists():
            try:
                data = json.loads(TRADES_FILE.read_text())
                intel.trades = [TradeRecord(**d) for d in data]
                intel._update_rules()
            except Exception:
                pass
        return intel
