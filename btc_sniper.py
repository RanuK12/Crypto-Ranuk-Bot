"""BTC Up/Down Sniper — Polymarket 5min/15min markets.

Strategy: Detect BTC direction via Binance price, place maker order
on the winning side 30-60s before market close.

@marketing101 style but adapted for $3.35 capital.
"""
import asyncio
import time
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

# Config
TRADE_SIZE = float(os.getenv("BTC_SNIPER_SIZE", "1.00"))  # USDC per trade
ENTRY_SECONDS_BEFORE = 60  # Enter 60s before close
MIN_PRICE_MOVE_PCT = 0.02  # Need at least 0.02% BTC move to have conviction
MAKER_PRICE = 0.18  # Place maker order at 18¢ (profit 82¢ if wins, ~455% return)
MAX_MAKER_PRICE = 0.20  # Max 20¢ (ensures ≥5 shares with $1.00)
MARKET_TYPE = "5m"  # "5m" or "15m"
INTERVAL = 300 if MARKET_TYPE == "5m" else 900

# Polymarket
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@ticker"

STATE_FILE = Path("/app/shared/btc_sniper_state.json")


class BTCSniper:
    def __init__(self):
        self.btc_price: float = 0
        self.btc_price_at_start: float = 0
        self.btc_price_1h_ago: float = 0
        self._price_history: list[float] = []  # prices every 5s for trend
        self.current_market_start: int = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        self.trades_today = 0
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
                "trades_today": self.trades_today,
                "last_btc": self.btc_price,
                "updated_at": time.time(),
            }, indent=2))
        except Exception:
            pass

    def _init_poly(self):
        """Initialize Polymarket CLOB client."""
        if self.poly_client:
            return self.poly_client
        try:
            from bot.config import CFG
            from bot.clients.polymarket import get_poly
            poly = get_poly()
            self.poly_client = poly.clob()
            return self.poly_client
        except Exception as e:
            print(f"[ERROR] Failed to init poly client: {e}")
            return None

    async def _get_btc_price(self, session: aiohttp.ClientSession) -> float:
        """Get current BTC price from Binance REST."""
        try:
            async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=aiohttp.ClientTimeout(total=5)) as r:
                data = await r.json()
                return float(data["price"])
        except Exception:
            return self.btc_price

    async def _get_market_tokens(self, session: aiohttp.ClientSession, timestamp: int) -> tuple:
        """Get Up/Down token IDs for a market."""
        slug = f"btc-updown-{MARKET_TYPE}-{timestamp}"
        try:
            async with session.get(f"{GAMMA_HOST}/events?slug={slug}", timeout=aiohttp.ClientTimeout(total=5)) as r:
                events = await r.json()
                if not events:
                    return None, None, None
                m = events[0]["markets"][0]
                raw_tokens = m.get("clobTokenIds", "[]")
                # clobTokenIds comes as a JSON string, not a list
                if isinstance(raw_tokens, str):
                    tokens = json.loads(raw_tokens)
                else:
                    tokens = raw_tokens
                if len(tokens) < 2:
                    return None, None, None
                condition_id = m.get("conditionId", "")
                return tokens[0], tokens[1], condition_id  # up_token, down_token, condition
        except Exception as e:
            print(f"[ERROR] Get market tokens: {e}")
            return None, None, None

    async def _place_maker_order(self, token_id: str, size: float, price: float) -> dict:
        """Place a market buy order (FOK) to fill immediately."""
        client = self._init_poly()
        if not client:
            return {"success": False, "error": "no client"}

        try:
            from py_clob_client_v2.clob_types import MarketOrderArgs, OrderType

            # MarketOrderArgs uses amount in USDC for BUY
            args = MarketOrderArgs(
                token_id=token_id,
                amount=float(round(size, 2)),
                side="BUY",
                price=price,
            )
            resp = client.create_and_post_market_order(args, order_type=OrderType.FOK)
            return {"success": True, "response": resp}
        except Exception as e:
            # Fallback: try as limit GTC order
            try:
                from py_clob_client_v2.clob_types import OrderArgs, OrderType
                shares = round(size / price, 2)
                args = OrderArgs(token_id=token_id, price=price, size=shares, side="BUY")
                resp = client.create_and_post_order(args, order_type=OrderType.GTC)
                return {"success": True, "response": resp, "type": "limit"}
            except Exception as e2:
                print(f"[ERROR] Both order types failed: FOK={e} | GTC={e2}")
                return {"success": False, "error": str(e2)}

    async def _check_orderbook(self, session: aiohttp.ClientSession, token_id: str) -> dict:
        """Check if there's liquidity to fill against."""
        try:
            async with session.get(f"{CLOB_HOST}/book?token_id={token_id}", timeout=aiohttp.ClientTimeout(total=5)) as r:
                return await r.json()
        except Exception:
            return {"bids": [], "asks": []}

    def _get_direction(self) -> str:
        """Only trade when micro (5min) and macro (1h trend) AGREE."""
        if self.btc_price <= 0 or self.btc_price_at_start <= 0:
            return "unknown"
        # Micro: change in this 5min window
        micro_change = (self.btc_price - self.btc_price_at_start) / self.btc_price_at_start
        # Macro: trend over last ~10min (120 samples at 5s = 10min)
        if len(self._price_history) >= 60:
            macro_price = self._price_history[-60]  # 5min ago
            macro_change = (self.btc_price - macro_price) / macro_price
        else:
            macro_change = micro_change

        # Need BOTH micro and macro to agree, and micro must be strong
        if micro_change > 0.0005 and macro_change > 0.0003:
            return "up"
        elif micro_change < -0.0005 and macro_change < -0.0003:
            return "down"
        return "flat"

    async def run(self):
        print(f"🎯 BTC Sniper started | Size: ${TRADE_SIZE} | Market: {MARKET_TYPE} | Entry: {ENTRY_SECONDS_BEFORE}s before close")

        async with aiohttp.ClientSession() as session:
            # Get initial BTC price
            self.btc_price = await self._get_btc_price(session)
            print(f"   BTC: ${self.btc_price:,.2f}")

            while True:
                try:
                    await self._cycle(session)
                except Exception as e:
                    print(f"[ERROR] Cycle failed: {e}")
                await asyncio.sleep(5)

    async def _cycle(self, session: aiohttp.ClientSession):
        now = int(time.time())

        # Calculate current market window
        market_start = now - (now % INTERVAL)
        market_end = market_start + INTERVAL
        time_to_close = market_end - now

        # Update BTC price
        self.btc_price = await self._get_btc_price(session)
        self._price_history.append(self.btc_price)
        if len(self._price_history) > 720:  # Keep 1h of data (720 × 5s)
            self._price_history = self._price_history[-720:]

        # Track price at market start
        if market_start != self.current_market_start:
            self.current_market_start = market_start
            self.btc_price_at_start = self.btc_price
            print(f"\n📊 New market window: {datetime.fromtimestamp(market_start, tz=timezone.utc).strftime('%H:%M')} - {datetime.fromtimestamp(market_end, tz=timezone.utc).strftime('%H:%M')} UTC")
            print(f"   BTC start price: ${self.btc_price:,.2f}")

        # Entry window: 60-120s before close
        if 60 <= time_to_close <= 120 and not hasattr(self, f'_traded_{market_start}'):
            direction = self._get_direction()
            change_pct = (self.btc_price - self.btc_price_at_start) / self.btc_price_at_start * 100

            print(f"   ⏰ Entry window! BTC: ${self.btc_price:,.2f} ({change_pct:+.3f}%) → {direction}")

            if direction == "flat":
                print(f"   ⏭ Skipping: no clear direction")
                return

            # Get market tokens
            up_token, down_token, condition = await self._get_market_tokens(session, market_start)
            if not up_token:
                print(f"   ❌ Market not found for ts={market_start}")
                return

            # Choose token based on direction
            token = up_token if direction == "up" else down_token
            side_label = "UP" if direction == "up" else "DOWN"

            # Check orderbook for best price
            ob = await self._check_orderbook(session, token)
            asks = ob.get("asks", [])

            # Determine entry price — use best ask if available and reasonable
            if asks:
                best_ask = float(asks[0]["price"])
                if best_ask <= MAX_MAKER_PRICE:
                    entry_price = best_ask  # Take the ask
                else:
                    # Ask too expensive — place our own limit order as maker
                    entry_price = MAKER_PRICE
                    print(f"   📝 Ask={best_ask:.3f} too high, placing maker @ {entry_price:.3f}")
            else:
                # No liquidity — place limit order at our price
                entry_price = MAKER_PRICE

            # Place order
            print(f"   🎯 Placing {side_label} order: ${TRADE_SIZE} @ {entry_price:.3f}")
            result = await self._place_maker_order(token, TRADE_SIZE, entry_price)

            if result.get("success"):
                resp = result.get("response", {})
                status = resp.get("status", "unknown") if isinstance(resp, dict) else str(resp)
                print(f"   ✅ Order placed! Status: {status}")
                self.trades_today += 1
                setattr(self, f'_traded_{market_start}', True)

                # Expected profit if wins
                shares = TRADE_SIZE / entry_price
                profit = shares * (1.0 - entry_price)
                print(f"   📈 If wins: +${profit:.3f} ({(1/entry_price - 1)*100:.0f}% return)")
            else:
                print(f"   ❌ Order failed: {result.get('error', 'unknown')}")

            self._save_state()


async def main():
    sniper = BTCSniper()
    await sniper.run()


if __name__ == "__main__":
    asyncio.run(main())
