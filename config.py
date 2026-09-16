
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

AUTO_TRADE_ENABLED = False


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
MIN_PROFIT = 0.1

# Minimum NET profit percentage required.
MIN_PROFIT_PERCENT = 0.20


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


# ============================================================
# FLASK
# ============================================================

HOST = os.getenv(
    "HOST",
    "127.0.0.1"
)


PORT = int(
    os.getenv(
        "PORT",
        "5000"
    )
)


DEBUG = os.getenv(
    "DEBUG",
    "True"
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
