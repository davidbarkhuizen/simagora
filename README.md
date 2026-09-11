# simagora

Financial instrument backtesting simulator.

## Overview

The simulator replays historical daily OHLCV (open/high/low/close/volume) price data
day by day, evaluates a trading strategy after each day's close, and submits any
resulting orders to a simulated broker for execution the following day. Execution is
"realistic" in that the broker fills orders at a price between the day's high and low
rather than at an exact known price.

Per the project's original design notes (see History below), the design has 3
conceptual agents:

1. **Trader** — runs a strategy and owns an account.
2. **Broker** — receives orders from the trader, determines execution price, and
   maintains the trader's account (cash balance, margin, open/closed positions).
3. **Data provider** — supplies market data.

## Layout

```
src/simagora/
  domain/       order data model - independent of simulation mechanics
  engine/       simulation mechanics - orchestration and execution
  marketdata/   CSV-backed historical price data access
  reporting/    plotting helpers
  launcher.py   entry point (Launcher, main())
  timer.py      small perf-timing helper (mostly unused, see below)
tests/
  run_tests.py  discovers and runs every test_*.py file below
  testutil.py   shared test doubles/factories (FakeDataFeed, broker/trader
                construction helpers) and constants used across test_*.py
  test_*.py     one file per module under test, e.g. test_broker.py
```

`src/` is a standard Python "src layout": the package isn't importable straight out
of a checkout, it must be installed first (see Setup below). This is deliberate -
it's what catches packaging mistakes (a module missing from the package, a stray
import that only works by accident because of the working directory) before they
reach a real install, rather than papering over them because the interpreter happens
to be run from the repo root.

### `domain/`

- `order.py` — an order to open a new position (buy/sell, quantity, stop-loss,
  take-profit, optional expiry date).
- `closeorder.py` — an order to close a specific already-open position by id,
  independent of stop-loss/take-profit/expiry.
- `orderreceipt.py`, `position.py`, `termnotice.py` — simple data/record classes
  used to track fills, open positions, and position termination.
- `autoid.py` — `HasAutoId`, a small mixin giving each of the classes above (plus
  `Account`/`Trader` in `engine/`) an independent auto-incrementing `id`.

### `engine/`

- `msgq.py` — a minimal in-memory message queue used to pass orders/receipts between
  trader and broker.
- `account.py` — per-trader cash/margin bookkeeping and P&L on position close.
- `broker.py` — receives orders via `msgq.py` message queues, computes a fill price
  (midpoint of the day's high/low), opens/closes `Position`s, checks stop-loss/
  take-profit levels against intraday high/low, and updates account balances.
- `trader.py` — holds a strategy and an `Account`, submits orders, and drains its
  own order/close-order receipts each day (`process_receipts()`), logging a warning
  for anything that didn't succeed (e.g. insufficient cash) instead of the receipt
  being silently discarded.
- `strategy.py` — the one implemented strategy, `MovingAverageCrossoverStrategy`:
  buy/sell based on whether the closing price is above/below the 20-day moving
  average of daily highs, with fixed 0.5%/1% stop-loss/take-profit bands. On each
  new same-direction signal, it also submits `CloseOrder`s for any of its own open
  positions, in that direction, that are currently in the money.
- `simulator.py` — drives the day-by-day simulation loop between a start and end date.

### `marketdata/`

- `csvhandler.py` — parses OHLCV CSV rows into `Decimal`-typed dicts.
- `datafeed.py` — loads daily OHLCV CSV data for an instrument and exposes price
  lookups and n-day moving averages (see Data below for where it reads from).

### `reporting/`

- `plot.py` — matplotlib plotting helpers. Currently unused/orphaned: nothing in
  `engine/` or `launcher.py` calls into it - `Simulator.plot()` does its own inline
  matplotlib plotting instead. It also has a function (`gen_plot_png_for_symbol_period`)
  that references Django ORM models (`Symbol`, `DailyCandleSticks`) that don't exist
  anywhere in this repo, evidently a leftover from a different, related project.

### Top level

- `launcher.py` — `Launcher`/`main()`, the intended entry point; see Running below.
- `timer.py` — a small perf-timing helper; its one class is entirely commented out,
  so today this module only re-exports `time.perf_counter` as `clock`.

## History

This project was originally called **ARACHNAGORA**, a market simulator /
back-tester, (C) 2010 david barkhuizen. What follows was folded in from
separate design-note `.txt` files that used to sit at the repo root
(`initial_spec.txt`, `strategy.txt`, `user_notes.txt` — removed now that
their content lives here, so it isn't duplicated in two places).

- **Original design spec.** Daily OHLCV price resolution; triggers evaluated
  after the day's close, with resulting orders submitted for execution the
  *following* day; realistic execution — the broker fills at some price
  between the day's high and low. All still true today — see Overview above.
  The original spec also had an empty "REFERENCE PRICE CALC" heading with no
  content ever written under it.
- **Strategy-vs-model deviation (unimplemented idea).** On an ongoing basis,
  compare the actual strategy's performance to a model, to see the deviation
  between the two.
- `user_notes.txt` was always empty — nothing to carry over.

## Position closing

A position closes the same day one of the following happens, in this order:

1. **Take-profit** — intraday high/low reaches the order's `take_profit` level.
2. **Stop-loss** — intraday high/low reaches the order's `stop_loss` level.
3. **Expiry** — `Order.expiry_date` is reached; settles at that day's closing price.
4. **Explicit close** — a `CloseOrder` referencing the position's id is submitted;
   settles at that day's midpoint execution price, same as opening a position. Only
   the position's own trader may close it this way — a `CloseOrder` from another
   trader is rejected. `strategy.py` submits one of these automatically for each of
   its own open positions that is in the money whenever a new same-direction signal
   fires, rather than leaving them to run until stop-loss/take-profit/expiry.

## Setup

The package needs to be installed (editable is fine) before it can be imported,
since `src/` isn't on `sys.path` by default:

```
pip install -e .
```

If you'd rather not install anything, point `PYTHONPATH` at `src/` instead for any
command below, e.g. `PYTHONPATH=src python3 tests/run_tests.py -v`.

## Testing

```
python3 tests/run_tests.py -v
```

Most of the suite drives `Broker`/`Trader`/`Strategy`/`Account` directly against a
`FakeDataFeed` test double defined in `tests/testutil.py`, so it needs no external
data or CSV files. A couple of tests (in `test_csvhandler.py`) do exercise
`csvhandler.py` directly against
real (temporary, self-contained) CSV files — `datafeed.py`/`DataFeed` itself is
still never touched, so no pre-existing data root is required either way.

## Data

`DataFeed` (`marketdata/datafeed.py`) reads daily OHLCV data from
`<instrument>.csv` under a data root directory, resolved in this order:

1. the `data_root` argument passed to `DataFeed(instrument, data_root=...)`,
2. the `SIMAGORA_DATA_ROOT` environment variable,
3. `data/csv/` under the current working directory, by default.

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
from simagora.launcher import Launcher

Launcher().go({
  'start_date': date(2008, 1, 1),
  'end_date':   date(2008, 6, 30),
  'ins':        'equity_index/^GSPC',  # resolved under the data root, see Data above
  'strat':      ['movavg'],  # a list - one Trader per element; the string itself is
                              # unused (Trader always loads MovingAverageCrossoverStrategy)
  'open_bal':   Decimal('10000.00'),
})
```

Run from the repo root (or wherever you want `data/`, `log/`, and `plot/` resolved
relative to) after completing Setup above. `go()` writes a run log to `log/` and a
result plot (via matplotlib) to `plot/` — both directories are checked into the repo
(empty, via `.gitkeep`) so this works out of the box; only a populated data root (see
Data above) is required. The snippet above was run end-to-end against a synthetic CSV
fixture, from both an editable install and a `PYTHONPATH=src` invocation, to confirm
it works before writing this section.
