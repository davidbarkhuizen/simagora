'''
exercises ATRTrendFollowingStrategy's own ATR-based stop-loss sizing -
the Donchian breakout entry and close-opposite-direction mechanics are
inherited unchanged from TrendFollowingBase and already covered in
depth via TrendFollowingStrategy in test_trend_following.py, so they
aren't re-tested here
'''

import unittest
from decimal import Decimal

from simagora.engine.strategy import ATRTrendFollowingStrategy

from testutil import FakeDataFeed, DAY1, make_flat_range_prices, make_trader_with_strategy, submitted_orders


class _ShortLookbackATRTrendFollowing(ATRTrendFollowingStrategy):
  '''test-only: short entry/ATR windows keep fixtures small (defaults are 20/14)'''
  entry_window_days = 3
  atr_window_days = 2


class TestATRTrendFollowingStrategy(unittest.TestCase):

  ENTRY_WINDOW = _ShortLookbackATRTrendFollowing.entry_window_days
  RANGE_HIGH = Decimal('105')
  RANGE_LOW = Decimal('95')
  RANGE_CLOSE = Decimal('100')

  def make_trader_with_breakout(self, breakout_prices, strategy_class=_ShortLookbackATRTrendFollowing):
    prices, breakout_date = make_flat_range_prices(
      self.ENTRY_WINDOW, self.RANGE_HIGH, self.RANGE_LOW, self.RANGE_CLOSE)
    prices[breakout_date] = breakout_prices

    datafeed = FakeDataFeed(prices)
    orderQ, broker, trader = make_trader_with_strategy(datafeed, strategy_class, DAY1, breakout_date)
    return orderQ, trader, breakout_date

  def test_buy_breakout_places_stop_loss_atr_multiplier_atrs_below_entry(self):
    orderQ, trader, breakout_date = self.make_trader_with_breakout(
      {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('110')})

    trader.execute_strategy(breakout_date)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertIsNone(orders[0].take_profit)
    # True Range of the last flat day (prev close 100): max(105-95=10, |105-100|=5, |95-100|=5) = 10
    # True Range of the breakout day (prev close 100): max(115-108=7, |115-100|=15, |108-100|=8) = 15
    # ATR(2) = mean(10, 15) = 12.5; stop = entry(110) - 3*12.5 = 72.5
    self.assertEqual(orders[0].stop_loss, Decimal('72.5'))

  def test_sell_breakout_places_stop_loss_atr_multiplier_atrs_above_entry(self):
    orderQ, trader, breakout_date = self.make_trader_with_breakout(
      {'high': Decimal('92'), 'low': Decimal('85'), 'close': Decimal('90')})

    trader.execute_strategy(breakout_date)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'sell')
    self.assertIsNone(orders[0].take_profit)
    # True Range of the breakout day (prev close 100): max(92-85=7, |92-100|=8, |85-100|=15) = 15
    # ATR(2) = mean(10, 15) = 12.5; stop = entry(90) + 3*12.5 = 127.5
    self.assertEqual(orders[0].stop_loss, Decimal('127.5'))

  def test_no_signal_when_the_atr_window_needs_more_history_than_is_available(self):
    class _MismatchedWindows(_ShortLookbackATRTrendFollowing):
      atr_window_days = 10  # needs 11 bars; only entry_window_days(3)+1=4 exist

    orderQ, trader, breakout_date = self.make_trader_with_breakout(
      {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('110')},
      strategy_class=_MismatchedWindows)

    trader.execute_strategy(breakout_date)  # must not raise

    self.assertEqual(len(submitted_orders(orderQ)), 0)


if __name__ == '__main__':
  unittest.main()
