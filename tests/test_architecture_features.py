import unittest

import config
from exchange import _consume_asks_for_quote, _consume_bids_for_base


class ArchitectureFeatureTests(unittest.TestCase):
    def test_live_only(self):
        self.assertEqual(config.TRADING_MODE, "LIVE")

    def test_supported_exchanges_include_kucoin(self):
        self.assertEqual(set(config.SUPPORTED_EXCHANGES), {"Binance", "Bybit", "KuCoin"})

    def test_depth_vwap_helpers(self):
        bought = _consume_asks_for_quote([[100, 0.02], [101, 0.02]], 3)
        self.assertIsNotNone(bought)
        base, spent, vwap = bought
        self.assertAlmostEqual(spent, 3.0)
        sold = _consume_bids_for_base([[102, 0.01], [101, 0.02]], base)
        self.assertIsNotNone(sold)
        self.assertGreater(sold[1], 0)
        self.assertGreater(vwap, 0)

    def test_safety_defaults_block_live_orders(self):
        self.assertFalse(config.LIVE_TRADING_ARMED)
        self.assertFalse(config.AUTO_TRADE_ENABLED)
        self.assertTrue(config.EMERGENCY_STOP)

    def test_stale_quote_guard_configured(self):
        self.assertGreater(config.MAX_QUOTE_AGE_MS, 0)
        self.assertGreaterEqual(config.ORDERBOOK_LIMIT, 20)


if __name__ == "__main__":
    unittest.main()
