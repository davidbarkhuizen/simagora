# Engine review: gaps and extensions

A high-level architectural review of the core simulation engine (`Broker`,
`Account`, `Trader`, `Simulator`, `MsgQ`, `Launcher`, the domain model, and
`marketdata`) — not the strategies, which are audited separately. Focused on
what a real backtesting engine would need that's conspicuously missing or
only partially handled, versus what's a deliberate, already-documented
simplification.

## 1. Obvious logical gaps

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

`adj_open`/`adj_high`/`adj_low` (derived from each bar's own
`close`-to-`adj_close` ratio) close out §1's `adj_close` item - a
strategy switching to the adjusted price series now gets an internally
consistent OHLC bar, the same way `adj_close` alone already worked.

The next real, scoped gap: finish the other half of §4's "no
market-impact modeling" note. `_filled_quantity_by_ins_date` (added for
`max_volume_fraction_per_fill`) already tracks how much of an
instrument's day has been filled before a given order - `calc_execution_price`
just never reads it. An opt-in `Broker.market_impact_factor` (default
0/None, preserving today's flat `(high+low)/2`) could shift the price
further, unfavorably, in proportion to
`already_filled / day_volume` - so the *second* trader (or the second
half of one large order, once partial fills exist) filling the same
instrument on the same day pays more than the first, rather than every
fill getting an identical price regardless of how much of the day's
liquidity is already spoken for. Reuses infrastructure the liquidity
cap already built rather than needing new state.
