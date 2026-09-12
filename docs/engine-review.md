# Engine review: gaps and extensions

A high-level architectural review of the core simulation engine (`Broker`,
`Account`, `Trader`, `Simulator`, `MsgQ`, `Launcher`, the domain model, and
`marketdata`) — not the strategies, which are audited separately. Focused on
what a real backtesting engine would need that's conspicuously missing or
only partially handled, versus what's a deliberate, already-documented
simplification.

## 1. Obvious logical gaps

- **Transaction cost only covers the open/close spread, not exits or fees.**
  `Broker.calc_execution_price` now applies an optional flat per-unit
  `transaction_cost` against every open and explicit-close fill (both
  round-trip legs), but stop-loss/take-profit/expiry exits still fill at
  their literal trigger level or the day's raw close, untouched by cost -
  and there's still no separate commission/fee model distinct from this
  spread-style cost.
- **No slippage on stop-loss execution.** `Account.stop_loss` always books
  the loss as exactly the margin reserved at entry, regardless of how far
  the day's low actually gapped past the stop level. Real stop orders can
  execute worse than their trigger in a fast market; here the loss is
  capped by construction.
- **`Order.target_price`/`target_floor`/`target_ceiling`** are accepted in
  `Order.__init__` and stored, but never read anywhere in the codebase —
  vestigial/unused fields.
- **`adj_close` is parsed but never consumed.** `csvhandler.row_to_dict`
  extracts it from every CSV row, but nothing in `DataFeed`/`Universe`/any
  strategy ever reads it — split/dividend-adjusted pricing (corporate
  actions) isn't actually applied even though the data pipeline carries the
  field that would support it.
- **No position sizing primitives.** Quantity is always a strategy-chosen
  integer (`1`, or a hand-computed share count for DollarCostAveraging/
  ValueAveraging). `Account.equity(date)` now gives a single "current
  equity" figure (see §3), but no strategy actually sizes against it yet —
  %-of-equity or volatility-targeted sizing would still need to be built
  per-strategy.
- **No margin calls / forced liquidation, no leverage limits, no borrow
  cost for short positions, no multi-currency.** None of these are modeled
  at all; not required at this scale, but a real gap if the simulator's
  ambitions grow.
- **Portfolio risk limits cap margin exposure and position counts, not
  true net exposure.** `Broker.execute_orders_to_open` supports optional
  `max_open_positions_per_trader`/`max_open_positions_per_instrument`/
  `max_margin_exposure_per_trader` gates, but the exposure cap sums every
  position's margin regardless of direction - a long and an offsetting
  short on the same instrument both count fully against it, rather than
  netting against each other the way a true "net exposure" figure would.
- **Order types are a fixed shape**: market fill + optional stop-loss +
  optional take-profit + optional expiry. No limit orders, no trailing
  stops (already called out per-strategy in `ATRTrendFollowingStrategy`'s
  docstring), no partial fills — an order either opens in full or is
  rejected in full.

## 2. Known/accepted simplifications

Already documented in their own docstrings — noted here for completeness,
not re-litigated:

- `ATRTrendFollowingStrategy`: stop is sized once at entry, no continuous
  chandelier-style ratcheting (the engine has no in-place `stop_loss`
  update mechanism).
- `PairsTradingStrategy`: directionally market-neutral, not precisely
  dollar/beta-neutral.
- `ValueAveragingStrategy`: buy-only variant (the engine's lot-based
  `Position` model can't precisely trim a fungible share pool).
- Same-day stop-loss-before-take-profit pessimism, and the
  midpoint-of-day-high/low execution price convention, are both
  intentional, documented simplifications.

## 3. Natural extensions

Reasonable next capabilities that fit the existing architecture without a
rewrite:

- **Nothing surfaces `engine/stats.py`'s metrics in a real run.**
  `Account.equity(date)`/`equity_curve()`/`trade_pnls()` and `stats.py`'s
  `total_return`/`cagr`/`max_drawdown`/`sharpe_ratio`/`win_rate`/
  `average_win`/`average_loss` are all pure library calls - nothing in
  `Simulator`/`Launcher` invokes them. `Simulator.plot()` remains the only
  actual reporting surface, and it's still just a matplotlib PNG plus a
  couple of `logging.info` lines.

## 4. Genuine engine-level edge cases worth flagging

- **`MsgQ.extract_matching`** does an O(n) linear scan with `list.pop(i)`
  inside a `while` loop — fine at backtest scale, no correctness issue,
  just worth knowing if instrument/trader counts ever grow large.
- **Multi-trader interactions are fully independent.** Traders share one
  `Broker`/`orderQ` but have separate `Account`s and no shared-liquidity or
  market-impact modeling — reasonable for independent-strategy backtests,
  but means the engine can't model traders competing for the same fills or
  one trader's flow affecting another's execution price.
- **No netting**: each `Order` always creates a new independent `Position`,
  even for the same instrument+direction already held by the same trader —
  consistent throughout (`open_positions_by`, `close_in_the_money_positions`,
  etc.), so this is a deliberate lot-based model, not an oversight, but
  worth naming since a portfolio-level "aggregate exposure per instrument"
  view doesn't exist without walking `open_positions` yourself.
- **`Launcher.report()`/`Simulator.plot()`** hardcode `'plot/' + time_stamp`
  as the output path with no directory-creation guard — will raise if
  `plot/` doesn't exist. Minor, easy to miss since it's outside the core
  sim loop.

## Biggest bang-for-buck

Surface `engine/stats.py`'s metrics in a real run (§3) — right now
`total_return`/`cagr`/`max_drawdown`/`sharpe_ratio`/`win_rate`/
`average_win`/`average_loss` are pure library calls nothing in
`Simulator`/`Launcher` invokes; `Simulator.plot()` remains a matplotlib PNG
plus a couple of `logging.info` lines. Computing them off
`trader.ac.equity_curve()`/`trader.ac.trade_pnls()` and logging/printing
the result at the end of a run (e.g. from `Launcher.report()`) is additive,
touches no existing logic, and finally makes every one of those already-built
metrics visible from an actual backtest instead of only from its own test suite.
