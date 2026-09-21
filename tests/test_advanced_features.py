import asyncio
import unittest
import config
from async_execution import AsyncExecutionEngine
from dex_flashloan import build_plan, execute_atomic_flashloan
from rebalance_engine import rebalance_policy_snapshot


class AdvancedFeatureTests(unittest.TestCase):
    def test_async_engine_exists_and_is_safe_by_default(self):
        self.assertTrue(hasattr(AsyncExecutionEngine, "fetch_orderbooks"))
        self.assertFalse(config.ASYNC_EXECUTION_ENABLED)

    def test_flashloan_is_disabled_and_never_submits(self):
        self.assertFalse(config.DEX_FLASHLOAN_ENABLED)
        result = execute_atomic_flashloan()
        self.assertEqual(result["status"], "NOT_SUBMITTED")

    def test_flashloan_plan_requires_receiver(self):
        result = build_plan("WETH", 1, "DEX-A", "DEX-B", 2, 0.50)
        self.assertFalse(result["valid"])
        self.assertTrue(any("receiver" in e.lower() for e in result["errors"]))

    def test_rebalance_has_asset_cap_and_whitelist(self):
        snap = rebalance_policy_snapshot()
        self.assertIn("max_asset_amount", snap)
        self.assertTrue(snap["whitelist_required"])


if __name__ == "__main__":
    unittest.main()
