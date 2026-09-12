[← README](../README.md)

# Multi-instrument support

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
    `calc_execution_price` returning `None`. Both methods share this rejection
    through a private `_calc_execution_price_or_reject()`, since either can hit it.
  - `Broker.manage_open_positions` simply leaves a position alone for the day if
    its instrument has no data, rather than checking take-profit/stop-loss/expiry
    against a missing high/low/close.

- **`BaseStrategy` is split by instrument shape.** `engine/strategy.py`'s
  `BaseStrategy` itself no longer knows about instruments at all — just the shared
  trader/datafeed wiring, order submission, `open_positions()` (this trader's own
  currently open positions, straight off `Broker.get_open_positions_for_trader()`
  - every strategy that manages its own open positions calls this rather than
  reaching into `self.trader.broker` directly), and `log_self()`. It's split into
  `SingleInstrumentStrategy` (sets `self.instrument = trader.instrument`) and
  `MultiInstrumentStrategy` (sets `self.universe = trader.universe`); the first
  three concrete strategies in [Strategies](strategies.md) all inherit from
  `SingleInstrumentStrategy`. `DataFeed`/`Universe`'s
  `n_day_return(instrument, date, price, n)` gives a multi-instrument strategy the
  point-in-time lookback return it needs (e.g. to rank instruments by momentum)
  that the other `n_day_*` window aggregates don't provide.

- **`DualMomentumStrategy`** (see [Strategies](strategies.md)) is the first
  concrete strategy built on this: it subclasses `MultiInstrumentStrategy`, ranks
  `self.universe` by `self.datafeed.n_day_return(...)` each day, and rotates its
  single long position into the leader.
- **`CrossSectionalMomentumStrategy`** (see [Strategies](strategies.md)) is the
  second: same ranking mechanism, but long the top performer(s) *and* short the
  bottom one(s) at once, rather than a single rotating long/cash position.
  Confirms shorting needed no engine changes either - `Account`'s
  `_signed_pdelta` P&L math was already symmetric between `'buy'`/`'sell'`.
- **`LowVolatilityStrategy`** (see [Strategies](strategies.md)) is the third:
  ranks by `n_day_std_dev` instead of `n_day_return`, and holds the
  *lowest*-ranked instruments (calmest) rather than the highest - showing the
  same ranking mechanism generalizes past momentum-style metrics. Long-only, no
  cash filter. Its tests caught a real bug in `FakeDataFeed` (the test double in
  `testutil.py`): `_trailing_values` (backing `n_day_moving_avg`/`n_day_high`/
  `n_day_low`/`n_day_std_dev`) raised `ValueError` for a date with no data at all,
  where the real `DataFeed` gracefully returns no values - unnoticed until a
  strategy called it against a *non-primary* universe instrument with a calendar
  gap, which no earlier test exercised.
- **Shared ranking/rotation plumbing lives on `MultiInstrumentStrategy` itself.**
  All three strategies above rank the universe by some metric and then reconcile
  currently-open positions against whatever that ranking wants, so that plumbing
  - not each strategy's own copy of it - lives once on the base class:
  `rank_universe(metric_fn)` ({instrument: metric_fn(instrument)}, dropping
  instruments `metric_fn` returns `None` for), `open_positions_by(key_fn,
  filter_fn=None)` (groups `BaseStrategy.open_positions()` however the caller
  needs - by instrument, by `(instrument, buysell)`, optionally filtered), and
  `close_positions(positions, date)`. Each concrete strategy's `execute()` just
  supplies its own metric and grouping key.
