'''exercises MeanReversionStrategy's Bollinger Band buy/sell signal logic'''

import unittest
from decimal import Decimal
from datetime import timedelta

from simagora.engine.strategy import MeanReversionStrategy

from testutil import FakeDataFeed, DAY1, make_broker_and_trader, submitted_orders


class TestMeanReversionStrategy(unittest.TestCase):

  WINDOW = MeanReversionStrategy.moving_average_window_days

  def make_datafeed_with_today(self, today_close):
    '''
    WINDOW-1 days alternating 98/102 (real historical variability -
    an artificially flat run would make even a tiny move on the last
    day look like an outlier), followed by one more day at today_close
    '''
    prices = {}
    d = DAY1
    for i in range(self.WINDOW - 1):
      close = Decimal('98') if (i % 2 == 0) else Decimal('102')
      prices[d] = {'high': close + 1, 'low': close - 1, 'close': close}
      d = d + timedelta(days=1)
    today = d
    prices[today] = {'high': today_close + 1, 'low': today_close - 1, 'close': today_close}
    return FakeDataFeed(prices), today

  def test_buy_signal_when_oversold(self):
    datafeed, today = self.make_datafeed_with_today(Decimal('80'))
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today, strategy_name='meanreversion')

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    self.assertLess(orders[0].stop_loss, Decimal('80'))
    self.assertGreater(orders[0].take_profit, Decimal('80'))

  def test_sell_signal_when_overbought(self):
    datafeed, today = self.make_datafeed_with_today(Decimal('120'))
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today, strategy_name='meanreversion')

    trader.execute_strategy(today)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'sell')
    self.assertGreater(orders[0].stop_loss, Decimal('120'))
    self.assertLess(orders[0].take_profit, Decimal('120'))

  def test_no_signal_within_the_band(self):
    datafeed, today = self.make_datafeed_with_today(Decimal('100'))
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, today, strategy_name='meanreversion')

    trader.execute_strategy(today)

    self.assertEqual(len(submitted_orders(orderQ)), 0)


if __name__ == '__main__':
  unittest.main()
