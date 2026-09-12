'''
exercises DualMomentumStrategy's own ranking/absolute-momentum-filter
logic end-to-end through a real Trader, with a FakeUniverse standing
in for Universe - AAA/BBB fixtures are set up per test so day2's
relative ranking (and, in some tests, day1's as well) is whatever that
test needs. rebalance_to's shared hold-without-churn/rotate-out-of-
stale-positions contract (inherited unchanged from
MultiInstrumentStrategy) is tested once, directly, in
test_strategy_base.py's TestRebalanceTo, rather than re-verified per
strategy
'''

import unittest
from decimal import Decimal

from simagora.engine.strategy import DualMomentumStrategy

from testutil import DAY1, DAY2, make_multi_instrument_trader, make_manual_position, submitted_orders, submitted_close_orders


class _ShortLookbackDualMomentum(DualMomentumStrategy):
  '''test-only: a 1-day lookback keeps fixtures small (default is 20)'''
  lookback_window_days = 1


class TestDualMomentumStrategy(unittest.TestCase):

  def make_trader(self, aaa_prices, bbb_prices, end_date=DAY2):
    return make_multi_instrument_trader(
      {'AAA': aaa_prices, 'BBB': bbb_prices}, _ShortLookbackDualMomentum, end_date=end_date)

  def test_no_signal_without_enough_preceding_history(self):
    # DAY1 has no preceding day, so n_day_return is None for both
    orderQ, broker, trader = self.make_trader(
      {DAY1: {'close': Decimal('100')}}, {DAY1: {'close': Decimal('100')}}, end_date=DAY1)

    trader.execute_strategy(DAY1)  # must not raise

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_buys_the_leader_when_it_has_positive_momentum(self):
    orderQ, broker, trader = self.make_trader(
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('110')}},   # +10%
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('102')}})   # +2%

    trader.execute_strategy(DAY2)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].ins, 'AAA')
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_absolute_momentum_filter_blocks_a_negative_leader_and_closes_out_to_cash(self):
    # BBB is the relative leader (-5% beats -10%) but still negative
    orderQ, broker, trader = self.make_trader(
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('90')}},   # -10%
      {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('95')}})   # -5%
    pos = make_manual_position(broker, trader, 'BBB')

    trader.execute_strategy(DAY2)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual([co.position_id for co in close_orders], [pos.id])
    self.assertEqual(len(submitted_orders(orderQ)), 0)

if __name__ == '__main__':
  unittest.main()
