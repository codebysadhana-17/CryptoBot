"""Inventory health and guarded cross-exchange rebalancing helpers.

Rebalancing uses exchange withdrawals only when BOTH AUTO_REBALANCE_ENABLED
and REBALANCE_ARMED are explicitly enabled and a destination address/network
are configured. It is disabled by default.
"""
from typing import Dict
import config


def build_inventory_report(balances: Dict) -> Dict:
    report = {}
    for exchange, data in (balances or {}).items():
        if not isinstance(data, dict):
            continue
        report[exchange] = {
            "connected": bool(data.get("connected")),
            "usdt_free": float(data.get("usdt", 0.0) or 0.0),
            "eth_free": float(data.get("eth", 0.0) or 0.0),
            "error": data.get("error"),
        }
    return {"exchanges": report}


def rebalance_status() -> dict:
    return {
        "enabled": bool(getattr(config, "AUTO_REBALANCE_ENABLED", False)),
        "armed": bool(getattr(config, "REBALANCE_ARMED", False)),
        "asset": getattr(config, "REBALANCE_ASSET", "ETH"),
        "network_configured": bool(getattr(config, "REBALANCE_NETWORK", "")),
        "destination_exchange": getattr(config, "REBALANCE_DESTINATION_EXCHANGE", ""),
        "destination_configured": bool(getattr(config, "REBALANCE_DESTINATION_ADDRESS", "")),
        "max_amount_usdt": float(getattr(config, "REBALANCE_MAX_ASSET_AMOUNT", 0.02)),
    }


def execute_guarded_withdraw(exchange, amount: float, address: str, tag: str = "", network: str = "") -> dict:
    """Execute one explicitly armed withdrawal through a CCXT exchange.

    This is intentionally not called by the arbitrage trade loop automatically.
    A higher-level rebalancing policy must first decide the exact source,
    destination, amount and network.
    """
    if not getattr(config, "AUTO_REBALANCE_ENABLED", False) or not getattr(config, "REBALANCE_ARMED", False):
        return {"success": False, "message": "Automatic rebalancing is not enabled and armed."}
    if getattr(config, "EMERGENCY_STOP", True):
        return {"success": False, "message": "Emergency stop is active."}
    amount = float(amount)
    if amount <= 0:
        return {"success": False, "message": "Withdrawal amount must be positive."}
    if amount > float(getattr(config, "REBALANCE_MAX_ASSET_AMOUNT", 0.02)):
        return {"success": False, "message": "Withdrawal exceeds configured rebalancing cap."}
    if not address or not network:
        return {"success": False, "message": "Destination address and network are required."}

    params = {}
    if tag:
        params["tag"] = tag
    if network:
        params["network"] = network
    try:
        result = exchange.withdraw(
            getattr(config, "REBALANCE_ASSET", "ETH"),
            amount,
            address,
            tag or None,
            params,
        )
        return {"success": True, "withdrawal": result}
    except Exception as exc:
        return {"success": False, "message": str(exc)}
