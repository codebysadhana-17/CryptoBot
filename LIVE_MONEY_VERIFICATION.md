# Live-Money Verification

This module is a controlled verification gate around the existing real CEX arbitrage execution path.

## What it verifies

- authenticated exchange access through the existing API-key path
- real wallet balance checks performed by the live execution engine
- real BUY order submission and exchange order ID
- real BUY fill confirmation
- fresh post-BUY SELL validation
- real SELL order submission and exchange order ID
- real SELL fill confirmation
- exchange-confirmed fees and realized net P&L
- persistent verification result

## Safety defaults

The following are OFF/blocked by default:

- `LIVE_VERIFICATION_ENABLED=false`
- `LIVE_VERIFICATION_ARMED=false`
- `EMERGENCY_STOP=true`

The API also requires an explicit `confirm_live_money=true` request field and enforces `LIVE_VERIFICATION_MAX_USDT` (default 5 USDT).

## Important

Automated tests mock the final execution call only to prove the state machine. They do **not** place real orders. `VERIFIED` can only be reached in a real deployment after the actual exchange execution function returns an exchange-confirmed completed two-leg trade.
