"""Native asyncio execution adapter.

This module uses CCXT's async_support clients. It is an optional execution
path and is disabled by default. It does not bypass the normal profit/risk
gates; callers must perform those checks before submitting an order.
"""
import asyncio
from typing import Dict, Any

import config

try:
    import ccxt.async_support as ccxt_async
except Exception:  # pragma: no cover
    ccxt_async = None

from database import get_api_key


class AsyncExecutionEngine:
    """Concurrent authenticated exchange operations with explicit close()."""

    def __init__(self):
        self.clients = {}

    def _client(self, name):
        if ccxt_async is None:
            raise RuntimeError("ccxt.async_support is unavailable")
        info = get_api_key(name)
        if not info or not info.get("api_key") or not info.get("api_secret"):
            raise RuntimeError(f"No API credentials configured for {name}")
        opts = {
            "apiKey": info["api_key"],
            "secret": info["api_secret"],
            "enableRateLimit": True,
            "timeout": 15000,
        }
        if name.lower() == "kucoin":
            if not info.get("api_passphrase"):
                raise RuntimeError("KuCoin API passphrase is required")
            opts["password"] = info["api_passphrase"]
            opts["options"] = {"defaultType": "spot"}
        elif name.lower() == "bybit":
            opts["options"] = {"defaultType": "spot", "adjustForTimeDifference": True}
        else:
            opts["options"] = {"defaultType": "spot", "adjustForTimeDifference": True}
        cls = getattr(ccxt_async, name.lower(), None)
        if cls is None:
            raise RuntimeError(f"Unsupported exchange: {name}")
        self.clients[name] = cls(opts)
        return self.clients[name]

    async def fetch_orderbooks(self, names=None, symbol=None):
        names = names or config.SUPPORTED_EXCHANGES
        symbol = symbol or config.SYMBOL
        clients = [self._client(n) for n in names]
        try:
            results = await asyncio.gather(
                *(c.fetch_order_book(symbol, limit=config.ORDERBOOK_LIMIT) for c in clients),
                return_exceptions=True,
            )
            return {
                n: r for n, r in zip(names, results)
                if not isinstance(r, Exception)
            }
        finally:
            await self.close()

    async def create_market_order(self, exchange_name, symbol, side, amount):
        if not config.ASYNC_EXECUTION_ENABLED:
            raise RuntimeError("Native async execution is disabled.")
        client = self._client(exchange_name)
        try:
            # No automatic call site enables this method. The caller must
            # explicitly opt in after all existing profit/risk checks.
            return await client.create_order(symbol, "market", side, amount)
        finally:
            await self.close()

    async def close(self):
        clients = list(self.clients.values())
        self.clients.clear()
        if clients:
            await asyncio.gather(
                *(c.close() for c in clients),
                return_exceptions=True,
            )


async def concurrent_health_check(names=None) -> Dict[str, Any]:
    """Concurrent public/authenticated connectivity check without orders."""
    names = names or config.SUPPORTED_EXCHANGES
    engine = AsyncExecutionEngine()
    try:
        clients = [engine._client(n) for n in names]
        results = await asyncio.gather(
            *(c.fetch_ticker(config.SYMBOL) for c in clients),
            return_exceptions=True,
        )
        return {
            n: {"ok": not isinstance(r, Exception),
                "error": None if not isinstance(r, Exception) else str(r)}
            for n, r in zip(names, results)
        }
    finally:
        await engine.close()
