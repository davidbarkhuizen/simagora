from decimal import Decimal

from ...domain.order import Order
from .strategy_base import MultiInstrumentStrategy

class LowVolatilityStrategy(MultiInstrumentStrategy):
  '''
  Low-volatility anomaly: ranks trader.universe by trailing
  lookback_window_days standard deviation of daily closes each day
  (n_day_std_dev) and holds long positions in the calmest top_n
  instruments - the opposite selection from a momentum-style strategy,
  betting steadier assets earn comparable or better risk-adjusted
  returns than the most volatile ones. Long-only, no short side, and
  no cash filter - it's always fully invested in the calmest names the
  universe currently offers. A currently-held instrument still among
  the calmest is left alone rather than churned.
  '''

  lookback_window_days = 20
  top_n = 1
  stop_loss_margin = Decimal('0.05')  # 5 %

  def execute(self, date):
    vols = self.rank_universe_or_none(
      lambda ins: self.datafeed.n_day_std_dev(ins, date, 'close', self.lookback_window_days))
    if (vols is None):
      # not enough trailing history anywhere yet
      return

    calmest = set(sorted(vols, key=vols.get)[:self.top_n])
    open_by_ins = self.open_positions_by(lambda o: o.ins, lambda o: o.buysell == 'buy')

    # CLOSE POSITIONS THAT FELL OUT OF THE CALMEST SET
    for ins, positions in open_by_ins.items():
      if (ins not in calmest):
        self.close_positions(positions, date)

    # OPEN WHATEVER'S CALMEST AND NOT ALREADY HELD
    for ins in calmest:
      if (ins in open_by_ins):
        continue
      cur_price = self.datafeed.get_price(ins, date, 'close')
      order = Order(ins, 'buy', 1, self.stop_loss_level(cur_price, 'buy', self.stop_loss_margin), None, date)
      self.submit_order(order)
