import ccxt
import time
from datetime import datetime
import sys
import os
import urllib.request
import json
import concurrent.futures

import config
from database import get_api_key



# ============================================================
# ENSURE WINDOWS STDOUT HANDLES UTF-8
# ============================================================

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ============================================================
# PROXY CONFIGURATION
# ============================================================

proxy_url = (
    os.environ.get("EXCHANGE_PROXY")
    or os.environ.get("HTTPS_PROXY")
    or os.environ.get("HTTP_PROXY")
)

if proxy_url:
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url


# ============================================================
# PUBLIC EXCHANGE CONFIGURATION
# ============================================================
# PUBLIC EXCHANGE CONFIGURATION & IN-MEMORY CACHING
# ============================================================

_price_cache = {"data": None, "timestamp": 0}
_balance_cache = {"data": None, "timestamp": 0}
_last_known_good_balances = {}
_authenticated_exchanges = {}

binance_opts = {
    "enableRateLimit": True,
    "timeout": 15000,
    "options": {
        "recvWindow": 60000,
        "adjustForTimeDifference": True,
        "fetchCurrencies": False
    }
}


bybit_opts = {
    "enableRateLimit": True,
    "timeout": 15000,
    "urls": {
        "api": {
            "public": "https://api.bybit.com",
            "private": "https://api.bybit.com"
        }
    },
    "options": {
        "defaultType": "spot",
        "recvWindow": 60000,
        "adjustForTimeDifference": True,
        "fetchCurrencies": False
    }
}


kucoin_opts = {
    "enableRateLimit": True,
    "timeout": 15000,
    "options": {
        "defaultType": "spot",
        "fetchCurrencies": False,
    },
}





# ============================================================
# APPLY PROXY
# ============================================================

if proxy_url:

    for opts in (
        binance_opts,
        bybit_opts,
        kucoin_opts,
    ):

        if "socks" in proxy_url.lower():
            opts["socksProxy"] = proxy_url
        else:
            opts["httpsProxy"] = proxy_url


# ============================================================
# PUBLIC EXCHANGE INSTANCES
# ============================================================

exchanges = {
    "Binance": ccxt.binance(binance_opts),
    "Bybit": ccxt.bybit(bybit_opts),
    "KuCoin": ccxt.kucoin(kucoin_opts),
}


# ============================================================
# APPLY PROXY TO SESSIONS
# ============================================================

if proxy_url:

    for ex in exchanges.values():

        try:

            ex.session.proxies = {
                "http": proxy_url,
                "https": proxy_url
            }

        except Exception:
            pass


# ============================================================
# GET AUTHENTICATED EXCHANGE
# ============================================================

def get_authenticated_exchange(name):

    key_info = get_api_key(name)

    if (
        not key_info
        or not key_info.get("api_key")
        or not key_info.get("api_secret")
        or (name.lower() == "kucoin" and not key_info.get("api_passphrase"))
    ):

        required = "API key, secret, and passphrase" if name.lower() == "kucoin" else "API key and secret"
        return None, f"No {required} configured for {name}."

    cache_key = (
        name.lower(),
        key_info["api_key"],
        key_info["api_secret"],
        key_info.get("api_passphrase", ""),
    )

    if cache_key in _authenticated_exchanges:
        return _authenticated_exchanges[cache_key], None

    exchange_class = getattr(
        ccxt,
        name.lower(),
        None
    )


    if not exchange_class:

        return None, f"Unsupported exchange: {name}"


    try:

        config_opts = {
            "apiKey": key_info["api_key"],
            "secret": key_info["api_secret"],
            "enableRateLimit": True,
            "timeout": 15000,
            "options": {
                "recvWindow": 60000,
                "adjustForTimeDifference": True,
                "fetchCurrencies": False
            }
        }

        if name.lower() == "kucoin":
            config_opts["password"] = key_info["api_passphrase"]
            config_opts["options"]["defaultType"] = "spot"


        if proxy_url:

            if "socks" in proxy_url.lower():

                config_opts["socksProxy"] = proxy_url

            else:

                config_opts["httpsProxy"] = proxy_url


        # ----------------------------------------------------
        # BYBIT
        # ----------------------------------------------------

        if name.lower() == "bybit":

            config_opts["urls"] = {
                "api": {
                    "public": "https://api.bybit.com",
                    "private": "https://api.bybit.com"
                }
            }

            config_opts["options"]["defaultType"] = "spot"




        # ----------------------------------------------------
        # CREATE INSTANCE
        # ----------------------------------------------------

        ex_instance = exchange_class(config_opts)
        ex_instance.has["fetchCurrencies"] = False
        ex_instance.options["fetchCurrencies"] = False


        # ----------------------------------------------------
        # APPLY PROXY
        # ----------------------------------------------------

        if (
            proxy_url
            and hasattr(ex_instance, "session")
        ):

            try:

                ex_instance.session.proxies = {
                    "http": proxy_url,
                    "https": proxy_url
                }

            except Exception:
                pass

        _authenticated_exchanges[cache_key] = ex_instance
        return ex_instance, None


    except Exception as e:

        return None, (
            f"Failed to initialize {name}: "
            f"{str(e)}"
        )


# ============================================================
# ACTUAL WALLET BALANCES
# ============================================================

def get_actual_wallet_balances(force_refresh=False):

    """
    Fetch REAL wallet balances from configured exchanges with 1s TTL caching.
    Retains last successful connection during transient network blips.
    """
    global _balance_cache, _last_known_good_balances

    now = time.time()
    if not force_refresh and _balance_cache["data"] and (now - _balance_cache["timestamp"]) < 1.0:
        return _balance_cache["data"]

    balances = {}
    exchange_names = [
        "Binance",
        "Bybit",
        "KuCoin",
    ]

    for exchange_name in exchange_names:

        try:

            # ------------------------------------------------
            # GET AUTHENTICATED INSTANCE
            # ------------------------------------------------

            exchange, error = (
                get_authenticated_exchange(
                    exchange_name
                )
            )


            if error or exchange is None:
                if exchange_name in _last_known_good_balances and _last_known_good_balances[exchange_name].get("connected"):
                    balances[exchange_name] = _last_known_good_balances[exchange_name].copy()
                else:
                    balances[exchange_name] = {
                        "connected": False,
                        "usdt": 0.0,
                        "total_usdt": 0.0,
                        "eth": 0.0,
                        "eth_total": 0.0,
                        "error": (
                            error
                            or "Unable to connect."
                        )
                    }

                continue


            # ------------------------------------------------
            # FETCH REAL BALANCE
            # ------------------------------------------------

            balance = safe_fetch_balance(exchange, exchange_name)

            free = balance.get("free", {}) or {}
            used = balance.get("used", {}) or {}
            total = balance.get("total", {}) or {}

            usdt_free = float(free.get("USDT", 0.0) or free.get("USD", 0.0) or 0.0)
            usdt_used = float(used.get("USDT", 0.0) or used.get("USD", 0.0) or 0.0)
            usdt_total = float(total.get("USDT", 0.0) or total.get("USD", 0.0) or (usdt_free + usdt_used) or 0.0)

            eth_free = float(free.get("ETH", 0.0) or 0.0)
            eth_used = float(used.get("ETH", 0.0) or 0.0)
            eth_total = float(total.get("ETH", 0.0) or (eth_free + eth_used) or 0.0)
            wallet_source = balance.get("wallet_source", "Spot")

            entry = {
                "connected": True,
                "usdt": round(usdt_free, 8),
                "total_usdt": round(usdt_total, 8),
                "eth": round(eth_free, 8),
                "eth_total": round(eth_total, 8),
                "wallet_source": wallet_source,
                "error": None
            }

            balances[exchange_name] = entry
            _last_known_good_balances[exchange_name] = entry

        except ccxt.AuthenticationError:
            if exchange_name in _last_known_good_balances:
                del _last_known_good_balances[exchange_name]
            balances[exchange_name] = {
                "connected": False,
                "usdt": 0.0,
                "total_usdt": 0.0,
                "eth": 0.0,
                "eth_total": 0.0,
                "error": "Invalid API key or secret."
            }

        except ccxt.PermissionDenied:
            if exchange_name in _last_known_good_balances:
                del _last_known_good_balances[exchange_name]
            balances[exchange_name] = {
                "connected": False,
                "usdt": 0.0,
                "total_usdt": 0.0,
                "eth": 0.0,
                "eth_total": 0.0,
                "error": "API key does not have balance permission."
            }

        except ccxt.NetworkError as e:
            if exchange_name in _last_known_good_balances and _last_known_good_balances[exchange_name].get("connected"):
                balances[exchange_name] = _last_known_good_balances[exchange_name].copy()
            else:
                balances[exchange_name] = {
                    "connected": False,
                    "usdt": 0.0,
                    "total_usdt": 0.0,
                    "eth": 0.0,
                    "eth_total": 0.0,
                    "error": f"Network error: {str(e)}"
                }

        except Exception as e:
            if exchange_name == "KuCoin":
                print(f"[KUCOIN ERROR] Reason: {str(e)[:200]}", flush=True)
            if exchange_name in _last_known_good_balances and _last_known_good_balances[exchange_name].get("connected"):
                balances[exchange_name] = _last_known_good_balances[exchange_name].copy()
            else:
                balances[exchange_name] = {
                    "connected": False,
                    "usdt": 0.0,
                    "total_usdt": 0.0,
                    "eth": 0.0,
                    "eth_total": 0.0,
                    "error": str(e)
                }

    _balance_cache["data"] = balances
    _balance_cache["timestamp"] = now

    return balances




# ============================================================
# SAFE BALANCE FETCH & TEST API CONNECTION
# ============================================================

def safe_fetch_balance(exchange_instance, name):
    """
    Safely fetch spot balances without hitting elevated endpoints
    like sapi/v1/capital/config/getall or v5/asset/coin/query-info.
    """
    name_lower = name.lower() if name else ""
    if hasattr(exchange_instance, "has"):
        exchange_instance.has["fetchCurrencies"] = False
    if hasattr(exchange_instance, "options"):
        exchange_instance.options["fetchCurrencies"] = False

    if name_lower == "binance":
        balance = exchange_instance.fetch_balance(params={"type": "spot"})
        free = balance.get("free", {}) or {}
        total = balance.get("total", {}) or {}
        spot_eth = float(free.get("ETH", 0.0) or 0.0)
        spot_eth_total = float(total.get("ETH", 0.0) or spot_eth)
        earn_eth = 0.0

        try:
            earn_response = exchange_instance.sapi_get_simple_earn_flexible_position({"asset": "ETH"})
            for position in earn_response.get("rows", []) or []:
                if position.get("asset", "").upper() == "ETH":
                    earn_eth += float(position.get("totalAmount", 0.0) or 0.0)
        except Exception:
            pass

        if earn_eth:
            free["ETH"] = spot_eth + earn_eth
            total["ETH"] = spot_eth_total + earn_eth
            balance["wallet_source"] = "Spot + Simple Earn"
        else:
            balance["wallet_source"] = "Spot"

        return balance
    elif name_lower == "bybit":
        for acc_type in ["UNIFIED", "SPOT"]:
            try:
                raw = exchange_instance.private_get_v5_account_wallet_balance({"accountType": acc_type})
                res_list = (raw.get("result", {}) or {}).get("list", [])
                if res_list:
                    coins = res_list[0].get("coin", []) or []
                    if not any(c.get("coin", "").upper() == "ETH" for c in coins):
                        eth_raw = exchange_instance.private_get_v5_account_wallet_balance({
                            "accountType": acc_type,
                            "coin": "ETH",
                        })
                        eth_list = (eth_raw.get("result", {}) or {}).get("list", [])
                        if eth_list:
                            coins.extend(eth_list[0].get("coin", []) or [])

                    free_dict = {}
                    total_dict = {}
                    for c in coins:
                        c_name = c.get("coin", "").upper()
                        wb = float(c.get("walletBalance", 0.0) or c.get("equity", 0.0) or 0.0)
                        available = c.get("availableToWithdraw")
                        ab = wb if available in (None, "") else float(available)
                        free_dict[c_name] = ab
                        total_dict[c_name] = wb
                    return {"free": free_dict, "total": total_dict, "used": {}}
            except Exception:
                continue

        return exchange_instance.fetch_balance()
    else:
        return exchange_instance.fetch_balance()


def test_exchange_connection(name):

    ex_instance, err = (
        get_authenticated_exchange(name)
    )

    if err:
        return {
            "success": False,
            "message": err
        }

    last_err = None
    for attempt in range(2):
        try:
            balance = safe_fetch_balance(ex_instance, name)

            usdt_free = float(
                balance
                .get("free", {})
                .get("USDT", 0.0)
                or balance
                .get("free", {})
                .get("USD", 0.0)
                or 0.0
            )

            eth_free = float(
                balance
                .get("free", {})
                .get("ETH", 0.0)
                or 0.0
            )

            usdt_total = float(
                balance
                .get("total", {})
                .get("USDT", 0.0)
                or balance
                .get("total", {})
                .get("USD", 0.0)
                or usdt_free
            )

            eth_total = float(
                balance
                .get("total", {})
                .get("ETH", 0.0)
                or eth_free
            )

            return {
                "success": True,
                "message": (
                    "KuCoin API connected successfully."
                    if name.lower() == "kucoin"
                    else f"Successfully connected to {name}!"
                ),
                "usdt_balance": round(usdt_free, 2),
                "usdt_total": round(usdt_total, 2),
                "eth_balance": round(eth_free, 8),
                "eth_total": round(eth_total, 8)
            }

        except (ccxt.AuthenticationError, ccxt.PermissionDenied):
            raise
        except (ccxt.NetworkError, Exception) as e:
            last_err = e
            time.sleep(1.0)

    err_msg = str(last_err or "")
    if "-1003" in err_msg or "request weight" in err_msg.lower() or "418" in err_msg:
        return {
            "success": False,
            "message": f"Binance Rate Limit: Shared Render IP temporarily limited (-1003). Please wait 2-3 minutes or switch Render Region to Singapore (Asia)."
        }

    if any(x in err_msg.lower() for x in ["api-key", "invalid", "auth", "signature", "permission", "capital/config", "query-info", "-2008", "-2014", "-2015", "10003"]):
        return {
            "success": False,
            "message": f"Authentication Error: Invalid API Key or Secret for {name}."
        }

    return {
        "success": False,
        "message": f"Network Error: Unable to reach {name} API servers ({err_msg[:80]}). Check connection."
    }


# ============================================================
# DIRECT PRICE FETCH
# ============================================================

def get_direct_price(
    name,
    symbol=None
):
    if symbol is None:
        symbol = config.SYMBOL

    clean_sym = symbol.replace(
        "/",
        ""
    )

    import ssl

    ctx = ssl.create_default_context()

    ctx.check_hostname = False

    ctx.verify_mode = (
        ssl.CERT_NONE
    )


    # ========================================================
    # BINANCE
    # ========================================================

    if name.lower() == "binance":

        urls = [

            (
                "https://data-api.binance.vision/"
                "api/v3/ticker/price?"
                f"symbol={clean_sym}"
            ),

            (
                "https://api.binance.us/"
                "api/v3/ticker/price?"
                f"symbol={clean_sym}"
            ),

            (
                "https://api.binance.com/"
                "api/v3/ticker/price?"
                f"symbol={clean_sym}"
            )
        ]


        for url in urls:

            try:

                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent":
                        "Mozilla/5.0"
                    }
                )


                res = json.loads(
                    urllib.request.urlopen(
                        req,
                        context=ctx,
                        timeout=1.5
                    ).read()
                )


                if (
                    "price" in res
                    and float(
                        res["price"]
                    ) > 0
                ):

                    return float(
                        res["price"]
                    )


            except Exception:

                continue


    # ========================================================
    # BYBIT
    # ========================================================

    elif name.lower() == "bybit":

        for base_url in [
            "https://api.bybit.com"
        ]:

            try:

                url = (
                    f"{base_url}/v5/market/tickers"
                    f"?category=spot"
                    f"&symbol={clean_sym}"
                )


                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent":
                        "Mozilla/5.0"
                    }
                )


                res = json.loads(
                    urllib.request.urlopen(
                        req,
                        context=ctx,
                        timeout=1.5
                    ).read()
                )


                tickers = (
                    res
                    .get("result", {})
                    .get("list", [])
                )


                if (
                    tickers
                    and "lastPrice"
                    in tickers[0]
                ):

                    price = float(
                        tickers[0]
                        ["lastPrice"]
                    )


                    if price > 0:
                        return price

            except Exception:
                continue

    # ========================================================
    # KUCOIN SPOT
    # ========================================================

    elif name.lower() == "kucoin":

        try:
            url = (
                "https://api.kucoin.com/api/v1/market/orderbook/level1"
                f"?symbol={symbol.replace('/', '-')}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "CryptoArbitrageBot/1.0"})
            res = json.loads(urllib.request.urlopen(req, context=ctx, timeout=1.5).read())
            ticker = res.get("data", {}) or {}
            for field in ("last", "price", "bestAsk", "bestBid"):
                value = ticker.get(field)
                if value is not None and float(value) > 0:
                    return float(value)
        except Exception as error:
            print(f"[KUCOIN ERROR] Reason: {str(error)[:200]}", flush=True)

    return None


# ============================================================
# FETCH SINGLE EXCHANGE PRICE
# ============================================================

def fetch_single_exchange_price(
    name_and_exchange
):

    name, exchange = (
        name_and_exchange
    )


    fetched_price = (
        get_direct_price(
            name,
            config.SYMBOL
        )
    )


    if fetched_price is None:

        try:

            ticker = (
                exchange.fetch_ticker(
                    config.SYMBOL
                )
            )


            last_price = ticker.get(
                "last"
            )


            if (
                last_price
                and float(last_price) > 0
            ):

                fetched_price = float(
                    last_price
                )


        except Exception:

            pass


    return name, fetched_price


# ============================================================
# GET LIVE PRICES
# ============================================================

def get_live_prices(force_refresh=False):

    global _price_cache

    now = time.time()
    if not force_refresh and _price_cache["data"] and (now - _price_cache["timestamp"]) < 0.8:
        return _price_cache["data"]

    prices = {}

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(exchanges)
    ) as executor:

        results = list(
            executor.map(
                fetch_single_exchange_price,
                exchanges.items()
            )
        )

    for name, fetched_price in results:

        if (
            fetched_price
            and fetched_price > 0
        ):

            prices[name] = round(
                fetched_price,
                2
            )

    if prices:
        _price_cache["data"] = prices
        _price_cache["timestamp"] = now

    return prices


# ============================================================
# HELPER: GET BASE / QUOTE CURRENCY
# ============================================================

def get_symbol_currencies(symbol):

    base, quote = symbol.split("/")

    return base, quote


# ============================================================
# HELPER: CHECK MARKET LIMITS
# ============================================================

def _order_fee(order):
    fee = order.get("fee") or {}
    if fee.get("cost") is not None:
        return float(fee.get("cost") or 0.0)
    fees = order.get("fees") or []
    return sum(float(item.get("cost") or 0.0) for item in fees if item)


def _resolve_filled_order(exchange, order):
    """Use the exchange's order record so accounting never relies on estimates."""
    order_id = order.get("id")
    resolved = order
    if order_id:
        try:
            resolved = exchange.fetch_order(order_id, config.SYMBOL) or order
        except Exception as error:
            print(f"ORDER STATUS: fetch failed for {order_id}: {error}", flush=True)

    status = str(resolved.get("status") or order.get("status") or "").lower()
    filled = float(resolved.get("filled") or order.get("filled") or 0.0)
    average = float(
        resolved.get("average")
        or order.get("average")
        or resolved.get("price")
        or order.get("price")
        or 0.0
    )
    return {
        "id": order_id,
        "status": status,
        "filled": filled,
        "average": average,
        "cost": float(resolved.get("cost") or order.get("cost") or 0.0),
        "fee": _order_fee(resolved) or _order_fee(order),
        "raw": resolved,
    }


def _filled(result, requested_amount):
    return result["filled"] >= float(requested_amount) * 0.999999 and (
        result["status"] in {"closed", "filled", "done"}
        or not result["status"]
    )

def validate_order_limits(
    exchange,
    symbol,
    amount,
    price
):

    try:

        market = exchange.market(
            symbol
        )


        limits = market.get(
            "limits",
            {}
        )


        min_amount = (
            limits
            .get("amount", {})
            .get("min")
        )


        min_cost = (
            limits
            .get("cost", {})
            .get("min")
        )


        order_cost = (
            amount * price
        )


        if (
            min_amount
            and amount < float(min_amount)
        ):

            return (
                False,
                (
                    f"Order amount "
                    f"{amount} is below "
                    f"exchange minimum "
                    f"{min_amount}"
                )
            )


        if (
            min_cost
            and order_cost < float(min_cost)
        ):

            return (
                False,
                (
                    f"Order value "
                    f"${order_cost:.2f} "
                    f"is below exchange "
                    f"minimum "
                    f"${min_cost:.2f}"
                )
            )


        return True, "OK"


    except Exception as e:

        return (
            False,
            (
                "Unable to validate "
                f"market limits: {str(e)}"
            )
        )


# ============================================================
# EXECUTE LIVE REAL TRADE
# ============================================================

def _emergency_stop_result(stage):
    return {
        "success": False,
        "status": "TRADE SKIPPED",
        "skip_reason": "Emergency stop is active",
        "message": f"Emergency stop activated before {stage}; no new order was submitted.",
    }


def emergency_stop_active():
    return bool(getattr(config, "EMERGENCY_STOP", True))

def execute_live_real_trade(
    buy_exchange_name,
    sell_exchange_name,
    buy_price,
    sell_price,
    trade_amount=1000.0
):

    if emergency_stop_active():
        return _emergency_stop_result("exchange execution")

    # --------------------------------------------------------
    # 1. LOAD BUY EXCHANGE
    # --------------------------------------------------------

    buy_ex, buy_err = (
        get_authenticated_exchange(
            buy_exchange_name
        )
    )


    if buy_err:

        return {
            "success": False,
            "message": buy_err
        }


    # --------------------------------------------------------
    # 2. LOAD SELL EXCHANGE
    # --------------------------------------------------------

    sell_ex, sell_err = (
        get_authenticated_exchange(
            sell_exchange_name
        )
    )


    if sell_err:

        return {
            "success": False,
            "message": sell_err
        }


    # --------------------------------------------------------
    # 3. LOAD MARKETS
    # --------------------------------------------------------

    try:

        if not getattr(buy_ex, "markets", None):
            buy_ex.load_markets(reload=False)
        if not getattr(sell_ex, "markets", None):
            sell_ex.load_markets(reload=False)


        base_currency, quote_currency = (
            get_symbol_currencies(
                config.SYMBOL
            )
        )


    except Exception as e:

        return {
            "success": False,
            "message": (
                "Unable to load market "
                f"information: {str(e)}"
            )
        }


    # --------------------------------------------------------
    # 4. FETCH ACTUAL BALANCES
    # --------------------------------------------------------

    try:

        buy_balance = (
            buy_ex.fetch_balance()
        )


        sell_balance = (
            sell_ex.fetch_balance()
        )


        free_usdt = float(
            buy_balance
            .get("free", {})
            .get(
                quote_currency,
                0.0
            )
            or 0.0
        )


        free_eth = float(
            sell_balance
            .get("free", {})
            .get(
                base_currency,
                0.0
            )
            or 0.0
        )


        min_required = float(
            getattr(
                config,
                "MIN_TRADE_USDT",
                5.0
            )
        )


        # ----------------------------------------------------
        # BUY BALANCE CHECK
        # ----------------------------------------------------

        if free_usdt < float(trade_amount) * 1.01:

            return {
                "success": False,
                "message": (
                    f"Insufficient "
                    f"{quote_currency} "
                    f"on {buy_exchange_name}. "
                    f"Required for requested trade plus fee: "
                    f"{float(trade_amount) * 1.01:.2f}. "
                    f"Available: "
                    f"{free_usdt:.2f}"
                )
            }


        # ----------------------------------------------------
        # DYNAMIC TRADE SIZE
        # ----------------------------------------------------

        if getattr(
            config,
            "DYNAMIC_BALANCE_TRADING",
            True
        ):

            trade_amount = min(
                float(trade_amount),
                free_usdt * 0.98
            )


        trade_amount = float(
            buy_ex.cost_to_precision(config.SYMBOL, trade_amount)
        )


        if trade_amount < min_required:

            return {
                "success": False,
                "message": (
                    f"Final trade amount "
                    f"{trade_amount:.4f} "
                    f"is below minimum "
                    f"{min_required:.2f}"
                )
            }


        print(
            f"BUY BALANCE: "
            f"{free_usdt:.4f} "
            f"{quote_currency}"
        )


        print(
            f"SELL BALANCE: "
            f"{free_eth:.8f} "
            f"{base_currency}"
        )


        print(
            f"TRADE AMOUNT: "
            f"{trade_amount:.4f} "
            f"{quote_currency}"
        )


    except Exception as e:

        return {
            "success": False,
            "message": (
                "Unable to verify "
                f"balances: {str(e)}"
            )
        }


    # --------------------------------------------------------
    # 5. CALCULATE ETH QUANTITY
    # --------------------------------------------------------

    try:

        raw_amount = (
            trade_amount /
            float(buy_price)
        )


        eth_amount = float(
            buy_ex.amount_to_precision(
                config.SYMBOL,
                raw_amount
            )
        )


    except Exception as e:

        return {
            "success": False,
            "message": (
                "Unable to calculate "
                f"order quantity: {str(e)}"
            )
        }


    if eth_amount <= 0:

        return {
            "success": False,
            "message": (
                "Calculated order "
                "quantity is zero."
            )
        }


    # --------------------------------------------------------
    # 6. SELL ETH BALANCE CHECK
    # --------------------------------------------------------

    required_eth = (
        eth_amount * 1.001
    )


    if free_eth < required_eth:

        return {
            "success": False,
            "message": (
                f"SELL BLOCKED. "
                f"Insufficient "
                f"{base_currency} "
                f"on {sell_exchange_name}. "
                f"Required approximately: "
                f"{required_eth:.8f} "
                f"{base_currency}. "
                f"Available: "
                f"{free_eth:.8f} "
                f"{base_currency}."
            )
        }


    # --------------------------------------------------------
    # 7. BUY MINIMUM ORDER
    # --------------------------------------------------------

    buy_valid, buy_message = (
        validate_order_limits(
            buy_ex,
            config.SYMBOL,
            eth_amount,
            buy_price
        )
    )


    if not buy_valid:

        return {
            "success": False,
            "message": (
                f"BUY BLOCKED: "
                f"{buy_message}"
            )
        }


    # Sell precision can differ from buy precision. Validate the exact
    # quantity that will be sent rather than assuming both markets match.
    try:
        sell_eth_amount = float(
            sell_ex.amount_to_precision(config.SYMBOL, eth_amount)
        )
    except Exception as e:
        return {
            "success": False,
            "message": f"SELL BLOCKED: invalid precision: {e}",
        }

    if sell_eth_amount <= 0 or free_eth < sell_eth_amount:
        return {
            "success": False,
            "message": (
                f"SELL BLOCKED: Insufficient {base_currency} on "
                f"{sell_exchange_name}; required {sell_eth_amount:.12f}, "
                f"available {free_eth:.12f}."
            ),
        }

    # --------------------------------------------------------
    # 8. SELL MINIMUM ORDER
    # --------------------------------------------------------

    sell_valid, sell_message = (
        validate_order_limits(
            sell_ex,
            config.SYMBOL,
            sell_eth_amount,
            sell_price
        )
    )


    if not sell_valid:

        return {
            "success": False,
            "message": (
                f"SELL BLOCKED: "
                f"{sell_message}"
            )
        }


    # --------------------------------------------------------
    # 9. PROFIT CHECK
    # --------------------------------------------------------

    fee_pct = float(
        getattr(
            config,
            "MAKER_TAKER_FEE_PCT",
            0.05
        )
    ) / 100


    estimated_buy_fee = (
        trade_amount * fee_pct
    )


    estimated_sell_value = (
        eth_amount *
        float(sell_price)
    )


    estimated_sell_fee = (
        estimated_sell_value *
        fee_pct
    )


    estimated_profit = (
        estimated_sell_value
        - trade_amount
        - estimated_buy_fee
        - estimated_sell_fee
    )


    min_profit = float(
        getattr(
            config,
            "MIN_PROFIT",
            0.1
        )
    )


    if estimated_profit < min_profit:

        return {
            "success": False,
            "message": (
                f"TRADE BLOCKED. "
                f"Estimated net profit "
                f"${estimated_profit:.4f} "
                f"is below minimum "
                f"${min_profit:.4f}"
            )
        }


    print(
        f"Estimated Net Profit: "
        f"${estimated_profit:.4f}"
    )


    # --------------------------------------------------------
    # 10. LIVE BUY
    # --------------------------------------------------------

    try:

        if emergency_stop_active():
            return _emergency_stop_result("buy order")

        print(
            f"Submitting LIVE BUY "
            f"on {buy_exchange_name}: "
                f"{eth_amount:.8f} "
            f"{base_currency}"
        )


        buy_order = (
            buy_ex.create_market_buy_order(
                config.SYMBOL,
                eth_amount
            )
        )
        buy_result = _resolve_filled_order(buy_ex, buy_order)
        buy_order_id = buy_result["id"]
        print(
            f"ORDER RESULT: exchange={buy_exchange_name} side=buy "
            f"symbol={config.SYMBOL} id={buy_order_id} "
            f"amount={eth_amount:.12f} filled={buy_result['filled']:.12f} "
            f"average={buy_result['average']:.8f} status={buy_result['status']} "
            f"fee={buy_result['fee']:.8f}",
            flush=True,
        )
        if not _filled(buy_result, eth_amount):
            return {
                "success": False,
                "message": (
                    f"BUY FAILED: order {buy_order_id} was not fully filled "
                    f"(status: {buy_result['status'] or 'unknown'})."
                ),
                "buy_order_id": buy_order_id,
                "order_result": buy_result,
            }


    except ccxt.InsufficientFunds as e:

        return {
            "success": False,
            "message": (
                f"BUY FAILED: "
                f"Insufficient funds "
                f"on {buy_exchange_name}: "
                f"{str(e)}"
            )
        }


    except Exception as e:

        return {
            "success": False,
            "message": (
                f"BUY FAILED on "
                f"{buy_exchange_name}: "
                f"{str(e)}"
            )
        }


    # --------------------------------------------------------
    # 11. LIVE SELL
    # --------------------------------------------------------

    try:

        if emergency_stop_active():
            return {
                **_emergency_stop_result("sell order"),
                "buy_order_id": buy_order_id,
                "recovery_required": True,
            }

        print(
            f"Submitting LIVE SELL "
            f"on {sell_exchange_name}: "
                f"{eth_amount:.8f} "
            f"{base_currency}"
        )


        sell_order = (
            sell_ex.create_market_sell_order(
                config.SYMBOL,
                sell_eth_amount
            )
        )
        sell_result = _resolve_filled_order(sell_ex, sell_order)
        sell_order_id = sell_result["id"]
        print(
            f"ORDER RESULT: exchange={sell_exchange_name} side=sell "
            f"symbol={config.SYMBOL} id={sell_order_id} "
            f"amount={sell_eth_amount:.12f} filled={sell_result['filled']:.12f} "
            f"average={sell_result['average']:.8f} status={sell_result['status']} "
            f"fee={sell_result['fee']:.8f}",
            flush=True,
        )
        if not _filled(sell_result, sell_eth_amount):
            return {
                "success": False,
                "message": (
                    f"SELL FAILED: order {sell_order_id} was not fully filled "
                    f"(status: {sell_result['status'] or 'unknown'})."
                ),
                "buy_order_id": buy_order_id,
                "sell_order_id": sell_order_id,
                "order_result": sell_result,
                "recovery_required": True,
            }


    except Exception as e:

        return {
            "success": False,
            "message": (
                f"WARNING: BUY ORDER "
                f"SUCCEEDED on "
                f"{buy_exchange_name} "
                f"(ID: {buy_order_id}), "
                f"but SELL FAILED on "
                f"{sell_exchange_name}: "
                f"{str(e)}"
            ),
            "buy_order_id": buy_order_id,
            "eth_amount": eth_amount
        }


    # --------------------------------------------------------
    # 12. ACTUAL ORDER VALUES
    # --------------------------------------------------------

    effective_buy_price = buy_result["average"] or buy_price


    effective_sell_price = sell_result["average"] or sell_price


    actual_buy_cost = buy_result["cost"] or (eth_amount * effective_buy_price)


    actual_sell_value = sell_result["cost"] or (sell_eth_amount * effective_sell_price)


    # --------------------------------------------------------
    # 13. FEES
    # --------------------------------------------------------

    buy_fee = buy_result["fee"]


    sell_fee = sell_result["fee"]


    total_fees = (
        buy_fee +
        sell_fee
    )


    net_profit = (
        actual_sell_value
        - actual_buy_cost
        - total_fees
    )


    # --------------------------------------------------------
    # 14. SUCCESS
    # --------------------------------------------------------

    return {

        "success": True,

        "message": (
            "LIVE TRADE EXECUTED "
            "SUCCESSFULLY. "
            f"BUY: {buy_exchange_name} | "
            f"SELL: {sell_exchange_name}"
        ),

        "trade": {

            "buy": buy_exchange_name,

            "sell": sell_exchange_name,

            "buy_exchange":
                buy_exchange_name,

            "sell_exchange":
                sell_exchange_name,

            "buy_price":
                effective_buy_price,

            "sell_price":
                effective_sell_price,

            "effective_buy_price":
                effective_buy_price,

            "effective_sell_price":
                effective_sell_price,

            "fees":
                round(
                    total_fees,
                    8
                ),

            "profit":
                round(
                    net_profit,
                    8
                ),

            "estimated_profit":
                round(
                    estimated_profit,
                    8
                ),

            "buy_order_id":
                buy_order_id,

            "sell_order_id":
                sell_order_id,

            "symbol":
                config.SYMBOL,

            "buy_side":
                "buy",

            "sell_side":
                "sell",

            "buy_status":
                buy_result["status"],

            "sell_status":
                sell_result["status"],

            "buy_filled":
                buy_result["filled"],

            "sell_filled":
                sell_result["filled"],

            "buy_average_price":
                effective_buy_price,

            "sell_average_price":
                effective_sell_price,

            "buy_fee":
                buy_fee,

            "sell_fee":
                sell_fee,

            "eth_amount":
                buy_result["filled"],

            "trade_amount":
                actual_buy_cost,

            "created_at":
                datetime.now()
                .astimezone()
                .isoformat(),

            "mode":
                "LIVE",

            "exchange_confirmed":
                True
        }
    }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\n=============================="
    )

    print(
        "LIVE EXCHANGE PRICES"
    )

    print(
        "==============================\n"
    )


    prices = get_live_prices()


    if not prices:

        print(
            "No exchange prices available."
        )

    print(
        "\n==============================\n"
    )


    print(
        "===== API CONNECTION TEST ====="
    )


    print("\nBinance:")

    print(
        test_exchange_connection(
            "Binance"
        )
    )


    print("\nBybit:")

    print(
        test_exchange_connection(
            "Bybit"
        )
    )




    print(
        "\n===== ACTUAL WALLET BALANCES ====="
    )


    wallet_balances = (
        get_actual_wallet_balances()
    )


    for exchange, data in (
        wallet_balances.items()
    ):

        print(
            f"{exchange}: "
            f"{data}"
        )