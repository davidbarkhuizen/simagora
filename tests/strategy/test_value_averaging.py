'''exercises ValueAveragingStrategy's target-value-gap buy sizing'''

import unittest
from decimal import Decimal

from simagora.engine.strategy import ValueAveragingStrategy

from testutil import FakeDataFeed, DAY1, make_trader_with_strategy, submitted_orders, make_manual_position


class _ShortIntervalVA(ValueAveragingStrategy):
  '''test-only: acts every 3rd trading day instead of the default 21'''
  interval_days = 3


class TestValueAveragingStrategy(unittest.TestCase):

  def make_trader(self, close_price):
    datafeed = FakeDataFeed({DAY1: {'high': close_price + 5, 'low': close_price - 5, 'close': close_price}})
    return make_trader_with_strategy(datafeed, _ShortIntervalVA, DAY1, DAY1, opening_bal=Decimal('100000'))

  def test_first_period_buys_enough_to_reach_one_deposit(self):
    orderQ, broker, trader = self.make_trader(Decimal('100'))

    trader.execute_strategy(DAY1)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertIsNone(orders[0].stop_loss)
    self.assertIsNone(orders[0].take_profit)
    # target = 1 * deposit_amount(1000), price = 100 -> 10 shares
    self.assertEqual(orders[0].quantity, Decimal('10'))

  def test_buys_more_after_a_price_drop_to_close_the_larger_gap(self):
    orderQ, broker, trader = self.make_trader(Decimal('50'))
    make_manual_position(broker, trader, 's&p500', execution_price=Decimal('100'),
                          quantity=Decimal('10'), stop_loss=None, take_profit=None)
    trader.strategy.trading_days_seen = 3  # the 2nd investment period

    trader.execute_strategy(DAY1)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    # target = 2*1000 = 2000, actual = 10*50 = 500, shortfall = 1500 -> 30 shares @ 50
    self.assertEqual(orders[0].quantity, Decimal('30'))

  def test_skips_the_purchase_when_the_position_already_meets_the_target(self):
    orderQ, broker, trader = self.make_trader(Decimal('250'))
    make_manual_position(broker, trader, 's&p500', execution_price=Decimal('100'),
                          quantity=Decimal('10'), stop_loss=None, take_profit=None)
    trader.strategy.trading_days_seen = 3  # the 2nd investment period

    trader.execute_strategy(DAY1)

    # target = 2000, actual = 10*250 = 2500 -> already ahead, no purchase
    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_does_not_act_before_the_interval_elapses(self):
    orderQ, broker, trader = self.make_trader(Decimal('100'))
    trader.strategy.trading_days_seen = 1  # not yet a multiple of interval_days=3

    trader.execute_strategy(DAY1)

    self.assertEqual(len(submitted_orders(orderQ)), 0)


if __name__ == '__main__':
  unittest.main()
