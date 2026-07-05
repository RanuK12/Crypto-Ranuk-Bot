"""Telegram Command Bot v3 — control panel + live config management."""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8107555656")
CRYPTO_STATE = Path("/app/shared/state.json")
COMMANDS_FILE = Path("/app/shared/commands.json")
TRADES_HISTORY = Path("/app/trades_history.json")
API_URL = f"https://api.telegram.org/bot{TOKEN}"

last_update_id = 0


async def api(method: str, **kwargs):
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API_URL}/{method}", json=kwargs, timeout=aiohttp.ClientTimeout(total=15)) as r:
            return await r.json()


async def send(text: str, reply_markup=None):
    params = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return await api("sendMessage", **params)


def kb(buttons):
    return {"keyboard": buttons, "resize_keyboard": True, "one_time_keyboard": False}


MAIN_MENU = kb([
    ["📊 Estado", "💰 Balance"],
    ["📈 PnL Hoy", "📋 Reporte"],
    ["⚙️ Config", "🎮 Control"],
    ["🔗 Dashboard"],
])


def _write_command(cmd: dict):
    """Write a command for the crypto bot to pick up."""
    try:
        existing = json.loads(COMMANDS_FILE.read_text()) if COMMANDS_FILE.exists() else {}
    except Exception:
        existing = {}
    existing.update(cmd)
    existing["_ts"] = time.time()
    COMMANDS_FILE.write_text(json.dumps(existing, indent=2))


def _load_commands() -> dict:
    try:
        return json.loads(COMMANDS_FILE.read_text()) if COMMANDS_FILE.exists() else {}
    except Exception:
        return {}


def _load_crypto() -> dict:
    for p in [CRYPTO_STATE, Path("/app/state.json")]:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return {}


def _load_trades() -> list:
    try:
        return json.loads(TRADES_HISTORY.read_text()) if TRADES_HISTORY.exists() else []
    except Exception:
        return []


async def _load_poly() -> dict:
    try:
        import requests
        funder = "0x1a1405f39232734ef1dbcf9ef06b9da72885f575"
        r = requests.get(f"https://data-api.polymarket.com/positions?user={funder}&sizeThreshold=0.1", timeout=10).json()
        active = [p for p in r if float(p.get("curPrice") or 0) > 0.001]
        total_val = sum(float(p.get("size", 0)) * float(p.get("curPrice", 0)) for p in active)
        return {"equity": total_val + 0.88, "positions": len(active), "pnl_today": 0.0}
    except Exception:
        return {"equity": 0, "positions": 0, "pnl_today": 0}


def _ago(ts: float) -> str:
    if not ts:
        return "?"
    diff = time.time() - ts
    if diff < 60: return f"{int(diff)}s"
    if diff < 3600: return f"{int(diff/60)}min"
    return f"{int(diff/3600)}h"


def _today_trades(trades: list) -> list:
    """Get trades from today (UTC)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = []
    for t in trades:
        et = t.get("entry_time", 0)
        if et > 0:
            d = datetime.fromtimestamp(et, tz=timezone.utc).strftime("%Y-%m-%d")
            if d == today:
                result.append(t)
    return result


# ═══════════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════════

async def handle_message(text: str):
    text = text.strip()

    # Simple commands
    simple = {
        "/start": cmd_menu, "/menu": cmd_menu, "🏠 Menú": cmd_menu,
        "📊 Estado": cmd_status, "💰 Balance": cmd_balance,
        "📈 PnL Hoy": cmd_pnl, "📋 Reporte": cmd_report,
        "🔗 Dashboard": cmd_dashboard,
        "⚙️ Config": cmd_config_menu,
        "⚙️ Config Crypto": cmd_config_crypto,
        "⚙️ Config Poly": cmd_config_poly,
        "🎮 Control": cmd_control_menu,
        "⏸ Pausar Bot": cmd_pause,
        "▶️ Reanudar Bot": cmd_resume,
        "🔄 Paper → Live": cmd_go_live,
        "🔄 Live → Paper": cmd_go_paper,
        "₿ Trades Hoy": cmd_trades_today,
        "₿ Últimos Trades": cmd_trades_last,
        "₿ Momentum": cmd_momentum,
        "🎯 Polymarket": cmd_poly,
    }
    handler = simple.get(text)
    if handler:
        await handler()
        return

    # Capital change: "capital 100" or "💵 Capital: 100"
    if text.lower().startswith("capital "):
        try:
            val = float(text.split()[-1])
            await cmd_set_capital(val)
        except ValueError:
            await send("❌ Formato: <code>capital 100</code>")
        return

    # Size change: "size 10"
    if text.lower().startswith("size "):
        try:
            val = float(text.split()[-1])
            await cmd_set_size(val)
        except ValueError:
            await send("❌ Formato: <code>size 10</code> (porcentaje)")
        return

    await send("❓ No entendí. Usá /menu\n\nComandos especiales:\n<code>capital 100</code> — cambiar capital\n<code>size 10</code> — cambiar % por trade", reply_markup=MAIN_MENU)


# ═══════════════════════════════════════════════════════════
# MAIN COMMANDS
# ═══════════════════════════════════════════════════════════

async def cmd_menu():
    await send("🤖 <b>Ranuk Trading System</b>\n\nSeleccioná una opción:", reply_markup=MAIN_MENU)


async def cmd_status():
    c = _load_crypto()
    p = await _load_poly()
    cmds = _load_commands()
    bal = c.get("balance", c.get("capital", 0))
    total = bal + p.get("equity", 0)
    wr = c.get("momentum_wins", 0) / max(c.get("momentum_wins", 0) + c.get("momentum_losses", 0), 1) * 100

    # Daily stats
    trades = _load_trades()
    today = _today_trades(trades)
    today_w = sum(1 for t in today if t["won"])
    today_l = len(today) - today_w

    paused = "⏸ PAUSADO" if cmds.get("paused") else "▶️ Activo"
    mode = cmds.get("mode", "paper")

    await send(
        f"📊 <b>Estado General</b> [{paused}]\n\n"
        f"💰 Capital total: <b>${total:.2f}</b>\n\n"
        f"₿ <b>Crypto Bot</b> (🟢 {mode})\n"
        f"  Balance: ${bal:.2f}\n"
        f"  PnL hoy: ${c.get('pnl_today', 0):+.4f}\n"
        f"  Hoy: {today_w}W/{today_l}L\n"
        f"  Total: W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)} ({wr:.0f}%)\n"
        f"  Open: {c.get('momentum_open', 0)} pos\n\n"
        f"🎯 <b>Polymarket</b> (🟢 live)\n"
        f"  Equity: ${p.get('equity', 0):.2f} | Pos: {p.get('positions', 0)}\n\n"
        f"⏱ Actualizado: {_ago(c.get('updated_at', 0))}",
        reply_markup=MAIN_MENU
    )


async def cmd_balance():
    c = _load_crypto()
    p = await _load_poly()
    bal = c.get("balance", c.get("capital", 0))
    total = bal + p.get("equity", 0)
    await send(
        f"💰 <b>Balance</b>\n\n"
        f"₿ Crypto:     ${bal:.2f}\n"
        f"🎯 Polymarket: ${p.get('equity', 0):.2f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>TOTAL: ${total:.2f}</b>\n\n"
        f"Fees acumulados: ${c.get('total_fees', 0):.4f}",
        reply_markup=MAIN_MENU
    )


async def cmd_pnl():
    c = _load_crypto()
    p = await _load_poly()
    trades = _load_trades()
    today = _today_trades(trades)
    today_w = [t for t in today if t["won"]]
    today_l = [t for t in today if not t["won"]]

    crypto_pnl = c.get("pnl_today", 0)
    total_pnl = crypto_pnl + p.get("pnl_today", 0)
    icon = "📈" if total_pnl >= 0 else "📉"

    msg = (
        f"{icon} <b>PnL Hoy</b>\n\n"
        f"₿ Crypto: ${crypto_pnl:+.4f}\n"
        f"  Grid: ${c.get('grid_pnl', 0):+.4f}\n"
        f"  Momentum: ${c.get('momentum_pnl', 0):+.4f}\n"
        f"  Open: {c.get('momentum_open', 0)} pos\n\n"
    )

    if today:
        today_wr = len(today_w) / len(today) * 100
        msg += (
            f"<b>Trades hoy: {len(today_w)}W/{len(today_l)}L ({today_wr:.0f}%)</b>\n"
        )
        if today_w:
            msg += f"  Avg win: +{sum(t['pnl_pct'] for t in today_w)/len(today_w)*100:.2f}%\n"
        if today_l:
            msg += f"  Avg loss: {sum(t['pnl_pct'] for t in today_l)/len(today_l)*100:.2f}%\n"
    else:
        msg += "Sin trades hoy aún\n"

    msg += f"\n🎯 Polymarket: ${p.get('pnl_today', 0):+.4f}\n\n<b>Total: ${total_pnl:+.4f}</b>"
    await send(msg, reply_markup=MAIN_MENU)


async def cmd_report():
    c = _load_crypto()
    p = await _load_poly()
    trades = _load_trades()
    today = _today_trades(trades)
    today_w = sum(1 for t in today if t["won"])

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = c.get("balance", c.get("capital", 0)) + p.get("equity", 0)
    wr = c.get("momentum_wins", 0) / max(c.get("momentum_wins", 0) + c.get("momentum_losses", 0), 1) * 100

    # Last 50 stats
    last50 = trades[-50:]
    l50w = sum(1 for t in last50 if t["won"])

    await send(
        f"📋 <b>Reporte — {now}</b>\n\n"
        f"💰 Capital: ${total:.2f}\n\n"
        f"━━━ <b>Hoy</b> ━━━\n"
        f"Trades: {today_w}W/{len(today)-today_w}L\n"
        f"PnL: ${c.get('pnl_today', 0):+.4f}\n\n"
        f"━━━ <b>Últimos 50</b> ━━━\n"
        f"WR: {l50w}/50 ({l50w/50*100:.0f}%)\n\n"
        f"━━━ <b>Histórico</b> ━━━\n"
        f"W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)} ({wr:.0f}%)\n"
        f"Momentum PnL: ${c.get('momentum_pnl', 0):+.4f}\n"
        f"Grid PnL: ${c.get('grid_pnl', 0):+.4f}\n"
        f"Fees: ${c.get('total_fees', 0):.4f}\n\n"
        f"🎯 Polymarket: ${p.get('equity', 0):.2f} ({p.get('positions', 0)} pos)",
        reply_markup=MAIN_MENU
    )


async def cmd_dashboard():
    await send(
        "🔗 <b>Dashboards</b>\n\n"
        "📊 Super Dashboard:\nhttp://209.38.36.108:9090\n\n"
        "🎯 Polymarket:\nhttp://209.38.36.108:8080",
        reply_markup=MAIN_MENU
    )


# ═══════════════════════════════════════════════════════════
# CONTROL COMMANDS
# ═══════════════════════════════════════════════════════════

async def cmd_control_menu():
    cmds = _load_commands()
    paused = cmds.get("paused", False)
    mode = cmds.get("mode", "paper")
    capital = cmds.get("capital", 70)
    size_pct = cmds.get("size_pct", 8)

    status = "⏸ PAUSADO" if paused else "▶️ Activo"
    await send(
        f"🎮 <b>Control Panel</b>\n\n"
        f"Estado: {status}\n"
        f"Modo: {mode}\n"
        f"Capital: ${capital}\n"
        f"Size: {size_pct}% (${capital*size_pct/100:.2f}/trade)\n\n"
        f"<b>Acciones:</b>",
        reply_markup=kb([
            ["⏸ Pausar Bot", "▶️ Reanudar Bot"],
            ["🔄 Paper → Live", "🔄 Live → Paper"],
            ["₿ Trades Hoy", "₿ Últimos Trades"],
            ["₿ Momentum", "🎯 Polymarket"],
            ["🏠 Menú"],
        ])
    )


async def cmd_pause():
    _write_command({"paused": True})
    await send("⏸ <b>Bot PAUSADO</b>\n\nNo abrirá nuevas posiciones.\nLas posiciones abiertas seguirán siendo monitoreadas.\n\nPara reanudar: ▶️ Reanudar Bot")


async def cmd_resume():
    _write_command({"paused": False})
    await send("▶️ <b>Bot REANUDADO</b>\n\nVuelve a operar normalmente.")


async def cmd_go_live():
    await send(
        "⚠️ <b>ATENCIÓN</b>\n\n"
        "Cambiar a LIVE significa operar con dinero real.\n"
        "Esto requiere reiniciar el container con MODE=live en .env.\n\n"
        "Por seguridad, este cambio se hace manual en el servidor.\n"
        "El bot seguirá en paper mode.",
        reply_markup=MAIN_MENU
    )


async def cmd_go_paper():
    _write_command({"mode": "paper"})
    await send("📝 Modo: <b>paper</b> confirmado.")


async def cmd_set_capital(val: float):
    if val < 10 or val > 10000:
        await send("❌ Capital debe estar entre $10 y $10,000")
        return
    _write_command({"capital": val})
    cmds = _load_commands()
    size_pct = cmds.get("size_pct", 8)
    await send(
        f"✅ Capital actualizado: <b>${val:.0f}</b>\n"
        f"Size por trade: ${val*size_pct/100:.2f} ({size_pct}%)\n\n"
        f"<i>Se aplica en el próximo ciclo del bot.</i>"
    )


async def cmd_set_size(val: float):
    if val < 1 or val > 20:
        await send("❌ Size debe estar entre 1% y 20%")
        return
    _write_command({"size_pct": val})
    cmds = _load_commands()
    capital = cmds.get("capital", 70)
    await send(
        f"✅ Size actualizado: <b>{val}%</b> (${capital*val/100:.2f}/trade)\n\n"
        f"<i>Se aplica en el próximo ciclo del bot.</i>"
    )


# ═══════════════════════════════════════════════════════════
# TRADES & MOMENTUM
# ═══════════════════════════════════════════════════════════

async def cmd_trades_today():
    trades = _load_trades()
    today = _today_trades(trades)
    if not today:
        await send("₿ Sin trades hoy aún")
        return
    today_w = [t for t in today if t["won"]]
    today_l = [t for t in today if not t["won"]]
    msg = f"₿ <b>Trades Hoy</b> — {len(today_w)}W/{len(today_l)}L\n\n"
    for t in today[-12:]:
        icon = "🟢" if t["won"] else "🔴"
        msg += f"{icon} {t['symbol']:11s} {t['reason']:7s} {t['pnl_pct']*100:+.1f}%\n"
    if today_w:
        msg += f"\nAvg win: +{sum(t['pnl_pct'] for t in today_w)/len(today_w)*100:.2f}%"
    if today_l:
        msg += f"\nAvg loss: {sum(t['pnl_pct'] for t in today_l)/len(today_l)*100:.2f}%"
    await send(msg)


async def cmd_trades_last():
    trades = _load_trades()
    last = trades[-12:]
    if not last:
        await send("₿ Sin trades")
        return
    msg = "₿ <b>Últimos 12 trades</b>\n\n"
    for t in last:
        icon = "🟢" if t["won"] else "🔴"
        msg += f"{icon} {t['symbol']:11s} {t['reason']:7s} {t['pnl_pct']*100:+.1f}%\n"
    wins = sum(1 for t in last if t["won"])
    msg += f"\n{wins}W/{12-wins}L ({wins/12*100:.0f}%)"
    await send(msg)


async def cmd_momentum():
    c = _load_crypto()
    cmds = _load_commands()
    wr = c.get("momentum_wins", 0) / max(c.get("momentum_wins", 0) + c.get("momentum_losses", 0), 1) * 100
    capital = cmds.get("capital", 70)
    size_pct = cmds.get("size_pct", 8)

    trades = _load_trades()
    today = _today_trades(trades)
    today_w = sum(1 for t in today if t["won"])

    await send(
        f"₿ <b>Momentum v6</b>\n\n"
        f"<b>Hoy:</b> {today_w}W/{len(today)-today_w}L\n"
        f"<b>Total:</b> W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)} ({wr:.0f}%)\n"
        f"PnL: ${c.get('momentum_pnl', 0):+.4f}\n"
        f"Open: {c.get('momentum_open', 0)} pos\n\n"
        f"<b>Config:</b>\n"
        f"• Capital: ${capital} | Size: {size_pct}% (${capital*size_pct/100:.2f})\n"
        f"• Min vol: $500k | Min change: +5%\n"
        f"• TP: +4% | SL: -1.5% | Timeout: 2h\n"
        f"• Exits: TP, TRAIL, SL, TIMEOUT\n\n"
        f"<i>Cambiar: </i><code>capital 100</code> <i>o</i> <code>size 10</code>"
    )


async def cmd_poly():
    p = await _load_poly()
    await send(
        f"🎯 <b>Polymarket</b>\n\n"
        f"Equity: ${p.get('equity', 0):.2f}\n"
        f"Posiciones: {p.get('positions', 0)}\n"
        f"Estrategia: tail_end (live)\n\n"
        f"Config: $1/trade | Min edge 3%\n"
        f"SL: -20% | Max days: 14\n\n"
        f"Dashboard: http://209.38.36.108:8080"
    )


# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════

async def cmd_config_menu():
    await send(
        "⚙️ <b>Configuración</b>",
        reply_markup=kb([["⚙️ Config Crypto", "⚙️ Config Poly"], ["🎮 Control", "🏠 Menú"]])
    )


async def cmd_config_crypto():
    cmds = _load_commands()
    capital = cmds.get("capital", 70)
    size_pct = cmds.get("size_pct", 8)
    paused = "⏸ PAUSADO" if cmds.get("paused") else "▶️ Activo"
    await send(
        f"⚙️ <b>Config Crypto Bot v6</b>\n\n"
        f"Estado: {paused}\n"
        f"Mode: paper\n"
        f"Capital: ${capital}\n"
        f"Size: {size_pct}% (${capital*size_pct/100:.2f}/trade)\n"
        f"Max positions: 8\n\n"
        f"Grid: BTC+ETH, ±2%, 8 levels\n"
        f"Momentum v6:\n"
        f"  Min vol: $500k | Min change: +5%\n"
        f"  TP: +4% | SL: -1.5% | Timeout: 2h\n"
        f"  Trailing: aggressive\n"
        f"  Daily loss cap: 8%\n\n"
        f"<b>Cambiar:</b>\n"
        f"<code>capital 100</code> — nuevo capital\n"
        f"<code>size 10</code> — nuevo % por trade"
    )


async def cmd_config_poly():
    await send(
        "⚙️ <b>Config Polymarket</b>\n\n"
        "Mode: live\n"
        "Capital: $3.88 | Size: $1/trade\n"
        "Strategy: tail_end\n"
        "Min edge: 3% | Min price: $0.75\n"
        "Max days: 14 | SL: -20% | TP: +30%\n"
        "Max exposure: 95%"
    )


# ═══════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════

async def poll():
    global last_update_id
    while True:
        try:
            data = await api("getUpdates", offset=last_update_id + 1, timeout=30)
            if data.get("ok"):
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if chat_id == CHAT_ID and text:
                        await handle_message(text)
        except Exception:
            await asyncio.sleep(5)
        await asyncio.sleep(1)


if __name__ == "__main__":
    print("🤖 Telegram Bot v3 started")
    asyncio.run(poll())
