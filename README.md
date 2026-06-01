# Ranuk Profit Bot 🤖💰

Multi-strategy crypto bot. Grid trading + momentum sniper. $20 initial capital.

## Strategies
- **Grid** (60% capital): BTC/ETH range trading, $0.02-0.08/day stable
- **Momentum** (10% capital): catches pumps like COS +29%, TP +10% / SL -3%

## Setup
```bash
cd /Users/emilioranucoli/Desktop/Oficina_Ranuk/Ranuk-Profit-Bot
source .venv/bin/activate
cp .env.example .env   # add Binance API keys for live
python main.py         # paper mode by default
```

## Go Live
1. Get Binance API key (spot trading enabled, no withdrawal)
2. Edit `.env`: `MODE=live`, add keys, set `TOTAL_CAPITAL_USDT=20`
3. `python main.py`

## Risk
- Daily loss cap: 3% ($0.60 on $20)
- Max per trade: 5% ($1)
- Kill switch auto-activates on cap breach


## Licencia

MIT — © 2026 Ranuk IT Solutions | [ranuk.dev](https://ranuk.dev)
