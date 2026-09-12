from decimal import Decimal

from .mean_reversion_base import MeanReversionBase

class RSIMeanReversionStrategy(MeanReversionBase):
  '''
  RSI-based mean reversion: buy when the rsi_window_days RSI
  (DataFeed.n_day_rsi) drops below oversold_threshold (default 30,
  the standard textbook level), sell when it rises above
  overbought_threshold (default 70) - the other standard
  mean-reversion indicator, taught alongside Bollinger Bands
  (MeanReversionStrategy's own approach) as its usual textbook
  counterpart. Same fixed stop-loss/take-profit bands and no further
  position-management, from the shared MeanReversionBase.
  '''

  rsi_window_days = 14  # Wilder's original recommendation, still the standard default
  oversold_threshold = Decimal('30')
  overbought_threshold = Decimal('70')

  def _signal(self, date):
    rsi = self.datafeed.n_day_rsi(self.instrument, date, 'close', self.rsi_window_days)
    if (rsi is None):
      return None

    if (rsi < self.oversold_threshold):
      return 'buy'
    elif (rsi > self.overbought_threshold):
      return 'sell'
    return None
