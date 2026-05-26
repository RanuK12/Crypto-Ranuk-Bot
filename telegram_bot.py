"""Telegram Command Bot — unified control panel for both trading bots."""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

TOKEN = os.getenv("TELEGRAM_TOKEN", "8895254248:AAGTy6NYZSphH1q6pa4SwHp2glTaraesgPI")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8107555656")
CRYPTO_STATE = Path("/app/shared/state.json")
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
    handlers = {
        "/start": cmd_menu, "/menu": cmd_menu, "🏠 Menú": cmd_menu,
        "📊 Estado General": cmd_status, "💰 Balance": cmd_balance,
        "📈 PnL Hoy": cmd_pnl, "📋 Reporte": cmd_report,
        "🔗 Dashboard": cmd_dashboard,
        "₿ Crypto Bot": cmd_crypto_menu,
        "₿ Estado Crypto": cmd_crypto_status,
        "₿ Trades Recientes": cmd_crypto_trades,
        "₿ Grid Info": cmd_crypto_grid,
        "₿ Momentum Info": cmd_crypto_momentum,
        "🎯 Polymarket Bot": cmd_poly_menu,
        "🎯 Posiciones": cmd_poly_positions,
        "🎯 PnL Poly": cmd_poly_pnl,
        "⚙️ Configuración": cmd_config_menu,
        "⚙️ Config Crypto": cmd_config_crypto,
        "⚙️ Config Poly": cmd_config_poly,
    }
    handler = handlers.get(text)
    if handler:
        await handler()
    else:
        await send("❓ No entendí. Usá /menu", reply_markup=MAIN_MENU)


# ═══════════════════════════════════════════════════════════
async def cmd_menu():
    await send("🤖 <b>Ranuk Trading System</b>\n\nSeleccioná una opción:", reply_markup=MAIN_MENU)


async def cmd_status():
    c = _load_crypto()
    p = await _load_poly()
    total = c.get("capital", 0) + p.get("equity", 0)
    wr = c.get("momentum_wins", 0) / max(c.get("momentum_wins", 0) + c.get("momentum_losses", 0), 1) * 100
    await send(
        f"📊 <b>Estado General</b>\n\n"
        f"💰 Capital total: <b>${total:.2f}</b>\n\n"
        f"₿ <b>Crypto Bot</b> (🟢 paper)\n"
        f"  Capital: ${c.get('capital', 0):.2f}\n"
        f"  PnL hoy: ${c.get('pnl_today', 0):+.2f}\n"
        f"  Grid: {c.get('grid_trades', 0)} trades, ${c.get('grid_pnl', 0):+.4f}\n"
        f"  Momentum: W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)} ({wr:.0f}%)\n"
        f"  Open: {c.get('momentum_open', 0)} posiciones\n\n"
        f"🎯 <b>Polymarket Bot</b> (🟢 live)\n"
        f"  Equity: ${p.get('equity', 0):.2f}\n"
        f"  Posiciones: {p.get('positions', 0)}",
        reply_markup=MAIN_MENU
    )


async def cmd_balance():
    c = _load_crypto()
    p = await _load_poly()
    total = c.get("capital", 0) + p.get("equity", 0)
    await send(
        f"💰 <b>Balance</b>\n\n"
        f"┌──────────────────────────┐\n"
        f"│ Crypto:     ${c.get('capital', 0):>8.2f}   │\n"
        f"│ Polymarket: ${p.get('equity', 0):>8.2f}   │\n"
        f"├──────────────────────────┤\n"
        f"│ <b>TOTAL:      ${total:>8.2f}</b>   │\n"
        f"└──────────────────────────┘\n\n"
        f"Fees acumulados: ${c.get('total_fees', 0):.4f}",
        reply_markup=MAIN_MENU
    )


async def cmd_pnl():
    c = _load_crypto()
    p = await _load_poly()
    crypto_pnl = c.get("pnl_today", 0)
    poly_pnl = p.get("pnl_today", 0)
    total_pnl = crypto_pnl + poly_pnl
    icon = "📈" if total_pnl >= 0 else "📉"
    await send(
        f"{icon} <b>PnL Hoy</b>\n\n"
        f"₿ Crypto: ${crypto_pnl:+.4f}\n"
        f"  Grid: ${c.get('grid_pnl', 0):+.4f}\n"
        f"  Momentum: ${c.get('momentum_pnl', 0):+.4f}\n"
        f"  Open: {c.get('momentum_open', 0)} pos\n\n"
        f"🎯 Polymarket: ${poly_pnl:+.4f}\n\n"
        f"<b>Total: ${total_pnl:+.4f}</b>",
        reply_markup=MAIN_MENU
    )


async def cmd_report():
    c = _load_crypto()
    p = await _load_poly()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = c.get("capital", 0) + p.get("equity", 0)
    wr = c.get("momentum_wins", 0) / max(c.get("momentum_wins", 0) + c.get("momentum_losses", 0), 1) * 100
    await send(
        f"📋 <b>Reporte — {now}</b>\n\n"
        f"💰 Capital: ${total:.2f}\n\n"
        f"━━━ ₿ Crypto (paper) ━━━\n"
        f"Capital: ${c.get('capital', 0):.2f}\n"
        f"Grid: {c.get('grid_trades', 0)} trades, ${c.get('grid_pnl', 0):+.4f}\n"
        f"Momentum: W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)} ({wr:.0f}% WR)\n"
        f"Momentum PnL: ${c.get('momentum_pnl', 0):+.4f}\n"
        f"Fees: ${c.get('total_fees', 0):.4f}\n\n"
        f"━━━ 🎯 Polymarket (live) ━━━\n"
        f"Equity: ${p.get('equity', 0):.2f}\n"
        f"Posiciones: {p.get('positions', 0)}",
        reply_markup=MAIN_MENU
    )


async def cmd_dashboard():
    await send(
        "🔗 <b>Dashboards</b>\n\n"
        "📊 Super Dashboard: http://209.38.36.108:9090\n"
        "🎯 Polymarket: http://209.38.36.108:8080\n\n"
        "<i>Actualizados en tiempo real.</i>",
        reply_markup=MAIN_MENU
    )


# ── Crypto submenu ──
async def cmd_crypto_menu():
    await send(
        "₿ <b>Crypto Bot</b>\n\nElegí una acción:",
        reply_markup=keyboard([
            ["₿ Estado Crypto", "₿ Trades Recientes"],
            ["₿ Grid Info", "₿ Momentum Info"],
            ["🏠 Menú"],
        ])
    )


async def cmd_crypto_status():
    c = _load_crypto()
    wr = c.get("momentum_wins", 0) / max(c.get("momentum_wins", 0) + c.get("momentum_losses", 0), 1) * 100
    await send(
        f"₿ <b>Crypto Bot — Estado</b>\n\n"
        f"Mode: paper | Capital: ${c.get('capital', 0):.2f}\n"
        f"PnL hoy: ${c.get('pnl_today', 0):+.4f}\n\n"
        f"<b>Grid:</b> ${c.get('grid_pnl', 0):+.4f} ({c.get('grid_trades', 0)} trades)\n"
        f"<b>Momentum:</b> ${c.get('momentum_pnl', 0):+.4f}\n"
        f"  W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)} ({wr:.0f}% WR)\n"
        f"  Open: {c.get('momentum_open', 0)} posiciones\n\n"
        f"Fees: ${c.get('total_fees', 0):.4f}\n"
        f"Actualizado: {_ago(c.get('updated_at', 0))}"
    )


async def cmd_crypto_trades():
    try:
        data = json.loads(TRADES_HISTORY.read_text())
        last = data[-10:]
        msg = "₿ <b>Últimos 10 trades</b>\n\n"
        for t in last:
            icon = "🟢" if t["won"] else "🔴"
            msg += f"{icon} {t['symbol']:12s} {t['reason']:7s} {t['pnl_pct']*100:+.1f}%\n"
        wins_last = sum(1 for t in last if t["won"])
        msg += f"\nÚltimos 10: {wins_last}W/{10-wins_last}L"
        await send(msg)
    except Exception:
        await send("₿ Sin trades disponibles")


async def cmd_crypto_grid():
    c = _load_crypto()
    await send(
        f"₿ <b>Grid Trading</b>\n\n"
        f"Pares: BTC/USDT, ETH/USDT\n"
        f"Rango: ±2% | Niveles: 8\n"
        f"Capital grid: 40% (${c.get('capital', 0) * 0.4:.1f})\n\n"
        f"Trades: {c.get('grid_trades', 0)}\n"
        f"PnL: ${c.get('grid_pnl', 0):+.4f}\n"
        f"Fees: ${c.get('grid_fees', 0):.4f}"
    )


async def cmd_crypto_momentum():
    c = _load_crypto()
    wr = c.get("momentum_wins", 0) / max(c.get("momentum_wins", 0) + c.get("momentum_losses", 0), 1) * 100
    await send(
        f"₿ <b>Momentum Scanner v6</b>\n\n"
        f"W{c.get('momentum_wins', 0)}/L{c.get('momentum_losses', 0)} ({wr:.0f}% WR)\n"
        f"PnL: ${c.get('momentum_pnl', 0):+.4f}\n"
        f"Open: {c.get('momentum_open', 0)} posiciones\n\n"
        f"<b>Configuración:</b>\n"
        f"• Capital: $70 | Size: 8%/trade ($5.60)\n"
        f"• Min vol: $500k | Min change: +5%\n"
        f"• TP: +4% | SL: -1.5% | Timeout: 2h\n"
        f"• Max posiciones: 8\n"
        f"• Exits: TP, TRAIL, SL, TIMEOUT\n\n"
        f"<i>v6: sin FLAT/EARLY exits, filtros data-driven</i>"
    )


# ── Polymarket submenu ──
async def cmd_poly_menu():
    await send(
        "🎯 <b>Polymarket Bot</b>\n\nElegí una acción:",
        reply_markup=keyboard([
            ["🎯 Posiciones", "🎯 PnL Poly"],
            ["🔗 Dashboard", "🏠 Menú"],
        ])
    )


async def cmd_poly_positions():
    try:
        import requests
        funder = "0x1a1405f39232734ef1dbcf9ef06b9da72885f575"
        r = requests.get(f"https://data-api.polymarket.com/positions?user={funder}&sizeThreshold=0.1", timeout=10).json()
        active = [p for p in r if float(p.get("curPrice") or 0) > 0.001]
        if not active:
            await send("🎯 Sin posiciones activas")
            return
        msg = "🎯 <b>Posiciones Polymarket</b>\n\n"
        total_val = 0
        for p in active:
            sz = float(p.get("size") or 0)
            cur = float(p.get("curPrice") or 0)
            val = sz * cur
            total_val += val
            title = (p.get("title") or "")[:35]
            msg += f"• {title}\n  Size: {sz:.2f} @ ${cur:.3f} = ${val:.2f}\n\n"
        msg += f"<b>Valor total posiciones: ${total_val:.2f}</b>"
        await send(msg)
    except Exception as e:
        await send(f"🎯 Error: {e}")


async def cmd_poly_pnl():
    p = await _load_poly()
    await send(
        f"🎯 <b>Polymarket</b>\n\n"
        f"Equity: ${p.get('equity', 0):.2f}\n"
        f"Posiciones: {p.get('positions', 0)}\n"
        f"Estrategia: tail_end (3W/0L)\n\n"
        f"<b>Config:</b>\n"
        f"• Capital: $3.88 | Size: $1/trade\n"
        f"• Min edge: 3% | Min price: $0.75\n"
        f"• SL: -20% | Max days: 14"
    )


# ── Config ──
async def cmd_config_menu():
    await send(
        "⚙️ <b>Configuración</b>\n\nElegí qué ver:",
        reply_markup=keyboard([
            ["⚙️ Config Crypto", "⚙️ Config Poly"],
            ["🏠 Menú"],
        ])
    )


async def cmd_config_crypto():
    await send(
        "⚙️ <b>Config Crypto Bot v6</b>\n\n"
        "<code>"
        "Mode: paper\n"
        "Capital: $70\n"
        "Position size: 8% ($5.60/trade)\n"
        "Max positions: 8\n"
        "Grid: BTC+ETH, ±2%, 8 levels, 40%\n"
        "Momentum v6 (data-driven):\n"
        "  Min volume: $500k\n"
        "  Min change: +5%\n"
        "  TP: +4% | SL: -1.5%\n"
        "  Timeout: 2h (swing)\n"
        "  Trailing: aggressive\n"
        "  NO FLAT/EARLY exits\n"
        "Daily loss cap: 8% ($5.60)\n"
        "Fees: 0.10% taker\n"
        "</code>"
    )


async def cmd_config_poly():
    await send(
        "⚙️ <b>Config Polymarket Bot</b>\n\n"
        "<code>"
        "Mode: live\n"
        "Capital: $3.88\n"
        "Trade size: $1.00\n"
        "Strategy: tail_end\n"
        "Min edge: 3% | Min price: $0.75\n"
        "Max days to resolution: 14\n"
        "SL: -20% | TP: +30%\n"
        "Max exposure: 95%\n"
        "R/R ratio min: 0.7\n"
        "</code>"
    )


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _load_crypto() -> dict:
    for p in [CRYPTO_STATE, Path("/app/state.json")]:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return {}


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
        return "desconocido"
    diff = time.time() - ts
    if diff < 60:
        return f"hace {int(diff)}s"
    if diff < 3600:
        return f"hace {int(diff/60)}min"
    return f"hace {int(diff/3600)}h"


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
    print("🤖 Telegram Bot v2 started")
    asyncio.run(poll())
