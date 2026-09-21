# Fixes Applied

This build is still **LIVE-only** and does not include paper/simulation trading.

## Execution safety fixes
- Manual execution can no longer bypass the configured profit-only threshold.
- A per-process LIVE execution lock blocks overlapping arbitrage executions.
- The SELL leg is paired to the quantity actually filled by the BUY leg.
- SELL balance is rechecked after BUY.
- Post-BUY SELL profitability now uses full executable bid depth/VWAP rather than only the first bid.
- Recovery is explicitly required when the second leg cannot be safely completed.
- Existing emergency-stop checks remain in place immediately before BUY and SELL submission.

## Dashboard state fixes
- Engine status now distinguishes emergency stop, unarmed live trading, disabled auto trading, and ready state.
- `TRADE EXECUTING` is no longer shown merely because an opportunity was detected.

## Testability
- CCXT is treated as an external runtime dependency; non-network unit tests can run without CCXT installed.
- Python compilation checks pass.
- The project test suite passes: 6/6 tests.
- No test submits an exchange order.

## Additional hardening in this build
- Dashboard opportunity analysis now applies the same USDT and percentage safety-buffer rule as final live execution, so the UI will not mark a route profitable when the executor would reject it.
- LIVE is now the database default for newly stored trade records; unconfirmed rows remain excluded from live P&L.
- Environment-based exchange secrets are preferred over credentials stored in SQLite when both exist.

## Not claimed
- No real-money order was submitted during validation.
- No profit or win-rate guarantee is made.
- Cross-process/multi-worker trading should still use a single dedicated worker/process for automatic live execution in production.
- API credentials remain a production security item and should be stored using a proper secret-management/encryption strategy.
