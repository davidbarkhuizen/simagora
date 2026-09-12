[← README](../README.md)

# Strategies

Selected by the `strat` list passed to `Launcher()`/`Simulator()` (see
[Running](running.md)) — each element is a registry name, looked up in
`strategy.STRATEGY_REGISTRY`:

- **`'movavg'`** — `MovingAverageCrossoverStrategy`. Buy/sell based on whether the
  closing price is above/below the 20-day moving average of daily highs, with fixed
  0.5%/1% stop-loss/take-profit bands. On each new same-direction signal, it also
  submits `CloseOrder`s for any of its own open positions, in that direction, that
  are currently in the money (see [Position closing](position-closing.md)). Built on
  `MovingAverageCrossoverBase`, shared with `DualMovingAverageCrossoverStrategy` below.
- **`'dualmacrossover'`** — `DualMovingAverageCrossoverStrategy`, the classic "golden
  cross"/"death cross": buy when the `fast_window_days` (default 50) moving average
  of closes crosses above the `slow_window_days` (default 200) moving average, sell
  when it crosses below — the standard textbook counterpart to `MovingAverageCrossoverStrategy`'s
  single-moving-average-vs-price version, sharing the same `MovingAverageCrossoverBase`
  for stop-loss/take-profit/close-in-the-money mechanics. Uses much wider 5%/10%
  bands than its sibling's 0.5%/1%, since a 50/200-day signal moves far more slowly
  than a 20-day one — the tighter bands sized for that faster signal would otherwise
  stop most positions out long before a multi-month trend plays out.
- **`'trend'`** — `TrendFollowingStrategy`. A Donchian-channel breakout: buy when
  the close breaks above the high of the preceding 20 days, sell when it breaks
  below their low. Stop-loss sits at the shorter 10-day low/high (the classic
  Turtle-style dual channel); there is deliberately no take-profit (`Order`'s
  `take_profit` can be `None` — `Broker.profit_taken_on_position` treats that as
  "never triggers"), since trend-following aims to let a winning position run until
  it's stopped out or the trend reverses. A fresh breakout also closes any of the
  trader's own open positions in the *opposite* direction. Built on
  `TrendFollowingBase`, shared with `ATRTrendFollowingStrategy` below.
- **`'atrtrend'`** — `ATRTrendFollowingStrategy`, sharing the same
  `TrendFollowingBase` Donchian-channel breakout entry and opposite-direction
  close mechanics as `TrendFollowingStrategy`, but placing the stop-loss
  `atr_multiplier` (default 3) average true ranges (`DataFeed.n_day_atr`, over
  `atr_window_days`, default 14) away from the entry price instead of a second,
  shorter Donchian channel — the standard "chandelier exit"-style alternative,
  scaled to how much the instrument is actually moving day to day. A genuine
  chandelier exit also ratchets the stop as the position moves favorably;
  `Broker.tighten_stop_loss` now provides the in-place update mechanism that
  would need (see [Layout](layout.md)'s `broker.py`), but this strategy
  doesn't call it yet, so it still places the ATR-sized stop once, at entry,
  and leaves it there for the life of the position.
- **`'meanreversion'`** — `MeanReversionStrategy`. Bollinger-Band mean reversion:
  buy when the close drops 2 standard deviations below its own 20-day moving
  average (oversold), sell when it rises the same distance above it (overbought),
  each with fixed 1%/2% stop-loss/take-profit bands. No position-management beyond
  that — a reversion trade is meant to be quick. Built on `MeanReversionBase`,
  shared with `RSIMeanReversionStrategy` below.
- **`'rsimeanreversion'`** — `RSIMeanReversionStrategy`, the other standard
  mean-reversion indicator, taught alongside Bollinger Bands as its usual
  textbook counterpart, sharing the same `MeanReversionBase` for stop-loss/
  take-profit mechanics. Buy when the `rsi_window_days` (default 14, Wilder's
  original recommendation) RSI (`DataFeed.n_day_rsi`) drops below
  `oversold_threshold` (default 30), sell when it rises above
  `overbought_threshold` (default 70).
- **`'dualmomentum'`** — `DualMomentumStrategy`, the first multi-instrument
  strategy (`MultiInstrumentStrategy`, trades across `trader.universe`). An
  Antonacci-style rotation: ranks `trader.universe` by trailing 20-day return
  (relative momentum) each day and holds a single long position in the leader,
  but only while the leader's own return is positive (absolute momentum filter) —
  otherwise it closes out to cash rather than holding a losing leader. Re-evaluated
  daily rather than the classic monthly rebalance, but a leader already held is
  left alone (no churn) until the ranking actually changes. No fixed take-profit —
  a position exits on a leader change or the absolute-momentum filter tripping —
  but every buy still carries a protective 5% `stop_loss_margin`, since
  `Broker.execute_orders_to_open` requires a `stop_loss` on every order to size
  margin.
- **`'crosssectionalmomentum'`** — `CrossSectionalMomentumStrategy`, also a
  `MultiInstrumentStrategy`. Ranks `trader.universe` by trailing 20-day return
  each day, goes long the single best performer and short (`'sell'`) the single
  worst (`top_n`/`bottom_n`, both default 1), and closes any of the trader's own
  open positions whose instrument/direction has fallen out of that set — a
  position already held in its currently-desired direction is left alone. Unlike
  `DualMomentumStrategy` there's no absolute-momentum cash filter and no
  guaranteed floor on the short leg's return - it's always long the top and short
  the bottom of whatever the universe offers that day. Shorting needed no new
  engine capability - `Account`'s P&L math (`_signed_pdelta`) is already symmetric
  between `'buy'`/`'sell'`, the same mechanism `MovingAverageCrossoverStrategy`/
  `TrendFollowingStrategy` already use for their own `'sell'` signals.
- **`'lowvolatility'`** — `LowVolatilityStrategy`, also a `MultiInstrumentStrategy`.
  Ranks `trader.universe` by trailing 20-day standard deviation of daily closes
  (`n_day_std_dev`) each day and holds long positions in the calmest `top_n`
  (default 1) instruments - the opposite selection from the momentum strategies
  above. Long-only, with no cash filter: it's always fully invested in whichever
  instruments are currently calmest. A currently-held instrument still among the
  calmest is left alone rather than churned.
- **`'dollarcostaveraging'`** — `DollarCostAveragingStrategy`. Buys a fixed
  quantity of `trader.instrument` every `interval_days` trading days (default 21,
  ~1 trading month), starting on the very first one, and does nothing else — no
  signal, no timing, no exit. The passive control-group baseline every other
  strategy above should be measured against. Each purchase has
  `stop_loss=take_profit=None`, opening as a fully-collateralized position (see
  [Position closing](position-closing.md)) that never auto-closes; positions
  simply accumulate and are marked to market for the rest of the run. Sized by a
  fixed share quantity rather than a fixed dollar amount, like every strategy
  above — an order submitted today executes at tomorrow's price (see
  [Overview](overview.md)), which isn't known yet at submission time. Built on
  `PeriodicInvestmentBase`, shared with `ValueAveragingStrategy` below.
- **`'valueaveraging'`** — `ValueAveragingStrategy`, the standard textbook
  counterpart to `DollarCostAveragingStrategy` (Edleson's Value Averaging),
  sharing the same `PeriodicInvestmentBase` schedule. Instead of a fixed
  quantity every period, buys however many shares are needed to bring the
  position's current market value up to a linearly growing target -
  `deposit_amount` × (periods elapsed + 1) - so it buys more when the price has
  dropped (the existing holding is worth less, so a bigger top-up is needed) and
  less when it's risen. Buy-only: if the position's value already meets or
  exceeds the target, that period's purchase is skipped rather than selling the
  excess - the commonly-discussed "no-sell" variant, since this engine's
  Order/Position model represents each purchase as its own discrete lot rather
  than a fungible pool of shares a partial close could trim precisely.
- **`'pairstrading'`** — `PairsTradingStrategy`, also a `MultiInstrumentStrategy`,
  but trades a fixed pair rather than ranking the whole universe: the first two
  instruments of `trader.universe` (`self.instrument_a`/`self.instrument_b`).
  Tracks the z-score of their price spread (`Universe.spread`) against its own
  trailing 20-day mean/std-dev — the same moving-average/std-dev shape
  `MeanReversionStrategy` uses on a single price series, applied to the spread
  between two instruments instead. Opens a pair position once the spread has
  drifted `entry_z_score` (default 2) standard deviations from its own mean —
  short whichever leg has gotten relatively rich, long whichever has gotten
  relatively cheap, one unit each — and closes both legs together once it has
  reverted back within `exit_z_score` (default 0.5) of it. Only one pair
  position is held at a time; a fresh entry signal while one is already open is
  ignored. A window with zero variance (every trailing spread value, today's own
  included, already equal to the mean) is treated as fully reverted for an
  already-open pair - the limiting case of a zero z-score - but as no signal at
  all for a fresh entry, since there's nothing to score one against. Sized as a
  single unit of each leg rather than a dollar/beta-neutral hedge ratio - true
  market-neutral sizing needs a rolling beta calculation this strategy doesn't
  attempt, so this is a directionally market-neutral approximation, not a
  precisely dollar-neutral one. The two legs aren't opened atomically (each is
  its own independent `Order`), so one can be rejected while the other opens, or
  one can later be stopped out on its own while the other survives; either way
  leaves a naked single-leg position, which `execute()` detects (exactly one of
  the pair's two legs open) and closes immediately rather than treating it as a
  complete, hedged pair.

An unrecognized name raises `ValueError` rather than silently falling back to a
default, so a typo doesn't quietly run the wrong strategy; `None` (what every
`Trader`-constructing test in this repo passes, since they don't care which
strategy loads) resolves to `'movavg'`.

`MovingAverageCrossoverStrategy`, `DualMovingAverageCrossoverStrategy`,
`TrendFollowingStrategy`, `ATRTrendFollowingStrategy`, `MeanReversionStrategy`,
`RSIMeanReversionStrategy`, `DollarCostAveragingStrategy`, and
`ValueAveragingStrategy` are single-instrument (`SingleInstrumentStrategy`
reads `trader.instrument`);
`DualMomentumStrategy`, `CrossSectionalMomentumStrategy`, `LowVolatilityStrategy`,
and `PairsTradingStrategy` are multi-instrument — see
[Multi-instrument support](multi-instrument.md) for the plumbing they're built on.
