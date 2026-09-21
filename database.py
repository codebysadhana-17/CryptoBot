import sqlite3
import os
import json
from datetime import datetime

from config import DATABASE_NAME, BACKUP_JSON_PATH


# ============================================================
# DATABASE FOLDER
# ============================================================

os.makedirs(
    os.path.dirname(DATABASE_NAME),
    exist_ok=True
)


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    conn = sqlite3.connect(
        DATABASE_NAME
    )

    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# CREATE DATABASE
# ============================================================

def create_database():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            buy_exchange TEXT NOT NULL,

            sell_exchange TEXT NOT NULL,

            buy_price REAL NOT NULL,

            sell_price REAL NOT NULL,

            fees REAL NOT NULL,

            profit REAL NOT NULL,

            buy_order_id TEXT DEFAULT '',

            sell_order_id TEXT DEFAULT '',

            eth_amount REAL DEFAULT 0.0,

            slippage REAL DEFAULT 0.0,

            trade_amount REAL DEFAULT 0.0,

            created_at
                TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY DEFAULT 1,
            usdt_balance REAL NOT NULL,
            binance_usdt REAL NOT NULL,
            bybit_usdt REAL NOT NULL,
            kucoin_usdt REAL DEFAULT 0.0,
            binance_eth REAL DEFAULT 0.0,
            bybit_eth REAL DEFAULT 0.0,
            kucoin_eth REAL DEFAULT 0.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migrate columns if existing tables lack new columns
    cursor.execute("PRAGMA table_info(trades)")
    columns = [row[1] for row in cursor.fetchall()]

    for col, col_type in [
        ("buy_order_id", "TEXT DEFAULT ''"),
        ("sell_order_id", "TEXT DEFAULT ''"),
        ("eth_amount", "REAL DEFAULT 0.0"),
        ("slippage", "REAL DEFAULT 0.0"),
        ("trade_amount", "REAL DEFAULT 0.0"),
        ("symbol", "TEXT DEFAULT 'ETH/USDT'"),
        ("buy_side", "TEXT DEFAULT 'buy'"),
        ("sell_side", "TEXT DEFAULT 'sell'"),
        ("buy_status", "TEXT DEFAULT ''"),
        ("sell_status", "TEXT DEFAULT ''"),
        ("buy_filled", "REAL DEFAULT 0.0"),
        ("sell_filled", "REAL DEFAULT 0.0"),
        ("buy_average_price", "REAL DEFAULT 0.0"),
        ("sell_average_price", "REAL DEFAULT 0.0"),
        ("buy_fee", "REAL DEFAULT 0.0"),
        ("sell_fee", "REAL DEFAULT 0.0"),
        ("mode", "TEXT DEFAULT 'LIVE'"),
        ("exchange_confirmed", "INTEGER DEFAULT 0")
    ]:
        if col not in columns:
            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")

    # Legacy/demo rows must never appear as live exchange executions.
    cursor.execute("DELETE FROM trades WHERE COALESCE(exchange_confirmed, 0) != 1")


    cursor.execute("PRAGMA table_info(portfolio)")
    port_cols = [row[1] for row in cursor.fetchall()]
    if "coinbase_usdt" not in port_cols:
        cursor.execute("ALTER TABLE portfolio ADD COLUMN coinbase_usdt REAL DEFAULT 3333.34")
    for eth_column in ("binance_eth", "bybit_eth", "kraken_eth"):
        if eth_column not in port_cols:
            cursor.execute(f"ALTER TABLE portfolio ADD COLUMN {eth_column} REAL DEFAULT 0.0")
    if "coinbase_eth" not in port_cols:
        cursor.execute("ALTER TABLE portfolio ADD COLUMN coinbase_eth REAL DEFAULT 0.0")

    # Seed portfolio if empty
    cursor.execute("SELECT COUNT(*) FROM portfolio")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO portfolio (id, usdt_balance, binance_usdt, bybit_usdt, kucoin_usdt, coinbase_usdt)
            VALUES (1, 0.00, 0.00, 0.00, 0.00, 0.00)
        """)


    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            exchange TEXT PRIMARY KEY,
            api_key TEXT NOT NULL,
            api_secret TEXT NOT NULL,
            api_passphrase TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("PRAGMA table_info(api_keys)")
    api_columns = [row[1] for row in cursor.fetchall()]
    if "api_passphrase" not in api_columns:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN api_passphrase TEXT DEFAULT ''")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS opportunity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buy_exchange TEXT,
            sell_exchange TEXT,
            symbol TEXT,
            spread REAL DEFAULT 0.0,
            net_profit REAL DEFAULT 0.0,
            profitable INTEGER DEFAULT 0,
            decision TEXT DEFAULT '',
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

    # Auto-restore trades from JSON backup if database was wiped on server restart
    restore_trades_from_json_backup()


def save_bot_setting(key, value):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            INSERT INTO bot_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
        """, (str(key), json.dumps(value)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error saving setting {key}: {e}", flush=True)


def load_all_bot_settings():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("SELECT key, value FROM bot_settings")
        rows = cursor.fetchall()
        conn.close()
        settings = {}
        for row in rows:
            try:
                settings[row["key"]] = json.loads(row["value"])
            except Exception:
                settings[row["key"]] = row["value"]
        return settings
    except Exception as e:
        print(f"⚠️ Error loading bot settings: {e}", flush=True)
        return {}


def sync_trades_to_json_backup():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()

        trades_list = [dict(row) for row in rows]
        with open(BACKUP_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(trades_list, f, indent=2)
    except Exception as e:
        print(f"⚠️ JSON backup sync error: {e}", flush=True)


def restore_trades_from_json_backup():
    if not os.path.exists(BACKUP_JSON_PATH):
        return

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM trades")
        count = cursor.fetchone()[0]

        if count == 0:
            with open(BACKUP_JSON_PATH, "r", encoding="utf-8") as f:
                backup_trades = json.load(f)

            if backup_trades and isinstance(backup_trades, list) and len(backup_trades) > 0:
                print(f"📦 Restoring {len(backup_trades)} trades from persistent JSON backup...", flush=True)
                for trade in backup_trades:
                    cursor.execute("""
                        INSERT INTO trades (
                            buy_exchange, sell_exchange, buy_price, sell_price, fees, profit,
                            buy_order_id, sell_order_id, eth_amount, slippage, trade_amount,
                            mode, exchange_confirmed, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade.get("buy_exchange") or trade.get("buy", ""),
                        trade.get("sell_exchange") or trade.get("sell", ""),
                        float(trade.get("buy_price", 0.0)),
                        float(trade.get("sell_price", 0.0)),
                        float(trade.get("fees", 0.0)),
                        float(trade.get("profit", 0.0)),
                        trade.get("buy_order_id", ""),
                        trade.get("sell_order_id", ""),
                        float(trade.get("eth_amount", 0.0)),
                        float(trade.get("slippage", 0.0)),
                        float(trade.get("trade_amount", 0.0)),
                        trade.get("mode", "LIVE"),
                        0,
                        trade.get("created_at") or datetime.now().astimezone().isoformat()
                    ))
                conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Restore trades from JSON backup error: {e}", flush=True)


# ============================================================
# API KEY MANAGEMENT
# ============================================================

def canonical_exchange_name(exchange):
    names = {
        "binance": "Binance",
        "bybit": "Bybit",
        "kucoin": "KuCoin",
    }
    return names.get(str(exchange).strip().lower(), str(exchange).strip())

def save_api_key(exchange, api_key, api_secret, api_passphrase=""):
    create_database()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO api_keys (exchange, api_key, api_secret, api_passphrase, is_active, updated_at)
        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(exchange) DO UPDATE SET
            api_key = excluded.api_key,
            api_secret = excluded.api_secret,
            api_passphrase = excluded.api_passphrase,
            is_active = 1,
            updated_at = CURRENT_TIMESTAMP
    """, (canonical_exchange_name(exchange), api_key.strip(), api_secret.strip(), api_passphrase.strip()))
    conn.commit()
    conn.close()


def get_api_key(exchange):
    # Production deployments should prefer environment/secret-manager values
    # over credentials persisted in the SQLite database.
    ex_upper = exchange.upper()
    env_key = os.environ.get(f"{ex_upper}_API_KEY") or os.environ.get(f"{ex_upper}_KEY")
    env_secret = os.environ.get(f"{ex_upper}_API_SECRET") or os.environ.get(f"{ex_upper}_SECRET")
    env_passphrase = os.environ.get(f"{ex_upper}_API_PASSPHRASE") or os.environ.get(f"{ex_upper}_PASSPHRASE")
    if env_key and env_secret:
        return {
            "exchange": exchange,
            "api_key": env_key.strip(),
            "api_secret": env_secret.strip(),
            "api_passphrase": (env_passphrase or "").strip(),
            "is_active": 1,
        }

    create_database()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM api_keys WHERE LOWER(exchange) = LOWER(?) AND is_active = 1", (exchange,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)

    return None


def get_all_api_keys():
    create_database()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT exchange, api_key, api_secret, is_active, updated_at
        FROM api_keys
        WHERE is_active = 1
    """)
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for row in rows:
        r = dict(row)
        raw_k = r["api_key"]
        configured = bool(raw_k and r.get("api_secret"))
        if not configured:
            continue
        masked = raw_k[:4] + "..." + raw_k[-4:] if len(raw_k) > 8 else "****"
        data = {
            "api_key_masked": masked,
            "has_key": True,
            "configured": True,
            "updated_at": r["updated_at"]
        }
        result[canonical_exchange_name(r["exchange"])] = data
        result[r["exchange"].lower()] = data
    return result



def delete_api_key(exchange):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM api_keys WHERE exchange = ?", (canonical_exchange_name(exchange),))
    conn.commit()
    conn.close()



# ============================================================
# PORTFOLIO MANAGEMENT
# ============================================================

def get_portfolio():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("SELECT * FROM portfolio WHERE id = 1")

    row = cursor.fetchone()

    conn.close()

    if row:
        d = dict(row)
        if "coinbase_usdt" not in d:
            d["coinbase_usdt"] = d.get("kraken_usdt", 3333.34)
        if "coinbase_eth" not in d:
            d["coinbase_eth"] = d.get("kraken_eth", 0.0)
        return d

    return {
        "usdt_balance": 0.00,
        "binance_usdt": 0.00,
        "bybit_usdt": 0.00,
        "kraken_usdt": 0.00,
        "coinbase_usdt": 0.00,
        "binance_eth": 0.0,
        "bybit_eth": 0.0,
        "kraken_eth": 0.0,
        "coinbase_eth": 0.0
    }


def update_portfolio(portfolio):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE portfolio
        SET usdt_balance = ?,
            binance_usdt = ?,
            bybit_usdt = ?,
            kraken_usdt = ?,
            coinbase_usdt = ?,
            binance_eth = ?,
            bybit_eth = ?,
            kraken_eth = ?,
            coinbase_eth = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (
        float(portfolio.get("usdt_balance", 0.0)),
        float(portfolio.get("binance_usdt", 0.0)),
        float(portfolio.get("bybit_usdt", 0.0)),
        float(portfolio.get("kraken_usdt", 0.0)),
        float(portfolio.get("coinbase_usdt", 0.0)),
        float(portfolio.get("binance_eth", 0.0)),
        float(portfolio.get("bybit_eth", 0.0)),
        float(portfolio.get("kraken_eth", 0.0)),
        float(portfolio.get("coinbase_eth", 0.0))
    ))

    conn.commit()

    conn.close()


def reset_portfolio(initial_usdt=0.00):

    per_ex = round(initial_usdt / 2, 2) if initial_usdt > 0 else 0.00

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE portfolio
        SET usdt_balance = ?,
            binance_usdt = ?,
            bybit_usdt = ?,
            kraken_usdt = ?,
            coinbase_usdt = ?,
            binance_eth = 0.0,
            bybit_eth = 0.0,
            kraken_eth = 0.0,
            coinbase_eth = 0.0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (initial_usdt, per_ex, per_ex, per_ex, per_ex))

    conn.commit()

    conn.close()


# ============================================================
# SAVE TRADE
# ============================================================

def save_trade(trade):

    if trade.get("exchange_confirmed") is not True:
        print("Unconfirmed trade rejected; it will not enter the audit log.", flush=True)
        return

    create_database()

    conn = get_connection()

    cursor = conn.cursor()

    created_at_str = trade.get("created_at")
    if not created_at_str:
        created_at_str = datetime.now().astimezone().isoformat()

    cursor.execute("""
        INSERT INTO trades
        (
            buy_exchange,
            sell_exchange,
            buy_price,
            sell_price,
            fees,
            profit,
            buy_order_id,
            sell_order_id,
            eth_amount,
            slippage,
            trade_amount,
            symbol,
            buy_side,
            sell_side,
            buy_status,
            sell_status,
            buy_filled,
            sell_filled,
            buy_average_price,
            sell_average_price,
            buy_fee,
            sell_fee,
            mode,
            exchange_confirmed,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.get("buy_exchange") or trade.get("buy", ""),
        trade.get("sell_exchange") or trade.get("sell", ""),
        float(trade["buy_price"]),
        float(trade["sell_price"]),
        float(trade["fees"]),
        float(trade["profit"]),
        trade.get("buy_order_id", ""),
        trade.get("sell_order_id", ""),
        float(trade.get("eth_amount", 0.0)),
        float(trade.get("slippage", 0.0)),
        float(trade.get("trade_amount", 0.0)),
        trade.get("symbol", "ETH/USDT"),
        trade.get("buy_side", "buy"),
        trade.get("sell_side", "sell"),
        trade.get("buy_status", ""),
        trade.get("sell_status", ""),
        float(trade.get("buy_filled", 0.0)),
        float(trade.get("sell_filled", 0.0)),
        float(trade.get("buy_average_price", 0.0)),
        float(trade.get("sell_average_price", 0.0)),
        float(trade.get("buy_fee", 0.0)),
        float(trade.get("sell_fee", 0.0)),
        trade.get("mode", "LIVE"),
        1,
        created_at_str
    ))

    conn.commit()
    conn.close()

    # Sync to persistent JSON backup file
    sync_trades_to_json_backup()


# ============================================================
# GET ALL TRADES
# ============================================================

def get_all_trades():

    create_database()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            buy_exchange,
            sell_exchange,
            buy_price,
            sell_price,
            fees,
            profit,
            buy_order_id,
            sell_order_id,
            eth_amount,
            slippage,
            trade_amount,
            symbol,
            buy_side,
            sell_side,
            buy_status,
            sell_status,
            buy_filled,
            sell_filled,
            buy_average_price,
            sell_average_price,
            buy_fee,
            sell_fee,
            COALESCE(mode, 'LIVE') AS mode,
                        exchange_confirmed,
            created_at
        FROM trades
                WHERE UPPER(COALESCE(mode, 'LIVE')) = 'LIVE'
                    AND exchange_confirmed = 1
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        d = dict(row)
        d["buy"] = d.get("buy_exchange", "")
        d["sell"] = d.get("sell_exchange", "")
        d["timestamp"] = d.get("created_at")
        result.append(d)

    return result


def get_latest_trade():
    create_database()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            buy_exchange,
            sell_exchange,
            buy_price,
            sell_price,
            fees,
            profit,
            buy_order_id,
            sell_order_id,
            eth_amount,
            slippage,
            trade_amount,
            symbol,
            buy_side,
            sell_side,
            buy_status,
            sell_status,
            buy_filled,
            sell_filled,
            buy_average_price,
            sell_average_price,
            buy_fee,
            sell_fee,
            COALESCE(mode, 'LIVE') AS mode,
                        exchange_confirmed,
            created_at
        FROM trades
                WHERE UPPER(COALESCE(mode, 'LIVE')) = 'LIVE'
                    AND exchange_confirmed = 1
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    conn.close()

    if row:
        d = dict(row)
        d["buy"] = d.get("buy_exchange", "")
        d["sell"] = d.get("sell_exchange", "")
        d["timestamp"] = d.get("created_at")
        return d

    return None



# ============================================================
# DELETE ALL TRADES
# ============================================================

def delete_all_trades():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    conn.commit()
    conn.close()

    if os.path.exists(BACKUP_JSON_PATH):
        try:
            with open(BACKUP_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception as e:
            print(f"Error clearing JSON backup: {e}", flush=True)

    print("All old trades deleted successfully.", flush=True)


# ============================================================
# TOTAL PROFIT
# ============================================================

def get_total_profit():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COALESCE(
                SUM(profit),
                0
            )
        FROM trades
                WHERE UPPER(COALESCE(mode, 'LIVE')) = 'LIVE'
                    AND exchange_confirmed = 1
    """)

    result = cursor.fetchone()[0]

    conn.close()

    return round(
        float(result),
        2
    )


def get_today_live_profit():
    """Return today's confirmed live-trade profit in the local timezone."""
    create_database()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT profit, created_at
        FROM trades
        WHERE UPPER(COALESCE(mode, 'LIVE')) = 'LIVE'
          AND exchange_confirmed = 1
    """)
    rows = cursor.fetchall()
    conn.close()

    today = datetime.now().astimezone().date()
    total = 0.0
    for row in rows:
        try:
            created_at = str(row["created_at"] or "").replace("Z", "+00:00")
            trade_date = datetime.fromisoformat(created_at).astimezone().date()
            if trade_date == today:
                total += float(row["profit"] or 0.0)
        except (TypeError, ValueError, OverflowError):
            continue

    return round(total, 8)


# ============================================================
# TOTAL TRADES
# ============================================================

def get_total_trades():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*)
        FROM trades
                WHERE UPPER(COALESCE(mode, 'LIVE')) = 'LIVE'
                    AND exchange_confirmed = 1
    """)

    result = cursor.fetchone()[0]

    conn.close()

    return int(result)


# ============================================================
# LIVE P&L MONITORING
# ============================================================

def _live_trade_rows():
    """Fetch only exchange-confirmed LIVE trades for reporting."""
    create_database()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT buy_exchange, sell_exchange, fees, profit, trade_amount,
               eth_amount, created_at
        FROM trades
        WHERE UPPER(COALESCE(mode, 'LIVE')) = 'LIVE'
          AND exchange_confirmed = 1
        ORDER BY id DESC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def _parse_trade_local_date(value):
    try:
        raw = str(value or "").replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt.astimezone().date()
    except (TypeError, ValueError, OverflowError):
        return None


def get_live_pnl_summary():
    """Return actual recorded LIVE execution P&L, not estimates."""
    rows = _live_trade_rows()
    today = datetime.now().astimezone().date()

    def summary_for(items):
        gross_profit = sum(max(float(r.get("profit") or 0.0), 0.0) for r in items)
        gross_loss = sum(min(float(r.get("profit") or 0.0), 0.0) for r in items)
        fees = sum(float(r.get("fees") or 0.0) for r in items)
        net = sum(float(r.get("profit") or 0.0) for r in items)
        volume = sum(float(r.get("trade_amount") or 0.0) for r in items)
        profitable = sum(1 for r in items if float(r.get("profit") or 0.0) > 0)
        loss = sum(1 for r in items if float(r.get("profit") or 0.0) < 0)
        return {
            "trade_count": len(items),
            "trade_value_usdt": round(volume, 8),
            "gross_profit_usdt": round(gross_profit, 8),
            "gross_loss_usdt": round(gross_loss, 8),
            "fees_usdt": round(fees, 8),
            "net_pnl_usdt": round(net, 8),
            "profitable_trades": profitable,
            "loss_trades": loss,
        }

    today_rows = [r for r in rows if _parse_trade_local_date(r.get("created_at")) == today]

    by_exchange = {}
    for exchange in ("Binance", "Bybit", "KuCoin"):
        ex_rows = [
            r for r in today_rows
            if str(r.get("buy_exchange", "")).lower() == exchange.lower()
            or str(r.get("sell_exchange", "")).lower() == exchange.lower()
        ]
        by_exchange[exchange] = summary_for(ex_rows)

    return {
        "today": summary_for(today_rows),
        "all_time": summary_for(rows),
        "by_exchange_today": by_exchange,
        "updated_at": datetime.now().astimezone().isoformat(),
    }
