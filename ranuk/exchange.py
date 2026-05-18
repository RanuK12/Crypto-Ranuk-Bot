"""Exchange adapter — Binance via ccxt, with fee tracking."""
from __future__ import annotations
import ccxt.async_support as ccxt
from ranuk.config import BINANCE_KEY, BINANCE_SECRET, IS_PAPER

# Binance VIP0 taker fee (market orders)
TAKER_FEE = 0.001  # 0.10%
# With BNB discount it's 0.075%, but we use worst-case

class Exchange:
    def __init__(self):
        opts = {"apiKey": BINANCE_KEY, "secret": BINANCE_SECRET}
        if IS_PAPER:
            opts["sandbox"] = True
        self.spot = ccxt.binance({**opts, "options": {"defaultType": "spot"}})
        self.total_fees_paid: float = 0.0

    async def price(self, symbol: str) -> float:
        t = await self.spot.fetch_ticker(symbol)
        return float(t["last"])

    async def buy(self, symbol: str, amount_usdt: float) -> dict:
        px = await self.price(symbol)
        fee = amount_usdt * TAKER_FEE
        effective = amount_usdt - fee  # what you actually get after fee
        qty = round(effective / px, 6)
        self.total_fees_paid += fee
        if IS_PAPER:
            return {"status": "paper", "symbol": symbol, "qty": qty, "price": px, "fee": fee}
        return await self.spot.create_market_buy_order(symbol, qty)

    async def sell(self, symbol: str, qty: float) -> dict:
        px = await self.price(symbol)
        proceeds = qty * px
        fee = proceeds * TAKER_FEE
        net_proceeds = proceeds - fee
        self.total_fees_paid += fee
        if IS_PAPER:
            return {"status": "paper", "symbol": symbol, "qty": qty, "price": px, "fee": fee, "net": net_proceeds}
        return await self.spot.create_market_sell_order(symbol, qty)

    async def top_gainers(self, limit: int = 20) -> list[dict]:
        tickers = await self.spot.fetch_tickers()
        pairs = [
            {"symbol": k, "change": float(v.get("percentage") or 0),
             "volume": float(v.get("quoteVolume") or 0)}
            for k, v in tickers.items()
            if k.endswith("/USDT") and v.get("percentage") is not None
        ]
        pairs.sort(key=lambda x: -x["change"])
        return pairs[:limit]

    async def close(self):
        await self.spot.close()
