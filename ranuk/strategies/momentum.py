"""Momentum Scanner v5 — High-frequency scalping + swing hybrid.

Key changes from v4 (which had 0% winrate on 24 recent trades):
  - Operates 24h (no hour restriction) — uses volatility regime instead
  - 8 max opportunities per scan (was 2)
  - SCAN_INTERVAL=5s (was 10s)
  - Dual mode: SCALP (quick 0.5-1.5% profit, 5min hold) + SWING (2-5%, 1-4h)
  - Smarter entry: requires price PULLBACK after pump (not buying the top)
  - Tighter risk: scalp SL=0.5%, swing SL=1.5%
  - Volume-weighted scoring instead of simple threshold
  - No blacklist/whitelist — pure data-driven scoring
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ranuk.config import TOTAL_CAPITAL, SCAN_INTERVAL
from ranuk.exchange import Exchange, TAKER_FEE
from ranuk.risk import RiskManager
from ranuk.intelligence import Intelligence, TradeRecord

MAX_POSITIONS = 10
MAX_PER_SCAN = 8
POSITION_SIZE_PCT = 0.04  # 4% of capital per trade ($0.80 on $20)


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
        return 0.012 if self.mode == "scalp" else 0.04

    @property
    def sl_pct(self) -> float:
        return 0.006 if self.mode == "scalp" else 0.015

    @property
    def timeout(self) -> float:
        return 300 if self.mode == "scalp" else 7200  # 5min / 2h

    @property
    def trailing_sl(self) -> float:
        gain = (self.highest - self.entry_price) / self.entry_price
        if self.mode == "scalp":
            if gain >= 0.008:
                return self.highest * (1 - 0.004)
            return self.entry_price * (1 - self.sl_pct)
        else:
            if gain >= 0.03:
                return self.highest * (1 - 0.015)
            elif gain >= 0.015:
                return self.highest * (1 - 0.01)
            return self.entry_price * (1 - self.sl_pct)


class MomentumScanner:
    def __init__(self, exchange: Exchange, risk: RiskManager):
        self.ex = exchange
        self.risk = risk
        self.intel = Intelligence.load()
        self.positions: dict[str, Position] = {}
        self.traded_today: set[str] = set()
        self._traded_day: str = ""
        self.total_pnl: float = 0.0
        self.total_fees: float = 0.0
        self.wins: int = 0
        self.losses: int = 0
        self._last_prices: dict[str, list[float]] = {}  # symbol -> recent prices for pullback detection

    def _reset_traded_today(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._traded_day != today:
            self.traded_today.clear()
            self._traded_day = today

    def _score_opportunity(self, g: dict) -> tuple[float, str]:
        """Score an opportunity. Returns (score, mode). Higher = better."""
        vol = g["volume"]
        change = g["change"]
        score = 0.0

        # Volume sweet spot: $100k-$800k (from winner data)
        if 100_000 <= vol <= 800_000:
            score += 2.0
        elif 50_000 <= vol <= 100_000:
            score += 1.0
        elif vol > 800_000:
            score += 0.5  # too crowded but still tradeable

        # Change sweet spot: 3-10% = early momentum, >10% = exhausted
        if 3.0 <= change <= 7.0:
            score += 3.0  # ideal: catching early
            mode = "swing"
        elif 1.5 <= change < 3.0:
            score += 2.5  # very early, scalp it
            mode = "scalp"
        elif 7.0 < change <= 12.0:
            score += 1.5  # moderate, scalp only
            mode = "scalp"
        elif 12.0 < change <= 20.0:
            score += 0.5  # risky but possible scalp
            mode = "scalp"
        else:
            return 0, "skip"

        # Pullback bonus: if we've seen this token before and price dipped
        if g["symbol"] in self._last_prices:
            prices = self._last_prices[g["symbol"]]
            if len(prices) >= 2 and prices[-1] < prices[-2]:
                score += 1.5  # buying a dip, not the top

        return score, mode

    async def scan_once(self) -> list[dict]:
        self._reset_traded_today()
        if len(self.positions) >= MAX_POSITIONS:
            return []

        gainers = await self.ex.top_gainers(80)
        opps = []

        for g in gainers:
            sym = g["symbol"]
            if sym in self.positions or sym in self.traded_today:
                continue
            if g["volume"] < 50_000:
                continue
            if g["change"] < 1.5 or g["change"] > 25:
                continue
            if any(x in sym for x in ["USD/", "UP/", "DOWN/", "BULL/", "BEAR/"]):
                continue

            score, mode = self._score_opportunity(g)
            if score < 2.0:
                continue

            # Spread check will happen at entry time
            opps.append({"symbol": sym, "volume": g["volume"], "change": g["change"],
                        "score": score, "mode": mode})

        # Track prices for pullback detection
        for g in gainers[:30]:
            sym = g["symbol"]
            self._last_prices.setdefault(sym, [])
            self._last_prices[sym].append(g["change"])
            if len(self._last_prices[sym]) > 6:
                self._last_prices[sym] = self._last_prices[sym][-6:]

        # Sort by score, take top N
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
                max_spread = 0.003 if opp["mode"] == "scalp" else 0.006
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

            # Take profit
            if pnl_pct >= pos.tp_pct:
                reason = "TP"
            # Trailing stop (only if we've been in profit)
            elif pos.highest > pos.entry_price * 1.005 and cur <= pos.trailing_sl:
                reason = "TRAIL"
            # Stop loss
            elif pnl_pct <= -pos.sl_pct:
                reason = "SL"
            # Timeout — exit at market
            elif held > pos.timeout:
                reason = "TIMEOUT"
            # Quick cut: if scalp and -0.3% after 60s, cut immediately
            elif pos.mode == "scalp" and held > 60 and pnl_pct < -0.003:
                reason = "EARLY"

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
                exits.append({"symbol": sym, "reason": reason, "pnl": net_pnl,
                             "pnl_pct": pnl_pct, "fee": sell_fee, "mode": pos.mode})
        return exits

    async def run_forever(self, log):
        log.info(
            f"[green]MomentumScanner v5 (scalp+swing)[/] "
            f"max_pos={MAX_POSITIONS} scan_interval={SCAN_INTERVAL}s "
            f"scalp_tp=1.2%/sl=0.6% swing_tp=4%/sl=1.5%"
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
