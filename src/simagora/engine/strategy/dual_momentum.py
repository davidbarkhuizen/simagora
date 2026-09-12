from decimal import Decimal

from ...domain.order import Order
from .strategy_base import MultiInstrumentStrategy

class DualMomentumStrategy(MultiInstrumentStrategy):
  '''
  Dual Momentum (Antonacci-style) instrument rotation: ranks
  trader.universe by their trailing lookback_window_days return
  (relative momentum) and holds a single long position in the leader -
  but only while the leader's own return is positive (absolute
  momentum filter); otherwise rotates fully to cash rather than
  holding a losing leader. Re-evaluated every day rather than the
  classic monthly rebalance, but a leader already held is left alone
  rather than churned, so a run of days with the same leader submits
  no new orders.

  No fixed take-profit - a position exits only when the leader changes
  or absolute momentum turns negative - but every buy still carries a
  protective stop_loss_margin band, since Broker.execute_orders_to_open
  requires a stop_loss on every order to size margin.
  '''

  lookback_window_days = 20
  stop_loss_margin = Decimal('0.05')  # 5 %

  def execute(self, date):
    returns = self.rank_universe(
      lambda ins: self.datafeed.n_day_return(ins, date, 'close', self.lookback_window_days))
    open_by_ins = self.open_positions_by(lambda o: o.ins, lambda o: o.buysell == 'buy')

    if (len(returns) == 0):
      # not enough trailing history anywhere yet
      return

    leader = max(returns, key=returns.get)

    if (returns[leader] <= 0):
      # ABSOLUTE MOMENTUM FILTER FAILED - rotate fully to cash
      for positions in open_by_ins.values():
        self.close_positions(positions, date)
      return

    if (leader in open_by_ins):
      # already positioned in the leader - leave it running, but close
      # any other open position left over from a since-changed leader
      for ins, positions in open_by_ins.items():
        if (ins != leader):
          self.close_positions(positions, date)
      return

    # ROTATE INTO THE NEW LEADER
    for positions in open_by_ins.values():
      self.close_positions(positions, date)

    cur_price = self.datafeed.get_price(leader, date, 'close')
    buy_order = Order(leader, 'buy', 1, self.stop_loss_level(cur_price, 'buy', self.stop_loss_margin), None, date)
    self.submit_order(buy_order)
