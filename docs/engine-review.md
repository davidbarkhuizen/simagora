# Engine review: gaps and extensions

A high-level architectural review of the core simulation engine (`Broker`,
`Account`, `Trader`, `Simulator`, `MsgQ`, `Launcher`, the domain model, and
`marketdata`) — not the strategies, which are audited separately. Focused on
what a real backtesting engine would need that's conspicuously missing or
only partially handled, versus what's a deliberate, already-documented
simplification.

## 1. Obvious logical gaps

- **No transaction cost modeling.** No commissions, fees, bid/ask spread, or
  slippage anywhere. `Broker.calc_execution_price` fills every order at the
  day's `(high+low)/2` — a clean but cost-free execution assumption.
- **No slippage on stop-loss execution.** `Account.stop_loss` always books
  the loss as exactly the margin reserved at entry, regardless of how far
  the day's low actually gapped past the stop level. Real stop orders can
  execute worse than their trigger in a fast market; here the loss is
  capped by construction.
- **`Order.leverage` is dead-ended.** All P&L/margin math throughout
  `Account`/`Broker` is written generically against `order.leverage`, but
  `Order.__init__` hardcodes `self.leverage = Decimal(1)` with no
  constructor parameter to set it — leverage is fully plumbed through but
  currently unreachable.
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

- ~~**Analytics/reporting.**~~ Done: `Account.equity(date)`/`equity_curve()`
  (cash + margin + unrealized open-position P&L, off the daily
  `d_cash_bal`/`d_margin_bal`/`net_open_position` series already tracked)
  and `Account.closed_trades`/`trade_pnls()` (now appended to by every
  close path — `_close_position`, `stop_loss`, `handle_expiry`) feed
  `engine/stats.py`'s `total_return`, `cagr`, `max_drawdown`,
  `sharpe_ratio`, `win_rate`, `average_win`, `average_loss`.
  `Simulator.plot()` remains the only *chart* surface — nothing renders
  these numbers yet, they're library functions a caller invokes directly.
- **Transaction cost modeling** could slot into
  `Broker.calc_execution_price`/`_calc_execution_price_or_reject` as an
  optional cost parameter without touching call sites.
- **Portfolio-level risk controls** (max concurrent positions, max
  gross/net exposure, per-instrument or per-trader position limits) —
  `Broker`/`Account` already have all the bookkeeping these would read
  from; there's just no gate that consults it before opening.
- **Wiring up `Order.leverage`** (accept it as a constructor parameter)
  would activate an already-implemented code path for free.

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

~~An `Account.equity()` accessor plus a small stats module (Sharpe/drawdown/
CAGR off the data already being tracked)~~ — done, see §3. ~~Wire up
`Account.closed_trades` so win rate and average win/loss can be added to
`stats.py`~~ — also done, see §3. All four were additive and touched no
existing bookkeeping logic.

Next candidate: wiring up `Order.leverage` (§3) — it activates an
already-implemented code path for free, and would let `stats.py`'s new
per-trade metrics be exercised against leveraged, not just 1x, positions.
