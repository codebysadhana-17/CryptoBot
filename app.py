
import os
import sys
import threading
import time

from flask import Flask, jsonify, render_template, request

import config
from arbitrage import (
    analyze_market,
    daily_loss_limit_reached,
    emergency_stop_active,
    execute_real_trade,
)
from database import (
    create_database,
    get_all_trades,
    get_latest_trade,
    get_total_profit,
    get_total_trades,
    load_all_bot_settings,
    save_bot_setting,
)

app = Flask(__name__)

create_database()
print(f"Database path: {config.DATABASE_NAME}", flush=True)

try:
    _saved = load_all_bot_settings()
    if "auto_trade" in _saved:
        config.AUTO_TRADE_ENABLED = bool(_saved["auto_trade"])
    if "min_profit" in _saved:
        config.MIN_PROFIT = float(_saved["min_profit"])
    if "trade_amount" in _saved:
        config.DEFAULT_TRADE_AMOUNT = float(_saved["trade_amount"])
except Exception as _e:
    print(f"⚠️ Error restoring saved settings: {_e}", flush=True)




# =====================================================
# BACKGROUND AUTO TRADER
# =====================================================

last_background_trade_result = None
last_execution_status = "MARKET SCANNING"


def start_background_auto_trader():

    def auto_trader_loop():
        global last_background_trade_result, last_execution_status

        print(
            "Background Auto-Trader Thread Started...",
            flush=True
        )

        while True:

            try:

                auto_enabled = getattr(
                    config,
                    "AUTO_TRADE_ENABLED",
                    False
                )

                live_armed = getattr(
                    config,
                    "LIVE_TRADING_ARMED",
                    False
                )

                trading_mode = getattr(
                    config,
                    "TRADING_MODE",
                    "LIVE"
                )

                if emergency_stop_active():
                    last_execution_status = "EMERGENCY STOP ACTIVE"
                    time.sleep(getattr(config, "REFRESH_INTERVAL", 1))
                    continue

                if daily_loss_limit_reached():
                    last_execution_status = "DAILY LOSS LIMIT REACHED"
                    time.sleep(getattr(config, "REFRESH_INTERVAL", 1))
                    continue

                # -------------------------------------------------
                # Safety: only run when explicitly enabled AND armed
                # -------------------------------------------------

                if (
                    auto_enabled
                    and live_armed
                    and trading_mode == "LIVE"
                ):

                    last_execution_status = "MARKET SCANNING"

                    market = analyze_market()

                    if market:

                        last_execution_status = "TRADE OPPORTUNITY"
                        last_execution_status = "TRADE EXECUTING"

                        result = execute_real_trade(
                            market,
                            is_manual=False
                        )

                        if result:

                            last_execution_status = (
                                "TRADE FILLED" if result.get("success")
                                else (
                                    "TRADE SKIPPED"
                                    if result.get("status") == "TRADE SKIPPED"
                                    else "TRADE FAILED"
                                )
                            )

                            last_background_trade_result = result

                            if result.get("success"):

                                trade = result.get(
                                    "trade",
                                    {}
                                )

                                print(
                                    "Background REAL trade executed: "
                                    f"{trade.get('buy_exchange')} -> "
                                    f"{trade.get('sell_exchange')}",
                                    flush=True,
                                )

                            else:

                                message = result.get(
                                    "message",
                                    "Trade not executed."
                                )

                                print(
                                    f"Background trade skipped: {message}",
                                    flush=True,
                                )

            except Exception as error:

                print(
                    f"Background Auto-Trader error: {error}",
                    flush=True
                )

                last_execution_status = "TRADE FAILED"

            time.sleep(
                getattr(
                    config,
                    "REFRESH_INTERVAL",
                    1
                )
            )

    threading.Thread(
        target=auto_trader_loop,
        daemon=True
    ).start()


start_background_auto_trader()


@app.route("/api/emergency-stop", methods=["GET", "POST"])
def emergency_stop_api():
    if request.method == "POST":
        config.EMERGENCY_STOP = True

    return jsonify({
        "success": True,
        "emergency_stop": emergency_stop_active(),
        "message": "Emergency stop is active; new orders are blocked."
        if emergency_stop_active()
        else "Emergency stop is inactive.",
    })


# =====================================================
# FRONTEND ROUTES
# =====================================================

@app.route("/")
@app.route("/prices")
@app.route("/arbitrage")
@app.route("/trades")
def dashboard():

    return render_template("index.html")


@app.route("/settings")
def settings_page():

    return render_template("index.html")


# =====================================================
# REAL EXCHANGE WALLET BALANCES
# =====================================================

def get_real_wallet_balances():

    """
    Reads actual Binance + Bybit wallet balances.

    This function NEVER executes a trade.
    API keys are never returned to the browser.
    """

    try:

        from exchange import get_actual_wallet_balances

        return get_actual_wallet_balances() or {}

    except Exception as error:

        print(
            f"Live wallet balance error: {error}",
            flush=True
        )

        return {}


@app.route("/api/live-balances", methods=["GET"])
def get_live_balances_api():

    balances = get_real_wallet_balances()

    if not balances:

        return jsonify({
            "success": False,
            "message": "Unable to fetch live exchange balances.",
            "balances": {},
        }), 503

    return jsonify({
        "success": True,
        "balances": balances,
    })


@app.route("/api/live-balance-summary", methods=["GET"])
def get_live_balance_summary():

    balances = get_real_wallet_balances()

    if not balances:

        return jsonify({
            "success": False,
            "message": "No live balances available.",
            "total_usdt": 0.0,
            "balances": {},
        }), 503

    total_usdt = 0.0

    for exchange_data in balances.values():

        if not isinstance(exchange_data, dict):
            continue

        try:

            total_usdt += float(
                exchange_data.get(
                    "total_usdt",
                    0
                ) or 0
            )

        except (TypeError, ValueError):

            pass

    return jsonify({
        "success": True,
        "total_usdt": round(
            total_usdt,
            2
        ),
        "balances": balances,
    })


# =====================================================
# REAL TRADE API
# =====================================================

@app.route("/api/trade", methods=["POST"])
def manual_trade_api():
    global last_execution_status, last_background_trade_result

    try:
        request_data = request.get_json() or {}

        custom_amount = request_data.get(
            "trade_amount"
        )

        # -------------------------------------------------
        # Validate custom amount
        # -------------------------------------------------

        if custom_amount is not None:

            try:

                custom_amount = float(
                    custom_amount
                )

                if custom_amount <= 0:

                    raise ValueError

            except (TypeError, ValueError):

                return jsonify({
                    "success": False,
                    "message": "Invalid trade amount.",
                }), 400

        # -------------------------------------------------
        # Get live market
        # -------------------------------------------------

        market = analyze_market()

        if not market:

            return jsonify({
                "success": False,
                "message": (
                    "Unable to fetch live exchange prices."
                ),
            }), 503

        # -------------------------------------------------
        # Apply custom trade amount
        # -------------------------------------------------

        if custom_amount is not None:

            max_amount = getattr(
                config,
                "MAX_TRADE_AMOUNT_USDT",
                custom_amount
            )

            min_amount = getattr(
                config,
                "MIN_TRADE_USDT",
                0.0
            )

            if custom_amount < min_amount:

                return jsonify({
                    "success": False,
                    "message": (
                        f"Trade amount must be at least "
                        f"{min_amount:.2f} USDT."
                    ),
                }), 400

            if custom_amount > max_amount:

                return jsonify({
                    "success": False,
                    "message": (
                        f"Trade amount cannot exceed "
                        f"{max_amount:.2f} USDT."
                    ),
                }), 400

            market["trade_amount"] = custom_amount

            buy_price = float(
                market.get("buy_price", 0)
            )

            if buy_price > 0:

                market["eth_amount"] = (
                    custom_amount / buy_price
                )

        # -------------------------------------------------
        # REAL TRADE EXECUTION
        # -------------------------------------------------

        result = execute_real_trade(
            market,
            custom_amount=custom_amount,
            is_manual=True,
        )

        last_background_trade_result = result
        last_execution_status = (
            "TRADE FILLED" if result.get("success")
            else (
                "TRADE SKIPPED"
                if result.get("status") == "TRADE SKIPPED"
                else "TRADE FAILED"
            )
        )

        if result.get("success"):

            return jsonify({
                "success": True,
                "message": (
                    "Real trade executed successfully."
                ),
                "trade": result.get(
                    "trade",
                    {}
                ),
                "summary": result.get(
                    "summary",
                    {}
                ),
            })

        return jsonify({
            "success": False,
            "message": result.get(
                "message",
                "Real trade was not executed."
            ),
            "details": result,
        }), 400
    except Exception as error:
        print(f"Trade API Error: {error}", flush=True)
        return jsonify({
            "success": False,
            "message": f"Trade Execution Error: {str(error)}"
        }), 400


# =====================================================
# SETTINGS API
# =====================================================

def current_settings():

    return {

        "auto_trade": getattr(
            config,
            "AUTO_TRADE_ENABLED",
            False
        ),

        "live_trading_armed": getattr(
            config,
            "LIVE_TRADING_ARMED",
            False
        ),

        "min_profit": getattr(
            config,
            "MIN_PROFIT",
            0.1
        ),

        "min_profit_percent": getattr(
            config,
            "MIN_PROFIT_PERCENT",
            0.20
        ),

        "trade_amount": getattr(
            config,
            "DEFAULT_TRADE_AMOUNT",
            5.0
        ),

        "max_trade_amount": getattr(
            config,
            "MAX_TRADE_AMOUNT_USDT",
            5.0
        ),

        "min_trade_amount": getattr(
            config,
            "MIN_TRADE_USDT",
            5.0
        ),

        "slippage_enabled": getattr(
            config,
            "SLIPPAGE_ENABLED",
            True
        ),

        "slippage_pct": getattr(
            config,
            "SLIPPAGE_PCT",
            0.05
        ),

        "cooldown": getattr(
            config,
            "AUTO_TRADE_COOLDOWN",
            30
        ),

        "symbol": getattr(
            config,
            "SYMBOL",
            "ETH/USDT"
        ),

        "trading_mode": getattr(
            config,
            "TRADING_MODE",
            "LIVE"
        ),

        "supported_exchanges": getattr(
            config,
            "SUPPORTED_EXCHANGES",
            ["Binance", "Bybit", "KuCoin"]
        ),
    }


@app.route("/api/settings", methods=["GET"])
def get_settings():

    return jsonify({
        "success": True,
        "settings": current_settings(),
    })


@app.route("/api/settings", methods=["POST"])
def update_settings():

    request_data = request.get_json()

    if not request_data:

        return jsonify({
            "success": False,
            "message": "No settings received.",
        }), 400

    # -------------------------------------------------
    # AUTO TRADING
    # -------------------------------------------------

    if "auto_trade" in request_data:
        val = bool(request_data["auto_trade"])
        config.AUTO_TRADE_ENABLED = val
        save_bot_setting("auto_trade", val)

    # MIN PROFIT
    min_prof_val = request_data.get("minimum_profit") if "minimum_profit" in request_data else request_data.get("min_profit")
    if min_prof_val is not None:
        try:
            value = float(min_prof_val)
            if value >= 0:
                config.MIN_PROFIT = value
        except (TypeError, ValueError):
            pass

    if "min_profit_percent" in request_data:
        try:
            value = float(request_data["min_profit_percent"])
            if value >= 0:
                config.MIN_PROFIT_PERCENT = value
        except (TypeError, ValueError):
            pass

    # TRADE AMOUNT
    trade_amt_val = request_data.get("trade_amount") if "trade_amount" in request_data else request_data.get("default_trade_amount")
    if trade_amt_val is not None:
        try:
            value = float(trade_amt_val)
            if value > 0:
                config.DEFAULT_TRADE_AMOUNT = value
        except (TypeError, ValueError):
            pass

    # SLIPPAGE
    if "slippage_enabled" in request_data:
        config.SLIPPAGE_ENABLED = bool(request_data["slippage_enabled"])

    if "slippage_pct" in request_data:
        try:
            value = float(request_data["slippage_pct"])
            if value >= 0:
                config.SLIPPAGE_PCT = value
        except (TypeError, ValueError):
            pass

    # COOLDOWN
    cooldown_val = request_data.get("auto_trade_cooldown") if "auto_trade_cooldown" in request_data else request_data.get("cooldown")
    if cooldown_val is not None:
        try:
            value = int(cooldown_val)
            if value >= 0:
                config.AUTO_TRADE_COOLDOWN = value
        except (TypeError, ValueError):
            pass

    # SYMBOL
    if "symbol" in request_data and request_data["symbol"]:
        config.SYMBOL = str(request_data["symbol"]).strip()

    # TRADING MODE
    if "trading_mode" in request_data and request_data["trading_mode"]:
        mode_val = str(request_data["trading_mode"]).upper().strip()
        if mode_val != "LIVE":
            return jsonify({
                "success": False,
                "message": "Only LIVE trading mode is supported; no paper or simulated mode is available.",
            }), 400
        config.TRADING_MODE = "LIVE"

    # -------------------------------------------------
    # IMPORTANT:
    # LIVE ARM IS NOT CHANGED FROM DASHBOARD
    #
    # This prevents accidental activation of real
    # trading from a normal settings request.
    # -------------------------------------------------

    return jsonify({
        "success": True,
        "message": "Settings updated successfully.",
        "settings": current_settings(),
    })


# =====================================================
# API KEY MANAGEMENT
# =====================================================

@app.route("/api/keys", methods=["GET"])
@app.route("/api/get-keys", methods=["GET"])
def get_keys_api():

    from database import get_all_api_keys

    return jsonify({
        "success": True,
        "keys": get_all_api_keys(),
    })


@app.route("/api/keys", methods=["POST"])
@app.route("/api/save-keys", methods=["POST"])
def save_key_api():

    from database import canonical_exchange_name, get_all_api_keys, save_api_key

    request_data = request.get_json() or {}

    exchange = canonical_exchange_name(request_data.get("exchange", ""))

    api_key = request_data.get(
        "api_key"
    )

    api_secret = request_data.get(
        "api_secret"
    )

    api_passphrase = request_data.get(
        "api_passphrase",
        ""
    )

    if not exchange or not api_key or not api_secret or (
        str(exchange).lower() == "kucoin" and not api_passphrase
    ):

        return jsonify({
            "success": False,
            "message": (
                "Exchange, API Key, and API Secret are required; "
                "KuCoin also requires an API Passphrase."
            ),
        }), 400

    supported = getattr(
        config,
        "SUPPORTED_EXCHANGES",
        ["Binance", "Bybit", "KuCoin"]
    )

    supported_by_name = {
        canonical_exchange_name(name): name
        for name in supported
    }

    if exchange not in supported_by_name:

        return jsonify({
            "success": False,
            "message": (
                f"Unsupported exchange: {exchange}. "
                f"Use only: {', '.join(supported)}"
            ),
        }), 400

    canonical_exchange = supported_by_name[exchange]
    save_api_key(
        canonical_exchange,
        api_key,
        api_secret,
        api_passphrase
    )

    try:
        from exchange import _authenticated_exchanges, _balance_cache
        _authenticated_exchanges.clear()
        _balance_cache["data"] = None
    except Exception:
        pass

    saved_key = get_all_api_keys().get(canonical_exchange)

    return jsonify({
        "success": True,
        "message": (
            f"API key for {canonical_exchange} saved successfully!"
        ),
        "key": saved_key,
    })


@app.route("/api/keys/delete", methods=["POST"])
def delete_key_api():

    from database import delete_api_key

    request_data = request.get_json() or {}

    exchange = request_data.get(
        "exchange"
    )

    if not exchange:

        return jsonify({
            "success": False,
            "message": "Exchange name required.",
        }), 400

    delete_api_key(exchange)

    try:
        from exchange import _authenticated_exchanges, _balance_cache
        _authenticated_exchanges.clear()
        _balance_cache["data"] = None
    except Exception:
        pass

    return jsonify({
        "success": True,
        "message": (
            f"API key for {exchange} removed."
        ),
    })


@app.route("/api/keys/test", methods=["GET", "POST"])
@app.route("/api/test-keys", methods=["GET", "POST"])
@app.route("/api/test-key/<exchange>", methods=["GET", "POST"])
def test_key_api(exchange=None):

    from database import canonical_exchange_name, save_api_key
    from exchange import test_exchange_connection

    request_data = request.get_json() or {}

    if not exchange:
        exchange = request_data.get(
            "exchange"
        )

    api_key = request_data.get(
        "api_key"
    )

    api_secret = request_data.get(
        "api_secret"
    )

    api_passphrase = request_data.get(
        "api_passphrase",
        ""
    )

    if not exchange:

        return jsonify({
            "success": False,
            "message": "Exchange name required.",
        }), 400

    exchange = canonical_exchange_name(exchange)

    supported = getattr(
        config,
        "SUPPORTED_EXCHANGES",
        ["Binance", "Bybit", "KuCoin"]
    )

    supported_by_name = {
        canonical_exchange_name(name): name
        for name in supported
    }

    if exchange not in supported_by_name:

        return jsonify({
            "success": False,
            "message": (
                f"Unsupported exchange: {exchange}."
            ),
        }), 400

    if api_key and api_secret and (
        str(exchange).lower() != "kucoin" or api_passphrase
    ):

        save_api_key(
            supported_by_name[exchange],
            api_key,
            api_secret,
            api_passphrase
        )

        try:
            from exchange import _authenticated_exchanges, _balance_cache
            _authenticated_exchanges.clear()
            _balance_cache["data"] = None
        except Exception:
            pass

    return jsonify(
        test_exchange_connection(exchange)
    )



# =====================================================
# MARKET API
# =====================================================

@app.route("/api/market")
def market_data():
    try:
        data = analyze_market()

        if data is None:

            return jsonify({
                "success": False,
                "message": (
                    "Unable to fetch enough exchange prices."
                ),
            }), 503

        # One timestamp identifies the complete exchange-price snapshot.
        data["timestamp"] = time.time() * 1000

        # -------------------------------------------------
        # LIVE WALLET BALANCES
        # -------------------------------------------------

        live_balances = get_real_wallet_balances()

        binance = (
            live_balances.get(
                "Binance",
                {}
            ) or {}
        )

        bybit = (
            live_balances.get(
                "Bybit",
                {}
            ) or {}
        )

        kucoin = (
            live_balances.get(
                "KuCoin",
                {}
            ) or {}
        )

        # -------------------------------------------------
        # REAL PORTFOLIO
        # -------------------------------------------------

        real_portfolio = {

            "binance_usdt": float(
                binance.get(
                    "total_usdt",
                    0
                ) or 0
            ),

            "binance_eth": float(
                binance.get(
                    "eth",
                    0
                ) or 0
            ),

            "binance_eth_wallet_source": binance.get(
                "wallet_source",
                "Spot"
            ),

            "bybit_usdt": float(
                bybit.get(
                    "total_usdt",
                    0
                ) or 0
            ),

            "bybit_eth": float(
                bybit.get(
                    "eth",
                    0
                ) or 0
            ),

            "kucoin_usdt": float(
                kucoin.get("total_usdt", 0) or 0
            ),

            "kucoin_eth": float(
                kucoin.get("eth", 0) or 0
            ),

            "kucoin_eth_wallet_source": kucoin.get(
                "wallet_source",
                "Spot"
            ),
        }

        # -------------------------------------------------
        # TOTAL USDT
        # -------------------------------------------------

        total_usdt = (
            real_portfolio[
                "binance_usdt"
            ]
            +
            real_portfolio[
                "bybit_usdt"
            ]
            + real_portfolio["kucoin_usdt"]
        )

        # -------------------------------------------------
        # TOTAL ETH
        # -------------------------------------------------

        total_eth = (
            real_portfolio[
            "binance_eth"
            ]
            +
            real_portfolio[
                "bybit_eth"
            ]
            + real_portfolio["kucoin_eth"]
        )

        # -------------------------------------------------
        # ETH PRICE
        # -------------------------------------------------

        prices = data.get(
            "prices",
            {}
        ) or {}

        valid_eth_prices = []

        for price in prices.values():

            try:

                price = float(price)

                if price > 0:

                    valid_eth_prices.append(
                        price
                    )

            except (TypeError, ValueError):

                pass

        if valid_eth_prices:

            eth_usdt_price = (
                sum(valid_eth_prices)
                /
                len(valid_eth_prices)
            )

        else:

            eth_usdt_price = 0.0

        # -------------------------------------------------
        # TOTAL REAL EQUITY
        # -------------------------------------------------

        total_equity_usdt = (
            total_usdt
            +
            (
                total_eth
                *
                eth_usdt_price
            )
        )

        # -------------------------------------------------
        # LATEST TRADE
        # -------------------------------------------------

        latest_trade = get_latest_trade()

        # -------------------------------------------------
        # RESPONSE
        # -------------------------------------------------

        response = jsonify({

            "success": True,

            "data": data,

            "summary": {

                "balance": round(
                    total_equity_usdt,
                    2
                ),

                "profit": get_total_profit(),

                "trades": get_total_trades(),

                "portfolio": real_portfolio,

                "total_usdt": round(
                    total_usdt,
                    2
                ),

                "total_eth": round(
                    total_eth,
                    8
                ),

                "eth_usdt_price": round(
                    eth_usdt_price,
                    2
                ),

                "wallet_status": {

                    "Binance": {

                        "connected": bool(
                            binance.get(
                                "connected",
                                False
                            )
                        ),

                        "error": binance.get(
                            "error"
                        ),
                    },

                    "Bybit": {

                        "connected": bool(
                            bybit.get(
                                "connected",
                                False
                            )
                        ),

                        "error": bybit.get(
                            "error"
                        ),
                    },

                    "KuCoin": {

                        "connected": bool(
                            kucoin.get("connected", False)
                        ),

                        "error": kucoin.get("error"),
                    },
                },
            },

            "settings": {

                "auto_trade": getattr(
                    config,
                    "AUTO_TRADE_ENABLED",
                    False
                ),

                "live_trading_armed": getattr(
                    config,
                    "LIVE_TRADING_ARMED",
                    False
                ),

                "min_profit": getattr(
                    config,
                    "MIN_PROFIT",
                    0.01
                ),

                "min_profit_percent": getattr(
                    config,
                    "MIN_PROFIT_PERCENT",
                    0.20
                ),

                "trading_mode": getattr(
                    config,
                    "TRADING_MODE",
                    "LIVE"
                ),

                "supported_exchanges": getattr(
                    config,
                    "SUPPORTED_EXCHANGES",
                    ["Binance", "Bybit", "KuCoin"]
                ),
            },

            "latest_trade": latest_trade,

            "execution_status": globals().get(
                "last_execution_status",
                "MARKET SCANNING",
            ),

            "last_execution_result": globals().get(
                "last_background_trade_result"
            ),

            "auto_trade": (
                globals().get("last_background_trade_result")
                if getattr(
                    config,
                    "AUTO_TRADE_ENABLED",
                    False
                )
                else None
            ),
        })
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
    except Exception as e:
        print(f"Error in /api/market endpoint: {e}", flush=True)
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500


# =====================================================
# TRADE HISTORY API
# =====================================================

@app.route("/api/trades")
def trades_api():

    return jsonify({
        "success": True,
        "trades": get_all_trades(),
    })


@app.route("/api/trades/clear", methods=["POST"])
@app.route("/api/clear-trades", methods=["POST"])
def clear_trades_api():

    from database import delete_all_trades

    delete_all_trades()

    return jsonify({
        "success": True,
        "message": (
            "Trade history cleared successfully."
        ),
    })


# =====================================================
# API ERROR HANDLERS (RETURN JSON NOT HTML FOR /api/)
# =====================================================

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": f"API endpoint not found: {request.path}"}), 404
    return render_template("index.html")

@app.errorhandler(500)
def handle_500(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500
    return render_template("index.html")


# =====================================================
# HEALTH CHECK
# =====================================================

@app.route("/api/health")
def health_check():

    return jsonify({

        "success": True,

        "status": "running",

        "mode": getattr(
            config,
            "TRADING_MODE",
            "LIVE"
        ),

        "live_trading_armed": getattr(
            config,
            "LIVE_TRADING_ARMED",
            False
        ),

        "auto_trade_enabled": getattr(
            config,
            "AUTO_TRADE_ENABLED",
            False
        ),

        "exchanges": getattr(
            config,
            "SUPPORTED_EXCHANGES",
            ["Binance", "Bybit", "KuCoin"]
        ),
    })


# =====================================================
# START SERVER
# =====================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
