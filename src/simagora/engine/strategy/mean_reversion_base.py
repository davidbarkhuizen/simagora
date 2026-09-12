from decimal import Decimal

from ...domain.order import Order
from .strategy_base import SingleInstrumentStrategy

class MeanReversionBase(SingleInstrumentStrategy):
  '''
  shared plumbing for mean-reversion strategies: buy when an
  oversold/overbought signal fires in one direction, sell when it
  fires in the other, each new position carrying fixed
  stop-loss/take-profit bands. A reversion trade is meant to be quick,
  so there's no other position-management logic beyond that - unlike
  the trend-following strategies. Concrete subclasses supply
  _signal(date), returning 'buy' (oversold - bet on a bounce back up),
  'sell' (overbought - bet on a pullback down), or None (neither).
  '''

  stop_loss_margin = Decimal('0.01')    # 1 %
  take_profit_margin = Decimal('0.02')  # 2 %

  def _signal(self, date):
    raise NotImplementedError

  def execute(self, date):
    signal = self._signal(date)
    if (signal is None):
      return

    ins = self.instrument
    cur_price = self.datafeed.get_price(ins, date, 'close')
    order = Order(ins, signal, 1,
      self.stop_loss_level(cur_price, signal, self.stop_loss_margin),
      self.take_profit_level(cur_price, signal, self.take_profit_margin), date)
    self.submit_order(order)
