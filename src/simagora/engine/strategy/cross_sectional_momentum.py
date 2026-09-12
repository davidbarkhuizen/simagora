from decimal import Decimal

from .strategy_base import MultiInstrumentStrategy

class CrossSectionalMomentumStrategy(MultiInstrumentStrategy):
  '''
  Cross-sectional momentum: ranks trader.universe by trailing
  lookback_window_days return (n_day_return) each day, goes long the
  top_n best performers and short (sell) the bottom_n worst, and
  closes any of the trader's own open positions whose instrument/
  direction has fallen out of that set. Re-evaluated daily rather than
  the classic monthly/quarterly rebalance, but a position already held
  in its currently-desired direction is left alone rather than
  churned.

  Unlike DualMomentumStrategy (a single long position, or cash), this
  is long AND short at once - shorting is exactly as well-supported by
  Broker/Account as going long (see _signed_pdelta in account.py,
  already exercised by MovingAverageCrossoverStrategy/
  TrendFollowingStrategy's own 'sell' orders), so no new engine
  capability was needed for this one either. Every order still carries
  a protective stop_loss_margin band, same reason as DualMomentumStrategy.
  '''

  lookback_window_days = 20
  top_n = 1
  bottom_n = 1
  stop_loss_margin = Decimal('0.05')  # 5 %

  def _open_leg(self, key, date):
    ins, buysell = key
    cur_price = self.datafeed.get_price(ins, date, 'close')
    self.submit_stop_only_order(ins, buysell, 1, cur_price, self.stop_loss_margin, date)

  def execute(self, date):
    returns = self.rank_universe_or_none(
      lambda ins: self.datafeed.n_day_return(ins, date, 'close', self.lookback_window_days))
    if (returns is None):
      # not enough trailing history anywhere yet
      return

    ranked = sorted(returns, key=returns.get, reverse=True)
    longs = set(ranked[:self.top_n])
    shorts = set(ranked[-self.bottom_n:]) if (self.bottom_n > 0) else set()
    shorts -= longs  # guard a universe too small to fill both sides distinctly

    desired = set((ins, 'buy') for ins in longs) | set((ins, 'sell') for ins in shorts)
    self.rebalance_to(desired, lambda o: (o.ins, o.buysell), self._open_leg, date)
