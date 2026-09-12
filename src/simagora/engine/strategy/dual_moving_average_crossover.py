from decimal import Decimal

from .moving_average_crossover_base import MovingAverageCrossoverBase

class DualMovingAverageCrossoverStrategy(MovingAverageCrossoverBase):
  '''
  the classic "golden cross"/"death cross" dual moving-average
  crossover: buy when the fast_window_days moving average of closes
  crosses above the slow_window_days moving average, sell when it
  crosses below - the standard textbook counterpart to
  MovingAverageCrossoverStrategy's single-moving-average-vs-price
  version. Same stop-loss/take-profit/close-in-the-money mechanics,
  from the shared MovingAverageCrossoverBase, just wider bands: a
  50/200-day pair reacts far more slowly than a 20-day single average,
  so the 0.5%/1% bands sized for that faster signal would otherwise
  stop most positions out long before a multi-month trend plays out.
  '''

  fast_window_days = 50
  slow_window_days = 200
  stop_loss_margin = Decimal('0.05')    # 5 %
  take_profit_margin = Decimal('0.10')  # 10 %

  def _fast_and_slow(self, date):
    ins = self.instrument
    fast = self.datafeed.n_day_moving_avg(ins, date, 'close', self.fast_window_days)
    slow = self.datafeed.n_day_moving_avg(ins, date, 'close', self.slow_window_days)
    return fast, slow
