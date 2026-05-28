"""Momentum Scanner v6 — Data-driven optimization from 798 real trades.

Key findings from v5 (798 trades, 210W/588L = 26.3% WR):
  - FLAT exit was DESTROYING performance: 465 trades (58%!), only 18% WR, net -4.51%
  - Without FLAT: 126W/207L = 38% WR, avg win +1.24%, avg loss -0.67% → PROFITABLE
  - TRAIL: 74% WR, net +13.19% → BEST exit
  - TP: 100% WR, net +69.65% → EXCELLENT
  - TIMEOUT: 33% WR but net +15.20% → POSITIVE (let winners run)
  - EARLY: 0% WR, net -15.22% → REMOVED
  - Winners avg volume: $7.6M vs losers much lower
  - Vol>1M + Change>=5%: 37% WR (vs 26% general)
  - Vol>1M + Change>=8%: 41% WR
  - Change 3-5%: only 22% WR → FILTER OUT
  - Change 5-8%: 29% WR → OK
  - Change 8-12%: 34% WR → BEST

Changes in v6:
  - REMOVED FLAT exit entirely (was generating 465 fee-losing trades)
  - REMOVED EARLY exit (0% WR, -15.22% net)
  - Volume minimum: 200k → 500k (winners are high-volume)
  - Change minimum: 2.5% → 5% (3-5% was 22% WR = garbage)
  - Scoring: heavily favor vol>1M (where 37-41% WR lives)
  - Swing timeout: 1h → 2h (TIMEOUT was net positive, let them run)
  - Fewer but BETTER trades = higher win rate + same R:R
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ranuk.config import SCAN_INTERVAL
from ranuk.config import TOTAL_CAPITAL as _INITIAL_CAPITAL
from ranuk.exchange import Exchange, TAKER_FEE
from ranuk.risk import RiskManager
from ranuk.intelligence import Intelligence, TradeRecord

MAX_POSITIONS = 8
MAX_PER_SCAN = 3
POSITION_SIZE_PCT = 0.08  # 8% of capital per trade ($5.60 on $70)
TOTAL_CAPITAL = _INITIAL_CAPITAL  # mutable at runtime via telegram commands
MIN_SCORE = 5.0  # Only high-quality (data shows lower scores = FLAT exits)


@dataclass
class Position:
    symbol: str
    entry_price: float
    qty: float
    size_usdt: float
    opened_at: float
    volume_at_entry: float
    change_at_entry: float
    mode: str  # "scalp" or "swing"
    highest: float = 0.0
    lowest_since: float = 0.0

    @property
    def tp_pct(self) -> float:
        return 0.015 if self.mode == "scalp" else 0.04

    @property
    def sl_pct(self) -> float:
        return 0.006 if self.mode == "scalp" else 0.015  # 1.5% SL

    @property
    def timeout(self) -> float:
        return 300 if self.mode == "scalp" else 7200  # 5min / 2h (TIMEOUT was net +15.20%)

    @property
    def trailing_sl(self) -> float:
        gain = (self.highest - self.entry_price) / self.entry_price
        if self.mode == "scalp":
            if gain >= 0.008:
                return self.highest * (1 - 0.003)
            return self.entry_price * (1 - self.sl_pct)
        else:
            # Looser trailing — let winners run to TP more often
            # Only trail after +2% gain, with 1.2% distance
            if gain >= 0.025:
                return self.highest * (1 - 0.010)
            elif gain >= 0.015:
                return self.highest * (1 - 0.012)
            return self.entry_price * (1 - self.sl_pct)


class MomentumScanner:
    def __init__(self, exchange: Exchange, risk: RiskManager):
        self.ex = exchange
        self.risk = risk
        self.intel = Intelligence.load()
        self.positions: dict[str, Position] = {}
        self.traded_today: set[str] = set()
        self._traded_day: str = ""
        self._cooldowns: dict[str, float] = {}  # symbol -> timestamp when can trade again
        self.total_pnl: float = 0.0
        self.total_fees: float = 0.0
        self.wins: int = 0
        self.losses: int = 0
        self._last_prices: dict[str, list[float]] = {}
        self._paused: bool = False

    def _reset_traded_today(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._traded_day != today:
            self.traded_today.clear()
            self._traded_day = today

    def _score_opportunity(self, g: dict) -> tuple[float, str]:
        """Score based on real data: vol>1M + change 5-12% = winners."""
        vol = g["volume"]
        change = g["change"]
        score = 0.0

        # Volume scoring (winners avg $7.6M, vol>1M = 36% WR vs 20% for <500k)
        if vol > 5_000_000:
            score += 4.0  # mega volume = strongest signal
        elif vol > 1_000_000:
            score += 3.0  # vol>1M = 36% WR in data
        elif vol > 500_000:
            score += 1.5  # acceptable but weaker
        else:
            return 0, "skip"  # <500k was terrible in data

        # Change scoring (8-12% = 34% WR, 5-8% = 29% WR, <5% = 22% WR)
        if 8.0 <= change <= 15.0:
            score += 3.0  # best bucket: 34% WR
            mode = "swing"
        elif 5.0 <= change < 8.0:
            score += 2.0  # decent: 29% WR
            mode = "swing"
        elif 15.0 < change <= 25.0:
            score += 1.0  # risky but can work with high vol
            mode = "scalp"
        else:
            return 0, "skip"

        # Pullback bonus
        if g["symbol"] in self._last_prices:
            prices = self._last_prices[g["symbol"]]
            if len(prices) >= 3 and prices[-1] < prices[-2] < prices[-3]:
                score += 2.0
            elif len(prices) >= 2 and prices[-1] < prices[-2]:
                score += 1.0

        return score, mode

    async def scan_once(self) -> list[dict]:
        self._reset_traded_today()
        if self._paused or len(self.positions) >= MAX_POSITIONS:
            return []

        gainers = await self.ex.top_gainers(80)
        opps = []

        for g in gainers:
            sym = g["symbol"]
            if sym in self.positions:
                continue
            # 1h cooldown after trading a token (prevents re-entry into falling tokens)
            if sym in self._cooldowns and time.time() < self._cooldowns[sym]:
                continue
            # Hard filters based on data
            if g["volume"] < 500_000:
                continue
            if g["change"] < 5.0 or g["change"] > 25.0:
                continue
            if any(x in sym for x in ["USD/", "UP/", "DOWN/", "BULL/", "BEAR/"]):
                continue

            score, mode = self._score_opportunity(g)
            if score < MIN_SCORE:
                continue

            opps.append({"symbol": sym, "volume": g["volume"], "change": g["change"],
                        "score": score, "mode": mode})

        # Track prices for pullback detection
        for g in gainers[:30]:
            sym = g["symbol"]
            self._last_prices.setdefault(sym, [])
            self._last_prices[sym].append(g["change"])
            if len(self._last_prices[sym]) > 6:
                self._last_prices[sym] = self._last_prices[sym][-6:]

        opps.sort(key=lambda x: -x["score"])
        slots = MAX_POSITIONS - len(self.positions)
        return opps[:min(MAX_PER_SCAN, slots)]

    async def enter(self, opp: dict) -> dict | None:
        symbol = opp["symbol"]
        size = TOTAL_CAPITAL * POSITION_SIZE_PCT
        if size < 0.5:
            return None
        ok, _ = self.risk.can_trade(size)
        if not ok:
            return None

        # Spread guard
        try:
            ticker = await self.ex.spot.fetch_ticker(symbol)
            bid = float(ticker.get("bid", 0) or 0)
            ask = float(ticker.get("ask", 0) or 0)
            if bid > 0 and ask > 0:
                spread = (ask - bid) / ((ask + bid) / 2)
                max_spread = 0.004 if opp["mode"] == "scalp" else 0.008
                if spread > max_spread:
                    return None
        except Exception:
            pass

        result = await self.ex.buy(symbol, size)
        px = result.get("price", 0)
        qty = result.get("qty", 0)
        fee = result.get("fee", 0)
        self.total_fees += fee
        if px and qty:
            self.positions[symbol] = Position(
                symbol=symbol, entry_price=px, qty=qty,
                size_usdt=size, opened_at=time.time(), highest=px,
                lowest_since=px,
                volume_at_entry=opp["volume"], change_at_entry=opp["change"],
                mode=opp["mode"],
            )
            self.traded_today.add(symbol)
            self.risk.state.total_exposure += size
        return result

    async def check_exits(self) -> list[dict]:
        exits = []
        for sym, pos in list(self.positions.items()):
            try:
                cur = await self.ex.price(sym)
            except Exception:
                continue
            if cur > pos.highest:
                pos.highest = cur
            if cur < pos.lowest_since:
                pos.lowest_since = cur

            pnl_pct = (cur - pos.entry_price) / pos.entry_price
            held = time.time() - pos.opened_at
            reason = None

            # Take profit (100% WR, net +69.65%)
            if pnl_pct >= pos.tp_pct:
                reason = "TP"
            # Trailing stop (74% WR, net +13.19% — our BEST exit)
            elif pos.highest > pos.entry_price * 1.005 and cur <= pos.trailing_sl:
                reason = "TRAIL"
            # Stop loss (necessary evil)
            elif pnl_pct <= -pos.sl_pct:
                reason = "SL"
            # Timeout (33% WR but net +15.20% — let winners run!)
            elif held > pos.timeout:
                reason = "TIMEOUT"
            # NO FLAT EXIT — it was destroying 58% of trades
            # NO EARLY EXIT — 0% WR, -15.22% net

            if reason:
                result = await self.ex.sell(sym, pos.qty)
                sell_fee = result.get("fee", pos.size_usdt * (1 + pnl_pct) * TAKER_FEE)
                self.total_fees += sell_fee
                net_pnl = (pos.size_usdt * pnl_pct) - sell_fee
                self.total_pnl += net_pnl
                won = net_pnl > 0
                if won:
                    self.wins += 1
                else:
                    self.losses += 1
                self.risk.register_pnl(net_pnl)
                self.risk.state.total_exposure -= pos.size_usdt

                self.intel.record_trade(TradeRecord(
                    symbol=sym, entry_price=pos.entry_price, exit_price=cur,
                    entry_time=pos.opened_at, exit_time=time.time(),
                    reason=reason, pnl_pct=pnl_pct,
                    volume_at_entry=pos.volume_at_entry,
                    change_at_entry=pos.change_at_entry,
                    hour_utc=datetime.fromtimestamp(pos.opened_at, tz=timezone.utc).hour,
                    won=won,
                ))
                del self.positions[sym]
                self._cooldowns[sym] = time.time() + 3600  # 1h cooldown
                exits.append({"symbol": sym, "reason": reason, "pnl": net_pnl,
                             "pnl_pct": pnl_pct, "fee": sell_fee, "mode": pos.mode})
        return exits

    async def run_forever(self, log):
        log.info(
            f"[green]MomentumScanner v6 (data-driven)[/] "
            f"max_pos={MAX_POSITIONS} min_vol=$500k min_change=5% "
            f"NO FLAT/EARLY exits | swing_tp=4%/sl=1.5%/timeout=2h"
        )
        while True:
            try:
                for e in await self.check_exits():
                    color = "green" if e["pnl"] > 0 else "red"
                    log.info(
                        f"[{color}]MOM {e['reason']}[/] {e['symbol']} [{e['mode']}] "
                        f"net=${e['pnl']:+.4f} ({e['pnl_pct']*100:+.1f}%) "
                        f"[W{self.wins}/L{self.losses}]"
                    )
                for opp in await self.scan_once():
                    r = await self.enter(opp)
                    if r:
                        log.info(
                            f"[cyan]MOM BUY[/] {opp['symbol']} [{opp['mode']}] "
                            f"@ ${r.get('price',0):.4f} score={opp['score']:.1f} "
                            f"vol=${opp['volume']:,.0f} +{opp['change']:.1f}%"
                        )
            except Exception as e:
                log.warning(f"Momentum: {e}")
            await asyncio.sleep(SCAN_INTERVAL)
