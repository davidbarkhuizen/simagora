import unittest
from decimal import Decimal

from simagora.domain.order import Order
from simagora.domain.closeorder import CloseOrder
from simagora.domain.orderreceipt import OrderReceipt
from simagora.domain.position import Position

from testutil import FakeDataFeed, DAY1, DAY2, DAY1_PRICES, make_broker_and_trader, open_position


class TestStrategyCloseInTheMoneyPositions(unittest.TestCase):

  def setUp(self):
    self.datafeed = FakeDataFeed({
      DAY1: DAY1_PRICES,
      DAY2: {'high': Decimal('112'), 'low': Decimal('108'), 'close': Decimal('110')},
    })
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY2)
    self.strategy = self.trader.strategy

  def make_manual_position(self, ins, buysell, execution_price):
    '''build a position directly, bypassing broker cash/margin bookkeeping,
    to control its execution price precisely for pnl testing'''
    order = Order(ins, buysell, 1, Decimal('1'), Decimal('1000'), DAY1)
    order.trader_id = self.trader.id
    receipt = OrderReceipt(order, 'opened', execution_price, DAY1, Decimal('0'))
    pos = Position(receipt)
    self.broker.open_positions.append(pos)
    self.broker.positions[pos.id] = pos
    return pos

  def test_close_in_the_money_positions_filters_by_direction_and_instrument(self):
    # day2 close (110) > day1 exec price (100): a 'buy' opened at 100 is in the money
    profitable_buy = self.make_manual_position('s&p500', 'buy', Decimal('100'))
    # exec price (120) > day2 close (110): a 'buy' opened at 120 is a loss
    losing_buy = self.make_manual_position('s&p500', 'buy', Decimal('120'))
    # exec price (120) > day2 close (110): a 'sell' opened at 120 is in the money
    profitable_sell = self.make_manual_position('s&p500', 'sell', Decimal('120'))
    # same as profitable_buy, but a different instrument
    other_instrument_buy = self.make_manual_position('other_instrument', 'buy', Decimal('100'))

    self.trader.ac.tally_individual_open_positions(DAY2)

    self.strategy.close_in_the_money_positions(DAY2, 'buy')

    closed_ids = [co.position_id for co in self.orderQ.extract_matching(lambda x: isinstance(x, CloseOrder))]

    self.assertEqual(closed_ids, [profitable_buy.id])
    self.assertNotIn(losing_buy.id, closed_ids)
    self.assertNotIn(profitable_sell.id, closed_ids)
    self.assertNotIn(other_instrument_buy.id, closed_ids)

  def test_execute_closes_existing_in_the_money_position_on_new_buy_signal(self):
    pos = open_position(self.trader, self.broker, DAY1, stop_loss=Decimal('50'), take_profit=Decimal('200'))

    # mimic the simulator's daily bookkeeping step, which runs before execute_strategy
    self.trader.ac.tally_individual_open_positions(DAY2)

    # day2: mavg('high') = avg(105, 112) = 108.5, close = 110 -> buy signal
    self.trader.execute_strategy(DAY2)

    new_orders = self.orderQ.extract_matching(lambda x: isinstance(x, Order))
    close_orders = self.orderQ.extract_matching(lambda x: isinstance(x, CloseOrder))

    self.assertEqual(len(new_orders), 1)
    self.assertEqual(new_orders[0].buysell, 'buy')

    self.assertEqual(len(close_orders), 1)
    self.assertEqual(close_orders[0].position_id, pos.id)


class TestStrategyLogSelf(unittest.TestCase):

  def setUp(self):
    datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

  def test_logs_its_own_source_without_truncating_lines(self):
    # previously trimmed the last 2 characters of every line assuming
    # CRLF endings, but the file uses LF - dropping the real last
    # character of every logged line (readline() already strips
    # nothing but the single trailing '\n')
    with self.assertLogs(level='INFO') as captured:
      self.trader.strategy.log_self()

    self.assertIn(
      'class MovingAverageCrossoverStrategy(object):',
      [record.getMessage() for record in captured.records],
    )


if __name__ == '__main__':
  unittest.main()
