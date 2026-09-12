from decimal import Decimal

from .mean_reversion_base import MeanReversionBase

class MeanReversionStrategy(MeanReversionBase):
  '''
  Bollinger-Band mean reversion: buy when the close drops
  band_width_std_devs standard deviations below its own
  moving_average_window_days moving average (oversold), sell when it
  rises the same distance above it (overbought) - betting the price
  reverts back toward its recent average.
  '''

  moving_average_window_days = 20
  band_width_std_devs = Decimal('2')

  def _signal(self, date):
    ins = self.instrument
    window = self.moving_average_window_days

    mavg = self.datafeed.n_day_moving_avg(ins, date, 'close', window)
    std_dev = self.datafeed.n_day_std_dev(ins, date, 'close', window)

    if (mavg is None) or (std_dev is None):
      return None

    cur_price = self.datafeed.get_price(ins, date, 'close')

    lower_band = mavg - (self.band_width_std_devs * std_dev)
    upper_band = mavg + (self.band_width_std_devs * std_dev)

    if (cur_price < lower_band):
      return 'buy'
    elif (cur_price > upper_band):
      return 'sell'
    return None
