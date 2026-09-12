from ...domain.order import Order
from .strategy_base import SingleInstrumentStrategy

class DollarCostAveragingStrategy(SingleInstrumentStrategy):
  '''
  buys a fixed quantity of self.instrument every interval_days trading
  days - starting on the very first one - and otherwise does nothing:
  no signal, no timing, no exit. The passive control-group baseline
  every other strategy should be measured against.

  Sized by a fixed share quantity rather than a fixed dollar amount,
  like every other strategy - an order submitted today executes
  at tomorrow's price (see Overview), which isn't known yet at
  submission time, so a strategy can't size to a precise dollar amount
  up front. Each purchase has stop_loss=take_profit=None, so it opens
  as a fully-collateralized position (see Position closing) that never
  auto-closes - positions simply accumulate and are marked to market
  for the rest of the run.
  '''

  interval_days = 21  # ~1 trading month
  quantity = 1

  def __init__(self, trader, start_date, end_date):
    SingleInstrumentStrategy.__init__(self, trader, start_date, end_date)
    self.trading_days_seen = 0

  def execute(self, date):
    if (self.trading_days_seen % self.interval_days == 0):
      order = Order(self.instrument, 'buy', self.quantity, None, None, date)
      self.submit_order(order)
    self.trading_days_seen += 1
