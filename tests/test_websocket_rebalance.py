import unittest
import config
from market_stream import PublicBBOStream
from inventory_manager import rebalance_status


class WebSocketRebalanceTests(unittest.TestCase):
    def test_websocket_is_configurable(self):
        self.assertTrue(hasattr(config, "WEBSOCKET_ENABLED"))
        self.assertTrue(hasattr(PublicBBOStream, "snapshot"))

    def test_rebalance_defaults_are_disabled_and_unarmed(self):
        self.assertFalse(config.AUTO_REBALANCE_ENABLED)
        self.assertFalse(config.REBALANCE_ARMED)
        status = rebalance_status()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["armed"])


if __name__ == "__main__":
    unittest.main()
