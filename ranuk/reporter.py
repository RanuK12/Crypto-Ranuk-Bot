"""Daily PDF report generator — creates a summary of both bots' performance."""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def generate_daily_report(crypto_state: dict, poly_state: dict = None) -> tuple[str, str]:
    """Generate text summary + HTML report file. Returns (text, filepath)."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # Crypto bot stats
    c_cap = crypto_state.get("capital", 0)
    c_pnl = crypto_state.get("pnl_today", 0)
    c_grid_pnl = crypto_state.get("grid_pnl", 0)
    c_grid_trades = crypto_state.get("grid_trades", 0)
    c_mom_pnl = crypto_state.get("momentum_pnl", 0)
    c_mom_w = crypto_state.get("momentum_wins", 0)
    c_mom_l = crypto_state.get("momentum_losses", 0)
    c_fees = crypto_state.get("total_fees", 0)

    # Polymarket stats
    p_equity = poly_state.get("equity", 0) if poly_state else 0
    p_pnl = poly_state.get("pnl_today", 0) if poly_state else 0
    p_positions = poly_state.get("positions", 0) if poly_state else 0

    total_capital = c_cap + p_equity
    total_pnl = c_pnl + p_pnl

    # Text summary for Telegram
    text = (
        f"📅 <b>{date_str}</b>\n\n"
        f"💰 <b>Capital total: ${total_capital:.2f}</b>\n"
        f"📈 PnL hoy: <b>${total_pnl:+.4f}</b>\n\n"
        f"━━━ Crypto Bot ━━━\n"
        f"  Capital: ${c_cap:.2f}\n"
        f"  Grid: {c_grid_trades} trades, ${c_grid_pnl:+.4f}\n"
        f"  Momentum: W{c_mom_w}/L{c_mom_l}, ${c_mom_pnl:+.4f}\n"
        f"  Fees: ${c_fees:.4f}\n\n"
        f"━━━ Polymarket Bot ━━━\n"
        f"  Equity: ${p_equity:.2f}\n"
        f"  PnL hoy: ${p_pnl:+.4f}\n"
        f"  Posiciones: {p_positions}\n"
    )

    # HTML report (viewable as PDF via browser print)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ranuk Daily Report {date_str}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; }}
h1 {{ color: #1a1a2e; border-bottom: 2px solid #16213e; padding-bottom: 10px; }}
.stat {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #eee; }}
.positive {{ color: #00b894; font-weight: bold; }}
.negative {{ color: #d63031; font-weight: bold; }}
.section {{ margin: 20px 0; padding: 15px; background: #f8f9fa; border-radius: 8px; }}
</style></head><body>
<h1>📊 Ranuk Trading Report</h1>
<p><b>Fecha:</b> {date_str} | <b>Capital total:</b> ${total_capital:.2f}</p>

<div class="section">
<h3>💰 Resumen</h3>
<div class="stat"><span>PnL del día</span><span class="{'positive' if total_pnl >= 0 else 'negative'}">${total_pnl:+.4f}</span></div>
<div class="stat"><span>Fees pagados</span><span>${c_fees:.4f}</span></div>
</div>

<div class="section">
<h3>₿ Crypto Bot</h3>
<div class="stat"><span>Capital</span><span>${c_cap:.2f}</span></div>
<div class="stat"><span>Grid trades</span><span>{c_grid_trades}</span></div>
<div class="stat"><span>Grid PnL</span><span class="{'positive' if c_grid_pnl >= 0 else 'negative'}">${c_grid_pnl:+.4f}</span></div>
<div class="stat"><span>Momentum W/L</span><span>{c_mom_w}/{c_mom_l}</span></div>
<div class="stat"><span>Momentum PnL</span><span class="{'positive' if c_mom_pnl >= 0 else 'negative'}">${c_mom_pnl:+.4f}</span></div>
</div>

<div class="section">
<h3>🎯 Polymarket Bot</h3>
<div class="stat"><span>Equity</span><span>${p_equity:.2f}</span></div>
<div class="stat"><span>PnL hoy</span><span class="{'positive' if p_pnl >= 0 else 'negative'}">${p_pnl:+.4f}</span></div>
<div class="stat"><span>Posiciones abiertas</span><span>{p_positions}</span></div>
</div>

<p style="color:#999;font-size:12px;margin-top:30px;">Generado automáticamente por Ranuk Trading System</p>
</body></html>"""

    filepath = REPORTS_DIR / f"report_{date_str}.html"
    filepath.write_text(html)
    return text, str(filepath)
