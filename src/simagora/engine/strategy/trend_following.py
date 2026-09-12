from .trend_following_base import TrendFollowingBase

class TrendFollowingStrategy(TrendFollowingBase):
  '''
  Donchian-channel breakout with a shorter second Donchian channel for
  the stop-loss (the classic Turtle-style dual channel): stop-loss
  sits at the exit_window_days low/high.

  On a fresh breakout, any of the trader's own open positions on this
  instrument in the OPPOSITE direction are closed immediately, since
  the trend has now turned against them - unlike
  MovingAverageCrossoverStrategy, same-direction winners are left to
  run rather than banked early.
  '''

  exit_window_days = 10

  def _stop_loss_for_entry(self, date, buysell, cur_price):
    ins = self.instrument
    if (buysell == 'buy'):
      return self.datafeed.n_day_low(ins, date, 'low', self.exit_window_days)
    else:
      return self.datafeed.n_day_high(ins, date, 'high', self.exit_window_days)
