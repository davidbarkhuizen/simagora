# simagora

Financial instrument backtesting simulator.

## Overview

The simulator replays historical daily OHLCV (open/high/low/close/volume) price data
day by day, evaluates a trading strategy after each day's close, and submits any
resulting orders to a simulated broker for execution the following day. Execution is
"realistic" in that the broker fills orders at a price between the day's high and low
rather than at an exact known price.

Per `initial_spec.txt`, the design has 3 conceptual agents:

1. **Trader** — runs a strategy and owns an account.
2. **Broker** — receives orders from the trader, determines execution price, and
   maintains the trader's account (cash balance, margin, open/closed positions).
3. **Data provider** — supplies market data.

## Architecture

- `datafeed.py` — loads daily OHLCV CSV data (via `csvhandler.py`) for an instrument
  and exposes price lookups and n-day moving averages.
- `trader.py` — holds a `Strategy` and an `Account`, and submits orders.
- `broker.py` — receives orders via `msgq.py` message queues, computes a fill price
  (midpoint of the day's high/low), opens/closes `Position`s, checks stop-loss/
  take-profit levels against intraday high/low, and updates account balances.
- `strategy.py` — the one implemented strategy: buy/sell based on whether the closing
  price is above/below the 20-day moving average of daily highs, with fixed 0.5%/1%
  stop-loss/take-profit bands. On each new same-direction signal, it also submits
  `CloseOrder`s for any of its own open positions, in that direction, that are
  currently in the money.
- `simulator.py` / `launcher.py` — drive the day-by-day simulation loop between a
  start and end date, then plot results with matplotlib (`plot.py`).
- `order.py` — an order to open a new position (buy/sell, quantity, stop-loss,
  take-profit, optional expiry date).
- `closeorder.py` — an order to close a specific already-open position by id,
  independent of stop-loss/take-profit/expiry.
- `orderreceipt.py`, `position.py`, `termnotice.py` — simple data/record classes
  used to track fills, open positions, and position termination.
- `account.py` — per-trader cash/margin bookkeeping and P&L on position close.
- `msgq.py` — a minimal in-memory message queue used to pass orders/receipts between
  trader and broker.
- `run_tests.py` — the test suite (see Testing below); includes a `FakeDataFeed`
  test double so it runs without any CSV data.
- `arch.py` — a personal archiving script that shells out to `rar` to zip the source
  into a parent directory.

## Notes and design docs

- `initial_spec.txt` — original design spec for reference price calculation and the
  3-agent architecture.
- `strategy.txt` — notes on an unimplemented idea: continuously compare a live
  strategy's performance to a model, pause trading during a losing streak, and resume
  once the model starts making money again.
- `user_notes.txt` — currently empty.

## Position closing

A position closes the same day one of the following happens, in this order:

1. **Take-profit** — intraday high/low reaches the order's `take_profit` level.
2. **Stop-loss** — intraday high/low reaches the order's `stop_loss` level.
3. **Expiry** — `Order.expiry_date` is reached; settles at that day's closing price.
4. **Explicit close** — a `CloseOrder` referencing the position's id is submitted;
   settles at that day's midpoint execution price, same as opening a position.
   `strategy.py` submits one of these automatically for each of its own open
   positions that is in the money whenever a new same-direction signal fires,
   rather than leaving them to run until stop-loss/take-profit/expiry.

## Testing

```
python3 run_tests.py -v
```

The suite doesn't touch `datafeed.py`/`csvhandler.py` or any CSV file — it drives
`Broker`/`Trader`/`Strategy`/`Account` directly against a `FakeDataFeed` test double
defined in `run_tests.py`, so it runs with no external data.

## Data

`DataFeed` (`datafeed.py`) reads daily OHLCV data from
`<instrument>.csv` under a data root directory, resolved in this order:

1. the `data_root` argument passed to `DataFeed(instrument, data_root=...)`,
2. the `SIMAGORA_DATA_ROOT` environment variable,
3. a `data/csv/` directory alongside the source files, by default.

No sample data ships with this repository, so a data root must be populated
(or pointed at via `SIMAGORA_DATA_ROOT`) before the simulator can run. Each CSV is
expected to have the columns `date, open, high, low, close, volume, adj_close`
(see `csvhandler.py`).

## Running

`launcher.py`'s `main()` shows the intended usage: construct a `Launcher`, call
`go()` with a parameter dict specifying instrument, strategy, date range, and
opening balance:

```python
from decimal import Decimal
from datetime import date
from launcher import Launcher

Launcher().go({
  'start_date': date(2008, 1, 1),
  'end_date':   date(2008, 6, 30),
  'ins':        'equity_index/^GSPC',  # resolved under the data root, see Data above
  'strat':      'movavg',              # unused - Trader always loads strategy.Strategy
  'open_bal':   Decimal('10000.00'),
})
```

`go()` writes a run log to `log/` and a result plot (via matplotlib) to `plot/` —
both directories are checked into the repo (empty, via `.gitkeep`) so this works
out of the box; only a populated data root (see Data above) is required. The
snippet above was run end-to-end against a synthetic CSV fixture to confirm it
works before writing this section.
