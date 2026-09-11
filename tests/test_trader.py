import unittest
from decimal import Decimal

from simagora.engine.trader import Trader
from simagora.domain.order import Order

from testutil import FakeDataFeed, DAY1, DAY1_PRICES, make_broker_and_trader, open_position


class TestTraderProcessReceipts(unittest.TestCase):

  def setUp(self):
    self.datafeed = FakeDataFeed({DAY1: DAY1_PRICES})
    (self.orderQ, self.receiptQ, self.term_req_Q, self.term_notice_Q,
     self.broker, self.trader) = make_broker_and_trader(
        self.datafeed, Decimal('10000'), 's&p500', DAY1, DAY1)

  def test_successful_order_is_recorded(self):
    open_position(self.trader, self.broker, DAY1)

    self.trader.process_receipts()

    self.assertEqual(self.receiptQ.get(), None)
    self.assertEqual(len(self.trader.order_receipts), 1)
    self.assertEqual(self.trader.order_receipts[0].status, 'opened')

  def test_rejected_order_is_recorded_not_silently_dropped(self):
    # opening_bal too small to cover the margin -> insufficient_cash_bal
    orderQ, receiptQ, term_req_Q, term_notice_Q, broker, trader = \
      make_broker_and_trader(self.datafeed, Decimal('0'), 's&p500', DAY1, DAY1)

    order = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    trader.submit_order(order)
    broker.execute_orders_to_open(DAY1)

    trader.process_receipts()

    self.assertEqual(receiptQ.get(), None)
    self.assertEqual(len(trader.order_receipts), 1)
    self.assertEqual(trader.order_receipts[0].status, 'insufficient_cash_bal')

  def test_only_drains_this_traders_own_receipts(self):
    open_position(self.trader, self.broker, DAY1)

    other_trader = Trader(self.datafeed, self.broker, Decimal('10000'), 's&p500', None, DAY1, DAY1)
    order_b = Order('s&p500', 'buy', 1, Decimal('90'), Decimal('110'), DAY1)
    other_trader.submit_order(order_b)
    self.broker.execute_orders_to_open(DAY1)

    self.trader.process_receipts()

    self.assertEqual(len(self.trader.order_receipts), 1)
    self.assertEqual(len(other_trader.order_receipts), 0)
    # other_trader's receipt is still on the shared queue, untouched
    remaining = self.receiptQ.get()
    self.assertIsNotNone(remaining)
    self.assertEqual(remaining.order.trader_id, other_trader.id)


if __name__ == '__main__':
  unittest.main()
