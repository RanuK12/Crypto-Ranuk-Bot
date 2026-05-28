"""Multi-Crypto Up/Down Sniper — BTC, ETH, SOL, XRP on Polymarket 5min markets.

Operates on 4 assets simultaneously = 4x more opportunities.
Only enters when volatility is high (learned from May 26 vs May 27).
"""
import asyncio
import time
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

# Config
TRADE_SIZE = float(os.getenv("SNIPER_SIZE", "1.00"))
MAKER_PRICE = 0.18
MAX_MAKER_PRICE = 0.22
INTERVAL = 300  # 5min markets
MIN_VOLATILITY = 0.0015  # 0.15% range in 5min required

# Assets: ETH (25% WR) + BTC with stricter threshold and later entry
ASSETS = [
    {"symbol": "BTCUSDT", "slug": "btc-updown-5m", "name": "BTC", "min_move": 0.001, "entry_window": (20, 50), "bias": "down"},  # 3/4 top wallets bearish
    {"symbol": "ETHUSDT", "slug": "eth-updown-5m", "name": "ETH", "min_move": 0.0004, "entry_window": (60, 120), "bias": "up"},  # 2/4 top wallets bullish
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
        self.active_positions: list[dict] = []  # {token_id, entry_price, shares, highest_price, name}
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        self.poly_client = None
        self._load_state()

    def _load_state(self):
        if STATE_FILE.exists():
            try:
                d = json.loads(STATE_FILE.read_text())
                self.wins = d.get("wins", 0)
                self.losses = d.get("losses", 0)
                self.total_pnl = d.get("total_pnl", 0.0)
            except Exception:
                pass

    def _save_state(self):
        try:
            STATE_FILE.write_text(json.dumps({
                "wins": self.wins, "losses": self.losses,
                "total_pnl": self.total_pnl,
                "last_prices": self.prices,
                "updated_at": time.time(),
            }, indent=2))
        except Exception:
            pass

    def _init_poly(self):
        if self.poly_client:
            return self.poly_client
        try:
            from bot.config import CFG
            from bot.clients.polymarket import get_poly
            self.poly_client = get_poly().clob()
            return self.poly_client
        except Exception as e:
            print(f"[ERROR] Poly init: {e}")
            return None

    async def _get_prices(self, session: aiohttp.ClientSession):
        """Get all crypto prices from Binance in one call."""
        try:
            async with session.get("https://api.binance.com/api/v3/ticker/price", timeout=aiohttp.ClientTimeout(total=5)) as r:
                data = await r.json()
                price_map = {t["symbol"]: float(t["price"]) for t in data}
                for asset in ASSETS:
                    if asset["symbol"] in price_map:
                        self.prices[asset["symbol"]] = price_map[asset["symbol"]]
                        self.price_history[asset["symbol"]].append(price_map[asset["symbol"]])
                        if len(self.price_history[asset["symbol"]]) > 720:
                            self.price_history[asset["symbol"]] = self.price_history[asset["symbol"]][-720:]
        except Exception:
            pass

    async def _get_market_tokens(self, session: aiohttp.ClientSession, slug_prefix: str, timestamp: int):
        slug = f"{slug_prefix}-{timestamp}"
        try:
            async with session.get(f"{GAMMA_HOST}/events?slug={slug}", timeout=aiohttp.ClientTimeout(total=5)) as r:
                events = await r.json()
                if not events:
                    return None, None
                m = events[0]["markets"][0]
                raw = m.get("clobTokenIds", "[]")
                tokens = json.loads(raw) if isinstance(raw, str) else raw
                return tokens[0], tokens[1] if len(tokens) >= 2 else (None, None)
        except Exception:
            return None, None

    async def _place_order(self, token_id: str, size: float, price: float) -> dict:
        client = self._init_poly()
        if not client:
            return {"success": False}
        try:
            from py_clob_client_v2.clob_types import MarketOrderArgs, OrderType
            args = MarketOrderArgs(token_id=token_id, amount=float(round(size, 2)), side="BUY", price=price)
            resp = client.create_and_post_market_order(args, order_type=OrderType.FOK)
            return {"success": True, "response": resp, "status": "matched"}
        except Exception:
            try:
                from py_clob_client_v2.clob_types import OrderArgs, OrderType
                shares = round(size / price, 2)
                args = OrderArgs(token_id=token_id, price=price, size=shares, side="BUY")
                resp = client.create_and_post_order(args, order_type=OrderType.GTC)
                status = resp.get("status", "live") if isinstance(resp, dict) else "live"
                return {"success": True, "response": resp, "status": status}
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def _sell_position(self, token_id: str, shares: float) -> dict:
        """Sell position to lock in profit."""
        try:
            from bot.clients.polymarket import get_poly
            poly = get_poly()
            result = poly.sell_position(token_id=token_id, shares=round(shares, 2))
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _check_signal(self, symbol: str, min_move: float = 0.0004) -> str:
        """Check if asset has clear direction with enough volatility."""
        price = self.prices.get(symbol, 0)
        start_price = self.prices_at_start.get(symbol, 0)
        if not price or not start_price:
            return "flat"

        history = self.price_history.get(symbol, [])

        # Volatility gate
        if len(history) >= 60:
            recent = history[-60:]
            vol = (max(recent) - min(recent)) / min(recent)
            if vol < MIN_VOLATILITY:
                return "flat"

        # Direction
        micro = (price - start_price) / start_price
        macro = 0
        if len(history) >= 60:
            macro = (price - history[-60]) / history[-60]

        if micro > min_move and macro > min_move * 0.25:
            return "up"
        elif micro < -min_move and macro < -min_move * 0.25:
            return "down"
        return "flat"

    async def run(self):
        print(f"🎯 Multi-Crypto Sniper | Assets: {[a['name'] for a in ASSETS]} | Size: ${TRADE_SIZE}")

        async with aiohttp.ClientSession() as session:
            await self._get_prices(session)
            prices_str = " ".join(f"{a['name']}=${self.prices.get(a['symbol'],0):,.2f}" for a in ASSETS)
            print(f"   Prices: {prices_str}")

            while True:
                try:
                    await self._cycle(session)
                except Exception as e:
                    print(f"[ERROR] {e}")
                await asyncio.sleep(5)

    async def _cycle(self, session: aiohttp.ClientSession):
        now = int(time.time())
        market_start = now - (now % INTERVAL)
        market_end = market_start + INTERVAL
        time_to_close = market_end - now

        await self._get_prices(session)

        # New window
        if market_start != self.current_market_start:
            self.current_market_start = market_start
            self.traded_this_window = set()
            self.prices_at_start = dict(self.prices)
            t = datetime.fromtimestamp(market_start, tz=timezone.utc).strftime('%H:%M')
            prices_str = " ".join(f"{a['name']}=${self.prices.get(a['symbol'],0):,.1f}" for a in ASSETS)
            print(f"\n📊 [{t}] New window | {prices_str}")

        # Entry check per asset (each has its own timing window)
        for asset in ASSETS:
            if asset["name"] in self.traded_this_window:
                continue

            entry_lo, entry_hi = asset.get("entry_window", (60, 120))
            if not (entry_lo <= time_to_close <= entry_hi):
                continue

            direction = self._check_signal(asset["symbol"], asset.get("min_move", 0.0004))
            if direction == "flat":
                continue

            # Bias filter: only trade in direction of top wallet consensus
            bias = asset.get("bias")
            if bias and direction != bias:
                continue

            # Get tokens
            up_token, down_token = await self._get_market_tokens(session, asset["slug"], market_start)
            if not up_token:
                continue

            token = up_token if direction == "up" else down_token
            side = "UP" if direction == "up" else "DOWN"

            # Check orderbook
            try:
                async with session.get(f"{CLOB_HOST}/book?token_id={token}", timeout=aiohttp.ClientTimeout(total=3)) as r:
                    ob = await r.json()
                asks = ob.get("asks", [])
                if asks and float(asks[0]["price"]) <= MAX_MAKER_PRICE:
                    entry_price = float(asks[0]["price"])
                else:
                    entry_price = MAKER_PRICE
            except Exception:
                entry_price = MAKER_PRICE

            change = (self.prices[asset["symbol"]] - self.prices_at_start[asset["symbol"]]) / self.prices_at_start[asset["symbol"]] * 100
            print(f"   🎯 {asset['name']} {side} ({change:+.3f}%) @ ${entry_price:.3f}")

            result = await self._place_order(token, TRADE_SIZE, entry_price)
            if result.get("success"):
                self.traded_this_window.add(asset["name"])
                shares = TRADE_SIZE / entry_price
                profit = shares * (1 - entry_price)
                print(f"   ✅ {result['status']} | If wins: +${profit:.2f} ({(1/entry_price-1)*100:.0f}%)")
                # Track position for trailing TP
                self.active_positions.append({
                    "token_id": token, "entry_price": entry_price,
                    "shares": shares, "highest_price": entry_price,
                    "name": asset["name"], "side": side,
                })
            else:
                print(f"   ❌ {result.get('error','')[:40]}")

            self._save_state()

        # === TRAILING TP MONITOR ===
        for pos in list(self.active_positions):
            try:
                async with session.get(f"{CLOB_HOST}/book?token_id={pos['token_id']}", timeout=aiohttp.ClientTimeout(total=3)) as r:
                    ob = await r.json()
                bids = ob.get("bids", [])
                if not bids:
                    continue
                best_bid = float(bids[0]["price"])

                # Update highest
                if best_bid > pos["highest_price"]:
                    pos["highest_price"] = best_bid

                gain_from_entry = (best_bid - pos["entry_price"]) / pos["entry_price"]
                drop_from_high = (pos["highest_price"] - best_bid) / pos["highest_price"] if pos["highest_price"] > 0 else 0

                # Trailing TP: if was up 100%+ and dropped 30% from peak → SELL
                if pos["highest_price"] >= pos["entry_price"] * 2.0 and drop_from_high >= 0.30:
                    print(f"   💰 TRAILING TP! {pos['name']} {pos['side']} | peak={pos['highest_price']:.3f} now={best_bid:.3f} (-{drop_from_high*100:.0f}%)")
                    sell_result = await self._sell_position(pos["token_id"], pos["shares"])
                    if sell_result.get("success"):
                        profit = pos["shares"] * (best_bid - pos["entry_price"])
                        self.total_pnl += profit
                        self.wins += 1
                        print(f"   🎉 SOLD! Profit: +${profit:.2f}")
                    self.active_positions.remove(pos)
                    self._save_state()
            except Exception:
                pass

        # Clean expired positions (market resolved)
        if time_to_close > 290:  # New window started, clear old positions
            self.active_positions = []


if __name__ == "__main__":
    asyncio.run(MultiSniper().run())
