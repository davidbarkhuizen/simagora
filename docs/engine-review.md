# Engine review: gaps and extensions

A high-level architectural review of the core simulation engine (`Broker`,
`Account`, `Trader`, `Simulator`, `MsgQ`, `Launcher`, the domain model, and
`marketdata`) — not the strategies, which are audited separately. Focused on
what a real backtesting engine would need that's conspicuously missing or
only partially handled, versus what's a deliberate, already-documented
simplification.

## 1. Obvious logical gaps

- **`adj_close` is reachable but incomplete.** `csvhandler.row_to_dict`
  parses it into every bar, and it's fully wired into `get_price`/
  `get_price_info` like any other field (`get_price(ins, date,
  'adj_close')` already works) - but nothing besides `close` has an
  adjusted counterpart. `open`/`high`/`low` stay raw, so a strategy that
  switches its own price field to `'adj_close'` still gets an internally
  inconsistent bar: every `n_day_high`/`n_day_low`/`n_day_atr` helper
  keeps computing off unadjusted highs/lows, reintroducing the exact
  split/dividend artifact adjusted pricing exists to avoid.
- **No margin calls / forced liquidation, no leverage limits, no borrow
  cost for short positions, no multi-currency.** None of these are modeled
  at all; not required at this scale, but a real gap if the simulator's
  ambitions grow.
- **Order types are a fixed shape**: market fill + optional stop-loss +
  optional take-profit + optional expiry. No limit orders, no partial
  fills — an order either opens in full or is rejected in full.
  `Broker.tighten_stop_loss(position, new_stop_loss)` now provides the
  in-place `stop_loss`-update mechanism a trailing stop needs, but
  nothing calls it yet - `ATRTrendFollowingStrategy` still sizes its
  stop once at entry with no ratcheting, so trailing-stop *behavior*
  remains unimplemented (a strategy-side change, out of scope here).

## 2. Known/accepted simplifications

Already documented in their own docstrings — noted here for completeness,
not re-litigated:

- `ATRTrendFollowingStrategy`: stop is sized once at entry, no continuous
  chandelier-style ratcheting - `Broker.tighten_stop_loss` now gives the
  engine an in-place `stop_loss`-update mechanism (see §1), but the
  strategy itself doesn't call it yet.
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

## Quick fixes

None outstanding.

## Biggest bang-for-buck

`Broker.tighten_stop_loss` closes out the last "add one primitive,
unblock a bigger feature" win inside "order types are a fixed shape"
(§1) - what's left there (limit orders, partial fills) both need
persistent, multi-day order state the engine doesn't have today (an
order is drained from `orderQ` and resolved once, not kept pending
across runs of `open_manage_and_close`), which is a structural change,
not a single additive primitive.

The next real, scoped gap: §1's `adj_close` item. A fix: derive
`adj_open`/`adj_high`/`adj_low` at CSV-load time
(`csvhandler.row_to_dict` or `DataFeed`) from each row's own
`close`-to-`adj_close` ratio, so a fully split/dividend-consistent OHLC
bar is available as a set, not one adjusted field mixed with three raw
ones.
