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

None outstanding.

## Quick fixes

None outstanding.

## Biggest bang-for-buck

`Broker.market_impact_factor` (shifting an opening fill's price further
unfavorably in proportion to `already_filled / day_volume`, reusing
`_filled_quantity_by_ins_date` from the liquidity cap) closes out §4 -
every edge case that section ever flagged is now addressed, and §1's
`adj_close`/commission/position-sizing/stop-tightening items are all
done from earlier rounds too.

What's left is genuinely different in kind: §1's two remaining
items - no margin calls/leverage limits/borrow cost/multi-currency
(an explicit non-goal at this scale, not a recommended next step), and
order types being a fixed shape (limit orders, partial fills) - are
real structural undertakings, not another single-primitive PR. Both
remaining order-type gaps share the same prerequisite: the engine has
no concept of an order that stays pending across days. `orderQ` is
drained and every order resolved (opened, rejected, or - for a
CloseOrder - closed) the same call it's processed in; nothing survives
from one `open_manage_and_close(date)` to the next. A limit order that
hasn't touched its limit today, or a partial fill's unfilled remainder,
both need somewhere to live until a later day's processing can act on
them again. Building that - a persistent pending-orders collection
`Broker` walks each day the way it already walks `open_positions` -
is the actual next project here, and it's a design task worth scoping
deliberately rather than slicing further.
