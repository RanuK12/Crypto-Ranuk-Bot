"""Telegram notifications — shared module for both bots.

Sends:
  - Trade alerts (BUY/SELL with PnL)
  - Daily PDF report at 21:00 UTC (18:00 Argentina)
  - Kill switch alerts
"""
from __future__ import annotations
import asyncio
import aiohttp
import json
import time
from datetime import datetime, timezone
from pathlib import Path

TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

def configure(token: str, chat_id: str):
    global TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    TELEGRAM_TOKEN = token
    TELEGRAM_CHAT_ID = chat_id

async def send_message(text: str, parse_mode: str = "HTML"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()
    except Exception:
        pass

async def send_document(file_path: str, caption: str = ""):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    try:
        async with aiohttp.ClientSession() as s:
            data = aiohttp.FormData()
            data.add_field("chat_id", TELEGRAM_CHAT_ID)
            data.add_field("caption", caption)
            data.add_field("document", open(file_path, "rb"), filename=Path(file_path).name)
            async with s.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as r:
                return await r.json()
    except Exception:
        pass

async def alert_trade(bot_name: str, action: str, symbol: str, pnl: float = 0, details: str = ""):
    icon = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "📊"
    msg = (
        f"{icon} <b>{bot_name}</b>\n"
        f"<b>{action}</b> {symbol}\n"
    )
    if pnl != 0:
        msg += f"PnL: <b>${pnl:+.4f}</b>\n"
    if details:
        msg += f"<i>{details}</i>"
    await send_message(msg)

async def alert_kill_switch(bot_name: str, reason: str):
    await send_message(f"🚨 <b>KILL SWITCH — {bot_name}</b>\nReason: {reason}")

async def send_daily_report(report_text: str, pdf_path: str = ""):
    await send_message(f"📋 <b>DAILY REPORT</b>\n\n{report_text}")
    if pdf_path and Path(pdf_path).exists():
        await send_document(pdf_path, "📊 Reporte diario completo")
