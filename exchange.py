try:
    import ccxt
    CCXT_AVAILABLE = True
except ModuleNotFoundError:  # Allows non-network unit tests to run without CCXT installed.
    ccxt = None
    CCXT_AVAILABLE = False

    class _CCXTError(Exception):
        pass

    class _CCXTExceptions:
        AuthenticationError = _CCXTError
        PermissionDenied = _CCXTError
        NetworkError = _CCXTError
        InsufficientFunds = _CCXTError

    ccxt = _CCXTExceptions()
import time
from datetime import datetime
import sys
import os
import urllib.request
import json
import concurrent.futures
import threading
import functools

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
_live_trade_lock = threading.Lock()

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

exchanges = {}
if CCXT_AVAILABLE:
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

    if not CCXT_AVAILABLE:
        return None, "CCXT is not installed. Run: pip install -r requirements.txt"

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
# FETCH SINGLE EXCHANGE QUOTE
# ============================================================

def _kucoin_public_orderbook(symbol):
    """Public KuCoin fallback. This endpoint requires no API key."""
    import ssl
    ctx = ssl.create_default_context()
    if proxy_url:
        # urllib honors HTTP(S)_PROXY from the environment.
        pass
    pair = symbol.replace("/", "-")
    url = (
        "https://api.kucoin.com/api/v1/market/orderbook/level1"
        f"?symbol={pair}"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CryptoBot/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, context=ctx, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data") or {}
    bid = float(data.get("bestBid") or 0)
    ask = float(data.get("bestAsk") or 0)
    last = float(data.get("price") or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        raise ValueError(f"Invalid KuCoin BBO: bid={bid}, ask={ask}")
    return {
        "bid": bid,
        "ask": ask,
        "last": last or ((bid + ask) / 2.0),
        "timestamp": data.get("time"),
        "source": "kucoin-rest-level1",
    }


def fetch_single_exchange_quote(name_and_exchange):
    """Fetch a fresh executable spot bid/ask quote.

    KuCoin has an explicit public REST fallback because public market data
    must not depend on authenticated API credentials.
    """
    name, exchange = name_and_exchange
    try:
        if not getattr(exchange, "markets", None):
            exchange.load_markets(reload=False)
        market = exchange.market(config.SYMBOL)
        if not market.get("spot", True):
            return name, None
        book = exchange.fetch_order_book(config.SYMBOL, limit=int(getattr(config, "ORDERBOOK_LIMIT", 50)))
        asks = book.get("asks") or []
        bids = book.get("bids") or []
        if not asks or not bids:
            raise ValueError("empty order book")
        ask = float(asks[0][0])
        bid = float(bids[0][0])
        if ask <= 0 or bid <= 0 or bid > ask:
            raise ValueError(f"invalid BBO bid={bid} ask={ask}")
        fetched_at = time.time()
        exchange_timestamp = book.get("timestamp")
        age_ms = None
        if exchange_timestamp:
            age_ms = max(0.0, fetched_at * 1000.0 - float(exchange_timestamp))
        return name, {
            "bid": bid,
            "ask": ask,
            "last": float(book.get("last") or ((bid + ask) / 2.0)),
            "timestamp": exchange_timestamp,
            "received_at": fetched_at,
            "age_ms": age_ms,
            "bids": bids,
            "asks": asks,
            "source": "ccxt-orderbook",
        }
    except Exception as exc:
        if name == "KuCoin":
            try:
                quote = _kucoin_public_orderbook(config.SYMBOL)
                print("[KUCOIN] Public REST fallback connected successfully.", flush=True)
                return name, quote
            except Exception as fallback_exc:
                print(f"[KUCOIN PUBLIC ERROR] {str(fallback_exc)[:240]}", flush=True)
        print(f"[{name} QUOTE ERROR] {str(exc)[:200]}", flush=True)
        return name, None


def _consume_asks_for_quote(asks, quote_amount):
    """Buy a fixed quote amount using the actual ask depth."""
    remaining = float(quote_amount)
    base = 0.0
    spent = 0.0
    for level in asks or []:
        if len(level) < 2:
            continue
        price, size = float(level[0]), float(level[1])
        if price <= 0 or size <= 0:
            continue
        level_quote = price * size
        take_quote = min(remaining, level_quote)
        base += take_quote / price
        spent += take_quote
        remaining -= take_quote
        if remaining <= 1e-12:
            break
    if remaining > 1e-9:
        return None
    return base, spent, spent / base if base else 0.0


def _consume_bids_for_base(bids, base_amount):
    """Sell a fixed base amount using the actual bid depth."""
    remaining = float(base_amount)
    base = 0.0
    received = 0.0
    for level in bids or []:
        if len(level) < 2:
            continue
        price, size = float(level[0]), float(level[1])
        if price <= 0 or size <= 0:
            continue
        take_base = min(remaining, size)
        base += take_base
        received += take_base * price
        remaining -= take_base
        if remaining <= 1e-12:
            break
    if remaining > 1e-9:
        return None
    return base, received, received / base if base else 0.0


def get_live_quotes(force_refresh=False):
    """Return fresh executable bid/ask quotes for every configured venue."""
    global _price_cache
    now = time.time()
    cache = _price_cache.get("quotes")
    if not force_refresh and cache and (now - _price_cache.get("quote_timestamp", 0)) < 0.5:
        return cache

    quotes = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(exchanges)) as executor:
        for name, quote in executor.map(fetch_single_exchange_quote, exchanges.items()):
            if quote:
                quotes[name] = quote

    if quotes:
        _price_cache["quotes"] = quotes
        _price_cache["quote_timestamp"] = now
        _price_cache["data"] = {name: round(q["last"], 8) for name, q in quotes.items()}
        _price_cache["timestamp"] = now
    return quotes


# ============================================================
# GET LIVE DISPLAY PRICES
# ============================================================

def get_live_prices(force_refresh=False):
    """Return last-traded/mid display prices while quotes remain executable bid/ask."""
    quotes = get_live_quotes(force_refresh=force_refresh)
    return {
        name: round(float(q.get("last") or ((q["bid"] + q["ask"]) / 2)), 8)
        for name, q in quotes.items()
    }


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
    fee_obj = resolved.get("fee") or order.get("fee") or {}
    fee_currency = fee_obj.get("currency")
    return {
        "id": order_id,
        "status": status,
        "filled": filled,
        "average": average,
        "cost": float(resolved.get("cost") or order.get("cost") or 0.0),
        "fee": _order_fee(resolved) or _order_fee(order),
        "fee_currency": fee_currency,
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

def _single_live_trade(fn):
    """Prevent overlapping LIVE arbitrage executions in one process."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not _live_trade_lock.acquire(blocking=False):
            return {
                "success": False,
                "status": "TRADE SKIPPED",
                "skip_reason": "LIVE TRADE ALREADY IN PROGRESS",
                "message": "Another LIVE trade is already in progress; new execution was blocked.",
            }
        try:
            return fn(*args, **kwargs)
        finally:
            _live_trade_lock.release()
    return wrapper


def execute_live_real_trade(
    buy_exchange_name,
    sell_exchange_name,
    buy_price=0.0,
    sell_price=0.0,
    trade_amount=1000.0
):
    """Execute one pre-funded cross-exchange LIVE arbitrage.

    The function deliberately refuses to place an order unless a fresh
    top-of-book calculation remains profitable after configured fees,
    slippage and a safety buffer.  This is a guard, not a guarantee: after
    the first order fills, market prices can still move before the second
    order is filled.
    """
    if emergency_stop_active():
        return _emergency_stop_result("exchange execution")

    if str(getattr(config, "TRADING_MODE", "LIVE")).upper() != "LIVE":
        return {"success": False, "message": "Only LIVE trading is supported."}

    if buy_exchange_name == sell_exchange_name:
        return {"success": False, "message": "Buy and sell exchanges must be different."}

    if buy_exchange_name not in config.SUPPORTED_EXCHANGES or sell_exchange_name not in config.SUPPORTED_EXCHANGES:
        return {"success": False, "message": "Unsupported exchange configured."}

    buy_ex, buy_err = get_authenticated_exchange(buy_exchange_name)
    if buy_err:
        return {"success": False, "message": buy_err}
    sell_ex, sell_err = get_authenticated_exchange(sell_exchange_name)
    if sell_err:
        return {"success": False, "message": sell_err}

    try:
        if not getattr(buy_ex, "markets", None):
            buy_ex.load_markets(reload=False)
        if not getattr(sell_ex, "markets", None):
            sell_ex.load_markets(reload=False)

        base_currency, quote_currency = get_symbol_currencies(config.SYMBOL)

        # ----------------------------------------------------
        # 1. FRESH EXECUTABLE PRICES — NEVER TRUST DASHBOARD PRICES
        # ----------------------------------------------------
        buy_book = buy_ex.fetch_order_book(config.SYMBOL, limit=int(getattr(config, "ORDERBOOK_LIMIT", 50)))
        sell_book = sell_ex.fetch_order_book(config.SYMBOL, limit=int(getattr(config, "ORDERBOOK_LIMIT", 50)))
        asks = buy_book.get("asks") or []
        bids = sell_book.get("bids") or []
        if not asks or not bids:
            return {"success": False, "message": "No executable bid/ask liquidity available."}

        fresh_buy_price = float(asks[0][0])
        fresh_sell_price = float(bids[0][0])
        if fresh_buy_price <= 0 or fresh_sell_price <= 0:
            return {"success": False, "message": "Invalid executable market prices."}
        if fresh_sell_price <= fresh_buy_price:
            return {"success": False, "message": "No positive arbitrage spread at execution time."}

        # ----------------------------------------------------
        # 2. BALANCES — PRE-FUNDED ARBITRAGE ONLY
        # ----------------------------------------------------
        buy_balance = buy_ex.fetch_balance()
        sell_balance = sell_ex.fetch_balance()
        buy_free_usdt = float((buy_balance.get("free", {}) or {}).get(quote_currency, 0.0) or 0.0)
        sell_free_eth = float((sell_balance.get("free", {}) or {}).get(base_currency, 0.0) or 0.0)

        requested_usdt = float(trade_amount)
        if requested_usdt <= 0:
            return {"success": False, "message": "Trade amount must be positive."}

        max_trade = float(getattr(config, "MAX_TRADE_AMOUNT_USDT", requested_usdt))
        min_trade = float(getattr(config, "MIN_TRADE_USDT", 0.0))
        usage = min(max(float(getattr(config, "MAX_BALANCE_USAGE", 0.90)), 0.0), 1.0)
        final_trade_usdt = min(requested_usdt, max_trade, buy_free_usdt * usage)
        final_trade_usdt = float(buy_ex.cost_to_precision(config.SYMBOL, final_trade_usdt))
        if final_trade_usdt < min_trade:
            return {"success": False, "message": f"Available USDT is insufficient for the configured minimum trade ({min_trade:.4f} USDT)."}

        raw_eth = final_trade_usdt / fresh_buy_price
        buy_eth = float(buy_ex.amount_to_precision(config.SYMBOL, raw_eth))
        sell_eth = float(sell_ex.amount_to_precision(config.SYMBOL, buy_eth))
        if buy_eth <= 0 or sell_eth <= 0:
            return {"success": False, "message": "Calculated ETH quantity is zero after exchange precision."}
        if sell_free_eth < sell_eth:
            return {
                "success": False,
                "message": f"SELL BLOCKED: need {sell_eth:.12f} {base_currency} on {sell_exchange_name}; available {sell_free_eth:.12f}."
            }

        # ----------------------------------------------------
        # 3. ORDER LIMITS
        # ----------------------------------------------------
        valid, message = validate_order_limits(buy_ex, config.SYMBOL, buy_eth, fresh_buy_price)
        if not valid:
            return {"success": False, "message": f"BUY BLOCKED: {message}"}
        valid, message = validate_order_limits(sell_ex, config.SYMBOL, sell_eth, fresh_sell_price)
        if not valid:
            return {"success": False, "message": f"SELL BLOCKED: {message}"}

        # ----------------------------------------------------
        # 4. PROFIT-ONLY GATE
        # Conservative fee + slippage estimate.  The configured safety
        # buffer must also be cleared before ANY real order is submitted.
        # ----------------------------------------------------
        fee_rate = float(getattr(config, "ESTIMATED_FEE_PERCENT", getattr(config, "MAKER_TAKER_FEE_PCT", 0.1))) / 100.0
        slip_rate = float(getattr(config, "SLIPPAGE_PCT", 0.0)) / 100.0 if getattr(config, "SLIPPAGE_ENABLED", True) else 0.0
        safety_buffer_pct = float(getattr(config, "PROFIT_SAFETY_BUFFER_PERCENT", 0.05)) / 100.0
        safety_buffer_usdt = float(getattr(config, "PROFIT_SAFETY_BUFFER_USDT", 0.01))

        conservative_buy = fresh_buy_price * (1.0 + slip_rate)
        conservative_sell = fresh_sell_price * (1.0 - slip_rate)
        estimated_buy_cost = buy_eth * conservative_buy
        estimated_sell_value = sell_eth * conservative_sell
        estimated_buy_fee = estimated_buy_cost * fee_rate
        estimated_sell_fee = estimated_sell_value * fee_rate
        estimated_net_profit = estimated_sell_value - estimated_buy_cost - estimated_buy_fee - estimated_sell_fee
        estimated_profit_pct = (estimated_net_profit / estimated_buy_cost * 100.0) if estimated_buy_cost else 0.0

        required_profit = max(
            float(getattr(config, "MIN_PROFIT", 0.01)) + safety_buffer_usdt,
            estimated_buy_cost * (float(getattr(config, "MIN_PROFIT_PERCENT", 0.20)) / 100.0 + safety_buffer_pct),
        )
        if estimated_net_profit <= 0 or estimated_net_profit < required_profit:
            return {
                "success": False,
                "status": "TRADE SKIPPED",
                "skip_reason": "NET PROFIT BELOW SAFE THRESHOLD",
                "message": (
                    f"TRADE BLOCKED: expected net profit {estimated_net_profit:.8f} USDT "
                    f"({estimated_profit_pct:.4f}%) is below the safe threshold {required_profit:.8f} USDT."
                ),
                "estimated_net_profit": estimated_net_profit,
            }

        # ----------------------------------------------------
        # 5. FINAL EMERGENCY-STOP CHECK BEFORE BUY
        # ----------------------------------------------------
        if emergency_stop_active():
            return _emergency_stop_result("buy order")

        print(f"Submitting LIVE BUY on {buy_exchange_name}: {buy_eth:.12f} {base_currency}", flush=True)
        buy_order = buy_ex.create_market_buy_order(config.SYMBOL, buy_eth)
        buy_result = _resolve_filled_order(buy_ex, buy_order)
        buy_order_id = buy_result["id"]
        print(
            f"ORDER RESULT: exchange={buy_exchange_name} side=buy symbol={config.SYMBOL} "
            f"id={buy_order_id} amount={buy_eth:.12f} filled={buy_result['filled']:.12f} "
            f"average={buy_result['average']:.8f} status={buy_result['status']} fee={buy_result['fee']:.8f}",
            flush=True,
        )

        if not _filled(buy_result, buy_eth):
            return {
                "success": False,
                "message": f"BUY FAILED: order {buy_order_id} was not fully filled (status: {buy_result['status'] or 'unknown'}).",
                "buy_order_id": buy_order_id,
                "order_result": buy_result,
                "recovery_required": buy_result["filled"] > 0,
            }

        # ----------------------------------------------------
        # 6. AFTER BUY: FRESH SELL PRICE + REALISTIC PROFIT RECHECK
        # ----------------------------------------------------
        if emergency_stop_active():
            return {
                **_emergency_stop_result("sell order"),
                "buy_order_id": buy_order_id,
                "recovery_required": True,
            }

        # Cross-exchange arbitrage is pre-funded. The sell inventory is on
        # the sell venue, so the buy fill does not transfer ETH to it.
        actual_buy_filled = float(buy_result.get("filled") or 0.0)
        if actual_buy_filled <= 0:
            return {
                "success": False,
                "message": "BUY BLOCKED: exchange reported zero filled quantity.",
                "buy_order_id": buy_order_id,
                "recovery_required": True,
            }
        sell_book_now = sell_ex.fetch_order_book(config.SYMBOL, limit=int(getattr(config, "ORDERBOOK_LIMIT", 50)))
        current_bids = sell_book_now.get("bids") or []
        if not current_bids:
            recovery = _recover_unhedged_buy(buy_ex, config.SYMBOL, actual_buy_filled if "actual_buy_filled" in locals() else buy_result.get("filled", 0.0))
            return {
                "success": False,
                "message": "SELL BLOCKED: sell order book became unavailable after BUY.",
                "buy_order_id": buy_order_id,
                "recovery_required": not recovery.get("success"),
                "recovery": recovery,
            }
        fresh_sell_price = float(current_bids[0][0])
        if fresh_sell_price <= 0:
            return {
                "success": False,
                "message": "SELL BLOCKED: invalid sell price after BUY.",
                "buy_order_id": buy_order_id,
                "recovery_required": True,
            }

        # Pair the SELL leg with the quantity that actually filled on BUY.
        # This prevents an estimated/pre-rounded quantity from creating a
        # mismatched two-leg trade after a partial fill or precision change.
        sell_eth = float(sell_ex.amount_to_precision(config.SYMBOL, actual_buy_filled))
        if sell_eth <= 0:
            return {
                "success": False,
                "message": "SELL BLOCKED: actual BUY fill rounds to zero on the sell exchange.",
                "buy_order_id": buy_order_id,
                "eth_amount": actual_buy_filled,
                "recovery_required": True,
            }

        # Re-check the sell wallet after BUY and use the full executable
        # bid depth (VWAP), not only the first bid, for the post-BUY gate.
        sell_balance_after = sell_ex.fetch_balance()
        sell_free_eth_after = float((sell_balance_after.get("free", {}) or {}).get(base_currency, 0.0) or 0.0)
        if sell_free_eth_after + 1e-12 < sell_eth:
            return {
                "success": False,
                "message": f"SELL BLOCKED: available {sell_free_eth_after:.12f} {base_currency} is below {sell_eth:.12f} after BUY.",
                "buy_order_id": buy_order_id,
                "eth_amount": actual_buy_filled,
                "recovery_required": True,
            }

        sell_fill = _consume_bids_for_base(current_bids, sell_eth)
        if not sell_fill:
            recovery = _recover_unhedged_buy(buy_ex, config.SYMBOL, actual_buy_filled)
            return {
                "success": False,
                "message": "SELL BLOCKED: insufficient executable bid depth after BUY.",
                "buy_order_id": buy_order_id,
                "eth_amount": actual_buy_filled,
                "recovery_required": not recovery.get("success"),
                "recovery": recovery,
            }
        _, sell_value_estimate, sell_vwap = sell_fill

        actual_buy_price = buy_result["average"] or fresh_buy_price
        actual_buy_cost = buy_result["cost"] or (actual_buy_filled * actual_buy_price)
        actual_buy_fee = buy_result["fee"]
        actual_sell_fee_estimate = sell_value_estimate * fee_rate
        buy_fee_quote = actual_buy_fee
        if buy_result.get("fee_currency") == base_currency:
            buy_fee_quote = actual_buy_fee * actual_buy_price
        post_buy_expected_profit = sell_value_estimate - actual_buy_cost - buy_fee_quote - actual_sell_fee_estimate
        if post_buy_expected_profit <= 0:
            recovery = _recover_unhedged_buy(buy_ex, config.SYMBOL, actual_buy_filled)
            return {
                "success": False,
                "status": "TRADE RECOVERED" if recovery.get("success") else "RECOVERY REQUIRED",
                "message": (
                    f"SELL BLOCKED: post-BUY executable price no longer covers costs "
                    f"(expected {post_buy_expected_profit:.8f} USDT)."
                ),
                "buy_order_id": buy_order_id,
                "eth_amount": actual_buy_filled,
                "recovery_required": not recovery.get("success"),
                "recovery": recovery,
            }

        # ----------------------------------------------------
        # 7. FINAL EMERGENCY-STOP CHECK BEFORE SELL
        # ----------------------------------------------------
        if emergency_stop_active():
            return {
                **_emergency_stop_result("sell order"),
                "buy_order_id": buy_order_id,
                "recovery_required": True,
            }

        print(f"Submitting LIVE SELL on {sell_exchange_name}: {sell_eth:.12f} {base_currency}", flush=True)
        sell_order = sell_ex.create_market_sell_order(config.SYMBOL, sell_eth)
        sell_result = _resolve_filled_order(sell_ex, sell_order)
        sell_order_id = sell_result["id"]
        print(
            f"ORDER RESULT: exchange={sell_exchange_name} side=sell symbol={config.SYMBOL} "
            f"id={sell_order_id} amount={sell_eth:.12f} filled={sell_result['filled']:.12f} "
            f"average={sell_result['average']:.8f} status={sell_result['status']} fee={sell_result['fee']:.8f}",
            flush=True,
        )

        if not _filled(sell_result, sell_eth):
            return {
                "success": False,
                "message": f"SELL FAILED: order {sell_order_id} was not fully filled (status: {sell_result['status'] or 'unknown'}).",
                "buy_order_id": buy_order_id,
                "sell_order_id": sell_order_id,
                "order_result": sell_result,
                "recovery_required": True,
            }

        # ----------------------------------------------------
        # 8. ACTUAL P&L FROM EXCHANGE CONFIRMATIONS
        # ----------------------------------------------------
        actual_buy_price = buy_result["average"] or fresh_buy_price
        actual_sell_price = sell_result["average"] or fresh_sell_price
        actual_buy_cost = buy_result["cost"] or (buy_result["filled"] * actual_buy_price)
        actual_sell_value = sell_result["cost"] or (sell_result["filled"] * actual_sell_price)
        buy_fee = buy_result["fee"]
        sell_fee = sell_result["fee"]

        buy_fee_quote = buy_fee * actual_buy_price if buy_result.get("fee_currency") == base_currency else buy_fee
        sell_fee_quote = sell_fee * actual_sell_price if sell_result.get("fee_currency") == base_currency else sell_fee
        total_fees = buy_fee_quote + sell_fee_quote
        net_profit = actual_sell_value - actual_buy_cost - total_fees

        trade = {
            "buy": buy_exchange_name,
            "sell": sell_exchange_name,
            "buy_exchange": buy_exchange_name,
            "sell_exchange": sell_exchange_name,
            "buy_price": actual_buy_price,
            "sell_price": actual_sell_price,
            "effective_buy_price": actual_buy_price,
            "effective_sell_price": actual_sell_price,
            "fees": round(total_fees, 8),
            "profit": round(net_profit, 8),
            "estimated_profit": round(estimated_net_profit, 8),
            "buy_order_id": buy_order_id,
            "sell_order_id": sell_order_id,
            "symbol": config.SYMBOL,
            "buy_side": "buy",
            "sell_side": "sell",
            "buy_status": buy_result["status"],
            "sell_status": sell_result["status"],
            "buy_filled": buy_result["filled"],
            "sell_filled": sell_result["filled"],
            "buy_average_price": actual_buy_price,
            "sell_average_price": actual_sell_price,
            "buy_fee": buy_fee_quote,
            "sell_fee": sell_fee_quote,
            "eth_amount": sell_result["filled"],
            "trade_amount": actual_buy_cost,
            "created_at": datetime.now().astimezone().isoformat(),
            "mode": "LIVE",
            "exchange_confirmed": True,
        }

        # A completed two-leg trade is always recorded for audit/risk control.
        # It is only reported as a successful profitable trade when actual P&L
        # is positive. Market movement after the first leg can still cause a
        # realized loss; no software can guarantee otherwise.
        if net_profit <= 0:
            return {
                "success": False,
                "status": "LIVE TRADE COMPLETED - NEGATIVE P&L",
                "message": f"LIVE trade completed but realized net P&L was {net_profit:.8f} USDT.",
                "trade": trade,
                "recovery_required": False,
            }

        return {
            "success": True,
            "status": "LIVE TRADE EXECUTED",
            "message": f"LIVE PROFITABLE TRADE EXECUTED: +{net_profit:.8f} USDT.",
            "trade": trade,
        }
    except ccxt.InsufficientFunds as exc:
        return {"success": False, "message": f"LIVE TRADE BLOCKED: insufficient funds: {exc}"}
    except ccxt.NetworkError as exc:
        return {"success": False, "message": f"LIVE TRADE BLOCKED: exchange/network error: {exc}", "recovery_required": True}
    except Exception as exc:
        return {"success": False, "message": f"LIVE TRADE ERROR: {exc}", "recovery_required": True}


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