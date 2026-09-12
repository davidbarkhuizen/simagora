from decimal import Decimal

from ...domain.order import Order
from .strategy_base import SingleInstrumentStrategy

class MeanReversionStrategy(SingleInstrumentStrategy):
  '''
  Bollinger-Band mean reversion: buy when the close drops
  band_width_std_devs standard deviations below its own
  moving_average_window_days moving average (oversold), sell when it
  rises the same distance above it (overbought) - betting the price
  reverts back toward its recent average. Unlike the trend-following
  strategies above, a reversion trade is meant to be quick, so it
  simply uses fixed percentage stop-loss/take-profit bands rather than
  any position-management logic beyond that.
  '''

  moving_average_window_days = 20
  band_width_std_devs = Decimal('2')
  stop_loss_margin = Decimal('0.01')    # 1 %
  take_profit_margin = Decimal('0.02')  # 2 %

  def execute(self, date):
    ins = self.instrument
    window = self.moving_average_window_days

    mavg = self.datafeed.n_day_moving_avg(ins, date, 'close', window)
    std_dev = self.datafeed.n_day_std_dev(ins, date, 'close', window)

    if (mavg is None) or (std_dev is None):
      return

    cur_price = self.datafeed.get_price(ins, date, 'close')

    lower_band = mavg - (self.band_width_std_devs * std_dev)
    upper_band = mavg + (self.band_width_std_devs * std_dev)

    if (cur_price < lower_band):
      # oversold - bet on a bounce back up
      buy_order = Order(ins, 'buy', 1,
        self.stop_loss_level(cur_price, 'buy', self.stop_loss_margin),
        self.take_profit_level(cur_price, 'buy', self.take_profit_margin), date)
      self.submit_order(buy_order)
    elif (cur_price > upper_band):
      # overbought - bet on a pullback down
      sell_order = Order(ins, 'sell', 1,
        self.stop_loss_level(cur_price, 'sell', self.stop_loss_margin),
        self.take_profit_level(cur_price, 'sell', self.take_profit_margin), date)
      self.submit_order(sell_order)
