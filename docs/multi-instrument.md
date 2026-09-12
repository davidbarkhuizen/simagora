[← README](../README.md)

# Multi-instrument support

`Broker`/`Account`/`Position`/`Order` are instrument-aware everywhere it matters —
every relevant call threads `order.ins` through (`Broker.calc_execution_price(ins,
...)`, `Account.tally_individual_open_positions` keyed off `order.ins`, etc.).
`DataFeed` tracks exactly one instrument; `Universe` is the multi-instrument
counterpart used when a strategy trades across more than one.

- `Simulator`/`Trader` both take an optional `universe` argument (a list of
  instruments, which must include `instrument`) alongside the existing single
  `instrument`. With `universe=None` (the default), `Simulator` builds a plain
  single-instrument `DataFeed`; given a `universe`, it builds a `Universe`
  instead and every `Trader` gets `self.universe` for a multi-instrument
  strategy to trade across. `instrument` remains the "primary" instrument
  `Simulator.plot()` charts either way, since that's inherently
  single-instrument-shaped.
- `Launcher`'s `p` dict accepts an optional `'universe'` key, threaded straight
  through to `Simulator`.
- **Calendar mismatches are handled, not just assumed away.**
  `Universe.date_is_trading_day()` is a *union* across the whole universe - true if
  *any* tracked instrument trades that date - so a date can be valid for one
  instrument and not another (different exchange holidays, different asset
  classes). Four places degrade gracefully rather than crashing on the resulting
  `None` price lookup:
  - `Trader.execute_strategy()` skips calling into the strategy entirely on a day
    the trader's own instrument has no data (checked directly - no way to ask a
    `Universe` "is it a trading day for *this* instrument" without it).
  - `Broker.execute_orders_to_open`/`execute_orders_to_close` reject with an
    `'instrument_not_trading'` receipt status (same pattern as
    `'gapped_through_stop_loss'`/`'insufficient_cash_bal'`) instead of crashing on
    `calc_execution_price` returning `None`. Both methods share this rejection
    through a private `_calc_execution_price_or_reject()`.
  - `Broker.manage_open_positions` leaves a position alone for the day if its
    instrument has no data, rather than checking take-profit/stop-loss/expiry
    against a missing high/low/close.
  - `Account.tally_individual_open_positions` leaves a position's mark-to-market
    history untouched for the day if its instrument has no data, rather than
    crashing on a missing close price; `record_net_end_of_day_pos` treats that
    day's untallied entry as a zero contribution rather than a missing key.
- **`BaseStrategy` carries only instrument-agnostic concerns.** `engine/strategy/strategy_base.py`'s
  `BaseStrategy` handles the shared trader/datafeed wiring, order submission,
  `open_positions()` (this trader's own currently open positions, straight off
  `Broker.get_open_positions_for_trader()` - every strategy that manages its own
  open positions calls this rather than reaching into `self.trader.broker`
  directly), and `log_self()`. It's split into `SingleInstrumentStrategy` (sets
  `self.instrument = trader.instrument`) and `MultiInstrumentStrategy` (sets
  `self.universe = trader.universe`); see [Strategies](strategies.md) for which
  concrete strategy inherits from which. `DataFeed`/`Universe`'s
  `n_day_return(instrument, date, price, n)` gives a multi-instrument strategy the
  point-in-time lookback return it needs (e.g. to rank instruments by momentum)
  that the other `n_day_*` window aggregates don't provide.
- **`DualMomentumStrategy`, `CrossSectionalMomentumStrategy`, and
  `LowVolatilityStrategy`** (see [Strategies](strategies.md)) rank `self.universe`
  by a metric (`n_day_return` for the first two, `n_day_std_dev` for the third)
  and reconcile currently-open positions against that ranking.
  **`PairsTradingStrategy`** is built on the same base but doesn't rank a
  universe at all - it trades a fixed pair (`self.universe`'s first two
  instruments) against `Universe.spread`/`n_day_spread_moving_avg`/
  `n_day_spread_std_dev` (see below) instead.
- **Shared plumbing lives on `MultiInstrumentStrategy` itself.**
  `rank_universe(metric_fn)` ({instrument: metric_fn(instrument)}, dropping
  instruments `metric_fn` returns `None` for - used by the three ranking
  strategies above, not by `PairsTradingStrategy`), `rank_universe_or_none(metric_fn)`
  (the same ranking, but `None` instead of an empty dict when nothing could be
  scored yet - each ranking strategy's `execute()` starts with `if (ranked is
  None): return`, replacing what used to be an `if (len(ranked) == 0): return`
  duplicated identically in all three), `open_positions_by(key_fn,
  filter_fn=None)` (groups `BaseStrategy.open_positions()` by instrument, by
  `(instrument, buysell)`, or otherwise, optionally filtered - every concrete
  multi-instrument strategy uses this one), and `close_positions(positions,
  date)` (ditto).
- **`Universe.spread`/`n_day_spread_moving_avg`/`n_day_spread_std_dev`** give a
  strategy the rolling mean/std-dev of the price *difference* between two
  instruments - the same moving-average/std-dev shape `MeanReversionStrategy`
  already uses on a single price series (see [Strategies](strategies.md)),
  applied to a spread instead. Built on `DataFeed.trailing_dates()`, which walks
  one instrument's own trading calendar; a day the other leg has no data for is
  dropped from the window rather than shifting it further back to compensate.
