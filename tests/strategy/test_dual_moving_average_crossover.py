'''
exercises DualMovingAverageCrossoverStrategy's own fast-vs-slow signal
logic - close_in_the_money_positions is inherited unchanged from
MovingAverageCrossoverBase and already covered in depth via
MovingAverageCrossoverStrategy in test_moving_average_crossover.py, so
it isn't re-tested here
'''

import unittest
from decimal import Decimal

from simagora.engine.strategy import DualMovingAverageCrossoverStrategy

from testutil import (
  FakeDataFeed, DAY1, make_trader_with_strategy, make_flat_range_prices,
  submitted_orders, assert_banded_order,
)


class _ShortLookbackDualMACrossover(DualMovingAverageCrossoverStrategy):
  '''test-only: 2/3-day windows keep fixtures small (defaults are 50/200)'''
  fast_window_days = 2
  slow_window_days = 3


class TestDualMovingAverageCrossoverStrategy(unittest.TestCase):

  def make_datafeed_with_today(self, today_close):
    '''3 flat days at 100, followed by one more day carrying today_close'''
    prices, today = make_flat_range_prices(3, Decimal('100'), Decimal('100'), Decimal('100'))
    prices[today] = {'high': today_close, 'low': today_close, 'close': today_close}
    return FakeDataFeed(prices), today

  def make_trader(self, today_close):
    datafeed, today = self.make_datafeed_with_today(today_close)
    orderQ, broker, trader = make_trader_with_strategy(datafeed, _ShortLookbackDualMACrossover, DAY1, today)
    return orderQ, trader, today

  def test_buy_signal_when_fast_average_crosses_above_slow(self):
    # fast(2-day) = avg(100, 130) = 115, slow(3-day) = avg(100, 100, 130) = 110
    orderQ, trader, today = self.make_trader(Decimal('130'))

    trader.execute_strategy(today)

    assert_banded_order(self, submitted_orders(orderQ), 'buy', Decimal('130'))

  def test_sell_signal_when_fast_average_crosses_below_slow(self):
    # fast(2-day) = avg(100, 70) = 85, slow(3-day) = avg(100, 100, 70) = 90
    orderQ, trader, today = self.make_trader(Decimal('70'))

    trader.execute_strategy(today)

    assert_banded_order(self, submitted_orders(orderQ), 'sell', Decimal('70'))

  def test_no_signal_when_fast_and_slow_averages_are_equal(self):
    orderQ, trader, today = self.make_trader(Decimal('100'))

    trader.execute_strategy(today)

    self.assertEqual(len(submitted_orders(orderQ)), 0)


if __name__ == '__main__':
  unittest.main()
