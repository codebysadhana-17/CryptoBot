"""Controlled real-money verification for the live arbitrage execution path.

This module never simulates success. VERIFIED is recorded only after the
existing real BUY + SELL execution function returns a completed LIVE trade.
It is disabled and unarmed by default and requires an explicit confirmation
payload at the API layer.
"""
from datetime import datetime, timezone

import config
from database import get_connection
from exchange import execute_live_real_trade


def _ensure_table():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS live_verification_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                buy_exchange TEXT,
                sell_exchange TEXT,
                symbol TEXT,
                trade_amount REAL,
                buy_order_id TEXT,
                sell_order_id TEXT,
                realized_pnl REAL,
                result_message TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_live_verification_status():
    _ensure_table()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM live_verification_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last = dict(row) if row else None
    finally:
        conn.close()
    return {
        "enabled": bool(getattr(config, "LIVE_VERIFICATION_ENABLED", False)),
        "armed": bool(getattr(config, "LIVE_VERIFICATION_ARMED", False)),
        "max_usdt": float(getattr(config, "LIVE_VERIFICATION_MAX_USDT", 5.0)),
        "verified": bool(last and last.get("status") == "VERIFIED"),
        "last_run": last,
    }


def _record(result, buy_exchange, sell_exchange, amount):
    trade = result.get("trade") or {}
    status = "VERIFIED" if result.get("success") and trade.get("exchange_confirmed") else "FAILED"
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO live_verification_runs
            (status, buy_exchange, sell_exchange, symbol, trade_amount,
             buy_order_id, sell_order_id, realized_pnl, result_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            status, buy_exchange, sell_exchange, config.SYMBOL, float(amount),
            str(result.get("buy_order_id") or trade.get("buy_order_id") or ""),
            str(result.get("sell_order_id") or trade.get("sell_order_id") or ""),
            float(trade.get("profit", 0.0) or 0.0),
            str(result.get("message", "")),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
    finally:
        conn.close()
    return status


def run_live_verification(buy_exchange, sell_exchange, amount, explicit_confirmation=False):
    """Run one explicitly confirmed, capped, real two-leg verification."""
    if not getattr(config, "LIVE_VERIFICATION_ENABLED", False):
        return {"success": False, "status": "BLOCKED", "message": "Live-money verification is disabled."}
    if not getattr(config, "LIVE_VERIFICATION_ARMED", False):
        return {"success": False, "status": "BLOCKED", "message": "Live-money verification is not armed."}
    if not explicit_confirmation:
        return {"success": False, "status": "BLOCKED", "message": "Explicit live-money confirmation is required."}
    if getattr(config, "EMERGENCY_STOP", True):
        return {"success": False, "status": "BLOCKED", "message": "Emergency stop is active."}
    if str(getattr(config, "TRADING_MODE", "LIVE")).upper() != "LIVE":
        return {"success": False, "status": "BLOCKED", "message": "Trading mode is not LIVE."}
    if buy_exchange == sell_exchange:
        return {"success": False, "status": "BLOCKED", "message": "Buy and sell exchanges must be different."}

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return {"success": False, "status": "BLOCKED", "message": "Invalid verification amount."}

    cap = float(getattr(config, "LIVE_VERIFICATION_MAX_USDT", 5.0))
    if amount <= 0 or amount > cap:
        return {"success": False, "status": "BLOCKED", "message": f"Verification amount must be > 0 and <= {cap:.2f} USDT."}

    result = execute_live_real_trade(
        buy_exchange_name=buy_exchange,
        sell_exchange_name=sell_exchange,
        trade_amount=amount,
    )
    status = _record(result, buy_exchange, sell_exchange, amount)
    result["verification_status"] = status
    result["verification_is_real"] = True
    return result
