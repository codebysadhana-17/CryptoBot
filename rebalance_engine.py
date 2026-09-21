"""Guarded cross-exchange inventory rebalancing."""
from typing import Dict, Any
import config
from inventory_manager import execute_guarded_withdraw


def _address_allowed(address: str) -> bool:
    allowed = getattr(config, "REBALANCE_ALLOWED_ADDRESSES", [])
    if not getattr(config, "REBALANCE_REQUIRE_WHITELIST", True):
        return True
    return bool(address) and address in allowed


def guarded_rebalance(source_exchange, destination_exchange, amount, address, tag="", network="") -> Dict[str, Any]:
    if not getattr(config, "AUTO_REBALANCE_ENABLED", False):
        return {"success": False, "status": "DISABLED", "message": "Auto-rebalance is disabled."}
    if not getattr(config, "REBALANCE_ARMED", False):
        return {"success": False, "status": "NOT_ARMED", "message": "Auto-rebalance is not armed."}
    if getattr(config, "EMERGENCY_STOP", True):
        return {"success": False, "status": "EMERGENCY_STOP", "message": "Emergency stop is active."}
    if not source_exchange or source_exchange == destination_exchange:
        return {"success": False, "status": "INVALID_ROUTE", "message": "Source and destination exchanges must differ."}
    if destination_exchange != getattr(config, "REBALANCE_DESTINATION_EXCHANGE", ""):
        return {"success": False, "status": "INVALID_DESTINATION", "message": "Destination exchange does not match configured destination."}
    if not _address_allowed(address):
        return {"success": False, "status": "ADDRESS_NOT_WHITELISTED", "message": "Destination address is not whitelisted."}
    if float(amount) <= 0 or float(amount) > float(getattr(config, "REBALANCE_MAX_ASSET_AMOUNT", 0.02)):
        return {"success": False, "status": "LIMIT", "message": "Amount exceeds the configured asset transfer cap."}

    # The exchange object must be supplied by the caller after authenticated
    # connection checks. This function never discovers arbitrary addresses.
    return {"success": False, "status": "READY_FOR_EXPLICIT_WITHDRAW",
            "message": "Route and safety checks passed; explicit exchange withdrawal call required."}


def rebalance_policy_snapshot() -> Dict[str, Any]:
    return {
        "enabled": bool(getattr(config, "AUTO_REBALANCE_ENABLED", False)),
        "armed": bool(getattr(config, "REBALANCE_ARMED", False)),
        "asset": getattr(config, "REBALANCE_ASSET", "ETH"),
        "max_asset_amount": float(getattr(config, "REBALANCE_MAX_ASSET_AMOUNT", 0.02)),
        "destination_exchange": getattr(config, "REBALANCE_DESTINATION_EXCHANGE", ""),
        "whitelist_required": bool(getattr(config, "REBALANCE_REQUIRE_WHITELIST", True)),
        "whitelist_count": len(getattr(config, "REBALANCE_ALLOWED_ADDRESSES", [])),
    }
