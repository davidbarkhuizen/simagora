from .moving_average_crossover_base import MovingAverageCrossoverBase

class MovingAverageCrossoverStrategy(MovingAverageCrossoverBase):
  '''
  buy when the closing price crosses above the n-day moving average of
  daily highs, sell when it crosses below; every new position carries
  fixed stop-loss/take-profit bands, and any of the strategy's own
  same-direction open positions that are currently in the money get
  closed out whenever a fresh same-direction signal fires
  '''

  moving_average_window_days = 20

  def _fast_and_slow(self, date):
    ins = self.instrument
    # n-day moving average of the daily high, vs today's closing price
    mavg = self.datafeed.n_day_moving_avg(ins, date, 'high', self.moving_average_window_days)
    cur_price = self.datafeed.get_price(ins, date, 'close')
    return cur_price, mavg
