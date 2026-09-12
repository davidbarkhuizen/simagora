from decimal import Decimal

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
    returns = self.rank_universe_or_none(
      lambda ins: self.datafeed.n_day_return(ins, date, 'close', self.lookback_window_days))
    if (returns is None):
      # not enough trailing history anywhere yet
      return

    leader = max(returns, key=returns.get)
    # ABSOLUTE MOMENTUM FILTER: an empty desired set rotates fully to
    # cash rather than holding a losing leader; otherwise the single
    # leader is the whole desired set - already holding it is left
    # alone, anything else open gets closed, same as every other
    # ranking/rotation strategy's rebalance
    desired = {leader} if (returns[leader] > 0) else set()

    self.rebalance_to(desired, lambda o: o.ins, self._open_long, date, filter_fn=lambda o: o.buysell == 'buy')
