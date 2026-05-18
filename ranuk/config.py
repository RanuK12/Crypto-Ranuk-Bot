"""Centralized configuration from .env"""
import os
from dotenv import load_dotenv
load_dotenv()

def _f(k, d): 
    try: return float(os.getenv(k, d))
    except: return d
def _i(k, d):
    try: return int(os.getenv(k, d))
    except: return d

MODE = os.getenv("MODE", "paper")
IS_PAPER = MODE == "paper"
TOTAL_CAPITAL = _f("TOTAL_CAPITAL_USDT", 20.0)

BINANCE_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "")

MAX_POSITION_PCT = _f("MAX_POSITION_PCT", 0.05)
DAILY_LOSS_CAP_PCT = _f("DAILY_LOSS_CAP_PCT", 0.03)

GRID_PAIRS = [p.strip() for p in os.getenv("GRID_PAIRS", "BTC/USDT,ETH/USDT").split(",")]
GRID_RANGE_PCT = _f("GRID_RANGE_PCT", 0.08)
GRID_LEVELS = _i("GRID_LEVELS", 10)
GRID_CAPITAL_PCT = _f("GRID_CAPITAL_PCT", 0.60)

SNIPER_CAPITAL_PCT = _f("SNIPER_CAPITAL_PCT", 0.10)
SNIPER_MAX_PER_TOKEN = _f("SNIPER_MAX_PER_TOKEN", 0.02)

SCAN_INTERVAL = _i("SCAN_INTERVAL", 5)
MOMENTUM_MIN_VOLUME = _f("MOMENTUM_MIN_VOLUME_USDT", 50000)
MOMENTUM_MIN_CHANGE = _f("MOMENTUM_MIN_CHANGE_PCT", 3.0)
