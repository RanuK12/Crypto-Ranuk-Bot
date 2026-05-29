"""Multi-Crypto Sniper v8 — Simple config that worked May 27 night (+$9.62).

Only trades when there's REAL volatility. No bias, no fancy filters.
The edge is: volatility + direction alignment = fills that win.
"""
import asyncio
import time
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

# Config — EXACTLY what worked on May 27 night
TRADE_SIZE = 2.50
MAKER_PRICE = 0.18
MAX_MAKER_PRICE = 0.22
INTERVAL = 300
MIN_VOLATILITY = 0.002  # 0.2% range required (was 0.15% — too loose)

ASSETS = [
    {"symbol": "BTCUSDT", "slug": "btc-updown-5m", "name": "BTC"},
    {"symbol": "ETHUSDT", "slug": "eth-updown-5m", "name": "ETH"},
]

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
STATE_FILE = Path("/app/shared/sniper_state.json")


class MultiSniper:
    def __init__(self):
        self.prices: dict[str, float] = {}
        self.prices_at_start: dict[str, float] = {}
        self.price_history: dict[str, list[float]] = {a["symbol"]: [] for a in ASSETS}
        self.current_market_start: int = 0
        self.traded_this_window: set[str] = set()
        self.wins = 0
        self.losses = 0
        self.poly_client = None

    def _init_poly(self):
        if self.poly_client:
            return self.poly_client
        try:
            from bot.clients.polymarket import get_poly
            self.poly_client = get_poly().clob()
            return self.poly_client
        except Exception as e:
            print(f"[ERROR] Poly init: {e}")
            return None

    async def _get_prices(self, session):
        try:
            async with session.get("https://api.binance.com/api/v3/ticker/price", timeout=aiohttp.ClientTimeout(total=5)) as r:
                data = await r.json()
                pm = {t["symbol"]: float(t["price"]) for t in data}
                for a in ASSETS:
                    if a["symbol"] in pm:
                        self.prices[a["symbol"]] = pm[a["symbol"]]
                        self.price_history[a["symbol"]].append(pm[a["symbol"]])
                        if len(self.price_history[a["symbol"]]) > 720:
                            self.price_history[a["symbol"]] = self.price_history[a["symbol"]][-720:]
        except Exception:
            pass

    async def _get_tokens(self, session, slug_prefix, timestamp):
        slug = f"{slug_prefix}-{timestamp}"
        try:
            async with session.get(f"{GAMMA_HOST}/events?slug={slug}", timeout=aiohttp.ClientTimeout(total=5)) as r:
                events = await r.json()
                if not events:
                    return None, None
                m = events[0]["markets"][0]
                raw = m.get("clobTokenIds", "[]")
                tokens = json.loads(raw) if isinstance(raw, str) else raw
                return (tokens[0], tokens[1]) if len(tokens) >= 2 else (None, None)
        except Exception:
            return None, None

    async def _place_order(self, token_id, size, price):
        client = self._init_poly()
        if not client:
            return {"success": False}
        try:
            from py_clob_client_v2.clob_types import MarketOrderArgs, OrderType
            args = MarketOrderArgs(token_id=token_id, amount=round(size, 2), side="BUY", price=price)
            resp = client.create_and_post_market_order(args, order_type=OrderType.FOK)
            return {"success": True, "status": "matched"}
        except Exception:
            try:
                from py_clob_client_v2.clob_types import OrderArgs, OrderType
                shares = round(size / price, 2)
                args = OrderArgs(token_id=token_id, price=price, size=shares, side="BUY")
                resp = client.create_and_post_order(args, order_type=OrderType.GTC)
                return {"success": True, "status": "live"}
            except Exception as e:
                return {"success": False, "error": str(e)}

    def _get_direction(self, symbol):
        price = self.prices.get(symbol, 0)
        start = self.prices_at_start.get(symbol, 0)
        if not price or not start:
            return "flat"
        history = self.price_history.get(symbol, [])

        # Volatility gate — MUST have real movement
        if len(history) >= 60:
            recent = history[-60:]
            vol = (max(recent) - min(recent)) / min(recent)
            if vol < MIN_VOLATILITY:
                return "flat"

        # Simple direction: price vs start of window
        change = (price - start) / start
        if change > 0.0005:
            return "up"
        elif change < -0.0005:
            return "down"
        return "flat"

    async def run(self):
        print(f"🎯 Sniper v8 | BTC+ETH | ${TRADE_SIZE} @ ${MAKER_PRICE} | vol>{MIN_VOLATILITY*100:.1f}%")
        async with aiohttp.ClientSession() as session:
            await self._get_prices(session)
            prices_str = " ".join(f"{a['name']}=${self.prices.get(a['symbol'],0):,.0f}" for a in ASSETS)
            print(f"   {prices_str}")
            while True:
                try:
                    await self._cycle(session)
                except Exception as e:
                    print(f"[ERROR] {e}")
                await asyncio.sleep(5)

    async def _cycle(self, session):
        now = int(time.time())
        market_start = now - (now % INTERVAL)
        market_end = market_start + INTERVAL
        time_to_close = market_end - now

        await self._get_prices(session)

        if market_start != self.current_market_start:
            self.current_market_start = market_start
            self.traded_this_window = set()
            self.prices_at_start = dict(self.prices)
            t = datetime.fromtimestamp(market_start, tz=timezone.utc).strftime('%H:%M')
            prices_str = " ".join(f"{a['name']}=${self.prices.get(a['symbol'],0):,.0f}" for a in ASSETS)
            print(f"\n📊 [{t}] {prices_str}")

        # Entry: 60-90s before close
        if not (60 <= time_to_close <= 90):
            return

        for asset in ASSETS:
            if asset["name"] in self.traded_this_window:
                continue

            direction = self._get_direction(asset["symbol"])
            if direction == "flat":
                continue

            up_token, down_token = await self._get_tokens(session, asset["slug"], market_start)
            if not up_token:
                continue

            token = up_token if direction == "up" else down_token
            side = "UP" if direction == "up" else "DN"
            change = (self.prices[asset["symbol"]] - self.prices_at_start[asset["symbol"]]) / self.prices_at_start[asset["symbol"]] * 100

            print(f"   🎯 {asset['name']} {side} ({change:+.2f}%)")
            result = await self._place_order(token, TRADE_SIZE, MAKER_PRICE)
            if result.get("success"):
                self.traded_this_window.add(asset["name"])
                print(f"   ✅ {result['status']}")
            else:
                print(f"   ❌ {result.get('error','')[:40]}")


if __name__ == "__main__":
    asyncio.run(MultiSniper().run())
