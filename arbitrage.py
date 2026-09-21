
# ============================================================
# REAL ARBITRAGE ENGINE
# Binance + Bybit
#
# NO PAPER TRADING
# NO SIMULATION
# NO FAKE PROFIT
# ============================================================

import time

import config

from database import (
    create_database,
    get_today_live_profit,
    save_trade,
)

from exchange import (
    get_live_quotes,
    execute_live_real_trade,
    _consume_asks_for_quote,
    _consume_bids_for_base,
)


# ============================================================
# STATE
# ============================================================

last_trade_time = 0
last_trade_key = None


def emergency_stop_active():
    return bool(getattr(config, "EMERGENCY_STOP", True))


def daily_loss_limit_reached():
    daily_loss = get_today_live_profit()
    limit = float(getattr(config, "MAX_DAILY_LOSS_USDT", 0.0))
    return limit >= 0 and daily_loss <= -limit


def _skip(reason, **details):
    """Return a visible, structured skip result without touching an exchange."""
    print(f"[ARBITRAGE CHECK] Decision: SKIP", flush=True)
    print(f"SKIP: {reason}", flush=True)
    result = {
        "success": False,
        "status": "TRADE SKIPPED",
        "skip_reason": reason,
        "message": f"SKIP: {reason}",
    }
    result.update(details)
    return result


# ============================================================
# ANALYZE MARKET
# ============================================================

def analyze_market():
    """Calculate the best executable ETH/USDT route from real order-book depth.

    The displayed spread is always: sell VWAP - buy VWAP for the configured
    trade notional. Last-traded prices are never used for arbitrage decisions.
    """
    try:
        quotes = get_live_quotes(force_refresh=True)
    except Exception as exc:
        print(f"[ARBITRAGE] Failed to fetch live quotes: {exc}", flush=True)
        return None

    if len(quotes) < 2:
        return None

    # Reject stale market data before ranking a route. A stale BBO can look
    # profitable while the executable book has already moved.
    max_age_ms = float(getattr(config, "MAX_QUOTE_AGE_MS", 2500))
    fresh_quotes = {}
    now_ms = time.time() * 1000.0
    for name, quote in quotes.items():
        received_at = quote.get("received_at")
        age_ms = quote.get("age_ms")
        if age_ms is None and received_at:
            age_ms = max(0.0, now_ms - float(received_at) * 1000.0)
        if age_ms is not None and age_ms > max_age_ms:
            print(f"[ARBITRAGE] SKIP stale quote: {name} age={age_ms:.0f}ms", flush=True)
            continue
        quote["age_ms"] = round(float(age_ms), 2) if age_ms is not None else None
        fresh_quotes[name] = quote
    quotes = fresh_quotes
    if len(quotes) < 2:
        return None

    trade_amount = min(float(config.DEFAULT_TRADE_AMOUNT), float(config.MAX_TRADE_AMOUNT_USDT))
    trade_amount = max(trade_amount, float(config.MIN_TRADE_USDT))
    fee_rate = float(config.ESTIMATED_FEE_PERCENT) / 100.0
    slip_rate = float(config.SLIPPAGE_PCT) / 100.0 if config.SLIPPAGE_ENABLED else 0.0
    opportunities = []

    for buy_exchange, buy_quote in quotes.items():
        for sell_exchange, sell_quote in quotes.items():
            if buy_exchange == sell_exchange:
                continue
            buy_depth = buy_quote.get("asks") or [[buy_quote["ask"], trade_amount / buy_quote["ask"]]]
            sell_depth = sell_quote.get("bids") or [[sell_quote["bid"], 10**9]]

            buy_fill = _consume_asks_for_quote(buy_depth, trade_amount)
            if not buy_fill:
                continue
            eth_amount, buy_cost, buy_vwap = buy_fill
            sell_fill = _consume_bids_for_base(sell_depth, eth_amount)
            if not sell_fill:
                continue
            sold_eth, sell_value, sell_vwap = sell_fill

            # Depth already models price impact. The configured slippage is an
            # additional latency/safety haircut, not the displayed spread.
            conservative_buy_cost = buy_cost * (1.0 + slip_rate)
            conservative_sell_value = sell_value * (1.0 - slip_rate)
            buy_fee = conservative_buy_cost * fee_rate
            sell_fee = conservative_sell_value * fee_rate
            net_profit = conservative_sell_value - conservative_buy_cost - buy_fee - sell_fee
            profit_pct = (net_profit / conservative_buy_cost * 100.0) if conservative_buy_cost else 0.0
            gross_difference = sell_vwap - buy_vwap
            gross_spread_pct = (gross_difference / buy_vwap * 100.0) if buy_vwap else 0.0
            # The analysis result must use the same safety-buffer rule as
            # the final live execution gate. This prevents the dashboard
            # from advertising a route that the executor will immediately
            # reject.
            safety_buffer_pct = float(getattr(config, "PROFIT_SAFETY_BUFFER_PERCENT", 0.0)) / 100.0
            safety_buffer_usdt = float(getattr(config, "PROFIT_SAFETY_BUFFER_USDT", 0.0))
            required_profit = max(
                float(config.MIN_PROFIT) + safety_buffer_usdt,
                conservative_buy_cost * (float(config.MIN_PROFIT_PERCENT) / 100.0 + safety_buffer_pct),
            )
            profitable = (
                net_profit > 0
                and net_profit >= required_profit
            )
            opportunities.append({
                "buy_exchange": buy_exchange,
                "sell_exchange": sell_exchange,
                "buy_price": round(buy_vwap, 8),
                "sell_price": round(sell_vwap, 8),
                "buy_ask": round(float(buy_quote["ask"]), 8),
                "sell_bid": round(float(sell_quote["bid"]), 8),
                "difference": round(gross_difference, 8),
                "spread_percent": round(gross_spread_pct, 8),
                "trade_amount": round(trade_amount, 8),
                "eth_amount": round(eth_amount, 12),
                "buy_fee": round(buy_fee, 8),
                "sell_fee": round(sell_fee, 8),
                "slippage": round(slip_rate * 100.0, 8),
                "net_profit": round(net_profit, 8),
                "net_profit_percent": round(profit_pct, 8),
                "profitable": profitable,
            })

    if not opportunities:
        return None

    opportunities.sort(key=lambda item: item["net_profit"], reverse=True)
    best = opportunities[0]
    prices = {name: round(float(q.get("last") or ((q["bid"] + q["ask"]) / 2.0)), 8) for name, q in quotes.items()}

    print("[ARBITRAGE CHECK]", flush=True)
    for name, q in quotes.items():
        print(f"{name}: bid={q['bid']:.8f} ask={q['ask']:.8f}", flush=True)
    print(f"Route: {best['buy_exchange']} ASK/VWAP -> {best['sell_exchange']} BID/VWAP", flush=True)
    print(f"Executable gross spread: {best['difference']:.8f} USDT ({best['spread_percent']:.6f}%)", flush=True)
    print(f"Net profit after fees/slippage: {best['net_profit']:.8f} USDT", flush=True)
    print(f"Decision: {'EXECUTE' if best['profitable'] else 'SKIP'}", flush=True)

    return {
        "prices": prices,
        "quotes": quotes,
        "opportunities": opportunities,
        "buy_exchange": best["buy_exchange"],
        "sell_exchange": best["sell_exchange"],
        "buy_price": best["buy_price"],
        "sell_price": best["sell_price"],
        "buy_ask": best["buy_ask"],
        "sell_bid": best["sell_bid"],
        "difference": best["difference"],
        "spread_percent": best["spread_percent"],
        "trade_amount": best["trade_amount"],
        "eth_amount": best["eth_amount"],
        "buy_fee": best["buy_fee"],
        "sell_fee": best["sell_fee"],
        "fees": round(best["buy_fee"] + best["sell_fee"], 8),
        "net_profit": best["net_profit"],
        "net_profit_percent": best["net_profit_percent"],
        "profitable": best["profitable"],
        "minimum_profit": float(config.MIN_PROFIT),
        "minimum_profit_percent": float(config.MIN_PROFIT_PERCENT),
        "auto_trade_enabled": bool(config.AUTO_TRADE_ENABLED),
        "live_trading_armed": bool(config.LIVE_TRADING_ARMED),
        "emergency_stop": emergency_stop_active(),
        "trading_mode": config.TRADING_MODE,
        "calculation": "order-book-depth-VWAP",
    }


def execute_real_trade(
    market_data,
    custom_amount=None,
    is_manual=False
):

    global last_trade_time
    global last_trade_key

    # ========================================================
    # LIVE ONLY
    # ========================================================

    if config.TRADING_MODE != "LIVE":
        return _skip("TRADING_MODE is not LIVE")

    if emergency_stop_active():
        return _skip("Emergency stop is active")

    if daily_loss_limit_reached():
        return _skip("Daily loss limit reached")

    # ========================================================
    # MARKET DATA CHECK
    # ========================================================

    if not market_data:
        return _skip("No live market data available")

    # ========================================================
    # AUTO / MANUAL CHECK
    # ========================================================

    if not is_manual and not config.AUTO_TRADE_ENABLED:
        return _skip("Auto trade disabled")

    # ========================================================
    # LIVE TRADING ARM CHECK
    # ========================================================

    if not config.LIVE_TRADING_ARMED:
        return _skip("LIVE_TRADING_ARMED is false")

    # ========================================================
    # EXCHANGE VALIDATION
    # ========================================================

    buy_exchange = (
        market_data.get(
            "buy_exchange"
        )
    )

    sell_exchange = (
        market_data.get(
            "sell_exchange"
        )
    )

    if not buy_exchange or not sell_exchange:

        return {

            "success": False,

            "message":
                "Invalid buy/sell exchange.",
        }

    if buy_exchange not in config.SUPPORTED_EXCHANGES:

        return {

            "success": False,

            "message":
                f"Unsupported buy exchange: {buy_exchange}",
        }

    if sell_exchange not in config.SUPPORTED_EXCHANGES:

        return {

            "success": False,

            "message":
                f"Unsupported sell exchange: {sell_exchange}",
        }

    if buy_exchange == sell_exchange:

        return {

            "success": False,

            "message":
                "Buy and sell exchanges cannot be the same.",
        }

    # ========================================================
    # PRICE VALIDATION
    # ========================================================

    buy_price = float(
        market_data.get(
            "buy_price",
            0
        )
    )

    sell_price = float(
        market_data.get(
            "sell_price",
            0
        )
    )

    if buy_price <= 0 or sell_price <= 0:

        return {

            "success": False,

            "message":
                "Invalid market prices.",
        }

    if sell_price <= buy_price:

        return {

            "success": False,

            "message":
                "No positive arbitrage spread.",
        }

    # ========================================================
    # PROFIT & SPREAD COMPUTATION
    # ========================================================

    net_profit = float(
        market_data.get(
            "net_profit",
            0
        )
    )

    net_profit_percent = float(
        market_data.get(
            "net_profit_percent",
            0
        )
    )

    # ========================================================
    # PROFIT-ONLY CHECK — APPLIES TO AUTO AND MANUAL EXECUTION
    # ========================================================

    # Manual mode may choose the amount, but it must never bypass the
    # project's profit-only rule. This prevents a UI/manual request from
    # submitting a known non-profitable arbitrage.
    if net_profit < float(config.MIN_PROFIT):
        return {
            "success": False,
            "status": "TRADE SKIPPED",
            "skip_reason": "NET PROFIT BELOW MINIMUM",
            "message": "Trade rejected: estimated net profit is below minimum.",
            "net_profit": net_profit,
            "minimum_profit": float(config.MIN_PROFIT),
        }

    if net_profit_percent < float(config.MIN_PROFIT_PERCENT):
        return {
            "success": False,
            "status": "TRADE SKIPPED",
            "skip_reason": "NET PROFIT PERCENT BELOW MINIMUM",
            "message": "Trade rejected: estimated net profit percentage is below minimum.",
            "net_profit_percent": net_profit_percent,
            "minimum_profit_percent": float(config.MIN_PROFIT_PERCENT),
        }

    # ========================================================
    # DUPLICATE / COOLDOWN PROTECTION
    # ========================================================

    current_time = time.time()

    trade_key = (
        f"{buy_exchange}:"
        f"{sell_exchange}"
    )

    if (
        trade_key == last_trade_key
        and (
            current_time -
            last_trade_time
        ) < float(
            config.AUTO_TRADE_COOLDOWN
        )
    ):

        remaining = max(
            0,
            int(
                config.AUTO_TRADE_COOLDOWN
                - (
                    current_time -
                    last_trade_time
                )
            )
        )

        return {

            "success": False,

            "message":
                (
                    f"Trade cooldown active. "
                    f"Wait {remaining} seconds."
                ),
        }

    # ========================================================
    # TRADE AMOUNT
    # ========================================================

    if custom_amount is not None:

        trade_amount = float(
            custom_amount
        )

    else:

        trade_amount = float(
            config.DEFAULT_TRADE_AMOUNT
        )

    # Never exceed maximum configured amount.

    trade_amount = min(
        trade_amount,
        float(config.MAX_TRADE_AMOUNT_USDT)
    )

    if trade_amount < float(
        config.MIN_TRADE_USDT
    ):

        return {

            "success": False,

            "message":
                (
                    f"Trade amount {trade_amount:.4f} USDT "
                    f"is below minimum "
                    f"{config.MIN_TRADE_USDT:.4f} USDT."
                ),
        }

    # ========================================================
    # REAL EXECUTION
    # ========================================================

    print()
    print(
        "=========================================="
    )
    print(
        "       REAL TRADE EXECUTION"
    )
    print(
        "=========================================="
    )

    print(
        f"BUY  : {buy_exchange}"
    )

    print(
        f"SELL : {sell_exchange}"
    )

    print(
        f"BUY PRICE  : {buy_price:.2f}"
    )

    print(
        f"SELL PRICE : {sell_price:.2f}"
    )

    print(
        f"AMOUNT     : {trade_amount:.4f} USDT"
    )

    print(
        f"EST. NET   : {net_profit:.8f} USDT"
    )

    print(
        "=========================================="
    )

    try:
        result = execute_live_real_trade(

            buy_exchange_name=
                buy_exchange,

            sell_exchange_name=
                sell_exchange,

            buy_price=
                buy_price,

            sell_price=
                sell_price,

            trade_amount=
                trade_amount,
        )
    except Exception as exec_err:
        return {
            "success": False,
            "message": f"Execution error: {str(exec_err)}"
        }

    # ========================================================
    # COMPLETED TRADE / AUDIT
    # ========================================================

    trade = result.get("trade")
    if trade and trade.get("exchange_confirmed") is True:
        save_trade(trade)
        last_trade_time = current_time
        last_trade_key = trade_key

    if result.get("success"):
        return {
            "success": True,
            "message": "REAL LIVE PROFITABLE TRADE EXECUTED.",
            "trade": trade,
            "buy_exchange": buy_exchange,
            "sell_exchange": sell_exchange,
            "trade_amount": trade_amount,
            "estimated_net_profit": net_profit,
        }

    # Both legs may have completed while the market moved. Preserve the
    # confirmed result for daily risk limits instead of hiding a realized loss.
    if trade:
        return {
            "success": False,
            "status": result.get("status", "LIVE TRADE COMPLETED"),
            "message": result.get("message", "LIVE trade completed without positive realized P&L."),
            "trade": trade,
            "recovery_required": result.get("recovery_required", False),
            "buy_exchange": buy_exchange,
            "sell_exchange": sell_exchange,
        }

    # ========================================================
    # FAILURE
    # ========================================================

    return {

        "success": False,

        "message":
            result.get(
                "message",
                "Real trade failed."
            ),

        "recovery_required":
            result.get(
                "recovery_required",
                False
            ),

        "buy_order_id":
            result.get(
                "buy_order_id"
            ),

        "sell_order_id":
            result.get(
                "sell_order_id"
            ),

        "eth_amount":
            result.get(
                "eth_amount"
            ),

        "buy_exchange":
            buy_exchange,

        "sell_exchange":
            sell_exchange,
    }


# ============================================================
# CLI TEST
# ============================================================

if __name__ == "__main__":

    create_database()

    data = analyze_market()

    if not data:

        print(
            "Unable to obtain enough live prices."
        )

    else:

        print()
        print(
            "=========================================="
        )
        print(
            "       LIVE ARBITRAGE ANALYSIS"
        )
        print(
            "=========================================="
        )

        # ----------------------------------------------------
        # PRICES
        # ----------------------------------------------------

        print(
            f"Binance   : "
            f"{data['prices'].get('Binance', 'N/A')}"
        )

        print(
            f"Bybit     : "
            f"{data['prices'].get('Bybit', 'N/A')}"
        )

        print(
            "------------------------------------------"
        )

        # ----------------------------------------------------
        # BUY / SELL
        # ----------------------------------------------------

        print(
            f"BUY       : "
            f"{data['buy_exchange']}"
        )

        print(
            f"BUY PRICE : "
            f"{data['buy_price']:.2f}"
        )

        print(
            f"SELL      : "
            f"{data['sell_exchange']}"
        )

        print(
            f"SELL PRICE: "
            f"{data['sell_price']:.2f}"
        )

        # ----------------------------------------------------
        # SPREAD
        # ----------------------------------------------------

        print(
            f"SPREAD    : "
            f"{data['spread_percent']:.4f}%"
        )

        print(
            f"DIFFERENCE: "
            f"{data['difference']:.8f} USDT"
        )

        # ----------------------------------------------------
        # TRADE SIZE
        # ----------------------------------------------------

        print(
            f"TRADE SIZE: "
            f"{data['trade_amount']:.4f} USDT"
        )

        print(
            f"ETH AMOUNT: "
            f"{data['eth_amount']:.12f} ETH"
        )

        # ----------------------------------------------------
        # FEES
        # ----------------------------------------------------

        print(
            f"EST. FEES : "
            f"{data['fees']:.8f} USDT"
        )

        # ----------------------------------------------------
        # PROFIT
        # ----------------------------------------------------

        print(
            f"NET PROFIT: "
            f"{data['net_profit']:.8f} USDT"
        )

        print(
            f"NET %     : "
            f"{data['net_profit_percent']:.4f}%"
        )

        # ----------------------------------------------------
        # PROFIT STATUS
        # ----------------------------------------------------

        if data["profitable"]:

            print(
                "STATUS    : ✅ PROFITABLE"
            )

        else:

            print(
                "STATUS    : ❌ NOT PROFITABLE"
            )

        # ----------------------------------------------------
        # SAFETY STATUS
        # ----------------------------------------------------

        print(
            "------------------------------------------"
        )

        print(
            f"AUTO TRADE: "
            f"{config.AUTO_TRADE_ENABLED}"
        )

        print(
            f"LIVE ARM  : "
            f"{config.LIVE_TRADING_ARMED}"
        )

        print(
            f"MODE      : "
            f"{config.TRADING_MODE}"
        )

        print(
            "=========================================="
        )
