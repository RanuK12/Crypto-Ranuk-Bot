"""Unified Dashboard v3 — fixed Polymarket display + shared state."""
import json
import time
from pathlib import Path
from aiohttp import web
import aiohttp

SHARED_STATE = Path("/app/shared/state.json")
STATE_FILE = Path("/app/state.json")
SHARED_TRADES = Path("/app/shared/trades_history.json")
TRADES_FILE = Path("/app/trades_history.json")
POLY_FUNDER = "0x1a1405f39232734ef1dbcf9ef06b9da72885f575"


def _read_json(paths):
    for p in paths:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return None


async def get_poly_data():
    try:
        async with aiohttp.ClientSession() as s:
            url = f"https://data-api.polymarket.com/positions?user={POLY_FUNDER}&sizeThreshold=0.1"
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                positions = await r.json()
        active = []
        for p in positions:
            cur = float(p.get("curPrice") or 0)
            avg = float(p.get("avgPrice") or 0)
            sz = float(p.get("size") or 0)
            initial = float(p.get("initialValue") or 0)
            current = float(p.get("currentValue") or 0)
            cash_pnl = float(p.get("cashPnl") or 0)
            redeemable = p.get("redeemable", False)
            # Show all positions (not just active ones)
            active.append({
                "title": p.get("title", "")[:50],
                "avg": avg, "cur": cur, "size": sz,
                "pnl": cash_pnl,
                "initial": initial, "current": current,
                "outcome": p.get("outcome", ""),
                "redeemable": redeemable,
                "status": "redeemable" if redeemable else ("active" if cur > 0 else "resolved"),
            })
        return active
    except Exception:
        return []


async def api_state(request):
    crypto = _read_json([SHARED_STATE, STATE_FILE, Path("state.json")]) or {}
    poly = await get_poly_data()
    # Calculate real equity: current value of active positions + redeemable
    poly_equity = sum(p["current"] for p in poly if p["status"] == "active")
    active_pos = [p for p in poly if p["status"] == "active"]
    poly_initial = sum(p["initial"] for p in active_pos)
    poly_pnl = sum(p["pnl"] for p in active_pos)
    trades = _read_json([SHARED_TRADES, TRADES_FILE, Path("trades_history.json")]) or []
    return web.json_response({
        "crypto": crypto,
        "poly": {
            "equity": round(poly_equity, 4),
            "invested": round(poly_initial, 4),
            "pnl": round(poly_pnl, 4),
            "positions": active_pos,
            "total_positions": len(active_pos),
        },
        "total_capital": round(crypto.get("capital", 70) + poly_equity, 2),
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
:root{--bg:#0a0a1a;--card:#111128;--border:#1e1e3a;--accent:#8b5cf6;--green:#10b981;--red:#ef4444;--text:#e2e8f0;--muted:#64748b;--yellow:#f59e0b}
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
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px}
.metric{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:20px;transition:all .2s}
.metric:hover{border-color:var(--accent);transform:translateY(-1px)}
.metric .label{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-weight:500}
.metric .value{font-size:1.6rem;font-weight:700;margin-top:6px}
.metric .change{font-size:.8rem;margin-top:4px;font-weight:500}
.pos{color:var(--green)}.neg{color:var(--red)}.warn{color:var(--yellow)}
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
.badge{font-size:.65rem;padding:2px 6px;border-radius:4px;font-weight:600}
.badge-active{background:rgba(16,185,129,.2);color:var(--green)}
.badge-resolved{background:rgba(100,116,139,.2);color:var(--muted)}
.badge-redeemable{background:rgba(245,158,11,.2);color:var(--yellow)}
</style>
</head>
<body>
<div class="header">
  <h1>⚡ <span>Ranuk Trading</span> <span class="live-badge">LIVE</span></h1>
  <div class="refresh-info"><div class="dot"></div><span id="timer">Actualizando...</span></div>
</div>
<div class="container">
  <div class="metrics" id="metrics"></div>
  <div class="row">
    <div class="panel"><h3>📈 PnL en tiempo real</h3><canvas id="chart"></canvas></div>
    <div class="panel"><h3>⚡ Últimos trades</h3><div id="trades"></div></div>
  </div>
  <div class="row">
    <div class="panel"><h3 id="polyTitle">🎯 Polymarket Posiciones</h3><table><thead><tr><th>Mercado</th><th>Outcome</th><th>Invertido</th><th>PnL</th><th>Status</th></tr></thead><tbody id="positions"></tbody></table></div>
    <div class="panel"><h3>₿ Crypto Stats</h3><div id="cryptoStats"></div></div>
  </div>
</div>
<script>
let history=[];let chart;let polyCount=0;
async function load(){
  try{
    const r=await fetch('/api/state');const d=await r.json();
    polyCount=d.poly.total_positions||0;
    renderMetrics(d);renderPositions(d.poly.positions);renderTrades(d.trades_history);renderCrypto(d.crypto);updateChart(d);
    document.getElementById('timer').textContent='Actualizado '+new Date().toLocaleTimeString();
  }catch(e){document.getElementById('timer').textContent='Error de conexión';}
}
function renderMetrics(d){
  const c=d.crypto||{};const wr=c.momentum_wins?Math.round(c.momentum_wins/(c.momentum_wins+(c.momentum_losses||0))*100):0;
  const balance=c.balance||c.capital||70;
  const momTrades=(c.momentum_wins||0)+(c.momentum_losses||0);
  document.getElementById('metrics').innerHTML=`
    <div class="metric"><div class="label">Balance Total</div><div class="value">$${(balance+(d.poly.equity||0)).toFixed(2)}</div><div class="change ${(c.pnl_today||0)>=0?'pos':'neg'}">Hoy: $${(c.pnl_today||0).toFixed(4)}</div></div>
    <div class="metric"><div class="label">Crypto Balance</div><div class="value">$${balance.toFixed(2)}</div><div class="change ${(c.momentum_pnl||0)>=0?'pos':'neg'}">Mom PnL: $${(c.momentum_pnl||0).toFixed(2)}</div></div>
    <div class="metric"><div class="label">Polymarket</div><div class="value">$${(d.poly.equity||0).toFixed(2)}</div><div class="change ${(d.poly.pnl||0)>=0?'pos':'neg'}">PnL: $${(d.poly.pnl||0).toFixed(2)} (${d.poly.total_positions} pos)</div></div>
    <div class="metric"><div class="label">Momentum WR</div><div class="value">${wr}%</div><div class="change">W${c.momentum_wins||0}/L${c.momentum_losses||0} (${momTrades})</div></div>
    <div class="metric"><div class="label">Open Positions</div><div class="value">${c.momentum_open||0}</div><div class="change">Max: 8</div></div>
    <div class="metric"><div class="label">Grid</div><div class="value ${(c.grid_pnl||0)>=0?'pos':'neg'}">$${(c.grid_pnl||0).toFixed(4)}</div><div class="change">${c.grid_trades||0} trades</div></div>
    <div class="metric"><div class="label">Fees</div><div class="value neg">$${(c.total_fees||0).toFixed(4)}</div><div class="change">0.10% taker</div></div>
  `;
}
function renderPositions(pos){
  const tb=document.getElementById('positions');
  const title=document.getElementById('polyTitle');
  if(!pos||!pos.length){tb.innerHTML='<tr><td colspan="5" class="empty">Sin posiciones</td></tr>';title.textContent='🎯 Polymarket Posiciones (0)';return;}
  title.textContent='🎯 Polymarket Posiciones ('+pos.length+')';
  tb.innerHTML=pos.map(p=>{
    const cls=p.pnl>=0?'pos':'neg';
    const badge=p.status==='active'?'badge-active':p.status==='redeemable'?'badge-redeemable':'badge-resolved';
    return`<tr><td>${p.title}</td><td>${p.outcome}</td><td>$${p.initial.toFixed(2)}</td><td class="${cls}">$${p.pnl.toFixed(2)}</td><td><span class="badge ${badge}">${p.status}</span></td></tr>`;
  }).join('');
}
function renderTrades(trades){
  const div=document.getElementById('trades');
  if(!trades||!trades.length){div.innerHTML='<div class="empty">Sin trades aún</div>';return;}
  div.innerHTML=trades.slice(-10).reverse().map(t=>{
    const icon=t.won?'🟢':'🔴';const cls=t.won?'pos':'neg';
    return`<div class="trade"><div><div class="sym">${icon} ${t.symbol}</div><div class="meta">${t.reason} · ${t.exit_time?new Date(t.exit_time*1000).toLocaleTimeString():'-'}</div></div><div class="pnl ${cls}">${(t.pnl_pct*100).toFixed(1)}%</div></div>`;
  }).join('');
}
function renderCrypto(c){
  if(!c||!c.capital){document.getElementById('cryptoStats').innerHTML='<div class="empty">Esperando datos...</div>';return;}
  const wr=c.momentum_wins?Math.round(c.momentum_wins/(c.momentum_wins+c.momentum_losses)*100):0;
  const balance=c.balance||c.capital||70;
  document.getElementById('cryptoStats').innerHTML=`
    <div class="trade"><div class="sym">💰 Balance</div><div class="pnl">$${balance.toFixed(2)}</div></div>
    <div class="trade"><div class="sym">📊 PnL Hoy</div><div class="pnl ${(c.pnl_today||0)>=0?'pos':'neg'}">$${(c.pnl_today||0).toFixed(4)}</div></div>
    <div class="trade"><div class="sym">🚀 Momentum</div><div class="pnl ${(c.momentum_pnl||0)>=0?'pos':'neg'}">$${(c.momentum_pnl||0).toFixed(4)}</div></div>
    <div class="trade"><div class="sym">📈 Win Rate</div><div class="pnl ${wr>=40?'pos':'neg'}">${wr}% (W${c.momentum_wins}/L${c.momentum_losses})</div></div>
    <div class="trade"><div class="sym">🎯 Open</div><div class="pnl">${c.momentum_open||0} posiciones</div></div>
    <div class="trade"><div class="sym">📊 Grid</div><div class="pnl ${(c.grid_pnl||0)>=0?'pos':'neg'}">$${(c.grid_pnl||0).toFixed(4)} (${c.grid_trades} trades)</div></div>
  `;
}
function updateChart(d){
  const balance=(d.crypto?.balance||d.crypto?.capital||70)+(d.poly?.equity||0);
  history.push({t:Date.now(),v:balance,c:d.crypto?.balance||d.crypto?.capital||70,p:d.poly?.equity||0});
  if(history.length>300)history.shift();
  if(!chart){
    chart=new Chart(document.getElementById('chart'),{type:'line',data:{labels:[],datasets:[
      {label:'Balance Total',data:[],borderColor:'#8b5cf6',backgroundColor:'rgba(139,92,246,.1)',fill:true,tension:.4,borderWidth:2},
      {label:'Crypto',data:[],borderColor:'#10b981',borderWidth:1.5,tension:.4,pointRadius:0},
      {label:'Poly',data:[],borderColor:'#f59e0b',borderWidth:1.5,tension:.4,pointRadius:0},
    ]},options:{responsive:true,animation:false,interaction:{intersect:false},plugins:{legend:{labels:{color:'#64748b',font:{size:11}}}},scales:{x:{display:false},y:{grid:{color:'#1e1e3a'},ticks:{color:'#64748b',callback:v=>'$'+v.toFixed(1)}}}}});
  }
  chart.data.labels=history.map((_,i)=>i);
  chart.data.datasets[0].data=history.map(h=>h.v);
  chart.data.datasets[1].data=history.map(h=>h.c);
  chart.data.datasets[2].data=history.map(h=>h.p);
  chart.update('none');
}
load();setInterval(load,5000);
</script>
</body>
</html>"""

app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/api/state", api_state)

if __name__ == "__main__":
    print("Dashboard v3 running on http://0.0.0.0:9090")
    web.run_app(app, host="0.0.0.0", port=9090, print=None)
