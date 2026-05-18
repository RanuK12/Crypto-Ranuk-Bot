"""Unified Dashboard v2 — professional UI, shared state, auto-refresh."""
import json
import time
from pathlib import Path
from aiohttp import web
import aiohttp

# Paths — works both locally and in Docker with shared volume
STATE_FILE = Path("/app/state.json") if Path("/app/state.json").exists() else Path(__file__).parent / "state.json"
TRADES_FILE = Path("/app/trades_history.json") if Path("/app/trades_history.json").exists() else Path(__file__).parent / "trades_history.json"
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
                active.append({"title": p.get("title", "")[:50], "avg": avg, "cur": cur, "size": sz, "pnl": round((cur - avg) * sz, 4), "outcome": p.get("outcome", "")})
        return active
    except Exception:
        return []


async def api_state(request):
    crypto = {}
    for p in [STATE_FILE, Path("state.json"), Path("/opt/ranuk/Crypto-Ranuk-Bot/state.json")]:
        if p.exists():
            try:
                crypto = json.loads(p.read_text())
                break
            except: pass
    poly = await get_poly_data()
    poly_equity = sum(p["size"] * p["cur"] for p in poly) + 0.13
    poly_pnl = sum(p["pnl"] for p in poly)
    trades = []
    for p in [TRADES_FILE, Path("trades_history.json"), Path("/opt/ranuk/Crypto-Ranuk-Bot/trades_history.json")]:
        if p.exists():
            try:
                trades = json.loads(p.read_text())
                break
            except: pass
    return web.json_response({
        "crypto": crypto,
        "poly": {"equity": round(poly_equity, 4), "pnl": round(poly_pnl, 4), "positions": poly},
        "total_capital": round(crypto.get("capital", 20) + poly_equity, 2),
        "total_pnl": round(crypto.get("pnl_today", 0) + poly_pnl, 4),
        "trades_history": trades[-50:],
        "timestamp": time.time(),
    })


async def index(request):
    return web.Response(text=HTML, content_type="text/html")


HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ranuk Trading</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a1a;--card:#111128;--border:#1e1e3a;--accent:#8b5cf6;--green:#10b981;--red:#ef4444;--text:#e2e8f0;--muted:#64748b}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.header{padding:24px 32px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border)}
.header h1{font-size:1.4rem;font-weight:700;display:flex;align-items:center;gap:10px}
.header h1 span{background:linear-gradient(135deg,var(--accent),var(--green));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.live-badge{font-size:.7rem;background:var(--green);color:#000;padding:3px 8px;border-radius:20px;font-weight:600;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
.refresh-info{font-size:.75rem;color:var(--muted);display:flex;align-items:center;gap:8px}
.refresh-info .dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
.container{max-width:1400px;margin:0 auto;padding:24px 32px}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.metric{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:20px;transition:all .2s}
.metric:hover{border-color:var(--accent);transform:translateY(-1px)}
.metric .label{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-weight:500}
.metric .value{font-size:1.8rem;font-weight:700;margin-top:6px}
.metric .change{font-size:.8rem;margin-top:4px;font-weight:500}
.pos{color:var(--green)}.neg{color:var(--red)}
.row{display:grid;grid-template-columns:2fr 1fr;gap:20px;margin-bottom:24px}
@media(max-width:900px){.row{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:20px}
.panel h3{font-size:.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:16px;font-weight:600}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:.7rem;color:var(--muted);text-transform:uppercase;padding:8px 12px;border-bottom:1px solid var(--border)}
td{padding:10px 12px;font-size:.85rem;border-bottom:1px solid var(--border)}
.trade{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-radius:8px;margin-bottom:4px;background:rgba(255,255,255,.02)}
.trade:hover{background:rgba(139,92,246,.05)}
.trade .sym{font-weight:600;font-size:.85rem}
.trade .meta{font-size:.75rem;color:var(--muted)}
.trade .pnl{font-weight:600;font-size:.85rem}
.empty{color:var(--muted);font-size:.85rem;padding:20px;text-align:center}
canvas{max-height:200px}
</style>
</head>
<body>
<div class="header">
  <h1>⚡ <span>Ranuk Trading</span></h1>
  <div class="refresh-info"><div class="dot"></div><span id="timer">Actualizando...</span></div>
</div>
<div class="container">
  <div class="metrics" id="metrics"></div>
  <div class="row">
    <div class="panel"><h3>📈 PnL en tiempo real</h3><canvas id="chart"></canvas></div>
    <div class="panel"><h3>⚡ Últimos trades</h3><div id="trades"></div></div>
  </div>
  <div class="row">
    <div class="panel"><h3>🎯 Posiciones Polymarket</h3><table><thead><tr><th>Mercado</th><th>Entry</th><th>Actual</th><th>PnL</th></tr></thead><tbody id="positions"></tbody></table></div>
    <div class="panel"><h3>₿ Crypto Stats</h3><div id="cryptoStats"></div></div>
  </div>
</div>
<script>
let history=[];let chart;
async function load(){
  try{
    const r=await fetch('/api/state');const d=await r.json();
    renderMetrics(d);renderPositions(d.poly.positions);renderTrades(d.trades_history);renderCrypto(d.crypto);updateChart(d);
    document.getElementById('timer').textContent='Actualizado '+new Date().toLocaleTimeString();
  }catch(e){document.getElementById('timer').textContent='Error de conexión';}
}
function renderMetrics(d){
  const c=d.crypto||{};const wr=c.momentum_wins?Math.round(c.momentum_wins/(c.momentum_wins+(c.momentum_losses||0))*100):0;
  document.getElementById('metrics').innerHTML=`
    <div class="metric"><div class="label">Capital Total</div><div class="value">$${(d.total_capital||0).toFixed(2)}</div><div class="change ${d.total_pnl>=0?'pos':'neg'}">Hoy: $${(d.total_pnl||0).toFixed(4)}</div></div>
    <div class="metric"><div class="label">Polymarket</div><div class="value">$${(d.poly.equity||0).toFixed(2)}</div><div class="change ${d.poly.pnl>=0?'pos':'neg'}">PnL: $${(d.poly.pnl||0).toFixed(4)}</div></div>
    <div class="metric"><div class="label">Crypto Bot</div><div class="value">$${(c.capital||20).toFixed(2)}</div><div class="change ${(c.pnl_today||0)>=0?'pos':'neg'}">PnL: $${(c.pnl_today||0).toFixed(4)}</div></div>
    <div class="metric"><div class="label">Grid</div><div class="value">${c.grid_trades||0}</div><div class="change ${(c.grid_pnl||0)>=0?'pos':'neg'}">$${(c.grid_pnl||0).toFixed(4)}</div></div>
    <div class="metric"><div class="label">Momentum</div><div class="value">W${c.momentum_wins||0}/L${c.momentum_losses||0}</div><div class="change">${wr}% winrate</div></div>
    <div class="metric"><div class="label">Fees</div><div class="value neg">$${(c.total_fees||0).toFixed(4)}</div><div class="change">Binance 0.10%</div></div>
  `;
}
function renderPositions(pos){
  const tb=document.getElementById('positions');
  if(!pos||!pos.length){tb.innerHTML='<tr><td colspan="4" class="empty">Sin posiciones activas — capital libre</td></tr>';return;}
  tb.innerHTML=pos.map(p=>`<tr><td>${p.title}</td><td>$${p.avg.toFixed(4)}</td><td>$${p.cur.toFixed(4)}</td><td class="${p.pnl>=0?'pos':'neg'}">$${p.pnl.toFixed(3)}</td></tr>`).join('');
}
function renderTrades(trades){
  const div=document.getElementById('trades');
  if(!trades||!trades.length){div.innerHTML='<div class="empty">Sin trades aún</div>';return;}
  div.innerHTML=trades.slice(-8).reverse().map(t=>{
    const icon=t.won?'🟢':'🔴';const cls=t.won?'pos':'neg';
    return`<div class="trade"><div><div class="sym">${icon} ${t.symbol}</div><div class="meta">${t.reason} · ${new Date(t.exit_time*1000).toLocaleTimeString()}</div></div><div class="pnl ${cls}">${(t.pnl_pct*100).toFixed(1)}%</div></div>`;
  }).join('');
}
function renderCrypto(c){
  if(!c||!c.capital){document.getElementById('cryptoStats').innerHTML='<div class="empty">Esperando datos...</div>';return;}
  const wr=c.momentum_wins?Math.round(c.momentum_wins/(c.momentum_wins+(c.momentum_losses||0))*100):0;
  document.getElementById('cryptoStats').innerHTML=`
    <div class="trade"><div class="sym">Grid PnL</div><div class="pnl ${(c.grid_pnl||0)>=0?'pos':'neg'}">$${(c.grid_pnl||0).toFixed(4)}</div></div>
    <div class="trade"><div class="sym">Grid Trades</div><div class="pnl">${c.grid_trades||0}</div></div>
    <div class="trade"><div class="sym">Momentum PnL</div><div class="pnl ${(c.momentum_pnl||0)>=0?'pos':'neg'}">$${(c.momentum_pnl||0).toFixed(4)}</div></div>
    <div class="trade"><div class="sym">Win Rate</div><div class="pnl">${wr}%</div></div>
    <div class="trade"><div class="sym">Open Positions</div><div class="pnl">${c.momentum_open||0}</div></div>
    <div class="trade"><div class="sym">Fees Grid</div><div class="pnl neg">$${(c.grid_fees||0).toFixed(4)}</div></div>
  `;
}
function updateChart(d){
  history.push({t:Date.now(),v:d.total_pnl||0,c:d.crypto?.pnl_today||0,p:d.poly?.pnl||0});
  if(history.length>200)history.shift();
  if(!chart){
    chart=new Chart(document.getElementById('chart'),{type:'line',data:{labels:[],datasets:[
      {label:'Total',data:[],borderColor:'#8b5cf6',backgroundColor:'rgba(139,92,246,.1)',fill:true,tension:.4,borderWidth:2},
      {label:'Crypto',data:[],borderColor:'#10b981',borderWidth:1,tension:.4,pointRadius:0},
      {label:'Poly',data:[],borderColor:'#f59e0b',borderWidth:1,tension:.4,pointRadius:0},
    ]},options:{responsive:true,interaction:{intersect:false},plugins:{legend:{labels:{color:'#64748b',font:{size:11}}}},scales:{x:{display:false},y:{grid:{color:'#1e1e3a'},ticks:{color:'#64748b',callback:v=>'$'+v.toFixed(3)}}}}});
  }
  chart.data.labels=history.map((_,i)=>i);
  chart.data.datasets[0].data=history.map(h=>h.v);
  chart.data.datasets[1].data=history.map(h=>h.c);
  chart.data.datasets[2].data=history.map(h=>h.p);
  chart.update('none');
}
load();setInterval(load,10000);
</script>
</body>
</html>"""

app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/api/state", api_state)

if __name__ == "__main__":
    print("Dashboard v2 running on http://0.0.0.0:9090")
    web.run_app(app, host="0.0.0.0", port=9090, print=None)
