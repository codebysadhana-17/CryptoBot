
# ============================================================
# CRYPTO ARBITRAGE BOT - REAL TRADING CONFIGURATION
# ============================================================

import os

# ============================================================
# BASE DIRECTORY
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# EXCHANGES
# ONLY BINANCE, BYBIT, AND KUCOIN ARE SUPPORTED
# ============================================================

SUPPORTED_EXCHANGES = [
    "Binance",
    "Bybit",
    "KuCoin",
]


# ============================================================
# TRADING SYMBOL
# ============================================================

SYMBOL = os.getenv(
    "TRADING_SYMBOL",
    "ETH/USDT"
)


# ============================================================
# TRADING MODE
# ============================================================

# This project uses LIVE exchange APIs.
TRADING_MODE = "LIVE"


# ============================================================
# AUTO TRADING
# ============================================================

# IMPORTANT:
#
# False = Bot detects arbitrage opportunity,
# but DOES NOT automatically place real orders.
#
# Keep this False until all testing is completed.

AUTO_TRADE_ENABLED = os.getenv("AUTO_TRADE_ENABLED", "false").lower() == "true"


# ============================================================
# LIVE TRADING ARM
# ============================================================

# Additional safety switch.
#
# False = REAL orders are blocked.
# True  = Real order execution is allowed
#         when all other conditions are satisfied.

LIVE_TRADING_ARMED = os.getenv("LIVE_TRADING_ARMED", "false").lower() == "true"

# Emergency stop defaults to active. It must be explicitly cleared before
# any live execution can be attempted.
EMERGENCY_STOP = os.getenv("EMERGENCY_STOP", "true").lower() != "false"


# ============================================================
# TRADE SIZE
# ============================================================

# First small live test amount.
DEFAULT_TRADE_AMOUNT = 5.0

# Never allow more than this amount per arbitrage trade.
MAX_TRADE_AMOUNT_USDT = 5.0

# Minimum trade amount requested by the bot.
MIN_TRADE_USDT = 5.0


# ============================================================
# DYNAMIC BALANCE
# ============================================================

# Use available wallet balance dynamically.
DYNAMIC_BALANCE_TRADING = True

# Maximum percentage of available USDT that can be used.
#
# 0.90 = maximum 90% of available free USDT.

MAX_BALANCE_USAGE = 0.90


# ============================================================
# PROFIT REQUIREMENT
# ============================================================

# Minimum NET profit required after estimated fees.
MIN_PROFIT = 0.01

# Minimum NET profit percentage required.
MIN_PROFIT_PERCENT = 0.20

# Extra margin above the minimum profit requirement. This reduces the
# chance that a tiny apparent edge is consumed by latency/market movement.
PROFIT_SAFETY_BUFFER_PERCENT = float(os.getenv("PROFIT_SAFETY_BUFFER_PERCENT", "0.05"))
PROFIT_SAFETY_BUFFER_USDT = float(os.getenv("PROFIT_SAFETY_BUFFER_USDT", "0.01"))


# ============================================================
# FEES
# ============================================================

# Conservative estimated fee per order.
#
# 0.10 means 0.10%.

ESTIMATED_FEE_PERCENT = 0.10

# Compatibility names used by existing code.
MAKER_TAKER_FEE_PCT = ESTIMATED_FEE_PERCENT

BUY_FEE = ESTIMATED_FEE_PERCENT

SELL_FEE = ESTIMATED_FEE_PERCENT


# ============================================================
# TRANSFER FEE
# ============================================================

# The bot does NOT automatically transfer ETH
# between Binance and Bybit.
#
# ETH must already exist on the selling exchange
# for cross-exchange arbitrage.

TRANSFER_FEE = 0.0


# ============================================================
# SLIPPAGE
# ============================================================

SLIPPAGE_ENABLED = True

# Conservative expected slippage.
#
# 0.05 means 0.05%.

SLIPPAGE_PCT = 0.05


# ============================================================
# EXECUTION SAFETY
# ============================================================

# Only one arbitrage position at a time.
MAX_OPEN_TRADES = 1

# Minimum time between automatic trade attempts.
AUTO_TRADE_COOLDOWN = 30

# Price checking interval (seconds).
REFRESH_INTERVAL = 1


# ============================================================
# DAILY LOSS LIMIT
# ============================================================

# Stop trading if daily loss reaches this amount.
MAX_DAILY_LOSS_USDT = 0.50


# ============================================================
# NETWORK
# ============================================================

REQUEST_TIMEOUT_MS = 20000

# Market-data safety. Quotes older than this are not actionable.
MAX_QUOTE_AGE_MS = int(os.getenv("MAX_QUOTE_AGE_MS", "2500"))

# Fetch enough depth to model the configured trade size rather than only BBO.
ORDERBOOK_LIMIT = int(os.getenv("ORDERBOOK_LIMIT", "50"))

# Low-latency public market-data stream. Execution still validates with REST
# order-book depth before placing a real order.
WEBSOCKET_ENABLED = os.getenv("WEBSOCKET_ENABLED", "true").lower() == "true"

# Optional inventory rebalancing. Disabled by default because exchange
# withdrawals are irreversible once accepted by the exchange/network.
AUTO_REBALANCE_ENABLED = os.getenv("AUTO_REBALANCE_ENABLED", "false").lower() == "true"
REBALANCE_ARMED = os.getenv("REBALANCE_ARMED", "false").lower() == "true"
REBALANCE_MIN_USDT = float(os.getenv("REBALANCE_MIN_USDT", "25"))
REBALANCE_MAX_USDT = float(os.getenv("REBALANCE_MAX_USDT", "25"))
REBALANCE_ASSET = os.getenv("REBALANCE_ASSET", "ETH")
REBALANCE_NETWORK = os.getenv("REBALANCE_NETWORK", "")
REBALANCE_DESTINATION_EXCHANGE = os.getenv("REBALANCE_DESTINATION_EXCHANGE", "")
REBALANCE_DESTINATION_ADDRESS = os.getenv("REBALANCE_DESTINATION_ADDRESS", "")
REBALANCE_DESTINATION_TAG = os.getenv("REBALANCE_DESTINATION_TAG", "")



# ============================================================
# ADVANCED EXECUTION / DEX / REBALANCE
# ============================================================

# Native asyncio execution adapter. Disabled by default; when enabled,
# callers must explicitly use the async execution engine.
ASYNC_EXECUTION_ENABLED = os.getenv("ASYNC_EXECUTION_ENABLED", "false").lower() == "true"

# DEX flashloan adapter. Disabled by default because a real flashloan requires
# a deployed receiver contract, chain/router addresses, gas controls, and
# transaction simulation.
DEX_FLASHLOAN_ENABLED = os.getenv("DEX_FLASHLOAN_ENABLED", "false").lower() == "true"
DEX_FLASHLOAN_CHAIN = os.getenv("DEX_FLASHLOAN_CHAIN", "ethereum")
DEX_FLASHLOAN_PROVIDER = os.getenv("DEX_FLASHLOAN_PROVIDER", "aave_v3")
DEX_FLASHLOAN_RECEIVER = os.getenv("DEX_FLASHLOAN_RECEIVER", "")

# Controlled live-money verification. Disabled and unarmed by default.
# When enabled, the verification endpoint still requires an explicit
# confirmation payload and a real two-leg LIVE trade to complete before
# the bot records a VERIFIED state.
LIVE_VERIFICATION_ENABLED = os.getenv("LIVE_VERIFICATION_ENABLED", "false").lower() == "true"
LIVE_VERIFICATION_ARMED = os.getenv("LIVE_VERIFICATION_ARMED", "false").lower() == "true"
LIVE_VERIFICATION_MAX_USDT = float(os.getenv("LIVE_VERIFICATION_MAX_USDT", "5.0"))

# Rebalancing limits are denominated in the configured REBALANCE_ASSET,
# because exchange withdrawal APIs require an asset quantity, not USDT.
REBALANCE_MAX_ASSET_AMOUNT = float(os.getenv("REBALANCE_MAX_ASSET_AMOUNT", "0.02"))
REBALANCE_ALLOWED_ADDRESSES = [
    x.strip() for x in os.getenv("REBALANCE_ALLOWED_ADDRESSES", "").split(",") if x.strip()
]
REBALANCE_REQUIRE_WHITELIST = os.getenv("REBALANCE_REQUIRE_WHITELIST", "true").lower() == "true"

# ============================================================
# DATABASE
# ============================================================

DATA_DIR = (
    os.environ.get("DATA_DIR")
    or os.path.join(BASE_DIR, "data")
)

os.makedirs(DATA_DIR, exist_ok=True)


DATABASE_NAME = (
    os.environ.get("DATABASE_PATH")
    or os.path.join(DATA_DIR, "trades.db")
)


BACKUP_JSON_PATH = os.path.join(
    DATA_DIR,
    "trades_history_backup.json"
)


# Background engine lock prevents duplicate auto-trader loops when Gunicorn
# starts multiple workers. Only one worker owns the execution loop.
AUTO_TRADER_LOCK_PATH = os.getenv(
    "AUTO_TRADER_LOCK_PATH",
    os.path.join(DATA_DIR, "auto_trader.lock")
)


# ============================================================
# FLASK
# ============================================================

HOST = os.getenv(
    "HOST",
    "0.0.0.0"
)


PORT = int(
    os.getenv(
        "PORT",
        "5000"
    )
)


DEBUG = os.getenv(
    "DEBUG",
    "False"
).lower() == "true"


# ============================================================
# VALIDATION
# ============================================================

def validate_config():

    if TRADING_MODE != "LIVE":
        raise RuntimeError(
            "Only LIVE trading mode is supported."
        )

    if not SUPPORTED_EXCHANGES:
        raise RuntimeError(
            "No exchanges configured."
        )

    # Make sure only the supported spot exchanges are configured.
    allowed_exchanges = {"Binance", "Bybit", "KuCoin"}

    for exchange in SUPPORTED_EXCHANGES:
        if exchange not in allowed_exchanges:
            raise RuntimeError(
                f"Unsupported exchange configured: {exchange}"
            )

    if DEFAULT_TRADE_AMOUNT <= 0:
        raise RuntimeError(
            "DEFAULT_TRADE_AMOUNT must be greater than zero."
        )

    if MAX_TRADE_AMOUNT_USDT <= 0:
        raise RuntimeError(
            "MAX_TRADE_AMOUNT_USDT must be greater than zero."
        )

    if MIN_TRADE_USDT <= 0:
        raise RuntimeError(
            "MIN_TRADE_USDT must be greater than zero."
        )

    if MAX_BALANCE_USAGE <= 0 or MAX_BALANCE_USAGE > 1:
        raise RuntimeError(
            "MAX_BALANCE_USAGE must be between 0 and 1."
        )

    if MAX_OPEN_TRADES < 1:
        raise RuntimeError(
            "MAX_OPEN_TRADES must be at least 1."
        )

    if MIN_PROFIT < 0:
        raise RuntimeError(
            "MIN_PROFIT cannot be negative."
        )

    if MIN_PROFIT_PERCENT < 0:
        raise RuntimeError(
            "MIN_PROFIT_PERCENT cannot be negative."
        )

    if ESTIMATED_FEE_PERCENT < 0:
        raise RuntimeError(
            "ESTIMATED_FEE_PERCENT cannot be negative."
        )

    if SLIPPAGE_PCT < 0:
        raise RuntimeError(
            "SLIPPAGE_PCT cannot be negative."
        )

    if MAX_DAILY_LOSS_USDT < 0:
        raise RuntimeError(
            "MAX_DAILY_LOSS_USDT cannot be negative."
        )


# ============================================================
# RUN CONFIG VALIDATION
# ============================================================

validate_config()
