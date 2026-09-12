'''
exercises LowVolatilityStrategy end-to-end through a real Trader,
with a FakeUniverse standing in for Universe
'''

import unittest
from decimal import Decimal

from simagora.engine.strategy import LowVolatilityStrategy

from testutil import DAY1, DAY2, make_multi_instrument_trader, make_manual_position, submitted_orders, submitted_close_orders


class _ShortLookbackLowVolatility(LowVolatilityStrategy):
  '''test-only: a 2-day lookback keeps fixtures small (default is 20) -
  n_day_std_dev needs at least 2 values to show any spread at all'''
  lookback_window_days = 2


class TestLowVolatilityStrategy(unittest.TestCase):

  # over DAY1->DAY2: AAA is flat (std 0, calmest), BBB moves modestly
  # (std 2), CCC moves the most (std 5)
  THREE_WAY_PRICES = {
    'AAA': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('100')}},
    'BBB': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('104')}},
    'CCC': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('110')}},
  }

  def make_trader(self, prices_by_ins, end_date=DAY2, strategy_class=_ShortLookbackLowVolatility):
    return make_multi_instrument_trader(prices_by_ins, strategy_class, end_date=end_date)

  def test_goes_long_the_calmest_instrument(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)

    trader.execute_strategy(DAY2)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].ins, 'AAA')
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_holds_the_calmest_instrument_without_churn_when_unchanged(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)
    make_manual_position(broker, trader, 'AAA')

    trader.execute_strategy(DAY2)

    self.assertEqual(len(submitted_orders(orderQ)), 0)
    self.assertEqual(len(submitted_close_orders(orderQ)), 0)

  def test_rotates_out_of_a_position_that_is_no_longer_the_calmest(self):
    orderQ, broker, trader = self.make_trader(self.THREE_WAY_PRICES)
    stale = make_manual_position(broker, trader, 'CCC')  # the most volatile of the three

    trader.execute_strategy(DAY2)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual([co.position_id for co in close_orders], [stale.id])

    new_orders = submitted_orders(orderQ)
    self.assertEqual(len(new_orders), 1)
    self.assertEqual(new_orders[0].ins, 'AAA')

  def test_instrument_with_no_data_for_the_date_is_dropped_from_ranking(self):
    # BBB has no DAY2 data at all (a calendar mismatch, not just a
    # shorter lookback) - n_day_std_dev returns None for it on DAY2,
    # and it must be excluded rather than crashing the ranking
    prices = {
      'AAA': {DAY1: {'close': Decimal('100')}, DAY2: {'close': Decimal('100')}},
      'BBB': {DAY1: {'close': Decimal('100')}},
    }
    orderQ, broker, trader = self.make_trader(prices)

    trader.execute_strategy(DAY2)  # must not raise

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].ins, 'AAA')


if __name__ == '__main__':
  unittest.main()
