"""DEX flashloan/atomic-arbitrage adapter.

A real flashloan is not a generic CCXT operation. It requires a deployed
receiver contract, chain/router configuration, gas estimation, transaction
simulation, and a contract that atomically repays the loan. This module
provides the safety/validation layer and a transaction-plan object, while
keeping actual on-chain submission disabled unless explicitly configured.
"""
from dataclasses import dataclass, asdict
from typing import Dict, Any
import config


@dataclass
class FlashloanPlan:
    provider: str
    chain: str
    asset: str
    amount: float
    buy_dex: str
    sell_dex: str
    receiver: str
    min_profit_usdt: float
    gas_budget_usdt: float
    slippage_pct: float

    def as_dict(self):
        return asdict(self)


def validate_plan(plan: FlashloanPlan) -> Dict[str, Any]:
    errors = []
    if not config.DEX_FLASHLOAN_ENABLED:
        errors.append("DEX flashloan execution is disabled.")
    if not plan.receiver:
        errors.append("Flashloan receiver contract is not configured.")
    if plan.amount <= 0:
        errors.append("Flashloan amount must be positive.")
    if plan.buy_dex == plan.sell_dex:
        errors.append("Buy and sell DEX must be different.")
    if plan.min_profit_usdt <= plan.gas_budget_usdt:
        errors.append("Minimum profit must exceed the gas budget.")
    if plan.slippage_pct < 0:
        errors.append("Slippage cannot be negative.")
    return {"valid": not errors, "errors": errors}


def build_plan(asset, amount, buy_dex, sell_dex, expected_profit_usdt,
               gas_budget_usdt, slippage_pct=0.20):
    plan = FlashloanPlan(
        provider=config.DEX_FLASHLOAN_PROVIDER,
        chain=config.DEX_FLASHLOAN_CHAIN,
        asset=asset,
        amount=float(amount),
        buy_dex=buy_dex,
        sell_dex=sell_dex,
        receiver=config.DEX_FLASHLOAN_RECEIVER,
        min_profit_usdt=float(expected_profit_usdt),
        gas_budget_usdt=float(gas_budget_usdt),
        slippage_pct=float(slippage_pct),
    )
    return {"plan": plan.as_dict(), **validate_plan(plan)}


def execute_atomic_flashloan(*args, **kwargs):
    """Intentionally refuses to submit an on-chain transaction.

    The missing receiver-contract ABI/address and chain-specific execution
    details must be supplied and independently audited before this can be
    connected to real funds.
    """
    return {
        "success": False,
        "status": "NOT_SUBMITTED",
        "message": (
            "Flashloan execution adapter is not connected to a deployed "
            "receiver contract; no on-chain transaction was submitted."
        ),
    }
