'''exercises DollarCostAveragingStrategy's fixed-quantity, fixed-interval buying'''

import unittest
from decimal import Decimal
from datetime import timedelta

from simagora.engine.strategy import DollarCostAveragingStrategy

from testutil import FakeDataFeed, DAY1, make_trader_with_strategy, submitted_orders


class _ShortIntervalDCA(DollarCostAveragingStrategy):
  '''test-only: buy every 3rd trading day instead of the default 21'''
  interval_days = 3


class TestDollarCostAveragingStrategy(unittest.TestCase):

  def make_trader(self, num_days):
    '''num_days flat trading days starting at DAY1; returns (orderQ, dates, trader)'''
    dates = []
    prices = {}
    d = DAY1
    for i in range(num_days):
      dates.append(d)
      prices[d] = {'high': Decimal('105'), 'low': Decimal('95'), 'close': Decimal('100')}
      d = d + timedelta(days=1)

    datafeed = FakeDataFeed(prices)
    orderQ, broker, trader = make_trader_with_strategy(datafeed, _ShortIntervalDCA, DAY1, dates[-1])
    return orderQ, dates, trader

  def test_buys_on_the_first_trading_day(self):
    orderQ, dates, trader = self.make_trader(1)

    trader.execute_strategy(dates[0])

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertEqual(orders[0].quantity, Decimal('1'))
    self.assertIsNone(orders[0].stop_loss)
    self.assertIsNone(orders[0].take_profit)

  def test_does_not_buy_again_before_the_interval_elapses(self):
    orderQ, dates, trader = self.make_trader(3)  # interval_days = 3 -> only day index 0 buys

    for d in dates:
      trader.execute_strategy(d)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)

  def test_buys_again_once_the_interval_elapses(self):
    orderQ, dates, trader = self.make_trader(6)  # interval_days = 3 -> buys on day index 0 and 3

    for d in dates:
      trader.execute_strategy(d)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 2)

  def test_quantity_is_configurable(self):
    class _CustomQuantityDCA(_ShortIntervalDCA):
      quantity = 5

    orderQ, dates, trader = self.make_trader(1)
    trader.strategy = _CustomQuantityDCA(trader, DAY1, dates[-1])

    trader.execute_strategy(dates[0])

    orders = submitted_orders(orderQ)
    self.assertEqual(orders[0].quantity, Decimal('5'))


if __name__ == '__main__':
  unittest.main()
