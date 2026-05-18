"""Ranuk Profit Bot v3 — fee-aware."""
import asyncio, json, time, logging
from pathlib import Path
from rich.logging import RichHandler
from ranuk.config import MODE, TOTAL_CAPITAL, IS_PAPER
from ranuk.exchange import Exchange
from ranuk.risk import RiskManager
from ranuk.strategies.grid import GridTrader
from ranuk.strategies.momentum import MomentumScanner

logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler()])
log = logging.getLogger("ranuk")
STATE_FILE = Path(__file__).parent / "state.json"

def save_state(risk, grid, momentum, ex):
    state = {
        "capital": risk.capital,
        "pnl_today": risk.state.pnl_today,
        "grid_pnl": sum(g.pnl for g in grid.grids.values()),
        "grid_fees": sum(g.fees for g in grid.grids.values()),
        "grid_trades": sum(g.trades for g in grid.grids.values()),
        "momentum_pnl": momentum.total_pnl,
        "momentum_fees": momentum.total_fees,
        "momentum_wins": momentum.wins,
        "momentum_losses": momentum.losses,
        "momentum_open": len(momentum.positions),
        "total_fees": ex.total_fees_paid,
        "updated_at": time.time(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))

async def heartbeat(risk, grid, momentum, ex):
    while True:
        gpnl = sum(g.pnl for g in grid.grids.values())
        gfees = sum(g.fees for g in grid.grids.values())
        gt = sum(g.trades for g in grid.grids.values())
        log.info(
            f"💓 cap=${risk.capital:.2f} pnl=${risk.state.pnl_today:+.4f} "
            f"grid[t={gt} p=${gpnl:+.4f}] "
            f"mom[{len(momentum.positions)} open p=${momentum.total_pnl:+.4f} W{momentum.wins}/L{momentum.losses}] "
            f"fees=${ex.total_fees_paid:.4f}"
        )
        save_state(risk, grid, momentum, ex)
        await asyncio.sleep(30)

async def main():
    log.info(f"═══ RANUK PROFIT BOT v3 (fee-aware) ═══")
    log.info(f"  Mode: {MODE} | Capital: ${TOTAL_CAPITAL:.2f} | Fee: 0.10%/trade")
    ex = Exchange()
    risk = RiskManager()
    grid = GridTrader(ex, risk)
    momentum = MomentumScanner(ex, risk)
    try:
        await asyncio.gather(grid.run_forever(log), momentum.run_forever(log), heartbeat(risk, grid, momentum, ex))
    except KeyboardInterrupt:
        pass
    finally:
        save_state(risk, grid, momentum, ex)
        await ex.close()

if __name__ == "__main__":
    asyncio.run(main())
