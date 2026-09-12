[← README](../README.md)

# Layout

```
src/simagora/
  domain/       order data model - independent of simulation mechanics
  engine/       simulation mechanics - orchestration and execution
  marketdata/   CSV-backed historical price data access
  launcher.py   entry point (Launcher, main())
tests/
  run_tests.py  discovers and runs every test_*.py file below
  testutil.py   shared test doubles/factories (FakeDataFeed, broker/trader
                construction helpers) and constants used across test_*.py
  test_*.py     one file per module under test, e.g. test_broker.py
```

`src/` is a standard Python "src layout": the package isn't importable straight out
of a checkout, it must be installed first (see [Setup](setup.md)). This is deliberate -
it's what catches packaging mistakes (a module missing from the package, a stray
import that only works by accident because of the working directory) before they
reach a real install, rather than papering over them because the interpreter happens
to be run from the repo root.

## `domain/`

- `order.py` — an order to open a new position (buy/sell, quantity, stop-loss,
  take-profit, optional expiry date).
- `closeorder.py` — an order to close a specific already-open position by id,
  independent of stop-loss/take-profit/expiry.
- `orderreceipt.py`, `position.py`, `termnotice.py` — simple data/record classes
  used to track fills, open positions, and position termination.
- `autoid.py` — `HasAutoId`, a small mixin giving each of the classes above (plus
  `Account`/`Trader` in `engine/`) an independent auto-incrementing `id`.

## `engine/`

- `msgq.py` — a minimal in-memory message queue used to pass orders/receipts between
  trader and broker.
- `account.py` — per-trader cash/margin bookkeeping and P&L on position close.
  `take_profit()` and `close_at_price()` are both just closing a position at some
  price and banking the resulting pnl - the only difference is which price and
  what `TermNotice` reason - so both delegate to a shared private
  `_close_position(date, pos, price, buysell, reason)`.
- `broker.py` — receives orders via `msgq.py` message queues, computes a fill price
  (midpoint of the day's high/low), opens/closes `Position`s, checks stop-loss/
  take-profit levels against intraday high/low, and updates account balances.
- `trader.py` — holds a strategy and an `Account`, submits orders, and drains its
  own order/close-order receipts each day (`process_receipts()`), logging a warning
  for anything that didn't succeed (e.g. insufficient cash) instead of the receipt
  being silently discarded.
- `strategy/` — a package: eleven strategies, one per file, all sharing
  `strategy_base.py`'s `BaseStrategy` for trader/datafeed wiring, order
  submission, and `log_self()` (which now logs the concrete strategy's own
  file, via `inspect.getfile()`, rather than one shared module); split into
  `SingleInstrumentStrategy`/`MultiInstrumentStrategy` for what instrument(s)
  they trade (see [Multi-instrument support](multi-instrument.md)). Three
  further pairs each share their own base for mechanics that differ only in
  what feeds the signal: `MovingAverageCrossoverStrategy`/
  `DualMovingAverageCrossoverStrategy` share `moving_average_crossover_base.py`'s
  `MovingAverageCrossoverBase` (differing in what "fast"/"slow" values they
  cross); `MeanReversionStrategy`/`RSIMeanReversionStrategy` share
  `mean_reversion_base.py`'s `MeanReversionBase` (Bollinger Bands vs RSI
  deciding oversold/overbought); `DollarCostAveragingStrategy`/
  `ValueAveragingStrategy` share `periodic_investment_base.py`'s
  `PeriodicInvestmentBase` (a fixed quantity vs a target-value gap deciding how
  much to buy each period). Selected
  by name (see [Strategies](strategies.md)) via `registry.py`'s
  `STRATEGY_REGISTRY`/`resolve_strategy_class()`, which `Trader.load_strategy()`
  calls with the `strategy_name` it was constructed with. `registry.py` is a
  separate module from `strategy_base.py` since it must import every concrete
  strategy file to build the registry - that dependency runs the opposite way
  from the base classes each concrete file imports, so the two can't live in
  the same module without a circular import. `__init__.py` re-exports every
  name (base classes, concrete strategies, the registry) so
  `from simagora.engine.strategy import ...` still works unchanged wherever it
  was already used.
- `simulator.py` — drives the day-by-day simulation loop between a start and end date.

## `marketdata/`

- `csvhandler.py` — parses OHLCV CSV rows into `Decimal`-typed dicts.
- `statistics.py` — `mean`/`population_std_dev`, the plain arithmetic shared by
  `DataFeed`'s own `n_day_moving_avg`/`n_day_std_dev` and `Universe`'s
  `n_day_spread_moving_avg`/`n_day_spread_std_dev` below, so the formula lives
  in exactly one place.
- `datafeed.py` — loads daily OHLCV CSV data for an instrument and exposes price
  lookups, n-day moving averages, n-day highs/lows (used for breakout signals -
  these exclude the given date itself, since a value is always part of its own
  running extreme), n-day standard deviation (used for Bollinger-Band-style
  bands), n-day return (the fractional change in a price field between a date
  and n trading days before it - a point-in-time lookback, unlike the other
  `n_day_*` methods which are all window aggregates), n-day RSI (Cutler's
  variant - a simple, not Wilder-smoothed, average of gains/losses over the
  window, consistent with every other `n_day_*` method's plain trailing-window
  style; needs n+1 trailing bars for the n day-over-day changes it's built
  from), and n-day ATR (Average True Range - the largest of a day's own
  high-low range, the gap up from the previous close to today's high, and the
  gap down from the previous close to today's low, simple-averaged the same
  way; also needs n+1 trailing bars, and takes no `price` field since True
  Range is inherently built from high, low, *and* close together). See
  [Data](data.md) for where it reads from. `get_price`/
  `get_price_info`/`date_is_trading_day` all resolve through the same
  `_index_of(date)` scan the `n_day_*` helpers already use, rather than each
  re-scanning `self.feed` for a matching date on its own.
- `universe.py` — `Universe`, a multi-instrument sibling of `DataFeed`: one
  `DataFeed` per instrument, dispatched by the `instrument` argument every method
  above already accepts but a plain `DataFeed` ignores (it only ever tracks one).
  Exposes the identical method set, so it's a drop-in replacement anywhere a
  "datafeed" is expected. See [Multi-instrument support](multi-instrument.md).
  Also inherits `SpreadStatsMixin`'s `spread`/`n_day_spread_moving_avg`/
  `n_day_spread_std_dev` for the price difference between two instruments, with
  no `DataFeed` equivalent since a spread is inherently a two-instrument concept
  - a day either leg has no data for is dropped from the trailing window rather
  than shifting it further back. The mixin lives in this file too so the test
  suite's `FakeUniverse` (`tests/testutil.py`) can inherit the identical spread
  math rather than reimplementing it.

## Top level

- `launcher.py` — `Launcher`/`main()`, the intended entry point; see
  [Running](running.md). `simulate()`/`report()` both print an announcement, time
  a call, print/log the elapsed time, and are both just
  `Launcher._timed(announcement, label, fn)` with a different `fn`
  (`self.sim.run`/`self.sim.plot`).
