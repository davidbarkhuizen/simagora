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
- `strategy.py` — three strategies, all sharing `BaseStrategy` for trader/datafeed
  wiring, order submission, and `log_self()`. Selected by name (see Strategies below)
  via `STRATEGY_REGISTRY`/`resolve_strategy_class()`, which `Trader.load_strategy()`
  calls with the `strategy_name` it was constructed with.
- `simulator.py` — drives the day-by-day simulation loop between a start and end date.

### `marketdata/`

- `csvhandler.py` — parses OHLCV CSV rows into `Decimal`-typed dicts.
- `datafeed.py` — loads daily OHLCV CSV data for an instrument and exposes price
  lookups, n-day moving averages, n-day highs/lows (used for breakout signals -
  these exclude the given date itself, since a value is always part of its own
  running extreme), and n-day standard deviation (used for Bollinger-Band-style
  bands). See Data below for where it reads from.
- `universe.py` — `Universe`, a multi-instrument sibling of `DataFeed`: one
  `DataFeed` per instrument, dispatched by the `instrument` argument every method
  above already accepts but a plain `DataFeed` ignores (it only ever tracks one).
  Exposes the identical method set, so it's a drop-in replacement anywhere a
  "datafeed" is expected. See Multi-instrument support below.

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

## Strategies

Selected by the `strat` list passed to `Launcher()`/`Simulator()` (see Running
below) — each element is a registry name, looked up in `strategy.STRATEGY_REGISTRY`:

- **`'movavg'`** — `MovingAverageCrossoverStrategy`. Buy/sell based on whether the
  closing price is above/below the 20-day moving average of daily highs, with fixed
  0.5%/1% stop-loss/take-profit bands. On each new same-direction signal, it also
  submits `CloseOrder`s for any of its own open positions, in that direction, that
  are currently in the money (see Position closing below).
- **`'trend'`** — `TrendFollowingStrategy`. A Donchian-channel breakout: buy when
  the close breaks above the high of the preceding 20 days, sell when it breaks
  below their low. Stop-loss sits at the shorter 10-day low/high (the classic
  Turtle-style dual channel); there is deliberately no take-profit (`Order`'s
  `take_profit` can be `None` — `Broker.profit_taken_on_position` treats that as
  "never triggers"), since trend-following aims to let a winning position run until
  it's stopped out or the trend reverses. A fresh breakout also closes any of the
  trader's own open positions in the *opposite* direction.
- **`'meanreversion'`** — `MeanReversionStrategy`. Bollinger-Band mean reversion:
  buy when the close drops 2 standard deviations below its own 20-day moving
  average (oversold), sell when it rises the same distance above it (overbought),
  each with fixed 1%/2% stop-loss/take-profit bands. No position-management beyond
  that — a reversion trade is meant to be quick.

An unrecognized name raises `ValueError` rather than silently falling back to a
default, so a typo doesn't quietly run the wrong strategy; `None` (what every
`Trader`-constructing test in this repo passes, since they don't care which
strategy loads) resolves to `'movavg'`.

All three strategies above are single-instrument (`BaseStrategy` reads
`trader.instrument`). No multi-instrument strategy is implemented yet — see
Multi-instrument support below for the plumbing that's in place for one, and
what's still needed.

## Multi-instrument support

`Broker`/`Account`/`Position`/`Order` were already instrument-aware everywhere it
mattered — every relevant call already threads `order.ins` through
(`Broker.calc_execution_price(ins, ...)`, `Account.tally_individual_open_positions`
keyed off `order.ins`, etc.) — so multi-instrument support turned out to need no
changes there at all. `DataFeed` was the actual bottleneck: constructed for exactly
one instrument, with every method silently ignoring the `instrument` argument it
was handed.

- `Simulator`/`Trader` both take an optional `universe` argument (a list of
  instruments, which must include `instrument`) alongside the existing single
  `instrument`. It's fully additive: `universe=None` (the default, and what every
  existing caller - `launcher.py`, every test - passes) reproduces today's behavior
  exactly, one single-instrument `DataFeed`. Given a `universe`, `Simulator` builds
  a `Universe` instead and every `Trader` gets `self.universe` for a
  multi-instrument strategy to trade across; `instrument` remains the "primary"
  instrument `Simulator.plot()` charts either way, since that's inherently
  single-instrument-shaped.
- `Launcher`'s `p` dict accepts an optional `'universe'` key, threaded straight
  through to `Simulator`.
- **Calendar mismatches are handled, not just assumed away.**
  `Universe.date_is_trading_day()` is a *union* across the whole universe - true if
  *any* tracked instrument trades that date - so a date can easily be valid for one
  instrument and not another (different exchange holidays, different asset
  classes). Three places would otherwise crash on the resulting `None` price
  lookup, so all three now degrade gracefully instead:
  - `Trader.execute_strategy()` skips calling into the strategy entirely on a day
    the trader's own instrument has no data (checked directly - no way to ask a
    `Universe` "is it a trading day for *this* instrument" without it).
  - `Broker.execute_orders_to_open`/`execute_orders_to_close` reject with a new
    `'instrument_not_trading'` receipt status (same pattern as the existing
    `'gapped_through_stop_loss'`/`'insufficient_cash_bal'`) instead of crashing on
    `calc_execution_price` returning `None`.
  - `Broker.manage_open_positions` simply leaves a position alone for the day if
    its instrument has no data, rather than checking take-profit/stop-loss/expiry
    against a missing high/low/close.

What's still needed before an actual multi-instrument strategy can be written: a
way to compute a return over an arbitrary lookback (none of `DataFeed`'s `n_day_*`
methods answer "what was the price N days ago" - they're all window aggregates),
and a `MultiInstrumentStrategy` base analogous to the existing single-instrument
one, reading `trader.universe` instead of `trader.instrument`.

## Position closing

A position closes the same day one of the following happens, in this order:

1. **Take-profit** — intraday high/low reaches the order's `take_profit` level.
   Never triggers if `take_profit` is `None` (`TrendFollowingStrategy`'s positions).
2. **Stop-loss** — intraday high/low reaches the order's `stop_loss` level.
3. **Expiry** — `Order.expiry_date` is reached; settles at that day's closing price.
4. **Explicit close** — a `CloseOrder` referencing the position's id is submitted;
   settles at that day's midpoint execution price, same as opening a position. Only
   the position's own trader may close it this way — a `CloseOrder` from another
   trader is rejected. `MovingAverageCrossoverStrategy` submits one of these
   automatically for each of its own open positions that is in the money whenever a
   new same-direction signal fires; `TrendFollowingStrategy` submits one for each of
   its own open positions in the *opposite* direction whenever a fresh breakout
   fires. Either way this happens rather than leaving the position to run until
   stop-loss/take-profit/expiry.

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
data or CSV files. A couple of tests (in `test_csvhandler.py` and `test_datafeed.py`)
do exercise `csvhandler.py`/the real `DataFeed` directly against real (temporary,
self-contained) CSV files — no pre-existing data root is required either way, since
those tests point `DataFeed` at their own fixture via its `data_root` argument.

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
  'strat':      ['movavg'],  # a list - one Trader per element; each name is looked
                              # up in strategy.STRATEGY_REGISTRY (see Strategies above)
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
