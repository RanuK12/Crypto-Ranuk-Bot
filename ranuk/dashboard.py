"""Unified Dashboard — serves a modern web UI showing both bots' performance."""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from aiohttp import web
import aiohttp

STATE_FILE = Path(__file__).parent / "state.json"
TRADES_FILE = Path(__file__).parent / "trades_history.json"
POLY_FUNDER = "0x1a1405f39232734ef1dbcf9ef06b9da72885f575"


async def get_poly_data():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://data-api.polymarket.com/positions?user={POLY_FUNDER}&sizeThreshold=0.1", timeout=aiohttp.ClientTimeout(total=10)) as r:
                positions = await r.json()
        active = []
        for p in positions:
            cur = float(p.get("curPrice") or 0)
            if cur > 0.001:
                avg = float(p.get("avgPrice") or 0)
                sz = float(p.get("size") or 0)
                active.append({"title": p.get("title", "")[:50], "avg": avg, "cur": cur, "size": sz, "pnl": (cur - avg) * sz})
        return active
    except Exception:
        return []


async def api_state(request):
    crypto = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    poly = await get_poly_data()
    poly_equity = sum(p["size"] * p["cur"] for p in poly)
    poly_pnl = sum(p["pnl"] for p in poly)
    trades = json.loads(TRADES_FILE.read_text()) if TRADES_FILE.exists() else []
    return web.json_response({
        "crypto": crypto,
        "poly": {"equity": poly_equity, "pnl": poly_pnl, "positions": poly},
        "total_capital": crypto.get("capital", 0) + poly_equity,
        "total_pnl": crypto.get("pnl_today", 0) + poly_pnl,
        "trades_history": trades[-50:],
        "timestamp": time.time(),
    })


async def index(request):
    return web.Response(text=HTML, content_type="text/html")


HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ranuk Trading Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f23; color: #e0e0e0; min-height: 100vh; }
.header { background: linear-gradient(135deg, #1a1a3e 0%, #0f0f23 100%); padding: 20px 30px; border-bottom: 1px solid #2a2a4a; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 1.5rem; background: linear-gradient(90deg, #00d4aa, #7c3aed); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.header .status { display: flex; gap: 15px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 5px; }
.status-dot.live { background: #00d4aa; box-shadow: 0 0 6px #00d4aa; }
.status-dot.paper { background: #f59e0b; box-shadow: 0 0 6px #f59e0b; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; padding: 20px 30px; }
.card { background: #1a1a3e; border-radius: 12px; padding: 20px; border: 1px solid #2a2a4a; transition: transform 0.2s; }
.card:hover { transform: translateY(-2px); border-color: #7c3aed; }
.card h3 { font-size: 0.85rem; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
.card .value { font-size: 2rem; font-weight: 700; }
.card .sub { font-size: 0.85rem; color: #666; margin-top: 4px; }
.positive { color: #00d4aa; }
.negative { color: #ef4444; }
.neutral { color: #e0e0e0; }
.chart-container { background: #1a1a3e; border-radius: 12px; padding: 20px; border: 1px solid #2a2a4a; margin: 0 30px 20px; }
.chart-container h3 { color: #888; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 15px; }
.positions { margin: 0 30px 20px; }
.positions h3 { color: #888; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; }
.pos-table { width: 100%; border-collapse: collapse; background: #1a1a3e; border-radius: 12px; overflow: hidden; border: 1px solid #2a2a4a; }
.pos-table th { background: #12122a; padding: 12px 15px; text-align: left; font-size: 0.75rem; color: #888; text-transform: uppercase; }
.pos-table td { padding: 12px 15px; border-top: 1px solid #2a2a4a; font-size: 0.9rem; }
.trades-list { margin: 0 30px 20px; }
.trade-item { display: flex; justify-content: space-between; padding: 10px 15px; background: #1a1a3e; border-radius: 8px; margin-bottom: 6px; border: 1px solid #2a2a4a; font-size: 0.85rem; }
.refresh { font-size: 0.75rem; color: #555; text-align: center; padding: 10px; }
</style>
</head>
<body>
<div class="header">
  <h1>⚡ Ranuk Trading System</h1>
  <div class="status">
    <span><span class="status-dot live"></span>Polymarket</span>
    <span><span class="status-dot paper"></span>Crypto</span>
  </div>
</div>

<div class="grid" id="cards"></div>
<div class="chart-container"><h3>PnL History</h3><canvas id="pnlChart" height="80"></canvas></div>
<div class="positions"><h3>Polymarket Positions</h3><table class="pos-table" id="polyTable"><thead><tr><th>Market</th><th>Entry</th><th>Current</th><th>PnL</th></tr></thead><tbody></tbody></table></div>
<div class="trades-list"><h3>Recent Momentum Trades</h3><div id="tradesList"></div></div>
<div class="refresh" id="lastUpdate"></div>

<script>
let pnlHistory = [];
let chart;

async function fetchData() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();
    updateCards(d);
    updatePositions(d.poly.positions);
    updateTrades(d.trades_history);
    updateChart(d);
    document.getElementById('lastUpdate').textContent = 'Last update: ' + new Date().toLocaleTimeString();
  } catch(e) { console.error(e); }
}

function updateCards(d) {
  const c = d.crypto || {};
  const totalPnl = d.total_pnl || 0;
  const pnlClass = totalPnl >= 0 ? 'positive' : 'negative';
  const wr = c.momentum_wins ? ((c.momentum_wins / (c.momentum_wins + (c.momentum_losses||0))) * 100).toFixed(0) : '0';
  document.getElementById('cards').innerHTML = `
    <div class="card"><h3>💰 Capital Total</h3><div class="value neutral">$${(d.total_capital||0).toFixed(2)}</div><div class="sub">Crypto + Polymarket</div></div>
    <div class="card"><h3>📈 PnL Hoy</h3><div class="value ${pnlClass}">$${totalPnl.toFixed(4)}</div><div class="sub">Combinado ambos bots</div></div>
    <div class="card"><h3>₿ Crypto Bot</h3><div class="value neutral">$${(c.capital||0).toFixed(2)}</div><div class="sub">Grid: ${c.grid_trades||0} trades | Mom: W${c.momentum_wins||0}/L${c.momentum_losses||0} (${wr}%)</div></div>
    <div class="card"><h3>🎯 Polymarket</h3><div class="value neutral">$${(d.poly?.equity||0).toFixed(2)}</div><div class="sub">${d.poly?.positions?.length||0} posiciones activas</div></div>
    <div class="card"><h3>📊 Grid PnL</h3><div class="value ${(c.grid_pnl||0)>=0?'positive':'negative'}">$${(c.grid_pnl||0).toFixed(4)}</div><div class="sub">${c.grid_trades||0} trades ejecutados</div></div>
    <div class="card"><h3>💸 Fees Pagados</h3><div class="value negative">$${(c.total_fees||0).toFixed(4)}</div><div class="sub">Binance 0.10% taker</div></div>
  `;
}

function updatePositions(positions) {
  const tbody = document.querySelector('#polyTable tbody');
  if (!positions || !positions.length) { tbody.innerHTML = '<tr><td colspan="4" style="color:#555">Sin posiciones activas</td></tr>'; return; }
  tbody.innerHTML = positions.map(p => {
    const pnlClass = p.pnl >= 0 ? 'positive' : 'negative';
    return `<tr><td>${p.title}</td><td>$${p.avg.toFixed(4)}</td><td>$${p.cur.toFixed(4)}</td><td class="${pnlClass}">$${p.pnl.toFixed(3)}</td></tr>`;
  }).join('');
}

function updateTrades(trades) {
  const div = document.getElementById('tradesList');
  if (!trades || !trades.length) { div.innerHTML = '<div class="trade-item" style="color:#555">Sin trades registrados</div>'; return; }
  div.innerHTML = trades.slice(-10).reverse().map(t => {
    const icon = t.won ? '🟢' : '🔴';
    return `<div class="trade-item"><span>${icon} ${t.symbol} (${t.reason})</span><span class="${t.won?'positive':'negative'}">${(t.pnl_pct*100).toFixed(1)}%</span></div>`;
  }).join('');
}

function updateChart(d) {
  pnlHistory.push({ t: Date.now(), v: d.total_pnl || 0 });
  if (pnlHistory.length > 100) pnlHistory.shift();
  if (!chart) {
    chart = new Chart(document.getElementById('pnlChart'), {
      type: 'line',
      data: { labels: [], datasets: [{ label: 'PnL', data: [], borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.1)', fill: true, tension: 0.4 }] },
      options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { grid: { color: '#2a2a4a' }, ticks: { color: '#888' } } } }
    });
  }
  chart.data.labels = pnlHistory.map((_, i) => i);
  chart.data.datasets[0].data = pnlHistory.map(p => p.v);
  chart.update('none');
}

fetchData();
setInterval(fetchData, 15000);
</script>
</body>
</html>"""


app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/api/state", api_state)


def run_dashboard(port=9090):
    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    print(f"Dashboard running on http://0.0.0.0:9090")
    run_dashboard()
