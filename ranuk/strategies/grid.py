"""Grid Trading v3 — fee-aware, wider steps for better profit/fee ratio.

Strategy to minimize fee impact:
  - Wider step (range/4 instead of range/8) = fewer trades but each one
    profits MORE than the fee cost.
  - With ±3% range and 4 levels on BTC ($79k):
    step = $4,740 * 0.015 = ~$1,185 per level
    profit per sell = step * qty ≈ $0.022
    fee round-trip = $0.003
    NET per sell = $0.019 (fee is only 14% of profit vs 40% before)
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from ranuk.config import GRID_PAIRS, GRID_RANGE_PCT, GRID_LEVELS, GRID_CAPITAL_PCT, TOTAL_CAPITAL
from ranuk.exchange import Exchange, TAKER_FEE
from ranuk.risk import RiskManager

@dataclass
class GridState:
    symbol: str
    center: float
    low: float
    high: float
    step: float
    per_level_usdt: float
    inventory: list[float] = field(default_factory=list)
    buy_prices: list[float] = field(default_factory=list)
    pnl: float = 0.0
    fees: float = 0.0
    trades: int = 0

class GridTrader:
    def __init__(self, exchange: Exchange, risk: RiskManager):
        self.ex = exchange
        self.risk = risk
        self.grids: dict[str, GridState] = {}

    async def setup_grid(self, symbol: str) -> GridState:
        px = await self.ex.price(symbol)
        cap = (TOTAL_CAPITAL * GRID_CAPITAL_PCT) / len(GRID_PAIRS)
        per_level = cap / GRID_LEVELS
        low = px * (1 - GRID_RANGE_PCT)
        high = px * (1 + GRID_RANGE_PCT)
        step = (high - low) / (GRID_LEVELS - 1) if GRID_LEVELS > 1 else (high - low)
        buy_prices = [round(low + step * i, 2) for i in range(GRID_LEVELS)]
        inventory = [0.0] * GRID_LEVELS
        grid = GridState(
            symbol=symbol, center=px, low=low, high=high,
            step=step, per_level_usdt=per_level,
            inventory=inventory, buy_prices=buy_prices,
        )
        self.grids[symbol] = grid
        return grid

    async def tick(self, symbol: str) -> list[dict]:
        grid = self.grids.get(symbol)
        if not grid:
            return []
        cur = await self.ex.price(symbol)
        results = []

        for i, level_px in enumerate(grid.buy_prices):
            # BUY at this level
            if cur <= level_px and grid.inventory[i] == 0:
                ok, _ = self.risk.can_trade(grid.per_level_usdt)
                if not ok:
                    continue
                fee = grid.per_level_usdt * TAKER_FEE
                qty = (grid.per_level_usdt - fee) / cur
                await self.ex.buy(symbol, grid.per_level_usdt)
                grid.inventory[i] = qty
                grid.fees += fee
                grid.trades += 1
                results.append({"action": "buy", "symbol": symbol, "price": cur, "level": i, "fee": fee})

            # SELL when price reaches next level up
            sell_target = level_px + grid.step
            if cur >= sell_target and grid.inventory[i] > 0:
                qty = grid.inventory[i]
                proceeds = qty * cur
                fee = proceeds * TAKER_FEE
                net = proceeds - fee
                # PnL = what we got out - what we put in
                cost = grid.per_level_usdt
                pnl = net - cost
                grid.pnl += pnl
                grid.fees += fee
                grid.inventory[i] = 0
                grid.trades += 1
                self.risk.register_pnl(pnl)
                await self.ex.sell(symbol, qty)
                results.append({"action": "sell", "symbol": symbol, "price": cur, "pnl": pnl, "fee": fee})

        # Reset if price escaped range
        if cur < grid.low * 0.97 or cur > grid.high * 1.03:
            for i, qty in enumerate(grid.inventory):
                if qty > 0:
                    proceeds = qty * cur
                    fee = proceeds * TAKER_FEE
                    cost = grid.per_level_usdt
                    pnl = (proceeds - fee) - cost
                    grid.pnl += pnl
                    grid.fees += fee
                    self.risk.register_pnl(pnl)
                    grid.inventory[i] = 0
                    await self.ex.sell(symbol, qty)
            old_pnl, old_fees = grid.pnl, grid.fees
            await self.setup_grid(symbol)
            self.grids[symbol].pnl = old_pnl
            self.grids[symbol].fees = old_fees
            results.append({"action": "reset", "symbol": symbol, "new_center": cur})
        return results

    async def run_forever(self, log):
        log.info(f"[green]GridTrader v3 (fee-aware)[/] pairs={GRID_PAIRS} range=±{GRID_RANGE_PCT*100:.1f}% levels={GRID_LEVELS}")
        for pair in GRID_PAIRS:
            g = await self.setup_grid(pair)
            log.info(f"  {pair}: ${g.low:,.0f}-${g.high:,.0f} step=${g.step:,.0f} ${g.per_level_usdt:.2f}/lvl")
        while True:
            for pair in GRID_PAIRS:
                try:
                    for r in await self.tick(pair):
                        if r["action"] == "sell":
                            log.info(f"[green]GRID SELL[/] {r['symbol']} @ ${r['price']:,.2f} pnl=${r['pnl']:+.4f} fee=${r['fee']:.4f}")
                        elif r["action"] == "buy":
                            log.info(f"[cyan]GRID BUY[/] {r['symbol']} @ ${r['price']:,.2f} lvl={r['level']} fee=${r['fee']:.4f}")
                        elif r["action"] == "reset":
                            log.info(f"[yellow]GRID RESET[/] {r['symbol']} new=${r['new_center']:,.2f}")
                except Exception as e:
                    log.warning(f"Grid {pair}: {e}")
            await asyncio.sleep(10)
