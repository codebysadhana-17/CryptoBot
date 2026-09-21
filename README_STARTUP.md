# CryptoBot - ETH/USDT Cross-Exchange Arbitrage

This project is a standalone arbitrage bot. It is not a copy-trading bot.

## Important execution model

The bot is **pre-funded cross-exchange arbitrage**:
- BUY ETH/USDT on the cheaper exchange.
- SELL ETH/USDT on the more expensive exchange.
- ETH must already be available on the selling exchange.
- The bot does not transfer ETH between exchanges during the trade.

## What was fixed

1. Arbitrage discovery now uses executable order-book ASK for BUY and BID for SELL instead of ticker last price.
2. A fresh order-book quote is fetched again immediately before live order submission.
3. Fees and configured slippage are included in the profitability gate.
4. Manual live trading is independent of the Auto Trade switch, but still requires the live arm and all safety checks.
5. Partial fills are never treated as a successful full arbitrage.
6. Tests are discoverable through `python -m unittest discover -v`.
7. Production debug mode defaults to false.

## Local setup

Python 3.11 is recommended (the included Dockerfile uses Python 3.11).

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
# source .venv/bin/activate

python -m pip install -r requirements.txt
python -m unittest discover -v
python app.py
```

Open `http://127.0.0.1:5000`.

## Exchange API permissions

Create separate spot API keys for Binance, Bybit and/or KuCoin.

Required permissions:
- Read / balance
- Spot trading

Do **not** grant withdrawal permission.

Store credentials through environment variables in production when possible. Never commit `.env`, API secrets, or database files.

## Live-trading activation

The safe defaults are intentionally OFF:

```text
AUTO_TRADE_ENABLED=false
LIVE_TRADING_ARMED=false
EMERGENCY_STOP=true
```

Before enabling live auto-trading:

1. Test each exchange API connection.
2. Confirm the symbol is available as spot ETH/USDT on both venues.
3. Confirm the BUY exchange has enough free USDT and the SELL exchange already has enough free ETH.
4. Confirm the SELL exchange already has enough free ETH.
5. Confirm the displayed opportunity uses BUY ASK and SELL BID.
6. Test one small manual live trade only if you accept the market risk.
7. Verify both exchange order IDs and filled quantities.
8. Verify the recorded realized P&L against exchange statements.
9. Only then arm auto-trading.

No software can guarantee profitable or successful execution: prices, liquidity, fees, rate limits, exchange outages, partial fills and network latency can change the outcome.

## Deployment

For the current single-process background trader, keep one Gunicorn worker:

```bash
gunicorn --workers 1 --threads 4 app:app
```

Do not scale this web process horizontally while auto-trading is enabled, because multiple workers would each start an auto-trader loop.

For a real production startup, move the auto-trader into a dedicated worker/service and keep the Flask web process separate.

## Profit-only rule

The bot has no paper/simulated execution path. A live order is submitted only when a fresh executable BUY ASK vs SELL BID calculation remains above the configured minimum net profit after estimated fees, configured slippage, and a safety buffer. It also rechecks the sell price after the BUY before submitting the SELL.

This is a **profit gate, not a profit guarantee**. Once the first real order is filled, market movement, liquidity, exchange outages or partial fills can make the second leg unprofitable. Confirmed completed trades are retained in the audit/risk history even if realized P&L is negative.


## Calculation and KuCoin fixes
- Trading spread is executable sell BID/VWAP minus buy ASK/VWAP, not last-price max/min.
- Order-book depth is consumed for the configured trade notional before estimating profit.
- KuCoin public market data has a REST Level-1 fallback, so public quotes do not require API keys.
- A trade is submitted only when the depth-based estimated net profit clears the configured USDT and percentage thresholds plus safety buffer.
- Real execution remains subject to fills, latency, fees and market movement; no software can guarantee a realized profit.

## Controlled Live-Money Verification

The project includes a guarded `/api/live-verification` flow. It does **not** simulate a successful trade: `VERIFIED` is recorded only when the existing LIVE execution path completes a real two-leg BUY+SELL and the exchange confirmations report the completed orders.

Defaults:
- `LIVE_VERIFICATION_ENABLED=false`
- `LIVE_VERIFICATION_ARMED=false`
- `LIVE_VERIFICATION_MAX_USDT=5.0`
- `EMERGENCY_STOP=true`

The run endpoint additionally requires `confirm_live_money=true`. The verification amount is capped before exchange execution. No withdrawal permission is required by this verification module.

Example request (only after intentionally enabling and arming the feature):

```json
POST /api/live-verification/run
{
  "confirm_live_money": true,
  "buy_exchange": "Binance",
  "sell_exchange": "Bybit",
  "trade_amount": 5
}
```

A successful response is only marked `VERIFIED` after the real execution function returns an exchange-confirmed completed trade. No real-money transaction was submitted during the automated test suite.
