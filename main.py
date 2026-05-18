"""Ranuk Profit Bot v5 — with Telegram alerts + daily reports."""
import asyncio, json, time, logging, os
from datetime import datetime, timezone
from pathlib import Path
from rich.logging import RichHandler
from ranuk.config import MODE, TOTAL_CAPITAL, IS_PAPER
from ranuk.exchange import Exchange
from ranuk.risk import RiskManager
from ranuk.strategies.grid import GridTrader
from ranuk.strategies.momentum import MomentumScanner
from ranuk import telegram
from ranuk.reporter import generate_daily_report

logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler()])
log = logging.getLogger("ranuk")
STATE_FILE = Path(__file__).parent / "state.json"

# Configure Telegram
TG_TOKEN = os.getenv("TELEGRAM_TOKEN", "8895254248:AAGTy6NYZSphH1q6pa4SwHp2glTaraesgPI")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
telegram.configure(TG_TOKEN, TG_CHAT_ID)

def save_state(risk, grid, momentum, ex):
    state = {
        "capital": risk.capital, "pnl_today": risk.state.pnl_today,
        "grid_pnl": sum(g.pnl for g in grid.grids.values()),
        "grid_fees": sum(g.fees for g in grid.grids.values()),
        "grid_trades": sum(g.trades for g in grid.grids.values()),
        "momentum_pnl": momentum.total_pnl, "momentum_fees": momentum.total_fees,
        "momentum_wins": momentum.wins, "momentum_losses": momentum.losses,
        "momentum_open": len(momentum.positions),
        "total_fees": ex.total_fees_paid, "updated_at": time.time(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))
    return state

async def heartbeat(risk, grid, momentum, ex):
    last_report_day = ""
    await telegram.send_message(f"🚀 <b>Ranuk Crypto Bot started</b>\nMode: {MODE} | Capital: ${TOTAL_CAPITAL:.2f}")
    while True:
        state = save_state(risk, grid, momentum, ex)
        gpnl = state["grid_pnl"]
        gt = state["grid_trades"]
        log.info(
            f"💓 cap=${risk.capital:.2f} pnl=${risk.state.pnl_today:+.4f} "
            f"grid[t={gt} p=${gpnl:+.4f}] "
            f"mom[{len(momentum.positions)} open p=${momentum.total_pnl:+.4f} W{momentum.wins}/L{momentum.losses}] "
            f"fees=${ex.total_fees_paid:.4f}"
        )
        # Daily report at 21:00 UTC (18:00 Argentina)
        now = datetime.now(timezone.utc)
        if now.hour == 21 and now.strftime("%Y-%m-%d") != last_report_day:
            last_report_day = now.strftime("%Y-%m-%d")
            text, filepath = generate_daily_report(state)
            await telegram.send_daily_report(text, filepath)
            log.info("[green]Daily report sent to Telegram[/]")

        await asyncio.sleep(30)

async def main():
    log.info(f"═══ RANUK PROFIT BOT v5 ═══")
    log.info(f"  Mode: {MODE} | Capital: ${TOTAL_CAPITAL:.2f} | Telegram: {'ON' if TG_CHAT_ID else 'OFF'}")
    ex = Exchange()
    risk = RiskManager()
    grid = GridTrader(ex, risk)
    momentum = MomentumScanner(ex, risk)
    # Patch momentum to send Telegram alerts on trades
    _orig_enter = momentum.enter
    async def _enter_with_alert(opp):
        r = await _orig_enter(opp)
        if r:
            await telegram.alert_trade("Crypto", "BUY", opp["symbol"], details=f"vol=${opp['volume']:,.0f}")
        return r
    momentum.enter = _enter_with_alert

    _orig_exits = momentum.check_exits
    async def _exits_with_alert():
        exits = await _orig_exits()
        for e in exits:
            await telegram.alert_trade("Crypto", f"SELL ({e['reason']})", e["symbol"], pnl=e["pnl"])
        return exits
    momentum.check_exits = _exits_with_alert

    try:
        await asyncio.gather(grid.run_forever(log), momentum.run_forever(log), heartbeat(risk, grid, momentum, ex))
    except KeyboardInterrupt:
        pass
    finally:
        save_state(risk, grid, momentum, ex)
        await telegram.send_message("⚠️ <b>Ranuk Crypto Bot stopped</b>")
        await ex.close()

if __name__ == "__main__":
    asyncio.run(main())
