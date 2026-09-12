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
  take-profit, optional expiry date, optional leverage - defaults to `1`,
  coerced to `Decimal` the same way `quantity` is).
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
  `take_profit()`, `stop_loss()`, `handle_expiry()`, and `close_at_price()` are
  all just closing a position at some price and banking the resulting pnl -
  the only difference is which price and what `TermNotice` reason - so all
  four delegate to a shared private `_close_position(date, pos, price,
  buysell, reason)`, which also appends the closed `Position` onto
  `closed_trades` and debits `Broker.commission_per_trade` (a flat cash fee
  charged once per fill, separate from `transaction_cost` - see `broker.py`
  below - so it never touches the recorded price or the trade's own pnl).
  `stop_loss()` fills at the worse of the order's own `stop_loss` level and
  the day's actual low/high (`pdata['low']`/`pdata['high']`), modeling
  slippage from a fast-market gap through the stop rather than always
  capping the loss at the margin reserved at entry. `equity(date)`/
  `equity_curve()` read back the daily `d_cash_bal`/`d_margin_bal`/
  `net_open_position` series `Simulator.run()` already records each trading
  day, giving cash + margin held + unrealized P&L as a single mark-to-market
  net worth figure; `trade_pnls()` reads `closed_trades`' `term_notice.profitloss`
  values back as a plain list - both are the inputs `stats.py` (below)
  computes performance metrics from. `quantity_for_equity_fraction(date,
  price, fraction, leverage=1)` turns a %-of-equity sizing rule into a
  whole-unit quantity (`floor(equity(date) * fraction * leverage / price)`,
  0 if that doesn't cover even one unit) - a primitive nothing currently
  calls, since every shipped strategy still sizes its own way (a fixed `1`,
  or a hand-computed share count). `net_quantity_by_instrument()` gives
  `{instrument: net signed quantity}` across a trader's own open positions,
  netting long/short lots on the same instrument against each other - each
  `Order` always opens its own independent `Position` even for the same
  instrument+direction already held (a deliberate lot-based model), so
  nothing else gives this aggregate view without walking every open
  position and grouping by instrument yourself.
- `stats.py` — performance metrics computed off an `Account.equity_curve()`
  (`total_return`, `cagr`, `max_drawdown`, an annualized `sharpe_ratio` -
  reusing `marketdata/statistics.py`'s `mean`/`population_std_dev` on the
  curve's `daily_returns`, the same population-statistics convention used
  elsewhere in the codebase) or an `Account.trade_pnls()` list
  (`win_rate`, `average_win`, `average_loss`).
- `broker.py` — receives orders via `msgq.py` message queues, computes a fill price
  (midpoint of the day's high/low, adjusted by an optional flat per-unit
  `transaction_cost` - added against a buy, subtracted against a sell,
  defaulting to `0`; `execute_orders_to_close` passes the *closing* fill's
  own direction, the opposite of the position's own buysell, so cost is
  charged on both legs of a round trip, not just the entry). `apply_exit_cost`
  applies that same cost convention to stop-loss/take-profit/expiry exits too
  (given the position's own original direction rather than a fresh fill
  direction), so every exit path pays the same `transaction_cost` an open or
  an explicit close already do. `Broker` opens/closes `Position`s, checks
  stop-loss/take-profit levels against intraday high/low, and updates account
  balances. `execute_orders_to_open` also gates each order behind four
  optional, independently-off-by-default portfolio risk limits -
  `max_open_positions_per_trader`, `max_open_positions_per_instrument`,
  `max_margin_exposure_per_trader` (netting a long and an offsetting short on
  the same instrument against each other rather than summing every position's
  margin regardless of direction), and `max_volume_fraction_per_fill` (every
  trader's opening fills for an instrument share a same-day liquidity budget,
  a fraction of that day's traded volume) - rejecting with a
  `max_..._exceeded`/`exceeds_available_liquidity` receipt status rather than
  opening the position when one is set and would be breached. An optional
  `market_impact_factor` shifts an opening fill's price further unfavorably
  in proportion to how much of that same shared liquidity budget earlier
  fills have already consumed that day, so later fills pay a worse price
  than earlier ones instead of every fill getting an identical price.
  `commission_per_trade` is a flat cash fee (distinct from `transaction_cost`)
  charged once per fill, both opening and closing - see `account.py` above
  for how it's booked on close. `tighten_stop_loss(position, new_stop_loss)`
  mutates an already-open position's `stop_loss` in place, but only in the
  risk-reducing direction relative to its current level - the missing
  in-place update mechanism a chandelier-style trailing stop needs, though
  no shipped strategy calls it yet (see [Strategies](strategies.md)'s
  `ATRTrendFollowingStrategy` entry).
- `trader.py` — holds a strategy and an `Account`, submits orders, and drains its
  own order/close-order receipts each day (`process_receipts()`), logging a warning
  for anything that didn't succeed (e.g. insufficient cash) instead of the receipt
  being silently discarded.
- `strategy/` — a package: twelve strategies, one per file, all sharing
  `strategy_base.py`'s `BaseStrategy` for trader/datafeed wiring, order
  submission, and `log_self()` (which now logs the concrete strategy's own
  file, via `inspect.getfile()`, rather than one shared module); split into
  `SingleInstrumentStrategy`/`MultiInstrumentStrategy` for what instrument(s)
  they trade (see [Multi-instrument support](multi-instrument.md)). Four
  further pairs each share their own base for mechanics that differ only in
  what feeds the signal: `MovingAverageCrossoverStrategy`/
  `DualMovingAverageCrossoverStrategy` share `moving_average_crossover_base.py`'s
  `MovingAverageCrossoverBase` (differing in what "fast"/"slow" values they
  cross); `TrendFollowingStrategy`/`ATRTrendFollowingStrategy` share
  `trend_following_base.py`'s `TrendFollowingBase` (a second, shorter Donchian
  channel vs an ATR multiple deciding where the initial stop sits);
  `MeanReversionStrategy`/`RSIMeanReversionStrategy` share
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
- `simulator.py` — drives the day-by-day simulation loop between a start and end
  date. Takes optional `transaction_cost`/`commission_per_trade`/
  `max_open_positions_per_trader`/`max_open_positions_per_instrument`/
  `max_margin_exposure_per_trader`/`max_volume_fraction_per_fill`/
  `market_impact_factor` (see `broker.py` above), all defaulting to
  `Broker`'s own defaults and forwarded straight to it. `report_performance()`
  logs/prints `stats.py`'s metrics (below) for every trader off its own
  `equity_curve()`/`trade_pnls()`, alongside `plot()`'s matplotlib PNG - the
  only two actual reporting surfaces a real run produces.

## `marketdata/`

- `csvhandler.py` — parses OHLCV CSV rows into `Decimal`-typed dicts, deriving
  `adj_open`/`adj_high`/`adj_low` from each row's own `close`-to-`adj_close`
  ratio (1, i.e. no adjustment, if `adj_close` is missing or non-positive) so
  a strategy that switches its price field to the adjusted series gets an
  internally consistent bar rather than an adjusted `close` mixed with raw
  `open`/`high`/`low`. See [Data](data.md).
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
  [Running](running.md). `simulate()` and `report()` each print an
  announcement, time a call, and print/log the elapsed time via
  `Launcher._timed(announcement, label, fn)`; `report()` calls it twice, for
  `self.sim.plot` and `self.sim.report_performance` (see `simulator.py`
  above).
