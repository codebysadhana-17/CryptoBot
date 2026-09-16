import ast
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class SafetyGuardTests(unittest.TestCase):
    def test_emergency_stop_blocks_before_exchange_execution(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch.dict(os.environ, {"DATA_DIR": data_dir}, clear=False):
                import importlib
                import config
                import arbitrage
                import exchange

                importlib.reload(config)
                importlib.reload(exchange)
                importlib.reload(arbitrage)
                config.EMERGENCY_STOP = True
                config.AUTO_TRADE_ENABLED = True
                config.LIVE_TRADING_ARMED = True

                with patch.object(exchange, "execute_live_real_trade") as execute:
                    result = arbitrage.execute_real_trade({
                        "buy_exchange": "Binance",
                        "sell_exchange": "Bybit",
                        "buy_price": 100.0,
                        "sell_price": 101.0,
                        "net_profit": 1.0,
                        "net_profit_percent": 1.0,
                    })

                self.assertFalse(result["success"])
                self.assertEqual(result["skip_reason"], "Emergency stop is active")
                execute.assert_not_called()

    def test_buy_and_sell_order_sites_are_guarded(self):
        source = (ROOT / "exchange.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "execute_live_real_trade"
        )
        calls = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {
                "create_market_buy_order",
                "create_market_sell_order",
            }
        ]
        self.assertEqual(len(calls), 2)
        function_source = source[function.lineno - 1:]
        self.assertGreaterEqual(
            function_source.count("if emergency_stop_active():"),
            3,
        )
        buy_guard = function_source.index('return _emergency_stop_result("buy order")')
        buy_call = function_source.index("create_market_buy_order")
        sell_guard = function_source.index('return {\n                **_emergency_stop_result("sell order")')
        sell_call = function_source.index("create_market_sell_order")
        self.assertLess(buy_guard, buy_call)
        self.assertLess(sell_guard, sell_call)

    def test_confirmed_live_queries_exclude_backup_rows(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch.dict(os.environ, {"DATA_DIR": data_dir}, clear=False):
                import importlib
                import config
                import database

                importlib.reload(config)
                importlib.reload(database)
                database.create_database()
                database.save_trade({
                    "buy_exchange": "Binance",
                    "sell_exchange": "Bybit",
                    "buy_price": 100.0,
                    "sell_price": 101.0,
                    "fees": 0.1,
                    "profit": 0.9,
                    "buy_order_id": "confirmed-buy",
                    "sell_order_id": "confirmed-sell",
                    "mode": "LIVE",
                    "exchange_confirmed": True,
                })

                self.assertEqual(database.get_total_profit(), 0.9)
                self.assertEqual(database.get_total_trades(), 1)
                self.assertEqual(database.get_all_trades()[0]["buy_order_id"], "confirmed-buy")

    def test_backup_confirmation_flag_is_never_trusted(self):
        with tempfile.TemporaryDirectory() as data_dir:
            backup_path = Path(data_dir) / "trades_history_backup.json"
            backup_path.write_text(json.dumps([{
                "buy_exchange": "Binance",
                "sell_exchange": "Bybit",
                "buy_price": 100.0,
                "sell_price": 101.0,
                "fees": 0.1,
                "profit": 0.9,
                "buy_order_id": "fake-buy",
                "sell_order_id": "fake-sell",
                "mode": "LIVE",
                "exchange_confirmed": True,
            }]), encoding="utf-8")

            with patch.dict(os.environ, {"DATA_DIR": data_dir}, clear=False):
                import importlib
                import config
                import database

                importlib.reload(config)
                importlib.reload(database)
                database.create_database()

                conn = sqlite3.connect(config.DATABASE_NAME)
                row = conn.execute(
                    "SELECT exchange_confirmed FROM trades"
                ).fetchone()
                conn.close()

                self.assertEqual(row[0], 0)
                self.assertEqual(database.get_all_trades(), [])


if __name__ == "__main__":
    unittest.main()
