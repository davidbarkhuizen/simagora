'''exercises TrendFollowingStrategy's Donchian-channel breakout entry and stop-loss placement'''

import unittest
from decimal import Decimal

from simagora.domain.order import Order
from simagora.domain.orderreceipt import OrderReceipt
from simagora.domain.position import Position
from simagora.engine.strategy import TrendFollowingStrategy

from testutil import (
  FakeDataFeed, DAY1, DAY1_PRICES,
  make_broker_and_trader, make_flat_range_prices, submitted_orders, submitted_close_orders,
)


class TestTrendFollowingStrategy(unittest.TestCase):

  ENTRY_WINDOW = TrendFollowingStrategy.entry_window_days
  RANGE_HIGH = Decimal('105')
  RANGE_LOW = Decimal('95')
  RANGE_CLOSE = Decimal('100')

  def make_datafeed_with_breakout(self, breakout_prices):
    '''
    ENTRY_WINDOW flat, range-bound days (fixed high/low/close), followed
    by one more day carrying breakout_prices; returns (datafeed, breakout_date)
    '''
    prices, breakout_date = make_flat_range_prices(
      self.ENTRY_WINDOW, self.RANGE_HIGH, self.RANGE_LOW, self.RANGE_CLOSE)
    prices[breakout_date] = breakout_prices
    return FakeDataFeed(prices), breakout_date

  def test_buy_breakout_above_entry_window_high(self):
    datafeed, breakout_date = self.make_datafeed_with_breakout(
      {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('110')})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, breakout_date, strategy_name='trend')

    trader.execute_strategy(breakout_date)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'buy')
    # stop-loss = the exit-window low over the days preceding the breakout
    self.assertEqual(orders[0].stop_loss, self.RANGE_LOW)
    self.assertIsNone(orders[0].take_profit)

  def test_sell_breakout_below_entry_window_low(self):
    datafeed, breakout_date = self.make_datafeed_with_breakout(
      {'high': Decimal('92'), 'low': Decimal('85'), 'close': Decimal('90')})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, breakout_date, strategy_name='trend')

    trader.execute_strategy(breakout_date)

    orders = submitted_orders(orderQ)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].buysell, 'sell')
    self.assertEqual(orders[0].stop_loss, self.RANGE_HIGH)
    self.assertIsNone(orders[0].take_profit)

  def test_no_signal_within_the_range(self):
    datafeed, breakout_date = self.make_datafeed_with_breakout(
      {'high': Decimal('104'), 'low': Decimal('96'), 'close': Decimal('101')})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, breakout_date, strategy_name='trend')

    trader.execute_strategy(breakout_date)

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_no_signal_without_enough_preceding_history(self):
    # only 1 day of history exists - n_day_high/n_day_low (which
    # exclude the current day) have nothing preceding to look at yet
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, DAY1, strategy_name='trend')

    trader.execute_strategy(DAY1)  # must not raise

    self.assertEqual(len(submitted_orders(orderQ)), 0)

  def test_closes_opposite_direction_position_on_new_breakout(self):
    datafeed, breakout_date = self.make_datafeed_with_breakout(
      {'high': Decimal('115'), 'low': Decimal('108'), 'close': Decimal('110')})
    (orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader) = make_broker_and_trader(
      datafeed, Decimal('10000'), 's&p500', DAY1, breakout_date, strategy_name='trend')

    # a pre-existing SELL position, opposite the upcoming buy breakout
    order = Order('s&p500', 'sell', 1, Decimal('1000'), None, DAY1)
    order.trader_id = trader.id
    receipt = OrderReceipt(order, 'opened', Decimal('100'), DAY1, Decimal('0'))
    pos = Position(receipt)
    broker.open_positions.append(pos)
    broker.positions[pos.id] = pos

    trader.execute_strategy(breakout_date)

    close_orders = submitted_close_orders(orderQ)
    self.assertEqual(len(close_orders), 1)
    self.assertEqual(close_orders[0].position_id, pos.id)


if __name__ == '__main__':
  unittest.main()
