import unittest
from unittest.mock import patch

import config
from live_verification import get_live_verification_status, run_live_verification


class LiveVerificationTests(unittest.TestCase):
    def test_defaults_are_disabled_and_unarmed(self):
        self.assertFalse(config.LIVE_VERIFICATION_ENABLED)
        self.assertFalse(config.LIVE_VERIFICATION_ARMED)
        status = get_live_verification_status()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["armed"])

    def test_explicit_confirmation_is_required(self):
        with patch.object(config, "LIVE_VERIFICATION_ENABLED", True), patch.object(config, "LIVE_VERIFICATION_ARMED", True), patch.object(config, "EMERGENCY_STOP", False):
            result = run_live_verification("Binance", "Bybit", 5, explicit_confirmation=False)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("confirmation", result["message"].lower())

    def test_amount_is_capped_before_exchange_call(self):
        with patch.object(config, "LIVE_VERIFICATION_ENABLED", True), patch.object(config, "LIVE_VERIFICATION_ARMED", True), patch.object(config, "EMERGENCY_STOP", False), patch.object(config, "LIVE_VERIFICATION_MAX_USDT", 5.0):
            result = run_live_verification("Binance", "Bybit", 5.01, explicit_confirmation=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("<= 5.00", result["message"])

    def test_success_requires_real_trade_result(self):
        fake = {
            "success": True,
            "status": "LIVE TRADE EXECUTED",
            "message": "LIVE PROFITABLE TRADE EXECUTED",
            "trade": {
                "exchange_confirmed": True,
                "buy_order_id": "B1",
                "sell_order_id": "S1",
                "profit": 0.02,
            },
        }
        with patch.object(config, "LIVE_VERIFICATION_ENABLED", True), patch.object(config, "LIVE_VERIFICATION_ARMED", True), patch.object(config, "EMERGENCY_STOP", False), patch("live_verification.execute_live_real_trade", return_value=fake):
            result = run_live_verification("Binance", "Bybit", 5, explicit_confirmation=True)
        self.assertEqual(result["verification_status"], "VERIFIED")
        self.assertTrue(result["verification_is_real"])


if __name__ == "__main__":
    unittest.main()
