[← README](../README.md)

# Overview

The simulator replays historical daily OHLCV (open/high/low/close/volume) price data
day by day, evaluates a trading strategy after each day's close, and submits any
resulting orders to a simulated broker for execution the following day. Execution is
"realistic" in that the broker fills orders at a price between the day's high and low
rather than at an exact known price.

The design has 3 conceptual agents:

1. **Trader** — runs a strategy and owns an account.
2. **Broker** — receives orders from the trader, determines execution price, and
   maintains the trader's account (cash balance, margin, open/closed positions).
3. **Data provider** — supplies market data.
