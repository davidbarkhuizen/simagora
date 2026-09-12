from .strategy_base import SingleInstrumentStrategy

class PeriodicInvestmentBase(SingleInstrumentStrategy):
  '''
  shared scheduling for strategies that act every interval_days trading
  days, starting on the very first one, and otherwise do nothing - no
  signal, no timing beyond the fixed schedule, no exit.
  DollarCostAveragingStrategy buys a fixed quantity every time;
  ValueAveragingStrategy buys however much is needed to bring the
  position up to a target value. Concrete subclasses supply
  _investment_order(date), returning the Order to submit this period,
  or None to skip it.
  '''

  interval_days = 21  # ~1 trading month

  def __init__(self, trader, start_date, end_date):
    SingleInstrumentStrategy.__init__(self, trader, start_date, end_date)
    self.trading_days_seen = 0

  def _investment_order(self, date):
    raise NotImplementedError

  def execute(self, date):
    if (self.trading_days_seen % self.interval_days == 0):
      order = self._investment_order(date)
      if (order is not None):
        self.submit_order(order)
    self.trading_days_seen += 1
