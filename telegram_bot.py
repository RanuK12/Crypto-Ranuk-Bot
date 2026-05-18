"""Telegram Command Bot — unified control panel for both trading bots.

Runs as a separate process, reads state from both bots, sends commands.
Never crashes the main bots — it's read-only + sends signals via files.
"""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

TOKEN = os.getenv("TELEGRAM_TOKEN", "8895254248:AAGTy6NYZSphH1q6pa4SwHp2glTaraesgPI")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8107555656")
CRYPTO_STATE = Path("/Users/emilioranucoli/Desktop/Oficina_Ranuk/Ranuk-Profit-Bot/state.json")
POLY_DIR = Path("/Users/emilioranucoli/Desktop/Oficina_Ranuk/Bot-Copy-Trading-Ranuk")
API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Track last update to avoid reprocessing
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


def keyboard(buttons: list[list[str]]):
    return {"keyboard": buttons, "resize_keyboard": True, "one_time_keyboard": False}


MAIN_MENU = keyboard([
    ["📊 Estado General", "💰 Balance"],
    ["₿ Crypto Bot", "🎯 Polymarket Bot"],
    ["📈 PnL Hoy", "📋 Reporte"],
    ["⚙️ Configuración", "🔗 Dashboard"],
])


async def handle_message(text: str):
    text = text.strip()

    if text in ("/start", "/menu", "🏠 Menú"):
        await send(
            "🤖 <b>Ranuk Trading System</b>\n\n"
            "Seleccioná una opción del menú:",
            reply_markup=MAIN_MENU
        )

    elif text == "📊 Estado General":
        await cmd_status()

    elif text == "💰 Balance":
        await cmd_balance()

    elif text == "₿ Crypto Bot":
        await send(
            "₿ <b>Crypto Bot</b>\n\nElegí una acción:",
            reply_markup=keyboard([
                ["₿ Estado Crypto", "₿ Trades Hoy"],
                ["₿ Grid Info", "₿ Momentum Info"],
                ["🏠 Menú"],
            ])
        )

    elif text == "🎯 Polymarket Bot":
        await send(
            "🎯 <b>Polymarket Bot</b>\n\nElegí una acción:",
            reply_markup=keyboard([
                ["🎯 Posiciones", "🎯 PnL Poly"],
                ["🎯 Wallets Activas", "🔗 Dashboard"],
                ["🏠 Menú"],
            ])
        )

    elif text == "📈 PnL Hoy":
        await cmd_pnl()

    elif text == "📋 Reporte":
        await cmd_report()

    elif text == "⚙️ Configuración":
        await send(
            "⚙️ <b>Configuración</b>\n\nElegí qué ver:",
            reply_markup=keyboard([
                ["⚙️ Config Crypto", "⚙️ Config Poly"],
                ["⚙️ Intelligence Rules", "⚙️ Fees"],
                ["🏠 Menú"],
            ])
        )

    elif text == "🔗 Dashboard":
        await send(
            "🔗 <b>Dashboard Polymarket</b>\n\n"
            "📍 Local: http://localhost:8080\n"
            "📍 DigitalOcean: http://&lt;TU_IP&gt;:8080\n\n"
            "<i>El dashboard muestra posiciones, PnL, y estrategias en tiempo real.</i>"
        )

    # ── Crypto subcommands ──
    elif text == "₿ Estado Crypto":
        await cmd_crypto_status()

    elif text == "₿ Trades Hoy":
        await cmd_crypto_trades()

    elif text == "₿ Grid Info":
        await cmd_crypto_grid()

    elif text == "₿ Momentum Info":
        await cmd_crypto_momentum()

    # ── Polymarket subcommands ──
    elif text == "🎯 Posiciones":
        await cmd_poly_positions()

    elif text == "🎯 PnL Poly":
        await cmd_poly_pnl()

    elif text == "🎯 Wallets Activas":
        await cmd_poly_wallets()

    # ── Config subcommands ──
    elif text == "⚙️ Config Crypto":
        await cmd_config_crypto()

    elif text == "⚙️ Config Poly":
        await cmd_config_poly()

    elif text == "⚙️ Intelligence Rules":
        await cmd_intelligence()

    elif text == "⚙️ Fees":
        await cmd_fees()

    else:
        await send("❓ No entendí. Usá el menú o escribí /menu", reply_markup=MAIN_MENU)


# ═══════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════

async def cmd_status():
    c = _load_crypto()
    p = await _load_poly()
    total = c.get("capital", 0) + p.get("equity", 0)
    await send(
        f"📊 <b>Estado General</b>\n\n"
        f"💰 Capital total: <b>${total:.2f}</b>\n\n"
        f"₿ <b>Crypto Bot</b> ({'🟢 paper' if True else '🔴 live'})\n"
        f"  Capital: ${c.get('capital', 0):.2f}\n"
        f"  PnL hoy: ${c.get('pnl_today', 0):+.4f}\n"
        f"  Grid trades: {c.get('grid_trades', 0)}\n"
        f"  Momentum: W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)}\n\n"
        f"🎯 <b>Polymarket Bot</b> (🟢 live)\n"
        f"  Equity: ${p.get('equity', 0):.2f}\n"
        f"  Posiciones: {p.get('positions', 0)}\n"
        f"  PnL hoy: ${p.get('pnl_today', 0):+.4f}",
        reply_markup=MAIN_MENU
    )


async def cmd_balance():
    c = _load_crypto()
    p = await _load_poly()
    total = c.get("capital", 0) + p.get("equity", 0)
    await send(
        f"💰 <b>Balance</b>\n\n"
        f"┌─────────────────────────┐\n"
        f"│ Crypto:     ${c.get('capital', 0):>8.2f}  │\n"
        f"│ Polymarket: ${p.get('equity', 0):>8.2f}  │\n"
        f"├─────────────────────────┤\n"
        f"│ <b>TOTAL:      ${total:>8.2f}</b>  │\n"
        f"└─────────────────────────┘\n\n"
        f"Fees hoy: ${c.get('total_fees', 0):.4f}",
        reply_markup=MAIN_MENU
    )


async def cmd_pnl():
    c = _load_crypto()
    p = await _load_poly()
    total_pnl = c.get("pnl_today", 0) + p.get("pnl_today", 0)
    icon = "📈" if total_pnl >= 0 else "📉"
    await send(
        f"{icon} <b>PnL Hoy</b>\n\n"
        f"₿ Crypto: ${c.get('pnl_today', 0):+.4f}\n"
        f"  Grid: ${c.get('grid_pnl', 0):+.4f}\n"
        f"  Momentum: ${c.get('momentum_pnl', 0):+.4f}\n\n"
        f"🎯 Polymarket: ${p.get('pnl_today', 0):+.4f}\n\n"
        f"<b>Total: ${total_pnl:+.4f}</b>",
        reply_markup=MAIN_MENU
    )


async def cmd_report():
    c = _load_crypto()
    p = await _load_poly()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = c.get("capital", 0) + p.get("equity", 0)
    await send(
        f"📋 <b>Reporte — {now}</b>\n\n"
        f"💰 Capital total: ${total:.2f}\n"
        f"📈 PnL combinado: ${c.get('pnl_today', 0) + p.get('pnl_today', 0):+.4f}\n\n"
        f"━━━ ₿ Crypto ━━━\n"
        f"Capital: ${c.get('capital', 0):.2f}\n"
        f"Grid: {c.get('grid_trades', 0)} trades, ${c.get('grid_pnl', 0):+.4f}\n"
        f"Momentum: W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)}, ${c.get('momentum_pnl', 0):+.4f}\n"
        f"Fees: ${c.get('total_fees', 0):.4f}\n\n"
        f"━━━ 🎯 Polymarket ━━━\n"
        f"Equity: ${p.get('equity', 0):.2f}\n"
        f"Posiciones: {p.get('positions', 0)}\n"
        f"PnL: ${p.get('pnl_today', 0):+.4f}",
        reply_markup=MAIN_MENU
    )


async def cmd_crypto_status():
    c = _load_crypto()
    await send(
        f"₿ <b>Crypto Bot — Estado</b>\n\n"
        f"Capital: ${c.get('capital', 0):.2f}\n"
        f"PnL hoy: ${c.get('pnl_today', 0):+.4f}\n"
        f"Grid PnL: ${c.get('grid_pnl', 0):+.4f} ({c.get('grid_trades', 0)} trades)\n"
        f"Momentum PnL: ${c.get('momentum_pnl', 0):+.4f}\n"
        f"Momentum W/L: {c.get('momentum_wins', 0)}/{c.get('momentum_losses', 0)}\n"
        f"Posiciones abiertas: {c.get('momentum_open', 0)}\n"
        f"Fees: ${c.get('total_fees', 0):.4f}\n"
        f"Última actualización: {_ago(c.get('updated_at', 0))}"
    )


async def cmd_crypto_trades():
    log_path = Path("/Users/emilioranucoli/Desktop/Oficina_Ranuk/Ranuk-Profit-Bot/bot.log")
    if not log_path.exists():
        await send("₿ Sin log disponible")
        return
    import re
    log = log_path.read_text()[-5000:]
    log = re.sub(r'\x1b\[[0-9;]*m', '', log)
    trades = [l for l in log.split('\n') if 'MOM' in l or 'GRID SELL' in l][-10:]
    if not trades:
        await send("₿ Sin trades recientes hoy")
        return
    msg = "₿ <b>Últimos trades</b>\n\n"
    for t in trades:
        msg += f"<code>{t[:80]}</code>\n"
    await send(msg)


async def cmd_crypto_grid():
    c = _load_crypto()
    await send(
        f"₿ <b>Grid Trading</b>\n\n"
        f"Pares: BTC/USDT, ETH/USDT\n"
        f"Rango: ±3%\n"
        f"Niveles: 4 por par\n"
        f"Trades ejecutados: {c.get('grid_trades', 0)}\n"
        f"PnL grid: ${c.get('grid_pnl', 0):+.4f}\n"
        f"Fees grid: ${c.get('grid_fees', 0):.4f}"
    )


async def cmd_crypto_momentum():
    c = _load_crypto()
    wr = c.get('momentum_wins', 0) / max(c.get('momentum_wins', 0) + c.get('momentum_losses', 0), 1) * 100
    await send(
        f"₿ <b>Momentum Scanner</b>\n\n"
        f"Wins: {c.get('momentum_wins', 0)}\n"
        f"Losses: {c.get('momentum_losses', 0)}\n"
        f"Win rate: {wr:.0f}%\n"
        f"PnL: ${c.get('momentum_pnl', 0):+.4f}\n"
        f"Posiciones abiertas: {c.get('momentum_open', 0)}\n"
        f"Fees: ${c.get('momentum_fees', 0):.4f}\n\n"
        f"⏰ Horas activas: 01-07h Argentina\n"
        f"🎯 TP: +12% | SL: -3% | Early: -1.5%/30min"
    )


async def cmd_poly_positions():
    try:
        import requests
        funder = "0x1a1405f39232734ef1dbcf9ef06b9da72885f575"
        r = requests.get(f"https://data-api.polymarket.com/positions?user={funder}&sizeThreshold=0.1", timeout=10).json()
        active = [p for p in r if float(p.get("curPrice") or 0) > 0.001]
        if not active:
            await send("🎯 Sin posiciones activas (capital libre para nuevas oportunidades)")
            return
        msg = "🎯 <b>Posiciones Polymarket</b>\n\n"
        total_pnl = 0
        for p in active:
            sz = float(p.get("size") or 0)
            avg = float(p.get("avgPrice") or 0)
            cur = float(p.get("curPrice") or 0)
            pnl = (cur - avg) * sz
            total_pnl += pnl
            title = (p.get("title") or "")[:35]
            icon = "🟢" if pnl > 0 else "🔴"
            msg += f"{icon} {title}\n   PnL: ${pnl:+.3f} (cur={cur:.3f})\n\n"
        msg += f"<b>Total unrealized: ${total_pnl:+.3f}</b>"
        await send(msg)
    except Exception as e:
        await send(f"🎯 Error consultando Polymarket: {e}")


async def cmd_poly_pnl():
    p = await _load_poly()
    await send(
        f"🎯 <b>Polymarket PnL</b>\n\n"
        f"Equity: ${p.get('equity', 0):.2f}\n"
        f"PnL hoy: ${p.get('pnl_today', 0):+.4f}\n"
        f"Posiciones: {p.get('positions', 0)}"
    )


async def cmd_poly_wallets():
    await send(
        "🎯 <b>Wallets monitoreadas</b>\n\n"
        "El bot copia trades de wallets top del leaderboard.\n"
        "Se actualizan cada 12h automáticamente.\n\n"
        "Filtros activos:\n"
        "• Win rate ≥ 50%\n"
        "• PnL total ≥ $500\n"
        "• No copiar eventos deportivos en vivo\n"
        "• No copiar wallets en pánico/liquidación"
    )


async def cmd_config_crypto():
    await send(
        "⚙️ <b>Config Crypto Bot</b>\n\n"
        "<code>"
        "Mode: paper\n"
        "Capital: $20\n"
        "Grid: BTC+ETH, ±3%, 4 levels\n"
        "Momentum: TP +12%, SL -3%\n"
        "Max per token: 10% ($2)\n"
        "Daily loss cap: 5% ($1)\n"
        "Fees: 0.10% taker\n"
        "</code>"
    )


async def cmd_config_poly():
    await send(
        "⚙️ <b>Config Polymarket Bot</b>\n\n"
        "<code>"
        "Mode: live\n"
        "Capital: ~$4.62\n"
        "Strategies: tail_end + smart_copy\n"
        "SL: 20% | TP: 30%\n"
        "Min entry price: $0.30\n"
        "Min hours to end: 3h\n"
        "Max price drift: 15%\n"
        "</code>"
    )


async def cmd_intelligence():
    intel_path = Path("/Users/emilioranucoli/Desktop/Oficina_Ranuk/Ranuk-Profit-Bot/trades_history.json")
    if intel_path.exists():
        trades = json.loads(intel_path.read_text())
        wins = sum(1 for t in trades if t.get("won"))
        losses = len(trades) - wins
        wr = wins / max(len(trades), 1) * 100
    else:
        trades, wins, losses, wr = [], 0, 0, 0
    await send(
        f"⚙️ <b>Intelligence Rules</b>\n\n"
        f"Trades históricos: {len(trades)}\n"
        f"Win rate histórico: {wr:.0f}%\n\n"
        f"<b>Reglas aprendidas:</b>\n"
        f"⏰ Horas: 01-07h Argentina\n"
        f"📊 Volumen: $176k - $2M\n"
        f"🚫 Blacklist: memecoins, PNUT, KITE, etc\n"
        f"✂️ Early exit: -1.5% después de 30min\n"
        f"🚀 No entrar si ya subió +20%\n\n"
        f"<i>Se auto-actualiza con cada trade</i>"
    )


async def cmd_fees():
    c = _load_crypto()
    await send(
        f"⚙️ <b>Fees acumulados</b>\n\n"
        f"₿ Crypto total: ${c.get('total_fees', 0):.4f}\n"
        f"  Grid: ${c.get('grid_fees', 0):.4f}\n"
        f"  Momentum: ${c.get('momentum_fees', 0):.4f}\n\n"
        f"🎯 Polymarket: incluidos en PnL\n\n"
        f"<i>Fee rate: 0.10% por trade (Binance VIP0)</i>"
    )


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _load_crypto() -> dict:
    try:
        return json.loads(CRYPTO_STATE.read_text())
    except Exception:
        return {}


async def _load_poly() -> dict:
    try:
        import requests
        funder = "0x1a1405f39232734ef1dbcf9ef06b9da72885f575"
        r = requests.get(f"https://data-api.polymarket.com/positions?user={funder}&sizeThreshold=0.1", timeout=10).json()
        active = [p for p in r if float(p.get("curPrice") or 0) > 0.001]
        total_val = sum(float(p.get("size", 0)) * float(p.get("curPrice", 0)) for p in active)
        return {"equity": total_val + 0.13, "positions": len(active), "pnl_today": 0.0}
    except Exception:
        return {"equity": 0, "positions": 0, "pnl_today": 0}


def _ago(ts: float) -> str:
    if not ts:
        return "desconocido"
    diff = time.time() - ts
    if diff < 60:
        return f"hace {int(diff)}s"
    if diff < 3600:
        return f"hace {int(diff/60)}min"
    return f"hace {int(diff/3600)}h"


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
    print("🤖 Telegram Command Bot started. Listening...")
    asyncio.run(poll())
