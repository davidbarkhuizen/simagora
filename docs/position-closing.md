[← README](../README.md)

# Position closing

A position closes the same day one of the following happens, in this order:

1. **Stop-loss** — intraday high/low reaches the order's `stop_loss` level. Checked
   before take-profit: daily OHLCV can't say which level a day's high/low range
   hit first, so a day spanning both is resolved pessimistically, as a loss. Never
   triggers if `stop_loss` is `None` — that instead marks a fully-collateralized
   position (the full notional value is held as margin, e.g. a plain unleveraged
   buy-and-hold purchase) with no price-based exit at all. Fills at the worse of
   the `stop_loss` level and the day's actual low/high, not always the level
   itself — a fast-market gap through the stop costs more than the margin
   reserved at entry, rather than being capped by construction.
2. **Take-profit** — intraday high/low reaches the order's `take_profit` level.
   Never triggers if `take_profit` is `None` (`TrendFollowingStrategy`'s positions).
3. **Expiry** — `Order.expiry_date` is reached; settles at that day's closing price.
4. **Explicit close** — a `CloseOrder` referencing the position's id is submitted;
   settles at that day's midpoint execution price, same as opening a position. Only
   the position's own trader may close it this way — a `CloseOrder` from another
   trader is rejected. `MovingAverageCrossoverStrategy` submits one of these
   automatically for each of its own open positions that is in the money whenever a
   new same-direction signal fires; `TrendFollowingStrategy` submits one for each of
   its own open positions in the *opposite* direction whenever a fresh breakout
   fires. Either way this happens rather than leaving the position to run until
   stop-loss/take-profit/expiry. `DualMomentumStrategy` submits one whenever the
   leader changes (rotating out of the old one) or the absolute-momentum filter
   trips (rotating fully to cash). `CrossSectionalMomentumStrategy` submits one
   for each open position whose instrument/direction has fallen out of the
   current top/bottom ranking. `LowVolatilityStrategy` submits one for each open
   position whose instrument is no longer among the calmest. `PairsTradingStrategy`
   submits one for each leg of its pair once their price spread has reverted back
   toward its own mean, or immediately for a lone surviving leg if the other has
   already closed on its own (stopped out, or rejected when the pair was opened).

See [Strategies](strategies.md) for details on each strategy named above.
