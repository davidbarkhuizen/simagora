'''exercises RSIMeanReversionStrategy's own RSI-based buy/sell signal logic'''

import unittest
from decimal import Decimal
from datetime import timedelta

from simagora.engine.strategy import RSIMeanReversionStrategy

from testutil import FakeDataFeed, DAY1, make_trader_with_strategy, submitted_orders


class _ShortLookbackRSIMeanReversion(RSIMeanReversionStrategy):
  '''test-only: a 2-day RSI window keeps fixtures small (default is 14)'''
  rsi_window_days = 2


class TestRSIMeanReversionStrategy(unittest.TestCase):

  def make_trader(self, closes):
    '''one flat trading day per close in `closes`, starting at DAY1'''
    prices = {}
    d = DAY1
    for close in closes:
      prices[d] = {'high': close + 1, 'low': close - 1, 'close': close}
      d = d + timedelta(days=1)
    today = d - timedelta(days=1)

    datafeed = FakeDataFeed(prices)
    orderQ, broker, trader = make_trader_with_strategy(datafeed, _ShortLookbackRSIMeanReversion, DAY1, today)
    return orderQ, trader, today

  def test_buy_signal_when_rsi_is_oversold(self):
    # closes 100 -> 90 -> 80: two losses, no gains -> RSI = 0
    orderQ, trader, today = self.make_trader([Decimal('100'), Decimal('90'), Decimal('80')])

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertLess(orders[0].stop_loss, Decimal('80'))
    self.assertGreater(orders[0].take_profit, Decimal('80'))

  def test_sell_signal_when_rsi_is_overbought(self):
    # closes 100 -> 110 -> 120: two gains, no losses -> RSI = 100
    orderQ, trader, today = self.make_trader([Decimal('100'), Decimal('110'), Decimal('120')])

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'sell')
    self.assertGreater(orders[0].stop_loss, Decimal('120'))
    self.assertLess(orders[0].take_profit, Decimal('120'))

  def test_no_signal_when_rsi_is_neutral(self):
    # closes 100 -> 105 -> 102: RSI = 62.5, between the 30/70 thresholds
    orderQ, trader, today = self.make_trader([Decimal('100'), Decimal('105'), Decimal('102')])

    trader.execute_strategy(today)

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_no_signal_without_enough_preceding_history(self):
    # rsi_window_days=2 needs 3 bars; only 1 exists
    orderQ, trader, today = self.make_trader([Decimal('100')])

    trader.execute_strategy(today)  # must not raise

    self.assertEqual(len(submitted_orders(orderQ)), 0)


if __name__ == '__main__':
  unittest.main()
