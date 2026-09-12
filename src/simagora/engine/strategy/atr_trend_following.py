from decimal import Decimal

from .trend_following_base import TrendFollowingBase

class ATRTrendFollowingStrategy(TrendFollowingBase):
  '''
  ATR trailing-stop trend following: the same Donchian-channel
  breakout entry as TrendFollowingStrategy, but the initial stop-loss
  is placed atr_multiplier average true ranges (DataFeed.n_day_atr)
  away from the entry price instead of a shorter Donchian exit
  channel - the standard alternative ("chandelier exit"-style) way
  real trend-following systems size their stop, scaled to how much the
  instrument is actually moving day to day rather than a fixed second
  lookback window.

  A genuine chandelier exit ratchets the stop up (for a long)/down
  (for a short) as the position moves favorably, re-tightening it
  daily; Broker.tighten_stop_loss provides that in-place update
  mechanism, but this variant doesn't call it, so it still places the
  stop once, at entry, atr_multiplier ATRs away, and leaves it there
  for the life of the position - the ATR-sized initial stop half of
  the technique, without the continuous ratcheting half.
  '''

  atr_window_days = 14         # Wilder's original ATR recommendation
  atr_multiplier = Decimal('3')  # a common chandelier-exit multiple

  def _stop_loss_for_entry(self, date, buysell, cur_price):
    atr = self.datafeed.n_day_atr(self.instrument, date, self.atr_window_days)
    if (atr is None):
      return None

    distance = self.atr_multiplier * atr
    return cur_price - distance if (buysell == 'buy') else cur_price + distance
