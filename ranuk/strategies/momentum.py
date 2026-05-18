"""Momentum Scanner v4 — AI-guided, learns from past trades.

Changes from v3:
  - Intelligence module filters entries (time, volume, blacklist)
  - Early exit at -1.5% after 30min (don't wait for -3% SL)
  - Records every trade for continuous learning
  - Only trades during profitable hours (04-10h UTC from data)
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from ranuk.config import SNIPER_MAX_PER_TOKEN, TOTAL_CAPITAL, MOMENTUM_MIN_VOLUME, MOMENTUM_MIN_CHANGE, SCAN_INTERVAL
from ranuk.exchange import Exchange, TAKER_FEE
from ranuk.risk import RiskManager
from ranuk.intelligence import Intelligence, TradeRecord

@dataclass
class Position:
    symbol: str
    entry_price: float
    qty: float
    size_usdt: float
    opened_at: float
    volume_at_entry: float
    change_at_entry: float
    highest: float = 0.0
    tp_pct: float = 0.12
    sl_pct: float = 0.03

    @property
    def trailing_sl(self) -> float:
        gain = (self.highest - self.entry_price) / self.entry_price
        if gain >= 0.08:
            return self.highest * (1 - 0.04)
        elif gain >= 0.05:
            return self.highest * (1 - 0.03)
        return self.entry_price * (1 - self.sl_pct)

class MomentumScanner:
    def __init__(self, exchange: Exchange, risk: RiskManager):
        self.ex = exchange
        self.risk = risk
        self.intel = Intelligence.load()
        self.positions: dict[str, Position] = {}
        self.traded_today: set[str] = set()
        self.total_pnl: float = 0.0
        self.total_fees: float = 0.0
        self.wins: int = 0
        self.losses: int = 0

    async def scan_once(self) -> list[dict]:
        gainers = await self.ex.top_gainers(50)
        opps = []
        for g in gainers:
            sym = g["symbol"]
            if sym in self.positions or sym in self.traded_today:
                continue
            if g["volume"] < MOMENTUM_MIN_VOLUME:
                continue
            if g["change"] < MOMENTUM_MIN_CHANGE or g["change"] > 40:
                continue
            if any(x in sym for x in ["USD/", "UP/", "DOWN/", "BULL/", "BEAR/"]):
                continue
            # Intelligence filter
            ok, reason = self.intel.should_enter(sym, g["volume"], g["change"])
            if not ok:
                continue
            opps.append({"symbol": sym, "volume": g["volume"], "change": g["change"]})
        return opps[:2]

    async def enter(self, opp: dict) -> dict | None:
        symbol = opp["symbol"]
        max_size = TOTAL_CAPITAL * SNIPER_MAX_PER_TOKEN
        size = min(max_size, self.risk.available_capital() * 0.15)
        if size < 1.0:
            return None
        ok, _ = self.risk.can_trade(size)
        if not ok:
            return None
        result = await self.ex.buy(symbol, size)
        px = result.get("price", 0)
        qty = result.get("qty", 0)
        fee = result.get("fee", 0)
        self.total_fees += fee
        if px and qty:
            self.positions[symbol] = Position(
                symbol=symbol, entry_price=px, qty=qty,
                size_usdt=size, opened_at=time.time(), highest=px,
                volume_at_entry=opp["volume"], change_at_entry=opp["change"],
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
            pnl_pct = (cur - pos.entry_price) / pos.entry_price
            held = time.time() - pos.opened_at
            reason = None

            if pnl_pct >= pos.tp_pct:
                reason = "TP"
            elif cur <= pos.trailing_sl and pos.highest > pos.entry_price * 1.05:
                reason = "TRAIL"
            elif pnl_pct <= -pos.sl_pct:
                reason = "SL"
            # EARLY EXIT: learned rule — cut at -1.5% after 30min
            elif self.intel.should_early_exit(pnl_pct, held):
                reason = "EARLY"
            elif held > 14400:
                reason = "TIMEOUT"

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

                # Record for learning
                from datetime import datetime, timezone
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
                exits.append({"symbol": sym, "reason": reason, "pnl": net_pnl, "pnl_pct": pnl_pct, "fee": sell_fee})
        return exits

    async def run_forever(self, log):
        log.info(
            f"[green]MomentumScanner v4 (AI-guided)[/] "
            f"hours={sorted(self.intel.best_hours)} "
            f"vol=${self.intel.min_volume/1000:.0f}k-${self.intel.max_volume/1000:.0f}k "
            f"blacklist={len(self.intel.trades)} past trades loaded"
        )
        while True:
            try:
                for e in await self.check_exits():
                    color = "green" if e["pnl"] > 0 else "red"
                    log.info(
                        f"[{color}]MOM {e['reason']}[/] {e['symbol']} "
                        f"net=${e['pnl']:+.4f} ({e['pnl_pct']*100:+.1f}%) "
                        f"[W{self.wins}/L{self.losses}]"
                    )
                for opp in await self.scan_once():
                    r = await self.enter(opp)
                    if r:
                        log.info(f"[cyan]MOM BUY[/] {opp['symbol']} @ ${r.get('price',0):.4f} vol=${opp['volume']:,.0f}")
            except Exception as e:
                log.warning(f"Momentum: {e}")
            await asyncio.sleep(SCAN_INTERVAL)
