# Engine review: gaps and extensions

A high-level architectural review of the core simulation engine (`Broker`,
`Account`, `Trader`, `Simulator`, `MsgQ`, `Launcher`, the domain model, and
`marketdata`) — not the strategies, which are audited separately. Focused on
what a real backtesting engine would need that's conspicuously missing or
only partially handled, versus what's a deliberate, already-documented
simplification.

## 1. Obvious logical gaps

- **`adj_close` is parsed but never consumed.** `csvhandler.row_to_dict`
  extracts it from every CSV row, but nothing in `DataFeed`/`Universe`/any
  strategy ever reads it — split/dividend-adjusted pricing (corporate
  actions) isn't actually applied even though the data pipeline carries the
  field that would support it.
- **No margin calls / forced liquidation, no leverage limits, no borrow
  cost for short positions, no multi-currency.** None of these are modeled
  at all; not required at this scale, but a real gap if the simulator's
  ambitions grow.
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
rewrite - none outstanding right now; `Simulator.report_performance()`
(called from `Launcher.report()`) now logs/prints `stats.py`'s
`total_return`/`cagr`/`max_drawdown`/`sharpe_ratio`/`win_rate`/
`average_win`/`average_loss` for every trader off its own
`trader.ac.equity_curve()`/`trader.ac.trade_pnls()`, alongside
`Simulator.plot()`'s matplotlib PNG.

## 4. Genuine engine-level edge cases worth flagging

- **No market-impact modeling.** `Broker.max_volume_fraction_per_fill` now
  lets every trader's OPENING fills for an instrument compete for a shared,
  finite same-day liquidity budget (a fraction of the day's traded volume),
  rather than each trader's fill being entirely independent of every other
  trader's - but the execution price itself is still always
  `(high+low)/2` regardless of how much of that budget a day's fills have
  already consumed. Real markets move price as volume is consumed
  (slippage that grows with fill size); this engine's execution price
  doesn't reflect that at all, for either a single large fill or several
  traders' combined same-day flow.
- **No netting**: each `Order` always creates a new independent `Position`,
  even for the same instrument+direction already held by the same trader —
  consistent throughout (`open_positions_by`, `close_in_the_money_positions`,
  etc.), so this is a deliberate lot-based model, not an oversight, but
  worth naming since a portfolio-level "aggregate exposure per instrument"
  view doesn't exist without walking `open_positions` yourself.

## Quick fixes

None outstanding.

## Biggest bang-for-buck

Every remaining §1 item from here on is a real design decision, not a
small additive change - this review has run out of "wire up plumbing
that already exists but nothing calls yet" candidates (transaction cost
on every exit path, stop-loss slippage, net margin exposure, a flat
commission, `Account.quantity_for_equity_fraction`, and now the last
vestigial-field cleanup are all done). The best-scoped remaining slice
of a bigger item: add the in-place `stop_loss`-tightening primitive §2
already notes is missing (`ATRTrendFollowingStrategy`'s docstring: "the
engine has no in-place `stop_loss` update mechanism"), e.g. a
`Broker.tighten_stop_loss(position, new_stop_loss)` that validates the
new level is strictly more conservative than the current one (closer to
the position's own execution price, on the position's own side of it)
before mutating `order.stop_loss` in place. Safe with no margin
recalculation needed, since tightening a stop only ever reduces the
loss already covered by the margin reserved at entry - and it directly
unblocks chandelier-style trailing stops for `ATRTrendFollowingStrategy`
(a strategy-side change, still someone else's later work) without
touching margin/risk accounting at all. Genuinely smaller in scope than
"order types are a fixed shape" as a whole, but still a real new engine
capability rather than a pure refactor - expect this round to look
different in kind from the last several.
